"""Reading a product's public data from Kosher Wine World, to fill in a catalog
item (the owner, 2026-11-16: "can we add a url text box ... so we can scrape
the data?", then "What about kosherwineworld.com?" and the store's password).

Kosher Wine World is a Shopify store that carries Satla's products under
Satla's own SKUs. While the store is closed to the public it answers only
after its storefront password, which the owner gave; it is kept in the site's
private config file (~/python/config/catalog_config.json, key `kww_password`),
never in the code.

Only that store is read, and only its product pages, its product list and its
product pictures: the address an admin types is checked against PAGE_HOSTS /
IMAGE_HOSTS before anything is fetched, so the box cannot be used to make the
server call another address.

KosherWine.com pages are NOT read: that site refuses automated requests, and
this module does not try to get around that. Instead the admin opens the page
in their own browser and pastes it into the form (the owner, 2026-11-17, to
"link and paste": "Yes"); pasted() reads the paste. Only a product PICTURE is
fetched from KosherWine.com (its picture addresses answer a plain request).

A page from ANY other site can be pasted the same way (the owner, 2026-11-17:
"shouldn't I have a text box I can dump a screen paste into of any rando site
that I find"): pasted() then reads what it can recognise, and a picture's
address in the paste is fetched by one plain request (public https addresses
only; a site that refuses is not worked around).

The search (the owner, 2026-11-17: "check ... for the closest matches, and to
return and let me know which ones are best in which order") ranks the product
lists of Kosher Wine World and of Kosher Wine Direct (kosherwinedirect.com, the
owner, 2026-11-17: "add KosherWineDirect.com to the search"), which listing()
and listing_kwd() read and the refresh keeps in Catalog.db. Kosher Wine Direct
is a public Shopify store whose robots rules allow its product list; its pages
carry a labelled Details table (Producer, Country, Region, Varietal, Style,
Alcohol, Bottle size, Hashgacha, Mevushal, Kosher for Passover).

Standard library only (the web worker loads it). Nothing here touches
QuickBooks or MMK.
"""
import difflib
import html
import ipaddress
import http.cookiejar
import json
import re
import socket
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

STORE = "https://kosherwineworld.com"
PAGE_HOSTS = {"kosherwineworld.com", "www.kosherwineworld.com"}
IMAGE_HOSTS = PAGE_HOSTS | {"cdn.shopify.com"}
USER_AGENT = "satla-catalog-admin/1.0"
TIMEOUT = 20
MAX_IMAGE_BYTES = 15_000_000
IMAGE_WIDTH = 1600                     # ask the store's image server for this width
KWD_STORE = "https://kosherwinedirect.com"
KWD_HOSTS = {"kosherwinedirect.com", "www.kosherwinedirect.com"}
KW_HOST = "www.kosherwine.com"         # pictures only, and the search link the admin opens
KW_IMAGE_PATH = "/media/catalog/product/"
KW_IMAGE_SIDE = 1200
KW_SEARCH = "https://www.kosherwine.com/shop.html?q="

# The store's product page lists a product's details as a plain row of values with
# no labels ("Red", "Dry", "Israel", "Blend", "14.50%", "Not Mevushal", "Kosher
# for Passover", "750 ML", "OU, Badatz Beit Yosef", "Upper Galilee"), leaving out
# whatever it does not know. So each value is recognised by what it says.
_DETAILS = re.compile(r'<div class="p_highlights[^"]*">(.*?)</div>\s*</div>', re.S)
_TYPES = {"red": "Red", "white": "White", "rose": "Rosé", "rosé": "Rosé", "sparkling": "Sparkling",
          "orange": "Orange", "dessert": "Dessert & Fortified", "fortified": "Dessert & Fortified"}
_SWEETNESS = {"dry": "Dry", "semi-dry": "Semi-Dry", "semi dry": "Semi-Dry", "off-dry": "Semi-Dry",
              "off dry": "Semi-Dry", "semi-sweet": "Semi-Sweet", "semi sweet": "Semi-Sweet",
              "sweet": "Sweet"}
_COUNTRIES = {"usa": "USA", "united states": "USA", "california": "USA", **{c.lower(): c for c in (
    "Argentina", "Australia", "Austria", "Canada", "Chile", "Cyprus", "France", "Georgia",
    "Germany", "Greece", "Hungary", "Ireland", "Israel", "Italy", "Japan", "Mexico", "Moldova",
    "Morocco", "New Zealand", "Poland", "Portugal", "Scotland", "South Africa", "Spain",
    "Ukraine", "United Kingdom")}}
