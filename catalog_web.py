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
                   send_file, send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import catalog_db as db
import catalog_insight as insight
import catalog_items as items
import catalog_pricelist as pricelist
import catalog_source as source
from urllib.parse import quote_plus

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

LIST_PDF_MAX = 30 * 1024 * 1024             # a supplier's price list, uploaded by an admin

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
        if request.endpoint == "admin_price_list" and g.user["is_admin"]:
            request.max_content_length = LIST_PDF_MAX      # a supplier's PDF is larger than a photo
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


def _price_list(code):
    """True for a choice on the switch that is a supplier's price list held in
    Catalog.db (the Meat list; `price_list` in db.states()): it has no stock,
    no customers and no orders, only items to look at (the owner, 2026-11-18:
    "View only first")."""
    return bool(g.states[code].get("price_list"))


def _sees_prices(code):
    """Whether the signed-in person sees this state's prices: everyone, unless
    the state's row says admins only (the owner, 2026-11-18, on the Meat
    prices: "Admins only")."""
    return bool(g.user["is_admin"]) or not g.states[code].get("price_admin_only")


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
                            and not _price_list(code) else "catalog"))


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
    # `out` marks an item with no stock (see _out()).
    have = db.snapshot(g.db, db.inv_source(g.state))["data"]
    if _price_list(g.state):
        return _list_page(have or {})
    products = [{
        "sku": r["sku"], "name": r["name"], "size": r["size"], "brand": r["brand"],
        "cat": r["category"], "type": r["type"], "sweet": r["sweetness"],
        "grape": r["grape"], "country": r["country"], "region": r["region"],
        "mev": r["mevushal"], "kfp": _kfp(r), "org": r["organic"], "vint": r["vintage"],
        **({"x": 1} if r["uncataloged"] else {}),
        **({"pv": r["photo_v"]} if r["photo_v"] else {}),
        **({"out": 1} if _out(have, r["sku"]) else {}),
    } for r in db.state_products(g.db, g.state)]
    return render_template("catalog.html", products=products)


def _list_page(have):
    """The catalog page of a price list: a table like the supplier's sheet (the
    owner, 2026-11-18: "Spreadsheet layout similar to the PDF. Meaning, rows
    and columns", "include the small pics", and the price "in an editable text
    box"). Rows keep the sheet's order (`n`; pricelist.ordered()). The price goes out only to
    someone who may see it, and only an admin gets the address that saves it."""
    prices = (db.snapshot(g.db, db.qbo_source(g.state))["data"] or {}) if _sees_prices(g.state) else None
    products = [{
        "sku": r["sku"], "name": r["name"], "size": r["size"], "brand": r["brand"],
        "cat": r["category"], "upc": r["upc"], "n": n,
        **({"pv": r["photo_v"]} if r["photo_v"] else {}),
        **({"price": (prices.get(r["sku"]) or {}).get("price")} if prices is not None else {}),
    } for n, r in enumerate(pricelist.ordered(g.db, g.state))]
    return render_template("catalog.html", products=products, prices=prices is not None,
                           pdf_url=url_for("list_pdf"),
                           price_url=url_for("admin_list_price") if g.user["is_admin"] else None,
                           upload_url=url_for("admin_price_list") if g.user["is_admin"] else None)


