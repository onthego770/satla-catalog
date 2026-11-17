"""catalog.satlaspirits.com: the salesman catalog site (Stage 1: sign in, catalog,
product page; Stage 2: customers, customer page with order history, invoice;
Stage 3: New Order and Copy Order, sent as an email; Admin pages for logins and
for editing, adding and deleting catalog items).

Illinois and Florida are kept completely apart (owner, 2026-11-15): each has its
own products, stock, prices, customers and orders. A login is given the states
it may use; the switch in the header picks the one every page shows (`g.state`).
The states themselves come from the library's STATES table by way of the
refresh, so nothing in this file names a state.

Run by gunicorn as the systemd service `catalog-web` (127.0.0.1:5001) behind
Caddy, the same arrangement as orders.satlaspirits.com.

This worker reads ONLY Catalog.db (and, for an admin, writes item data to it:
catalog_items.py). It never calls QuickBooks or MMK: prices and
on hand come from the snapshot that `manage.py refresh` stores on a timer (see
catalog_live.py), so a page view cannot disturb the QuickBooks token or the MMK
login. Nothing on the site is visible without signing in.

An order is never stored: it lives in the salesman's browser until Send, and
Send turns it into one email through the library's mail_send.send_mail().

Local test over plain http: CATALOG_WEB_INSECURE=1 (relaxes the HTTPS-only cookie).
"""
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import catalog_db as db
import catalog_items as items
import catalog_source as source

CONFIG_PATH = db.ROOT.parent / "config" / "catalog_config.json"
PHOTO_DIR = db.ROOT / "photos"
OFFICE_TZ = ZoneInfo("America/Chicago")
LIBRARY = db.ROOT.parent / "qbo_scripts"          # the existing API library
MIN_PASSWORD = 8

app = Flask(__name__)
# Behind Caddy: trust one proxy hop so the visitor's address (login throttle) and
# the https scheme (secure cookie) are the real ones.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = json.loads(CONFIG_PATH.read_text())["secret_key"]
app.config.update(
    SESSION_COOKIE_NAME="satla_catalog",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("CATALOG_WEB_INSECURE") != "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,        # the largest post is an item's two photos
)

# Brute-force throttle for /login: recent failures per visitor address.
# In-process, which is enough for a single worker.
_LOGIN_FAILS = {}
_MAX_FAILS = 8
_FAIL_WINDOW = 300


def _throttled(ip):
    now = time.time()
    recent = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _FAIL_WINDOW]
    _LOGIN_FAILS[ip] = recent
    return len(recent) >= _MAX_FAILS


@app.before_request
def _open_db():
    g.db = db.connect()
    g.user = None
    g.states, g.allowed, g.state = {}, [], None
    uid = session.get("uid")
    if uid:
        user = db.user_by_id(g.db, uid)
        if user and user["active"]:
            g.user = user
            # g.states: every state the site knows. g.allowed: the ones this
            # login may use. g.state: the one the switch is on.
            g.states = db.states(g.db)
            mine = db.user_states(user)
            g.allowed = [code for code in g.states if code in mine]
            if session.get("state") in g.allowed:
                g.state = session["state"]
            elif g.allowed:
                g.state = g.allowed[0]
        else:
            session.clear()


@app.teardown_request
def _close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


@app.before_request
def _check_form_token():
    """Every form a signed-in person posts must carry the token this site put
    in the page, so another website cannot post on their behalf."""
    if request.method == "POST" and g.user is not None:
        sent = request.form.get("csrf") or ""
        if not secrets.compare_digest(sent, session.get("csrf") or "-"):
            abort(400)


def _form_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        if not g.user["is_admin"]:
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/photo/"):
                abort(401)
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        if g.state is None:
            return render_template("message.html", title="No state yet", message=(
                "This login has not been given a state yet. "
                "Ask an admin to tick one for you on the Admin page.")), 403
        return view(*args, **kwargs)
    return wrapped


def _use_state(code):
    """A page that belongs to one state (a customer, an invoice, an order): refuse
    it to a login without that state, and move the switch to it."""
    if code not in g.allowed:
        abort(404)
    if code != g.state:
        session["state"] = g.state = code


def _state_name(code):
    return g.states[code]["name"]


def _order_to(code):
    """Where an order for a customer of this state is emailed: the state's
    `order_email` in the library's STATES (the owner, 2026-11-17: each state's
    orders go to their own address). '' when the state has none."""
    return g.states[code].get("order_email") or ""


