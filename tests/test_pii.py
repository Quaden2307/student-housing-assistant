import json

import pytest

from housing.parse.kijiji import next_data, parse_detail
from housing.parse.pii import (
    REDACTED,
    encode_next_data,
    hash_id,
    redact_url,
    scrub_page,
    strip_contact_info,
)
from tests.helpers import load


def test_strips_emails_and_phone_formats():
    text = "Call 519-555-0199 or (519) 555 0199 or +1 519.555.0199, email me@example.com"
    out = strip_contact_info(text)
    assert "519" not in out and "example.com" not in out
    assert out.count(REDACTED) == 4
    assert out == f"Call {REDACTED} or {REDACTED} or {REDACTED}, email {REDACTED}"


def test_leaves_prices_dates_postal_codes_and_none_alone():
    text = "$1,200/month, available 2026-11-01, N2L 3G1, 5 bedroom house at 123 King St N"
    assert strip_contact_info(text) == text
    assert strip_contact_info(None) is None


@pytest.mark.parametrize(
    "number",
    [
        "(519 )555 0199",
        "519 - 555 - 0199",
        "519  555  0199",
        "(519) 555 - 0199",
        "519 .555.0199",
        "519 555 01 99",
        "five one nine 555 0199",
        "5 1 9 5 5 5 0 1 9 9",
        "+1 519 555 0199",
        "15195550199",
    ],
)
def test_loose_phone_spacings_are_stripped(number):
    assert strip_contact_info(f"Text me at {number} to book") == f"Text me at {REDACTED} to book"


def test_seven_digit_number_only_after_a_contact_word():
    assert strip_contact_info("call 555-0199") == f"call {REDACTED}"
    assert strip_contact_info("Rooms 650-1000 per month") == "Rooms 650-1000 per month"


def test_written_out_emails():
    assert strip_contact_info("reach me at gmail dot com") == f"reach {REDACTED}"
    assert strip_contact_info("me [at] gmail.com") == REDACTED
    assert (
        strip_contact_info("located at Columbia. Close to campus")
        == "located at Columbia. Close to campus"
    )


def test_names_after_contact_phrases_and_sign_offs():
    assert (
        strip_contact_info("Please contact Candice at 519-555-0199")
        == f"Please contact {REDACTED} at {REDACTED}"
    )
    assert (
        strip_contact_info("Text Sarah or Mike for a viewing") == f"Text {REDACTED} for a viewing"
    )
    assert strip_contact_info("My name is Priya, text me") == f"My name is {REDACTED}, text me"
    assert strip_contact_info("Thanks,\nSam Lee") == f"Thanks,\n{REDACTED}"
    assert strip_contact_info("Ask for John.") == f"Ask for {REDACTED}."
    assert strip_contact_info("contact Subhra for details") == f"contact {REDACTED} for details"


@pytest.mark.parametrize(
    "text",
    [
        "Contact the landlord",
        "Contact Me today",
        "Call Today!",
        "message Kijiji",
        "Thanks for reading",
        "Contact Waterloo Property Management",
        "Reach out anytime",
        "Email Address: see above",
        "Text Only, no calls",
        "one two three bedroom units",
        "Rooms 101, 102, 103, 104 available",
        "2026 2027 10 11",
        "units 1000 1100 1200 1300",
        "Rent $650 - $750 - $850",
    ],
)
def test_contact_words_without_contact_details_are_left_alone(text):
    assert strip_contact_info(text) == text


def test_redact_url_only_touches_the_slug():
    base = "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo"
    assert (
        redact_url(f"{base}/1-bedroom-available-519-555-0199/1742392485")
        == f"{base}/1-bedroom-available/1742392485"
    )
    assert (
        redact_url(f"{base}/nice-room-near-uw/1742392485") == f"{base}/nice-room-near-uw/1742392485"
    )
    assert redact_url(f"{base}/5195550199/1742392485") == f"{base}/listing/1742392485"
    assert redact_url(None) is None


