"""The Phase 1c clean training table (HANDOFF sections 3 and 7).

:func:`load_training` turns the raw tables into the one DataFrame the notebooks,
baselines and models consume. The model target is ``price_per_bedroom``: the
asking price for a ``room``, else the asking price divided by bedrooms (HANDOFF
section 3). The asking price and the target are never model inputs; the input
space is :data:`CATEGORICALS` + :data:`NUMERICS` + :data:`BOOLEANS`, and
:data:`GROUP` (the dedup key) is the cross-validation grouping column so a model
never sees the same house in both train and test (docs/pipeline.md section 5).

Reads only: this module never writes to any table.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

import pandas as pd

from housing.features.build import price_per_bedroom
from housing.geo.distances import walk_laurier_min, walk_uw_min
from housing.geo.ion_stops import nearest_ion_stop
from housing.geo.regions import REGIONS, in_region
from housing.parse.kijiji import LOCATION
from housing.parse.units import extract as extract_unit

TARGET = "price_per_bedroom"
"""The model target (HANDOFF section 3). Never a model input."""

GROUP = "dedup_key"
"""Grouping column for cross-validation splits and dedup."""

CATEGORICALS = [
    "unit_type",
    "lease_term",
    "building_type",
    "neighbourhood",
    "city",
    "landlord_type",
]
"""Categorical model inputs (str or NA)."""

NUMERICS = [
    "bedrooms",
    "bathrooms",
    "sqft",
    "walk_uw_min",
    "walk_laurier_min",
    "ion_distance_m",
    "move_in_month",
    "listing_month",
    "listing_year",
]
"""Numeric model inputs (NaN / NA allowed)."""

BOOLEANS = [
    "utilities_included",
    "furnished",
    "laundry_in_unit",
    "year_built_after_2018",
    "bathroom_private",
    "is_takeover",
    "internet_included",
]
"""Boolean model inputs (pandas ``boolean`` dtype, NA allowed)."""

# Cleaning bounds from docs/pipeline.md section 4 ("Cleaning rules for the training view").
# The out-of-region rule checks each listing against its own market's box (geo.regions).
_BEDROOM_BOUNDS = (1, 8)
_BATHROOM_BOUNDS = (1, 6)
_TARGET_BOUNDS = (300.0, 3000.0)
_ROOM_PRICE_BOUNDS = (300.0, 1800.0)
_WANTED_PREFIXES = ("looking for", "wanted", "seeking")
# Per-term and per-contract totals are not monthly prices. docs/pipeline.md section 4
# says convert or drop; we drop, because the term length is usually unstated and a
# guessed conversion would plant a wrong-but-plausible target (docs/decisions.md
# 2026-10-23). Matched on the title and the description together.
_PER_TERM_RE = re.compile(
    r"per\s+(?:school\s+)?(?:term|semester)\b"  # "$2,400 per term", "per semester"
    r"|/\s*(?:term|semester)\b"  # "2400/term"
    r"|per\s+\d{1,2}\s*months?\b"  # "per 4 months"
    r"|\b\d{1,2}\s*months?\s+for\s+\$?\s*\d{3,}",  # "4 months for $2400"
    re.IGNORECASE,
)
# The 5-percent clause of HANDOFF section 5: same dedup key and prices within 5 percent
# is the same unit. Prices further apart under one key (two different rooms in one
# house) stay separate training rows.
_SAME_UNIT_PRICE_RATIO = 1.05

# Column -> dtype of the returned frame, in contract order. "str" is pandas 3's
# string dtype (missing stays missing); "Int64" and "boolean" are the nullable kinds.
_DTYPES: dict[str, str] = {
    "listing_id": "int64",
    "dedup_key": "str",
    "price": "float64",
    "price_per_bedroom": "float64",
    "unit_type": "str",
    "lease_term": "str",
    "building_type": "str",
    "neighbourhood": "str",
    "landlord_type": "str",
    "bedrooms": "Int64",
    "bathrooms": "float64",
    "sqft": "float64",
    "walk_uw_min": "float64",
    "walk_laurier_min": "float64",
    "ion_distance_m": "float64",
    "move_in_month": "Int64",
    "utilities_included": "boolean",
    "furnished": "boolean",
    "laundry_in_unit": "boolean",
    "year_built_after_2018": "boolean",
    "bathroom_private": "boolean",
    "is_takeover": "boolean",
    "internet_included": "boolean",
    "listing_month": "Int64",
    "listing_year": "Int64",
    "city": "str",
    "first_seen": "str",
    "last_seen": "str",
    "is_archive": "boolean",
}

COLUMNS = list(_DTYPES)
"""Columns of the returned frame, in order."""

# One join over everything a training row needs. Both 'active' and 'gone' listings are
# usable history (a gone ad's last asking price is still an observation), so no status
# filter. The price is the latest non-null snapshot price per listing; the target is
# recomputed from it below rather than read from features.price_per_bedroom, so the
# frame is internally consistent even when the features table is stale.
_QUERY = """
WITH latest_price AS (
    SELECT listing_id, price FROM (
        SELECT listing_id, price,
               ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY scraped_at DESC, id DESC) AS rn
        FROM snapshots
        WHERE price IS NOT NULL
    )
    WHERE rn = 1
),
attrs AS (
    SELECT listing_id,
           MAX(CASE WHEN name = 'areainfeet' THEN value END) AS areainfeet,
           MAX(CASE WHEN name = 'forrentbyhousing' THEN value END) AS landlord_type,
           MAX(CASE WHEN name = 'text_bathroom_private' THEN value END) AS bathroom_private,
           MAX(CASE WHEN name = 'text_is_takeover' THEN value END) AS is_takeover,
           MAX(CASE WHEN name = 'text_internet_included' THEN value END) AS internet_included,
           MAX(CASE WHEN name = 'category' THEN value END) AS category,
           MAX(CASE WHEN name = 'location' THEN value END) AS location
    FROM listing_attributes
    GROUP BY listing_id
)
SELECT l.id AS listing_id, l.dedup_key, l.title, l.description, l.lat, l.lon,
       l.first_seen, l.last_seen,
       p.price,
       u.unit_type, u.bedrooms, u.bathrooms, u.lease_term, u.move_in_month,
       u.utilities_included, u.furnished, u.laundry_in_unit,
       u.building_type, u.year_built_after_2018,
       f.walk_uw_min, f.walk_laurier_min, f.ion_distance_m, f.neighbourhood,
       a.areainfeet, a.landlord_type, a.bathroom_private, a.is_takeover,
       a.internet_included, a.category, a.location