@app.context_processor
def _asset_version():
    def asset(name):
        path = db.ROOT / "static" / name
        return url_for("static", filename=name, v=int(path.stat().st_mtime))
    return {"asset": asset, "form_token": _form_token}


@app.after_request
def _no_store(resp):
    # Pages hold prices and stock: never let a shared cache keep them.
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# --- sign in ------------------------------------------------------------------

def _safe_next(target):
    """Only ever redirect to a path on this site."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("catalog")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("catalog"))
    error = None
    email = ""
    if request.method == "POST":
        ip = request.remote_addr or "?"
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if _throttled(ip):
            return render_template("login.html", email=email, error=(
                "Too many failed attempts. Wait five minutes and try again.")), 429
        user = db.user_by_email(g.db, email)
        if user and user["active"] and check_password_hash(user["password_hash"], password):
            _LOGIN_FAILS.pop(ip, None)
            session.clear()
            session.permanent = True
            session["uid"] = user["id"]
            return redirect(_safe_next(request.args.get("next")))
        _LOGIN_FAILS.setdefault(ip, []).append(time.time())
        error = "That email and password do not match a login."
    return render_template("login.html", email=email, error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/state", methods=["POST"])
@login_required
def set_state():
    """The header switch: show another state's catalog and customers."""
    code = request.form.get("state")
    if code not in g.allowed:
        abort(400)
    session["state"] = code
    return redirect(url_for("customers" if request.form.get("section") == "customers"
                            else "catalog"))


# --- catalog ------------------------------------------------------------------
# A state's catalog is db.state_products(): the catalog products that have a
# record in that state's inventory (Illinois, a record in MMK; Florida, an active
# item in QuickBooks Florida), in stock or not. Florida also lists the QuickBooks
# Florida items that have no catalog entry yet, marked "Not in catalog" (the
# owner, 2026-11-15: "This gives us an idea of what is missing").

@app.route("/")
def home():
    return redirect(url_for("catalog"))


def _kfp(r):
    """Kosher for Passover, the owner's rule (2026-11-15): every wine is, all
    year round; anything else only when the product data says "Yes"."""
    return "Yes" if r["category"] == "Wine" else r["kfp"]


@app.route("/catalog")
@login_required
def catalog():
    # Short keys keep the page small; the grid needs no descriptions.
    # `x` marks an item with no catalog entry.
    products = [{
        "sku": r["sku"], "name": r["name"], "size": r["size"], "brand": r["brand"],
        "cat": r["category"], "type": r["type"], "sweet": r["sweetness"],
        "grape": r["grape"], "country": r["country"], "region": r["region"],
        "mev": r["mevushal"], "kfp": _kfp(r), "org": r["organic"], "vint": r["vintage"],
        **({"x": 1} if r["uncataloged"] else {}),
        **({"pv": r["photo_v"]} if r["photo_v"] else {}),
    } for r in db.state_products(g.db, g.state)]
    return render_template("catalog.html", products=products)


def _when(stamp):
    """A stored UTC stamp as {'iso', 'text'}; text is office (Central) time, and
    the page rewrites it into the viewer's own time zone."""
    if not stamp:
        return None
    dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    local = dt.astimezone(OFFICE_TZ)
    return {"iso": stamp, "text": local.strftime("%b %-d, %-I:%M %p") + " Central"}


def _cases(value):
    """Cases as text, to two decimals at most: 12, 3.5, 54.17 (never 12.0)."""
    return f"{round(value, 2):g}"


def _state_figures(sku, state):
    """Regular price per case and cases on hand in one state, from the last
    snapshot: the price from that state's QuickBooks company, on hand from its
    inventory system."""
    qbo, inv = db.snapshot(g.db, db.qbo_source(state)), db.snapshot(g.db, db.inv_source(state))
    name = _state_name(state)

    if qbo["data"] is None:
        price = {"text": "Unavailable", "muted": True}
    elif (qbo["data"].get(sku) or {}).get("price") is None:
        price = {"text": f"No price in QuickBooks {name}", "muted": True}
    else:
        price = {"text": f"${qbo['data'][sku]['price']:,.2f}", "muted": False}
    if inv["data"] is None:
        hand = {"text": "Unavailable", "muted": True}
    elif inv["data"].get(sku) is None:
        hand = {"text": "—", "muted": True}
    else:
        hand = {"text": _cases(inv["data"][sku]), "muted": False}

    sources = []
    for label, snap in ((f"Regular price: QuickBooks {name}", qbo),
                        (f"On hand: {g.states[state]['inventory']}", inv)):
        sources.append({"label": label, "as_of": _when(snap["fetched_at"]),
                        "stale": not snap["ok"], "tried": _when(snap["attempted_at"])})
    return {"state": name, "price": price, "hand": hand, "sources": sources}


