/* Catalog screen: search, browse menu, filters, product grid.
   The behaviour is the approved wireframe's (wireframes/index.html), moved here
   with real data: every search word must match, accents are ignored; within one
   filter any ticked value matches, across filters all must match; the country
   filter has no region level under it (the owner, 2026-11-15: "Country is
   enough"); a blank field means unknown, not "no"; products are listed by
   brand then name. No prices on this screen. */
"use strict";
(function () {
  const P = JSON.parse(document.getElementById("pdata").textContent);
  const view = document.getElementById("view"), ovl = document.getElementById("overlay");
  const {esc, norm, wordsMatch, load, save: store} = window.Satla;
  const sid = s => String(s).replace(/[^a-zA-Z0-9]+/g, "_");

  P.forEach(p => {
    p.hay = norm([p.name, p.brand, p.grape, p.country, p.region, p.sku, document.body.dataset.list ? p.cat : ""].join(" "));
    p.grapes = p.grape ? p.grape.split(/\s*,\s*/) : [];
  });
  P.sort((a, b) => norm(a.brand + a.name).localeCompare(norm(b.brand + b.name)));
  const BY = Object.fromEntries(P.map(p => [p.sku, p]));

  /* ---------- menu and filters (agreed 2026-10-29) ---------- */
  const MENU = [["all", "All"], ["wine", "Wine"], ["spirits", "Spirits"], ["liq", "Liqueurs & Aperitifs"], ["sake", "Sake"], ["rtd", "Ready-to-Drink"], ["beer", "Beer"], ["brands", "Brands (A–Z)"], ["countries", "Countries"], ["mev", "Mevushal"], ["kfp", "Kosher for Passover"], ["new", "New Arrivals"]];
  /* A price list (the Meat list; the server marks the page): its items are not
     drinks, so the menu is All, the list's own sections (each item's category,
     A to Z) and Brands; the stock and bottle-size filters are left out. */
  const LIST = !!document.body.dataset.list;
  const SECTION = "sec:";
  if (LIST) {
    P.sort((a, b) => a.n - b.n);                 /* the list's own order, section by section */
    const sections = [...new Set(P.map(p => p.cat).filter(Boolean))];
    MENU.splice(0, MENU.length, ["all", "All"], ...sections.map(s => [SECTION + s, s]), ["brands", "Brands (A–Z)"]);
  }
  /* Items the state sells that have no catalog entry yet (marked x by the server). */
  if (P.some(p => p.x)) MENU.push(["nocat", "Not in catalog"]);
  const SUB = {wine: ["Red", "White", "Rosé", "Sparkling", "Orange", "Dessert & Fortified"], spirits: ["Tequila", "Whiskey", "Gin", "Vodka", "Brandy & Cognac"]};
  const ml = s => { const m = /([\d.]+)\s*(ml|l)/i.exec(s || ""); return m ? parseFloat(m[1]) * (m[2].toLowerCase() === "l" ? 1000 : 1) : 0; };
  const FG = [
    {k: "stock", label: "Stock", get: p => [p.out ? "" : "In stock only"]},   /* the owner, 2026-11-17 */
    {k: "country", label: "Country", get: p => [p.country]},
    {k: "brand", label: "Brand / producer", get: p => [p.brand]},
    {k: "grape", label: "Grape / base", get: p => p.grapes},
    {k: "sweet", label: "Sweetness", get: p => [p.sweet], ord: ["Dry", "Semi-Dry", "Semi-Sweet", "Sweet"]},
    {k: "mev", label: "Mevushal", get: p => [p.mev], ord: ["Yes", "No"]},
    {k: "kfp", label: "Kosher for Passover", get: p => [p.kfp]},
    {k: "org", label: "Organic", get: p => [p.org]},
    {k: "size", label: "Bottle size", get: p => [p.size], cmp: (a, b) => ml(a) - ml(b)},
    {k: "vint", label: "Vintage", get: p => [p.vint], cmp: (a, b) => (a === "NV") - (b === "NV") || b.localeCompare(a)}
  ];
  const blankF = () => ({stock: [], country: [], brand: [], grape: [], sweet: [], mev: [], kfp: [], org: [], size: [], vint: []});

  /* ---------- state: kept for the browser tab, so "Back to results" returns
     to the same search, menu, filters and scroll position ---------- */
  const KEY = "satla.catalog.v2." + document.body.dataset.state;   /* each state keeps its own search and filters */
  const wideQuery = window.matchMedia("(min-width:700px)");
  const S = {q: "", menu: "all", sub: null, f: blankF(), openF: {country: true}, drawer: false, wide: wideQuery.matches, scroll: 0};
  const saved = load(KEY);
  if (saved) {
    S.q = saved.q || ""; S.sub = saved.sub || null; S.scroll = saved.scroll || 0;
    if (MENU.some(m => m[0] === saved.menu)) S.menu = saved.menu;
    /* only the filters that exist today: a tab saved earlier may hold others */
    for (const k in S.f) if (saved.f && Array.isArray(saved.f[k])) S.f[k] = saved.f[k];
    Object.assign(S.openF, saved.openF || {});
  }
  function save() { store(KEY, {q: S.q, menu: S.menu, sub: S.sub, f: S.f, openF: S.openF, scroll: window.scrollY}); }

  /* ---------- catalog logic ---------- */
  function menuMatch(p) {
    if (S.menu.startsWith(SECTION)) return p.cat === S.menu.slice(SECTION.length);
    switch (S.menu) {
      case "wine": return p.cat === "Wine" && (!S.sub || p.type === S.sub);
      case "spirits": return p.cat === "Spirits" && (!S.sub || p.type === S.sub);
      case "liq": return p.cat === "Liqueur & Aperitif";
      case "sake": return p.cat === "Sake";
      case "rtd": return p.cat === "Ready-to-Drink";
      case "beer": return p.cat === "Beer";
      case "mev": return p.mev === "Yes";
      case "kfp": return p.kfp === "Yes";
      case "nocat": return !!p.x;
      case "new": return false;
      default: return true;
    }
  }
  const qMatch = (p, q) => wordsMatch(p.hay, q);
  function fMatch(p, skip) {
    for (const g of FG) {
      if (g.k === skip) continue;
      const sel = S.f[g.k]; if (!sel.length) continue;
      if (!g.get(p).some(v => sel.includes(v))) return false;
    }
    return true;
  }
  function options(g, base) {
    const m = new Map();
    base.filter(p => fMatch(p, g.k)).forEach(p => g.get(p).forEach(v => { if (v) m.set(v, (m.get(v) || 0) + 1); }));
    S.f[g.k].forEach(v => { if (!m.has(v)) m.set(v, 0); });
    const a = [...m.entries()];
    if (g.ord) a.sort((x, y) => g.ord.indexOf(x[0]) - g.ord.indexOf(y[0]));
    else if (g.cmp) a.sort((x, y) => g.cmp(x[0], y[0]));
    else a.sort((x, y) => norm(x[0]).localeCompare(norm(y[0])));
    return a;
  }
  const nFilters = () => Object.values(S.f).reduce((s, a) => s + a.length, 0);
  const baseList = () => P.filter(p => menuMatch(p) && qMatch(p, S.q));

  /* ---------- view parts ---------- */
  const photo = p => window.Satla.photo(p.sku, p.pv);
  function badges(p) {
    return '<div class="tags">' + (p.out ? '<span class="tag out">OUT</span>' : "") + (p.mev === "Yes" ? '<span class="tag">Mevushal</span>' : "") + (p.org === "Yes" ? '<span class="tag">Organic</span>' : "") + (p.x ? '<span class="tag">Not in catalog</span>' : "") + "</div>";
  }
  function filtersHTML(base) {
    let h = '<div class="filters">';
    for (const g of FG) {
      if (LIST && (g.k === "stock" || g.k === "size")) continue;
      const o = options(g, base); if (!o.length) continue;
      h += '<details data-fg="' + g.k + '"' + (S.openF[g.k] ? " open" : "") + "><summary>" + g.label + (S.f[g.k].length ? " (" + S.f[g.k].length + ")" : "") + '</summary><div class="opts" id="opts-' + g.k + '">';
      for (const [v, n] of o) {
        const on = S.f[g.k].includes(v);
        h += '<label class="opt"><input type="checkbox" id="f-' + g.k + "-" + sid(v) + '" data-f="' + g.k + '" data-v="' + esc(v) + '"' + (on ? " checked" : "") + "><span>" + esc(v) + "</span><small>" + n + "</small></label>";
      }
      h += "</div></details>";
    }
    return h + "</div>";
  }
  const chipLabel = (k, v) => k === "mev" ? "Mevushal: " + v : k === "kfp" ? "Kosher for Passover" : k === "org" ? "Organic" : v;

  function catalogHTML() {
    const base = baseList(), res = base.filter(p => fMatch(p));
    const listView = S.menu === "brands" || S.menu === "countries";
    let h = '<div class="srow"><input class="inp" id="q" type="search" data-in="q" placeholder="' + (LIST ? "Search name, section, item number" : "Search name, brand, grape, country, region") + '" value="' + esc(S.q) + '" aria-label="Search products" enterkeyhint="search"></div>';
    h += '<div class="chips" id="menu" role="group" aria-label="Browse menu">' + MENU.map(m => '<button class="chip" data-act="menu" data-m="' + esc(m[0]) + '" aria-pressed="' + (S.menu === m[0]) + '">' + esc(m[1]) + "</button>").join("") + "</div>";
    if (SUB[S.menu]) h += '<div class="chips" id="submenu" role="group" aria-label="' + S.menu + ' types"><button class="chip" data-act="sub" data-s="" aria-pressed="' + (!S.sub) + '">All ' + (S.menu === "wine" ? "wine" : "spirits") + "</button>" + SUB[S.menu].map(s => '<button class="chip" data-act="sub" data-s="' + esc(s) + '" aria-pressed="' + (S.sub === s) + '">' + s + "</button>").join("") + "</div>";
    if (listView) {
      const key = S.menu === "brands" ? "brand" : "country", m = new Map();
      P.forEach(p => { if (p[key]) m.set(p[key], (m.get(p[key]) || 0) + 1); });
      const items = [...m.entries()].sort((a, b) => norm(a[0]).localeCompare(norm(b[0])));
      h += '<p class="meta">' + items.length + (key === "brand" ? " brands" : " countries") + '. Choose one to see its products.</p><div class="alist">';
      let L = "";
      for (const [v, n] of items) {
        if (key === "brand") { const l = norm(v)[0].toUpperCase().replace(/\d/, "#"); if (l !== L) { L = l; h += "<h4>" + L + "</h4>"; } }
        h += '<button data-act="pick" data-k="' + key + '" data-v="' + esc(v) + '"><span>' + esc(v) + "</span><small>" + n + "</small></button>";
      }
      return h + "</div>";
    }
    if (LIST) return h + listHTML(res);
    h += '<div class="cat">';
    if (S.wide) h += '<div><div class="count"><b>Filters</b>' + (nFilters() ? '<button class="link" data-act="clear">Clear all</button>' : "") + "</div>" + filtersHTML(base) + "</div>";
    h += '<div class="col"><div class="count"><span><b>' + res.length + "</b> of " + P.length + ' products</span>' +
      (S.wide ? "" : '<button class="btn sm" data-act="drawer">Filters' + (nFilters() ? " (" + nFilters() + ")" : "") + "</button>") + "</div>";
    if (nFilters()) {
      h += '<div class="chips" id="active">';
      for (const k in S.f) for (const v of S.f[k]) h += '<button class="chip x" data-act="unf" data-f="' + k + '" data-v="' + esc(v) + '" aria-label="Remove filter ' + esc(v) + '">' + esc(chipLabel(k, v)) + " ×</button>";
      h += '<button class="chip" data-act="clear">Clear all</button></div>';
    }
    if (S.menu === "new") h += '<div class="empty"><b>New Arrivals is not set up yet.</b><br>The product data has no arrival date, so nothing can be listed here until the rule is decided.</div>';
    else if (!P.length) h += '<div class="empty"><b>No products are listed for this state yet.</b><br>They are read every 30 minutes.</div>';
    else if (!res.length) h += '<div class="empty"><b>No products match.</b><br>Remove a filter or change the search.</div>';
    else {
      h += '<div class="grid">';
      for (const p of res) h += '<a class="card" href="/product/' + encodeURIComponent(p.sku) + '">' + photo(p) + '<span class="eyebrow">' + esc(p.brand) + "</span><h3>" + esc(p.name) + '</h3><span class="meta">' + esc([p.type, p.country, p.size].filter(Boolean).join(" · ")) + "</span>" + badges(p) + "</a>";
      h += "</div>";
    }
    return h + "</div></div>";
  }

  /* A price list's page (the owner, 2026-11-18): a sheet like the supplier's,
     rows and columns, with the small picture; the price column only for
     someone who may see prices, and as a box to type in for an admin (leaving
     the box saves it: see the "change" listener). */
  const PRICES = !!view.dataset.prices, PRICE_URL = view.dataset.priceUrl || "";
  const priceText = v => v == null ? "" : v.toFixed(2);
  function listHTML(res) {
    /* The PDF holds exactly the rows shown just now (the owner, 2026-11-18): the
       search, section and brand in force; with nothing filtered, the whole list.
       Without the Price column unless the viewer may see prices. */
    const part = res.length < P.length, only = part ? "only=" + encodeURIComponent(res.map(p => p.sku).join(",")) : "";
    const shown = part ? " (" + res.length + " shown)" : "";
    const pdf = view.dataset.pdfUrl, pdfs = !pdf || !res.length ? "" : '<span class="srow">' +
      (PRICES ? '<a class="btn sm" href="' + pdf + "?prices=1" + (only && "&" + only) + '">Download PDF' + shown + '</a><a class="btn sm" href="' + pdf + (only && "?" + only) + '">PDF without prices' + shown + "</a>"
              : '<a class="btn sm" href="' + pdf + (only && "?" + only) + '">Download PDF' + shown + "</a>") + "</span>";
    /* Admins: the page that takes a supplier's newer list (a PDF). */
    const up = view.dataset.uploadUrl ? '<a class="btn sm" href="' + view.dataset.uploadUrl + '">Upload a new list</a>' : "";
    let h = '<div class="count"><span><b>' + res.length + "</b> of " + P.length + " items</span>" + pdfs + up + "</div>";
    if (nFilters()) {
      h += '<div class="chips" id="active">';
      for (const k in S.f) for (const v of S.f[k]) h += '<button class="chip x" data-act="unf" data-f="' + k + '" data-v="' + esc(v) + '" aria-label="Remove filter ' + esc(v) + '">' + esc(chipLabel(k, v)) + " ×</button>";
      h += "</div>";
    }
    if (!P.length) return h + '<div class="empty"><b>No items are listed here yet.</b></div>';
    if (!res.length) return h + '<div class="empty"><b>No items match.</b><br>Change the search.</div>';
    const cols = 6 + (PRICES ? 1 : 0);
    h += '<div class="tw"><table class="sheet"><thead><tr><th></th><th>SKU</th><th>Description</th><th>UPC</th><th>Brand</th><th>Specs</th>' + (PRICES ? '<th class="num">Price</th>' : "") + "</tr></thead><tbody>";
    let sec = null;
    for (const p of res) {
      if (p.cat !== sec) { sec = p.cat; h += '<tr class="sec"><th colspan="' + cols + '">' + esc(sec || "Other") + "</th></tr>"; }
      const href = "/product/" + encodeURIComponent(p.sku);
      h += '<tr><td class="pic"><a href="' + href + '" tabindex="-1" aria-hidden="true">' + photo(p) + '</a></td><td class="mono">' + esc(p.sku) + '</td><td><a class="link" href="' + href + '">' + esc(p.name) + '</a></td><td class="mono">' + esc(p.upc) + "</td><td>" + esc(p.brand) + "</td><td>" + esc(p.size) + "</td>";
      if (PRICES) h += '<td class="num">' + (PRICE_URL
        ? '<input class="inp price" id="pr-' + sid(p.sku) + '" data-price="' + esc(p.sku) + '" inputmode="decimal" autocomplete="off" value="' + priceText(p.price) + '" aria-label="Price of ' + esc(p.name) + '">'
        : (p.price == null ? "" : "$" + priceText(p.price))) + "</td>";
      h += "</tr>";
    }
    return h + "</tbody></table></div>" + (PRICE_URL ? '<p class="meta" id="price-msg" role="status">Type a price and move off the box: it is saved at once. Only admins see prices.</p>' : "");
  }
  /* Save a typed price; the box turns green when it is stored, red when not. */
  async function savePrice(box) {
    const p = BY[box.dataset.price], msg = document.getElementById("price-msg");
    const body = new FormData();
    body.append("csrf", view.dataset.csrf); body.append("sku", p.sku); body.append("price", box.value);
    box.classList.remove("saved", "bad");
    let r = null;
    try { r = await (await fetch(PRICE_URL, {method: "POST", body, credentials: "same-origin"})).json(); } catch (e) { /* reported below */ }
    const now = document.getElementById(box.id) || box;    /* the page may have been redrawn meanwhile */
    if (r && r.ok) {
      p.price = r.price; now.value = priceText(r.price); now.classList.add("saved");
      if (msg) msg.textContent = "Saved: " + p.sku + " " + p.name + (r.price == null ? ", no price." : ", $" + priceText(r.price) + ".");
    } else {
      now.classList.add("bad");
      if (msg) msg.textContent = "NOT saved: " + p.sku + " " + p.name + ". " + ((r && r.error) || "The site did not answer; reload the page and try again.");
    }
  }

  /* ---------- render (keeps focus, caret and inner scroll positions) ---------- */
  function render() {
    const ae = document.activeElement, fid = ae && ae.id ? ae.id : "";
    const ss = ae && fid && "selectionStart" in ae ? [ae.selectionStart, ae.selectionEnd] : null;
    const keep = {};
    document.querySelectorAll(".opts,.bd,.chips[id]").forEach(e => { if (e.id) keep[e.id] = [e.scrollTop, e.scrollLeft]; });
    view.innerHTML = catalogHTML();
    let o = "";
    if (S.drawer && !S.wide) {
      const base = baseList(), n = base.filter(p => fMatch(p)).length;
      o = '<div class="overlay" data-act="closedrawer"><div class="drawer" role="dialog" aria-label="Filters"><div class="hd"><b>Filters</b>' + (nFilters() ? '<button class="link" data-act="clear">Clear all</button>' : "") + '</div><div class="bd" id="drawerbd">' + filtersHTML(base) + '</div><div class="ft"><span class="meta">' + n + ' products</span><button class="btn pri" data-act="closedrawer" data-x="1">Show products</button></div></div></div>';
    }
    ovl.innerHTML = o;
    document.body.style.overflow = o ? "hidden" : "";
    for (const id in keep) { const e = document.getElementById(id); if (e) { e.scrollTop = keep[id][0]; e.scrollLeft = keep[id][1]; } }
    if (fid) {
      const e = document.getElementById(fid);
      if (e) { e.focus({preventScroll: true}); if (ss && e.setSelectionRange) { try { e.setSelectionRange(ss[0], ss[1]); } catch (x) { /* some input types have no caret */ } } }
    }
    save();
  }
  function toggle(arr, v) { const i = arr.indexOf(v); if (i < 0) arr.push(v); else arr.splice(i, 1); }

  document.addEventListener("click", e => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    const d = b.dataset;
    switch (d.act) {
      case "menu": S.menu = d.m; S.sub = null; render(); break;
      case "sub": S.sub = d.s || null; render(); break;
      case "pick": S.f = blankF(); S.f[d.k] = [d.v]; S.menu = "all"; S.sub = null; S.openF[d.k] = true; render(); window.scrollTo(0, 0); break;
      case "drawer": S.drawer = true; render(); break;
      case "closedrawer": if (e.target === b || d.x) { S.drawer = false; render(); } break;
      case "clear": S.f = blankF(); render(); break;
      case "unf": toggle(S.f[d.f], d.v); render(); break;
    }
  });
  document.addEventListener("input", e => { if (e.target.dataset && e.target.dataset.in === "q") { S.q = e.target.value; render(); } });
  document.addEventListener("change", e => {
    const t = e.target;
    if (t.dataset && t.dataset.price) { savePrice(t); return; }
    if (!(t.dataset && t.dataset.f)) return;
    toggle(S.f[t.dataset.f], t.dataset.v);
    render();
  });
  document.addEventListener("toggle", e => { const k = e.target.dataset && e.target.dataset.fg; if (k) { S.openF[k] = e.target.open; save(); } }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && S.drawer) { S.drawer = false; render(); } });
  document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.dataset && e.target.dataset.price) e.target.blur(); });
  wideQuery.addEventListener("change", e => { S.wide = e.matches; if (S.wide) S.drawer = false; render(); });
  window.addEventListener("pagehide", save);

  const startScroll = S.scroll;
  render();
  if (startScroll) window.scrollTo(0, startScroll);
})();
