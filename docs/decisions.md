# Decisions

One entry per non-trivial decision: date, decision, why. Newest at the bottom.
Changes to the contracts (HANDOFF sections 2, 3 and 5) need Caden's sign-off and are logged here too.

| Date | Decision | Why |
|---|---|---|
| 2026-10-04 | Pin Python 3.11 in `.python-version` (`requires-python >= 3.11`). | 3.11 is the floor HANDOFF names and the safest target for the Phase 2 stack (LightGBM, SHAP, sentence-transformers). 3.13 is also installed via uv if we want to move later. |
| 2026-10-04 | Project name `student-housing-assistant`, import package `housing` under `src/`, built with `uv_build` (`module-name = "housing"`). | Matches the layout in HANDOFF section 6 (`src/housing/...`) while keeping the repo name for the distribution. |
| 2026-10-04 | ruff enforces pydocstyle (Google convention) on `src/` and `scripts/`; tests are exempt from docstring rules. | Makes the "docstrings on public functions" convention a lint failure instead of a code-review nag. |
| 2026-10-04 | Add dependencies only when code that uses them lands (today: `pyyaml`; dev: `pytest`, `ruff`). | Keeps the lockfile honest about what the pipeline needs; scraping and ML libraries arrive with tasks 4 to 5 and Phase 2. |
| 2026-10-04 | All file locations go through `housing.paths` (repo root derived from the package location; `HOUSING_DATA_DIR` and `HOUSING_DB_PATH` env overrides). | Notebooks, scripts and tests run from different working directories; one module settles where `data/`, the DB and the schema live, and tests can redirect to a temp dir. |
| 2026-10-04 | `src/housing/db/schema.sql` is the section 5 DDL verbatim with `IF NOT EXISTS`; no indexes yet. | Keep the contract file identical to HANDOFF. Indexes get added, and logged here, when a query needs them. |
| 2026-10-04 | Every connection from `housing.db.connect` turns on `PRAGMA foreign_keys` and WAL journaling. | SQLite ignores `REFERENCES` unless foreign keys are enabled per connection. WAL lets a notebook read while the sweep writes. |
| 2026-10-04 | Schema version lives in SQLite's `PRAGMA user_version` (now 1); no migrations table. | Avoids creating a table outside the section 5 contract. Future changes bump `SCHEMA_VERSION` and add guarded `ALTER` steps in `migrate.py`. |
| 2026-10-04 | TEXT timestamps are ISO 8601 UTC (`2026-10-05T14:03:00Z`); `posted_at` is `YYYY-MM-DD`; booleans in `units` are 0, 1 or NULL. | Section 5 declares TEXT but not a format. Fixing it before the first sweep keeps rows sortable and comparable across sources. |
