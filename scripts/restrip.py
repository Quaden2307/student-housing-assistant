"""Re-apply the contact-info rules to every stored listing.

    uv run python scripts/restrip.py [--db PATH]

Run after ``housing.parse.pii`` gets stricter: every title, description and URL slug already
in the database goes through the current rules again. Markers from earlier passes stay.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from housing.db import connect
from housing.db.queries import restrip_listings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db", type=Path, default=None, help="database file (default: data/housing.db)"
    )
    args = parser.parse_args(argv)
    conn = connect(args.db)
    changed = restrip_listings(conn)
    conn.close()
    print(f"re-stripped {changed} listings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
