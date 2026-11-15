# Satla Catalog — Build Plan for the Current Release

Version 0.10 — 2026-11-14 — Draft for Dovid's review. Nothing here has been built. No production code exists yet.

## How to use this document
- This is the staged plan for building the current release: what gets built in what order, what each stage depends on, and what "done" means for each.
- It follows the two specs and never overrides them: claude/satla-catalog-data-model.md (master spec) and claude/satla-functional-spec.md (what the release does; its section 0 holds the latest decisions). The screens are in claude/satla-wireframes.html.
- Same rule as the specs: any change to the plan is written here in full in the same turn, with a new version and a change-log row.
- Items marked DECISION are Dovid's to make. Items marked ASSUMED were filled in by Claude because the question was not answered; they are not agreed.
- The project is in test mode (Dovid, 2026-11-12): no product renames, no changes to QuickBooks or MMK data.

## 1. What this release is
One website for salesmen, behind a login, with three functions:
1. Product catalog without prices: search, the agreed menu and filters, and a product page.
2. Customer lookup with order history.
3. New Order from the customer page, sent as an email.

Ground rules that shape the build:
- WHERE DATA LIVES (Dovid, 2026-11-13 14:37, verbatim): "QBO will be read for invoicing. MMK will be read for QTY on HAND. Our Catalog.db will hold all the item data." This replaces the v0.2 wording that the site reads only the shared database.
- Nothing is written to QuickBooks or MMK in this release.
- No admin screens. Salesman logins and product data are loaded by hand behind the scenes.
- Phone first: every screen has to work at phone width.
- Host: the existing DigitalOcean droplet (master spec section 2).

## 2. Where each piece of data comes from
Rows marked (to confirm) were not covered by Dovid's statement.

| Data | Comes from | Used for |
|---|---|---|
| Products: names, descriptions, filter fields | claude/Satla_Master_Catalog.csv, loaded once into the site's own database | Catalog, product page, New Order product list |
| Product photos | The standardized set from the photo job (grid 600x800, detail 900x1200), copied to the droplet | Catalog, product page, New Order |
| Bottles per case, bottle size (ml) | Catalog.db (item data; the values exist today in QuickBooks and MMK) | Product page |
| Regular price per case, per state | Read from QuickBooks (Dovid, 2026-11-13: "Regular price - Read from QBO"); the item UnitPrice | Product page; default price on New Order |
| Cases on hand | Illinois: read from MMK. Florida: read from the Florida QuickBooks company (Dovid, 2026-11-13) | Product page; New Order lines |
| Customers: name, address, contact, balance | QuickBooks, both companies | Customer list and customer page |
| Invoices with line items, last 12 months | QuickBooks, both companies | Order history |
| Previous price per customer and product | QuickBooks invoices (the most recent one containing the product) | Default price on New Order |
| Salesman logins | The site's own database, entered by hand | Sign in |

## 3. Stages
Each stage ends with something Dovid can open on his phone and check. A stage is not done until every line under "Done means" is true.

### Stage 0 — Checks and decisions before any code
Purpose: remove the unknowns that would otherwise surface halfway through the build.

Work:
- QuickBooks field check on the droplet, read only, for BOTH companies: confirm where the regular price, bottles per case and bottle size sit on an item; confirm the invoice line fields (item, quantity, price) and that quantity is in cases; confirm the droplet can read the Florida company as well as the Illinois one.
- Copy the standardized photos (grid and detail) from the Mac mini to the droplet.
- Settle the DECISIONS in section 5.

Depends on: nothing.

Done means:
- A short written report of the QuickBooks fields exists and is recorded in the master spec.
- Both QuickBooks companies can be read from the droplet without disturbing the existing order scripts.
- The photo files are on the droplet and the file count matches (178 grid, 178 detail).
- Every DECISION in section 5 has an answer recorded in the specs.

Dovid's part: answer the decisions; run the two Claude Code briefs (QuickBooks field check on the droplet, photo copy from the Mac mini).

### Stage 1 — Sign in and catalog (Function 1)
Scope: wireframe screens 1, 2 and 3.
- Sign in for salesmen. No sign-up.
- The site's own database, loaded from the catalog file (178 products).
- Catalog: search, browse menu, filters, product cards with the standardized photos.
- Product page with every product field, bottles per case, and for each state the regular price per case and cases on hand.
- Catalog.db filled with the item data, and the read of quantity on hand from MMK.

Depends on: Stage 0 (photos on the droplet; where bottles per case sits in QuickBooks).

