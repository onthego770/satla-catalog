# Satla Spirits catalog — description style guide

Audience: retail store buyers and restaurant/bar buyers browsing a B2B wholesale catalog. They want to know quickly what the product is and who it will sell to. Not consumers.

## Format
- 2 or 3 sentences, about 35–60 words total. Plain prose, no HTML, no bullet points, no line breaks.
- Sentence 1 — what it is: producer/brand, style (e.g. dry red, sweet white, sparkling, tequila añejo, cream liqueur), main grape(s) or base, and country/region.
- Sentence 2 — how it tastes, in plain words: body (light / medium / full), sweetness if relevant, 2–3 main flavors.
- Sentence 3 — how it sells/uses: food pairings, occasion, or serving (e.g. "chilled", "for cocktails"), or a practical selling point (e.g. "easy-drinking everyday red", "approachable price-point bubbly", "gift-worthy").

## Tone
- Clear, factual, confident. Write like a good distributor sell sheet, not a sommelier.
- No fancy or flowery language. Banned: "exquisite", "symphony", "tantalizing", "elevate", "embark", "journey", "delight your palate", "harmonious", "indulge", "boasts", "captivating", "testament", exclamation marks, first person ("we", "our").
- Do not mention prices, retailers, websites, "this listing", vintage-substitution policies, shipping, or awards unless the source states the award.

## Facts
- Use ONLY facts present in the row's source data (satla_name, matched_name, existing_description, Source* columns). Never invent grapes, regions, aging, ABV, scores or tasting notes.
- If the source text is thin, write a shorter, accurate description (2 sentences is fine). Say what it is and give a sensible, generic use ("pairs with everyday meals") only if it's obviously true for the category.
- Do NOT state vintage years (vintages change; the catalog stays). Do NOT state mevushal, kosher certification, Kosher for Passover or ABV in the text — those live in their own columns.
- The existing_description may belong to a different vintage, or (rarely) be wrong. If it clearly contradicts satla_name (different grape/product), ignore it, write from the names only, and set flag.
- Different bottle sizes of the same product: same core description; for minis/large formats you may add a short note (e.g. "Single-serve 200 ml bottle.").
- Use the product name as the Satla customer would recognize it (clean up capitalization, e.g. "HARMINO Moscato (M)" → "Harmino Moscato"). Fix obvious typos.

## Output
Write a JSON array to the output file, one object per input row, same order:
{"sku": "...", "description": "...", "flag": ""}
`flag` is empty unless something needs a human check (contradiction, too little info, size mismatch) — then a short note.
