"""Tests for the Wayback backfill: queueing, downloading, counting and resuming. No network."""

import gzip
import json
import sqlite3

import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.scrape.backfill import (
    captured_at,
    download,
    index_page,
    inventory,
    queue,
    rebuild,
    summary,
)
from housing.scrape.fetch import BlockedError, FetchError, FetchResult
from housing.scrape.wayback import Capture
from tests.archive_pages import ad, html_cards_page, nextjs_page, v2_page

APTS = "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212"
ROOMS = "https://www.kijiji.ca/b-room-rental-roommate/kitchener-waterloo/c36l1700212"


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    migrate(connection)
    yield connection
    connection.close()


class FakeFetcher:
    """Plays a page (or raises) per capture URL, scrubs and stores it like Fetcher.get."""

    def __init__(self, tmp_path, pages):
        self.dir = tmp_path / "raw"
        self.pages = pages
        self.calls = []

    def get(self, url, name, *, ext="html", scrub=None, **kwargs):
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        text = scrub(page) if scrub else page
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{name}.{ext}.gz"
        path.write_bytes(gzip.compress(text.encode()))
        return FetchResult(url, 200, text, path, "2026-10-16T12:00:00Z", False)


def queue_captures(conn, *timestamps, url=APTS):
    queue(conn, [Capture(ts, url) for ts in timestamps], since=2024)
    conn.commit()


def raw_url(ts, url=APTS):
    return Capture(ts, url).raw_url


def listing(conn, source_id):
    return conn.execute(
        "SELECT * FROM archive_listings WHERE source_id = ?", (source_id,)
    ).fetchone()


# --- choosing what to queue -------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (APTS, ("apartments", 1)),
        (ROOMS, ("rooms", 1)),
        (APTS + "/", ("apartments", 1)),
        (
            "http://www.kijiji.ca:80/b-apartments-condos/kitchener-waterloo/c37l1700212",
            ("apartments", 1),
        ),
        (
            "https://www.kijiji.ca/b-room-rental-roommate/kitchener-waterloo/page-3/c36l1700212",
            ("rooms", 3),
        ),
        (APTS + "?sort=priceAsc", None),
        ("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/c37l1700273", None),
        ("https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/apt/1687981149", None),
        (
            "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/2-bedroom/c37l1700212",
            None,
        ),
    ],
)
def test_index_page_accepts_only_plain_index_urls(url, expected):
    assert index_page(url) == expected


def test_captured_at():
    assert captured_at("20240421185515") == "2024-04-21T18:55:15Z"


def test_queue_keeps_one_capture_per_page_per_day_from_the_start_year(conn):
    found = [
        Capture("20170105000000", APTS),  # before 2024
        Capture("20240610080000", APTS),
        Capture("20240610200000", APTS.replace("https", "http")),  # same page, same day
        Capture("20240611080000", APTS),
        Capture("20240611080000", ROOMS),
        Capture("20240611090000", APTS + "?sort=priceAsc"),  # filtered result set
    ]
    assert queue(conn, found, since=2024) == 3
    assert queue(conn, found, since=2024) == 0  # re-running adds nothing
    rows = conn.execute("SELECT category, timestamp, status FROM archive_captures").fetchall()
    assert sorted((r[0], r[1], r[2]) for r in rows) == [
        ("apartments", "20240610080000", "pending"),
        ("apartments", "20240611080000", "pending"),
        ("rooms", "20240611080000", "pending"),
    ]


def test_inventory_queries_both_categories(conn, tmp_path):
    def cdx(*rows):
        return json.dumps([["timestamp", "original"], *rows])

    class CdxFetcher:
        def __init__(self):
            self.names = []

        def get(self, url, name, *, ext="html", **kwargs):
            self.names.append(name)
            body = cdx(["20240610080000", APTS]) if "apartments" in url else cdx()
            return type("R", (), {"text": body})()

    fetcher = CdxFetcher()
    assert inventory(conn, fetcher) == {"apartments": 1, "rooms": 0}
    assert len(fetcher.names) == 2


# --- downloading and counting ------------------------------------------------------------


