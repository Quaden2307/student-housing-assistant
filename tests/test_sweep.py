"""The sweep against fake fetchers that serve the saved index pages."""

import re
from pathlib import Path

import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.parse.pii import REDACTED
from housing.scrape.fetch import FetchResult
from housing.scrape.kijiji import sweep
from tests.helpers import LISTING_TYPES, edit_next_data, load, with_entity, with_pagination

ROOMS = "kijiji_index_rooms_2026-10-14.html.gz"
T1 = "2026-10-14T20:00:00Z"
T2 = "2026-10-15T20:00:00Z"


class FakeFetcher:
    """Serves one saved page (rooms page 1 by default) for every URL and records each call."""

    def __init__(self, text=None):
        self.text = text if text is not None else load(ROOMS)
        self.urls = []
        self.kwargs = []

    def page_for(self, url):
        return self.text

    def get(self, url, name, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        path = Path("data/raw/kijiji/2026-10-14") / f"{name}.html.gz"
        return FetchResult(url, 200, self.page_for(url), path, T1, False)


SHARED_ID = "1744792340"  # the one card that repeats on every page, like a promoted ad


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


def test_page_cap_marks_the_sweep_incomplete(conn):
    stats = sweep(conn, PagedFetcher(total=120), "rooms", max_pages=2, scraped_at=T1)
    assert stats.pages == 2 and "page cap 2" in stats.stopped_early


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
