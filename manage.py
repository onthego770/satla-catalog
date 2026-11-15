#!/usr/bin/env python3
"""Behind-the-scenes commands for the catalog site. (Logins can also be managed
by an admin on the site's Admin page.)

Run with the library's Python, by explicit path:

  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py init
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py load-products
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py load-pack
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py refresh
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py add-user "Full Name" name@example.com
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py set-password name@example.com
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py remove-user name@example.com
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py list-users
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py set-admin name@example.com on
  ~/python/venvs/qbo311/bin/python3 ~/python/catalog/manage.py order-email on

init           Create Catalog.db and the site's secret key. Safe to re-run.
load-products  Load / update the products from Satla_Master_Catalog.csv. Product
               names are taken as they are (test mode: nothing is renamed).
load-pack      Fill bottles per case and ml from QuickBooks and MMK (read-only).
refresh        Read regular prices and on hand from QuickBooks and MMK (read-only)
               into the snapshot the pages show. A timer runs this every 30 minutes.
set-admin      Give (on) or take away (off) a login's admin rights: the Admin page.
order-email    Switch the sending of New Order emails on or off. While it is off,
               Send order shows the email it would send and sends nothing. The
               email goes out from the mailbox in ~/python/config/mail_config.json
               through the library's mail_send.send_mail().
add-user       Create a salesman login. The password is typed at a hidden prompt;
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


def cmd_load_products(_args):
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
    extra = sorted(db.skus(con) - seen)
    con.close()
    print(f"{len(seen)} products loaded from {CSV_PATH.name}")
    if extra:
        print(f"note: {len(extra)} products are in Catalog.db but not in the file "
              f"(left as they are): {', '.join(extra)}")


def cmd_load_pack(args):
    import catalog_live
    missing = catalog_live.load_pack(overwrite=args.overwrite)
    if missing:
        print("unknown:", ", ".join(missing))


def cmd_refresh(_args):
    import catalog_live
    catalog_live.refresh()


def _ask_password():
    while True:
        pw = getpass.getpass("Password: ")
        if len(pw) < MIN_PASSWORD:
            print(f"At least {MIN_PASSWORD} characters.")
            continue
        if pw == getpass.getpass("Again: "):
            return pw
        print("The two did not match.")


def cmd_add_user(args):
    email = args.email.strip().lower()
    con = db.connect()
    if db.user_by_email(con, email):
        sys.exit(f"{email} already has a login. Use set-password to change it.")
    pw = _ask_password()
    db.add_user(con, args.name, email, generate_password_hash(pw))
    print(f"login created for {args.name} <{email}>")


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
              f"{'ADMIN' if r['is_admin'] else '':<5}  since {r['created_at'][:10]}")


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
    sub.add_parser("load-products").set_defaults(func=cmd_load_products)
    lp = sub.add_parser("load-pack")
    lp.add_argument("--overwrite", action="store_true", help="replace values already filled")
    lp.set_defaults(func=cmd_load_pack)
    sub.add_parser("refresh").set_defaults(func=cmd_refresh)
    au = sub.add_parser("add-user")
    au.add_argument("name")
    au.add_argument("email")
    au.set_defaults(func=cmd_add_user)
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
