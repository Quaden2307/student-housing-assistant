# Student Housing Assistant: hand-off

Project lead: Caden Sun (GitHub `Quaden2307`). UW Data Science Club project, Fall 2026, continuing into Winter 2027.
Status on Oct 4, 2026: nothing is built yet. This week's job is the repo, the database, and the first scrape.

Read this whole file before writing code. Sections 2, 3 and 5 are contracts; change them only with Caden's sign-off and log the change in `docs/decisions.md`.

---

## 1. What this is

Students in Waterloo see an asking price for a room or unit and have no way to know if it's reasonable. Listing sites never say a unit is overpriced, and judging it yourself means knowing the whole market.

We are building a model that learns, from thousands of scraped Waterloo and Kitchener rental listings, how a unit's details map to its rent. On top of it sits a small app: the user gives us one listing (a link, or pasted text, or a form), and we tell them what similar units go for, where this asking price sits, why, and show comparable listings.

This is a data science project first. The scraper and the app are plumbing. The dataset, the analysis notebooks, the trained model and its evaluation are the deliverables.

Test for whether the ML is real: make up a unit that does not exist in the dataset (a 4-month furnished sublet, utilities included, 14 minutes from campus, in a 6-bed house) and the model still returns a sensible price. A lookup table can't do that. The median-by-neighbourhood lookup is the baseline the model must beat, not the product.

---

## 2. Product contract: input and output

### Input

Three ways in, in order of reliability:

1. **Pasted text.** The user pastes the listing's title, description and price. We extract the unit schema (section 3) from it with an LLM call plus regex for price and bedrooms. This path never breaks because of blocking. Treat it as the primary path, not the fallback.
2. **Form.** The user fills the schema fields by hand.
3. **URL.** For supported sites (Kijiji first), fetch the page and parse it into the schema. Best effort. If the fetch fails or the site is unsupported, fall back to path 1 with a one-line message.

Whichever path, the extracted fields are shown back to the user to confirm or edit before scoring. A bad parse must not become a bad verdict silently.

### Output

One scored result with these fields. Everything on screen is a view of them.

| Field | Meaning |
|---|---|
| `expected` | Predicted price per bedroom per month, in dollars |
| `range_low`, `range_high` | 10th and 90th percentile of what units like this ask |
| `price_percentile` | 0 to 100. Where the asking price sits in the model's distribution for this unit. Lower is cheaper. 50 means exactly as expected. "Cheaper than 70% of comparable units" is percentile 30. |
| `band` | `GOOD_DEAL` if percentile <= 25, `FAIR` if 25 to 75, `OVERPRICED` if >= 75. Thresholds get tuned after calibration (section 7). |
| `gap_dollars`, `gap_percent` | Asking minus expected |
| `drivers` | Top three SHAP contributions, rendered in plain words ("11-min walk to UW: +$60") |
| `comparables` | 3 to 5 listings from our DB: same unit type, nearest in distance and features, each with price, key fields, and a link out to the source. Never re-host their photos or full text. |
| `confidence` | Count of similar listings within 1.5 km, the model's held-out MAE, and an `out_of_distribution` flag when there are fewer than 10 similar listings |

Decision on "Good / Fair / Bad vs a score out of 100": both, from one number. The percentile is the score; the band is the label derived from it. Rule: never show a band whose margin is inside the model's error. If the held-out MAE is $115 and the gap is $40, say "within the model's margin" and mark it `FAIR`.

---

## 3. Unit schema (the contract)

Lives in `schema/unit_schema.yaml`. The scraper, the text extractor, the form and the model all read from this file. If the scraper and the model disagree about what `bedrooms` means, this file settles it.

Required. No prediction without these.

| Field | Type | Values / notes |
|---|---|---|
| `unit_type` | enum | `room` (one bedroom in a shared house or apartment), `studio`, `1bed`, `2bed`, `3plus`, `house` |
| `bedrooms` | int | Total bedrooms in the whole unit. For a `room` listing, the house's total. |
| `lat`, `lon` | float | Geocoded from address, intersection or postal code. Kijiji detail pages carry map coordinates; prefer those. |
| `lease_term` | enum | `sublet_4mo`, `8mo`, `12mo`, `month_to_month`, `unknown` |
| `move_in_month` | int 1 to 12 | The Sept / Jan / May cycle moves prices |

Optional. Missing is allowed and is represented as null, never as a guessed value.

| Field | Type |
|---|---|
| `utilities_included` | bool |
| `furnished` | bool |
| `bathrooms` | float |
| `laundry_in_unit` | bool |
| `building_type` | enum: `house`, `lowrise`, `purpose_built_student`, `unknown` |
| `year_built_after_2018` | bool (units first occupied after Nov 15, 2018 are exempt from Ontario rent control; only fill it if a source states it) |