@app.route("/product/<path:sku>")
@login_required
def product(sku):
    p = db.state_product(g.db, g.state, sku)
    if p is None:
        other = db.product(g.db, sku)
        if other is None:
            abort(404)
        if db.snapshot(g.db, db.inv_source(g.state))["data"] is not None:
            return render_template("message.html", title="Not in this state", message=(
                f"{other['name']} is not in the {_state_name(g.state)} catalog.")), 404
        p = dict(other, uncataloged=False)      # inventory never read yet: show it
    bpc = p["bottles_per_case"]
    facts = [
        ("Brand", p["brand"]), ("Category", p["category"]), ("Type", p["type"]),
        ("Style", p["style"]), ("Sweetness", p["sweetness"]), ("Grape / base", p["grape"]),
        ("Country", p["country"]), ("Region", p["region"]),
        ("Sub-region / appellation", p["subregion"]), ("ABV", p["abv"]),
        ("Vintage", p["vintage"]), ("Bottle size", p["size"]),
        ("Bottles per case", _cases(bpc) if bpc else ""),
        ("Mevushal", p["mevushal"]), ("Organic", p["organic"]),
        ("Kosher certifier", p["certifier"]), ("SKU", p["sku"]),
    ]
    return render_template("product.html", p=p, facts=facts, live=_state_figures(sku, g.state),
                           inventory_name=g.states[g.state]["inventory"],
                           can_add=bool(p["uncataloged"]) and items.inventory_item(g.db, sku) is not None)


# --- customers and order history (Stage 2) ------------------------------------
# Everything here is the last copy read from each state's QuickBooks company by
# the refresh timer. A customer belongs to the state whose QuickBooks company
# holds it. Customers and orders come from QuickBooks only, so KOVAL customers
# and orders, which live only in MMK, never appear.


@app.template_filter("money")
def money(value):
    """$1,234.50; a negative amount as -$20.00."""
    value = value or 0
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


def _day(iso_date):
    """'2026-11-03' as 'Nov 3, 2026'."""
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%b %-d, %Y")


def _qbo_sources(companies):
    out = []
    for code in companies:
        snap = db.snapshot(g.db, db.qbo_source(code))
        out.append({"label": _state_name(code), "as_of": _when(snap["fetched_at"]),
                    "stale": not snap["ok"]})
    return out


def _whose():
    """Whose customers the signed-in person sees: None = everyone's (an admin),
    otherwise their own name, matched to the customer's SALESMAN field in
    QuickBooks. The owner, 2026-11-15: "Each salesman should see only their own
    customers, However Yoel and Dovid are Admins, so we can see everything." """
    return None if g.user["is_admin"] else g.user["name"]


def _customer(company, cid):
    """The customer, or a 404 when it does not exist or is not this person's.
    Every page about one customer (its page, invoices, orders) goes through here."""
    c = db.customer(g.db, company, cid, _whose())
    if c is None:
        abort(404)
    return c


@app.route("/customers")
@login_required
def customers():
    rows = [{"co": r["company"], "id": r["id"], "name": r["name"], "city": r["city"],
             "st": r["state"]} for r in db.customers(g.db, g.state, _whose())]
    return render_template("customers.html", customers=rows, mine=_whose() is not None,
                           sources=_qbo_sources((g.state,)))


@app.route("/customer/<company>/<cid>")
@login_required
def customer(company, cid):
    _use_state(company)
    c = _customer(company, cid)
    invoices = [{"id": v["id"], "doc_number": v["doc_number"], "date": _day(v["txn_date"]),
                 "items": len(json.loads(v["lines"])), "total": v["total"],
                 "open": (v["balance"] or 0) > 0.004}
                for v in db.customer_invoices(g.db, company, cid)]
    place = " ".join(x for x in (", ".join(x for x in (c["city"], c["state"]) if x), c["zip"]) if x)
    address = ", ".join(x for x in (c["street"], place) if x)
    return render_template("customer.html", c=c, address=address, invoices=invoices,
                           company_name=_state_name(company),
                           sources=_qbo_sources((company,)))


