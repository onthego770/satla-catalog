# Satla catalog and salesman ordering site — full handoff

Written 2026-11-13 for Claude Code on the VPS, by the Claude that did the design work with the owner in his Claude Project named "Catalog". This file collects everything from those conversations that matters for building. Where it and the specs disagree, the specs win; where the specs and the owner disagree, the owner wins and the specs get updated.

Read this whole file before proposing anything.

---

## 1. Status in one paragraph

Nothing has been built. No production code exists. What exists: an agreed set of wireframes (nine screens), a functional spec, a master spec, a staged build plan, a cleaned catalog file of 178 products, and a standardized set of product photos. The owner wants to start coding from the wireframes. Stage 1 (sign in and catalog) can start as soon as the owner approves what to build it with. Stages 2 and 3 are blocked on three unanswered data questions (section 8).

## 2. The business and the people

- Satla Spirits: a kosher wine and spirits importer and distributor. Illinois office at 8401 Crawford Ave, Ste 103, Skokie, IL 60076. Also operates in Florida. Everything it sells is kosher.
- It is B2B wholesale. Customers are retailers, restaurants and chains. No consumers.
- The owner is Dovid Feldman. He makes every decision. He is a PHP web developer himself and also works in Python, so he can read code. He has a manager who will later review product data questions (photos, labels); that review has not happened.
- The users of this release are Satla's salesmen. Nobody else.
- The project is in TEST MODE (owner, 2026-11-12): "Please don't rename anything. We are just in test-mode phase!" Do not rename products or change product names anywhere, in any system.

## 3. Systems, and where data lives

The owner's statement, 2026-11-13, verbatim. This is the governing rule:

> "QBO will be read for invoicing. MMK will be read for QTY on HAND. Our Catalog.db will hold all the item data."

| Kind of data | Where it lives |
|---|---|
| All item data: the product record (names, descriptions, photos, filter fields, bottles per case, ml and the rest) | Catalog.db, our own database, to be created here |
| Invoicing: invoices, used for order history and for a customer's previous prices | Read from QuickBooks Online (QBO) |
| Quantity on hand | Read from MMK |

Facts the owner has stated about the systems:
- QuickBooks Online currently powers the whole operation: accounting, banking, P&L, inventory. "Perhaps one day, we will just use QBO as the accounting software."
- Illinois and Florida are SEPARATE QuickBooks Online companies, with completely different products and prices.
- QuickBooks contains a lot of old items that are not sellable and not in stock.
- MMK is the 3PL (third-party warehouse and logistics provider) for the Chicago branch. It covers ILLINOIS ONLY. In Illinois, MMK is the inventory master: "the bottom line" for what can ship.
- Florida has no MMK. Florida's inventory is accurate: if an item exists in Florida inventory, it is sellable. (Understood to be the Florida QuickBooks company's inventory; not explicitly confirmed.)
- SKUs are identical in MMK and QuickBooks. The SKU is the key that ties the systems together.
- Bottles per case and bottle size (ml) exist in QuickBooks and in MMK.
- The regular (standard) price per case is "in the INV table in QBO".
- There is NO separate pricing table per customer.
- License numbers "belong there, too. For IL, they are mainly in MMK, but we need to keep these synced." (Reading not confirmed; license numbers are not shown in this release.)
- MMK and QuickBooks need to be kept in sync with each other. The owner finds the multi-system syncing "complicated". Keep this release free of new syncing.

NOT covered by the owner's statement. These are open. Ask him; do not assume:
1. Customers (name, address, contact, balance): ANSWERED 2026-11-14: "I'd like that the SATLA inventory be pulled from MMK, but the Customer LIst and Orders be pulled from QBO. I don't want any KOVAL customers or Koval Orders (all in MMK) included in the catalog."
2. ANSWERED 2026-11-13: "Regular price - Read from QBO".
3. ANSWERED 2026-11-13 (Dovid, to Claude Code on the VPS): "Florida is all contained within QBO Florida, which you should also have access to." Florida quantity on hand is read from the Florida QuickBooks company.
4. Does "read" mean at the moment a screen opens, or on a schedule?
5. How MMK is read automatically. No method is settled. The only existing MMK automation is `mmk_upload.py`, which drives MMK through a browser (Playwright/Chromium).

