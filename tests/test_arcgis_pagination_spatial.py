"""Pagination, server-side spatial filtering, fallback, and regression.

Covers the large-FeatureServer requirements: the 2000 service page size
must not silently bound analysis; proximity must filter server-side where
supported (ANY-semantics across reference polygons); and an unavailable
distance capability must fall back to a *complete* local computation.
"""

import json

import pytest

from agent.tools.data import arcgis as live


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _point_feature(oid, lon=-83.5, lat=41.6):
    return {"type": "Feature", "properties": {"OBJECTID": oid},
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def _point_page(ids, exceeded, lon=-83.5, lat=41.6):
    return {"features": [_point_feature(i, lon, lat) for i in ids],
            **({"exceededTransferLimit": True} if exceeded else {})}


def _install_live(monkeypatch, get_pages=None, post_pages=None,
                  count=None, caps=None):
    """Monkeypatch live transport + metadata. Lists are consumed in order."""
    from agent.tools.data import arcgis as L

    L.clear_capability_cache()
    monkeypatch.setattr(L, "_mock_enabled", lambda: False)
    monkeypatch.setattr(L, "_layer_urls",
                        lambda dataset, extra=None: ["http://x/0"])
    get_pages = list(get_pages or [])
    post_pages = list(post_pages or [])
    calls = {"get": [], "post": [], "describe": []}

    def fake_describe(url):
        calls["describe"].append(url)
        return dict({
            "geometryType": "esriGeometryPoint",
            "supportsPagination": True,
            "supportsQueryWithDistance": True,
            "supportsAdvancedQueries": True,
            "maxRecordCount": 2000,
        }, **(caps or {}))

    def fake_post(url, data=None, timeout=None):
        calls["post"].append(dict(data or {}))
        if (data or {}).get("returnCountOnly") == "true":
            return _FakeResponse({"count": count if count is not None
                                  else sum(len(p.get("features", []))
                                           for p in post_pages)})
        if not post_pages:
            return _FakeResponse({"features": []})
        return _FakeResponse(post_pages.pop(0))

    def fake_get(url, params=None, timeout=None):
        calls["get"].append(dict(params or {}))
        if (params or {}).get("returnCountOnly") == "true":
            return _FakeResponse({"count": count})
        if not get_pages:
            return _FakeResponse({"features": []})
        return _FakeResponse(get_pages.pop(0))

    monkeypatch.setattr(L, "describe_layer", fake_describe)
    monkeypatch.setattr(L.requests, "post", fake_post)
    monkeypatch.setattr(L.requests, "get", fake_get)
    return L, calls


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    live.clear_capability_cache()
    yield
    live.clear_capability_cache()


def test_id_phase_recovery_when_spatial_blanks(monkeypatch):
    """County quirk: spatial+geometry POSTs blank while light POSTs hit.

    Full-geometry spatial fetch returns 0 rows (and the count probe lies
    with 0), but OBJECTID-only collection + attribute fetch must still
    recover the matches with strategy ``server_spatial_ids``.
    """
    from agent.tools.data import arcgis as L

    L.clear_capability_cache()
    monkeypatch.setattr(L, "_mock_enabled", lambda: False)
    monkeypatch.setattr(L, "_layer_urls",
                        lambda dataset, extra=None: ["http://x/0"])
    monkeypatch.setattr(L, "describe_layer", lambda url: {
        "geometryType": "esriGeometryPoint", "supportsPagination": True,
        "supportsQueryWithDistance": True, "supportsAdvancedQueries": True})

    def fake_post(url, data=None, timeout=None):
        data = dict(data or {})
        if data.get("returnCountOnly") == "true":
            return _FakeResponse({"count": 0})  # lying count probe
        if "OBJECTID IN" in str(data.get("where", "")):
            return _FakeResponse({"features": [_point_feature(7),
                                                _point_feature(9)]})
        if data.get("returnGeometry") == "false":
            return _FakeResponse({"features": [
                {"type": "Feature", "properties": {"OBJECTID": 7},
                 "geometry": None},
                {"type": "Feature", "properties": {"OBJECTID": 9},
                 "geometry": None}]})
        return _FakeResponse({"features": []})  # geometry variant blanks

    monkeypatch.setattr(L.requests, "post", fake_post)
    monkeypatch.setattr(
        L.requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse({"count": 0}))
    out = L.query_arcgis("septic_systems", near=_near_poly(), distance_km=2,
                         max_features=100)
    assert out["ok"] and out["count"] == 2
    assert out["strategy"] == "server_spatial_ids"
    assert out["total_count"] == 2 and not out["truncated"]


def test_envelope_window_recovery(monkeypatch):
    """Envelope-bbox + local filter recovers when spatial POSTs blank.

    Spatial predicate POSTs (full and ID-phase) return nothing while a
    plain envelope-bbox GET returns candidates; the exact local metric
    filter must keep only true matches with strategy ``bbox_window_local``.
    """
    from agent.tools.data import arcgis as L

    L.clear_capability_cache()
    monkeypatch.setattr(L, "_mock_enabled", lambda: False)
    monkeypatch.setattr(L, "_layer_urls",
                        lambda dataset, extra=None: ["http://x/0"])
    monkeypatch.setattr(L, "describe_layer", lambda url: {
        "geometryType": "esriGeometryPoint", "supportsPagination": True,
        "supportsQueryWithDistance": True, "supportsAdvancedQueries": True})

    def fake_post(url, data=None, timeout=None):
        data = dict(data or {})
        if data.get("returnCountOnly") == "true":
            return _FakeResponse({"count": 0})
        return _FakeResponse({"features": []})  # all spatial POSTs blank

    def fake_get(url, params=None, timeout=None):
        params = dict(params or {})
        if params.get("returnCountOnly") == "true":
            return _FakeResponse({"count": 0})
        # Envelope-bbox plain GET returns one near + one far candidate.
        return _FakeResponse({"features": [
            _point_feature(11, lon=-83.549, lat=41.605),
            _point_feature(12, lon=-84.90, lat=40.00)]})

    monkeypatch.setattr(L.requests, "post", fake_post)
    monkeypatch.setattr(L.requests, "get", fake_get)
    ref = _near_poly(lon=-83.55, lat=41.60, size=0.02)
    out = L.query_arcgis("septic_systems", near=ref, distance_km=2,
                         max_features=100)
    assert out["ok"]
    assert out["strategy"] == "bbox_window_local"
    oids = [f["properties"]["OBJECTID"] for f in out["features"]]
    assert oids == [11]  # only the truly-near candidate survives


def test_zero_total_probe_runs_without_error(monkeypatch):
    """Empty spatial result with total==0 must run the verify probe cleanly.

    Regression: the probe once referenced an out-of-scope variable
    (NameError), turning an honest zero into a step failure.
    """
    from agent.tools.data import arcgis as L

    L.clear_capability_cache()
    monkeypatch.setattr(L, "_mock_enabled", lambda: False)
    monkeypatch.setattr(L, "_layer_urls",
                        lambda dataset, extra=None: ["http://x/0"])
    monkeypatch.setattr(L, "describe_layer", lambda url: {
        "geometryType": "esriGeometryPoint", "supportsPagination": True,
        "supportsQueryWithDistance": True, "supportsAdvancedQueries": True})
    monkeypatch.setattr(L.requests, "post",
                        lambda url, data=None, timeout=None: _FakeResponse(
                            {"count": 0} if (data or {}).get("returnCountOnly")
                            == "true" else {"features": []}))
    monkeypatch.setattr(
        L.requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse({"count": 0}))
    out = L.query_arcgis("septic_systems", near=_near_poly(), distance_km=2,
                         max_features=100)
    assert out["ok"] and out["count"] == 0
    assert "NameError" not in json.dumps(out.get("layer_errors", []))


def _near_poly(lon=-83.55, lat=41.60, size=0.02):
    return {
        "type": "FeatureCollection", "crs": "EPSG:4326",
        "features": [{
            "type": "Feature", "properties": {"OBJECTID": 1},
            "geometry": {"type": "Polygon", "coordinates": [[
                [lon, lat], [lon + size, lat],
                [lon + size, lat + size], [lon, lat + size],
                [lon, lat]]]}}]}


# ------------------------------------------------------------ Test 1: paging ---

def test_pagination_combines_pages_over_2000(monkeypatch):
    pages = [_point_page(range(1, 2001), True),
             _point_page(range(2001, 4001), True),
             _point_page(range(4001, 5501), False)]
    L, calls = _install_live(monkeypatch, get_pages=list(pages), count=5500)
    out = L.query_arcgis("septic_systems", max_features=6000, page_size=2000)
    assert out["ok"] and out["count"] == 5500
    assert out["total_count"] == 5500 and not out["truncated"]
    assert out["complete"] is True
    assert out["pages"] == 3
    assert out["pagination"]["page_size"] == 2000
    # Every request respects the per-request service page size.
    for c in calls["get"]:
        if c.get("returnCountOnly") != "true":
            assert int(c.get("resultRecordCount", 0)) <= 2000


def test_mock_pagination_over_2000(monkeypatch):
    import agent.tools.data.arcgis_mock as mock

    pts = [(-83.50 - i * 0.0001, 41.60) for i in range(4500)]
    monkeypatch.setattr(mock, "_SEPTIC_POINTS", pts)
    out = mock.query_mock("septic_systems", max_features=4500, page_size=2000)
    assert out["ok"] and out["count"] == 4500
    assert out["pages"] == 3 and not out["truncated"]


# ------------------------------------------------------- Test 2: exactly 2000 ---

def test_exactly_2000_makes_no_extra_request(monkeypatch):
    L, calls = _install_live(
        monkeypatch,
        get_pages=[_point_page(range(1, 2001), False)], count=2000)
    out = L.query_arcgis("septic_systems", max_features=6000, page_size=2000)
    assert out["ok"] and out["count"] == 2000 and not out["truncated"]
    data_calls = [c for c in calls["get"] if c.get("returnCountOnly") != "true"]
    assert len(data_calls) == 1  # count probe + exactly one data page


# ------------------------------------------------------------- Test 3: 2001 ---

def test_2001_retrieves_remainder(monkeypatch):
    L, calls = _install_live(
        monkeypatch,
        get_pages=[_point_page(range(1, 2001), True),
                   _point_page([2001], False)], count=2001)
    out = L.query_arcgis("septic_systems", max_features=5000, page_size=2000)
    assert out["ok"] and out["count"] == 2001
    assert out["total_count"] == 2001 and not out["truncated"]
    assert out["pages"] == 2


# -------------------------------------------------- Test 4: spatial filter ---

def _near_and_far_page():
    # OID 3 sits inside the default _near_poly (trust-but-verify keeps it);
    # OID 99 is ~3km east, outside the 2km radius (verification drops it
    # even though the stub server returned it — server rows are checked).
    return {"features": [_point_feature(3, lon=-83.54, lat=41.605),
                         _point_feature(99, lon=-83.50, lat=41.60)]}


def test_spatial_filter_posts_server_params(monkeypatch):
    L, calls = _install_live(
        monkeypatch, post_pages=[_near_and_far_page()], count=2)
    out = L.query_arcgis("septic_systems", max_features=100,
                         near=_near_poly(), distance_km=2)
    assert out["ok"] and out["count"] == 1
    assert out["features"][0]["properties"]["OBJECTID"] == 3
    assert out["strategy"] == "server_spatial"
    bodies = [c for c in calls["post"] if c.get("returnCountOnly") != "true"]
    assert bodies
    body = bodies[0]
    assert body["spatialRel"] == "esriSpatialRelIntersects"
    assert float(body["distance"]) == 2000.0
    assert body["units"] == "esriSRUnit_Meter"
    assert "rings" in body["geometry"]


def test_spatial_filter_dict_form_matches_near(monkeypatch):
    L, calls = _install_live(
        monkeypatch, post_pages=[_near_and_far_page()], count=2)
    near = _near_poly()
    out = L.query_arcgis(
        "septic_systems", max_features=100,
        spatial_filter={"reference": near, "relationship": "within_distance",
                        "distance": 2000, "units": "meters"})
    assert out["ok"] and out["count"] == 1
    assert out["features"][0]["properties"]["OBJECTID"] == 3
    assert out["strategy"] == "server_spatial"
    assert out["spatial_filter"]["relationship"] == "within_distance"
    bodies = [c for c in calls["post"] if c.get("returnCountOnly") != "true"]
    assert bodies and float(bodies[0]["distance"]) == 2000.0


def test_spatial_filter_dataset_name_reference_mock():
    from agent.config import settings

    if not settings.ARCGIS_USE_MOCK:
        pytest.skip("mock mode disabled")
    from agent.tools.data.arcgis import query_arcgis

    out = query_arcgis(
        "septic_systems", max_features=2000,
        spatial_filter={"reference": "floodplains",
                        "relationship": "within_distance",
                        "distance": 2000, "units": "meters"})
    assert out["ok"]
    assert out["strategy"] in ("server_spatial",
                               "local_fallback_distance_unsupported")
    assert out["count"] >= 1  # fixtures overlap by construction


# --------------------------------------- Test 5: ANY (not ALL) semantics ---

def test_multiple_reference_polygons_use_any_semantics(monkeypatch):
    import agent.tools.data.arcgis as L

    L.clear_capability_cache()
    monkeypatch.setattr(L, "_mock_enabled", lambda: False)
    monkeypatch.setattr(L, "_layer_urls",
                        lambda dataset, extra=None: ["http://x/0"])
    monkeypatch.setattr(L, "describe_layer", lambda url: {
        "geometryType": "esriGeometryPoint", "supportsPagination": True,
        "supportsQueryWithDistance": True, "supportsAdvancedQueries": True})
    # Force the batched (per-chunk POST) path instead of the dissolved-union
    # optimisation so each reference polygon produces its own request.
    monkeypatch.setattr(L, "NEAR_BATCH_SIZE", 1)
    _orig_near_chunks = L._near_chunks
    monkeypatch.setattr(
        L, "_dissolved_near_chunks",
        lambda near, dm: (*_orig_near_chunks(near, dm), "batched"))
    seen_geoms = []

    def fake_post(url, data=None, timeout=None):
        data = dict(data or {})
        if data.get("returnCountOnly") == "true":
            return _FakeResponse({"count": 1})
        seen_geoms.append(data.get("geometry", ""))
        # Each reference chunk matches a *different* septic point (OR).
        oid = 101 if len(seen_geoms) == 1 else 202
        return _FakeResponse(_point_page([oid], False))

    monkeypatch.setattr(L.requests, "post", fake_post)
    monkeypatch.setattr(L.requests, "get",
                        lambda url, params=None, timeout=None: _FakeResponse(
                            {"count": 2}))

    two_polys = {
        "type": "FeatureCollection", "crs": "EPSG:4326",
        "features": [
            {"type": "Feature", "properties": {"OBJECTID": 1},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [-83.62, 41.58], [-83.60, 41.58], [-83.60, 41.60],
                 [-83.62, 41.60], [-83.62, 41.58]]]}},
            {"type": "Feature", "properties": {"OBJECTID": 2},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [-83.50, 41.58], [-83.48, 41.58], [-83.48, 41.60],
                 [-83.50, 41.60], [-83.50, 41.58]]]}},
        ]}
    out = L.query_arcgis("septic_systems", near=two_polys, distance_km=2)
    assert out["ok"]
    oids = sorted(f["properties"]["OBJECTID"] for f in out["features"])
    assert oids == [101, 202]  # ANY: matches from either chunk are kept
    assert len(seen_geoms) == 2  # one POST per reference chunk


