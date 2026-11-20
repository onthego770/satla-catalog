"""Catalog.db: the catalog site's own SQLite database.

Owner's rule (2026-11-13): "QBO will be read for invoicing. MMK will be read for
QTY on HAND. Our Catalog.db will hold all the item data."

Tables:

  products       One row per Satla SKU. The item data: names, descriptions, filter
                 fields, bottles per case, ml. First loaded from
                 Satla_Master_Catalog.csv (`manage.py load-products`); bottles per
                 case and ml are filled from QuickBooks / MMK (`manage.py load-pack`).
                 Since 2026-11-16 this table is the MASTER: admins edit, add and
                 delete items on the site (catalog_items.py), and the file is
                 rewritten from it after every change. `photo_v` changes when
                 the product's photo does, so browsers fetch the new one.
  product_changes  The history of those changes: who, when, the row before and
                 after (JSON; NULL = no catalog entry), and whether the photos
                 changed (the earlier ones are kept in photos/history/<id>/).
                 The History page undoes a change from it.
  users          Logins (email, name, hashed password, is_admin, states). `states`
                 is the comma-separated list of state codes the login may use
                 ("IL,FL"; owner, 2026-11-15). There is no sign-up. An admin (owner, 2026-11-15) manages logins on the
                 site's Admin page; `manage.py add-user` still works too.
                 A price-list state (see `states`) keeps its items here too:
                 the list's section is the `category`, its "Specs" the `size`,
                 and `upc` its UPC (catalog_pricelist.py).
  live_snapshot  The LAST READ, per state: `qbo_<st>` = regular prices from that
                 state's QuickBooks company; `inv_<st>` = cases on hand for the
                 catalog products that state HAS (Illinois: MMK; Florida:
                 QuickBooks Florida), which is also the list of what the state
                 sells; `states` = the states themselves, copied from the
                 library's STATES table. For a price-list state (the Meat
                 list) the same three keys hold the supplier's price list as
                 last loaded by `manage.py load-price-list`, and the timer
                 leaves them alone. This is a cache of a read,
                 not item data: `manage.py refresh` rewrites it on a timer and the
                 pages show its "as of" time. Nothing here is ever written back to
                 QuickBooks or MMK.
  qbo_customers  The LAST READ of each QuickBooks company's customers (name,
  qbo_invoices   address, contact, balance, salesman) and of its invoices for a little
                 over two years (catalog_live.HISTORY_DAYS) with their line items. Also a cache of a read: the same
                 timer replaces both tables, per company, each time it runs.
  qbo_last_prices  What each customer last paid per case for each product: the
                 most recent QuickBooks invoice, however old, that includes it.
                 The New Order screen starts each price here ("previous price").
                 Replaced by the same timer, with the two tables above.
                 Customers and orders come from QuickBooks only (owner,
                 2026-11-14); KOVAL customers and orders live only in MMK and are
                 never read, so they cannot appear here.

This module has no third-party imports, so the web worker stays small. Everything
that talks to QuickBooks or MMK lives in catalog_live.py and goes through the
existing library in ~/python/qbo_scripts.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "Catalog.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku              TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    size             TEXT,
    brand            TEXT,
    category         TEXT,
    type             TEXT,
    style            TEXT,
    sweetness        TEXT,
    grape            TEXT,
    country          TEXT,
    region           TEXT,
    subregion        TEXT,
    abv              TEXT,
    kosher           TEXT,
    mevushal         TEXT,
    kfp              TEXT,
    organic          TEXT,
    certifier        TEXT,
    vintage          TEXT,
    description      TEXT,
    qbo_item_id      TEXT,
    bottles_per_case REAL,
    bottle_ml        REAL,
    pack_source      TEXT,
    upc              TEXT,
    photo_v          INTEGER             -- set when the photo changes (cache key); NULL = never changed
);
CREATE TABLE IF NOT EXISTS product_changes (
    id        INTEGER PRIMARY KEY,
    at        TEXT NOT NULL,             -- UTC, as now_utc()
    user_id   INTEGER,
    user_name TEXT,
    sku       TEXT NOT NULL,
    action    TEXT NOT NULL,             -- 'add', 'edit', 'delete', 'undo'
    before    TEXT,                      -- JSON of the products row; NULL = was not in the catalog
    after     TEXT,                      -- JSON of the products row; NULL = no longer in the catalog
    photo     INTEGER NOT NULL DEFAULT 0, -- 1 = new photos put in, 2 = photos removed; the earlier ones are in photos/history/<id>/
    undoes    INTEGER                    -- for an 'undo': the id of the change it took back
);
CREATE INDEX IF NOT EXISTS product_changes_by_sku ON product_changes (sku, id);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    states        TEXT NOT NULL DEFAULT ''   -- "IL,FL": the states this login may use
);
CREATE TABLE IF NOT EXISTS qbo_customers (
    company TEXT NOT NULL,          -- state code ('IL', 'FL'): which QuickBooks company
    id      TEXT NOT NULL,          -- QuickBooks Customer Id (per company)
    name    TEXT,
    street  TEXT,
    city    TEXT,
    state   TEXT,
    zip     TEXT,
    contact TEXT,
    phone   TEXT,
    email   TEXT,
    balance REAL,
    salesman TEXT,                  -- the customer's SALESMAN custom field in QuickBooks ('' = not set)
    PRIMARY KEY (company, id)
);
CREATE TABLE IF NOT EXISTS qbo_invoices (
    company     TEXT NOT NULL,
    id          TEXT NOT NULL,      -- QuickBooks Invoice Id (per company)
    doc_number  TEXT,
    customer_id TEXT,
    txn_date    TEXT,               -- YYYY-MM-DD
    total       REAL,
    balance     REAL,               -- 0 = paid
    lines       TEXT,               -- JSON: [{sku, name, qty, price, amount}]
    PRIMARY KEY (company, id)
);
CREATE INDEX IF NOT EXISTS qbo_invoices_by_customer
    ON qbo_invoices (company, customer_id, txn_date);
CREATE TABLE IF NOT EXISTS qbo_last_prices (
    company     TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    sku         TEXT NOT NULL,
    price       REAL NOT NULL,      -- per case, as on the invoice line
    txn_date    TEXT NOT NULL,      -- YYYY-MM-DD of that invoice
    PRIMARY KEY (company, customer_id, sku)
);
CREATE TABLE IF NOT EXISTS hidden_items (
    sku       TEXT PRIMARY KEY,   -- an inventory item kept off Admin > Add items (both states)
    hidden_at TEXT NOT NULL,
    hidden_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_snapshot (
    source       TEXT PRIMARY KEY,
    attempted_at TEXT,
    fetched_at   TEXT,
    ok           INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    payload      TEXT
);
"""