Done means:
- A salesman can sign in on a phone and cannot see anything without signing in.
- All 178 products appear, each with its standardized photo; no broken images.
- Search finds products by name, brand, grape, country and region.
- Every menu item and every filter behaves as in the wireframes, and the product counts match the catalog file.
- The product page shows every field in the functional spec, plus bottles per case, regular price and cases on hand for each state, and the on-hand figure matches MMK.
- No price appears on the catalog grid.
- It is usable at phone width and at laptop width.

### Stage 2 — Customers and order history (Function 2)
Scope: wireframe screens 4, 5 and 6.
- Customer list from both QuickBooks companies, with search and the All / Illinois / Florida switch.
- Customer page: name, address and contact, balance owed.
- Order history: QuickBooks invoices for the last 12 months, newest first; each opens to its line items.

Depends on: Stage 0 (QuickBooks read for both companies), Stage 1 (sign in).

Done means:
- Every salesman sees all customers from both companies.
- A customer's page matches what QuickBooks shows for that customer: address, contact, balance.
- The invoice list matches QuickBooks for the last 12 months, and each invoice's lines and total match QuickBooks.
- Nothing on these screens can change anything in QuickBooks.
- Dovid has spot-checked at least five customers in each state against QuickBooks.

### Stage 3 — New Order by email (Function 3, version A)
Scope: wireframe screens 7, 8 and 9.
- New Order starts from the customer page.
- Product list with search and category chips.
- Quantity in cases only; part of a case is a decimal such as 0.5.
- Price per case: starts at the customer's previous price for that product if there is one, otherwise the regular QuickBooks price; the salesman can type over it; a drop-down beside it offers Regular and Previous.
- A product that is not in the customer's QuickBooks company has no regular price and cannot be added.
- Copy Order: a button on a past invoice that starts a new order with the same products and quantities, opening on the review screen (details to confirm; functional spec section 0).
- Review screen with an optional note to the office.
- Send: one email to florida@satlaspirits.com with a copy to the salesman; then a confirmation screen showing what was sent.
- The order is not saved. Leaving an order with lines on it asks before discarding.

Depends on: Stages 1 and 2; the DECISION on how the site sends email.

Done means:
- For a test customer, the default price on every product matches the rule: previous price when QuickBooks has a past invoice for it, regular price when it does not. Dovid has checked at least ten products by hand against QuickBooks.
- The drop-down switches between Regular and Previous, and a typed price is kept.
- Copy Order on a past invoice produces a new order with the same products and quantities, priced by the usual rule, and sends nothing until Send order is pressed.
- The email arrives at florida@satlaspirits.com and at the salesman's address, and lists customer, state, salesman, each line (SKU, product, size, cases, price per case and whether it is the regular, previous or a typed price, line total), the order total and the note.
- The office can enter an order into QuickBooks from the email alone, without calling the salesman.
- A whole order can be placed one-handed on a phone.

### Stage 4 — Pilot
Scope: real use by one or two salesmen for real orders, alongside the way orders are placed today.

Done means:
- At least ten real orders have gone through the site and been entered into QuickBooks by the office.
- Every problem found is written down and either fixed or deliberately deferred.
- Dovid says it is ready for the rest of the sales team.

