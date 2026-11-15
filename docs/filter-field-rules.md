# Satla catalog — filter field rules

Fill structured filter fields for each product in a B2B kosher wine & spirits catalog. Use ONLY the facts in the row (satla_name, matched_name, description, old_source_text, kosherwine_specs) plus basic, universally true category knowledge (e.g. Chianti Classico is from Tuscany and made mainly from Sangiovese; Barolo is Nebbiolo from Piedmont; Sancerre white is Sauvignon Blanc; Prosecco is Italian sparkling; Cava is Spanish sparkling; bourbon is a whiskey from the USA; KOVAL is in Chicago, Illinois, USA; Crater Lake Spirits is in Oregon, USA; tequila is from Mexico; cognac is French brandy; sake is Japanese). Never guess anything else. Leave a field empty rather than guess.

## Precedence
- `kosherwine_specs`, when present, is the authority for: sweetness, country, region, abv, mevushal, kfp, certifier, and wine color. Copy them exactly (normalize "Rose" → "Rosé").
- If the Satla name marks mevushal ("(M)", "MEVUSHAL") but kosherwine_specs says No (or the reverse), keep the kosherwine value and write a note: "Mevushal conflict: Satla name says X, KosherWine.com says Y".
- Without kosherwine_specs: mevushal = "Yes" if satla_name has "(M)" or "MEVUSHAL"/"Mevushal"/"Mevoshal" in satla_name or matched_name; otherwise leave empty. For spirits, liqueurs, sake and RTD leave mevushal empty (not applicable).

## Fields (JSON keys) and allowed values
- `brand`: producer/brand as customers know it, clean capitalization (e.g. "Adir", "Bat Shlomo", "KOVAL", "Thresh & Winnow" → use "KOVAL" for KOVAL's Thresh & Winnow line, "Gondola", "Harmino", "Vincenzi", "Bicerin", "Crater Lake Spirits", "Black Infusions", "Shimon & Co", "Aragvi", "GRW", "La Forêt Blanche", "Viña Memorias", "Padre Bendicho", "Château Joséphine", "Pescaja", "Negretti", "Vallepicciola", "Castellare di Castellina").
- `category`: one of Wine | Spirits | Liqueur & Aperitif | Sake | Ready-to-Drink.
  - Vermouth, port → Wine (type "Dessert & Fortified"). Amaretto, sambuca, cream/fruit/coffee liqueurs, aperitivos (Capasso, Arancia), arak/anise, Tubi 60, Black Infusions → Liqueur & Aperitif. Canned/bottled cocktails and Crater Lake Rock & Rye (ready to serve) → Ready-to-Drink.
- `type`:
  - Wine: Red | White | Rosé | Sparkling | Orange | Dessert & Fortified. Sparkling wins over color (a sparkling rosé is "Sparkling"). Moscato with light fizz ("bubbly", "lightly sparkling", "effervescence") → Sparkling.
  - Spirits: Tequila | Whiskey | Gin | Vodka | Brandy & Cognac.
  - Liqueur & Aperitif: Liqueur | Aperitivo | Anise.
  - Sake: Sake. Ready-to-Drink: Cocktail.
- `style`: optional finer label, e.g. Blanco / Reposado / Añejo / Extra Añejo; Bourbon / Rye / Single Malt / Four Grain / Millet; Prosecco / Cava / Champagne / Moscato; Port / Vermouth; Cream Liqueur / Coffee Liqueur / Amaretto / Sambuca; Junmai / Honjozo. Empty if nothing fits.
- `sweetness` (wine only): Dry | Semi-Dry | Semi-Sweet | Sweet. Empty for non-wine or if unknown.
- `grape`: grape(s) or base, comma-separated, most important first (e.g. "Cabernet Sauvignon", "Saperavi", "Cabernet Sauvignon, Petit Verdot, Shiraz"; spirits: "Blue agave", "Corn, Millet", "Rye", "Malted barley", "Rice"). Only if stated or universally implied by the appellation/style. Empty if unknown (e.g. an unnamed "red blend").
- `country`: Israel | Italy | France | Spain | USA | Mexico | Georgia | Argentina | South Africa | Portugal | Germany | Japan | … (English).
- `region`: as specific as the source allows (e.g. "Upper Galilee", "Judean Hills", "Piedmont", "Tuscany", "Bordeaux", "Kakheti", "Jalisco", "Chicago, Illinois", "Oregon"). Empty if unknown.
- `abv`: e.g. "14.5%". Only from kosherwine_specs or an explicit statement in the text (e.g. "40% ABV", "94 proof" → 47%). Empty otherwise.
- `kosher`: "Yes" if any source says kosher or gives a kosher certifier, or if kosherwine_specs exists; otherwise "Unconfirmed".
- `mevushal`: Yes | No | empty (see precedence).
- `kfp` (Kosher for Passover): "Yes" if kosherwine_specs has it or text/name says "Kosher for Passover"; "No" if text says "Not Kosher for Passover"; else empty.
- `organic`: "Yes" if source says organic (e.g. USDA Organic, organic grains); else empty.
- `certifier`: from kosherwine_specs or text; else empty.
- `vintage`: the 4-digit year in satla_name only (e.g. "2022"); "NV" for non-vintage sparkling/fortified/spirits/liqueurs; empty for wines whose satla_name has no year.
- `notes`: short note for anything a human should check (conflicts, guesses avoided, etc.). Empty if fine.

## Output
Write a JSON array to the output file, one object per input row in the same order, with exactly these keys:
sku, brand, category, type, style, sweetness, grape, country, region, abv, kosher, mevushal, kfp, organic, certifier, vintage, notes
