# Student Housing Assistant

A fair-price check for Waterloo student rentals. A model trained on scraped
Kitchener-Waterloo listings predicts what a unit should rent for per bedroom,
and a small app scores one listing against it. UW Data Science Club, Fall 2026.

`HANDOFF.md` is the source of truth: product contract, unit schema, data plan,
database schema, layout, modelling plan and the week-by-week calendar.
Decisions are logged in `docs/decisions.md`.

## Status

Oct 16, 2026: the collection pipeline is built, reviewed and scheduled: Kijiji index sweep, detail
pages, unit-field extraction, derived features, a daily 06:30 run on Caden's Mac with a Discord
report. The database holds about 2,000 listings. See `docs/pipeline.md` for how it works and
`docs/plan.md` for what comes next.

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
sh scripts/install_launchd.sh            # schedule the daily run at 06:30 on this Mac
uv run pytest                            # tests
uv run ruff check . && uv run ruff format --check .
```
