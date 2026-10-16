"""Parse Kijiji pages from the embedded Next.js JSON, not the HTML.

Every Kijiji page carries its data in ``<script id="__NEXT_DATA__">`` as a normalized Apollo
cache under ``props.pageProps.__APOLLO_STATE__``. What lives where is recorded in
``docs/sources.md`` section 1, and the saved pages under ``tests/fixtures/`` pin it down:
``tests/test_parse_kijiji.py`` is the early warning when Kijiji changes layout.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

BASE_URL = "https://www.kijiji.ca"
LOCATION = "kitchener-waterloo"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


@dataclass(frozen=True)
class Category:
    """One Kijiji category we sweep."""

    name: str
    slug: str
    code: str
    category_id: int


CATEGORIES: dict[str, Category] = {
    "apartments": Category("apartments", "b-apartments-condos", "c37l1700212", 37),
    "rooms": Category("rooms", "b-room-rental-roommate", "c36l1700212", 36),
}


class ParseError(ValueError):
    """The page does not have the structure we expect; Kijiji may have changed layout."""


class AdRemovedError(ParseError):
    """A detail URL was redirected to the search page: the ad has been taken down."""


@dataclass(frozen=True)
class IndexCard:
    """One listing as it appears on an index page."""

    source_id: str
    url: str | None
    title: str
    price: float | None
    """Dollars per month; None when the ad says "Please Contact"."""
    price_type: str | None
    """``FIXED`` or ``CONTACT``."""
    address_text: str | None
    lat: float | None
    lon: float | None
    activation_date: str | None
    """First posted, ISO UTC."""
    sorting_date: str | None
    """Last bumped, ISO UTC."""
    neighbourhood: str | None
    intersection: str | None
    category_id: int | None
    ad_source: str | None
    """``ORGANIC`` or ``TOP_AD``."""
    poster_id: str | None = None
    """Kijiji's account id for the poster; stored only as a salted hash."""
    image_count: int = 0
    attributes: dict[str, list[str]] = field(default_factory=dict)
    """Kijiji attributes by canonical name, e.g. ``{"numberbedrooms": ["2"]}``."""


@dataclass(frozen=True)
class IndexPage:
    """One parsed index page."""

    total_count: int
    offset: int
    limit: int
    cards: list[IndexCard]


def index_url(category: str, page: int = 1) -> str:
    """Return the index URL for a category and 1-based page, without any query string."""
    cat = CATEGORIES[category]
    base = f"{BASE_URL}/{cat.slug}/{LOCATION}"
    return f"{base}/{cat.code}" if page == 1 else f"{base}/page-{page}/{cat.code}"


def next_data(html: str) -> dict:
    """Return the parsed ``__NEXT_DATA__`` JSON of a Kijiji page."""
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ParseError("no __NEXT_DATA__ script tag in page")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ParseError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc


def apollo_state(html: str) -> dict:
    """Return the normalized Apollo cache of a Kijiji page."""
    try:
        return next_data(html)["props"]["pageProps"]["__APOLLO_STATE__"]
    except (KeyError, TypeError) as exc:
        raise ParseError(f"missing {exc} in __NEXT_DATA__") from exc


def parse_index(html: str) -> IndexPage:
    """Parse an index page into its pagination info and listing cards.

    Main listings come first, then promoted top listings not already present. Cards are
    unique by ad id within the page.
    """
    state = apollo_state(html)
    root = state.get("ROOT_QUERY") or {}
    srp_key = next((k for k in root if k.startswith("searchResultsPageByUrl:")), None)
    if srp_key is None:
        raise ParseError("no searchResultsPageByUrl entry in the Apollo cache")
    srp = root[srp_key]
    pagination = srp.get("pagination") or {}
    results = srp.get("results") or {}
    total_count = int(pagination.get("totalCount") or 0)
    main_key = next((k for k in results if k.startswith("mainListings")), None)
    if main_key is None and total_count > 0:
        raise ParseError("no mainListings in searchResultsPageByUrl")

    refs: list[str] = []
    if main_key:
        refs += [r["__ref"] for r in results.get(main_key) or []]
    refs += [r["__ref"] for r in results.get("topListings") or []]

    cards: list[IndexCard] = []
    seen: set[str] = set()
    for ref in refs:
        entity = state.get(ref)
        if not entity:
            continue
        source_id = str(entity.get("id"))
        if source_id in seen:
            continue
        seen.add(source_id)
        cards.append(_card(entity, state))

    return IndexPage(
        total_count=total_count,
        offset=int(pagination.get("offset") or 0),
        limit=int(pagination.get("limit") or 40),
        cards=cards,
    )


