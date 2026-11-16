# Satla catalog and salesman ordering site

This directory is where the site for catalog.satlaspirits.com gets built. Stages 1 (sign in, catalog, product page) and 2 (customers, order history, invoice) are live as of 2026-11-14. Stage 3 (New Order, Copy Order, the order email) and an Admin page for logins are live as of 2026-11-15, with the SENDING of order emails switched off until the owner decides which mailbox they are sent from (`manage.py order-email on` switches it on; ask him first).

## What is here
- `catalog_web.py`: the Flask site. Reads only `Catalog.db`; never calls QuickBooks or MMK. An order is never stored: it lives in the browser (`static/order.js`) until Send, which emails it through the library's `mail_send.send_mail()`. Every form posted by a signed-in person carries a `csrf` token (`form_token()` in templates).
- `catalog_db.py`: Catalog.db schema and queries (products, users with an is_admin flag and a list of allowed states, live_snapshot per state, and qbo_customers / qbo_invoices / qbo_last_prices: a read-only copy of QuickBooks customers, 12 months of invoices, and what each customer last paid for each product from all invoices, replaced by the refresh timer).
- `catalog_live.py`: the read-only QuickBooks / MMK reads, all through the library in `~/python/qbo_scripts`. It loops over the library's `STATES` table; nothing in the site names a state.
- `manage.py`: init, load-products, load-pack, refresh, add-user, set-password, remove-user, list-users, set-admin, set-states, order-email. Run with `~/python/venvs/qbo311/bin/python3 /home/dovid/python/catalog/manage.py <command>`.
- `templates/`, `static/`: pages, styles and scripts (taken from the approved wireframes). `static/common.js` holds the helpers every page script shares (escaping, search, photo box, money); do not copy them into a page script.
- `photos/grid`, `photos/detail`: 178 photos each, named `<SKU>.webp`.
- `deploy/`: service, refresh timer, Caddy site and `install.sh`. Service `catalog-web` on 127.0.0.1:5001; timer `catalog-refresh` every 30 minutes. After changing Python code or templates: `sudo systemctl restart catalog-web`.
- No new packages: it runs on the existing `qbo311` environment. Do not `pip install` into it.

## Before anything else
Session handoffs are dated files, `docs/HANDOFF-YYYY-MM-DD.md`. When the owner says "read today's handoff" (or "the latest handoff"), read the one with the newest date first (a letter after the date marks a later handoff of the same day); the newest is `docs/HANDOFF-2026-11-15b.md`. When you write a new one at the end of a session, name it the same way and update this line.

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
- Salesmen only. Illinois and Florida are kept completely apart (see "Illinois and Florida" below): a switch in the header picks the state, and each login has the states it may use.
- Kosher labels (the owner's words, 2026-11-15): "Everything we sell is Kosher. Please just have the Mevushal symbol. Also, please don't have a box saying "Kosher for Passover". Instead, make that a category filter only". No "Kosher" or "Kosher for Passover" label on a card or product page; only Mevushal (and Organic). Kosher for Passover is a menu category and a filter. "Everything except the liqour / sake is Kosher for Passover all year round. I still feel that it should be a filter, but just so you know, all wines should show up, only Alcohol should be considered Not default." (2026-11-15) Every Wine product counts as Kosher for Passover (`_kfp()` in `catalog_web.py`); other products only when the product data says Yes.
- No prices on the catalog grid. Regular price and cases on hand appear on the product page and the order screen.
- Orders are in cases only; part of a case is a decimal such as 0.5. No loose bottles.
- Order price default: the customer's previous price for that product, otherwise the regular price. The salesman can type over it; a drop-down offers Regular and Previous.
- The order is emailed to florida@satlaspirits.com with a copy to the salesman. It is not saved.
- Everything inside the wireframes other than the products, descriptions and photos is invented sample data.

## Illinois and Florida (the owner's words, 2026-11-15)
"IL and FL will maintain two separate inventory / orders / customers lists competely. We don't use MMK for FL, only QBO." "I'd love for the API to be basically the same wrapper function, but with passed in state (either FL or IL). So, if we add another state somewhere else, we can just pass in NJ." "there should be a toggle switch in the UI for either IL or FL. once we click IL, the whole catalog refreshes for IL data. I'd like to set the choice of possible States to be something I enable when creating the user." "Right now, any items already in the catalog that ALSO exist in FL should be shown in FL." "Customers obviously need to be divided up between the two states, based on their QBO entries." (Full text: functional spec section 0.)
- This replaces "one combined catalog, no state picker". Every page shows one state: `g.state` in `catalog_web.py`.
- A state's catalog is the catalog products with a record in that state's inventory system: Illinois 178, Florida 100 (active QuickBooks Florida items only).
- Florida also lists the QuickBooks Florida items that have NO catalog entry. His words (2026-11-15): "Option 3, show them in the Florida catalog - yes. This gives us an idea of what is missing." Built and live the same day: the Florida catalog lists every active QuickBooks Florida item with a SKU: 457, of which 100 are catalog products and 357 have no catalog entry. Those 357 show the QuickBooks name, bottle size, bottles per case, regular price and cases on hand, a blank photo box and a "Not in catalog" label; a "Not in catalog" menu entry lists them; they have no brand, category or filter data, so the menu and filters do not find them but search does (search now also matches the SKU). They can be ordered like any Florida product with a regular price, Copy Order includes them, and customers' previous prices cover them (Claude's reading: he asked for them to be shown; ordering what is shown was not said separately). Illinois is unchanged (178). Which state does this is the `catalog_all` flag in the library's `STATES`. The one place that builds a state's product list is `db.state_products()`.
- A customer belongs to the state whose QuickBooks company holds it.
- Allowed states are ticked per login on the Admin page. His examples: Yoel, IL and FL; Eli Stone (the KOVAL rep), IL only; Henry, FL only.
- The states live in ONE place, `STATES` in `~/python/qbo_scripts/mmk_common.py`. Adding a state is a row there; do not name a state in the site's code.