UPDATE 2026-11-13 (Claude Code on the VPS):
- DOVID'S ANSWERS TO CLAUDE CODE ON THE VPS, 2026-11-13 (evening), VERBATIM: (a) what to build with (Flask, SQLite, Caddy proposed): "As long as it's what's being used on the orders.satlaspirits.com website." (b) "Yes, read-only qbo / mmk is always OK, both IL & FL". (c) "Regular price - Read from QBO". (d) "Customers - no from MMK" — AMBIGUOUS (customers read from MMK instead of QuickBooks, or not from MMK); re-asked, NOT decided. (e) "On Hand - MMK / Prices  Idon't know all this." — on hand is read from MMK; whether reads happen when a screen opens or on a schedule was left to Claude Code, which will use a short cache with an "as of" time (Claude Code's choice, to confirm). (f) reuse mmk_data.py for the MMK read: "yes, mmk_data.py". (g) CODE RULE: "Please make sure we are not duplicating ANY code. I have API for almost EVERYTHING, and I ALWAYS want it used. If you need to create a new API, please do so, keeping future usability in mind. Please put in the same API library as we currently have, and document the function." The API library is ~/python/qbo_scripts (the code behind orders.satlaspirits.com). 
- STAGE 0 CHECK DONE 2026-11-13 (read-only, through the existing library: qbo.qbo_client, mc.get_current_inventory_qbo, mc.get_current_inventory_mmk): both QuickBooks companies are readable from the VPS (Illinois 546 items, Florida 477). Of the 178 catalog SKUs: 148 are in Illinois QuickBooks, 100 in Florida QuickBooks (all 100 are also in Illinois), 30 are in neither (almost all KOVAL KOV- SKUs, plus I-AD02R-23 and a few others); 128 are in stock at MMK. Bottles per case and ml are parsed by the library from the QuickBooks item description and were known for every catalog SKU found. The regular price is the QuickBooks item UnitPrice (filled on 98 of 100 sampled Illinois items and 94 of 100 Florida). The orders site uses Flask, gunicorn and Caddy and has NO database (config files only), so SQLite for Catalog.db is new on this server — to confirm with Dovid.

## 4. This server

Known facts. Most were recorded in July 2026 and should be verified on the machine before relying on them:
- A DigitalOcean droplet, Ubuntu 24.04, hostname QBO-Server. 1 GB of memory plus 2 GB of swap (the swap was added for headless Chromium). It was resized once already; resizing again is an option.
- A non-root user with passwordless sudo. SSH key login only. Firewall (ufw) allows 22, 80 and 443.
- `catalog.satlaspirits.com` already resolves to this server (owner, 2026-11-13).
- Claude Code is set up here in its own directory: this one.
- The existing QuickBooks tooling lives in `~/python/qbo_scripts`, with configs in `~/python/config` and a virtual environment named `qbo311`. Scripts there include `qbo_pull_orders.py`, `qbo_mmk_salesorder.py` and `mmk_upload.py`.
- This server OWNS THE QUICKBOOKS TOKEN CHAIN. The business's order flow depends on it. Breaking it stops orders.
- A web server for a rep-facing app was planned earlier (FastAPI or Flask, systemd, Caddy for HTTPS). Whether any of it is installed is unknown. Check.
- A Florida QuickBooks config exists (`~/python/config/qbo_config_fl.json`) and the owner says this server should have access to the Florida company. An actual read has not been tested. Check before Stage 2.

Hard limits on this server:
- Do not modify, move or delete anything under `~/python`. Ask before reusing its QuickBooks connection, and prove a read does not disturb the existing scripts before depending on it.
- Never write to QuickBooks. Never write to MMK. This release only reads them.

## 5. What is in this directory

