"""Editing the catalog's items: change one, add one, delete one, undo.

The owner, 2026-11-16, asked for a "modify item" function for admins, and
answered: change the product name, "YES"; add an item, "YES, please include";
delete an item, "YES, FOR SURE"; who edits, "ONLY DOVID & YOEL".

Everything that changes the `products` table after the first load goes through
save() here, so that every change

  * is written to `product_changes` (who, when, the row before and after),
  * keeps the photos it replaces or removes (photos/history/<change id>/),
  * and rewrites Satla_Master_Catalog.csv from Catalog.db (export_file()),
    because Catalog.db is the master and the file is its copy.

Nothing here reads or writes QuickBooks or MMK. What those systems call an item
comes from the snapshots the refresh stored (catalog_db.extra_source / qbo_source).

No third-party imports: the web worker loads this module.
"""
import csv
import io
import json
import os
import re
import struct
import time
import unicodedata

import catalog_db as db
from catalog_source import plain

PHOTO_DIR = db.ROOT / "photos"
CSV_PATH = db.ROOT / "Satla_Master_Catalog.csv"

# The two sizes every product photo is kept in (the approved standard: a white
# 3:4 picture, the product centred and filling 90% of the height, or 90% of the
# width when it is wide). The admin's browser makes both (static/item.js).
PHOTO_SIZES = {"grid": (600, 800), "detail": (900, 1200)}
MAX_PHOTO_BYTES = 2_000_000
KEEP = object()                    # save(photos=KEEP): leave the photos alone

YES_NO = ("", "Yes", "No")

# The fields an admin edits: (products column, label, kind, longest value).
# kind: "text", "long" (the description), "yesno", "number".
FIELDS = [
    ("name", "Product name", "text", 200),
    ("brand", "Brand", "text", 80),
    ("category", "Category", "text", 60),
    ("type", "Type", "text", 60),
    ("style", "Style", "text", 60),
    ("sweetness", "Sweetness", "text", 40),
    ("grape", "Grape / base", "text", 200),
    ("country", "Country", "text", 60),
    ("region", "Region", "text", 80),
    ("subregion", "Sub-region / appellation", "text", 100),
    ("abv", "ABV", "text", 20),
    ("vintage", "Vintage", "text", 20),
    ("size", "Bottle size", "text", 20),
    ("bottles_per_case", "Bottles per case", "number", 8),
    ("mevushal", "Mevushal", "yesno", 3),
    ("kfp", "Kosher for Passover", "yesno", 3),
    ("organic", "Organic", "yesno", 3),
    ("certifier", "Kosher certifier", "text", 120),
    ("description", "Description", "long", 3000),
]
LABELS = {col: label for col, label, _kind, _n in FIELDS}
# Fields that offer the values already in use (and still take a new one).
SUGGESTED = ("brand", "category", "type", "style", "sweetness", "grape", "country",
             "region", "subregion", "abv", "size", "certifier")

_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ml|cl|l)\s*$", re.IGNORECASE)


def _columns(con):
    return [d[0] for d in con.execute("SELECT * FROM products LIMIT 0").description]


def _row(con, sku):
    r = db.product(con, sku)
    return dict(r) if r is not None else None


def size_ml(text):
    """'750 ml' -> 750.0, '1.5 L' -> 1500.0; None when the text is not a size."""
    m = _SIZE.match(text or "")
    if not m:
        return None
    return float(m.group(1)) * {"ml": 1, "cl": 10, "l": 1000}[m.group(2).lower()]


# --- what the other systems call an item --------------------------------------

def inventory_item(con, sku):
    """What the inventory systems hold for a SKU: {'name', 'ml', 'bpc', 'state'}
    from the first state whose inventory has it, or None when no state does.
    An item can be added to the catalog only when this finds it (the owner:
    never add a product from QuickBooks Illinois alone, and nothing from thin air)."""
    for state in db.states(con):
        have = db.snapshot(con, db.inv_source(state))["data"] or {}
        v = (db.snapshot(con, db.extra_source(state))["data"] or {}).get(sku)
        if v is not None and sku in have:
            return dict(v, state=state)
    return None


