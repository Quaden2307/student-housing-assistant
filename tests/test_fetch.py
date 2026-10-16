"""Tests for the polite fetcher: robots matching, raw storage and caching, hard stops."""

import gzip
import json

import pytest
import requests

from housing.scrape.fetch import BlockedError, Fetcher, RobotsDisallowed, RobotsRules

# A cut-down copy of Kijiji's robots.txt rules that matter to us (fetched 2026-10-14).
KIJIJI_ROBOTS = """
User-Agent: Mediapartners-Google
Disallow: /b-search-map-ajax-search-ads.json*

User-agent: *
Disallow: /v-*/*/*/c*
Disallow: /rss-*
# Search params
Disallow: /*?*sort=*
Disallow: /*?*price=*
Disallow: /*?*imageNumber=*
"""


def test_robots_allows_index_and_detail_paths():
    rules = RobotsRules(KIJIJI_ROBOTS)
    assert rules.allows("/b-apartments-condos/kitchener-waterloo/c37l1700212")
    assert rules.allows("/b-apartments-condos/kitchener-waterloo/page-2/c37l1700212")
    assert rules.allows("/v-apartments-condos/kitchener-waterloo/some-slug/1743010220")


def test_robots_disallows_query_params_rss_and_the_v_rule():
    rules = RobotsRules(KIJIJI_ROBOTS)
    assert not rules.allows("/b-apartments-condos/kitchener-waterloo/c37l1700212?sort=dateDesc")
    assert not rules.allows("/v-apartments-condos/kitchener-waterloo/slug/1743010220?imageNumber=2")
    assert not rules.allows("/rss-srp-apartments")
    assert not rules.allows("/v-apartments-condos/kitchener-waterloo/slug/c37l1700212")
    # Mediapartners-only rules do not apply to us.
    assert rules.allows("/b-search-map-ajax-search-ads.json")


def test_robots_longest_match_and_allow_tie():
    rules = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a/b\nAllow: /c\nDisallow: /c\n")
    assert not rules.allows("/a/x")
    assert rules.allows("/a/b/x")
    assert rules.allows("/c")
    assert RobotsRules("").allows("/anything")


class FakeResponse:
    def __init__(self, status, body, url="https://example.test/page"):
        self.status_code = status
        self.content = body.encode()
        self.text = body
        self.encoding = "utf-8"
        self.url = url
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class FakeSession:
    """Serves canned responses and records every URL requested."""

    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        reply = self.responses[url]
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSING_DATA_DIR", str(tmp_path))
    return tmp_path / "raw"


def make_fetcher(responses):
    session = FakeSession(responses)
    fetcher = Fetcher("test", min_delay=0, max_delay=0, session=session)
    return fetcher, session


def test_get_stores_raw_copy_and_serves_it_from_cache(raw_dir):
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(
                200, "User-agent: *\nDisallow: /private\n"
            ),
            "https://example.test/page": FakeResponse(200, "<html>hello</html>"),
        }
    )
    first = fetcher.get("https://example.test/page", "page")
    assert first.text == "<html>hello</html>" and not first.from_cache
    assert gzip.decompress(first.path.read_bytes()) == b"<html>hello</html>"
    meta = json.loads((first.path.parent / "page.meta.json").read_text())
    assert meta["status"] == 200 and meta["url"] == "https://example.test/page"
    assert first.path.is_relative_to(raw_dir / "test")

    second = fetcher.get("https://example.test/page", "page")
    assert second.from_cache and second.text == first.text
    assert session.calls == ["https://example.test/robots.txt", "https://example.test/page"]


def test_robots_disallowed_path_is_never_requested(raw_dir):
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(
                200, "User-agent: *\nDisallow: /private\n"
            )
        }
    )
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://example.test/private/x", "private")
    assert session.calls == ["https://example.test/robots.txt"]


def test_403_and_challenge_pages_raise_blocked(raw_dir):
    fetcher, _ = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/forbidden": FakeResponse(403, "nope"),
            "https://example.test/challenge": FakeResponse(200, "<title>Just a moment...</title>"),
        }
    )
    with pytest.raises(BlockedError):
        fetcher.get("https://example.test/forbidden", "forbidden")
    with pytest.raises(BlockedError):
        fetcher.get("https://example.test/challenge", "challenge")


def test_missing_robots_means_no_rules(raw_dir):
    fetcher, _ = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(404, "not here"),
            "https://example.test/page": FakeResponse(200, "ok"),
        }
    )
    assert fetcher.get("https://example.test/page", "page").text == "ok"


def test_retries_then_gives_up_on_server_errors(raw_dir, monkeypatch):
    monkeypatch.setattr("housing.scrape.fetch.time.sleep", lambda s: None)
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/flaky": FakeResponse(503, "busy"),
        }
    )
    with pytest.raises(Exception, match="gave up"):
        fetcher.get("https://example.test/flaky", "flaky")
    assert session.calls.count("https://example.test/flaky") == 3


