"""Catalog.db: the catalog site's own SQLite database.

Owner's rule (2026-11-13): "QBO will be read for invoicing. MMK will be read for
QTY on HAND. Our Catalog.db will hold all the item data."

Tables:

  products       One row per Satla SKU. The item data: names, descriptions, filter
                 fields, bottles per case, ml. First loaded from
                 Satla_Master_Catalog.csv (`manage.py load-products`); bottles per
                 case and ml are filled from QuickBooks / MMK (`manage.py load-pack`).
  users          Logins (email, name, hashed password, is_admin). There is no
                 sign-up. An admin (owner, 2026-11-15) manages logins on the
                 site's Admin page; `manage.py add-user` still works too.
  live_snapshot  The LAST READ of regular prices and quantity on hand from
                 QuickBooks (Illinois, Florida) and MMK. This is a cache of a read,
                 not item data: `manage.py refresh` rewrites it on a timer and the
                 pages show its "as of" time. Nothing here is ever written back to
                 QuickBooks or MMK.
  qbo_customers  The LAST READ of each QuickBooks company's customers (name,
  qbo_invoices   address, contact, balance) and of its invoices for the last 12
                 months with their line items. Also a cache of a read: the same
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
    pack_source      TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS qbo_customers (
    company TEXT NOT NULL,          -- 'IL' or 'FL': which QuickBooks company
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
CREATE TABLE IF NOT EXISTS live_snapshot (
    source       TEXT PRIMARY KEY,
    attempted_at TEXT,
    fetched_at   TEXT,
    ok           INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    payload      TEXT
);
"""

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
    con.close()
    DB_PATH.chmod(0o600)                          # holds password hashes


# --- products ---------------------------------------------------------------

def all_products(con):
    """Every product, sorted by brand then name (the catalog has no sort control)."""
    rows = con.execute("SELECT * FROM products").fetchall()
    return sorted(rows, key=lambda r: ((r["brand"] or "") + (r["name"] or "")).casefold())


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


def add_user(con, name, email, password_hash, is_admin=False):
    """Create a login. The caller hashes the password (werkzeug) and has already
    checked that the email is free."""
    with con:
        con.execute("INSERT INTO users (email, name, password_hash, created_at, is_admin) "
                    "VALUES (?,?,?,?,?)", (email.strip().lower(), name.strip(),
                                           password_hash, now_utc(), int(bool(is_admin))))


def update_user(con, uid, **fields):
    """Change a login: any of password_hash, active, is_admin, name."""
    allowed = {"password_hash", "active", "is_admin", "name"}
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
            "contact, phone, email, balance) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(company, c["id"], c["name"], c["street"], c["city"], c["state"], c["zip"],
              c["contact"], c["phone"], c["email"], c["balance"]) for c in customers])
        con.executemany(
            "INSERT INTO qbo_invoices (company, id, doc_number, customer_id, txn_date, "
            "total, balance, lines) VALUES (?,?,?,?,?,?,?,?)",
            [(company, v["id"], v["doc_number"], v["customer_id"], v["txn_date"],
              v["total"], v["balance"], json.dumps(v["lines"])) for v in invoices])


def customers(con):
    """Every customer of both companies, by name."""
    rows = con.execute("SELECT company, id, name, city, state FROM qbo_customers").fetchall()
    return sorted(rows, key=lambda r: (r["name"] or "").casefold())


def customer(con, company, cid):
    return con.execute("SELECT * FROM qbo_customers WHERE company = ? AND id = ?",
                       (company, cid)).fetchone()


def customer_invoices(con, company, cid):
    """A customer's invoices, newest first."""
    return con.execute(
        "SELECT * FROM qbo_invoices WHERE company = ? AND customer_id = ? "
        "ORDER BY txn_date DESC, CAST(doc_number AS INTEGER) DESC",
        (company, cid)).fetchall()


def invoice(con, company, iid):
    return con.execute("SELECT * FROM qbo_invoices WHERE company = ? AND id = ?",
                       (company, iid)).fetchone()


def last_prices(con, company, cid):
    """{sku: {'price', 'date'}}: what this customer last paid per case for each
    product, from the most recent QuickBooks invoice that includes it."""
    return {r["sku"]: {"price": r["price"], "date": r["txn_date"]} for r in con.execute(
        "SELECT sku, price, txn_date FROM qbo_last_prices WHERE company = ? AND customer_id = ?",
        (company, cid))}
