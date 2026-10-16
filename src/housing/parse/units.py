"""Map a listing's attributes and text to the unit schema fields (HANDOFF section 3).

Two sources: the structured attributes Kijiji exposes (apartments carry about 35, rooms
almost none) and regular expressions over the title and description. Attributes decide
counts and dates; an explicit statement in the text beats an attribute flag for utilities
and furnishing, because posters write "all inclusive" in the title and leave the boxes
unticked. The conventions are logged in ``docs/decisions.md`` (2026-10-14) and repeated in
``schema/unit_schema.yaml``. Fields go into ``units``; useful signals that are not schema
fields (per-room pricing, private bathroom, lease takeover, "available now") are returned
as ``flags`` and stored in ``listing_attributes`` with a ``text_`` prefix.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

HOUSE_TYPES = {"house", "townhouse", "duplex-triplex", "basement-apartment"}

# Per-room pricing posted under a whole-unit category, or a room ad in general. "bedroom
# for rent" only counts without a count in front: "TWO BEDROOM FOR RENT" is a whole unit.
_NOT_AFTER_COUNT = (
    r"(?<!\d[\s-])(?<!one[\s-])(?<!two[\s-])(?<!three[\s-])(?<!four[\s-])"
    r"(?<!five[\s-])(?<!six[\s-])"
)
PER_ROOM_RE = re.compile(
    rf"\b(per room|per bedroom|/room|/bedroom|one room|1 room|single room|private room|"
    rf"rooms? for rent|rooms? available|room in a|rooms in a|room rental|"
    rf"roommates? (?:wanted|needed)|looking for (?:a |an? )?roommates?|"
    rf"shared (?:house|apartment|unit|accommodation|living)|student rooms?|each room|"
    rf"female only|male only|females only|males only|all[- ]female|all[- ]male|"
    rf"{_NOT_AFTER_COUNT}bedroom for rent|furnished rooms?|last room|room available)\b",
    re.IGNORECASE,
)
WHOLE_UNIT_RE = re.compile(
    r"\b(entire|whole|full) (?:house|unit|apartment|basement|place|home|condo|townhouse)\b",
    re.IGNORECASE,
)
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8
}  # fmt: skip
BEDROOMS_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight)\s*(?:\+\s*\d\s*)?[- ]?\s*"
    r"(?:bed(?:room)?s?|br|bdrm|bdr)\b",
    re.IGNORECASE,
)
BATHROOMS_RE = re.compile(
    r"\b(\d+(?:\.5)?|one|two|three|four)\s*[- ]?\s*(?:bath(?:room)?s?|washrooms?)\b",
    re.IGNORECASE,
)
PRIVATE_BATH_RE = re.compile(
    r"\b(en[- ]?suite|private (?:bath|bathroom|washroom)|own (?:bath|bathroom|washroom)|"
    r"(?:bath|bathroom|washroom) (?:of your own|to yourself))\b",
    re.IGNORECASE,
)
MONTH = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
# For "available <month>" the verb "may" is a trap ("parking available, may be shared"):
# accept it only capitalised or followed by a day or year.
MONTH_STRICT_MAY = MONTH.replace("may", r"may(?=\s*\d)|(?-i:May|MAY)")
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
RANGE_RE = re.compile(
    rf"\b({MONTH})\.?\s*(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s*)?(?:20\d\d\s*)?"
    rf"(?:-|–|to|through|until|till)\s*({MONTH})\b",
    re.IGNORECASE,
)
SUBLET_RE = re.compile(
    r"\b(sublet|sub-let|sublease|sub-lease|subletting|4[\s-]*months?|four[\s-]*months?|"
    r"winter term|summer term|spring term|fall term|co-?op term|term rental|short[\s-]*term)\b",
    re.IGNORECASE,
)
NO_SUBLET_RE = re.compile(
    r"\bno (?:short[\s-]*term|sub-?lets?|sub-?letting|sub-?leas(?:e|es|ing))\b", re.IGNORECASE
)
TAKEOVER_RE = re.compile(
    r"\b(lease[\s-]*takeover|take[\s-]*over (?:my|the|our|this) lease|lease assignment|"
    r"assign(?:ing|ment of)? (?:my|the|our) lease|takeover)\b",
    re.IGNORECASE,
)
EIGHT_RE = re.compile(r"\b(8[\s-]*months?|eight[\s-]*months?|school year)\b", re.IGNORECASE)
TWELVE_RE = re.compile(
    r"\b(12[\s-]*months?|twelve[\s-]*months?|1[\s-]*year|one[\s-]*year|annual lease|"
    r"yearly lease)\b",
    re.IGNORECASE,
)
M2M_RE = re.compile(r"\b(month[\s-]*to[\s-]*month|monthly lease|no lease)\b", re.IGNORECASE)
AVAILABLE_NOW_RE = re.compile(
    r"\b(available (?:now|immediately|asap|right away|today)|"
    r"immediate (?:occupancy|possession|move[\s-]*in)|"
    r"move[\s-]*in (?:ready|today|now|immediately))\b",
    re.IGNORECASE,
)
_AVAILABLE = (
    r"(?:available|availability|move[\s-]*in|starting|start date|lease (?:starts?|begins?)|"
    r"from|for)"
)
AVAILABLE_MONTH_RE = re.compile(
    rf"{_AVAILABLE}\W{{0,25}}(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+)?({MONTH_STRICT_MAY})\b\.?\s*"
    rf"(?:\d{{1,2}}(?:st|nd|rd|th)?)?,?\s*(20\d\d)?",
    re.IGNORECASE,
)
# An ISO date counts as the move-in date only next to availability wording; a bare
# "2027-04-30" in the text may be the lease end.
ISO_AVAILABLE_RE = re.compile(rf"{_AVAILABLE}\W{{0,25}}(20\d\d)-(\d\d)-(\d\d)\b", re.IGNORECASE)
ALL_INCLUSIVE_RE = re.compile(
    r"\b(all[\s-]*inclusive|all[\s-]*included|all[\s-]*in(?=\s*(?:[.,!;:()]|$))|"
    r"utilities (?:are )?included|inclusive of (?:all )?utilities|includes? (?:all )?utilities|"
    r"everything included|incl(?:\.|udes|uding)? (?:all )?utilities|utilities incl|"
    r"inclusive rent|rent includes? (?:all )?utilities|utilities inclusive|"
    r"utilities(?:(?!\bnot\b|\bexcept\b|\bextra\b)[^.\n]){0,30}?\bincluded)\b",
    re.IGNORECASE | re.MULTILINE,
)
UTILITIES_EXTRA_RE = re.compile(
    r"(\bplus utilities\b|\+\s*utilities|"
    r"\butilities\W{0,3}(?:are |is )?(?:extra|not included|not incl|excluded|separate|"
    r"additional|on top)\b|"
    r"\butilities\b(?:(?!\bincluded\b)[^.\n;]){0,25}?\b(?:are |is )?"
    r"(?:not included|not incl|excluded)\b|"
    r"\bexcluding utilities\b|"
    r"\bhydro (?:is )?(?:extra|not included|separate)\b|"
    r"\btenants? pays? (?:for )?(?:all )?(?:utilities|hydro)\b|"
    r"\bresponsible for (?:all )?utilities\b)",
    re.IGNORECASE,
)
INTERNET_RE = re.compile(
    r"\b(internet|wi-?fi)\b.{0,15}\b(included|incl|free)\b|"
    r"\b(free|includes?|including)\b.{0,15}\b(internet|wi-?fi)\b",
    re.IGNORECASE,
)
UNFURNISHED_RE = re.compile(
    r"\b(un-?furnished|non-?furnished|not furnished|no furniture|without furniture|"
    r"isn'?t furnished|is not furnished|furniture not included)\b",
    re.IGNORECASE,
)
FURNISHED_RE = re.compile(r"(?<!un-)(?<!not )(?<!non-)\bfurnished\b", re.IGNORECASE)
LAUNDRY_IN_UNIT_RE = re.compile(
    r"\b(en[\s-]*suite laundry|in[\s-]*(?:unit|suite) laundry|laundry in (?:the )?(?:unit|suite)|"
    r"private laundry|own (?:washer|laundry)|"
    r"washer (?:and|&|/) dryer in (?:the )?(?:unit|suite)|in[\s-]*unit washer)\b",
    re.IGNORECASE,
)
LAUNDRY_SHARED_RE = re.compile(
    r"\b(shared laundry|coin laundry|common laundry|laundry room|laundry facilities|"
    r"laundry (?:in|on) (?:the )?(?:building|site|premises|basement))\b",
    re.IGNORECASE,
)
# Explicit purpose-built wording. Generic "student housing" is not enough: shared houses
# advertise that too.
STUDENT_BUILDING_RE = re.compile(
    r"\b(student (?:building|residence|apartments?|apt|living|tower|suites?|rental building)|"
    r"purpose[\s-]*built)\b",
    re.IGNORECASE,
)
HOUSE_WORDS_RE = re.compile(
    r"\b(house|townhouse|townhome|detached|bungalow|duplex|triplex|basement)\b", re.IGNORECASE
)
# A statement about the building's age; "brand new unit" also describes renovations.
NEW_BUILD_RE = re.compile(
    r"\b(new build|brand[\s-]*new (?:building|construction)|newly (?:built|constructed)|"
    r"built in 20(?:19|2\d)|new construction)\b",
    re.IGNORECASE,
)

# Known purpose-built student buildings near the campuses, matched on the street address
# (number and street, lowercase, street words abbreviated) in the address text or the
# description. The year is the first occupancy where docs/market.md section 5 records it;
# None means not verified yet.
PBSH_BUILDINGS: tuple[tuple[str, str, int | None], ...] = (
    ("330 phillip", "ICON Waterloo", None),
    ("250 albert", "Sage Platinum I", None),
    ("308 lester", "Sage Platinum II", None),
    ("257 hemlock", "Sage X", None),
    ("251 hemlock", "Sage VI", None),
    ("333 king st n", "King Street Towers I", None),
    ("339 king st n", "King Street Towers II", None),
    ("315 king st n", "Preston House", 2013),
    ("328 regina", "Bridgeport House", 2014),
    ("252 phillip", "Hespeler House", None),
    ("254 phillip", "Fergus House", None),
    ("308 king st n", "308 King", None),
    ("250 phillip", "Elora House", 2022),
    ("256 phillip", "Blair House", None),
    ("167 king st n", "167 King", 2013),
    ("173 king st n", "173 King", None),
    ("1 columbia st w", "The MARQ", None),
    ("130 columbia st w", "The Hub", None),
    ("228 albert", "Accommod8u 228 Albert", None),
    ("246 albert", "Accommod8u 246 Albert", None),
    ("250 lester", "Accommod8u 250 Lester", None),
    ("251 lester", "KW4Rent 251 Lester", None),
    ("280 phillip", "WCRI", None),
    ("275 larch", "275 Larch", None),
    ("60 university ave e", "Conestoga 60 University", None),
    ("50 university ave e", "Conestoga 50 University", None),
    ("400b albert", "Conestoga 400B Albert", None),
)
_STREET_WORDS = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr",
    "north": "n", "south": "s", "east": "e", "west": "w",
}  # fmt: skip
_STREET_WORD_RE = re.compile(r"\b(street|avenue|road|drive|north|south|east|west)\b\.?")
_STREET_ABBREV_RE = re.compile(r"\b(st|ave|rd|dr|n|s|e|w)\.")
# The number must match whole: "1 columbia st w" is not inside "121 columbia st w".
PBSH_PATTERNS: tuple[tuple[re.Pattern[str], str, int | None], ...] = tuple(
    (re.compile(rf"(?<!\w){re.escape(key)}\b"), name, year) for key, name, year in PBSH_BUILDINGS
)


def normalise_address(text: str) -> str:
    """Lowercase ``text`` with street words abbreviated ("Street West" to "st w")."""
    low = _STREET_WORD_RE.sub(lambda m: _STREET_WORDS[m.group(1)], text.lower())
    low = _STREET_ABBREV_RE.sub(r"\1", low)
    return re.sub(r"\s+", " ", low)


@dataclass
class UnitFields:
    """The section 3 fields for one listing plus extra text-derived flags."""

    unit_type: str | None = None
    bedrooms: int | None = None
    bathrooms: float | None = None
    lease_term: str = "unknown"
    move_in_month: int | None = None
    utilities_included: bool | None = None
    furnished: bool | None = None
    laundry_in_unit: bool | None = None
    building_type: str = "unknown"
    year_built_after_2018: bool | None = None
    extracted_by: str = "regex"
    flags: dict[str, str] = field(default_factory=dict)


def _first(attrs: Mapping[str, str], name: str) -> str | None:
    value = attrs.get(name)
    if value is None:
        return None
    value = str(value).split("|")[0].strip()
    return None if value in ("", "Not Available") else value


def _attr_bool(attrs: Mapping[str, str], name: str) -> bool | None:
    value = _first(attrs, name)
    return None if value is None else value == "1"


def _number(text: str) -> float | None:
    low = text.lower()
    if low in NUMBER_WORDS:
        return float(NUMBER_WORDS[low])
    try:
        return float(text)
    except ValueError:
        return None


def unit_type_for(bedrooms: float | None) -> str | None:
    """Whole-unit type from a bedroom count (``0`` is a studio, ``1.5`` is one plus den)."""
    if bedrooms is None:
        return None
    if bedrooms < 1:
        return "studio"
    if bedrooms < 2:
        return "1bed"
    if bedrooms < 3:
        return "2bed"
    return "3plus"


def _text_bedrooms(text: str) -> list[int]:
    """Every bedroom count mentioned in the text, in order."""
    return [
        int(n)
        for m in BEDROOMS_RE.finditer(text)
        if (n := _number(m.group(1))) is not None and 1 <= n <= 12
    ]


def _bedrooms(
    attributes: Mapping[str, str], text: str, category: str
) -> tuple[int | None, float | None]:
    """Return ``(bedrooms, raw attribute value)``; the raw value keeps 0 for studios.

    From text, a room ad gets the largest count mentioned ("one bedroom in a 5 bedroom
    house" is a 5-bedroom house); a whole-unit ad gets the first.
    """
    raw_value = _first(attributes, "numberbedrooms")
    raw = _number(raw_value) if raw_value else None
    if raw is not None:
        return max(int(raw), 1), raw  # studio convention: 0 is stored as 1
    found = _text_bedrooms(text)
    if not found:
        return None, None
    return (max(found) if category == "rooms" else found[0]), None


def _bathrooms(attributes: Mapping[str, str], text: str) -> float | None:
    raw_value = _first(attributes, "numberbathrooms")
    raw = _number(raw_value) if raw_value else None
    if raw is not None:
        return raw / 10 if raw > 8 else raw  # Kijiji stores bathrooms times 10
    for m in BATHROOMS_RE.finditer(text):
        n = _number(m.group(1))
        if n is not None and 0.5 <= n <= 8:
            return n
    return None


def range_span_months(text: str) -> int | None:
    """Months between the two ends of the first "<month> to <month>" range in ``text``.

    "January to April" is 3, "September to August" is 11, "May to May" is 12; None when
    there is no range.
    """
    m = RANGE_RE.search(text)
    if not m:
        return None
    start = MONTHS[m.group(1)[:3].lower()]
    end = MONTHS[m.group(2)[:3].lower()]
    return (end - start) % 12 or 12


def _lease_term(attributes: Mapping[str, str], text: str) -> str:
    """Text first, then Kijiji's ``agreementtype`` (which has no sublet or 8-month value).

    Explicit words win over a month range, and a range is read by its length: up to about
    five months is a sublet, six to nine an 8-month lease, longer a year.
    """
    if SUBLET_RE.search(NO_SUBLET_RE.sub(" ", text)):
        return "sublet_4mo"
    if EIGHT_RE.search(text):
        return "8mo"
    if TWELVE_RE.search(text):
        return "12mo"
    span = range_span_months(text)
    if span is not None:
        if span <= 5:
            return "sublet_4mo"
        return "8mo" if span <= 9 else "12mo"
    agreement = _first(attributes, "agreementtype")
    if agreement == "one-year":
        return "12mo"
    if agreement == "month-to-month":
        return "month_to_month"
    if M2M_RE.search(text):
        return "month_to_month"
    return "unknown"


def _move_in_month(attributes: Mapping[str, str], text: str) -> int | None:
    """The stated move-in month, never imputed."""
    available = _first(attributes, "dateavailable")
    if available and re.fullmatch(r"20\d\d-\d\d-\d\d", available[:10]):
        return int(available[5:7])
    m = AVAILABLE_MONTH_RE.search(text)
    if m:
        return MONTHS[m.group(2)[:3].lower()]
    r = RANGE_RE.search(text)
    if r:
        return MONTHS[r.group(1)[:3].lower()]
    iso = ISO_AVAILABLE_RE.search(text)
    if iso and 1 <= int(iso.group(2)) <= 12:
        return int(iso.group(2))
    return None


def _utilities(attributes: Mapping[str, str], text: str) -> bool | None:
    """True when heat, hydro and water are all included; internet does not count.

    An explicit statement in the text wins; otherwise Kijiji's three flags decide.
    """
    if UTILITIES_EXTRA_RE.search(text):
        return False
    if ALL_INCLUSIVE_RE.search(text):
        return True
    parts = [_attr_bool(attributes, name) for name in ("heat", "hydro", "water")]
    if all(p is not None for p in parts):
        return all(parts)
    return None


def _furnished(attributes: Mapping[str, str], text: str) -> bool | None:
    """The text's explicit statement, else Kijiji's ``furnished`` flag."""
    if UNFURNISHED_RE.search(text):
        return False
    if FURNISHED_RE.search(text):
        return True
    return _attr_bool(attributes, "furnished")


def _laundry(attributes: Mapping[str, str], text: str) -> bool | None:
    in_unit = _attr_bool(attributes, "laundryinunit")
    in_building = _attr_bool(attributes, "laundryinbuilding")
    if in_unit is not None or in_building is not None:
        return bool(in_unit)
    if LAUNDRY_IN_UNIT_RE.search(text):
        return True
    if LAUNDRY_SHARED_RE.search(text):
        return False
    return None


def extract(
    *,
    category: str,
    title: str,
    description: str | None,
    attributes: Mapping[str, str],
    address: str | None = None,
) -> UnitFields:
    """Extract the unit fields for one listing.

    Args:
        category: ``"apartments"`` or ``"rooms"``, the Kijiji category it was listed under.
        title: Listing title.
        description: Full description if the detail page was fetched, else None.
        attributes: Kijiji attributes by canonical name, multiple values joined with ``|``.
        address: Listing address text, used for the known-building registry.
    """
    text = f"{title}\n{description or ''}"
    out = UnitFields()

    out.bedrooms, raw_bedrooms = _bedrooms(attributes, text, category)
    out.bathrooms = _bathrooms(attributes, text)

    # Unit type: the category plus text, with text overriding a misleading category.
    unittype = _first(attributes, "unittype")
    whole_unit = bool(WHOLE_UNIT_RE.search(text))
    per_room = bool(PER_ROOM_RE.search(text))
    if category == "rooms":
        out.unit_type = unit_type_for(out.bedrooms) if whole_unit and not per_room else "room"
    elif per_room and not whole_unit:
        out.unit_type = "room"
        out.flags["per_room_price"] = "1"
        # A room's bedrooms is the house total; the poster may have entered the room's 1.
        house = max(_text_bedrooms(text), default=0)
        if house > (out.bedrooms or 0):
            out.bedrooms = house
    elif unittype in ("house", "townhouse", "duplex-triplex"):
        out.unit_type = "house"
    else:
        out.unit_type = unit_type_for(raw_bedrooms if raw_bedrooms is not None else out.bedrooms)

    out.lease_term = _lease_term(attributes, text)
    if TAKEOVER_RE.search(text):
        out.flags["is_takeover"] = "1"
    out.move_in_month = _move_in_month(attributes, text)
    if AVAILABLE_NOW_RE.search(text):
        out.flags["available_now"] = "1"

    out.utilities_included = _utilities(attributes, text)
    internet = _attr_bool(attributes, "internet")
    if internet or (internet is None and INTERNET_RE.search(text)):
        out.flags["internet_included"] = "1"

    out.furnished = _furnished(attributes, text)
    out.laundry_in_unit = _laundry(attributes, text)
    if PRIVATE_BATH_RE.search(text):
        out.flags["bathroom_private"] = "1"

    # Building type and age: the registry, Kijiji's unit type, explicit wording, house words.
    haystack = normalise_address(f"{address or ''}\n{text}")
    building = next((b for b in PBSH_PATTERNS if b[0].search(haystack)), None)
    house_words = bool(HOUSE_WORDS_RE.search(text))
    if building:
        out.building_type = "purpose_built_student"
        out.flags["building_name"] = building[1]
        if building[2] is not None:
            out.year_built_after_2018 = building[2] > 2018
    elif unittype in HOUSE_TYPES:
        out.building_type = "house"
    elif STUDENT_BUILDING_RE.search(text):
        out.building_type = "purpose_built_student"
    elif house_words and (category == "rooms" or unittype is None):
        out.building_type = "house"
    if out.year_built_after_2018 is None and NEW_BUILD_RE.search(text):
        out.year_built_after_2018 = True

    out.extracted_by = "page_attrs" if raw_bedrooms is not None else "regex"
    return out
