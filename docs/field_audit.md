# Field audit

Which HANDOFF section 3 fields a Kijiji listing actually carries, and where. This table decides what the
unit schema really is: a field that is rarely present or only in free text costs extraction work and rows.

Status: measured 2026-11-04 over every listing in the database (2,438 apartments, 483 rooms;
detail pages fetched for 480 rooms and 2,238 apartments) after the extraction rules
in `housing.parse.units` ran. Counts say how many listings end up with a value in `units`. Regenerate with
`uv run python scripts/field_audit.py` after a sweep or a rule change.

## Section 3 fields, as extracted

| Field | Apartments | Rooms | Where it comes from |
|---|---|---|---|
| `unit_type` | 2,438 (100%) | 474 (98%) | attribute `unittype` and bedrooms; the category for rooms; text rules for per-room ads |
| `bedrooms` | 2,438 (100%) | 205 (42%) | attribute `numberbedrooms`; rooms only from text (the house total is often not stated) |
| `bathrooms` | 2,438 (100%) | 130 (27%) | attribute `numberbathrooms` (times 10); rooms from text |
| `lease_term` | 1,305 (54%) | 161 (33%) | text (sublet, 8-month, month ranges by span) first, then `agreementtype`; `Not Available` is common |
| `move_in_month` | 1,306 (54%) | 185 (38%) | attribute `dateavailable`, then text near availability wording; never imputed |
| `utilities_included` | 2,437 (100%) | 263 (54%) | explicit text first, then attributes `heat`, `hydro`, `water` |
| `furnished` | 1,212 (50%) | 365 (76%) | explicit text first, then attribute `furnished` |
| `laundry_in_unit` | 2,437 (100%) | 109 (23%) | attributes `laundryinunit`, `laundryinbuilding`; rooms from text |
| `building_type` | 1,023 (42%) | 293 (61%) | known-building registry, Kijiji's unit type, explicit wording, house words; `unknown` otherwise |
| `year_built_after_2018` | 69 (3%) | 6 (1%) | registry years and wording about the building's age only |

## Listing-level fields

| Field | Apartments | Rooms |
|---|---|---|
| price (latest snapshot) | 2,403 (99%) | 455 (94%) |
| lat, lon | 2,438 (100%) | 483 (100%) |
| postal code in address | 2,244 (92%) | 386 (80%) |
| posted date | 2,438 (100%) | 483 (100%) |
| full description (detail fetched) | 2,238 (92%) | 480 (99%) |

## Raw Kijiji attributes present (value given and not `Not Available`)

| Attribute | Apartments | Rooms |
|---|---|---|
| `numberbedrooms` | 2,437 (100%) | 8 (2%) |
| `numberbathrooms` | 2,437 (100%) | 8 (2%) |
| `unittype` | 1,236 (51%) | 8 (2%) |
| `agreementtype` | 1,254 (51%) | 8 (2%) |
| `dateavailable` | 1,147 (47%) | 8 (2%) |
| `furnished` | 1,120 (46%) | 319 (66%) |
| `heat` | 2,437 (100%) | 8 (2%) |
| `hydro` | 2,437 (100%) | 8 (2%) |
| `water` | 2,437 (100%) | 8 (2%) |
| `internet` | 2,437 (100%) | 8 (2%) |
| `laundryinunit` | 2,437 (100%) | 8 (2%) |
| `laundryinbuilding` | 2,437 (100%) | 8 (2%) |
| `areainfeet` | 2,437 (100%) | 8 (2%) |
| `petsallowed` | 1,254 (51%) | 280 (58%) |
| `numberparkingspots` | 1,227 (50%) | 8 (2%) |
| `airconditioning` | 1,254 (51%) | 8 (2%) |
| `forrentbyhousing` | 2,437 (100%) | 8 (2%) |
| `smokingpermitted` | 1,254 (51%) | 8 (2%) |

## Distributions after extraction

- `unit_type`: 2bed 826, 1bed 636, room 633, 3plus 452, house 300, studio 65, null 9
- `lease_term`: unknown 1,455, 12mo 1,195, sublet_4mo 131, month_to_month 113, 8mo 27
- `building_type`: unknown 1,605, house 1,150, purpose_built_student 166

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