Derived by us, never entered by anyone. Rebuilt from the fields above at any time.

| Field | How |
|---|---|
| `price_per_bedroom` | `room`: asking price. Otherwise asking price / bedrooms. **This is the model target.** |
| `walk_uw_min`, `walk_laurier_min` | Haversine distance to campus in v1; OSRM walking time later if someone wants it |
| `ion_distance_m` | Distance to the nearest ION LRT stop (hardcode the stop coordinates) |
| `neighbourhood` | Postal prefix (first three characters) in v1 |
| `days_on_market` | `last_seen` minus `posted_at`, scraped listings only |

Asking price is not a feature. It is the target when training and the thing we compare against when scoring.

Schema rule: every field must be readable from a typical listing page and easy for a person to type into a form. If it fails either test, cut it. Keep the schema around this size.

---

## 4. Data: what is known, sources, and the blocking plan

### Verified on Sept 29, 2026

- Kijiji Kitchener/Waterloo, Apartments & Condos for rent (houses included): **1,522 active listings**.
  `https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212`
- Kijiji Kitchener/Waterloo, Room Rentals & Roommates: **309 active listings**.
  `https://www.kijiji.ca/b-room-rental-roommate/kitchener-waterloo/c36l1700212`
- A plain HTTP GET of those index pages returned full HTML including the total count ("Results 1 - 40 of 1,522"). Detail pages are untested.
- apartments.com claims about 1,350 listings for Waterloo but sits behind Cloudflare and its terms prohibit scraping. Skip it.
- Late September is the seasonal low for rooms (everyone just moved in). October and November are when January sublets and leases get posted, so room volume should rise through our window.

### What this means for volume

The first sweep is the dataset: about 1,800 unique listings on day one. Daily sweeps after that add new listings (guess 50 to 150 a day for KW) and, more importantly, history: which listings vanished, which dropped price, how long they sat. Realistic by mid-November: 3,000 to 5,000 raw unique listings, about half surviving cleaning. 2,000 clean rows with this schema is enough for gradient boosting.

Snapshots are not training rows. 1,800 listings scraped daily for 40 days is 72,000 snapshot rows and still 1,800 training examples. Count unique listings.

Rooms-only is thin (309 today). We model rooms and whole units together, with `unit_type` as a feature. Waterloo and Kitchener both.

### Source priority

1. Kijiji, both categories above, KW region (`l1700212`).
2. One of rentals.ca or Zumper for whole units. Both appear to serve listing data as JSON to their own front ends; verify before building a parser.
3. Places4Students for student rooms. Small, but it's the student-specific source.
4. Never Facebook or Instagram. A manual-entry form (Google Form writing to the schema) is how team members capture Facebook-group listings, by reading them as humans.

### Blocking playbook

- Fetch and record `robots.txt` for every source before the first request. Findings go in `docs/sources.md`.
- One worker, one request every 2 to 3 seconds, a realistic User-Agent, no parallelism. A full Kijiji index sweep is about 50 requests. Fetch detail pages only for listings not seen before (about 100 a day). This footprint is small enough that blocking is unlikely.
- Prefer embedded JSON over HTML parsing: look for a `__NEXT_DATA__` script tag or `application/ld+json` blocks before writing CSS selectors.
- Store every raw response gzipped under `data/raw/<source>/<date>/`. Parsers get re-run against raw files when a site changes layout, so history is never lost.
- On 403 or a captcha page: stop for 24 hours, then try the site's own JSON endpoints, then Playwright with a real browser profile as the last resort. If still blocked, drop the site and move on. No proxy rotation, no captcha solving, no more than two hours fighting one site.
- For the user-facing URL path (section 2), the same rules apply with a 10-second timeout, and any failure falls back to pasted text.

### Past data and seasonality

Listing-level history is not available anywhere free. The price model is cross-sectional (what does a unit like this ask for right now), so it doesn't need history. Seasonality is handled three ways:

1. `move_in_month` is a feature. Listings posted in Oct and Nov advertise immediate, January, May and September starts, so the model learns the move-in effect from within-window variation.
2. Wayback Machine index captures give thin rows (title, price, rough location, posted date, bedrooms from the title) across past seasons. Count them first with the CDX API:
   `https://web.archive.org/cdx/search/cdx?url=kijiji.ca/b-apartments-condos/kitchener-waterloo/*&output=json&collapse=timestamp:6`
   If there are a few dozen captures spread across seasons, parse them into a separate `archive_listings` table and use them for a monthly price index in the report, and as a `seasonal_index` feature if it's stable. If there are only a handful, skip it. Fully-featured historical rows exist only in Common Crawl and are a term-2 sub-project.