_CERTIFIER = re.compile(r"\b(OU|OK|Badatz|Star-?K|Kof-?K|CRC|Rabbi|Rav|Beit|Beth|Din|Edah|Eda|"
                        r"Chasam|Chatam|Kehal|Kosher|Rabbinate|Triangle)\b", re.I)
_ABV = re.compile(r"^(\d+(?:\.\d+)?)\s*%$")
_SIZE = re.compile(r"^(\d+(?:\.\d+)?)\s*(ml|cl|l|liter|litre)s?$", re.I)

_HANDLE = re.compile(r"/products/([^/?#\s]+?)(?:\.js|\.json)?/?$")      # some of the store's addresses hold stars or accents
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_lock = threading.Lock()
_opener = None                         # one signed-in session per worker process


class SourceError(Exception):
    """A message an admin can read: why the page could not be used."""


def _session():
    global _opener
    if _opener is None:
        jar = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        _opener.addheaders = [("User-Agent", USER_AGENT)]
    return _opener


def _get(url, hosts, password, limit):
    """The bytes at `url` and their content type, signing in to the store first
    if it asks for its password. Every address, including one a redirect leads
    to, must be on `hosts`."""
    def fetch():
        with _session().open(url, timeout=TIMEOUT) as r:
            final = urllib.parse.urlsplit(r.geturl())
            if final.path.rstrip("/") == "/password":
                return None
            if final.scheme != "https" or final.hostname not in hosts:
                raise SourceError("The store sent the request somewhere unexpected.")
            data = r.read(limit + 1)
            if len(data) > limit:
                raise SourceError("That file is too large.")
            return data, r.headers.get_content_type()

    def attempt():
        try:
            return fetch()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return None                              # the closed store: sign in
            if e.code == 404:
                raise SourceError("Kosher Wine World has no product at that address.")
            raise SourceError(f"Kosher Wine World answered with an error ({e.code}).")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SourceError("Kosher Wine World could not be reached. Try again in a minute.")

    with _lock:
        got = attempt()
        if got is None:
            if not password:
                raise SourceError("The store is closed and its password is not set on the server.")
            form = urllib.parse.urlencode({"form_type": "storefront_password", "utf8": "✓",
                                           "password": password}).encode()
            try:
                _session().open(STORE + "/password", data=form, timeout=TIMEOUT).close()
            except (urllib.error.URLError, TimeoutError, OSError):
                raise SourceError("Kosher Wine World could not be reached. Try again in a minute.")
            got = attempt()
            if got is None:
                raise SourceError("Kosher Wine World did not accept the store password. "
                                  "It may have been changed.")
        return got


def _check(url, hosts):
    parts = urllib.parse.urlsplit((url or "").strip())
    if parts.scheme != "https" or parts.hostname not in hosts or parts.port not in (None, 443):
        return None
    return parts


def plain(text):
    """Text for comparing: accents and capitals do not count ("CHÂTEAU" = "chateau")."""
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if not unicodedata.combining(c)).casefold()


def password(config_path):
    """The Kosher Wine World storefront password from the site's private config
    file, or '' when it is not set."""
    try:
        return json.loads(config_path.read_text()).get("kww_password") or ""
    except (OSError, ValueError):
        return ""


def _text(body_html):
    """A product description as plain text: tags dropped, paragraphs kept as lines."""
    t = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h\d)\s*/?>", "\n", body_html or "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = [" ".join(line.split()) for line in t.splitlines()]
    return "\n".join(line for line in lines if line)


def details(page_html):
    """The details row of a store product page as catalog fields: any of type,
    category, sweetness, country, grape, abv, mevushal, kfp, size, certifier,
    region, written the way the catalog writes them ("14.5%", "750 ml", "Yes").
    A field the page does not give is left out, except `organic`: the owner,
    2026-11-16, "if the listing doesn't say "Organic" please switch to "No"",
    so it is "Yes" when the row says Organic and "No" otherwise."""
    m = _DETAILS.search(page_html)
    return _fields(re.findall(r"<div>([^<]*)", m.group(1)) if m else [])


