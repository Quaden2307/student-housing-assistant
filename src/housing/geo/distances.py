"""Straight-line distances to the campuses (HANDOFF section 3, derived fields)."""

from __future__ import annotations

import math

UW = (43.4723, -80.5449)
"""University of Waterloo, HANDOFF section 12."""

LAURIER = (43.4738, -80.5275)
"""Wilfrid Laurier University, HANDOFF section 12."""

EARTH_RADIUS_M = 6_371_000.0

WALK_M_PER_MIN = 80.0
"""About 4.8 km/h; v1 converts straight-line distance to minutes at this pace."""


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def walk_minutes(distance_m: float) -> float:
    """Convert a straight-line distance to walking minutes (v1: no routing)."""
    return distance_m / WALK_M_PER_MIN


def walk_uw_min(lat: float, lon: float) -> float:
    """Walking minutes from a point to UW, straight line."""
    return walk_minutes(haversine_m(lat, lon, *UW))


def walk_laurier_min(lat: float, lon: float) -> float:
    """Walking minutes from a point to Laurier, straight line."""
    return walk_minutes(haversine_m(lat, lon, *LAURIER))