def system_names(con, sku):
    """[(system, name)] for the edit form: what each state's inventory system
    and each state's QuickBooks company call this SKU. Read-only reference."""
    out, seen = [], set()
    for state, info in db.states(con).items():
        inv = (db.snapshot(con, db.extra_source(state))["data"] or {}).get(sku) or {}
        qbo = (db.snapshot(con, db.qbo_source(state))["data"] or {}).get(sku) or {}
        for system, name in ((info["inventory"], inv.get("name")),
                             ("QuickBooks " + info["name"], qbo.get("name"))):
            if name and system not in seen:
                seen.add(system)
                out.append((system, name))
    return out


def suggestions(con):
    """{column: [values in use, sorted]} for the fields in SUGGESTED. Grapes are
    offered one by one (the field holds a comma-separated list)."""
    out = {}
    for col in SUGGESTED:
        values = set()
        for (v,) in con.execute(f"SELECT DISTINCT {col} FROM products"):
            parts = (v or "").split(",") if col == "grape" else [v or ""]
            values.update(p.strip() for p in parts if p.strip())
        out[col] = sorted(values, key=str.casefold)
    return out


_TAG_SUFFIX = re.compile(r"\s+(winery|wineries|wines|wine|distillery|vineyards?|cellars?)$", re.I)


def brand_for(con, names, tags=()):
    """The brand of a product, worked out from its name, or '' when it cannot be
    told. A retailer's page has no brand field (its "vendor" is the
    distributor), so: the longest brand already in the catalog that one of
    `names` begins with ("Adir A Red Blend 2023" -> "Adir"); failing that, one
    of the page's `tags` that names a winery and that a name begins with
    ("ramat negev wines" + "Ramat Negev Red Exodus" -> "Ramat Negev")."""
    names = [" ".join((n or "").split()) for n in names if n]
    def begins(name, start):
        return plain(name).startswith(plain(start)) and (
            len(name) == len(start) or not name[len(start)].isalnum())
    known = sorted(suggestions(con)["brand"], key=len, reverse=True)
    for brand in known:
        if any(begins(n, brand) for n in names):
            return brand
    for tag in sorted(tags, key=len, reverse=True):
        start = _TAG_SUFFIX.sub("", " ".join(str(tag).split()))
        for n in names:
            if len(start) >= 3 and begins(n, start):
                return n[:len(start)]                    # as the name writes it
    # A brand whose name is longer than what the product names carry ("Crater
    # Lake Spirits" for "Crater Lake Vodka"): the brand of the catalog products
    # whose names begin with the same two words or more.
    best, brands = 1, []
    for row in con.execute("SELECT name, brand FROM products WHERE brand <> ''"):
        theirs = plain(row["name"]).split()
        for n in names:
            mine = plain(n).split()
            same = next((i for i, (a, b) in enumerate(zip(mine, theirs)) if a != b),
                        min(len(mine), len(theirs)))
            if same > best:
                best, brands = same, []
            if same == best and same > 1:
                brands.append(row["brand"])
    return max(set(brands), key=brands.count) if brands else ""


# A word in a product's name that tells its menu type, for a page with no type
# field (a store's spirits pages give only ABV and size). Used only for a type
# the catalog already has.
_KIND_WORDS = {"vodka": "Vodka", "gin": "Gin", "tequila": "Tequila", "mezcal": "Tequila",
               "whiskey": "Whiskey", "whisky": "Whiskey", "bourbon": "Whiskey",
               "scotch": "Whiskey", "cognac": "Brandy & Cognac", "brandy": "Brandy & Cognac",
               "armagnac": "Brandy & Cognac", "liqueur": "Liqueur", "sake": "Sake",
               "lager": "Lager"}


