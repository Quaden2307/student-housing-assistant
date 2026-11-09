"""Parse archived (Wayback Machine) Kijiji index pages into index cards.

Kijiji's index page changed shape over the years, so a capture is classified before it
is parsed. Formats seen in 2014 to 2026 captures:

- ``nextjs``: today's page. ``__NEXT_DATA__`` with ``mainListings`` and
  ``RealEstateListing``/``StandardListing`` entities. Parsed by the live parser,
  :func:`housing.parse.kijiji.parse_index`, so archive and live cards are identical.
- ``nextjs_v2``: an older Next.js page (e.g. 2024-04-21). The same data under
  ``results.organic``/``results.topAds``, ``ListingV2`` entities, attributes as
  ``{name, values}`` and **no coordinates**.
- ``classic``: the server-rendered ``div.search-item`` era, roughly 2016 to 2022
  (verified on 2017-01-06, 2017-06-09 and 2022-06-05 captures). Cards carry an ad id
  (``data-listing-id`` or ``data-ad-id``), title, price, location, ``span.date-posted``,
  a description snippet, and from about 2019 a nearest intersection and a bedrooms span.
  Served in English or French depending on the crawler's locale, so prices and dates are
  parsed in both.
- ``classic_v0``: the older ``<table class="regular-ad|top-feature">`` layout, roughly
  2013 to 2015 (verified on 2014-10-08 and 2015-03-01 captures). Title, price, snippet
  and a relative posting date; no location, intersection or bedrooms span. Bedrooms come
  from the listing URL's category slug (``/v-2-bedroom-apartments-condos/...``).
- ``html_cards``: a server-rendered page without ``__NEXT_DATA__`` (e.g. 2025-02-10).
  Prices only in the HTML and no posting dates. Not parsed yet, and its body is not
  stored: its descriptions carry contact details that :func:`scrub_page` cannot reach.
- ``unknown``: anything else (a redirect page, an error page, a new layout).

Archived **ad pages** (one listing each, ``/v-.../<ad id>``) have their own formats:

- ``nextjs_ad``: today's ad page (seen from mid-2025). Parsed by the live
  :func:`housing.parse.kijiji.parse_detail`; stored scrubbed by :func:`scrub_page`.
- ``vip_legacy``: the older ad page (2024 to early 2025), whose data sits in a
  ``window.__data`` blob under ``viewItemPage.viewItemData``. It carries the poster's
  first name and has no first-posting date, only the last bump. Its raw page is **not**
  stored: :func:`scrub_ad_capture` keeps only the fields we use, with contact details
  stripped, as a JSON extract that :func:`parse_ad_capture` reads back.
- ``removed``: the ad URL redirected to a search page (the ad was taken down).
"""

from __future__ import annotations

import dataclasses
import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from bs4 import BeautifulSoup, NavigableString, Tag

from housing.parse.kijiji import (
    BASE_URL,
    NEXT_DATA_RE,
    DetailPage,
    IndexCard,
    ParseError,
    apollo_state,
    parse_detail,
    parse_index,
)
from housing.parse.pii import (
    EMAIL_RE,
    OBFUSCATED_EMAIL_RE,
    REDACTED,
    encode_next_data,
    redact_url,
    scrub_page,
    strip_contact_info,
)

FORMATS = ("nextjs", "nextjs_v2", "classic", "classic_v0", "html_cards", "unknown")
AD_FORMATS = ("nextjs_ad", "vip_legacy", "removed", "unknown")