# CSV column -> products column: the pack figures, which the file gained when
# Catalog.db became the master (2026-11-16), so the file is a complete copy.
CSV_PACK_COLUMNS = {
    "Bottles per Case": "bottles_per_case",
    "Bottle ml": "bottle_ml",
    "Pack Source": "pack_source",
}
# CSV column -> products column: added with the Meat price list (2026-11-18).
# Written by the export; `manage.py load-products` reads it when the file has it.
CSV_LATER_COLUMNS = {
    "UPC": "upc",
}

# CSV column -> products column. Only the columns the handoff marks "use".
CSV_COLUMNS = {
    "Satla SKU": "sku",
    "Satla Product Name": "name",
    "Bottle Size": "size",
    "Brand": "brand",
    "Category": "category",
    "Type": "type",
    "Style": "style",
    "Sweetness": "sweetness",
    "Grape / Base": "grape",
    "Country": "country",
    "Region": "region",
    "Sub-region / Appellation": "subregion",
    "ABV": "abv",
    "Kosher": "kosher",
    "Mevushal": "mevushal",
    "Kosher for Passover": "kfp",
    "Organic": "organic",
    "Kosher Certifier": "certifier",
    "Vintage": "vintage",
    "Product Description": "description",
    "QBO Item ID": "qbo_item_id",
}


