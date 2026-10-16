"""Read and write helpers for the contract tables (HANDOFF section 5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping

from housing.db.migrate import TABLES
from housing.parse.pii import redact_url, strip_contact_info
from housing.parse.units import UnitFields

_UPSERT_LISTING = """
INSERT INTO listings (source, source_id, url, title, address_text, lat, lon, posted_at,
                      first_seen, last_seen, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
ON CONFLICT(source, source_id) DO UPDATE SET
    url = COALESCE(excluded.url, listings.url),
    title = COALESCE(excluded.title, listings.title),
    address_text = COALESCE(excluded.address_text, listings.address_text),
    lat = COALESCE(excluded.lat, listings.lat),
    lon = COALESCE(excluded.lon, listings.lon),
    posted_at = COALESCE(listings.posted_at, excluded.posted_at),
    last_seen = excluded.last_seen,
    status = 'active'
RETURNING id
"""


def upsert_listing(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_id: str,
    seen_at: str,
    url: str | None = None,
    title: str | None = None,
    address_text: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    posted_at: str | None = None,
) -> tuple[int, bool]:
    """Insert a listing, or refresh one seen again, and return ``(listing id, created)``.

    A listing is identified by ``(source, source_id)``. On a repeat sighting ``last_seen``
    moves forward, the status returns to active, null values never overwrite known ones,
    and ``posted_at`` keeps its first value.
    """
    existing = conn.execute(
        "SELECT id FROM listings WHERE source = ? AND source_id = ?", (source, source_id)
    ).fetchone()
    row = conn.execute(
        _UPSERT_LISTING,
        (source, source_id, url, title, address_text, lat, lon, posted_at, seen_at, seen_at),
    ).fetchone()
    return int(row[0]), existing is None


def insert_snapshot(
    conn: sqlite3.Connection,
    listing_id: int,
    scraped_at: str,
    price: float | None,
    raw_path: str | None,
) -> int:
    """Record one sighting of a listing and return the snapshot id."""
    cursor = conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price, raw_path) VALUES (?, ?, ?, ?)",
        (listing_id, scraped_at, price, raw_path),
    )
    return int(cursor.lastrowid)


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return the row count of every contract table."""
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
        for table in TABLES
    }


