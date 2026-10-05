# Student Housing Assistant

A fair-price check for Waterloo student rentals. A model trained on scraped
Kitchener-Waterloo listings predicts what a unit should rent for per bedroom,
and a small app scores one listing against it. UW Data Science Club, Fall 2026.

`HANDOFF.md` is the source of truth: product contract, unit schema, data plan,
database schema, layout, modelling plan and the week-by-week calendar.
Decisions are logged in `docs/decisions.md`.

## Status

Oct 4, 2026: repo and SQLite database set up. Next: the first Kijiji sweep.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in `.python-version`.

```sh
uv sync                                  # create .venv and install dependencies
uv run python -m housing.db.migrate      # create data/housing.db (gitignored)
uv run pytest                            # tests
uv run ruff check . && uv run ruff format --check .
```
