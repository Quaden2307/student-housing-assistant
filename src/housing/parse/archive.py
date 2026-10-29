"""Parse archived (Wayback Machine) Kijiji index pages into index cards.

Kijiji's index page changed shape over the years, so a capture is classified before it
is parsed. Formats seen in 2024 to 2026 captures:

- ``nextjs``: today's page. ``__NEXT_DATA__`` with ``mainListings`` and
  ``RealEstateListing``/``StandardListing`` entities. Parsed by the live parser,
  :func:`housing.parse.kijiji.parse_index`, so archive and live cards are identical.
- ``nextjs_v2``: an older Next.js page (e.g. 2024-04-21). The same data under
  ``results.organic``/``results.topAds``, ``ListingV2`` entities, attributes as
  ``{name, values}`` and **no coordinates**.
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
from datetime import UTC, datetime

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
from housing.parse.pii import encode_next_data, scrub_page, strip_contact_info

FORMATS = ("nextjs", "nextjs_v2", "html_cards", "unknown")
AD_FORMATS = ("nextjs_ad", "vip_legacy", "removed", "unknown")

_DROPPED_RE = re.compile(r"<!-- archive-format: (\w+); body not stored -->")


class UnsupportedFormat(ParseError):
    """The capture is in a format this module does not parse (yet)."""

    def __init__(self, fmt: str) -> None:
        super().__init__(f"archived page format {fmt!r} is not parsed")
        self.format = fmt


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
    return "unknown"


def scrub_capture(html: str) -> str:
    """Make an archived page safe to store, per the privacy rule.

    Next.js formats go through the live pipeline's :func:`scrub_page`. Any other format
    is replaced by a one-line marker naming the format, so nothing unscrubbed is written
    to ``data/raw/`` and :func:`detect_format` still reports what the page was. Such
    captures are downloaded again once a parser and scrubber exist for them.
    """
    fmt = detect_format(html)
    if fmt in ("nextjs", "nextjs_v2"):
        return scrub_page(html)
    return f"<!-- archive-format: {fmt}; body not stored -->\n"


def parse_capture(html: str) -> tuple[str, int, list[IndexCard]]:
    """Parse an archived index page.

    Returns:
        The format, Kijiji's total listing count for the category at capture time, and
        the cards (unique by ad id, main listings first).

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
