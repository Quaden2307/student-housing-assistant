"""Tests for archived ad pages in the backfill: queueing, recording, extraction. No network."""

import gzip
import json
import sqlite3

import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.scrape.backfill import ad_page, download, inventory, queue_ads, rebuild
from housing.scrape.wayback import Capture
from tests.archive_pages import (
    ad,
    nextjs_ad_page,
    nextjs_page,
    removed_ad_page,
    v2_page,
    vip_legacy_page,
)
from tests.test_backfill import ROOMS, FakeFetcher, listing, queue_captures, raw_url

ROOM_AD = "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/room-near-uw/1722665773"
OTHER_AD = ROOM_AD.replace("1722665773", "1733845598")


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    migrate(connection)
    yield connection
    connection.close()


def queue_ad(conn, ts, url=ROOM_AD):
    queue_ads(conn, [Capture(ts, url)], since=2024)
    conn.commit()


def ad_url(ts, url=ROOM_AD):
    return Capture(ts, url).raw_url


def unit(conn, source_id):
    return conn.execute("SELECT * FROM archive_units WHERE source_id = ?", (source_id,)).fetchone()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (ROOM_AD, ("rooms", "1722665773")),
        (ROOM_AD + "/", ("rooms", "1722665773")),
        (
            "http://www.kijiji.ca:80/v-apartments-condos/kitchener-waterloo/2-bed/1687981149",
            ("apartments", "1687981149"),
        ),
        (ROOM_AD + "?imageNumber=3", None),
        ("https://www.kijiji.ca/v-room-rental-roommate/city-of-toronto/room/1722665773", None),
        ("https://www.kijiji.ca/v-cars-trucks/kitchener-waterloo/civic/1722665773", None),
        (ROOMS, None),
    ],
)
def test_ad_page_accepts_only_plain_kw_ad_urls(url, expected):
    assert ad_page(url) == expected


def test_queue_ads_keeps_each_ad_once_at_its_earliest_capture(conn):
    renamed = ROOM_AD.replace("room-near-uw", "updated-title")  # same ad id, new slug
    found = [
        Capture("20250901000000", renamed),
        Capture("20250831233726", ROOM_AD),
        Capture("20250902000000", ROOM_AD + "?imageNumber=2"),
        Capture("20230101000000", OTHER_AD.replace("1733845598", "1600000000")),  # before 2024
        Capture("20260308131028", OTHER_AD),
    ]
    assert queue_ads(conn, found, since=2024) == 2
    assert queue_ads(conn, found, since=2024) == 0  # re-running adds nothing
    rows = conn.execute(
        "SELECT timestamp, kind, page, category FROM archive_captures ORDER BY timestamp"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("20250831233726", "ad", 0, "rooms"),
        ("20260308131028", "ad", 0, "rooms"),
    ]


def test_inventory_queues_ad_pages_when_asked(conn):
    class CdxFetcher:
        def __init__(self):
            self.urls = []

        def get(self, url, name, *, ext="html", **kwargs):
            self.urls.append(url)
            rows = [["timestamp", "original"]]
            if "v-room-rental-roommate" in url:
                rows.append(["20250831233726", ROOM_AD])
            return type("R", (), {"text": json.dumps(rows)})()

    fetcher = CdxFetcher()
    assert inventory(conn, fetcher, ads=("rooms",)) == {
        "apartments": 0,
        "rooms": 0,
        "rooms ads": 1,
    }
    assert len(fetcher.urls) == 3 and "collapse=urlkey" in fetcher.urls[-1]


def test_a_room_ad_page_becomes_a_listing_with_text_and_unit_fields(conn, tmp_path):
    queue_ad(conn, "20250831233726")
    pages = {ad_url("20250831233726"): nextjs_ad_page(1722665773, 800)}
    report = download(conn, FakeFetcher(tmp_path, pages), limit=10)
    assert (report.parsed, report.cards) == (1, 1)

    row = listing(conn, "1722665773")
    assert (row["category"], row["first_price"], row["posted_at"]) == ("rooms", 800, "2025-08-12")
    assert "January - April 2027" in row["description"]
    for word in ("Alex", "Smith", "519-555", "example.com"):
        assert word not in row["description"], word
    assert row["lat"] == 43.47712

    u = unit(conn, "1722665773")
    assert (u["unit_type"], u["bedrooms"], u["lease_term"]) == ("room", 5, "sublet_4mo")
    assert (u["furnished"], u["utilities_included"]) == (1, 1)
    cap = conn.execute("SELECT kind, format, status FROM archive_captures").fetchone()
    assert tuple(cap) == ("ad", "nextjs_ad", "parsed")


def test_hidden_pin_coordinates_are_not_kept(conn, tmp_path):
    queue_ad(conn, "20250831233726")
    pages = {ad_url("20250831233726"): nextjs_ad_page(1722665773, show_pin=False)}
    download(conn, FakeFetcher(tmp_path, pages), limit=10)
    assert listing(conn, "1722665773")["lat"] is None