| Path | What it is |
|---|---|
| `CLAUDE.md` | The short rules. Loaded every session. |
| `docs/HANDOFF.md` | This file. |
| `docs/satla-catalog-data-model.md` | Master spec (v0.30). Section 0 is the data rule. Long, with history; later corrections override earlier text. |
| `docs/satla-functional-spec.md` | What the release does (v0.11). Section 0 holds the latest decisions and overrides everything below it. |
| `docs/satla-build-plan.md` | Stages 0 to 4 and what "done" means (v0.5). |
| `docs/catalog-work-log.md` | How the product data was built; the column dictionary. |
| `docs/filter-field-rules.md` | Allowed values for the filter fields. Needed only when adding or changing a product. |
| `docs/description-style-guide.md` | How product descriptions are written. Needed only when adding or changing a product. |
| `Satla_Master_Catalog.csv` | The product data: 178 rows, one per SKU, UTF-8 with a BOM. |
| `wireframes/index.html` | The clickable wireframes. Open in a browser. Notes beside each screen say who sees it, what each control does and the rules, each tagged Decided, Proposed, Open or Later. |
| `wireframes/photos/` | The 178 standardized GRID photos, 600x800 WebP, named `<Satla SKU>.webp`. |

The wireframe page is a single file of plain HTML, CSS and JavaScript with the product data embedded. It is a design reference, not a starting codebase. Its sample logic (filters, price defaults, Copy Order) shows the intended behavior.

## 6. What is NOT in this directory, and where it is

| Missing here | Where it is | Needed for |
|---|---|---|
| DETAIL photos, 900x1200 WebP, 178 files | Owner's Mac mini, `~/satla-photos/detail`. Also in his Google Drive folder "satla-photos" (inside "Logs"). | The product page. Must be copied here. |
| Full-resolution photo masters (PNG) | Mac mini `~/satla-photos/masters` | Regenerating sizes later |
| Original downloaded photos | Mac mini `~/satla-photos/originals` | Reprocessing |
| `photo-review.csv` (per-SKU photo status, sizes, scale factors) | Mac mini `~/satla-photos`, and the Drive folder | Knowing which photos are weak |
| The photo job's own `HANDOFF.md` and its scripts (`download.py`, `process.py`, `sheets.py`, `review.py`) | Mac mini `~/satla-photos` and `~/satla-photos/scripts` | Replacing a photo |
| `kosherwine-specs.json` (raw spec data for 103 products) | The "Catalog" Claude Project | Only for rechecking filter fields |
| Catalog.db | Does not exist yet | Everything |
| Any QuickBooks field facts (which fields hold price, bottles per case, ml; invoice line fields; quantity unit) | Not yet checked | Stages 1 to 3 |
| A method for reading MMK | Not settled | Quantity on hand |
| The list of salesmen and their email addresses | Owner has not given it | Logins |
| How the site sends email, and from which address | Not decided | Stage 3 |
| The choice of language, framework and database | Not decided | Before any code |
| QBO Item IDs for 173 of the 178 products | Only 5 are known (see section 9) | Matching to QuickBooks is by SKU, so not blocking |

Links:
- Published wireframes (shared by link): https://claude.ai/artifact/LauytfSzqMdtEMGvt8AghM
- Photos in Google Drive: https://drive.google.com/drive/folders/17FgYJnM2KOaEe84JJHjg_5PrAsXeDJBd
- The masters of all documents live in the owner's Claude Project "Catalog". The copies in `docs/` are working copies.

## 7. The release, screen by screen

One internal website behind a login. Phone first: every screen must work at phone width and at laptop width. Nine screens.

General rules:
- Salesmen are the only users. No public access, no trade buyer logins, no sign-up. No admin screens: logins and product data are set up by hand behind the scenes.
- One combined catalog of all 178 products. No Illinois / Florida picker, and products are not tagged by state.
- Everything is kosher, so kosher is a badge on the page, not a filter.
- A blank field means unknown, not "no".

