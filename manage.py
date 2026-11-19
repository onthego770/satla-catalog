#!/usr/bin/env python3
"""Behind-the-scenes commands for the catalog site. (Logins can also be managed
by an admin on the site's Admin page.)

Run with the library's Python, by explicit path:

  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py init
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py load-products
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py load-pack
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py refresh
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py add-user "Full Name" name@example.com --states IL,FL
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py set-states name@example.com IL
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py set-password name@example.com
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py remove-user name@example.com
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py list-users
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py set-admin name@example.com on
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py order-email on

init           Create Catalog.db and the site's secret key. Safe to re-run.
load-products  Load the products from Satla_Master_Catalog.csv OVER Catalog.db. Needs
               --force: Catalog.db is the master since 2026-11-16 (admins edit items
               on the site) and the file is its copy, so this is only for restoring.
export-products  Rewrite Satla_Master_Catalog.csv from Catalog.db. The site does this
               itself after every change an admin makes.
load-pack      Fill bottles per case and ml from QuickBooks and MMK (read-only).
refresh        Read regular prices and on hand from QuickBooks and MMK (read-only)
               into the snapshot the pages show. A timer runs this every 30 minutes.
               Once a day it also reads the product lists of Kosher Wine World and
               Kosher Wine Direct, for the edit form's Find button.
load-price-list  Load a supplier's price list (a PDF) as the items of a price-list
               state, e.g. `load-price-list MEAT ~/GEN7.pdf --list GEN7`: new items get a
               catalog entry, prices follow the list, entries already there follow
               what the supplier changed since its last list. Nothing is read from
               QuickBooks or MMK.
read-price-list  Say what loading a newer issue of a list would change, without
               changing anything (the site's "Upload a new list" page runs this):
               `read-price-list MEAT ~/GEN7.pdf out.json`. It works out whose list it is.
price-list-pdf  Print a price-list state's sheet to a PDF file (the site's "Download
               PDF" button runs this): `price-list-pdf MEAT out.pdf --prices`.
store-list     Read the product lists of Kosher Wine World and Kosher Wine Direct now.
set-admin      Give (on) or take away (off) a login's admin rights: the Admin page.
order-email    Switch the sending of New Order emails on or off. While it is off,
               Send order shows the email it would send and sends nothing. The
               email goes out from the mailbox in ~/python/config/mail_config.json
               through the library's mail_send.send_mail().
set-states     Set which states a login may use (IL, FL, or IL,FL).
add-user       Create a salesman login for the states given with --states. The password is typed at a hidden prompt;
               never put a password on the command line or in a chat.
"""
import argparse
import csv
import getpass
import json
import secrets
import sys

from werkzeug.security import generate_password_hash

import catalog_db as db

CSV_PATH = db.ROOT / "Satla_Master_Catalog.csv"
CONFIG_PATH = db.ROOT.parent / "config" / "catalog_config.json"   # ~/python/config, chmod 600
MIN_PASSWORD = 8


def cmd_init(_args):
    db.init()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps({"secret_key": secrets.token_hex(32)}, indent=2))
        print(f"created {CONFIG_PATH}")
    CONFIG_PATH.chmod(0o600)
    print(f"database ready: {db.DB_PATH}")


