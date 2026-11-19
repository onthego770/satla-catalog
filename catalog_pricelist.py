"""A supplier's price list as one choice on the state switch.

The owner, 2026-11-18, on Springfield Group's GEN7 meat price list (a PDF):
"Can you create another tab - FL/IL and now /MEAT where this is listed? in the
catalog?" His choices the same day: view only (no orders), prices for admins
only, and the tab for admins only at first.

Such a choice is a row in the library's STATES whose inventory is "list": it
has no QuickBooks company and no MMK. Its items are the rows of the supplier's
price list, kept here in Catalog.db:

  * each row becomes a catalog product through catalog_items.save() (name,
    brand, the list's section as the category, the list's "Specs" as the size,
    UPC, and the list's picture when one was made), so admins edit it like any
    other item and Item history shows it;
  * the three snapshots every page already reads are written from the list:
    `qbo_<st>` = {sku: {price, name}} (the list price), `inv_<st>` = {sku: None}
    (which items the list holds; stock is not known) and `extra_<st>` =
    {sku: {name, ml, bpc}}. The refresh timer leaves them alone
    (catalog_live.refresh() skips a "list" state).

Loading a newer list replaces the snapshots (so prices follow the list, except
a price an admin typed on the site, which stays; and an item the supplier
dropped leaves the catalog page) and adds the items that are new. An item that
already has a catalog entry FOLLOWS THE SUPPLIER'S CHANGES: where the list now
prints a different description, brand, section, specs, UPC or kosher line than
its last issue printed, the entry takes it; everything else in the entry (what
an admin edited, and what the supplier did not change) stays. What each issue
printed is kept with the item in the `extra_<st>` snapshot (`printed`).

UPLOADING A LIST ON THE SITE (the owner, 2026-11-19: "can we include an Upload
box where I can enter in either a new CHB pdf or Springfield pdf so you can
parse it and update all the items and add any new items?"). upload_read() keeps
the PDF, works out whose list it is (identify()) and what it would change
(compare()); the admin sees that and confirms; upload_apply() starts the load
and upload_state() says how it went. Both run manage.py as a separate process (pypdf and the browser stay out of the web
worker); the loaded PDFs are kept in price-lists/.

THE DOWNLOADED PDF (the owner, 2026-11-18: "Using the SatlaMeat Logo that I
uploaded to the drive, can you create a downloaed pdf?"). sheet_html() lays the
list out as a sheet (logo, date, the same rows and columns as the page) and
write_pdf() prints it to a PDF with the server's Chromium. The web worker never
starts a browser itself: pdf_file() runs `manage.py price-list-pdf` as a
separate process, one at a time, and keeps the result in pdf-cache/ until the
list, a price, a photo or the day changes. A state's logo is the file
static/logo-<state code in lower case>.png; without one the sheet has no logo.

read_pdf() needs pypdf and write_pdf() needs Playwright (both already in the
qbo311 environment); each is imported only inside the function that uses it,
so the web worker, which imports this module for pdf_file(), stays small.
"""
import base64
import fcntl
import hashlib
import html
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import time
import zlib
from datetime import date

import catalog_db as db
import catalog_items as items

# Where each column of the list starts, in PDF points from the left edge, as
# the supplier's report lays it out (Telerik Reporting, letter page).
_COLUMNS = (("sku", 70, 110), ("name", 110, 270), ("upc", 270, 360),
            ("brand", 360, 430), ("specs", 430, 520), ("price", 520, 600))
_ROW_ABOVE, _ROW_BELOW = 4, 36      # a row's text sits from 4 pt above its price to 36 pt below
_PRICE = re.compile(r"^\$[\d,]+\.\d\d$")