# --------------------------- Test 6: distance capability unavailable ---

def test_distance_unsupported_falls_back_complete(monkeypatch):
    # Target layer: 2500 features; only the LAST one is near the reference.
    # A naive first-2000 slice would miss it entirely.
    far = [_point_feature(i, lon=-84.50, lat=41.00) for i in range(1, 2500)]
    near_pt = _point_feature(2500, lon=-83.549, lat=41.605)
    all_feats = far + [near_pt]
    pages = [
        {"features": all_feats[0:2000], "exceededTransferLimit": True},
        {"features": all_feats[2000:], },
    ]
    L, _ = _install_live(monkeypatch, get_pages=list(pages), count=2500,
                         caps={"supportsPagination": True,
                               "supportsQueryWithDistance": False,
                               "supportsAdvancedQueries": True})
    ref = _near_poly(lon=-83.55, lat=41.60, size=0.02)
    out = L.query_arcgis("septic_systems", max_features=5000, page_size=2000,
                         near=ref, distance_km=2)
    assert out["ok"]
    assert out["strategy"] == "local_fallback_distance_unsupported"
    oids = [f["properties"]["OBJECTID"] for f in out["features"]]
    assert oids == [2500]  # found despite being outside the first page
    assert out["truncated"] is False


def test_mock_distance_unsupported_strategy(monkeypatch):
    import agent.tools.data.arcgis_mock as mock

    monkeypatch.setattr(mock, "MOCK_DISTANCE_SUPPORTED", False)
    try:
        from agent.tools.data.arcgis_mock import floodplain_fixture

        flood = {"type": "FeatureCollection", "crs": "EPSG:4326",
                 "features": floodplain_fixture()}
        out = mock.query_mock("septic_systems", near=flood, distance_km=2)
        assert out["ok"]
        assert out["strategy"] == "local_fallback_distance_unsupported"
    finally:
        monkeypatch.setattr(mock, "MOCK_DISTANCE_SUPPORTED", True)


