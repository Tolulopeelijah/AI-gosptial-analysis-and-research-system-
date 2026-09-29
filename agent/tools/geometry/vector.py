"""Deterministic vector overlay and generalisation operations.

All tools consume FeatureCollections (inline or `$step_id`) and return
FeatureCollections in EPSG:4326. Set operations union the B side first, so
results stay correct for multi-feature inputs. Simplification is metric
(reprojected), never in degrees.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..common import (collection, crs_of, metric_crs_for, reproject, to_meters,
                      to_wgs_feature, valid_shapes)


def _union_of(pairs, src: str):
    from shapely.ops import unary_union

    return unary_union([reproject(g, src, src) for _, g in pairs])


def union(input: Dict[str, Any]):
    """Dissolve all input features into non-overlapping output geometries."""
    from shapely.ops import unary_union

    pairs = valid_shapes(input)
    if not pairs:
        return collection([], note="empty input")
    merged = unary_union([g for _, g in pairs])
    geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    src = crs_of(input)
    feats = [to_wgs_feature(g, {"part": i, "from_features": len(pairs)}, src)
             for i, g in enumerate(geoms)]
    return collection(feats, inputs=len(pairs))


def _binary_op(input_a, input_b, op: str):
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    if not pairs_a:
        return collection([], note="empty input_a")
    from shapely.ops import unary_union

    src_a = crs_of(input_a)
    b_union = unary_union([g for _, g in pairs_b]) if pairs_b else None
    feats = []
    for feat, geom in pairs_a:
        if b_union is None or b_union.is_empty:
            result = geom if op in ("difference", "symmetric_difference") else None
        elif op == "difference":
            result = geom.difference(b_union)
        elif op == "symmetric_difference":
            result = geom.symmetric_difference(b_union)
        else:
            result = geom.intersection(b_union)
        if result is None or result.is_empty:
            continue
        props = dict(feat.get("properties", {}) or {})
        feats.append(to_wgs_feature(result, props, src_a))
    return collection(feats, compared={"a": len(pairs_a), "b": len(pairs_b)})


def difference(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """Parts of A not covered by B (per A feature)."""
    return _binary_op(input_a, input_b, "difference")


def symmetric_difference(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """Areas covered by exactly one of A / B (per A feature)."""
    return _binary_op(input_a, input_b, "symmetric_difference")


def clip(input: Dict[str, Any], clip_area: Dict[str, Any]):
    """Parts of input inside the clip_area (per input feature)."""
    pairs = valid_shapes(input)
    areas = valid_shapes(clip_area, "clip_area")
    if not pairs:
        return collection([], note="empty input")
    if not areas:
        return collection([], note="empty clip area")
    from shapely.ops import unary_union

    src = crs_of(input)
    mask = unary_union([g for _, g in areas])
    feats = []
    for feat, geom in pairs:
        cut = geom.intersection(mask)
        if cut.is_empty:
            continue
        feats.append(to_wgs_feature(
            cut, dict(feat.get("properties", {}) or {}), src))
    return collection(feats, compared={"input": len(pairs), "clip": len(areas)})


def dissolve(input: Dict[str, Any], by_attribute: Optional[str] = None):
    """Merge features: all into one, or one per distinct attribute value."""
    from shapely.ops import unary_union

    pairs = valid_shapes(input)
    if not pairs:
        return collection([], note="empty input")
    src = crs_of(input)
    groups: Dict[str, List] = {}
    for feat, geom in pairs:
        key = str((feat.get("properties", {}) or {}).get(by_attribute)) \
            if by_attribute else "__all__"
        groups.setdefault(key, []).append(geom)
    feats = []
    for key, geoms in groups.items():
        merged = unary_union(geoms)
        parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        for i, part in enumerate(parts):
            props = {"dissolved_count": len(geoms)}
            if by_attribute:
                props[by_attribute] = None if key == "None" else key
            props["part"] = i
            feats.append(to_wgs_feature(part, props, src))
    return collection(feats, groups=len(groups), inputs=len(pairs))


def convex_hull(input: Dict[str, Any]):
    """Smallest convex polygon containing each feature."""
    pairs = valid_shapes(input)
    src = crs_of(input)
    feats = [to_wgs_feature(geom.convex_hull,
                            dict(feat.get("properties", {}) or {}), src)
             for feat, geom in pairs]
    return collection(feats)


def simplify(input: Dict[str, Any], tolerance_meters: float = 10.0):
    """Metric simplification (Douglas-Peucker) reporting vertex reduction."""
    pairs = valid_shapes(input)
    if not pairs:
        return collection([], note="empty input")
    tol = to_meters(tolerance_meters, "meters")
    src = crs_of(input)
    metric = metric_crs_for([g for _, g in pairs])
    feats, before, after = [], 0, 0
    for feat, geom in pairs:
        gm = reproject(geom, src, metric)
        before += sum(len(getattr(p, "exterior", p).coords)
                      for p in ([gm] if gm.geom_type != "MultiPolygon"
                                else list(gm.geoms)))
        simple = gm.simplify(tol, preserve_topology=True)
        after += sum(len(getattr(p, "exterior", p).coords)
                     for p in ([simple] if simple.geom_type != "MultiPolygon"
                               else list(simple.geoms)))
        feats.append(to_wgs_feature(simple,
                                    dict(feat.get("properties", {}) or {}), metric))
    # Geometries are in the metric CRS here; to_wgs_feature reprojects back.
    return collection(feats, vertices_before=before, vertices_after=after,
                      tolerance_m=tolerance_meters)


VECTOR_SCHEMAS = {
    "union": ({"properties": {
        "input": {"description": "Result reference to a FeatureCollection."}}}, ["input"]),
    "difference": ({"properties": {
        "input_a": {"description": "Result reference kept where B is absent."},
        "input_b": {"description": "Result reference subtracted."}}},
        ["input_a", "input_b"]),
    "symmetric_difference": ({"properties": {
        "input_a": {"description": "Result reference, set A."},
        "input_b": {"description": "Result reference, set B."}}},
        ["input_a", "input_b"]),
    "clip": ({"properties": {
        "input": {"description": "Result reference to clip."},
        "clip_area": {"description": "Result reference with clip geometries."}}},
        ["input", "clip_area"]),
    "dissolve": ({"properties": {
        "input": {"description": "Result reference."},
        "by_attribute": {"type": "string", "description": "Optional dissolve field."}}},
        ["input"]),
    "convex_hull": ({"properties": {
        "input": {"description": "Result reference."}}}, ["input"]),
    "simplify": ({"properties": {
        "input": {"description": "Result reference."},
        "tolerance_meters": {"type": "number", "description": "Default 10."}}},
        ["input"]),
}
