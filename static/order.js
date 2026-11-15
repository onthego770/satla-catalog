/* New Order and Review order (wireframe screens 7 and 8), for one customer.
   Rules, as approved:
   - cases only; part of a case is a decimal such as 0.5; a product is on the
     order when its cases are above zero;
   - the price per case starts at what this customer paid last time, otherwise
     at the regular QuickBooks price; the salesman can type over it, and a
     picker offers Regular and Previous;
   - a product with no regular price in the customer's QuickBooks company
     cannot be added;
   - Copy Order copies products and quantities, not prices, and opens on Review;
   - nothing is saved on the server: the order lives in this browser tab until
     Send, and leaving with lines on it asks first. */
"use strict";
(function () {
  const {esc, norm, wordsMatch, load, save, photo, money} = window.Satla;
  const DATA = JSON.parse(document.getElementById("odata").textContent);
  const P = DATA.products, INFO = DATA.info;
  const bySku = Object.fromEntries(P.map(p => [p.sku, p]));
  const view = document.getElementById("view"), ovl = document.getElementById("overlay");
  const KEY = "satla.order.v1." + INFO.co + "." + INFO.id;
  const CATS = [["all", "All"], ["Wine", "Wine"], ["Spirits", "Spirits"], ["Liqueur & Aperitif", "Liqueurs & Aperitifs"], ["Sake", "Sake"], ["Ready-to-Drink", "Ready-to-Drink"]];
  const SHOW = 40;
  const sid = s => String(s).replace(/[^a-zA-Z0-9]+/g, "_");
  const r2 = n => Math.round(n * 100) / 100;
  const same = (a, b) => Math.abs(a - b) < 0.005;
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
  P.forEach(p => { p.hay = norm([p.name, p.brand, p.grape, p.country, p.region, p.sku].join(" ")); });

  /* lines: {sku: {c: cases, p: price chosen or typed (absent = the default)}} */
  const S = {lines: {}, note: "", q: "", cat: "all", screen: "order", copied: null, skipped: [], dialog: false, leaving: false};

  const saved = load(KEY);
  if (saved && saved.lines) {
    for (const [sku, l] of Object.entries(saved.lines)) if (bySku[sku] && bySku[sku].reg != null) S.lines[sku] = l;
    S.note = saved.note || ""; S.copied = saved.copied || null; S.skipped = saved.skipped || [];
  }
  if (INFO.copy) {                       /* Copy Order replaces whatever was on the screen */
    S.lines = {}; S.note = ""; S.copied = INFO.copy.doc; S.skipped = [];
    for (const l of INFO.copy.lines) {
      const p = bySku[l.sku];
      if (p && p.reg != null && l.qty > 0) (S.lines[p.sku] = S.lines[p.sku] || {c: 0}).c = r2(S.lines[p.sku].c + l.qty);
      else if (l.name || l.sku) S.skipped.push(l.name || l.sku);
    }
    S.screen = "review";
    history.replaceState(null, "", location.pathname);      /* a reload must not copy again */
  }
  function keep() { save(KEY, {lines: S.lines, note: S.note, copied: S.copied, skipped: S.skipped}); }

  /* ---------- pricing ---------- */
  const startPrice = p => p.prev ? p.prev.p : p.reg;
  const linePrice = p => { const l = S.lines[p.sku]; return l && l.p != null ? l.p : startPrice(p); };
  const source = p => { const pc = linePrice(p); return p.prev && same(pc, p.prev.p) ? "prev" : same(pc, p.reg) ? "reg" : "typed"; };
  const SRC = {prev: "previous price", reg: "regular price", typed: "typed price"};
  const olines = () => P.filter(p => S.lines[p.sku] && S.lines[p.sku].c > 0).map(p => {
    const c = S.lines[p.sku].c, pc = linePrice(p);
    return {p: p, c: c, pc: pc, src: SRC[source(p)], t: r2(c * pc)};
  });
  const ototal = ls => ls.reduce((s, l) => s + l.t, 0);

  /* ---------- pieces ---------- */
  function stepper(p) {
    const c = (S.lines[p.sku] || {c: 0}).c, id = sid(p.sku);
    return '<span class="step">Cases<span class="s"><button type="button" data-step="-1" data-sku="' + esc(p.sku) + '" aria-label="Fewer cases">−</button>' +
      '<input type="number" min="0" step="0.5" inputmode="decimal" id="n-' + id + '" data-qty="' + esc(p.sku) + '" value="' + c + '" aria-label="Cases of ' + esc(p.name) + '">' +
      '<button type="button" data-step="1" data-sku="' + esc(p.sku) + '" aria-label="More cases">+</button></span></span>';
  }
  function pricebox(p) {
    const cur = linePrice(p), sel = source(p), id = sid(p.sku);
    return '<span class="pricebox"><label for="p-' + id + '">Price per case</label>' +
      '<input class="pin" id="p-' + id + '" inputmode="decimal" data-price="' + esc(p.sku) + '" value="' + cur.toFixed(2) + '">' +
      '<select class="psel" id="ps-' + id + '" data-psel="' + esc(p.sku) + '" aria-label="Choose the regular or the previous price">' +
      (p.prev ? '<option value="prev"' + (sel === "prev" ? " selected" : "") + ">Previous " + money(p.prev.p) + " · " + esc(p.prev.d) + "</option>" : "") +
      '<option value="reg"' + (sel === "reg" ? " selected" : "") + ">Regular " + money(p.reg) + "</option>" +
      (sel === "typed" ? '<option value="typed" selected>Typed ' + money(cur) + "</option>" : "") + "</select></span>" +
      '<span class="meta" style="display:block;margin-top:4px">On hand: ' + (p.hand == null ? "unavailable" : esc(p.hand) + " cases") + "</span>";
  }
  function oline(p) {
    const ok = p.reg != null;
    return '<div class="oline' + (ok ? "" : " off") + '">' + photo(p.sku) + "<div><h4>" + esc(p.name) + '</h4><span class="meta">' + esc([p.sku, p.size].filter(Boolean).join(" · ")) + "</span><br>" +
      (ok ? pricebox(p) : '<span class="price open">No ' + esc(INFO.state) + " price in QuickBooks: cannot be ordered</span>") + "</div>" +
      (ok ? '<div class="qty">' + stepper(p) + "</div>" : "") + "</div>";
  }
  const who = '<span class="meta">' + esc(INFO.name) + ' <span class="st">' + INFO.co + "</span></span>";

  /* ---------- screens ---------- */
  function orderScreen() {
    const res = P.filter(p => (S.cat === "all" || p.cat === S.cat) && wordsMatch(p.hay, S.q)), show = res.slice(0, SHOW), ls = olines();
    let h = '<div class="subbar"><div><button class="link" type="button" data-act="cancel">‹ Cancel</button><h2>New Order</h2>' + who + "</div></div>" +
      '<div class="wrap"><div class="pad"><div class="ord"><div class="col">' +
      '<div class="srow"><input class="inp" id="oq" type="search" placeholder="Search products to add" value="' + esc(S.q) + '" aria-label="Search products to add" enterkeyhint="search"></div>' +
      '<div class="chips" role="group" aria-label="Category">' + CATS.map(k => '<button class="chip" type="button" data-cat="' + esc(k[0]) + '" aria-pressed="' + (S.cat === k[0]) + '">' + k[1] + "</button>").join("") + "</div>" +
      '<div class="meta">Showing ' + show.length + " of " + res.length + " products" + (res.length > SHOW ? ". Search to narrow the list." : "") + "</div><div>";
    if (!res.length) h += '<div class="empty"><b>No products match.</b><br>Change the search or the category.</div>';
    h += show.map(oline).join("") + "</div></div>" +
      '<div class="box side"><h3>This order</h3>' + (ls.length ? ls.map(l => '<div class="sline"><span>' + esc(l.p.name) + '<br><span class="meta">' + plural(l.c, "case", "cases") + '</span></span><span class="num">' + money(l.t) + "</span></div>").join("") : '<p class="meta">No products added yet.</p>') + "</div>" +
      "</div></div></div>" +
      '<div class="foot"><span class="t">' + plural(ls.length, "line", "lines") + " · <b>" + money(ototal(ls)) + '</b></span><button class="btn pri" type="button" data-act="review"' + (ls.length ? "" : " disabled") + ">Review order</button></div>";
    return h;
  }
  function reviewScreen() {
    const ls = olines();
    let h = '<div class="subbar"><div><button class="link" type="button" data-act="add">‹ Add more products</button><h2>Review order</h2>' + who + "</div>" +
      '<button class="link" type="button" data-act="cancel">Cancel order</button></div><div class="wrap"><div class="pad">';
    if (S.copied) {
      h += '<div class="box" style="border-style:dashed"><span><b>Copied from invoice ' + esc(S.copied) + ".</b> Same products and quantities. Each price is today's default and can be changed.</span>" +
        (S.skipped.length ? "<span>" + plural(S.skipped.length, "line was", "lines were") + " left out because the product is not in the catalog or cannot be ordered: " + esc(S.skipped.join("; ")) + ".</span>" : "") + "</div>";
    }
    h += "<div>" + ls.map(l => '<div class="oline">' + photo(l.p.sku) + "<div><h4>" + esc(l.p.name) + '</h4><span class="meta">' + esc([l.p.sku, l.p.size].filter(Boolean).join(" · ")) + "</span><br>" +
      '<span class="price">' + money(l.pc) + " per case, " + l.src + " · Line total <b>" + money(l.t) + '</b> · <button class="link" type="button" data-rm="' + esc(l.p.sku) + '">Remove</button></span></div>' +
      '<div class="qty">' + stepper(l.p) + "</div></div>").join("") + "</div>";
    if (!ls.length) h += '<div class="empty"><b>The order is empty.</b><br>Go back and add products.</div>';
    h += '<label class="field" for="onote"><span>Note to the office (optional)</span><textarea class="inp" id="onote" rows="2" maxlength="2000" placeholder="Delivery instructions, PO number">' + esc(S.note) + "</textarea></label>" +
      '<div class="box"><h3>Where this order goes</h3><dl class="kv"><dt>To</dt><dd>' + esc(INFO.to) + "</dd><dt>Copy</dt><dd>" + esc(INFO.me) + " (you)</dd><dt>Saved?</dt><dd>No. The email is the order.</dd></dl></div></div></div>" +
      '<div class="foot"><span class="t">Total <b>' + money(ototal(ls)) + '</b></span><button class="btn pri" type="button" data-act="send"' + (ls.length ? "" : " disabled") + ">Send order</button></div>";
    return h;
  }

  function render() {
    const ae = document.activeElement, fid = ae && ae.id, caret = fid === "oq" ? [ae.selectionStart, ae.selectionEnd] : null;
    dirty = false;
    view.innerHTML = S.screen === "review" ? reviewScreen() : orderScreen();
    ovl.innerHTML = S.dialog ? '<div class="overlay"><div class="dialog" role="alertdialog" aria-label="Discard this order?"><b>Discard this order?</b><span>It has not been sent and it is not saved. Leaving now loses it.</span><div class="acts"><button class="btn" type="button" data-act="keep">Keep working</button><button class="btn pri" type="button" data-act="discard">Discard</button></div></div></div>' : "";
    if (fid) { const e = document.getElementById(fid); if (e) { e.focus({preventScroll: true}); if (caret) try { e.setSelectionRange(caret[0], caret[1]); } catch (x) { /* no caret */ } } }
    keep();
  }
  function go(screen) { S.screen = screen; render(); window.scrollTo(0, 0); }
  const line = sku => S.lines[sku] || (S.lines[sku] = {c: 0});

  document.addEventListener("click", e => {
    const t = e.target.closest("button"); if (!t) return;
    const d = t.dataset;
    if (d.step) { const l = line(d.sku); l.c = Math.max(0, r2(l.c + (+d.step))); render(); }
    else if (d.rm) { delete S.lines[d.rm]; render(); }
    else if (d.cat) { S.cat = d.cat; render(); }
    else if (d.act === "review") go("review");
    else if (d.act === "add") go("order");
    else if (d.act === "cancel") { if (olines().length) { S.dialog = true; render(); } else leave(); }
    else if (d.act === "keep") { S.dialog = false; render(); }
    else if (d.act === "discard") leave();
    else if (d.act === "send") send(t);
  });
  document.addEventListener("input", e => {
    const t = e.target;
    if (t.id === "oq") { S.q = t.value; render(); }
    else if (t.id === "onote") { S.note = t.value; keep(); }
  });
  /* Cases and prices are taken when the field is left, so typing "0.5" is not
     interrupted half way. The redraw that follows is described at settle(). */
  document.addEventListener("change", e => {
    const t = e.target, d = t.dataset || {};
    if (d.qty) { line(d.qty).c = Math.max(0, r2(+t.value || 0)); settle(); }
    else if (d.price) {
      const v = parseFloat(String(t.value).replace(/[^0-9.]/g, ""));
      if (isFinite(v) && v >= 0) line(d.price).p = r2(v);
      settle();
    } else if (d.psel) {
      const p = bySku[d.psel];
      if (t.value === "reg") line(p.sku).p = p.reg; else if (t.value === "prev" && p.prev) line(p.sku).p = p.prev.p;
      render();
    }
  });

  /* A field's change arrives when the finger goes down on the next thing. Redrawing
     at that moment would replace the button being pressed and lose the tap, so the
     redraw waits until the finger is up. */
  let down = false, dirty = false;
  function settle() {
    keep();
    if (down) dirty = true;
    /* Not at once: when the change comes from moving to the next field (Tab, or the
       keyboard's Next), wait until that field has the cursor so the redraw can put
       the cursor back in it. */
    else setTimeout(render, 0);
  }
  document.addEventListener("pointerdown", () => { down = true; }, true);
  ["pointerup", "pointercancel"].forEach(n => document.addEventListener(n, () => {
    down = false;
    setTimeout(() => { if (dirty) { dirty = false; render(); } }, 0);
  }, true));

  function leave() {
    S.leaving = true;
    try { sessionStorage.removeItem(KEY); } catch (x) { /* nothing stored */ }
    location.href = INFO.back;
  }
  function send(button) {
    const ls = olines(); if (!ls.length) return;
    button.disabled = true; button.textContent = "Sending…";
    S.leaving = true;
    document.getElementById("sendorder").value = JSON.stringify({nonce: INFO.nonce, note: S.note, lines: ls.map(l => ({sku: l.p.sku, cases: l.c, price: l.pc}))});
    document.getElementById("sendform").submit();
  }
  window.addEventListener("beforeunload", e => { if (!S.leaving && olines().length) { e.preventDefault(); e.returnValue = ""; } });
  /* Coming back with the browser's Back button after a send: start clean. */
  window.addEventListener("pageshow", e => { if (e.persisted) location.reload(); });

  render();
})();
