<!-- Research archive. Produced 2026-10-14 by a desk-research agent for this project; every figure carries a URL and a reliability label ([M] measured, [L] listing snapshot, [A] anecdotal, [C] computed). The curated version is docs/market.md. -->

# Waterloo student rental market: desk-research brief (2026-10-14)

Scope: facts for the price model in HANDOFF.md (target `price_per_bedroom`; features `unit_type`, `lease_term`, `move_in_month`, postal-prefix `neighbourhood`, campus distance, `building_type`, `year_built_after_2018`). No listing sites were scraped; Kijiji/rentals.ca/Places4Students figures below come from search-engine snippets or single public stats pages and are labelled as such. All URLs were accessed 2026-10-14; publication dates are given where the page states one. Nothing was written into `src/` or `tests/`; scratch files (CMHC PDFs, HMIP HTML, extracted text) are in the session scratchpad only.

Labels used: **[M]** measured by a survey/registry/official notice; **[L]** listing snapshot (asking prices, small samples); **[A]** anecdotal/commentary; **[C]** computed by me from sourced inputs. CMHC reliability codes: a excellent, b very good, c good, d poor, ** suppressed.

---

## 1. Market level

### 1.1 CMHC Rental Market Survey, October 2025 (Fall 2025 report) [M]

Report page (CMHC, "Date Published: December 11, 2025"): https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/market-reports/rental-market-reports-major-centres?selected=kitchenerCambridgeWaterlooDiv
PDF (pp. 46–49): https://eppd1strscr01.blob.core.windows.net/cmhcprdcontainer/sf/project/archive/housing_markets/rentalmarketreportcanadaandselectedmarkets/rental-market-report-2025-fall-en.pdf

| Kitchener-Cambridge-Waterloo CMA, Oct 2025 | Value |
|---|---|
| Purpose-built apartment vacancy rate | 4.1% ("stayed the same in 2025, holding at a multi-decade high") |
| Purpose-built avg 2-bedroom rent | $1,832, up 3.3% |
| Condominium apartment vacancy / avg 2-bed rent | 0.8% / $2,197 |
| Rental apartment supply growth 2025 | +2.8% |
| Vacancy, lowest-rent quartile | under 1% |
| Incentives | "landlords offering significant incentives, such as 1–2 months of free rent" on high-end units |
| Turnover rent | "average rent for a 2-bedroom turnover unit ... was little changed"; same-sample non-turnover rent "stagnant" |
| Student demand | "The federal cap on international study permits continued to ease demand in areas with large student populations. This was clear in Zone 4 (Waterloo), home to the University of Waterloo and Wilfrid Laurier University, where the vacancy rate increased." Zone 3 (Kitchener West) was the only other zone with a higher vacancy rate. |
| Other | KCW "has one of Ontario's most tariff-exposed economies" |

Note the universe difference: the report headline uses purpose-built *apartments* (4.1%, $1,832); the HMIP tables below use *row + apartment* (4.0%, $1,816 for 2-bed). Both are the primary rental market (purpose-built structures of 3+ units); rooms in houses, secondary suites and condos are not in these tables.

### 1.2 CMA by bedroom type, Oct 2023–2025 (row + apartment) [M]

Source: CMHC HMIP, https://www03.cmhc-schl.gc.ca/hmip-pimh/en/TableMapChart/TableMatchingCriteria?GeographyType=MetropolitanMajorArea&GeographyId=0850&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Average+Rent+%28%24%29&ColumnField=2&RowField=TIMESERIES and the same URL with `CategoryLevel2=Vacancy+Rate+%28%25%29`.

| Oct | Studio rent | 1-bed | 2-bed | 3+ bed | Total | Total vacancy | 1-bed vac | 2-bed vac | 3+ vac |
|---|---|---|---|---|---|---|---|---|---|
| 2022 | $1,063 | $1,240 | $1,454 | $1,590 | $1,390 | 1.2% | 1.2% | 1.1% | 1.4% |
| 2023 | $1,157 | $1,342 | $1,637 | $1,935 | $1,561 | 2.1% | 2.4% | 2.0% | 1.7% |
| 2024 | $1,250 | $1,499 | $1,747 | $1,789 | $1,658 | 3.5% | 4.1% | 3.3% | 2.4% |
| 2025 | $1,255 (b) | $1,546 (a) | $1,816 (a) | $1,861 (b) | $1,716 (a) | 4.0% (b) | 4.7% (c) | 3.9% (a) | 1.8% (b) |

CMA time series (same source, Summary Statistics, RowField=TIMESERIES): avg rent % change 2019 +5.0, 2020 +3.9, 2021 +5.5, 2022 +7.2, 2023 +8.8, 2024 +3.5, 2025 +3.3; universe 36,836 units (2019) to 42,911 (2025). Vacancy 2019–2021 2.0% each year.

### 1.3 Zones and census subdivisions, Oct 2025 [M]

Sources: HMIP summary by zone https://www03.cmhc-schl.gc.ca/hmip-pimh/en/TableMapChart/TableCategory?geographyType=MetropolitanMajorArea&geographyId=0850&categoryLevel1=Primary+Rental+Market&categoryLevel2=Summary+Statistics ; rent by zone x bedroom (`...Average+Rent+%28%24%29&ColumnField=2&RowField=25`); vacancy by zone x bedroom (`...Vacancy+Rate+%28%25%29&ColumnField=2`); CSD tables (`RowField=22`).

| Zone (CMHC RMS) | Vacancy | Avg rent (all) | Median | YoY rent | Units | 1-bed | 2-bed | 3+ bed | 1-bed vac | 2-bed vac | 3+ vac |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Zone 4 Waterloo** (= City of Waterloo) | **3.2% (b)** | **$1,842 (a)** | $1,850 | **+3.0% (b)** | 10,993 | $1,747 (b) | $1,901 (a) | $1,876 (b) | 3.5 (c) | 3.4 (c) | 1.2 (d) |
| Zone 1 Kitchener East | 3.6% | $1,550 | $1,545 | +3.0% | 12,442 | $1,353 | $1,651 | $1,692 | 2.6 | 4.6 | 1.3 |
| Zone 2 Kitchener Central | 3.3% | $1,650 | $1,599 | +3.8% (d) | 5,022 | $1,409 | $1,863 | $2,125 (d) | 3.6 (d) | 2.9 | ** |
| Zone 3 Kitchener West | 7.1% (c) | $1,758 | $1,825 | +2.1% | 6,652 | $1,628 | $1,850 | $2,191 | ** | 5.2 | 4.5 |
| Zone 5 Cambridge | 3.4% | $1,857 | $1,875 | +4.9% | 6,819 | $1,697 | $1,918 | ** | 3.9 | 3.2 | ** |
| Zone 6 Three Townships | 2.3% | $1,305 | $1,143 | +5.0% | 983 | $1,205 | $1,364 | $1,444 | 3.3 | ** | 1.7 |
| CMA | 4.0% | $1,716 | $1,716 | +3.3% | 42,911 | $1,546 | $1,816 | $1,861 | 4.7 | 3.9 | 1.8 |
| Kitchener (CY) | 4.6% (b) | $1,632 | $1,612 | +2.9% | 24,116 | $1,455 | $1,747 | $1,860 | 5.3 | 4.5 | 2.3 |

Zone 4 boundary (report p. 49): Woolwich Twp (north), Kitchener city boundary (south), Grand River (east), Wilmot Line (west), i.e. the whole City of Waterloo. Studio: Waterloo $1,348 (c), Kitchener East $1,293 (c), Kitchener West $1,171 (b).

### 1.4 CMHC neighbourhoods inside Waterloo, Oct 2025 [M] (closest official figures to the student area)

