"""First-class CRS operations.

Every geographic payload in this system carries an optional `crs` member
(default EPSG:4326). These tools inspect, assign (when missing/known-wrong),
and transform it. `transform_crs` handles whole FeatureCollections;
`transform_coordinates` handles raw position arrays.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, collection, features_of, table, valid_shapes

COMMON_CRS = {
    "EPSG:4326": "WGS 84 (lon/lat degrees)",
    "EPSG:3857": "Web Mercator (metres)",
    "EPSG:4269": "NAD83 (lon/lat degrees)",
    "EPSG:26916": "NAD83 / UTM zone 16N (metres; covers Ohio)",
    "EPSG:26917": "NAD83 / UTM zone 17N (metres; covers eastern Ohio)",
    "EPSG:32617": "WGS 84 / UTM zone 17N (metres)",
    "EPSG:3734": "NAD83 / Ohio North (ftUS)",
    "EPSG:3735": "NAD83 / Ohio South (ftUS)",
}


def get_crs(input: Dict[str, Any]):
    """Report the CRS declared on a result (EPSG:4326 when absent)."""
    from ..common import crs_of

    crs = crs_of(input)
    try:
        from pyproj import CRS

        info = CRS(crs)
        return {"ok": True, "crs": crs, "name": info.name,
                "is_geographic": info.is_geographic,
                "is_projected": info.is_projected,
                "axis_units": str(info.axis_info[0].unit_name) if info.axis_info else ""}
    except Exception as exc:
        raise ToolError(f"unrecognised CRS '{crs}': {exc}") from exc


def set_crs(input: Dict[str, Any], crs: str):
    """Assign (not transform) a CRS label — for payloads known to be in a CRS
    but missing the member. Coordinates are untouched."""
    from pyproj import CRS

    try:
        CRS(crs)
    except Exception as exc:
        raise ToolError(f"invalid CRS '{crs}': {exc}") from exc
    feats = features_of(input)
    out = collection([dict(f) for f in feats])
    out["crs"] = crs
    out["crs_assigned"] = True
    return out


def transform_crs(input: Dict[str, Any], target_crs: str):
    """Reproject every feature of a collection into `target_crs`."""
    from shapely.geometry import mapping

    from ..common import crs_of, reproject

    pairs = valid_shapes(input)
    try:
        from pyproj import CRS

        CRS(target_crs)
    except Exception as exc:
        raise ToolError(f"invalid target CRS '{target_crs}': {exc}") from exc
    src = crs_of(input)
    feats = []
    for feat, geom in pairs:
        projected = reproject(geom, src, target_crs)
        feats.append({"type": "Feature",
                      "properties": dict(feat.get("properties", {}) or {}),
                      "geometry": mapping(projected)})
    out = collection(feats, source_crs=src)
    out["crs"] = target_crs
    return out


def get_utm_zone(lon: float, lat: float):
    """UTM zone number + EPSG code for a longitude/latitude."""
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        raise ToolError("lon/lat must be numbers")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ToolError("coordinates out of range")
    zone = int((lon + 180) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    hemisphere = "N" if lat >= 0 else "S"
    return {"ok": True, "zone": zone, "hemisphere": hemisphere,
            "epsg": f"EPSG:{epsg}"}


def transform_coordinates(coordinates: List[List[float]], source_crs: str,
                          target_crs: str):
    """Reproject raw [x, y] positions (table of source → target)."""
    from pyproj import CRS, Transformer

    for name, value in (("source_crs", source_crs), ("target_crs", target_crs)):
        try:
            CRS(value)
        except Exception as exc:
            raise ToolError(f"invalid {name} '{value}': {exc}") from exc
    if not isinstance(coordinates, list) or not coordinates:
        raise ToolError("'coordinates' must be a non-empty array of [x, y]")
    transformer = Transformer.from_crs(CRS(source_crs), CRS(target_crs),
                                       always_xy=True)
    rows = []
    for i, pos in enumerate(coordinates):
        if (not isinstance(pos, (list, tuple)) or len(pos) < 2):
            raise ToolError(f"position {i} must be [x, y]")
        x, y = transformer.transform(float(pos[0]), float(pos[1]))
        rows.append({"index": i, "x": pos[0], "y": pos[1],
                     "x_out": round(x, 4), "y_out": round(y, 4)})
    return table(["index", "x", "y", "x_out", "y_out"], rows,
                 source_crs=source_crs, target_crs=target_crs)


CRS_SCHEMAS = {
    "get_crs": ({"properties": {
        "input": {"description": "Result reference or collection."}}}, ["input"]),
    "set_crs": ({"properties": {
        "input": {"description": "Result reference or collection."},
        "crs": {"type": "string", "description": "CRS to assign, e.g. 'EPSG:4326'."}}},
        ["input", "crs"]),
    "transform_crs": ({"properties": {
        "input": {"description": "Result reference or collection."},
        "target_crs": {"type": "string", "description": "e.g. 'EPSG:3857'."}}},
        ["input", "target_crs"]),
    "get_utm_zone": ({"properties": {
        "lon": {"type": "number"}, "lat": {"type": "number"}}}, ["lon", "lat"]),
    "transform_coordinates": ({"properties": {
        "coordinates": {"description": "Array of [x, y] positions."},
        "source_crs": {"type": "string"},
        "target_crs": {"type": "string"}}},
        ["coordinates", "source_crs", "target_crs"]),
}
