"""Copy a raw Kijiji page into tests/fixtures with personal data scrubbed.

    uv run python scripts/make_fixture.py data/raw/kijiji/<date>/detail_<id>.html.gz <fixture_name>

The page goes through ``housing.parse.pii.scrub_page`` (poster names and phone numbers
removed, listing text stripped of contact details). On top of that, for a committed file:
poster account ids are replaced with fake stable ids (the real ones link to public
profiles), and Kijiji's client identifiers (``machId``, ``pageLoadId``) and our User-Agent
are blanked. The output is gzipped like the input.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

from housing.parse.kijiji import NEXT_DATA_RE
from housing.parse.pii import encode_next_data, scrub_page
from housing.paths import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures"
FAKE_POSTER_ID_BASE = 10_000_001


def poster_ids_in(state: dict) -> set[str]:
    """Every poster account id in an Apollo cache (profiles and ``posterInfo`` blocks)."""
    ids: set[str] = set()
    for key, entity in state.items():
        if not isinstance(entity, dict):
            continue
        if key.startswith("StandardProfileV2:"):
            ids.add(key.split(":", 1)[1])
            if entity.get("id") is not None:
                ids.add(str(entity["id"]))
        poster = entity.get("posterInfo")
        if isinstance(poster, dict) and poster.get("posterId") is not None:
            ids.add(str(poster["posterId"]))
    return ids


def scrub(html: str) -> str:
    """Return ``html`` scrubbed for a committed fixture (see the module docstring)."""
    html = scrub_page(html)
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise SystemExit("no __NEXT_DATA__ in page")
    data = json.loads(match.group(1))
    page_props = data["props"]["pageProps"]
    for key in ("userAgent", "machId", "pageLoadId"):
        if isinstance(page_props.get(key), str):
            page_props[key] = "[removed]"
    state = page_props.get("__APOLLO_STATE__") or {}
    root = state.get("ROOT_QUERY")
    if isinstance(root, dict) and isinstance(root.get("userAgent"), str):
        root["userAgent"] = "[removed]"
    html = html[: match.start(1)] + encode_next_data(data) + html[match.end(1) :]
    for i, poster_id in enumerate(sorted(poster_ids_in(state))):
        fake = str(FAKE_POSTER_ID_BASE + i)
        html = re.sub(rf"(?<!\d){re.escape(poster_id)}(?!\d)", fake, html)
    return html


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw", type=Path, help="gzipped raw page under data/raw/")
    parser.add_argument("name", help="fixture name without extension")
    args = parser.parse_args(argv)
    html = gzip.decompress(args.raw.read_bytes()).decode("utf-8", "replace")
    out = FIXTURES / f"{args.name}.html.gz"
    out.write_bytes(gzip.compress(scrub(html).encode("utf-8")))
    print(f"wrote {out.relative_to(REPO_ROOT)} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
