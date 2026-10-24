"""Synthetic archived Kijiji index pages for the backfill tests, one builder per format."""

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
