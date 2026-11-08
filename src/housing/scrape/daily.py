"""The daily run: sweep Kijiji, mark gone listings, fetch details, extract, build features, report.

    uv run python scripts/sweep.py            # what the launchd job runs
    uv run python -m housing.scrape.daily --details 300

Exit codes: 0 ok; 1 the run crashed (traceback in the log); 2 blocked by the site (stop for
24 hours); 3 a page could not be parsed or a sweep was incomplete (nothing marked gone);
4 the network or the site failed for good (a category failed to fetch even after one retry,
or the details pass lost the network). Every outcome is printed and posted to Discord.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from housing.db import connect
from housing.db.migrate import migrate
from housing.db.queries import count_listings, count_pending_details, count_unkeyed, mark_gone
from housing.features.build import build_features
from housing.features.dedup import assign_dedup_keys
from housing.notify import discord
from housing.parse.extract import extract_all
from housing.parse.kijiji import CATEGORIES, LOCATIONS, ParseError
from housing.paths import REPO_ROOT
from housing.scrape.fetch import (
    BlockedError,
    Fetcher,
    FetchError,
    keep_awake,
    utc_now_iso,
    wait_for_network,
)
from housing.scrape.kijiji import SOURCE, DetailStats, SweepStats, fetch_details, sweep

log = logging.getLogger(__name__)

GONE_AFTER_HOURS = 40
"""Hours unseen before an active listing is marked gone, time-based, not sweep-based.