3. Term 2 collects the January and May seasons for real.

Every Kijiji listing carries its posting date, so the first sweep already tells us how long each active listing has been up.

For sanity checks, CMHC's Rental Market Survey publishes average rents by zone for Kitchener-Cambridge-Waterloo. Our scraped medians should land in the same neighbourhood.

---

## 5. Database

SQLite at `data/housing.db` (gitignored). Move to free-tier Postgres only if the app needs it. Tables:

```sql
listings (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,            -- 'kijiji', 'rentals_ca', 'p4s', 'manual'
  source_id TEXT NOT NULL,         -- the site's own ad id
  url TEXT,
  title TEXT,
  description TEXT,                -- contact info stripped at parse time
  address_text TEXT,
  lat REAL, lon REAL,
  posted_at TEXT,                  -- ISO date from the listing, if shown
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL,            -- 'active', 'gone'
  dedup_key TEXT,                  -- see below
  UNIQUE(source, source_id)
);

snapshots (                        -- one row per scrape per listing
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  scraped_at TEXT NOT NULL,
  price REAL,
  raw_path TEXT                    -- path to the gzipped raw response
);

units (                            -- the schema fields, one row per listing
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  unit_type TEXT, bedrooms INTEGER, bathrooms REAL,
  lease_term TEXT, move_in_month INTEGER,
  utilities_included INTEGER, furnished INTEGER, laundry_in_unit INTEGER,
  building_type TEXT, year_built_after_2018 INTEGER,
  extracted_by TEXT,               -- 'page_attrs', 'regex', 'llm', 'human'
  extracted_at TEXT
);

features (                         -- derived; drop and rebuild freely
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  price_per_bedroom REAL,
  walk_uw_min REAL, walk_laurier_min REAL, ion_distance_m REAL,
  neighbourhood TEXT, days_on_market INTEGER,
  built_at TEXT
);

predictions (                      -- batch scores of active listings per model version
  listing_id INTEGER REFERENCES listings(id),
  model_version TEXT,
  expected REAL, q10 REAL, q90 REAL, percentile REAL,
  scored_at TEXT,
  PRIMARY KEY (listing_id, model_version)
);
```

Dedup: landlords repost constantly with new ad ids, and the same unit appears on several sites. `dedup_key` is normalized address + `unit_type` + `bedrooms`, and two listings with the same key and prices within 5% are the same unit: keep one `listings` row, add a snapshot. Image hashing can tighten this later.

Privacy: strip names, phone numbers and emails from descriptions at parse time. We never store contact info. We never display scraped photos or full descriptions in the app; comparables show our summary plus a link out.

Keep a 100-row `data/sample.csv` committed so a new team member can open the EDA notebook without running the scraper.

---

## 6. Repo layout and conventions

Repo: `github.com/Quaden2307/student-housing-assistant` (transfer to the club org later if they want it).

```
student-housing-assistant/
  CLAUDE.md                  # short conventions, points here
  HANDOFF.md                 # this file
  README.md                  # the project summary from section 1, team-facing
  pyproject.toml             # uv-managed; python >= 3.11
  schema/unit_schema.yaml    # THE contract (section 3)
  src/housing/
    scrape/   fetch.py (rate limit, caching, raw storage), kijiji.py, base.py
    parse/    kijiji.py, text_extract.py (pasted text or description -> schema), pii.py
    db/       schema.sql, migrate.py, queries.py
    geo/      geocode.py (Nominatim, 1 req/s, cached), distances.py, ion_stops.py
    features/ build.py
    model/    baseline.py, train.py, evaluate.py, predict.py, explain.py
    app/      streamlit_app.py, api.py (only if needed)
  notebooks/  01_eda.ipynb 02_baseline.ipynb 03_model.ipynb 04_errors.ipynb 05_calibration.ipynb
  tests/      fixtures/ (saved HTML and JSON), test_parse_kijiji.py, test_text_extract.py, test_features.py
  scripts/    sweep.py (one full scrape of all sources), audit_fields.py, wayback_count.py
  data/       raw/ (gitignored), housing.db (gitignored), sample.csv (committed)
  docs/       sources.md, field_audit.md, decisions.md
```

