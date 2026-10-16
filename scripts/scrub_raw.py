"""Scrub personal data out of raw Kijiji pages saved before the fetcher did it on the way in.

    uv run python scripts/scrub_raw.py [data/raw/kijiji]

Every ``*.html.gz`` under the directory goes through ``housing.parse.pii.scrub_page``
(poster name and phone removed, listing text stripped of contact details) and is rewritten
in place. Parsers read the same fields before and after.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from housing.parse.pii import scrub_page
from housing.paths import raw_dir
from housing.scrape.fetch import scrub_stored_pages


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, nargs="?", default=None)
    args = parser.parse_args(argv)
    directory = args.directory or raw_dir() / "kijiji"
    changed = scrub_stored_pages(directory, scrub_page)
    print(f"scrubbed {changed} pages under {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
