"""Tests for the database schema and migration (HANDOFF.md section 5)."""

import sqlite3

import pytest

from housing.db import connect
from housing.db.migrate import SCHEMA_VERSION, TABLES, main, migrate

# Column names and declared types, copied from HANDOFF.md section 5. If this
# fails, either schema.sql drifted from the contract or the contract changed
# and needs Caden's sign-off plus a line in docs/decisions.md.
EXPECTED_COLUMNS = {
    "listings": [
        ("id", "INTEGER"),
        ("source", "TEXT"),
        ("source_id", "TEXT"),
        ("url", "TEXT"),
        ("title", "TEXT"),
        ("description", "TEXT"),
        ("address_text", "TEXT"),
        ("lat", "REAL"),
        ("lon", "REAL"),
        ("posted_at", "TEXT"),
        ("first_seen", "TEXT"),
        ("last_seen", "TEXT"),
        ("status", "TEXT"),
        ("dedup_key", "TEXT"),
    ],
    "snapshots": [
        ("id", "INTEGER"),
        ("listing_id", "INTEGER"),
        ("scraped_at", "TEXT"),
        ("price", "REAL"),
        ("raw_path", "TEXT"),
    ],
    "units": [
        ("listing_id", "INTEGER"),
        ("unit_type", "TEXT"),
        ("bedrooms", "INTEGER"),
        ("bathrooms", "REAL"),
        ("lease_term", "TEXT"),
        ("move_in_month", "INTEGER"),
        ("utilities_included", "INTEGER"),
        ("furnished", "INTEGER"),
        ("laundry_in_unit", "INTEGER"),
        ("building_type", "TEXT"),
        ("year_built_after_2018", "INTEGER"),
        ("extracted_by", "TEXT"),
        ("extracted_at", "TEXT"),
    ],
    "features": [
        ("listing_id", "INTEGER"),
        ("price_per_bedroom", "REAL"),
        ("walk_uw_min", "REAL"),
        ("walk_laurier_min", "REAL"),
        ("ion_distance_m", "REAL"),
        ("neighbourhood", "TEXT"),
        ("days_on_market", "INTEGER"),
        ("built_at", "TEXT"),
    ],
    "predictions": [
        ("listing_id", "INTEGER"),
        ("model_version", "TEXT"),
        ("expected", "REAL"),
        ("q10", "REAL"),
        ("q90", "REAL"),
        ("percentile", "REAL"),
        ("scored_at", "TEXT"),
    ],
}

NOW = "2026-10-05T00:00:00Z"


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    migrate(connection)
    yield connection
    connection.close()


def table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return sorted(row["name"] for row in rows)


def primary_key(conn, table):
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # table_info.pk is the 1-based position in the primary key, 0 if not part of it.
    return [row["name"] for row in sorted(info, key=lambda r: r["pk"]) if row["pk"]]


def insert_listing(conn, source_id="123"):
    cursor = conn.execute(
        "INSERT INTO listings (source, source_id, first_seen, last_seen, status)"
        " VALUES (?, ?, ?, ?, ?)",
        ("kijiji", source_id, NOW, NOW, "active"),
    )
    return cursor.lastrowid


def test_creates_exactly_the_contract_tables(conn):
    assert table_names(conn) == sorted(TABLES)


@pytest.mark.parametrize("table", TABLES)
def test_columns_match_handoff_section_5(conn, table):
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    assert [(row["name"], row["type"]) for row in info] == EXPECTED_COLUMNS[table]


def test_primary_keys(conn):
    assert primary_key(conn, "listings") == ["id"]
    assert primary_key(conn, "snapshots") == ["id"]
    assert primary_key(conn, "units") == ["listing_id"]
    assert primary_key(conn, "features") == ["listing_id"]
    assert primary_key(conn, "predictions") == ["listing_id", "model_version"]


def test_migrate_is_idempotent_and_records_version(conn):
    insert_listing(conn)
    assert migrate(conn) == SCHEMA_VERSION
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert table_names(conn) == sorted(TABLES)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1


def test_same_ad_cannot_be_inserted_twice(conn):
    insert_listing(conn, "123")
    with pytest.raises(sqlite3.IntegrityError):
        insert_listing(conn, "123")


def test_required_listing_columns_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO listings (source, source_id) VALUES ('kijiji', '1')")


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (?, ?, ?)",
            (999, NOW, 800.0),
        )
    listing_id = insert_listing(conn)
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (?, ?, ?)",
        (listing_id, NOW, 800.0),
    )
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_connect_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "housing.db"
    connect(path).close()
    assert path.exists()


def test_connect_default_path_honours_env(tmp_path, monkeypatch):
    path = tmp_path / "env.db"
    monkeypatch.setenv("HOUSING_DB_PATH", str(path))
    connect().close()
    assert path.exists()


def test_cli_creates_database_and_lists_tables(tmp_path, capsys):
    path = tmp_path / "cli.db"
    assert main(["--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert path.exists()
    assert str(path) in out
    for table in TABLES:
        assert table in out
