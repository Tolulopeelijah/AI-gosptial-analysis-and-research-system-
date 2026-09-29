"""Location resolution via Nominatim (OpenStreetMap geocoder).

No API key required. Nominatim's usage policy asks for identification and
light use — every request carries a contact User-Agent and single lookups
never batch. For bulk geocoding, self-host or use a commercial provider.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..common import ToolError, collection, http_get

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
HEADERS = {"User-Agent": "weis-geospatial-agent/1.0 (research use)"}


def _search(params: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    from ..common import cap_int

    limit = cap_int(limit, 1, 20, name="limit")
    params = {**params, "format": "jsonv2", "limit": limit,
              "addressdetails": 1, "polygon_geojson": 0}
    resp = http_get(NOMINATIM_URL + "/search", params=params, timeout=30,
                    headers=HEADERS)
    try:
        return resp.json()
    except Exception as exc:
        from ..common import CapabilityError

        raise CapabilityError(f"Nominatim returned non-JSON: {exc}") from exc


def _to_feature(hit: Dict[str, Any]) -> Dict[str, Any]:
    addr = hit.get("address", {}) or {}
    return {
        "type": "Feature",
        "properties": {
            "name": hit.get("display_name", "").split(",")[0],
            "display_name": hit.get("display_name"),
            "place_type": hit.get("type"),
            "place_class": hit.get("class"),
            "country": addr.get("country"),
            "state": addr.get("state"),
            "county": addr.get("county"),
            "city": addr.get("city") or addr.get("town") or addr.get("village"),
            "postcode": addr.get("postcode"),
            "osm_type": hit.get("osm_type"),
            "osm_id": hit.get("osm_id"),
        },
        "geometry": {"type": "Point",
                     "coordinates": [float(hit["lon"]), float(hit["lat"])]},
    }


def geocode(query: str, limit: int = 5):
    """Forward geocode a place/address to point features."""
    if not isinstance(query, str) or not query.strip():
        raise ToolError("provide a place or address to geocode")
    hits = _search({"q": query.strip()}, limit)
    return collection([_to_feature(h) for h in hits if h.get("lat")],
                      query=query, service="nominatim")


def reverse_geocode(lat: float, lon: float):
    """Nearest address/place for coordinates, with admin hierarchy."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ToolError("lat/lon must be numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ToolError("coordinates out of range")
    resp = http_get(NOMINATIM_URL + "/reverse",
                    params={"lat": lat, "lon": lon, "format": "jsonv2",
                            "addressdetails": 1},
                    timeout=30, headers=HEADERS)
    try:
        hit = resp.json()
    except Exception as exc:
        from ..common import CapabilityError

        raise CapabilityError(f"Nominatim returned non-JSON: {exc}") from exc
    if hit.get("error"):
        return collection([], note=f"no result: {hit['error']}")
    hit = {**hit, "lat": str(lat), "lon": str(lon)}
    return collection([_to_feature(hit)], service="nominatim")


def resolve_location(text: str):
    """Natural-language location → point feature(s). Accepts 'lat, lon'
    pairs directly, otherwise geocodes. Answers 'where is X' for the agent."""
    if not isinstance(text, str) or not text.strip():
        raise ToolError("provide a location to resolve")
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", text.strip())
    if m:
        first, second = float(m.group(1)), float(m.group(2))
        # Disambiguate lat,lon vs lon,lat by range.
        if abs(first) <= 90 >= abs(second) or abs(second) > 90:
            lat, lon = first, second
        else:
            lat, lon = second, first
        res = reverse_geocode(lat, lon)
        res["resolved_as"] = "coordinates"
        return res
    res = geocode(text.strip(), limit=3)
    res["resolved_as"] = "geocoded"
    return res


GEOCODING_SCHEMAS = {
    "geocode": ({"properties": {
        "query": {"type": "string", "description": "Place or address."},
        "limit": {"type": "integer", "description": "Max results (default 5)."}}},
        ["query"]),
    "reverse_geocode": ({"properties": {
        "lat": {"type": "number"}, "lon": {"type": "number"}}}, ["lat", "lon"]),
    "resolve_location": ({"properties": {
        "text": {"type": "string",
                 "description": "'lat, lon' pair or place name."}}}, ["text"]),
}
