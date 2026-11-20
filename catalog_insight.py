"""What to sell to a customer, worked out from the QuickBooks invoices that
Catalog.db already holds (the owner, 2026-11-19: "when the saleperson clicks on
"Customer" (and sees their own customers), there is a bunch of helpful data they
are presented with that helps them close a sale").

Nothing here is typed in by anyone and nothing is stored: every figure is worked
out from the last read of a state's invoices (qbo_invoices) each time a page is
built. This module reads no database and calls nothing outside; catalog_web.py
hands it the rows. It names no state: it is given one state's invoices and one
state's products.

Words used here and on the pages:
  cases     the quantity on an invoice line (the site's invoices are in cases;
            part of a case is a decimal).
  bought    an invoice line with a SKU, a quantity above zero and an amount
            above zero. A free sample (amount 0) is not a purchase.
  rhythm    the usual gap, in days, between the days something was bought: the
            median gap. It needs two different days.
  status    where a product (or the customer as a whole) stands against its
            rhythm today: see status().
"""
import json
from datetime import date, timedelta
from statistics import median

# Every threshold in ONE place, so they can be tuned without reading the code.
RULES = {
    "window_days": 365,       # "the last 12 months"
    "active_days": 90,        # "products bought lately" on the customer page
    "min_cycle_days": 7,      # a rhythm is never taken as shorter than a week
    "due_soon": 0.85,         # Due soon: at 85% of the usual gap or later
    "overdue": 1.25,          # Overdue: past 125% of the usual gap
    "lapsed_cycles": 3,       # Lapsed: past 3 usual gaps ...
    "lapsed_min_days": 90,    # ... and never sooner than 90 days
    "winback_min_cases": 3,   # a win-back sold at least this many cases in a year
    "new_days": 60,           # New: first sold in the state this many days ago or less
    "peer_band": 0.5,         # similar customers: 12-month cases within 50% either way
    "peer_min": 5,            # fewer similar customers than this: use every buying customer
    "gap_share": 0.25,        # a gap: carried by at least a quarter of the similar customers
    "gap_min_peers": 2,       # ... and by at least two of them
    "top": 5,                 # best sellers that count as "top"
    "asks": 3, "winbacks": 3, "gaps": 3, "new": 2,     # how many of each are shown
}

OVERDUE, DUE, LAPSED, OK = "overdue", "due", "lapsed", "ok"
STATUS_WORDS = {OVERDUE: "Overdue", DUE: "Due soon", LAPSED: "Lapsed", OK: "On track"}
# The order in which statuses need attention (the customers list sorts by it).
ATTENTION = {OVERDUE: 0, DUE: 1, LAPSED: 2, OK: 3, None: 4}


def rhythm(days):
    """The usual gap in days between the given days (dates): the median gap
    between different days, never under RULES['min_cycle_days']. None when
    there are fewer than two different days."""
    days = sorted(set(days))
    if len(days) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return max(median(gaps), RULES["min_cycle_days"])


def status(days_since, cycle):
    """Where something last bought `days_since` days ago stands against its
    usual gap `cycle` (None = no rhythm known): LAPSED past three gaps and at
    least 90 days; else OVERDUE past 1.25 gaps; else DUE from 0.85 of a gap;
    else OK. With no rhythm only LAPSED can be told; otherwise None."""
    if days_since > max(RULES["lapsed_cycles"] * (cycle or 0), RULES["lapsed_min_days"]):
        return LAPSED
    if not cycle:
        return None
    if days_since > RULES["overdue"] * cycle:
        return OVERDUE
    if days_since >= RULES["due_soon"] * cycle:
        return DUE
    return OK


def span(days):
    """A number of days in words: '10 days', '5 weeks'."""
    if days is None:
        return ""
    if days < 14:
        n = max(1, round(days))
        return f"{n} day" + ("" if n == 1 else "s")
    return f"{round(days / 7)} weeks"


def cases(value):
    """Cases as text, two decimals at most: 12, 3.5 (never 12.0)."""
    return f"{round(value, 2):g}"


