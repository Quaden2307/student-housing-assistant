"""Rewrite ``docs/field_audit.md`` from the database: field coverage per category.

    uv run python scripts/field_audit.py

Counts how many listings end up with a value for every HANDOFF section 3 field (after the
extraction rules), for the listing-level fields, and for the raw Kijiji attributes, split by
category. Run it after a sweep or after changing the rules in ``housing.parse.units``.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from housing.db import connect
from housing.paths import REPO_ROOT

UNIT_FIELDS = {
    "unit_type": "attribute `unittype` and bedrooms; the category for rooms; text rules for per-room ads",
    "bedrooms": "attribute `numberbedrooms`; rooms only from text (the house total is often not stated)",
    "bathrooms": "attribute `numberbathrooms` (times 10); rooms from text",
    "lease_term": "text (sublet, 8-month, month ranges by span) first, then `agreementtype`; `Not Available` is common",
    "move_in_month": "attribute `dateavailable`, then text near availability wording; never imputed",
    "utilities_included": "explicit text first, then attributes `heat`, `hydro`, `water`",
    "furnished": "explicit text first, then attribute `furnished`",
    "laundry_in_unit": "attributes `laundryinunit`, `laundryinbuilding`; rooms from text",
    "building_type": "known-building registry, Kijiji's unit type, explicit wording, house words; `unknown` otherwise",
    "year_built_after_2018": "registry years and wording about the building's age only",
}  # fmt: skip
LISTING_FIELDS = {
    "price (latest snapshot)": "EXISTS (SELECT 1 FROM snapshots s WHERE s.listing_id = l.id AND s.price IS NOT NULL)",
    "lat, lon": "l.lat IS NOT NULL",
    "postal code in address": "f.neighbourhood IS NOT NULL",
    "posted date": "l.posted_at IS NOT NULL",
    "full description (detail fetched)": "l.description IS NOT NULL",
}  # fmt: skip
ATTRIBUTES = [
    "numberbedrooms", "numberbathrooms", "unittype", "agreementtype", "dateavailable", "furnished",
    "heat", "hydro", "water", "internet", "laundryinunit", "laundryinbuilding", "areainfeet",
    "petsallowed", "numberparkingspots", "airconditioning", "forrentbyhousing", "smokingpermitted",
]  # fmt: skip
CATEGORIES = ("apartments", "rooms")
CATEGORY_JOIN = (
    "JOIN listing_attributes c ON c.listing_id = l.id AND c.name = 'category' AND c.value = ?"
)


def pct(part: int, whole: int) -> str:
    """Format ``part`` as a percentage of ``whole``."""
    return f"{100 * part / whole:.0f}%" if whole else "-"


def build(conn) -> str:
    """Return the Markdown for ``docs/field_audit.md``."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    n = {
        c: conn.execute(f"SELECT COUNT(*) FROM listings l {CATEGORY_JOIN}", (c,)).fetchone()[0]
        for c in CATEGORIES
    }
    described = {
        c: conn.execute(
            f"SELECT COUNT(*) FROM listings l {CATEGORY_JOIN} WHERE l.description IS NOT NULL", (c,)
        ).fetchone()[0]
        for c in CATEGORIES
    }
    out = [
        "# Field audit",
        "",
        "Which HANDOFF section 3 fields a Kijiji listing actually carries, and where. This table decides what the",
        "unit schema really is: a field that is rarely present or only in free text costs extraction work and rows.",
        "",
        f"Status: measured {today} over every listing in the database ({n['apartments']:,} apartments, {n['rooms']:,} rooms;",
        f"detail pages fetched for {described['rooms']:,} rooms and {described['apartments']:,} apartments) after the extraction rules",
        "in `housing.parse.units` ran. Counts say how many listings end up with a value in `units`. Regenerate with",
        "`uv run python scripts/field_audit.py` after a sweep or a rule change.",
        "",
        "## Section 3 fields, as extracted",
        "",
        "| Field | Apartments | Rooms | Where it comes from |",
        "|---|---|---|---|",
    ]
    for col, where in UNIT_FIELDS.items():
        cond = (
            f"u.{col} != 'unknown'"
            if col in ("lease_term", "building_type")
            else f"u.{col} IS NOT NULL"
        )
        counts = {
            c: conn.execute(
                f"SELECT COUNT(*) FROM units u JOIN listings l ON l.id = u.listing_id {CATEGORY_JOIN} WHERE {cond}",
                (c,),
            ).fetchone()[0]
            for c in CATEGORIES
        }
        out.append(
            f"| `{col}` | {counts['apartments']:,} ({pct(counts['apartments'], n['apartments'])}) | {counts['rooms']:,} ({pct(counts['rooms'], n['rooms'])}) | {where} |"
        )
    out += ["", "## Listing-level fields", "", "| Field | Apartments | Rooms |", "|---|---|---|"]
    for label, cond in LISTING_FIELDS.items():
        counts = {
            c: conn.execute(
                f"SELECT COUNT(*) FROM listings l LEFT JOIN features f ON f.listing_id = l.id {CATEGORY_JOIN} WHERE {cond}",
                (c,),
            ).fetchone()[0]
            for c in CATEGORIES
        }
        out.append(
            f"| {label} | {counts['apartments']:,} ({pct(counts['apartments'], n['apartments'])}) | {counts['rooms']:,} ({pct(counts['rooms'], n['rooms'])}) |"
        )
    out += [
        "",
        "## Raw Kijiji attributes present (value given and not `Not Available`)",
        "",
        "| Attribute | Apartments | Rooms |",
        "|---|---|---|",
    ]
    for name in ATTRIBUTES:
        counts = {
            c: conn.execute(
                f"SELECT COUNT(*) FROM listing_attributes a JOIN listings l ON l.id = a.listing_id {CATEGORY_JOIN}"
                " WHERE a.name = ? AND a.value IS NOT NULL AND a.value != '' AND a.value != 'Not Available'",
                (c, name),
            ).fetchone()[0]
            for c in CATEGORIES
        }
        out.append(
            f"| `{name}` | {counts['apartments']:,} ({pct(counts['apartments'], n['apartments'])}) | {counts['rooms']:,} ({pct(counts['rooms'], n['rooms'])}) |"
        )
    out += ["", "## Distributions after extraction", ""]
    for col in ("unit_type", "lease_term", "building_type"):
        pairs = conn.execute(
            f"SELECT {col}, COUNT(*) FROM units GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        out.append(f"- `{col}`: " + ", ".join(f"{v or 'null'} {k:,}" for v, k in pairs))
    out += [
        "",
        "## What this means",
        "",
        "- Apartments are structured: every section 3 field except lease term, move-in month, furnished and",
        "  building type is filled for essentially all listings from the index card alone. Lease term and move-in",
        "  are given for about half; the rest say `Not Available`.",
        "- Rooms are text: only price, location, posted dates and sometimes furnished are structured. After the",
        "  detail page is fetched the text rules fill bedrooms for less than half, because the house's bedroom",
        "  count is simply not stated in most room ads. For `unit_type = room` the model should treat `bedrooms`",
        "  as optional (open question for Caden: section 3 lists it as required).",
        "- `building_type` is `unknown` for most apartments because nothing structured separates a low-rise from a",
        "  tower; the known-building registry catches the purpose-built student towers.",
        "- Prices need the cleaning rules in `docs/pipeline.md` section 4: a handful of ads carry placeholder",
        "  prices of $1 or per-term totals.",
        "",
        "## Remaining audit work",
        "",
        "- The daily job fetches 300 more detail pages each run, newest first, so within a week every active",
        "  listing has its full text; rerun this script then.",
        "- Save three more detail pages as fixtures (a professional landlord's apartment, a sublet, a per-room ad",
        "  under apartments) with `scripts/make_fixture.py`; two are in `tests/fixtures/` already.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "field_audit.md")
    args = parser.parse_args(argv)
    conn = connect(args.db)
    args.out.write_text(build(conn))
    conn.close()
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