@app.route("/price-list.pdf")
@login_required
def list_pdf():
    """A price list's sheet as a PDF to download, with the state's logo (the
    owner, 2026-11-18). `?prices=1` adds the Price column, for someone who may
    see prices; anyone else gets the sheet without it whatever they ask.
    `?only=` limits it to the items the page is showing (the owner, 2026-11-18:
    "the pdf only prints what's been filtered at that moment")."""
    if not _price_list(g.state):
        abort(404)
    prices = request.args.get("prices") == "1" and _sees_prices(g.state)
    # `only`: the item numbers the page is showing just now (its search, section
    # and brand), separated by commas; absent = the whole list.
    only = None
    if request.args.get("only"):
        held = {p["sku"] for p in db.state_products(g.db, g.state)}
        only = held & set(request.args["only"].split(","))
        if not only:
            abort(404)
        if only == held:
            only = None
    try:
        path = pricelist.pdf_file(g.db, g.state, prices, only)
    except RuntimeError as e:
        app.logger.error("price list PDF failed: %s", e)
        return render_template("message.html", title="The PDF could not be made", message=(
            "The server could not make the PDF just now. Try again in a minute.")), 503
    today = datetime.now(OFFICE_TZ).strftime("%Y-%m-%d")
    resp = send_file(path, mimetype="application/pdf", as_attachment=True, max_age=0,
                     download_name=f"Satla-{_state_name(g.state)}-price-list-{today}"
                                   f"{'' if only is None else '-selection'}"
                                   f"{'' if prices else '-no-prices'}.pdf")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _typed_price(text):
    """A price as an admin typed it ("14.04", "$1,200"): a float, or None for a
    blank box. ValueError when it is not a price."""
    text = (text or "").strip().replace("$", "").replace(",", "")
    price = round(float(text), 2) if text else None
    if price is not None and not 0 <= price <= 99999:      # also refuses "nan"
        raise ValueError(text)
    return price


@app.route("/admin/list-price", methods=["POST"])
@admin_required
def admin_list_price():
    """Save one price typed on a price list's catalog page. Answers JSON:
    {'ok': True, 'price': number or None} or {'ok': False, 'error': text}."""
    sku = request.form.get("sku") or ""
    if g.state is None or not _price_list(g.state):
        abort(400)
    try:
        price = _typed_price(request.form.get("price"))
    except ValueError:
        return jsonify(ok=False, error="Type a price such as 14.04, or leave it blank."), 400
    if not db.set_list_price(g.db, g.state, sku, price, g.user["name"]):
        return jsonify(ok=False, error="That item is not on the list."), 404
    return jsonify(ok=True, price=price)


@app.route("/admin/price-list", methods=["GET", "POST"])
@admin_required
def admin_price_list():
    """Upload a newer issue of one of a price list's supplier lists (the owner,
    2026-11-19: "an Upload box where I can enter in either a new CHB pdf or
    Springfield pdf so you can parse it and update all the items and add any
    new items"). Three steps on one page: choose the PDF; see what it would
    change (nothing is changed yet); confirm. The reading and the loading are
    pricelist.upload_read() and upload_apply()."""
    if g.state is None or not _price_list(g.state):
        abort(404)
    page = dict(state_name=_state_name(g.state),
                lists=sorted({v.get("list") for v in (db.snapshot(g.db, db.extra_source(g.state))["data"]
                                                      or {}).values() if v.get("list")}))
    if request.method == "GET" and request.args.get("job"):
        # A load that was confirmed: still running (the page asks again), done, or failed.
        how = pricelist.upload_state(g.state, request.args["job"])
        if how is None:
            return redirect(url_for("admin_price_list"))
        if how.get("running"):
            return render_template("pricelist.html", **page, running=True)
        if how["ok"]:
            return render_template("pricelist.html", **page, done=how["message"])
        app.logger.error("price list upload failed: %s", how["message"])
        return render_template("pricelist.html", **page, problem=(
            f"The list was NOT loaded, or only part of it. {how['message']} "
            "Look at the list and at Admin › Item history before trying again."))
    if request.method == "GET":
        return render_template("pricelist.html", **page)
    if request.form.get("action") == "read":
        f = request.files.get("file")
        data = f.read(LIST_PDF_MAX + 1) if f and f.filename else b""
        if not data.startswith(b"%PDF"):
            return render_template("pricelist.html", **page, problem=(
                "Choose the supplier's price list as a PDF file, then press Read the list."))
        try:
            token, seen = pricelist.upload_read(g.state, data)
        except RuntimeError as e:
            return render_template("pricelist.html", **page, problem=f"The list was not read. {e}")
        return render_template("pricelist.html", **page, token=token, seen=seen, file_name=f.filename)
    token = request.form.get("token") or ""
    seen = pricelist.upload_seen(token)
    if seen is None:
        return render_template("pricelist.html", **page, problem=(
            "That upload is no longer here. Choose the file again."))
    add = set(request.form.getlist("add"))
    # The price boxes: only a price typed over what the box held is a choice.
    prices, bad = {}, []
    for box, rows in (("newprice", seen["new"]),):
        for n, r in enumerate(rows):
            try:
                price = _typed_price(request.form.get(f"{box}-{n}"))
            except ValueError:
                bad.append(r["name"])
                continue
            if price != (None if r["price"] is None else round(r["price"], 2)):
                prices[r["sku"]] = r["price"] = price       # shown again if the page comes back
    if bad:
        return render_template("pricelist.html", **page, token=token, seen=seen,
                               file_name=request.form.get("file_name") or "This file", problem=(
            "Nothing was loaded. Type a price such as 14.04, or leave the box blank, for: "
            + ", ".join(bad) + "."))
    choices = {
        "sections": {r["sku"]: " ".join((request.form.get(f"section-{n}") or "").split())[:60]
                     for n, r in enumerate(seen["new"]) if not r["section"]},
        "leave": [r["sku"] for r in seen["new"] if r["sku"] not in add],
        "prices": prices,
    }
    try:
        pricelist.upload_apply(g.state, token, choices, g.user["name"])
    except RuntimeError as e:
        return render_template("pricelist.html", **page, problem=f"The list was NOT loaded: {e}.")
    return redirect(url_for("admin_price_list", job=token))