def cmd_load_products(args):
    if not args.force:
        sys.exit("Catalog.db is the master since 2026-11-16: admins edit items on the site "
                 f"and {CSV_PATH.name} is rewritten from it.\nLoading the file would overwrite "
                 "those edits with whatever the file holds. If that is what you want, "
                 "run it again with --force.")
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cols = list(db.CSV_COLUMNS.values())
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "sku")
    sql = (f"INSERT INTO products ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
           f"ON CONFLICT(sku) DO UPDATE SET {updates}")
    con = db.connect()
    seen = set()
    with con:
        for r in rows:
            values = [(r.get(src) or "").strip() for src in db.CSV_COLUMNS]
            if not values[0]:
                continue
            seen.add(values[0])
            con.execute(sql, values)
        for r in rows:                      # columns the file gained later
            sku = (r.get("Satla SKU") or "").strip()
            for src, col in db.CSV_LATER_COLUMNS.items():
                if sku and src in r:
                    con.execute(f"UPDATE products SET {col}=? WHERE sku=?", ((r[src] or "").strip(), sku))
        # The pack figures, when the file has them (it does once it has been exported).
        for r in rows:
            sku = (r.get("Satla SKU") or "").strip()
            if sku and all(src in r for src in db.CSV_PACK_COLUMNS):
                bpc, ml = (float(r[c]) if (r[c] or "").strip() else None
                           for c in ("Bottles per Case", "Bottle ml"))
                con.execute("UPDATE products SET bottles_per_case=?, bottle_ml=?, pack_source=? "
                            "WHERE sku=?", (bpc, ml, (r["Pack Source"] or "").strip() or None, sku))
    extra = sorted(db.skus(con) - seen)
    con.close()
    print(f"{len(seen)} products loaded from {CSV_PATH.name}")
    if extra:
        print(f"note: {len(extra)} products are in Catalog.db but not in the file "
              f"(left as they are): {', '.join(extra)}")


def cmd_export_products(_args):
    import catalog_items
    con = db.connect()
    n = catalog_items.export_file(con)
    con.close()
    print(f"{n} products written to {CSV_PATH.name} from Catalog.db")


def cmd_load_pack(args):
    import catalog_live
    missing = catalog_live.load_pack(overwrite=args.overwrite)
    if missing:
        print("unknown:", ", ".join(missing))


STORE_LIST_HOURS = 24


