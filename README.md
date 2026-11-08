# Student Housing Assistant

A fair-price check for Waterloo student rentals. A model trained on scraped
Kitchener-Waterloo listings predicts what a unit should rent for per bedroom,
and a small app scores one listing against it. UW Data Science Club, Fall 2026.

`HANDOFF.md` is the source of truth: product contract, unit schema, data plan,
database schema, layout, modelling plan and the week-by-week calendar.
Decisions are logged in `docs/decisions.md`.

## Status

Nov 6, 2026: the daily sweep now covers four Ontario university markets — Kitchener-Waterloo,
Guelph, Hamilton and London — toward a 10,000-listing target, and the Wayback archive rows
(9,316 past ads, 2014 to 2026) can opt into training with `--archive`, which takes the clean
table from ~2,200 rows to ~10,250. The pipeline rides out laptop sleep and network flaps
(in-process caffeinate, sleep-aware retries, one bounded retry pass per sweep) and assigns
dedup keys itself. Baselines on the live-only table: median lookup MAE $160, ridge $142 on
grouped cross-validation. `docs/architecture.md` is the system map; `docs/pipeline.md` has
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
uv run python -m housing.scrape.kijiji   # KW index sweep only; --location hamilton|london|guelph|all for the other markets
uv run python -m housing.parse.extract --all   # re-run the unit-field rules
uv run python -m housing.features.build        # rebuild derived features
uv run python -m housing.features.dedup        # assign dedup keys (the daily run does this too)
uv run python -m housing.scrape.backfill --summary   # state of the Wayback archive
uv run python -m housing.model.baseline        # clean-table size and baseline errors; --archive adds the Wayback rows
sh scripts/install_launchd.sh            # schedule the daily run at 06:30 on this Mac
uv run pytest                            # tests
uv run ruff check . && uv run ruff format --check .
```