def test_an_ad_seen_in_many_captures_is_one_listing_with_its_price_history(conn, tmp_path):
    queue_captures(conn, "20240610080000", "20240611080000", "20240612080000")
    a, b = ad(1, 1000), ad(2, 1500)
    pages = {
        raw_url("20240610080000"): v2_page([a, b, {**b, "top": True}]),
        raw_url("20240611080000"): v2_page([{**a, "price": 950}]),
        raw_url("20240612080000"): v2_page([{**a, "price": 900}]),
    }
    report = download(conn, FakeFetcher(tmp_path, pages), limit=10)
    assert (report.parsed, report.cards) == (3, 4)

    assert conn.execute("SELECT COUNT(*) FROM archive_listings").fetchone()[0] == 2
    one = listing(conn, "1")
    assert one["sightings"] == 3
    assert (one["first_price"], one["last_price"]) == (1000, 900)
    assert (one["min_price"], one["max_price"]) == (900, 1000)
    assert (one["first_seen"], one["last_seen"]) == ("2024-06-10T08:00:00Z", "2024-06-12T08:00:00Z")
    assert one["posted_at"] == "2024-06-01"
    assert json.loads(one["attributes"]) == {"numberbedrooms": ["2"]}
    assert listing(conn, "2")["sightings"] == 1  # the repeated top ad counted once

    cap = conn.execute("SELECT * FROM archive_captures ORDER BY timestamp").fetchone()
    assert (cap["status"], cap["format"], cap["cards"], cap["total_count"]) == (
        "parsed",
        "nextjs_v2",
        2,
        1427,
    )


def test_coordinates_fill_in_from_a_later_capture(conn, tmp_path):
    queue_captures(conn, "20240610080000", "20260101080000")
    pages = {
        raw_url("20240610080000"): v2_page([ad(1)]),
        raw_url("20260101080000"): nextjs_page([ad(1, lat=43.48)]),
    }
    download(conn, FakeFetcher(tmp_path, pages), limit=10)
    assert listing(conn, "1")["lat"] == 43.48


def test_unsupported_pages_are_recorded_and_not_stored(conn, tmp_path):
    queue_captures(conn, "20250210033232")
    fetcher = FakeFetcher(tmp_path, {raw_url("20250210033232"): html_cards_page()})
    report = download(conn, fetcher, limit=10)
    assert report.unsupported == 1
    cap = conn.execute("SELECT * FROM archive_captures").fetchone()
    assert (cap["status"], cap["format"]) == ("unsupported", "html_cards")
    stored = gzip.decompress(next(fetcher.dir.iterdir()).read_bytes()).decode()
    assert "example.com" not in stored


def test_a_block_stops_the_run_and_the_queue_resumes_later(conn, tmp_path):
    queue_captures(conn, "20240610080000", "20240611080000", "20240612080000")
    pages = {
        raw_url("20240610080000"): v2_page([ad(1)]),
        raw_url("20240611080000"): BlockedError("HTTP 429", status=429),
        raw_url("20240612080000"): v2_page([ad(3)]),
    }
    fetcher = FakeFetcher(tmp_path, pages)
    report = download(conn, fetcher, limit=10)
    assert report.blocked and (report.attempted, report.parsed) == (1, 1)
    assert len(fetcher.calls) == 2  # never asked for the third after the block

    pages[raw_url("20240611080000")] = v2_page([ad(2)])
    report = download(conn, fetcher, limit=10)
    assert (report.parsed, report.blocked) == (2, None)
    assert conn.execute("SELECT COUNT(*) FROM archive_listings").fetchone()[0] == 3