def now_utc():
    """Current time as an ISO string in UTC, the form every timestamp here uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    """A connection with rows addressable by column name."""
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def init():
    """Create the database file and tables if they are missing. Safe to re-run."""
    con = connect()
    with con:
        con.execute("PRAGMA journal_mode=WAL")   # the web reads while the timer writes
        con.executescript(SCHEMA)
        # Columns added after the first release (CREATE TABLE IF NOT EXISTS does
        # not add a column to a table that already exists).
        if "is_admin" not in {r["name"] for r in con.execute("PRAGMA table_info(users)")}:
            con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "states" not in {r["name"] for r in con.execute("PRAGMA table_info(users)")}:
            # Logins made before states existed saw everything: they keep both.
            con.execute("ALTER TABLE users ADD COLUMN states TEXT NOT NULL DEFAULT ''")
            con.execute("UPDATE users SET states = 'IL,FL'")
        if "photo_v" not in {r["name"] for r in con.execute("PRAGMA table_info(products)")}:
            con.execute("ALTER TABLE products ADD COLUMN photo_v INTEGER")
        if "upc" not in {r["name"] for r in con.execute("PRAGMA table_info(products)")}:
            con.execute("ALTER TABLE products ADD COLUMN upc TEXT")
        if "salesman" not in {r["name"] for r in con.execute("PRAGMA table_info(qbo_customers)")}:
            # Filled by the next refresh; until then only admins see customers.
            con.execute("ALTER TABLE qbo_customers ADD COLUMN salesman TEXT")
        # The Illinois on-hand read used to be stored as 'mmk_il'; it is 'inv_il' now.
        con.execute("DELETE FROM live_snapshot WHERE source = 'mmk_il'")
    con.close()
    DB_PATH.chmod(0o600)                          # holds password hashes


# --- products ---------------------------------------------------------------

def product(con, sku):
    return con.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()


def skus(con):
    return {r["sku"] for r in con.execute("SELECT sku FROM products")}


# --- users ------------------------------------------------------------------

def user_by_email(con, email):
    return con.execute("SELECT * FROM users WHERE email = ?",
                       ((email or "").strip().lower(),)).fetchone()


def user_by_id(con, uid):
    return con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def users(con):
    """Every login, by name."""
    return con.execute("SELECT * FROM users ORDER BY name COLLATE NOCASE").fetchall()


def add_user(con, name, email, password_hash, is_admin=False, states=()):
    """Create a login. The caller hashes the password (werkzeug) and has already
    checked that the email is free. `states`: the state codes it may use."""
    with con:
        con.execute("INSERT INTO users (email, name, password_hash, created_at, is_admin, states) "
                    "VALUES (?,?,?,?,?,?)", (email.strip().lower(), name.strip(), password_hash,
                                             now_utc(), int(bool(is_admin)), ",".join(states)))


def user_states(user):
    """The state codes a login may use, as a list."""
    return [c for c in (user["states"] or "").split(",") if c]


def update_user(con, uid, **fields):
    """Change a login: any of password_hash, active, is_admin, name, states
    (states as the stored text, "IL,FL")."""
    allowed = {"password_hash", "active", "is_admin", "name", "states"}
    if not fields or set(fields) - allowed:
        raise ValueError(f"update_user takes only {sorted(allowed)}")
    with con:
        con.execute(f"UPDATE users SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                    (*fields.values(), uid))


def remove_user(con, uid):
    with con:
        con.execute("DELETE FROM users WHERE id=?", (uid,))


def admin_count(con):
    """How many active admins there are (the last one cannot be switched off)."""
    return con.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND active=1").fetchone()[0]


# --- live snapshot ----------------------------------------------------------

STATES_SOURCE = "states"


def qbo_source(state):
    """Snapshot key of a state's regular prices (its QuickBooks company)."""
    return "qbo_" + state.lower()


def inv_source(state):
    """Snapshot key of a state's inventory: which products it has, and cases on hand."""
    return "inv_" + state.lower()


def extra_source(state):
    """Snapshot key of what a state's inventory system says about EVERY item it
    holds, with or without a catalog entry: {sku: {name, ml, bpc}}. It is where
    an item with no catalog entry gets its name, and what an admin adds an item
    from. (The key says "extra" because it first held only the items with no
    catalog entry.)"""
    return "extra_" + state.lower()


MEVUSHAL_IN_NAME = re.compile(r"\(M\)|mevush?al", re.IGNORECASE)