_DROPPED_RE = re.compile(r"<!-- archive-format: (\w+); body not stored -->")
_SEARCH_ITEM_RE = re.compile(r'class="[^"]*\bsearch-item\b')
_V0_CARD_RE = re.compile(r'<table class="[^"]*\b(?:regular-ad|top-feature)\b')
# The dataLayer's own render time ("ts":"2017-06-09 05:18:07.106+0000"), present from
# about 2016 on; it is the capture moment, which relative posting dates resolve against.
_PAGE_TS_RE = re.compile(r'"ts":"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
# Total listing count: the "Filter Results (1,124)" badge, the dataLayer's result count,
# then the French page title ("703 annonces | ...").
_TITLECOUNT_RE = re.compile(r'class="titlecount">\s*\(([\d,.\s ]+)\)')
_DATALAYER_TOTAL_RE = re.compile(r'"tr":(\d+)')
_TITLE_TOTAL_RE = re.compile(r"<title>\s*([\d\s ,.]+)annonces?", re.I)
_CATEGORY_ID_RE = re.compile(r'"c":\{"c":\{"id":(\d+)')
# "< 19 hours ago", "&lt; 25 minutes ago", "Il y a moins de 24 heures".
_REL_DATE_RE = re.compile(
    r"(?:<|&lt;|\bil y a moins de)\s*(\d+)\s*(minute|hour|heure|day|jour)", re.I
)
_ABS_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")  # dd/mm/yyyy
_ABS_DASH_DATE_RE = re.compile(r"\b(\d{1,2})-([^\s\d-]+)-(\d{2})\b")  # 10-mai-22, 13-Jun-22
_SLUG_BEDROOMS_RE = re.compile(r"^/v-(\d+)(?:-plus)?-bedroom")
_BEDROOMS_LABEL_RE = re.compile(r"(bedrooms|pi[eè]ces|chambres)\s*:?\s*(.*)", re.I)
_TRAILING_ID_RE = re.compile(r"/(\d{5,})/?$")

# English and French month names, matched whole, then on their first 4 and 3 letters
# ("juillet" -> "juil", "June" -> "jun"); "jui" is left out as juin/juillet is ambiguous.
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "janv": 1, "fév": 2, "févr": 2, "fev": 2, "fevr": 2, "mars": 3, "avr": 4,
    "mai": 5, "juin": 6, "juil": 7, "aoû": 8, "août": 8, "aou": 8, "aout": 8,
    "sept": 9, "déc": 12,
}  # fmt: skip

_PRICE_SKIP = frozenset({"price-drop-parent", "dealer-logo"})
_LOCATION_SKIP = frozenset({"date-posted", "tooltip-content", "tooltip-trigger"})
_DESCRIPTION_SKIP = frozenset({"dealer-logo", "details", "tagline"})


class UnsupportedFormat(ParseError):
    """The capture is in a format this module does not parse (yet)."""

    def __init__(self, fmt: str) -> None:
        super().__init__(f"archived page format {fmt!r} is not parsed")
        self.format = fmt


@dataclass(frozen=True)
class ClassicCard(IndexCard):
    """An :class:`IndexCard` plus the description snippet a classic-era card shows."""

    description: str | None = None
    """The card's teaser text, contact info stripped at parse time."""


def detect_format(html: str) -> str:
    """Return which of :data:`FORMATS` an archived index page is in."""
    dropped = _DROPPED_RE.search(html[:500])
    if dropped:
        return dropped.group(1)
    if NEXT_DATA_RE.search(html):
        try:
            results = _results(apollo_state(html))
        except ParseError:
            return "unknown"
        if any(k.startswith("mainListings") for k in results):
            return "nextjs"
        if "organic" in results:
            return "nextjs_v2"
        return "unknown"
    if 'data-testid="listing-card"' in html:
        return "html_cards"
    if "data-vip-url=" in html:
        if _SEARCH_ITEM_RE.search(html):
            return "classic"
        if _V0_CARD_RE.search(html):
            return "classic_v0"
    return "unknown"


def scrub_capture(html: str) -> str:
    """Make an archived page safe to store, per the privacy rule.

    Next.js formats go through the live pipeline's :func:`scrub_page`; classic formats
    through :func:`_scrub_classic`, which strips contact details from every visible text
    node, listing URL and image alt without changing what the page parses to. Any other
    format is replaced by a one-line marker naming the format, so nothing unscrubbed is
    written to ``data/raw/`` and :func:`detect_format` still reports what the page was.
    Such captures are downloaded again once a parser and scrubber exist for them.
    """
    fmt = detect_format(html)
    if fmt in ("nextjs", "nextjs_v2"):
        return scrub_page(html)
    if fmt in ("classic", "classic_v0"):
        return _scrub_classic(html)
    return f"<!-- archive-format: {fmt}; body not stored -->\n"


