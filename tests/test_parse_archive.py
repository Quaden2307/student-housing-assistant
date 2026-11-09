"""Tests for classifying, scrubbing and parsing archived index pages."""

import re

import pytest

from housing.parse.archive import (
    UnsupportedFormat,
    detect_ad_format,
    detect_format,
    parse_ad_capture,
    parse_capture,
    scrub_ad_capture,
    scrub_capture,
)
from housing.parse.pii import EMAIL_RE, OBFUSCATED_EMAIL_RE, strip_contact_info
from tests.archive_pages import (
    ad,
    html_cards_page,
    nextjs_ad_page,
    nextjs_page,
    removed_ad_page,
    v2_page,
    vip_legacy_page,
)
from tests.helpers import load

# The five classic-era fixtures: real Wayback captures, scrubbed before they were saved.
# fixture -> (format, capture time, cards on the page, Kijiji's total count)
CLASSIC_FIXTURES = {
    "wayback_classic_v0_apts_2014.html.gz": ("classic_v0", "2014-10-08T00:12:47Z", 25, 1357),
    "wayback_classic_v0_apts_2015.html.gz": ("classic_v0", "2015-03-01T02:51:56Z", 25, 1509),
    "wayback_classic_apts_2017.html.gz": ("classic", "2017-06-09T05:18:07Z", 25, 1124),
    "wayback_classic_rooms_2017.html.gz": ("classic", "2017-01-06T18:59:52Z", 25, 1624),
    "wayback_classic_apts_2022_fr.html.gz": ("classic", "2022-06-05T03:35:46Z", 45, 732),
}


def parse_fixture(name):
    """Parse a classic fixture with its capture time; return (total, cards by ad id)."""
    fmt, captured_at, cards_expected, _ = CLASSIC_FIXTURES[name]
    got_fmt, total, cards = parse_capture(load(name), captured_at)
    assert got_fmt == fmt and len(cards) == cards_expected
    return total, {c.source_id: c for c in cards}


def classic_card_html(
    ad_id,
    *,
    title,
    price,
    posted,
    desc="Nice place",
    beds=None,
    top=False,
    slug=None,
    cat="v-apartments-condos",
    extra="",
):
    """One synthetic ``div.search-item`` card in the 2016 to 2022 markup."""
    slug = slug or f"ad-{ad_id}"
    classes = "search-item " + ("top-feature" if top else "regular-ad")
    beds_html = f'<span class="bedrooms">{beds}</span>' if beds else ""
    href = f"/{cat}/kitchener-waterloo/{slug}/{ad_id}"
    return f"""
    <div data-listing-id="{ad_id}" data-vip-url="{href}?src=search" class="{classes}">
      <div class="info">
        <div class="price"> {price}</div>
        <div class="title"><a href="{href}" class="title">{title}</a></div>
        <div class="location">Kitchener / Waterloo<span class="date-posted">{posted}</span></div>
        <div class="description">{desc}{extra}<div class="details"></div></div>
      </div>
      <div class="rental-info">{beds_html}</div>
    </div>"""


def classic_page(cards_html, ts="2022-06-05 03:35:47.000+0000"):
    """A synthetic classic index page: dataLayer with the render time, count badge, cards."""
    data_layer = (
        'var dataLayer = [{"p":{"t":"ResultsBrowse"},"c":{"c":{"id":37,"n":"apartments"}},'
        f'"s":{{"tr":1234,"pn":1}},"ts":"{ts}"}}];'
    )
    return (
        "<html><head><title>Apartments | Kijiji</title></head><body>"
        f'<script type="text/javascript">{data_layer}</script>'
        '<span class="titlecount">(1,234)</span>'
        f"{cards_html}</body></html>"
    )


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


# --- the classic (2013 to 2022) server-rendered layouts ----------------------------------


@pytest.mark.parametrize("name", CLASSIC_FIXTURES)
def test_classic_fixtures_classify_and_parse(name):
    fmt, _, _, total_expected = CLASSIC_FIXTURES[name]
    html = load(name)
    assert detect_format(html) == fmt
    total, by_id = parse_fixture(name)
    assert total == total_expected
    assert all(c.source_id.isdigit() and c.url and c.title for c in by_id.values())
    assert all((c.lat, c.lon) == (None, None) for c in by_id.values())


