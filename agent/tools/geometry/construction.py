"""Geometry construction: build GeoJSON features from coordinates.

Every tool returns a FeatureCollection in EPSG:4326 so results flow straight
into buffer/intersect/measure/map tools via $step_id references. Use
create_circle for map-perfect circles; for analysis buffers prefer `buffer`
(CRS-aware metric buffering).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, collection


def _feat(geom: Dict[str, Any], props: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"type": "Feature", "properties": props or {}, "geometry": geom}


def create_point(lon: float, lat: float, properties: Dict[str, Any] | None = None):
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        raise ToolError("lon/lat must be numbers")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ToolError(f"coordinates out of range: lon={lon}, lat={lat}")
    return collection([_feat({"type": "Point", "coordinates": [lon, lat]}, properties)])


def create_line(coordinates: List[List[float]],
                properties: Dict[str, Any] | None = None):
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ToolError("'coordinates' needs at least 2 [lon, lat] positions")
    for c in coordinates:
        if (not isinstance(c, (list, tuple)) or len(c) < 2
                or not all(isinstance(v, (int, float)) for v in c[:2])):
            raise ToolError("each position must be [lon, lat] numbers")
    return collection([_feat({"type": "LineString",
                              "coordinates": [[float(x), float(y)] for x, y in coordinates]},
                             properties)])


def create_polygon(rings: List[List[List[float]]],
                   properties: Dict[str, Any] | None = None):
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise ToolError("'rings' must be a list of linear rings")
    clean = []
    for ring in rings:
        pts = [[float(x), float(y)] for x, y in ring]
        if len(pts) < 4:
            raise ToolError("each ring needs at least 4 positions")
        if pts[0] != pts[-1]:
            pts.append(list(pts[0]))
        clean.append(pts)
    return collection([_feat({"type": "Polygon", "coordinates": clean}, properties)])


def create_bbox(west: float, south: float, east: float, north: float,
                properties: Dict[str, Any] | None = None):
    from ..common import parse_bbox

    w, s, e, n = parse_bbox(f"{west},{south},{east},{north}")
    return collection([_feat(
        {"type": "Polygon",
         "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}, properties)])


def create_hex_grid(bbox: str, size_meters: float = 1000.0):
    """Hexagonal tessellation (flat-top) covering a bbox, sized in metres."""
    from shapely.geometry import Polygon, mapping

    from ..common import metric_crs_for, parse_bbox, reproject, to_meters

    w, s, e, n = parse_bbox(bbox)
    size = to_meters(size_meters, "meters")
    box = Polygon([(w, s), (e, s), (e, n), (w, n)])
    metric = metric_crs_for([box])
    mb = reproject(box, "EPSG:4326", metric)
    minx, miny, maxx, maxy = mb.bounds
    dx, dy = size * 1.5, size * (3 ** 0.5)
    feats = []
    row = col = 0
    y = miny
    while y < maxy + dy:
        x = minx + (dx / 2 if row % 2 else 0)
        while x < maxx + dx:
            cx = x + size / 2
            import math

            ring = [(cx + size * math.cos(math.pi / 3 * k),
                     y + dy / 2 + size * math.sin(math.pi / 3 * k)) for k in range(6)]
            hexagon = Polygon(ring + [ring[0]])
            if hexagon.intersects(mb):
                back = reproject(hexagon, metric, "EPSG:4326")
                feats.append({"type": "Feature",
                              "properties": {"row": row, "col": col},
                              "geometry": mapping(back)})
            col += 1
            x += dx
        row += 1
        col = 0
        y += dy
    return collection(feats, cell_size_m=size)


def create_voronoi(input: Dict[str, Any], bbox: str | None = None):
    """Voronoi regions of input point features, clipped to a bbox (or the
    points' envelope expanded 10%)."""
    from shapely.geometry import MultiPoint, mapping
    from shapely.ops import unary_union, voronoi_diagram

    from ..common import crs_of, parse_bbox, valid_shapes

    pairs = valid_shapes(input)
    if not pairs:
        raise ToolError("voronoi needs at least one input feature")
    pts = [g for _, g in pairs
           if g.geom_type in ("Point", "MultiPoint")]
    if len(pts) < len(pairs):
        raise ToolError("voronoi input must be point features")
    if len(pts) < 2:
        raise ToolError("voronoi needs at least 2 points")
    if bbox:
        w, s, e, n = parse_bbox(bbox)
        from shapely.geometry import box as sbox

        envelope = sbox(w, s, e, n)
    else:
        minx, miny, maxx, maxy = unary_union(pts).bounds
        dx, dy = (maxx - minx) * 0.1 + 1e-9, (maxy - miny) * 0.1 + 1e-9
        from shapely.geometry import box as sbox

        envelope = sbox(minx - dx, miny - dy, maxx + dx, maxy + dy)
    regions = voronoi_diagram(MultiPoint(pts), envelope=envelope)
    geoms = list(regions.geoms) if hasattr(regions, "geoms") else [regions]
    feats = [{"type": "Feature", "properties": {"region": i},
              "geometry": mapping(g)} for i, g in enumerate(geoms)]
    src = crs_of(input)
    out = collection(feats, clipped=bool(bbox))
    out["crs"] = src
    return out


CONSTRUCTION_SCHEMAS = {
    "create_point": ({"properties": {
        "lon": {"type": "number"}, "lat": {"type": "number"},
        "properties": {"description": "Optional attribute object."}}}, ["lon", "lat"]),
    "create_line": ({"properties": {
        "coordinates": {"description": "Array of [lon, lat], at least 2."},
        "properties": {"description": "Optional attribute object."}}}, ["coordinates"]),
    "create_polygon": ({"properties": {
        "rings": {"description": "Array of linear rings (outer + holes)."},
        "properties": {"description": "Optional attribute object."}}}, ["rings"]),
    "create_bbox": ({"properties": {
        "west": {"type": "number"}, "south": {"type": "number"},
        "east": {"type": "number"}, "north": {"type": "number"},
        "properties": {"description": "Optional attribute object."}}},
        ["west", "south", "east", "north"]),
    "create_hex_grid": ({"properties": {
        "bbox": {"type": "string", "description": "'west,south,east,north' (EPSG:4326)."},
        "size_meters": {"type": "number", "description": "Hex size in metres (default 1000)."}}},
        ["bbox"]),
    "create_voronoi": ({"properties": {
        "input": {"description": "Result reference to point features."},
        "bbox": {"type": "string", "description": "Optional clip 'west,south,east,north'."}}},
        ["input"]),
}
