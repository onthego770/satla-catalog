"""catalog.satlaspirits.com: the salesman catalog site (Stage 1: sign in, catalog,
product page).

Run by gunicorn as the systemd service `catalog-web` (127.0.0.1:5001) behind
Caddy, the same arrangement as orders.satlaspirits.com.

This worker reads ONLY Catalog.db. It never calls QuickBooks or MMK: prices and
on hand come from the snapshot that `manage.py refresh` stores on a timer (see
catalog_live.py), so a page view cannot disturb the QuickBooks token or the MMK
login. Nothing on the site is visible without signing in.

Local test over plain http: CATALOG_WEB_INSECURE=1 (relaxes the HTTPS-only cookie).
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, abort, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import catalog_db as db

CONFIG_PATH = db.ROOT.parent / "config" / "catalog_config.json"
PHOTO_DIR = db.ROOT / "photos"
OFFICE_TZ = ZoneInfo("America/Chicago")

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
    uid = session.get("uid")
    if uid:
        user = db.user_by_id(g.db, uid)
        if user and user["active"]:
            g.user = user
        else:
            session.clear()


@app.teardown_request
def _close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/photo/"):
                abort(401)
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def _asset_version():
    def asset(name):
        path = db.ROOT / "static" / name
        return url_for("static", filename=name, v=int(path.stat().st_mtime))
    return {"asset": asset}


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


# --- catalog ------------------------------------------------------------------

@app.route("/")
def home():
    return redirect(url_for("catalog"))


@app.route("/catalog")
@login_required
def catalog():
    # Short keys keep the page small; the grid needs no descriptions.
    products = [{
        "sku": r["sku"], "name": r["name"], "size": r["size"], "brand": r["brand"],
        "cat": r["category"], "type": r["type"], "sweet": r["sweetness"],
        "grape": r["grape"], "country": r["country"], "region": r["region"],
        "mev": r["mevushal"], "kfp": r["kfp"], "org": r["organic"], "vint": r["vintage"],
    } for r in db.all_products(g.db)]
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


def _state_figures(sku):
    """Regular price per case and cases on hand for Illinois and Florida, from the
    last snapshot. Illinois price: QuickBooks Illinois. Illinois on hand: MMK.
    Florida price and on hand: QuickBooks Florida."""
    il, fl, mmk = (db.snapshot(g.db, s) for s in ("qbo_il", "qbo_fl", "mmk_il"))

    def price(snap):
        if snap["data"] is None:
            return {"text": "Unavailable", "muted": True}
        item = snap["data"].get(sku)
        if not item or item.get("price") is None:
            return {"text": "No price in QuickBooks", "muted": True}
        return {"text": f"${item['price']:,.2f}", "muted": False}

    if mmk["data"] is None:
        il_hand = {"text": "Unavailable", "muted": True}
    else:
        # MMK lists in-stock products only: absent means none available.
        il_hand = {"text": _cases(mmk["data"].get(sku) or 0), "muted": False}
    if fl["data"] is None:
        fl_hand = {"text": "Unavailable", "muted": True}
    else:
        item = fl["data"].get(sku)
        qty = item.get("qty") if item else None
        fl_hand = ({"text": "—", "muted": True} if qty is None
                   else {"text": _cases(qty), "muted": False})

    sources = []
    for label, snap in (("Illinois price: QuickBooks Illinois", il),
                        ("Illinois on hand: MMK", mmk),
                        ("Florida price and on hand: QuickBooks Florida", fl)):
        sources.append({"label": label, "as_of": _when(snap["fetched_at"]),
                        "stale": not snap["ok"], "tried": _when(snap["attempted_at"])})
    return {"il_price": price(il), "fl_price": price(fl),
            "il_hand": il_hand, "fl_hand": fl_hand, "sources": sources}


@app.route("/product/<path:sku>")
@login_required
def product(sku):
    p = db.product(g.db, sku)
    if p is None:
        abort(404)
    bpc = p["bottles_per_case"]
    facts = [
        ("Brand", p["brand"]), ("Category", p["category"]), ("Type", p["type"]),
        ("Style", p["style"]), ("Sweetness", p["sweetness"]), ("Grape / base", p["grape"]),
        ("Country", p["country"]), ("Region", p["region"]),
        ("Sub-region / appellation", p["subregion"]), ("ABV", p["abv"]),
        ("Vintage", p["vintage"]), ("Bottle size", p["size"]),
        ("Bottles per case", _cases(bpc) if bpc else ""),
        ("Kosher", p["kosher"]), ("Mevushal", p["mevushal"]),
        ("Kosher for Passover", p["kfp"]), ("Organic", p["organic"]),
        ("Kosher certifier", p["certifier"]), ("SKU", p["sku"]),
    ]
    return render_template("product.html", p=p, facts=facts, live=_state_figures(sku))


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
