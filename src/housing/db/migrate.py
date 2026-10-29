"""Create or update the database schema.

Run ``uv run python -m housing.db.migrate`` to create ``data/housing.db``.

``schema.sql`` (next to this file) only uses ``CREATE TABLE IF NOT EXISTS``, so
applying it to an existing database leaves it untouched. The schema version is
kept in SQLite's built-in ``PRAGMA user_version`` instead of a migrations table,
so nothing outside the section 5 contract is created. When the schema changes:
bump ``SCHEMA_VERSION``, and in ``migrate`` add an ``ALTER TABLE`` step that runs
only when the stored version is older.
"""

from __future__ import annotations

import argparse
import sqlite3
from importlib import resources
from pathlib import Path

from housing.db import connect
from housing.paths import db_path

SCHEMA_VERSION = 4
"""Version written to ``PRAGMA user_version`` after ``schema.sql`` is applied.

History: 1 = the five section 5 tables (2026-10-04); 2 = adds ``listing_attributes`` (2026-10-14);
3 = adds the Wayback backfill tables ``archive_*`` (2026-10-16); 4 = archived ad pages:
``archive_captures.kind``, ``archive_listings.description`` and ``archive_units`` (2026-10-28).
"""

TABLES = ("listings", "snapshots", "units", "features", "predictions")
"""The five tables of HANDOFF.md section 5, in dependency order."""

AUX_TABLES = (
    "listing_attributes",
    "archive_captures",
    "archive_sightings",
    "archive_listings",
    "archive_units",
)
"""Auxiliary tables outside the contract (see schema.sql)."""


def schema_sql() -> str:
    """Return the contents of ``schema.sql``."""
    return resources.files("housing.db").joinpath("schema.sql").read_text(encoding="utf-8")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply ``schema.sql`` to ``conn`` and record the schema version.

    Safe to run on every start-up: existing tables and rows are left as they are.

    Returns:
        The schema version now stored in the database.
    """
    conn.executescript(schema_sql())
    _add_missing_columns(conn)
    # PRAGMA statements cannot take bound parameters, hence the f-string.
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION


ADDED_COLUMNS = (
    ("archive_captures", "kind", "TEXT NOT NULL DEFAULT 'index'"),
    ("archive_listings", "description", "TEXT"),
)
"""Columns added to existing tables after they were first created, with their definitions.

``CREATE TABLE IF NOT EXISTS`` leaves an existing table as it is, so a database created
before a column existed gets it here. Each step runs only when the column is missing,
which keeps ``migrate`` safe to call on every start-up.
"""


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, column, definition in ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def main(argv: list[str] | None = None) -> int:
    """Create the database if needed and print its tables with row counts."""
    parser = argparse.ArgumentParser(description="Create or update the housing SQLite database.")
    parser.add_argument(
        "--db", type=Path, default=None, help=f"database file (default: {db_path()})"
    )
    args = parser.parse_args(argv)
    path = args.db if args.db is not None else db_path()

    conn = connect(path)
    version = migrate(conn)
    print(f"{path}  (schema version {version})")
    for table in (*TABLES, *AUX_TABLES):
        (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  {table:12s} {count:>7d} rows")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