def kind_for(con, name):
    """(category, type) that a product's name states ("Crater Lake Vodka" ->
    ("Spirits", "Vodka")), or ('', ''). Only a type some catalog product already
    has, with the category that type is filed under."""
    for word in re.findall(r"\w+", plain(name)):
        kind = _KIND_WORDS.get(word)
        row = kind and con.execute("SELECT category FROM products WHERE type = ? GROUP BY category "
                                   "ORDER BY COUNT(*) DESC LIMIT 1", (kind,)).fetchone()
        if row:
            return row["category"], kind
    return "", ""


def brand_country(con, brand):
    """The country of a brand's catalog products when they all agree, else ''."""
    found = {r["country"] for r in con.execute(
        "SELECT DISTINCT country FROM products WHERE brand = ? AND country <> ''", (brand,))}
    return found.pop() if len(found) == 1 else ""


def grape_for(con, name):
    """The grape a product's name states, or '': the longest grape already in the
    catalog that appears in `name` as whole words ("Adir Winemaker Edition
    Petite Sirah 2023" -> "Petite Sirah"). For a page that has no grape field."""
    padded = " " + " ".join(re.findall(r"\w+", plain(name))) + " "
    for grape in sorted(suggestions(con)["grape"], key=len, reverse=True):
        if " " + " ".join(re.findall(r"\w+", plain(grape))) + " " in padded:
            return grape
    return ""


# --- the form ------------------------------------------------------------------

def blank_item(con, sku):
    """The form's starting values for an item with no catalog entry yet: what the
    inventory system knows, or None when no inventory system has the SKU."""
    inv = inventory_item(con, sku)
    if inv is None:
        return None
    return dict(dict.fromkeys(_columns(con)), sku=sku, name=inv["name"] or sku,
                size=db._size(inv["ml"]), bottles_per_case=inv["bpc"], bottle_ml=inv["ml"])


def clean(form):
    """The posted form as ({column: value}, [problems]). Text is trimmed and its
    inner runs of spaces collapsed (the description keeps its line breaks);
    blank is ''. `bottles_per_case` comes back as a float or None."""
    values, problems = {}, []
    for col, label, kind, longest in FIELDS:
        raw = str(form.get(col) or "")
        if kind == "long":
            text = "\n".join(" ".join(line.split()) for line in raw.splitlines()).strip()
        else:
            text = " ".join(raw.split())
        if len(text) > longest:
            problems.append(f"{label} is too long (at most {longest} characters).")
        if kind == "yesno" and text not in YES_NO:
            problems.append(f"{label} must be Yes, No or blank.")
        if kind == "number":
            try:
                number = float(text) if text else None
            except ValueError:
                number = -1
            if number is not None and not 0 < number <= 999:
                problems.append(f"{label} must be a number above 0, or blank.")
                number = None
            values[col] = number
        else:
            values[col] = text
    if not values["name"]:
        problems.append("The product needs a name.")
    return values, problems


def merged(before, values):
    """The products row after an edit: `before` (a full row) with the form's
    `values` laid over it. A field that was blank and stays blank keeps what it
    held (None or ''), so an untouched form changes nothing. A new bottle size
    resets bottle_ml; a changed pack figure is marked as typed by an admin, so
    `manage.py load-pack --overwrite` will not replace it."""
    after = dict(before)
    for col, value in values.items():
        if (before.get(col) or "") != (value or ""):
            after[col] = value
    if after["size"] != before.get("size"):
        after["bottle_ml"] = size_ml(after["size"])
    if (after["bottles_per_case"], after["bottle_ml"]) != (before.get("bottles_per_case"),
                                                          before.get("bottle_ml")):
        after["pack_source"] = "admin"
    if not after.get("kosher"):
        after["kosher"] = "Yes"            # the owner: "Everything we sell is Kosher"
    return after


# --- photos --------------------------------------------------------------------

