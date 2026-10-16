"""Helpers shared by the sweep and daily tests: saved pages with their JSON edited."""

import gzip
import json
from collections.abc import Callable
from pathlib import Path

from housing.parse.kijiji import NEXT_DATA_RE
from housing.parse.pii import encode_next_data

FIXTURES = Path(__file__).parent / "fixtures"
LISTING_TYPES = ("RealEstateListing", "StandardListing")


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
