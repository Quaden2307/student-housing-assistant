# Pipeline: how a listing becomes rows, features and (later) a verdict

Written 2026-10-14, revised 2026-10-16 after the review. Describes what is built and how it writes
to the database. `HANDOFF.md` remains the contract; `docs/decisions.md` records every call made here.

## 1. Lanes into the one SQLite database

| Lane | What | Cadence | State |
|---|---|---|---|
| 1. Current | Kijiji KW index sweep, both categories, through the embedded page JSON; detail pages for the full text; everything below | Daily, 06:30 via launchd | Built |
| 2. Historical | Wayback captures of the same index pages (2014 to 2017 and 2024 on) into a separate `archive_listings` table, for a monthly price index. Mark's lane | One-off backfill, paced at one request per 15 to 20 s | Planned; see `docs/sources.md` section 7 |
| 3. Manual | A Google Form for Facebook-group listings read by people, written with `source = 'manual'` | Ongoing | Planned |
| 4. Reference | Campus coordinates, ION stations (hardcoded from GTFS), CMHC and asking-rent anchors for sanity checks | Once | Built where needed |

## 2. The daily run

`scripts/sweep.py` calls `housing.scrape.daily.run`, which does these steps in order and never
stops on a site problem without reporting it.

| Step | Module | Reads | Writes | Requests |
|---|---|---|---|---|
| Index sweep, apartments then rooms | `scrape.kijiji.sweep` | index pages (40 cards each), always fetched fresh | `listings` upsert, one `snapshots` row per listing, every card attribute into `listing_attributes` | about 48 |
| Gone rule | `db.queries.mark_gone` | `listings.last_seen` | `status = 'gone'` for active listings last seen over 40 h ago, only when both sweeps were complete: last page reached within the cap, at least 90 percent of the site's count seen, pagination advancing | 0 |
| Details | `scrape.kijiji.fetch_details` | pending listings (no `detail_fetched_at`), rooms first, newest first; failed ones retried after 3 days | `listings.description` (contact details stripped), address, coordinates and posting date fill gaps, detail attributes, `image_count`, `views`, `end_date`, `detail_status`, `poster_hash`; a removed ad gets `detail_error = removed`; the pass stops after 3 failures in a row | up to 300 |
| Extraction | `parse.extract.extract_all` | title, description, attributes | `units` (rewritten for every listing), `text_*` flags into `listing_attributes` | 0 |
| Features | `features.build.build_features` | listings, units, latest snapshot price | `features`, dropped and rebuilt | 0 |
| Report | `scrape.daily.DailyReport`, `notify.discord` | the counts above | stdout, Discord (`DISCORD_WEBHOOK_URL`) | 1 |

Rate and safety (`scrape.fetch.Fetcher`): one worker, 2 to 3 s between requests, one desktop
User-Agent, robots.txt re-read each run with wildcard matching (a 5xx on robots.txt stops the
run), three attempts on connection errors and 5xx, a hard stop on 403, 429 or a challenge page
whatever its status code (exit code 2: wait 24 hours).

Raw storage: every response is scrubbed (poster name and phone nulled, listing text stripped
of contact details) and gzipped under `data/raw/kijiji/<YYYY-MM-DD>/` with a `.meta.json`
beside it (`index_<category>_p<N>`, `detail_<ad id>`, `robots.txt`). Detail pages are served
from that file on a repeat request the same day, so parsers can be re-run offline and an
interrupted details pass resumes without new requests; index pages are always refetched so
every snapshot is a real sighting.

Exit codes: 0 ok; 1 the run crashed (traceback in `logs/`); 2 blocked; 3 a page did not parse
or a sweep was incomplete (nothing marked gone); 4 the network or site failed for good. Every
outcome is printed and posted to Discord, with an `ALERT` prefix when a human should look.

### Running it

```sh
uv run python scripts/sweep.py                      # the whole daily run
uv run python -m housing.scrape.kijiji --details 50 # sweep only, plus 50 detail pages
uv run python -m housing.parse.extract --all        # re-run the extraction rules
uv run python -m housing.features.build             # rebuild derived features
sh scripts/install_launchd.sh                       # schedule it daily on this Mac
```

## 3. Write rules

