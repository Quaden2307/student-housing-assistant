# Waterloo student rental market: what the model needs to know

Curated from `docs/research/market-brief-2026-10-14.md` (full sources there). Updated 2026-10-14.
Labels: [M] measured by a survey or official notice, [L] listing snapshot (asking prices, small samples),
[A] anecdotal, [C] computed.

## 1. Where the market is

- [M] CMHC Rental Market Survey, October 2025 (published Dec 11, 2025): Kitchener-Cambridge-Waterloo
  purpose-built vacancy 4.1 percent, a multi-decade high; average 2-bed $1,832 (+3.3 percent). CMHC says
  the study-permit cap "continued to ease demand in areas with large student populations", clearest in
  Zone 4 (City of Waterloo), where vacancy rose.
- [M] Zone 4 Waterloo, Oct 2025: vacancy 3.2 percent, average rent $1,842, 1-bed $1,747, 2-bed $1,901,
  3+ bed $1,876, 3+ bed vacancy only 1.2 percent. CMHC neighbourhood "Waterloo University": 2-bed $2,277,
  15 percent above "Waterloo Uptown" ($1,975).
- [M] Rent by year built, Zone 4, Oct 2025: 2000-or-later $2,279 and 1.9 percent vacancy, versus
  1980-1999 $1,722 and 4.2 percent. Building age is a real price driver.
- [L] Asking-rent trackers in 2026 point the other way from CMHC's sitting-tenant averages: Zumper
  (Oct 14, 2026) Waterloo median $1,996, flat YoY, 1-bed $1,795 (-2 percent), 2-bed $2,060 (-2 percent);
  Kitchener median $1,815 (-4 percent), rooms $850. Rentals.ca (Oct 2025) had KW asking rents -6.8 percent YoY.
- [M] Demand shock: new international student arrivals fell about 69 percent in H1 2025 versus H1 2024;
  the cap runs to 2027. Landlords offer one to two months free on high-end units (CMHC) and purpose-built
  operators advertise "2 months free" and "1 month free".

Implication: our scraped medians are asking prices in a softening market and should land below CMHC's
October 2025 averages for the same unit type, not on them. Sanity checks must compare like with like:
Zumper and rentals.ca asking figures, not CMHC averages.

## 2. What students actually pay [L unless noted]

| Product | Typical ask, 2025-26 | Source |
|---|---|---|
| Room in a 5-bed Northdale or Columbia St house | $610 to $1,000 per room; many "all inclusive" | RentWoch list, Oct 2025 (31 listings) |
| Room, other Kijiji and Places4Students samples | $550 to $965 | search snippets |
| Ensuite room in a purpose-built student tower | $1,050 to $1,350 | thestudentsublet, Sept 2026 [A] |
| Purpose-built "from" prices | $959 (58 Cardill) to $2,250 (ICON) | uhomes index |
| Private studio or 1-bed near campus | $1,600 to $1,750 in 2026, down from $1,800 to $2,000 in 2023 | broker commentary [A] |
| Whole 2-bed near campus | about $2,221 (Jul 2025, -5 percent YoY) | Globe via PayProp [A] |
| WCRI co-op single room, per month [C] | Fall $627 to $652; Spring $420 to $445 | posted rates [M] |

## 3. Lease cycle and term effects

- [M] UW co-op: four-month work terms, so subletting is common; typical leases are one year; 8-month
  (Sept to April) and 4-month contracts exist in campus housing and in private listings.
- [L] Summer or spring sublets: -20 to -33 percent against the full-term ask in the few priced cases
  (400 Albert St $625 to $500; Cedarbrae $950 to $700; WCRI Fall versus Spring -33 percent).
- [L] 8-month versus 12-month lease in one ad: $820 versus $780, a 5 percent premium for the shorter term.
- [A] September-start listings appear in May and June once co-op matches are out; unbooked rooms face price
  drops after Aug 1. Listings posted in October already carry Jan 2027 and May 2027 starts.
- [M] Kijiji ads expire after 60 days; reposting "creates a new posting period" and bumps reset ordering.
  `days_on_market` must come from the first activation date of the first ad for that unit, not the latest.

## 4. Geography

- [M] Postal prefixes: N2L (Waterloo South) holds both campuses, Northdale, Phillip, Lester, Albert, Hazel
  and Columbia St; N2J (Waterloo Southeast) holds Uptown and the King St N and Regina St N towers; N2T and
  N2V cover Beechwood, Westvale, Laurelwood and Clair Hills; N2K is east of the parkway. Kitchener runs
  N2A to N2R, with N2G central and N2H north central.
