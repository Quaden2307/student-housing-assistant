"""Wayback Machine capture listing through the CDX API (HANDOFF.md section 4).

The CDX API lists every archived capture of a URL or URL prefix. It is how we
size the history available for Kitchener-Waterloo listings and, later, how the
backfill finds the captures to download and parse.

``web.archive.org/robots.txt`` returns 404 (checked 2026-10-15), so it places
no restrictions. All requests still go through :class:`~housing.scrape.fetch.Fetcher`
for rate limiting, retries and raw storage (``data/raw/wayback/<date>/``), with a
User-Agent that says who we are.

CDX reference: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlencode

from housing.scrape.fetch import Fetcher

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"

USER_AGENT = (
    "student-housing-assistant/0.1 (UW Data Science Club research; "
    "https://github.com/Quaden2307/student-housing-assistant)"
)
"""The Internet Archive asks automated clients to identify themselves."""


@dataclass(frozen=True)
class Capture:
    """One archived capture.

    Attributes:
        timestamp: ``YYYYMMDDhhmmss``, UTC.
        original: The URL as it was captured.
    """

    timestamp: str
    original: str

    @property
    def year(self) -> str:
        """``YYYY`` of the capture."""
        return self.timestamp[:4]

    @property
    def month(self) -> str:
        """``YYYY-MM`` of the capture."""
        return f"{self.timestamp[:4]}-{self.timestamp[4:6]}"

    @property
    def raw_url(self) -> str:
        """The capture's original bytes, without the Wayback toolbar or link rewriting."""
        return f"https://web.archive.org/web/{self.timestamp}id_/{self.original}"


def cdx_url(pattern: str, *, collapse: str | None = None, limit: int | None = None) -> str:
    """Build a CDX query for successful (HTTP 200) captures of ``pattern``.

    Args:
        pattern: A URL, or a prefix ending in ``/*`` for everything under it.
        collapse: CDX collapse key. ``timestamp:8`` keeps one capture per URL per
            day; ``urlkey`` keeps only the first capture of each distinct URL.
        limit: Maximum rows to return.
    """
    params = {"url": pattern, "output": "json", "fl": "timestamp,original"}
    params["filter"] = "statuscode:200"
    if collapse:
        params["collapse"] = collapse
    if limit is not None:
        params["limit"] = str(limit)
    return f"{CDX_ENDPOINT}?{urlencode(params)}"


def parse_cdx(body: bytes | str) -> list[Capture]:
    """Parse a CDX ``output=json`` response.

    The response is a JSON list of rows whose first row is the field names. An
    empty body or ``[]`` means no captures.
    """
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    if not text.strip():
        return []
    rows = json.loads(text)
    if not rows:
        return []
    header = rows[0]
    ts, orig = header.index("timestamp"), header.index("original")
    return [Capture(row[ts], row[orig]) for row in rows[1:]]


def raw_stem(pattern: str, collapse: str | None = None) -> str:
    """File stem for a CDX query's raw copy, e.g. ``cdx_kijiji_ca_b_rooms_timestamp_8``."""
    parts = [pattern, collapse or ""]
    return "cdx_" + "_".join(re.sub(r"[^A-Za-z0-9]+", "_", p).strip("_") for p in parts if p)


def captures(fetcher: Fetcher, pattern: str, *, collapse: str | None = None) -> list[Capture]:
    """Return the HTTP 200 captures of ``pattern``, fetched politely and stored raw.

    The same query on the same day is served from the raw copy.
    """
    result = fetcher.get(
        cdx_url(pattern, collapse=collapse), raw_stem(pattern, collapse), ext="json"
    )
    return parse_cdx(result.text)


def count_by(items: Iterable[Capture], period: str = "month") -> Counter[str]:
    """Count captures per ``year`` or ``month``."""
    if period not in ("year", "month"):
        raise ValueError(f"period must be 'year' or 'month', not {period!r}")
    return Counter(getattr(c, period) for c in items)


def make_fetcher() -> Fetcher:
    """A fetcher for the Wayback Machine: raw files under ``data/raw/wayback/``.

    CDX queries over a URL prefix can take a minute to answer, hence the long timeout.
    """
    fetcher = Fetcher("wayback", timeout=180.0)
    # Fetcher sends a desktop browser User-Agent by default (the Kijiji playbook); the
    # Internet Archive prefers clients that identify themselves.
    fetcher.session.headers["User-Agent"] = USER_AGENT
    return fetcher