def _card(entity: dict, state: dict) -> IndexCard:
    price = entity.get("price") or {}
    amount = price.get("amount")
    location = entity.get("location") or {}
    coords = location.get("coordinates") or {}
    hood = location.get("neighbourhoodInfo")
    hood_name = None
    if isinstance(hood, dict):
        hood_name = (
            state.get(hood["__ref"], {}).get("name") if "__ref" in hood else hood.get("name")
        )
    attributes: dict[str, list[str]] = {}
    for attr in (entity.get("attributes") or {}).get("all") or []:
        name = attr.get("canonicalName")
        if name:
            attributes[name] = [str(v) for v in attr.get("canonicalValues") or []]
    url = entity.get("url")
    intersection = location.get("nearestIntersection") or []
    poster = entity.get("posterInfo") or {}
    return IndexCard(
        source_id=str(entity.get("id")),
        url=url.split("?")[0] if url else None,
        title=(entity.get("title") or "").strip(),
        price=amount / 100 if isinstance(amount, int | float) else None,
        price_type=price.get("type"),
        address_text=location.get("address") or None,
        lat=coords.get("latitude"),
        lon=coords.get("longitude"),
        activation_date=entity.get("activationDate"),
        sorting_date=entity.get("sortingDate"),
        neighbourhood=hood_name,
        intersection=" & ".join(str(x) for x in intersection) or None,
        category_id=entity.get("categoryId"),
        ad_source=entity.get("adSource"),
        poster_id=str(poster["posterId"]) if poster.get("posterId") is not None else None,
        image_count=int(entity.get("imageCount") or 0),
        attributes=attributes,
    )


def category_name(category_id: int | None) -> str | None:
    """Map a Kijiji category id to our category name (``apartments`` or ``rooms``)."""
    for cat in CATEGORIES.values():
        if cat.category_id == category_id:
            return cat.name
    return None


@dataclass(frozen=True)
class DetailPage:
    """One listing's detail page. Poster name and phone number are never read."""

    source_id: str
    url: str | None
    title: str
    description: str
    price: float | None
    price_type: str | None
    address_text: str | None
    lat: float | None
    lon: float | None
    show_pin: bool | None
    """False means Kijiji rounded the coordinates to about a kilometre; prefer the card's."""
    activation_date: str | None
    sorting_date: str | None
    end_date: str | None
    status: str | None
    category_id: int | None
    image_count: int
    poster_id: str | None
    views: int | None
    attributes: dict[str, list[str]] = field(default_factory=dict)


def parse_detail(html: str) -> DetailPage:
    """Parse a detail page (``/v-.../<ad id>``) from its embedded JSON.

    Attribute values come from ``canonicalValues`` when present, otherwise from the display
    ``values`` (Kijiji leaves ``canonicalValues`` empty for dates and square footage there).

    Raises:
        AdRemovedError: The page is a search results page, which is where Kijiji redirects
            the URL of an ad that has been taken down.
        ParseError: Anything else unexpected in the page.
    """
    state = apollo_state(html)
    root = state.get("ROOT_QUERY") or {}
    key = next((k for k in root if k.startswith("listing(")), None)
    if key is None:
        if any(k.startswith("searchResultsPageByUrl:") for k in root):
            raise AdRemovedError("redirected to the search page: the ad was removed")
        raise ParseError("no listing(...) entry in the Apollo cache")
    ref = root[key].get("__ref") if isinstance(root[key], dict) else None
    entity = state.get(ref) if ref else None
    if not entity:
        raise ParseError("listing entity missing from the Apollo cache")

    price = entity.get("price") or {}
    amount = price.get("amount")
    location = entity.get("location") or {}
    coords = location.get("coordinates") or {}
    attributes: dict[str, list[str]] = {}
    for attr in (entity.get("attributes") or {}).get("all") or []:
        name = attr.get("canonicalName")
        if not name:
            continue
        values = attr.get("canonicalValues") or attr.get("values") or []
        attributes[name] = [str(v) for v in values]
    url = entity.get("url")
    poster = entity.get("posterInfo") or {}
    metrics = entity.get("metrics") or {}
    return DetailPage(
        source_id=str(entity.get("id")),
        url=url.split("?")[0] if url else None,
        title=(entity.get("title") or "").strip(),
        description=(entity.get("description") or "").replace("\r\n", "\n").strip(),
        price=amount / 100 if isinstance(amount, int | float) else None,
        price_type=price.get("type"),
        address_text=location.get("address") or None,
        lat=coords.get("latitude"),
        lon=coords.get("longitude"),
        show_pin=location.get("showPinOnMap"),
        activation_date=entity.get("activationDate"),
        sorting_date=entity.get("sortingDate"),
        end_date=entity.get("endDate"),
        status=entity.get("status"),
        category_id=entity.get("categoryId"),
        image_count=len(entity.get("imageUrls") or []),
        poster_id=str(poster["posterId"]) if poster.get("posterId") is not None else None,
        views=metrics.get("views"),
        attributes=attributes,
    )