# --------------------------------------------- Test 7: existing workflows ---

def test_buffer_intersect_nearest_still_work(points=None):
    from agent.tools.gis.operations import buffer, intersect, nearest

    pts = {"type": "FeatureCollection", "crs": "EPSG:4326", "features": [
        {"type": "Feature", "properties": {"id": 1},
         "geometry": {"type": "Point", "coordinates": [-83.70, 41.60]}},
        {"type": "Feature", "properties": {"id": 2},
         "geometry": {"type": "Point", "coordinates": [-83.00, 41.00]}}]}
    poly = {"type": "FeatureCollection", "crs": "EPSG:4326", "features": [
        {"type": "Feature", "properties": {"id": "fp"},
         "geometry": {"type": "Polygon", "coordinates": [[
             [-83.72, 41.58], [-83.68, 41.58], [-83.68, 41.62],
             [-83.72, 41.62], [-83.72, 41.58]]]}}]}
    assert buffer(pts, 2000, "meters")["count"] == 2
    assert intersect(pts, poly)["count"] == 1
    assert nearest(pts, poly, k=1)["row_count"] == 2


def test_rule_planner_still_emits_near_plan():
    from agent.planner import RulePlanner

    plan = RulePlanner().plan(
        "Find septic systems within 2 km of floodplain areas")["plan"]
    by_id = {s.id: s for s in plan.steps}
    assert by_id["septic"].arguments.get("near") == "$floodplains"
    assert by_id["septic"].arguments.get("distance_km") == 2


