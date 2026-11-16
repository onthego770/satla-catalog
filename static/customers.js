/* Customers screen: search by business name or city. The page holds one state's
   customers: the state the header switch is on. */
"use strict";
(function () {
  const {esc, norm, wordsMatch, load, save} = window.Satla;
  const C = JSON.parse(document.getElementById("cdata").textContent);
  const view = document.getElementById("view");
  const KEY = "satla.customers.v2." + document.body.dataset.state;
  C.forEach(c => { c.hay = norm(c.name + " " + c.city); });
  const saved = load(KEY) || {};
  const S = {q: saved.q || ""};

  function html() {
    const list = C.filter(c => wordsMatch(c.hay, S.q));
    let h = '<div class="srow"><input class="inp" id="cq" type="search" placeholder="Search customers by name or city" value="' + esc(S.q) + '" aria-label="Search customers" enterkeyhint="search"></div>' +
      '<div class="meta">' + list.length + " of " + C.length + " customers</div>";
    if (!C.length) return h + '<div class="empty"><b>No customers have been read yet.</b><br>They are read from QuickBooks every 30 minutes.</div>';
    if (!list.length) return h + '<div class="empty"><b>No customers match.</b><br>Check the spelling.</div>';
    return h + '<div class="list">' + list.map(c => '<a class="rowbtn" href="/customer/' + c.co + "/" + encodeURIComponent(c.id) + '"><b>' + esc(c.name) + '</b><span class="meta">' + esc([c.city, c.st].filter(Boolean).join(", ") || "No address in QuickBooks") + '</span></a>').join("") + "</div>";
  }
  function render() {
    const ae = document.activeElement, keepFocus = ae && ae.id === "cq", caret = keepFocus ? [ae.selectionStart, ae.selectionEnd] : null;
    view.innerHTML = html();
    if (keepFocus) { const e = document.getElementById("cq"); e.focus({preventScroll: true}); try { e.setSelectionRange(caret[0], caret[1]); } catch (x) { /* no caret */ } }
    remember();
  }
  function remember() { save(KEY, {q: S.q, scroll: window.scrollY}); }
  document.addEventListener("input", e => { if (e.target.id === "cq") { S.q = e.target.value; render(); } });
  window.addEventListener("pagehide", remember);
  render();
  if (saved.scroll) window.scrollTo(0, saved.scroll);
})();
