"""Geometry: construction, vector ops, relationships, proximity, measurement, CRS."""

import math

import pytest

from agent.tools.geometry import (construction as C, crs as S, measurement as M,
                                  proximity as P, relationships as R,
                                  vector as V)


def test_create_point_line_polygon_bbox():
    pt = C.create_point(-83.5, 41.6, {"id": 1})
    assert pt["features"][0]["geometry"] == {"type": "Point",
                                             "coordinates": [-83.5, 41.6]}
    with pytest.raises(Exception):
        C.create_point(-200, 41.6)
    line = C.create_line([[-83.7, 41.6], [-83.5, 41.6]])
    assert line["features"][0]["geometry"]["type"] == "LineString"
    with pytest.raises(Exception):
        C.create_line([[-83.7, 41.6]])
    poly = C.create_polygon([[[-83.7, 41.5], [-83.4, 41.5], [-83.4, 41.7],
                              [-83.7, 41.5]]])
    assert poly["features"][0]["geometry"]["coordinates"][0][0] == \
        poly["features"][0]["geometry"]["coordinates"][0][-1]
    box = C.create_bbox(-83.7, 41.5, -83.4, 41.7)
    assert box["count"] == 1
    with pytest.raises(Exception):
        C.create_bbox(-83.4, 41.5, -83.7, 41.7)


def test_hex_grid_and_voronoi(points):
    grid = C.create_hex_grid("-83.7,41.5,-83.4,41.7", 5000)
    assert grid["count"] > 5
    assert all(f["geometry"]["type"] == "Polygon" for f in grid["features"])
    vor = C.create_voronoi(points)
    assert vor["count"] == 3
    with pytest.raises(Exception):
        C.create_voronoi({"type": "FeatureCollection", "features": []})


def test_vector_overlay(points, poly):
    assert V.union(poly)["count"] == 1
    assert V.convex_hull(points)["count"] == 3
    clipped = V.clip(points, poly)
    assert clipped["count"] == 2
    assert clipped["compared"] == {"input": 3, "clip": 1}
    assert V.difference(poly, poly)["count"] == 0
    dissolved = V.dissolve(points)
    assert dissolved["features"][0]["properties"]["dissolved_count"] == 3
    by_zone = V.dissolve(poly, by_attribute="zone")
    assert by_zone["features"][0]["properties"]["zone"] == "Z"
    simple = V.simplify(poly, tolerance_meters=100)
    assert simple["vertices_after"] <= simple["vertices_before"]


def test_relationships(points, poly):
    assert R.within(points, poly)["count"] == 2
    assert R.disjoint(points, poly)["count"] == 1
    assert R.covers(poly, points)["count"] == 0  # polygon vs union-of-points
    assert R.contains(poly, poly)["count"] == 1
    rel = R.relate(points, poly)
    assert len(rel["matrix_table"]["rows"]) == 3
    assert all(len(r["de9im"]) == 9 for r in rel["matrix_table"]["rows"])
    filt = R.spatial_filter(points, poly, predicate="within")
    assert filt["count"] == 2
    with pytest.raises(Exception):
        R.spatial_filter(points, poly, predicate="nearby")


def test_proximity_metric(points, poly):
    d = P.distance(points, poly)
    assert d["row_count"] == 3
    assert all(r["distance_km"] >= 0 for r in d["rows"])
    # Point inside the polygon must be ~0 km away (not degrees).
    inside = next(r for r in d["rows"] if r["a_index"] == 0)
    assert inside["distance_km"] < 1.0
    near = P.within_distance(points, poly, 1, unit="kilometers")
    assert 1 <= near["count"] <= 2
    with pytest.raises(Exception):
        P.within_distance(points, poly, -5)
    mat = P.distance_matrix(points)
    assert mat["row_count"] == 9
    assert all(r["distance_km"] == 0 for r in mat["rows"] if r["a_index"] == r["b_index"])


def test_measurement_units(poly, points):
    area = M.calculate_area(poly, unit="sqkm")
    assert area["rows"][0]["unit"] == "sqkm"
    assert 400 < area["rows"][0]["value"] < 700
    with pytest.raises(Exception):
        M.calculate_area(poly, unit="acres")
    line = C.create_line([[-83.7, 41.6], [-83.5, 41.6]])
    length = M.calculate_length(line, unit="kilometers")
    assert 15 < length["rows"][0]["value"] < 20
    bearing = M.calculate_bearing(points, points)
    assert bearing["rows"][0]["bearing_deg"] == 0.0
    cents = M.calculate_centroid_coords(points)
    assert cents["rows"][0]["lon"] == pytest.approx(-83.55)
    stats = M.calculate_geometry_statistics(poly)
    assert stats["rows"][0]["geom_type"] == "Polygon"
    assert stats["rows"][0]["vertices"] == 5


def test_crs_roundtrip(points):
    assert S.get_crs(points)["crs"] == "EPSG:4326"
    assert S.get_crs({})["crs"] == "EPSG:4326"
    assert S.get_utm_zone(-83.55, 41.6)["epsg"] == "EPSG:32617"
    assert S.get_utm_zone(-83.55, -23.5)["hemisphere"] == "S"
    moved = S.transform_crs(points, "EPSG:3857")
    assert moved["crs"] == "EPSG:3857"
    back = S.transform_crs(moved, "EPSG:4326")
    x0 = points["features"][0]["geometry"]["coordinates"]
    x1 = back["features"][0]["geometry"]["coordinates"]
    assert abs(x0[0] - x1[0]) < 1e-6 and abs(x0[1] - x1[1]) < 1e-6
    labelled = S.set_crs({"type": "FeatureCollection", "features": []}, "EPSG:3857")
    assert labelled["crs"] == "EPSG:3857"
    with pytest.raises(Exception):
        S.set_crs(points, "EPSG:999999")
    moved_pts = S.transform_coordinates([[-83.55, 41.6]], "EPSG:4326", "EPSG:3857")
    assert abs(moved_pts["rows"][0]["x_out"]) > 1e6  # metres, not degrees
