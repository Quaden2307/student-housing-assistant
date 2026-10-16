"""Unit-field extraction rules."""

import pytest

from housing.parse.units import extract

HOUSE_ATTRS = {
    "unittype": "house", "numberbedrooms": "3", "numberbathrooms": "10", "agreementtype": "one-year",
    "dateavailable": "2026-09-15T00:00:00Z", "furnished": "0", "laundryinunit": "1", "laundryinbuilding": "0",
    "heat": "0", "hydro": "0", "water": "0", "internet": "0",
}  # fmt: skip


def test_apartments_house_from_attributes():
    u = extract(category="apartments", title="3 bedrooms house for rent", description="Nice house.",
                attributes=HOUSE_ATTRS, address="Waterloo, ON N2J 3X2")  # fmt: skip
    assert (u.unit_type, u.bedrooms, u.bathrooms) == ("house", 3, 1.0)
    assert u.lease_term == "12mo" and u.move_in_month == 9
    assert u.utilities_included is False and u.furnished is False and u.laundry_in_unit is True
    assert u.building_type == "house" and u.year_built_after_2018 is None
    assert u.extracted_by == "page_attrs" and u.flags == {}


def test_studio_and_bedroom_buckets():
    assert (
        extract(
            category="apartments",
            title="Bachelor",
            description=None,
            attributes={"numberbedrooms": "0"},
        ).bedrooms
        == 1
    )
    assert (
        extract(
            category="apartments",
            title="Bachelor",
            description=None,
            attributes={"numberbedrooms": "0"},
        ).unit_type
        == "studio"
    )
    assert (
        extract(
            category="apartments", title="x", description=None, attributes={"numberbedrooms": "1.5"}
        ).unit_type
        == "1bed"
    )
    assert (
        extract(
            category="apartments", title="x", description=None, attributes={"numberbedrooms": "2"}
        ).unit_type
        == "2bed"
    )
    assert (
        extract(
            category="apartments",
            title="x",
            description=None,
            attributes={"numberbedrooms": "4", "unittype": "apartment"},
        ).unit_type
        == "3plus"
    )
    assert (
        extract(
            category="apartments", title="x", description=None, attributes={"numberbathrooms": "15"}
        ).bathrooms
        == 1.5
    )


def test_per_room_ad_under_apartments_becomes_room_and_keeps_house_bedrooms():
    u = extract(
        category="apartments",
        title="The Block - Student Apt Waterloo",
        description="$1200 per room in a 2 bedroom, 2 bathroom unit. All inclusive, furnished, ensuite bathroom.",
        attributes={
            "numberbedrooms": "2",
            "numberbathrooms": "20",
            "unittype": "apartment",
            "agreementtype": "one-year",
        },
    )
    assert u.unit_type == "room" and u.bedrooms == 2 and u.bathrooms == 2.0
    assert u.flags["per_room_price"] == "1" and u.flags["bathroom_private"] == "1"
    assert u.utilities_included is True  # no heat/hydro/water attributes, so the text decides
    assert u.building_type == "purpose_built_student"


def test_rooms_category_text_extraction():
    u = extract(
        category="rooms",
        title="Female sublet January - April 2027, 275 Larch St",
        description="One bedroom in a 2 bedroom, 2 bathroom apartment at 275 Larch St (Building C) for the "
        "Winter 2027 term. Fully furnished, all utilities and internet included. Ensuite laundry.",
        attributes={"furnished": "1", "petsallowed": "limited"},
        address="Waterloo, ON N2L 3R2",
    )
    assert u.unit_type == "room" and u.bedrooms == 2 and u.bathrooms == 2.0
    assert u.lease_term == "sublet_4mo" and u.move_in_month == 1
    assert u.utilities_included is True and u.flags["internet_included"] == "1"
    assert u.furnished is True and u.laundry_in_unit is True
    assert u.building_type == "purpose_built_student" and u.flags["building_name"] == "275 Larch"
    assert u.extracted_by == "regex"


def test_rooms_in_a_house_with_utilities_extra_and_shared_laundry():
    u = extract(
        category="rooms",
        title="Room for rent in shared house",
        description="Room in a 5 bedroom house near UW, available now. $650 plus utilities. "
        "Shared laundry in the basement. Unfurnished. 8 month lease available.",
        attributes={},
    )
    assert u.unit_type == "room" and u.bedrooms == 5
    assert u.lease_term == "8mo" and u.move_in_month is None and u.flags["available_now"] == "1"
    assert u.utilities_included is False and u.furnished is False and u.laundry_in_unit is False
    assert u.building_type == "house"


