"""Aggregation and spatial summarization over features and tables.

Answers "how many per area", "share of area", and "density" questions by
combining counts, grouped statistics, and metric area measurement. Density and
percentage tools state their units explicitly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, table, valid_shapes


def _numeric_column(rows: List[Dict[str, Any]], field: str) -> List[float]:
    vals = []
    for r in rows:
        v = r.get(field)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return vals


def count_features(input: Dict[str, Any]):
    """Feature count (and per-geometry-type breakdown) for a collection."""
    pairs = valid_shapes(input)
    by_type: Dict[str, int] = {}
    for _, g in pairs:
        by_type[g.geom_type] = by_type.get(g.geom_type, 0) + 1
    return table(["metric", "value"],
                 [{"metric": "count", "value": len(pairs)}] +
                 [{"metric": f"type:{k}", "value": v} for k, v in sorted(by_type.items())])


def aggregate_features(input: Dict[str, Any], field: str, operation: str = "sum"):
    """Single rolled-up value over a numeric attribute table or feature
    properties: sum|mean|min|max|count."""
    if operation not in ("sum", "mean", "min", "max", "count"):
        raise ToolError("operation must be sum|mean|min|max|count")
    if input.get("type") == "table":
        rows = input.get("rows", [])
    else:
        rows = [dict(feat.get("properties", {}) or {})
                for feat, _ in valid_shapes(input)]
    vals = _numeric_column(rows, field)
    if operation == "count":
        value: Any = len([r for r in rows if r.get(field) is not None])
    elif not vals:
        value = None
    elif operation == "sum":
        value = float(sum(vals))
    elif operation == "mean":
        value = float(sum(vals) / len(vals))
    elif operation == "min":
        value = float(min(vals))
    else:
        value = float(max(vals))
    return table(["field", "operation", "n", "value"],
                 [{"field": field, "operation": operation, "n": len(vals),
                   "value": value}])


def summarize_by_attribute(input: Dict[str, Any], field: str, group_by: str):
    """Group statistics (count/mean/min/max) of a numeric field per category."""
    if input.get("type") == "table":
        rows = input.get("rows", [])
    else:
        rows = [dict(feat.get("properties", {}) or {})
                for feat, _ in valid_shapes(input)]
    groups: Dict[str, List[float]] = {}
    counts: Dict[str, int] = {}
    for r in rows:
        key = str(r.get(group_by))
        counts[key] = counts.get(key, 0) + 1
        v = r.get(field)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            groups.setdefault(key, []).append(float(v))
    out = []
    for key in sorted(counts):
        vals = groups.get(key, [])
        out.append({"group": key, "count": counts[key],
                    "mean": round(sum(vals) / len(vals), 4) if vals else None,
                    "min": min(vals) if vals else None,
                    "max": max(vals) if vals else None})
    return table(["group", "count", "mean", "min", "max"], out,
                 field=field, group_by=group_by)


def percentage_by_area(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """Share (%) of each A polygon's metric area covered by B (per A feature)."""
    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    from shapely.ops import unary_union

    from ..common import crs_of, metric_crs_for, reproject

    src_a, src_b = crs_of(input_a), crs_of(input_b)
    metric = metric_crs_for([g for _, g in pairs_a] + [g for _, g in pairs_b])
    b_union = unary_union([reproject(g, src_b, metric) for _, g in pairs_b]) \
        if pairs_b else None
    rows = []
    for i, (_, geom_a) in enumerate(pairs_a):
        ga = reproject(geom_a, src_a, metric)
        area = ga.area
        covered = ga.intersection(b_union).area if b_union is not None and area else 0.0
        rows.append({"feature": i, "area_sqm": round(area, 2),
                     "covered_sqm": round(covered, 2),
                     "percentage": round(100.0 * covered / area, 2) if area else 0.0,
                     "unit": "percent"})
    return table(["feature", "area_sqm", "covered_sqm", "percentage", "unit"], rows)


AGGREGATION_SCHEMAS = {
    "count_features": ({"properties": {
        "input": {"description": "Result reference."}}}, ["input"]),
    "aggregate_features": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "field": {"type": "string", "description": "Numeric field."},
        "operation": {"type": "string", "description": "sum|mean|min|max|count."}}},
        ["input", "field"]),
    "summarize_by_attribute": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "field": {"type": "string", "description": "Numeric field."},
        "group_by": {"type": "string", "description": "Category field."}}},
        ["input", "field", "group_by"]),
    "percentage_by_area": ({"properties": {
        "input_a": {"description": "Result reference (areas)."},
        "input_b": {"description": "Result reference (coverage)."}}},
        ["input_a", "input_b"]),
}