def _fields(values, loose_too=True):
    """A row of unlabelled detail values as catalog fields (see details()). One
    value may hold the country and the region together ("Israel, Galilee").
    `loose_too=False` keeps only the values recognised by what they say (for a
    page whose other lines are not details at all)."""
    values = [" ".join(html.unescape(v).split()) for v in values]
    out, loose = {"organic": "No"}, []        # loose: (position, value) not yet recognised
    anchors = []                              # positions of ABV / Mevushal / Passover / size
    for i, v in enumerate(v for v in values if v):
        low = v.lower()
        place, _, within = v.partition(",")
        if within.strip() and place.strip().lower() in _COUNTRIES and "country" not in out:
            out["country"] = _COUNTRIES[place.strip().lower()]
            out.setdefault("region", within.strip())
            continue
        if _ABV.match(v):
            out["abv"] = f"{float(_ABV.match(v).group(1)):g}%"
        elif low in ("mevushal", "not mevushal", "non mevushal", "non-mevushal"):
            out["mevushal"] = "Yes" if low == "mevushal" else "No"
        elif low in ("kosher for passover", "not kosher for passover", "not for passover"):
            out["kfp"] = "Yes" if low == "kosher for passover" else "No"
        elif low in ("organic", "certified organic", "organic wine"):
            out["organic"] = "Yes"
        elif _SIZE.match(v):
            n, unit = float(_SIZE.match(v).group(1)), _SIZE.match(v).group(2).lower()
            ml = n * {"ml": 1, "cl": 10}.get(unit, 1000)
            out["size"] = f"{ml / 1000:g} L" if ml >= 1000 else f"{ml:g} ml"
        elif low in _TYPES and "type" not in out:
            out["type"], out["category"] = _TYPES[low], "Wine"
            continue
        elif low in _SWEETNESS and "sweetness" not in out:
            out["sweetness"] = _SWEETNESS[low]
            continue
        elif low in _COUNTRIES and "country" not in out:
            out["country"] = _COUNTRIES[low]
            continue
        else:
            loose.append((i, v))
            continue
        anchors.append(i)
    # What is left: the grape comes before the ABV / Mevushal / size values, the
    # certifier and the region after them.
    if not loose_too:
        return out
    first = min(anchors) if anchors else len(values)
    grapes = [v for i, v in loose if i < first]
    if grapes:
        out["grape"] = ", ".join(grapes)
    for _i, v in (x for x in loose if x[0] > first):
        key = "certifier" if _CERTIFIER.search(v) and "certifier" not in out else "region"
        out.setdefault(key, v)
    return out


def product(url, password):
    """What Kosher Wine World holds for the product page at `url`:
    {'url', 'name', 'sku', 'vintage', 'description', 'image', 'tags'} plus
    whatever its details row gives (see details()). `tags` are the store's own
    labels for the product (sometimes the winery, e.g. "adir winery"). `sku` is the store's SKU for it (often
    Satla's own SKU, not always the same one); `vintage` is the year in the
    name, if it has one; `image` is the address of its main picture ('' when
    it has none), to pass to image(). Raises SourceError with a message for
    the admin."""
    direct = _check(url, KWD_HOSTS)
    if direct and _HANDLE.search(direct.path):
        return _kwd_product(_HANDLE.search(direct.path).group(1))
    parts = _check(url, PAGE_HOSTS)
    m = _HANDLE.search(parts.path) if parts else None
    if not m:
        raise SourceError("Paste the address of a product page on kosherwineworld.com or "
                          "kosherwinedirect.com, like https://kosherwineworld.com/products/adir-a-red-blend-2017")
    page = f"{STORE}/products/{urllib.parse.quote(urllib.parse.unquote(m.group(1)), safe='-_.~')}"
    data, _kind = _get(page + ".js", PAGE_HOSTS, password, 2_000_000)
    try:
        d = json.loads(data)
        name = " ".join(str(d["title"]).split())
    except (ValueError, KeyError, TypeError):
        raise SourceError("Kosher Wine World did not send product data for that address.")
    skus = [str(v.get("sku") or "").strip() for v in d.get("variants") or []]
    image = str(d.get("featured_image") or (d.get("images") or [""])[0] or "")
    if image.startswith("//"):
        image = "https:" + image
    year = _YEAR.search(name)
    try:                                          # the details are only on the page itself
        extra = details(_get(page, PAGE_HOSTS, password, 3_000_000)[0].decode("utf-8", "replace"))
    except SourceError:
        extra = {"organic": "No"}
    if re.search(r"\borganic\b", name, re.I):
        extra["organic"] = "Yes"
    return {**extra, "store": "Kosher Wine World", "tags": [str(t) for t in d.get("tags") or []], "url": page, "name": name, "sku": next((s for s in skus if s), ""),
            "vintage": year.group(1) if year else "", "description": _text(d.get("description")),
            "image": image if _check(image, IMAGE_HOSTS) else ""}


