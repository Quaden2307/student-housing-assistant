# Sources

What we know about each listing source: reachability, robots.txt, terms, page structure, which
schema fields it carries, and the counts we have seen. Updated 2026-10-14 from a read-only probe
(12 requests total across four sites, 3 s apart, one desktop Chrome User-Agent, raw responses
saved gzipped under `data/raw/<source>/2026-10-14/`). Re-check robots.txt before every sweep.

## Summary

| Source | Reachable with plain HTTP | robots.txt for our paths | Terms on scraping | Listing JSON | Verdict (Oct 14) |
|---|---|---|---|---|---|
| Kijiji KW (apartments c37, rooms c36) | Yes, all 8 requests 200, no bot wall | Index and detail paths allowed; query-string filters and `/rss-*` disallowed | Prohibits "robot, spider, scraper or other automated means ... without our express written permission" | `__NEXT_DATA__` with a normalized Apollo cache, plus ld+json | Primary source. Needs Caden's call on the Terms clause. |
| rentals.ca | No: city page returns 403 Cloudflare managed challenge | `Allow: /`, but JSON feeds (`*-feed.json`), map `bbox=` and filter facets disallowed | Not read (page unreachable) | Unknown | Blocked for curl. Cheapest candidate if a browser-profile fallback is ever tried. |
| Zumper | No: JavaScript "Client Challenge" even for robots.txt | Unknown | Not read | Unknown | Blocked. Drop unless a real need appears. |
| Places4Students | No: HTTP 429 Vercel Security Checkpoint on robots.txt | Unknown | Not read; search-engine summary says scrapers need written permission | Unknown | Blocked. Drop. |
| apartments.com | Not tried | Not tried | Prohibits scraping (HANDOFF section 4) | n/a | Skipped per HANDOFF. |
| Facebook, Instagram | Never | n/a | n/a | n/a | Manual-entry form only. |

## 1. Kijiji Kitchener-Waterloo (primary)

URLs (location id `l1700212`, categories c37 long-term rentals and c36 room rentals and roommates):

- `https://www.kijiji.ca/b-apartments-condos/kitchener-waterloo/c37l1700212`
- `https://www.kijiji.ca/b-room-rental-roommate/kitchener-waterloo/c36l1700212`

### Counts seen

| Date | Apartments, condos and houses | Rooms and roommates | Note |
|---|---|---|---|
| 2026-09-29 | 1,522 | 309 | HANDOFF section 4 |
| 2026-10-14 | 1,612 | 260 | `pagination.totalCount` in the index JSON; "Results 1 - 40 of 1,612" on the page |

Sweep log (fill in from the first sweep on): date, category, pages fetched, listings seen, new, gone.

| Date | Category | Pages | Seen | New | Gone |
|---|---|---|---|---|---|
| | | | | | |

### robots.txt (fetched 2026-10-14; `Last-Modified: 13 Oct 2026`, so it changes; re-fetch each run)

Two groups, `Mediapartners-Google` and `User-agent: *`. The `*` group has 233 `Disallow` rules, no `Allow`,
no `Crawl-delay`, no `Sitemap`. Lines that matter for us:

- `Disallow: /v-*/*/*/c*` only matches detail URLs whose fourth path segment starts with `c`. Live detail
  URLs end in a 10-digit ad id, so they are allowed.
- There is no `/b-` rule in the `*` group, so both index paths and their `/page-N/` forms are allowed.
- `Disallow: /rss-*`: no RSS feeds.
- Under `# Search params`, one rule per query parameter, including `sort=`, `price=`, `bedrooms=`,
  `address=`, `ll=`, `radius=`, `imageNumber=`, `adId=`, `move-in-date=`, `furnished=`.
  Consequence: fetch clean path-only URLs, never add a query string. The default server sort is already
  date descending. Strip `?imageNumber=N` variants from listing links found in the HTML.

### Page structure