def _out(have, sku):
    """Out of stock: the state's last inventory read shows 0 cases or fewer
    (the owner, 2026-11-17: a red "OUT" box like the Mevushal one). Unknown
    stock (inventory not read yet) is not called out."""
    return have is not None and sku in have and have[sku] is not None and have[sku] <= 0


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

    if _price_list(state):
        # A price list: the list's own price, and no stock figure at all.
        listed = (qbo["data"] or {}).get(sku) or {}
        price = ({"text": "No price on the list", "muted": True} if listed.get("price") is None
                 else {"text": f"${listed['price']:,.2f}", "muted": False})
        edited = listed.get("edited")
        return {"state": name, "price": price, "hand": None, "list": True,
                "edited": edited and {"by": edited["by"], "at": _when(edited["at"]),
                                      "was": None if edited["was"] is None else f"${edited['was']:,.2f}"},
                "sources": [{"label": "Price: " + g.states[state]["inventory"],
                             "as_of": _when(qbo["fetched_at"]), "stale": False,
                             "tried": _when(qbo["attempted_at"])}]}
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
        hand = {"text": _cases(inv["data"][sku]), "muted": False, "out": _out(inv["data"], sku)}

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
    listed = _price_list(g.state)
    facts = [(label, value) for label, value in (
        ("Brand", p["brand"]), ("Section", p["category"]), ("Type", p["type"]),
        ("Country", p["country"]), ("Specs", p["size"]), ("UPC", p["upc"]),
        ("Kosher certifier", p["certifier"]), ("SKU", p["sku"])) if value
    ] if listed else [
        ("Brand", p["brand"]), ("Category", p["category"]), ("Type", p["type"]),
        ("Style", p["style"]), ("Sweetness", p["sweetness"]), ("Grape / base", p["grape"]),
        ("Country", p["country"]), ("Region", p["region"]),
        ("Sub-region / appellation", p["subregion"]), ("ABV", p["abv"]),
        ("Vintage", p["vintage"]), ("Bottle size", p["size"]),
        ("Bottles per case", _cases(bpc) if bpc else ""),
        ("Mevushal", p["mevushal"]), ("Organic", p["organic"]),
        ("Kosher certifier", p["certifier"]), *([("UPC", p["upc"])] if p["upc"] else []),
        ("SKU", p["sku"]),
    ]
    return render_template("product.html", p=p, facts=facts,
                           live=_state_figures(sku, g.state) if _sees_prices(g.state) else None,
                           inventory_name=g.states[g.state]["inventory"],
                           out=_out(db.snapshot(g.db, db.inv_source(g.state))["data"], sku),
                           can_add=bool(p["uncataloged"]) and items.inventory_item(g.db, sku) is not None,
                           in_states=[] if p["uncataloged"] else items.catalog_states(g.db, sku),
                           # Copy is between states that sell the same drinks, never
                           # to or from a price list.
                           all_states=[] if listed else
                           [st for st in g.states if not _price_list(st)])


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


