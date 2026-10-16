import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.features.build import (
    build_features,
    days_on_market,
    neighbourhood_from_address,
    price_per_bedroom,
)
from housing.geo.distances import LAURIER, UW, haversine_m, walk_uw_min
from housing.geo.ion_stops import ION_STOPS, nearest_ion_stop


def test_haversine_uw_to_laurier_is_about_1_4_km():
    assert 1350 < haversine_m(*UW, *LAURIER) < 1450
    assert haversine_m(*UW, *UW) == 0


def test_walk_minutes_at_80_m_per_min():
    assert walk_uw_min(*UW) == 0
    assert 17 < walk_uw_min(*LAURIER) < 18.5


def test_nearest_ion_stop():
    assert len(ION_STOPS) == 19
    name, distance = nearest_ion_stop(*UW)
    assert name == "University of Waterloo" and distance < 400
    assert nearest_ion_stop(43.4516, -80.4922)[0] == "Kitchener City Hall"


@pytest.mark.parametrize(
    "address, fsa",
    [
        ("44 Chapel, Kitchener, ON, N2G 2S5", "N2G"),
        ("Waterloo, ON N2L3G1", "N2L"),
        ("423 Tamarack Dr, Waterloo, ON n2l 4g9", "N2L"),
        ("Waterloo, ON", None),
        (None, None),
    ],
)
def test_neighbourhood_from_address(address, fsa):
    assert neighbourhood_from_address(address) == fsa


def test_price_per_bedroom_rules():
    assert price_per_bedroom(650, "room", 5) == 650
    assert price_per_bedroom(2400, "house", 3) == 800
    assert price_per_bedroom(1500, "studio", 1) == 1500
    assert price_per_bedroom(1500, "2bed", None) is None
    assert price_per_bedroom(None, "room", 5) is None
    assert price_per_bedroom(0, "room", 5) is None


def test_days_on_market():
    assert days_on_market("2026-10-05", "2026-10-14T20:00:00Z") == 9
    assert days_on_market("2026-10-20", "2026-10-14T20:00:00Z") == 0
    assert days_on_market(None, "2026-10-14T20:00:00Z") is None
    assert days_on_market("bad", "2026-10-14") is None


def test_build_features_uses_latest_price_and_units(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO listings (id, source, source_id, address_text, lat, lon, posted_at, first_seen,"
        " last_seen, status) VALUES (1, 'kijiji', '1', '44 Chapel, Kitchener, ON, N2G 2S5', 43.45265,"
        " -80.47965, '2026-10-05', '2026-10-14T00:00:00Z', '2026-10-15T00:00:00Z', 'active')"
    )
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (1, '2026-10-14T00:00:00Z', 1600)"
    )
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (1, '2026-10-15T00:00:00Z', 1500)"
    )
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (1, '2026-10-16T00:00:00Z', NULL)"
    )
    conn.execute("INSERT INTO units (listing_id, unit_type, bedrooms) VALUES (1, '2bed', 2)")
    conn.execute(
        "INSERT INTO listings (id, source, source_id, first_seen, last_seen, status)"
        " VALUES (2, 'kijiji', '2', '2026-10-14T00:00:00Z', '2026-10-14T00:00:00Z', 'active')"
    )
    conn.commit()

    assert build_features(conn, built_at="2026-10-16T00:00:00Z") == 2
    row = conn.execute("SELECT * FROM features WHERE listing_id = 1").fetchone()
    assert row["price_per_bedroom"] == 750 and row["neighbourhood"] == "N2G"
    assert row["days_on_market"] == 10 and row["built_at"] == "2026-10-16T00:00:00Z"
    assert 50 < row["walk_uw_min"] < 90 and row["ion_distance_m"] < 2000
    empty = conn.execute("SELECT * FROM features WHERE listing_id = 2").fetchone()
    assert empty["price_per_bedroom"] is None and empty["walk_uw_min"] is None
    assert build_features(conn) == 2  # rebuild is idempotent
    conn.close()
