"""One full scrape of all sources: the entry point for the daily launchd job.

Equivalent to ``uv run python -m housing.scrape.daily``; see that module for options.
"""

from housing.scrape.daily import main

if __name__ == "__main__":
    raise SystemExit(main())
