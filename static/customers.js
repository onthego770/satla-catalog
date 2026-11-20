/* Customers screen: search by business name or city. The page holds one state's
   customers: the state the header switch is on (for a salesman, only their own).
   Each row shows how long ago the customer last ordered and, when the customer
   is past its usual gap between orders, a mark (worked out on the server:
   catalog_insight.py). "Needs attention first" puts those on top. */
"use strict";
(function () {
  const {esc, norm, wordsMatch, load, save} = window.Satla;
  const C = JSON.parse(document.getElementById("cdata").textContent);
  const view = document.getElementById("view");
  const KEY = "satla.customers.v2." + document.body.dataset.state;
  C.forEach(c => { c.hay = norm(c.name + " " + c.city); });
  const saved = load(KEY) || {};
  const S = {q: saved.q || "", sort: saved.sort === "due" ? "due" : "az"};
  const WORDS = JSON.parse(view.dataset.words || "{}");
  const ago = d => d === 0 ? "today" : d === 1 ? "yesterday" : d < 60 ? d + " days ago" : d < 730 ? Math.round(d / 30.44) + " months ago" : "over 2 years ago";
  /* overdue, then due soon, then lapsed, then on track, then no orders; inside each, the
     most recent buyer first (a weekly customer two weeks late comes before a yearly one) */
  const byNeed = (a, b) => (a.rank == null ? 9 : a.rank) - (b.rank == null ? 9 : b.rank) || (a.days || 0) - (b.days || 0) || a.name.localeCompare(b.name);
  function end(c) {
    if (c.days == null) return '<span class="end meta">No orders in 2 years</span>';
    return '<span class="end">' + (c.flag && c.flag !== "ok" ? '<span class="tag s-' + c.flag + '">' + esc(WORDS[c.flag]) + "</span><br>" : "") + '<span class="meta">Last order ' + ago(c.days) + "</span></span>";
  }

  function html() {
    const list = C.filter(c => wordsMatch(c.hay, S.q));
    if (S.sort === "due") list.sort(byNeed);
    let h = '<div class="srow"><input class="inp" id="cq" type="search" placeholder="Search customers by name or city" value="' + esc(S.q) + '" aria-label="Search customers" enterkeyhint="search"></div>' +
      '<div class="count"><span class="meta">' + list.length + " of " + C.length + ' customers</span><span class="chips" role="group" aria-label="Order of the list">' +
      [["az", "A to Z"], ["due", "Needs attention first"]].map(k => '<button class="chip" type="button" data-sort="' + k[0] + '" aria-pressed="' + (S.sort === k[0]) + '">' + k[1] + "</button>").join("") + "</span></div>";
    /* a salesman sees only the customers with their name in QuickBooks' SALESMAN field */
    if (!C.length && view.dataset.mine) return h + '<div class="empty"><b>No customers in this state are under your name.</b><br>A customer shows here when its SALESMAN field in QuickBooks is your name. Ask the office if one is missing.</div>';
    if (!C.length) return h + '<div class="empty"><b>No customers have been read yet.</b><br>They are read from QuickBooks every 30 minutes.</div>';
    if (!list.length) return h + '<div class="empty"><b>No customers match.</b><br>Check the spelling.</div>';
    return h + '<div class="list">' + list.map(c => '<a class="rowbtn" href="/customer/' + c.co + "/" + encodeURIComponent(c.id) + '"><b>' + esc(c.name) + '</b><span class="meta">' + esc([c.city, c.st].filter(Boolean).join(", ") || "No address in QuickBooks") + "</span>" + end(c) + "</a>").join("") + "</div>";
  }
  function render() {
    const ae = document.activeElement, keepFocus = ae && ae.id === "cq", caret = keepFocus ? [ae.selectionStart, ae.selectionEnd] : null;
    view.innerHTML = html();
    if (keepFocus) { const e = document.getElementById("cq"); e.focus({preventScroll: true}); try { e.setSelectionRange(caret[0], caret[1]); } catch (x) { /* no caret */ } }
    remember();
  }
  function remember() { save(KEY, {q: S.q, sort: S.sort, scroll: window.scrollY}); }
  document.addEventListener("click", e => { const t = e.target.closest("button[data-sort]"); if (t) { S.sort = t.dataset.sort; render(); } });
  document.addEventListener("input", e => { if (e.target.id === "cq") { S.q = e.target.value; render(); } });
  window.addEventListener("pagehide", remember);
  render();
  if (saved.scroll) window.scrollTo(0, saved.scroll);
})();