## Florida (the owner's words, 2026-11-13)
"Florida is all contained within QBO Florida, which you should also have access to." Florida quantity on hand is read from the Florida QuickBooks company.
- "Any items not in the QBO FL inventory are no longer avail" (2026-11-15) The 78 catalog products with no active QuickBooks Florida item are not shown in Florida. The QuickBooks Florida items that are not catalog products are shown too; see "Illinois and Florida".

## Satla and KOVAL (the owner's words, 2026-11-14)
"I'd like that the SATLA inventory be pulled from MMK, but the Customer LIst and Orders be pulled from QBO. I don't want any KOVAL customers or Koval Orders (all in MMK) included in the catalog."
- "KOVAL products stay in the catalog." (2026-11-14) The 29 `KOV-` products are in MMK but in neither QuickBooks company: they show on hand, have no regular price, and cannot be ordered.
- Customers and orders: QuickBooks only. KOVAL customers and orders exist only in MMK, so never read customers or orders from MMK for this site.

## Illinois and MMK (the owner's words, 2026-11-15)
"All items that have a record in MMK should be shown in the catalog. Each item there should have a corresponding record in QBO that should be the same. My point was that items in QBO that are NOT in MMK do not get shown, and QBO is a graveyard for old items."
- All 178 catalog products have a record in MMK's product list (checked 2026-11-15). A product in MMK with no stock shows 0 cases on hand.
- Never add a product to the catalog from QuickBooks alone.
- "Let's leave those out, but please keep as an OPEN ITEM a modual to quickly and easily add new items." (2026-11-15) The 13 MMK products that are not in the catalog stay out. Open item, not built: a module to quickly and easily add new items.

## Mevushal (the owner's words, 2026-11-15)
"there are many wines where the title has "(M)" or "Mevusal" but the catalog doesn't. Can you make sure that any time the title says "M" or "Mevusal" the catalog reflects that. For example: Drimia Cabernet Sauvignon MEVUSHAL". Built and live the same day: a product whose name holds "(M)" or "Mevushal" (any case, also spelled "Mevusal") is Mevushal on the card, the product page, the Mevushal menu and the filter, whatever the product data says (`mevushal()` in catalog_db.py; the data in Catalog.db and the spreadsheet is not changed). It changed 6 catalog products (I-AD109, I-AD132, I-AD40W-M, I-DR01, I-LR115, IT1751241323) and marks 96 of the Florida items that have no catalog entry.

