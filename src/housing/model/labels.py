"""Fix room vs whole-unit mislabels in the training table from the listing title.

An experiment on ``mark/lightgbm-v1``, opt-in (``python -m housing.model.lgbm --fix-labels``).
The model's worst misses were mostly labelling errors, not model errors:

* a single room in a shared unit labelled as a whole unit ("Spacious Student Bedroom
  Available on Hickory St!" as ``1bed``; "1 BEDROOM FOR RENT IN SPACIOUS 2-BEDROOM CONDO"
  as ``2bed``, whose price was then wrongly divided by 2);
* a whole unit labelled as a room ("2 BED ROOM 1 BATH APARTMENT FOR RENT" as ``room``),
  usually posted in the rooms category.

Rules read the title only, never the model's error: dropping rows because the model
misses them would flatter the score. The one price condition is the basement rule, where
the title alone cannot tell a basement room from a basement apartment.

``load_training`` does not keep titles, so :func:`attach_titles` joins them back from
``listings`` (live rows, positive ``listing_id``) and ``archive_listings`` (archive rows,
``dedup_key = 'archive:<source_id>'``).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from housing.model.dataset import GROUP, TARGET

# A single room within a larger unit: "bedroom in a", "1 room in", "room available in".
_ROOM_IN = (
    r"\b(?:bed\s?)?rooms?\s+(?:available\s+|avail\.?\s+|for\s+rent\s+)?in\s+"
    r"(?:a|an|the|our|my|shared|spacious|\d|one|two|three|four|five)\b"
)
# Other phrasings that rent one room or one person's share. "1 bedroom available" is left
# out on purpose: it is how whole 1-bedroom apartments are usually advertised.
_ROOM_ONLY = (
    r"(?<!1 )(?<!1-)(?<!one )\b(?:student\s+)?bed\s?rooms?\s+(?:available|avail|for\s+rent)\b"
    r"|\broom\s+(?:available|avail|left|for\s+rent|for\s+(?:a\s+)?(?:female|male|girls?|boys?))\b"
    r"|\bper\s+(?:person|room|bed|student|tenant)\b"
    r"|\baccom+[ao]dation\s+available\b"
    r"|\b(?:ensuite|private|furnished|master)\s+(?:bed\s?)?room\b"
    r"|\broom\s?mates?\b|\bshare\b|\bsharing\b"
    r"|\bshared\s+(?:room|house|home|property|unit|apartment|accommodation)\b"
    r"|\broom\s+sublet\b|\bsublet(?:ting)?\s*:?\s*(?:1|one|a)\s+(?:bed\s?)?room\b"
)
ROOM_IN_RE = re.compile(_ROOM_IN)
ROOM_ONLY_RE = re.compile(_ROOM_ONLY)
STRONG_ROOM_RE = re.compile(f"{_ROOM_IN}|{_ROOM_ONLY}")
# The listing's own asking price has to agree with the title. $1,200 is about the 95th
# percentile of room prices on the archive table: a "room" relabel needs a price at or
# below it, a whole-unit relabel a price at or above it. Titles alone were wrong about a
# third of the time without this check ("1 Bedroom Available" at $1,700 is an apartment;
# "6 BEDROOMS STUDENT HOUSE FOR RENT" at $700 is one room in it).
ROOM_MAX_PRICE = 1200.0
WHOLE_UNIT_MIN_PRICE = 1200.0

_COUNT = r"(\d|one|two|three|four|five|1|2|3|4|5)"
# An explicit whole unit with a bedroom count: "2 bed room 1 bath apartment",
# "one-bed condo", "2 bedroom unit", "2 bedroom private basement".
WHOLE_UNIT_RE = re.compile(
    rf"\b{_COUNT}[\s-]?(?:bed\s?rooms?|beds?|bdrms?|br)\b"
    r"(?:[^|]{0,40}?)\b(?:apartment|apt|unit|condo|house|townhouse|basement|suite|home)\b"
)
STUDIO_RE = re.compile(r"\b(?:studio|bachelor)\b")
BASEMENT_RE = re.compile(r"\bbasement\b")

# Ads that are not a rentable home at a per-bedroom price. Each priced far below its type in
# the error review of Caden's 2026-11-18 data, so the model learned them as cheap rooms.
# Someone looking for a place (the loader's wanted filter only checks the title's start).
WANTED_RE = re.compile(
    r"\b(?:wanting to rent|looking (?:for )?an? ?room+ate|in search of (?:an? )?room+ate"
    r"|(?:i'?m |am |is |are |tenant |student |guy |girl |woman |man )looking for (?:an? )?"
    r"(?:room|place|unit|apartment|house))"
)
# A bed in a bedroom shared with a stranger: a different product from a private room.
SHARED_ROOM_RE = re.compile(
    r"\b(?:shared (?:bed)?room|room[\s-]?sharing|sharing room|in sharing|spot in an? shared"
    r"|bed in an? shared|share an? room)\b"
)
# Commercial space. "Den/office" and "office space" inside a home stay in.
NON_RESIDENTIAL_RE = re.compile(
    r"^(?!.*\b(?:bed\s?rooms?|beds?|br|rooms?|den|house|home|apartment|apt|condo)\b)"
    r".*\b(?:office|commercial|retail|warehouse|clinic)\b"
)

_WORD_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
WHOLE_UNIT_TYPES = ("studio", "1bed", "2bed", "3plus", "house")


@dataclass
class LabelReport:
    """What :func:`fix_labels` changed.

    Attributes:
        to_room: Whole-unit rows relabelled ``room`` (target becomes the asking price).
        to_unit: Room rows relabelled as a whole unit with the stated bedroom count.
        to_studio: Room rows relabelled ``studio``.
        dropped_basement_units: Room rows dropped as whole basement apartments with no
            bedroom count.
        dropped_not_a_home: Rows dropped as wanted ads, beds in a shared bedroom, or
            commercial space (rule 0).
        no_title: Rows with no title to read (left unchanged).
        examples: A few ``(old, new, title)`` tuples for the report.
    """

    to_room: int = 0
    to_unit: int = 0
    to_studio: int = 0
    dropped_basement_units: int = 0
    dropped_not_a_home: int = 0
    no_title: int = 0
    examples: list[tuple[str, str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"label fixes: {self.to_room} whole-unit rows -> room, {self.to_unit} room rows ->"
            f" whole unit, {self.to_studio} room rows -> studio, dropped"
            f" {self.dropped_basement_units} basement apartments with no bedroom count and"
            f" {self.dropped_not_a_home} wanted / shared-room / commercial ads"
            f" ({self.no_title} rows had no title)"
        )


def attach_titles(conn: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with a ``title`` column joined back from the database.

    Args:
        conn: Open database connection; read only.
        df: The clean frame from ``load_training``.

    Returns:
        A copy of ``df`` with ``title`` (str or None), row order and index unchanged.
    """
    live = dict(conn.execute("SELECT id, title FROM listings").fetchall())
    archive = dict(
        conn.execute("SELECT 'archive:' || source_id, title FROM archive_listings").fetchall()
    )
    titles = [
        archive.get(key) if str(key).startswith("archive:") else live.get(int(lid))
        for key, lid in zip(df[GROUP], df["listing_id"], strict=True)
    ]
    out = df.copy()
    out["title"] = titles
    return out


