"""Synthetic archived Kijiji index pages for the backfill tests, one builder per format."""

import json

from housing.parse.pii import encode_next_data

SRP = "searchResultsPageByUrl:/b-apartments-condos/kitchener-waterloo/c37l1700212"


def _page(state: dict) -> str:
    data = {"props": {"pageProps": {"__APOLLO_STATE__": state}}}
    return (
        "<html><head><title>Apartments</title></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{encode_next_data(data)}</script>'
        "</body></html>"
    )


def ad(
    ad_id,
    price=1000,
    *,
    top=False,
    posted="2024-06-01T12:00:00Z",
    beds="2",
    lat=43.47,
    description="Nice place",
):
    """One listing's fields, shared by both builders."""
    return {
        "id": str(ad_id),
        "price": price,
        "top": top,
        "posted": posted,
        "beds": beds,
        "lat": lat,
        "description": description,
    }


def v2_page(ads, total=1427):
    """The 2024 layout: ``results.organic``/``topAds``, ``ListingV2``, no coordinates."""
    state: dict = {}
    organic, top_ads = [], []
    for a in ads:
        key = f"ListingV2:{a['id']}"
        state[f"Profile:9{a['id']}"] = {"__typename": "Profile", "id": int(f"9{a['id']}")}
        state[key] = {
            "__typename": "ListingV2",
            "id": a["id"],
            "title": f"Apartment {a['id']}",
            "description": a["description"],
            "seoUrl": f"/v-apartments-condos/kitchener-waterloo/apartment/{a['id']}",
            "price": {"amount": a["price"] * 100, "type": "FIXED"},
            "activationDate": a["posted"],
            "sortingDate": a["posted"],
            "adSource": "TOP_AD" if a["top"] else "ORGANIC",
            "categoryId": 37,
            "imageUrls": ["x"],
            "location": {
                "address": "200 University Ave W, Waterloo, ON, N2L 3G1",
                "nearestIntersection": ["University Ave", "Phillip St"],
            },
            "posterInfo": {"__ref": f"Profile:9{a['id']}"},
            "attributes": [{"name": "numberbedrooms", "values": [a["beds"]]}],
        }
        (top_ads if a["top"] else organic).append({"__ref": key})
    state["ROOT_QUERY"] = {
        SRP: {
            "pagination": {"offset": 0, "limit": 40, "totalCount": total},
            "results": {"organic": organic, "topAds": top_ads},
        }
    }
    return _page(state)


def nextjs_page(ads, total=1612):
    """Today's layout, read by the live parser: ``mainListings``, with coordinates."""
    state: dict = {}
    main, top_ads = [], []
    for a in ads:
        key = f"RealEstateListing:{a['id']}"
        state[key] = {
            "__typename": "RealEstateListing",
            "id": a["id"],
            "title": f"Apartment {a['id']}",
            "description": a["description"],
            "url": f"https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/apt/{a['id']}",
            "price": {"amount": a["price"] * 100, "type": "FIXED"},
            "activationDate": a["posted"],
            "sortingDate": a["posted"],
            "adSource": "TOP_AD" if a["top"] else "ORGANIC",
            "categoryId": 37,
            "imageCount": 3,
            "location": {
                "address": "200 University Ave W, Waterloo, ON, N2L 3G1",
                "coordinates": {"latitude": a["lat"], "longitude": -80.54},
            },
            "posterInfo": {"posterId": f"9{a['id']}"},
            "attributes": {
                "all": [{"canonicalName": "numberbedrooms", "canonicalValues": [a["beds"]]}]
            },
        }
        (top_ads if a["top"] else main).append({"__ref": key})
    state["ROOT_QUERY"] = {
        SRP: {
            "pagination": {"offset": 0, "limit": 40, "totalCount": total},
            "results": {"mainListings({})": main, "topListings": top_ads},
        }
    }
    return _page(state)