- [C] Straight-line distances: Northdale to UW 1.1 km and to Laurier 0.4 km; King St N towers to UW
  1.9 km; Uptown to UW 2.0 km; Laurelwood 2.8 to 4.0 km; downtown Kitchener 4.9 km to UW and 3.8 km to
  Laurier. UW to Laurier is 1.4 km. At 5 km/h, 1 km is about 12 minutes.

## 5. Buildings: a registry is cheap and valuable

Purpose-built student towers are a distinct product (furnished ensuite suites, per-bed pricing, incentives)
and the only reliable way to fill `building_type = purpose_built_student` and `year_built_after_2018` is a
hand-kept table of known buildings matched on address or name. Known so far [M for addresses]:

| Building | Address | First occupied | Note |
|---|---|---|---|
| ICON Waterloo | 330 Phillip St | after 2018 | two 25-storey towers |
| Sage Platinum I and II, Sage X, Sage VI | 250 Albert St, 308 Lester St, 257 and 251 Hemlock St | mostly after 2018 | verify per tower |
| Elora House | 250 Phillip St | 2022 | Rez-One |
| Blair House | 256 Phillip St | to verify | Rez-One |
| Hespeler House, Fergus House | 252 and 254 Phillip St | to verify | 476 beds each, 4-bed/4-bath suites |
| King Street Towers I and II | 333 and 339 King St N | to verify | 536 and 419 beds |
| Preston House | 315 King St N | 2013 | under rent control |
| Bridgeport House | 328 Regina St N | 2014 | under rent control |
| 308 King | 308 King St N | to verify | 659 beds |
| 167 and 173 King St N | 167 King St N | 2013 | Centurion REIT |
| The MARQ | 1 Columbia St W | to verify | 5-bed ensuite units |
| The Hub | 130 Columbia St W | to verify | |
| Accommod8u / KW4Rent | 228 and 246 Albert St, 250 and 251 Lester St | to verify | |
| WCRI | 280 Phillip St | mixed | co-op, per-term pricing |
| Conestoga College housing | 50 and 60 University Ave E, 400B Albert St | to verify | per-contract pricing |

[M] Ontario rent-increase guideline does not apply to units first occupied after November 15, 2018; the
2026 guideline is 2.1 percent and 2027 is 1.9 percent.

[M] City of Waterloo licensing (bylaw 2025-044, in force July 1, 2026): low-rise rentals are licensed in
classes capped at five bedrooms (Class A) or treated as lodging houses (five or more persons). Apartment
buildings are exempt. This is why 5-bed houses are the modal per-room product and why "licensed" appears
in house ads but not tower ads. In 2022/23 the city counted 5,900 licensed low-density beds versus 22,285
multi-residential beds in the campus catchment.

## 6. Cleaning rules the data demands

| Trap | Rule |
|---|---|
| Per-room prices posted under the apartments category | Detect "per room", "room in", "student room", "last room", "per person", "per bed" in title or description; set `unit_type = room` and keep the price as the per-bedroom price |
| Dual pricing in one ad ("$4,250 or $850 per person"; "$820 on 8-month or $780 on 12-month") | Take the first price that matches the unit type; flag for review |
| Wanted ads | Kijiji's index is already filtered to `type=OFFER`; still drop titles starting "Looking for", "Wanted", "Seeking" |
| Out-of-region listings in the KW index (Listowel, Wellington North) | Bounding box roughly lat 43.36 to 43.56, lon -80.65 to -80.35; drop outside |
| Attribute garbage ("6 students", 2 bedrooms, 60 bathrooms, $5,700) | Range checks: bedrooms 1 to 8, bathrooms 1 to 6, room price $300 to $1,800, per-bedroom price $300 to $3,000 |
| Per-term or per-contract totals | Prices above $3,000 for a room, or text with "per term", "per semester", "4 months for": convert or drop |
| Reduced-price and incentive markers | Keep the current price; record `priceDrop` flag from the page JSON as a note, not a feature |
| Reposts and bumps | Dedup by normalized address + unit type + bedrooms; `posted_at` = earliest activation date in the group |
| Far-future starts | `move_in_month` as stated; the model sees month only |
| Gender-restricted rooms | Not stored and not a feature (protected characteristic); nothing to do |

## 7. Positioning

No existing tool prices a room or bed as a function of distance to campus, lease term, move-in month,
furnishing and utilities together, and none reports where a specific asking price sits in the
distribution. CMHC is annual and excludes rooms and per-bed towers; Zumper and rentals.ca give city
medians only; Rentometer is US-only.
