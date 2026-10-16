import json

import pytest

from housing.parse.kijiji import next_data
from housing.parse.pii import REDACTED, hash_id, redact_url, scrub_page, strip_contact_info


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


def test_hash_id_needs_a_salt_and_depends_on_it(monkeypatch):
    monkeypatch.setenv("HOUSING_HASH_SALT", "s1")
    a = hash_id("42")
    assert a == hash_id("42") and len(a) == 16 and hash_id(None) is None
    monkeypatch.setenv("HOUSING_HASH_SALT", "s2")
    assert hash_id("42") != a
    monkeypatch.delenv("HOUSING_HASH_SALT")
    with pytest.raises(RuntimeError, match="HOUSING_HASH_SALT"):
        hash_id("42")
