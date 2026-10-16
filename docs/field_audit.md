# Field audit

Which HANDOFF section 3 fields a Kijiji listing actually carries, and where. This table decides what the
unit schema really is: a field that is rarely present or only in free text costs extraction work and rows.

Status: measured 2026-10-16 over every listing in the database (1,720 apartments, 277 rooms;
detail pages fetched for 277 rooms and 323 apartments) after the extraction rules
in `housing.parse.units` ran. Counts say how many listings end up with a value in `units`. Regenerate with
`uv run python scripts/field_audit.py` after a sweep or a rule change.

## Section 3 fields, as extracted

| Field | Apartments | Rooms | Where it comes from |
|---|---|---|---|
| `unit_type` | 1,720 (100%) | 277 (100%) | attribute `unittype` and bedrooms; the category for rooms; text rules for per-room ads |
| `bedrooms` | 1,720 (100%) | 112 (40%) | attribute `numberbedrooms`; rooms only from text (the house total is often not stated) |
| `bathrooms` | 1,720 (100%) | 67 (24%) | attribute `numberbathrooms` (times 10); rooms from text |
| `lease_term` | 855 (50%) | 87 (31%) | text (sublet, 8-month, month ranges by span) first, then `agreementtype`; `Not Available` is common |
| `move_in_month` | 777 (45%) | 95 (34%) | attribute `dateavailable`, then text near availability wording; never imputed |
| `utilities_included` | 1,719 (100%) | 149 (54%) | explicit text first, then attributes `heat`, `hydro`, `water` |
| `furnished` | 774 (45%) | 208 (75%) | explicit text first, then attribute `furnished` |
| `laundry_in_unit` | 1,719 (100%) | 58 (21%) | attributes `laundryinunit`, `laundryinbuilding`; rooms from text |
| `building_type` | 407 (24%) | 163 (59%) | known-building registry, Kijiji's unit type, explicit wording, house words; `unknown` otherwise |
| `year_built_after_2018` | 18 (1%) | 3 (1%) | registry years and wording about the building's age only |

## Listing-level fields

| Field | Apartments | Rooms |
|---|---|---|
| price (latest snapshot) | 1,693 (98%) | 256 (92%) |
| lat, lon | 1,720 (100%) | 277 (100%) |
| postal code in address | 1,603 (93%) | 208 (75%) |
| posted date | 1,720 (100%) | 277 (100%) |
| full description (detail fetched) | 323 (19%) | 277 (100%) |

## Raw Kijiji attributes present (value given and not `Not Available`)

| Attribute | Apartments | Rooms |
|---|---|---|
| `numberbedrooms` | 1,719 (100%) | 0 (0%) |
| `numberbathrooms` | 1,719 (100%) | 0 (0%) |
| `unittype` | 837 (49%) | 0 (0%) |
| `agreementtype` | 854 (50%) | 0 (0%) |
| `dateavailable` | 759 (44%) | 0 (0%) |
| `furnished` | 767 (45%) | 178 (64%) |
| `heat` | 1,719 (100%) | 0 (0%) |
| `hydro` | 1,719 (100%) | 0 (0%) |
| `water` | 1,719 (100%) | 0 (0%) |
| `internet` | 1,719 (100%) | 0 (0%) |
| `laundryinunit` | 1,719 (100%) | 0 (0%) |
| `laundryinbuilding` | 1,719 (100%) | 0 (0%) |
| `areainfeet` | 1,719 (100%) | 0 (0%) |
| `petsallowed` | 854 (50%) | 155 (56%) |
| `numberparkingspots` | 840 (49%) | 0 (0%) |
| `airconditioning` | 854 (50%) | 0 (0%) |
| `forrentbyhousing` | 1,719 (100%) | 0 (0%) |
| `smokingpermitted` | 854 (50%) | 0 (0%) |

## Distributions after extraction

- `unit_type`: 2bed 607, 1bed 494, 3plus 335, room 304, house 204, studio 53
- `lease_term`: unknown 1,055, 12mo 798, month_to_month 88, sublet_4mo 46, 8mo 10
- `building_type`: unknown 1,427, house 504, purpose_built_student 66

## What this means

- Apartments are structured: every section 3 field except lease term, move-in month, furnished and
  building type is filled for essentially all listings from the index card alone. Lease term and move-in
  are given for about half; the rest say `Not Available`.
- Rooms are text: only price, location, posted dates and sometimes furnished are structured. After the
  detail page is fetched the text rules fill bedrooms for less than half, because the house's bedroom
  count is simply not stated in most room ads. For `unit_type = room` the model should treat `bedrooms`
  as optional (open question for Caden: section 3 lists it as required).
- `building_type` is `unknown` for most apartments because nothing structured separates a low-rise from a
  tower; the known-building registry catches the purpose-built student towers.
- Prices need the cleaning rules in `docs/pipeline.md` section 4: a handful of ads carry placeholder
  prices of $1 or per-term totals.

## Remaining audit work

- The daily job fetches 300 more detail pages each run, newest first, so within a week every active
  listing has its full text; rerun this script then.
- Save three more detail pages as fixtures (a professional landlord's apartment, a sublet, a per-room ad
  under apartments) with `scripts/make_fixture.py`; two are in `tests/fixtures/` already.