def test_connection_errors_are_retried(raw_dir, monkeypatch):
    monkeypatch.setattr("housing.scrape.fetch.time.sleep", lambda s: None)
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/down": requests.ConnectionError("refused"),
        }
    )
    with pytest.raises(Exception, match="gave up"):
        fetcher.get("https://example.test/down", "down")
    assert session.calls.count("https://example.test/down") == 3


def test_429_raises_blocked(raw_dir):
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/limited": FakeResponse(429, "slow down"),
        }
    )
    with pytest.raises(BlockedError):
        fetcher.get("https://example.test/limited", "limited")
    assert session.calls.count("https://example.test/limited") == 1


def test_challenge_page_with_a_server_error_status_is_a_hard_stop(raw_dir, monkeypatch):
    monkeypatch.setattr("housing.scrape.fetch.time.sleep", lambda s: None)
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/cf": FakeResponse(503, "<html><title>Just a moment...</title>"),
        }
    )
    with pytest.raises(BlockedError):
        fetcher.get("https://example.test/cf", "cf")
    assert session.calls.count("https://example.test/cf") == 1


def test_requests_are_spaced_two_to_three_seconds_with_a_browser_user_agent(raw_dir, monkeypatch):
    sleeps = []
    monkeypatch.setattr("housing.scrape.fetch.time.sleep", sleeps.append)
    monkeypatch.setattr("housing.scrape.fetch.time.monotonic", lambda: 0.0)
    session = FakeSession(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/a": FakeResponse(200, "a"),
            "https://example.test/b": FakeResponse(200, "b"),
        }
    )
    fetcher = Fetcher("test", session=session)
    fetcher.get("https://example.test/a", "a")
    fetcher.get("https://example.test/b", "b")
    assert len(sleeps) == 3 and all(2.0 <= s <= 3.0 for s in sleeps)
    assert session.headers["User-Agent"].startswith("Mozilla/5.0")


def test_no_back_off_sleep_after_the_last_attempt(raw_dir, monkeypatch):
    sleeps = []
    monkeypatch.setattr("housing.scrape.fetch.time.sleep", sleeps.append)
    fetcher, _ = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/flaky": FakeResponse(503, "busy"),
        }
    )
    with pytest.raises(Exception, match="gave up") as info:
        fetcher.get("https://example.test/flaky", "flaky")
    assert sleeps == [5, 10] and info.value.status == 503


def test_robots_server_error_stops_the_run(raw_dir, monkeypatch):
    monkeypatch.setattr("housing.scrape.fetch.time.sleep", lambda s: None)
    fetcher, session = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(503, "down"),
            "https://example.test/page": FakeResponse(200, "ok"),
        }
    )
    with pytest.raises(Exception, match="gave up"):
        fetcher.get("https://example.test/page", "page")
    assert "https://example.test/page" not in session.calls


def test_robots_is_fetched_fresh_each_run(raw_dir):
    responses = {
        "https://example.test/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /old\n"),
        "https://example.test/page": FakeResponse(200, "ok"),
    }
    fetcher, _ = make_fetcher(responses)
    fetcher.get("https://example.test/page", "page")
    responses["https://example.test/robots.txt"] = FakeResponse(
        200, "User-agent: *\nDisallow: /page\n"
    )
    fetcher2, _ = make_fetcher(responses)
    with pytest.raises(RobotsDisallowed):
        fetcher2.get("https://example.test/page", "page", refresh=True)


def test_scrub_is_applied_before_the_raw_copy_is_written(raw_dir):
    fetcher, _ = make_fetcher(
        {
            "https://example.test/robots.txt": FakeResponse(200, ""),
            "https://example.test/page": FakeResponse(200, "<html>hello</html>"),
        }
    )
    result = fetcher.get(
        "https://example.test/page", "page", scrub=lambda t: t.replace("hello", "x")
    )
    assert result.text == "<html>x</html>"
    assert gzip.decompress(result.path.read_bytes()) == b"<html>x</html>"
    assert json.loads((result.path.parent / "page.meta.json").read_text())["scrubbed"] is True


def test_scrub_stored_pages_rewrites_files_in_place(tmp_path):
    from housing.scrape.fetch import scrub_stored_pages

    page = tmp_path / "2026-10-14" / "detail_1.html.gz"
    page.parent.mkdir()
    page.write_bytes(gzip.compress(b"<html>hello</html>"))
    (page.parent / "detail_1.meta.json").write_text(json.dumps({"status": 200}))
    (page.parent / "other.html.gz").write_bytes(gzip.compress(b"<html>bye</html>"))
    assert scrub_stored_pages(tmp_path, lambda t: t.replace("hello", "x")) == 1
    assert gzip.decompress(page.read_bytes()) == b"<html>x</html>"
    assert json.loads((page.parent / "detail_1.meta.json").read_text())["scrubbed"] is True