def parse_capture(html: str, captured_at: str | None = None) -> tuple[str, int, list[IndexCard]]:
    """Parse an archived index page.

    Args:
        html: The capture's body (scrubbed or raw; parsing strips contact info either way).
        captured_at: The capture time, ISO 8601 UTC. Classic pages show relative posting
            dates ("< 2 hours ago"), which resolve against the page's own embedded render
            time when it has one, and against this otherwise. Without either, relative
            dates parse to ``None``.

    Returns:
        The format, Kijiji's total listing count for the category at capture time, and
        the cards (unique by ad id, in page order).

    Raises:
        UnsupportedFormat: ``html_cards`` or ``unknown``.
        ParseError: A Next.js page whose JSON does not have the expected shape.
    """
    fmt = detect_format(html)
    if fmt == "nextjs":
        page = parse_index(html)
        return fmt, page.total_count, page.cards
    if fmt == "nextjs_v2":
        return fmt, *_parse_v2(html)
    if fmt in ("classic", "classic_v0"):
        return fmt, *_parse_classic(html, fmt, captured_at)
    raise UnsupportedFormat(fmt)


def _results(state: dict) -> dict:
    root = state.get("ROOT_QUERY") or {}
    key = next((k for k in root if k.startswith("searchResultsPageByUrl:")), None)
    if key is None:
        raise ParseError("no searchResultsPageByUrl entry in the Apollo cache")
    return root[key].get("results") or {}


def _parse_v2(html: str) -> tuple[int, list[IndexCard]]:
    state = apollo_state(html)
    root = state["ROOT_QUERY"]
    srp = root[next(k for k in root if k.startswith("searchResultsPageByUrl:"))]
    results = srp.get("results") or {}
    total = int((srp.get("pagination") or {}).get("totalCount") or 0)
    refs = [r["__ref"] for r in (results.get("organic") or []) + (results.get("topAds") or [])]
    cards: list[IndexCard] = []
    seen: set[str] = set()
    for ref in refs:
        entity = state.get(ref)
        if not entity or str(entity.get("id")) in seen:
            continue
        seen.add(str(entity.get("id")))
        cards.append(_v2_card(entity, state))
    return total, cards


def _v2_card(entity: dict, state: dict) -> IndexCard:
    """Map a ``ListingV2`` entity onto the live parser's :class:`IndexCard`."""
    price = entity.get("price") or {}
    amount = price.get("amount")
    location = entity.get("location") or {}
    intersection = location.get("nearestIntersection") or []
    url = entity.get("seoUrl")
    if url and url.startswith("/"):
        url = BASE_URL + url
    attributes = {
        a["name"]: [str(v) for v in a.get("values") or []]
        for a in entity.get("attributes") or []
        if isinstance(a, dict) and a.get("name")
    }
    # posterInfo is a reference to a Profile entity whose id is the poster's account id.
    poster_ref = (entity.get("posterInfo") or {}).get("__ref")
    poster_id = (state.get(poster_ref) or {}).get("id") if poster_ref else None
    return IndexCard(
        source_id=str(entity.get("id")),
        url=url.split("?")[0] if url else None,
        title=(entity.get("title") or "").strip(),
        price=amount / 100 if isinstance(amount, int | float) else None,
        price_type=price.get("type"),
        address_text=location.get("address") or None,
        lat=None,
        lon=None,
        activation_date=entity.get("activationDate"),
        sorting_date=entity.get("sortingDate"),
        neighbourhood=None,
        intersection=" & ".join(str(x) for x in intersection) or None,
        category_id=entity.get("categoryId"),
        ad_source=entity.get("adSource"),
        poster_id=str(poster_id) if poster_id is not None else None,
        image_count=len(entity.get("imageUrls") or []),
        attributes=attributes,
    )


