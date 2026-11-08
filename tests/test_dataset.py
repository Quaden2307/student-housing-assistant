import pandas as pd
import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.model.dataset import (
    BOOLEANS,
    CATEGORICALS,
    GROUP,
    NUMERICS,
    TARGET,
    load_training,
)

# The Sprint 2 training-frame contract, written out by hand on purpose: if the module
# drifts, this test must fail rather than drift with it.
EXPECTED_COLUMNS = [
    "listing_id",
    "dedup_key",
    "price",
    "price_per_bedroom",
    "unit_type",
    "lease_term",
    "building_type",
    "neighbourhood",
    "landlord_type",
    "bedrooms",
    "bathrooms",
    "sqft",
    "walk_uw_min",
    "walk_laurier_min",
    "ion_distance_m",
    "move_in_month",
    "utilities_included",
    "furnished",
    "laundry_in_unit",
    "year_built_after_2018",
    "bathroom_private",
    "is_takeover",
    "internet_included",
    "listing_month",
    "listing_year",
    "city",
    "first_seen",
    "last_seen",
    "is_archive",
]


def _add(
    conn,
    lid,
    *,
    title="2 bedroom unit",
    description=None,
    address="44 Chapel St, Kitchener, ON N2G 2S5",
    lat=43.47,
    lon=-80.52,
    first_seen="2026-10-01T06:30:00Z",
    last_seen="2026-10-20T06:30:00Z",
    dedup_key=None,
    price=1000.0,
    snapshot=True,
    units=True,
    unit_type="2bed",
    bedrooms=2,
    bathrooms=1.0,
    lease_term="12mo",
    move_in_month=None,
    utilities_included=None,
    furnished=None,
    laundry_in_unit=None,
    building_type="unknown",
    year_built_after_2018=None,
    neighbourhood="N2G",
    attrs=None,
):
    conn.execute(
        "INSERT INTO listings (id, source, source_id, title, description, address_text, lat, lon,"
        " first_seen, last_seen, status, dedup_key)"
        " VALUES (?, 'kijiji', ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        (lid, str(lid), title, description, address, lat, lon, first_seen, last_seen, dedup_key),
    )
    if snapshot:
        conn.execute(
            "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (?, ?, ?)",
            (lid, last_seen, price),
        )
    if units:
        conn.execute(
            "INSERT INTO units (listing_id, unit_type, bedrooms, bathrooms, lease_term,"
            " move_in_month, utilities_included, furnished, laundry_in_unit, building_type,"
            " year_built_after_2018) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lid,
                unit_type,
                bedrooms,
                bathrooms,
                lease_term,
                move_in_month,
                utilities_included,
                furnished,
                laundry_in_unit,
                building_type,
                year_built_after_2018,
            ),
        )
    conn.execute(
        "INSERT INTO features (listing_id, walk_uw_min, walk_laurier_min, ion_distance_m,"
        " neighbourhood) VALUES (?, 10.0, 12.0, 350.0, ?)",
        (lid, neighbourhood),
    )
    for name, value in (attrs or {}).items():
        conn.execute(
            "INSERT INTO listing_attributes (listing_id, name, value) VALUES (?, ?, ?)",
            (lid, name, value),
        )


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    # 1: kept room; its target is the asking price even with the house's bedroom count
    _add(
        conn,
        1,
        title="Room in a 5 bed house",
        unit_type="room",
        bedrooms=5,
        bathrooms=1.5,
        price=650,
        neighbourhood="N2L",
        attrs={"category": "rooms", "text_bathroom_private": "1", "areainfeet": "n/a"},
    )
    # 2: kept 2bed; latest non-null snapshot price must win (2400, not 2500 or the NULL)
    _add(
        conn,
        2,
        bedrooms=2,
        price=2400,
        move_in_month=9,
        utilities_included=1,
        furnished=0,
        building_type="lowrise",
        attrs={
            "category": "apartments",
            "areainfeet": "750",
            "forrentbyhousing": "ownr",
            "text_internet_included": "1",
        },
    )
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (2, '2026-09-20T06:30:00Z', 2500)"
    )
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (2, '2026-10-21T06:30:00Z', NULL)"
    )
    # 3: no snapshot price at all
    _add(conn, 3, snapshot=False)
    # 4 and 5: out of region (Toronto-ish latitude; missing coordinates)
    _add(conn, 4, lat=43.70)
    _add(conn, 5, lat=None)
    # 6: wanted ad
    _add(conn, 6, title="Looking for a room near UW", unit_type="room", bedrooms=4, price=800)
    # 7: bedrooms out of 1..8
    _add(conn, 7, unit_type="3plus", bedrooms=12, price=3000)
    # 8: bathrooms out of 1..6 is cleared, the row is kept
    _add(conn, 8, bedrooms=2, bathrooms=9.0, price=2000, attrs={"areainfeet": "0"})
    # 9: a whole unit with no bedroom count has no target
    _add(conn, 9, bedrooms=None, price=1500)
    # 10: price per bedroom below 300
    _add(conn, 10, unit_type="1bed", bedrooms=1, price=150)
    # 11: room asking 2000 passes the 300..3000 target range but not the room range
    _add(conn, 11, unit_type="room", bedrooms=4, price=2000)
    # 12 and 13: same unit, two ads; the newer last_seen wins
    _add(
        conn,
        12,
        unit_type="room",
        bedrooms=5,
        price=700,
        last_seen="2026-10-18T06:30:00Z",
        dedup_key="addr:250 lester st|room|5",
    )
    _add(
        conn,
        13,
        unit_type="room",
        bedrooms=5,
        price=720,
        last_seen="2026-10-22T06:30:00Z",
        dedup_key="addr:250 lester st|room|5",
    )
    # 14: rooms-category ad that was never extracted still counts as a room
    _add(conn, 14, units=False, price=700, attrs={"category": "rooms"})
    # 15 and 16: same key and same last_seen; the higher listing id wins the tie
    _add(
        conn,
        15,
        unit_type="room",
        bedrooms=4,
        price=600,
        last_seen="2026-10-22T06:30:00Z",
        dedup_key="addr:99 maple st|room|4",
    )
    _add(
        conn,
        16,
        unit_type="room",
        bedrooms=4,
        price=610,
        last_seen="2026-10-22T06:30:00Z",
        dedup_key="addr:99 maple st|room|4",
    )
    # 17 and 18: per-term totals, in the title and in the description
    _add(conn, 17, title="2 bed sublet - 4 months for $2400", price=2400)
    _add(
        conn,
        18,
        unit_type="room",
        bedrooms=4,
        price=900,
        description="Rent is $3600 per semester, all inclusive.",
    )
    # 19 to 23: boundary rows pinning the cleaning thresholds exactly
    _add(conn, 19, unit_type="3plus", bedrooms=8, price=4000)  # bedrooms top bound: kept
    _add(conn, 20, unit_type="1bed", bedrooms=1, price=300)  # target floor: kept
    _add(conn, 21, unit_type="1bed", bedrooms=1, price=250)  # below the floor: dropped
    _add(conn, 22, unit_type="room", bedrooms=5, price=1800)  # room price ceiling: kept
    _add(conn, 23, bedrooms=2, bathrooms=6.0, price=2000)  # bathrooms top bound: not cleared
    # 24 to 26: one key, prices beyond 5% apart are different units (HANDOFF section 5):
    # 600 and 612 band together (newest, 26, kept); 900 is its own band and stays
    _add(
        conn,
        24,
        unit_type="room",
        bedrooms=6,
        price=600,
        last_seen="2026-10-18T06:30:00Z",
        dedup_key="addr:77 king st n|room|6",
    )
    _add(
        conn,
        25,
        unit_type="room",
        bedrooms=6,
        price=900,
        last_seen="2026-10-20T06:30:00Z",
        dedup_key="addr:77 king st n|room|6",
    )
    _add(
        conn,
        26,
        unit_type="room",
        bedrooms=6,
        price=612,
        last_seen="2026-10-22T06:30:00Z",
        dedup_key="addr:77 king st n|room|6",
    )
    return conn