def image(url, password):
    """(bytes, content type) of a product picture, for the edit page's photo
    tool: from Kosher Wine World's image servers (signed in, full width), from
    KosherWine.com, or from any other public https address by one plain
    request (see _picture)."""
    kw = _kw_image(url)
    if kw:
        return _kw_picture(kw)
    parts = _check(url, IMAGE_HOSTS)
    if not parts:
        return _picture(html.unescape(url or ""))
    query = urllib.parse.parse_qsl(parts.query)
    query = [(k, v) for k, v in query if k != "width"] + [("width", str(IMAGE_WIDTH))]
    data, kind = _get(urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))),
                      IMAGE_HOSTS, password, MAX_IMAGE_BYTES)
    if not kind.startswith("image/"):
        raise SourceError("Kosher Wine World did not send a picture.")
    return data, kind


# --- finding a product on the store ----------------------------------------------

def listing(password):
    """Every product the store lists, as [{'url', 'name', 'skus', 'image'}]:
    the page's address, the store's name for it, its SKUs (often Satla's own)
    and its main picture ('' when it has none). About ten requests; the refresh
    runs it once a day and keeps the result, so a search never waits for it."""
    out = []
    for page in range(1, 60):
        data, _kind = _get(f"{STORE}/products.json?limit=250&page={page}", PAGE_HOSTS,
                           password, 30_000_000)
        try:
            products = json.loads(data)["products"]
        except (ValueError, KeyError, TypeError):
            raise SourceError("Kosher Wine World did not send its product list.")
        if not products:
            break
        for p in products:
            skus = {str(v.get("sku") or "").strip() for v in p.get("variants") or []}
            picture = next((str(i.get("src") or "") for i in p.get("images") or []), "")
            out.append({"store": "Kosher Wine World", "url": f"{STORE}/products/{p.get('handle')}",
                        "name": " ".join(str(p.get("title") or "").split()),
                        "skus": sorted(skus - {""}),
                        "image": picture if _check(picture, IMAGE_HOSTS) else ""})
    return out


# Words that do not tell one product from another, in a name from QuickBooks, MMK
# or a store ("SAT-Adir Plato 750/12", "... (M)", "... Kosher Wine").
_NOISE = {"sat", "kosher", "wine", "wines", "the", "mevushal", "mevusal", "mevoshal", "non",
          "not", "ml", "for", "passover"}


def words(name):
    """The telling words of a product name, as written, in order: no pack or size
    figures, no year, no (M), none of the _NOISE words."""
    out = []
    for word in re.split(r"[^\w'’]+", name or ""):
        p = plain(word).replace("'", "").replace("’", "")
        if len(p) > 1 and p not in _NOISE and not any(c.isdigit() for c in p):
            out.append(word)
    return out


def _same(a, b):
    """Two words that are one word spelled two ways ("Shor" / "Shorr", "Sirah" / "Syrah")."""
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[0] == b[0]
                      and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)


def _stem(sku):
    """A SKU without its vintage or Mevushal ending: I-EY16R-20 -> I-EY16R, I-AD40W-M -> I-AD40W."""
    s = re.sub(r"-\d{2}$", "", (sku or "").strip().upper())
    return re.sub(r"-M$|(?<=\d[A-Z])M$", "", s)


def rank(products, sku="", name="", limit=6):
    """The products of listing() that best match an item number and / or a name,
    best first, each with 'why' (a few words for the admin). The order: the same
    item number; the same item number apart from a vintage or (M) ending; then
    the closest names. A name counts only when its first word (the brand) is in
    the store's name and at least one more word is shared."""
    sku = (sku or "").strip().upper()
    mine = [plain(w) for w in words(name)]
    found = []
    for p in products:
        theirs = [s.upper() for s in p["skus"]]
        title = [plain(w) for w in words(p["name"])]
        hits = sum(1 for a in mine if any(_same(a, b) for b in title))
        back = sum(1 for b in title if any(_same(a, b) for a in mine))
        close = 0.7 * hits / len(mine) + 0.3 * back / len(title) if mine and title else 0
        if sku and sku in theirs:
            order, why = 0, "Same item number"
        elif sku and len(_stem(sku)) >= 5 and _stem(sku) in [_stem(s) for s in theirs]:
            order, why = 1, "Same item number, other vintage or (M)"
        elif (mine and title and close >= 0.45 and any(_same(mine[0], b) for b in title)
              and (hits >= 2 or len(mine) == 1)):
            order, why = 2, "Name matches" if close >= 0.95 else "Name is close"
        else:
            continue
        found.append((order, -close, p["name"].casefold(), dict(p, why=why)))
    found.sort(key=lambda f: f[:3])
    return [f[3] for f in found[:limit]]


