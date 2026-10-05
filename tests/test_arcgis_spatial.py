"""Server-side ArcGIS spatial queries: near/distance_km, paging, truncation.

Covers the fetch-then-intersect fix: proximity filtering happens at the
ArcGIS source (or the mock equivalent), pages until exhausted, and any cap
is reported in execution metadata + explanation instead of silently dropping
matches.
"""

import pytest

from agent.plans import ExecutionPlan, PlanStep, PlanValidationError, validate_plan

QUERY = "Find septic systems within 2 km of floodplain areas"
TOOLS = {"query_arcgis", "buffer", "intersect"}
DATASETS = {"septic_systems", "floodplains"}


def _needs_mock():
    from agent.config import settings

    if not settings.ARCGIS_USE_MOCK:
        pytest.skip("mock mode disabled")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _near_poly():
    return {
        "type": "FeatureCollection",
        "crs": "EPSG:4326",
        "features": [{
            "type": "Feature", "properties": {"OBJECTID": 1},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.62, 41.58], [-83.48, 41.58], [-83.48, 41.70],
                [-83.62, 41.70], [-83.62, 41.58]]]},
        }],
    }


# ---------------------------------------------------------------- planner ---

def test_rule_planner_emits_two_step_near_plan():
    from agent.planner import RulePlanner

    plan = RulePlanner().plan(QUERY)["plan"]
    assert plan is not None
    by_id = {s.id: s for s in plan.steps}
    assert set(by_id) == {"septic", "floodplains"}
    septic = by_id["septic"]
    assert septic.arguments.get("near") == "$floodplains"
    assert septic.arguments.get("distance_km") == 2
    assert "floodplains" in septic.depends_on


def test_e2e_septic_within_2km_returns_expected_ids():
    _needs_mock()
    from agent.agent import GeospatialAgent
    from agent.planner import RulePlanner

    agent = GeospatialAgent()
    agent.planner = RulePlanner()
    resp = agent.ask(QUERY)
    assert resp["status"] == "completed"
    septic_layers = [layer for layer in resp["results"]
                     if layer["metadata"]["dataset"] == "septic_systems"]
    assert len(septic_layers) == 1
    oids = sorted(f["properties"]["OBJECTID"]
                  for f in septic_layers[0]["data"]["features"])
    assert oids == [3, 6, 7, 8]
    # No client-side buffer/intersect round-trip anymore.
    tools = {s["tool"] for s in resp["execution"]["plan"]["steps"]}
    assert "buffer" not in tools and "intersect" not in tools


# -------------------------------------------------------------------- mock ---

def test_mock_near_without_distance_is_pure_intersect():
    _needs_mock()
    from agent.tools.data.arcgis_mock import query_mock, floodplain_fixture

    flood = {"type": "FeatureCollection", "crs": "EPSG:4326",
             "features": floodplain_fixture()}
    out = query_mock("septic_systems", near=flood)
    assert out["ok"]
    assert sorted(f["properties"]["OBJECTID"] for f in out["features"]) == [6, 7, 8]


def test_mock_pagination_returns_all_rows(monkeypatch):
    import agent.tools.data.arcgis_mock as mock

    monkeypatch.setattr(mock, "_SEPTIC_POINTS",
                        [(-83.50 - i * 0.001, 41.60) for i in range(7)])
    out = mock.query_mock("septic_systems", max_features=100, page_size=3)
    assert out["ok"] and out["count"] == 7
    assert out["pages"] == 3 and not out["truncated"]


def test_mock_truncation_reports_counts():
    _needs_mock()
    from agent.tools.data.arcgis_mock import query_mock, floodplain_fixture

    flood = {"type": "FeatureCollection", "crs": "EPSG:4326",
             "features": floodplain_fixture()}
    out = query_mock("septic_systems", near=flood, distance_km=2, max_features=2)
    assert out["ok"] and out["count"] == 2
    assert out["truncated"] is True and out["total_count"] == 4
    assert "septic_systems" in (out["truncation_warning"] or "")
    assert "incomplete" in (out["truncation_warning"] or "")


# -------------------------------------------------------------- truncation ---

def test_truncation_warning_in_execution_and_explanation():
    _needs_mock()
    from agent.orchestration import Orchestrator
    from agent.tools.registry import build_tool_registry

    plan = ExecutionPlan(goal=QUERY, steps=[
        PlanStep(id="floodplains", tool="query_arcgis",
                 arguments={"dataset": "floodplains", "max_features": 2000},
                 depends_on=[]),
        PlanStep(id="septic", tool="query_arcgis",
                 arguments={"dataset": "septic_systems", "max_features": 2,
                            "near": "$floodplains", "distance_km": 2},
                 depends_on=["floodplains"]),
    ])
    resp = Orchestrator(build_tool_registry()).execute(plan, query_id="q_trunc")
    assert resp["status"] == "completed"
    warnings = resp["execution"].get("truncation_warnings") or []
    assert any("septic_systems" in w for w in warnings)
    # Explanation stays conversational but must stay honest about the cap.
    assert "first 2" in resp["explanation"]
    assert "Goal:" not in resp["explanation"]


