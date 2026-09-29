"""Analysis: joins, aggregation, statistics, temporal."""

import pytest

from agent.tools.analysis import (aggregation as A, joins as J,
                                  statistics as S, temporal as T)


def test_spatial_join_variants(points, poly):
    joined = J.spatial_join(points, poly)
    assert joined["count"] == 3  # 2 matched + 1 passthrough
    assert joined["features"][0]["properties"]["zone"] == "Z"
    assert "_join_b_index" in joined["features"][0]["properties"]
    agg = J.aggregate_join(poly, points, operation="count")
    assert agg["features"][0]["properties"]["_agg_count"] == 2
    total = J.aggregate_join(poly, points, operation="sum", field="v")
    assert total["features"][0]["properties"]["_agg_sum"] == 30.0
    avg = J.aggregate_join(poly, points, operation="mean", field="v")
    assert avg["features"][0]["properties"]["_agg_mean"] == 15.0
    with pytest.raises(Exception):
        J.aggregate_join(poly, points, operation="sum")
    near = J.join_by_nearest(points, poly, k=1)
    assert near["count"] == 3
    assert all("_distance_km" in f["properties"] for f in near["features"])
    moved = J.transfer_attributes(points, poly, fields=["zone"])
    assert all(f["properties"]["zone"] == "Z" for f in moved["features"])
    with pytest.raises(Exception):
        J.transfer_attributes(points, poly, fields=[])


def test_aggregation(points, poly):
    assert A.count_features(points)["rows"][0] == {"metric": "count", "value": 3}
    total = A.aggregate_features(points, field="v", operation="sum")
    assert total["rows"][0]["value"] == 60.0
    assert A.aggregate_features(points, field="v", operation="mean")["rows"][0]["value"] == 20.0
    grouped = A.summarize_by_attribute(points, field="v", group_by="id")
    assert len(grouped["rows"]) == 3
    pct = A.percentage_by_area(poly, poly)
    assert pct["rows"][0]["percentage"] == 100.0
    assert pct["rows"][0]["unit"] == "percent"


def test_descriptive_stats(points):
    assert S.calculate_mean(points, "v")["rows"][0]["mean"] == 20.0
    std = S.calculate_std(points, "v")["rows"][0]
    assert std["std"] == pytest.approx(8.165, abs=0.01)
    assert std["variance"] == pytest.approx(66.667, abs=0.01)
    pct = S.calculate_percentiles(points, "v")
    assert [r["percentile"] for r in pct["rows"]] == [0, 25, 50, 75, 100]
    corr = S.calculate_correlation(points, "id", "v")
    assert corr["rows"][0]["pearson_r"] == pytest.approx(1.0)
    with pytest.raises(Exception):
        S.calculate_mean(points, "missing_field")
    with pytest.raises(Exception):
        S.calculate_percentiles(points, "v", percentiles=[150])


def _clustered_points():
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"v": v},
         "geometry": {"type": "Point", "coordinates": c}}
        for v, c in [(10, (-83.55, 41.60)), (12, (-83.56, 41.61)),
                     (11, (-83.57, 41.62)), (30, (-83.00, 41.00)),
                     (32, (-83.01, 41.02))]]}


def test_spatial_statistics():
    pts = _clustered_points()
    moran = S.moran_i(pts, "v")["rows"][0]
    assert moran["interpretation"] == "clustered"
    assert moran["moran_i"] > moran["expected"]
    assert 0 <= moran["p_value"] <= 1
    lisa = S.local_moran(pts, "v")
    assert {r["quadrant"] for r in lisa["rows"]} <= {"HH", "LL", "HL", "LH"}
    getis = S.getis_ord(pts, "v")
    assert len(getis["rows"]) == 5
    hot = S.hotspot_analysis(pts, "v")
    assert {r["class"] for r in hot["rows"]} <= {"hotspot", "coldspot", "not_significant"}
    kde = S.kernel_density(pts)
    assert kde["count"] > 0 and kde["units"] == "density_per_km2"
    with pytest.raises(Exception):
        S.moran_i({"type": "FeatureCollection", "features": pts["features"][:3]}, "v")


def test_temporal(small_table):
    day = T.filter_by_date(small_table, "2020-01-03")
    assert day["row_count"] == 1 and day["rows"][0]["v"] == 30
    window = T.filter_by_time_range(small_table, "2020-01-02", "2020-01-04")
    assert window["row_count"] == 3
    with pytest.raises(Exception):
        T.filter_by_time_range(small_table, "2020-01-05", "2020-01-01")
    monthly = T.aggregate_temporal(small_table, "v", freq="ME")
    assert monthly["row_count"] == 1 and monthly["rows"][0]["v"] == 40.0
    stats = T.temporal_statistics(small_table, "v")
    assert stats["rows"][0]["span_days"] == 6.0
    trend = T.detect_temporal_trend(small_table, "v")
    assert trend["rows"][0]["direction"] == "increasing"
    assert trend["rows"][0]["slope_per_day"] == pytest.approx(10.0)
