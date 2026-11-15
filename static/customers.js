/* Customers screen: search by business name or city, and an All / Illinois /
   Florida switch (the QuickBooks company the customer lives in). */
"use strict";
(function () {
  const {esc, norm, wordsMatch, load, save} = window.Satla;
  const C = JSON.parse(document.getElementById("cdata").textContent);
  const view = document.getElementById("view");
  const KEY = "satla.customers.v1", STATES = [["all", "All"], ["IL", "Illinois"], ["FL", "Florida"]];
  C.forEach(c => { c.hay = norm(c.name + " " + c.city); });
  const saved = load(KEY) || {};
  const S = {q: saved.q || "", co: STATES.some(s => s[0] === saved.co) ? saved.co : "all"};

  function html() {
    const list = C.filter(c => (S.co === "all" || c.co === S.co) && wordsMatch(c.hay, S.q));
    let h = '<div class="srow"><input class="inp" id="cq" type="search" placeholder="Search customers by name or city" value="' + esc(S.q) + '" aria-label="Search customers" enterkeyhint="search"></div>' +
      '<div class="chips" role="group" aria-label="State">' + STATES.map(s => '<button class="chip" data-co="' + s[0] + '" aria-pressed="' + (S.co === s[0]) + '">' + s[1] + "</button>").join("") + "</div>" +
      '<div class="meta">' + list.length + " of " + C.length + " customers</div>";
    if (!C.length) return h + '<div class="empty"><b>No customers have been read yet.</b><br>They are read from QuickBooks every 30 minutes.</div>';
    if (!list.length) return h + '<div class="empty"><b>No customers match.</b><br>Check the spelling or switch the state.</div>';
    return h + '<div class="list">' + list.map(c => '<a class="rowbtn" href="/customer/' + c.co + "/" + encodeURIComponent(c.id) + '"><b>' + esc(c.name) + '</b><span class="meta">' + esc([c.city, c.st].filter(Boolean).join(", ") || "No address in QuickBooks") + '</span><span class="end"><span class="st">' + c.co + "</span></span></a>").join("") + "</div>";
  }
  function render() {
    const ae = document.activeElement, keepFocus = ae && ae.id === "cq", caret = keepFocus ? [ae.selectionStart, ae.selectionEnd] : null;
    view.innerHTML = html();
    if (keepFocus) { const e = document.getElementById("cq"); e.focus({preventScroll: true}); try { e.setSelectionRange(caret[0], caret[1]); } catch (x) { /* no caret */ } }
    remember();
  }
  function remember() { save(KEY, {q: S.q, co: S.co, scroll: window.scrollY}); }
  document.addEventListener("input", e => { if (e.target.id === "cq") { S.q = e.target.value; render(); } });
  document.addEventListener("click", e => { const b = e.target.closest("[data-co]"); if (b) { S.co = b.dataset.co; render(); } });
  window.addEventListener("pagehide", remember);
  render();
  if (saved.scroll) window.scrollTo(0, saved.scroll);
})();