## SKU `I-AD132` (2026-11-15)
"I-AD132 really is the Marselan. MMK has it wrong. I've asked them to update. Can you make sure it is correct in the catalog at least?" NOT DONE YET: the catalog entry under I-AD132 (name, photo, description) is the Adir November box. Claude proposed moving that entry and its photos to I-AD136 (the November box in QuickBooks) and making I-AD132 the Marselan from QuickBooks; the step was blocked by the permission system (it re-keys a product, renames it and moves photos), so it waits for his go-ahead. Until then I-AD132 still shows as Adir November, 6 per case. DONE 2026-11-15 after his "let's try again": the Adir November entry (photo, description) is now `I-AD136`, named "Adir NOVEMBER In Box" as in QuickBooks, 6 per case; `I-AD132` is a new entry "Adir Marselan Red (M)" (the QuickBooks Illinois name; Florida calls it "Adir Winemaker Edition Marselan (M)"), Adir / Wine / Red / Marselan / Israel / Galilee / Mevushal, 12 per case, no photo or description yet. Same change made in `Satla_Master_Catalog.csv`. Catalog.db now holds 179 products (178 photos). Illinois still lists 178: the Marselan shows, and Adir November does not until MMK has it under `I-AD136`. Florida lists 457: 101 catalog products and 356 without a catalog entry. Background (how it stood before the fix): "Adir November == 6" (Dovid, 2026-11-15). `I-AD132` (Adir NOVEMBER In Box MEVUSHAL) set to 6 bottles per case in Catalog.db by hand (pack_source "owner"; it was 12, taken from QuickBooks Illinois). FOUND, NOT FIXED, told him: SKU `I-AD132` is a different product in QuickBooks. MMK: "Adir NOVEMBER In Box MEVUSHAL 750/6". QuickBooks Illinois `I-AD132`: "Adir Marselan Red (M)", $432, 12 per case. QuickBooks Florida `I-AD132`: "Adir Winemaker Edition Marselan (M)", $480, 12 per case, about 19 cases. QuickBooks has the November box as `I-AD136` ($690, 6 per case; Florida also `I-AD35RM-20`). So the site shows Adir November with the Marselan's regular price, Florida stock and previous prices (11 customer prices). Refilling pack data with overwrite would put 12 back. Waiting for his decision.

## Built with (approved 2026-11-14)
Flask, gunicorn and Caddy, the same as orders.satlaspirits.com; Catalog.db is a SQLite file ("SQLLite is perfect").

## Code rule (the owner's words, 2026-11-13)
"Please make sure we are not duplicating ANY code. I have API for almost EVERYTHING, and I ALWAYS want it used. If you need to create a new API, please do so, keeping future usability in mind. Please put in the same API library as we currently have, and document the function."
- The API library is `~/python/qbo_scripts` (behind orders.satlaspirits.com): `qbo_mmk_salesorder.py` (as `qbo`), `mmk_common.py` (as `mc`), `mmk_data.py` (as `md`), `fl_sales.py`, `mail_remit.py`, `mail_send.py` (sending; added for the order email). Read its `CLAUDE.md` and the matching `.claude/rules/*.md` note before using or changing a module.
- Run it with `~/python/venvs/qbo311/bin/python3` by explicit path. Always take a QuickBooks client from `qbo.qbo_client(path)`; Florida is `~/python/config/qbo_config_fl.json`.
- Read-only QuickBooks and MMK calls are always allowed, both companies. Regular price is the `unit_price` column of `mc.get_current_inventory_qbo()` (per company; 0.0 = none set). By state (use these): `mc.get_current_inventory(state)` gives which products a state has and its cases on hand, the same columns for any state; `mc.get_regular_prices(state)` gives the regular price. They wrap `mc.get_current_inventory_mmk()` (Illinois) and `mc.get_current_inventory_qbo()` (Florida).
- `sudo systemctl restart mmk-web` is needed after changing any module the orders site imports; ask the owner first.

## Open questions that block Stage 2 and Stage 3
Ask the owner; do not assume:
- How is MMK read automatically? No method is settled.
- Which mailbox are order emails sent FROM? Asked 2026-11-15; the owner's reply: "Let's just move on from that for now. I asked for florida@satlaspirits.com" (the order goes TO that address; the sender is not decided). Do not switch sending on, and do not send a test email to florida@satlaspirits.com, without his say-so.

## Admin (the owner's words, 2026-11-15)
"Can you make sure I'm an ADMIN?" He chose: manage logins on the site. `/admin/users` (admins only): add a login, set a password, switch a login off or on, give or remove admin rights. Product data is still loaded by hand.

## Working with the owner
- Record what he says about data and rules in his own words. Do not generalize a short answer; if it could cover several things, ask which.
- Check the documents before asking him something. He does not want to repeat a decision.
- Plain language, conclusion first. Real paths in commands, never placeholders.

## Keeping the documents in step
The masters live in the owner's Claude Project named "Catalog". The copies in `docs/` are working copies. When a decision changes, update the copy here with a version bump and a change-log row, and tell the owner so the Project copy can be updated too.