# --- What to sell (owner, 2026-11-19) -------------------------------------------
# Worked out from the stored invoices each time a page is built; nothing is
# typed in and nothing is stored. The rules are in catalog_insight.py.

_BOOKS = {}          # {state: (the stamp of its invoice read, insight.book())}


def _today():
    """Today at the office (Central time)."""
    return datetime.now(OFFICE_TZ).date()


def _date(iso_date):
    return datetime.strptime(iso_date, "%Y-%m-%d").date()


def _book(company):
    """insight.book() for one state's invoices, kept in this worker until the
    refresh reads them again (sorting them out for every page view would be
    wasted work on a small server)."""
    stamp = db.snapshot(g.db, db.qbo_source(company))["attempted_at"]
    held = _BOOKS.get(company)
    if held is None or held[0] != stamp:
        held = _BOOKS[company] = (stamp, insight.book(db.company_invoices(g.db, company)))
    return held[1]


def _brief(company, cid, today=None):
    """insight.brief() for one customer: what they buy, what they stopped
    buying, what similar customers carry, what is new, and what to ask for.
    The products are the ones New Order offers (_order_products()), so what is
    suggested is exactly what can be ordered."""
    products = {p["sku"]: p for p in _order_products(company, cid)}
    return insight.brief(_book(company), cid, products, today or _today())


@app.template_filter("shortday")
def shortday(day):
    """A date as 'Aug 14', with the year when it is not this year."""
    return day.strftime("%b %-d" if day.year == _today().year else "%b %-d, %Y")


@app.template_filter("cs")
def cs(value):
    return _cases(value)


@app.template_filter("span")
def span(days):
    return insight.span(days)


@app.route("/customers")
@login_required
def customers():
    if _price_list(g.state):
        return render_template("message.html", title="No customers here", message=(
            f"{_state_name(g.state)} is a price list to look at: it has no customers "
            "or orders on this site. Use the switch at the top for a state's customers."))
    # Beside each customer: how long ago the last order was and where the
    # customer stands against its usual gap between orders (catalog_insight).
    flags = insight.customer_flags(
        {cid: [_date(d) for d in days] for cid, days in db.order_days(g.db, g.state).items()},
        _today())
    rows, seen = [], db.customers(g.db, g.state, _whose())
    # Above the list: what these customers owe in all, what is past due, and
    # the customers most worth a call today (catalog_insight.opportunities()).
    owing = [r for r in seen if (r["balance"] or 0) > 0.004]
    late = [r for r in seen if (r["overdue"] or 0) > 0.004]
    names = {r["id"]: r for r in seen}
    board = {
        "due": sum(r["balance"] for r in owing), "due_customers": len(owing),
        "open_n": sum(r["open_n"] or 0 for r in owing),
        "late": sum(r["overdue"] for r in late), "late_customers": len(late),
        "late_n": sum(r["overdue_n"] or 0 for r in late),
        "late_since": _date(min(r["overdue_since"] for r in late if r["overdue_since"]))
                      if any(r["overdue_since"] for r in late) else None,
        "asks": [{**o, "name": names[o["id"]]["name"], "city": names[o["id"]]["city"],
                  "late": names[o["id"]]["overdue"] or 0}
                 for o in insight.opportunities(_book(g.state)["orders"], list(names), _today())],
    }
    for r in seen:
        f = flags.get(r["id"])
        rows.append({"co": r["company"], "id": r["id"], "name": r["name"], "city": r["city"],
                     "st": r["state"],
                     # what the customer owes in all, and the part of it past due
                     "bal": round(r["balance"] or 0, 2), "late": round(r["overdue"] or 0, 2),
                     **({"days": f["days"], "flag": f["status"],
                         "rank": insight.ATTENTION[f["status"]]} if f else {})})
    return render_template("customers.html", customers=rows, mine=_whose() is not None,
                           board=board,
                           words=insight.STATUS_WORDS,
                           sources=_qbo_sources((g.state,)))