Source: HMIP rent by neighbourhood (`...Average+Rent+%28%24%29&ColumnField=2&RowField=24`) and vacancy by neighbourhood (`...Vacancy+Rate+%28%25%29&ColumnField=2&RowField=24`). Neighbourhood boundaries were not retrieved.

| CMHC neighbourhood | 1-bed | 2-bed | 3+ bed | Total | Vacancy total | 1-bed vac | 2-bed vac | 3+ vac |
|---|---|---|---|---|---|---|---|---|
| **Waterloo University** | $1,832 (b) | **$2,277 (b)** | $1,886 (d) | $2,039 (b) | 3.1 (d) | 3.4 (d) | 3.7 (d) | 0.4 (b) |
| Waterloo Uptown | $1,805 (b) | $1,975 (b) | $1,939 (a) | $1,895 (b) (studio $1,112) | 2.7 (b) | 2.9 (b) | 2.6 (c) | ** |
| Waterloo North-East | $1,742 (c) | $1,739 (b) | $2,029 (b) | $1,762 (b) | 3.2 (b) | 4.1 (d) | 3.2 (c) | 1.2 (a) |
| Waterloo North-West | $1,334 (b) | $1,718 (b) | $1,645 (b) | $1,637 (b) | 3.9 (d) | ** | 4.3 (d) | ** |
| Kitchener Central | $1,409 (b) | $1,863 (a) | $2,125 (d) | $1,650 (a) | 3.3 (c) | 3.6 (d) | 2.9 (b) | ** |
| Kitchener South-West | $1,577 | $1,897 | $2,310 | $1,803 | 4.7 | 4.9 | 4.6 | 5.2 |
| Kitchener South-East | $1,571 | $1,715 | $1,695 | $1,676 | 5.2 | 5.4 | 5.7 | 1.6 |
| Kitchener South-Central | $1,078 | $1,265 | ** | $1,137 | 0.5 | 0.6 | 0.3 | ** |
| Kitchener North-East | $1,528 | $1,548 | $1,698 | $1,565 | 2.2 | ** | 3.0 | ** |

[C] "Waterloo University" 2-bed is 15% above "Waterloo Uptown" 2-bed and 20% above the Zone 4 2-bed average.

### 1.5 Rent by year of construction and structure size, Oct 2025 [M]

Sources: `...Average+Rent+%28%24%29&ColumnField=28&RowField=TIMESERIES` (year built), `...ColumnField=28&RowField=25` (by zone), `...Vacancy+Rate+%28%25%29&ColumnField=28&RowField=25`, `...ColumnField=29&RowField=TIMESERIES` (structure size, apartments only).

| Year built | CMA 2023 | CMA 2024 | CMA 2025 | Zone 4 Waterloo 2025 rent | Zone 4 vacancy 2025 |
|---|---|---|---|---|---|
| Before 1960 | $1,413 (c) | $1,240 (c) | $1,494 (c) | ** | ** |
| 1960–1979 | $1,374 | $1,481 | $1,500 (a) | $1,643 (a) | 3.5 (b) |
| 1980–1999 | $1,525 | $1,593 | $1,687 (a) | $1,722 (a) | 4.2 (b) |
| 2000 or later | $2,030 | $2,016 | $2,109 (a) | **$2,279 (a)** | **1.9 (c)** |
| Total | $1,561 | $1,658 | $1,716 | $1,842 | 3.2 |

Other zones, 2000-or-later rent: Kitchener West $2,188 (b), Cambridge $2,229, Kitchener East $1,916, Kitchener Central $1,756 (c). Structure size (apartments only, CMA 2025): 3–5 units $1,504; 6–19 $1,434 (c); 20–49 $1,551; 50–199 $1,788; 200+ $1,954; total $1,726. CMHC's finest construction bucket is "2000 or later", so no official rent split exists at the Nov 15, 2018 threshold. Fall 2024 report: "rents for newer 2-bedroom rental units averaging $2,356 (Table 1.2.2)".

### 1.6 October 2024 survey context [M]

CMHC Fall 2024 PDF (pp. 44–45): https://assets.cmhc-schl.gc.ca/sites/cmhc/professional/housing-markets-data-and-research/market-reports/rental-market-report/fall-2024/rental-market-report-fall-2024-en.pdf — "the vacancy rate reached its highest level since 1993"; "The cap on international study permits in 2024 reduced student rental demand, contributing to higher vacancies in Zones 1 and 4 (Kitchener East and Waterloo, respectively)"; 2-bed rent growth "slowed to 4.2% from 7.4% in 2023"; supply expansion "especially in Zones 2, 4 and 5". CTV Kitchener, Jan 5, 2025 (headline/date fetched; body only via search snippet): purpose-built vacancy 3.6%, avg 2-bed $1,766 (+4.2%): https://www.ctvnews.ca/kitchener/article/vacancy-rate-in-kitchener-cambridge-waterloo-hits-highest-level-since-1993-report . Zone-level October 2024 tables were not retrievable from HMIP without a form POST (gap).

### 1.7 2026 asking-rent trackers [L]

