import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.features.dedup import assign_dedup_keys, dedup_key, main, normalize_address


@pytest.mark.parametrize(
    "raw, expected",
    [
        # unit markers stripped, postal and city/province tails stripped, street words abbreviated
        ("Unit 2 - 123 King Street North, Waterloo, ON N2J 2X8", "123 king st n"),
        ("#4-55 Hickory St W, Waterloo, Ontario, Canada", "55 hickory st w"),
        ("Upper 250 Lester Street, Waterloo", "250 lester st"),
        ("Basement - 12 Marshall St, Kitchener, ON", "12 marshall st"),
        ("bsmt 10 Austin Dr", "10 austin dr"),
        ("44 Chapel St, Kitchener, ON, N2G 2S5", "44 chapel st"),
        # trailing unit markers name a unit inside the building too
        ("250 Lester St Unit 8, Waterloo, ON", "250 lester st"),
        ("12 Marshall St - Apt 3", "12 marshall st"),
        ("55 Hickory St W #4", "55 hickory st w"),
        ("123 King St, Waterloo, Unit 4", "123 king st"),
        # a bare city or postal code identifies nothing
        ("Waterloo, ON", None),
        ("Waterloo, ON N2L 3G1", None),
        ("King Street North, Waterloo", None),  # no street number
        ("", None),
        (None, None),
    ],
)
def test_normalize_address(raw, expected):
    assert normalize_address(raw) == expected


def test_normalize_address_keeps_street_named_after_city():
    # "waterloo" is only stripped as a trailing component, not inside the street
    assert normalize_address("10 Waterloo St S, Kitchener, ON") == "10 waterloo st s"


def test_dedup_key_addr_form():
    key = dedup_key("Unit 2 - 123 King Street North, Waterloo, ON N2J 2X8", None, None, "room", 5)
    assert key == "addr:123 king st n|room|5"
    # the address wins over coordinates, missing unit fields become "?"
    assert dedup_key("123 King St N", 43.0, -80.0, None, None) == "addr:123 king st n|?|?"


def test_dedup_key_geo_fallback_snaps_to_grid():
    base = dedup_key(None, 43.47230, -80.54500, "2bed", 2)
    assert base == "geo:43.4725:-80.5450|2bed|2"
    # ~20 m apart: same 0.0005-degree cell, same key
    assert dedup_key(None, 43.47248, -80.54500, "2bed", 2) == base
    # ~200 m apart: different cell, different key
    assert dedup_key(None, 43.47410, -80.54500, "2bed", 2) != base
    # a bare city falls back to the grid when coordinates exist
    assert dedup_key("Waterloo, ON", 43.47230, -80.54500, "2bed", 2) == base
    # known limitation, pinned on purpose: snapping is rounding, not clustering, so two
    # pins ~7 m apart that straddle a cell line keep different keys (see the docstring)
    assert dedup_key(None, 43.47224, -80.54500, "2bed", 2) != base


def test_dedup_key_none_when_no_location():
    assert dedup_key(None, None, None, "room", 3) is None
    assert dedup_key("Waterloo, ON", None, None, "room", 3) is None
    assert dedup_key(None, 43.47, None, "room", 3) is None


def _add(conn, lid, address=None, lat=None, lon=None, unit_type=None, bedrooms=None):
    conn.execute(
        "INSERT INTO listings (id, source, source_id, address_text, lat, lon, first_seen,"
        " last_seen, status) VALUES (?, 'kijiji', ?, ?, ?, ?, '2026-10-20T00:00:00Z',"
        " '2026-10-22T00:00:00Z', 'active')",
        (lid, str(lid), address, lat, lon),
    )
    if unit_type is not None or bedrooms is not None:
        conn.execute(
            "INSERT INTO units (listing_id, unit_type, bedrooms) VALUES (?, ?, ?)",
            (lid, unit_type, bedrooms),
        )


def _make_db(path):
    conn = connect(path)
    migrate(conn)
    _add(conn, 1, address="250 Lester Street, Waterloo, ON", unit_type="room", bedrooms=5)
    _add(
        conn,
        2,
        address="Unit 8 - 250 Lester St, Waterloo, ON N2L 3W2",
        unit_type="room",
        bedrooms=5,
    )
    _add(conn, 3, address="44 Chapel St, Kitchener, ON", unit_type="2bed", bedrooms=2)
    _add(conn, 4, lat=43.47230, lon=-80.54500, unit_type="1bed", bedrooms=1)
    _add(conn, 5)  # no address, no coordinates: no key
    conn.commit()
    return conn


def test_assign_dedup_keys_sets_shares_and_is_idempotent(tmp_path):
    conn = _make_db(tmp_path / "t.db")
    assert assign_dedup_keys(conn) == 4  # listing 5 stays NULL, so it does not count
    keys = dict(conn.execute("SELECT id, dedup_key FROM listings"))
    assert keys[1] == keys[2] == "addr:250 lester st|room|5"  # two ads, one unit
    assert keys[3] == "addr:44 chapel st|2bed|2"
    assert keys[4] == "geo:43.4725:-80.5450|1bed|1"
    assert keys[5] is None
    assert assign_dedup_keys(conn) == 0  # idempotent


def test_assign_dedup_keys_cli(tmp_path, capsys):
    db = tmp_path / "cli.db"
    _make_db(db).close()
    assert main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "4 set or changed" in out
    assert "1 keys shared by 2+ listings" in out
