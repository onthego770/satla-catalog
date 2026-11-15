# Satla Catalog — Functional Spec (business functionality)

Version 0.16 — 2026-11-15 — Draft

## How to use this document
- This doc describes WHAT the application does for its users, release by release. The data behind it is in claude/satla-catalog-data-model.md (read that first; it is the master spec).
- Same rule as the master spec: any decision about functionality is written here in full in the same turn, with a new version and a change-log row.
- Items marked OPEN have not been decided by Dovid. Do not treat them as agreed.
- Items marked "APPROVED 2026-11-12" were first put into the wireframes by Claude as proposals; Dovid approved all of them on 2026-11-12, so they are decided.
- The project is in TEST-MODE / build-out phase (Dovid, 2026-11-12): do not rename products or change names anywhere; data questions wait for the manager's review.
- Wireframes for this release: claude/satla-wireframes.html in this Project (clickable, annotated; source of the published wireframe page). They must always match this doc.

## 0. Latest decisions (2026-11-13) — these OVERRIDE anything below that conflicts
- ADMIN (Dovid, 2026-11-15, VERBATIM: "ok, user made. Can you make sure I'm an ADMIN? Also, let's go to Stage 3"). Asked what an admin should be able to do, he chose "Manage logins on the site". So: a login can be an admin; an admin has an Admin tab with a Logins page (add a login, set a password, switch a login off or on, give or remove admin rights). Dovid's own login is an admin. This REPLACES "Admin: none in this release" in section 5 for logins only; product changes are still made by hand behind the scenes.
- ORDER EMAIL SENDER — OPEN. Asked 2026-11-15 which mailbox the order email is sent FROM (a satlaspirits.com mailbox, or the login already on the server for reading remittance email). Dovid's reply, VERBATIM: "Let's just move on from that for now. I asked for florida@satlaspirits.com". Read as: the order goes TO florida@satlaspirits.com, as already decided; the sender is not decided. Stage 3 is built with sending switched OFF until he decides (build plan v0.12).
- COPY ORDER as built 2026-11-15: as proposed below, and a line whose product is not one of the catalog products is also left out and named (the catalog products are the only things that can be ordered).
- DECIDED by Dovid 2026-11-14, VERBATIM: "KOVAL products stay in the catalog. SQLLite is perfect. Please add price column." So: the 29 KOV- products stay in the catalog (they are in MMK inventory but in neither QuickBooks company, so they show on hand but have no regular price and cannot be ordered under the existing rule); Catalog.db is a SQLite file; the regular price is now returned by the existing library function mc.get_current_inventory_qbo() as the column unit_price (added and documented in ~/python/qbo_scripts/mmk_common.py on 2026-11-14; per company; 0.0 means no price set). Checked live: all 149 Illinois and all 101 Florida catalog items have a price above zero.
- SATLA vs KOVAL (Dovid, 2026-11-14, VERBATIM): "we have two sources of everything. Mainly, in IL, SATLA is the parent company, but that's broken down into SATLA and KOVAL orders and customers. MMK has the orders for both divisions, and all the products and inventory both divisisons share. However, KOVAL orders and customers are NOT part of the Satla catalog." and "I'd like that the SATLA inventory be pulled from MMK, but the Customer LIst and Orders be pulled from QBO. I don't want any KOVAL customers or Koval Orders (all in MMK) included in the catalog." This settles the customers question ("Customers - no from MMK" meant: not from MMK): customers and orders are read from QuickBooks; inventory from MMK. Because KOVAL customers and orders exist only in MMK and never in QuickBooks (existing library notes: the KOVAL channel is salesman Eli Stone, no QuickBooks invoice by design), reading customers and orders only from QuickBooks leaves them out with no extra filter. OPEN, asked 2026-11-14: whether KOVAL PRODUCTS (the KOV- SKUs in the 178-product file) stay in the catalog. They are in MMK inventory but not in either QuickBooks company, so they have no regular price and cannot be ordered under the existing rule.
- DOVID'S ANSWERS TO CLAUDE CODE ON THE VPS, 2026-11-13 (evening), VERBATIM: (a) what to build with (Flask, SQLite, Caddy proposed): "As long as it's what's being used on the orders.satlaspirits.com website." (b) "Yes, read-only qbo / mmk is always OK, both IL & FL". (c) "Regular price - Read from QBO". (d) "Customers - no from MMK" — AMBIGUOUS (customers read from MMK instead of QuickBooks, or not from MMK); re-asked, NOT decided. (e) "On Hand - MMK / Prices  Idon't know all this." — on hand is read from MMK; whether reads happen when a screen opens or on a schedule was left to Claude Code, which will use a short cache with an "as of" time (Claude Code's choice, to confirm). (f) reuse mmk_data.py for the MMK read: "yes, mmk_data.py". (g) CODE RULE: "Please make sure we are not duplicating ANY code. I have API for almost EVERYTHING, and I ALWAYS want it used. If you need to create a new API, please do so, keeping future usability in mind. Please put in the same API library as we currently have, and document the function." The API library is ~/python/qbo_scripts (the code behind orders.satlaspirits.com). 
- FLORIDA (Dovid, 2026-11-13, to Claude Code on the VPS, VERBATIM): "Florida is all contained within QBO Florida, which you should also have access to." So Florida quantity on hand is read from the Florida QuickBooks company (MMK stays Illinois only). This closes point (3) of the NOT STATED list below. A read of the Florida company from the VPS has not been tested yet.
- COPY ORDER (requested by Dovid 2026-11-13 14:53: "add a feature where we can click Copy Order"). Claude's reading, TO CONFIRM: a button on a past order (the invoice screen) that starts a New Order for the same customer with the same products and quantities. PROPOSED details: quantities are copied but prices are not — each line takes the usual default (previous price, otherwise regular) and can be changed; a product that can no longer be ordered is left out and the salesman is told; the copy opens on the Review order screen so it can be adjusted, and nothing is sent until Send order is pressed. The button is on the invoice screen only, not on each row of the history list. (The other possible meaning, copying an order's text to the clipboard, was not built.)
- WHERE EACH KIND OF DATA LIVES (corrected by Dovid 2026-11-13 14:37; replaces the v0.9 "reads only the shared database" principle, which was Claude's over-reading):
  - Dovid's statement, 2026-11-13 14:37, VERBATIM: "QBO will be read for invoicing. MMK will be read for QTY on HAND. Our Catalog.db will hold all the item data."

  | Kind of data | Where it lives |
  |---|---|
  | All item data (the product record: names, descriptions, photos, filter fields, bottles per case, ml and the rest) | Catalog.db, our own database |
  | Invoicing (invoices; used for order history and for a customer's previous prices) | Read from QuickBooks |
  | Quantity on hand | Read from MMK |

  - This REPLACES what Claude recorded a few minutes earlier (master spec v0.26 / functional spec v0.9 / build plan v0.2): "the application reads only the shared database; no direct reads of MMK or QuickBooks". That was an over-reading of Dovid's "We are going to store ALL info in our shared database" — he meant all ITEM info. QuickBooks and MMK ARE read.
  - NOT STATED by Dovid, so NOT decided — ask, do not assume: (1) customers (name, address, contact, balance): presumably read from QuickBooks with the invoicing; (2) the regular (standard) price per case: Dovid earlier said it is "in the INV table in QBO"; whether it is also item data held in Catalog.db is not stated; (3) Florida quantity on hand: MMK covers Illinois only; (4) whether "read" means at the moment a screen opens or on a schedule.
  - Instruction to any chat: record Dovid's statements about where data lives in his own words and do not extend them. Three corrections in one day (v0.20 to v0.27) came from Claude generalizing short answers.

- PRICE AND STOCK ON THE PRODUCT PAGE (decided by Dovid 2026-11-13): this is not an outward-facing website, so the product page shows, per state, the regular (standard) price per case and cases on hand. In Illinois MMK is the inventory master. The catalog grid still shows no prices. Each New Order line also shows cases on hand for the customer's state, as information only (does not block the order; PROPOSED detail). This replaces "catalog without pricing" for the product page.
- CASES ONLY (decided by Dovid 2026-11-13 12:00): "We don't sell loose bottles. If someone orders 1/2 case, we just put QTY .5 or something. This is B2B Wholesale." Orders are entered in CASES only; part of a case is a decimal quantity (0.5). There is no bottles quantity and no bottle price. This supersedes "adds products with cases and bottles" below and closes the loose-bottle pricing question. Price is per case.
- Not answered by Dovid on 2026-11-13, so ASSUMED by Claude for now (see claude/satla-build-plan.md section 5): assigned rep and license number stay off the customer page; New Arrivals stays in the menu showing no products; "previous price" = most recent invoice of any age.
- Build plan written 2026-11-13: claude/satla-build-plan.md.
- BOTTLES PER CASE — CORRECTED by Dovid 2026-11-13 (11:34): "Bottles / case and ML is of course in QBO, and MMK, and will be in the shared database." So bottles per case and bottle size (ml) DO exist in QuickBooks and in MMK, and the catalog's own (shared) database will hold them too. Bottles per case is SHOWN on the product page, read from QuickBooks, as first decided on 2026-11-12. Every line in this doc or the master spec saying bottles per case is not in QuickBooks, or is left off the product page, is WRONG and superseded. (Claude had misread Dovid's earlier "None of these exist in QBO!" as covering bottles per case.)
- Because of that misreading, the other two items from the same message are UNVERIFIED and must be re-asked, not assumed: whether the assigned rep exists in QuickBooks, and where license numbers are today.
- ORDER-SCREEN PRICE RULE (decided by Dovid 2026-11-13). There is no separate pricing table per customer. For each product on a New Order:
  1. The default is the REGULAR price: the product's price in the QuickBooks item list ("catalog pricing, which is in the INV table in QBO").
  2. If that customer has bought the product before, the price they paid the last time ("PREV price", taken from their past orders in QuickBooks) REPLACES the regular price as the default.
  - Dovid's example: Rosé is $140 a case in QuickBooks, so $140 is the default; a customer who bought it before at $130 gets $130 as the default.
  - On screen: "Price" is a text field filled with the previous price (or the regular price when there is none), with a drop-down next to it offering the Regular price and the Previous price.
  - The price field can be typed over by the salesman. This SUPERSEDES the "prices are read-only" detail approved on 2026-11-12.
  - This supersedes the 2026-11-12 wording "the order screen shows that customer's QuickBooks prices" and Claude's 2026-11-13 suggestion to show no prices (rejected by Dovid).
  - PROPOSED by Claude, not yet confirmed: "previous" means the most recent QuickBooks invoice for that customer containing the product, however old it is.
  - Still applies (approved 2026-11-12): a product that is not in the customer's QuickBooks company has no regular price and cannot be ordered.
  - (Closed 2026-11-13: no loose bottles; cases only, decimals allowed.)
- CUT-DOWN OF THE FIRST RELEASE (proposed by Claude 2026-11-13 so the release needs no syncing and no hand-maintained data; shown to Dovid as a table; he rejected only the "no prices" row; the other rows are TREATED AS ACCEPTED, TO CONFIRM):
  - (Withdrawn 2026-11-13: bottles per case stays on the product page; see the first bullet of this section.)
  - License number and assigned rep are left off the customer list and the customer page for now.
  - The customer page shows name, address and contact, and balance owed, all read-only from QuickBooks.
  - Order history: QuickBooks invoices, unchanged.
- LICENSE NUMBERS (Dovid 2026-11-13): "licenses belong there, too. For IL, they are mainly in MMK, but we need to keep these synced." Claude's reading, still to confirm: they belong with the customer in QuickBooks; Illinois ones are mainly in MMK today; MMK and QuickBooks must be kept in sync. Not part of this release.
- What this release reads from QuickBooks (read-only): customers (name, address, contact, balance), invoices with line items (order history AND the source of previous prices), and the item list (regular prices). Nothing is written to QuickBooks.

## 1. Scope of the current release (set by Dovid 2026-11-12)
Three functions, and nothing else for now:
1. Product catalog, without pricing, with detailed product data, searchable, filtered by the categories already agreed.
2. Customer lookup with order history.
3. Salesman ordering from the customer page ("New Order"). First version sends the order as an email; later the order is inserted into QuickBooks.

Explicitly NOT in this release:
- Admin screens (deferred by Dovid).
- Prices in the catalog.
- Trade buyer logins and "Add to order request".
- A public (no-login) catalog. The long-term design in the master spec still has one; in this release everything is behind the salesman login (decided 2026-11-12).
- A state picker / per-state catalog. This release shows one combined catalog (decided 2026-11-12).
- The daily MMK / QuickBooks check and mismatch report (design recorded in the master spec, section 5A; build later).
- Promotions, special terms, sell sheets, Encompass submission.

## 2. Function 1 — Product catalog (no pricing)
- Who (decided 2026-11-12): salesmen only, after login. No public access in this release.
- Data: claude/Satla_Master_Catalog.csv (178 products, each with photo, description and filter fields).
- Illinois / Florida (decided 2026-11-12): ONE COMBINED CATALOG. All 178 products are shown together. Products are not tagged by state and there is no state picker in this release.
- Search: a search box over product name, brand, grape, country and region.
- Browse menu (agreed 2026-10-29, master spec section 3): Wine → Red / White / Rosé / Sparkling / Orange / Dessert & Fortified; Spirits → Tequila / Whiskey / Gin / Vodka / Brandy & Cognac; Liqueurs & Aperitifs; Sake; Ready-to-Drink; Brands (A–Z); Countries; Kosher & Mevushal; New Arrivals.
- Filters (agreed 2026-10-29): country & region, brand/producer, grape, sweetness, Mevushal, Kosher for Passover, Organic, bottle size, vintage. Kosher is a site-wide badge, not a filter (everything is kosher). The price-tier filter is left out because the catalog has no pricing.
- Allowed values for each filter: claude/filter-field-rules.md. A blank value means unknown, not "no" (catalog-work-log.md), so a product with a blank field is not matched by either Yes or No.
- Product detail ("more detailed data"): large photo; description; brand; category, type and style; sweetness; grape / base; country, region and sub-region / appellation; ABV; vintage; bottle size; bottles per case; mevushal, Kosher for Passover and organic flags; kosher certifier; SKU.
- Bottles per case (decided 2026-11-12): SHOWN on the product detail page. It is not in the dataset; it comes from QuickBooks.
- UPC (decided 2026-11-12): NOT shown in this release.
- No prices anywhere in the catalog or on the product detail page.
- OPEN (found while building the wireframes): "New Arrivals" is in the agreed menu, but the dataset has no arrival date or "new" flag. What makes a product a new arrival has to be defined before that menu item can show anything.
- CORRECTED 2026-11-13: bottles per case does NOT exist in QuickBooks (Dovid). It is kept in the catalog's own database. OPEN: where the first values come from.

## 3. Function 2 — Customer lookup with order history
- Who: salesmen (logged in).
- Which customers (decided 2026-11-12): a salesman sees ALL customers, from both QuickBooks companies (Illinois and Florida), not only his own.
- Lookup: a search box over the customer list. APPROVED 2026-11-12 (first proposed in the wireframes): search covers business name and city, and an All / Illinois / Florida switch narrows the list by the customer's QuickBooks company.
- Customer page (decided 2026-11-12) shows, besides the name:
  - Address and contact (address, contact name, phone, email).
  - License number.
  - Balance owed.
  - Assigned rep.
  - The "New Order" button (Function 3).
  - Order history.
- Order history (decided 2026-11-12):
  - Lists QuickBooks INVOICES (not estimates or sales orders).
  - Goes back 12 MONTHS.
  - Each invoice opens to show its LINE ITEMS (products and quantities).
  - APPROVED 2026-11-12 (first proposed in the wireframes): each invoice row shows date, invoice number, total and paid / open status; the line items show quantity, rate and amount exactly as QuickBooks holds them.
- Data source: customers, balances and invoices live in QuickBooks (Illinois company and Florida company, separately). Master spec: ACCOUNT carries qbo_customer_id. This means the release needs a read connection to both QuickBooks companies.
- CORRECTED 2026-11-13: the license number and the assigned rep do NOT exist in QuickBooks (Dovid). The assigned rep would be kept in the catalog's own database. LICENSE NUMBER, corrected again by Dovid 2026-11-13: licenses "belong there, too" — read as: they belong with the customer in QuickBooks; for Illinois they are mainly in MMK today and the two must be kept in sync (reading to confirm). OPEN: whether the customer page shows license number and assigned rep in this release at all, given that neither is in QuickBooks today.
- What earlier chats recorded (draft site map, 2026-10-29, never approved): "Home / my accounts: a customer list for picking who you're ordering for" and "Order history per account". Nothing more detailed exists in this Project's chats (re-checked 2026-11-12).

## 4. Function 3 — Salesman ordering from the customer page
- Flow: salesman opens a customer → clicks "New Order" → adds products with cases and bottles → reviews → submits.
- Version A (now): submitting sends the order as an email.
- Version B (later): submitting inserts the order into QuickBooks (that customer's QuickBooks company).
- Designed phone-first (master spec requirement).
- Who receives the order email (decided 2026-11-12): it goes to the office address florida@satlaspirits.com, with a copy to the salesman who placed the order. No copy to the customer.
  - Decided 2026-11-12: orders for ILLINOIS customers also go to florida@satlaspirits.com, for now.
- Prices on the order screen (decided 2026-11-12): YES. The order screen shows THAT CUSTOMER'S QuickBooks prices (from the customer's own QuickBooks company), with line totals and an order total. The catalog itself still shows no prices.
  - CORRECTED 2026-11-13: QuickBooks holds NO customer-specific prices (Dovid). So "that customer's QuickBooks prices" cannot be shown as decided. OPEN: which price the order screen shows — the item's standard QuickBooks price, a price list kept in the catalog database, or no price for now.
  - APPROVED 2026-11-12 (first proposed in the wireframes): prices are read-only (the salesman cannot change them); a product that has no price in the customer's QuickBooks company is shown as "No price in QuickBooks" and cannot be added. Because the catalog is combined and products are not tagged by state, this is the only thing that stops a Florida-only product going onto an Illinois customer's order.
- Saved or emailed (decided 2026-11-12): EMAIL ONLY. The order is not stored in the system.
  - Consequence: a submitted order does NOT appear in the customer's order history right away. It appears once the office has entered it in QuickBooks and it has been invoiced (order history lists QuickBooks invoices only).
  - Consequence: there are no saved drafts. An order exists only on the screen until it is sent. APPROVED 2026-11-12 (first proposed in the wireframes): leaving the order screen with lines on it asks "Discard this order?" first.
  - Consequence: the master spec tables ORDER_REQUEST and ORDER_LINE are not used by Version A. They come into use with Version B or whenever orders are stored.
- APPROVED 2026-11-12 (first proposed in the wireframes):
  - An optional "Note to the office" box on the order (delivery instructions, PO number).
  - The email subject is "New order — [customer] — [date]" and the body lists customer, state, salesman, each line (SKU, product, size, cases, bottles, price, line total), the order total and the note.
  - After sending, a confirmation screen shows what was sent and to whom.

## 5. Users in this release
- Salesman: logs in; uses all three functions. He is the only kind of user.
- Public visitor: none in this release (the catalog is behind the login).
- Admin: none in this release. Salesman logins and product changes are set up by hand behind the scenes.

## 6. Screens (as wireframed 2026-11-12)
| # | Screen | Function | Reached from |
|---|---|---|---|
| 1 | Sign in | all | Start |
| 2 | Catalog (search, browse menu, filters, product grid) | 1 | Sign in; top navigation |
| 3 | Product detail | 1 | Catalog |
| 4 | Customers (lookup) | 2 | Top navigation |
| 5 | Customer page (details, New Order, order history) | 2 | Customers |
| 6 | Invoice (line items) | 2 | Customer page |
| 7 | New Order (add products) | 3 | Customer page |
| 8 | Review order | 3 | New Order |
| 9 | Order sent (confirmation and email preview) | 3 | Review order |

All customers, invoices, prices, bottles-per-case values and salesman names in the wireframes are invented samples. The products, photos and descriptions are the real ones from claude/Satla_Master_Catalog.csv.

## 7. Open and to-confirm items (all in one place)
- New Arrivals: what makes a product a new arrival (section 2).
- Confirm: "previous price" = most recent invoice of any age (section 0).
- Confirm the cut-down rows and the license-number reading (section 0).
- License number and assigned rep: currently left off the screens (section 0), to confirm; whether the assigned rep is in QuickBooks is unverified.

## 8. Next step
- Done 2026-11-12: Dovid reviewed and approved the wireframes and every proposed detail.
- Next: show the standardized photos in the wireframes (photo job, master spec section 6); settle the open items in section 7; then the build plan.

## Change log
- 2026-11-15 — v0.16 — (VPS working copy.) Admin can manage logins on the site (Dovid). Order email sender recorded as open. Stage 3 built, sending off.
- 2026-11-14 — v0.15 — (VPS working copy.) KOVAL products stay; SQLite approved; regular price comes from mc.get_current_inventory_qbo() unit_price.
- 2026-11-14 — v0.14 — (VPS working copy.) Customers and orders from QuickBooks, inventory from MMK, no KOVAL customers or orders. Open: KOVAL products.
- 2026-11-13 — v0.13 — (VPS working copy.) Dovid: regular price is read from QuickBooks; on hand from MMK; code must reuse the existing API library. Customers source ambiguous, re-asked.
- 2026-11-13 — v0.12 — (Edited in the VPS working copy.) Dovid: "Florida is all contained within QBO Florida, which you should also have access to." Florida quantity on hand is read from the Florida QuickBooks company.
- 2026-11-13 — v0.11 — Copy Order added at Dovid's request: copies a past invoice's products and quantities into a new order (reading and details to confirm). Wireframes updated.
- 2026-11-13 — v0.10 — CORRECTION from Dovid: QuickBooks is read for invoicing, MMK is read for quantity on hand, Catalog.db holds all the item data. The v0.9 principle is withdrawn.
- 2026-11-13 — v0.9 — Governing principle recorded: the application reads only the shared database, which stores ALL information; QuickBooks and MMK are only sources it is loaded from. Product page gains regular price and cases on hand per state; order lines show on hand. Wireframes updated.
- 2026-11-13 — v0.8 — Dovid: no loose bottles; orders are in cases only, with decimals for part cases. Wireframes updated. Three unanswered questions recorded as assumptions. Build plan created (claude/satla-build-plan.md).
- 2026-11-13 — v0.7 — CORRECTION from Dovid: bottles per case and bottle size (ml) are in QuickBooks and MMK and will be in the shared database. Bottles per case is back on the product page. Claude's earlier record that it was not in QuickBooks was a misreading. Assigned rep and license location flagged as unverified.
- 2026-11-13 — v0.6 — New section 0. Dovid set the order-screen price rule: default to the regular QuickBooks item price, replaced by the customer's previous price when they have bought the product before; price is an editable field with a Regular / Previous drop-down; no per-customer price table. First release cut down (bottles per case, license number and assigned rep left off; treated as accepted, to confirm). Wireframes updated to match. Open: loose-bottle pricing.
- 2026-11-13 — v0.5 — License numbers: Dovid says they belong with QuickBooks too; Illinois ones are mainly in MMK today and need syncing (reading to confirm). Whether license number and assigned rep appear on the customer page in this release is reopened.
- 2026-11-13 — v0.4 — Dovid: customer-specific prices, license number, assigned rep and bottles per case do not exist in QuickBooks. License, rep and bottles per case move to the catalog's own database. The order-screen price decision is reopened.
- 2026-11-12 — v0.3 — Dovid approved every detail that v0.2 marked PROPOSED (customer search fields and the Illinois / Florida switch, invoice row contents, read-only prices, "no price in the customer's QuickBooks company = cannot be ordered", the discard warning, the note to the office, the email layout, the confirmation screen). Illinois orders also go to florida@satlaspirits.com for now. Test-mode phase recorded: no renames. Still open: New Arrivals rule, QuickBooks fields for license / rep / bottles per case, QuickBooks price storage.
- 2026-11-12 — v0.2 — All nine OPEN items from v0.1 answered by Dovid: catalog is behind the salesman login; one combined catalog (no state tags, no state picker); bottles per case shown, UPC not; salesmen see all customers; customer page shows address and contact, license number, balance owed and assigned rep; order history = QuickBooks invoices, last 12 months, with line items; order email goes to florida@satlaspirits.com with a copy to the salesman; the order screen shows the customer's QuickBooks prices; orders are emailed only, not saved. Consequences and PROPOSED wireframe details recorded; screen list added; new open items listed (New Arrivals rule, Illinois order address, QuickBooks fields for license / rep / bottles per case). Wireframes saved as claude/satla-wireframes.html.
- 2026-11-12 — v0.1 — First draft. Scope of the current release set by Dovid: catalog without pricing, customer lookup with order history, salesman ordering from the customer page (email first, QuickBooks later). Admin and everything else deferred.
