/* Helpers shared by every page's script. Loaded from base.html. */
"use strict";
window.Satla = {
  /* Text made safe to put inside HTML. */
  esc: s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])),
  /* Lower case with accents removed, so "rose" finds "Rosé". */
  norm: s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(),
  /* True when every word typed appears in the prepared text `hay`. */
  wordsMatch: (hay, q) => window.Satla.norm(q).split(/\s+/).filter(Boolean).every(t => hay.includes(t)),
  /* Small per-tab memory, so Back returns to the same search and position.
     A private window may refuse storage; pages work without it. */
  load: key => { try { return JSON.parse(sessionStorage.getItem(key) || "null"); } catch (e) { return null; } },
  save: (key, value) => { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* see above */ } }
};
/* Show each "as of" time in the viewer's own time zone. */
document.querySelectorAll("time[datetime]").forEach(t => {
  const d = new Date(t.getAttribute("datetime"));
  if (!isNaN(d)) t.textContent = d.toLocaleString("en-US", {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
});
