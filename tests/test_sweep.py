"""The sweep against fake fetchers that serve the saved index pages."""

import re

import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.parse.pii import REDACTED
from housing.scrape.fetch import BlockedError, FetchError
from housing.scrape.kijiji import sweep
from tests.helpers import SHARED_ID, FakeFetcher, PagedFetcher, load, with_entity

ROOMS = "kijiji_index_rooms_2026-10-14.html.gz"
T1 = "2026-10-14T20:00:00Z"
T2 = "2026-10-15T20:00:00Z"


class FlakyPagedFetcher(PagedFetcher):
    """Raises the configured exception when asked for a failing page.

    ``fail_pages`` maps a page number to the exception its fetch raises; with
    ``fail_once`` each page fails only the first time and serves normally after.
    """

    def __init__(self, fail_pages, *, fail_once=False, total=120, limit=40, text=None):
        super().__init__(total=total, limit=limit, text=text)
        self.fail_pages = dict(fail_pages)
        self.fail_once = fail_once
        self.raised = set()

    def get(self, url, name, **kwargs):
        match = re.search(r"/page-(\d+)/", url)
        page = int(match.group(1)) if match else 1
        if page in self.fail_pages and not (self.fail_once and page in self.raised):
            self.raised.add(page)
            raise self.fail_pages[page]
        return super().get(url, name, **kwargs)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "t.db")
    migrate(connection)
    yield connection
    connection.close()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_one_page_sweep_records_every_card_once(conn):
    stats = sweep(conn, FakeFetcher(), "rooms", max_pages=1, scraped_at=T1)
    assert (stats.pages, stats.seen, stats.new, stats.total_count) == (1, 41, 41, 260)
    assert "page cap 1" in stats.stopped_early  # 260 listings need 7 pages
    assert count(conn, "listings") == 41 and count(conn, "snapshots") == 41
    row = conn.execute(
        "SELECT source, status, posted_at, length(title) > 0 FROM listings LIMIT 1"
    ).fetchone()
    assert tuple(row)[:2] == ("kijiji", "active") and len(row[2]) == 10 and row[3]


def test_index_pages_are_fetched_fresh_and_scrubbed(conn):
    fetcher = FakeFetcher()
    sweep(conn, fetcher, "rooms", max_pages=1, scraped_at=T1)
    assert fetcher.kwargs and all(
        kw["refresh"] is True and callable(kw["scrub"]) for kw in fetcher.kwargs
    )


def test_complete_sweep_visits_every_page_and_snapshots_each_listing_once(conn):
    fetcher = PagedFetcher(total=120)
    stats = sweep(conn, fetcher, "rooms", max_pages=60, scraped_at=T1)
    assert stats.pages == 3 and len(fetcher.urls) == 3 and stats.stopped_early is None
    assert "/page-2/" in fetcher.urls[1] and "/page-3/" in fetcher.urls[2]
    # 41 distinct cards on page 1, 40 new ones on each later page; the promoted card that
    # repeats on every page gets one listing row and one snapshot.
    assert stats.seen == 121 and count(conn, "listings") == count(conn, "snapshots") == 121
    shared = conn.execute(
        "SELECT COUNT(*) FROM snapshots s JOIN listings l ON l.id = s.listing_id"
        " WHERE l.source_id = ?",
        (SHARED_ID,),
    ).fetchone()[0]
    assert shared == 1


def test_second_sweep_adds_snapshots_not_listings(conn):
    sweep(conn, PagedFetcher(total=40), "rooms", max_pages=1, scraped_at=T1)
    stats = sweep(conn, PagedFetcher(total=40), "rooms", max_pages=1, scraped_at=T2)
    assert (stats.seen, stats.new) == (41, 0) and stats.stopped_early is None
    assert count(conn, "listings") == 41 and count(conn, "snapshots") == 82
    assert conn.execute("SELECT MIN(last_seen) FROM listings").fetchone()[0] == T2


def test_new_is_counted_once_even_when_two_runs_share_a_timestamp(conn):
    sweep(conn, PagedFetcher(total=40), "rooms", max_pages=1, scraped_at=T1)
    assert sweep(conn, PagedFetcher(total=40), "rooms", max_pages=1, scraped_at=T1).new == 0


