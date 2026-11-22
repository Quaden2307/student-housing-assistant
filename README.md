# Student Housing Assistant

A fair-price check for Waterloo student rentals. A model trained on scraped
Kitchener-Waterloo listings predicts what a unit should rent for per bedroom,
and a small app scores one listing against it. UW Data Science Club, Fall 2026.

`HANDOFF.md` is the source of truth: product contract, unit schema, data plan,
database schema, layout, modelling plan and the week-by-week calendar.
Decisions are logged in `docs/decisions.md`.

## Status (Nov 21, 2026)

**Data.** The daily sweep covers four Ontario university markets — Kitchener-Waterloo
(3,784 listings), Hamilton (2,587), London (2,223) and Guelph (560) — 9,154 in total
against the 10,000-listing target, backed by 132,335 snapshots. The Wayback lane holds 10,965
past ads (2014 to 2026) drawn from 3,260 captures, and 2,174 of the 2,796 inventoried ad
pages have been downloaded and parsed for their full descriptions (stored scrubbed;
schema v5 adds `archive_units`). Archive rows opt into training with `--archive`, which
takes the clean table from 6,595 rows to 16,047.

**Pipeline.** Runs unattended with a Discord report: it rides out laptop sleep and network
flaps (in-process caffeinate, sleep-aware retries, one bounded retry pass per sweep),
assigns dedup keys itself, and `housing.scrape.rescrub` re-applies the newest PII rules to
raw pages already on disk.

**Model.** Baselines on grouped 5-fold cross-validation of the live-only table: median
lookup MAE $163 ± 5 (16.0%), ridge $146 ± 5 (14.5%); holding out the newest 25%, $172 and
$153. Training with `--archive` is an experiment, not the default: scored on held-out
Waterloo listings it makes ridge *worse*, $142 to $164, because 2014–2017 ads sit near
$500/bed against $933 today (`notebooks/02_geography.ipynb`, decision 2026-11-21).

LightGBM v1 landed on Nov 18: log target, per-unit-type conformal range, SHAP drivers, and
the HANDOFF section 2 verdict fields. Because the table holds four cities but the product
only answers for one, `--eval-city` (default Kitchener-Waterloo) reports a KW-only block
beside the pooled numbers. On KW live rows it scores **MAE $119 (12.0%)** against ridge $136
and the lookup $152, with 82% time-split range coverage. That clears the Phase 2 checkpoint;
error analysis is in `notebooks/03_error_analysis.ipynb`.

**Where things are.** `docs/architecture.md` is the system map; `docs/pipeline.md` has the
write rules and the tier A/B feature split; `docs/plan.md` has what comes next and the open
decisions; `docs/sources.md` has every source's status and the Wayback results;
`docs/market.md` is the domain background the model rests on; `docs/field_audit.md` records
what each schema field actually comes from. Under `notebooks/`: `01_eda.ipynb` (first look at
the clean table, outputs stale as of Oct 24), `02_geography.ipynb` (whether non-Waterloo and
archive rows help — they do not) and `03_error_analysis.ipynb` (where the error is, and the
Phase 2 order of work).

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in `.python-version`.
Copy `.env.example` to `.env` and set `HOUSING_HASH_SALT` (any random string) and, when you
have one, `DISCORD_WEBHOOK_URL`.

On macOS, LightGBM needs OpenMP: `brew install libomp`. Without it `import lightgbm` fails
and `pytest` aborts during collection, not just on the model's own tests.

```sh
uv sync                                  # create .venv and install dependencies
uv run python -m housing.db.migrate      # create data/housing.db (gitignored)
uv run python scripts/sweep.py           # the daily run: sweep, details, extraction, features, report
uv run python -m housing.scrape.kijiji   # KW index sweep only; --location hamilton|london|guelph|all for the other markets
uv run python -m housing.parse.extract --all   # re-run the unit-field rules
uv run python -m housing.features.build        # rebuild derived features
uv run python -m housing.features.dedup        # assign dedup keys (the daily run does this too)
uv run python -m housing.scrape.backfill --summary   # state of the Wayback archive
uv run python -m housing.scrape.rescrub --dry-run     # re-apply current PII rules to stored raw pages (drop --dry-run to write)
uv run python -m housing.model.baseline        # clean-table size and baseline errors; --archive adds the Wayback rows
uv run python -m housing.model.lgbm            # the Phase 2 model; --eval-city scores one market, --fix-labels, --save
uv run python -m housing.model.score           # batch-score active listings into predictions; --dry-run, --load, --save
sh scripts/install_launchd.sh            # schedule the daily run at 06:30 on this Mac
uv run pytest                            # tests
uv run ruff check . && uv run ruff format --check .
```
