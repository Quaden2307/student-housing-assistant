"""Write ``data/sample.csv``: 100 parsed listings so the EDA notebook opens without the scraper.

    uv run python scripts/export_sample.py

Rows join ``listings``, ``units`` and ``features``. Contact details were already stripped at
parse time; on top of that the street address is dropped (only the postal prefix and
coordinates rounded to about 100 m are kept) and the description is left out. The sample
is 60 apartments and 40 rooms with a price, chosen with a fixed random seed.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from housing.db import connect
from housing.paths import data_dir

COLUMNS = [
    "source", "source_id", "url", "category", "title", "posted_at", "first_seen", "last_seen",
    "status", "price", "unit_type", "bedrooms", "bathrooms", "lease_term", "move_in_month",
    "utilities_included", "furnished", "laundry_in_unit", "building_type",
    "year_built_after_2018", "extracted_by", "price_per_bedroom", "walk_uw_min",
    "walk_laurier_min", "ion_distance_m", "neighbourhood", "days_on_market", "lat", "lon",
]  # fmt: skip

_QUERY = """
SELECT l.source, l.source_id, l.url, a.value AS category, l.title, l.posted_at, l.first_seen,
       l.last_seen, l.status, p.price,
       u.unit_type, u.bedrooms, u.bathrooms, u.lease_term, u.move_in_month,
       u.utilities_included, u.furnished, u.laundry_in_unit, u.building_type,
       u.year_built_after_2018, u.extracted_by,
       f.price_per_bedroom, f.walk_uw_min, f.walk_laurier_min, f.ion_distance_m,
       f.neighbourhood, f.days_on_market,
       ROUND(l.lat, 3) AS lat, ROUND(l.lon, 3) AS lon
FROM listings l
JOIN listing_attributes a ON a.listing_id = l.id AND a.name = 'category'
LEFT JOIN units u ON u.listing_id = l.id
LEFT JOIN features f ON f.listing_id = l.id
JOIN (
    SELECT listing_id, price FROM (
        SELECT listing_id, price,
               ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY scraped_at DESC, id DESC) AS rn
        FROM snapshots WHERE price IS NOT NULL
    ) WHERE rn = 1
) p ON p.listing_id = l.id
WHERE a.value = ?
ORDER BY l.id
"""


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export a 100-row PII-safe sample to data/sample.csv."
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="default: data/sample.csv")
    parser.add_argument("--seed", type=int, default=20261014)
    args = parser.parse_args(argv)
    out = args.out or data_dir() / "sample.csv"

    conn = connect(args.db)
    rng = random.Random(args.seed)
    rows: list[dict] = []
    for category, n in (("apartments", 60), ("rooms", 40)):
        pool = [dict(r) for r in conn.execute(_QUERY, (category,)).fetchall()]
        rows += rng.sample(pool, min(n, len(pool)))
    conn.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in COLUMNS})
    print(f"wrote {out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
