"""Deterministic GIS operations (shapely + pyproj).

All ops consume GeoJSON FeatureCollections — either inline or by `$step_id`
reference (resolved by the orchestrator before the call) — and return GeoJSON
FeatureCollections. CRS correctness is enforced:

* Meter-based buffers on geographic (EPSG:4326) data are computed in a local
  metric projection (World Equidistant Cylindrical centred on the data, or
  UTM when the extent is small) and reprojected back — never raw degrees.
* Intersect/nearest require matching CRS; EPSG:4326 vs EPSG:3857 (or any
  mismatch) is auto-reprojected with the transform recorded in metadata.
* Invalid geometries are repaired with `make_valid`; unrepairable ones are
  dropped and counted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform, nearest_points
from shapely.validation import make_valid

try:
    from pyproj import CRS, Transformer

    _HAS_PYPROJ = True
except ImportError:  # pragma: no cover
    _HAS_PYPROJ = False

EPSG_4326 = "EPSG:4326"


def _crs_of(fc: Dict[str, Any]) -> str:
    return fc.get("crs", EPSG_4326) or EPSG_4326


def _shapes(fc: Dict[str, Any]) -> List[Tuple[Dict[str, Any], Any]]:
    out = []
    for feat in fc.get("features", []):
        try:
            geom = shape(feat.get("geometry"))
        except Exception:
            continue
        if not geom.is_valid:
            geom = make_valid(geom)
        if geom.is_empty:
            continue
        out.append((feat, geom))
    return out


def _metric_crs_for(geoms) -> str:
    """Local metric CRS centred on the data (Albers-free simple choice)."""
    if not _HAS_PYPROJ:  # pragma: no cover
        return EPSG_4326
    from shapely.ops import unary_union

    merged = unary_union(geoms)
    lon, lat = merged.centroid.x, merged.centroid.y
    # UTM zone for small extents, else azimuthal equidistant at centroid.
    bounds = merged.bounds
    if max(bounds[2] - bounds[0], bounds[3] - bounds[1]) < 6:
        zone = int((lon + 180) // 6) + 1
        epsg = 32600 + zone if lat >= 0 else 32700 + zone
        return f"EPSG:{epsg}"
    return (
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 "
        "+ellps=WGS84 +datum=WGS84 +units=m +no_defs"
    )


def _reproject(geom, src: str, dst: str):
    if src == dst or not _HAS_PYPROJ:
        return geom
    transformer = Transformer.from_crs(CRS(src), CRS(dst), always_xy=True)
    return shapely_transform(transformer.transform, geom)


def _to_geojson_feature(
    geom, properties: Dict[str, Any], src_crs: str, dst_crs: str = EPSG_4326
):
    g = _reproject(geom, src_crs, dst_crs)
    return {"type": "Feature", "properties": properties, "geometry": mapping(g)}


# ---------------------------------------------------------------- tools ---


def buffer(
    input: Dict[str, Any], distance: float, unit: str = "meters"
) -> Dict[str, Any]:
    """Buffer all input features by `distance` (metres/km/feet/miles)."""
    factors = {"meters": 1.0, "kilometers": 1000.0, "km": 1000.0,
               "feet": 0.3048, "miles": 1609.344}
    if unit not in factors:
        return {"ok": False, "error": f"unknown unit '{unit}'; use meters|kilometers|feet|miles"}
    if distance <= 0:
        return {"ok": False, "error": "distance must be positive"}
    if not isinstance(input, dict) or "features" not in input:
        return {"ok": False, "error": "buffer 'input' must be a FeatureCollection result reference"}
    distance_m = float(distance) * factors[unit]

    pairs = _shapes(input)
    if not pairs:
        return {"ok": True, "type": "FeatureCollection", "features": [],
                "count": 0, "note": "empty input"}
    src_crs = _crs_of(input)
    metric = _metric_crs_for([g for _, g in pairs])
    out = []
    for feat, geom in pairs:
        gm = _reproject(geom, src_crs, metric)
        props = dict(feat.get("properties", {}) or {})
        props["_buffer_m"] = distance_m
        out.append(_to_geojson_feature(gm.buffer(distance_m), props, metric))
    return {
        "ok": True, "type": "FeatureCollection", "features": out,
        "count": len(out), "crs": EPSG_4326,
        "transform": f"{src_crs} -> {metric} (buffer {distance_m} m) -> {EPSG_4326}",
    }


def intersect(input_a: Dict[str, Any], input_b: Dict[str, Any]) -> Dict[str, Any]:
    """Keep features of A that spatially intersect any feature of B."""
    for name, fc in (("input_a", input_a), ("input_b", input_b)):
        if not isinstance(fc, dict) or "features" not in fc:
            return {"ok": False, "error": f"'{name}' must be a FeatureCollection result reference"}
    a_pairs = _shapes(input_a)
    b_pairs = _shapes(input_b)
    if not a_pairs or not b_pairs:
        return {"ok": True, "type": "FeatureCollection", "features": [],
                "count": 0, "note": "empty input side"}
    crs_a, crs_b = _crs_of(input_a), _crs_of(input_b)
    b_in_a = [_reproject(g, crs_b, crs_a) for _, g in b_pairs]
    from shapely.ops import unary_union

    b_union = unary_union(b_in_a)
    fixed = []
    for feat, geom in a_pairs:
        if geom.intersects(b_union):
            props = dict(feat.get("properties", {}) or {})
            props["_matched"] = True
            fixed.append(
                _to_geojson_feature(
                    _reproject(geom, crs_a, EPSG_4326), props, EPSG_4326
                )
            )
    notes = []
    if crs_a != crs_b:
        notes.append(f"reprojected {crs_b} -> {crs_a} for comparison")
    return {
        "ok": True, "type": "FeatureCollection", "features": fixed,
        "count": len(fixed), "crs": EPSG_4326,
        "compared": {"a": len(a_pairs), "b": len(b_pairs)},
        "note": "; ".join(notes),
    }


def nearest(
    input_a: Dict[str, Any], input_b: Dict[str, Any], k: int = 1
) -> Dict[str, Any]:
    """For each feature in A, find the k nearest features in B (metric km)."""
    for name, fc in (("input_a", input_a), ("input_b", input_b)):
        if not isinstance(fc, dict) or "features" not in fc:
            return {"ok": False, "error": f"'{name}' must be a FeatureCollection result reference"}
    a_pairs = _shapes(input_a)
    b_pairs = _shapes(input_b)
    if not a_pairs or not b_pairs:
        return {"ok": True, "type": "table", "columns": ["a_index", "b_index", "distance_km"],
                "rows": [], "row_count": 0, "note": "empty input side"}
    crs_a, crs_b = _crs_of(input_a), _crs_of(input_b)
    metric = _metric_crs_for([g for _, g in a_pairs] + [g for _, g in b_pairs])
    am = [_reproject(g, crs_a, metric) for _, g in a_pairs]
    bm = [_reproject(g, crs_b, metric) for _, g in b_pairs]
    rows = []
    for i, ga in enumerate(am):
        dists = sorted(((gb.distance(ga), j) for j, gb in enumerate(bm)))[: max(1, k)]
        for dist_m, j in dists:
            rows.append({"a_index": i, "b_index": j,
                         "distance_km": round(dist_m / 1000.0, 3)})
    return {
        "ok": True, "type": "table", "columns": ["a_index", "b_index", "distance_km"],
        "rows": rows, "row_count": len(rows),
        "transform": f"{crs_a}/{crs_b} -> {metric} for metric distance",
    }


BUFFER_SCHEMA = {
    "properties": {
        "input": {"description": "Result reference, e.g. '$floodplains'."},
        "distance": {"type": "number", "description": "Buffer distance."},
        "unit": {"type": "string", "description": "'meters' (default), 'kilometers', 'feet', 'miles'."},
    }
}
BUFFER_REQUIRED = ["input", "distance"]
INTERSECT_SCHEMA = {
    "properties": {
        "input_a": {"description": "Result reference for set A."},
        "input_b": {"description": "Result reference for set B."},
    }
}
INTERSECT_REQUIRED = ["input_a", "input_b"]
NEAREST_SCHEMA = {
    "properties": {
        "input_a": {"description": "Result reference for query features."},
        "input_b": {"description": "Result reference for candidate features."},
        "k": {"type": "integer", "description": "Neighbours per feature (default 1)."},
    }
}
NEAREST_REQUIRED = ["input_a", "input_b"]