# --- a KosherWine.com page the admin pasted ---------------------------------------

_KW_CHROME = re.compile(r"^(rating:?|\d+%?\s*of\s*\d+|\d+|\d+\s+reviews?|review|\$[\d.,]+.*|"
                        r"mix & match.*|add to (cart|list)|add your review|buy a box.*|qty|"
                        r"out of stock.*|notify me.*|skip to .*)$", re.I)
_KW_END = re.compile(r"^(get expert help|more from .*|customer reviews|product questions)$", re.I)


def _kw_image(url):
    parts = _check(html.unescape(url or ""), {KW_HOST})
    return parts if parts and parts.path.startswith(KW_IMAGE_PATH) else None


def pasted(text, hint=""):
    """A product page that the admin copied in their own browser and pasted,
    read into the same shape product() gives. `text` is either the page as it
    reads on screen (select all, copy) or its source (View Source, select all,
    copy). A KosherWine.com page is read by its known layout; a page from any
    other site by what can be recognised in it (_pasted_any), where `hint` (the
    item's name on the form) tells which line is the product's name. The source
    also gives the picture; with the on-screen text the admin can add the
    picture's address on a line of its own. `sku` is the retailer's own number,
    not Satla's. Raises SourceError with a message for the admin."""
    text = text or ""
    source = "<meta" in text or "<div" in text
    if source and "p_highlights" in text:
        found = _pasted_source(text)
    else:
        found = {} if source or "kosherwine" not in text.lower() else _pasted_screen(text)
        if not found.get("name"):
            found = _pasted_any(text, hint, source)
    if not found.get("name") or (len(found) < 6 and not found.get("description")):
        raise SourceError("Nothing in that paste reads as a product's details. Open the "
                          "product's page, select all of it, copy, and paste it here.")
    name = found["name"]
    year = _YEAR.search(name)
    found["vintage"] = year.group(1) if year else ""
    if re.search(r"\borganic\b", name, re.I):
        found["organic"] = "Yes"
    for key in ("url", "sku", "description", "image"):
        found.setdefault(key, "")
    found.setdefault("tags", [])
    return found


def _meta(text, prop):
    """The content of a page source's <meta property= / name=`prop`>, or ''."""
    m = re.search(r'<meta\s+(?:property|name)=["\']%s["\']\s+content=["\']([^"\']*)["\']'
                  % re.escape(prop), text)
    return " ".join(html.unescape(m.group(1)).split()) if m else ""


def _ld_product(text):
    """The schema.org Product a page source describes itself with, or {}."""
    for block in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                            text, re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        nodes = d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") in ("Product", ["Product"]):
                return node
    return {}


