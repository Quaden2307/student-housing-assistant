# Field audit

Which HANDOFF section 3 fields a Kijiji listing actually carries, and where. This table decides what the
unit schema really is: a field that is rarely present or only in free text costs extraction work and rows.

Status: preliminary, 2026-10-14, from 45 apartments cards and 41 rooms cards on page 1 of each index plus
4 detail pages (2 per category). The full audit per HANDOFF task 6 (20 detail pages, 5 saved as fixtures)
is still to do; counts below are over the cards, not over 20 detail pages.

Where a value lives: `attr` is the structured attributes block in the page JSON, `json` another key in the
page JSON, `text` the title or description only, `-` absent.

| Field | Apartments (45 cards) | Rooms (41 cards) | Detail page adds | Notes |
|---|---|---|---|---|
| price | json `price.amount` 44/45 (cents) | json 39/41 | nothing | CONTACT-type prices have no amount |
| unit_type | attr `unittype` 45/45 | - | nothing | apartment, house, condo, basement-apartment. Per-room ads appear under apartments: needs a text rule |
| bedrooms | attr `numberbedrooms` 45/45 | text only | nothing | "0" = studio, "1.5" = 1 + den; rooms need the house total from text |
| lat, lon | json `location.coordinates` 45/45 | json 41/41 | rounds to 2 decimals when pin hidden | card value is better; postal centroid when no street number |
| lease_term | attr `agreementtype` 45/45 | text only | nothing | only one-year and month-to-month exist; sublet and 8-month only in text |
| move_in_month | attr `dateavailable` 17/45 | text only | same attr in `values[0]` | "available now" and month names in text are the fallback |
| utilities_included | attr `heat`,`hydro`,`water` 45/45 | text only | nothing | internet and cabletv also present |
| furnished | attr `furnished` 44/45 | attr 32/41 | nothing | |
| bathrooms | attr `numberbathrooms` 45/45 | text only | display value | canonical value is bathrooms times 10 |
| laundry_in_unit | attr `laundryinunit` 45/45 | text only | nothing | `laundryinbuilding` also present |
| building_type | partly from `unittype` | text only | nothing | house vs apartment is structured; purpose-built student vs lowrise is text only (building names) |
| year_built_after_2018 | - | - | - | only phrases like "new build"; leave null unless stated |
| address / postal code | json `location.address` 45/45; postal code in it 44/45 | 41/41; postal 34/41 | ld+json `streetAddress` | street number on 40/45 apartments, 11/41 rooms; `nearestIntersection` on all cards |
| posted date | json `activationDate`, `sortingDate` 45/45 | 41/41 | `endDate` = activation + 60 d | sortingDate is the last bump |
| description | json, truncated to about 200 chars | same | full plain text | contact info seen in 1 of 4 detail descriptions: strip at parse time |

## What this means

- Apartments: everything except sublet terms, move-in month (17 of 45) and building type comes from the
  index card. Detail pages are needed for the full description, mostly to catch per-room pricing, sublets
  and move-in dates.
- Rooms: only price, location, posted dates and sometimes furnished are structured. Bedrooms, lease term,
  move-in month, utilities and bathrooms must be extracted from the detail-page description. Every rooms
  listing needs its detail page fetched once.

## Method for the full audit (task 6)

1. Pick 20 detail pages: 10 from each category, spread across professional and owner posters, houses and
   apartments, sublets and leases. List the ad ids here.
2. For every field above, count in how many of the 20 it is present and where it lives.
3. Save 5 of the pages (plus one index page per category) under `tests/fixtures/` for the parser tests.

Ad ids used: to fill.
