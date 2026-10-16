"""Tests for the Wayback CDX helpers. No network."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from housing.scrape.wayback import (
    USER_AGENT,
    Capture,
    captures,
    cdx_url,
    count_by,
    make_fetcher,
    parse_cdx,
    raw_stem,
)

ROWS = [
    ["timestamp", "original"],
    ["20160420090313", "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212"],
    ["20240421185515", "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212"],
    [
        "20240402120000",
        "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/page-2/c37l1700212",
    ],
    ["20250210033232", "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212"],
]


def test_query_asks_for_successful_captures_as_json():
    url = cdx_url("kijiji.ca/b-apartments-condos/kitchener-waterloo/*", collapse="timestamp:8")
    parts = urlsplit(url)
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://web.archive.org/cdx/search/cdx"
    )
    assert parse_qs(parts.query) == {
        "url": ["kijiji.ca/b-apartments-condos/kitchener-waterloo/*"],
        "output": ["json"],
        "fl": ["timestamp,original"],
        "filter": ["statuscode:200"],
        "collapse": ["timestamp:8"],
    }
    assert "limit" in parse_qs(urlsplit(cdx_url("x", limit=5)).query)


def test_parse_reads_rows_after_the_header():
    caps = parse_cdx(json.dumps(ROWS).encode())
    assert len(caps) == 4
    assert caps[0] == Capture("20160420090313", ROWS[1][1])


def test_parse_finds_columns_by_name():
    swapped = [["original", "timestamp"], [ROWS[1][1], ROWS[1][0]]]
    assert parse_cdx(json.dumps(swapped)) == [Capture(ROWS[1][0], ROWS[1][1])]


@pytest.mark.parametrize("body", [b"", b"  \n", b"[]"])
def test_no_captures(body):
    assert parse_cdx(body) == []


def test_periods_and_raw_url():
    cap = Capture("20240421185515", "https://www.kijiji.ca/b-x/c37l1700212")
    assert (cap.year, cap.month) == ("2024", "2024-04")
    assert cap.raw_url == (
        "https://web.archive.org/web/20240421185515id_/https://www.kijiji.ca/b-x/c37l1700212"
    )


def test_count_by_year_and_month():
    caps = parse_cdx(json.dumps(ROWS))
    assert count_by(caps, "year") == {"2016": 1, "2024": 2, "2025": 1}
    assert count_by(caps, "month") == {"2016-04": 1, "2024-04": 2, "2025-02": 1}
    with pytest.raises(ValueError):
        count_by(caps, "week")


def test_raw_stems_are_readable_and_distinct():
    pattern = "kijiji.ca/b-room-rental-roommate/kitchener-waterloo/*"
    assert raw_stem(pattern, "timestamp:8") == (
        "cdx_kijiji_ca_b_room_rental_roommate_kitchener_waterloo_timestamp_8"
    )
    assert raw_stem(pattern, "urlkey") != raw_stem(pattern, "timestamp:8")
    assert raw_stem(pattern) == "cdx_kijiji_ca_b_room_rental_roommate_kitchener_waterloo"


def test_fetcher_identifies_the_project():
    assert make_fetcher().session.headers["User-Agent"] == USER_AGENT


class FakeFetcher:
    """Stands in for Fetcher.get: records the call and returns CDX JSON."""

    def __init__(self, body):
        self.body = body
        self.calls = []

    def get(self, url, name, *, ext="html", **kwargs):
        self.calls.append((url, name, ext))
        return type("Result", (), {"text": self.body})()


def test_captures_goes_through_the_fetcher_and_parses():
    fake = FakeFetcher(json.dumps(ROWS))
    caps = captures(fake, "kijiji.ca/b-apartments-condos/kitchener-waterloo/*", collapse="urlkey")
    assert len(caps) == 4
    ((url, name, ext),) = fake.calls
    assert "collapse=urlkey" in url and ext == "json"
    assert name == raw_stem("kijiji.ca/b-apartments-condos/kitchener-waterloo/*", "urlkey")
