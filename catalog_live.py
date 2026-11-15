"""Reads of QuickBooks and MMK for the catalog site. READ-ONLY.

Every call here goes through the existing library in ~/python/qbo_scripts (the
code behind orders.satlaspirits.com). Nothing is reimplemented:

  Regular price, Florida on hand   mmk_common.get_current_inventory_qbo(qb)
                                   (column unit_price; qty_on_hand)
  Customers                        qbo.fetch_customers(qb)
  Invoices (all of them: the last  qbo.fetch_invoices_since(qb, date)
    12 months are shown; older ones
    only supply previous prices)
  Invoice line items, with SKUs    qbo.fetch_item_skus() + qbo.build_orders()
  Illinois on hand                 mmk_common.get_current_inventory_mmk()
  Bottles per case, ml             the bpc / vol_ml columns of those same two reads

Run with ~/python/venvs/qbo311/bin/python3 (the library's environment). The web
worker never imports this module: `manage.py refresh` runs it on a timer and
stores the result in Catalog.db's live_snapshot table, so a page view costs no
QuickBooks or MMK call and never touches the QuickBooks token.

Two rules inherited from the library's notes:
  * A QuickBooks client always comes from qbo.qbo_client(); the library function
    used here does that itself.
  * A scheduled job must NEVER trigger an MMK login (reCAPTCHA; an account lock
    would take the order system down). So MMK is read only when the saved login
    is already alive; otherwise the read is skipped and the page shows the last
    known figures with their time.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import catalog_db as db

LIBRARY = Path.home() / "python" / "qbo_scripts"
FL_CONFIG = Path.home() / "python" / "config" / "qbo_config_fl.json"

# company code -> (snapshot source key, plain name, QuickBooks config path;
# None is the library's default, the Illinois company)
COMPANIES = {"IL": ("qbo_il", "QuickBooks Illinois", None),
             "FL": ("qbo_fl", "QuickBooks Florida", FL_CONFIG)}
MMK_SOURCE = "mmk_il"
HISTORY_DAYS = 365          # order history: QuickBooks invoices, last 12 months
ALL_INVOICES_FROM = "2000-01-01"   # previous prices use every invoice, however old


def _library():
    """Import the existing API library (lazily: it pulls in pandas)."""
    if str(LIBRARY) not in sys.path:
        sys.path.insert(0, str(LIBRARY))
    import mmk_common as mc
    return mc


def _num(value):
    """A pandas cell as a float, or None for blank / NaN."""
    if value is None or value != value:
        return None
    return float(value)


def read_qbo_items(qb, catalog_skus):
    """{sku: {price, qty, bpc, ml}} for the catalog's SKUs in one QuickBooks
    company (`qb` is a client from qbo.qbo_client()).

    `price` is the regular price per case (None when QuickBooks has none set);
    `qty` is quantity on hand in cases (None for a non-inventory item). Where
    QuickBooks holds two items with the same SKU, the active Inventory one wins.
    """
    mc = _library()
    df = mc.get_current_inventory_qbo(qb=qb)
    df = df[df["sku"].isin(catalog_skus)].copy()
    df["_rank"] = (df["active"].fillna(False).astype(bool) * 2
                   + (df["type"] == "Inventory") * 1)
    df = df.sort_values("_rank", ascending=False).drop_duplicates("sku")
    out = {}
    for r in df.itertuples():
        price = _num(r.unit_price)
        out[r.sku] = {"price": price if price and price > 0 else None,
                      "qty": _num(r.qty_on_hand),
                      "bpc": _num(r.bpc), "ml": _num(r.vol_ml)}
    return out


def read_mmk_stock(catalog_skus):
    """{sku: {cases, bpc, ml}} for the catalog's SKUs that MMK has IN STOCK.

    MMK's report lists in-stock products only, so a catalog SKU that is absent
    here has 0 available. Raises RuntimeError, without attempting a login, when
    the saved MMK login is not alive.
    """
    mc = _library()
    config = mc.load_config(mc.DEFAULT_CONFIG)
    state = mc.cached_session_status(config)
    if state != "alive":
        raise RuntimeError(f"the saved MMK login is {state}; sign in on the MMK login "
                           "tab of orders.satlaspirits.com")
    df = mc.get_current_inventory_mmk(config=config)
    df = df[df["sku"].isin(catalog_skus)]
    return {r.sku: {"cases": _num(r.available_cases), "bpc": _num(r.bpc),
                    "ml": _num(r.vol_ml)} for r in df.itertuples()}


def read_company(config_path, catalog_skus):
    """One QuickBooks company in ONE client session (one token handshake):
    its catalog items, its customers, and its invoices.

    Returns (items, customers, invoices, last_prices). `customers` and `invoices`
    are rows ready for Catalog.db: a customer's address is the billing address,
    or the shipping address when there is no billing one; an invoice carries its
    product lines as [{sku, name, qty, price, amount}], exactly as QuickBooks
    holds them. `invoices` covers the last 12 months only.

    `last_prices` is {(customer_id, sku): (price, 'YYYY-MM-DD')}: for each
    customer and catalog product, the price per case on the most recent invoice
    that includes it, however old (wireframe rule, approved 2026-11-12). A line
    with no price or a price of zero (a free sample) is not a previous price.
    """
    _library()
    import qbo_mmk_salesorder as qbo

    since = date.today() - timedelta(days=HISTORY_DAYS)
    with qbo.qbo_client(config_path) as qb:
        items = read_qbo_items(qb, catalog_skus)
        raw_customers = qbo.fetch_customers(qb)
        raw_invoices = qbo.fetch_invoices_since(qb, ALL_INVOICES_FROM)
        sku_map = qbo.fetch_item_skus(qb, raw_invoices)
    customers = []
    for c in raw_customers:
        addr = c["billing"] if (c["billing"]["street"] or c["billing"]["city"]) else c["shipping"]
        customers.append({"id": c["id"], "name": c["name"], "contact": c["contact"],
                          "phone": c["phone"], "email": c["email"], "balance": c["balance"],
                          **addr})
    invoices, last_prices = [], {}
    cutoff = since.strftime("%Y-%m-%d")
    for o in qbo.build_orders(raw_invoices, "", sku_map):       # oldest first
        day = o["date"].strftime("%Y-%m-%d")
        for ln in o["lines"]:
            price = _num(ln["price"])
            if ln["sku"] in catalog_skus and price and price > 0:
                last_prices[(str(o["customer_id"]), ln["sku"])] = (price, day)
        if day < cutoff:
            continue
        invoices.append({
            "id": str(o["id"]), "doc_number": o["docnumber"], "customer_id": str(o["customer_id"]),
            "txn_date": day,
            "total": _num(o["total"]) or 0.0, "balance": _num(o["balance"]) or 0.0,
            "lines": [{"sku": ln["sku"], "name": ln["name"], "qty": _num(ln["qty"]),
                       "price": _num(ln["price"]), "amount": _num(ln["amount"])}
                      for ln in o["lines"]]})
    return items, customers, invoices, last_prices


def refresh(log=print):
    """Read every source and store it in Catalog.db. One source failing does not
    stop the others; a failure keeps that source's last good figures."""
    db.init()                                        # creates any missing table
    con = db.connect()
    catalog_skus = db.skus(con)
    results = {}
    for company, (source, label, path) in COMPANIES.items():
        try:
            data, customers, invoices, last_prices = read_company(path, catalog_skus)
            db.replace_company(con, company, customers, invoices, last_prices)
            db.save_snapshot(con, source, payload={
                s: {"price": v["price"], "qty": v["qty"]} for s, v in data.items()})
            results[source] = data
            log(f"{label}: {len(data)} catalog items, {len(customers)} customers, "
                f"{len(invoices)} invoices, {len(last_prices)} previous prices read")
        except Exception as e:                       # noqa: BLE001 - keep going
            db.save_snapshot(con, source, error=f"{type(e).__name__}: {e}")
            log(f"{label}: FAILED - {type(e).__name__}: {e}")
    try:
        data = read_mmk_stock(catalog_skus)
        db.save_snapshot(con, MMK_SOURCE, payload={s: v["cases"] for s, v in data.items()})
        results[MMK_SOURCE] = data
        log(f"MMK: {len(data)} catalog items in stock")
    except Exception as e:                           # noqa: BLE001
        db.save_snapshot(con, MMK_SOURCE, error=f"{type(e).__name__}: {e}")
        log(f"MMK: FAILED - {type(e).__name__}: {e}")
    con.close()
    return results


def load_pack(overwrite=False, log=print):
    """Fill products.bottles_per_case and bottle_ml (item data held in Catalog.db)
    from QuickBooks Illinois, then QuickBooks Florida, then MMK: the first source
    that knows the value wins. Blank values only, unless overwrite=True."""
    results = refresh(log=log)
    con = db.connect()
    filled = 0
    with con:
        for row in con.execute("SELECT sku, bottles_per_case, bottle_ml FROM products").fetchall():
            if row["bottles_per_case"] and row["bottle_ml"] and not overwrite:
                continue
            for source in ("qbo_il", "qbo_fl", MMK_SOURCE):
                v = results.get(source, {}).get(row["sku"])
                if v and v.get("bpc") and v.get("ml"):
                    con.execute("UPDATE products SET bottles_per_case=?, bottle_ml=?, "
                                "pack_source=? WHERE sku=?",
                                (v["bpc"], v["ml"], source, row["sku"]))
                    filled += 1
                    break
    missing = [r["sku"] for r in con.execute(
        "SELECT sku FROM products WHERE bottles_per_case IS NULL ORDER BY sku")]
    con.close()
    log(f"bottles per case / ml filled for {filled} products; still unknown for {len(missing)}")
    return missing