# --- the classic (2013 to 2022) server-rendered layouts ----------------------------------


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _parse_classic(html: str, fmt: str, captured_at: str | None) -> tuple[int, list[ClassicCard]]:
    """Parse a ``classic`` or ``classic_v0`` page into its total count and cards."""
    soup = _soup(html)
    now = _page_time(html, captured_at)
    category_id = _category_id(html)
    if fmt == "classic":
        tags = soup.select("div.search-item[data-vip-url]")
    else:
        tags = [
            t
            for t in soup.find_all("table", attrs={"data-vip-url": True})
            if {"regular-ad", "top-feature"} & set(t.get("class") or ())
        ]
    cards: list[ClassicCard] = []
    seen: set[str] = set()
    for tag in tags:
        card = _classic_card(tag, fmt, now, category_id)
        if card.source_id and card.source_id not in seen:
            seen.add(card.source_id)
            cards.append(card)
    return _classic_total(html), cards


def _classic_card(tag: Tag, fmt: str, now: datetime | None, category_id: int | None) -> ClassicCard:
    """Build a card from one ``div.search-item`` (classic) or ``<table>`` (classic_v0)."""
    vip = tag.get("data-vip-url") or ""
    path = vip.split("?")[0]
    source_id = str(tag.get("data-listing-id") or tag.get("data-ad-id") or _trailing_id(path))
    title = strip_contact_info(_text(tag.select_one("a.title"))) or ""
    if fmt == "classic":
        price_el = tag.select_one("div.price")
        posted_el = tag.select_one("span.date-posted")
        desc_el = tag.select_one("div.description")
        address = _text(tag.select_one("div.location"), _LOCATION_SKIP) or None
        crossings = [_text(s) for s in tag.select("span.nearest-intersection span.intersection")]
        intersection = " & ".join(c for c in crossings if c) or None
    else:
        price_el = tag.select_one("td.price")
        posted_el = tag.select_one("td.posted")
        cell = tag.select_one("td.description")
        paragraphs = cell.find_all("p") if cell else []
        desc_el = next((p for p in paragraphs if "details" not in (p.get("class") or [])), None)
        address = None
        intersection = None
    price, price_type = _price(_text(price_el, _PRICE_SKIP))
    posted = _posted_iso(_text(posted_el), now)
    description = strip_contact_info(_text(desc_el, _DESCRIPTION_SKIP)) or None
    bedrooms = _bedrooms(tag, path)
    return ClassicCard(
        source_id=source_id,
        url=redact_url(BASE_URL + path) if path.startswith("/") else None,
        title=title,
        price=price,
        price_type=price_type,
        address_text=address,
        lat=None,
        lon=None,
        activation_date=posted,
        sorting_date=posted,
        neighbourhood=None,
        intersection=intersection,
        category_id=category_id,
        ad_source="TOP_AD" if "top-feature" in (tag.get("class") or ()) else "ORGANIC",
        poster_id=None,
        image_count=0,
        attributes={"numberbedrooms": [str(bedrooms)]} if bedrooms is not None else {},
        description=description,
    )


def _text(tag: Tag | None, skip: frozenset[str] = frozenset()) -> str:
    """Tag's visible text, whitespace-collapsed, skipping children with a class in ``skip``."""
    if tag is None:
        return ""
    parts = []
    for node in tag.find_all(string=True):
        if type(node) is not NavigableString:  # script and style text, comments, doctypes
            continue
        parent = node.parent
        while parent is not None and parent is not tag:
            if skip & set(parent.get("class") or ()):
                break
            parent = parent.parent
        else:
            parts.append(str(node))
    return " ".join(" ".join(parts).split())


def _trailing_id(path: str) -> str:
    match = _TRAILING_ID_RE.search(path)
    return match.group(1) if match else ""


def _page_time(html: str, captured_at: str | None) -> datetime | None:
    """The page's own render time, else the caller's capture time; naive UTC."""
    match = _PAGE_TS_RE.search(html)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    if captured_at:
        try:
            return datetime.fromisoformat(captured_at.replace("Z", ""))
        except ValueError:
            return None
    return None


def _category_id(html: str) -> int | None:
    match = _CATEGORY_ID_RE.search(html)
    return int(match.group(1)) if match else None


def _classic_total(html: str) -> int:
    for pattern in (_TITLECOUNT_RE, _DATALAYER_TOTAL_RE, _TITLE_TOTAL_RE):
        match = pattern.search(html)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
    return 0