def mevushal(name, value):
    """A product's Mevushal value. The owner's rule (2026-11-15): "any time the
    title says "M" or "Mevusal" the catalog reflects that", so a name holding
    "(M)" or "Mevushal" is Yes whatever the product data says; otherwise the
    product data stands."""
    return "Yes" if MEVUSHAL_IN_NAME.search(name or "") else value


def _size(ml):
    """Bottle size as the catalog writes it: 750 ml, 1.5 L."""
    if not ml:
        return None
    return f"{ml / 1000:g} L" if ml >= 1000 else f"{ml:g} ml"


def state_products(con, state):
    """Every product of one state, as dicts with the products table's columns
    plus `uncataloged`, sorted by brand then name.

    A state's products are the catalog products that have a record in its
    inventory (snapshot inv_<st>), then, for a state that lists its whole
    inventory (`catalog_all` in the library's STATES), the items with no
    catalog entry: see uncataloged(), less the ones an admin hid (the owner,
    2026-11-17: "anything that I deem "Hidden" I don't want to show up on the
    Catalog page"; see hidden_items()). `mevushal` follows the name: see mevushal()."""
    have = snapshot(con, inv_source(state))["data"] or {}
    out = [dict(r, uncataloged=False) for r in con.execute("SELECT * FROM products")
           if r["sku"] in have]
    if (states(con).get(state) or {}).get("catalog_all"):
        hidden = hidden_items(con)
        out += [r for r in uncataloged(con, state) if r["sku"] not in hidden]
    for p in out:
        p["mevushal"] = mevushal(p["name"], p["mevushal"])
    return sorted(out, key=lambda r: ((r["brand"] or "") + (r["name"] or "")).casefold())


def hidden_items(con):
    """{sku: row} of the inventory items an admin took off Admin > Add items
    (the owner, 2026-11-17: "Please remove these from the Admin / Add Items
    list for IL and FL"). They stay in the inventory systems; that list shows
    them apart, and the catalog, product pages and New Order leave them out
    (state_products())."""
    return {r["sku"]: dict(r) for r in con.execute("SELECT * FROM hidden_items")}


def hide_item(con, sku, user_name, hidden=True):
    """Take an item off Admin > Add items (hidden=True) or put it back."""
    with con:
        if hidden:
            con.execute("INSERT OR REPLACE INTO hidden_items (sku, hidden_at, hidden_by) VALUES (?,?,?)",
                        (sku, now_utc(), user_name))
        else:
            con.execute("DELETE FROM hidden_items WHERE sku = ?", (sku,))


def uncataloged(con, state):
    """The items of a state's inventory that have NO catalog entry, as product
    dicts: they carry only what the inventory system knows (SKU, name, bottle
    size, bottles per case), every other column is None, and `uncataloged` is
    True. A state that lists its whole inventory shows them (state_products());
    for every state they are what an admin can add to the catalog."""
    have = snapshot(con, inv_source(state))["data"] or {}
    extra = snapshot(con, extra_source(state))["data"] or {}
    catalog = skus(con)
    columns = [d[0] for d in con.execute("SELECT * FROM products LIMIT 0").description]
    return [dict(dict.fromkeys(columns), sku=sku, name=v["name"] or sku,
                 size=_size(v["ml"]), bottles_per_case=v["bpc"],
                 bottle_ml=v["ml"], uncataloged=True)
            for sku, v in extra.items() if sku in have and sku not in catalog]


def state_product(con, state, sku):
    """One product of a state as state_products() gives it, or None when the
    state does not have it."""
    return next((p for p in state_products(con, state) if p["sku"] == sku), None)


def states(con):
    """{code: {'name', 'inventory', 'catalog_all', 'order_email', 'price_list',
    'price_admin_only'}} for every
    state the last refresh knew, in the library's order. `inventory` names the
    system that holds that state's inventory ("MMK", "QuickBooks Florida");
    `catalog_all` is True for a state whose catalog lists every item of that
    inventory; `order_email` is where an order for a customer of that state is
    emailed ('' = nowhere: the state cannot send orders); `price_list` is True
    for a choice that is a supplier's price list held in Catalog.db (the Meat
    list: no QuickBooks company, no MMK, no stock, customers or orders; see
    catalog_pricelist.py); `price_admin_only` is True when only admins see
    that state's prices; `contact` is the line its price list PDF prints under
    the date ('' = none)."""
    return snapshot(con, STATES_SOURCE)["data"] or {}