def test_contract_constants():
    assert TARGET == "price_per_bedroom"
    assert GROUP == "dedup_key"
    assert CATEGORICALS == [
        "unit_type",
        "lease_term",
        "building_type",
        "neighbourhood",
        "city",
        "landlord_type",
    ]
    assert NUMERICS == [
        "bedrooms",
        "bathrooms",
        "sqft",
        "walk_uw_min",
        "walk_laurier_min",
        "ion_distance_m",
        "move_in_month",
        "listing_month",
        "listing_year",
    ]
    assert BOOLEANS == [
        "utilities_included",
        "furnished",
        "laundry_in_unit",
        "year_built_after_2018",
        "bathroom_private",
        "is_takeover",
        "internet_included",
    ]


def test_columns_and_dtypes_match_contract(conn):
    df, _ = load_training(conn)
    assert list(df.columns) == EXPECTED_COLUMNS
    assert str(df["listing_id"].dtype) == "int64"
    for col in ("bedrooms", "move_in_month", "listing_month", "listing_year"):
        assert str(df[col].dtype) == "Int64", col
    for col in (
        "price",
        "price_per_bedroom",
        "bathrooms",
        "sqft",
        "walk_uw_min",
        "walk_laurier_min",
        "ion_distance_m",
    ):
        assert str(df[col].dtype) == "float64", col
    for col in BOOLEANS:
        assert str(df[col].dtype) == "boolean", col
    for col in (*CATEGORICALS, GROUP, "first_seen", "last_seen"):
        assert pd.api.types.is_string_dtype(df[col].dtype), col