@app.route("/customer/<company>/<cid>")
@login_required
def customer(company, cid):
    _use_state(company)
    c = _customer(company, cid)
    today = _today()
    listed = (today - timedelta(days=insight.RULES["window_days"])).isoformat()
    invoices = [{"id": v["id"], "doc_number": v["doc_number"], "date": _day(v["txn_date"]),
                 "items": len(json.loads(v["lines"])), "total": v["total"],
                 "open": (v["balance"] or 0) > 0.004}
                for v in db.customer_invoices(g.db, company, cid, listed)]
    place = " ".join(x for x in (", ".join(x for x in (c["city"], c["state"]) if x), c["zip"]) if x)
    address = ", ".join(x for x in (c["street"], place) if x)
    return render_template("customer.html", c=c, address=address, invoices=invoices,
                           brief=_brief(company, cid, today), words=insight.STATUS_WORDS,
                           rules=insight.RULES, today=today,
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
                    **({"out": 1} if _out(have, sku) else {}),
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
    if request.args.get("due"):
        # From the customer page's "Start an order": the products that are due,
        # at their usual quantity. It uses the Copy Order path of order.js.
        due = _brief(company, cid)["due"]
        if due:
            copy = {"doc": "", "label": "Started from the products that are due",
                    "lines": due}
    elif iid:
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
    entry can be added only when a state's inventory system holds it, or from
    scratch through "Add new item" on Admin > Add items (?new=1)."""
    row = db.product(g.db, sku)
    adding = row is None
    scratch = adding and request.args.get("new") == "1" and items.clean_sku(sku) == sku
    p = items.blank_item(g.db, sku, scratch=scratch) if adding else dict(row)
    if p is None:
        abort(404)
    scratch = adding and items.inventory_item(g.db, sku) is None
    source, matches = _copy_source(sku, p) if adding else (None, [])
    if source:
        p = items.copied(g.db, source, p)
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
            if photos is items.KEEP and source:
                photos = items.photos_of(source["sku"]) or items.KEEP   # the copy takes the photo too
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
    photo_sku = source["sku"] if source else (None if adding else sku)
    has_photo = bool(photo_sku) and (PHOTO_DIR / "detail" / f"{photo_sku}.webp").exists()
    shown = not adding and bool(g.state and db.state_product(g.db, g.state, sku))
    held = items.catalog_states(g.db, sku)
    return render_template("item.html", p=p, adding=adding, scratch=scratch, shown=shown, problems=problems,
                           source=source, matches=[m for m in matches if not source or m["sku"] != source["sku"]],
                           photo_sku=photo_sku, photo_v=(source or p).get("photo_v"),
                           source_states="/".join(items.catalog_states(g.db, source["sku"])) if source else "",
                           # An item only a price list holds: its "size" is the list's Specs.
                           specs=bool(held) and all(_price_list(st) for st in held),
                           fields=items.FIELDS, suggest=items.suggestions(g.db),
                           names=items.system_names(g.db, sku), has_photo=has_photo,
                           sizes=items.PHOTO_SIZES), (400 if problems else 200)


def _copy_source(sku, p):
    """For the Add form: the catalog entry to fill it from, and the entries
    that may be the same item under another number in the other state's
    catalog (the owner, 2026-11-18: "check the opposite catalog to see if it's
    already there? If yes ... pre-populate the screen with that"). `?copy=<SKU>`
    names the entry (the product page's Copy button); `?copy=` starts blank;
    with neither, the best match fills the form only when it is strong
    (items.sure_match()); otherwise they are only offered."""
    inv = items.inventory_item(g.db, sku)
    mine = [inv["state"]] if inv else ([g.state] if g.state else [])
    other = [st for st in g.states if st not in mine and not _price_list(st)]
    matches = items.copy_matches(g.db, sku, (p.get("name") or "") if inv else "", other)
    asked = request.args.get("copy")
    if asked:
        row = db.product(g.db, asked)
        if row is None or asked == sku:
            abort(404)
        return dict(row), matches
    if asked is None and (sure := items.sure_match(matches)):
        return dict(db.product(g.db, sure["sku"])), matches
    return None, matches


@app.route("/admin/copy/<path:sku>", methods=["GET"])
@admin_required
def admin_copy(sku):
    """The product page's Copy button: put a copy of this catalog entry under
    the item number another state uses for the same item. Lists that state's
    items with no catalog entry, closest first, and takes any item number."""
    row = db.product(g.db, sku)
    to = request.args.get("to") or ""
    if row is None or to not in g.states or _price_list(to):
        abort(404)
    error = None
    number = items.clean_sku(request.args.get("number")) if "number" in request.args else None
    if "number" in request.args:
        if number is None:
            error = "Type an item number (letters, digits, spaces and . _ / - only, at most 40 characters)."
        elif db.product(g.db, number):
            error = f"{number} is already in the catalog ({db.product(g.db, number)['name']}). Open its page to edit it."
        else:
            args = {"copy": sku} | ({} if items.inventory_item(g.db, number) else {"new": 1})
            return redirect(url_for("admin_item", sku=number, **args))
    hidden = db.hidden_items(g.db)
    rows = [dict(r, hidden=r["sku"] in hidden) for r in items.other_items(g.db, sku, row["name"], to)]
    there = items.copy_matches(g.db, sku, row["name"], [to])
    return render_template("copy.html", p=row, to=to, to_name=_state_name(to), there=there,
                           inventory_name=g.states[to]["inventory"], rows=rows, error=error,
                           number=request.args.get("number") or ""), (400 if error else 200)


def _store_password():
    """The Kosher Wine World storefront password, from the site's private config."""
    return source.password(CONFIG_PATH)


def _found(found):
    """What a retailer's page gave, ready for the edit form: the picture goes
    through this site, and what the page has no field for is worked out: the
    brand from the names; the grape, and for spirits the category and type,
    from the page's product name when the page gave none; the country from
    the brand's other catalog products when they all agree."""
    if found["image"]:
        found["image"] = url_for("admin_source_image", u=found["image"])
    found["brand"] = items.brand_for(g.db, [found["name"], request.form.get("name")],
                                     found.pop("tags"))
    if not found.get("grape"):
        found["grape"] = items.grape_for(g.db, found["name"])
    if not found.get("category"):                # a spirits page gives no type at all
        found["category"], kind = items.kind_for(g.db, found["name"])
        found["type"] = found.get("type") or kind
    if not found.get("country") and found["brand"]:
        found["country"] = items.brand_country(g.db, found["brand"])
    return jsonify(found)


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
    return _found(found)


@app.route("/admin/source/paste", methods=["POST"])
@admin_required
def admin_source_paste():
    """The edit form's paste box: a product page of KosherWine.com or of any
    other site, which the admin copied in their own browser and pasted, read
    into the same JSON as admin_source(). No page is requested from such a
    site; only the product's picture is fetched."""
    try:
        found = source.pasted(request.form.get("text"), request.form.get("name") or "")
    except source.SourceError as e:
        return jsonify(error=str(e)), 400
    return _found(found)


@app.route("/admin/source/find", methods=["POST"])
@admin_required
def admin_source_find():
    """The edit form's Find button: the closest matches on Kosher Wine World and
    Kosher Wine Direct for an item number and / or a wine name, best first, from
    the copies of those stores' product lists the refresh keeps; and the address
    of the same search on KosherWine.com, for the admin to open in their own
    browser."""
    sku = " ".join((request.form.get("sku") or "").split())
    name = " ".join((request.form.get("name") or "").split())[:200]
    item = request.form.get("item") or ""
    if not sku and not name:
        return jsonify(error="Type an item number or a wine name first."), 400
    snaps = {label: db.snapshot(g.db, src) for label, src in
             (("Kosher Wine World", db.STORE_SOURCE), ("Kosher Wine Direct", db.KWD_SOURCE))}
    matches = source.rank([dict(p, store=p.get("store") or label)
                           for label, snap in snaps.items() for p in snap["data"] or []],
                          sku, name, limit=8)
    for m in matches:
        if m["image"]:
            m["thumb"] = m["image"] + ("&" if "?" in m["image"] else "?") + "width=160"
        # Their page filed under a DIFFERENT item's number: say which item that is here.
        others = [s for s in m["skus"] if s.upper() != item.upper()]
        if item and len(others) == len(m["skus"]):
            for s in others:
                row = db.product(g.db, s) or items.inventory_item(g.db, s)
                if row:
                    m["other"] = (f"Careful: their page is filed under item number {s}, "
                                  f"which here is {row['name']}.")
                    break
    said = " ".join(source.words(name))
    return jsonify(matches=matches, words=said,
                   listed={label: len(snap["data"] or []) for label, snap in snaps.items()},
                   as_of={label: (_when(snap["fetched_at"]) or {}).get("text", "")
                          for label, snap in snaps.items()},
                   kw_search=source.KW_SEARCH + quote_plus(said) if said else "")


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


@app.route("/admin/items", methods=["GET", "POST"])
@admin_required
def admin_items():
    """What can be added: the items of the current state's inventory that have
    no catalog entry, less those an admin hid (a Hide button on each row, and
    "Show again" under the list; a hidden item is also off the catalog). Also
    "Add new item" from scratch, and the catalog items no inventory holds yet."""
    if g.state is None:
        abort(404)
    rows = sorted(db.uncataloged(g.db, g.state), key=lambda r: (r["name"] or "").casefold())
    if request.method == "POST" and request.form.get("action") == "new":
        sku = items.clean_sku(request.form.get("new_sku"))
        if sku is None:
            _note("Type the new item's number (letters, digits, spaces and . _ / - only, "
                  "at most 40 characters), then press Add new item.")
            return redirect(url_for("admin_items"))
        if db.product(g.db, sku) or items.inventory_item(g.db, sku):
            return redirect(url_for("admin_item", sku=sku))   # edit it, or add it from its inventory record
        return redirect(url_for("admin_item", sku=sku, new=1))
    if request.method == "POST":
        sku = request.form.get("sku") or ""
        row = next((r for r in rows if r["sku"] == sku), None)
        if row is None:
            abort(400)
        hide = request.form.get("action") == "hide"
        db.hide_item(g.db, sku, g.user["name"], hidden=hide)
        _note(f"{row['name']} ({sku}) " + ("is hidden from this list." if hide else "is back on this list."))
        return redirect(url_for("admin_items"))
    hidden = db.hidden_items(g.db)
    return render_template("items.html", rows=[r for r in rows if r["sku"] not in hidden],
                           hidden=[r for r in rows if r["sku"] in hidden],
                           state_name=_state_name(g.state), waiting=items.not_in_inventory(g.db),
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