STORE_SOURCE = "kww_products"          # the Kosher Wine World product list (catalog_source.listing)
KWD_SOURCE = "kwd_products"            # the Kosher Wine Direct product list (catalog_source.listing_kwd)


def save_snapshot(con, source, payload=None, error=None):
    """Record one read attempt. A failed read keeps the last good figures and
    their time, and stores why it failed, so a page can say "as of ..." honestly
    instead of going blank."""
    stamp = now_utc()
    with con:
        con.execute("INSERT OR IGNORE INTO live_snapshot (source) VALUES (?)", (source,))
        if error is None:
            con.execute("UPDATE live_snapshot SET attempted_at=?, fetched_at=?, ok=1, "
                        "error=NULL, payload=? WHERE source=?",
                        (stamp, stamp, json.dumps(payload), source))
        else:
            con.execute("UPDATE live_snapshot SET attempted_at=?, ok=0, error=? "
                        "WHERE source=?", (stamp, str(error)[:300], source))


def set_list_price(con, state, sku, price, user_name):
    """Change one item's price on a price-list state's list (the owner,
    2026-11-18: the price "in an editable text box. Moving off the text box
    saves the price changes"). `price` is a float, or None for no price.
    Returns False when the list does not hold the SKU.

    The price lives in the state's price snapshot (qbo_source()); the entry is
    marked `edited` = {'by', 'at', 'was'} (`was` = the price the supplier's
    list printed), so the page can say so and a later load of the supplier's
    list keeps the typed price (catalog_pricelist.load()). The snapshot's "as
    of" time, which is when the list was loaded, is not touched."""
    source = qbo_source(state)
    with con:
        con.execute("BEGIN IMMEDIATE")           # two admins typing at once: one after the other
        row = con.execute("SELECT payload FROM live_snapshot WHERE source = ?", (source,)).fetchone()
        data = json.loads(row["payload"]) if row and row["payload"] else {}
        if sku not in data:
            return False
        entry = data[sku]
        if entry.get("price") != price:
            was = entry["edited"]["was"] if entry.get("edited") else entry.get("price")
            entry["price"] = price
            entry["edited"] = {"by": user_name, "at": now_utc(), "was": was}
            if price == was:                     # typed back to the list's own price
                del entry["edited"]
            con.execute("UPDATE live_snapshot SET payload = ? WHERE source = ?", (json.dumps(data), source))
    return True


def snapshot(con, source):
    """{'data': {sku: ...} or None, 'fetched_at', 'attempted_at', 'ok', 'error'}.
    `data` is None only when the source has never been read successfully."""
    r = con.execute("SELECT * FROM live_snapshot WHERE source = ?", (source,)).fetchone()
    if r is None:
        return {"data": None, "fetched_at": None, "attempted_at": None,
                "ok": False, "error": "not read yet"}
    return {"data": json.loads(r["payload"]) if r["payload"] else None,
            "fetched_at": r["fetched_at"], "attempted_at": r["attempted_at"],
            "ok": bool(r["ok"]), "error": r["error"]}


# --- QuickBooks customers and invoices (a cache of the last read) -----------

def replace_company(con, company, customers, invoices, last_prices):
    """Swap in one company's freshly read customers, invoices and last prices,
    all or nothing, so a page never sees half of a read. `last_prices` is
    {(customer_id, sku): (price, 'YYYY-MM-DD')}."""
    with con:
        con.execute("DELETE FROM qbo_customers WHERE company = ?", (company,))
        con.execute("DELETE FROM qbo_invoices WHERE company = ?", (company,))
        con.execute("DELETE FROM qbo_last_prices WHERE company = ?", (company,))
        con.executemany(
            "INSERT INTO qbo_last_prices (company, customer_id, sku, price, txn_date) "
            "VALUES (?,?,?,?,?)",
            [(company, cid, sku, price, day) for (cid, sku), (price, day) in last_prices.items()])
        con.executemany(
            "INSERT INTO qbo_customers (company, id, name, street, city, state, zip, "
            "contact, phone, email, balance, salesman) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(company, c["id"], c["name"], c["street"], c["city"], c["state"], c["zip"],
              c["contact"], c["phone"], c["email"], c["balance"], c.get("salesman") or "")
             for c in customers])
        con.executemany(
            "INSERT INTO qbo_invoices (company, id, doc_number, customer_id, txn_date, "
            "total, balance, lines) VALUES (?,?,?,?,?,?,?,?)",
            [(company, v["id"], v["doc_number"], v["customer_id"], v["txn_date"],
              v["total"], v["balance"], json.dumps(v["lines"])) for v in invoices])