def test_cleaning_counts(conn):
    df, report = load_training(conn)
    assert report.no_price == 1
    assert report.no_location == 1  # missing coordinates are not "out of region"
    assert report.out_of_region == 1
    assert report.wanted_ad == 1
    assert report.per_term_price == 2  # one in the title, one in the description
    assert report.bad_bedrooms == 1
    assert report.no_target == 1
    assert report.target_out_of_range == 2
    assert report.room_price_out_of_range == 1
    assert report.bathrooms_cleared == 1
    assert report.duplicates == 3
    assert report.kept == len(df) == 12
    assert sorted(df["listing_id"]) == [1, 2, 8, 13, 14, 16, 19, 20, 22, 23, 25, 26]
    line = str(report)
    assert "\n" not in line and "kept 12" in line and "duplicates=3" in line
    assert "no_location=1" in line and "per_term_price=2" in line


def test_values_follow_the_rules(conn):
    df, _ = load_training(conn)
    rows = df.set_index("listing_id")
    # a room's target is the asking price, even though bedrooms holds the house total
    assert rows.loc[1, "price_per_bedroom"] == rows.loc[1, "price"] == 650.0
    assert rows.loc[1, "bedrooms"] == 5
    assert rows.loc[1, "bathroom_private"] is True or rows.loc[1, "bathroom_private"] == True  # noqa: E712
    assert pd.isna(rows.loc[1, "internet_included"])  # no flag: unknown, not False
    assert pd.isna(rows.loc[1, "sqft"])  # non-numeric areainfeet
    assert pd.isna(rows.loc[1, "landlord_type"])
    assert rows.loc[1, "neighbourhood"] == "N2L"
    # whole unit: price / bedrooms, latest non-null snapshot price
    assert rows.loc[2, "price"] == 2400.0
    assert rows.loc[2, "price_per_bedroom"] == 1200.0
    assert rows.loc[2, "sqft"] == 750.0
    assert rows.loc[2, "landlord_type"] == "ownr"
    assert rows.loc[2, "internet_included"] == True  # noqa: E712
    assert rows.loc[2, "utilities_included"] == True  # noqa: E712
    assert rows.loc[2, "furnished"] == False  # noqa: E712
    assert pd.isna(rows.loc[2, "laundry_in_unit"])
    # missing detection flags read as False, not NA
    assert rows.loc[2, "bathroom_private"] == False  # noqa: E712
    assert rows.loc[2, "is_takeover"] == False  # noqa: E712
    assert rows.loc[2, "move_in_month"] == 9
    assert rows.loc[2, "listing_month"] == 10  # month of first_seen
    assert rows.loc[2, "walk_uw_min"] == 10.0
    assert rows.loc[2, "lease_term"] == "12mo"
    assert rows.loc[2, "building_type"] == "lowrise"
    # bathrooms outside 1..6 cleared, row kept
    assert pd.isna(rows.loc[8, "bathrooms"])
    assert pd.isna(rows.loc[8, "sqft"])  # areainfeet "0" means not given
    assert rows.loc[8, "price_per_bedroom"] == 1000.0
    # rooms-category ad with no units row becomes a room priced as asked
    assert rows.loc[14, "unit_type"] == "room"
    assert rows.loc[14, "price_per_bedroom"] == 700.0
    assert pd.isna(rows.loc[14, "bedrooms"])
    # a keyless row gets the per-row sentinel, so it is its own CV group, never NA
    assert rows.loc[14, "dedup_key"] == "listing:14"
    assert df["dedup_key"].notna().all()
    # boundary rows sit exactly on the cleaning thresholds and are kept intact
    assert rows.loc[19, "bedrooms"] == 8
    assert rows.loc[20, "price_per_bedroom"] == 300.0
    assert rows.loc[22, "price"] == 1800.0
    assert rows.loc[23, "bathrooms"] == 6.0  # on the bound: not cleared


def test_dedup_keeps_newest_ad_per_key(conn):
    df, report = load_training(conn)
    ids = set(df["listing_id"])
    assert 13 in ids and 12 not in ids  # newer last_seen wins
    assert 16 in ids and 15 not in ids  # same last_seen: higher id wins
    assert report.duplicates == 3

    both, report_all = load_training(conn, dedup=False)
    assert report_all.duplicates == 0
    assert {12, 13, 15, 16, 24, 25, 26} <= set(both["listing_id"])
    assert report_all.kept == len(both) == 15
    assert both["dedup_key"].notna().all()  # sentinels fill keyless rows here too


