# Satla Catalog — Working Notes & Data Dictionary

Companion to claude/satla-catalog-data-model.md (the master spec). This file records HOW the product dataset was built, what every column means, which sources and tools were used, and what is still open, so any new chat can continue without re-doing work. Where this file and the master spec disagree, the master spec wins.

Last updated: 2026-11-13

---

## 1. Files in this Project

| Project path | What it is |
|---|---|
| claude/satla-catalog-data-model.md | Master spec and source of truth: requirements, data model, decisions, open items, change log. Read first. |
| claude/satla-functional-spec.md | What the current release does for its users. Its section 0 holds the latest decisions. |
| claude/satla-build-plan.md | Staged build plan for the current release (stages 0 to 4, what "done" means, decisions, risks). |
| claude/satla-wireframes.html | Source of the published clickable wireframes (https://claude.ai/artifact/LauytfSzqMdtEMGvt8AghM). References photos as photos/<SKU>.webp; the published page has them built in. |
| claude/Satla_Master_Catalog.csv | Current product dataset (178 rows), one per Satla SKU. Photo addresses, descriptions, filter fields. |
| claude/catalog-work-log.md | This file: methods, column dictionary, sources, tools, gotchas. |
| claude/description-style-guide.md | Rules used to write every product description. Use for any new or rewritten description. |
| claude/filter-field-rules.md | Rules and allowed values used to fill the filter fields. Use for any new product. |
| claude/kosherwine-specs.json | Raw KosherWine.com spec blocks for the 103 matched products (SKU → [page slug, page title, "sweetness\|country, region\|ABV\|mevushal\|color\|KFP\|size\|certifier"]). |
| claude/satla-spec-page.html | Source of the published spec page (rendered view with the ER diagram, Mermaid). STALE: still reflects master spec v0.7. Edit this and republish; never let it say anything the spec doesn't. |

Published spec page (private to Dovid): https://claude.ai/artifact/WFZzQkG57vuCyKC6AX3Yxx.

Note: an older duplicate of the master spec at satla-catalog-data-model.md (no claude/ prefix) was deleted from the Project on 2026-11-13 at Dovid's request. The only master spec is the one under claude/.

Outside the Project (the Project stores only text):
- Standardized product photos: Mac mini ~/satla-photos, copied to the Google Drive folder "satla-photos" (inside Dovid's "Logs" folder), https://drive.google.com/drive/folders/17FgYJnM2KOaEe84JJHjg_5PrAsXeDJBd. See section 2A.

Chat-only intermediate files from 2026-10-28/29 (Satla_Catalog_Validated.csv, Satla_Master_Catalog_183_Photo_Sizes.csv, …) are superseded by the Project CSV. Ignore them.

## 2. How the dataset was built (history)

1. Start: Dovid's file Satla_Master_Catalog_193_Aragvi_Images_Added.csv (183 rows, built in earlier chats with another tool), later replaced by Satla_Master_Catalog_193_Tropez_Candidate_Image_Recorded.csv (193 rows).
2. Validation (2026-10-28): found 12 rows with another product's photo/description, missing descriptions, mevushal/size mismatches. Dovid's next file fixed most.
3. Photo load check: every photo URL loaded in the Claude desktop app's built-in browser (see 5). All loaded. NOTE: this only confirmed that each web address loads and measured its size. The photos were NOT downloaded at this point.
4. Removed 10 products with no photo (list in spec section 6) → 183 rows.
5. Photo sizes measured; rule set to ≥500 px on the longest side (web catalog, compressed images). Low-res photos replaced with larger manufacturer/retailer images, each visually checked. Dovid supplied URLs for Alavida Malbec, Comte de Montaigne, Vincenzi Capasso, Miyamagiku, Bicerin Dark Chocolate, KOVAL Chrysanthemum Honey.
6. Descriptions: all 183 rewritten in the standard trade format (description-style-guide.md) from source facts only; retailer text not copied.
7. Filter fields: KosherWine.com spec blocks scraped for 103 matched products (authority for sweetness, country, region, ABV, mevushal, KFP, certifier); remaining fields from names/descriptions per filter-field-rules.md. Regions normalized to broad filter values; appellation kept in Sub-region.
8. Dovid's decisions applied (spec section 6): all products kosher; Black Fig & Tubi 60 = liqueur; Gondola Sparkling Rosé = sparkling; Sofei correct; Eldod Tempranillo Spanish mevushal; 100 Tropez dry Provence rosé; mevushal conflicts deferred.
9. Duplicates resolved 2026-10-29: kept I-AD01M-R, T-GO08M-R, I-AD20M-E, IT1210103325, IT1212352325 (names updated to QBO names); dropped I-AD02R-M, I-GO108, I-AD120, IT1210103324, IT1212352324 → 178 rows.
10. Photo job, 2026-11-12 (section 2A): photos downloaded and standardized for the first time. Three wrong photo sources found and replaced in the CSV; one wrong-product photo flagged.

## 2A. Photo job (2026-11-12)

Why: the wireframes showed bottles at very different sizes because each source frames its photo differently, and every photo loaded from someone else's website.

How: Dovid ran Claude Code on the Mac mini in ~/satla-photos with a read-only copy of the CSV. Claude's cloud workspace cannot reach the photo sites, so it could not do this itself.

Standard (approved by Dovid): white 3:4 canvas; bottle fills at most 90% of the height and 90% of the width, whichever limit hits first; upscale at most 1.5x, pad beyond that; grid 600x800 WebP and detail 900x1200 WebP; a full-resolution PNG master kept for each. Simple white trim; the AI cutout is used only for IT-1545 Bicerin Dark Chocolate, because it clipped clear glass stoppers elsewhere.

Result: 178 products — 158 OK, 15 NEEDS NEW PHOTO, 5 CHECK. Dovid: leave these as they are for the build-out phase; his manager will review later. The full lists of the 15 and the 5 are in master spec section 6.

What is in ~/satla-photos (and the Drive copy):
- photo-review.csv — one row per SKU: status, reason, version used, pixel sizes, scale factors, fill %. Start here.
- HANDOFF.md — the photo job's own summary, including how to replace a photo.
- grid/ (600x800 WebP), detail/ (900x1200 WebP), masters/ (PNG), originals/, originals-replaced/.
- sheets/ — contact sheets sheet-01 to 06 (30 per sheet, labelled by SKU) and trim comparisons.
- replacements.csv — overrides a catalog photo URL without touching the catalog. use-ai.txt — SKUs that use the AI cutout.
- scripts/ — download.py, process.py, sheets.py, review.py (run in that order).
- Satla_Master_Catalog.csv — a read-only copy. The Project copy is the master.

Changes the photo job caused in the Project CSV (applied 2026-11-12; columns Direct Photo URL, Photo Size, Photo Size Rating, Source, Photo Status):
- V-NU02 Naulin Cognac VS and V-NU04 Naulin Cognac VSOP: the old URLs were vineyard photos; now Naulin's official bottle shots.
- IT1211541322 Pescaja Solo Noi: the Kosher Wine World image showed Pescaja Contro Vento; now a Best Buy Liquors image.
- I-DE33: Photo Status and Description Notes now say the photo and product page show Delta Eta Fusion, while Dovid confirmed the product is Delta Sigma Fusion red. NOT renamed (test mode: no renames). Its description and filter fields may describe the wrong wine.

Where the photos are used: the published wireframes have the 178 grid images built into the page. The photos are not yet on the droplet; copying grid/ and detail/ there is part of build plan Stage 0.

Lessons from the photo job:
- The faint "Koby" watermarks on Kosher Wine World images are removed by the trim.
- A "trim failed" flag is usually a reflection or a bottle touching the edge. Look before replacing.
- Product-page images can show the wrong bottle even when the page itself is correct. Read the label.
- Black Butte Whiskey and Alavida Cabernet were never bad photos. They looked cut off in an early wireframe because of a display fault in the page, since fixed.

## 3. Column dictionary (Satla_Master_Catalog.csv)

Current, authoritative columns:
- Satla SKU, Satla Product Name, Bottle Size — from Satla/QuickBooks. SKU is the join key to QBO. Names follow QuickBooks; do not rename here.
- QBO Item ID — QuickBooks item ID (from qbo.intuit.com/app/item?itemId=…). Filled where Dovid supplied it (5 so far); to be filled for all by the QBO sync.
- Brand, Category, Type, Style, Sweetness, Grape / Base, Country, Region, Sub-region / Appellation, ABV, Kosher, Mevushal, Kosher for Passover, Organic, Kosher Certifier, Vintage — catalog filter fields (allowed values in filter-field-rules.md; Kosher = Yes for all). Blank = unknown, not "no".
- Filter Notes — anything to check about the filter fields.
- Matched Product Name, Source, Product Page URL — the product page the data came from.
- Direct Photo URL — the web address of the ORIGINAL source photo. The standardized photo for a product is not addressed here; it is the file named <Satla SKU>.webp in grid/ and detail/ (section 2A). Photo Size (W x H px) and Photo Size Rating (Good ≥1000 / OK 500–999 / Too small <500) describe the original. Photo Status says how the original was found or verified, and carries the photo job's notes for the four rows it changed.
- Product Description — final catalog text. Description Notes — anything to check. Description Status — how it was written.
- KosherWine.com Product URL, KOVAL Product URL, KWW Product URL/Name/Image URL — reference links.
- Previous Description (source text) — the old/source text, reference only. Do not publish.

Where data lives (Dovid 2026-11-13, verbatim): "QBO will be read for invoicing. MMK will be read for QTY on HAND. Our Catalog.db will hold all the item data." See master spec section 0, which also lists what that statement does not cover. Bottles per case and bottle size in ml exist today in QuickBooks and in MMK and are item data. Dovid said the regular price is "in the INV table in QBO"; whether it is also held in Catalog.db is not decided. There is no per-customer price table: an order line defaults to the customer's previous price, otherwise the regular price.

Legacy columns (from the earlier tool; may be stale — do NOT trust for status): Match Status, Follow-up Needed, Image URL Evidence, Catalog Readiness, Packaging Note.

## 4. Sources

- KosherWine.com — best structured source. Product pages have a spec block (sweetness, country/region, ABV, mevushal, color, KFP, size, certifier). Sitemap: https://www.kosherwine.com/sitemaps/kosherwine/sitemap.xml (~2,950 product slugs). Full-size image = og:image URL with the query string removed; "?width=1000" does not upscale.
- Kosher Wine World (kosherwineworld.com) — Shopify store, password-protected; Dovid enters the password himself in the built-in browser (Claude must never type passwords). Once unlocked, /products.json?limit=250&page=N returns the whole catalog. Many products list vendor "SATLA SPIRITS". Its descriptions were copied verbatim in the old file (now rewritten).
- KOVAL (koval-distillery.com) — product pages have only small (~220×510) bottle images for liqueurs; /press has full-res downloads for whiskeys and gins only (incl. Overproof Bourbon and Bourbon BIB, which were removed for lack of a photo).
- Manufacturer sites used for photos: Domaine Bousquet (Alavida), Crater Lake (Squarespace CDN), Black Infusions, Bendistillery, Cognac Naulin, Marin Sake Imports (Miyamagiku).
- Best Buy Liquors — used by the photo job for Pescaja Solo Noi.

## 5. Tools & gotchas (for Claude in a new chat)

- The cloud sandbox (Bash) cannot reach outside websites — don't use it to fetch pages or images. It also cannot reach the droplet or the Mac mini.
- WebFetch only opens URLs the user typed in chat, and can't read image files.
- Use the Claude desktop app's built-in browser (mcp__remote-devices__Claude_Browser__*) for loading images, measuring sizes (new Image() → naturalWidth/Height in javascript_tool), screenshots for visual checks, and fetching KosherWine.com pages same-origin. Dovid does NOT want his own Chrome used.
- Each new site needs request_access in the built-in browser.
- Long javascript_tool scripts time out at 45 s: start work in the background (window variables) and poll.
- Always visually check a replacement photo before swapping it in (right bottle, right size/format).
- Downloading or processing photos in bulk: do it with Claude Code on Dovid's Mac mini (section 2A), not from a Project chat.
- The Google Drive connection in a Project chat can read text files in the satla-photos folder, but returns only recognized text for image files, not the picture. To look at photos, have Dovid connect a folder holding them through the Claude desktop app (he downloaded grid/ to ~/Downloads/grid on his MacBook Air on 2026-11-12).
- A published claude.ai page blocks every outside image. Photos must be built into the page (as data inside it) to show there.
- Dovid's replies can be terse. On 2026-11-13 "None of these exist in QBO!" was misread as meaning bottles per case is not in QuickBooks; it is. When a short answer could cover several items, ask which.

## 6. Still open (mirror of spec section 6)

- Mevushal conflicts — deferred: I-AD109, I-AD132, I-AD40W-M, I-DR01, I-LR115, IT1751241323 (sheet follows KosherWine.com).
- Bicerin Peppermint size (700 ml vs 1 L); country unknown for Black Infusions (2), Eldod Cabernet, Misceo.
- Photos: 15 need a new photo and 5 have label questions (lists in master spec section 6); waiting for the manager's review.
- I-DE33 is Delta Sigma Fusion red with a Delta Eta Fusion photo, page and possibly description. No rename while in test mode.
- "New Arrivals" has no rule: the dataset has no arrival date or "new" flag.
- Next steps are in claude/satla-build-plan.md, starting with Stage 0.
- UPDATE 2026-11-16 (VPS working copy): the catalog file now holds 178 products. Since the 178 of 2026-11-13: `I-AD132` re-keyed to `I-AD136` (Adir NOVEMBER In Box) and a new `I-AD132` (Adir Marselan Red (M)) added, 2026-11-15; `I-AD02R-23` deleted 2026-11-16 at Dovid's word ("it was a mistake"). The photo masters do not have these changes. Product counts by category elsewhere in this file are from the first 178.