Both index and detail pages are server-rendered Next.js. Each page has exactly one
`<script id="__NEXT_DATA__" type="application/json">` whose `props.pageProps.__APOLLO_STATE__` is a
normalized Apollo cache, plus `application/ld+json` blocks (`ItemList` of `SingleFamilyResidence` on the
index, one `SingleFamilyResidence` and a `BreadcrumbList` on detail). No `window.__*` store.

Index page: `ROOT_QUERY["searchResultsPageByUrl:<path>"]` holds `pagination {offset, limit: 40, totalCount}`,
`results.topListings` (promoted, 6 on apartments and 1 on rooms, may duplicate a main listing: dedupe by id)
and `results["mainListings({...})"]` (40 refs, ordered by `sortingDate` descending). Listing entities are
`RealEstateListing:<id>` (apartments) and `StandardListing:<id>` (rooms). Pagination is not rendered in the
HTML and the string `page-2` appears nowhere on page 1; the API paginates by `offset`/`limit`. The
`/page-2/` path form is allowed by robots but has not been verified yet. Verify with one request on day one.

Detail page: `ROOT_QUERY['listing({"id":"<id>","isExternalId":false,"trackView":true})']` points at the same
entity type with the full `description` (plain text, `\r\n` newlines, no HTML), attributes with display
values, `endDate` (activation + 60 days: Kijiji ads expire after 60 days unless renewed), `metrics.views`,
`posterInfo` and a `StandardProfileV2` profile entity.