Conventions:
- Python 3.11+, `uv` for dependencies, `ruff` for lint and format, `pytest`. Type hints and docstrings on public functions.
- Every parser has a fixture test against saved HTML or JSON. That test is the early warning when a site changes layout.
- Scrapers are CLIs: `python -m housing.scrape.kijiji --category rooms --max-pages 2`.
- Notebooks are for exploration. Anything the pipeline depends on lives in `src/` and is imported by the notebook.
- Scheduling: a local cron or launchd job this week; GitHub Actions cron once the sweep is stable. Some sites block GitHub's IP ranges, so expect to fall back to a small VPS or an AWS Lambda on EventBridge.
- A Discord webhook posts "swept N listings, M new, K gone" after every run, and alerts on zero. A silently dead scraper is the usual way this kind of project dies.
- Log every non-trivial decision in `docs/decisions.md` as date, decision, why.

Dev environment: Caden's MacBook Pro (M1, 8 GB RAM). Keep memory light; pandas is fine at this size, no Spark. School H100s are available but only matter for the optional text model in Phase 2.

---

## 7. Modelling plan (Phase 2; do not start before the clean table exists)

- Target: `log(price_per_bedroom)`. Report errors in dollars (MAE) and percent (MAPE), because a $100 miss on a $600 room and on a $2,500 unit are not the same error.
- Baselines, in order: (1) median `price_per_bedroom` by `neighbourhood` and `unit_type`, the lookup table; (2) ridge regression on one-hot categoricals plus numerics.
- Model: LightGBM regression. The default; XGBoost vs LightGBM vs CatBoost is a rounding error at this size, so put effort into features and cleaning instead.
- Range: v1 uses the empirical residual distribution from cross-validation (percentile of `log(asking) - prediction` among held-out residuals; this gives `price_percentile` immediately). v2 trains LightGBM quantile models at alpha 0.1 and 0.9 for a conditional range.
- Splits: `GroupKFold` by `dedup_key` (address) so the model can't memorise a house. Also a time split (train on listings first seen before a date, test on later ones) as a second check.
- Evaluation notebook reports: MAE and MAPE vs both baselines; error by `unit_type`, `neighbourhood`, `lease_term`; coverage of the 10 to 90 range on held-out data (should be about 80%); and the worst 20 residuals inspected by hand.
- Explanations: SHAP values, rendered as the top three drivers in words.
- Optional experiment if time allows, and the one that makes the ML unmistakable at the showcase: add the listing description. Compare (a) the lookup, (b) LightGBM on the schema, (c) LightGBM on the schema plus sentence-transformer embeddings of the description, and optionally (d) a fine-tuned DistilBERT regressor on the text. One results table on the same held-out set. Don't promise (c) or (d) wins; on small data it often doesn't, and showing that is a legitimate finding.

---

## 8. App (Phase 3)

Streamlit. One check page, one methodology page.