def _usual(quantities):
    """The usual quantity per order: the median, to the nearest half case."""
    return max(0.5, round(median(quantities) * 2) / 2)


def _months(first, last, today):
    """The months a product was bought in, in words: 'Jun', 'Mar–Jun',
    'Nov 2025–Feb 2026' (the year is left out when it is this year)."""
    def m(d, year):
        return d.strftime("%b %Y") if year else d.strftime("%b")
    if (first.year, first.month) == (last.year, last.month):
        return m(last, last.year != today.year)
    if first.year == last.year:
        return m(first, False) + "–" + m(last, last.year != today.year)
    return m(first, True) + "–" + m(last, True)


def book(invoices):
    """One state's invoices, sorted out once for every page that asks:

      orders  {customer_id: [(day, total, balance, doc_number)]}, oldest first
      buys    {customer_id: {sku: {day: cases}}}: what was bought (see the top)
      first   {sku: the first day anyone in the state bought it}
      buyers  {sku: how many customers ever bought it}

    `invoices` is the rows of qbo_invoices for the state (customer_id,
    txn_date, total, balance, doc_number, lines as JSON text)."""
    orders, buys, first, buyers = {}, {}, {}, {}
    for v in invoices:
        cid, day = v["customer_id"], date.fromisoformat(v["txn_date"])
        orders.setdefault(cid, []).append((day, v["total"] or 0.0, v["balance"] or 0.0,
                                           v["doc_number"]))
        for ln in json.loads(v["lines"] or "[]"):
            sku = ln.get("sku")
            if not sku or not (ln.get("qty") or 0) > 0 or not (ln.get("amount") or 0) > 0:
                continue
            by_day = buys.setdefault(cid, {}).setdefault(sku, {})
            by_day[day] = by_day.get(day, 0) + ln["qty"]
            if sku not in first or day < first[sku]:
                first[sku] = day
    for mine in buys.values():
        for sku in mine:
            buyers[sku] = buyers.get(sku, 0) + 1
    for rows in orders.values():
        rows.sort(key=lambda r: r[0])
    return {"orders": orders, "buys": buys, "first": first, "buyers": buyers}


def customer_flags(order_days, today):
    """For the customers list: {customer_id: {last, days, cycle, status}} from
    {customer_id: [the days of its invoices]}. `days` is how long ago the last
    order was; `status` is the customer's own, against its usual gap between
    orders. A customer with no invoices is not in the result."""
    out = {}
    for cid, days in order_days.items():
        days = sorted(set(days))
        since = max(0, (today - days[-1]).days)
        cycle = rhythm(days)
        out[cid] = {"last": days[-1], "days": since, "cycle": cycle,
                    "status": status(since, cycle)}
    return out


