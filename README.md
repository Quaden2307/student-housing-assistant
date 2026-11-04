# Student Housing Assistant

A fair-price check for Waterloo student rentals. A model trained on scraped
Kitchener-Waterloo listings predicts what a unit should rent for per bedroom,
and a small app scores one listing against it. UW Data Science Club, Fall 2026.

`HANDOFF.md` is the source of truth: product contract, unit schema, data plan,
database schema, layout, modelling plan and the week-by-week calendar.
Decisions are logged in `docs/decisions.md`.

## Status

Nov 3, 2026: the daily 06:30 pipeline now rides out laptop sleep and network flaps (in-process
caffeinate, sleep-aware retries, one bounded retry pass per category) and assigns dedup keys
itself. The database holds 2,900+ live listings and 9,316 archived past ads spanning 2014 to
2026, now tagged with postal prefixes for a neighbourhood-level price index. Phase 1c is done:
a ~2,000-row clean training table with recorded baselines (median lookup MAE $158, ridge $143
on grouped cross-validation). `docs/architecture.md` is the system map; `docs/pipeline.md` has
the write rules; `docs/plan.md` has what comes next; `docs/sources.md` has every source's
status and the Wayback results.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in `.python-version`.
Copy `.env.example` to `.env` and set `HOUSING_HASH_SALT` (any random string) and, when you
have one, `DISCORD_WEBHOOK_URL`.

```sh
uv sync                                  # create .venv and install dependencies
uv run python -m housing.db.migrate      # create data/housing.db (gitignored)
uv run python scripts/sweep.py           # the daily run: sweep, details, extraction, features, report
uv run python -m housing.scrape.kijiji   # index sweep only (about 48 requests)
uv run python -m housing.parse.extract --all   # re-run the unit-field rules
uv run python -m housing.features.build        # rebuild derived features
uv run python -m housing.features.dedup        # assign dedup keys (the daily run does this too)
uv run python -m housing.scrape.backfill --summary   # state of the Wayback archive
uv run python -m housing.model.baseline        # clean-table size and baseline errors
sh scripts/install_launchd.sh            # schedule the daily run at 06:30 on this Mac
uv run pytest                            # tests
uv run ruff check . && uv run ruff format --check .
```
