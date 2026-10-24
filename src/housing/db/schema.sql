-- Student Housing Assistant database. This is the DDL from HANDOFF.md section 5
-- and it is a contract: change it only with Caden's sign-off and a line in
-- docs/decisions.md. Applied by `uv run python -m housing.db.migrate`; every
-- statement uses IF NOT EXISTS so re-running it is harmless.
--
-- Conventions: TEXT timestamps are ISO 8601 in UTC ("2026-10-05T14:03:00Z");
-- date-only columns (posted_at) are "YYYY-MM-DD"; booleans are 0, 1 or NULL.

CREATE TABLE IF NOT EXISTS listings (
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
  dedup_key TEXT,                  -- normalized address + unit_type + bedrooms
  UNIQUE(source, source_id)
);

-- One row per scrape per listing. Snapshots are history, never training rows.
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  scraped_at TEXT NOT NULL,
  price REAL,
  raw_path TEXT                    -- path to the gzipped raw response
);

-- The unit schema fields (HANDOFF section 3), one row per listing.
CREATE TABLE IF NOT EXISTS units (
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  unit_type TEXT, bedrooms INTEGER, bathrooms REAL,
  lease_term TEXT, move_in_month INTEGER,
  utilities_included INTEGER, furnished INTEGER, laundry_in_unit INTEGER,
  building_type TEXT, year_built_after_2018 INTEGER,
  extracted_by TEXT,               -- 'page_attrs', 'regex', 'llm', 'human'
  extracted_at TEXT
);

-- Derived from listings + units; drop and rebuild freely.
CREATE TABLE IF NOT EXISTS features (
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  price_per_bedroom REAL,
  walk_uw_min REAL, walk_laurier_min REAL, ion_distance_m REAL,
  neighbourhood TEXT, days_on_market INTEGER,
  built_at TEXT
);

-- Batch scores of active listings, one row per listing per model version.
CREATE TABLE IF NOT EXISTS predictions (
  listing_id INTEGER REFERENCES listings(id),
  model_version TEXT,
  expected REAL, q10 REAL, q90 REAL, percentile REAL,
  scored_at TEXT,
  PRIMARY KEY (listing_id, model_version)
);

-- ---------------------------------------------------------------------------
-- Auxiliary tables. Not part of the HANDOFF section 5 contract; added by
-- decisions logged in docs/decisions.md. They hang off listings.id and can be
-- rebuilt from the raw pages at any time.
-- ---------------------------------------------------------------------------

-- Every raw attribute a source exposes for a listing, plus our own flags
-- (poster_hash, per_room_price, ...), so features can be added later without
-- widening `units`. One row per (listing, name); multi-valued joined with '|'.
CREATE TABLE IF NOT EXISTS listing_attributes (
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  name TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (listing_id, name)
);

-- Wayback Machine backfill (lane 2; HANDOFF section 4 names "a separate archive_listings
-- table"). Outside the section 5 contract, added at schema version 3 and pending Caden's
-- sign-off. Archived index pages feed a historical price index; they are never training
-- rows. Prices are stored as listed (nominal dollars) with their dates; any adjustment for
-- inflation or market drift happens at analysis time, never in these tables.

-- One row per archived index page: the backfill's work queue and its provenance.
CREATE TABLE IF NOT EXISTS archive_captures (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,         -- Wayback's 14-digit capture time, UTC
  original TEXT NOT NULL,          -- the archived Kijiji URL
  category TEXT NOT NULL,          -- 'apartments' or 'rooms'
  page INTEGER NOT NULL,
  captured_at TEXT NOT NULL,       -- the same time as ISO 8601 UTC
  status TEXT NOT NULL,            -- 'pending', 'parsed', 'unsupported', 'failed'
  format TEXT,                     -- 'nextjs', 'nextjs_v2', 'html_cards', 'unknown'
  cards INTEGER,
  total_count INTEGER,             -- Kijiji's own listing count for the category then
  raw_path TEXT,
  fetched_at TEXT,
  error TEXT,
  UNIQUE(timestamp, original)
);

-- One row per ad per capture it appears in: the archive's equivalent of snapshots.
CREATE TABLE IF NOT EXISTS archive_sightings (
  capture_id INTEGER NOT NULL REFERENCES archive_captures(id),
  source_id TEXT NOT NULL,         -- Kijiji ad id
  price REAL,                      -- dollars per month as listed; null for "Please Contact"
  ad_source TEXT,                  -- 'ORGANIC' or 'TOP_AD'
  sorting_date TEXT,               -- last bump, ISO UTC
  PRIMARY KEY (capture_id, source_id)
);

-- One row per Kijiji ad seen in any capture. Counts and indexes use these rows, never
-- sightings, so an ad that sat unrented for weeks still counts once.
CREATE TABLE IF NOT EXISTS archive_listings (
  source_id TEXT PRIMARY KEY,
  category TEXT,
  url TEXT,
  title TEXT,                      -- contact details stripped
  address_text TEXT,
  lat REAL, lon REAL,              -- null for 2024-era captures, which carry no coordinates
  posted_at TEXT,                  -- Kijiji activationDate (first posting), YYYY-MM-DD
  first_seen TEXT NOT NULL,        -- earliest capture showing the ad
  last_seen TEXT NOT NULL,         -- latest capture showing the ad
  sightings INTEGER NOT NULL DEFAULT 0,
  first_price REAL,                -- price at first_seen
  last_price REAL,                 -- price at last_seen
  min_price REAL,
  max_price REAL,
  poster_hash TEXT,                -- salted hash, as in listing_attributes
  attributes TEXT,                 -- JSON: Kijiji canonical attribute name -> list of values
  in_live INTEGER NOT NULL DEFAULT 0  -- 1 if the daily sweep has the same ad id
);
