"""Rebuild the ``features`` table from ``listings``, ``units`` and ``snapshots``.

    uv run python -m housing.features.build

Everything here is derived (HANDOFF section 3), so the table is dropped and rebuilt on
every run. The price used is the latest non-null snapshot price for the listing.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from datetime import date
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.geo.distances import walk_laurier_min, walk_uw_min
from housing.geo.ion_stops import nearest_ion_stop
from housing.scrape.fetch import utc_now_iso

log = logging.getLogger(__name__)

FSA_RE = re.compile(r"\b([A-Za-z]\d[A-Za-z])\s?\d[A-Za-z]\d\b")

_LATEST_PRICES = """
SELECT listing_id, price FROM (
    SELECT listing_id, price,
           ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY scraped_at DESC, id DESC) AS rn
    FROM snapshots WHERE price IS NOT NULL
) WHERE rn = 1
"""

_ROWS = """
SELECT l.id, l.lat, l.lon, l.address_text, l.posted_at, l.last_seen, u.unit_type, u.bedrooms
FROM listings l LEFT JOIN units u ON u.listing_id = l.id
"""


def neighbourhood_from_address(address: str | None) -> str | None:
    """Return the postal prefix (forward sortation area, e.g. ``N2L``) found in an address."""
    if not address:
        return None
    match = FSA_RE.search(address)
    return match.group(1).upper() if match else None


def price_per_bedroom(
    price: float | None, unit_type: str | None, bedrooms: int | None
) -> float | None:
    """The model target: the asking price for a room, else price divided by bedrooms."""
    if price is None or price <= 0:
        return None
    if unit_type == "room":
        return float(price)
    if bedrooms is None or bedrooms < 1:
        return None
    return float(price) / bedrooms


def days_on_market(posted_at: str | None, last_seen: str | None) -> int | None:
    """Days between the listing's posting date and the last time we saw it."""
    if not posted_at or not last_seen:
        return None
    try:
        posted = date.fromisoformat(posted_at[:10])
        seen = date.fromisoformat(last_seen[:10])
    except ValueError:
        return None
    return max((seen - posted).days, 0)


def build_features(conn: sqlite3.Connection, built_at: str | None = None) -> int:
    """Drop and rebuild every row of ``features``; return the number of rows written."""
    built_at = built_at or utc_now_iso()
    prices = dict(conn.execute(_LATEST_PRICES).fetchall())
    rows = []
    for lid, lat, lon, address, posted_at, last_seen, unit_type, bedrooms in conn.execute(_ROWS):
        has_point = lat is not None and lon is not None
        ion = nearest_ion_stop(lat, lon)[1] if has_point else None
        rows.append(
            (
                lid,
                price_per_bedroom(prices.get(lid), unit_type, bedrooms),
                walk_uw_min(lat, lon) if has_point else None,
                walk_laurier_min(lat, lon) if has_point else None,
                ion,
                neighbourhood_from_address(address),
                days_on_market(posted_at, last_seen),
                built_at,
            )
        )
    with conn:
        conn.execute("DELETE FROM features")
        conn.executemany(
            "INSERT INTO features (listing_id, price_per_bedroom, walk_uw_min, walk_laurier_min,"
            " ion_distance_m, neighbourhood, days_on_market, built_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Rebuild the derived features table.")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = connect(args.db)
    migrate(conn)
    n = build_features(conn)
    with_price = conn.execute(
        "SELECT COUNT(*) FROM features WHERE price_per_bedroom IS NOT NULL"
    ).fetchone()[0]
    print(f"features rebuilt: {n} rows, {with_price} with price_per_bedroom")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