### Screen 1 — Sign in
Email and password. Accounts are created by the office. Forgotten-password handling is not specified.

### Screen 2 — Catalog
- Search over product name, brand, grape, country and region. Every word typed must match; accents are ignored.
- Browse menu, agreed 2026-10-29: Wine → Red / White / Rosé / Sparkling / Orange / Dessert & Fortified; Spirits → Tequila / Whiskey / Gin / Vodka / Brandy & Cognac; Liqueurs & Aperitifs; Sake; Ready-to-Drink; Brands (A–Z); Countries; Kosher & Mevushal; New Arrivals.
- Filters, agreed 2026-10-29: country and region, brand, grape, sweetness, Mevushal, Kosher for Passover, Organic, bottle size, vintage. Within one filter, any ticked value matches; across filters, all must match. A region narrows only its own country. Each value shows a count.
- Filters are a side panel at laptop width and a slide-in drawer on a phone.
- Product cards: standardized photo, brand, name, type, country, size, badges. Sorted by brand, then name. No sort control.
- NO PRICES on the grid.
- New Arrivals has no rule: the data has no arrival date or "new" flag. It shows an explanation instead of products.

### Screen 3 — Product page
- Large photo, description, and every product field: brand, category, type, style, sweetness, grape / base, country, region, sub-region, ABV, vintage, bottle size, bottles per case, kosher, mevushal, Kosher for Passover, organic, certifier, SKU. A field with no value shows a dash.
- UPC is not shown.
- A "Price and stock by state" block, decided 2026-11-13: for Illinois and for Florida, the regular price per case and cases on hand. The owner: "this is not an outward facing website."
- No order button here. Ordering starts from a customer page.

### Screen 4 — Customers
- Every salesman sees ALL customers, from both QuickBooks companies.
- Search by business name or city. An All / Illinois / Florida switch. Each row shows name, city and state.

### Screen 5 — Customer page
- Name, state, address and contact, balance owed. Read-only.
- License number and assigned rep are NOT shown in this release (assumed; see section 8).
- A "New Order" button.
- Order history: QuickBooks INVOICES (not estimates or sales orders), last 12 months, newest first. Each row: date, invoice number, total, paid or open.

### Screen 6 — Invoice
- Line items: product, quantity, rate, amount, and the total. Read-only.
- A "Copy Order" button (requested 2026-11-13): starts a new order for the same customer with the same products and quantities, and opens it on the review screen. Proposed details: quantities are copied but prices are not, each line taking the usual default; a product that can no longer be ordered is left out and the salesman is told how many lines were dropped; nothing is sent until Send order is pressed.

### Screen 7 — New Order
- Reached from the customer page. Product list with search and category chips.
- Quantity is in CASES ONLY. The owner: "We don't sell loose bottles. If someone orders 1/2 case, we just put QTY .5 or something. This is B2B Wholesale." So quantity accepts decimals. There is no bottles quantity and no bottle price.
- PRICE RULE (owner, 2026-11-13): the default is the regular price from QuickBooks; if that customer has bought the product before, the price they paid last time replaces it as the default. His example: rosé is $140 a case in QuickBooks, so $140 is the default; a customer who bought it before at $130 gets $130.
- Price is a text field filled with that default, which the salesman can type over. Next to it, a drop-down offering the Previous price (with its date) and the Regular price.
- Each line shows cases on hand, as information only. It does not block the order.
- A product with no regular price for the customer's state cannot be ordered. With one combined catalog and no state tags, this is the only thing keeping a Florida-only product off an Illinois order.
- The order is NOT saved anywhere. It exists only on the screen until sent. Leaving with lines on it asks "Discard this order?" first.

### Screen 8 — Review order
Lines with quantity controls and remove; an optional note to the office; a box showing where the order will go; Send order.

