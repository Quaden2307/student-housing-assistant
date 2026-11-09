"""Re-apply the PII scrub to raw pages already stored under ``data/raw``.

Pages are scrubbed once, when they are fetched, so a page saved before a scrubbing rule
existed still carries whatever that rule now removes. This CLI walks every ``*.html.gz``
under the raw root, re-runs the scrubber that matches the page's format, and rewrites the
file only when the text actually changes. Metadata sidecars (``*.meta.json``) record the
original fetch and are left alone.

Formats are routed exactly as at store time: Next.js pages (live index, live detail and
archived nextjs captures) go through :func:`housing.parse.pii.scrub_page`, classic-era
archive captures through the classic text-node scrub, and anything else is returned by
:func:`scrub_page` unchanged, so an unparseable page can never be damaged.

Usage::

    uv run python -m housing.scrape.rescrub [--root data/raw] [--dry-run]
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
from pathlib import Path

from housing.parse.archive import _scrub_classic, detect_format
from housing.parse.pii import scrub_page
from housing.paths import raw_dir

logger = logging.getLogger(__name__)


def rescrub_text(html: str) -> str:
    """Return ``html`` with the current scrubbing rules applied, whatever its format.

    Classic-era archive captures get the classic text-node scrub; every other page goes
    through :func:`scrub_page`, which only touches pages with a parseable
    ``__NEXT_DATA__`` and returns anything else as is.
    """
    if detect_format(html) in ("classic", "classic_v0"):
        return _scrub_classic(html)
    return scrub_page(html)


def rescrub_file(path: Path, *, dry_run: bool = False, backup_to: Path | None = None) -> bool:
    """Re-scrub one gzipped page in place. Returns True when the file changed.

    With ``backup_to``, the original file is copied there before being rewritten, so
    the pass can be undone.
    """
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        html = fh.read()
    scrubbed = rescrub_text(html)
    if scrubbed == html:
        return False
    if not dry_run:
        if backup_to is not None:
            backup_to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_to)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(scrubbed)
    return True


def rescrub_tree(
    root: Path, *, dry_run: bool = False, backup_root: Path | None = None
) -> tuple[int, int, int]:
    """Re-scrub every ``*.html.gz`` under ``root``.

    With ``backup_root``, each file about to change is first copied there under its
    path relative to ``root``.

    Returns:
        ``(seen, changed, skipped)`` file counts; skipped files could not be read
        (bad gzip or undecodable text) and are logged, never rewritten.
    """
    seen = changed = skipped = 0
    for path in sorted(root.rglob("*.html.gz")):
        seen += 1
        backup_to = backup_root / path.relative_to(root) if backup_root is not None else None
        try:
            if rescrub_file(path, dry_run=dry_run, backup_to=backup_to):
                changed += 1
                logger.info("rescrubbed %s", path)
        except (OSError, UnicodeDecodeError) as exc:
            skipped += 1
            logger.warning("skipping %s: %s", path, exc)
    return seen, changed, skipped


def main(argv: list[str] | None = None) -> int:
    """Run the re-scrub and print a one-line summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="raw store root (default data/raw)")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    parser.add_argument(
        "--backup", type=Path, default=None, help="copy originals here before rewriting"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    root = args.root if args.root is not None else raw_dir()
    seen, changed, skipped = rescrub_tree(root, dry_run=args.dry_run, backup_root=args.backup)
    verb = "would change" if args.dry_run else "changed"
    print(f"{seen} pages seen, {verb} {changed}, skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