def test_whole_unit_posted_under_rooms():
    u = extract(category="rooms", title="Entire basement apartment for rent",
                description="Whole unit, 2 bedroom basement, separate entrance, available Nov 1st.", attributes={})  # fmt: skip
    assert u.unit_type == "2bed" and u.bedrooms == 2 and u.move_in_month == 11
    assert u.building_type == "house"


def test_lease_takeover_and_twelve_month_text():
    u = extract(
        category="rooms",
        title="Lease takeover from May 1",
        description="12 month lease, takeover my room.",
        attributes={},
    )
    assert u.lease_term == "12mo" and u.flags["is_takeover"] == "1" and u.move_in_month == 5


def test_month_to_month_and_new_build():
    u = extract(category="apartments", title="Brand new building", description="Month to month, built in 2024. Available ASAP.",
                attributes={"numberbedrooms": "1", "unittype": "apartment"})  # fmt: skip
    assert u.lease_term == "month_to_month" and u.year_built_after_2018 is True
    assert u.move_in_month is None and u.flags["available_now"] == "1"


def test_registry_years_set_rent_control_flag():
    pre = extract(category="apartments", title="x", description="Bridgeport House", attributes={"numberbedrooms": "4"},
                  address="328 Regina St N, Waterloo")  # fmt: skip
    post = extract(category="apartments", title="x", description="Elora House", attributes={"numberbedrooms": "4"},
                   address="250 Phillip St, Waterloo")  # fmt: skip
    assert pre.year_built_after_2018 is False and post.year_built_after_2018 is True
    assert pre.building_type == post.building_type == "purpose_built_student"


def test_nothing_known_gives_nulls_and_unknowns():
    u = extract(category="apartments", title="Apartment", description=None, attributes={})
    assert u.unit_type is None and u.bedrooms is None and u.bathrooms is None
    assert u.lease_term == "unknown" and u.building_type == "unknown"
    assert u.utilities_included is None and u.move_in_month is None and u.flags == {}


@pytest.mark.parametrize(
    "text, term",
    [
        ("Room Sept to April", "8mo"),
        ("Lease September to April", "8mo"),
        ("Room May 2027 to April 2028", "12mo"),
        ("Lease from September 2026 to August 2027, 12 months.", "12mo"),
        ("Rooms available Jan 2027 - Dec 2027", "12mo"),
        ("Single bedroom (Jan 2027-Aug 2027), 8-month lease", "8mo"),
        ("Jan - April sublet", "sublet_4mo"),
        ("Room October to December", "sublet_4mo"),
        ("From May 1 to August 31", "sublet_4mo"),
        ("Winter term rental", "sublet_4mo"),
        ("September 2026 – August", "12mo"),
        ("Jan. 01 - August", "8mo"),
        ("October to August", "12mo"),
    ],
)
def test_lease_term_from_text(text, term):
    assert extract(category="rooms", title=text, description="", attributes={}).lease_term == term


def test_no_short_term_is_not_a_sublet():
    attrs = {"numberbedrooms": "2", "agreementtype": "one-year"}
    u = extract(category="apartments", title="2 bed", description="No short term rentals. One year lease.", attributes=attrs)  # fmt: skip
    assert u.lease_term == "12mo"
    u = extract(category="apartments", title="2 bed", description="No sublets.", attributes={"numberbedrooms": "2", "agreementtype": "month-to-month"})  # fmt: skip
    assert u.lease_term == "month_to_month"


def building_for(address, title="x"):
    u = extract(category="apartments", title=title, description=None, attributes={"numberbedrooms": "2"}, address=address)  # fmt: skip
    return u.building_type, u.flags.get("building_name")


def test_registry_matches_whole_street_numbers_and_spelled_out_streets():
    assert building_for("1 Columbia Street West, Waterloo, ON") == (
        "purpose_built_student",
        "The MARQ",
    )
    assert building_for("121 Columbia St W, Waterloo, ON N2L 3L1") == ("unknown", None)
    assert building_for("1250 Albert St, Waterloo") == ("unknown", None)
    assert building_for("250 Albert St., Waterloo") == ("purpose_built_student", "Sage Platinum I")
    assert building_for("333 King Street North Service Rd") == (
        "purpose_built_student",
        "King Street Towers I",
    )
    assert building_for("121 Columbia St W", title="Good Student Housing: From 725 -750/Room.") == (
        "unknown",
        None,
    )