### Screen 9 — Order sent
- Sending sends ONE EMAIL: to florida@satlaspirits.com, with a copy to the salesman. No copy to the customer. Illinois orders go to the same address for now.
- Email content: subject "New order — customer — date"; body lists customer, state, salesman, each line (SKU, product, size, cases, price per case and whether it is the regular, previous or a typed price, line total), the order total and the note.
- The office then enters the order into QuickBooks by hand. A sent order therefore does not appear in order history until it has been invoiced in QuickBooks.

## 8. Where every decision stands

DECIDED by the owner: everything in section 7 not listed below; the data rule in section 3; the web address; the photo standard in section 10; test mode.

PROPOSED by Claude and approved by the owner on 2026-11-12: customer search by name and city; the Illinois / Florida switch; invoice rows showing total and paid / open; the discard warning; the note to the office; the email layout; the confirmation screen; "no regular price for the customer's state means it cannot be ordered".

PROPOSED and NOT yet confirmed:
- "Previous price" means the most recent invoice for that customer containing the product, however old.
- On hand is information only and does not block an order.
- Copy Order's details: prices follow the usual default instead of the old invoice's prices; the button is on the invoice screen only; it lands on the review screen.

ASSUMED because the owner did not answer when asked on 2026-11-13:
- Assigned rep stays off the customer page.
- License number stays off the customer page.
- New Arrivals stays in the menu showing no products.

OPEN, needs the owner:
- The data questions in section 3 (customers, regular price, Florida on hand, when reads happen, the MMK method).
- What to build with.
- How the site sends email and from which address.
- Who the first salesmen are, and who pilots.
- The New Arrivals rule.
- Forgotten passwords.

## 9. The product data

`Satla_Master_Catalog.csv`: 178 products. By category: Wine 111, Spirits 41, Liqueur & Aperitif 20, Ready-to-Drink 4, Sake 2.

Columns to USE:
- `Satla SKU` — the key. Matches QuickBooks and MMK.
- `Satla Product Name` — follows QuickBooks. Do not rename.
- `Bottle Size`, `Brand`, `Category`, `Type`, `Style`, `Sweetness`, `Grape / Base` (comma-separated when more than one), `Country`, `Region`, `Sub-region / Appellation`, `ABV`, `Kosher` (Yes for all), `Mevushal`, `Kosher for Passover`, `Organic`, `Kosher Certifier`, `Vintage`.
- `Product Description` — the catalog text.
- `Direct Photo URL` — the web address of the ORIGINAL source photo. Do not show this in the site. The standardized photo for a product is the file `<Satla SKU>.webp`.
- `QBO Item ID` — filled for only 5 rows: I-AD01M-R = 36, I-AD20M-E = 56, T-GO08M-R = 513, IT1210103325 = 483, IT1212352325 = 482. QuickBooks item IDs are per company, so a product in both states has two.

Columns to IGNORE (legacy, may be stale): `Match Status`, `Follow-up Needed`, `Image URL Evidence`, `Catalog Readiness`, `Packaging Note`. Reference only, never publish: `Previous Description (source text)`, and the `KWW…`, `KosherWine.com…` and `KOVAL…` link columns.

Rules behind the data:
- One catalog entry per product. Where two SKUs were the same product, only the current one is kept.
- Descriptions: 2 to 3 plain sentences; no vintage years, no kosher, mevushal or ABV in the text.
- Bottles per case and ml are NOT in this file. They are item data that exists today in QuickBooks and MMK.

Known data issues. Leave all of these alone unless the owner says otherwise:
- I-DE33 is named "Delta Sigma Cabernet Sauvignon (M)". The owner confirmed the product is Delta Sigma Fusion red (72% Cabernet Sauvignon, 28% Shiraz). Its photo, product page and possibly its description and filter fields are for Delta Eta Fusion. NOT renamed: test mode.
- Mevushal conflicts, deferred by the owner (the Satla name says mevushal, KosherWine.com says not; the file follows KosherWine.com): I-AD109, I-AD132, I-AD40W-M, I-DR01, I-LR115, IT1751241323.
- Bicerin Peppermint: source says 700 ml, Satla says 1 L.
- Country unknown for Black Infusions (2 products), Eldod Cabernet, Misceo.
- A name typo the owner said he would fix in QuickBooks: "Repodaso" should be Reposado (MX-MT12).
- The 178 products have never been checked against MMK or against either QuickBooks company. Some may not be sellable, and some sellable products may be missing.

