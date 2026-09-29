"""Distance and proximity, always CRS-aware.

Distances compute in a local metric projection (never in degrees) and report
kilometres. `distance` pairs every A with every B; `within_distance` filters;
`distance_matrix` returns the full A×B table for analysis tools downstream.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import (collection, crs_of, metric_crs_for, reproject, table,
                      to_meters, to_wgs_feature, valid_shapes)


def _metric_pairs(input_a, input_b):
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    if not pairs_a or not pairs_b:
        raise ValueError("empty")
    src_a, src_b = crs_of(input_a), crs_of(input_b)
    metric = metric_crs_for([g for _, g in pairs_a] + [g for _, g in pairs_b])
    am = [reproject(g, src_a, metric) for _, g in pairs_a]
    bm = [reproject(g, src_b, metric) for _, g in pairs_b]
    return pairs_a, pairs_b, am, bm, metric


def distance(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """Pairwise A×B distances in kilometres (table)."""
    try:
        pairs_a, pairs_b, am, bm, metric = _metric_pairs(input_a, input_b)
    except ValueError:
        return table(["a_index", "b_index", "distance_km"], [],
                     row_count=0, note="empty input side")
    rows = [{"a_index": i, "b_index": j,
             "distance_km": round(gb.distance(ga) / 1000.0, 4)}
            for i, ga in enumerate(am) for j, gb in enumerate(bm)]
    return table(["a_index", "b_index", "distance_km"], rows,
                 transform=f"metric via {metric}")


def within_distance(input_a: Dict[str, Any], input_b: Dict[str, Any],
                    distance: float, unit: str = "meters"):
    """A features within `distance` of any B feature (metric)."""
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    if not pairs_a or not pairs_b:
        return collection([], note="empty input side")
    radius_m = to_meters(distance, unit)
    src_a, src_b = crs_of(input_a), crs_of(input_b)
    metric = metric_crs_for([g for _, g in pairs_a] + [g for _, g in pairs_b])
    from shapely.ops import unary_union

    b_union = unary_union([reproject(g, src_b, metric) for _, g in pairs_b])
    feats = []
    for feat, geom in pairs_a:
        gm = reproject(geom, src_a, metric)
        if gm.distance(b_union) <= radius_m:
            props = dict(feat.get("properties", {}) or {})
            props["_within_m"] = radius_m
            feats.append(to_wgs_feature(geom, props, src_a))
    return collection(feats, radius_m=radius_m)


def distance_matrix(input_a: Dict[str, Any], input_b: Dict[str, Any] | None = None):
    """Full A×B kilometre matrix (B defaults to A). Rows carry a_index,
    b_index, distance_km — same grain as `distance`, kept as the named matrix
    step planners expect."""
    return distance(input_a, input_b if input_b is not None else input_a)


PROXIMITY_SCHEMAS = {
    "distance": ({"properties": {
        "input_a": {"description": "Result reference."},
        "input_b": {"description": "Result reference."}}},
        ["input_a", "input_b"]),
    "within_distance": ({"properties": {
        "input_a": {"description": "Result reference filtered."},
        "input_b": {"description": "Result reference measured against."},
        "distance": {"type": "number"},
        "unit": {"type": "string",
                 "description": "'meters' (default), 'kilometers', 'feet', 'miles'."}}},
        ["input_a", "input_b", "distance"]),
    "distance_matrix": ({"properties": {
        "input_a": {"description": "Result reference (rows)."},
        "input_b": {"description": "Result reference (columns); defaults to A."}}},
        ["input_a"]),
}