def brief(bk, cid, products, today):
    """Everything the customer page shows about what to sell to one customer.

    `bk` is book() for the customer's state; `products` is {sku: {...}} for the
    products that state sells today, each with name, brand, grape, reg (regular
    price, None = cannot be ordered), prev (what this customer last paid),
    hand (cases on hand as text) and out (true when out of stock).

    Returns a dict:
      figures   last order, usual gap and status; sales this year to date and
                the same days last year; products bought lately; open invoices
      bought    every product bought in the last 12 months, best seller first
      winbacks  bought well, then stopped (LAPSED)
      gaps      carried by similar customers, not by this one
      peers     {n, similar}: how many customers `gaps` compares with, and
                whether they are of similar size or simply everyone
      new       first sold in the state lately, never bought by this customer
      asks      up to three things to ask for today, most pressing first
      due       [{sku, name, qty}]: the OVERDUE and DUE products that can be
                ordered now, at their usual quantity (New Order starts from it)
    A product that cannot be ordered or is out of stock is never suggested
    (winbacks, gaps, new, asks, due); `bought` shows it all the same.
    """
    R = RULES
    mine = bk["buys"].get(cid, {})
    orders = bk["orders"].get(cid, [])
    order_days = sorted({d for d, total, _b, _n in orders if total > 0})
    win = today - timedelta(days=R["window_days"])
    before = win - timedelta(days=R["window_days"])
    lately = today - timedelta(days=R["active_days"])
    my_cycle = rhythm(order_days)

    def sellable(sku):
        p = products.get(sku)
        return p is not None and p["reg"] is not None and not p.get("out")

    # --- every product this customer bought, with its own rhythm --------------
    known = []
    for sku, by_day in mine.items():
        p = products.get(sku)
        if p is None:                       # QuickBooks holds old items the state no longer sells
            continue
        days = sorted(by_day)
        since = max(0, (today - days[-1]).days)
        own = rhythm(days)
        cycle = own or my_cycle
        known.append({
            "sku": sku, "name": p["name"], "p": p,
            "cases": sum(q for d, q in by_day.items() if d > win),
            "cases_before": sum(q for d, q in by_day.items() if before < d <= win),
            "cases_all": sum(by_day.values()),
            "first": days[0], "last": days[-1], "since": since, "times": len(days),
            "qty": _usual(list(by_day.values())), "cycle": cycle, "own_cycle": own is not None,
            "status": status(since, cycle), "sellable": sellable(sku)})
    bought = sorted((m for m in known if m["cases"] > 0),
                    key=lambda m: (-m["cases"], m["name"].casefold()))
    for i, m in enumerate(bought, 1):
        m["rank"] = i
    top = bought[:R["top"]]

    winbacks = sorted(
        (m for m in known if m["status"] == LAPSED and m["sellable"]
         and max(m["cases"], m["cases_before"]) >= R["winback_min_cases"]),
        key=lambda m: (-m["cases_all"], m["name"].casefold()))[:R["winbacks"]]
    for m in winbacks:
        m["months"] = _months(m["first"], m["last"], today)

    # --- similar customers, and what they carry that this one does not -------
    year = {}                               # {customer: {sku: cases in the last 12 months}}
    for other, skus in bk["buys"].items():
        got = {s: c for s, c in ((s, sum(q for d, q in by_day.items() if d > win))
                                 for s, by_day in skus.items()) if c > 0}
        if got:
            year[other] = got
    volume = {c: sum(v.values()) for c, v in year.items()}
    my_volume = volume.get(cid, 0)
    others = [c for c in year if c != cid]
    band = [c for c in others
            if my_volume and (1 - R["peer_band"]) * my_volume <= volume[c] <= (1 + R["peer_band"]) * my_volume]
    similar = len(band) >= R["peer_min"]
    peers = band if similar else others
    gaps = []
    if peers:
        carried = {}
        for c in peers:
            for sku, n in year[c].items():
                carried.setdefault(sku, []).append(n)
        mine_now = {m["sku"] for m in bought} | {m["sku"] for m in winbacks}
        for sku, each in carried.items():
            if (sku in mine_now or not sellable(sku) or len(each) < R["gap_min_peers"]
                    or len(each) / len(peers) < R["gap_share"]):
                continue
            gaps.append({"sku": sku, "name": products[sku]["name"], "p": products[sku],
                         "n": len(each), "of": len(peers), "each": sum(each) / len(each)})
        gaps.sort(key=lambda x: (-x["n"], -x["each"], x["name"].casefold()))
        gaps = gaps[:R["gaps"]]

    def active(skus):                       # different products bought lately
        return sum(1 for by_day in skus.values() if any(d > lately for d in by_day))
    peer_active = (sum(active(bk["buys"][c]) for c in peers) / len(peers)) if peers else None

    # --- new in the state, never bought here ---------------------------------
    since_new = today - timedelta(days=R["new_days"])
    top_grape = {}                          # grape -> the rank of the best seller made of it
    for m in top:
        grape = (m["p"].get("grape") or "").strip()
        if grape:
            top_grape.setdefault(grape.casefold(), (m["rank"], grape))
    my_brands = {}
    for m in bought:
        brand = (m["p"].get("brand") or "").strip()
        if brand:
            my_brands[brand.casefold()] = my_brands.get(brand.casefold(), 0) + 1
    new = []
    for sku, first in bk["first"].items():
        if first < since_new or sku in mine or not sellable(sku):
            continue
        p = products[sku]
        grape, brand = (p.get("grape") or "").strip(), (p.get("brand") or "").strip()
        buyers = bk["buyers"].get(sku, 0)
        fit = 0
        if grape.casefold() in top_grape:
            rank, word = top_grape[grape.casefold()]
            fit, why = 2, f"{word} is their #{rank} seller."
        elif brand.casefold() in my_brands:
            n = my_brands[brand.casefold()]
            fit, why = 1, f"They already buy {n} {brand} product{'' if n == 1 else 's'}."
        elif buyers > 1:
            why = f"{buyers} customers have bought it since it arrived."
        else:
            why = "New here."
        new.append({"sku": sku, "name": p["name"], "p": p, "first": first, "fit": fit,
                    "buyers": buyers, "why": why})
    new.sort(key=lambda x: (-x["fit"], -x["buyers"], x["name"].casefold()))
    new = new[:R["new"]]

    # --- what to ask for today ------------------------------------------------
    def reorder(m):
        text = f"Their #{m['rank']} seller."
        if m["cycle"]:
            text += (f" Usually every {span(m['cycle'])}; it has been {span(m['since'])}.")
        return {"kind": "reorder", "sku": m["sku"], "qty": m["qty"],
                "lead": f"Reorder {m['name']}: {cases(m['qty'])} cs.", "text": text}
    ready = [m for m in bought if m["sellable"]]
    kinds = [
        [reorder(m) for m in ready if m["rank"] <= R["top"] and m["status"] == OVERDUE],
        [{"kind": "new", "sku": x["sku"], "qty": 1, "lead": f"Introduce the new {x['name']}: 1 cs.",
          "text": x["why"]} for x in new[:1]],
        [{"kind": "winback", "sku": m["sku"], "qty": m["qty"],
          "lead": f"Win back {m['name']}: {cases(m['qty'])} cs.",
          "text": f"Bought {cases(m['cases_all'])} cs {m['months']}, nothing in {span(m['since'])}."}
         for m in winbacks[:1]],
        [{"kind": "gap", "sku": x["sku"], "qty": 1, "lead": f"Add {x['name']}: 1 cs.",
          "text": f"Carried by {x['n']} of {x['of']} "
                  f"{'similar customers' if similar else 'customers'}."} for x in gaps[:1]],
        [reorder(m) for m in ready if m["status"] in (OVERDUE, DUE)],
    ]
    asks, used = [], set()
    for one_each in (True, False):          # one of each kind first, then whatever is left
        for kind in kinds:
            for a in kind:
                if len(asks) < R["asks"] and a["sku"] not in used:
                    asks.append(a)
                    used.add(a["sku"])
                    if one_each:
                        break
    due = [{"sku": m["sku"], "name": m["name"], "qty": m["qty"]}
           for m in ready if m["status"] in (OVERDUE, DUE)]

    # --- the four figures -----------------------------------------------------
    try:
        last_year = today.replace(year=today.year - 1)
    except ValueError:                      # Feb 29
        last_year = today.replace(year=today.year - 1, day=28)
    ytd = sum(t for d, t, _b, _n in orders if d.year == today.year and d <= today)
    ytd_before = sum(t for d, t, _b, _n in orders if d.year == today.year - 1 and d <= last_year)
    unpaid = [(d, b) for d, _t, b, _n in orders if b > 0.004]
    since = max(0, (today - order_days[-1]).days) if order_days else None
    figures = {
        "last": order_days[-1] if order_days else None, "since": since, "cycle": my_cycle,
        "status": status(since, my_cycle) if since is not None else None,
        "ytd": ytd, "ytd_before": ytd_before,
        "ytd_change": round((ytd - ytd_before) / ytd_before * 100) if ytd_before > 0 else None,
        "active": active(mine), "peer_active": peer_active,
        "open": len(unpaid),
        "open_oldest": max(0, (today - min(d for d, _b in unpaid)).days) if unpaid else None,
    }
    return {"figures": figures, "bought": bought, "winbacks": winbacks, "gaps": gaps,
            "peers": {"n": len(peers), "similar": similar}, "new": new, "asks": asks, "due": due}
