/* The edit-item page (admins): turn any picture the admin picks into the two
   catalog photos, in the browser, to the approved standard: a white 3:4 picture
   with the product centred and filling 90% of the height (or 90% of the width
   when it is wide), 600x800 for the grid and 900x1200 for the product page,
   as WebP. The server only checks and stores them; it has no image library.

   Also the "Fill from Kosher Wine World" box: the server reads that store's
   product page (catalog_source.py) and this page puts what it found into the
   form: blank fields are filled, the picture goes through the same photo tool,
   and a button offers anything that would replace what is already there.
   Nothing is saved until the admin presses Save. */
"use strict";
(function () {
  const box = document.getElementById("photobox");
  if (!box) return;
  const pick = document.getElementById("photo-src"), msg = document.getElementById("photo-msg");
  const now = document.getElementById("photo-now"), img = now.querySelector("img");
  const out = {grid: document.getElementById("photo-grid"), detail: document.getElementById("photo-detail")};
  const remove = document.querySelector('input[name="photo_remove"]');
  const FILL = 0.9, WHITE = 240, WORK = 1600, QUALITY = 0.85;
  const say = (text, bad) => { msg.textContent = text; msg.classList.toggle("open", !!bad); };
  const clear = () => { for (const k in out) out[k].value = ""; };

  /* Find the product in a picture: {x, y, w, h} in the picture's own pixels, the
     box around the product only, or null for a blank picture.

     Store pictures often carry things that are not the product: a watermark
     repeated in the corners ("Koby"), score badges beside the bottle, a title
     above it. Measured with them, the bottle comes out small. So the picture
     is split into its separate pieces (touching non-white areas); the largest
     piece is the product, and a piece is DROPPED when it is small (under a
     fifth of the product's area) AND lies wholly outside the product's own box
     (with a margin), or when it is lettering printed just outside the product.
     A box beside the bottle, a second bottle, a cap or a label that reads as
     its own piece are all kept. When something was dropped the result carries
     `mask` (a canvas at scale `k` that is opaque over the kept pieces), which
     render() uses to paint the dropped pieces out, and `dropped`, their count. */
  function productBox(bmp) {
    const k = Math.min(1, WORK / Math.max(bmp.width, bmp.height));
    const w = Math.max(1, Math.round(bmp.width * k)), h = Math.max(1, Math.round(bmp.height * k));
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const x = c.getContext("2d", {willReadFrequently: true});
    x.fillStyle = "#fff"; x.fillRect(0, 0, w, h); x.drawImage(bmp, 0, 0, w, h);
    const d = x.getImageData(0, 0, w, h).data, n = w * h;
    const ink = new Uint8Array(n);
    for (let i = 0, j = 0; i < n; i++, j += 4) if (d[j] < WHITE || d[j + 1] < WHITE || d[j + 2] < WHITE) ink[i] = 1;
    /* Grow the ink a little, so the parts of one object join up (a cap above a
       pale neck, the letters of a label) and so the mask clears the edges. */
    const r = Math.max(2, Math.round(Math.max(w, h) * 0.006)), wide = new Uint8Array(n), grown = new Uint8Array(n);
    for (let y = 0; y < h; y++) for (let xx = 0, run = -1; xx < w + r; xx++) {
      if (xx < w && ink[y * w + xx]) run = xx + r;
      if (xx - r >= 0 && xx - r < w && run >= xx - r) wide[y * w + xx - r] = 1;
      if (xx < w && run >= xx) wide[y * w + xx] = 1;
    }
    for (let xx = 0; xx < w; xx++) for (let y = 0, run = -1; y < h + r; y++) {
      if (y < h && wide[y * w + xx]) run = y + r;
      if (y - r >= 0 && y - r < h && run >= y - r) grown[(y - r) * w + xx] = 1;
      if (y < h && run >= y) grown[y * w + xx] = 1;
    }
    /* Label the pieces of the grown ink; measure each by its real ink. */
    const label = new Int32Array(n), pieces = [], stack = new Int32Array(n);
    for (let start = 0; start < n; start++) {
      if (!grown[start] || label[start]) continue;
      const id = pieces.length + 1, p = {area: 0, x0: w, x1: -1, y0: h, y1: -1};
      let top = 0; stack[top++] = start; label[start] = id;
      while (top) {
        const i = stack[--top], px = i % w, py = (i - px) / w;
        if (ink[i]) { p.area++; if (px < p.x0) p.x0 = px; if (px > p.x1) p.x1 = px; if (py < p.y0) p.y0 = py; if (py > p.y1) p.y1 = py; }
        if (px > 0 && grown[i - 1] && !label[i - 1]) { label[i - 1] = id; stack[top++] = i - 1; }
        if (px < w - 1 && grown[i + 1] && !label[i + 1]) { label[i + 1] = id; stack[top++] = i + 1; }
        if (py > 0 && grown[i - w] && !label[i - w]) { label[i - w] = id; stack[top++] = i - w; }
        if (py < h - 1 && grown[i + w] && !label[i + w]) { label[i + w] = id; stack[top++] = i + w; }
      }
      pieces.push(p);
    }
    const real = pieces.filter(p => p.area > 1);            /* more than a stray speck */
    if (!real.length) return null;
    const main = real.reduce((a, p) => p.area > a.area ? p : a);
    const mx = (main.x1 - main.x0 + 1) * 0.06, my = (main.y1 - main.y0 + 1) * 0.06;
    const outside = p => p.x1 < main.x0 - mx || p.x0 > main.x1 + mx || p.y1 < main.y0 - my || p.y0 > main.y1 + my;
    /* Lettering that sits just outside the product (a year or a title printed
       above it): tiny, thin strokes rather than a solid shape such as a cap. */
    const lettering = p => p.area < main.area * 0.02 && p.area < (p.x1 - p.x0 + 1) * (p.y1 - p.y0 + 1) * 0.5 &&
      (p.x1 < main.x0 || p.x0 > main.x1 || p.y1 < main.y0 || p.y0 > main.y1);
    let x0 = w, x1 = -1, y0 = h, y1 = -1, dropped = 0;
    pieces.forEach(p => {
      p.keep = p === main || (p.area > 1 && !(p.area < main.area * 0.2 && outside(p)) && !lettering(p));
      if (!p.keep) { if (p.area > 1) dropped++; return; }
      if (p.x0 < x0) x0 = p.x0; if (p.x1 > x1) x1 = p.x1; if (p.y0 < y0) y0 = p.y0; if (p.y1 > y1) y1 = p.y1;
    });
    const out = {x: x0 / k, y: y0 / k, w: (x1 - x0 + 1) / k, h: (y1 - y0 + 1) / k, k, dropped, mask: null};
    if (dropped) {
      const m = document.createElement("canvas"); m.width = w; m.height = h;
      const mc = m.getContext("2d"), md = mc.createImageData(w, h);
      for (let i = 0; i < n; i++) if (label[i] && pieces[label[i] - 1].keep) md.data[i * 4 + 3] = 255;
      mc.putImageData(md, 0, 0);
      out.mask = m;
    }
    return out;
  }

  function render(bmp, b, size) {
    const [W, H] = size.split("x").map(Number);
    const c = document.createElement("canvas"); c.width = W; c.height = H;
    const x = c.getContext("2d", {alpha: false});
    x.fillStyle = "#fff"; x.fillRect(0, 0, W, H);
    x.imageSmoothingEnabled = true; x.imageSmoothingQuality = "high";
    const s = Math.min(FILL * H / b.h, FILL * W / b.w), dw = b.w * s, dh = b.h * s, dx = (W - dw) / 2, dy = (H - dh) / 2;
    if (!b.mask) x.drawImage(bmp, b.x, b.y, b.w, b.h, dx, dy, dw, dh);
    else {                                  /* the product alone: everything that was dropped is painted out */
      const o = document.createElement("canvas"); o.width = W; o.height = H;
      const ox = o.getContext("2d");
      ox.imageSmoothingEnabled = true; ox.imageSmoothingQuality = "high";
      ox.drawImage(bmp, b.x, b.y, b.w, b.h, dx, dy, dw, dh);
      ox.globalCompositeOperation = "destination-in";
      ox.drawImage(b.mask, b.x * b.k, b.y * b.k, b.w * b.k, b.h * b.k, dx, dy, dw, dh);
      x.drawImage(o, 0, 0);
    }
    return new Promise(done => c.toBlob(done, "image/webp", QUALITY));
  }

  /* Make the two catalog photos from a picture (a file the admin picked, or one
     fetched from the store) and show the preview. True when it worked. */
  async function usePicture(blob) {
    clear();
    say("Preparing the photo…");
    let bmp;
    try { bmp = await createImageBitmap(blob); }
    catch (e) { say("The browser could not read that file as a picture. Try a JPG, PNG or WebP file.", true); return false; }
    const b = productBox(bmp);
    if (!b) { say("That picture is blank.", true); return false; }
    const made = {};
    for (const kind in out) {
      const webp = await render(bmp, b, box.dataset[kind]);
      if (!webp || webp.type !== "image/webp") {
        clear();
        say("This browser cannot make the catalog's photo format. Open this page in Chrome, Edge or Firefox to change a photo.", true);
        return false;
      }
      made[kind] = webp;
    }
    for (const kind in out) {
      const dt = new DataTransfer();
      dt.items.add(new File([made[kind]], kind + ".webp", {type: "image/webp"}));
      out[kind].files = dt.files;
    }
    img.src = URL.createObjectURL(made.detail);
    now.classList.remove("noimg");
    if (remove) remove.checked = false;
    box.dataset.dropped = b.dropped;
    say("This is how the new photo will look" + (b.dropped ? " (a watermark or other marks around the product were taken out)" : "") + ". Press Save to keep it; choose another picture to try again.");
    return true;
  }

  pick.addEventListener("change", async () => {
    const file = pick.files[0];
    if (!file) return clear();
    if (!await usePicture(file)) pick.value = "";
  });
  if (remove) remove.addEventListener("change", () => {
    if (remove.checked && out.grid.files.length) { pick.value = ""; clear(); say("The new picture was dropped. The photo will be removed when you press Save."); }
  });

  /* --- Fill from Kosher Wine World --- */
  const src = document.getElementById("sourcebox");
  if (!src) return;
  const url = document.getElementById("source-url"), go = document.getElementById("source-go");
  const smsg = document.getElementById("source-msg"), acts = document.getElementById("source-acts");
  const tell = (text, bad) => { smsg.textContent = text; smsg.classList.toggle("open", !!bad); };
  const field = name => document.getElementById("f-" + name);
  /* What the store can give, in the order the form shows it: [field, what to call it]. */
  const THEIRS = [["brand", "brand"], ["category", "category"], ["type", "type"], ["sweetness", "sweetness"], ["grape", "grape"], ["country", "country"], ["region", "region"],
    ["abv", "ABV"], ["vintage", "vintage"], ["size", "bottle size"], ["mevushal", "Mevushal"], ["kfp", "Kosher for Passover"], ["organic", "Organic"], ["certifier", "certifier"], ["description", "description"]];
  const button = (label, fn) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn sm"; b.textContent = label;
    b.addEventListener("click", async () => { b.disabled = true; await fn(); b.remove(); });
    acts.appendChild(b);
  };
  async function theirPhoto(address) {
    try {
      const r = await fetch(address, {credentials: "same-origin"});
      if (!r.ok) throw new Error();
      pick.value = "";
      return await usePicture(await r.blob());
    } catch (e) { say("The picture could not be fetched from Kosher Wine World.", true); return false; }
  }
  async function fill() {
    const address = url.value.trim();
    if (!address) return tell("Paste the address of the product's page first.", true);
    go.disabled = true; acts.textContent = ""; tell("Reading the page…");
    let d;
    try {
      const body = new URLSearchParams({csrf: src.dataset.csrf, url: address, name: field("name").value});
      const r = await fetch(src.dataset.url, {method: "POST", body, credentials: "same-origin"});
      d = await r.json();
      if (!r.ok) throw new Error(d.error || "");
    } catch (e) {
      go.disabled = false;
      return tell(e.message || "The page could not be read. Check the address and try again.", true);
    }
    go.disabled = false;
    const done = [];
    /* A blank field is filled; a field that already holds something else gets a
       button that shows their value. The store's SKU is shown, never checked:
       the store often files a product under a different SKU of the same wine. */
    for (const [name, label] of THEIRS) {
      const f = field(name), theirs = d[name];
      if (!theirs || f.value.trim() === theirs) continue;
      if (!f.value.trim()) { f.value = theirs; done.push(label); }
      else button("Use their " + label + (name === "description" ? "" : ": " + theirs), () => { f.value = theirs; });
    }
    if (d.name && field("name").value.trim() !== d.name) button("Use their name: " + d.name, () => { field("name").value = d.name; });
    if (d.image) {
      if (now.classList.contains("noimg")) { if (await theirPhoto(d.image)) done.push("photo"); }
      else button("Use their photo", () => theirPhoto(d.image));
    }
    let text = "Found: " + d.name + (d.sku ? " (their SKU " + d.sku + ")" : "") + ". ";
    text += done.length ? "Filled in: " + done.join(", ") + ". " : "Nothing was blank to fill in. ";
    const missing = [d.description ? "" : "description", d.image ? "" : "picture"].filter(Boolean);
    if (missing.length) text += "Their page has no " + missing.join(" or ") + ". ";
    if (acts.children.length) text += "The buttons below put their value in place of yours. ";
    text += "Check it, then press the button at the bottom to save.";
    tell(text, false);
  }
  go.addEventListener("click", fill);
  url.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); fill(); } });
})();
