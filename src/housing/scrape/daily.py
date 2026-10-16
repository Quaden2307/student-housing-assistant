"""The daily run: sweep Kijiji, mark gone listings, fetch details, extract, build features, report.

    uv run python scripts/sweep.py            # what the launchd job runs
    uv run python -m housing.scrape.daily --details 300

Exit codes: 0 ok; 1 the run crashed (traceback in the log); 2 blocked by the site (stop for
24 hours); 3 a page could not be parsed or a sweep was incomplete (nothing marked gone);
4 the network or the site failed for good. Every outcome is printed and posted to Discord.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.db.queries import count_listings, mark_gone
from housing.features.build import build_features
from housing.notify import discord
from housing.parse.extract import extract_all
from housing.parse.kijiji import CATEGORIES, ParseError
from housing.scrape.fetch import BlockedError, Fetcher, FetchError, utc_now_iso
from housing.scrape.kijiji import SOURCE, DetailStats, SweepStats, fetch_details, sweep

log = logging.getLogger(__name__)

GONE_AFTER_HOURS = 40
"""A listing missed by two consecutive daily sweeps is marked gone (one miss can be a glitch)."""


@dataclass
class DailyReport:
    """What a daily run did, for the console and Discord."""

    started_at: str
    sweeps: list[SweepStats] = field(default_factory=list)
    gone: int = 0
    details: DetailStats = field(default_factory=DetailStats)
    units_extracted: int = 0
    features_rows: int = 0
    listings_total: int = 0
    listings_active: int = 0
    requests_made: int = 0
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0

    def problems(self) -> list[str]:
        """What a human should look at: errors, empty or incomplete sweeps, aborted details."""
        found = list(self.errors)
        found += [f"{s.category}: 0 seen" for s in self.sweeps if s.seen == 0]
        found += [
            f"{s.category} incomplete: {s.stopped_early}" for s in self.sweeps if s.stopped_early
        ]
        if self.details.aborted:
            found.append(f"details {self.details.aborted}")
        if len(self.sweeps) < len(CATEGORIES):
            found.append(f"only {len(self.sweeps)} of {len(CATEGORIES)} categories swept")
        return found

    def message(self) -> str:
        """One-line summary; prefixed with ALERT when something needs a human."""
        parts = [f"{s.category} {s.seen} seen ({s.new} new)" for s in self.sweeps]
        text = (
            f"Housing sweep {self.started_at[:10]}: " + ", ".join(parts) + f"; {self.gone} gone;"
            f" details {self.details.fetched} fetched/{self.details.failed} failed"
            f"/{self.details.removed} removed;"
            f" units {self.units_extracted}; features {self.features_rows};"
            f" DB {self.listings_total} listings ({self.listings_active} active);"
            f" {self.requests_made} requests"
        )
        problems = self.problems()
        if problems:
            text = "ALERT " + text + " | " + "; ".join(problems)
        return text


def run(
    conn,
    fetcher: Fetcher,
    *,
    max_details: int = 300,
    max_pages: int = 60,
    gone_after_hours: int = GONE_AFTER_HOURS,
    now: datetime | None = None,
) -> DailyReport:
    """Run every step in order and return the report; never raises for site or network problems."""
    now = now or datetime.now(UTC)
    scraped_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    report = DailyReport(started_at=scraped_at)
    complete = True
    for category in CATEGORIES:
        try:
            stats = sweep(conn, fetcher, category, max_pages=max_pages, scraped_at=scraped_at)
        except BlockedError as exc:
            report.errors.append(f"blocked: {exc}")
            report.exit_code = 2
            complete = False
            break
        except ParseError as exc:
            report.errors.append(f"{category} parse failure: {exc}")
            report.exit_code = 3
            complete = False
            break
        except FetchError as exc:
            report.errors.append(f"{category} fetch failure: {exc}")
            report.exit_code = 4
            complete = False
            break
        report.sweeps.append(stats)
        if stats.stopped_early or stats.seen == 0:
            complete = False
            report.exit_code = report.exit_code or 3
    if complete:
        cutoff = (now - timedelta(hours=gone_after_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        report.gone = mark_gone(conn, SOURCE, cutoff)
        conn.commit()
    else:
        log.warning("sweep incomplete; not marking anything gone")
    if report.exit_code in (0, 3) and max_details:
        try:
            report.details = fetch_details(conn, fetcher, limit=max_details, scraped_at=scraped_at)
        except BlockedError as exc:
            report.errors.append(f"blocked during details: {exc}")
            report.exit_code = 2
        if report.details.aborted:
            report.exit_code = report.exit_code or 4
    report.units_extracted = extract_all(conn, only_missing=False, extracted_at=utc_now_iso())
    report.features_rows = build_features(conn)
    report.listings_total = count_listings(conn)
    report.listings_active = count_listings(conn, "active")
    report.requests_made = fetcher.requests_made
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Whatever happens, one line is printed and posted."""
    parser = argparse.ArgumentParser(
        description="Daily sweep, details, extraction, features, report."
    )
    parser.add_argument("--details", type=int, default=300, help="detail pages per run")
    parser.add_argument("--max-pages", type=int, default=60)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--no-notify", action="store_true", help="do not post to Discord")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    conn = connect(args.db)
    try:
        migrate(conn)
        report = run(conn, Fetcher(SOURCE), max_details=args.details, max_pages=args.max_pages)
    except Exception as exc:  # the launchd job must report a crash, not die silently
        log.exception("daily run crashed")
        message = f"ALERT Housing sweep {utc_now_iso()[:10]} crashed: {type(exc).__name__}: {exc}"
        exit_code = 1
    else:
        message = report.message()
        exit_code = report.exit_code
    finally:
        conn.close()
    print(message)
    if not args.no_notify:
        discord(message)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