def test_classic_2017_apartments_spot_checks():
    _, by_id = parse_fixture("wayback_classic_apts_2017.html.gz")
    top = by_id["1222433957"]  # "05/06/2017" is day first; bachelor slug is 0 bedrooms
    assert (top.price, top.price_type) == (935.0, "FIXED")
    assert top.activation_date == "2017-06-05T00:00:00Z"
    assert top.ad_source == "TOP_AD" and top.category_id == 37
    assert top.attributes == {"numberbedrooms": ["0"]}
    assert top.address_text == "Kitchener / Waterloo"
    assert top.url == (
        "https://www.kijiji.ca/v-bachelor-studio-apartments-condos/kitchener-waterloo"
        "/fantastic-bachelor-apartment-for-rent-call-today/1222433957"
    )
    # "< 19 hours ago" resolves against the page's own render time, across midnight.
    assert by_id["1213183575"].activation_date == "2017-06-08T10:18:07Z"
    organic = by_id["1271631528"]  # "< 19 minutes ago", 1-bedroom slug
    assert (organic.ad_source, organic.price) == ("ORGANIC", 1330.0)
    assert organic.activation_date == "2017-06-09T04:59:07Z"
    assert organic.attributes == {"numberbedrooms": ["1"]}


def test_classic_2017_rooms_have_absolute_dates_and_no_bedrooms():
    _, by_id = parse_fixture("wayback_classic_rooms_2017.html.gz")
    assert all(c.attributes == {} for c in by_id.values())  # room slugs state no bedrooms
    assert all(c.category_id == 36 for c in by_id.values())
    old = by_id["1227508026"]  # "29/12/2016": the year before the capture
    assert (old.price, old.activation_date) == (470.0, "2016-12-29T00:00:00Z")
    assert by_id["1164756905"].activation_date == "2017-01-04T00:00:00Z"
    fresh = by_id["1229282112"]  # "< 25 minutes ago"
    assert (fresh.price, fresh.activation_date) == (480.0, "2017-01-06T18:34:51Z")


def test_classic_v0_2014_spot_checks():
    _, by_id = parse_fixture("wayback_classic_v0_apts_2014.html.gz")
    card = by_id["1024190610"]
    assert (card.price, card.price_type) == (900.0, "FIXED")
    assert card.attributes == {"numberbedrooms": ["2"]}  # from the /v-2-bedroom-... slug
    assert card.ad_source == "ORGANIC"
    assert card.description.startswith("This is a second floor apartment")
    assert "306" not in card.description  # the snippet's phone number is stripped at parse
    top = by_id["1022698821"]
    assert (top.ad_source, top.price) == ("TOP_AD", 1099.0)
    assert top.activation_date is None  # top ads show no posting date in this era
    assert top.attributes == {"numberbedrooms": ["3"]}
    assert by_id["1018146482"].attributes == {"numberbedrooms": ["4"]}  # 4-plus-bedroom slug
    assert all(c.address_text is None and c.intersection is None for c in by_id.values())


def test_classic_v0_relative_dates_resolve_against_the_capture_time():
    html = load("wayback_classic_v0_apts_2014.html.gz")
    # This era embeds no render time, so "< 10 minutes ago" needs the capture time.
    _, _, cards = parse_capture(html, "2014-10-08T00:12:47Z")
    by_id = {c.source_id: c for c in cards}
    assert by_id["1024190610"].activation_date == "2014-10-08T00:02:47Z"
    _, _, without = parse_capture(html)
    assert {c.source_id: c for c in without}["1024190610"].activation_date is None


def test_classic_v0_2015_please_contact_is_price_none():
    _, by_id = parse_fixture("wayback_classic_v0_apts_2015.html.gz")
    wanted = by_id["1054289563"]
    assert (wanted.price, wanted.price_type) == (None, "CONTACT")
    assert by_id["1054275775"].attributes == {"numberbedrooms": ["0"]}  # bachelor-studio slug
    fresh = by_id["1054291535"]  # "< 2 hours ago" before a 02:51 capture crosses midnight
    assert (fresh.price, fresh.activation_date) == (1499.0, "2015-03-01T00:51:56Z")