## 10. The photos

Standard, approved by the owner: white 3:4 canvas; the bottle fills at most 90% of the height and at most 90% of the width; upscale at most 1.5x and pad beyond that; grid 600x800 WebP; detail 900x1200 WebP; a PNG master kept for each. Files are named by SKU.

Result of the first pass: 158 OK, 15 need a new photo, 5 have a label question. The owner: leave them as they are for the build-out phase; his manager will review later.

Need a new photo, wrong product (1): I-DE33.

Need a new photo, too small (14): I-DE27 Delta Lamda (smallest; undersized even in the grid), I-BT123 Bat Shlomo Regavim, I-DR12R-M-23 Drimia Susya, IL-103 Katlav Wadi, KOV-2154 KOVAL Coffee Liqueur, KOV-24526 KOVAL Ginger Liqueur 750 ml, KOV-321434 KOVAL Ginger Liqueur 375 ml, KOV-321437 KOVAL Rose Hip Liqueur, MISCEO, JP-MSI04 Miyamagiku Tokubetsu Junmai, IT-3330 Vincenzi Capasso, MX-VM01, MX-VM02, MX-VM03 Viva Mexico Blanco, Reposado, Añejo.

Label does not match the SKU exactly (5): RSH-TROP100-19-3L- (photo is a standard 100 Tropez rosé; SKU is the 2019 Reserve 3 L); I-AD02R-23 (label 2015, SKU 2023); IT1709281322 (label Chianti Classico 2021, SKU Riserva 2022); GE0101152322 (label 2021, SKU 2022); IT1241451320 (label is Barolo Bricco Ambrogio, the same wine as IT1241571320).

Accepted as they are: several KOVAL and Crater Lake sizes share one photo; I-BT112 and I-AD132 are shown with their wooden boxes; KOV-341973 and KOV-341975 show a 4-pack carton plus can.

A display lesson from the wireframes: put the photo in a box and fit it inside (contain), never let it size the box. An early version cropped every photo on the product page because the box was not 3:4.

## 11. Not in this release

Do not build any of these now. They are recorded in the specs for later:
- Inserting orders into QuickBooks (version B of ordering). Sending to Encompass.
- A public catalog, a state picker, trade buyer logins, prices on the grid, "Add to order request".
- Admin screens.
- The daily automated check of MMK, QuickBooks and the catalog, and its mismatch report.
- Showing or syncing license numbers and assigned reps.
- Promotions, special customer terms, sell sheets.
- Replacing the flagged photos.

## 12. Working with the owner

- He answers briefly. A short answer can be about one item when it looks like it covers several. On 2026-11-13 Claude generalized three short answers and had to correct the specs each time. When a short answer could cover more than one thing, ask which.
- Record what he says about data and rules in his own words. Do not extend it.
- He wants decisions written into the documents in the same turn they are made, with a version bump and a change-log row. He does not want to repeat himself to a later session.
- When giving him commands, use real paths from his setup, never placeholders.
- He wants plain language, the conclusion first, and no code before he has approved the approach.
- He gets frustrated when a decision he has made is reopened. Check the documents before asking him anything.

## 13. First steps for you

1. Read `CLAUDE.md`, this file, the three spec documents, and open `wireframes/index.html`.
2. Look at this server: what is installed, how much memory is free, whether a web server is running, how `catalog.satlaspirits.com` is currently served. Change nothing.
3. Propose to the owner, in plain language: what to build it with, how Catalog.db will be structured for the item data, and a plan for Stage 0 and Stage 1. Wait for his yes.
4. Ask him the open questions in section 8 that block Stage 2 and Stage 3, in one batch, multiple choice where possible.
5. Ask him to copy the detail photos here from the Mac mini.
6. Build Stage 1 only after steps 3 to 5.
