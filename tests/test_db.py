"""Tests for the database schema and migration (HANDOFF.md section 5)."""

import sqlite3

import pytest

from housing.db import connect
from housing.db.migrate import AUX_TABLES, SCHEMA_VERSION, TABLES, main, migrate

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


def test_creates_exactly_the_contract_and_auxiliary_tables(conn):
    assert table_names(conn) == sorted((*TABLES, *AUX_TABLES))
    assert AUX_TABLES == (
        "listing_attributes",
        "archive_captures",
        "archive_sightings",
        "archive_listings",
        "archive_units",
    )


def test_listing_attributes_columns(conn):
    info = conn.execute("PRAGMA table_info(listing_attributes)").fetchall()
    assert [(row["name"], row["type"]) for row in info] == [
        ("listing_id", "INTEGER"),
        ("name", "TEXT"),
        ("value", "TEXT"),
    ]
    assert primary_key(conn, "listing_attributes") == ["listing_id", "name"]


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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 5
    assert table_names(conn) == sorted((*TABLES, *AUX_TABLES))
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1


def test_migrate_v4_dedupes_snapshots_and_makes_insert_snapshot_an_upsert(tmp_path):
    from housing.db.migrate import schema_sql
    from housing.db.queries import insert_snapshot

    # A hand-built version 3 database: the tables exist but not the unique index, so one
    # listing can carry duplicate (listing_id, scraped_at) snapshots.
    conn = connect(tmp_path / "v3.db")
    conn.executescript(schema_sql())
    conn.execute("PRAGMA user_version = 3")
    lid = insert_listing(conn)
    for price in (800.0, 900.0):
        conn.execute(
            "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (?, ?, ?)",
            (lid, NOW, price),
        )
    conn.commit()

    assert migrate(conn) == SCHEMA_VERSION
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    rows = conn.execute("SELECT id, price FROM snapshots").fetchall()
    assert len(rows) == 1 and rows[0]["price"] == 800.0  # the first row of each pair wins
    # A re-sighting at the same scraped_at now updates in place instead of raising.
    assert insert_snapshot(conn, lid, NOW, 950.0, "raw/p1") == rows[0]["id"]
    assert [tuple(r) for r in conn.execute("SELECT price, raw_path FROM snapshots")] == [
        (950.0, "raw/p1")
    ]
    conn.close()


def test_migrate_v4_adds_the_archive_columns_only_when_missing(tmp_path):
    # An old archive_listings without the two columns gets them from the guarded ALTER...
    conn = connect(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE archive_listings (source_id TEXT PRIMARY KEY,"
        " first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)"
    )
    conn.execute("PRAGMA user_version = 3")
    migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(archive_listings)")}
    assert {"neighbourhood", "intersection"} <= columns
    conn.close()
    # ...and a fresh database, which has them from schema.sql, migrates cleanly too.
    fresh = connect(tmp_path / "fresh.db")
    migrate(fresh)
    columns = {row["name"] for row in fresh.execute("PRAGMA table_info(archive_listings)")}
    assert {"neighbourhood", "intersection"} <= columns
    fresh.close()


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


def test_connect_waits_a_minute_for_a_locked_database(tmp_path):
    connection = connect(tmp_path / "t.db")
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 60000
    connection.close()
