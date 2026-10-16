"""Fixture tests for the Kijiji index parser (pages saved 2026-10-14)."""

import gzip
from pathlib import Path

import pytest

from housing.parse.kijiji import (
    AdRemovedError,
    ParseError,
    _card,
    index_url,
    next_data,
    parse_detail,
    parse_index,
)
from housing.parse.pii import strip_contact_info

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return gzip.decompress((FIXTURES / name).read_bytes()).decode()


@pytest.fixture(scope="module")
def apartments():
    return parse_index(load("kijiji_index_apartments_2026-10-14.html.gz"))


@pytest.fixture(scope="module")
def rooms():
    return parse_index(load("kijiji_index_rooms_2026-10-14.html.gz"))


def test_index_urls_have_no_query_string():
    assert (
        index_url("apartments")
        == "https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212"
    )
    assert (
        index_url("rooms", 3)
        == "https://www.kijiji.ca/b-room-rental-roommate/kitchener-waterloo/page-3/c36l1700212"
    )


def test_apartments_pagination_and_card_count(apartments):
    assert (apartments.total_count, apartments.offset, apartments.limit) == (1612, 0, 40)
    assert len(apartments.cards) == 45  # 40 main + 6 promoted, one of which repeats
    assert len({c.source_id for c in apartments.cards}) == 45


def test_apartments_card_fields(apartments):
    card = next(c for c in apartments.cards if c.source_id == "1744430634")
    assert card.price == 1495.0 and card.price_type == "FIXED"
    assert card.url.startswith("https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/")
    assert card.address_text == "44 Chapel, Kitchener, ON, N2G 2S5"
    assert (card.lat, card.lon) == (43.45265, -80.47965)
    assert card.activation_date == "2026-10-05T23:09:54.000Z"
    assert card.category_id == 37
    assert card.attributes["numberbedrooms"] and card.attributes["numberbathrooms"]
    assert card.attributes["unittype"]
    assert card.poster_id and card.poster_id.isdigit() and card.image_count > 0


def test_card_url_drops_the_query_string():
    entity = {"id": 1, "url": "https://www.kijiji.ca/v-x/kw/slug/1?imageNumber=2", "title": " t "}
    card = _card(entity, {})
    assert card.url == "https://www.kijiji.ca/v-x/kw/slug/1" and card.title == "t"
    assert card.price is None and card.attributes == {} and card.poster_id is None


def test_every_apartments_card_has_location_and_attributes(apartments):
    assert all(c.lat and c.lon and c.address_text for c in apartments.cards)
    assert all("numberbedrooms" in c.attributes for c in apartments.cards)
    assert all(c.activation_date and c.url and c.title for c in apartments.cards)


def test_contact_price_is_none(apartments):
    contact = [c for c in apartments.cards if c.price_type == "CONTACT"]
    assert len(contact) == 1 and contact[0].price is None
    assert all(c.price for c in apartments.cards if c.price_type == "FIXED")


def test_rooms_page(rooms):
    assert rooms.total_count == 260
    assert len(rooms.cards) == 41
    assert all(c.category_id == 36 for c in rooms.cards)
    assert all(c.lat and c.lon for c in rooms.cards)
    assert sum(1 for c in rooms.cards if not c.attributes) == 9
    assert sum(1 for c in rooms.cards if c.price_type == "CONTACT") == 2


def test_parse_error_on_foreign_html():
    with pytest.raises(ParseError):
        parse_index("<html><body>nothing here</body></html>")


def test_malformed_next_data_is_a_parse_error():
    with pytest.raises(ParseError, match="not valid JSON"):
        parse_index('<script id="__NEXT_DATA__" type="application/json">{"props": {broken</script>')


def test_index_without_main_listings_is_a_parse_error():
    html = load("kijiji_index_apartments_2026-10-14.html.gz").replace(
        '"mainListings(', '"mainResults('
    )
    with pytest.raises(ParseError, match="mainListings"):
        parse_index(html)


def test_detail_url_redirected_to_the_search_page_means_the_ad_was_removed():
    with pytest.raises(AdRemovedError):
        parse_detail(load("kijiji_index_rooms_2026-10-14.html.gz"))


@pytest.fixture(scope="module")
def house():
    from housing.parse.kijiji import parse_detail

    return parse_detail(load("kijiji_detail_apartments_house_2026-10-14.html.gz"))


@pytest.fixture(scope="module")
def room():
    from housing.parse.kijiji import parse_detail

    return parse_detail(load("kijiji_detail_rooms_2026-10-14.html.gz"))


def test_detail_house_core_fields(house):
    assert house.source_id == "1743010220"
    assert house.price == 2400.0 and house.price_type == "FIXED"
    assert house.url == (
        "https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/"
        "3-bedrooms-house-for-rent-waterloo/1743010220"
    )
    assert house.address_text == "Waterloo, ON N2J 3X2, Canada"
    assert (house.lat, house.lon, house.show_pin) == (43.48129, -80.51484, True)
    assert house.activation_date.startswith("2026-09-04")
    assert house.end_date.startswith("2026-11-03")
    assert house.status == "ACTIVE" and house.category_id == 37
    assert 400 < len(house.description) < 500 and "\r" not in house.description
    assert house.image_count == 13 and house.views == 739
    assert house.poster_id and house.poster_id.isdigit()


def test_detail_house_attributes_use_display_values_when_canonical_is_empty(house):
    a = house.attributes
    assert a["unittype"] == ["house"] and a["numberbedrooms"] == ["3"]
    assert a["numberbathrooms"] == ["10"] and a["agreementtype"] == ["one-year"]
    assert a["dateavailable"] == ["2026-09-15T00:00:00Z"]
    assert a["areainfeet"] == ["1000"]
    assert a["furnished"] == ["0"] and a["laundryinunit"] == ["1"]
    assert a["heat"] == ["0"] and a["hydro"] == ["0"] and a["water"] == ["0"]
    assert a["forrentbyhousing"] == ["ownr"]
    assert len(a) >= 30


def test_detail_room_has_no_attributes_but_full_text(room):
    assert room.source_id == "1744792340" and room.category_id == 36
    assert room.price == 625.0
    assert room.attributes == {}
    assert room.address_text.endswith("N2L 4G9")
    assert (room.lat, room.lon, room.show_pin) == (43.48413, -80.53434, True)
    assert 1000 < len(room.description) < 1300
    assert room.image_count == 10 and room.views == 42


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.html.gz")))
def test_fixture_carries_no_personal_data(name):
    page_props = next_data(load(name))["props"]["pageProps"]
    assert page_props.get("userAgent") == "[removed]" and page_props.get("machId") == "[removed]"
    for key, entity in page_props["__APOLLO_STATE__"].items():
        if not isinstance(entity, dict):
            continue
        if key.startswith("StandardProfileV2:"):
            assert entity.get("name") == "[removed]"
        poster = entity.get("posterInfo") or {}
        assert poster.get("phoneNumber") is None
        if poster.get("posterId") is not None:
            assert 10_000_000 < int(poster["posterId"]) < 10_001_000  # fake ids from make_fixture
        for field in ("title", "description"):
            if isinstance(entity.get(field), str):
                assert strip_contact_info(entity[field]) == entity[field]
