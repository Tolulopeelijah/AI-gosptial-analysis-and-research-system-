"""CRS-aware measurement with explicit units.

Areas in square metres/kilometres, lengths in metres/kilometres, bearings in
degrees clockwise from north. Every numeric answer names its unit — a result
without units is a bug here.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import crs_of, metric_crs_for, reproject, table, valid_shapes


def _projected(pairs, src: str):
    metric = metric_crs_for([g for _, g in pairs])
    return [reproject(g, src, metric) for _, g in pairs], metric


def calculate_area(input: Dict[str, Any], unit: str = "sqm"):
    """Polygon area per feature. unit: sqm (default) or sqkm."""
    if unit not in ("sqm", "sqkm"):
        from ..common import ToolError

        raise ToolError("unit must be 'sqm' or 'sqkm'")
    pairs = valid_shapes(input)
    src = crs_of(input)
    geoms, metric = _projected(pairs, src)
    rows = []
    for i, ((feat, _), gm) in enumerate(zip(pairs, geoms)):
        area = gm.area
        rows.append({"feature": i,
                     "area_sqm": round(area, 2),
                     "area_sqkm": round(area / 1e6, 6),
                     "value": round(area / 1e6, 6) if unit == "sqkm" else round(area, 2),
                     "unit": unit})
    return table(["feature", "area_sqm", "area_sqkm", "value", "unit"], rows,
                 transform=f"metric via {metric}")


def calculate_length(input: Dict[str, Any], unit: str = "meters"):
    """Line length per feature (polygon inputs measure exterior rings)."""
    if unit not in ("meters", "kilometers"):
        from ..common import ToolError

        raise ToolError("unit must be 'meters' or 'kilometers'")
    pairs = valid_shapes(input)
    src = crs_of(input)
    geoms, metric = _projected(pairs, src)
    rows = []
    for i, ((_, _), gm) in enumerate(zip(pairs, geoms)):
        length = gm.length
        rows.append({"feature": i,
                     "length_m": round(length, 2),
                     "value": round(length / 1000.0, 4) if unit == "kilometers"
                     else round(length, 2),
                     "unit": unit})
    return table(["feature", "length_m", "value", "unit"], rows,
                 transform=f"metric via {metric}")


def calculate_bearing(input_a: Dict[str, Any], input_b: Dict[str, Any]):
    """Bearing in degrees clockwise from north, A centroid → B centroid."""
    import math

    pairs_a = valid_shapes(input_a, "input_a")
    pairs_b = valid_shapes(input_b, "input_b")
    if not pairs_a or not pairs_b:
        return table(["a_index", "b_index", "bearing_deg"], [], row_count=0,
                     note="empty input side")
    rows = []
    for i, (_, ga) in enumerate(pairs_a):
        ca = ga.centroid
        for j, (_, gb) in enumerate(pairs_b):
            cb = gb.centroid
            dx, dy = cb.x - ca.x, cb.y - ca.y
            bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
            rows.append({"a_index": i, "b_index": j,
                         "bearing_deg": round(bearing, 2)})
    return table(["a_index", "b_index", "bearing_deg"], rows,
                 note="bearings from WGS84 centroid deltas; metric-grade "
                      "bearings need projected inputs")


def calculate_centroid_coords(input: Dict[str, Any]):
    """Centroid longitude/latitude per feature (table)."""
    pairs = valid_shapes(input)
    rows = [{"feature": i, "lon": round(g.centroid.x, 6),
             "lat": round(g.centroid.y, 6)} for i, (_, g) in enumerate(pairs)]
    return table(["feature", "lon", "lat"], rows, crs=crs_of(input))


def calculate_geometry_statistics(input: Dict[str, Any]):
    """Per-feature area, length, vertex count, bbox, geometry type."""
    pairs = valid_shapes(input)
    src = crs_of(input)
    geoms, metric = _projected(pairs, src)
    rows = []
    for i, ((_, g), gm) in enumerate(zip(pairs, geoms)):
        try:
            vertices = len(gm.exterior.coords)
        except AttributeError:
            try:
                vertices = len(gm.coords)
            except AttributeError:
                vertices = sum(len(part.coords) for part in gm.geoms)
        minx, miny, maxx, maxy = gm.bounds
        rows.append({"feature": i, "geom_type": g.geom_type,
                     "area_sqm": round(gm.area, 2),
                     "length_m": round(gm.length, 2),
                     "vertices": vertices,
                     "bbox": [round(v, 2) for v in (minx, miny, maxx, maxy)],
                     "bbox_crs": metric})
    return table(["feature", "geom_type", "area_sqm", "length_m", "vertices",
                  "bbox", "bbox_crs"], rows)


MEASUREMENT_SCHEMAS = {
    "calculate_area": ({"properties": {
        "input": {"description": "Result reference with polygons."},
        "unit": {"type": "string", "description": "'sqm' (default) or 'sqkm'."}}},
        ["input"]),
    "calculate_length": ({"properties": {
        "input": {"description": "Result reference with lines."},
        "unit": {"type": "string", "description": "'meters' (default) or 'kilometers'."}}},
        ["input"]),
    "calculate_bearing": ({"properties": {
        "input_a": {"description": "Result reference (origins)."},
        "input_b": {"description": "Result reference (destinations)."}}},
        ["input_a", "input_b"]),
    "calculate_centroid_coords": ({"properties": {
        "input": {"description": "Result reference."}}}, ["input"]),
    "calculate_geometry_statistics": ({"properties": {
        "input": {"description": "Result reference."}}}, ["input"]),
}