# ---------------------------------- Test 8: regression beyond first 2000 ---

def test_regression_answer_outside_first_2000_found(monkeypatch):
    """Septic #8421 near floodplain #2315: must not return 0 via truncation."""
    import agent.tools.data.arcgis_mock as mock

    # 9000 far-away septic points + the answer near the target floodplain.
    far_septic = [(-84.90 - (i % 100) * 0.001, 40.00 + (i % 100) * 0.001)
                  for i in range(9000)]
    answer = (-83.549, 41.605)
    monkeypatch.setattr(mock, "_SEPTIC_POINTS", far_septic + [answer])
    # 3000 far-away floodplain polys (elsewhere: no overlap with far septic
    # cluster) + the relevant one near the answer.
    flood_polys = [
        {"ring": [[-85.50, 39.00], [-85.49, 39.00], [-85.49, 39.01],
                  [-85.50, 39.01], [-85.50, 39.00]], "zone": "X"}
        for _ in range(3000)
    ] + [{"ring": [[-83.56, 41.60], [-83.54, 41.60], [-83.54, 41.61],
                    [-83.56, 41.61], [-83.56, 41.60]], "zone": "AE"}]
    monkeypatch.setattr(mock, "_FLOODPLAIN_POLYS", flood_polys)

    from agent.tools.data.arcgis_mock import floodplain_fixture

    flood = {"type": "FeatureCollection", "crs": "EPSG:4326",
             "features": floodplain_fixture()}
    # Reference floodplain #2315 equivalent: the last (near) polygon only.
    ref = {"type": "FeatureCollection", "crs": "EPSG:4326",
           "features": flood["features"][-1:]}
    out = mock.query_mock("septic_systems", near=ref, distance_km=2,
                          max_features=20000, page_size=2000)
    assert out["ok"] and out["count"] == 1
    lon, lat = out["features"][0]["geometry"]["coordinates"]
    assert abs(lon - answer[0]) < 1e-9 and abs(lat - answer[1]) < 1e-9

    # The old buggy path (first-2000 slices intersected locally) finds nothing.
    first_septic = mock.query_mock("septic_systems", max_features=2000)
    first_flood = mock.query_mock("floodplains", max_features=2000)
    assert first_septic["ok"] and first_flood["ok"]
    from agent.tools.gis.operations import buffer as _buffer
    from agent.tools.gis.operations import intersect as _intersect

    buf = _buffer(first_flood, 2, unit="kilometers")
    buggy = _intersect(first_septic, buf)
    assert buggy["count"] == 0  # documents the original failure mode