def test_failures_are_kept_for_retry_after_pending_captures(conn, tmp_path):
    queue_captures(conn, "20240610080000", "20240611080000")
    pages = {
        raw_url("20240610080000"): FetchError("HTTP 503", status=503),
        raw_url("20240611080000"): v2_page([ad(2)]),
    }
    fetcher = FakeFetcher(tmp_path, pages)
    report = download(conn, fetcher, limit=10)
    assert (report.failed, report.parsed) == (1, 1)
    failed = conn.execute("SELECT * FROM archive_captures WHERE status = 'failed'").fetchone()
    assert "503" in failed["error"]

    queue_captures(conn, "20240612080000")
    pages[raw_url("20240612080000")] = v2_page([ad(3)])
    pages[raw_url("20240610080000")] = v2_page([ad(1)])
    fetcher.calls.clear()
    download(conn, fetcher, limit=10)
    assert fetcher.calls == [raw_url("20240612080000"), raw_url("20240610080000")]


def test_consecutive_failures_stop_the_run(conn, tmp_path):
    stamps = [f"202406{d:02d}080000" for d in range(10, 16)]
    queue_captures(conn, *stamps)
    fetcher = FakeFetcher(tmp_path, {raw_url(s): FetchError("HTTP 503") for s in stamps})
    report = download(conn, fetcher, limit=10, max_failures=3)
    assert report.failed == 3 and len(fetcher.calls) == 3


def test_ads_the_daily_sweep_has_are_flagged(conn, tmp_path):
    conn.execute(
        "INSERT INTO listings (source, source_id, first_seen, last_seen, status)"
        " VALUES ('kijiji', '2', '2026-10-14T00:00:00Z', '2026-10-14T00:00:00Z', 'active')"
    )
    queue_captures(conn, "20261015080000")
    pages = {raw_url("20261015080000"): nextjs_page([ad(1), ad(2)])}
    download(conn, FakeFetcher(tmp_path, pages), limit=10)
    assert (listing(conn, "1")["in_live"], listing(conn, "2")["in_live"]) == (0, 1)
    assert "Unique ads: 2" in summary(conn)


def test_poster_ids_are_hashed_and_skipped_without_a_salt(conn, tmp_path, monkeypatch):
    queue_captures(conn, "20240610080000", "20240611080000")
    pages = {
        raw_url("20240610080000"): v2_page([ad(1)]),
        raw_url("20240611080000"): v2_page([ad(2)]),
    }
    fetcher = FakeFetcher(tmp_path, pages)
    download(conn, fetcher, limit=1)
    hashed = listing(conn, "1")["poster_hash"]
    assert hashed and "91" not in hashed

    monkeypatch.delenv("HOUSING_HASH_SALT")
    download(conn, fetcher, limit=1)
    assert listing(conn, "2")["poster_hash"] is None
    assert "HOUSING_HASH_SALT not set" in summary(conn)


def test_rebuild_reproduces_the_tables_from_stored_pages(conn, tmp_path):
    queue_captures(conn, "20240610080000", "20240611080000")
    pages = {
        raw_url("20240610080000"): v2_page([ad(1, 1000), ad(2)]),
        raw_url("20240611080000"): v2_page([ad(1, 950)]),
    }
    download(conn, FakeFetcher(tmp_path, pages), limit=10)

    def snapshot():
        return (
            [tuple(r) for r in conn.execute("SELECT * FROM archive_listings ORDER BY source_id")],
            [tuple(r) for r in conn.execute("SELECT * FROM archive_sightings ORDER BY 1, 2")],
        )

    before = snapshot()
    assert rebuild(conn) == 2
    assert snapshot() == before


def test_summary_reports_a_lower_bound_on_days_listed(conn, tmp_path):
    queue_captures(conn, "20240610080000", "20240620080000")
    a = ad(1, posted="2024-06-01T00:00:00Z")
    pages = {raw_url("20240610080000"): v2_page([a]), raw_url("20240620080000"): v2_page([a])}
    download(conn, FakeFetcher(tmp_path, pages), limit=10)
    text = summary(conn)
    assert "Unique ads: 1 from 2 sightings (1 seen in 2+ captures" in text
    row = next(line for line in text.splitlines() if line.strip().startswith("2024"))
    assert row.split()[-2:] == ["1,000", "19"]  # median first price; June 1 to June 20


def test_schema_has_the_archive_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"archive_captures", "archive_sightings", "archive_listings"} <= names
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO archive_sightings (capture_id, source_id) VALUES (999, '1')")
