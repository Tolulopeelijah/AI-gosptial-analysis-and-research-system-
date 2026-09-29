"""Spatial relationship predicates with real filtering semantics.

Each predicate keeps the A features satisfying the DE-9IM relationship
against the union of B — these are distinct topological questions, not
aliases (e.g. `covers` includes boundary contact, `contains` excludes it).
`relate` exposes raw DE-9IM strings for custom patterns; `spatial_filter`
parameterises the predicate by name for planned queries.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, collection, crs_of, to_wgs_feature, valid_shapes

PREDICATES = ("intersects", "within", "contains", "crosses", "touches",
              "overlaps", "disjoint", "equals", "covers", "covered_by")


def _predicate_op(name: str, input_a: Dict[str, Any], input_b: Dict[str, Any]):
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
            matched = (name == "disjoint")
        else:
            matched = bool(getattr(geom, name)(b_union))
        if matched:
            props = dict(feat.get("properties", {}) or {})
            props["_predicate"] = name
            feats.append(to_wgs_feature(geom, props, src_a))
    return collection(feats, predicate=name,
                      compared={"a": len(pairs_a), "b": len(pairs_b)})


def within(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """A features completely inside B."""
    return _predicate_op("within", input_a, input_b)


def contains(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """A features containing B (B interior, no boundary-only contact)."""
    return _predicate_op("contains", input_a, input_b)


def disjoint(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """A features sharing no point with B."""
    return _predicate_op("disjoint", input_a, input_b)


def covers(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """A features covering B (boundary contact allowed)."""
    return _predicate_op("covers", input_a, input_b)


def relate(input_a: Dict[str, Any], input_b: Dict[str, Any],
           pattern: str | None = None):
    """DE-9IM matrix per A feature against the B union; optional pattern
    filter (e.g. 'T********' keeps A features intersecting B)."""
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    from shapely.ops import unary_union

    src_a = crs_of(input_a)
    b_union = unary_union([g for _, g in pairs_b]) if pairs_b else None
    rows: List[Dict[str, Any]] = []
    feats = []
    for i, (feat, geom) in enumerate(pairs_a):
        matrix = geom.relate(b_union) if b_union is not None else "FFFFFFFFF"
        keep = True
        if pattern:
            if len(pattern) != 9:
                raise ToolError("DE-9IM pattern must be 9 characters")
            keep = all(p in ("*", m) for p, m in zip(pattern, matrix))
        rows.append({"a_index": i, "de9im": matrix, "kept": keep})
        if keep:
            props = dict(feat.get("properties", {}) or {})
            props["_de9im"] = matrix
            feats.append(to_wgs_feature(geom, props, src_a))
    from ..common import table

    return {"ok": True, "type": "FeatureCollection", "features": feats,
            "count": len(feats), "crs": "EPSG:4326",
            "matrix_table": {"columns": ["a_index", "de9im", "kept"], "rows": rows}}


def spatial_filter(input_a: Dict[str, Any], input_b: Dict[str, Any],
                   predicate: str = "intersects"):
    """Filter A by any named predicate (for planned queries that choose the
    relationship at plan time)."""
    if predicate not in PREDICATES:
        raise ToolError(f"unknown predicate '{predicate}'; use one of "
                        f"{', '.join(PREDICATES)}")
    return _predicate_op(predicate, input_a, input_b)


RELATIONSHIP_SCHEMAS = {
    name: ({"properties": {
        "input_a": {"description": "Result reference filtered."},
        "input_b": {"description": "Result reference compared against."}}},
        ["input_a", "input_b"])
    for name in ("within", "contains", "disjoint", "covers")
}
RELATIONSHIP_SCHEMAS["relate"] = ({"properties": {
    "input_a": {"description": "Result reference."},
    "input_b": {"description": "Result reference."},
    "pattern": {"type": "string",
                "description": "Optional 9-char DE-9IM pattern, '*' wildcards."}}},
    ["input_a", "input_b"])
RELATIONSHIP_SCHEMAS["spatial_filter"] = ({"properties": {
    "input_a": {"description": "Result reference filtered."},
    "input_b": {"description": "Result reference compared against."},
    "predicate": {"type": "string",
                  "description": f"One of: {', '.join(PREDICATES)}."}}},
    ["input_a", "input_b"])
