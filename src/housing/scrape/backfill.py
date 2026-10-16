"""Wayback Machine backfill: archived Kijiji index pages into the ``archive_*`` tables.

Lane 2 of ``docs/pipeline.md``. Three steps, each safe to re-run:

1. **Inventory** (``--inventory``): list the archived captures of both KW index pages
   through the CDX API and queue one capture per category, page and day in
   ``archive_captures``. Two requests.
2. **Download** (``--download N``): fetch up to N queued captures, oldest first, one
   every 15 to 20 seconds (archive.org answers 429 "abusive bot traffic" to anything
   faster), parse them, and record every listing card. A 403 or 429 stops the run; the
   queue resumes where it left off on the next run, on any day.
3. **Summary** (``--summary``): what has been collected so far.

``--rebuild`` re-parses every stored capture from ``data/raw/`` without a request, for
when a parser improves or the hash salt becomes available.

Counting rules, so the archive does not overweight slow-to-rent listings:

- An ad is one ``archive_listings`` row however many captures show it. Sightings record
  each appearance and its price, but they are never counted as listings.
- Promoted (``TOP_AD``) cards that repeat within a page are counted once per capture.
- The same page captured twice on the same day (``http`` and ``https``, say) is queued
  once.
- Ads the daily sweep also has are flagged ``in_live``, so the two sources are never
  added together.

Prices are stored as listed, with their dates; inflation is an analysis-time adjustment.

Usage::

    uv run python -m housing.scrape.backfill --inventory --summary
    uv run python -m housing.scrape.backfill --download 40      # about 12 minutes
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.parse.archive import UnsupportedFormat, parse_capture, scrub_capture
from housing.parse.kijiji import CATEGORIES, IndexCard, ParseError
from housing.parse.pii import hash_id, strip_contact_info
from housing.paths import REPO_ROOT
from housing.scrape.fetch import BlockedError, Fetcher, FetchError
from housing.scrape.wayback import USER_AGENT, Capture, captures

log = logging.getLogger(__name__)

SOURCE = "wayback"

_INDEX_RE = re.compile(
    r"^https?://(?:www\.)?kijiji\.ca(?::\d+)?/(?P<slug>b-[a-z0-9-]+)/kitchener-waterloo/"
    r"(?:page-(?P<page>\d+)/)?(?P<code>c\d+l1700212)/?$"
)


def make_backfill_fetcher() -> Fetcher:
    """A fetcher paced for archive.org: one request every 15 to 20 seconds."""
    fetcher = Fetcher(SOURCE, min_delay=15.0, max_delay=20.0, timeout=90.0)
    fetcher.session.headers["User-Agent"] = USER_AGENT
    return fetcher


def index_page(original: str) -> tuple[str, int] | None:
    """Return ``(category, page)`` if ``original`` is a plain KW index URL, else ``None``.

    Query strings (sorting, filters) and other paths are excluded: they are different
    result sets, not the index the live sweep reads.
    """
    match = _INDEX_RE.match(original)
    if not match:
        return None
    for name, cat in CATEGORIES.items():
        if cat.slug == match["slug"] and cat.code == match["code"]:
            return name, int(match["page"] or 1)
    return None


def captured_at(timestamp: str) -> str:
    """Convert a 14-digit Wayback timestamp to ISO 8601 UTC."""
    t = timestamp
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[8:10]}:{t[10:12]}:{t[12:14]}Z"


def inventory(conn: sqlite3.Connection, fetcher: Fetcher, since: int = 2024) -> dict[str, int]:
    """Queue every capture of the KW index pages from ``since`` on.

    Returns:
        Newly queued captures per category.
    """
    added: dict[str, int] = {}
    for name, cat in CATEGORIES.items():
        pattern = f"kijiji.ca/{cat.slug}/kitchener-waterloo/*"
        found = captures(fetcher, pattern, collapse="timestamp:8")
        added[name] = queue(conn, found, since)
    conn.commit()
    return added


def queue(conn: sqlite3.Connection, found: list[Capture], since: int) -> int:
    """Insert index-page captures from ``since`` on, one per category, page and day."""
    added = 0
    for cap in sorted(found, key=lambda c: c.timestamp):
        where = index_page(cap.original)
        if where is None or int(cap.year) < since:
            continue
        category, page = where
        day = cap.timestamp[:8]
        if conn.execute(
            "SELECT 1 FROM archive_captures WHERE category = ? AND page = ?"
            " AND substr(timestamp, 1, 8) = ?",
            (category, page, day),
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO archive_captures"
            " (timestamp, original, category, page, captured_at, status)"
            " VALUES (?, ?, ?, ?, ?, 'pending')",
            (cap.timestamp, cap.original, category, page, captured_at(cap.timestamp)),
        )
        added += 1
    return added


@dataclass
class DownloadReport:
    """What one ``download`` run did."""

    attempted: int = 0
    parsed: int = 0
    unsupported: int = 0
    failed: int = 0
    cards: int = 0
    blocked: str | None = None

    def line(self) -> str:
        """One-line summary for the log."""
        text = (
            f"{self.attempted} captures tried: {self.parsed} parsed ({self.cards} cards),"
            f" {self.unsupported} unsupported, {self.failed} failed"
        )
        return text + (f"; BLOCKED: {self.blocked}" if self.blocked else "")


def download(
    conn: sqlite3.Connection, fetcher: Fetcher, limit: int, max_failures: int = 3
) -> DownloadReport:
    """Fetch, parse and record up to ``limit`` queued captures, oldest first.

    Pending captures go before failed ones, which are retried. The run stops at the
    first block (403 or 429) or after ``max_failures`` failures in a row; every capture
    is committed as it completes, so an interrupted run loses nothing.
    """
    report = DownloadReport()
    rows = conn.execute(
        "SELECT * FROM archive_captures WHERE status IN ('pending', 'failed')"
        " ORDER BY status = 'failed', timestamp LIMIT ?",
        (limit,),
    ).fetchall()
    in_a_row = 0
    for row in rows:
        report.attempted += 1
        cap = Capture(row["timestamp"], row["original"])
        name = f"capture_{row['category']}_p{row['page']}_{row['timestamp']}"
        try:
            result = fetcher.get(cap.raw_url, name, scrub=scrub_capture)
        except BlockedError as exc:
            report.blocked = str(exc)
            report.attempted -= 1
            break
        except FetchError as exc:
            _set_status(conn, row["id"], "failed", error=str(exc))
            report.failed += 1
            in_a_row += 1
            if in_a_row >= max_failures:
                log.warning("%d failures in a row; stopping this run", in_a_row)
                break
            continue
        in_a_row = 0
        raw_path = _repo_relative(result.path)
        status = _process(conn, row, result.text, raw_path, result.fetched_at)
        report.parsed += status == "parsed"
        report.unsupported += status == "unsupported"
        report.failed += status == "failed"
        if status == "parsed":
            report.cards += conn.execute(
                "SELECT cards FROM archive_captures WHERE id = ?", (row["id"],)
            ).fetchone()[0]
    refresh_listings(conn)
    return report


def rebuild(conn: sqlite3.Connection) -> int:
    """Re-parse every stored capture from ``data/raw/``; no network. Returns captures parsed."""
    conn.execute("DELETE FROM archive_sightings")
    conn.execute("DELETE FROM archive_listings")
    rows = conn.execute(
        "SELECT * FROM archive_captures WHERE raw_path IS NOT NULL ORDER BY timestamp"
    ).fetchall()
    parsed = 0
    for row in rows:
        path = Path(row["raw_path"])
        path = path if path.is_absolute() else REPO_ROOT / path
        if not path.exists():
            log.warning("raw file missing for capture %s: %s", row["id"], path)
            continue
        text = gzip.decompress(path.read_bytes()).decode("utf-8", "replace")
        parsed += _process(conn, row, text, row["raw_path"], row["fetched_at"]) == "parsed"
    refresh_listings(conn)
    return parsed


def _process(
    conn: sqlite3.Connection, row: sqlite3.Row, text: str, raw_path: str, fetched_at: str | None
) -> str:
    """Parse one capture's text and record it. Returns the capture's new status."""
    try:
        fmt, total, cards = parse_capture(text)
    except UnsupportedFormat as exc:
        _set_status(
            conn, row["id"], "unsupported", fmt=exc.format, raw_path=raw_path, fetched_at=fetched_at
        )
        return "unsupported"
    except ParseError as exc:
        _set_status(
            conn,
            row["id"],
            "failed",
            error=f"parse: {exc}",
            raw_path=raw_path,
            fetched_at=fetched_at,
        )
        return "failed"
    record_cards(conn, row["id"], row["captured_at"], row["category"], cards)
    _set_status(
        conn,
        row["id"],
        "parsed",
        fmt=fmt,
        cards=len(cards),
        total=total,
        raw_path=raw_path,
        fetched_at=fetched_at,
    )
    return "parsed"


def _set_status(
    conn: sqlite3.Connection,
    capture_id: int,
    status: str,
    *,
    fmt: str | None = None,
    cards: int | None = None,
    total: int | None = None,
    raw_path: str | None = None,
    fetched_at: str | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE archive_captures SET status = ?, format = COALESCE(?, format),"
        " cards = ?, total_count = COALESCE(?, total_count),"
        " raw_path = COALESCE(?, raw_path), fetched_at = COALESCE(?, fetched_at), error = ?"
        " WHERE id = ?",
        (status, fmt, cards, total, raw_path, fetched_at, error, capture_id),
    )
    conn.commit()


def record_cards(
    conn: sqlite3.Connection,
    capture_id: int,
    seen_at: str,
    category: str,
    cards: list[IndexCard],
) -> None:
    """Record one capture's cards: a sighting each, and one ``archive_listings`` row per ad.

    An ad already known keeps its first values; nulls are filled from later captures
    (coordinates, for an ad first seen on a 2024 page), and ``first_seen``/``last_seen``
    widen to cover this capture.
    """
    salted = bool(os.environ.get("HOUSING_HASH_SALT"))
    for card in cards:
        conn.execute(
            "INSERT OR IGNORE INTO archive_sightings"
            " (capture_id, source_id, price, ad_source, sorting_date) VALUES (?, ?, ?, ?, ?)",
            (capture_id, card.source_id, card.price, card.ad_source, card.sorting_date),
        )
        conn.execute(
            """
            INSERT INTO archive_listings (source_id, category, url, title, address_text,
                lat, lon, posted_at, first_seen, last_seen, poster_hash, attributes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                category = COALESCE(archive_listings.category, excluded.category),
                url = COALESCE(archive_listings.url, excluded.url),
                title = COALESCE(archive_listings.title, excluded.title),
                address_text = COALESCE(archive_listings.address_text, excluded.address_text),
                lat = COALESCE(archive_listings.lat, excluded.lat),
                lon = COALESCE(archive_listings.lon, excluded.lon),
                posted_at = COALESCE(archive_listings.posted_at, excluded.posted_at),
                first_seen = MIN(archive_listings.first_seen, excluded.first_seen),
                last_seen = MAX(archive_listings.last_seen, excluded.last_seen),
                poster_hash = COALESCE(archive_listings.poster_hash, excluded.poster_hash),
                attributes = COALESCE(archive_listings.attributes, excluded.attributes)
            """,
            (
                card.source_id,
                category,
                card.url,
                strip_contact_info(card.title) or None,
                card.address_text,
                card.lat,
                card.lon,
                card.activation_date[:10] if card.activation_date else None,
                seen_at,
                seen_at,
                hash_id(card.poster_id) if salted else None,
                json.dumps(card.attributes, sort_keys=True) if card.attributes else None,
            ),
        )


def refresh_listings(conn: sqlite3.Connection) -> None:
    """Recompute each ad's sighting count and price history, and flag ads the sweep has."""
    conn.executescript(
        """
        UPDATE archive_listings SET
          sightings = (SELECT COUNT(*) FROM archive_sightings s
                       WHERE s.source_id = archive_listings.source_id),
          first_price = (SELECT s.price FROM archive_sightings s
                         JOIN archive_captures c ON c.id = s.capture_id
                         WHERE s.source_id = archive_listings.source_id
                         ORDER BY c.captured_at LIMIT 1),
          last_price = (SELECT s.price FROM archive_sightings s
                        JOIN archive_captures c ON c.id = s.capture_id
                        WHERE s.source_id = archive_listings.source_id
                        ORDER BY c.captured_at DESC LIMIT 1),
          min_price = (SELECT MIN(s.price) FROM archive_sightings s
                       WHERE s.source_id = archive_listings.source_id),
          max_price = (SELECT MAX(s.price) FROM archive_sightings s
                       WHERE s.source_id = archive_listings.source_id),
          in_live = EXISTS (SELECT 1 FROM listings l
                            WHERE l.source = 'kijiji' AND l.source_id = archive_listings.source_id);
        """
    )
    conn.commit()


def summary(conn: sqlite3.Connection) -> str:
    """Return a plain-text report of the backfill's state."""
    out: list[str] = []
    rows = conn.execute(
        "SELECT status, COALESCE(format, '-') AS fmt, COUNT(*) AS n FROM archive_captures"
        " GROUP BY status, fmt ORDER BY status, fmt"
    ).fetchall()
    total = sum(r["n"] for r in rows)
    out.append(f"Captures queued: {total}")
    out += [f"  {r['status']:12s} {r['fmt']:11s} {r['n']:>5}" for r in rows]

    ads = conn.execute(
        "SELECT COUNT(*) AS ads, COALESCE(SUM(sightings), 0) AS sightings,"
        " SUM(sightings > 1) AS repeat_ads, SUM(min_price <> max_price) AS price_changed,"
        " SUM(in_live) AS in_live, SUM(lat IS NULL) AS no_coords,"
        " SUM(poster_hash IS NULL) AS no_poster_hash FROM archive_listings"
    ).fetchone()
    out.append(
        f"\nUnique ads: {ads['ads']} from {ads['sightings']} sightings"
        f" ({ads['repeat_ads'] or 0} seen in 2+ captures, {ads['price_changed'] or 0} changed"
        f" price, {ads['in_live'] or 0} also in the daily sweep)"
    )
    out.append(
        f"  missing coordinates: {ads['no_coords'] or 0}; missing poster hash:"
        f" {ads['no_poster_hash'] or 0}"
        + ("" if os.environ.get("HOUSING_HASH_SALT") else " (HOUSING_HASH_SALT not set)")
    )

    out.append("\nBy year first seen (nominal dollars, first price seen, archive-only ads):")
    out.append(f"  {'year':6s} {'category':11s} {'ads':>5s} {'median $':>9s} {'days up*':>9s}")
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for r in conn.execute(
        "SELECT substr(first_seen, 1, 4) AS year, category, first_price, posted_at, last_seen"
        " FROM archive_listings WHERE in_live = 0"
    ):
        groups.setdefault((r["year"], r["category"]), []).append(r)
    for (year, category), items in sorted(groups.items()):
        prices = [r["first_price"] for r in items if r["first_price"]]
        days = [
            (date.fromisoformat(r["last_seen"][:10]) - date.fromisoformat(r["posted_at"])).days
            for r in items
            if r["posted_at"]
        ]
        median_price = f"{statistics.median(prices):,.0f}" if prices else "-"
        median_days = f"{statistics.median(days):.0f}" if days else "-"
        out.append(
            f"  {year:6s} {category:11s} {len(items):>5} {median_price:>9s} {median_days:>9s}"
        )
    out.append(
        "  * median days from posting to the last capture showing the ad: a lower bound on"
        " time listed, not time to rent (only page 1 was archived from 2024 on)."
    )
    return "\n".join(out)


def _repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 2 blocked by archive.org (wait some hours)."""
    parser = argparse.ArgumentParser(description="Backfill archived Kijiji KW index pages.")
    parser.add_argument("--inventory", action="store_true", help="queue captures (2 requests)")
    parser.add_argument("--since", type=int, default=2024, help="first year to queue")
    parser.add_argument("--download", type=int, default=0, metavar="N", help="fetch N captures")
    parser.add_argument("--rebuild", action="store_true", help="re-parse stored captures")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--db", type=Path, default=None, help="database file")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    conn = connect(args.db)
    migrate(conn)
    fetcher = make_backfill_fetcher()
    exit_code = 0
    try:
        if args.inventory:
            added = inventory(conn, fetcher, args.since)
            log.info("queued %s new captures", added)
        if args.download:
            report = download(conn, fetcher, args.download)
            log.info(report.line())
            if report.blocked:
                exit_code = 2
        if args.rebuild:
            log.info("rebuilt from %d stored captures", rebuild(conn))
    except BlockedError as exc:
        log.error("blocked by archive.org: %s; try again in a few hours", exc)
        exit_code = 2
    if args.summary or not (args.inventory or args.download or args.rebuild):
        print(summary(conn))
    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