Check page: text box for pasted listing or a URL, plus the form underneath. Parse, show the filled form, user confirms, then the verdict card: a horizontal bar from `range_low` to `range_high` with the asking price marked on it, the band, the gap, the three drivers, confidence, and the comparables with links out. Changing a field and re-scoring should be instant (that's the "tweak and re-check" feature; it costs nothing once the form exists).

Methodology page: what the data is, that these are asking prices not paid prices, what the model can't see (condition, landlord, roommates), the held-out error, the last sweep time.

Batch score all active listings after every sweep and write to `predictions`. The comparables query and the drift check both read from it.

Not in scope now: accounts, saved searches, a browse-and-rank mode, alerts, mobile, chat. A browse-and-rank view is the same model scored in batch, so it's cheap later.

---

## 9. Phases and checkpoints

Caden's plan: Phase 1 data collection 1.5 months, Phase 2 model 1 month, Phase 3 UI 0.5 months. Mapped onto the calendar from Oct 5. Phases overlap: the EDA and baseline notebooks start as soon as there's data, and the eval harness is built during Phase 1 against `sample.csv`.

| Phase | Dates | Work | Checkpoint |
|---|---|---|---|
| 1a | Oct 5 to 11 | Repo, DB, first Kijiji sweep, field audit, schema v1, sources.md, Wayback count (section 10) | ~1,800 listings in the DB and a field availability table |
| 1b | Oct 12 to 25 (reading week Oct 12 to 16) | Daily sweep running, detail-page parser, geocoding, dedup, PII stripping, parser tests | Scraper runs unattended with a Discord report |
| 1c | Oct 26 to Nov 15 | Second source, text extraction for lease_term / utilities / furnished, cleaning rules, EDA notebook, baseline, features table | Clean table with N rows, baseline MAE recorded |
| 2 | Nov 16 to Dec 15 (fall exams land in the second half; plan light work then) | LightGBM, grouped CV, error analysis, residual-based percentile, quantile range, calibration, SHAP, optional text experiment | Beats the baseline on held-out listings, range coverage measured, error-analysis notebook written |
| 3 | Dec 16 to early Jan | Streamlit app, methodology page, batch scoring, written report | Live URL where a real listing goes in and a verdict comes out |

Done for term 1 means: that live URL, plus a report showing the model beats the lookup baseline on listings it never saw, with the calibration result.

Team: 5 to 6 people in three pairs (scraping and data; analysis and modelling; app). Everything in the repo, nothing that only one person can run. Club projects lose people by midterms; the fixture tests and `decisions.md` are what let the next person pick up.

---

## 10. This week, Oct 5 to 11: tasks in order

1. Initialise the repo with the layout in section 6: `uv init`, `ruff`, `pytest`, `.gitignore` covering `data/raw/`, `data/housing.db`, `.env`. Push to GitHub.
2. Write `schema/unit_schema.yaml` from section 3, and a tiny loader in `src/housing/schema.py` that the parser and form will import.
3. `db/schema.sql` and `migrate.py` for the tables in section 5. Create `data/housing.db`.
4. `scrape/fetch.py`: rate-limited GET with caching to `data/raw/`, robots.txt check, one User-Agent, retries with backoff, hard stop on 403.
5. `scrape/kijiji.py` + `parse/kijiji.py`: sweep both category index pages (all pages, 40 listings each), parse title, price, location string, posted date, url, bedrooms if present, insert into `listings` and `snapshots`. Target: about 1,800 rows. Record the real count in `docs/sources.md`.
6. Fetch 20 sample detail pages across both categories. Save five of them as fixtures. Write `docs/field_audit.md`: for every schema field, what fraction of the 20 have it, and where it lives (attributes block, embedded JSON, or only in the description text). This table decides what the schema really is.
7. Parser tests against the fixtures.
8. `scripts/wayback_count.py`: hit the CDX API for both index URLs, print capture counts by month, write the result to `docs/sources.md`.
9. Spend at most one hour on a secondary source: find whether rentals.ca or Zumper exposes listing JSON for Waterloo, and note what you find in `docs/sources.md`.
10. Commit `data/sample.csv` (100 parsed rows, PII stripped).

Not this week: modelling, the app, geocoding beyond a smoke test, GitHub Actions. Everything downstream depends on the field audit; building on fields that turn out to be empty is the main way to waste the first month.

---

## 11. Rules for the agent

Ask Caden before:
- Scraping any site not listed in section 4.
- Adding a paid service or anything that needs a credit card.
- Using proxies or browser automation beyond the Playwright fallback described above.
- Changing the schema (section 3) or the DB schema (section 5).
- Committing anything under `data/` other than `sample.csv`.

Never:
- Scrape Facebook or Instagram.
- Solve or bypass captchas, rotate proxies, or spoof beyond a normal User-Agent.
- Store names, phone numbers or emails from listings.
- Display scraped photos or full listing text in the app.
- Count snapshots as training rows.

Working style:
- Code that Caden can read and extend: small modules, type hints, docstrings, no clever metaprogramming. He knows Python, pandas, XGBoost and PyTorch well and has built a scraping pipeline before (a flight-price predictor). Explain anything unusual in a comment.
- When a site blocks you, document it and move on. Two hours maximum per site.
- When a design decision comes up that this file doesn't settle, make the call, log it in `docs/decisions.md`, and flag it in your summary.
- Report at the end of each session: what works, the row count in `listings`, what's blocked, and what's next.

---

## 12. References

- Kijiji KW apartments: `https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212` (1,522 on Sept 29, 2026)
- Kijiji KW rooms: `https://www.kijiji.ca/b-room-rental-roommate/kitchener-waterloo/c36l1700212` (309 on Sept 29, 2026)
- Wayback CDX API: `https://web.archive.org/cdx/search/cdx?url=<url or prefix/*>&output=json&collapse=timestamp:6` (one row per month; drop `collapse` for every capture)
- Nominatim usage policy: one request per second, identify with a User-Agent, cache everything. Addresses repeat, so the cache does most of the work.
- CMHC Rental Market Survey (Kitchener-Cambridge-Waterloo zones) for sanity-checking scraped medians.
- Ontario rent control: units first occupied after Nov 15, 2018 are exempt from the annual guideline, which is why `year_built_after_2018` is a candidate feature.
- Campus coordinates for distance features: UW (43.4723, -80.5449), Laurier (43.4738, -80.5275). ION stop coordinates: hardcode from the GRT GTFS feed.