FROM listings l
LEFT JOIN units u ON u.listing_id = l.id
LEFT JOIN features f ON f.listing_id = l.id
LEFT JOIN latest_price p ON p.listing_id = l.id
LEFT JOIN attrs a ON a.listing_id = l.id
"""


@dataclass
class CleaningReport:
    """Counts from one :func:`load_training` call: drops per rule, plus rows kept.

    ``bathrooms_cleared`` rows are kept; only the out-of-range bathroom value is
    set to NA. Every other count is dropped rows, counted once each, at the
    first rule a row fails.
    """

    no_price: int = 0
    no_location: int = 0
    out_of_region: int = 0
    wanted_ad: int = 0
    per_term_price: int = 0
    bad_bedrooms: int = 0
    no_target: int = 0
    target_out_of_range: int = 0
    room_price_out_of_range: int = 0
    duplicates: int = 0
    bathrooms_cleared: int = 0
    kept: int = 0
    archive_in: int = 0
    """Archive rows that entered cleaning (``include_archive=True`` only)."""

    def __str__(self) -> str:
        drops = (
            ("no_price", self.no_price),
            ("no_location", self.no_location),
            ("out_of_region", self.out_of_region),
            ("wanted_ad", self.wanted_ad),
            ("per_term_price", self.per_term_price),
            ("bad_bedrooms", self.bad_bedrooms),
            ("no_target", self.no_target),
            ("target_out_of_range", self.target_out_of_range),
            ("room_price_out_of_range", self.room_price_out_of_range),
            ("duplicates", self.duplicates),
        )
        dropped = ", ".join(f"{name}={count}" for name, count in drops)
        total = sum(count for _, count in drops)
        text = (
            f"clean table: kept {self.kept} rows; dropped {total} ({dropped});"
            f" bathrooms set NA on {self.bathrooms_cleared}"
        )
        if self.archive_in:
            text += f"; archive rows in: {self.archive_in}"
        return text


def _bools(values: pd.Series, missing: bool | None) -> pd.Series:
    """Map a raw column (0/1 ints or '1' text flags) to nullable booleans.

    Args:
        values: Raw column values.
        missing: What an absent value means: False for text detections, None
            (pd.NA) where absence is genuinely unknown.
    """

    def one(value: object) -> bool | None:
        if value is None or pd.isna(value):
            return missing
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes")
        return bool(value)

    return pd.Series(pd.array([one(v) for v in values], dtype="boolean"), index=values.index)


def _drop(df: pd.DataFrame, mask: pd.Series, report: CleaningReport, rule: str) -> pd.DataFrame:
    """Drop the rows ``mask`` marks and record the count on ``report.<rule>``."""
    mask = mask.fillna(False).astype(bool)
    setattr(report, rule, int(mask.sum()))
    return df.loc[~mask]


def _empty_frame() -> pd.DataFrame:
    """The contract columns and dtypes with zero rows."""
    return pd.DataFrame({column: pd.Series(dtype=dtype) for column, dtype in _DTYPES.items()})


_ARCHIVE_QUERY = """
SELECT source_id, category, title, address_text, lat, lon,
       first_seen, last_seen, last_price, attributes, neighbourhood
