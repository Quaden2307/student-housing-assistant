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