# -------------------------------------------------------------- validation ---

def test_validation_accepts_near_and_rejects_unknown_ref():
    ok = ExecutionPlan(goal=QUERY, steps=[
        PlanStep(id="floodplains", tool="query_arcgis",
                 arguments={"dataset": "floodplains"}, depends_on=[]),
        PlanStep(id="septic", tool="query_arcgis",
                 arguments={"dataset": "septic_systems",
                            "near": "$floodplains", "distance_km": 2},
                 depends_on=["floodplains"]),
    ])
    validate_plan(ok, known_tools=TOOLS, known_datasets=DATASETS,
                  gis_result_tools={"buffer", "intersect"})

    unknown = ExecutionPlan(goal=QUERY, steps=[
        PlanStep(id="septic", tool="query_arcgis",
                 arguments={"dataset": "septic_systems", "near": "$ghost"},
                 depends_on=["ghost"]),
    ])
    with pytest.raises(PlanValidationError):
        validate_plan(unknown, known_tools=TOOLS, known_datasets=DATASETS,
                      gis_result_tools={"buffer", "intersect"})

    missing_dep = ExecutionPlan(goal=QUERY, steps=[
        PlanStep(id="floodplains", tool="query_arcgis",
                 arguments={"dataset": "floodplains"}, depends_on=[]),
        PlanStep(id="septic", tool="query_arcgis",
                 arguments={"dataset": "septic_systems",
                            "near": "$floodplains", "distance_km": 2},
                 depends_on=[]),
    ])
    with pytest.raises(PlanValidationError):
        validate_plan(missing_dep, known_tools=TOOLS, known_datasets=DATASETS,
                      gis_result_tools={"buffer", "intersect"})


# ------------------------------------------------------------------- live ---

def _live_monkeys(monkeypatch, post_pages, count=5, get_pages=()):
    import agent.tools.data.arcgis as live

    monkeypatch.setattr(live, "_mock_enabled", lambda: False)
    monkeypatch.setattr(live, "_layer_urls",
                        lambda dataset, extra=None: ["http://x/0"])
    monkeypatch.setattr(live, "describe_layer",
                        lambda url: {"geometryType": "esriGeometryPoint"})
    calls = {"post": [], "get": []}
    get_pages = list(get_pages)

    def fake_post(url, data=None, timeout=None):
        calls["post"].append(dict(data or {}))
        if (data or {}).get("returnCountOnly") == "true":
            return _FakeResponse({"count": count})
        idx = sum(1 for c in calls["post"]
                  if c.get("returnCountOnly") != "true") - 1
        return _FakeResponse(post_pages[min(idx, len(post_pages) - 1)])

    def fake_get(url, params=None, timeout=None):
        calls["get"].append(dict(params or {}))
        if (params or {}).get("returnCountOnly") == "true":
            return _FakeResponse({"count": count})
        return _FakeResponse(get_pages.pop(0))

    monkeypatch.setattr(live.requests, "post", fake_post)
    monkeypatch.setattr(live.requests, "get", fake_get)
    return live, calls


def _point_page(ids, exceeded):
    return {
        "features": [
            {"type": "Feature", "properties": {"OBJECTID": i},
             "geometry": {"type": "Point", "coordinates": [-83.5, 41.6]}}
            for i in ids
        ],
        **({"exceededTransferLimit": True} if exceeded else {}),
    }


def test_live_pagination_pages_until_exhausted(monkeypatch):
    live, calls = _live_monkeys(
        monkeypatch, [],
        get_pages=[_point_page([1, 2, 3], True), _point_page([4, 5], False)])
    out = live.query_arcgis("septic_systems", max_features=10)
    assert out["ok"] and out["count"] == 5
    assert out["total_count"] == 5 and not out["truncated"]
    assert len(calls["post"]) == 0  # non-spatial path still GETs pages
    assert len(calls["get"]) == 3  # count + 2 pages


def test_live_near_posts_spatial_params(monkeypatch):
    live, calls = _live_monkeys(
        monkeypatch, [_point_page([3], False)], count=1)
    out = live.query_arcgis("septic_systems", max_features=100,
                            near=_near_poly(), distance_km=2)
    assert out["ok"] and out["count"] == 1
    bodies = [c for c in calls["post"] if c.get("returnCountOnly") != "true"]
    assert bodies, "spatial fetch must POST"
    body = bodies[0]
    assert body["geometryType"] == "esriGeometryPolygon"
    assert body["spatialRel"] == "esriSpatialRelIntersects"
    assert int(body["inSR"]) == 4326
    assert float(body["distance"]) == 2000.0
    assert body["units"] == "esriSRUnit_Meter"
    assert "rings" in body["geometry"]
