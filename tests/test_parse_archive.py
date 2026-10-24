"""Tests for classifying, scrubbing and parsing archived index pages."""

import pytest

from housing.parse.archive import (
    UnsupportedFormat,
    detect_format,
    parse_capture,
    scrub_capture,
)
from tests.archive_pages import ad, html_cards_page, nextjs_page, v2_page
from tests.helpers import load


@pytest.mark.parametrize(
    ("html", "fmt"),
    [
        (nextjs_page([ad(1)]), "nextjs"),
        (v2_page([ad(1)]), "nextjs_v2"),
        (html_cards_page(), "html_cards"),
        ("<html><body>Got an HTTP 302 response at crawl time</body></html>", "unknown"),
        ('<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>', "unknown"),
    ],
)
def test_detect_format(html, fmt):
    assert detect_format(html) == fmt


def test_todays_layout_goes_through_the_live_parser():
    fmt, total, cards = parse_capture(nextjs_page([ad(1, 1200), ad(2, top=True)], total=1612))
    assert (fmt, total) == ("nextjs", 1612)
    assert [c.source_id for c in cards] == ["1", "2"]
    assert cards[0].price == 1200 and cards[0].lat == 43.47


def test_real_live_fixture_parses_as_an_archive_capture():
    fmt, total, cards = parse_capture(load("kijiji_index_rooms_2026-10-14.html.gz"))
    assert fmt == "nextjs" and total > 0 and len(cards) >= 40


def test_v2_cards_map_onto_index_cards():
    page = v2_page([ad(7, 1910, posted="2024-03-12T09:03:01Z", beds="1"), ad(8, top=True)])
    fmt, total, cards = parse_capture(page)
    assert (fmt, total) == ("nextjs_v2", 1427)
    c = cards[0]
    assert c.source_id == "7"
    assert c.price == 1910.0
    assert c.url == "https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/apartment/7"
    assert c.activation_date == "2024-03-12T09:03:01Z"
    assert c.attributes == {"numberbedrooms": ["1"]}
    assert c.poster_id == "97"
    assert (c.lat, c.lon) == (None, None)  # this era carries no coordinates
    assert c.intersection == "University Ave & Phillip St"
    assert cards[1].ad_source == "TOP_AD"


def test_a_top_ad_repeated_in_the_organic_list_is_one_card():
    a = ad(5)
    page = v2_page([a, {**a, "top": True}])
    _, _, cards = parse_capture(page)
    assert [c.source_id for c in cards] == ["5"]


def test_html_cards_are_not_stored_and_stay_identifiable():
    stored = scrub_capture(html_cards_page())
    assert "example.com" not in stored and "1,500" not in stored
    assert detect_format(stored) == "html_cards"
    with pytest.raises(UnsupportedFormat) as info:
        parse_capture(stored)
    assert info.value.format == "html_cards"


def test_unknown_pages_are_not_stored_either():
    stored = scrub_capture("<html>call 519-555-0199</html>")
    assert "519" not in stored and detect_format(stored) == "unknown"


def test_json_pages_are_scrubbed_by_the_live_scrubber():
    page = v2_page([ad(1, description="Text 519-555-0199 or email bob@example.com")])
    stored = scrub_capture(page)
    assert "519-555-0199" not in stored and "bob@example.com" not in stored
    assert detect_format(stored) == "nextjs_v2"
    assert parse_capture(stored)[2][0].price == 1000