def salesman_key(name):
    """A salesman's name as it is compared: case and spacing do not count, so the
    login "Henry Kogel" matches QuickBooks' "HENRY KOGEL". '' for no name."""
    return " ".join((name or "").split()).casefold()


def customers(con, company, salesman=None):
    """The customers of one state's QuickBooks company, by name. `salesman` None
    (an admin) = every customer; a name = only the customers whose SALESMAN field
    in QuickBooks is that name (the owner, 2026-11-15: "Each salesman should see
    only their own customers"). A customer with no SALESMAN belongs to nobody."""
    rows = con.execute("SELECT company, id, name, city, state, salesman FROM qbo_customers "
                       "WHERE company = ?", (company,)).fetchall()
    if salesman is not None:
        key = salesman_key(salesman)
        rows = [r for r in rows if key and salesman_key(r["salesman"]) == key]
    return sorted(rows, key=lambda r: (r["name"] or "").casefold())


def customer(con, company, cid, salesman=None):
    """One customer, or None when there is no such customer OR it is not
    `salesman`'s (same rule as `customers()`; None = an admin, sees everyone)."""
    row = con.execute("SELECT * FROM qbo_customers WHERE company = ? AND id = ?",
                      (company, cid)).fetchone()
    if row is not None and salesman is not None:
        key = salesman_key(salesman)
        if not key or salesman_key(row["salesman"]) != key:
            return None
    return row


def salesman_counts(con):
    """{(company, salesman_key): number of customers}, for the Admin page: how
    many customers each login sees. Customers with no SALESMAN are under ''."""
    out = {}
    for r in con.execute("SELECT company, salesman FROM qbo_customers"):
        k = (r["company"], salesman_key(r["salesman"]))
        out[k] = out.get(k, 0) + 1
    return out


def customer_invoices(con, company, cid, since=""):
    """A customer's invoices, newest first; `since` ('YYYY-MM-DD') leaves out
    the older ones (the table holds a little over two years; the customer page
    lists twelve months)."""
    return con.execute(
        "SELECT * FROM qbo_invoices WHERE company = ? AND customer_id = ? AND txn_date >= ? "
        "ORDER BY txn_date DESC, CAST(doc_number AS INTEGER) DESC",
        (company, cid, since)).fetchall()


def company_invoices(con, company):
    """Every stored invoice of one state's QuickBooks company, with its lines:
    what catalog_insight.book() is built from."""
    return con.execute("SELECT customer_id, txn_date, total, balance, doc_number, lines "
                       "FROM qbo_invoices WHERE company = ?", (company,)).fetchall()


def order_days(con, company):
    """{customer_id: [the day of each of its stored invoices, 'YYYY-MM-DD']} for
    one state, for the customers list (catalog_insight.customer_flags())."""
    out = {}
    for r in con.execute("SELECT customer_id, txn_date FROM qbo_invoices "
                         "WHERE company = ? AND total > 0", (company,)):
        out.setdefault(r["customer_id"], []).append(r["txn_date"])
    return out


def invoice(con, company, iid):
    return con.execute("SELECT * FROM qbo_invoices WHERE company = ? AND id = ?",
                       (company, iid)).fetchone()


def last_prices(con, company, cid):
    """{sku: {'price', 'date'}}: what this customer last paid per case for each
    product, from the most recent QuickBooks invoice that includes it."""
    return {r["sku"]: {"price": r["price"], "date": r["txn_date"]} for r in con.execute(
        "SELECT sku, price, txn_date FROM qbo_last_prices WHERE company = ? AND customer_id = ?",
        (company, cid))}
