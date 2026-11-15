# Satla catalog and salesman ordering site

This directory is where the site for catalog.satlaspirits.com gets built. Stage 1 (sign in, catalog, product page) was built 2026-11-14; Stages 2 and 3 are not built.

## What is here (Stage 1)
- `catalog_web.py`: the Flask site. Reads only `Catalog.db`; never calls QuickBooks or MMK.
- `catalog_db.py`: Catalog.db schema and queries (products, users, live_snapshot).
- `catalog_live.py`: the read-only QuickBooks / MMK reads, all through the library in `~/python/qbo_scripts`.
- `manage.py`: init, load-products, load-pack, refresh, add-user, set-password, remove-user, list-users. Run with `~/python/venvs/qbo311/bin/python3 /home/dovid/python/catalog/manage.py <command>`.
- `templates/`, `static/`: pages, styles and the catalog script (taken from the approved wireframes).
- `photos/grid`, `photos/detail`: 178 photos each, named `<SKU>.webp`.
- `deploy/`: service, refresh timer, Caddy site and `install.sh`. Service `catalog-web` on 127.0.0.1:5001; timer `catalog-refresh` every 30 minutes. After changing Python code or templates: `sudo systemctl restart catalog-web`.
- No new packages: it runs on the existing `qbo311` environment. Do not `pip install` into it.

## Before anything else
Read `docs/HANDOFF.md` in full. It holds everything the owner and the design Claude agreed: where data lives, what is in this directory, what is missing and where it is, every screen and rule, which decisions are settled and which are open, and how to work with the owner. Then read the three specs it points to and open `wireframes/index.html`.

Do not write code until the owner has approved what to build it with and a plan for Stage 0 and Stage 1.

## What is being built
An internal website for Satla Spirits salesmen, behind a login. Three functions: a product catalog, customer lookup with order history, and New Order from the customer page, sent as an email. It is not an outward-facing site.

## Where data lives (the owner's words, 2026-11-13)
"QBO will be read for invoicing. MMK will be read for QTY on HAND. Our Catalog.db will hold all the item data."

## Hard limits
- Never write to QuickBooks or MMK. This release only reads them.
- Do not modify, move or delete EXISTING code or data under `~/python` (additive, documented API functions in `~/python/qbo_scripts` are the one exception; see "Code rule"). The existing QuickBooks order scripts live there and own the QuickBooks token chain; breaking it stops the business's order flow. Ask before reusing that connection.
- Test mode: do not rename products or change product names anywhere.
- Build only what is in the current release. `docs/HANDOFF.md` section 11 lists what is out.
- The server is small (1 GB of memory). Choose tools accordingly.

## Rules of the release, in brief
- Salesmen only. One combined catalog of 178 products; no state picker.
- No prices on the catalog grid. Regular price and cases on hand appear on the product page and the order screen.
- Orders are in cases only; part of a case is a decimal such as 0.5. No loose bottles.
- Order price default: the customer's previous price for that product, otherwise the regular price. The salesman can type over it; a drop-down offers Regular and Previous.
- The order is emailed to florida@satlaspirits.com with a copy to the salesman. It is not saved.
- Everything inside the wireframes other than the products, descriptions and photos is invented sample data.

## Florida (the owner's words, 2026-11-13)
"Florida is all contained within QBO Florida, which you should also have access to." Florida quantity on hand is read from the Florida QuickBooks company.

## Satla and KOVAL (the owner's words, 2026-11-14)
"I'd like that the SATLA inventory be pulled from MMK, but the Customer LIst and Orders be pulled from QBO. I don't want any KOVAL customers or Koval Orders (all in MMK) included in the catalog."
- "KOVAL products stay in the catalog." (2026-11-14) The 29 `KOV-` products are in MMK but in neither QuickBooks company: they show on hand, have no regular price, and cannot be ordered.
- Customers and orders: QuickBooks only. KOVAL customers and orders exist only in MMK, so never read customers or orders from MMK for this site.

## Built with (approved 2026-11-14)
Flask, gunicorn and Caddy, the same as orders.satlaspirits.com; Catalog.db is a SQLite file ("SQLLite is perfect").

## Code rule (the owner's words, 2026-11-13)
"Please make sure we are not duplicating ANY code. I have API for almost EVERYTHING, and I ALWAYS want it used. If you need to create a new API, please do so, keeping future usability in mind. Please put in the same API library as we currently have, and document the function."
- The API library is `~/python/qbo_scripts` (behind orders.satlaspirits.com): `qbo_mmk_salesorder.py` (as `qbo`), `mmk_common.py` (as `mc`), `mmk_data.py` (as `md`), `fl_sales.py`, `mail_remit.py`. Read its `CLAUDE.md` and the matching `.claude/rules/*.md` note before using or changing a module.
- Run it with `~/python/venvs/qbo311/bin/python3` by explicit path. Always take a QuickBooks client from `qbo.qbo_client(path)`; Florida is `~/python/config/qbo_config_fl.json`.
- Read-only QuickBooks and MMK calls are always allowed, both companies. Regular price is the `unit_price` column of `mc.get_current_inventory_qbo()` (per company; 0.0 = none set). On hand: Illinois `mc.get_current_inventory_mmk()`, Florida `mc.get_current_inventory_qbo()`.
- `sudo systemctl restart mmk-web` is needed after changing any module the orders site imports; ask the owner first.

## Open questions that block Stage 2 and Stage 3
Ask the owner; do not assume:
- How is MMK read automatically? No method is settled.

## Working with the owner
- Record what he says about data and rules in his own words. Do not generalize a short answer; if it could cover several things, ask which.
- Check the documents before asking him something. He does not want to repeat a decision.
- Plain language, conclusion first. Real paths in commands, never placeholders.

## Keeping the documents in step
The masters live in the owner's Claude Project named "Catalog". The copies in `docs/` are working copies. When a decision changes, update the copy here with a version bump and a change-log row, and tell the owner so the Project copy can be updated too.