Fields on an index card (same values on the detail page unless noted): `id`, `title`, `description`
(truncated to about 200 characters on the card), `url`, `activationDate` (first posting), `sortingDate`
(last bump; differed from activation on 41 of 45 apartments cards), `price.type` FIXED or CONTACT and
`price.amount` in cents, `location.address` (free text; postal code inside it on 44 of 45 apartments cards and
34 of 41 rooms cards, street number on 40 of 45 and 11 of 41), `location.coordinates` (5 decimals; listings
without a street number share a postal-code centroid; the detail page rounds to 2 decimals when
`showPinOnMap` is false, so keep the card's coordinates), `location.nearestIntersection` (card only),
`location.neighbourhoodInfo.name`, `attributes.all[]` as `canonicalName`/`canonicalValues`.

Apartments attributes (present on 45 of 45 cards unless noted): `unittype` (apartment, house, condo,
basement-apartment; townhouse and duplex-triplex exist in the labels), `numberbedrooms` ("0" is a studio,
"1.5" is one plus den), `numberbathrooms` (bathrooms times 10: "10", "15", "20"), `agreementtype` (only
one-year and month-to-month exist; no sublet or 8-month value), `furnished` (44 of 45), `heat`, `hydro`,
`water`, `internet`, `cabletv` (0/1 utilities-included flags), `laundryinunit`, `laundryinbuilding`,
`dateavailable` (ISO date, 17 of 45; on detail pages it sits in `values[0]` and `canonicalValues` is empty),
`petsallowed`, `numberparkingspots`, `areainfeet`, `smokingpermitted`, `forrentbyhousing` (reprofessional on
38 of 45, ownr on 7), and a set of 0/1 building and accessibility flags.

Rooms attributes: only `furnished` (32 of 41) and `petsallowed` (24 of 41); 9 of 41 cards have no attributes
at all. Bedrooms, bathrooms, unit type, lease term, move-in date and utilities for rooms exist only in the
title and description text, and the full description is only on the detail page.

Personal data seen: `posterInfo.phoneNumber` (masked) and the poster's `StandardProfileV2.name` exist on
detail pages; one of four detail descriptions contained phone- and email-like text. All three are dropped at
parse time per the privacy rule.

### Data-quality traps observed on 86 cards

- Categories cross-contaminate: rooms priced per room are posted under apartments (a purpose-built student
  building ad at $1,200 with `numberbedrooms` 2 where the text says the price is for one room), and whole
  basements or 2-bed units are posted under rooms. `unit_type` cannot come from the category alone.
- The KW index includes out-of-region listings (Listowel, Wellington North; latitudes up to 43.99). A
  bounding-box filter is needed.
- Attribute garbage exists: one card had `numberbedrooms` 2, `numberbathrooms` 60 and $5,700 for "6 students".
- `price.type` CONTACT (1 of 45, 2 of 41) has no amount; such listings are dropped from training.
- Sublets and 8-month leases are never structured; they appear only in text ("SUBLET", "January - April 2027").

### Terms of Use (fetched 2026-10-14 from the page the kijiji.ca footer links to, last modified April 8, 2026)

Under "Using the Services", users agree not to "use any robot, spider, scraper or other automated means to
access Kijiji and collect content for any purpose without our express written permission", not to "impose
an unreasonable load on our infrastructure", and not to "harvest or otherwise collect information about
others, including email addresses, without their consent". Decision on how to proceed: Caden's.

### Anti-bot observations

None. Server is Google Frontend; no Cloudflare, DataDome, PerimeterX or Akamai markers; all responses were
full server-rendered pages. The server echoes the User-Agent into the page JSON and sets a `machId` device
cookie on every response. Keep one realistic User-Agent and one worker.

### Raw files

`data/raw/kijiji/2026-10-14/`: `robots.txt.gz`, `index_apartments_p1.html.gz`, `index_rooms_p1.html.gz`,
four `detail_<adid>.html.gz` (ad ids 1743010220, 1744807256, 1744792340, 1744696300), `terms_of_use.html.gz`,
each with a `.headers.gz` beside it, and `request_log.txt`. Candidates for `tests/fixtures/`.

### Open points

- `/page-2/` path form unverified.
- Detail pages for professional landlords (84 percent of apartments cards) not fetched yet.
- Whether `machId` cookie persistence matters is untested.

## 2. rentals.ca

- `robots.txt` (200, served from Cloudflare cache): `User-agent: *`, `Allow: /`, no `Crawl-delay`. Disallows
  `*-feed.json`, `*-feed.xml`, `bbox=` map queries, filter facets (`rentrange=`, `baths=`, `amenities=`,
  `types=`, `categories=`), 3D tours, login redirects and tracking parameters. So the plain city page is
  allowed and any JSON feed is explicitly off limits.
- `https://rentals.ca/waterloo`: HTTP 403, Cloudflare managed challenge (`cf-mitigated: challenge`,
  "Just a moment..."). Stopped after this request, per the playbook.
- Terms not read (page unreachable). Read `https://rentals.ca/terms` in a browser before building anything.
- Listing counts, JSON availability and field coverage: not found.
- Raw: `data/raw/rentals_ca/2026-10-14/` (robots and the challenge page).

## 3. Zumper

- `https://www.zumper.com/robots.txt` returned HTTP 200 but an HTML "Client Challenge" interstitial that
  requires JavaScript (Fastly-fronted), not a robots file. Stopped after this request.
- Nothing else observed. Raw: `data/raw/zumper/2026-10-14/`.

## 4. Places4Students

- `https://www.places4students.com/robots.txt` returned HTTP 429 with a Vercel Security Checkpoint page
  ("We're verifying your browser"). Stopped after this request.
- Likely listing URLs from a search engine, unverified: `/schools/200/listings/properties` and
  `/schools/200/listings/sublets` for the University of Waterloo.
- Raw: `data/raw/p4s/2026-10-14/`.

## 5. apartments.com

Skipped per HANDOFF section 4 (Cloudflare, terms prohibit scraping). Not contacted.

## 6. Manual entry form

Not built yet. The plan from HANDOFF section 4: a form writing rows with `source = 'manual'` so team members
can enter Facebook-group listings by reading them as humans.

## 7. Wayback Machine

Pending: capture counts by month for both index URLs (HANDOFF section 10, task 8).

## 8. ION LRT stops

Pending: station coordinates from the GRT GTFS feed, for the `ion_distance_m` feature.