## 4. Not in this plan (later stages, already recorded in the specs)
- Version B of ordering: inserting the order into QuickBooks instead of emailing it.
- Showing license numbers and assigned reps; syncing license numbers between MMK and QuickBooks.
- The daily MMK / QuickBooks / catalog check and mismatch report.
- Public catalog, state picker, trade buyer logins, prices in the catalog.
- Admin screens, promotions and special terms, sell sheets, Encompass.
- Replacing the 15 photos marked NEEDS NEW PHOTO and answering the 5 label questions (waiting for the manager's review).

## 5. Decisions and assumptions
DECISIONS still needed from Dovid:
1. Four points Dovid's data statement did not cover: (a) are customers read from QuickBooks along with invoicing; (b) is the regular price item data in Catalog.db or read from QuickBooks; (c) ANSWERED 2026-11-13: Florida's quantity on hand is read from the Florida QuickBooks company ("Florida is all contained within QBO Florida, which you should also have access to."); (d) are QuickBooks and MMK read at the moment a screen opens, or on a schedule. Also still unsettled: the method for reading MMK automatically (master spec section 5A).
2. How the site sends the order email, and from which address it appears to come.
3. ANSWERED 2026-11-13: the web address is catalog.satlaspirits.com, which already resolves to the VPS (the droplet). Dovid also has Claude Code set up on the VPS in its own directory, ready for the build.
4. Who the first salesmen are (names and email addresses for their logins), and who pilots it.
5. What it is built with. The master spec fixes the host (the droplet) but not the tools. This is a choice to make with whoever writes the code, before Stage 1.

ASSUMED by Claude because the question was not answered on 2026-11-13 (change any of these and the plan changes with it):
- Assigned rep: left off the customer page in this release.
- License number: left off the customer page in this release.
- New Arrivals: stays in the menu but shows no products until a rule is decided; it is not part of any "Done means" above.
- "Previous price" means the most recent invoice for that customer containing the product, however old.

STAGE 0 PROGRESS, 2026-11-13:
- STAGE 0 CHECK DONE 2026-11-13 (read-only, through the existing library: qbo.qbo_client, mc.get_current_inventory_qbo, mc.get_current_inventory_mmk): both QuickBooks companies are readable from the VPS (Illinois 546 items, Florida 477). Of the 178 catalog SKUs: 148 are in Illinois QuickBooks, 100 in Florida QuickBooks (all 100 are also in Illinois), 30 are in neither (almost all KOVAL KOV- SKUs, plus I-AD02R-23 and a few others); 128 are in stock at MMK. Bottles per case and ml are parsed by the library from the QuickBooks item description and were known for every catalog SKU found. The regular price is the QuickBooks item UnitPrice (filled on 98 of 100 sampled Illinois items and 94 of 100 Florida). The orders site uses Flask, gunicorn and Caddy and has NO database (config files only), so SQLite for Catalog.db is new on this server — to confirm with Dovid.
- DOVID'S ANSWERS TO CLAUDE CODE ON THE VPS, 2026-11-13 (evening), VERBATIM: (a) what to build with (Flask, SQLite, Caddy proposed): "As long as it's what's being used on the orders.satlaspirits.com website." (b) "Yes, read-only qbo / mmk is always OK, both IL & FL". (c) "Regular price - Read from QBO". (d) "Customers - no from MMK" — AMBIGUOUS (customers read from MMK instead of QuickBooks, or not from MMK); re-asked, NOT decided. (e) "On Hand - MMK / Prices  Idon't know all this." — on hand is read from MMK; whether reads happen when a screen opens or on a schedule was left to Claude Code, which will use a short cache with an "as of" time (Claude Code's choice, to confirm). (f) reuse mmk_data.py for the MMK read: "yes, mmk_data.py". (g) CODE RULE: "Please make sure we are not duplicating ANY code. I have API for almost EVERYTHING, and I ALWAYS want it used. If you need to create a new API, please do so, keeping future usability in mind. Please put in the same API library as we currently have, and document the function." The API library is ~/python/qbo_scripts (the code behind orders.satlaspirits.com). 
- Still to do in Stage 0: copy the detail photos; settle customers source, SQLite, email sending, salesman list.

- SATLA vs KOVAL (Dovid, 2026-11-14, VERBATIM): "we have two sources of everything. Mainly, in IL, SATLA is the parent company, but that's broken down into SATLA and KOVAL orders and customers. MMK has the orders for both divisions, and all the products and inventory both divisisons share. However, KOVAL orders and customers are NOT part of the Satla catalog." and "I'd like that the SATLA inventory be pulled from MMK, but the Customer LIst and Orders be pulled from QBO. I don't want any KOVAL customers or Koval Orders (all in MMK) included in the catalog." This settles the customers question ("Customers - no from MMK" meant: not from MMK): customers and orders are read from QuickBooks; inventory from MMK. Because KOVAL customers and orders exist only in MMK and never in QuickBooks (existing library notes: the KOVAL channel is salesman Eli Stone, no QuickBooks invoice by design), reading customers and orders only from QuickBooks leaves them out with no extra filter. OPEN, asked 2026-11-14: whether KOVAL PRODUCTS (the KOV- SKUs in the 178-product file) stay in the catalog. They are in MMK inventory but not in either QuickBooks company, so they have no regular price and cannot be ordered under the existing rule.

- DECIDED by Dovid 2026-11-14, VERBATIM: "KOVAL products stay in the catalog. SQLLite is perfect. Please add price column." So: the 29 KOV- products stay in the catalog (they are in MMK inventory but in neither QuickBooks company, so they show on hand but have no regular price and cannot be ordered under the existing rule); Catalog.db is a SQLite file; the regular price is now returned by the existing library function mc.get_current_inventory_qbo() as the column unit_price (added and documented in ~/python/qbo_scripts/mmk_common.py on 2026-11-14; per company; 0.0 means no price set). Checked live: all 149 Illinois and all 101 Florida catalog items have a price above zero. Decision 5 (what it is built with) is ANSWERED: Flask, gunicorn and Caddy as on orders.satlaspirits.com, with SQLite for Catalog.db.

- STAGE 1 BUILT 2026-11-14 (Claude Code on the VPS), not yet live: sign in, catalog and product page, in /home/dovid/python/catalog (catalog_web.py, catalog_db.py, catalog_live.py, manage.py, templates/, static/, deploy/). Built with Flask and gunicorn from the existing qbo311 environment (nothing new installed), SQLite Catalog.db, Caddy. Catalog.db holds the 178 products (bottles per case and ml filled for 177; unknown for I-AD02R-23), the salesman logins (hashed passwords), and a snapshot of the last read of prices and on hand. All QuickBooks and MMK reads go through the existing library (mc.get_current_inventory_qbo, mc.get_current_inventory_mmk); the web pages read only Catalog.db. CHOICES MADE BY CLAUDE CODE, to confirm with Dovid: (1) prices and on hand are re-read every 30 minutes by a timer and each figure shows its "as of" time; (2) the refresh never triggers an MMK login, so when the saved MMK login has lapsed the page keeps the last known Illinois on hand and says so; (3) a product with no QuickBooks price in a state shows "No price in QuickBooks" (the 29 KOVAL products show this in both states); (4) Illinois on hand shows 0 when MMK does not list the product as in stock; (5) the Customers tab is left off until Stage 2. Tested locally in a headless browser at phone and laptop width. Going live needs deploy/install.sh (system service, refresh timer, Caddy site), which Dovid has to run or approve, and at least one salesman login (manage.py add-user).

## 6. Risks
| Risk | Why it matters | How the plan handles it |
|---|---|---|
| The droplet's QuickBooks connection is shared with the existing order scripts | Breaking it would stop today's order flow | Stage 0 confirms the new reads do not disturb the existing scripts before anything is built |
| The droplet may only be connected to one QuickBooks company | Customers and prices are needed from both | Checked in Stage 0 |
| Quantity on hand is read from MMK | There is no settled automatic way to read MMK yet | Stage 0 settles the method; until it works, on hand shows as unavailable |
| A figure can be older than it looks | A salesman could see stock that has since sold | Every stock figure shows its "as of" time |
| Invoice quantities may not always be in cases | A previous "price" could be per bottle on old invoices | Stage 0 field check; Stage 3 hand check of ten products |
| The droplet is small (1 GB of memory) | It already runs the QuickBooks scripts | Watch memory in Stage 1; resizing the droplet is a known option |
| 15 products have photos flagged as too small or wrong | They will look weaker than the rest | Accepted for the build-out phase at Dovid's instruction |
| One combined catalog with no state tags | A salesman can browse products his customer's state does not carry | The no-regular-price rule in Stage 3 stops such a product being ordered |

## Change log
- 2026-11-14 — v0.10 — (VPS working copy.) Stage 1 built and tested locally; not yet live. Choices made by Claude Code listed in section 5 for Dovid to confirm.
- 2026-11-14 — v0.9 — (VPS working copy.) Decision 5 answered (Flask, gunicorn, Caddy, SQLite); KOVAL products stay; price column added to the library.
- 2026-11-14 — v0.8 — (VPS working copy.) Decision 1(a) answered: customers and orders are read from QuickBooks; no KOVAL customers or orders. Open: KOVAL products.
- 2026-11-13 — v0.7 — (VPS working copy.) Regular price source answered; Stage 0 read check done and recorded in section 5; code-reuse rule recorded.
- 2026-11-13 — v0.6 — (Edited in the VPS working copy.) Decision 1(c) answered by Dovid: "Florida is all contained within QBO Florida, which you should also have access to." Florida on hand is read from the Florida QuickBooks company.
- 2026-11-13 — v0.5 — Decision 3 answered: catalog.satlaspirits.com already points at the VPS; Claude Code is set up there in its own directory. A handoff package (specs, plan, wireframes with photos, catalog file, CLAUDE.md) was prepared for that directory.
- 2026-11-13 — v0.4 — Copy Order added to Stage 3.
- 2026-11-13 — v0.3 — Corrected to Dovid's statement: QuickBooks read for invoicing, MMK read for quantity on hand, Catalog.db holds all item data. v0.2's "reads only the shared database" withdrawn. Decision 1 now lists the four points not covered.
- 2026-11-13 — v0.2 — Reworked around Dovid's governing principle: the site reads only the shared database, which stores all information; QuickBooks and MMK are load sources. Added regular price and cases on hand per state to the product page and on hand to order lines. Decision 1 is now about load frequency and the MMK load method.
- 2026-11-13 — v0.1 — First draft, written after Dovid set the order price rule and confirmed orders are in cases only.