def _price(text: str) -> tuple[float | None, str | None]:
    """Dollars and price type from "$1,200.00", "2 500,00 $", "Please Contact", etc."""
    t = " ".join(text.replace("\xa0", " ").split())
    if not t:
        return None, None
    low = t.lower()
    if "contact" in low or "demande" in low:
        return None, "CONTACT"
    if "swap" in low or "trade" in low or "échange" in low or "troc" in low:
        return None, "SWAP_TRADE"
    match = re.search(r"\d[\d\s,.]*", t)
    if not match:
        return None, None
    digits = match.group(0).replace(" ", "").rstrip(",.")
    if "," in digits and "." in digits:
        digits = digits.replace(",", "")  # English thousands: 1,099.00
    elif re.search(r",\d{1,2}$", digits):
        digits = digits.replace(",", ".")  # French decimals: 2500,00
    else:
        digits = digits.replace(",", "")
    try:
        return float(digits), "FIXED"
    except ValueError:
        return None, None


def _posted_iso(text: str, now: datetime | None) -> str | None:
    """ISO UTC posting date from a classic card's date text, English or French.

    Relative dates ("< 19 hours ago", "Il y a moins de 24 heures") resolve to the stated
    bound before ``now`` (the capture time), so they are the earliest the ad can have
    been posted; absolute dates ("05/06/2017" day first, "10-mai-22") map via the month
    table and land at midnight UTC.
    """
    t = " ".join(text.replace("\xa0", " ").split())
    if not t:
        return None
    match = _REL_DATE_RE.search(t)
    if match:
        if now is None:
            return None
        unit = {"m": "minutes", "h": "hours", "d": "days", "j": "days"}[match.group(2)[0].lower()]
        posted = now - timedelta(**{unit: int(match.group(1))})
        return posted.strftime("%Y-%m-%dT%H:%M:%SZ")
    match = _ABS_SLASH_DATE_RE.search(t)
    if match:
        day, month, year = (int(g) for g in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"
    match = _ABS_DASH_DATE_RE.search(t)
    if match:
        month = _month_number(match.group(2))
        if month:
            day, year = int(match.group(1)), 2000 + int(match.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"
    return None


def _month_number(token: str) -> int | None:
    t = token.lower().rstrip(".")
    for key in (t, t[:4], t[:3]):
        if key in _MONTHS:
            return _MONTHS[key]
    return None


def _bedrooms(tag: Tag, path: str) -> int | None:
    """Bedrooms a card states: its bedrooms span, else its URL's category slug.

    The span reads "Bedrooms: 2" in English and "Pièces: 3 1/2" in French. Pièces is the
    Quebec room count: every room counts, the living room and kitchen included, and the
    1/2 is the bathroom, so bedrooms = rooms - 2.5. The 2022-06-05 capture confirms it
    seven times over ("4 Bedroom ... home" shows "Pièces: 6 1/2", "Beautiful 1 bedroom
    apartment" shows "Pièces: 3 1/2"). Floored, with a minimum of 1, so a bachelor's
    "1 1/2 ou 2 1/2" counts as 1. Logged in docs/decisions.md.
    """
    el = tag.select_one("span.bedrooms")
    if el is not None:
        text = _text(el).replace("½", "1/2")
        label = _BEDROOMS_LABEL_RE.search(text)
        value = (label.group(2) if label else text).strip().lower()
        if "bachelor" in value or "studio" in value:
            return 0
        match = re.match(r"(\d+)(\s*1/2)?", value)
        if match:
            rooms = int(match.group(1)) + (0.5 if match.group(2) else 0)
            if label and label.group(1).lower().startswith("pi"):  # Quebec room count
                return max(1, int(rooms - 2.5))
            return int(rooms)
    match = _SLUG_BEDROOMS_RE.match(path)
    if match:
        return int(match.group(1))
    if path.startswith("/v-bachelor-studio"):
        return 0
    return None


def _scrub_classic(html: str) -> str:
    """Strip contact details from a classic page without changing what it parses to.

    Every visible text node (titles, descriptions, image alts) goes through
    :func:`strip_contact_info`; listing URLs (``data-vip-url`` and ``/v-...`` hrefs) are
    cleaned by :func:`redact_url`, which keeps the trailing ad id; ``tel:`` links lose
    their href. Script and style bodies keep their digits (they hold the result count,
    the render time, and ad ids that phone-number rules would eat, never listing text),
    but a final pass removes emails wherever they sit, scripts included (the 2014-10-08
    capture carries the Alexa crawler's address inside its dataLayer).
    """
    soup = _soup(html)
    for node in soup.find_all(string=True):
        if type(node) is not NavigableString:  # script and style text, comments, doctypes
            continue
        clean = strip_contact_info(str(node))
        if clean != node:
            node.replace_with(clean)
    for tag in soup.select("[data-vip-url]"):
        tag["data-vip-url"] = redact_url(tag["data-vip-url"])
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.lower().startswith(("tel:", "sms:", "callto:")):
            del link["href"]
        elif href.startswith("/v-") or "kijiji.ca/v-" in href:
            link["href"] = redact_url(href)
    for img in soup.find_all("img", alt=True):
        clean = strip_contact_info(img["alt"])
        if clean != img["alt"]:
            img["alt"] = clean
    out = str(soup)
    return OBFUSCATED_EMAIL_RE.sub(REDACTED, EMAIL_RE.sub(REDACTED, out))


# --- ad pages ------------------------------------------------------------------------------

_LEGACY_RE = re.compile(r"window\.__data\s*=\s*")
_EXTRACT_RE = re.compile(r"<!-- archive-format: (\w+); extract -->\n")
_TAG_RE = re.compile(r"<[^>]+>")
_SURNAME_AFTER_REMOVED = re.compile(r"\[removed\][ \t]+[A-Z][\w'-]+")


def detect_ad_format(html: str) -> str:
    """Return which of :data:`AD_FORMATS` an archived ad page (or a stored copy) is in."""
    stored = _EXTRACT_RE.match(html) or _DROPPED_RE.search(html[:500])
    if stored:
        return stored.group(1)
    if NEXT_DATA_RE.search(html):
        try:
            root = apollo_state(html).get("ROOT_QUERY") or {}
        except ParseError:
            return "unknown"
        if any(k.startswith("listing(") for k in root):
            return "nextjs_ad"
        if any(k.startswith("searchResultsPageByUrl:") for k in root):
            return "removed"
        return "unknown"
    if _legacy_blob(html) is not None:
        return "vip_legacy"
    return "unknown"


def scrub_ad_capture(html: str) -> str:
    """Make an archived ad page safe to store.

    ``nextjs_ad`` pages go through the live :func:`scrub_page`. ``vip_legacy`` pages are
    replaced by an extract of the fields we use (title and description stripped of
    contact details; the poster's name and phone are never read), so the parse can be
    repeated without keeping personal data. Anything else becomes a one-line marker.
    """
    fmt = detect_ad_format(html)
    if fmt == "nextjs_ad":
        return _scrub_nextjs_ad(html)
    if fmt == "vip_legacy":
        detail = _legacy_detail(html)
        seller = str((_legacy_blob(html) or {}).get("sellerName") or "")
        fields = dataclasses.asdict(detail)
        fields["title"] = _without_name(strip_contact_info(detail.title) or "", seller)
        fields["description"] = _without_name(strip_contact_info(detail.description) or "", seller)
        return f"<!-- archive-format: {fmt}; extract -->\n{json.dumps(fields, sort_keys=True)}\n"
    return f"<!-- archive-format: {fmt}; body not stored -->\n"


def parse_ad_capture(text: str) -> tuple[str, DetailPage | None]:
    """Parse an archived ad page, or a stored copy of one.

    Returns:
        The format and the parsed page; the page is ``None`` for ``removed``.

    Raises:
        UnsupportedFormat: ``unknown``.
        ParseError: A known format whose contents do not have the expected shape.
    """
    fmt = detect_ad_format(text)
    if fmt == "nextjs_ad":
        return fmt, parse_detail(text)
    if fmt == "removed":
        return fmt, None
    if fmt == "vip_legacy":
        extract = _EXTRACT_RE.match(text)
        if extract:
            return fmt, DetailPage(**json.loads(text[extract.end() :]))
        return fmt, _legacy_detail(text)
    raise UnsupportedFormat(fmt)


def _scrub_nextjs_ad(html: str) -> str:
    """:func:`scrub_page`, plus the poster's name wherever it starts a line, and surnames.

    ``scrub_page`` replaces the profile name with a word-boundary regex over the raw
    page. Inside the JSON a line break is escaped as a backslash and the letter n, so a
    name that starts a line ("Thanks!!", blank line, "Alex Smith") follows a letter and
    is never matched. Here the names are also removed from the decoded titles and descriptions,
    where line breaks are real, together with a capitalised surname after them.
    """
    state = apollo_state(html)
    names = [
        str(entity["name"])
        for key, entity in state.items()
        if key.startswith("StandardProfileV2:") and isinstance(entity, dict) and entity.get("name")
    ]
    scrubbed = scrub_page(html)
    match = NEXT_DATA_RE.search(scrubbed)
    data = json.loads(match.group(1))
    entities = data["props"]["pageProps"]["__APOLLO_STATE__"].values()
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        for field in ("title", "description"):
            if isinstance(entity.get(field), str):
                text = entity[field]
                for name in names:
                    text = _without_name(text, name)
                entity[field] = _SURNAME_AFTER_REMOVED.sub("[removed]", text)
    scrubbed = scrubbed[: match.start(1)] + encode_next_data(data) + scrubbed[match.end(1) :]
    return _SURNAME_AFTER_REMOVED.sub("[removed]", scrubbed)


def _without_name(text: str, name: str) -> str:
    """Remove the poster's name from ``text``, with a capitalised surname right after it.

    The page gives the poster's display name, so it can be removed wherever it appears:
    descriptions are often signed off with the full name on a line of its own after a
    blank line ("Thanks!!", blank line, "First Last"), which :func:`strip_contact_info`
    does not catch.
    """
    name = name.strip()
    if len(name) < 3:
        return text
    return re.sub(rf"\b{re.escape(name)}\b(?:[ \t]+[A-Z][\w'-]+)?", "[removed]", text)


def _legacy_blob(html: str) -> dict | None:
    match = _LEGACY_RE.search(html)
    if not match:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, match.end())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    ad = (data.get("viewItemPage") or {}).get("viewItemData")
    return ad if isinstance(ad, dict) and ad.get("adId") else None


def _epoch_ms(value: object) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _legacy_detail(html: str) -> DetailPage:
    """Map a ``vip_legacy`` blob onto :class:`DetailPage`. Poster name and phone are not read."""
    ad = _legacy_blob(html)
    if ad is None:
        raise ParseError("no window.__data viewItemData in page")
    price = ad.get("price") or {}
    amount = price.get("amount")
    location = ad.get("adLocation") or {}
    url = ad.get("seoUrl")
    attributes = {
        a["machineKey"]: [str(a["machineValue"])]
        for a in (ad.get("adAttributes") or {}).get("attributes") or []
        if isinstance(a, dict) and a.get("machineKey") and a.get("machineValue") is not None
    }
    # Descriptions sometimes carry <br> and other markup; keep the text only.
    description = html_lib.unescape(_TAG_RE.sub("\n", ad.get("description") or ""))
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    category = ad.get("categoryId")
    return DetailPage(
        source_id=str(ad["adId"]),
        url=url.split("?")[0] if url else None,
        title=html_lib.unescape(ad.get("title") or "").strip(),
        description=description,
        price=amount / 100 if isinstance(amount, int | float) else None,
        price_type=price.get("type"),
        address_text=location.get("mapAddress") or None,
        lat=location.get("latitude"),
        lon=location.get("longitude"),
        show_pin=None,
        # This layout has no first-posting date: sortingDate is the last bump, and it is
        # also the "Posted" date the page displays.
        activation_date=None,
        sorting_date=_epoch_ms(ad.get("sortingDate")),
        end_date=None,
        status=None,
        category_id=int(category) if str(category or "").isdigit() else None,
        image_count=len(ad.get("media") or []),
        poster_id=str(ad["posterId"]) if ad.get("posterId") is not None else None,
        views=None,
        attributes=attributes,
    )