@app.route("/invoice/<company>/<iid>")
@login_required
def invoice(company, iid):
    _use_state(company)
    v = db.invoice(g.db, company, iid)
    if v is None:
        abort(404)
    c = _customer(company, v["customer_id"])
    lines, product_sum = [], 0.0
    products = {p["sku"]: p for p in db.state_products(g.db, company)}
    for ln in json.loads(v["lines"]):
        p = products.get(ln["sku"])
        product_sum += ln["amount"] or 0
        # A product of this state shows its SKU and size and links to its page;
        # anything else (QuickBooks holds old items) shows its QuickBooks name only.
        detail = " · ".join(x for x in (ln["sku"], p["size"] if p else "") if x)
        lines.append({"name": ln["name"], "sku": ln["sku"], "in_catalog": p is not None,
                      "detail": detail,
                      "qty": _cases(ln["qty"]) if ln["qty"] is not None else "",
                      "price": money(ln["price"]) if ln["price"] is not None else "",
                      "amount": money(ln["amount"]) if ln["amount"] is not None else ""})
    adjustment = round((v["total"] or 0) - product_sum, 2)
    return render_template("invoice.html", v=v, lines=lines, date=_day(v["txn_date"]),
                           is_open=(v["balance"] or 0) > 0.004,
                           adjustment=adjustment if abs(adjustment) >= 0.01 else None,
                           customer_name=c["name"],
                           company_name=_state_name(company),
                           sources=_qbo_sources((company,)))


# --- New Order and Copy Order (Stage 3) ----------------------------------------
# The order is built in the salesman's browser (static/order.js) and is never
# stored here. Send posts it once; this side checks every line again against
# Catalog.db, writes the email and hands it to the library's mail_send.

def _order_products(company, cid):
    """Every product of the customer's state as the order screen needs it:
    `reg` is the regular price per case in that state's QuickBooks company
    (None = cannot be ordered), `prev` is what this customer last paid, `hand`
    is cases on hand in that state's inventory. A product the state does not
    have is not listed, so it cannot be ordered there."""
    prices = db.snapshot(g.db, db.qbo_source(company))["data"] or {}
    have = db.snapshot(g.db, db.inv_source(company))["data"] or {}
    last = db.last_prices(g.db, company, cid)
    out = []
    for r in db.state_products(g.db, company):
        sku = r["sku"]
        hand, prev = have[sku], last.get(sku)
        out.append({"sku": sku, "name": r["name"], "size": r["size"], "brand": r["brand"],
                    "pv": r["photo_v"], "cat": r["category"], "grape": r["grape"], "country": r["country"],
                    "region": r["region"], "reg": (prices.get(sku) or {}).get("price"),
                    "hand": _cases(hand) if hand is not None else None,
                    "prev": {"p": prev["price"], "d": _day(prev["date"])} if prev else None})
    return out


def _order_sources(company):
    out = []
    for label, source in (("Regular prices: QuickBooks " + _state_name(company), db.qbo_source(company)),
                          ("On hand: " + g.states[company]["inventory"], db.inv_source(company))):
        snap = db.snapshot(g.db, source)
        out.append({"label": label, "as_of": _when(snap["fetched_at"]), "stale": not snap["ok"]})
    return out


@app.route("/order/<company>/<cid>")
@login_required
def order(company, cid):
    _use_state(company)
    c = _customer(company, cid)
    copy = None
    iid = request.args.get("copy")
    if iid:
        v = db.invoice(g.db, company, iid)
        if v is None or v["customer_id"] != cid:
            abort(404)
        copy = {"doc": v["doc_number"],
                "lines": [{"sku": ln["sku"], "name": ln["name"], "qty": ln["qty"]}
                          for ln in json.loads(v["lines"])]}
    info = {"co": company, "id": cid, "name": c["name"], "state": _state_name(company),
            "to": _order_to(company), "me": g.user["email"], "copy": copy,
            "back": url_for("customer", company=company, cid=cid),
            "send": url_for("order_send", company=company, cid=cid),
            "nonce": secrets.token_urlsafe(12)}
    return render_template("order.html", c=c, info=info, sources=_order_sources(company),
                           products=_order_products(company, cid))


