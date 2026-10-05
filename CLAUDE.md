# Student Housing Assistant

A fair-price check for Waterloo student rentals: a model trained on scraped Kitchener-Waterloo listings predicts what a unit should rent for per bedroom, and a small app scores one listing against it.

Read `HANDOFF.md` before doing anything. It holds the product contract (section 2), the unit schema (3), the data and blocking plan (4), the database schema (5), the layout and conventions (6), the modelling plan (7), the phase calendar (9), and this week's ordered tasks (10). Sections 2, 3 and 5 are contracts: don't change them without Caden's sign-off, and log changes in `docs/decisions.md`.

## Conventions

- Python 3.11+, `uv`, `ruff`, `pytest`. Type hints and docstrings on public functions.
- Every parser has a fixture test against saved HTML or JSON in `tests/fixtures/`.
- Raw responses go to `data/raw/` gzipped. `data/` is gitignored except `data/sample.csv`.
- Scrapers are CLIs under `src/housing/scrape/`, one worker, one request every 2 to 3 seconds, a normal User-Agent, hard stop on 403.
- Strip names, phone numbers and emails from listing text at parse time. Never store contact info.
- Notebooks explore; anything the pipeline depends on lives in `src/` and is imported.
- Log decisions in `docs/decisions.md` as date, decision, why.

## Ask before

Scraping a site not listed in `HANDOFF.md` section 4, adding a paid service, using proxies, changing either schema, or committing data.

## Never

Scrape Facebook or Instagram, bypass captchas, rotate proxies, display scraped photos or full listing text in the app, or count snapshots as training rows.

## End of session

Report what works, the row count in `listings`, what's blocked, and what's next.