def test_dedup_splits_one_key_by_five_percent_price_bands(conn):
    # 24 ($600), 26 ($612) and 25 ($900) share one key: the two within 5% collapse to
    # the newest ad, while $900 is another unit at the same address and stays its own
    # training row -- still sharing the CV group (HANDOFF section 5).
    df, _ = load_training(conn)
    ids = set(df["listing_id"])
    assert 26 in ids and 24 not in ids  # same band: newest kept
    assert 25 in ids  # >5% away: a different unit survives dedup
    same_key = df[df["dedup_key"] == "addr:77 king st n|room|6"]
    assert sorted(same_key["listing_id"]) == [25, 26]


def test_per_term_totals_are_dropped(conn):
    df, report = load_training(conn)
    assert report.per_term_price == 2
    assert {17, 18}.isdisjoint(set(df["listing_id"]))


def test_empty_database(tmp_path):
    conn = connect(tmp_path / "empty.db")
    migrate(conn)
    df, report = load_training(conn)
    assert list(df.columns) == EXPECTED_COLUMNS
    assert len(df) == 0
    assert report.kept == 0
    assert "kept 0" in str(report)


def test_out_of_region_checks_each_listing_against_its_own_market(conn):
    # The same Hamilton coordinates: dropped for a listing with no location attribute
    # (pre-expansion rows default to Kitchener-Waterloo), kept for one swept in Hamilton.
    _add(conn, 30, lat=43.25, lon=-79.87, attrs={"category": "apartments"})
    _add(
        conn,
        31,
        lat=43.25,
        lon=-79.87,
        attrs={"category": "apartments", "location": "hamilton"},
    )
    df, _ = load_training(conn)
    ids = set(df["listing_id"])
    assert 31 in ids and 30 not in ids
    assert df.loc[df["listing_id"] == 31, "city"].iloc[0] == "hamilton"
    assert not df["is_archive"].any()


def _add_archive(
    conn,
    source_id,
    *,
    category="apartments",
    title="2 bed apartment",
    price=1200.0,
    first_seen="2014-07-11T00:00:00Z",
    last_seen="2014-08-11T00:00:00Z",
    attributes='{"numberbedrooms": ["2"]}',
    in_live=0,
    neighbourhood=None,
):
    conn.execute(
        "INSERT INTO archive_listings (source_id, category, title, first_seen, last_seen,"
        " sightings, last_price, attributes, in_live, neighbourhood)"
        " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (
            source_id,
            category,
            title,
            first_seen,
            last_seen,
            price,
            attributes,
            in_live,
            neighbourhood,
        ),
    )


def test_archive_rows_are_ignored_by_default(tmp_path):
    conn = connect(tmp_path / "arc0.db")
    migrate(conn)
    _add(conn, 1)
    _add_archive(conn, "900001")
    df, report = load_training(conn)
    assert len(df) == 1 and report.archive_in == 0


def test_archive_rows_join_training_with_listing_year(tmp_path):
    conn = connect(tmp_path / "arc.db")
    migrate(conn)
    _add(conn, 1)  # one live row, kept
    _add_archive(conn, "900001", neighbourhood="N2L")
    _add_archive(conn, "900002", in_live=1)  # the live sweep has this ad: excluded
    _add_archive(conn, "900003", price=None)  # no price: excluded
    _add_archive(
        conn,
        "900004",
        category="rooms",
        title="Room for rent near campus",
        price=550.0,
        attributes="{}",
        first_seen="2017-03-01T00:00:00Z",
        last_seen="2017-04-01T00:00:00Z",
    )
    df, report = load_training(conn, include_archive=True)
    assert report.archive_in == 2 and "archive rows in: 2" in str(report)
    arch = df[df["is_archive"]]
    assert set(arch["dedup_key"]) == {"archive:900001", "archive:900004"}
    assert (arch["listing_id"] < 0).all()  # never a real listings.id
    one = arch[arch["dedup_key"] == "archive:900001"].iloc[0]
    # The stored attribute JSON runs through the live unit extractor: bedrooms 2,
    # so the $1,200 ask becomes $600 per bedroom, with the era kept as a feature.
    assert one["bedrooms"] == 2 and one["price_per_bedroom"] == 600.0
    assert one["listing_year"] == 2014 and one["city"] == "kitchener-waterloo"
    assert one["neighbourhood"] == "N2L"
    room = arch[arch["dedup_key"] == "archive:900004"].iloc[0]
    assert room["unit_type"] == "room" and room["price_per_bedroom"] == 550.0
    live = df[~df["is_archive"]]
    assert list(live["listing_id"]) == [1]