def webp_size(data):
    """(width, height) of a WebP image, or None when `data` is not one."""
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L" and data[20] == 0x2F:
        bits = struct.unpack("<I", data[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        return (int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1)
    return None


def check_photos(photos):
    """A problem with an uploaded pair {'grid': bytes, 'detail': bytes}, or None."""
    for kind, (w, h) in PHOTO_SIZES.items():
        data = photos.get(kind) or b""
        if not data:
            return "The photo did not arrive complete. Choose it again."
        if len(data) > MAX_PHOTO_BYTES:
            return "The photo is too large."
        if webp_size(data) != (w, h):
            return ("The photo is not in the catalog's format. Choose the picture "
                    "again on the edit page, in Chrome, Edge or Firefox.")
    return None


def _photo_path(kind, sku):
    return PHOTO_DIR / kind / f"{sku}.webp"


def _history_dir(change_id):
    return PHOTO_DIR / "history" / str(change_id)


def _replace_photos(sku, change_id, photos):
    """Move the product's current photos into photos/history/<change_id>/ and
    put `photos` ({kind: bytes}; {} = none) in their place."""
    kept = _history_dir(change_id)
    for kind in PHOTO_SIZES:
        path = _photo_path(kind, sku)
        if path.exists():
            kept.mkdir(parents=True, exist_ok=True)
            os.replace(path, kept / f"{kind}.webp")     # a rename: the file itself is kept
        data = photos.get(kind)
        if data:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".new")
            tmp.write_bytes(data)
            os.replace(tmp, path)


def _kept_photos(change_id):
    """The photos a change put aside: {kind: bytes}; {} when it kept none (the
    product had no photo before it)."""
    out = {}
    for kind in PHOTO_SIZES:
        path = _history_dir(change_id) / f"{kind}.webp"
        if path.exists():
            out[kind] = path.read_bytes()
    return out


# --- save, undo, history -------------------------------------------------------

def save(con, sku, after, user, action, photos=KEEP, undoes=None):
    """Make one change to the catalog and record it. Returns the change's id, or
    None when nothing changed.

    `after` is the whole products row the SKU should have (a dict with every
    column), or None to take the SKU out of the catalog. `photos` is KEEP, or
    {kind: bytes} to replace the photos ({} removes them); deleting an item
    always puts its photos aside. `user` is the signed-in user's row; `action`
    is 'add', 'edit', 'delete' or 'undo'.

    The change row, the products row and the photo files go together: if a file
    cannot be moved the database change is rolled back. The catalog file is
    rewritten afterwards."""
    before = _row(con, sku)
    if after is None and photos is KEEP:
        photos = {}
    if photos is not KEEP:
        has_photo = any(_photo_path(kind, sku).exists() for kind in PHOTO_SIZES)
        if not photos and not has_photo:
            photos = KEEP                       # nothing to remove
    if after is not None:
        after = dict(after, sku=sku)
        if photos is not KEEP:                  # a new cache key, never one used before
            after["photo_v"] = max(int(time.time()), ((before or {}).get("photo_v") or 0) + 1)
    if after == before and photos is KEEP:
        return None
    with con:
        cur = con.execute(
            "INSERT INTO product_changes (at, user_id, user_name, sku, action, before, after, "
            "photo, undoes) VALUES (?,?,?,?,?,?,?,?,?)",
            (db.now_utc(), user["id"], user["name"], sku, action,
             json.dumps(before) if before is not None else None,
             json.dumps(after) if after is not None else None,
             0 if photos is KEEP else (1 if photos else 2), undoes))
        change_id = cur.lastrowid
        con.execute("DELETE FROM products WHERE sku = ?", (sku,))
        if after is not None:
            cols = _columns(con)
            con.execute(f"INSERT INTO products ({', '.join(cols)}) "
                        f"VALUES ({', '.join('?' * len(cols))})", [after.get(c) for c in cols])
        if photos is not KEEP:
            _replace_photos(sku, change_id, photos)
    export_file(con)
    return change_id


def change(con, change_id):
    return con.execute("SELECT * FROM product_changes WHERE id = ?", (change_id,)).fetchone()


def can_undo(con, c):
    """True when change `c` is still the last word on its SKU: the product is
    exactly as that change left it."""
    after = json.loads(c["after"]) if c["after"] else None
    return _row(con, c["sku"]) == after


def undo(con, change_id, user):
    """Take one change back: the product returns to how it was before it,
    photos included. The undo is itself recorded (and can be undone). Raises
    ValueError when the product has been changed again since."""
    c = change(con, change_id)
    if c is None:
        raise ValueError("That change does not exist.")
    if not can_undo(con, c):
        raise ValueError(f"{c['sku']} has been changed again since then. "
                         "Undo the later change first.")
    before = json.loads(c["before"]) if c["before"] else None
    photos = _kept_photos(change_id) if c["photo"] else KEEP
    return save(con, c["sku"], before, user, "undo", photos=photos, undoes=change_id)


def _text(value):
    if value is None or value == "":
        return "blank"
    if isinstance(value, float):
        return f"{value:g}"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"


def changes(con, limit=200):
    """The latest changes, newest first, each a dict for the History page:
    id, at, user_name, sku, action, name, `what` (a list of plain sentences) and
    `undo` (True when it can still be taken back)."""
    out = []
    for c in con.execute("SELECT * FROM product_changes ORDER BY id DESC LIMIT ?", (limit,)):
        before = json.loads(c["before"]) if c["before"] else None
        after = json.loads(c["after"]) if c["after"] else None
        what = []
        if before is None and after is not None:
            what.append("Added to the catalog.")
        elif after is None:
            what.append("Deleted from the catalog.")
        else:
            for col, label, _kind, _n in FIELDS:
                if (before.get(col) or "") != (after.get(col) or ""):
                    what.append(f"{label}: {_text(before.get(col))} → {_text(after.get(col))}")
        if c["photo"] and after is not None and before is not None:
            what.append("Photo removed." if c["photo"] == 2 else
                        "Photo replaced." if _history_dir(c["id"]).exists() else "Photo added.")
        if c["action"] == "undo":
            what.insert(0, f"Undid change {c['undoes']}.")
        out.append({"id": c["id"], "at": c["at"], "user_name": c["user_name"], "sku": c["sku"],
                    "action": c["action"], "name": (after or before or {}).get("name") or c["sku"],
                    "what": what, "undo": can_undo(con, c),
                    "in_catalog": after is not None})
    return out


# --- the catalog file ----------------------------------------------------------

def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def export_file(con, path=None):
    """Rewrite Satla_Master_Catalog.csv from Catalog.db, which is the master.

    Rows keep the file's order and its other columns (the working columns the
    site does not use); the columns the site holds are replaced with Catalog.db's
    values; a product that is no longer in Catalog.db loses its row; a new one
    is added at the end. The pack figures (CSV_PACK_COLUMNS) are added as columns
    if the file lacks them. Returns the number of products written."""
    path = path or CSV_PATH
    mapping = {**db.CSV_COLUMNS, **db.CSV_PACK_COLUMNS}
    header, old, newline = list(mapping), {}, "\n"
    if path.exists():
        text = path.read_text(encoding="utf-8-sig")
        newline = "\r\n" if "\r\n" in text else "\n"
        reader = csv.DictReader(io.StringIO(text, newline=""))
        header = list(reader.fieldnames or []) + [c for c in mapping if c not in (reader.fieldnames or [])]
        for r in reader:
            sku = (r.get("Satla SKU") or "").strip()
            if sku:
                old[sku] = r
    products = {r["sku"]: r for r in con.execute("SELECT * FROM products")}
    order = [s for s in old if s in products] + sorted(s for s in products if s not in old)
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=header, lineterminator=newline, extrasaction="ignore")
    w.writeheader()
    for sku in order:
        row = dict.fromkeys(header, "")
        row.update({k: v for k, v in old.get(sku, {}).items() if k in row and v is not None})
        row.update({src: _cell(products[sku][col]) for src, col in mapping.items()})
        w.writerow(row)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(out.getvalue(), encoding="utf-8-sig", newline="")
    os.replace(tmp, path)
    return len(order)