def _bedroom_count(match: re.Match[str]) -> int:
    word = match.group(1).lower()
    return _WORD_COUNTS.get(word) or int(word)


def _unit_type_for(bedrooms: int) -> str:
    return "1bed" if bedrooms == 1 else "2bed" if bedrooms == 2 else "3plus"


def fix_labels(df: pd.DataFrame) -> tuple[pd.DataFrame, LabelReport]:
    """Relabel room / whole-unit mistakes from the title and recompute the target.

    Rules, first match wins:

    0. Any row whose title is a wanted ad (``WANTED_RE``), a bed in a shared bedroom
       (``SHARED_ROOM_RE``) or commercial space (``NON_RESIDENTIAL_RE``) is dropped:
       none is a home rented at a per-bedroom price the app scores.
    1. A whole-unit row whose title rents one room becomes ``room``, and its target
       becomes the asking price, since a room's price is per bedroom already.
       ``bedrooms`` is kept: for a room it means the unit's total. "Room in a ..." always
       counts; looser phrases count only without an explicit whole unit in the title,
       and only when the price is at most ``ROOM_MAX_PRICE``.
    2. A room row whose title has no room wording but names a whole unit with a bedroom
       count (``WHOLE_UNIT_RE``), at ``WHOLE_UNIT_MIN_PRICE`` or more, becomes
       ``1bed``/``2bed``/``3plus`` with that count; the target becomes price / bedrooms.
    3. A room row whose title says studio or bachelor, with no room wording, becomes
       ``studio``.
    4. A room row whose title says basement, with no room wording and no count, at
       ``WHOLE_UNIT_MIN_PRICE`` or more, is dropped: a whole basement apartment whose
       bedroom count is unknown.

    Args:
        df: Clean frame with ``title``, ``price``, ``unit_type``, ``bedrooms`` and the
            target column (see :func:`attach_titles`).

    Returns:
        ``(fixed_frame, report)``; the frame keeps the input's columns and dtypes, minus
        dropped rows, with a fresh index.
    """
    report = LabelReport()
    out = df.copy()
    keep = pd.Series(True, index=out.index)
    for idx, row in out.iterrows():
        title = row.get("title")
        if title is None or pd.isna(title) or not str(title).strip():
            report.no_title += 1
            continue
        text = str(title).lower()
        unit_type = row["unit_type"]
        room_words = bool(STRONG_ROOM_RE.search(text))
        # "Room in a ..." always means one room; the looser phrases ("private room",
        # "bedrooms available") yield to an explicit whole unit in the same title.
        rents_a_room = bool(ROOM_IN_RE.search(text)) or (
            bool(ROOM_ONLY_RE.search(text)) and not WHOLE_UNIT_RE.search(text)
        )
        price = float(row["price"])
        new = None
        if WANTED_RE.search(text) or SHARED_ROOM_RE.search(text) or NON_RESIDENTIAL_RE.search(text):
            new = "dropped"
            keep[idx] = False
            report.dropped_not_a_home += 1
        elif unit_type in WHOLE_UNIT_TYPES and rents_a_room and price <= ROOM_MAX_PRICE:
            new = "room"
            out.at[idx, "unit_type"] = "room"
            out.at[idx, TARGET] = price
            report.to_room += 1
        elif unit_type == "room" and not room_words:
            whole = WHOLE_UNIT_RE.search(text)
            if whole and price >= WHOLE_UNIT_MIN_PRICE:
                beds = _bedroom_count(whole)
                new = _unit_type_for(beds)
                out.at[idx, "unit_type"] = new
                out.at[idx, "bedrooms"] = beds
                out.at[idx, TARGET] = price / beds
                report.to_unit += 1
            elif STUDIO_RE.search(text):
                new = "studio"
                out.at[idx, "unit_type"] = "studio"
                out.at[idx, "bedrooms"] = 1
                report.to_studio += 1
            elif BASEMENT_RE.search(text) and price >= WHOLE_UNIT_MIN_PRICE:
                new = "dropped"
                keep[idx] = False
                report.dropped_basement_units += 1
        if new is not None and len(report.examples) < 12:
            report.examples.append((str(unit_type), new, str(title)))
    return out[keep].reset_index(drop=True), report