FROM archive_listings
WHERE in_live = 0 AND last_price IS NOT NULL
"""


def _archive_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    """The Wayback archive rows shaped like the live query's output, before cleaning.

    Each row re-runs the live pipeline's unit extraction
    (:func:`housing.parse.units.extract`) over the stored attribute JSON and the title,
    so an archive row's bedrooms, unit type and booleans mean exactly what a live row's
    do. Ads the live sweep also has (``in_live = 1``) and ads without a price are
    excluded up front. ``listing_id`` is a negative ordinal: these rows live in
    ``archive_listings``, not ``listings``, and a negative id can never collide with a
    real listing id in one frame. Every archive row is Kitchener-Waterloo; the lane
    only backfills the KW index pages.
    """
    rows = []
    for ordinal, row in enumerate(conn.execute(_ARCHIVE_QUERY), start=1):
        (
            source_id,
            category,
            title,
            address,
            lat,
            lon,
            first_seen,
            last_seen,
            price,
            attributes_json,
            neighbourhood,
        ) = row
        try:
            raw = json.loads(attributes_json) if attributes_json else {}
        except ValueError:
            raw = {}
        attrs = {name: "|".join(str(v) for v in values) for name, values in raw.items()}
        unit = extract_unit(
            category=category or "apartments",
            title=title or "",
            description=None,
            attributes=attrs,
            address=address,
        )
        in_kw = REGIONS[LOCATION].contains(lat, lon)
        rows.append(
            {
                "listing_id": -ordinal,
                "dedup_key": f"archive:{source_id}",
                "title": title,
                "description": None,
                "lat": lat,
                "lon": lon,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "price": price,
                "unit_type": unit.unit_type,
                "bedrooms": unit.bedrooms,
                "bathrooms": unit.bathrooms,
                "lease_term": unit.lease_term,
                "move_in_month": unit.move_in_month,
                "utilities_included": unit.utilities_included,
                "furnished": unit.furnished,
                "laundry_in_unit": unit.laundry_in_unit,
                "building_type": unit.building_type,
                "year_built_after_2018": unit.year_built_after_2018,
                "walk_uw_min": walk_uw_min(lat, lon) if in_kw else None,
                "walk_laurier_min": walk_laurier_min(lat, lon) if in_kw else None,
                "ion_distance_m": nearest_ion_stop(lat, lon)[1] if in_kw else None,
                "neighbourhood": neighbourhood,
                "areainfeet": attrs.get("areainfeet"),
                "landlord_type": attrs.get("forrentbyhousing"),
                "bathroom_private": unit.flags.get("bathroom_private"),
                "is_takeover": unit.flags.get("is_takeover"),
                "internet_included": unit.flags.get("internet_included"),
                "category": category,
                "location": LOCATION,
                "is_archive": True,
            }
        )
    return pd.DataFrame(rows, dtype=object)


def load_training(
    conn: sqlite3.Connection, *, dedup: bool = True, include_archive: bool = False
) -> tuple[pd.DataFrame, CleaningReport]:
    """Build the Phase 1c clean training table.

    Joins ``listings`` (active and gone alike -- both are usable history, a gone
    ad's last asking price is still an observation), ``units``, ``features``,
    the latest non-null snapshot price per listing and the modelled
    ``listing_attributes`` (``areainfeet`` -> ``sqft``, ``forrentbyhousing`` ->
    ``landlord_type``, the ``text_*`` flags, and ``category``), then applies the
    cleaning rules of docs/pipeline.md section 4 and counts each one in a
    :class:`CleaningReport`.

    Conventions decided here (see also docs/decisions.md):

    * ``text_is_takeover`` and ``text_bathroom_private`` are detections the
      extractor writes only when the text states them, so a missing flag means
      False, not unknown. ``text_internet_included`` absence stays NA: silence
      about internet is genuinely ambiguous.
    * A rooms-category ad with no extracted ``unit_type`` is still a room ad,
      so ``category = 'rooms'`` backfills ``unit_type = 'room'``.
    * ``areainfeet`` of 0 or non-numeric means "not given" on Kijiji -> NA.
    * Rows with no coordinates at all are dropped under their own
      ``no_location`` counter, not ``out_of_region``: a missing location is a
      geocoding gap, not evidence the unit sits outside KW.
    * Per-term and per-contract totals ("per term", "per semester", "4 months
      for $2400" in the title or description) are dropped, not converted, and
      counted as ``per_term_price``.
    * Bedrooms present but outside 1..8 drops the row; bathrooms present but
      outside 1..6 only clears the value, because a garbage bathroom count does
      not make the price wrong.
    * Rows with no dedup key get the per-row sentinel ``listing:<listing_id>``,
      so each keyless ad is its own unit for dedup *and* its own CV group
      (``GroupKFold`` refuses NaN groups).
    * ``dedup=True`` keeps the most recent ad (max ``last_seen``, ties to max
      ``listing_id``) per dedup key *and 5-percent price band*: same key with
      prices within 5 percent is the same unit (HANDOFF section 5); same key
      with prices further apart (two different rooms in one house) stays
      separate training rows that still share the CV group.

    Args:
        conn: Open database connection; nothing is written to it.
        dedup: Keep one row per dedup key (the default for training). Pass
            False to keep every surviving ad, e.g. for the EDA notebook.
        include_archive: Also load the Wayback archive rows as training rows
            (docs/decisions.md 2026-11-06; off by default). Archive rows are
            index-card data only: no walk times for most, no description, and
            prices from their own era, which is why ``listing_year`` is a model
            input. Ads the live sweep also has (``in_live = 1``) are excluded,
            and the location rules are waived for archive rows because their
            provenance (the KW index pages) already fixes the market.

    Returns:
        The clean frame (columns and dtypes exactly :data:`COLUMNS` /
        the contract) and the cleaning report.
    """
    report = CleaningReport()
    cursor = conn.execute(_QUERY)
    names = [description[0] for description in cursor.description]
    df = pd.DataFrame([tuple(row) for row in cursor.fetchall()], columns=names, dtype=object)
    df["is_archive"] = False
    if include_archive:
        archive = _archive_frame(conn)
        report.archive_in = len(archive)
        if not archive.empty:
            df = pd.concat([df, archive], ignore_index=True) if not df.empty else archive
    if df.empty:
        return _empty_frame(), report

    # Typed columns first, so the rules below compare numbers, not SQLite TEXT.
    floats = (
        "price",
        "lat",
        "lon",
        "bathrooms",
        "walk_uw_min",
        "walk_laurier_min",
        "ion_distance_m",
    )
    for column in floats:
        df[column] = pd.to_numeric(df[column], errors="coerce").astype("float64")
    for column in ("bedrooms", "move_in_month"):
        df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
    sqft = pd.to_numeric(df["areainfeet"], errors="coerce")
    df["sqft"] = sqft.where(sqft > 0).astype("float64")
    df["unit_type"] = df["unit_type"].where(
        df["unit_type"].notna(),
        df["category"].map(lambda c: "room" if c == "rooms" else None),
    )
    df["listing_month"] = pd.to_numeric(
        df["first_seen"].astype("str").str[5:7], errors="coerce"
    ).astype("Int64")
    df["listing_year"] = pd.to_numeric(
        df["first_seen"].astype("str").str[:4], errors="coerce"
    ).astype("Int64")
    # Pre-expansion listings carry no location attribute; they are all Kitchener-Waterloo.
    df["city"] = df["location"].where(df["location"].notna(), LOCATION)
    for column in (
        "utilities_included",
        "furnished",
        "laundry_in_unit",
        "year_built_after_2018",
        "internet_included",
    ):
        df[column] = _bools(df[column], missing=None)
    for column in ("bathroom_private", "is_takeover"):
        df[column] = _bools(df[column], missing=False)

    # Drop rules, in docs/pipeline.md order; each row counted once. The two location
    # rules only bind live rows: an archive row's market is fixed by its provenance
    # (the KW index pages) and most archive captures carry no coordinates at all.
    df = _drop(df, df["price"].isna(), report, "no_price")
    # No coordinates is a geocoding gap, not an out-of-region unit; count it apart so
    # the report shows what missing locations cost (lat/lon are required by section 3).
    live = ~df["is_archive"].astype(bool)
    df = _drop(df, live & (df["lat"].isna() | df["lon"].isna()), report, "no_location")
    live = ~df["is_archive"].astype(bool)
    in_box = pd.Series(
        [
            in_region(city, lat, lon)
            for city, lat, lon in zip(df["city"], df["lat"], df["lon"], strict=True)
        ],
        index=df.index,
    )
    df = _drop(df, live & ~in_box, report, "out_of_region")
    title = df["title"].astype("str").str.strip().str.lower()
    df = _drop(df, title.str.startswith(_WANTED_PREFIXES), report, "wanted_ad")
    # Per-term totals would train as monthly prices with inflated targets, so the rule
    # runs before the target bounds, which a $2,400-per-term ad can otherwise pass.
    text = (
        df["title"].astype("str").fillna("") + " " + df["description"].astype("str").fillna("")
    ).str.lower()
    df = _drop(df, text.str.contains(_PER_TERM_RE), report, "per_term_price")
    bad_bedrooms = df["bedrooms"].notna() & ~df["bedrooms"].between(*_BEDROOM_BOUNDS)
    df = _drop(df, bad_bedrooms, report, "bad_bedrooms")

    bad_bathrooms = df["bathrooms"].notna() & ~df["bathrooms"].between(*_BATHROOM_BOUNDS)
    report.bathrooms_cleared = int(bad_bathrooms.sum())
    df.loc[bad_bathrooms, "bathrooms"] = float("nan")

    df[TARGET] = pd.array(
        [
            price_per_bedroom(
                None if pd.isna(price) else float(price),
                None if pd.isna(unit_type) else unit_type,
                None if pd.isna(bedrooms) else int(bedrooms),
            )
            for price, unit_type, bedrooms in zip(
                df["price"], df["unit_type"], df["bedrooms"], strict=True
            )
        ],
        dtype="float64",
    )
    df = _drop(df, df[TARGET].isna(), report, "no_target")
    df = _drop(df, ~df[TARGET].between(*_TARGET_BOUNDS), report, "target_out_of_range")
    room_bad = (df["unit_type"] == "room") & ~df["price"].between(*_ROOM_PRICE_BOUNDS)
    df = _drop(df, room_bad, report, "room_price_out_of_range")

    # A row with no dedup key is its own unit (docs/decisions.md 2026-10-23): a per-row
    # sentinel makes that hold everywhere at once -- the dedup below, nunique() counts
    # and GroupKFold, which refuses NaN groups outright.
    missing_key = df[GROUP].isna()
    df.loc[missing_key, GROUP] = "listing:" + df.loc[missing_key, "listing_id"].astype("str")

    if dedup:
        # HANDOFF section 5's 5-percent clause: within a key, sort by price and start a
        # new band when an ad asks more than 5 percent above the previous one (chained,
        # so $600/$615/$640 stay one band). Each band keeps its most recent ad; ISO 8601
        # UTC strings sort lexicographically in time order (docs/decisions.md).
        by_price = df.sort_values([GROUP, "price"], kind="stable")
        previous = by_price.groupby(GROUP)["price"].shift()
        band_start = previous.isna() | (by_price["price"] > previous * _SAME_UNIT_PRICE_RATIO)
        bands = band_start.groupby(by_price[GROUP]).cumsum()
        newest = (
            df.assign(_price_band=bands)
            .sort_values(["last_seen", "listing_id"], kind="stable")
            .drop_duplicates([GROUP, "_price_band"], keep="last")
        )
        report.duplicates = len(df) - len(newest)
        df = df.loc[newest.index.sort_values()]

    out = df[COLUMNS].reset_index(drop=True).astype(_DTYPES)
    report.kept = len(out)
    return out, report