def _checked_order(company, cid, payload):
    """The posted order, checked line by line against Catalog.db. Returns
    (lines, note) or raises ValueError with a message for the salesman."""
    products = {p["sku"]: p for p in _order_products(company, cid)}
    raw = payload.get("lines")
    if not isinstance(raw, list) or not raw:
        raise ValueError("The order has no lines.")
    lines, seen = [], set()
    for ln in raw[:300]:
        p = products.get(str(ln.get("sku")))
        if p is None or p["sku"] in seen:
            raise ValueError("The order holds a product that is not in the "
                             f"{_state_name(company)} catalog.")
        seen.add(p["sku"])
        if p["reg"] is None:
            raise ValueError(f"{p['name']} has no regular price in QuickBooks "
                             f"{_state_name(company)}, so it cannot be ordered.")
        try:
            cases, price = round(float(ln.get("cases")), 2), round(float(ln.get("price")), 2)
        except (TypeError, ValueError):
            raise ValueError(f"{p['name']}: the cases or the price is not a number.")
        if not 0 < cases <= 9999 or not 0 <= price <= 99999:
            raise ValueError(f"{p['name']}: check the cases and the price.")
        if p["prev"] and abs(price - p["prev"]["p"]) < 0.005:
            src = "previous price"
        elif abs(price - p["reg"]) < 0.005:
            src = "regular price"
        else:
            src = "typed price"
        lines.append({"p": p, "cases": cases, "price": price, "src": src,
                      "total": round(cases * price, 2)})
    return lines, str(payload.get("note") or "").strip()[:2000]


def _order_email(c, company, lines, note):
    """(subject, body) of the order email, in the layout approved in the
    wireframes (screen 9)."""
    today = datetime.now(OFFICE_TZ).strftime("%b %-d, %Y")
    subject = f"New order — {c['name']} — {today}"
    rows = [f"{ln['p']['sku']}  {ln['p']['name']}"
            + (f" ({ln['p']['size']})" if ln['p']['size'] else "") + "\n"
            f"   {_cases(ln['cases'])} {'case' if ln['cases'] == 1 else 'cases'} @ "
            f"{money(ln['price'])} per case ({ln['src']}) = {money(ln['total'])}" for ln in lines]
    body = (f"Customer: {c['name']} ({_state_name(company)})\n"
            f"Salesman: {g.user['name']} <{g.user['email']}>\n\n" + "\n".join(rows) +
            f"\n\nOrder total: {money(sum(ln['total'] for ln in lines))}\n"
            f"Note: {note or 'none'}\n")
    return subject, body


def _send_order_email(to, subject, body):
    """Send to `to` through the library (mail_send.send_mail). Returns None when
    sent, or the reason it was not. Sending stays off until the owner switches
    it on (`manage.py order-email on`): the message goes out from the business
    mailbox."""
    try:
        enabled = json.loads(CONFIG_PATH.read_text()).get("order_email") is True
    except (OSError, ValueError):
        enabled = False
    if not enabled:
        return "Sending order emails is not switched on yet."
    if not to:
        return "No address is set for this state's orders."
    if str(LIBRARY) not in sys.path:
        sys.path.insert(0, str(LIBRARY))
    import mail_send                               # stdlib only; no QuickBooks, no MMK
    from pipeline_errors import PipelineError
    try:
        mail_send.send_mail(to, subject, body, cc=g.user["email"],
                            reply_to=g.user["email"], from_name="Satla Catalog orders")
    except PipelineError as e:
        return str(e)
    return None


@app.route("/order/<company>/<cid>/send", methods=["POST"])
@login_required
def order_send(company, cid):
    _use_state(company)
    c = _customer(company, cid)
    back = url_for("order", company=company, cid=cid)
    ctx = {"c": c, "back": back, "to": _order_to(company), "cc": g.user["email"],
           "customer_url": url_for("customer", company=company, cid=cid),
           "draft_key": f"satla.order.v1.{company}.{cid}"}
    try:
        payload = json.loads(request.form.get("order") or "")
        lines, note = _checked_order(company, cid, payload)
    except (ValueError, AttributeError) as e:
        return render_template("sent.html", sent=False, problem=str(e), **ctx), 400
    nonce = str(payload.get("nonce") or "")
    if nonce and nonce in session.get("sent", []):
        return render_template("sent.html", sent=False, repeat=True, **ctx)
    subject, body = _order_email(c, company, lines, note)
    problem = _send_order_email(_order_to(company), subject, body)
    if problem is None and nonce:
        session["sent"] = (session.get("sent", []) + [nonce])[-5:]
    return render_template("sent.html", sent=problem is None, problem=problem,
                           subject=subject, body=body, **ctx)