def test_legacy_ad_pages_have_no_posting_date_and_no_stored_name(conn, tmp_path):
    queue_ad(conn, "20241211094501")
    fetcher = FakeFetcher(tmp_path, {ad_url("20241211094501"): vip_legacy_page(1722665773, 1145)})
    download(conn, fetcher, limit=10)
    row = listing(conn, "1722665773")
    assert (row["first_price"], row["posted_at"]) == (1145, None)
    sighting = conn.execute("SELECT sorting_date FROM archive_sightings").fetchone()
    assert sighting[0] == "2024-12-08T18:58:32Z"
    stored = gzip.decompress(next(fetcher.dir.iterdir()).read_bytes()).decode()
    assert "Alex" not in stored and "sellerName" not in stored


def test_a_removed_ad_is_recorded_as_removed(conn, tmp_path):
    queue_ad(conn, "20250831233726")
    report = download(
        conn, FakeFetcher(tmp_path, {ad_url("20250831233726"): removed_ad_page()}), limit=10
    )
    assert report.removed == 1
    assert conn.execute("SELECT status FROM archive_captures").fetchone()[0] == "removed"
    assert conn.execute("SELECT COUNT(*) FROM archive_listings").fetchone()[0] == 0


def test_an_ad_on_an_index_page_and_its_own_page_is_one_listing(conn, tmp_path):
    queue_captures(conn, "20250901080000", url=ROOMS)
    queue_ad(conn, "20250831233726")
    pages = {
        raw_url("20250901080000", ROOMS): nextjs_page([ad(1722665773, 750)]),
        ad_url("20250831233726"): nextjs_ad_page(1722665773, 800),
    }
    download(conn, FakeFetcher(tmp_path, pages), limit=10)
    row = listing(conn, "1722665773")
    assert row["sightings"] == 2
    assert (row["first_price"], row["last_price"]) == (800, 750)  # the ad page came first
    assert row["description"] is not None


def test_index_only_ads_get_unit_fields_from_their_attributes(conn, tmp_path):
    queue_captures(conn, "20240610080000")
    pages = {raw_url("20240610080000"): v2_page([ad(1, beds="2")])}
    download(conn, FakeFetcher(tmp_path, pages), limit=1)
    u = unit(conn, "1")
    assert (u["unit_type"], u["bedrooms"]) == ("2bed", 2)


def test_rebuild_reproduces_index_and_ad_captures(conn, tmp_path):
    queue_captures(conn, "20240610080000")
    queue_ad(conn, "20241211094501")
    queue_ad(conn, "20250831233726", url=OTHER_AD)
    pages = {
        raw_url("20240610080000"): v2_page([ad(1)]),
        ad_url("20241211094501"): vip_legacy_page(1722665773),
        ad_url("20250831233726", OTHER_AD): nextjs_ad_page(1733845598),
    }
    download(conn, FakeFetcher(tmp_path, pages), limit=10)

    def snapshot():
        tables = [
            [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
            for t in ("archive_listings", "archive_sightings")
        ]
        # Every column but extracted_at, which is the run's clock, must match exactly.
        units = conn.execute(
            "SELECT source_id, unit_type, bedrooms, bathrooms, lease_term, move_in_month,"
            " utilities_included, furnished, laundry_in_unit, building_type,"
            " year_built_after_2018, extracted_by, flags FROM archive_units ORDER BY source_id"
        ).fetchall()
        return tables, [tuple(r) for r in units]

    before = snapshot()
    assert rebuild(conn) == 3
    assert snapshot() == before


def test_migrate_adds_the_new_columns_to_an_older_archive(tmp_path):
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript(
        """
        CREATE TABLE archive_captures (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL,
          original TEXT NOT NULL, category TEXT NOT NULL, page INTEGER NOT NULL,
          captured_at TEXT NOT NULL, status TEXT NOT NULL, format TEXT, cards INTEGER,
          total_count INTEGER, raw_path TEXT, fetched_at TEXT, error TEXT,
          UNIQUE(timestamp, original));
        INSERT INTO archive_captures (timestamp, original, category, page, captured_at, status)
          VALUES ('20240610080000', 'x', 'apartments', 1, '2024-06-10T08:00:00Z', 'parsed');
        CREATE TABLE archive_listings (source_id TEXT PRIMARY KEY, category TEXT,
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
        """
    )
    old.commit()
    old.close()
    conn = connect(tmp_path / "old.db")
    migrate(conn)
    assert conn.execute("SELECT kind FROM archive_captures").fetchone()[0] == "index"
    assert "description" in {r[1] for r in conn.execute("PRAGMA table_info(archive_listings)")}
    migrate(conn)  # and again: nothing to add, no error
    conn.close()
