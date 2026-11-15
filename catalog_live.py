"""Reads of QuickBooks and MMK for the catalog site. READ-ONLY.

Every call here goes through the existing library in ~/python/qbo_scripts (the
code behind orders.satlaspirits.com). Nothing is reimplemented:

  Regular price, Florida on hand   mmk_common.get_current_inventory_qbo(config_path)
                                   (column unit_price; qty_on_hand)
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
from pathlib import Path

import catalog_db as db

LIBRARY = Path.home() / "python" / "qbo_scripts"
FL_CONFIG = Path.home() / "python" / "config" / "qbo_config_fl.json"

# source key -> (plain name, QuickBooks config path or None for the default IL one)
QBO_SOURCES = {"qbo_il": ("QuickBooks Illinois", None),
               "qbo_fl": ("QuickBooks Florida", FL_CONFIG)}
MMK_SOURCE = "mmk_il"


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


def read_qbo_items(config_path, catalog_skus):
    """{sku: {price, qty, bpc, ml}} for the catalog's SKUs in one QuickBooks company.

    `price` is the regular price per case (None when QuickBooks has none set);
    `qty` is quantity on hand in cases (None for a non-inventory item). Where
    QuickBooks holds two items with the same SKU, the active Inventory one wins.
    """
    mc = _library()
    df = mc.get_current_inventory_qbo(config_path=config_path)
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


def refresh(log=print):
    """Read all three sources and store them in live_snapshot. One source failing
    does not stop the others; a failure keeps that source's last good figures."""
    con = db.connect()
    catalog_skus = db.skus(con)
    results = {}
    for source, (label, path) in QBO_SOURCES.items():
        try:
            data = read_qbo_items(path, catalog_skus)
            db.save_snapshot(con, source, payload={
                s: {"price": v["price"], "qty": v["qty"]} for s, v in data.items()})
            results[source] = data
            log(f"{label}: {len(data)} catalog items read")
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
