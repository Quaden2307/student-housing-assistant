"""The daily run end to end against fake pages: sweep, gone rule, details, extraction, features, report."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.parse.extract import main as extract_main
from housing.parse.pii import REDACTED
from housing.scrape import daily
from housing.scrape.daily import DailyReport, run
from housing.scrape.fetch import BlockedError, FetchError, FetchResult
from housing.scrape.kijiji import SweepStats, fetch_details
from tests.helpers import load, with_entity, with_pagination

APARTMENTS = "kijiji_index_apartments_2026-10-14.html.gz"
ROOMS = "kijiji_index_rooms_2026-10-14.html.gz"
DETAIL = "kijiji_detail_rooms_2026-10-14.html.gz"
DETAIL_ID = "1744792340"
DAY1 = datetime(2026, 10, 15, 6, 30, tzinfo=UTC)
DAY2 = datetime(2026, 10, 16, 6, 30, tzinfo=UTC)
ROOM_URL = "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/x/"


class FakeFetcher:
    """Serves the saved index pages as complete one-page categories, plus one saved detail page.

    ``totalCount`` is rewritten to 40 so page 1 is the last page; ``complete=False`` keeps
    the real pagination (1,612 and 260 listings), which a one-page sweep cannot cover. The
    detail page is served with the requested ad id; every second request is served broken
    unless ``detail_ok`` decides otherwise.
    """

    def __init__(self, *, blocked=False, complete=True, pages=None, detail=None, detail_ok=None):
        self.pages = pages or {"apartments": load(APARTMENTS), "rooms": load(ROOMS)}
        if complete:
            self.pages = {k: with_pagination(v, totalCount=40) for k, v in self.pages.items()}
        self.detail = detail or load(DETAIL)
        self.detail_ok = detail_ok or (lambda n: n % 2 == 1)
        self.blocked = blocked
        self.requests_made = 0
        self.detail_requests = 0

    def get(self, url, name, **kwargs):
        self.requests_made += 1
        if self.blocked:
            raise BlockedError(f"HTTP 403 with a block or challenge for {url}", status=403)
        if name.startswith("detail_"):
            self.detail_requests += 1
            if self.detail_ok(self.detail_requests):
                text = self.detail.replace(DETAIL_ID, name.removeprefix("detail_"))
            else:
                text = "<html>no next data</html>"
        else:
            text = self.pages["rooms" if "room-rental" in url else "apartments"]
        path = Path("data/raw/kijiji/x") / f"{name}.html.gz"
        return FetchResult(url, 200, text, path, "2026-10-15T06:31:00Z", False)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSING_DATA_DIR", str(tmp_path))
    connection = connect(tmp_path / "t.db")
    migrate(connection)
    yield connection
    connection.close()


def add_listing(conn, source_id, last_seen):
    conn.execute(
        "INSERT INTO listings (source, source_id, url, first_seen, last_seen, status)"
        " VALUES ('kijiji', ?, ?, '2026-10-10T00:00:00Z', ?, 'active')",
        (source_id, ROOM_URL + source_id, last_seen),
    )
    conn.commit()


def status_of(conn, source_id):
    return conn.execute("SELECT status FROM listings WHERE source_id = ?", (source_id,)).fetchone()[
        0
    ]


def attributes_of(conn, listing_id):
    rows = conn.execute(
        "SELECT name, value FROM listing_attributes WHERE listing_id = ?", (listing_id,)
    ).fetchall()
    return dict(rows)


def stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_daily_run_populates_every_table(conn):
    report = run(conn, FakeFetcher(), max_details=2, max_pages=1, now=DAY1)
    assert [s.seen for s in report.sweeps] == [45, 41] and report.exit_code == 0
    assert report.gone == 0 and report.listings_total == 86 and report.listings_active == 86
    assert (report.details.fetched, report.details.failed, report.details.removed) == (1, 1, 0)
    assert report.units_extracted == 86 and report.features_rows == 86
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("units", "features", "listing_attributes")
    }
    assert (
        counts["units"] == 86 and counts["features"] == 86 and counts["listing_attributes"] > 86 * 5
    )
    fetched = conn.execute("SELECT id FROM listings WHERE length(description) > 1000").fetchall()
    assert len(fetched) == 1
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE description = ''").fetchone()[0] == 0
    good = attributes_of(conn, fetched[0][0])
    assert (
        good["detail_status"] == "ACTIVE"
        and good["detail_fetched_at"]
        and "detail_error" not in good
    )
    failed = conn.execute(
        "SELECT listing_id FROM listing_attributes WHERE name = 'detail_failed_at'"
    ).fetchall()
    assert len(failed) == 1
    bad = attributes_of(conn, failed[0][0])
    assert "no __NEXT_DATA__" in bad["detail_error"] and "detail_fetched_at" not in bad
    rooms_units = conn.execute(
        "SELECT COUNT(*) FROM units u JOIN listing_attributes a ON a.listing_id = u.listing_id"
        " WHERE a.name = 'category' AND a.value = 'rooms' AND u.unit_type = 'room'"
    ).fetchone()[0]
    assert rooms_units >= 35
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM features WHERE price_per_bedroom IS NOT NULL"
        ).fetchone()[0]
        > 70
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM units WHERE extracted_by = 'page_attrs'").fetchone()[0]
        >= 45
    )
    names = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT name FROM listing_attributes WHERE name LIKE 'text%'"
        )
    }
    assert "text_per_room_price" in names and "per_room_price" not in names
    assert "ALERT" not in report.message() and "apartments 45 seen (45 new)" in report.message()


def test_gone_rule_needs_two_missed_days(conn):
    run(conn, FakeFetcher(), max_details=0, max_pages=1, now=DAY1)
    add_listing(conn, "missed-once", stamp(DAY1 - timedelta(hours=24)))
    add_listing(conn, "missed-39h", stamp(DAY1 - timedelta(hours=39)))
    add_listing(conn, "missed-41h", stamp(DAY1 - timedelta(hours=41)))
    add_listing(conn, "missed-twice", stamp(DAY1 - timedelta(hours=48)))
    report = run(conn, FakeFetcher(), max_details=0, max_pages=1, now=DAY1)
    assert report.gone == 2 and "ALERT" not in report.message()
    assert status_of(conn, "missed-once") == "active" and status_of(conn, "missed-39h") == "active"
    assert status_of(conn, "missed-41h") == "gone" and status_of(conn, "missed-twice") == "gone"
    # Every card on the page was seen again and stays active.
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE status = 'active'").fetchone()[0] == 88


def test_capped_sweep_marks_nothing_gone_and_alerts(conn):
    add_listing(conn, "stale", "2026-10-13T06:30:00Z")
    report = run(conn, FakeFetcher(complete=False), max_details=0, max_pages=1, now=DAY1)
    assert report.sweeps[0].total_count == 1612 and all(s.stopped_early for s in report.sweeps)
    assert report.gone == 0 and status_of(conn, "stale") == "active" and report.exit_code == 3
    assert report.message().startswith("ALERT") and "page cap 1" in report.message()


def test_blocked_run_marks_nothing_gone_and_alerts(conn):
    add_listing(conn, "stale", "2026-10-13T06:30:00Z")
    report = run(conn, FakeFetcher(blocked=True), max_details=0, max_pages=1, now=DAY1)
    assert report.exit_code == 2 and report.sweeps == [] and report.gone == 0
    assert status_of(conn, "stale") == "active"
    assert report.message().startswith("ALERT") and "blocked" in report.message()


def test_parse_failure_marks_nothing_gone_and_alerts(conn):
    add_listing(conn, "stale", "2026-10-13T06:30:00Z")
    fetcher = FakeFetcher()
    fetcher.pages["rooms"] = "<html>not kijiji</html>"
    report = run(conn, fetcher, max_details=0, max_pages=1, now=DAY1)
    assert report.exit_code == 3 and len(report.sweeps) == 1 and report.gone == 0
    assert status_of(conn, "stale") == "active"
    assert report.message().startswith("ALERT") and "rooms parse failure" in report.message()


def test_fetch_error_during_sweep_is_reported_not_raised(conn):
    add_listing(conn, "stale", "2026-10-13T06:30:00Z")

    class FlakyFetcher(FakeFetcher):
        def get(self, url, name, **kwargs):
            if "room-rental" in url:
                raise FetchError(f"gave up on {url} after 3 attempts: HTTP 503", status=503)
            return super().get(url, name, **kwargs)

    report = run(conn, FlakyFetcher(), max_details=0, max_pages=1, now=DAY1)
    assert report.exit_code == 4 and report.gone == 0 and status_of(conn, "stale") == "active"
    assert report.message().startswith("ALERT") and "rooms fetch failure" in report.message()


def test_stuck_pagination_alerts(conn):
    # Every URL serves page 1, so page 2 comes back with offset 0.
    report = run(conn, FakeFetcher(complete=False), max_details=0, max_pages=5, now=DAY1)
    assert all("page 2 came back as page 1" in s.stopped_early for s in report.sweeps)
    assert report.message().startswith("ALERT") and report.exit_code == 3 and report.gone == 0


def test_report_alerts_on_zero_seen_or_a_missing_category():
    report = DailyReport(
        started_at="2026-10-15T06:30:00Z",
        sweeps=[SweepStats("apartments", pages=1, seen=45), SweepStats("rooms", pages=1, seen=0)],
    )
    assert report.message().startswith("ALERT") and "rooms: 0 seen" in report.message()
    one = DailyReport(started_at="2026-10-15T06:30:00Z", sweeps=[SweepStats("apartments", seen=45)])
    assert one.message().startswith("ALERT") and "1 of 2 categories" in one.message()


def test_contact_info_is_stripped_before_storage(conn):
    pages = {
        "apartments": with_entity(load(APARTMENTS), "1744430634", title="Call 519-555-0199 now"),
        "rooms": load(ROOMS),
    }
    detail = with_entity(
        load(DETAIL),
        DETAIL_ID,
        description="Nice room. Call 519-555-0199 or landlord@example.com. Ask for Candice.",
    )
    fetcher = FakeFetcher(pages=pages, detail=detail, detail_ok=lambda n: True)
    run(conn, fetcher, max_details=1, max_pages=1, now=DAY1)
    text = " ".join(
        f"{t or ''} {d or ''} {u or ''}"
        for t, d, u in conn.execute("SELECT title, description, url FROM listings")
    )
    assert "519-555-0199" not in text and "example.com" not in text and "Candice" not in text
    assert text.count(REDACTED) >= 4


def test_units_are_rewritten_after_details_arrive(conn):
    run(conn, FakeFetcher(), max_details=0, max_pages=1, now=DAY1)
    detail = with_entity(
        load(DETAIL),
        DETAIL_ID,
        description="Fully furnished room, 2 bathrooms, ensuite laundry, all inclusive.",
    )
    run(
        conn,
        FakeFetcher(detail=detail, detail_ok=lambda n: True),
        max_details=1,
        max_pages=1,
        now=DAY2,
    )
    lid = conn.execute(
        "SELECT id FROM listings WHERE description LIKE 'Fully furnished%'"
    ).fetchone()[0]
    row = conn.execute(
        "SELECT furnished, bathrooms, laundry_in_unit, utilities_included FROM units WHERE listing_id = ?",
        (lid,),
    ).fetchone()
    assert tuple(row) == (1, 2.0, 1, 1)


def test_failed_detail_is_retried_after_three_days(conn):
    run(conn, FakeFetcher(detail_ok=lambda n: False), max_details=1, max_pages=1, now=DAY1)
    (lid,) = conn.execute(
        "SELECT listing_id FROM listing_attributes WHERE name = 'detail_failed_at'"
    ).fetchone()
    fetcher = FakeFetcher(detail_ok=lambda n: True)
    # The next day the failed listing is skipped and another one is fetched instead.
    stats = fetch_details(conn, fetcher, limit=1, scraped_at=stamp(DAY2))
    assert stats.fetched == 1
    assert (
        conn.execute("SELECT description FROM listings WHERE id = ?", (lid,)).fetchone()[0] is None
    )
    # Three days on it is tried again, and the failure marks go away on success.
    fetch_details(conn, fetcher, limit=100, scraped_at=stamp(DAY1 + timedelta(days=4)))
    assert conn.execute("SELECT description FROM listings WHERE id = ?", (lid,)).fetchone()[0]
    assert not {"detail_error", "detail_failed_at"} & attributes_of(conn, lid).keys()


def test_details_stop_after_three_failures_in_a_row(conn):
    report = run(
        conn, FakeFetcher(detail_ok=lambda n: False), max_details=10, max_pages=1, now=DAY1
    )
    assert report.details.failed == 3 and report.details.aborted and report.exit_code == 4
    assert report.message().startswith("ALERT") and "3 failures in a row" in report.message()


def test_removed_ad_is_recorded_without_counting_as_a_failure(conn):
    # Kijiji answers a removed ad's URL with the search page.
    fetcher = FakeFetcher(detail=load(ROOMS), detail_ok=lambda n: True)
    report = run(conn, fetcher, max_details=5, max_pages=1, now=DAY1)
    assert (report.details.fetched, report.details.failed, report.details.removed) == (0, 0, 5)
    assert report.details.aborted is None and "ALERT" not in report.message()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM listing_attributes WHERE name = 'detail_error' AND value = 'removed'"
        ).fetchone()[0]
        == 5
    )


def test_detail_page_for_another_ad_is_a_failure(conn):
    add_listing(conn, "999", stamp(DAY1))

    class SameAdFetcher(FakeFetcher):
        def get(self, url, name, **kwargs):
            result = super().get(url, name, **kwargs)
            return FetchResult(url, 200, self.detail, result.path, result.fetched_at, False)

    stats = fetch_details(
        conn, SameAdFetcher(detail_ok=lambda n: True), limit=1, scraped_at=stamp(DAY1)
    )
    assert (stats.fetched, stats.failed) == (0, 1)
    (lid,) = conn.execute("SELECT id FROM listings WHERE source_id = '999'").fetchone()
    assert attributes_of(conn, lid)["detail_error"].startswith(
        "page is ad 1744792340, expected 999"
    )


def test_daily_main_exit_code_and_notify(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(daily, "Fetcher", lambda source: FakeFetcher(blocked=True))
    posted = []
    monkeypatch.setattr(daily, "discord", posted.append)
    db = str(tmp_path / "t.db")
    assert daily.main(["--db", db, "--details", "0"]) == 2
    assert posted and posted[0].startswith("ALERT")
    assert daily.main(["--db", db, "--details", "0", "--no-notify"]) == 2 and len(posted) == 1


def test_daily_main_ok_run_returns_zero_and_posts_a_plain_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(daily, "Fetcher", lambda source: FakeFetcher())
    posted = []
    monkeypatch.setattr(daily, "discord", posted.append)
    assert daily.main(["--db", str(tmp_path / "t.db"), "--details", "0"]) == 0
    assert posted[0].startswith("Housing sweep") and "apartments 45 seen" in posted[0]


def test_daily_main_reports_a_crash(tmp_path, monkeypatch):
    def boom(source):
        raise RuntimeError("HOUSING_HASH_SALT is not set")

    monkeypatch.setattr(daily, "Fetcher", boom)
    posted = []
    monkeypatch.setattr(daily, "discord", posted.append)
    assert daily.main(["--db", str(tmp_path / "t.db")]) == 1
    assert posted[0].startswith("ALERT") and "crashed" in posted[0] and "SALT" in posted[0]


def test_extract_cli_all_flag_rewrites_every_row(conn, tmp_path):
    run(conn, FakeFetcher(), max_details=0, max_pages=1, now=DAY1)
    conn.execute("UPDATE units SET extracted_at = 'old'")
    conn.commit()
    db = str(tmp_path / "t.db")
    assert extract_main(["--db", db]) == 0
    assert conn.execute("SELECT COUNT(*) FROM units WHERE extracted_at = 'old'").fetchone()[0] == 86
    assert extract_main(["--db", db, "--all"]) == 0
    assert conn.execute("SELECT COUNT(*) FROM units WHERE extracted_at = 'old'").fetchone()[0] == 0


def test_stale_text_flags_are_cleared_on_re_extraction(conn):
    from housing.parse.extract import extract_all

    run(conn, FakeFetcher(), max_details=0, max_pages=1, now=DAY1)
    (lid,) = conn.execute(
        "SELECT id FROM listings WHERE title NOT LIKE '%takeover%' LIMIT 1"
    ).fetchone()
    conn.execute(
        "INSERT INTO listing_attributes (listing_id, name, value) VALUES (?, 'text_is_takeover', '1')"
        " ON CONFLICT(listing_id, name) DO UPDATE SET value = '1'",
        (lid,),
    )
    conn.commit()
    extract_all(conn, only_missing=False)
    assert "text_is_takeover" not in attributes_of(conn, lid)
