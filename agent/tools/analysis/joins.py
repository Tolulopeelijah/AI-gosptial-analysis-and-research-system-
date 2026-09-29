"""Spatial joins: combine attributes across layers by location.

`spatial_join` is the general engine (named DE-9IM predicate);
`join_by_nearest` attaches the closest B feature per A feature with distance;
`aggregate_join` rolls B-side values up per A polygon (count/sum/mean/min/max);
`transfer_attributes` copies named fields across an existing spatial match
(e.g. after an intersect step) by nearest centroid.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, collection, crs_of, to_wgs_feature, valid_shapes
from ..geometry.relationships import PREDICATES


def spatial_join(input_a: Dict[str, Any], input_b: Dict[str, Any],
                 predicate: str = "intersects", suffix: str = "_b"):
    """Attach each intersecting B feature's attributes to A (one output row
    per A×B match; an unmatched A passes through with null B fields)."""
    if predicate not in PREDICATES:
        raise ToolError(f"unknown predicate '{predicate}'")
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    from shapely.ops import unary_union

    src_a = crs_of(input_a)
    b_geoms = [g for _, g in pairs_b]
    feats = []
    for feat_a, geom_a in pairs_a:
        matched = [i for i, gb in enumerate(b_geoms)
                   if bool(getattr(geom_a, predicate)(gb))] if b_geoms else []
        base = dict(feat_a.get("properties", {}) or {})
        if not matched:
            feats.append(to_wgs_feature(geom_a, base, src_a))
            continue
        for j in matched:
            props = dict(base)
            for k, v in (pairs_b[j][0].get("properties", {}) or {}).items():
                props[f"{k}{suffix}" if k in props else k] = v
            props["_join_b_index"] = j
            feats.append(to_wgs_feature(geom_a, props, src_a))
    return collection(feats, predicate=predicate, matches=len(feats))


def join_by_nearest(input_a: Dict[str, Any], input_b: Dict[str, Any],
                    k: int = 1, suffix: str = "_nearest"):
    """Attach the k nearest B features' attributes + metric distance in km."""
    from ..common import cap_int, metric_crs_for, reproject

    k = cap_int(k, 1, 25, name="k")
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    if not pairs_a or not pairs_b:
        return collection([], note="empty input side")
    src_a, src_b = crs_of(input_a), crs_of(input_b)
    metric = metric_crs_for([g for _, g in pairs_a] + [g for _, g in pairs_b])
    am = [reproject(g, src_a, metric) for _, g in pairs_a]
    bm = [reproject(g, src_b, metric) for _, g in pairs_b]
    feats = []
    for i, (feat_a, geom_a) in enumerate(pairs_a):
        ranked = sorted(((bm[j].distance(am[i]), j) for j in range(len(bm))))[:k]
        for dist_m, j in ranked:
            props = dict(feat_a.get("properties", {}) or {})
            for fkey, v in (pairs_b[j][0].get("properties", {}) or {}).items():
                props[f"{fkey}{suffix}" if fkey in props else fkey] = v
            props["_nearest_b_index"] = j
            props["_distance_km"] = round(dist_m / 1000.0, 4)
            feats.append(to_wgs_feature(geom_a, props, src_a))
    return collection(feats, k=k)


def aggregate_join(input_a: Dict[str, Any], input_b: Dict[str, Any],
                   operation: str = "count", field: str | None = None,
                   predicate: str = "intersects"):
    """One output per A feature with a rolled-up B value: count of matching B
    features, or sum/mean/min/max of a numeric B field."""
    if operation not in ("count", "sum", "mean", "min", "max"):
        raise ToolError("operation must be count|sum|mean|min|max")
    if predicate not in PREDICATES:
        raise ToolError(f"unknown predicate '{predicate}'")
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    src_a = crs_of(input_a)
    feats = []
    for feat_a, geom_a in pairs_a:
        matched = [pairs_b[j][0] for j in range(len(pairs_b))
                   if bool(getattr(geom_a, predicate)(pairs_b[j][1]))]
        props = dict(feat_a.get("properties", {}) or {})
        if operation == "count":
            props["_agg_count"] = len(matched)
        else:
            if not field:
                raise ToolError(f"operation '{operation}' needs 'field'")
            vals = [m.get("properties", {}).get(field) for m in matched]
            vals = [v for v in vals if isinstance(v, (int, float))]
            if not vals:
                props[f"_agg_{operation}"] = None
            elif operation == "sum":
                props["_agg_sum"] = float(sum(vals))
            elif operation == "mean":
                props["_agg_mean"] = float(sum(vals) / len(vals))
            elif operation == "min":
                props["_agg_min"] = float(min(vals))
            else:
                props["_agg_max"] = float(max(vals))
        props["_agg_n"] = len(matched)
        feats.append(to_wgs_feature(geom_a, props, src_a))
    return collection(feats, operation=operation, field=field)


def transfer_attributes(target: Dict[str, Any], source: Dict[str, Any],
                        fields: List[str]):
    """Copy named fields from each source feature to the target feature with
    the nearest centroid (for pairing attributes after a geometric step)."""
    if not isinstance(fields, list) or not fields:
        raise ToolError("'fields' must be a non-empty array of field names")
    pairs_t = valid_shapes(target, "target")
    pairs_s = valid_shapes(source, "source")
    if not pairs_t or not pairs_s:
        return collection([], note="empty input side")
    src = crs_of(target)
    s_centroids = [g.centroid for _, g in pairs_s]
    feats = []
    for feat_t, geom_t in pairs_t:
        c = geom_t.centroid
        best = min(range(len(s_centroids)),
                   key=lambda j: s_centroids[j].distance(c))
        props = dict(feat_t.get("properties", {}) or {})
        sprops = pairs_s[best][0].get("properties", {}) or {}
        for f in fields:
            props[f] = sprops.get(f)
        feats.append(to_wgs_feature(geom_t, props, src))
    return collection(feats, fields=fields)


JOIN_SCHEMAS = {
    "spatial_join": ({"properties": {
        "input_a": {"description": "Result reference (rows kept)."},
        "input_b": {"description": "Result reference (attributes attached)."},
        "predicate": {"type": "string", "description": "Default 'intersects'."},
        "suffix": {"type": "string", "description": "Rename clashes (default '_b')."}}},
        ["input_a", "input_b"]),
    "join_by_nearest": ({"properties": {
        "input_a": {"description": "Result reference."},
        "input_b": {"description": "Result reference."},
        "k": {"type": "integer", "description": "Neighbours per feature (default 1)."},
        "suffix": {"type": "string", "description": "Default '_nearest'."}}},
        ["input_a", "input_b"]),
    "aggregate_join": ({"properties": {
        "input_a": {"description": "Result reference (one output each)."},
        "input_b": {"description": "Result reference (rolled up)."},
        "operation": {"type": "string", "description": "count|sum|mean|min|max."},
        "field": {"type": "string", "description": "Numeric B field (non-count ops)."},
        "predicate": {"type": "string", "description": "Default 'intersects'."}}},
        ["input_a", "input_b"]),
    "transfer_attributes": ({"properties": {
        "target": {"description": "Result reference receiving fields."},
        "source": {"description": "Result reference providing fields."},
        "fields": {"description": "Array of field names to copy."}}},
        ["target", "source", "fields"]),
}