def test_classic_2022_french_prices_dates_and_quebec_bedrooms():
    total, by_id = parse_fixture("wayback_classic_apts_2022_fr.html.gz")
    assert total == 732
    absolute = by_id["1616480565"]  # "1 760,00 $", "10-mai-22", "Pièces: 3 1/2"
    assert (absolute.price, absolute.price_type) == (1760.0, "FIXED")
    assert absolute.activation_date == "2022-05-10T00:00:00Z"
    assert absolute.attributes == {"numberbedrooms": ["1"]}
    relative = by_id["1617760366"]  # "Il y a moins de 24 heures", "Pièces: 6 1/2"
    assert relative.price == 2998.0
    assert relative.activation_date == "2022-06-04T03:35:47Z"  # page render time, minus a day
    assert relative.attributes == {"numberbedrooms": ["4"]}
    assert relative.intersection == "Huron Road & Plains Road"
    contact = by_id["1611532565"]  # "Sur demande"
    assert (contact.price, contact.price_type) == (None, "CONTACT")
    assert by_id["1604827042"].activation_date == "2022-06-02T00:00:00Z"  # "02-juin-22"
    assert by_id["1604827042"].attributes == {"numberbedrooms": ["5"]}  # "Pièces: 7 1/2 +"
    assert by_id["1616881350"].attributes == {"numberbedrooms": ["1"]}  # "1 ½ ou 2 ½", floor 1
    assert by_id["1617848987"].attributes == {"numberbedrooms": ["1"]}  # "3 1/2 et coin détente"


@pytest.mark.parametrize(
    "name", ["wayback_classic_v0_apts_2014.html.gz", "wayback_classic_apts_2022_fr.html.gz"]
)
def test_scrubbed_classic_fixtures_parse_identically(name):
    _, captured_at, _, _ = CLASSIC_FIXTURES[name]
    html = load(name)
    stored = scrub_capture(html)
    assert detect_format(stored) == detect_format(html)
    assert parse_capture(stored, captured_at) == parse_capture(html, captured_at)


def test_scrubbing_a_dirty_classic_page_keeps_the_parse():
    page = classic_page(
        classic_card_html(
            101,
            title="Two bedroom, call Mike 519-555-0199",
            price="$1,200.00",
            posted="< 2 hours ago",
            desc="Email bob@example.com or text 519 555 0199 for a viewing.",
            slug="two-bedroom-call-519-555-0199",
            cat="v-2-bedroom-apartments-condos",
            extra='<a href="tel:5195550199">call us</a>',
        )
    )
    stored = scrub_capture(page)
    assert "519-555-0199" not in stored and "519 555 0199" not in stored
    assert "bob@example.com" not in stored and "tel:" not in stored
    assert detect_format(stored) == "classic"
    assert parse_capture(stored) == parse_capture(page)
    _, _, (card,) = parse_capture(stored)
    assert card.price == 1200.0 and card.source_id == "101"
    assert "519" not in card.title and "Mike" not in card.title
    assert "519" not in (card.description or "") and "bob" not in (card.description or "")
    assert "519" not in card.url and card.url.endswith("/101")


def test_classic_price_and_bedroom_variants_parse():
    page = classic_page(
        classic_card_html(201, title="A", price="Sur demande", posted="10-mai-22")
        + classic_card_html(202, title="B", price="Swap / Trade", posted="05/06/2017")
        + classic_card_html(
            203, title="C", price="2 500,00&nbsp;$", posted="Il y a moins de 24 heures"
        )
        + classic_card_html(204, title="D", price="Please Contact", posted="", beds="Pièces: 5 1/2")
        + classic_card_html(
            205, title="E", price="$850.00", posted="", beds="Bedrooms: 2", top=True
        )
    )
    fmt, total, cards = parse_capture(page)
    assert (fmt, total, len(cards)) == ("classic", 1234, 5)
    by_id = {c.source_id: c for c in cards}
    assert (by_id["201"].price, by_id["201"].price_type) == (None, "CONTACT")
    assert by_id["201"].activation_date == "2022-05-10T00:00:00Z"
    assert (by_id["202"].price, by_id["202"].price_type) == (None, "SWAP_TRADE")
    assert by_id["202"].activation_date == "2017-06-05T00:00:00Z"
    assert by_id["203"].price == 2500.0
    assert by_id["203"].activation_date == "2022-06-04T03:35:47Z"  # a day before the dataLayer ts
    assert by_id["204"].attributes == {"numberbedrooms": ["3"]}  # 5 1/2 Quebec rooms
    assert by_id["204"].activation_date is None
    assert by_id["205"].attributes == {"numberbedrooms": ["2"]}  # English span
    assert by_id["205"].ad_source == "TOP_AD"


