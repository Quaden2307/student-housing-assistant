"""SQLite access for the housing database (HANDOFF.md section 5).

Typical use::

    from housing.db import connect
    from housing.db.migrate import migrate

    conn = connect()   # data/housing.db, created if missing
    migrate(conn)      # apply schema.sql; safe to call on every start-up
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from housing.paths import db_path


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the housing database and return a connection.

    Args:
        path: Database file. Defaults to ``housing.paths.db_path()``, which is
            ``data/housing.db`` unless ``HOUSING_DB_PATH`` is set. Missing
            parent directories are created.

    Returns:
        A connection with foreign keys enforced, WAL journaling, and
        ``sqlite3.Row`` rows, so columns can be read by name.
    """
    resolved = Path(path) if path is not None else db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    # SQLite ignores REFERENCES clauses unless this is turned on, per connection.
    conn.execute("PRAGMA foreign_keys = ON")
    # Two writers can overlap (the daily sweep and the Wayback backfill share the file).
    # The features rebuild holds the write lock for a few seconds, which overflowed the
    # 5-second default on 2026-10-23; wait up to a minute instead of crashing.
    conn.execute("PRAGMA busy_timeout = 60000")
    # WAL lets a notebook read while the scraper writes without "database is locked".
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn
