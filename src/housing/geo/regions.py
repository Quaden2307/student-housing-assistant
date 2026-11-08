"""Bounding boxes for the markets we sweep (docs/pipeline.md section 4).

Each box is generous enough to hold the whole urban area and tight enough that a
listing whose pin falls outside it is in the wrong market (a Toronto ad posted
into a local category, a typo'd coordinate). The cleaning rules drop such rows
as ``out_of_region`` against the listing's own city; the walk-to-campus features
are only defined for Kitchener-Waterloo and use its box as the guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from housing.parse.kijiji import LOCATION


@dataclass(frozen=True)
class Region:
    """One market's bounding box, degrees WGS84."""

    lat_lo: float
    lat_hi: float
    lon_lo: float
    lon_hi: float

    def contains(self, lat: float | None, lon: float | None) -> bool:
        """True when both coordinates are present and inside the box."""
        if lat is None or lon is None:
            return False
        return self.lat_lo <= lat <= self.lat_hi and self.lon_lo <= lon <= self.lon_hi


REGIONS: dict[str, Region] = {
    "kitchener-waterloo": Region(43.36, 43.56, -80.65, -80.35),
    "guelph": Region(43.47, 43.62, -80.33, -80.15),
    "hamilton": Region(43.15, 43.35, -80.10, -79.60),
    "london": Region(42.90, 43.08, -81.40, -81.10),
}


def in_region(location: str | None, lat: float | None, lon: float | None) -> bool:
    """True when the point lies inside its market's box.

    Args:
        location: Location name as swept (``listing_attributes.location``);
            None or an unknown name falls back to Kitchener-Waterloo, the
            market every pre-expansion listing belongs to.
        lat: Latitude, or None.
        lon: Longitude, or None.
    """
    return REGIONS.get(location or LOCATION, REGIONS[LOCATION]).contains(lat, lon)