def _brand(product, text):
    brand = product.get("brand") or _meta(text, "product:brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    return [" ".join(str(brand).split())] if brand else []


def _pasted_source(text):
    meta = lambda prop: _meta(text, prop)
    product = _ld_product(text)
    m = re.search(r'class="p_highlights[^"]*">(.*?)</table>', text, re.S)
    out = _fields([_text(v) for v in re.findall(r"<li>(.*?)</li>", m.group(1), re.S)] if m else [])
    out["name"] = " ".join(str(product.get("name") or "").split()) or meta("og:title")
    out["description"] = _text(str(product.get("description") or "")) or meta("og:description")
    out["sku"] = str(product.get("sku") or "")
    out["tags"] = _brand(product, text)
    m = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', text)
    if m and _check(html.unescape(m.group(1)), {KW_HOST}):
        out["url"] = html.unescape(m.group(1))
    m = re.search(r'class="gallery-placeholder__image"\s+src="([^"]+)"', text)
    picture = html.unescape(m.group(1)) if m else str(product.get("image") or "") or meta("og:image")
    if _kw_image(picture):
        out["image"] = picture
    return out


def _pasted_screen(text):
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    out = {}
    picture = next((w for line in lines for w in line.split() if _kw_image(w)), "")
    start = next((i for i, line in enumerate(lines) if re.search(r"\bSKU:\s*\S", line)), None)
    if start is None:
        return out
    sku = re.search(r"\bSKU:\s*(\S+)", lines[start]).group(1)
    body = [line for line in lines[start + 1:] if not _kw_image(line)]
    end = next((i for i, line in enumerate(body) if _KW_END.match(line)), len(body))
    body = [line for line in body[:end] if not _KW_CHROME.match(line)]
    if not body:
        return out
    name, rest = body[0], body[1:]
    # The details are short values, one to a line; the description is sentences.
    out = _fields([line for line in rest if len(line) <= 60])
    out.update(name=name, sku=sku, image=picture,
               description="\n".join(line for line in rest if len(line) > 60))
    return out


def _kw_picture(parts):
    """(bytes, content type) of a KosherWine.com product picture, asked for at
    KW_IMAGE_SIDE pixels."""
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k not in ("width", "height")]
    query += [("width", str(KW_IMAGE_SIDE)), ("height", str(KW_IMAGE_SIDE))]
    return _picture(urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))))


