"""Run the unit-field extraction over the database.

    uv run python -m housing.parse.extract          # listings without a units row
    uv run python -m housing.parse.extract --all    # re-extract everything (rules changed)

Reads title, description and the stored attributes of each listing, writes the section 3
fields to ``units`` and the extra text flags to ``listing_attributes`` as ``text_<flag>``.
Flags that no longer fire are removed, so a rule change propagates everywhere.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.db.queries import (
    delete_attributes,
    get_attributes,
    listings_for_extraction,
    replace_attributes,
    upsert_units,
)
from housing.parse.units import extract
from housing.scrape.fetch import utc_now_iso

log = logging.getLogger(__name__)

TEXT_FLAG_PREFIX = "text_"


def category_of(url: str | None, attributes: dict[str, str | None]) -> str:
    """The listing's category: the stored attribute, else the Kijiji URL, else apartments."""
    stored = attributes.get("category")
    if stored in ("apartments", "rooms"):
        return stored
    if url and "/v-room-rental-roommate/" in url:
        return "rooms"
    return "apartments"


def extract_all(
    conn: sqlite3.Connection, *, only_missing: bool, extracted_at: str | None = None
) -> int:
    """Extract unit fields for the selected listings; return how many rows were written."""
    extracted_at = extracted_at or utc_now_iso()
    rows = listings_for_extraction(conn, only_missing=only_missing)
    for row in rows:
        attributes = get_attributes(conn, row["id"])
        fields = extract(
            category=category_of(row["url"], attributes),
            title=row["title"] or "",
            description=row["description"],
            attributes={k: v for k, v in attributes.items() if v is not None},
            address=row["address_text"],
        )
        upsert_units(conn, row["id"], fields, extracted_at)
        delete_attributes(conn, row["id"], prefix=TEXT_FLAG_PREFIX)
        if fields.flags:
            replace_attributes(
                conn, row["id"], {f"{TEXT_FLAG_PREFIX}{k}": v for k, v in fields.flags.items()}
            )
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Extract unit fields into the units table.")
    parser.add_argument("--all", action="store_true", help="re-extract every listing")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = connect(args.db)
    migrate(conn)
    n = extract_all(conn, only_missing=not args.all)
    summary = conn.execute(
        "SELECT COUNT(*), SUM(unit_type IS NOT NULL), SUM(bedrooms IS NOT NULL),"
        " SUM(move_in_month IS NOT NULL), SUM(lease_term != 'unknown') FROM units"
    ).fetchone()
    print(
        f"extracted {n}; units rows {summary[0]}: unit_type {summary[1]}, bedrooms {summary[2]},"
        f" move_in_month {summary[3]}, lease_term known {summary[4]}"
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
