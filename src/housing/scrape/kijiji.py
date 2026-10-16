"""Sweep the Kijiji Kitchener-Waterloo index pages into the database.

    uv run python -m housing.scrape.kijiji --category both --max-pages 60

One run fetches every index page of each category (40 listings a page, about 48 requests for
both categories), upserts each listing into ``listings`` and adds one ``snapshots`` row per
listing seen, holding the price on the card and the path of the raw page it came from.
Index pages are always fetched fresh, so a snapshot is a real sighting. Detail pages are a
separate step. Exit code 2 means the site blocked us: stop for 24 hours.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.db.queries import (
    count_listings,
    delete_attributes,
    insert_snapshot,
    pending_details,
    replace_attributes,
    set_detail,
    upsert_listing,
)
from housing.parse.kijiji import (
    CATEGORIES,
    AdRemovedError,
    IndexCard,
    ParseError,
    category_name,
    index_url,
    parse_detail,
    parse_index,
)
from housing.parse.pii import hash_id, redact_url, scrub_page, strip_contact_info
from housing.paths import REPO_ROOT
from housing.scrape.fetch import BlockedError, Fetcher, FetchError, utc_now_iso

log = logging.getLogger(__name__)

SOURCE = "kijiji"

COMPLETE_FRACTION = 0.9
"""A sweep that saw fewer than this share of the site's count is incomplete."""

DETAIL_RETRY_DAYS = 3
"""A detail page whose fetch failed is tried again after this many days."""

MAX_CONSECUTIVE_DETAIL_FAILURES = 3
"""Stop the details step after this many failures in a row (the network or the layout)."""


@dataclass
class SweepStats:
    """What one category sweep did."""

    category: str
    pages: int = 0
    seen: int = 0
    new: int = 0
    total_count: int = 0
    stopped_early: str | None = None
    """Why the sweep is not a complete picture of the category; None when it is."""


def sweep(
    conn,
    fetcher: Fetcher,
    category: str,
    *,
    max_pages: int = 60,
    scraped_at: str | None = None,
) -> SweepStats:
    """Walk one category's index pages and record every listing seen.

    The sweep is complete when the last page was reached within ``max_pages`` and at least
    ``COMPLETE_FRACTION`` of the site's total count was seen; otherwise ``stopped_early``
    says why, and the caller must not mark anything gone.

    Args:
        conn: Open database connection; committed after every page.
        fetcher: The rate-limited fetcher for ``kijiji``.
        category: ``"apartments"`` or ``"rooms"``.
        max_pages: Safety cap on pages per category.
        scraped_at: Timestamp shared by every snapshot of this run (defaults to now).
    """
    scraped_at = scraped_at or utc_now_iso()
    stats = SweepStats(category)
    seen_ids: set[str] = set()  # promoted ads repeat across pages; one snapshot per run
    for page in range(1, max_pages + 1):
        result = fetcher.get(
            index_url(category, page), f"index_{category}_p{page}", refresh=True, scrub=scrub_page
        )
        index = parse_index(result.text)
        if page > 1 and index.offset == 0:
            stats.stopped_early = (
                f"page {page} came back as page 1; the pagination URL form is wrong"
            )
            break
        if index.total_count <= 0:
            stats.stopped_early = f"page {page} reports no listings at all"
            break
        stats.pages += 1
        stats.total_count = index.total_count
        raw_path = _repo_relative(result.path)
        for card in index.cards:
            if card.source_id in seen_ids:
                continue
            seen_ids.add(card.source_id)
            listing_id, created = upsert_listing(
                conn,
                source=SOURCE,
                source_id=card.source_id,
                seen_at=scraped_at,
                url=redact_url(card.url),
                title=strip_contact_info(card.title),
                address_text=card.address_text,
                lat=card.lat,
                lon=card.lon,
                posted_at=card.activation_date[:10] if card.activation_date else None,
            )
            insert_snapshot(conn, listing_id, scraped_at, card.price, raw_path)
            replace_attributes(conn, listing_id, card_attributes(card))
            stats.seen += 1
            stats.new += int(created)
        conn.commit()
        log.info(
            "%s page %d: %d cards, offset %d of %d",
            category,
            page,
            len(index.cards),
            index.offset,
            index.total_count,
        )
        if not index.cards or index.offset + index.limit >= index.total_count:
            break
    else:
        stats.stopped_early = (
            f"page cap {max_pages} reached with {stats.seen} of {stats.total_count} seen"
        )
    if stats.stopped_early is None and stats.seen < COMPLETE_FRACTION * stats.total_count:
        stats.stopped_early = f"only {stats.seen} of {stats.total_count} listings seen"
    if stats.stopped_early:
        log.error("%s sweep incomplete: %s", category, stats.stopped_early)
    return stats


def card_attributes(card: IndexCard) -> dict[str, str | None]:
    """Everything on an index card worth keeping, as ``listing_attributes`` rows."""
    attrs: dict[str, str | None] = {
        name: "|".join(values) for name, values in card.attributes.items()
    }
    attrs.update(
        {
            "category": category_name(card.category_id),
            "price_type": card.price_type,
            "ad_source": card.ad_source,
            "sorting_date": card.sorting_date,
            "neighbourhood_name": card.neighbourhood,
            "intersection": card.intersection,
            "image_count": str(card.image_count),
            "poster_hash": hash_id(card.poster_id),
        }
    )
    return {name: value for name, value in attrs.items() if value is not None}