def _public(url):
    """The parts of `url` when it is an https address of a public web server
    (never this machine or a private network), else None."""
    parts = urllib.parse.urlsplit((url or "").strip())
    if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443):
        return None
    try:
        found = socket.getaddrinfo(parts.hostname, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return None
    return parts if found and all(ipaddress.ip_address(f[4][0]).is_global for f in found) else None


class _PublicOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public(newurl):
            raise SourceError("That address led somewhere the server will not go.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _picture(url):
    """(bytes, content type) of a picture at a public https address, by one plain
    request: no sign-in, no session, nothing to get past a site that refuses."""
    refused = SourceError("That site did not give the picture to the server. Save the picture "
                          "from your browser and choose it under Photo instead.")
    if not _public(url):
        raise SourceError("That is not the address of a picture on a public website.")
    parts = urllib.parse.urlsplit(url)            # an address may hold letters outside ASCII
    url = urllib.parse.urlunsplit(parts._replace(
        path=urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
        query=urllib.parse.quote(parts.query, safe="=&%:@!$'()*+,;/?-._~")))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.build_opener(_PublicOnly).open(req, timeout=TIMEOUT) as r:
            data, kind = r.read(MAX_IMAGE_BYTES + 1), r.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise refused
    if len(data) > MAX_IMAGE_BYTES or not kind.startswith("image/") or "svg" in kind:
        raise refused
    return data, kind


# --- a page from any other site, pasted --------------------------------------------

_PICTURE = re.compile(r"^https://\S+\.(?:jpe?g|png|webp)(?:\?\S*)?$", re.I)
_ABV_NEAR = (re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:abv|alc|alcohol)", re.I),
             re.compile(r"(?:abv|alcohol(?: by volume)?|alc\.?\s*/\s*vol\.?)\D{0,12}(\d{1,2}(?:\.\d+)?)\s*%", re.I))
_PROOF = re.compile(r"\b(\d{2,3})\s*proof\b", re.I)
_SIZE_NEAR = re.compile(r"\b(\d{2,4}\s?ml|\d(?:\.\d+)?\s?(?:l|liters?|litres?))\b", re.I)
_NOT_PROSE = re.compile(r"cookie|privacy|shipping|subscribe|newsletter|©|all rights reserved|"
                        r"sign in|log in|your cart|javascript|for reference only|without notice|"
                        r"review", re.I)


def _pasted_any(text, hint, source):
    """A product page of any site, read by what can be recognised: labelled lines
    ("Country: USA", "ABV: 40%"), lone values the catalog knows ("Red", "Dry",
    "France", "750 ML", "Mevushal"), an ABV, proof or bottle size in the text,
    the paragraphs that read as the description, and a picture's address. The
    product's name is the line that shares the most words with `hint`. A page
    source also gives what it says about itself (its Product data, og: tags)."""
    name = titled = description = picture = ""
    tags = []
    if source:
        product = _ld_product(text)
        name = " ".join(str(product.get("name") or "").split())
        titled = _meta(text, "og:title")
        description = _text(str(product.get("description") or "")) or _meta(text, "og:description")
        shown = product.get("image")
        shown = shown[0] if isinstance(shown, list) and shown else shown
        shown = shown.get("url") if isinstance(shown, dict) else shown
        picture = html.unescape(str(shown or "")) or _meta(text, "og:image")
        tags = _brand(product, text)
        text = _text(re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", text))
    raw = [line.strip() for line in text.splitlines() if line.strip()]   # spacing kept, for labels
    lines = [" ".join(line.split()) for line in raw]
    if not picture:
        picture = next((line for line in lines if _PICTURE.match(line)), "")
    lines = [line for line in lines if not _PICTURE.match(line)]
    mine = [plain(w) for w in words(hint)]
    at = 0
    if mine:                                   # the line that reads most like the item's name
        def hits(line):
            theirs = [plain(w) for w in words(line)]
            return sum(1 for a in mine if any(_same(a, b) for b in theirs))
        best = max(range(len(lines)), key=lambda i: (hits(lines[i]), -len(words(lines[i])), -i),
                   default=0)
        if lines and len(lines[best]) <= 120 and hits(lines[best]) >= min(2, len(mine)):
            at, name = best, name or lines[best]
    values, pairs = [], []
    for line in (line for line in raw if len(line) <= 80):
        found = _label_of(line)
        if found:
            pairs.append(found)
        else:
            values.append(" ".join(line.split()))
    out = _fields(values, loose_too=False)
    labelled, producer = _labelled([(k, v) for k, v in pairs])
    out.update(labelled)                       # a labelled value wins over a lone one
    tags = tags or ([producer] if producer else [])
    whole = " ".join(lines)
    if "abv" not in out:
        m = next((m for m in (p.search(whole) for p in _ABV_NEAR) if m), None)
        if m:
            out["abv"] = f"{float(m.group(1)):g}%"
        elif _PROOF.search(whole):
            out["abv"] = f"{float(_PROOF.search(whole).group(1)) / 2:g}%"
    if "size" not in out and _SIZE_NEAR.search(whole):
        out.update({k: v for k, v in _fields([_SIZE_NEAR.search(whole).group(1)], False).items()
                    if k == "size"})
    if not description:                        # the first paragraphs after the name that read as prose
        prose = [line for line in lines[at:] if len(line) >= 100 and "." in line
                 and not _NOT_PROSE.search(line)]
        description = "\n".join(prose[:2])
    out.update(name=name or titled or " ".join(hint.split()), description=description, tags=tags,
               image=picture if _public(picture) else "")
    return out


# --- Kosher Wine Direct (kosherwinedirect.com) --------------------------------------

def _plain_get(url, hosts, limit):
    """The bytes at `url` on one of `hosts`, by one plain request (a public store:
    no sign-in, no session). A redirect elsewhere is refused."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            final = urllib.parse.urlsplit(r.geturl())
            if final.scheme != "https" or final.hostname not in hosts:
                raise SourceError("Kosher Wine Direct sent the request somewhere unexpected.")
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise SourceError("Kosher Wine Direct has no product at that address." if e.code == 404
                          else f"Kosher Wine Direct answered with an error ({e.code}).")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SourceError("Kosher Wine Direct could not be reached. Try again in a minute.")
    if len(data) > limit:
        raise SourceError("That file is too large.")
    return data


def listing_kwd():
    """Every product Kosher Wine Direct lists, in the shape of listing(). The
    store's SKUs are blank, so a match there is always by name."""
    out = []
    for page in range(1, 60):
        data = _plain_get(f"{KWD_STORE}/products.json?limit=250&page={page}", KWD_HOSTS, 30_000_000)
        try:
            products = json.loads(data)["products"]
        except (ValueError, KeyError, TypeError):
            raise SourceError("Kosher Wine Direct did not send its product list.")
        if not products:
            break
        for p in products:
            skus = {str(v.get("sku") or "").strip() for v in p.get("variants") or []}
            picture = next((str(i.get("src") or "") for i in p.get("images") or []), "")
            out.append({"store": "Kosher Wine Direct", "url": f"{KWD_STORE}/products/{p.get('handle')}",
                        "name": " ".join(str(p.get("title") or "").split()),
                        "skus": sorted(skus - {""}),
                        "image": picture if _check(picture, IMAGE_HOSTS) else ""})
    return out


def _kwd_product(handle):
    """What Kosher Wine Direct holds for one product, in the shape of product():
    the details from the Details table in its description, the description's
    lead paragraph, the producer (as a tag, for the brand rule) and its picture."""
    page = f"{KWD_STORE}/products/{urllib.parse.quote(urllib.parse.unquote(handle), safe='-_.~')}"
    try:
        d = json.loads(_plain_get(page + ".js", KWD_HOSTS, 2_000_000))
        name = " ".join(str(d["title"]).split())
    except (ValueError, KeyError, TypeError):
        raise SourceError("Kosher Wine Direct did not send product data for that address.")
    body = str(d.get("description") or "")
    pairs = [(_text(a), _text(b)) for a, b in
             re.findall(r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", body, re.S)]
    out, producer = _labelled(pairs)
    lead = re.search(r'<p class="kwd-lead">(.*?)</p>', body, re.S)
    description = _text(lead.group(1)) if lead else _text(re.split(r"(?i)<h3", body)[0])
    image = str(d.get("featured_image") or "")
    if image.startswith("//"):
        image = "https:" + image
    year = _YEAR.search(name)
    out.setdefault("organic", "No")
    if re.search(r"\borganic\b", name, re.I):
        out["organic"] = "Yes"
    return {**out, "store": "Kosher Wine Direct", "url": page, "name": name, "sku": "",
            "tags": [t for t in (producer, str(d.get("vendor") or "")) if t],
            "vintage": out.get("vintage") or (year.group(1) if year else ""),
            "description": description,
            "image": image if _check(image, IMAGE_HOSTS) else ""}


# --- labelled details: "Country: Italy", "Alcohol    13.5%", a Details table -----------

_LABEL_KEYS = {
    "producer": "brand", "brand": "brand", "winery": "brand", "distillery": "brand", "maker": "brand",
    "country": "country", "country of origin": "country", "origin": "country",
    "region": "region", "appellation": "subregion", "sub-region": "subregion", "subregion": "subregion",
    "varietal": "grape", "varietals": "grape", "grape": "grape", "grapes": "grape",
    "grape variety": "grape", "grape varieties": "grape", "blend": "grape",
    "style": "style", "color": "style", "colour": "style", "type": "style", "sweetness": "style",
    "alcohol": "abv", "abv": "abv", "alcohol by volume": "abv", "alc/vol": "abv",
    "alcohol content": "abv", "bottle size": "size", "size": "size", "volume": "size",
    "vintage": "vintage", "hashgacha": "certifier", "hechsher": "certifier",
    "certifier": "certifier", "kosher certification": "certifier", "kosher supervision": "certifier",
    "supervision": "certifier", "kashrus": "certifier", "mevushal": "mevushal",
    "kosher for passover": "kfp", "passover": "kfp"}
_LABEL_ORDER = sorted(_LABEL_KEYS, key=len, reverse=True)


def _label_of(line):
    """(label key, value) when a short line is a labelled detail ("Country: Italy",
    "Country    Italy", "Alcohol 13.5%"), else None."""
    low = line.lower()
    for label in _LABEL_ORDER:
        if low.startswith(label):
            rest = line[len(label):]
            if rest[:1] in (":", "：") or (rest[:1].isspace() and rest.strip()):
                value = rest.lstrip(":： ").strip()
                if value:
                    return label, value
    return None


def _labelled(pairs):
    """Catalog fields from (label, value) pairs, and the producer's name ('' if
    none). Unknown labels are ignored."""
    out, producer = {}, ""
    for label, value in pairs:
        key = _LABEL_KEYS.get(" ".join(label.lower().rstrip(":").split()))
        value = " ".join(value.split())
        if not key or not value:
            continue
        if key == "brand":
            producer = producer or value
        elif key == "style":                     # "Red, Dry" -> type and sweetness
            out.update({k: v for k, v in _fields([p for p in value.split(",")], False).items()
                        if k in ("type", "category", "sweetness")})
        elif key == "abv":
            m = re.search(r"\d+(?:\.\d+)?", value)
            if m:
                out["abv"] = f"{float(m.group()):g}%"
        elif key == "size":
            out.update({k: v for k, v in _fields([value.replace(" ", "")], False).items() if k == "size"})
        elif key in ("mevushal", "kfp"):
            low = value.lower()
            if low.startswith(("yes", "no", "not")):
                out[key] = "Yes" if low.startswith("yes") else "No"
        elif key == "vintage":
            m = _YEAR.search(value)
            if m:
                out["vintage"] = m.group(1)
        elif key == "country":
            out["country"] = _COUNTRIES.get(value.lower(), value)
        else:
            out[key] = value
    return out, producer
