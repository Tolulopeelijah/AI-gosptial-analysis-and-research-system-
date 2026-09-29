"""OpenStreetMap access through the Overpass API.

One shared core (`overpass_query`) plus named presets per data theme. All
presets build Overpass QL from validated parameters — no hand-written query
strings reach the model. Results are Points (nodes/centroids) unless geometry
is requested. Network-dependent; Overpass enforces fair-use timeouts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..common import CapabilityError, ToolError, cap_int, collection, parse_bbox

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def overpass_query(ql: str, timeout: int = 60):
    """Run raw Overpass QL (advanced use; presets are preferred)."""
    from ..common import http_get

    if not isinstance(ql, str) or len(ql.strip()) < 10:
        raise ToolError("provide a non-trivial Overpass QL query")
    if len(ql) > 8000:
        raise ToolError("query too long (8000 char cap)")
    resp = http_get(OVERPASS_URL, params={"data": ql}, timeout=timeout)
    try:
        return resp.json()
    except Exception as exc:
        raise CapabilityError(f"Overpass returned non-JSON: {exc}") from exc


def _elements_to_features(doc: Dict[str, Any], want_geometry: bool = False):
    feats = []
    for el in doc.get("elements", []):
        typ = el.get("type")
        tags = el.get("tags", {}) or {}
        if typ == "node":
            geom: Optional[Dict[str, Any]] = {"type": "Point",
                                              "coordinates": [el["lon"], el["lat"]]}
        elif want_geometry and typ == "way" and el.get("geometry"):
            pts = [[p["lon"], p["lat"]] for p in el["geometry"]]
            closed = len(pts) > 3 and pts[0] == pts[-1]
            geom = {"type": "Polygon" if closed else "LineString",
                    "coordinates": [pts] if closed else pts}
        elif typ == "way" and el.get("center"):
            geom = {"type": "Point",
                    "coordinates": [el["center"]["lon"], el["center"]["lat"]]}
        elif typ == "relation" and el.get("center"):
            geom = {"type": "Point",
                    "coordinates": [el["center"]["lon"], el["center"]["lat"]]}
        else:
            continue
        props = {"osm_type": typ, "osm_id": el.get("id"),
                 "name": tags.get("name"), **{f"tag:{k}": v for k, v in tags.items()
                                              if k != "name"}}
        feats.append({"type": "Feature", "properties": props, "geometry": geom})
    return feats


def _run_nwr(nwr_body: str, bbox: str, max_features: int, want_geometry: bool,
             theme: str, timeout: int = 60):
    w, s, e, n = parse_bbox(bbox)
    max_features = cap_int(max_features, 1, 2000, name="max_features")
    out = "geom" if want_geometry else "center"
    ql = (f"[out:json][timeout:{min(timeout, 120)}];"
          f"(nwr({s},{w},{n},{e}){nwr_body};);out {out} {max_features};")
    doc = overpass_query(ql, timeout=timeout + 30)
    feats = _elements_to_features(doc, want_geometry)[:max_features]
    return collection(feats, theme=theme, bbox=[w, s, e, n])


def query_osm_pois(bbox: str, category: str = "amenity", max_features: int = 200,
                   want_geometry: bool = False):
    """Points of interest: amenity|shop|tourism|leisure|healthcare|emergency."""
    if category not in ("amenity", "shop", "tourism", "leisure", "healthcare",
                        "emergency", "office", "craft"):
        raise ToolError(f"unknown POI category '{category}'")
    return _run_nwr(f'["{category}"]', bbox, max_features, want_geometry,
                    f"pois:{category}")


def query_osm_roads(bbox: str, road_class: str = "all", max_features: int = 500,
                    want_geometry: bool = True):
    """Roads: motorway|trunk|primary|secondary|tertiary|residential|all."""
    if road_class != "all" and not __import__("re").match(
            r"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street|track|path)$",
            road_class):
        raise ToolError(f"unknown road class '{road_class}'")
    filt = '["highway"]' if road_class == "all" else f'["highway"="{road_class}"]'
    return _run_nwr(filt, bbox, max_features, want_geometry, f"roads:{road_class}")


def query_osm_buildings(bbox: str, max_features: int = 500,
                        want_geometry: bool = True):
    """Buildings (ways/relations with a building tag)."""
    return _run_nwr('["building"]', bbox, max_features, want_geometry, "buildings")


def query_osm_landuse(bbox: str, landuse: str = "", max_features: int = 200,
                      want_geometry: bool = True):
    """Landuse polygons; optional value (residential, farmland, forest…)."""
    filt = '["landuse"]' if not landuse else f'["landuse"="{landuse}"]'
    if landuse and not __import__("re").match(r"^[a-z_]+$", landuse):
        raise ToolError("landuse value must be lowercase letters/underscores")
    return _run_nwr(filt, bbox, max_features, want_geometry,
                    f"landuse:{landuse or 'all'}")


def query_osm_water(bbox: str, max_features: int = 200, want_geometry: bool = True):
    """Water bodies and waterways (natural=water, waterway=*, leisure=swimming)."""
    return _run_nwr('["natural"="water"]', bbox, max_features, want_geometry,
                    "water")


OSM_SCHEMAS = {
    "overpass_query": ({"properties": {
        "ql": {"type": "string", "description": "Full Overpass QL (advanced)."},
        "timeout": {"type": "integer", "description": "Seconds (default 60)."}}},
        ["ql"]),
    "query_osm_pois": ({"properties": {
        "bbox": {"type": "string"}, "category": {"type": "string"},
        "max_features": {"type": "integer"},
        "want_geometry": {"type": "boolean"}}}, ["bbox"]),
    "query_osm_roads": ({"properties": {
        "bbox": {"type": "string"}, "road_class": {"type": "string"},
        "max_features": {"type": "integer"},
        "want_geometry": {"type": "boolean"}}}, ["bbox"]),
    "query_osm_buildings": ({"properties": {
        "bbox": {"type": "string"}, "max_features": {"type": "integer"},
        "want_geometry": {"type": "boolean"}}}, ["bbox"]),
    "query_osm_landuse": ({"properties": {
        "bbox": {"type": "string"}, "landuse": {"type": "string"},
        "max_features": {"type": "integer"},
        "want_geometry": {"type": "boolean"}}}, ["bbox"]),
    "query_osm_water": ({"properties": {
        "bbox": {"type": "string"}, "max_features": {"type": "integer"},
        "want_geometry": {"type": "boolean"}}}, ["bbox"]),
}