# --- Admin: logins (owner, 2026-11-15) -----------------------------------------

@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    note = error = None
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        states = [code for code in g.states if code in f.getlist("states")]
        if action == "add":
            name, email, pw = (f.get("name") or "").strip(), (f.get("email") or "").strip().lower(), f.get("password") or ""
            if not name or "@" not in email:
                error = "Enter a name and an email address."
            elif len(pw) < MIN_PASSWORD:
                error = f"The password needs at least {MIN_PASSWORD} characters."
            elif db.user_by_email(g.db, email):
                error = f"{email} already has a login."
            elif not states:
                error = "Tick at least one state for the login."
            else:
                db.add_user(g.db, name, email, generate_password_hash(pw),
                            f.get("is_admin") == "1", states)
                note = f"Login created for {name} ({', '.join(states)})."
        else:
            user = db.user_by_id(g.db, f.get("uid"))
            if user is None:
                abort(404)
            me = user["id"] == g.user["id"]
            if action == "password":
                pw = f.get("password") or ""
                if len(pw) < MIN_PASSWORD:
                    error = f"The password needs at least {MIN_PASSWORD} characters."
                else:
                    db.update_user(g.db, user["id"], password_hash=generate_password_hash(pw))
                    note = f"Password changed for {user['name']}."
            elif action == "states":
                if not states:
                    error = ("A login needs at least one state. "
                             "To stop someone signing in, switch the login off.")
                else:
                    db.update_user(g.db, user["id"], states=",".join(states))
                    note = f"{user['name']} can now use: {', '.join(states)}."
            elif action in ("active", "admin"):
                field = "active" if action == "active" else "is_admin"
                turn_on = f.get("value") == "1"
                if me and not turn_on:
                    error = "You cannot switch off your own login or your own admin rights."
                else:
                    db.update_user(g.db, user["id"], **{field: int(turn_on)})
                    what = "Login" if action == "active" else "Admin rights"
                    note = f"{what} switched {'on' if turn_on else 'off'} for {user['name']}."
            else:
                abort(400)
    counts = db.salesman_counts(g.db)
    users = [{**dict(u), "states": db.user_states(u),
              "sees": {code: counts.get((code, db.salesman_key(u["name"])), 0)
                       for code in db.user_states(u)}}
             for u in db.users(g.db)]
    return render_template("admin.html", users=users, note=note, error=error,
                           min_password=MIN_PASSWORD), (400 if error else 200)


# --- Admin: catalog items (owner, 2026-11-16) -----------------------------------
# "Can we discuss how we can create a "modify item" functionality for admins?"
# His answers: change the product name, "YES"; add an item, "YES, please
# include"; delete an item, "YES, FOR SURE"; who edits, "ONLY DOVID & YOEL".
# All of the work is in catalog_items.py; every change is recorded and can be
# undone from the History page. Nothing here touches QuickBooks or MMK.

def _note(text=None):
    """A one-time message for the next admin page: set it, or take it."""
    if text is None:
        return session.pop("note", None)
    session["note"] = text


def _posted_photos():
    """The photo pair the edit page made, as {kind: bytes}; {} when the admin
    ticked "remove the photo"; items.KEEP when the photo was left alone."""
    if request.form.get("photo_remove") == "1":
        return {}
    photos = {kind: f.read(items.MAX_PHOTO_BYTES + 1)
              for kind in items.PHOTO_SIZES
              if (f := request.files.get("photo_" + kind)) and f.filename}
    return photos or items.KEEP