def _png(width, height, rgb):
    """Raw 8-bit RGB pixels as a PNG file (standard library only)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    lines = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(lines)) + chunk(b"IEND", b""))


def read_pdf(path):
    """The rows of a price list PDF, top to bottom, as dicts: `section` (the
    heading the row stands under, e.g. "Deli"), `sku`, `name`, `upc`, `brand`,
    `specs`, `price` (a float) and `picture` (the row's small picture as PNG
    bytes, or None).

    The report wraps a long SKU, description or spec onto a second line; the
    pieces are put back together by where they stand on the page (a SKU's
    pieces join without a space, the others with one). Raises ValueError when
    the file does not read as such a list (no rows, a row with no SKU or name,
    or the same SKU twice)."""
    import pypdf

    rows, section = [], ""
    for page in pypdf.PdfReader(str(path)).pages:
        texts, pictures = [], []
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject") or {}

        def on_text(text, cm, tm, _font, size, texts=texts):
            if text.strip():
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                texts.append((y, x, " ".join(text.split()), abs(size)))

        def on_draw(operator, args, cm, _tm, pictures=pictures, xobjects=xobjects):
            if operator == b"Do" and args and args[0] in xobjects:
                pictures.append((cm[5], cm[5] + cm[3], cm[4], xobjects[args[0]]))

        page.extract_text(visitor_text=on_text, visitor_operand_before=on_draw)
        prices = sorted((t for t in texts if _PRICE.match(t[2]) and t[1] >= _COLUMNS[-1][1]),
                        reverse=True)
        # Section headings stand at the left margin, left of the SKU column.
        headings = sorted(((y, text) for y, x, text, size in texts
                           if x < 60 and size >= 10 and text.isupper()), reverse=True)
        for price_y, _x, price_text, _size in prices:
            for y, text in headings:
                if y > price_y:
                    section = text.title()
            row = {"section": section, "price": float(price_text[1:].replace(",", "")),
                   "picture": None}
            for col, left, right in _COLUMNS[:-1]:
                parts = [text for y, x, text, _s in sorted(texts, reverse=True)
                         if left <= x < right and price_y - _ROW_BELOW < y <= price_y + _ROW_ABOVE]
                row[col] = ("" if col == "sku" else " ").join(parts)
            for bottom, top, x, obj in pictures:
                if x < 60 and bottom <= price_y <= top and obj.get("/ColorSpace") == "/DeviceRGB":
                    row["picture"] = _png(int(obj["/Width"]), int(obj["/Height"]), obj.get_data())
            rows.append(row)
        headings_below = [text for y, text in headings if not prices or y < prices[-1][0]]
        if headings_below:                       # a heading at the foot of a page
            section = headings_below[-1].title()
    if not rows:
        raise ValueError("No price list rows were found in that file.")
    for r in rows:
        if not r["sku"] or not r["name"]:
            raise ValueError(f"A row could not be read: {r['sku'] or '(no SKU)'} {r['name']!r}")
    skus = [r["sku"] for r in rows]
    twice = sorted({s for s in skus if skus.count(s) > 1})
    if twice:
        raise ValueError(f"The list holds an item number twice: {', '.join(twice)}")
    return rows


_CARD_LABELS = ("UPC", "Brand", "Specs", "Kosher", "Price")


def _then(m, n):
    """Two PDF matrices [a b c d e f] as one: `m` first, then `n`."""
    return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]


def _box(m, x0, y0, x1, y1):
    """The box (left, bottom, right, top) around a rectangle moved by matrix `m`."""
    xs = [x * m[0] + y * m[2] + m[4] for x in (x0, x1) for y in (y0, y1)]
    ys = [x * m[1] + y * m[3] + m[5] for x in (x0, x1) for y in (y0, y1)]
    return min(xs), min(ys), max(xs), max(ys)


def _shown(page):
    """What a page shows, where it shows it: (texts, pictures). `texts` are
    (y, x, text, size) in page points, a lone space included (a word set
    letter by letter has its spaces as pieces of their own); `pictures` are
    (left, bottom, right, top, object, matrix): an image, or a drawing placed
    as a picture (a product's artwork), with the matrix that places it.

    A page of CH Butcher's catalog is partly pasted together: a card cut out
    of another page and moved here is a form with a clip box and a shift, and
    the reader's own positions ignore both. So the page's own text is read
    with its forms left out; a form that is only shifted has its text and
    images read apart, kept where they fall inside its clip box, and shifted;
    any other form (scaled or turned) is a picture, and the lettering inside
    it is not text of the list."""
    from pypdf.generic import DictionaryObject, NameObject

    texts, pictures, forms = [], [], []
    resources = page["/Resources"] if "/Resources" in page else {}        # ([] follows a reference)
    xobjects = resources["/XObject"] if "/XObject" in resources else {}

    def text_into(out):
        def on_text(text, cm, tm, _font, size):
            if text.strip() or "\xa0" in text or text == " ":
                out.append((tm[4] * cm[1] + tm[5] * cm[3] + cm[5], tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                            " ".join(text.split()), abs(size) * abs(tm[3] or tm[0])))
        return on_text

    def on_draw(operator, args, cm, _tm):
        if operator == b"Do" and args and args[0] in xobjects:
            obj = xobjects[args[0]]
            if obj.get("/Subtype") == "/Image":
                pictures.append((*_box(cm, 0, 0, 1, 1), obj, list(cm)))
            else:
                forms.append((obj, list(cm)))

    # The page's own text, with its forms out of the way for the moment.
    images = DictionaryObject({k: v for k, v in xobjects.items() if v.get("/Subtype") == "/Image"})
    try:
        resources[NameObject("/XObject")] = images
        page.extract_text(visitor_text=text_into(texts), visitor_operand_before=on_draw)
    finally:
        if xobjects:
            resources[NameObject("/XObject")] = xobjects
    for form, cm in forms:
        m = _then([float(v) for v in form.get("/Matrix") or (1, 0, 0, 1, 0, 0)], cm)
        left, bottom, right, top = (float(v) for v in form["/BBox"])
        if max(abs(m[0] - 1), abs(m[3] - 1), abs(m[1]), abs(m[2])) > 0.01:
            pictures.append((*_box(m, left, bottom, right, top), form, cm))
            continue
        inner, held = [], []

        def find(scope, name):                   # a name inside the form, or inside a form it holds
            inside = (scope.get("/Resources") or {}).get("/XObject") or {}
            if name in inside:
                return inside[name]
            for child in inside.values():
                if child.get("/Subtype") == "/Form" and (got := find(child, name)) is not None:
                    return got
            return None

        def on_inner(operator, args, icm, _tm, form=form, held=held):
            obj = find(form, args[0]) if operator == b"Do" and args else None
            if obj is not None and obj.get("/Subtype") == "/Image":
                held.append((obj, list(icm)))

        page.extract_xform_text(form, (0, 90, 180, 270), 200.0, on_inner, None, text_into(inner))
        for y, x, text, size in inner:
            if left <= x <= right and bottom <= y <= top:
                texts.append((y + m[5], x + m[4], text, size))
        for obj, icm in held:
            l, b, r, t = _box(icm, 0, 0, 1, 1)
            if left <= (l + r) / 2 <= right and bottom <= (b + t) / 2 <= top:
                pictures.append((*_box(_then(icm, m), 0, 0, 1, 1), obj, _then(icm, m)))
    return texts, pictures


def read_cards_pdf(path, brand, section="Other"):
    """The rows of a price list laid out as CARDS, two to a row (CH Butcher's
    "Product catalog"): each card is a name in capitals (sometimes followed by
    its flavour in small capitals), then lines "UPC ...", "Brand ...", "Specs
    ..." (one or two lines), "Kosher ...", "Price ...", with a picture in a
    grey tile to its left. Returns dicts like read_pdf()'s, plus `certifier`
    (the card's Kosher line as printed), `group` (the name without the flavour,
    e.g. "BEEF TALLOW") and with `picture` as {'object', 'matrix'} (the image
    or drawing the page shows in the card's tile; make_photos() draws it).
    `price` is None where the card prints no figure ("TBD").

    Such a list prints no item numbers, so each item's `sku` is `brand` + "-" +
    its UPC, which stays the same from one issue of the list to the next.
    `brand` is also the row's brand (the owner names it; the list's own
    spelling is not used) and `section` its section (None: the list names no
    section; load() then asks its caller). Raises ValueError when no card is
    found, a card has no UPC or name, or a UPC comes twice."""
    import pypdf

    rows = []
    for page in pypdf.PdfReader(str(path)).pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        texts, pictures = _shown(page)
        # The cards' own lettering is small; headings and the page's address are not.
        texts = [t for t in set(texts) if t[3] < 7.8 and 0 <= t[0] <= height and 0 <= t[1] <= width]
        for left in (True, False):                   # the left column of cards, then the right
            mine = sorted((t for t in texts if (t[1] < width / 2) == left), reverse=True)
            tops = [t for t in mine if t[2] == "UPC"]
            for n, (upc_y, upc_x, _t, _s) in enumerate(tops):
                floor = tops[n + 1][0] + 30 if n + 1 < len(tops) else 0     # the next card's name line
                card = [t for t in mine if floor < t[0] <= upc_y + 30 and t[1] >= upc_x - 2]
                head = sorted((t for t in card if upc_y + 8 < t[0]), key=lambda t: t[1])
                group = " ".join(t[2] for t in head if t[3] >= 6 and t[2])
                # The flavour: small capitals set one letter at a time (a raised comma is an apostrophe).
                small = [t for t in head if t[3] < 6]
                base = min((t[0] for t in small), default=0)
                flavour = " ".join("".join("'" if t[2] == "," and t[0] > base + 1 else (t[2] or " ")
                                           for t in small).split())
                title = " ".join(x for x in (group, flavour) if x)
                fields, label = dict.fromkeys(_CARD_LABELS, ""), None
                # Each label stands on the first line of its value; a second line of a value has none.
                lines = {}
                for y, x, text, _size in card:
                    if y <= upc_y + 8 and text:
                        lines.setdefault(round(y / 3), []).append((x, text))
                for key in sorted(lines, reverse=True):
                    words = [t for _x, t in sorted(lines[key])]
                    found = next((w for w in words if w in _CARD_LABELS), None)
                    label = found or label
                    value = " ".join(w for w in words if w != found)
                    if label:
                        fields[label] = " ".join(x for x in (fields[label], value) if x)
                # The picture: whatever the page draws in the grey tile left of the card.
                tile = (upc_x - 112, upc_y - 62, upc_x - 20, upc_y + 36)
                picture = None
                for l, b, r, t, obj, matrix in pictures:
                    if tile[0] <= (l + r) / 2 <= tile[2] and tile[1] <= (b + t) / 2 <= tile[3] \
                            and r - l > 20 and r - l < 100:
                        picture = {"object": obj, "matrix": matrix, "box": (l, b, r, t)}
                upc = re.sub(r"\D", "", fields["UPC"])
                price = fields["Price"].replace("$", "").replace(",", "")
                if not title or not upc:
                    raise ValueError(f"A card could not be read: {title!r} UPC {fields['UPC']!r} "
                                     f"Price {fields['Price']!r}")
                rows.append({"section": section, "sku": f"{brand}-{upc}", "name": title, "group": group,
                             "upc": upc, "brand": brand, "specs": fields["Specs"],
                             "certifier": fields["Kosher"],
                             "price": float(price) if re.fullmatch(r"\d+(\.\d\d)?", price) else None,
                             "picture": picture, "_at": (page.page_number, -upc_y, not left)})
    if not rows:
        raise ValueError("No price list cards were found in that file.")
    rows.sort(key=lambda r: r["_at"])                # as the pages read
    for r in rows:
        del r["_at"]
    skus = [r["sku"] for r in rows]
    twice = sorted({s for s in skus if skus.count(s) > 1})
    if twice:
        raise ValueError(f"The list holds a UPC twice: {', '.join(twice)}")
    return rows


def ordered(con, state):
    """A price-list state's products in the order its sheet shows them: section
    by section (the sections in the order the lists first name them), and
    inside a section as the lists were loaded, each in its own order."""
    held = {sku: n for n, sku in enumerate(db.snapshot(con, db.inv_source(state))["data"] or {})}
    rows = sorted(db.state_products(con, state), key=lambda r: held.get(r["sku"], len(held)))
    sections = {}
    for r in rows:
        sections.setdefault(r["category"] or "", len(sections))
    return sorted(rows, key=lambda r: sections[r["category"] or ""])       # a stable sort


# What a list prints about an item: (the row's key, the products column that
# holds it, what the page calls it).
PRINTED = (("name", "name", "Description"), ("brand", "brand", "Brand"),
           ("section", "category", "Section"), ("specs", "size", "Specs"),
           ("upc", "upc", "UPC"), ("certifier", "certifier", "Kosher"))


def _printed(row):
    """What the list prints about one item, as kept in the `extra_<st>`
    snapshot: only the things this layout prints (a card names no section, a
    table row no kosher line)."""
    return {key: row[key] for key, _col, _label in PRINTED if row.get(key) is not None}


def _follows(entry, before, row):
    """The supplier's changes to one item that has a catalog entry: a list of
    {field, label, have, list, edited}, one for each thing the list now prints
    differently from its last issue (`before`, the kept `printed`) and that the
    entry does not already say. `edited`: the entry no longer holds what the
    last issue printed (an admin changed it on the site). With no record of
    the last issue nothing is called a change: the entry is left as it is."""
    out = []
    for key, col, label in PRINTED:
        new = row.get(key)
        if new is None or not before or key not in before:
            continue
        have = entry[col] or ""
        if (before[key] or "") != (new or "") and have != (new or ""):
            out.append({"field": key, "label": label, "have": have, "list": new or "",
                        "edited": have != (before[key] or "")})
    return out


def identify(con, state, path):
    """Whose list a PDF is, of the suppliers' lists `state` already holds:
    (name, cards, rows), `cards` True for the card layout (read_cards_pdf(),
    with `name` as the brand and no section) and False for the table
    (read_pdf()). The file is read both ways; it belongs to the list that
    shares the most item numbers with it. Raises ValueError when it reads as
    neither layout or shares no item with any list here (a new supplier's
    list is loaded with manage.py, where its name and layout are given)."""
    import pypdf

    held = db.snapshot(con, db.extra_source(state))["data"] or {}
    names = sorted({v.get("list") for v in held.values() if v.get("list")})
    best, problems = None, []
    for cards in (False, True):
        try:
            rows = read_cards_pdf(path, "", None) if cards else read_pdf(path)
        except ValueError as e:
            problems.append(str(e))
            continue
        except (pypdf.errors.PyPdfError, OSError, KeyError, struct.error):
            raise ValueError("That file does not read as a PDF.") from None
        for name in names:
            mine = {sku for sku, v in held.items() if v.get("list") == name}
            shared = len(mine & {f"{name}-{r['upc']}" if cards else r["sku"] for r in rows})
            if shared and (best is None or shared > best[0]):
                best = (shared, name, cards, rows)
    if best is None:
        raise ValueError(
            ("This file does not read as a price list: " + " ".join(problems)) if len(problems) == 2 else
            "This file reads as a price list, but none of its items is on a list already here ("
            + ", ".join(names) + "). A new supplier's list has to be set up first.")
    _shared, name, cards, rows = best
    if cards:                                    # read with no brand: the list's name is the brand
        rows = [dict(r, brand=name, sku=f"{name}-{r['upc']}") for r in rows]
    return name, cards, rows


def _section_for(row, entries):
    """A section to offer for a new item whose list names none: the section of
    this supplier's items here whose names begin with the same words (its
    `group`, e.g. "BEEF JERKY"), or failing that the group itself ("Beef
    Tallow")."""
    group = (row.get("group") or row["name"]).casefold()
    like = [p["category"] for p in entries
            if (p["name"] or "").casefold().startswith(group) and p["category"]]
    if like:
        return max(set(like), key=like.count)
    return (row.get("group") or row["name"]).title()


def compare(con, state, name, rows):
    """What loading `rows` as the list `name` would change, for the admin to
    see before it is done. A dict of lists: `new` (items with no catalog
    entry: sku, name, specs, upc, price, section or None, suggest (a section to
    offer when the list names none), picture True/False),
    `gone` (on this supplier's last list and not on this one), `prices` (sku,
    name, old, new), `items` (every item of the list that has an entry, for
    the page's price boxes: sku, name, now (the price on the site), list (what
    this list prints), price (what a load leaves: a price typed on the site
    stays, else the list's), typed True/False), `details` (sku, name and
    the changes of _follows()), `photos` (entries with no photo that the list
    has a picture for); and `count`, `same` (items with no change at all),
    `list`, `sections` (the sections the state has now)."""
    extra = db.snapshot(con, db.extra_source(state))["data"] or {}
    prices = db.snapshot(con, db.qbo_source(state))["data"] or {}
    before = {sku for sku, v in extra.items() if v.get("list") == name}
    out = {"list": name, "count": len(rows), "same": 0, "new": [], "gone": [], "prices": [],
           "items": [], "details": [], "photos": [],
           "sections": list(dict.fromkeys(r["category"] or "Other" for r in ordered(con, state)))}
    mine = [p for p in db.state_products(con, state) if p["sku"] in before]
    for r in rows:
        entry, same = db.product(con, r["sku"]), True
        if entry is None:
            out["new"].append({"sku": r["sku"], "name": r["name"], "specs": r["specs"], "upc": r["upc"],
                               "price": r["price"], "section": r["section"],
                               "suggest": None if r["section"] else _section_for(r, mine),
                               "picture": bool(r["picture"])})
            continue
        old = prices.get(r["sku"]) or {}
        typed = bool(old.get("edited"))
        out["items"].append({"sku": r["sku"], "name": entry["name"], "now": old.get("price"),
                             "list": r["price"], "typed": typed,
                             "price": old["price"] if typed else r["price"]})
        if not typed and r["sku"] in before and old.get("price") != r["price"]:
            out["prices"].append({"sku": r["sku"], "name": entry["name"], "old": old.get("price"),
                                  "new": r["price"]})
            same = False
        changes = _follows(entry, (extra.get(r["sku"]) or {}).get("printed"), r)
        if changes:
            out["details"].append({"sku": r["sku"], "name": entry["name"], "changes": changes})
            same = False
        if r["picture"] and not items.photos_of(r["sku"]):
            out["photos"].append({"sku": r["sku"], "name": entry["name"]})
            same = False
        out["same"] += same
    on_list = {r["sku"] for r in rows}
    out["gone"] = [{"sku": sku, "name": extra[sku].get("name") or ""} for sku in extra
                   if sku in before and sku not in on_list]
    return out


def load(con, state, rows, user, name, photos=None, log=print, choices=None):
    """Make `rows` (read_pdf() or read_cards_pdf()) the supplier list called
    `name` ("GEN7", "CHB") of `state`, beside the other suppliers' lists the
    state already holds, and return (added, kept, gone): the SKUs given a new
    catalog entry, those that already had one, and those of this supplier's
    earlier list that this one no longer holds (they leave the catalog page;
    their entries stay). The other suppliers' items, prices and order are not
    touched (the owner, 2026-11-18, on a second supplier: "Can you add to our
    database of meat items?"). Each item's list is the `list` key of its entry
    in the `extra_<st>` snapshot, and `printed` there is what this issue prints
    about it.

    An entry that was already there follows the supplier's changes since the
    last issue and nothing else (_follows(); the owner, 2026-11-19: "update
    all the items and add any new items"), and gets the list's picture when it
    has no photo. A price typed on the site stays.

    `user` is the row the change history is written under ({'id', 'name'}).
    `photos` is {sku: {'grid': bytes, 'detail': bytes}} (make_photos()) for
    entries that are new or have no photo. `choices`, what an admin chose on
    the upload page, all optional: 'sections' {sku: the section of a new item
    whose row names none}, 'skip' [[sku, field]] (supplier's changes NOT to
    take), 'prices' {sku: a price or None} (prices typed over on the upload
    page: each stands in place of the list's, marked as typed by `user`),
    'leave' [sku] (new items NOT to add: they stay off the page and are
    offered again by the next list).
    Raises ValueError, changing nothing, when `state` is not a price-list state
    or when one of the item numbers already belongs to a product of another
    state (one catalog entry serves every state that holds its item number, so
    the two would be shown as one item)."""
    states = db.states(con)
    if not (states.get(state) or {}).get("price_list"):
        raise ValueError(f"{state} is not a price-list state (see STATES in the library).")
    choices = choices or {}
    sections = choices.get("sections") or {}
    skip = {tuple(x) for x in choices.get("skip") or ()}
    leave = set(choices.get("leave") or ())
    rows = [r for r in rows if r["sku"] not in leave or db.product(con, r["sku"]) is not None]
    old_extra = db.snapshot(con, db.extra_source(state))["data"] or {}
    old_prices = db.snapshot(con, db.qbo_source(state))["data"] or {}
    others = [sku for sku, v in old_extra.items() if v.get("list") != name]
    before = set(old_extra) - set(others)
    taken = {sku.casefold(): f"the {old_extra[sku].get('list') or 'other'} list" for sku in others}
    for other in states:
        if other != state:
            for sku in db.snapshot(con, db.inv_source(other))["data"] or {}:
                taken[sku.casefold()] = f"{states[other]['inventory']} ({other})"
    for sku in db.skus(con) - set(old_extra):
        taken.setdefault(sku.casefold(), "the catalog")
    # An item back on the list after an issue without it still has its entry,
    # which no list holds: it is known by its UPC.
    back = {r["sku"] for r in rows if r["upc"] and (e := db.product(con, r["sku"])) is not None
            and e["upc"] == r["upc"] and taken.get(r["sku"].casefold()) == "the catalog"}
    clash = [f"{r['sku']} (already in {taken[r['sku'].casefold()]})" for r in rows
             if r["sku"].casefold() in taken and r["sku"] not in back]
    if clash:
        raise ValueError("These item numbers are already used by another item: " + ", ".join(clash))
    for sku, photo in (photos or {}).items():
        if problem := items.check_photos(photo):
            raise ValueError(f"{sku}: {problem}")

    columns = [d[0] for d in con.execute("SELECT * FROM products LIMIT 0").description]
    added, kept, updated = [], [], 0
    for r in rows:
        entry, photo = db.product(con, r["sku"]), (photos or {}).get(r["sku"])
        if entry is None:
            row = dict(dict.fromkeys(columns), sku=r["sku"], name=r["name"], brand=r["brand"],
                       category=r["section"] or sections.get(r["sku"]) or "Other",
                       size=r["specs"], upc=r["upc"], certifier=r.get("certifier") or None,
                       organic="No")           # the owner, 2026-11-18: Organic is No unless a source says Yes
            items.save(con, r["sku"], row, user, "add", photos=photo or items.KEEP)
            added.append(r["sku"])
            continue
        kept.append(r["sku"])
        takes = {col: r[key] for key, col, _label in PRINTED
                 for c in _follows(entry, (old_extra.get(r["sku"]) or {}).get("printed"), r)
                 if c["field"] == key and (r["sku"], key) not in skip}
        if photo and items.photos_of(r["sku"]):
            photo = None                        # only an entry with no photo gets the list's picture
        if (takes or photo) and items.save(con, r["sku"], dict(entry, **takes), user, "edit",
                                           photos=photo or items.KEEP):
            updated += 1
    # A price an admin typed on the site (db.set_list_price()) stays; its `was`
    # follows the list, so the page still shows what the supplier prints.
    typed = {sku: v for sku, v in old_prices.items() if v.get("edited")}
    prices = {r["sku"]: {"price": r["price"], "name": r["name"]} for r in rows}
    moved = sum(1 for sku, v in prices.items()
                if sku in before and sku not in typed and (old_prices.get(sku) or {}).get("price") != v["price"])
    for sku in prices.keys() & typed.keys():
        was = prices[sku]["price"]
        prices[sku]["price"] = typed[sku]["price"]
        if was != typed[sku]["price"]:
            prices[sku]["edited"] = dict(typed[sku]["edited"], was=was)
    # A price typed over on the upload page (the owner, 2026-11-19: "an open
    # text box so we can replace the pricing right there") stands like one
    # typed on the catalog page.
    for sku, price in (choices.get("prices") or {}).items():
        if sku in prices and prices[sku]["price"] != price:
            was = prices[sku].get("edited", {}).get("was", prices[sku]["price"])
            prices[sku] = {"price": price, "name": prices[sku]["name"]}
            if price != was:
                prices[sku]["edited"] = {"by": user["name"], "at": db.now_utc(), "was": was}
    # The lists keep their order on the page: this one's items take the place
    # of its earlier issue (a list that is new here goes last); the other
    # suppliers' items stay as they stand.
    mine = {r["sku"]: {"name": r["name"], "ml": None, "bpc": None, "list": name,
                       "printed": _printed(r)} for r in rows}
    extra = {}
    for sku, v in old_extra.items():
        if sku in others:
            extra[sku] = v
        else:
            extra.update(mine)                  # at the first item of the earlier issue
    extra.update(mine)
    db.save_snapshot(con, db.qbo_source(state), payload={
        sku: prices[sku] if sku in prices else old_prices[sku]
        for sku in extra if sku in prices or sku in old_prices})
    db.save_snapshot(con, db.extra_source(state), payload=extra)
    db.save_snapshot(con, db.inv_source(state), payload=dict.fromkeys(extra))
    gone = sorted(before - {r["sku"] for r in rows})
    log(f"{states[state]['name']}, {name}: {len(rows)} items on the list; {len(added)} added to the "
        f"catalog, {len(kept)} already there ({updated} of them updated), {moved} prices changed, "
        f"{len(gone)} no longer on the list"
        + (f"; {n} prices typed on the site were kept" if (n := sum(1 for sku in prices.keys() & typed.keys()
                                                                     if prices[sku]["price"] == typed[sku]["price"])) else ""))
    return added, kept, gone


# A sheet of card pictures (make_photos()): cells this many points wide and
# high, so many across and down, each picture inside the middle of its cell.
_CELL_W, _CELL_H, _SHEET_COLS, _SHEET_ROWS, _CELL_FILL, _SHEET_ZOOM = 300, 400, 4, 3, 0.85, 200


def _picture_sheet(pictures):
    """A one-page PDF showing the card pictures `pictures` (a list of
    read_cards_pdf()'s {'object', 'matrix', 'box'}, at most one sheet's worth)
    on white, one to a cell, each as the list's own page draws it (an image
    with its cut-out mask, or a product's artwork) but larger. Bytes."""
    import io

    import pypdf
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=_CELL_W * _SHEET_COLS, height=_CELL_H * _SHEET_ROWS)
    names, draw = DictionaryObject(), []
    for n, pic in enumerate(pictures):
        left, bottom, right, top = pic["box"]
        k = min(_CELL_W * _CELL_FILL / (right - left), _CELL_H * _CELL_FILL / (top - bottom))
        cx = (n % _SHEET_COLS + 0.5) * _CELL_W
        cy = (_SHEET_ROWS - n // _SHEET_COLS - 0.5) * _CELL_H
        m = _then(pic["matrix"], [k, 0, 0, k, cx - k * (left + right) / 2, cy - k * (bottom + top) / 2])
        names[NameObject(f"/P{n}")] = pic["object"].clone(writer).indirect_reference
        draw.append("q " + " ".join(f"{v:.5f}" for v in m) + f" cm /P{n} Do Q")
    content = DecodedStreamObject()
    content.set_data("\n".join(draw).encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): names})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_photos(pictures):
    """The catalog photos of a list's pictures: {sku: {'grid': bytes, 'detail':
    bytes}} from {sku: picture}, a picture as read_pdf() gives it (PNG bytes)
    or as read_cards_pdf() does ({'object', 'matrix', 'box'}: what the list's
    page draws in the card's tile). Made by the site's own photo tool
    (static/item.js, `catalogPhotos`) in the server's Chromium, so they come
    out to the same standard as a photo an admin picks; a blank picture is
    left out. Run from manage.py, never inside the web worker.

    A card's picture may be a drawing (a product's artwork), which only a PDF
    viewer can draw. So card pictures are put on sheets (_picture_sheet()),
    each sheet is opened in the full Chromium's own PDF viewer and
    photographed, and every cell of the photograph goes to the photo tool."""
    from playwright.sync_api import sync_playwright

    if not pictures:
        return {}
    b64 = lambda data: base64.b64encode(data).decode()
    sizes = {kind: f"{w}x{h}" for kind, (w, h) in items.PHOTO_SIZES.items()}
    plain = {sku: pic for sku, pic in pictures.items() if isinstance(pic, bytes)}
    cards = [(sku, pic) for sku, pic in pictures.items() if not isinstance(pic, bytes)]
    per = _SHEET_COLS * _SHEET_ROWS
    made = {}
    # Cut `cells` ([sku, column, row]) out of a picture (`png`; of a sheet when
    # `cols`, else the one cell is the whole picture) and make each one's photos.
    cut = """async ([png, cells, cols, rows, sizes]) => {
        const bytes = t => Uint8Array.from(atob(t), c => c.charCodeAt(0));
        const whole = new Blob([bytes(png)], {type: "image/png"}), bmp = await createImageBitmap(whole);
        let x0 = 0, y0 = 0, cw = bmp.width, ch = bmp.height;
        if (cols) {                  /* the sheet's page: the white between the viewer's grey */
            const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
            const x = c.getContext("2d", {willReadFrequently: true}); x.drawImage(bmp, 0, 0);
            const white = d => d[0] > 252 && d[1] > 252 && d[2] > 252;
            const row = x.getImageData(0, bmp.height >> 1, bmp.width, 1).data;
            let a = 0, b = bmp.width - 1;
            while (a < b && !white(row.subarray(a * 4))) a++;
            while (b > a && !white(row.subarray(b * 4))) b--;
            const col = x.getImageData((a + b) >> 1, 0, 1, bmp.height).data;
            let t = 0, u = bmp.height - 1;
            while (t < u && !white(col.subarray(t * 4))) t++;
            while (u > t && !white(col.subarray(u * 4))) u--;
            x0 = a; y0 = t; cw = (b - a + 1) / cols; ch = (u - t + 1) / rows;
            if (!(cw > 100 && Math.abs(ch / cw - %f) < 0.03)) return null;     /* not drawn yet */
        }
        const out = {};
        for (const [sku, cx, cy] of cells) {
            const edge = cols ? 4 : 0;           /* keep clear of the neighbouring cells */
            const c = document.createElement("canvas"); c.width = Math.floor(cw) - 2 * edge; c.height = Math.floor(ch) - 2 * edge;
            c.getContext("2d").drawImage(bmp, -(x0 + cx * cw + edge), -(y0 + cy * ch + edge));
            const photos = await window.catalogPhotos(cols ? await new Promise(done => c.toBlob(done, "image/png")) : whole, sizes);
            if (!photos) continue;
            out[sku] = {};
            for (const kind in photos) {
                const b = new Uint8Array(await photos[kind].arrayBuffer());
                let t = ""; for (let i = 0; i < b.length; i += 0x8000) t += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
                out[sku][kind] = btoa(t);
            }
        }
        return out;
    }""" % (_CELL_H / _CELL_W)
    PDF_DIR.mkdir(exist_ok=True)
    sheet_file = PDF_DIR / f".pictures-{os.getpid()}.pdf"
    with sync_playwright() as p:
        # The full browser when a sheet has to be shown: only it has a PDF viewer.
        browser = p.chromium.launch(**({"channel": "chromium"} if cards else {}))
        tool = browser.new_page()
        tool.add_script_tag(path=str(db.ROOT / "static" / "item.js"))

        def keep(got):
            for sku, photos in (got or {}).items():
                made[sku] = {kind: base64.b64decode(text) for kind, text in photos.items()}

        for sku, png in plain.items():
            keep(tool.evaluate(cut, [b64(png), [[sku, 0, 0]], 0, 0, sizes]))
        try:
            scale = _SHEET_ZOOM / 100 * 96 / 72
            viewer = browser.new_page(viewport={"width": int(_CELL_W * _SHEET_COLS * scale) + 80,
                                                "height": int(_CELL_H * _SHEET_ROWS * scale) + 80}) if cards else None
            for start in range(0, len(cards), per):
                batch = cards[start:start + per]
                sheet_file.write_bytes(_picture_sheet([pic for _sku, pic in batch]))
                viewer.goto("about:blank")
                viewer.goto(f"{sheet_file.as_uri()}#toolbar=0&navpanes=0&zoom={_SHEET_ZOOM}")
                cells = [[sku, n % _SHEET_COLS, n // _SHEET_COLS] for n, (sku, _pic) in enumerate(batch)]
                # The viewer says nothing when it has finished drawing: the sheet
                # is done when two looks in a row are the same.
                shot, got = None, None
                for _try in range(25):
                    viewer.wait_for_timeout(700)
                    last, shot = shot, viewer.screenshot()
                    if shot == last:             # (the same twice before the sheet shows is not it)
                        seen = tool.evaluate(cut, [b64(shot), cells, _SHEET_COLS, _SHEET_ROWS, sizes])
                        got = seen if seen is not None else got
                        if seen is not None and len(seen) == len(cells):
                            break
                        shot = None
                if got is None:
                    raise ValueError("The list's pictures could not be drawn.")
                keep(got)
        finally:
            sheet_file.unlink(missing_ok=True)
        browser.close()
    return made


# --- a list uploaded on the site -----------------------------------------------

UPLOAD_DIR = db.ROOT / "price-lists"     # the PDFs admins uploaded (not in git)


def _manage(args, timeout):
    """Run `manage.py <args>` as a separate process, one such process at a time
    (the server is small, and some of them start a browser), and return what
    it printed. Raises RuntimeError with its last words when it failed."""
    PDF_DIR.mkdir(exist_ok=True)
    with open(PDF_DIR / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            done = subprocess.run([sys.executable, str(db.ROOT / "manage.py"), *args],
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("it took too long") from None
    if done.returncode != 0:
        # Its last line is the reason (above it: the PDF reader's own warnings).
        raise RuntimeError((done.stderr or done.stdout or "no output").strip().splitlines()[-1][-600:])
    return done.stdout.strip()


def _pending(token):
    if not re.fullmatch(r"[0-9a-f]{16}", token or ""):
        return None
    return UPLOAD_DIR / f"pending-{token}.pdf"


def upload_read(state, data):
    """Keep an uploaded PDF (`data`, its bytes) and say what loading it would
    do: (token, the dict of compare() plus 'cards'). Nothing in the catalog
    changes. Raises RuntimeError with the reason when it does not read as one
    of the state's lists (the file is then kept as price-lists/failed-...)."""
    UPLOAD_DIR.mkdir(exist_ok=True)
    for kind, days in (("pending-*", 1), ("failed-*", 14)):    # never confirmed; not read
        for old in UPLOAD_DIR.glob(kind):
            if old.stat().st_mtime < time.time() - days * 86400:
                old.unlink(missing_ok=True)
    token = secrets.token_hex(8)
    pdf = _pending(token)
    pdf.write_bytes(data)
    try:
        _manage(["read-price-list", state, str(pdf), str(pdf.with_suffix(".json"))], 45)
    except RuntimeError:
        # Kept for two weeks, so the reason it did not read can be looked into.
        os.replace(pdf, UPLOAD_DIR / f"failed-{date.today().isoformat()}-{token}.pdf")
        raise
    return token, json.loads(pdf.with_suffix(".json").read_text())


def upload_seen(token):
    """What upload_read() said about a kept upload, or None when it is gone."""
    pdf = _pending(token)
    if pdf is None or not pdf.exists() or not pdf.with_suffix(".json").exists():
        return None
    return json.loads(pdf.with_suffix(".json").read_text())


def upload_apply(state, token, choices, by):
    """Start loading the upload the admin confirmed, with their `choices` (see
    load()), under the name `by` in Item history. The loading runs on its own
    (`manage.py load-price-list --photos --report`): making the photos of many
    new items takes longer than a page can wait. upload_state() says how it
    went. Raises RuntimeError when the upload is no longer here."""
    seen, pdf = upload_seen(token), _pending(token)
    if seen is None:
        raise RuntimeError("that upload is no longer here; upload the file again")
    plan = pdf.with_suffix(".choices")
    plan.write_text(json.dumps(choices))
    pdf.with_suffix(".json").replace(pdf.with_suffix(".loading"))     # confirmed: not to be loaded twice
    subprocess.Popen([sys.executable, str(db.ROOT / "manage.py"), "load-price-list", state, str(pdf),
                      "--list", seen["list"], "--by", by, "--photos", "--choices", str(plan),
                      "--report", str(pdf.with_suffix(".report")), *(["--cards"] if seen["cards"] else [])],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def upload_state(state, token):
    """How a confirmed upload is doing: None (no such upload), {'running':
    True}, or {'ok': True/False, 'message': the loader's report or the reason
    it failed}. Once it has loaded, the PDF is kept as
    price-lists/<state>-<list>-<day>.pdf. A load that has said nothing for
    ten minutes is called failed."""
    pdf = _pending(token)
    if pdf is None:
        return None
    report, loading = pdf.with_suffix(".report"), pdf.with_suffix(".loading")
    if report.exists():
        said = json.loads(report.read_text())
        if said["ok"] and pdf.exists() and loading.exists():
            os.replace(pdf, UPLOAD_DIR / f"{state}-{json.loads(loading.read_text())['list']}-"
                                         f"{date.today().isoformat()}.pdf")
        for done in (loading, pdf.with_suffix(".choices")):
            done.unlink(missing_ok=True)
        return said
    if not loading.exists():
        return None
    if loading.stat().st_mtime < time.time() - 600:
        return {"ok": False, "message": "The loading stopped without a report."}
    return {"running": True}


# --- the downloaded PDF ---------------------------------------------------------

PDF_DIR = db.ROOT / "pdf-cache"


def _logo(state):
    path = db.ROOT / "static" / f"logo-{state.lower()}.png"
    return path if path.exists() else None


def _inline(path):
    """A picture file as a data: address, so the sheet is one self-contained
    page (and the browser lets write_pdf() redraw the pictures smaller)."""
    kind = {".png": "png", ".webp": "webp", ".jpg": "jpeg"}[path.suffix.lower()]
    return f"data:image/{kind};base64,{base64.b64encode(path.read_bytes()).decode()}"


def sheet_rows(con, state, prices, only=None):
    """The list's items in the list's own order, as the sheet prints them:
    dicts with sku, name, upc, brand, specs, section, photo (a Path or None)
    and, when `prices`, price (a float or None). `only`: a set of SKUs to keep
    (what the page is showing: the owner, 2026-11-18, "the pdf only prints
    what's been filtered at that moment"); None = every item."""
    listed = db.snapshot(con, db.qbo_source(state))["data"] or {}
    rows = []
    for r in ordered(con, state):
        if only is not None and r["sku"] not in only:
            continue
        photo = items.PHOTO_DIR / "grid" / f"{r['sku']}.webp"
        row = {"sku": r["sku"], "name": r["name"], "upc": r["upc"] or "", "brand": r["brand"] or "",
               "specs": r["size"] or "", "section": r["category"] or "Other",
               "photo": photo if photo.exists() else None, "photo_v": r["photo_v"]}
        if prices:
            row["price"] = (listed.get(r["sku"]) or {}).get("price")
        rows.append(row)
    return rows


def sheet_html(con, state, prices, only=None):
    """The whole sheet as one HTML page for printing: the state's logo, the
    day and the state's contact line, then every item under its section heading, with the Price column only
    when `prices`."""
    e = html.escape
    name = db.states(con)[state]["name"]
    contact = db.states(con)[state].get("contact") or ""
    logo = _logo(state)
    body, section = [], None
    cols = 6 + bool(prices)
    for r in sheet_rows(con, state, prices, only):
        if r["section"] != section:
            section = r["section"]
            body.append(f'<tr class="sec"><th colspan="{cols}">{e(section)}</th></tr>')
        pic = f'<img src="{_inline(r["photo"])}" alt="">' if r["photo"] else ""
        price = ""
        if prices:
            price = '<td class="num">' + ("" if r["price"] is None else f"${r['price']:,.2f}") + "</td>"
        body.append(f'<tr><td class="pic">{pic}</td><td class="mono">{e(r["sku"])}</td>'
                    f'<td class="name">{e(r["name"])}</td><td class="mono">{e(r["upc"])}</td>'
                    f'<td>{e(r["brand"])}</td><td>{e(r["specs"])}</td>{price}</tr>')
    today = date.today().strftime("%B %-d, %Y")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{e(name)} price list</title>
<style>
@page {{ size: Letter; margin: 0.5in 0.5in 0.6in }}
body {{ font: 9.5pt/1.3 Helvetica, Arial, "Liberation Sans", sans-serif; color: #111; margin: 0 }}
header {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 1.5pt solid #111; padding-bottom: 6pt; margin-bottom: 4pt }}
header img {{ height: 96pt }}
header h1 {{ font-size: 18pt; margin: 0; text-align: right }}
header p {{ margin: 3pt 0 0; text-align: right; color: #444 }}
header p.contact {{ margin-top: 8pt; color: #111; font-size: 10.5pt; font-weight: 600 }}
table {{ border-collapse: collapse; width: 100% }}
thead th {{ font-size: 7.5pt; text-transform: uppercase; letter-spacing: .05em; color: #444; text-align: left; padding: 5pt 4pt; border-bottom: 1pt solid #111 }}
td {{ padding: 3pt 4pt; border-bottom: .5pt solid #bbb; vertical-align: middle }}
tr {{ break-inside: avoid }}
tr.sec {{ break-after: avoid }}
tr.sec th {{ text-align: left; font-size: 10pt; text-transform: uppercase; letter-spacing: .04em; background: #e4e7e8; padding: 5pt 4pt; border-bottom: 1pt solid #111 }}
.pic {{ width: 30pt; height: 38pt; padding: 2pt 4pt }}
.pic img {{ width: 28.5pt; height: 38pt; object-fit: contain; display: block }}
.mono {{ font-family: "Courier New", "Liberation Mono", monospace; font-size: 8.5pt; white-space: nowrap }}
.name {{ font-weight: 600 }}
.num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums }}
</style></head><body>
<header>{f'<img src="{_inline(logo)}" alt="">' if logo else f"<b>{e(name)}</b>"}
<div><h1>Price List</h1><p>{e(today)}</p>{f'<p class="contact">{e(contact)}</p>' if contact else ''}</div></header>
<table><thead><tr><th></th><th>SKU</th><th>Description</th><th>UPC</th><th>Brand</th><th>Specs</th>{'<th class="num">Price</th>' if prices else ''}</tr></thead>
<tbody>{''.join(body)}</tbody></table></body></html>"""


def write_pdf(con, state, prices, path, only=None):
    """Print the sheet to a PDF file at `path` with the server's Chromium
    (letter pages, "Page n of N" at the foot). Run from manage.py, never
    inside the web worker."""
    from playwright.sync_api import sync_playwright

    PDF_DIR.mkdir(exist_ok=True)
    page_file = PDF_DIR / f".sheet-{os.getpid()}.html"
    page_file.write_text(sheet_html(con, state, prices, only), encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(page_file.as_uri())
            # The catalog photos are 600 x 800; printed whole they make a 20 MB
            # file. Each is redrawn at the size the sheet shows it (three times
            # over, for a sharp print) and the logo is left as it is.
            page.evaluate("""async () => {
                for (const img of document.querySelectorAll("td.pic img")) {
                    await img.decode().catch(() => {});
                    if (!img.naturalWidth) { img.remove(); continue; }
                    const c = document.createElement("canvas"); c.width = 120; c.height = 160;
                    const x = c.getContext("2d"); x.fillStyle = "#fff"; x.fillRect(0, 0, 120, 160);
                    x.imageSmoothingQuality = "high"; x.drawImage(img, 0, 0, 120, 160);
                    img.src = c.toDataURL("image/jpeg", 0.85);
                    await img.decode().catch(() => {});
                }
            }""")
            page.pdf(path=str(path), format="Letter", print_background=True,
                     display_header_footer=True, header_template="<span></span>",
                     footer_template=('<div style="font: 8px Helvetica, Arial, sans-serif; width: 100%; '
                                      'text-align: center; color: #555">Page <span class="pageNumber"></span>'
                                      ' of <span class="totalPages"></span></div>'),
                     margin={"top": "0.5in", "bottom": "0.6in", "left": "0.5in", "right": "0.5in"})
            browser.close()
    finally:
        page_file.unlink(missing_ok=True)


def pdf_file(con, state, prices, only=None):
    """The path of the sheet's PDF (of the SKUs in `only`, or of every item), made now if the list, a price, a photo, the
    logo or the day has changed since the last one (otherwise the kept file is
    returned at once). The printing runs as a separate `manage.py
    price-list-pdf` process, one at a time. Raises RuntimeError with the reason
    when the PDF could not be made."""
    logo = _logo(state)
    stamp = json.dumps([sheet_rows(con, state, prices, only), date.today().isoformat(),
                        db.states(con)[state].get("contact"),
                        logo.stat().st_mtime if logo else None], default=str, sort_keys=True)
    # A sheet of part of the list is kept apart from the whole one (one of each).
    kind = f"{state}-{'prices' if prices else 'plain'}-{'all' if only is None else 'part'}-"
    path = PDF_DIR / f"{kind}{hashlib.sha1(stamp.encode()).hexdigest()[:16]}.pdf"
    if path.exists():
        return path
    tmp = path.with_suffix(".new")
    try:
        _manage(["price-list-pdf", state, str(tmp), *(["--prices"] if prices else []),
                 *(["--only", ",".join(sorted(only))] if only is not None else [])], 50)
    except RuntimeError as e:
        raise RuntimeError(f"making the PDF: {e}") from None
    if not tmp.exists():
        raise RuntimeError("making the PDF: no file was written")
    os.replace(tmp, path)
    for old in PDF_DIR.glob(kind + "*.pdf"):
        if old != path:
            old.unlink(missing_ok=True)
    return path