def count_listings(conn: sqlite3.Connection, status: str | None = None) -> int:
    """Return the number of listings, optionally only those with ``status``."""
    if status is None:
        return int(conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
    return int(
        conn.execute("SELECT COUNT(*) FROM listings WHERE status = ?", (status,)).fetchone()[0]
    )


def replace_attributes(
    conn: sqlite3.Connection, listing_id: int, attributes: Mapping[str, str | None]
) -> None:
    """Upsert ``listing_attributes`` rows; names not given are left as they are."""
    conn.executemany(
        "INSERT INTO listing_attributes (listing_id, name, value) VALUES (?, ?, ?)"
        " ON CONFLICT(listing_id, name) DO UPDATE SET value = excluded.value",
        [(listing_id, name, value) for name, value in attributes.items()],
    )


def delete_attributes(
    conn: sqlite3.Connection,
    listing_id: int,
    *,
    names: Iterable[str] = (),
    prefix: str | None = None,
) -> None:
    """Delete a listing's attributes by name, or every name starting with ``prefix``."""
    for name in names:
        conn.execute(
            "DELETE FROM listing_attributes WHERE listing_id = ? AND name = ?", (listing_id, name)
        )
    if prefix is not None:
        conn.execute(
            "DELETE FROM listing_attributes WHERE listing_id = ? AND substr(name, 1, ?) = ?",
            (listing_id, len(prefix), prefix),
        )


def get_attributes(conn: sqlite3.Connection, listing_id: int) -> dict[str, str | None]:
    """Return a listing's attributes as a name to value dict."""
    rows = conn.execute(
        "SELECT name, value FROM listing_attributes WHERE listing_id = ?", (listing_id,)
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def set_detail(
    conn: sqlite3.Connection,
    listing_id: int,
    *,
    description: str | None,
    address_text: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    posted_at: str | None = None,
) -> None:
    """Store detail-page fields.

    Address, coordinates and the posting date only fill gaps: the index card's values are kept.
    """
    conn.execute(
        "UPDATE listings SET description = ?, address_text = COALESCE(address_text, ?),"
        " lat = COALESCE(lat, ?), lon = COALESCE(lon, ?), posted_at = COALESCE(posted_at, ?)"
        " WHERE id = ?",
        (description, address_text, lat, lon, posted_at, listing_id),
    )


def pending_details(
    conn: sqlite3.Connection, source: str, limit: int, *, retry_failed_before: str = ""
) -> list[sqlite3.Row]:
    """Active listings whose detail page has not been fetched, rooms first, newest first.

    A listing counts as fetched once it has a ``detail_fetched_at`` attribute. One whose
    fetch failed (``detail_failed_at``) is retried only when that timestamp is older than
    ``retry_failed_before``; the default retries nothing.
    """
    return conn.execute(
        "SELECT l.id, l.source_id, l.url FROM listings l"
        " LEFT JOIN listing_attributes d ON d.listing_id = l.id AND d.name = 'detail_fetched_at'"
        " LEFT JOIN listing_attributes f ON f.listing_id = l.id AND f.name = 'detail_failed_at'"
        " WHERE l.source = ? AND l.status = 'active' AND l.url IS NOT NULL"
        " AND d.value IS NULL AND (f.value IS NULL OR f.value < ?)"
        " ORDER BY (l.url LIKE '%/v-room-rental-roommate/%') DESC, l.first_seen DESC, l.id"
        " LIMIT ?",
        (source, retry_failed_before, limit),
    ).fetchall()


def mark_gone(conn: sqlite3.Connection, source: str, not_seen_since: str) -> int:
    """Mark active listings last seen before ``not_seen_since`` as gone; return how many."""
    cursor = conn.execute(
        "UPDATE listings SET status = 'gone'"
        " WHERE source = ? AND status = 'active' AND last_seen < ?",
        (source, not_seen_since),
    )
    return cursor.rowcount


def restrip_listings(conn: sqlite3.Connection) -> int:
    """Re-apply the contact-info rules to every stored title, description and URL.

    Run after the rules in ``housing.parse.pii`` get stricter; returns how many listings
    changed. Already-redacted markers stay as they are.
    """
    changed = 0
    for row in conn.execute("SELECT id, url, title, description FROM listings").fetchall():
        clean = (
            redact_url(row["url"]),
            strip_contact_info(row["title"]),
            strip_contact_info(row["description"]),
        )
        if clean != (row["url"], row["title"], row["description"]):
            conn.execute(
                "UPDATE listings SET url = ?, title = ?, description = ? WHERE id = ?",
                (*clean, row["id"]),
            )
            changed += 1
    conn.commit()
    return changed


_UPSERT_UNITS = """
INSERT INTO units (listing_id, unit_type, bedrooms, bathrooms, lease_term, move_in_month,
                   utilities_included, furnished, laundry_in_unit, building_type,
                   year_built_after_2018, extracted_by, extracted_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(listing_id) DO UPDATE SET
    unit_type = excluded.unit_type, bedrooms = excluded.bedrooms, bathrooms = excluded.bathrooms,
    lease_term = excluded.lease_term, move_in_month = excluded.move_in_month,
    utilities_included = excluded.utilities_included, furnished = excluded.furnished,
    laundry_in_unit = excluded.laundry_in_unit, building_type = excluded.building_type,
    year_built_after_2018 = excluded.year_built_after_2018, extracted_by = excluded.extracted_by,
    extracted_at = excluded.extracted_at
"""


def _as_int(value: bool | None) -> int | None:
    return None if value is None else int(value)


def upsert_units(
    conn: sqlite3.Connection, listing_id: int, fields: UnitFields, extracted_at: str
) -> None:
    """Write (or rewrite) a listing's ``units`` row from extracted fields."""
    conn.execute(
        _UPSERT_UNITS,
        (
            listing_id,
            fields.unit_type,
            fields.bedrooms,
            fields.bathrooms,
            fields.lease_term,
            fields.move_in_month,
            _as_int(fields.utilities_included),
            _as_int(fields.furnished),
            _as_int(fields.laundry_in_unit),
            fields.building_type,
            _as_int(fields.year_built_after_2018),
            fields.extracted_by,
            extracted_at,
        ),
    )


def listings_for_extraction(conn: sqlite3.Connection, *, only_missing: bool) -> list[sqlite3.Row]:
    """Listings to run the unit extraction on: all, or only those without a ``units`` row."""
    return conn.execute(
        "SELECT l.id, l.url, l.title, l.description, l.address_text FROM listings l"
        " LEFT JOIN units u ON u.listing_id = l.id"
        " WHERE ? = 0 OR u.listing_id IS NULL ORDER BY l.id",
        (int(only_missing),),
    ).fetchall()