@app.route("/admin/item/<path:sku>", methods=["GET", "POST"])
@admin_required
def admin_item(sku):
    """Edit a catalog item, or add one: the same form. A SKU with no catalog
    entry can be added only when a state's inventory system holds it."""
    row = db.product(g.db, sku)
    adding = row is None
    p = items.blank_item(g.db, sku) if adding else dict(row)
    if p is None:
        abort(404)
    problems = []
    if request.method == "POST":
        if request.form.get("action") == "delete":
            if adding:
                abort(400)
            if request.form.get("sure") != "1":
                problems.append("Tick the box to confirm, then press Delete.")
            else:
                items.save(g.db, sku, None, g.user, "delete")
                _note(f"{p['name']} ({sku}) was deleted from the catalog. "
                      "Undo is on this page if that was a mistake.")
                return redirect(url_for("admin_history"))
        else:
            values, problems = items.clean(request.form)
            photos = _posted_photos()
            if photos is not items.KEEP and photos:
                problem = items.check_photos(photos)
                if problem:
                    problems.append(problem)
            if problems:
                p = dict(p, **values)              # show what was typed
            else:
                items.save(g.db, sku, items.merged(p, values), g.user,
                           "add" if adding else "edit", photos=photos)
                if g.state and db.state_product(g.db, g.state, sku):
                    return redirect(url_for("product", sku=sku))
                _note(f"{values['name']} ({sku}) was saved. It is not in the "
                      f"{_state_name(g.state) if g.state else 'current'} catalog, "
                      "so its page is not shown here.")
                return redirect(url_for("admin_history"))
    has_photo = not adding and (PHOTO_DIR / "detail" / f"{sku}.webp").exists()
    return render_template("item.html", p=p, adding=adding, problems=problems,
                           fields=items.FIELDS, suggest=items.suggestions(g.db),
                           names=items.system_names(g.db, sku), has_photo=has_photo,
                           sizes=items.PHOTO_SIZES), (400 if problems else 200)


def _store_password():
    """The Kosher Wine World storefront password, from the site's private config."""
    try:
        return json.loads(CONFIG_PATH.read_text()).get("kww_password") or ""
    except (OSError, ValueError):
        return ""


@app.route("/admin/source", methods=["POST"])
@admin_required
def admin_source():
    """The edit form's "Fill from Kosher Wine World" box: what that store holds
    for the product page whose address the admin pasted, as JSON. Nothing is
    saved: the page puts it into the form and the admin presses Save."""
    try:
        found = source.product(request.form.get("url"), _store_password())
    except source.SourceError as e:
        return jsonify(error=str(e)), 400
    if found["image"]:
        found["image"] = url_for("admin_source_image", u=found["image"])
    # The store has no brand field: work it out from the names (theirs, and the
    # one the form holds now).
    found["brand"] = items.brand_for(g.db, [found["name"], request.form.get("name")],
                                     found.pop("tags"))
    return jsonify(found)


@app.route("/admin/source/image")
@admin_required
def admin_source_image():
    """A Kosher Wine World product picture, passed through to the edit page's
    photo tool (a browser cannot read another site's picture into a canvas)."""
    try:
        data, kind = source.image(request.args.get("u"), _store_password())
    except source.SourceError as e:
        return jsonify(error=str(e)), 400
    return Response(data, mimetype=kind, headers={"Cache-Control": "private, max-age=300"})


@app.route("/admin/items")
@admin_required
def admin_items():
    """What can be added: the items of the current state's inventory that have
    no catalog entry."""
    if g.state is None:
        abort(404)
    rows = sorted(db.uncataloged(g.db, g.state), key=lambda r: (r["name"] or "").casefold())
    return render_template("items.html", rows=rows, state_name=_state_name(g.state),
                           inventory_name=g.states[g.state]["inventory"], note=_note())


@app.route("/admin/history", methods=["GET", "POST"])
@admin_required
def admin_history():
    error = None
    if request.method == "POST":
        try:
            items.undo(g.db, request.form.get("id"), g.user)
            _note("The change was undone.")
            return redirect(url_for("admin_history"))
        except ValueError as e:
            error = str(e)
    rows = [dict(c, when=_when(c["at"])) for c in items.changes(g.db)]
    return render_template("history.html", rows=rows, note=_note(), error=error), \
        (400 if error else 200)


# --- photos (behind the login, like everything else) ---------------------------

@app.route("/photo/<any(grid, detail):kind>/<path:name>")
@login_required
def photo(kind, name):
    if not name.endswith(".webp"):
        abort(404)
    resp = send_from_directory(PHOTO_DIR / kind, name, max_age=86400)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@app.errorhandler(404)
def not_found(_e):
    if g.get("user") is None:
        return redirect(url_for("login"))
    return render_template("message.html", title="Not found",
                           message="That page or product does not exist."), 404
