"""Count Wayback Machine captures of Kijiji Kitchener-Waterloo rental pages (HANDOFF task 8).

Sizes the history available for the backfill. Four CDX queries, one request
each, 2 to 3 seconds apart; raw responses go to ``data/raw/wayback/<date>/``.

- Index pages: days on which some page of the category index was captured.
  Each capture holds up to 40 listing cards.
- Ad pages: distinct ad URLs, counted in the month of their first capture.

Usage::

    uv run python scripts/wayback_count.py              # by month (HANDOFF task 8)
    uv run python scripts/wayback_count.py --by year

The output is a Markdown table, ready to paste into notes.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime

from housing.scrape.fetch import FetchError
from housing.scrape.wayback import captures, count_by, make_fetcher

QUERIES = {
    "Apartments index (capture-days)": (
        "kijiji.ca/b-apartments-condos/kitchener-waterloo/*",
        "timestamp:8",
    ),
    "Rooms index (capture-days)": (
        "kijiji.ca/b-room-rental-roommate/kitchener-waterloo/*",
        "timestamp:8",
    ),
    "Apartment ads (new URLs)": ("kijiji.ca/v-apartments-condos/kitchener-waterloo/*", "urlkey"),
    "Room ads (new URLs)": ("kijiji.ca/v-room-rental-roommate/kitchener-waterloo/*", "urlkey"),
}
"""Column label -> (CDX URL pattern, collapse key)."""


def render(counts: dict[str, Counter[str]], period: str) -> str:
    """Render one column per query and one row per period as a Markdown table."""
    periods = sorted(set().union(*counts.values()))
    lines = [
        "| " + " | ".join([period.capitalize(), *counts]) + " |",
        "|" + "---|" * (len(counts) + 1),
    ]
    for p in periods:
        lines.append("| " + " | ".join([p, *(str(c.get(p, 0)) for c in counts.values())]) + " |")
    totals = [f"**{sum(c.values()):,}**" for c in counts.values()]
    lines.append("| " + " | ".join(["**Total**", *totals]) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the four CDX queries and print the counts table."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--by", choices=("year", "month"), default="month")
    args = parser.parse_args(argv)

    fetcher = make_fetcher()
    counts: dict[str, Counter[str]] = {}
    for label, (pattern, collapse) in QUERIES.items():
        print(f"querying {pattern} ...", file=sys.stderr)
        try:
            counts[label] = count_by(captures(fetcher, pattern, collapse=collapse), args.by)
        except FetchError as error:
            print(f"failed: {error}", file=sys.stderr)
            return 1

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    print(f"Wayback Machine, Kijiji Kitchener-Waterloo, HTTP 200 captures, queried {today}\n")
    print(render(counts, args.by))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