- **Identity.** A listing is `(source, source_id)`. Seen again: `last_seen` moves, status returns
  to `active`, null values never overwrite known ones, `posted_at` keeps its first value
  (Kijiji's `activationDate`, the first posting; bumps are ignored).
- **Snapshots.** One row per listing per run, price from the index card in dollars, null for
  "Please Contact", `raw_path` pointing at the index page. Promoted ads that repeat across
  pages get one row.
- **Attributes.** `listing_attributes(listing_id, name, value)`: Kijiji's canonical names as
  they come (`numberbedrooms`, `agreementtype`, `heat`...), multi-valued joined with `|`, plus
  ours: `category`, `price_type`, `ad_source`, `sorting_date`, `neighbourhood_name`,
  `intersection`, `image_count`, `views`, `end_date`, `poster_hash`, `detail_fetched_at`,
  `detail_raw_path`, `detail_error`, and the extraction flags `text_per_room_price`,
  `text_is_takeover`, `text_bathroom_private`, `text_available_now`, `text_internet_included`,
  `text_building_name`.
- **Units.** One row per listing, rewritten on every run from the rules in
  `housing.parse.units`, so a rule change propagates everywhere with `--all`. `extracted_by`
  is `page_attrs` when the bedroom count came from attributes, else `regex`.
- **Features.** Dropped and rebuilt every run.
- **Privacy.** Emails (also written out), phone numbers (also spaced or spelled out), names
  after contact phrases and sign-offs are stripped from titles and descriptions before they
  are stored, and the URL slug is redacted the same way; poster names and phone fields are
  never read; poster ids are stored only as a salted hash (`HOUSING_HASH_SALT`, mandatory).
  Raw pages are scrubbed on the way in. Photos are never stored. `scripts/restrip.py`
  re-applies the rules to stored rows after they get stricter.
- **Formats.** Timestamps are ISO 8601 UTC (`2026-10-14T20:00:00Z`), dates `YYYY-MM-DD`,
  booleans 0, 1 or null.

## 4. Features

The target is `price_per_bedroom`: the asking price for a `room`, else price divided by
bedrooms, modelled on its log. The asking price is never a feature.

A feature earns its place only if the app can obtain it at prediction time from pasted text,
the form or a URL. Tier A is the model's input space; tier B exists for analysis and the report.

### Tier A: model inputs

| Feature | Source | Where it lives | Notes and hypotheses from `docs/market.md` |
|---|---|---|---|
| `unit_type` | attributes, text rules, category | `units` | per-room ads under apartments are reclassified as `room` |
| `bedrooms` | attributes, text | `units` | a room's value is the house total; studio stored as 1 |
| `bathrooms` | attributes, text | `units` | |
| `lease_term` | text first, then `agreementtype` | `units` | sublets ask 20 to 33 percent less; 8-month about 5 percent more |
| `move_in_month` | `dateavailable`, text | `units` | the Sept, Jan, May cycle; stored only when stated |
| `utilities_included` | heat, hydro, water flags, text | `units` | internet excluded on purpose |
| `furnished` | attribute, text | `units` | |
| `laundry_in_unit` | attributes, text | `units` | |
| `building_type` | registry, wording, unit type | `units` | purpose-built towers price per bed with ensuites |
| `year_built_after_2018` | registry years, "new build" text | `units` | rent-control exemption; CMHC shows post-2000 stock renting about 32 percent above 1980s stock in Waterloo |
| `walk_uw_min`, `walk_laurier_min` | coordinates | `features` | straight line at 80 m per minute; the nearer campus matters most |
| `ion_distance_m` | coordinates, 19 stations | `features` | |
| `neighbourhood` | postal prefix in the address | `features` | N2L holds both campuses; CMHC's "Waterloo University" 2-bed rents 15 percent above Uptown |
| `sqft` | `areainfeet` | `listing_attributes` | on about 85 percent of apartments cards; `0` means not given |
| `text_bathroom_private` | text | `listing_attributes` | ensuite rooms ask $1,050 to $1,350 versus $610 to $1,000 |
| `text_is_takeover` | text | `listing_attributes` | a takeover inherits an older rent |
| `text_internet_included` | attribute, text | `listing_attributes` | internet is the item most often excluded from "all inclusive" |
| `petsallowed`, `numberparkingspots`, `airconditioning`, `dishwasher`, `balcony`, `elevator`, `gym` | attributes | `listing_attributes` | candidates; each is one more form field, so they must earn a place in the error analysis |
| `forrentbyhousing` | attribute | `listing_attributes` | professional versus owner; correlates with purpose-built buildings |
| listing month | `first_seen` at training, today at scoring | derived in the notebook | seasonality of asking prices within the window |

### Tier B: analysis only, never model inputs

`days_on_market` (needs the posting date, absent for a pasted listing), `image_count`,
`views`, `ad_source`, `price_type`, price drops across snapshots, `poster_hash` (dedup),
`detail_fetched_at`. They go into the report and the dedup logic, not the model, because
the model would train on signals it never sees at prediction time.

### Cleaning rules for the training view

Applied when building the clean table (Sprint 2), not in the raw tables:

| Trap | Rule |
|---|---|
| Out-of-region listings in the KW index | drop outside about lat 43.36 to 43.56, lon -80.65 to -80.35 |
| No price (`price_type = CONTACT`) | drop |
| Attribute garbage | bedrooms 1 to 8, bathrooms 1 to 6, room price $300 to $1,800, per-bedroom price $300 to $3,000 |
| Per-term or per-contract totals | text with "per term", "per semester", "4 months for": convert or drop |
| Wanted ads | titles starting "Looking for", "Wanted", "Seeking" |
| Reposts and bumps | dedup key from normalized address, unit type and bedrooms (plus `poster_hash` as a tiebreaker); one row per key; `posted_at` from the earliest ad in the group |
| Gender-restricted rooms | not stored, not a feature |

## 5. Dedup and splits (Sprint 2)

`dedup_key` = normalized address (lowercase, unit numbers stripped, or coordinates rounded
to about 50 m when there is no street number) + `unit_type` + `bedrooms`. Two listings with
the same key and prices within 5 percent are the same unit. Every ad keeps its own
`listings` row; training uses one row per key, cross-validation groups by key, and
comparables show the most recent ad of each unit.

## 6. Maintenance scripts

`scripts/make_fixture.py` copies a raw page into `tests/fixtures/` with poster ids and client
identifiers replaced. `scripts/scrub_raw.py` scrubs pages saved before the fetcher did it.
`scripts/restrip.py` re-applies the contact-stripping rules to stored rows.
`scripts/export_sample.py` writes the committed 100-row `data/sample.csv`.

## 7. What is not built yet

Dedup, the clean training view, the manual form, the Wayback lane, geocoding for sources
without coordinates, and everything from HANDOFF Phase 2 on.