@dataclass
class DetailStats:
    """What one detail-fetching pass did."""

    fetched: int = 0
    failed: int = 0
    removed: int = 0
    """Ads whose page redirected to the search results: taken down since the sweep."""
    aborted: str | None = None
    """Set when the pass stopped after repeated failures; the report must ALERT."""


def fetch_details(
    conn, fetcher: Fetcher, *, limit: int, scraped_at: str | None = None
) -> DetailStats:
    """Fetch detail pages for listings that have none yet (rooms first) and store the fields.

    The full description is stored with contact details stripped; address, coordinates and
    the posting date only fill gaps because the index card's values are at least as good.
    A page that cannot be fetched or parsed keeps a null description and gets
    ``detail_error`` and ``detail_failed_at`` attributes, and is retried after
    ``DETAIL_RETRY_DAYS``. A removed ad (Kijiji redirects to the search page) is recorded as
    ``detail_error = removed`` and left to the gone rule. After
    ``MAX_CONSECUTIVE_DETAIL_FAILURES`` failures in a row the pass stops, since the network
    or the page layout is the problem, not the ad.
    """
    scraped_at = scraped_at or utc_now_iso()
    retry_before = (
        datetime.strptime(scraped_at, "%Y-%m-%dT%H:%M:%SZ") - timedelta(days=DETAIL_RETRY_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = DetailStats()
    consecutive_failures = 0
    for row in pending_details(conn, SOURCE, limit, retry_failed_before=retry_before):
        name = f"detail_{row['source_id']}"
        try:
            result = fetcher.get(row["url"], name, scrub=scrub_page)
            detail = parse_detail(result.text)
            if detail.source_id != row["source_id"]:
                raise ParseError(f"page is ad {detail.source_id}, expected {row['source_id']}")
        except BlockedError:
            raise
        except AdRemovedError:
            log.info("detail %s: the ad was removed", row["source_id"])
            replace_attributes(
                conn, row["id"], {"detail_error": "removed", "detail_failed_at": scraped_at}
            )
            stats.removed += 1
            conn.commit()
            continue
        except (FetchError, ParseError) as exc:
            log.warning("detail %s failed: %s", row["source_id"], exc)
            replace_attributes(
                conn, row["id"], {"detail_error": str(exc)[:200], "detail_failed_at": scraped_at}
            )
            stats.failed += 1
            consecutive_failures += 1
            conn.commit()
            if consecutive_failures >= MAX_CONSECUTIVE_DETAIL_FAILURES:
                stats.aborted = f"stopped after {consecutive_failures} failures in a row ({exc})"
                log.error("details %s", stats.aborted)
                break
            continue
        consecutive_failures = 0
        set_detail(
            conn,
            row["id"],
            description=strip_contact_info(detail.description),
            address_text=detail.address_text,
            lat=detail.lat,
            lon=detail.lon,
            posted_at=detail.activation_date[:10] if detail.activation_date else None,
        )
        attrs: dict[str, str | None] = {
            name: "|".join(values) for name, values in detail.attributes.items()
        }
        attrs.update(
            {
                "image_count": str(detail.image_count),
                "views": str(detail.views) if detail.views is not None else None,
                "end_date": detail.end_date,
                "detail_status": detail.status,
                "poster_hash": hash_id(detail.poster_id),
                "detail_fetched_at": result.fetched_at or scraped_at,
                "detail_raw_path": _repo_relative(result.path),
            }
        )
        replace_attributes(conn, row["id"], {k: v for k, v in attrs.items() if v is not None})
        delete_attributes(conn, row["id"], names=("detail_error", "detail_failed_at"))
        stats.fetched += 1
        conn.commit()
    return stats


def _repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Sweep Kijiji KW index pages into the database.")
    parser.add_argument("--category", choices=[*CATEGORIES, "both"], default="both")
    parser.add_argument("--max-pages", type=int, default=60, help="safety cap per category")
    parser.add_argument(
        "--details", type=int, default=0, help="also fetch up to N pending detail pages"
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="database file (default: data/housing.db)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    conn = connect(args.db)
    migrate(conn)
    fetcher = Fetcher(SOURCE)
    categories = list(CATEGORIES) if args.category == "both" else [args.category]
    scraped_at = utc_now_iso()
    exit_code = 0
    for category in categories:
        try:
            stats = sweep(conn, fetcher, category, max_pages=args.max_pages, scraped_at=scraped_at)
        except BlockedError as exc:
            log.error("blocked, stopping the run: %s", exc)
            exit_code = 2
            break
        except ParseError as exc:
            log.error("could not parse a %s page (raw copy is saved): %s", category, exc)
            exit_code = 3
            break
        line = (
            f"{category}: {stats.pages} pages, {stats.seen} listings seen, {stats.new} new"
            f" (site total {stats.total_count})"
        )
        if stats.stopped_early:
            line += f"; incomplete: {stats.stopped_early}"
            exit_code = exit_code or 3
        print(line)
    if args.details and exit_code != 2:
        try:
            details = fetch_details(conn, fetcher, limit=args.details, scraped_at=scraped_at)
            print(
                f"details: {details.fetched} fetched, {details.failed} failed,"
                f" {details.removed} removed" + (f"; {details.aborted}" if details.aborted else "")
            )
        except BlockedError as exc:
            log.error("blocked while fetching details: %s", exc)
            exit_code = 2
    print(
        f"listings in DB: {count_listings(conn)} ({count_listings(conn, 'active')} active);"
        f" requests this run: {fetcher.requests_made}"
    )
    conn.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