| Source (date) | Area | Studio | 1-bed | 2-bed | 3-bed | 4-bed | All / median | Rooms | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Zumper Rent Research, "last updated Oct 14, 2026" (FAQ: as of Oct 10, 2026) https://www.zumper.com/rent-research/kitchener-on | Kitchener | $1,449 (−6% YoY) | $1,699 (−4%) | $1,992 (−1%) | $2,199 (−14%) | $3,350 (+36%) | median $1,815, −4% YoY (2024 peak $2,090) | $850 | 30-day rolling listings; apartments $1,800, condos $1,910, houses $2,224 |
| Zumper, Oct 14, 2026 https://www.zumper.com/rent-research/waterloo-on | Waterloo | $1,446 (+17%) | $1,795 (−2%) | $2,060 (−2%) | $2,385 (+2%) | $3,100 (+52% YoY, +60% 30-day) | median $1,996, flat YoY | n/a | neighbourhood medians: Beechwood $2,350, Lincoln Heights $2,078, Colonial Acres $1,935, Maple Hills $1,914, Lakeshore $1,909, Downtown Waterloo $1,905, Westvale $1,900, Uptown $1,895, Uptown West $1,875, Lincoln Village $1,845; houses $3,200 |
| Rentals.ca city page, "September 2026" (search snippet; page returns 403 to fetch) https://rentals.ca/waterloo | Waterloo | – | $1,884 | $2,302 | – | – | $2,158 all types | – | listing averages |
| Rentals.ca city page, Sept 2026 (snippet) https://rentals.ca/kitchener | Kitchener | – | $1,709 (Jul 2026 snippet: $1,684) | $2,063 (Jul: $2,078) | – | – | $1,935 | – | |
| Rentals.ca/Urbanation National Rent Report, Sept 2026 (title of summary at https://refdesk.ca/blog/rentals-ca-september-2026-asking-rent-2034-24-months-decline-renters-landlords-guide ; page 429) | Canada | | | | | | $2,034, −4.2% YoY, "24th straight annual decline" | | KW rows not retrieved |
| liv.rent August 2026 Ontario report, via liv.rent post of Aug 28, 2026 https://liv.rent/blog/renters/buy-vs-rent-kitchener-waterloo-ontario/ | Kitchener | | unfurnished $1,635 | | | | | | same post cites MyNextKWHome snapshot Aug 24, 2026: Kitchener $2,180, Waterloo $2,328 avg asking; KWC combined 1-bed $1,707, 2-bed $2,149, 3-bed $2,683 |
| MyNextKWHome, Jul 2026 (snippet; page 429) https://www.mynextkwhome.com/rent/market-report | KW (MLS) | | $1,683 | $2,054 | $2,659 | | $2,159 | | |
| Door Insight, Aug 2026 (snippet; page 403) https://doorinsight.com/rent-stats/on/waterloo | Waterloo | | | median $2,145, −6.7% YoY | | | | | |
| Rentals.ca report of Oct 28, 2025 via Global News Oct 29, 2025 https://globalnews.ca/news/11498829/international-student-cap-canada-rent-prices | KW | | | | | | avg rents −6.8% YoY (Toronto −8.1%, London −6.6%; Ontario −5.8%) | | Academica Oct 30, 2025: new international student arrivals −69% H1 2025 vs H1 2024 https://academica.ca/top-ten/student-rental-prices-fall-near-pse-institutions-after-federal-cap-report/ |
| D&D Property Management, Apr 2026 https://ddpropertymanagement.ca/kw-rental-market-report | KCW | | median ~$1,820 | ~$2,210 | | | vacancy ~2.1%; new-lease YoY ~+5.4% | | blends own portfolio; low reliability |

StatCan's Quarterly Rent Statistics (CMA-level asking rents) exists and its Q1 2026 release charts KCW, but the KCW value was not retrieved: https://www150.statcan.gc.ca/n1/daily-quotidien/260609/dq260609c-eng.htm

---

## 2. Student-specific

### 2.1 Rooms in shared houses near UW/Laurier, 2025–26 asking [L]

RentWoch (WOCH) list page dated Oct 21, 2025, 31 listings, mostly Northdale/Columbia/State St 5-bed houses, per-room "starting at": https://rentwoch.com/housing/student-housing-waterloo-2025-2026-rentwoch-off-campus-rentals/

| Address | Beds/baths | Start | Per-room ask | Notes |
|---|---|---|---|---|
| 22 Columbia St W | 5/2 | Sept 2026 | $610 | |
| 57 Columbia St W | 5/2 | Sept 2026 | $625 | |
| 400 Albert St (single rooms) | 4/1 | May/Sept 2026 | $625 | hydro, water, gas, heat, internet, in-suite laundry included; **sublets from $500 (May 1–Aug 25, 2026)** |
| 24 Columbia St W | 5/2 | Sept 2026 | $650 | **8-month lease from Sept 1, 2026** |
| 313 Spruce St | 5/2 | Sept 2026 | $650 (card) | "REDUCED PRICE FROM $695.00 ALL INCLUSIVE" |
| 64–66 Cardill Cres | 5/2 | Sept 2026 | $675 | |
| 419 Hazel St / 303 Westcourt Pl / 134 Columbia St W | 3/1, 5/2, 5/3 | Sept 2026 / Jan 2027 / Jan 2027 | $695 | 134 Columbia: "8 AND 4 MONTH OPTIONS AVAILABLE FOR JAN 2027", "PRICES REDUCED FROM $695" |
| 505–517 Sunnydale Pl | 3–4 bed townhomes | Sept 2026 | $695–$750 | "INCLUDING hydro, water & gas" |
| 64 University Ave E | 5/2 | May 2027 | $725 | 12-month lease |
| 267 State St | 3/1 | May 2026 | $820 | "REDUCED PRICE ... PER ROOM PLUS" utilities |
| 118 Columbia St W / 146 King St N | 5/3, 5/2 | Sept / May 2026 | $850 | parking extra |
| 271 State St | 5-bed and 4-bed units | May 2026 | $875 / $899 | 5-bed: tenants pay hydro/water/gas |
| 275 State St / 273-3 State St / 341 Lester St / 400B Albert St | 2/1, 5/2, 5/5, 4/4 | Sept/May/Sept/Sept 2026 | $895 | 341 Lester "NEW PRICE", **all-female roommates** |
| 42 Beech St | 5/2 | May 2026 | $925 | |
| 279 State St | 5/2 | May 1, 2026 | $950 | unfurnished, tenants pay utilities |
| 28 University Ave E | 5/5 | Sept 2026 | $995 | parking extra |
| 121 University Ave E | 5/2 | May 2026 | $1,000 | "$1000.00 PER ROOM" |
| 277 State St | 2/1 | no vacancy | – | "owner pays utilities for an extra $55/month per room" |

Kijiji / Realtor.ca examples (search snippets only; listing pages not fetched):
- 336 King St N, furnished rooms "$790.00 per room", gas/water/sewer/hydro/internet included: https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/waterloo-student-rooms-rental/1732122213
- Austin Dr 5-bed, $800/month per room, lease from May 1, 2026; Columbia St furnished rooms "$895.00 all inclusive"; Hickory St rooms from $595; "girls-only spring sublet" Columbia St $550: https://www.kijiji.ca/b-room-rental-roommate/kitchener-area/room-for-rent-in-waterloo/k0c36l1700209
- Beechwood: 77 Helene Cres $775 (Sept 1, 2026); Beechwood upstairs bedroom **$820/month on an 8-month lease or $780/month on a 12-month lease**; Lakeshore furnished 5-bed house $900/room: https://www.kijiji.ca/b-room-rental-roommate/kitchener-area/university-rent-student/k0c36l1700209
- 191 Cedarbrae Ave, 5-bed upper unit, **4-month summer sublet $700, marked down from $950** (May 1–Aug 27, 2026): https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/reduced-renovated-furnished-student-rental-near-cc-uw-wlu/1736660444 ; Kitchener basement room May–Aug sublet $575 utilities included: https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/575-basement-room-kitchener-sublet-gone-by-may/1734967689
- 16 Marshall St (Realtor.ca, house listing): "room-by-room basis at $805 per room": https://www.realtor.ca/real-estate/30077385/16-marshall-street-waterloo
- Places4Students Laurier index (snippets; page 429 on fetch): room-level rents mostly ~$700–$965, overall ~$650 to $1,900+; 338 King St N, one bedroom in a 5-bed unit $725+; some 4-month terms and Jan 2027 starts: https://www.places4students.com/schools/202/listings/properties . 345 King St N furnished room, 12-month leases "$930 to $965", guarantor required: https://www.places4students.com/schools/200/listings/properties/221350
- Zumper Kitchener "rooms" average $850 (Oct 14, 2026; see 1.7).
- Globe and Mail, Nov 16, 2025 [A]: a UW international student shared summer accommodation with four others at $800/month, "at least $200 below the recent average"; CMHC analyst (KW): "There's less competition for units": https://www.theglobeandmail.com/canada/education/article-immigration-international-student-limits-visas-universities-colleges/

[C] Across the 30 RentWoch rooms with a price, the per-room asks cluster between $610 and $1,000; the Kijiji/Places4Students snippets fall in $550–$965.

### 2.2 Purpose-built student housing (PBSH), per bed/room [L]

- thestudentsublet.com, Sept 7, 2026 [A]: furnished private bedroom in a shared 4–5-bed apartment $800–$1,100; **ensuite room in a purpose-built student building $1,050–$1,350**; private 1-bed/studio $1,700–$2,200; listing activity for September "can start in May or June, once co-op matches are finalized"; after Aug 1 unbooked rooms "often face price drops"; standard student leases "often include water and high-speed internet", hydro "billed separately or capped": https://thestudentsublet.com/blog/fall-2026-sublet-guide-waterloo
- uhomes.com Waterloo index (57 properties, 12 shown; CA$/month "from" prices; per-bed vs per-unit basis not stated): Bridgeport House 328 Regina St N from $1,030; 58 Cardill Cres from $959; 64 Marshall St from $1,099; 308 King St N from $1,240; Blair House 256 Phillip St from $1,365; K2 Condo 158 King St N from $1,700; The Hub 130 Columbia St W from $1,829; 268 Lester St from $1,850; 311/316 Batavia Pl $1,900/$2,000; Vogue Residences 155 King St N from $2,070; ICON 330 Phillip St from $2,250: https://en.uhomes.com/ca/waterloo
- Apartments.com student page (search snippet; site is Cloudflare-gated): "Bridgeport House at 2 months free and King Street Towers at 1 month free"; "average student apartment at $1,785": https://www.apartments.com/waterloo-on/student-housing/
- 110 University Ave "rent starting at $950/month on a 12-month lease" (expired Kijiji ad, snippet): https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/spacious-student-accommodation-furnished-and-en-suite-bathroom/1737831474
- Kim Louie (broker), Mar 31, 2026 [A]: 1-bed near the universities $1,800–$2,000 in 2023, "now listed at $1,600–$1,750"; ICON and Sage "added over 2,000 beds" since 2022: https://kimlouie.net/2026/03/31/the-student-housing-reversal-navigating-waterloos-new-rental-reality
- PayProp, Dec 11, 2025, summarizing The Globe and Mail [A]: average 2-bed near campus in Waterloo **$2,221 in July 2025, down 5% YoY; 2-bed rents elsewhere in Waterloo −2.1%**; Kitchener property manager: landlords "cutting prices, offering shorter leases, and renting to tenants they might previously have seen as a risk": https://www.payprop.com/blog/ontario-slow-student-rental-market (original Globe piece not retrievable; PayProp's text says "within two kilometres of Conestoga College", which may be a summarizing error)
- Zoocasa, May 28, 2026 [A]: "sublets on University Avenue and Phillip Street ... about $495 to $600"; "some buildings are also offering incentives like one month free on fall leases"; newer towers near ION "still achieving premium rents, but ... taking longer to lease up": https://www.zoocasa.com/blog/student-rental-markets/
- lease24.io, Jun 18, 2026 [A]: Waterloo rents "fell about 8 to 9% year-over-year by early 2026"; median ~$1,950; 1-bed $1,700–$2,100: https://lease24.io/blog/waterloo-rental-market-2026-student-housing-and-tech-worker

### 2.3 Institutional and co-op per-term pricing [M, posted rates]

- WCRI A-Dorms, 280 Phillip St, 4-month contracts incl. rent, utilities, internet: Fall 2026 double $2,009, single $2,509–$2,609, large single $3,179–$3,229; Winter 2026 double $1,680, single $2,112–$2,213; Spring 2026 double $1,282, single $1,680–$1,781, large single $1,957–$2,007; $800 two-term commitment fee for new fall members: https://wcri.coop/housing-charges/ . [C] Fall single ≈ $627–$652/month; Spring single ≈ $420–$445/month (−33%); double Fall ≈ $502/month.
- Conestoga College housing, 60 University Ave E (N2J 2V8), furnished room in 3- or 5-bed apartment, hydro/water/heat/internet included: Fall 2025 contract Sept 1, 2025–Aug 24, 2026 $9,588 total (monthly plan $799/month); Winter 2026 contract Jan 5–Aug 24, 2026 $6,392: https://www.conestogac.on.ca/student-housing/conestoga-housing/waterloo-60-university-ave-east . 400B Albert St $899 private room/private bath, $849 shared bath (snippet): https://www.conestogac.on.ca/student-housing/conestoga-housing/waterloo-400b-albert-st . 50 University Ave E shared room $5,988/yr or $499/month (2024–25): https://conestogac.on.ca/student-housing/conestoga-housing/waterloo-50-university-ave-east
- UW Campus Housing (co-op page): "4-month all-inclusive hassle-free contracts" for winter/spring and "8-month (fall-winter or fall-spring) contracts": https://uwaterloo.ca/co-operative-education/your-work-term/find-place-to-live-co-op

### 2.4 Four-month sublets and the discount [A/L — no measured series exists]

| Evidence | Term | Full ask | Sublet ask | Discount [C] |
|---|---|---|---|---|
| 400 Albert St (RentWoch, Oct 2025) | May 1–Aug 25, 2026 | $625 | from $500 | −20% |
| 191 Cedarbrae Ave (Kijiji snippet) | May 1–Aug 27, 2026 | $950 | $700 | −26% |
| WCRI single room (posted rates) | Spring 2026 vs Fall 2026 | $2,509–2,609/term | $1,680–1,781/term | −32% to −33% |
| Zoocasa (May 2026) | summer | – | $495–$600 on University Ave/Phillip St | – |
| UW CESA student page (undated, old) https://www.eng.uwaterloo.ca/~uwcesa/housing.php | winter | – | "reducing rent by $20 or $25"; spring "under $300/month ... as low as $200" | – |
| Beechwood room (Kijiji snippet) | 8-month vs 12-month lease | $780 (12-mo) | $820 (8-mo) | **+5.1% premium for 8-month** |

Direction is consistent across sources (summer/spring cheapest, 8-month dearer than 12-month) but the magnitudes are single listings.

### 2.5 What "all-inclusive" covers [L]

- Conestoga: "hydro, water, heat and high-speed internet" plus furnished room (60 University Ave E; 50 University Ave E pages above).
- WCRI: "Rates include rent, utilities, and internet" (wcri.coop above).
- 400 Albert St: free "hydro, water, gas, heat" plus internet and in-suite laundry; 505–517 Sunnydale: "hydro, water & gas"; 277 State St: utilities for +$55/month per room (RentWoch above).
- Private listings vary and contradict themselves: 392 Albert St listing says internet and hydro included and also that tenant pays hydro (https://www.padmapper.com/rentals/19345529p/studio-5-bath-apartment-at-392-albert-st-waterloo-on-n2l-3v1); Hemlock St unit includes internet, heat, A/C, water, tenant pays hydro only (https://malkearns.meadowtownerealty.com/listing/707-251-hemlock-street-waterloo-ontario-x13218048/); Columbia-area house "$799 inclusive of all utilities except internet & phone" (https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/students-rental-in-waterloo/1737266476).
- City of Waterloo student guide (PDF, last modified Apr 10, 2024): parking, storage, internet and utilities are "often ... not covered in your rent"; "most landlords will request the first and last month's rent upfront": https://www.waterloo.ca/media/ef5ne5fc/student-guide-to-housing.pdf

### 2.6 Major PBSH buildings and operators, Northdale / King St N / University Ave corridor [M for addresses and bed counts where from operator or transaction notices]

| Building | Address (postal) | Operator / owner | Size | Source (date) |
|---|---|---|---|---|
| ICON Waterloo | 330 Phillip St (N2L 3W9), at Phillip & Columbia | Craft Property Group (management/leasing) | two 25-storey towers; furnished 2/3/4-person suites; "early bird pricing for 2027" waitlist | https://www.iconstudents.com/ (2026-10-14) |
| Sage Platinum I / Platinum II / Sage X / Sage VI | 250 Albert St / 308 Lester St / 257 Hemlock St / 251 Hemlock St | Sage Living (office 3-180 Columbia St W) | furnished suites | https://www.sagecondoliving.ca/ and its project pages (2026-10-14) |
| King Street Towers I & II | 333 and 339 King St N | Alignvest Student Housing REIT | 17 storeys/536 beds and 21 storeys/419 beds | https://www.multihousingnews.com/alignvest-acquires-ontario-student-housing-portfolio/ ; https://renx.ca/alignvest-buys-4-student-housing-buildings-doubles-portfolio (2019) |
| Preston House | 315 King St N (N2J 4H1) | Alignvest | 17 storeys, 310 beds, 62 furnished units, built 2013 | https://www.reminetwork.com/?p=26828 |
| Bridgeport House | 328 Regina St N (N2J 0B5) | Alignvest-owned; OSM labels it "Rez-One - Bridgeport House" | 18 storeys, 485 beds, 97 furnished units, built 2014 | same; https://www.connectcre.ca/stories/alignvest-acquires-new-waterloo-student-housing-asset/ |
| Hespeler House and Fergus House | 252 and 254 Phillip St (N2L 0E1) | Alignvest (acquired June 2024) | 21 storeys each, 476 beds each, furnished 4-bed/4-bath suites | https://gslglobal.com/2024/06/26/ash-reit-hespeler-and-fergus-house-closing-press-release-june-2024-pdf/ |
| 308 King | 308 King St N (N2J 2Z2) | Alignvest (binding agreement) | 25 storeys, 340 furnished apartments, 659 beds; REIT portfolio 5,302 beds after it | https://renx.ca/index.php/alignvest-acquires-new-340-apt-waterloo-tower |
| Elora House / Blair House | 250 / 256 Phillip St (N2L 6B6) | Rez-One | Elora: 21 storeys, 119 suites, opened Sept 2022 | https://rez-one.ca/ ; https://campusguides.ca/2021/09/03/best-places-to-live-at-near-the-university-of-waterloo/ |
| Accommod8u / KW4Rent | 228 Albert St, 246 Albert St, 250 Lester St (Accommod8u); 251 Lester St (KW4Rent) | same parent company per WUSA Housing Report May 2021 | – | https://www.accommod8u.com/ ; https://wusa.ca/wp-content/uploads/2022/08/WUSA-Housing-Report-May-2021-1.pdf |
| 167 and 173 King St N | 167 King St N | Centurion Apartment REIT (2013 acquisition); 167 King is 12 storeys, 205 students, 41 units | https://www.reminetwork.com/?p=1357 ; https://masrioarchitects.ca/portfolio-item/167-king-st/ |
| The MARQ | 1 Columbia St W (N2L 0C8) | – | furnished 5-bed ensuite units | https://erasmusplay.com/zh/waterloo/apartments/1-columbia-st-w-waterloo-on-n2l-0c8-canada-11884780 |
| The Hub | 130 Columbia St W (N2L 0G6) | – | – | https://en.uhomes.com/ca/waterloo |
| WCRI (co-op) | 280 Phillip St | member-owned co-op | "over 1300 residents in its 13 dormitories and apartments" (2024) | https://en.wikipedia.org/wiki/Waterloo_Co%E2%80%91operative_Residence_Inc. (edited Jul 26, 2026) |
| Conestoga College leased housing | 50 and 60 University Ave E; 400B Albert St | Conestoga | furnished 3/5-bed suites | Conestoga pages above |
| Laurier Ezra-Bricker apartments | near Laurier | Laurier-owned, managed by Campus Living Centres | – | https://students.wlu.ca/student-life/residence-and-off-campus-housing/off-campus-initiatives/off-campus-housing.html |

Names "Luxe" and "Society 145" came up in the task but could not be verified in this pass. 345 King St N is described as a 386-student, 94-unit building only in a low-reliability brokerage upload.

Bed stock [M]: City of Waterloo Student Accommodations Report 2023 (2022/23 data): on-campus beds 9,235; low-density licensed rental beds 5,900; multi-residential beds in the catchment area 22,285; traditional apartment beds 2,445; total 39,865; off-campus 30,630; potential off-campus tenants 35,360; implied deficit ~4,730; average multi-residential beds per unit 2.6 (down from 3.5 in 2016); 4,660 potential future beds; Waterloo holds 42.0% (17,567 beds) of Canada's off-campus PBSH per a 2019 study cited in the report: https://www.waterloo.ca/media/vz1oskqu/student-accommodations-report-2023.pdf

### 2.7 Policy and news, 2024–2026

- IRCC study-permit cap [M]: began January 2024; issuance targets 485,000 (2024), 437,000 (2025, −10%), up to 408,000 (2026: 155,000 new arrivals + 253,000 extensions; −7% vs 2025, −16% vs 2024); 309,670 application spaces for PAL/TAL-required applicants in 2026; Ontario allocation 104,780 PAL/TAL-required applications (notice dated Nov 25, 2025): https://www.canada.ca/en/immigration-refugees-citizenship/news/notices/2026-provincial-territorial-allocations-under-international-student-cap.html . Auditor General, March 2026: cap extended to 2027; in 2024 fewer than half the forecast new permits were approved; study permit holders in Canada fell from over 1,000,000 (Jan 2024) to about 725,000 (Sept 2025): https://www.canada.ca/en/auditor-general/media-room/international-student-program-reforms-controlled-growth-fell-short-improving-integrity.html ; https://www.canada.ca/en/immigration-refugees-citizenship/corporate/reports-statistics/statistics-open-data/immigration-stats/students-workers.html . (Zoocasa's "70,074 permits for Ontario, −42%" conflicts with the IRCC figure; treat Zoocasa's as unverified.)
- UW [M]: Board SPF minutes, Oct 14, 2025: "In 2024/25 Waterloo registered slightly over 7,000 international students on campus, about 41% of the overall graduate student body and around 15% of the overall undergraduate student body. The undergraduate international applicant pool decreased, in part influenced by the federal government caps on study permits"; domestic undergrad intake +2% in fall 2025; international graduate enrolment "steady"; teaching ~500 more students than planned: https://uwaterloo.ca/secretariat/sites/default/files/uploads/documents/2025-10-14-spf-minutes-draft.pdf . 2025–26 Operating Fund structural deficit $44M (revenue $842M, expenses $886M), drivers include "limits on international enrolments": https://uwaterloo.ca/waterloo-budget-plan/frequently-asked-questions ; https://uwaterloo.ca/daily-bulletin/2026-02-03 . The "−12% international undergrad fall 2025" (Kim Louie) and "−30%, $75M deficit" (aggregator) claims were not confirmed by a UW source.
- Region [A/M]: Observer Xtra, Mar 12, 2026: Waterloo Region "shed more than 25,000 foreign students in two years"; Conestoga College international enrolment −75%; 8,060 new/extended permits at Conestoga "last year": https://www.observerxtra.com/falling-number-of-foreign-students-lead-decline-in-regions-population/
- CMHC/CTV linkage of vacancy to student demand: sections 1.1 and 1.6. CTV Jan 7, 2025 (tenants' group) only restates the 30-year-high vacancy: https://www.ctvnews.ca/kitchener/article/tenants-group-demands-action-as-high-rents-persist-despite-rising-vacancies/
- Operator incentives: CMHC "1–2 months of free rent" (1.1); Apartments.com "2 months free" Bridgeport House and "1 month free" King Street Towers (2.2); Zoocasa "one month free on fall leases" (2.2); RentWoch "1 FREE MONTH LIMITED TIME" on a Sept 2026 5-bed suite (https://rentwoch.com/). PBSH per-bed price cuts: no measured series found; only "REDUCED PRICE" markers on house listings and the lease24/Kim Louie commentary.
- Short-term rentals: City of Waterloo limited STRs to principal residences (Jan 2025): https://www.ctvnews.ca/kitchener/article/city-of-waterloo-limits-short-term-rentals-to-principal-residences/ ; Kim Louie says the apartment-unit STR exemption ends July 2026 and ~100 of ~500 STRs may return to long-term rental [A].

---

## 3. Structural facts (features and cleaning rules)

### 3.1 Lease cycle and terms
- UW co-op: "a work term is normally four months long"; "All sequences contain at least one eight-month school term and some will contain one eight-month work term": https://academic-calendar-archive.uwaterloo.ca/undergraduate-studies/2023-2024/page/Co-operative-Education-Program-Regulations.html
- UW off-campus housing: "Typically, a lease is one year in length"; "Due to the co-op work terms outside of the region, subletting is common for Waterloo students"; landlords sometimes ask "more than 60 days' notice to terminate a tenancy (sometimes even 7 or 8 months!)": https://uwaterloo.ca/off-campus-housing/signing-lease ; co-op housing page: advertise your unit "to avoid paying rent in two places"; Co-op Connection Discord housing channels; Places4Students, Facebook Marketplace/groups, Kijiji named as sources: https://uwaterloo.ca/co-operative-education/your-work-term/find-place-to-live-co-op
- Market evidence of 8-month leases: RentWoch 24 Columbia (8-month from Sept 1, 2026), 134 Columbia (8- and 4-month options for Jan 2027), Beechwood $820/8-mo vs $780/12-mo, Conestoga Winter contract Jan 5–Aug 24, UW Campus Housing 8-month contracts (2.1, 2.3).
- Timing: thestudentsublet: September-term listings start May/June after co-op matches, post by Aug 1; City guide: "many leases are signed 6 to 12 months before the move-in date"; RentWoch (Oct 2025) already lists May 2026, Sept 2026, Jan 2027 and May 2027 starts.
- Ontario law on terms (LTB "A Guide to the RTA", last updated July 2026): "The end of a lease does not mean a tenant has to move out"; a monthly-paying tenant continues as a monthly tenant on the same terms; assignment = new person replaces the tenant; sublet = tenant returns before the tenancy ends; both need landlord approval and the landlord must have "a good reason for refusing"; rent deposit at most one month (or one week for weekly tenants) and usable only for the last month: https://tribunalsontario.ca/documents/ltb/Brochures/Guide%20to%20RTA%20(English).html . "Lease takeover" has no statutory definition; in local listings it means taking the remainder of a fixed term (assignment), while "sublet" means a short Jan–Apr or May–Aug stay: https://www.kijiji.ca/b-for-rent/kitchener-area/waterloo-sublet/k0c30349001l1700209

### 3.2 Rent-control exemption [M, official]
ontario.ca "Residential rent increases" (Updated June 23, 2026): the guideline "does not apply to new buildings, additions to existing buildings and most new basement apartments that are occupied for the first time for residential purposes after November 15, 2018"; in a dispute "the landlord must prove that the building was first occupied for residential purposes after November 15, 2018"; 90 days' written notice; guidelines 2019 1.8%, 2020 2.2%, 2021 0% (freeze), 2022 1.2%, 2023 2.5%, 2024 2.5%, 2025 2.5%, **2026 2.1%, 2027 1.9%**: https://www.ontario.ca/page/residential-rent-increases . LTB guide (July 2026): units not occupied residentially on or before Nov 15, 2018 "may be exempt from the rent increase guideline"; still 90 days' notice, no limit on size. Several PBSH towers above opened 2013–2014 (Preston, Bridgeport, 167 King) and are therefore under the guideline; Elora House (2022), ICON and the Sage towers post-date the cut-off.

### 3.3 City of Waterloo rental licensing [M]
- Current: Bylaw 2025-044, "Comprehensive Residential Rental Licensing Bylaw", in force **July 1, 2026**: Class A "a Low-Rise Residential Rental Unit where the property owner does not reside and has five (5) Bedrooms or less"; Class B owner-occupied with "five (5) tenant occupied Bedrooms or less"; Class C "operating as Lodging House" (Lodging House: owner "offers Lodging Units to five (5) or more persons, with or without meals"; building ≤600 m², ≤3 storeys, ≤2 bathrooms, 1 kitchen); Class D grandparented; Class S short-term rental in an apartment; bedroom floor area 14 m² for three occupants, 7 m² per adult for four or more; "No more than fifty per cent (50%) of the Rental Unit's Gross Floor Area shall be comprised of Bedrooms" (transitional exemptions to Jan 1, 2027); exempt: "A Rental Unit located in an Apartment Building, unless ... operated as a Short-Term Rental" (Apartment Building = 3+ storeys and 5+ units with interior corridor) and on-campus institutional housing: https://www.waterloo.ca/bylaws-and-enforcement/bylaw-directory/rental-housing-licensing-bylaw/ . Council summary June 23, 2025: https://www.waterloo.ca/news/posts/council-summary-june-23-2025/ . Class C fee $786 (application package rev. Jan 9, 2026): https://www.waterloo.ca/media/gyrohd1d/residential-rental-licence-application-package.pdf
- Prior regime (Bylaw 2011-047 as amended 2012-004, in force Apr 1, 2012, per OHRC): Class A/B "up to 4 bedrooms"; Class C lodging houses "5 or more bedrooms"; 7 m² per person; bedrooms ≤40% of GFA (A) / 50% (B); apartment buildings and university residences exempt: https://www.ohrc.on.ca/en/report-inquiry-rental-housing-licensing-city-waterloo/3-background
- City student guide (Apr 2024): licence required for any low-rise unit (≤3 storeys); unlicensed renting "can lead to up to $100,000 in fines"; licence lookup via the City's eservices portal; the guide lists "Waterloo general market average rent per unit": $1,771 1-bed, $1,917 2-bed, $1,991 3+ (source not stated): https://www.waterloo.ca/media/ef5ne5fc/student-guide-to-housing.pdf
- How this shapes listings: 5-bed houses dominate the per-room market (2.1) because 5 bedrooms was the lodging-house threshold under the old bylaw and is now the Class A cap; towers are licence-exempt, so "licensed" wording in ads applies to houses/townhouses/low-rise only; 2022/23 licensed low-density stock was 5,900 beds vs 22,285 multi-residential beds (2.6).

### 3.4 Postal-code prefixes (FSAs) [M]
Wikipedia list (accessed 2026-10-14): https://en.wikipedia.org/wiki/List_of_postal_codes_of_Canada:_N

| FSA | Canada Post name | What it covers (sample postal codes, OSM/Nominatim 2026-10-14) |
|---|---|---|
| **N2L** | Waterloo South | UW (N2L 3G1), Laurier 75 University Ave W (N2L 3C5), Northdale node (N2L 3T6), Hazel St (N2L 3P2), Lester St (N2L 3W6), Albert St (N2L 0G7), 252 Phillip (N2L 0E1), ICON 330 Phillip (N2L 3W9), The Hub 130 Columbia W (N2L 0G6), 268 Lester (N2L 3W5), 58 Cardill (N2L 3Y8), Bearinger Rd (N2L 5G4) |
| **N2J** | Waterloo Southeast | Uptown / Waterloo Public Square (N2J 1N9), 315 King St N (N2J 4H1), 328 Regina St N (N2J 0B5), 308 King N (N2J 2Z2), 155/158 King N (N2J 0E8 / N2J 2Y2), 60 University Ave E (N2J 2V8), 64 Marshall St (N2J 2T4) — the King St N corridor and east of it |
| N2K | Waterloo East | east of the Conestoga Parkway (no sample geocoded) |
| **N2T** | Waterloo Southwest | Laurelwood node (N2T 2R5), Keats Way (N2T 2C6), Erb St W (N2T 2Z7) — Beechwood/Westvale/Laurelwood |
| **N2V** | Waterloo Northwest | Laurelwood Dr (N2V 2W9), Columbia St W in Clair Hills (N2V 2V5), Westmount Rd N (N2V 2A4) |
| Kitchener | N2A East, N2B Northeast, N2C South Central, N2E Southwest, **N2G Central** (City Hall N2G 4G7), N2H North Central, N2M Northwest, N2N West, N2P Southeast, N2R South |
| Cambridge | N1R Central, N1S Southwest, N1T East, N3C Northeast, N3E Northwest, N3H West |

The student core (both campuses, Northdale, Phillip/Lester/Albert/Hazel/Columbia) sits in N2L; the King St N towers split between N2L (west of King) and N2J (King St N and Regina St N); Laurelwood straddles N2T/N2V; the Lakeshore area near Bearinger Rd sits at the N2L/N2V boundary (not fully resolved). Nominatim was queried at one request per 1.5 s with an identifying User-Agent: https://nominatim.openstreetmap.org/

### 3.5 Distances to campus [C from sourced coordinates]
Anchors: UW (43.4723, −80.5449) and Laurier (43.4738, −80.5275) from HANDOFF s.12; OSM centroids UW (43.4702, −80.5452; its relation's bounding box is very wide, so the HANDOFF point is the better campus anchor) and Laurier (43.4728, −80.5281); neighbourhood nodes from Nominatim 2026-10-14. Straight-line haversine, km.

| Place (coordinate) | to UW | to Laurier |
|---|---|---|
| Northdale node (43.4742, −80.5320) | 1.06 | 0.36 |
| Hazel St, Northdale (43.4786, −80.5307) | 1.35 | 0.59 |
| Hespeler House, 252 Phillip (43.4735, −80.5359) | 0.74 | 0.68 |
| Bridgeport House, 328 Regina N (43.4798, −80.5241) | 1.88 | 0.72 |
| Uptown / Waterloo Public Square (43.4640, −80.5223) | 2.04 | 1.17 |
| Laurelwood node (43.4696, −80.5794) / Laurelwood Dr centroid (43.4706, −80.5941) | 2.80 / 3.98 | 4.21 / 5.39 |
| Lakeshore (Lakeshore Optimist Park, 43.4981, −80.5549; Nominatim had no node for the neighbourhood itself) | 2.98 | 3.49 |
| Downtown Kitchener node (43.4507, −80.4926) / Kitchener City Hall (43.4516, −80.4922) | 4.86 / 4.84 | 3.82 / 3.77 |
| UW to Laurier | 1.41 | – |

At a 5 km/h walking pace, 1 km ≈ 12 minutes straight-line; OSM-centroid versions differ by ≤0.2 km.

---

## 4. Comparable tools

| Tool | What it shows | What it lacks for Waterloo students | Source |
|---|---|---|---|
| CMHC HMIP / Rental Market Survey | Official October averages and vacancy by bedroom, zone, CSD, neighbourhood, year built, structure size (sections 1.1–1.5) | Annual only; purpose-built 3+ unit structures only (no rooms in houses, no per-bed PBSH pricing, no condos in the primary tables); neighbourhood cells often "d" or suppressed; no lease-term or furnishing dimension | HMIP URLs in section 1 |
| Zumper Rent Research | City/neighbourhood medians by bedroom and property type incl. "rooms" (Kitchener $850), 30-day rolling, daily | No address-level estimate; Waterloo page has no "rooms" figure; "near University of Waterloo/Laurier" pages show only generic US/Canada tables; 4-bed cells swing ±50% (small n) | https://www.zumper.com/rent-research/waterloo-on ; https://www.zumper.com/rent-research/near-university-of-waterloo-on |
| Rentals.ca | City averages by bedroom from active listings; monthly national report with Urbanation; Oct 2025 student-city analysis | No public per-listing estimator found; blocks automated access (403); no room/per-bed or term-length view | https://rentals.ca/waterloo ; Global News Oct 29, 2025 |
| Rentometer | Address-level estimate: average, median, 25th/75th percentiles, sample size and radius, from asking rents | "Analyze rental markets across the United States" — US only | https://www.rentometer.com/rent-estimate |
| liv.rent | Monthly Ontario reports (furnished/unfurnished by city), landlord pricing guide | No Waterloo estimator; Waterloo figures borrowed from Kitchener ("numbers are taken from our latest data for Kitchener") | https://liv.rent/blog/renters/buy-vs-rent-kitchener-waterloo-ontario/ ; https://liv.rent/blog/landlords/how-much-to-charge-for-rent/ |
| HouseSigma / RentSeeker | HouseSigma: rental-yield assessment on sale listings; RentSeeker: city-average comparison studio–3-bed | No per-unit rent estimate confirmed; nothing student-specific | https://hardbacon.ca/en/mortgage/housesigma-review/ ; https://dailyhive.com/toronto/compare-canadian-rent-prices-real-time-rentseeker |
| StatCan Quarterly Rent Statistics | CMA-level quarterly asking rents by bedroom | CMA only; no sub-city or room data | https://www150.statcan.gc.ca/n1/en/surveys/5427 |
| Door Insight, MyNextKWHome, D&D PM | KW listing/MLS stats by bedroom (1.7) | No rooms, no distance, no term; D&D blends its own portfolio | URLs in 1.7 |
| UW Off-Campus Housing | Lease/sublet/assignment explanations, interactive neighbourhood map, Region "rental lingo" sheet (link broken) | No prices or ranges | https://uwaterloo.ca/off-campus-housing/ |
| WUSA Housing Playbook | Lease agreements, rights and responsibilities | No prices | https://www.ctvnews.ca/kitchener/article/4-people-living-in-1-bedroom-how-the-university-of-waterloo-is-helping-students-navigate-regions-housing-landscape/ |
| Laurier off-campus page | Partnership with Places4Students; lists Kijiji, Facebook Marketplace, PadMapper, Rentals.ca; "never rent a property unseen" | No prices | https://students.wlu.ca/student-life/residence-and-off-campus-housing/off-campus-initiatives/off-campus-housing.html |
| Places4Students | Listings with per-room prices, lease term (12-month, 4-month), utilities, sublet flags | No estimator or market statistics | https://www.places4students.com/schools/202/listings/properties |
| City of Waterloo Student Guide (2024) | Three average rents (3.3), licensing and lease basics | Source/date of rents not stated; no rooms | https://www.waterloo.ca/media/ef5ne5fc/student-guide-to-housing.pdf |
| Student-written guides | UW CESA page (undated: "$400/month" rooms, spring sublets "under $300"); campusguides.ca (2021) building list | Stale; no method | https://www.eng.uwaterloo.ca/~uwcesa/housing.php ; https://campusguides.ca/2021/09/03/best-places-to-live-at-near-the-university-of-waterloo/ |

Common gap: no tool prices a *room* or *bed* as a function of distance to campus, lease term (4/8/12 months), move-in month, furnishing and utilities together; none reports a percentile for a given listing.

---

## 5. Data-quality traps in Waterloo listings

| Trap | Evidence | Source |
|---|---|---|
| **Wanted ads mixed with offers** | Kijiji has "Offering" and "Wanted" ad types: "If you've accidentally posted as a Wanted ad instead of an Offering ad, or vice versa, you will need to delete and repost the ad." Room Rentals & Roommates carries "students looking for room to rent" ads. | https://help.kijiji.ca/helpdesk/basics/i-posted-my-ad-incorrectly (snippet; redirected page 404) ; https://www.kijiji.ca/b-room-rental-roommate/kitchener-area/students-looking-for-room-to-rent/k0c36l1700209 |
| **Per-room prices in whole-unit categories** | A listing titled "Waterloo student room rental" sits in Apartments & Condos; RentWoch cards show a per-room "starting at" price against a 5-bed/2-bath unit (and "$0" when no vacancy); Realtor.ca house listing priced "room-by-room ... $805 per room"; "$1000.00 PER ROOM" headings | https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/waterloo-student-room-rental/1736895849 ; RentWoch page (2.1); Realtor.ca 16 Marshall St (2.1) |
| **"Per person" phrasing / dual pricing** | Waterloo house on liv.rent: "$4250/month or $850 per person per month plus utilities"; Western's board shows the same pattern ("$1000 per bdrm") | https://liv.rent/index.html/rental-listings/detail/house/waterloo/86151 ; https://offcampus.uwo.ca/Listings/Details/43751 |
| **Gender-restricted rooms** | roomies.ca "females" pages for Waterloo; RentWoch 341 Lester "all-female roommates"; Kijiji "girls-only spring sublet $550". Legal basis: Ontario Human Rights Code s.21(1) (occupants "share a bathroom or kitchen facility with the owner or family of the owner") and s.21(2) (occupancy "restricted to persons who are of the same sex") | https://roomies.ca/rooms/riverside-cambridge-waterloo-county-on/females?page=7 ; https://www.ohrc.on.ca/en/policy-human-rights-and-rental-housing/iii-ontario-human-rights-code |
| **Per-term totals** | WCRI quotes 4-month totals ($2,009–$3,229); Conestoga quotes contract totals ($9,588 for Sept 1–Aug 24; $6,392 for Jan 5–Aug 24) with "monthly" instalments ($799) that run only Sept–June | https://wcri.coop/housing-charges/ ; Conestoga page (2.3) |
| **Weekly prices** | Not observed in any Waterloo source reviewed; Ontario law contemplates weekly tenancies (deposit "one week's rent") so the format is legal | LTB guide (3.1) |
| **Lease-length pricing in one ad** | "$820 monthly on an 8-month lease or $780 monthly on a 12-month lease"; 271 State St $875 (5-bed) vs $899 (4-bed) in one listing; 134 Columbia "8 AND 4 MONTH OPTIONS" | Kijiji snippet (2.1); RentWoch (2.1) |
| **Reduced-price markers and incentives** | "REDUCED PRICE FROM $695.00", "NEW PRICE $895.00", "HEAVILY DISCOUNTED $950 → $700"; "1 FREE MONTH"; "2 months free" (Bridgeport House); Kijiji sells a "Price Drop & Reduced" badge | RentWoch; Kijiji snippets; https://help.kijiji.ca/performance/PriceDrop |
| **Posting date is not first-seen date** | "Most Kijiji ads remain active for 60 days before they expire"; reposting "creates a new posting period" and "places it back among the newest ads in its category"; older help text: "Bump Up ... will reset the post date of your ad, but it won't extend its duration"; paid Real Estate Professional ads run 31 days then need reposting | https://community.kijiji.ca/helpdesk/basics/how-long-are-ads-active (posted May 25, 2026) ; https://help.kijiji.ca/performance/BumpUp |
| **Cross-posting across sites** | Laurier directs landlords/students to Places4Students, Kijiji, Facebook Marketplace, PadMapper and Rentals.ca; the same Northdale addresses appear on RentWoch, Kijiji, Places4Students and uhomes (e.g., 345 King St N, 400 Albert St, Columbia St W houses) | Laurier page (4); RentWoch; Places4Students; uhomes (2.2) |
| **Far-future move-in dates** | Oct 2025 page lists May 2026, Sept 2026, Jan 2027 and May 2027 starts; Places4Students shows Jan 2027 starts; stale text ("September 2020", "start searching by December 2024") survives in live listings | RentWoch (2.1); Places4Students (2.1) |
| **Utilities contradictions** | 392 Albert St listing says hydro included and tenant pays hydro; "all inclusive except internet & phone" | 2.5 |
| **Parking/storage ads in rental categories** | Not verified in this pass (no Kijiji index page was fetched); Kijiji's For Rent index for KW is at https://www.kijiji.ca/b-for-rent/kitchener-waterloo/c30349001l1700212 | – |
| **Survey-universe mismatches when sanity-checking** | CMHC apartment-only vs row+apartment (4.1% vs 4.0%; $1,832 vs $1,816); third-party "CMHC" restatements differ (WealthNorth: 1-bed $1,548 +3.3%, 2-bed $1,834 +3.7%, vacancy 4.2% for 6+ unit buildings) | 1.1–1.2; https://wealthnorth.ca/housing/rentals/kitchener-waterloo/ |
| **Small-sample tracker swings** | Zumper Waterloo 4-bed +52% YoY / +60% in 30 days; Kitchener 3-bed −14% YoY | 1.7 |

---

## 6. Measured vs anecdotal, and what bears on the model

**Measured [M]:** everything in sections 1.1–1.6 (CMHC), 2.3 posted institutional rates, 2.6 addresses/bed counts from operators and transaction notices, 2.7 IRCC/Auditor General/UW minutes, 3.2 Ontario guideline and exemption wording, 3.3 bylaw text, 3.4 FSAs. **Listing snapshots [L]:** 1.7 trackers, 2.1–2.2 asking prices, 2.5 utilities. **Anecdotal [A]:** broker/blog commentary (Kim Louie, lease24, Zoocasa, thestudentsublet, PayProp's Globe summary), single Kijiji ads. **Computed [C]:** distances, per-month equivalents, discount percentages.

Facts that bear on schema fields (no recommendations):
- `price_per_bedroom`: official 1-bed rents in the City of Waterloo were $1,747 (zone) and $1,832 ("Waterloo University" neighbourhood) in Oct 2025, while per-room asks in 5-bed Northdale houses cluster at $610–$1,000 and PBSH "from" prices at $1,030–$1,365 for Bridgeport/308 King/Blair House; whole 2-beds near campus asked ~$2,221 (Jul 2025) vs $2,277 CMHC neighbourhood average.
- `unit_type` / `bedrooms`: 3+ bed vacancy is far lower (Zone 4 1.2%, CMA 1.8%) than 1-bed (4.7%); 5-bed houses are the modal per-room product because of the licensing threshold.
- `lease_term` / `move_in_month`: one listing shows an 8-month premium of ~5%; summer/spring sublets show −20% to −33% in the few priced cases; September listings surface in May–June; the market also carries 12-month leases starting in May.
- `building_type` / `year_built_after_2018`: CMHC's "2000 or later" stock in the Waterloo zone rents at $2,279 vs $1,722 for 1980–1999 (+32%) and has 1.9% vacancy vs 4.2%; CMHC has no 2018 split, so the feature must come from listing/operator text (Elora 2022, ICON, Sage are post-2018; Preston 2013, Bridgeport 2014, 167 King 2013 are pre-2018).
- `neighbourhood` (postal prefix): N2L contains both campuses and Northdale; N2J contains the King St N towers and Uptown; CMHC's own "Waterloo University" vs "Uptown" split shows a 15% 2-bed gap.
- `utilities_included` / `furnished`: institutional and many house listings bundle hydro, water, heat, gas and internet; private ads contradict themselves, and internet is the item most often excluded.
- `days_on_market`: Kijiji ads last 60 days and reposts/bumps reset ordering and (per older help text) the post date.
- Sanity-check anchors: CMA average rent +3.3% (CMHC, Oct 2025) vs asking-rent trackers at −2% to −7% YoY in 2026 (Zumper, Door Insight, Rentals.ca Oct 2025), i.e. sitting-tenant averages and asking rents are moving in opposite directions.

**Not retrieved / gaps:** October 2024 zone and neighbourhood tables (HMIP needs a form POST); rentals.ca pages and report tables (403); Places4Students listing index (429); CTV Jan 2025 article body; CMHC neighbourhood boundary definitions; any measured series of PBSH per-bed price changes; verification of "Luxe" and "Society 145"; UW's official fall-2025 international enrolment percentage.
