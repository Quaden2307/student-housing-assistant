"""Dedup keys: one key per physical unit, however many ads point at it.

Landlords repost constantly under new ad ids and the same unit shows up on
several sites, so raw ads overcount popular houses. ``listings.dedup_key``
(HANDOFF section 5) is **normalized address + unit_type + bedrooms**; when the
address cannot be normalized, coordinates snapped to a coarse grid stand in
(docs/pipeline.md section 5). Downstream, the clean table keeps one row per key
and cross-validation groups by it, so a model never sees the same house in both
train and test.

Run ``uv run python -m housing.features.dedup`` to fill ``listings.dedup_key``.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.parse.units import normalise_address

GRID_DEG = 0.0005
"""Grid step, in degrees, for the coordinate fallback of :func:`dedup_key`.

0.0005 degrees is about 55 m of latitude and about 40 m of longitude at
Waterloo's 43.5 N -- roughly one building's footprint, the "coordinates rounded
to about 50 m" of docs/pipeline.md section 5. Coarser would merge neighbouring
houses into one key; finer would split one house across keys on Kijiji's own
pin jitter.
"""

# A leading unit marker names a unit inside the building; the key must name the
# building itself, so "Unit 2 - 123 King St N" and "#4-123 King St N" both
# normalize to "123 king st n". The \b stops "united" or "lowery" matching.
_UNIT_MARKER_RE = re.compile(
    r"^(?:(?:unit|apt|apartment|suite)\b\s*#?\s*\w+|#\s*\w+|(?:upper|lower|bsmt|basement)\b)"
    r"\s*[-,:]*\s*"
)
# Unit markers also trail the street address ("250 Lester St Unit 8",
# "12 Marshall St - Apt 3"); docs/pipeline.md section 5 strips unit numbers
# wherever they sit. Applied after the city/province tail is trimmed.
_TRAILING_UNIT_RE = re.compile(r"[\s,.:-]*(?:\b(?:unit|apt|apartment|suite)\b\s*#?\s*\w+|#\s*\w+)$")
# Canadian postal code, with or without the inner space ("N2L 3G1", "n2l3g1").
_POSTAL_RE = re.compile(r"\b[a-z]\d[a-z]\s?\d[a-z]\d\b")
# Trailing city / province / country components say nothing about the building.
_TAIL_RE = re.compile(r"[\s,.-]*\b(?:canada|ontario|ont|on|kitchener|waterloo)\b[\s,.-]*$")
_EDGE_SEPARATORS_RE = re.compile(r"^[\s,.-]+|[\s,.-]+$")


def normalize_address(address_text: str | None) -> str | None:
    """Normalize an address so the same building always yields the same string.

    Lowercases and abbreviates street words (via
    :func:`housing.parse.units.normalise_address`), strips a leading unit marker
    ("Unit 2 -", "#4-", "upper", "bsmt", "basement -"), a trailing one
    ("... Unit 8", "... - Apt 3", "... #4"), the postal code, "Canada" and a
    trailing city or province, and collapses whitespace.

    Args:
        address_text: The address as scraped, or None.

    Returns:
        The normalized street address, e.g. ``"123 king st n"``, or None when
        nothing is left or there is no street number: a bare "Waterloo, ON"
        identifies nothing and must not become a shared key.
    """
    if not address_text:
        return None
    text = normalise_address(address_text)
    text = _POSTAL_RE.sub(" ", text)
    for _ in range(3):  # "upper unit 2 - ..." stacks two markers
        stripped = _UNIT_MARKER_RE.sub("", text.strip())
        if stripped == text.strip():
            break
        text = stripped
    while True:
        # Alternate the two tail rules until stable: "123 King St Unit 4, Waterloo"
        # needs the city gone before the unit marker is trailing, and vice versa.
        trimmed = _TRAILING_UNIT_RE.sub("", _TAIL_RE.sub("", text))
        if trimmed == text:
            break
        text = trimmed
    text = _EDGE_SEPARATORS_RE.sub("", re.sub(r"\s+", " ", text))
    if not text or not re.search(r"\d", text):
        return None
    return text


def dedup_key(
    address_text: str | None,
    lat: float | None,
    lon: float | None,
    unit_type: str | None,
    bedrooms: int | None,
) -> str | None:
    """Build the dedup key for one listing (HANDOFF section 5).

    Args:
        address_text: The listing's address text, if any.
        lat: Latitude, used only when the address does not normalize.
        lon: Longitude, used with ``lat``.
        unit_type: Section 3 unit type; missing becomes ``"?"``.
        bedrooms: Bedroom count; missing becomes ``"?"``.

    Returns:
        ``"addr:<normalized>|<unit_type>|<bedrooms>"`` when the address
        normalizes; else ``"geo:<lat>:<lon>|..."`` with both coordinates
        snapped to the :data:`GRID_DEG` grid (about 50 m); else None when there
        is no location at all. Snapping is rounding, not clustering
        (docs/pipeline.md section 5): two pins in the same cell share a key,
        but pins a few metres apart that straddle a cell line do not, so an
        address-less unit with pin jitter can keep two keys. Acceptable for
        now; HANDOFF section 5 names image hashing as the later tightening.
    """
    tail = f"|{unit_type or '?'}|{bedrooms if bedrooms is not None else '?'}"
    address = normalize_address(address_text)
    if address:
        return f"addr:{address}{tail}"
    if lat is not None and lon is not None:
        # Multiples of 0.0005 are exact at four decimals, so the format is stable.
        snapped_lat = round(lat / GRID_DEG) * GRID_DEG
        snapped_lon = round(lon / GRID_DEG) * GRID_DEG
        return f"geo:{snapped_lat:.4f}:{snapped_lon:.4f}{tail}"
    return None


def assign_dedup_keys(conn: sqlite3.Connection) -> int:
    """Set ``listings.dedup_key`` for every listing from its address and unit.

    Recomputes the key from ``listings`` (address, coordinates) joined to the
    listing's ``units`` row, and writes it only where it differs, so the call
    is idempotent and a second run changes nothing.

    Args:
        conn: Open database connection.

    Returns:
        How many rows changed.
    """
    rows = conn.execute(
        "SELECT l.id, l.address_text, l.lat, l.lon, l.dedup_key, u.unit_type, u.bedrooms"
        " FROM listings l LEFT JOIN units u ON u.listing_id = l.id"
    ).fetchall()
    updates = [
        (key, listing_id)
        for listing_id, address, lat, lon, current, unit_type, bedrooms in rows
        if (key := dedup_key(address, lat, lon, unit_type, bedrooms)) != current
    ]
    with conn:
        conn.executemany("UPDATE listings SET dedup_key = ? WHERE id = ?", updates)
    return len(updates)


def main(argv: list[str] | None = None) -> int:
    """CLI: fill ``listings.dedup_key`` and report how much the dataset shrinks."""
    parser = argparse.ArgumentParser(description="Assign dedup keys to listings.")
    parser.add_argument("--db", type=Path, default=None, help="database file (default: data/)")
    args = parser.parse_args(argv)
    conn = connect(args.db)
    migrate(conn)
    changed = assign_dedup_keys(conn)
    keyed = conn.execute("SELECT COUNT(*) FROM listings WHERE dedup_key IS NOT NULL").fetchone()[0]
    shared = conn.execute(
        "SELECT COUNT(*) FROM (SELECT dedup_key FROM listings WHERE dedup_key IS NOT NULL"
        " GROUP BY dedup_key HAVING COUNT(*) >= 2)"
    ).fetchone()[0]
    print(
        f"dedup keys: {changed} set or changed, {keyed} listings keyed,"
        f" {shared} keys shared by 2+ listings"
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