def test_whole_unit_titles_are_not_rooms():
    attrs = {"numberbedrooms": "2", "unittype": "apartment"}
    for title, description in [
        ("TWO BEDROOM FOR RENT: Two month free promotion", ""),
        ("2 bedroom apartment, roommates welcome", ""),
        ("2 bedroom apartment", "No roommates allowed."),
        ("Spacious 2 bedroom unit", "Includes a room for a home office."),
    ]:
        u = extract(category="apartments", title=title, description=description, attributes=attrs)
        assert u.unit_type == "2bed" and "per_room_price" not in u.flags, title
    attrs = {"numberbedrooms": "3", "unittype": "house"}
    assert extract(category="apartments", title="Master bedroom for rent in 3 bedroom house", description="", attributes=attrs).unit_type == "room"  # fmt: skip
    assert extract(category="apartments", title="Roommate wanted for 3 bedroom house", description="", attributes=attrs).unit_type == "room"  # fmt: skip


def test_per_room_ad_under_apartments_takes_the_house_total():
    u = extract(category="apartments", title="Room for rent in 5 bedroom house", description="One room available in a 5 bedroom house.",
                attributes={"numberbedrooms": "1", "unittype": "house"})  # fmt: skip
    assert u.unit_type == "room" and u.bedrooms == 5


@pytest.mark.parametrize(
    "text, furnished",
    [
        ("The room is not furnished.", False),
        ("**NOT FURNISHED**", False),
        ("Utilities extra. Not furnished.", False),
        ("Unfurnished", False),
        ("Non-furnished room", False),
        ("Fully furnished", True),
        ("Quiet street", None),
    ],
)
def test_furnished_wording(text, furnished):
    assert (
        extract(category="rooms", title="Room", description=text, attributes={}).furnished
        is furnished
    )


def test_text_beats_attribute_flags_for_utilities_and_furnished():
    u = extract(category="apartments", title="2 bedroom ALL INCLUSIVE", description="Rent includes all utilities.",
                attributes={"numberbedrooms": "2", "heat": "0", "hydro": "0", "water": "0"})  # fmt: skip
    assert u.utilities_included is True
    u = extract(category="apartments", title="Fully Furnished, All Inclusive, 1 Parking", description=None,
                attributes={"numberbedrooms": "1", "furnished": "0"})  # fmt: skip
    assert u.furnished is True and u.utilities_included is True
    u = extract(category="apartments", title="1 bedroom", description="Plus utilities.",
                attributes={"numberbedrooms": "1", "heat": "1", "hydro": "1", "water": "1"})  # fmt: skip
    assert u.utilities_included is False
    u = extract(category="apartments", title="1 bedroom", description="Quiet building.",
                attributes={"numberbedrooms": "1", "heat": "1", "hydro": "1", "water": "0", "furnished": "1"})  # fmt: skip
    assert u.utilities_included is False and u.furnished is True


@pytest.mark.parametrize(
    "text, included",
    [
        ("Utilities: Not included", False),
        ("Rent $700. Utilities and internet are not included.", False),
        ("Utilities not incl.", False),
        ("Great for students, all in a quiet neighbourhood.", None),
        ("$650 all in.", True),
        ("Rent is 650 all in", True),
        ("Utilities (heat, water) included", True),
        ("Utilities included; cable not included", True),
    ],
)
def test_utilities_wording(text, included):
    assert (
        extract(category="rooms", title="Room", description=text, attributes={}).utilities_included
        is included
    )


def test_new_build_wording_needs_a_statement_about_the_building():
    attrs = {"numberbedrooms": "1"}
    assert extract(category="apartments", title="Brand new unit, renovated", description=None, attributes=attrs).year_built_after_2018 is None  # fmt: skip
    assert extract(category="apartments", title="New build, 1 bedroom", description=None, attributes=attrs).year_built_after_2018 is True  # fmt: skip
    assert extract(category="apartments", title="x", description="Built in 2021.", attributes=attrs).year_built_after_2018 is True  # fmt: skip


@pytest.mark.parametrize(
    "text, month",
    [
        ("Lease ends 2027-04-30.", None),
        ("Available 2026-11-01.", 11),
        ("Parking available, may be shared. Available now.", None),
        ("Available May 1st", 5),
        ("AVAILABLE MAY", 5),
        ("available may 2027", 5),
    ],
)
def test_move_in_month_is_never_a_lease_end_or_the_verb_may(text, month):
    assert (
        extract(category="rooms", title="Room", description=text, attributes={}).move_in_month
        == month
    )


def test_student_housing_wording_does_not_turn_a_house_into_a_tower():
    u = extract(category="apartments", title="Student Housing 90A McDougall 4 bed 750 incl util", description=None,
                attributes={"numberbedrooms": "4", "unittype": "house"})  # fmt: skip
    assert u.building_type == "house"
    u = extract(
        category="rooms",
        title="Student housing, room in a 5 bedroom house",
        description=None,
        attributes={},
    )
    assert u.building_type == "house"
    u = extract(category="apartments", title="Student residence, 2 bed", description=None, attributes={"numberbedrooms": "2"})  # fmt: skip
    assert u.building_type == "purpose_built_student"