def test_sweep_stops_when_pagination_does_not_advance(conn):
    fetcher = FakeFetcher()
    stats = sweep(conn, fetcher, "rooms", max_pages=5, scraped_at=T1)
    assert stats.pages == 1 and "page 2 came back as page 1" in stats.stopped_early
    assert len(fetcher.urls) == 2 and "/page-2/" in fetcher.urls[1]
    assert stats.fetch_failed is False  # the page answered; nothing transient to retry


def test_page_cap_marks_the_sweep_incomplete(conn):
    stats = sweep(conn, PagedFetcher(total=120), "rooms", max_pages=2, scraped_at=T1)
    assert stats.pages == 2 and "page cap 2" in stats.stopped_early
    assert stats.fetch_failed is False


def test_mid_sweep_fetch_failure_returns_partial_stats(conn):
    fetcher = FlakyPagedFetcher({2: FetchError("gave up on x after 4 attempt(s): refused")})
    stats = sweep(conn, fetcher, "rooms", max_pages=60, scraped_at=T1)
    assert (stats.pages, stats.seen) == (1, 41)
    assert stats.fetch_failed is True and "fetch failure at page 2" in stats.stopped_early
    assert count(conn, "listings") == 41 and count(conn, "snapshots") == 41


def test_page_one_fetch_failure_returns_zero_stats(conn):
    fetcher = FlakyPagedFetcher({1: FetchError("gave up on x after 1 attempt(s): refused")})
    stats = sweep(conn, fetcher, "rooms", max_pages=60, scraped_at=T1)
    assert (stats.pages, stats.seen) == (0, 0) and stats.fetch_failed is True
    assert count(conn, "listings") == 0 and count(conn, "snapshots") == 0


def test_blocked_mid_sweep_still_raises_with_earlier_pages_committed(conn):
    fetcher = FlakyPagedFetcher({2: BlockedError("HTTP 403 with a block for x", status=403)})
    with pytest.raises(BlockedError):
        sweep(conn, fetcher, "rooms", max_pages=60, scraped_at=T1)
    assert count(conn, "listings") == 41 and count(conn, "snapshots") == 41


def test_resweep_with_the_same_scraped_at_does_not_duplicate_snapshots(conn):
    sweep(conn, PagedFetcher(total=40), "rooms", max_pages=1, scraped_at=T1)
    stats = sweep(conn, PagedFetcher(total=40), "rooms", max_pages=1, scraped_at=T1)
    assert (stats.seen, stats.new) == (41, 0)
    assert count(conn, "listings") == 41 and count(conn, "snapshots") == 41


def test_cli_exits_4_on_a_fetch_failed_sweep(tmp_path, monkeypatch, capsys):
    from housing.scrape import kijiji

    monkeypatch.setenv("HOUSING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(kijiji, "keep_awake", lambda: None)
    monkeypatch.setattr(
        kijiji,
        "Fetcher",
        lambda source: FlakyPagedFetcher(
            {1: FetchError("gave up on x after 4 attempt(s): refused")}
        ),
    )
    assert kijiji.main(["--db", str(tmp_path / "t.db"), "--category", "rooms"]) == 4
    assert "incomplete: fetch failure at page 1" in capsys.readouterr().out


def test_too_few_listings_marks_the_sweep_incomplete(conn):
    # One final page claiming 100 listings but carrying 41: under 90 percent seen.
    stats = sweep(conn, PagedFetcher(total=100, limit=100), "rooms", max_pages=1, scraped_at=T1)
    assert stats.pages == 1 and "only 41 of 100" in stats.stopped_early


def test_zero_total_marks_the_sweep_incomplete(conn):
    stats = sweep(conn, PagedFetcher(total=0), "rooms", max_pages=1, scraped_at=T1)
    assert stats.seen == 0 and "no listings" in stats.stopped_early


def test_contact_info_in_title_and_url_slug_is_stripped(conn):
    html = with_entity(
        load(ROOMS),
        "1744792340",
        title="Room available, call 519-555-0199 or me@example.com",
        url="https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/room-available-call-519-555-0199/1744792340",
    )
    sweep(conn, PagedFetcher(total=40, text=html), "rooms", max_pages=1, scraped_at=T1)
    row = conn.execute("SELECT title, url FROM listings WHERE source_id = '1744792340'").fetchone()
    assert (
        "519" not in row["title"] and "example.com" not in row["title"] and REDACTED in row["title"]
    )
    assert row["url"] == (
        "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/room-available-call/1744792340"
    )
