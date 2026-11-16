"""Reading a product's public data from Kosher Wine World, to fill in a catalog
item (the owner, 2026-11-16: "can we add a url text box ... so we can scrape
the data?", then "What about kosherwineworld.com?" and the store's password).

Kosher Wine World is a Shopify store that carries Satla's products under
Satla's own SKUs. While the store is closed to the public it answers only
after its storefront password, which the owner gave; it is kept in the site's
private config file (~/python/config/catalog_config.json, key `kww_password`),
never in the code.

Only that store is read, and only its product pages and its product pictures:
the address an admin types is checked against PAGE_HOSTS / IMAGE_HOSTS before
anything is fetched, so the box cannot be used to make the server call another
address. KosherWine.com is NOT read: it refuses automated requests, and this
module does not try to get around that.

Standard library only (the web worker loads it). Nothing here touches
QuickBooks or MMK.
"""
import html
import http.cookiejar
import json
import re
import threading
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
    if not m:
        return {"organic": "No"}
    values = [" ".join(html.unescape(v).split()) for v in re.findall(r"<div>([^<]*)", m.group(1))]
    out, loose = {"organic": "No"}, []        # loose: (position, value) not yet recognised
    anchors = []                              # positions of ABV / Mevushal / Passover / size
    for i, v in enumerate(v for v in values if v):
        low = v.lower()
        if _ABV.match(v):
            out["abv"] = f"{float(_ABV.match(v).group(1)):g}%"
        elif low in ("mevushal", "not mevushal", "non mevushal", "non-mevushal"):
            out["mevushal"] = "Yes" if low == "mevushal" else "No"
        elif low in ("kosher for passover", "not kosher for passover"):
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
    parts = _check(url, PAGE_HOSTS)
    m = _HANDLE.search(parts.path) if parts else None
    if not m:
        raise SourceError("Paste the address of a product page on kosherwineworld.com, "
                          "like https://kosherwineworld.com/products/adir-a-red-blend-2017")
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
    return {**extra, "tags": [str(t) for t in d.get("tags") or []], "url": page, "name": name, "sku": next((s for s in skus if s), ""),
            "vintage": year.group(1) if year else "", "description": _text(d.get("description")),
            "image": image if _check(image, IMAGE_HOSTS) else ""}


def image(url, password):
    """(bytes, content type) of a product picture from the store, for the edit
    page's photo tool. Only addresses on the store's own image servers."""
    parts = _check(url, IMAGE_HOSTS)
    if not parts:
        raise SourceError("That is not a Kosher Wine World picture.")
    query = urllib.parse.parse_qsl(parts.query)
    query = [(k, v) for k, v in query if k != "width"] + [("width", str(IMAGE_WIDTH))]
    data, kind = _get(urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))),
                      IMAGE_HOSTS, password, MAX_IMAGE_BYTES)
    if not kind.startswith("image/"):
        raise SourceError("Kosher Wine World did not send a picture.")
    return data, kind