def _store_list(force=False):
    """Keep a copy of the product lists of Kosher Wine World and Kosher Wine
    Direct in Catalog.db, for the edit form's Find button. Each is read again
    once it is STORE_LIST_HOURS old; a failed read keeps the last good list."""
    from datetime import datetime, timedelta, timezone
    import catalog_source as source
    con = db.connect()
    for snap_source, label, read in (
            (db.STORE_SOURCE, "Kosher Wine World", lambda: source.listing(source.password(CONFIG_PATH))),
            (db.KWD_SOURCE, "Kosher Wine Direct", source.listing_kwd)):
        last = db.snapshot(con, snap_source)["attempted_at"]
        if last and not force:
            age = datetime.now(timezone.utc) - datetime.strptime(
                last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if age < timedelta(hours=STORE_LIST_HOURS):
                continue
        try:
            products = read()
            db.save_snapshot(con, snap_source, products)
            print(f"{label} product list: {len(products)} products")
        except source.SourceError as e:
            db.save_snapshot(con, snap_source, error=e)
            print(f"{label} product list not read: {e}")
    con.close()


def cmd_refresh(_args):
    import catalog_live
    catalog_live.refresh()
    _store_list()


def cmd_load_price_list(args):
    import fcntl
    import catalog_items
    import catalog_live
    import catalog_pricelist
    said = []

    def report(ok, message):                    # for the upload page, which is waiting
        if args.report:
            with open(args.report, "w") as f:
                json.dump({"ok": ok, "message": message}, f)

    try:
        db.init()
        con = db.connect()
        catalog_live.save_states(con)           # so a state added to the library is known
        state = _states(con, args.state)[0]
        rows = (catalog_pricelist.read_cards_pdf(args.file, args.list, args.section) if args.cards
                else catalog_pricelist.read_pdf(args.file))
        choices = json.loads(open(args.choices).read()) if args.choices else None
        photos = None
        if args.photos:                         # for the items that have no photo yet
            leave = set((choices or {}).get("leave") or ())
            catalog_pricelist.PDF_DIR.mkdir(exist_ok=True)
            with open(catalog_pricelist.PDF_DIR / ".lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)         # one browser at a time: the server is small
                photos = catalog_pricelist.make_photos({
                    r["sku"]: r["picture"] for r in rows
                    if r["picture"] and r["sku"] not in leave and not catalog_items.photos_of(r["sku"])})
        catalog_pricelist.load(con, state, rows, {"id": None, "name": args.by}, args.list,
                               photos=photos, choices=choices,
                               log=lambda text: (said.append(text), print(text)))
    except ValueError as e:
        report(False, str(e))
        sys.exit(str(e))
    except BaseException as e:
        report(False, f"{type(e).__name__}: {e}")
        raise
    report(True, " ".join(said))


def cmd_read_price_list(args):
    import catalog_pricelist
    con = db.connect()
    state = _states(con, args.state)[0]
    try:
        name, cards, rows = catalog_pricelist.identify(con, state, args.file)
        found = dict(catalog_pricelist.compare(con, state, name, rows), cards=cards)
    except ValueError as e:
        sys.exit(str(e))
    with open(args.out, "w") as f:
        json.dump(found, f)
    print(f"{name}: {found['count']} items; {len(found['new'])} new, {len(found['prices'])} prices changed, "
          f"{len(found['details'])} with other changes, {len(found['gone'])} no longer on the list")


def cmd_price_list_pdf(args):
    import catalog_pricelist
    con = db.connect()
    catalog_pricelist.write_pdf(con, _states(con, args.state)[0], args.prices, args.out,
                                only=set(args.only.split(",")) if args.only else None)


def cmd_store_list(_args):
    _store_list(force=True)


def _ask_password():
    while True:
        pw = getpass.getpass("Password: ")
        if len(pw) < MIN_PASSWORD:
            print(f"At least {MIN_PASSWORD} characters.")
            continue
        if pw == getpass.getpass("Again: "):
            return pw
        print("The two did not match.")


def _states(con, text):
    """'il, fl' as ['IL', 'FL'], checked against the states the site knows."""
    known = db.states(con)
    codes = [c.strip().upper() for c in text.split(",") if c.strip()]
    bad = [c for c in codes if c not in known]
    if bad or not codes:
        sys.exit(f"unknown state {', '.join(bad) or '(none given)'}; the states are: {', '.join(known)}")
    return [c for c in known if c in codes]


def cmd_add_user(args):
    email = args.email.strip().lower()
    con = db.connect()
    states = _states(con, args.states)
    if db.user_by_email(con, email):
        sys.exit(f"{email} already has a login. Use set-password to change it.")
    pw = _ask_password()
    db.add_user(con, args.name, email, generate_password_hash(pw), states=states)
    print(f"login created for {args.name} <{email}>, states: {', '.join(states)}")


def cmd_set_states(args):
    con = db.connect()
    user = db.user_by_email(con, args.email)
    if not user:
        sys.exit(f"no login for {args.email}")
    states = _states(con, args.states)
    db.update_user(con, user["id"], states=",".join(states))
    print(f"{user['email']} may now use: {', '.join(states)}")


def cmd_set_password(args):
    con = db.connect()
    user = db.user_by_email(con, args.email)
    if not user:
        sys.exit(f"no login for {args.email}")
    pw = _ask_password()
    db.update_user(con, user["id"], password_hash=generate_password_hash(pw), active=1)
    print(f"password changed for {user['email']}")


def cmd_remove_user(args):
    con = db.connect()
    user = db.user_by_email(con, args.email)
    if not user:
        sys.exit(f"no login for {args.email}")
    db.remove_user(con, user["id"])
    print(f"login removed for {user['email']}")


def cmd_list_users(_args):
    con = db.connect()
    rows = db.users(con)
    if not rows:
        print("no logins yet")
    for r in rows:
        print(f"{r['name']:<28} {r['email']:<36} {'active' if r['active'] else 'OFF':<6} "
              f"{'ADMIN' if r['is_admin'] else '':<5} {r['states'] or 'NO STATE':<8} since {r['created_at'][:10]}")


def cmd_set_admin(args):
    con = db.connect()
    user = db.user_by_email(con, args.email)
    if not user:
        sys.exit(f"no login for {args.email}")
    db.update_user(con, user["id"], is_admin=int(args.state == "on"))
    print(f"admin rights {args.state} for {user['email']}")


def cmd_order_email(args):
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg["order_email"] = args.state == "on"
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.chmod(0o600)
    tmp.replace(CONFIG_PATH)
    print(f"sending of order emails is now {args.state.upper()}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init").set_defaults(func=cmd_init)
    lpr = sub.add_parser("load-products")
    lpr.add_argument("--force", action="store_true",
                     help="overwrite Catalog.db's products with the file (Catalog.db is the master)")
    lpr.set_defaults(func=cmd_load_products)
    sub.add_parser("export-products").set_defaults(func=cmd_export_products)
    lp = sub.add_parser("load-pack")
    lp.add_argument("--overwrite", action="store_true", help="replace values already filled")
    lp.set_defaults(func=cmd_load_pack)
    sub.add_parser("refresh").set_defaults(func=cmd_refresh)
    sub.add_parser("store-list").set_defaults(func=cmd_store_list)
    pl = sub.add_parser("load-price-list")
    pl.add_argument("state", help="the price-list state, e.g. MEAT")
    pl.add_argument("file", help="the supplier's price list, a PDF")
    pl.add_argument("--list", required=True,
                    help="which supplier's list this is, e.g. GEN7 or CHB; only that list's items are replaced")
    pl.add_argument("--cards", action="store_true",
                    help="the PDF is laid out as cards with no item numbers (CH Butcher); "
                         "--list is then also the brand, and each item number is <list>-<UPC>")
    pl.add_argument("--section", help="with --cards: the section its new items go under "
                                       "(else the one chosen on the upload page, else Other)")
    pl.add_argument("--by", default="manage.py load-price-list",
                    help="the name Item history shows for the items it adds")
    pl.add_argument("--photos", action="store_true",
                    help="make a photo from the list's picture for each item that has none")
    pl.add_argument("--report", help="a JSON file to write how it went into ({ok, message})")
    pl.add_argument("--choices", help="a JSON file of what an admin chose on the upload page "
                                      "(see catalog_pricelist.load())")
    pl.set_defaults(func=cmd_load_price_list)
    rl = sub.add_parser("read-price-list")
    rl.add_argument("state", help="the price-list state, e.g. MEAT")
    rl.add_argument("file", help="a newer issue of one of the state's lists, a PDF")
    rl.add_argument("out", help="the JSON file to write what it would change into")
    rl.set_defaults(func=cmd_read_price_list)
    pp = sub.add_parser("price-list-pdf")
    pp.add_argument("state", help="the price-list state, e.g. MEAT")
    pp.add_argument("out", help="the PDF file to write")
    pp.add_argument("--prices", action="store_true", help="include the Price column")
    pp.add_argument("--only", help="only these item numbers, separated by commas")
    pp.set_defaults(func=cmd_price_list_pdf)
    au = sub.add_parser("add-user")
    au.add_argument("name")
    au.add_argument("email")
    au.add_argument("--states", required=True, help="the states this login may use: IL, FL or IL,FL")
    au.set_defaults(func=cmd_add_user)
    ss = sub.add_parser("set-states")
    ss.add_argument("email")
    ss.add_argument("states", help="IL, FL or IL,FL")
    ss.set_defaults(func=cmd_set_states)
    for name, func in (("set-password", cmd_set_password), ("remove-user", cmd_remove_user)):
        sp = sub.add_parser(name)
        sp.add_argument("email")
        sp.set_defaults(func=func)
    sub.add_parser("list-users").set_defaults(func=cmd_list_users)
    sa = sub.add_parser("set-admin")
    sa.add_argument("email")
    sa.add_argument("state", choices=["on", "off"])
    sa.set_defaults(func=cmd_set_admin)
    oe = sub.add_parser("order-email")
    oe.add_argument("state", choices=["on", "off"])
    oe.set_defaults(func=cmd_order_email)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