def html_cards_page():
    """The 2025 server-rendered layout, with a contact email in a description."""
    return (
        '<html><body><section data-testid="listing-card" data-listingid="1">'
        '<p data-testid="listing-price">$1,500</p>'
        "<p>Email jane.doe@example.com for showings</p></section></body></html>"
    )


# --- ad pages ------------------------------------------------------------------------------

ROOM_TEXT = (
    "4-month winter sublet, January - April 2027. Room in a 5 bedroom house near UW, "
    "fully furnished, utilities included. Text 519-555-0199 or email alex.smith@example.com."
    "\n\nThanks!!\n\nAlex Smith"
)


def nextjs_ad_page(
    ad_id,
    price=800,
    *,
    description=ROOM_TEXT,
    show_pin=True,
    posted="2025-08-12T10:00:00Z",
    seller="Alex",
):
    """Today's ad page, read by the live ``parse_detail``; the poster's name is in it."""
    entity_key = f"StandardListing:{ad_id}"
    state = {
        "ROOT_QUERY": {
            f'listing({{"id":"{ad_id}","isExternalId":false,"trackView":true}})': {
                "__ref": entity_key
            }
        },
        entity_key: {
            "__typename": "StandardListing",
            "id": str(ad_id),
            "title": f"Room {ad_id} near UW",
            "description": description,
            "url": f"https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/room/{ad_id}",
            "price": {"amount": price * 100, "type": "FIXED"},
            "location": {
                "address": "200 Lester St, Waterloo, ON N2L 3W6",
                "coordinates": {"latitude": 43.47712, "longitude": -80.53451},
                "showPinOnMap": show_pin,
            },
            "activationDate": posted,
            "sortingDate": posted,
            "endDate": None,
            "status": "ACTIVE",
            "categoryId": 36,
            "imageUrls": ["a", "b"],
            "posterInfo": {"posterId": "4242", "phoneNumber": "5195550199"},
            "metrics": {"views": 120},
            "attributes": {"all": [{"canonicalName": "furnished", "canonicalValues": ["1"]}]},
        },
        "StandardProfileV2:4242": {"__typename": "StandardProfileV2", "name": seller},
    }
    return _page(state).replace("<body>", f"<body><span>Posted by {seller}</span>", 1)


def vip_legacy_page(
    ad_id, price=900, *, description=ROOM_TEXT, seller="Alex", sorting_ms=1733684312000
):
    """The 2024 to early-2025 ad page: a ``window.__data`` blob with the poster's name."""
    blob = {
        "viewItemPage": {
            "viewItemData": {
                "adId": ad_id,
                "title": f"Room {ad_id} &amp; more",
                "description": description.replace("\n", "<br>"),
                "price": {"amount": price * 100, "type": "FIXED"},
                "adLocation": {
                    "latitude": 43.47195,
                    "longitude": -80.52436,
                    "mapAddress": "167 King St. N, Waterloo, ON, N2J 2Y1",
                },
                "adPosted": False,
                "sortingDate": sorting_ms,
                "categoryId": "36",
                "seoUrl": "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/"
                f"room/{ad_id}?siteLocale=en_CA",
                "media": [{"type": "image"}, {"type": "image"}],
                "posterId": "67337130",
                "sellerName": seller,
                "userEmail": None,
                "adAttributes": {
                    "attributes": [
                        {"machineKey": "furnished", "machineValue": "1"},
                        {"machineKey": "petsallowed", "machineValue": "limited"},
                    ]
                },
            }
        }
    }
    return (
        '<html><head><script>window.__CWVL = "VIP";</script>'
        f"<script>window.__data = {json.dumps(blob)};</script></head>"
        f'<body><div>{seller}</div><div id="vip-body">{description}</div></body></html>'
    )


def removed_ad_page():
    """What an ad URL serves once the ad is gone: Kijiji redirects to a search page."""
    return nextjs_page([])
