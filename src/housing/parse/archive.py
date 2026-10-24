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
"""

from __future__ import annotations

import re

from housing.parse.kijiji import (
    BASE_URL,
    NEXT_DATA_RE,
    IndexCard,
    ParseError,
    apollo_state,
    parse_index,
)
from housing.parse.pii import scrub_page

FORMATS = ("nextjs", "nextjs_v2", "html_cards", "unknown")

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
