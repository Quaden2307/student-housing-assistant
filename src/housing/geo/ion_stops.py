"""ION light rail stations, for the ``ion_distance_m`` feature.

Coordinates come from the Grand River Transit GTFS feed (route 301), platforms averaged
per station; provenance in ``docs/sources.md`` section 8. Station locations do not change
between schedule periods, so this is hardcoded as HANDOFF section 12 asks.
"""

from __future__ import annotations

from housing.geo.distances import haversine_m

ION_STOPS: tuple[tuple[str, float, float], ...] = (
    ("Conestoga", 43.498291, -80.529561),
    ("Northfield", 43.497205, -80.543206),
    ("Research & Technology", 43.481615, -80.545159),
    ("University of Waterloo", 43.473387, -80.541351),
    ("Laurier-Waterloo Park", 43.468874, -80.534423),
    ("Willis Way", 43.462158, -80.523373),
    ("Waterloo Public Square", 43.464151, -80.523003),
    ("Allen", 43.459847, -80.518370),
    ("Grand River Hospital", 43.457292, -80.512056),
    ("Central", 43.453180, -80.499114),
    ("Victoria Park", 43.450190, -80.493692),
    ("Kitchener City Hall", 43.451950, -80.490834),
    ("Frederick", 43.449639, -80.487361),
    ("Queen", 43.448613, -80.489361),
    ("Kitchener Market", 43.446315, -80.483622),
    ("Borden", 43.442412, -80.475368),
    ("Mill", 43.433656, -80.477940),
    ("Block Line", 43.422788, -80.463009),
    ("Fairway", 43.422333, -80.441830),
)


def nearest_ion_stop(lat: float, lon: float) -> tuple[str, float]:
    """Return the nearest station's name and its straight-line distance in metres."""
    name, distance = min(
        (
            (stop_name, haversine_m(lat, lon, stop_lat, stop_lon))
            for stop_name, stop_lat, stop_lon in ION_STOPS
        ),
        key=lambda pair: pair[1],
    )
    return name, distance
