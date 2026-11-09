"""Wayback Machine backfill: archived Kijiji pages into the ``archive_*`` tables.

Lane 2 of ``docs/pipeline.md``. Two kinds of archived page:

- **Index pages** (``kind = 'index'``): a page of up to 40 listing cards.
- **Ad pages** (``kind = 'ad'``, ``--ads rooms``): one ad with its full description.
  Rooms have no structured bedroom, lease or utility fields, so their history needs
  the text, and only 8 days of rooms index pages were archived since 2024.

Steps, each safe to re-run:

1. **Inventory** (``--inventory``, plus ``--ads rooms|apartments|both``): list archived
   captures through the CDX API and queue them in ``archive_captures``: index pages
   once per category, page and day; ad pages once per ad id, its earliest capture
   (closest to posting, so the original asking price). Two requests, plus one per ad
   category.
2. **Download** (``--download N``): fetch up to N queued captures, oldest first, one
   every 15 to 20 seconds (archive.org answers 429 "abusive bot traffic" to anything
   faster), parse them and record them. A 403 or 429 stops the run; the queue resumes
   where it left off on the next run, on any day.
3. **Extraction**, after every download or rebuild: the live unit-field rules
   (:func:`housing.parse.units.extract`) are run over every archived ad's title,
   description and attributes into ``archive_units``.
4. **Summary** (``--summary``): what has been collected so far.

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
from housing.features.build import neighbourhood_from_address
from housing.parse.archive import (
    UnsupportedFormat,
    parse_ad_capture,
    parse_capture,
    scrub_ad_capture,
    scrub_capture,
)
from housing.parse.kijiji import CATEGORIES, DetailPage, IndexCard, ParseError
from housing.parse.pii import hash_id, strip_contact_info
from housing.parse.units import extract
from housing.paths import REPO_ROOT
from housing.scrape.fetch import BlockedError, Fetcher, FetchError, keep_awake, utc_now_iso
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
        # The archive lane only covers Kitchener-Waterloo, so the KW location id
        # completes the category prefix here (the regex pins l1700212 the same way).
        if cat.slug == match["slug"] and f"{cat.prefix}l1700212" == match["code"]:
            return name, int(match["page"] or 1)
    return None


_AD_RE = re.compile(
    r"^https?://(?:www\.)?kijiji\.ca(?::\d+)?/(?P<slug>v-[a-z0-9-]+)/kitchener-waterloo/"
    r"[^/?#]+/(?P<ad_id>\d{8,})/?$"
)


def ad_page(original: str) -> tuple[str, str] | None:
    """Return ``(category, ad id)`` if ``original`` is a plain KW ad URL, else ``None``.

    URLs with a query string (``?imageNumber=3``, tracking parameters) are other views
    of the same ad and are skipped; the plain URL is queued instead.
    """
    match = _AD_RE.match(original)
    if not match:
        return None
    for name, cat in CATEGORIES.items():
        if "v-" + cat.slug.removeprefix("b-") == match["slug"]:
            return name, match["ad_id"]
    return None


def captured_at(timestamp: str) -> str:
    """Convert a 14-digit Wayback timestamp to ISO 8601 UTC."""
    t = timestamp
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[8:10]}:{t[10:12]}:{t[12:14]}Z"


def inventory(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    since: int = 2024,
    ads: tuple[str, ...] = (),
) -> dict[str, int]:
    """Queue every capture of the KW index pages, and of the ``ads`` categories' ad pages.

    Args:
        conn: The database.
        fetcher: Used for the CDX queries.
        since: First year to queue.
        ads: Categories whose ad pages to queue too, e.g. ``("rooms",)``.

    Returns:
        Newly queued captures per category (``"<category>"`` for index pages,
        ``"<category> ads"`` for ad pages).
    """
    added: dict[str, int] = {}
    for name, cat in CATEGORIES.items():
        pattern = f"kijiji.ca/{cat.slug}/kitchener-waterloo/*"
        found = captures(fetcher, pattern, collapse="timestamp:8")
        added[name] = queue(conn, found, since)
    for name in ads:
        slug = "v-" + CATEGORIES[name].slug.removeprefix("b-")
        # collapse=urlkey keeps each URL's earliest capture.
        found = captures(fetcher, f"kijiji.ca/{slug}/kitchener-waterloo/*", collapse="urlkey")
        added[f"{name} ads"] = queue_ads(conn, found, since)
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


def queue_ads(conn: sqlite3.Connection, found: list[Capture], since: int) -> int:
    """Insert ad-page captures from ``since`` on: each ad id once, at its earliest capture.

    An ad can be archived under more than one URL (Kijiji changes the slug when the
    title changes), so ads are matched by id, against what is already queued too.
    """
    queued = {
        hit[1]
        for (original,) in conn.execute("SELECT original FROM archive_captures WHERE kind = 'ad'")
        if (hit := ad_page(original))
    }
    added = 0
    for cap in sorted(found, key=lambda c: c.timestamp):
        hit = ad_page(cap.original)
        if hit is None or int(cap.year) < since or hit[1] in queued:
            continue
        queued.add(hit[1])
        conn.execute(
            "INSERT INTO archive_captures"
            " (timestamp, original, category, page, kind, captured_at, status)"
            " VALUES (?, ?, ?, 0, 'ad', ?, 'pending')",
            (cap.timestamp, cap.original, hit[0], captured_at(cap.timestamp)),
        )
        added += 1
    return added


@dataclass
class DownloadReport:
    """What one ``download`` run did."""

    attempted: int = 0
    parsed: int = 0
    unsupported: int = 0
    removed: int = 0
    failed: int = 0
    cards: int = 0
    blocked: str | None = None

    def line(self) -> str:
        """One-line summary for the log."""
        text = (
            f"{self.attempted} captures tried: {self.parsed} parsed ({self.cards} listings),"
            f" {self.unsupported} unsupported, {self.removed} removed ads, {self.failed} failed"
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
        if row["kind"] == "ad":
            hit = ad_page(row["original"])
            ad_id = hit[1] if hit else row["id"]
            name, scrub = f"ad_{row['category']}_{ad_id}_{row['timestamp']}", scrub_ad_capture
        else:
            name = f"capture_{row['category']}_p{row['page']}_{row['timestamp']}"
            scrub = scrub_capture
        try:
            result = fetcher.get(cap.raw_url, name, scrub=scrub)
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
        report.removed += status == "removed"
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
    conn.execute("DELETE FROM archive_units")  # references archive_listings
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
    if row["kind"] == "ad":
        return _process_ad(conn, row, text, raw_path, fetched_at)
    try:
        # Classic-era pages state posting dates relative to the capture moment.
        fmt, total, cards = parse_capture(text, row["captured_at"])
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


def _process_ad(
    conn: sqlite3.Connection, row: sqlite3.Row, text: str, raw_path: str, fetched_at: str | None
) -> str:
    """Parse one ad-page capture and record it. Returns the capture's new status."""
    stored = {"raw_path": raw_path, "fetched_at": fetched_at}
    try:
        fmt, detail = parse_ad_capture(text)
    except UnsupportedFormat as exc:
        _set_status(conn, row["id"], "unsupported", fmt=exc.format, **stored)
        return "unsupported"
    except ParseError as exc:
        _set_status(conn, row["id"], "failed", error=f"parse: {exc}", **stored)
        return "failed"
    if detail is None:  # the URL redirected to a search page: the ad was taken down
        _set_status(conn, row["id"], "removed", fmt=fmt, **stored)
        return "removed"
    record_ad(conn, row["id"], row["captured_at"], row["category"], detail)
    _set_status(conn, row["id"], "parsed", fmt=fmt, cards=1, **stored)
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
    widen to cover this capture. ``neighbourhood`` (the postal prefix in the address) and
    ``intersection`` (classic and v2 cards carry one) fill gaps the same way the address
    does.
    """
    for card in cards:
        _sighting(conn, capture_id, card.source_id, card.price, card.ad_source, card.sorting_date)
        _upsert_listing(
            conn,
            source_id=card.source_id,
            category=category,
            url=card.url,
            title=card.title,
            description=None,  # the card's snippet is truncated; only ad pages fill this
            address_text=card.address_text,
            lat=card.lat,
            lon=card.lon,
            activation_date=card.activation_date,
            seen_at=seen_at,
            poster_id=card.poster_id,
            attributes=card.attributes,
            intersection=card.intersection,
        )


def record_ad(
    conn: sqlite3.Connection, capture_id: int, seen_at: str, category: str, detail: DetailPage
) -> None:
    """Record one ad-page capture: a sighting, and the ad's row with its full description.

    Coordinates are kept only when the ad showed its pin: otherwise Kijiji rounded them
    to about a kilometre, too coarse for walking times (the live pipeline's rule too).
    """
    _sighting(conn, capture_id, detail.source_id, detail.price, None, detail.sorting_date)
    exact = detail.show_pin is not False
    _upsert_listing(
        conn,
        source_id=detail.source_id,
        category=category,
        url=detail.url,
        title=detail.title,
        description=strip_contact_info(detail.description) or None,
        address_text=detail.address_text,
        lat=detail.lat if exact else None,
        lon=detail.lon if exact else None,
        activation_date=detail.activation_date,
        seen_at=seen_at,
        poster_id=detail.poster_id,
        attributes=detail.attributes,
    )


def _sighting(
    conn: sqlite3.Connection,
    capture_id: int,
    source_id: str,
    price: float | None,
    ad_source: str | None,
    sorting_date: str | None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO archive_sightings"
        " (capture_id, source_id, price, ad_source, sorting_date) VALUES (?, ?, ?, ?, ?)",
        (capture_id, source_id, price, ad_source, sorting_date),
    )


def _upsert_listing(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    category: str,
    url: str | None,
    title: str,
    description: str | None,
    address_text: str | None,
    lat: float | None,
    lon: float | None,
    activation_date: str | None,
    seen_at: str,
    poster_id: str | None,
    attributes: dict[str, list[str]],
    intersection: str | None = None,
) -> None:
    """Insert an ad, or widen a known one: first values stick, nulls are filled later."""
    salted = bool(os.environ.get("HOUSING_HASH_SALT"))
    conn.execute(
        """
        INSERT INTO archive_listings (source_id, category, url, title, description,
            address_text, lat, lon, posted_at, first_seen, last_seen, poster_hash, attributes,
            neighbourhood, intersection)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            category = COALESCE(archive_listings.category, excluded.category),
            url = COALESCE(archive_listings.url, excluded.url),
            title = COALESCE(archive_listings.title, excluded.title),
            description = COALESCE(archive_listings.description, excluded.description),
            address_text = COALESCE(archive_listings.address_text, excluded.address_text),
            lat = COALESCE(archive_listings.lat, excluded.lat),
            lon = COALESCE(archive_listings.lon, excluded.lon),
            posted_at = COALESCE(archive_listings.posted_at, excluded.posted_at),
            first_seen = MIN(archive_listings.first_seen, excluded.first_seen),
            last_seen = MAX(archive_listings.last_seen, excluded.last_seen),
            poster_hash = COALESCE(archive_listings.poster_hash, excluded.poster_hash),
            attributes = COALESCE(archive_listings.attributes, excluded.attributes),
            neighbourhood = COALESCE(archive_listings.neighbourhood, excluded.neighbourhood),
            intersection = COALESCE(archive_listings.intersection, excluded.intersection)
        """,
        (
            source_id,
            category,
            url,
            strip_contact_info(title) or None,
            description,
            address_text,
            lat,
            lon,
            activation_date[:10] if activation_date else None,
            seen_at,
            seen_at,
            hash_id(poster_id) if salted else None,
            json.dumps(attributes, sort_keys=True) if attributes else None,
            neighbourhood_from_address(address_text),
            intersection,
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
    extract_units(conn)


def extract_units(conn: sqlite3.Connection, extracted_at: str | None = None) -> int:
    """Rewrite ``archive_units`` from every archived ad with the live extraction rules.

    The same :func:`housing.parse.units.extract` the daily run uses, on the archived
    title, description (when an ad page supplied one) and attributes, so archive and
    live units follow one set of rules and a rule change reaches both on the next run.

    Returns:
        Rows written.
    """
    extracted_at = extracted_at or utc_now_iso()
    conn.execute("DELETE FROM archive_units")
    rows = conn.execute(
        "SELECT source_id, category, title, description, address_text, attributes"
        " FROM archive_listings"
    ).fetchall()
    for row in rows:
        stored = json.loads(row["attributes"] or "{}")
        fields = extract(
            category=row["category"] or "apartments",
            title=row["title"] or "",
            description=row["description"],
            attributes={name: "|".join(values) for name, values in stored.items()},
            address=row["address_text"],
        )
        conn.execute(
            "INSERT INTO archive_units (source_id, unit_type, bedrooms, bathrooms, lease_term,"
            " move_in_month, utilities_included, furnished, laundry_in_unit, building_type,"
            " year_built_after_2018, extracted_by, extracted_at, flags)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["source_id"],
                fields.unit_type,
                fields.bedrooms,
                fields.bathrooms,
                fields.lease_term,
                fields.move_in_month,
                _as_int(fields.utilities_included),
                _as_int(fields.furnished),
                _as_int(fields.laundry_in_unit),
                fields.building_type,
                _as_int(fields.year_built_after_2018),
                fields.extracted_by,
                extracted_at,
                json.dumps({f"text_{k}": v for k, v in fields.flags.items()}, sort_keys=True)
                if fields.flags
                else None,
            ),
        )
    conn.commit()
    return len(rows)


def _as_int(value: bool | None) -> int | None:
    return None if value is None else int(value)


def summary(conn: sqlite3.Connection) -> str:
    """Return a plain-text report of the backfill's state."""
    out: list[str] = []
    rows = conn.execute(
        "SELECT kind, status, COALESCE(format, '-') AS fmt, COUNT(*) AS n FROM archive_captures"
        " GROUP BY kind, status, fmt ORDER BY kind DESC, status, fmt"
    ).fetchall()
    total = sum(r["n"] for r in rows)
    out.append(f"Captures queued: {total}")
    out += [f"  {r['kind']:6s} {r['status']:12s} {r['fmt']:11s} {r['n']:>5}" for r in rows]

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

    out.append("\nUnit fields from the extraction rules (archive_units):")
    out.append(
        f"  {'category':11s} {'ads':>5s} {'with text':>9s} {'bedrooms':>8s} {'lease known':>11s}"
        f" {'sublets':>7s} {'takeovers':>9s}"
    )
    for r in conn.execute(
        "SELECT l.category, COUNT(*) AS ads, SUM(l.description IS NOT NULL) AS with_text,"
        " SUM(u.bedrooms IS NOT NULL) AS bedrooms, SUM(u.lease_term != 'unknown') AS lease,"
        " SUM(u.lease_term = 'sublet_4mo') AS sublets,"
        " SUM(u.flags LIKE '%\"text_is_takeover\"%') AS takeovers"
        " FROM archive_listings l JOIN archive_units u USING (source_id)"
        " GROUP BY l.category ORDER BY l.category"
    ):
        out.append(
            f"  {r['category']:11s} {r['ads']:>5} {r['with_text'] or 0:>9} {r['bedrooms'] or 0:>8}"
            f" {r['lease'] or 0:>11} {r['sublets'] or 0:>7} {r['takeovers'] or 0:>9}"
        )
    return "\n".join(out)


def _repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 2 blocked by archive.org (wait some hours)."""
    parser = argparse.ArgumentParser(description="Backfill archived Kijiji KW pages.")
    parser.add_argument("--inventory", action="store_true", help="queue captures (2+ requests)")
    parser.add_argument(
        "--ads",
        choices=("rooms", "apartments", "both"),
        default=None,
        help="with --inventory, also queue that category's archived ad pages",
    )
    parser.add_argument("--since", type=int, default=2024, help="first year to queue")
    parser.add_argument("--download", type=int, default=0, metavar="N", help="fetch N captures")
    parser.add_argument("--rebuild", action="store_true", help="re-parse stored captures")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--db", type=Path, default=None, help="database file")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    keep_awake()  # a paced multi-hour download dies the same way a sweep does when the Mac sleeps

    conn = connect(args.db)
    migrate(conn)
    fetcher = make_backfill_fetcher()
    exit_code = 0
    try:
        if args.inventory:
            ads = {"rooms": ("rooms",), "apartments": ("apartments",), "both": tuple(CATEGORIES)}
            added = inventory(conn, fetcher, args.since, ads.get(args.ads, ()))
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
