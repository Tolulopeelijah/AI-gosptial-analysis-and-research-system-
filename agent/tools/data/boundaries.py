"""Administrative boundaries for natural-language geography.

Boundaries come from OpenStreetMap relations via Nominatim's polygon output
(no key, same usage policy as geocoding). `get_admin_boundary` returns the
boundary polygon for a named place; `find_containing_region` answers "what
admin area contains this point"; `get_admin_hierarchy` lists the enclosing
levels for a place name.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, collection, http_get, table
from .geocoding import HEADERS, NOMINATIM_URL


def get_admin_boundary(place: str, admin_level: str = ""):
    """Boundary polygon(s) for a named country/state/county/district.

    `admin_level` optionally prefers a result whose class/type contains the
    given text (e.g. 'county', 'administrative'); otherwise the first polygon
    result wins and the choice is reported.
    """
    if not isinstance(place, str) or not place.strip():
        raise ToolError("provide a place name")
    resp = http_get(NOMINATIM_URL + "/search",
                    params={"q": place.strip(), "format": "jsonv2", "limit": 10,
                            "addressdetails": 1, "polygon_geojson": 1,
                            "extratags": 1},
                    timeout=30, headers=HEADERS)
    try:
        hits = resp.json()
    except Exception as exc:
        from ..common import CapabilityError

        raise CapabilityError(f"Nominatim returned non-JSON: {exc}") from exc
    polys = [h for h in hits if h.get("geojson")]
    if not polys:
        return collection([], note=f"no boundary polygon found for '{place}'")
    chosen = polys[0]
    if admin_level:
        want = admin_level.lower()
        for h in polys:
            if want in str(h.get("type", "")).lower() or \
               want in str(h.get("class", "")).lower():
                chosen = h
                break
    geom = chosen["geojson"]
    if geom.get("type") not in ("Polygon", "MultiPolygon"):
        return collection([], note="boundary geometry is not polygonal")
    feat = {"type": "Feature",
            "properties": {"name": chosen.get("display_name", "").split(",")[0],
                           "display_name": chosen.get("display_name"),
                           "place_type": chosen.get("type"),
                           "osm_id": chosen.get("osm_id")},
            "geometry": geom}
    return collection([feat], place=place, candidates=len(polys))


def find_containing_region(lat: float, lon: float):
    """Point feature for the place plus its admin hierarchy as properties."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ToolError("lat/lon must be numbers")
    resp = http_get(NOMINATIM_URL + "/reverse",
                    params={"lat": lat, "lon": lon, "format": "jsonv2",
                            "addressdetails": 1, "zoom": 10},
                    timeout=30, headers=HEADERS)
    try:
        hit = resp.json()
    except Exception as exc:
        from ..common import CapabilityError

        raise CapabilityError(f"Nominatim returned non-JSON: {exc}") from exc
    addr = hit.get("address", {}) or {}
    props = {
        "display_name": hit.get("display_name"),
        "country": addr.get("country"),
        "country_code": addr.get("country_code"),
        "state": addr.get("state"),
        "county": addr.get("county"),
        "city": addr.get("city") or addr.get("town") or addr.get("village"),
    }
    return collection([{"type": "Feature", "properties": props,
                        "geometry": {"type": "Point",
                                     "coordinates": [lon, lat]}}])


def get_admin_hierarchy(place: str):
    """Enclosing admin levels (country → state → county → city) as a table."""
    if not isinstance(place, str) or not place.strip():
        raise ToolError("provide a place name")
    resp = http_get(NOMINATIM_URL + "/search",
                    params={"q": place.strip(), "format": "jsonv2", "limit": 1,
                            "addressdetails": 1},
                    timeout=30, headers=HEADERS)
    try:
        hits = resp.json()
    except Exception as exc:
        from ..common import CapabilityError

        raise CapabilityError(f"Nominatim returned non-JSON: {exc}") from exc
    if not hits:
        return table(["level", "name"], [], row_count=0,
                     note=f"no result for '{place}'")
    addr = hits[0].get("address", {}) or {}
    order = ["country", "state", "county", "city", "town", "village",
             "suburb", "postcode"]
    rows = [{"level": lvl, "name": addr[lvl]} for lvl in order if addr.get(lvl)]
    return table(["level", "name"], rows,
                 display_name=hits[0].get("display_name"))


BOUNDARIES_SCHEMAS = {
    "get_admin_boundary": ({"properties": {
        "place": {"type": "string", "description": "e.g. 'Lucas County, Ohio'."},
        "admin_level": {"type": "string",
                        "description": "Optional preference, e.g. 'county'."}}},
        ["place"]),
    "find_containing_region": ({"properties": {
        "lat": {"type": "number"}, "lon": {"type": "number"}}}, ["lat", "lon"]),
    "get_admin_hierarchy": ({"properties": {
        "place": {"type": "string"}}}, ["place"]),
}
