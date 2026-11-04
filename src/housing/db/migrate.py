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
3 = adds the Wayback backfill tables ``archive_*`` (2026-10-16); 4 = snapshots unique per
(listing_id, scraped_at); archive_listings gains neighbourhood and intersection (2026-11-03).
"""

TABLES = ("listings", "snapshots", "units", "features", "predictions")
"""The five tables of HANDOFF.md section 5, in dependency order."""

AUX_TABLES = ("listing_attributes", "archive_captures", "archive_sightings", "archive_listings")
"""Auxiliary tables outside the contract (see schema.sql)."""


def schema_sql() -> str:
    """Return the contents of ``schema.sql``."""
    return resources.files("housing.db").joinpath("schema.sql").read_text(encoding="utf-8")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply ``schema.sql`` to ``conn`` and record the schema version.

    Safe to run on every start-up: existing tables and rows are left as they are, except
    for the guarded version-4 step, which runs once (duplicate snapshots within one run
    collapse to their first row; ``archive_listings`` gains two columns it may already
    have from ``schema.sql``). The snapshots unique index lives here, not in the contract
    DDL (the 2026-10-04 decision on indexes).

    Returns:
        The schema version now stored in the database.
    """
    prior = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.executescript(schema_sql())
    if prior < 4:
        conn.execute(
            "DELETE FROM snapshots WHERE id NOT IN"
            " (SELECT MIN(id) FROM snapshots GROUP BY listing_id, scraped_at)"
        )
        present = {row[1] for row in conn.execute("PRAGMA table_info(archive_listings)")}
        for column in ("neighbourhood", "intersection"):
            if column not in present:  # fresh databases get them from schema.sql
                conn.execute(f"ALTER TABLE archive_listings ADD COLUMN {column} TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_snapshots_run ON snapshots (listing_id, scraped_at)"
    )
    # PRAGMA statements cannot take bound parameters, hence the f-string.
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION


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
