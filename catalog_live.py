"""Reads of QuickBooks and MMK for the catalog site. READ-ONLY.

Every call here goes through the existing library in ~/python/qbo_scripts (the
code behind orders.satlaspirits.com). Nothing is reimplemented, and nothing here
knows which system a state keeps its inventory in: the library's STATES table
does (Illinois: MMK; Florida: QuickBooks Florida), so a state added there shows
up on the site at the next refresh.

  Which products a state has, and   mmk_common.get_current_inventory(state)
    its cases on hand
  Regular price                     mmk_common.get_regular_prices(state)
  Customers                         qbo.fetch_customers(qb)
  Invoices (all of them: the last   qbo.fetch_invoices_since(qb, date)
    12 months are shown; older ones
    only supply previous prices)
  Invoice line items, with SKUs     qbo.fetch_item_skus() + qbo.build_orders()
  Bottles per case, ml              the bpc / vol_ml columns of the first two

Run with ~/python/venvs/qbo311/bin/python3 (the library's environment). The web
worker never imports this module: `manage.py refresh` runs it on a timer and
stores the result in Catalog.db, so a page view costs no QuickBooks or MMK call
and never touches the QuickBooks token.

Two rules inherited from the library's notes:
  * A QuickBooks client always comes from qbo.qbo_client().
  * A scheduled job must NEVER trigger an MMK login (reCAPTCHA; an account lock
    would take the order system down). So inventory is read with
    mmk_login=False: when the saved MMK login is not alive the read is skipped
    and the page shows the last known figures with their time.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import catalog_db as db

LIBRARY = Path.home() / "python" / "qbo_scripts"
HISTORY_DAYS = 800          # invoices kept: a little over two years, so that "this year
                            # against the same days last year" and "bought well, then
                            # stopped" can be worked out (catalog_insight.py). The
                            # customer page still LISTS the last 12 months.
ALL_INVOICES_FROM = "2000-01-01"   # previous prices use every invoice, however old
# The customer custom field in QuickBooks that names the customer's salesman.
# A company that has no such field gives every customer a blank salesman.
SALESMAN_FIELD = "SALESMAN"
# The library's word for a STATES row with no inventory system behind it.
PRICE_LIST = "list"


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


def _wanted(df, skus):
    """The rows of a library table for the SKUs in `skus`; None = every row."""
    return df if skus is None else df[df["sku"].isin(skus)]


def read_inventory(state, skus, qb=None):
    """{sku: {cases, bpc, ml, name}} for the SKUs in `skus` (None = every item)
    that have a record in the state's inventory system (in stock or not; `cases`
    is None only for an item QuickBooks does not track; `name` is that system's
    name for the item). A SKU absent here is not sold in that state. Never
    triggers an MMK login."""
    df = _wanted(_library().get_current_inventory(state, qb=qb, mmk_login=False), skus)
    return {r.sku: {"cases": _num(r.cases_on_hand), "bpc": _num(r.bpc),
                    "ml": _num(r.vol_ml), "name": r.name} for r in df.itertuples()}


def read_company(state, qb, skus):
    """One state's QuickBooks company through ONE client session `qb`: the
    regular prices of the items in `skus` (None = every item), its customers,
    and its invoices.

    Returns (items, customers, invoices, last_prices, history). `items` is
    {sku: {price, bpc, ml, name}}; `price` is the regular price per case (None
    when QuickBooks has none set), `name` what that company calls the item. `customers` and `invoices`
    are rows ready for Catalog.db: a customer's address is the billing address,
    or the shipping address when there is no billing one, and `salesman` is the
    customer's SALESMAN custom field ('' when blank); an invoice carries its
    product lines as [{sku, name, qty, price, amount}], exactly as QuickBooks
    holds them. `invoices` covers the last HISTORY_DAYS days only.

    `last_prices` is {(customer_id, sku): (price, 'YYYY-MM-DD')}: for each
    customer and each of those items, the price per case on the most recent invoice
    that includes it, however old (wireframe rule, approved 2026-11-12). A line
    with no price or a price of zero (a free sample) is not a previous price.
    
    The fifth value, `history`, is every invoice of the company, however old,
    for the kept history (db.keep_invoices()): the same fields plus the
    customer's name, the due date and `raw`, the invoice as QuickBooks gave it.
    """
    mc = _library()
    import qbo_mmk_salesorder as qbo

    since = date.today() - timedelta(days=HISTORY_DAYS)
    prices = mc.get_regular_prices(state, qb=qb)
    items = {r.sku: {"price": _num(r.unit_price), "bpc": _num(r.bpc), "ml": _num(r.vol_ml),
                     "name": r.name}
             for r in _wanted(prices, skus).itertuples()}
    raw_customers = qbo.fetch_customers(qb)
    custom = qbo.fetch_customer_custom_fields(qb)
    raw_invoices = qbo.fetch_invoices_since(qb, ALL_INVOICES_FROM)
    sku_map = qbo.fetch_item_skus(qb, raw_invoices)
    customers = []
    for c in raw_customers:
        addr = c["billing"] if (c["billing"]["street"] or c["billing"]["city"]) else c["shipping"]
        customers.append({"id": c["id"], "name": c["name"], "contact": c["contact"],
                          "phone": c["phone"], "email": c["email"], "balance": c["balance"],
                          "salesman": custom.get(c["id"], {}).get(SALESMAN_FIELD, ""),
                          **addr})
    invoices, last_prices, overdue, opened = [], {}, {}, {}
    history, as_read = [], {str(v.Id): v for v in raw_invoices}
    cutoff = since.strftime("%Y-%m-%d")
    today = date.today().isoformat()
    for o in qbo.build_orders(raw_invoices, "", sku_map):       # oldest first
        day = o["date"].strftime("%Y-%m-%d")
        # Overdue: what is still open on an invoice whose QuickBooks due date
        # has passed (an invoice with no due date is due on its own day). Every
        # invoice counts, however old, not only the ones kept below.
        owed, cid = _num(o["balance"]) or 0.0, str(o["customer_id"])
        if owed > 0.004:
            opened[cid] = opened.get(cid, 0) + 1
            due = o["due"] or day
            if due < today:                 # [amount, invoices, the earliest due date]
                was = overdue.get(cid, [0.0, 0, due])
                overdue[cid] = [was[0] + owed, was[1] + 1, min(was[2], due)]
        for ln in o["lines"]:
            price = _num(ln["price"])
            if ln["sku"] in items and price and price > 0:
                last_prices[(str(o["customer_id"]), ln["sku"])] = (price, day)
        row = {
            "id": str(o["id"]), "doc_number": o["docnumber"], "customer_id": str(o["customer_id"]),
            "txn_date": day,
            "total": _num(o["total"]) or 0.0, "balance": _num(o["balance"]) or 0.0,
            "lines": [{"sku": ln["sku"], "name": ln["name"], "qty": _num(ln["qty"]),
                       "price": _num(ln["price"]), "amount": _num(ln["amount"])}
                      for ln in o["lines"]]}
        # The kept history: EVERY invoice, however old, each line with its SKU,
        # and the invoice exactly as QuickBooks gave it (db.keep_invoices()).
        history.append({**row, "customer": o["customer"], "due_date": o["due"],
                        "raw": as_read[str(o["id"])].to_json()})
        if day < cutoff:
            continue
        invoices.append(row)
    for c in customers:
        # never more than the customer owes in all (a credit can stand against it)
        late = overdue.get(str(c["id"]), [0.0, 0, None])
        c["overdue"] = round(max(0.0, min(late[0], _num(c["balance"]) or 0.0)), 2)
        # how many invoices are open, how many of them are past due, and the
        # due date of the one that has been past due the longest
        c["open_n"], c["overdue_n"], c["overdue_since"] = opened.get(str(c["id"]), 0), late[1], late[2]
    return items, customers, invoices, last_prices, history


def save_states(con):
    """Copy the library's STATES table into Catalog.db (snapshot `states`), for
    the web pages: each state's name, the name of its inventory system, and the
    flags the site acts on. `price_list` marks a row whose inventory is "list":
    a supplier's price list held in Catalog.db, with no QuickBooks company and
    no MMK behind it."""
    mc = _library()
    db.save_snapshot(con, db.STATES_SOURCE, payload={
        code: {"name": info["name"], "inventory": info["inventory_name"],
               "catalog_all": bool(info.get("catalog_all")),
               "order_email": info.get("order_email") or "",
               "price_list": info["inventory"] == PRICE_LIST,
               "price_admin_only": bool(info.get("price_admin_only")),
               "contact": info.get("contact") or ""}
        for code, info in mc.STATES.items()})


def refresh(log=print):
    """Read every state and store it in Catalog.db. One source failing does not
    stop the others; a failure keeps that source's last good figures.

    A price-list state (the Meat list) is skipped: nothing outside holds it.

    Stored per state (codes come from the library's STATES): snapshot
    `qbo_<st>` = {sku: {price, name}} for every item of that state's QuickBooks
    company, snapshot `inv_<st>` = {sku: cases on hand} for every item of that
    state's inventory, snapshot `extra_<st>` = {sku: {name, ml, bpc}} = what
    the inventory system says about each of those items, and the company's
    customers / invoices / last prices. Snapshot `states` is the list of states
    itself, for the web pages, with each state's `catalog_all` flag.

    EVERY item is stored, with or without a catalog entry (since 2026-11-16):
    an admin can add an item to the catalog or delete one on the site, and the
    pages must be right at once, not at the next refresh. Which items a state
    SHOWS is decided when a page is built (db.state_products()): the catalog
    products its inventory holds, plus, for a `catalog_all` state, the items
    with no catalog entry.
    """
    mc = _library()
    import qbo_mmk_salesorder as qbo

    db.init()                                        # creates any missing table
    con = db.connect()
    catalog_skus = db.skus(con)
    save_states(con)
    results = {}

    def inventory(state, qb):
        """Read and store one state's inventory; never raises."""
        source = db.inv_source(state)
        try:
            data = read_inventory(state, None, qb=qb)
            extra = sum(1 for s in data if s not in catalog_skus)
            db.save_snapshot(con, source, payload={s: v["cases"] for s, v in data.items()})
            db.save_snapshot(con, db.extra_source(state), payload={
                s: {"name": v["name"], "ml": v["ml"], "bpc": v["bpc"]} for s, v in data.items()})
            results[source] = data
            log(f"{label} inventory ({info['inventory_name']}): {len(data) - extra} catalog "
                f"products, {extra} items with no catalog entry, "
                f"{sum(1 for v in data.values() if v['cases'])} in stock")
        except Exception as e:                       # noqa: BLE001 - keep going
            db.save_snapshot(con, source, error=f"{type(e).__name__}: {e}")
            log(f"{label} inventory ({info['inventory_name']}): FAILED - {type(e).__name__}: {e}")

    for state, info in mc.STATES.items():
        if info["inventory"] == PRICE_LIST:
            # Nothing to read: its price list is loaded by hand
            # (`manage.py load-price-list`) and its snapshots stay as loaded.
            log(f"{info['name']}: a price list held in Catalog.db, not read here")
            continue
        source, label = db.qbo_source(state), info["name"]
        inventory_read = False
        try:
            with qbo.qbo_client(info["qbo_config"]) as qb:
                data, customers, invoices, last_prices, history = read_company(state, qb, None)
                db.replace_company(con, state, customers, invoices, last_prices)
                kept = db.keep_invoices(con, state, history)
                db.save_snapshot(con, source, payload={
                    s: {"price": v["price"], "name": v["name"]} for s, v in data.items()})
                results[source] = data
                log(f"QuickBooks {label}: {len(data)} items, {len(customers)} customers, "
                    f"{len(invoices)} invoices, {len(last_prices)} previous prices read; "
                    f"{kept} invoices in the kept history")
                inventory_read = True
                inventory(state, qb)                 # same client when it is QuickBooks
        except Exception as e:                       # noqa: BLE001 - keep going
            db.save_snapshot(con, source, error=f"{type(e).__name__}: {e}")
            log(f"QuickBooks {label}: FAILED - {type(e).__name__}: {e}")
        if not inventory_read:
            # QuickBooks failed; inventory kept elsewhere (MMK) can still be read.
            inventory(state, None)
    con.close()
    return results


def load_pack(overwrite=False, log=print):
    """Fill products.bottles_per_case and bottle_ml (item data held in Catalog.db)
    from each state's QuickBooks company, then each state's inventory system: the
    first source that knows the value wins. Blank values only, unless overwrite=True;
    a figure typed by a person (pack_source 'admin' or 'owner') is never replaced."""
    results = refresh(log=log)
    sources = sorted(results, key=lambda k: not k.startswith("qbo_"))   # QuickBooks first
    con = db.connect()
    filled = 0
    with con:
        for row in con.execute("SELECT sku, bottles_per_case, bottle_ml, pack_source "
                               "FROM products").fetchall():
            if row["bottles_per_case"] and row["bottle_ml"] and not overwrite:
                continue
            if row["pack_source"] in ("admin", "owner"):
                continue
            for source in sources:
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
