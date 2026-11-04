"""Helpers shared by the sweep and daily tests: saved pages with their JSON edited."""

import gzip
import json
import re
from collections.abc import Callable
from pathlib import Path

from housing.parse.kijiji import NEXT_DATA_RE
from housing.parse.pii import encode_next_data
from housing.scrape.fetch import FetchResult

FIXTURES = Path(__file__).parent / "fixtures"
LISTING_TYPES = ("RealEstateListing", "StandardListing")
ROOMS_INDEX = "kijiji_index_rooms_2026-10-14.html.gz"
SHARED_ID = "1744792340"  # the one card that repeats on every page, like a promoted ad


def load(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode()


def edit_next_data(html: str, edit: Callable[[dict], None]) -> str:
    """Return ``html`` with ``edit(data)`` applied to its ``__NEXT_DATA__`` JSON."""
    match = NEXT_DATA_RE.search(html)
    data = json.loads(match.group(1))
    edit(data)
    return html[: match.start(1)] + encode_next_data(data) + html[match.end(1) :]


def with_pagination(html: str, **values) -> str:
    """Rewrite pagination fields (``offset``, ``limit``, ``totalCount``) of an index page."""

    def edit(data):
        root = data["props"]["pageProps"]["__APOLLO_STATE__"]["ROOT_QUERY"]
        srp = next(v for k, v in root.items() if k.startswith("searchResultsPageByUrl:"))
        srp["pagination"].update(values)

    return edit_next_data(html, edit)


def with_entity(html: str, source_id: str, **fields) -> str:
    """Set fields on the listing entity ``source_id`` of an index or detail page."""

    def edit(data):
        state = data["props"]["pageProps"]["__APOLLO_STATE__"]
        key = next(
            k for k in state if k.split(":")[0] in LISTING_TYPES and k.endswith(f":{source_id}")
        )
        state[key].update(fields)

    return edit_next_data(html, edit)


class FakeFetcher:
    """Serves one saved page (rooms page 1 by default) for every URL and records each call."""

    def __init__(self, text=None):
        self.text = text if text is not None else load(ROOMS_INDEX)
        self.urls = []
        self.kwargs = []
        self.requests_made = 0

    def page_for(self, url):
        return self.text

    def get(self, url, name, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        self.requests_made += 1
        path = Path("data/raw/kijiji/2026-10-14") / f"{name}.html.gz"
        return FetchResult(url, 200, self.page_for(url), path, "2026-10-14T20:00:00Z", False)


class PagedFetcher(FakeFetcher):
    """Pagination rewritten to span ``total`` listings; page N gets its own ad ids except one.

    Page 1 keeps the fixture's ids. Later pages suffix the page number to every id but
    ``SHARED_ID``, which repeats on every page the way a promoted ad does.
    """

    def __init__(self, total=120, limit=40, text=None):
        super().__init__(text)
        self.total = total
        self.limit = limit

    def page_for(self, url):
        match = re.search(r"/page-(\d+)/", url)
        page = int(match.group(1)) if match else 1
        html = with_pagination(
            self.text, offset=(page - 1) * self.limit, limit=self.limit, totalCount=self.total
        )
        if page == 1:
            return html

        def renumber(data):
            state = data["props"]["pageProps"]["__APOLLO_STATE__"]
            for key, entity in state.items():
                if key.split(":")[0] in LISTING_TYPES and str(entity.get("id")) != SHARED_ID:
                    entity["id"] = f"{entity['id']}{page}"

        return edit_next_data(html, renumber)
