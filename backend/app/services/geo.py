"""Where a village actually is.

The district heatmap (FR-08.1) used to derive every village's position by
hashing its name into a bounding box over Maharashtra. That produced a
stable dot per village, which is all the map needed to render -- but the
dots were in the wrong places, so two neighbouring villages could sit a
hundred kilometres apart and a supervisor who knows the district would
(correctly) stop trusting the screen.

This module keeps a small gazetteer for the places the pilot actually
covers, and is honest about the rest:

- A village in `_GAZETTEER` gets its real position.
- Anything else keeps the old deterministic placeholder, and
  `locate()` reports `approximate=True` so the dashboard can mark that
  dot as "position approximate" instead of quietly implying a survey
  coordinate.

The coordinates below are town / taluka centres in Pune district to
roughly 3 decimal places (~100m), which is the right precision for a dot
on a district-level map -- they are NOT surveyed village boundaries. A
real deployment replaces this file with the district's own GIS layer, or
with the GPS fix the mobile app can capture at registration; the
`approximate` flag is what lets that happen without changing the API.
"""
from __future__ import annotations

import hashlib

from app.services.identity import village_code

# Last-resort box: Maharashtra, roughly. Only reached for a village this
# gazetteer has never heard of *and* whose district is unknown too.
_FALLBACK_LAT_RANGE = (17.5, 21.5)
_FALLBACK_LNG_RANGE = (73.0, 76.5)

# Roughly 25km either way: near enough that an unmapped village lands in
# its own district and the map still frames the district, far enough
# apart that two of them don't sit on top of each other.
_DISTRICT_JITTER = 0.22

# Keyed by identity.village_code() -- upper-case, punctuation to hyphens --
# so "Wagholi", "wagholi" and " Wagholi " are one place, using the same key
# the rest of the app already groups villages by.
_GAZETTEER: dict[str, tuple[float, float]] = {
    "PUNE-RURAL": (18.520, 73.857),   # Pune, the district HQ the rural block reports to
    "WAGHOLI": (18.579, 73.982),
    "SHIRUR": (18.828, 74.376),
    "BARAMATI": (18.151, 74.577),
    "DAUND": (18.467, 74.583),
    "INDAPUR": (18.117, 75.017),
    "JUNNAR": (19.209, 73.875),
    "KHED": (18.872, 73.893),         # Rajgurunagar, the taluka seat
    "AMBEGAON": (19.045, 73.853),     # Ghodegaon, the taluka seat
    "PURANDAR": (18.347, 74.033),     # Saswad, the taluka seat
    "VELHE": (18.306, 73.628),
    "MULSHI": (18.483, 73.500),
}

# Where a district sits, for framing the map and for placing a village
# inside it that the gazetteer above doesn't know. Keyed by
# identity.district_code().
_DISTRICT_CENTRES: dict[str, tuple[float, float]] = {
    "PUNE": (18.62, 74.10),
}

# What the map opens on when it has nothing at all to frame.
DISTRICT_CENTRE = _DISTRICT_CENTRES["PUNE"]


def district_centre(district: str | None) -> tuple[float, float] | None:
    return _DISTRICT_CENTRES.get((district or "").upper())


def locate(village: str | None, district: str | None = None) -> tuple[float, float, bool]:
    """Return (lat, lng, approximate) for a village name.

    `approximate` is True when the position is a deterministic placeholder
    rather than a real coordinate, so the caller can label it as such.

    `district` (identity.district_code()) keeps an unmapped village inside
    the district it actually belongs to. Without it, placeholders were
    scattered across the whole state, so one unmapped village in a Pune
    caseload dragged the map's auto-framing out to cover Maharashtra --
    a district officer opening her dashboard saw a state map with her own
    district as a smudge in the middle.
    """
    key = village_code(village)
    if key and key in _GAZETTEER:
        lat, lng = _GAZETTEER[key]
        return lat, lng, False

    # Placeholder: stable per name, so the same village doesn't jump
    # between refreshes, and inside its own district where possible --
    # visible, and still honest about being unmapped.
    digest = hashlib.sha256((key or "unknown").encode()).hexdigest()
    frac_lat = int(digest[:8], 16) / 0xFFFFFFFF
    frac_lng = int(digest[8:16], 16) / 0xFFFFFFFF

    centre = district_centre(district)
    if centre is not None:
        lat = centre[0] + (frac_lat - 0.5) * 2 * _DISTRICT_JITTER
        lng = centre[1] + (frac_lng - 0.5) * 2 * _DISTRICT_JITTER
    else:
        lat = _FALLBACK_LAT_RANGE[0] + frac_lat * (_FALLBACK_LAT_RANGE[1] - _FALLBACK_LAT_RANGE[0])
        lng = _FALLBACK_LNG_RANGE[0] + frac_lng * (_FALLBACK_LNG_RANGE[1] - _FALLBACK_LNG_RANGE[0])
    return round(lat, 5), round(lng, 5), True