About two daily runs when runs succeed, but after failed days the next complete sweep marks
the whole backlog at once (155 and 265 gone in one day after the October outages).
``mark_gone`` only runs after every sweep in ``SWEEP_PLAN`` came back complete, so failed
days defer, never fabricate, gone markings.
"""

RETRY_NETWORK_WAIT = 300.0
"""Awake seconds to wait for DNS before the one retry pass over fetch-failed categories."""

SWEEP_PLAN: list[tuple[str, str]] = [
    (location, category) for location in LOCATIONS for category in CATEGORIES
]
"""Every (location, category) pair the daily run sweeps, in order. Kitchener-Waterloo
first (the original market), then the expansion markets (docs/decisions.md 2026-11-06)."""

ERR_LOG_MAX_BYTES = 5 * 1024 * 1024
"""Rotate ``logs/sweep.err.log`` to ``.1`` once it passes this size."""


@dataclass
class DailyReport:
    """What a daily run did, for the console and Discord."""

    started_at: str
    sweeps: list[SweepStats] = field(default_factory=list)
    gone: int = 0
    details: DetailStats = field(default_factory=DetailStats)
    units_extracted: int = 0
    dedup_changed: int = 0
    features_rows: int = 0
    pending_details: int = 0
    unkeyed: int = 0
    listings_total: int = 0
    listings_active: int = 0
    requests_made: int = 0
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0

    def problems(self) -> list[str]:
        """What a human should look at: errors, empty or incomplete sweeps, aborted details."""
        found = list(self.errors)
        found += [f"{s.label}: 0 seen" for s in self.sweeps if s.seen == 0]
        found += [
            f"{s.label} incomplete: {s.stopped_early}" for s in self.sweeps if s.stopped_early
        ]
        if self.details.aborted:
            found.append(f"details {self.details.aborted}")
        if len(self.sweeps) < len(SWEEP_PLAN):
            found.append(f"only {len(self.sweeps)} of {len(SWEEP_PLAN)} sweeps done")
        return found

    def message(self) -> str:
        """One-line summary; prefixed with ALERT when something needs a human."""
        parts = [f"{s.label} {s.seen} seen ({s.new} new)" for s in self.sweeps]
        text = (
            f"Housing sweep {self.started_at[:10]}: " + ", ".join(parts) + f"; {self.gone} gone;"
            f" details {self.details.fetched} fetched/{self.details.failed} failed"
            f"/{self.details.removed} removed;"
            f" units {self.units_extracted}; dedup {self.dedup_changed} changed;"
            f" features {self.features_rows};"
            f" DB {self.listings_total} listings ({self.listings_active} active);"
            f" {self.requests_made} requests;"
            f" pending details {self.pending_details}; unkeyed {self.unkeyed}"
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
    """Run every step in order and return the report; never raises for site or network problems.

    A category whose sweep ends on a network failure (or sees nothing at all) is retried
    once after the whole loop, behind a fresh ``wait_for_network``; page-cap, stuck
    pagination and under-90-percent sweeps are answered-page anomalies, not transient,
    and are never retried. Exit grading is 2 (blocked) over 4 (fetch failed) over 3
    (incomplete), and ``mark_gone`` stays gated on final completeness.
    """
    now = now or datetime.now(UTC)
    scraped_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    report = DailyReport(started_at=scraped_at)
    fetch_failed_outside = False
    for location, category in SWEEP_PLAN:
        try:
            stats = sweep(
                conn,
                fetcher,
                category,
                location=location,
                max_pages=max_pages,
                scraped_at=scraped_at,
            )
        except BlockedError as exc:
            report.errors.append(f"blocked: {exc}")
            report.exit_code = 2
            break
        except ParseError as exc:
            report.errors.append(f"{category} parse failure: {exc}")
            report.exit_code = 3
            break
        except FetchError as exc:
            # Safety net: sweep() swallows fetch failures into partial stats now, so this
            # normally never fires; still, one dead category must not cost the other.
            report.errors.append(f"{category} fetch failure: {exc}")
            fetch_failed_outside = True
            continue
        report.sweeps.append(stats)
    if report.exit_code != 2:
        for i, failed in enumerate(report.sweeps):
            if not (failed.fetch_failed or failed.seen == 0):
                continue  # page cap / stuck pagination / <90% are not transient
            if not wait_for_network(timeout=RETRY_NETWORK_WAIT):
                log.error("network still gone; keeping %s partial stats", failed.label)
                break
            log.info("retrying %s once: %s", failed.label, failed.stopped_early)
            try:
                again = sweep(
                    conn,
                    fetcher,
                    failed.category,
                    location=failed.location,
                    max_pages=max_pages,
                    scraped_at=scraped_at,
                )
            except BlockedError as exc:
                report.errors.append(f"blocked during retry: {exc}")
                report.exit_code = 2
                break
            except ParseError as exc:
                report.errors.append(f"{failed.label} parse failure on retry: {exc}")
                break
            # Upsert creations are one-time events, disjoint across the two attempts.
            again.new += failed.new
            report.sweeps[i] = again
    if report.exit_code != 2 and (
        fetch_failed_outside or any(s.fetch_failed for s in report.sweeps)
    ):
        report.exit_code = 4
    complete = len(report.sweeps) == len(SWEEP_PLAN) and all(
        s.seen > 0 and not s.stopped_early for s in report.sweeps
    )
    if report.exit_code == 0 and not complete:
        report.exit_code = 3
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
    # Dedup keys need units written, hence after extraction; self-commits and is idempotent.
    report.dedup_changed = assign_dedup_keys(conn)
    report.features_rows = build_features(conn)
    report.pending_details = count_pending_details(conn, SOURCE)
    report.unkeyed = count_unkeyed(conn, SOURCE)
    report.listings_total = count_listings(conn)
    report.listings_active = count_listings(conn, "active")
    report.requests_made = fetcher.requests_made
    return report


def rotate_err_log(max_bytes: int = ERR_LOG_MAX_BYTES) -> None:
    """Rename ``logs/sweep.err.log`` over ``sweep.err.log.1`` once it exceeds ``max_bytes``.

    launchd holds the err-log file descriptor, so a rotation takes effect on the next
    run, which is fine. Any filesystem trouble is logged and ignored.
    """
    err_log = REPO_ROOT / "logs" / "sweep.err.log"
    try:
        if err_log.exists() and err_log.stat().st_size > max_bytes:
            err_log.replace(err_log.with_name(err_log.name + ".1"))
    except OSError as exc:
        log.warning("could not rotate %s: %s", err_log, exc)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Whatever happens, one line is printed and posted."""
    rotate_err_log()
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
    keep_awake()
    if not wait_for_network():
        # Nothing was fetched, so nothing in the database changed: report and bow out.
        message = (
            f"ALERT Housing sweep {utc_now_iso()[:10]}: no network"
            " (www.kijiji.ca did not resolve within 10 minutes); nothing fetched"
        )
        print(message)
        if not args.no_notify:
            discord(message)
        return 4
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
