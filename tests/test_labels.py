"""Tests for the title-based room / whole-unit label fixes."""

import pandas as pd
import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.model.labels import attach_titles, fix_labels


def frame(rows):
    """rows: (unit_type, bedrooms, price, title). Target as load_training computes it."""
    df = pd.DataFrame(rows, columns=["unit_type", "bedrooms", "price", "title"])
    df["bedrooms"] = df["bedrooms"].astype("Int64")
    df["price_per_bedroom"] = [
        p if u == "room" or pd.isna(b) else p / b
        for u, b, p in zip(df.unit_type, df.bedrooms, df.price, strict=True)
    ]
    df["dedup_key"] = [f"k{i}" for i in range(len(df))]
    return df


@pytest.mark.parametrize(
    ("unit_type", "bedrooms", "price", "title"),
    [
        ("1bed", 1, 695, "10 Hickory | Spacious Student Bedroom Available on Hickory St!"),
        ("2bed", 2, 650, "1 BEDROOM FOR RENT IN SPACIOUS 2-BEDROOM CONDO"),
        ("house", 3, 795, "Room avail for female, walking dis to Laurier"),
        ("2bed", 2, 895, "Private Shared studio unit for $895 per person"),
        ("1bed", 1, 695, "Bedroom in a Furnished 5 Bedroom Apartment Steps from Laurier/UW"),
    ],
)
def test_single_rooms_in_whole_unit_labels_become_rooms(unit_type, bedrooms, price, title):
    fixed, report = fix_labels(frame([(unit_type, bedrooms, price, title)]))
    assert report.to_room == 1
    assert fixed.loc[0, "unit_type"] == "room"
    assert fixed.loc[0, "price_per_bedroom"] == price  # no longer divided by bedrooms


@pytest.mark.parametrize(
    ("price", "title"),
    [
        (1699, "1 Bedroom Available in Kitchener | 50% off FMR | CALL NOW!"),
        (1525, "Spacious One Bedroom Available July 1st"),
        (1950, "Bright room-sized den in 2 bed condo"),
        (1100, "1 bed 2 bath apartment"),
    ],
)
def test_whole_units_stay_whole_units(price, title):
    fixed, report = fix_labels(frame([("1bed", 1, price, title)]))
    assert report.to_room == 0
    assert fixed.loc[0, "unit_type"] == "1bed"


def test_room_relabel_needs_a_room_price():
    fixed, report = fix_labels(frame([("1bed", 1, 1600, "Private room in a luxury condo")]))
    assert report.to_room == 0 and fixed.loc[0, "unit_type"] == "1bed"


def test_whole_unit_in_rooms_category_gets_its_bedroom_count():
    fixed, report = fix_labels(
        frame([("room", None, 1800, "2 BED ROOM 1 BATH APARTMENT FOR RENT IN WATERLOO")])
    )
    assert report.to_unit == 1
    assert fixed.loc[0, "unit_type"] == "2bed"
    assert fixed.loc[0, "bedrooms"] == 2
    assert fixed.loc[0, "price_per_bedroom"] == 900


@pytest.mark.parametrize(
    ("price", "title"),
    [
        (700, "6 BEDROOMS STUDENT HOUSE FOR RENT"),  # per-room price
        (695, "FIRST MONTH FREE- 1 ROOM LEFT FOR FEMALE IN A 3 BEDROOM UNIt"),
        (1500, "2 Bedroom Shared Home"),
        (975, "1 room sublet in 2-bedroom apartment - Sunview st"),
    ],
)
def test_rooms_naming_their_house_stay_rooms(price, title):
    fixed, report = fix_labels(frame([("room", None, price, title)]))
    assert report.to_unit == 0
    assert fixed.loc[0, "unit_type"] == "room"


def test_studio_and_basement_rules():
    fixed, report = fix_labels(
        frame(
            [
                ("room", None, 950, "A very clean and quiet bachelor unit"),
                ("room", None, 1500, "Walkout Basement"),
                ("room", None, 460, "Basement Room for Rent - Kitchener"),
                ("room", None, 700, "Basement for rent near Conestoga"),
            ]
        )
    )
    assert report.to_studio == 1 and report.dropped_basement_units == 1
    assert list(fixed["unit_type"]) == ["studio", "room", "room"]


@pytest.mark.parametrize(
    ("unit_type", "price", "title"),
    [
        ("room", 390, "(wanting to rent a room)"),
        ("room", 550, "Looking a Roomate"),
        ("room", 600, "Christian guy looking for room rental."),
        ("room", 975, "In search of roommate"),
        ("room", 500, "Shared room in kitchener for male"),
        ("room", 432, "Downtown Kitchener – Room Sharing Available!"),
        ("room", 450, "Room for Rent in Sharing near Conestoga"),
        ("room", 550, "Spot in a shared room"),
        ("1bed", 375, "therapy/ counselling office for rent in Waterloo"),
        ("studio", 3000, "Office Space for Lease – 541 Queen St, Kitchener!"),
    ],
)
def test_ads_that_are_not_a_home_are_dropped(unit_type, price, title):
    fixed, report = fix_labels(frame([(unit_type, 1, price, title)]))
    assert report.dropped_not_a_home == 1 and fixed.empty


@pytest.mark.parametrize(
    "title",
    [
        "Upper 2 bedroom or 1 plus den/office -- King & Rosedale",
        "Room with private bathroom & office for rent",
        "For rent - new 3 BR house with office in Kitchener",
        "Room for rent near University of Waterloo",
        "Roommate wanted - 3 Bed 1 Bath House w/Backyard",
        "Private room in a shared house",
    ],
)
def test_homes_that_mention_offices_or_sharing_stay(title):
    _, report = fix_labels(frame([("room", None, 700, title)]))
    assert report.dropped_not_a_home == 0


def test_rows_without_title_are_left_alone():
    fixed, report = fix_labels(frame([("1bed", 1, 700, None)]))
    assert report.no_title == 1 and fixed.loc[0, "unit_type"] == "1bed"


def test_attach_titles_reads_live_and_archive(tmp_path):
    conn = connect(tmp_path / "h.db")
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    required = {
        r[1]: r[4] for r in conn.execute("PRAGMA table_info(listings)") if r[3] and r[1] != "id"
    }
    values = {c: f"x{c}" for c in required}
    values["title"] = "Live title"
    assert "title" in cols
    names = ", ".join(values)
    conn.execute(
        f"INSERT INTO listings (id, {names}) VALUES (7, {', '.join('?' * len(values))})",
        list(values.values()),
    )
    conn.execute(
        "INSERT INTO archive_listings (source_id, title, first_seen, last_seen)"
        " VALUES ('a1', 'Archive title', '2024-01-01', '2024-01-02')"
    )
    df = pd.DataFrame({"dedup_key": ["addr:x", "archive:a1"], "listing_id": [7, -1]})
    out = attach_titles(conn, df)
    assert list(out["title"]) == ["Live title", "Archive title"]