@pytest.mark.parametrize("name", CLASSIC_FIXTURES)
def test_classic_fixtures_carry_no_contact_info(name):
    """The committed wayback fixtures hold no email, phone, tel: link or poster name."""
    html = load(name)
    assert EMAIL_RE.search(html) is None
    assert OBFUSCATED_EMAIL_RE.search(html) is None
    assert re.search(r"href=[\"'](?:tel|sms|callto):", html, re.I) is None
    # A phone number written with separators; bare digit runs are ad ids, which stay.
    assert (
        re.search(r"(?<!\d)\(?\d{3}\)?[\s.\u00a0-]{1,3}\d{3}[\s.\u00a0-]{1,3}\d{4}(?!\d)", html)
        is None
    )
    assert re.search(r"sellerName|posterName|profileName", html, re.I) is None
    _, by_id = parse_fixture(name)
    for card in by_id.values():
        assert strip_contact_info(card.title) == card.title
        assert card.description is None or strip_contact_info(card.description) == card.description


def test_unknown_layouts_still_raise_unsupported():
    with pytest.raises(UnsupportedFormat) as info:
        parse_capture("<html><body>nothing to see</body></html>", "2020-01-01T00:00:00Z")
    assert info.value.format == "unknown"


# --- ad pages ------------------------------------------------------------------------------

PERSONAL = ("Alex", "Smith", "519-555-0199", "5195550199", "alex.smith@example.com")


@pytest.mark.parametrize(
    ("html", "fmt"),
    [
        (nextjs_ad_page(1), "nextjs_ad"),
        (vip_legacy_page(1), "vip_legacy"),
        (removed_ad_page(), "removed"),
        ("<html><body>Wayback Machine has not archived that URL.</body></html>", "unknown"),
        ('<html><script>window.__data = {"homepage": {}};</script></html>', "unknown"),
    ],
)
def test_detect_ad_format(html, fmt):
    assert detect_ad_format(html) == fmt


def test_todays_ad_page_is_stored_scrubbed_and_parsed_by_the_live_parser():
    stored = scrub_ad_capture(nextjs_ad_page(11, 800, show_pin=False))
    for word in PERSONAL:
        assert word not in stored, word
    fmt, ad = parse_ad_capture(stored)
    assert fmt == "nextjs_ad"
    assert (ad.source_id, ad.price, ad.show_pin) == ("11", 800.0, False)
    assert ad.activation_date == "2025-08-12T10:00:00Z"
    assert "January - April 2027" in ad.description


def test_legacy_ad_page_is_stored_as_an_extract_without_personal_data():
    page = vip_legacy_page(22, 900)
    stored = scrub_ad_capture(page)
    assert stored.startswith("<!-- archive-format: vip_legacy; extract -->")
    for word in (*PERSONAL, "sellerName"):
        assert word not in stored, word
    assert detect_ad_format(stored) == "vip_legacy"

    fmt, ad = parse_ad_capture(stored)
    assert fmt == "vip_legacy"
    assert (ad.source_id, ad.price, ad.category_id) == ("22", 900.0, 36)
    assert ad.title == "Room 22 & more"  # HTML entities decoded
    assert ad.url == "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/room/22"
    assert ad.activation_date is None  # this layout has no first-posting date
    assert ad.sorting_date == "2024-12-08T18:58:32Z"
    assert ad.attributes == {"furnished": ["1"], "petsallowed": ["limited"]}
    assert (ad.poster_id, ad.image_count, ad.lat) == ("67337130", 2, 43.47195)
    assert "<br>" not in ad.description and "5 bedroom house" in ad.description


def test_legacy_extract_parses_like_the_raw_page():
    page = vip_legacy_page(23, description="Plain room, no contact details here.")
    raw = parse_ad_capture(page)[1]
    stored = parse_ad_capture(scrub_ad_capture(page))[1]
    assert raw == stored


def test_a_removed_ad_parses_to_nothing():
    assert parse_ad_capture(removed_ad_page()) == ("removed", None)


def test_unknown_ad_pages_are_not_stored():
    stored = scrub_ad_capture("<html>Call Alex at 519-555-0199</html>")
    assert "519" not in stored and "Alex" not in stored
    with pytest.raises(UnsupportedFormat):
        parse_ad_capture(stored)