def test_scrub_page_removes_profile_name_phone_and_contact_text():
    state = {
        "StandardProfileV2:1": {"id": "1", "name": "Jane Poster"},
        "StandardListing:2": {
            "id": "2",
            "title": "Room call 519-555-0199",
            "description": "Email me@example.com <b>now</b>",
            "posterInfo": {"posterId": "1", "phoneNumber": "519-555-0199"},
        },
    }
    page = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"__APOLLO_STATE__": state}}})
        + '</script><a href="/o-profile/1/1">Jane Poster</a></html>'
    )
    out = scrub_page(page)
    assert "Jane Poster" not in out and "519-555-0199" not in out and "example.com" not in out
    assert '"phoneNumber":null' in out and "</b>" not in out.split("</script>")[0]
    entity = next_data(out)["props"]["pageProps"]["__APOLLO_STATE__"]["StandardListing:2"]
    assert entity["title"] == f"Room call {REDACTED}" and entity["description"].endswith(
        "<b>now</b>"
    )
    assert scrub_page("<html>no data</html>") == "<html>no data</html>"


def _detail_page(description, poster_name, outside=""):
    """A minimal detail page: one listing and the poster's profile, plus HTML after the JSON."""
    state = {
        "StandardListing:2": {"id": "2", "title": "Room near UW", "description": description},
        "StandardProfileV2:1": {"id": "1", "name": poster_name},
    }
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + encode_next_data({"props": {"pageProps": {"__APOLLO_STATE__": state}}})
        + f"</script>{outside}</html>"
    )


def _description(html):
    return next_data(html)["props"]["pageProps"]["__APOLLO_STATE__"]["StandardListing:2"][
        "description"
    ]


def test_sign_off_after_repeated_punctuation_and_a_blank_line():
    assert strip_contact_info("Thanks!!\n\nJames Smith") == f"Thanks!!\n\n{REDACTED}"
    assert strip_contact_info("Cheers...\nJames Smith") == f"Cheers...\n{REDACTED}"
    assert strip_contact_info("Thanks!! for reading") == "Thanks!! for reading"


def test_surname_after_a_removed_name_is_removed_too():
    assert strip_contact_info("Ask [removed] Smith about it") == "Ask [removed] about it"
    assert strip_contact_info("Ask [removed] O'Brien.") == "Ask [removed]."
    assert strip_contact_info("Contact [removed] Today") == "Contact [removed] Today"


def test_scrub_page_removes_poster_name_at_the_start_of_a_line():
    # In the JSON a line break is the two characters "\n", so "\nAlex" has no word boundary.
    out = scrub_page(_detail_page("Nice room.\n\nAlex Smith", "Alex"))
    assert "Alex" not in out and "Smith" not in out
    assert _description(out) == "Nice room.\n\n[removed]"


def test_scrub_page_removes_poster_name_after_escaped_html_and_its_surname():
    # "<" is escaped as "\u003c", so "<b>Alex" is "\u003cb\u003eAlex" in the raw page.
    out = scrub_page(_detail_page("<b>Alex</b> or ask Alex Smith about it", "Alex"))
    assert "Alex" not in out and "Smith" not in out
    assert _description(out) == "<b>[removed]</b> or ask [removed] about it"


def test_scrub_page_removes_surnames_left_by_an_earlier_scrub():
    # A page scrubbed before the surname rule: its profile name is already gone.
    out = scrub_page(
        _detail_page("Ask [removed] Smith about it", "[removed]", "<p>[removed] Smith</p>")
    )
    assert "Smith" not in out and _description(out) == "Ask [removed] about it"


def test_scrub_page_removes_poster_name_from_every_copy_on_a_real_page():
    # Kijiji repeats the description in ld+json blocks (JSON-escaped too), meta tags and the
    # rendered body; the name must go from all of them, not only from __NEXT_DATA__.
    html = load("kijiji_detail_rooms_2026-10-14.html.gz")
    end = "Minimum 12-month lease."
    html = html.replace(end + '"', end + '\\n\\nAlex Smith"')
    html = html.replace(end + "</div>", end + "\nAlex Smith</div>")
    html = html.replace('"name":"[removed]"', '"name":"Alex"')
    assert html.count("Alex Smith") >= 3
    out = scrub_page(html)
    assert "Alex" not in out and "Smith" not in out
    assert parse_detail(out).description.endswith(end + "\n\n[removed]")


def test_hash_id_needs_a_salt_and_depends_on_it(monkeypatch):
    monkeypatch.setenv("HOUSING_HASH_SALT", "s1")
    a = hash_id("42")
    assert a == hash_id("42") and len(a) == 16 and hash_id(None) is None
    monkeypatch.setenv("HOUSING_HASH_SALT", "s2")
    assert hash_id("42") != a
    monkeypatch.delenv("HOUSING_HASH_SALT")
    with pytest.raises(RuntimeError, match="HOUSING_HASH_SALT"):
        hash_id("42")
