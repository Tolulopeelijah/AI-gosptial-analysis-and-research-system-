"""Core test suite: plans, GIS correctness, tools, orchestration, end-to-end."""

from __future__ import annotations

import json
import math

import pytest

from agent.orchestration import Orchestrator
from agent.plans import ExecutionPlan, PlanStep, PlanValidationError, topo_order, validate_plan
from agent.results import ResultStore
from agent.tools import Tool
from agent.tools.gis.operations import buffer, intersect, nearest


TOOLS = {"query_arcgis", "query_maumee", "buffer", "intersect", "nearest",
         "search_knowledge_base", "list_datasets", "describe_dataset"}
DATASETS = {"septic_systems", "floodplains", "maumee_water_quality"}

POINTS = {
    "type": "FeatureCollection",
    "crs": "EPSG:4326",
    "features": [
        {"type": "Feature", "properties": {"id": 1},
         "geometry": {"type": "Point", "coordinates": [-83.70, 41.60]}},
        {"type": "Feature", "properties": {"id": 2},
         "geometry": {"type": "Point", "coordinates": [-83.00, 41.00]}},
    ],
}
POLY = {
    "type": "FeatureCollection",
    "crs": "EPSG:4326",
    "features": [
        {"type": "Feature", "properties": {"id": "fp"},
         "geometry": {"type": "Polygon", "coordinates": [[
             [-83.72, 41.58], [-83.68, 41.58],
             [-83.68, 41.62], [-83.72, 41.62], [-83.72, 41.58]]]}},
    ],
}


# ------------------------------------------------------------ plans ---

def _plan(*steps) -> ExecutionPlan:
    return ExecutionPlan(goal="test", steps=list(steps))


def test_validate_ok_and_topo_levels():
    plan = _plan(
        PlanStep(id="a", tool="query_arcgis", arguments={"dataset": "floodplains"}, depends_on=[]),
        PlanStep(id="b", tool="query_arcgis", arguments={"dataset": "septic_systems"}, depends_on=[]),
        PlanStep(id="c", tool="intersect", arguments={"input_a": "$a", "input_b": "$b"}, depends_on=["a", "b"]),
    )
    validate_plan(plan, known_tools=TOOLS, known_datasets=DATASETS,
                  gis_result_tools={"buffer", "intersect", "nearest"})
    levels = topo_order(plan)
    assert len(levels) == 2 and len(levels[0]) == 2


def test_validate_rejects_unknown_tool():
    plan = _plan(PlanStep(id="a", tool="teleport", arguments={}, depends_on=[]))
    with pytest.raises(PlanValidationError):
        validate_plan(plan, known_tools=TOOLS)


def test_validate_rejects_unknown_dataset():
    plan = _plan(PlanStep(id="a", tool="query_arcgis",
                          arguments={"dataset": "hospitals"}, depends_on=[]))
    with pytest.raises(PlanValidationError):
        validate_plan(plan, known_tools=TOOLS, known_datasets=DATASETS)


def test_validate_rejects_cycle():
    plan = _plan(
        PlanStep(id="a", tool="buffer", arguments={"input": "$b", "distance": 5}, depends_on=["b"]),
        PlanStep(id="b", tool="buffer", arguments={"input": "$a", "distance": 5}, depends_on=["a"]),
    )
    with pytest.raises(PlanValidationError):
        validate_plan(plan, known_tools=TOOLS)


def test_validate_rejects_dangling_dep():
    plan = _plan(PlanStep(id="a", tool="buffer",
                          arguments={"input": "$ghost", "distance": 5}, depends_on=["ghost"]))
    with pytest.raises(PlanValidationError):
        validate_plan(plan, known_tools=TOOLS)


def test_result_store_missing_ref():
    store = ResultStore()
    with pytest.raises(KeyError):
        store.get("$nope")


# --------------------------------------------------------------- GIS ---

def test_buffer_area_approximately_pi_r_squared():
    fc = {"type": "FeatureCollection", "crs": "EPSG:4326", "features": [POINTS["features"][0]]}
    out = buffer(fc, 2000, "meters")
    assert out["ok"] and out["count"] == 1
    from shapely.geometry import shape

    g = shape(out["features"][0]["geometry"])
    # area in degrees is meaningless; reproject check via bounding size instead:
    # buffered polygon must strictly contain the point + span ~4km in metric CRS
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shp_transform

    t = Transformer.from_crs(CRS("EPSG:4326"), CRS("EPSG:32617"), always_xy=True)
    gm = shp_transform(t.transform, g)
    assert abs(gm.area - math.pi * 2000**2) / (math.pi * 2000**2) < 0.02


def test_buffer_rejects_bad_unit_and_distance():
    assert not buffer(POINTS, -5)["ok"]
    assert not buffer(POINTS, 5, unit="lightyears")["ok"]


def test_intersect_keeps_only_overlapping():
    out = intersect(POINTS, POLY)
    assert out["ok"]
    assert out["count"] == 1
    assert out["features"][0]["properties"]["id"] == 1


def test_intersect_empty_input_side():
    empty = {"type": "FeatureCollection", "features": []}
    out = intersect(empty, POLY)
    assert out["ok"] and out["count"] == 0


def test_intersect_crs_mismatch_auto_handled():
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shp_transform
    from shapely.geometry import mapping

    t = Transformer.from_crs(CRS("EPSG:4326"), CRS("EPSG:3857"), always_xy=True)
    web = {"type": "FeatureCollection", "crs": "EPSG:3857", "features": [
        {"type": "Feature", "properties": {"id": "fp"},
         "geometry": mapping(shp_transform(
             t.transform,
             __import__("shapely.geometry", fromlist=["shape"]).shape(
                 POLY["features"][0]["geometry"])))}]}
    out = intersect(POINTS, web)
    assert out["ok"] and out["count"] == 1
    assert "reprojected" in out["note"]


def test_nearest_distances_metric():
    out = nearest(POINTS, POLY, k=1)
    assert out["ok"] and out["row_count"] == 2
    assert out["rows"][0]["distance_km"] == pytest.approx(0.0, abs=0.01)
    assert out["rows"][1]["distance_km"] > 50


# --------------------------------------------------------- data tools ---

def test_xlsx_schema_real_file():
    from agent.tools.data.xlsx import query_maumee

    out = query_maumee(operation="schema")
    assert out["ok"] and out["row_count"] > 22000
    assert "DateTime" in out["columns"]
    assert "TP" in out["parameters"]


def test_xlsx_summary_tp():
    from agent.tools.data.xlsx import query_maumee

    out = query_maumee(parameter="TP", operation="summary")
    assert out["ok"]
    row = next(r for r in out["rows"] if "TP" in r["column"])
    assert row["n"] > 20000 and row["mean"] > 0


def test_xlsx_bad_parameter():
    from agent.tools.data.xlsx import query_maumee

    with pytest.raises(ValueError):
        query_maumee(parameter="XYZ")


def test_arcgis_mock_mode_returns_flagged_fixture():
    from agent.config import settings
    from agent.tools.data.arcgis import query_arcgis

    out = query_arcgis("septic_systems")
    if settings.ARCGIS_USE_MOCK:
        assert out["ok"] and out.get("mocked") is True
        assert out.get("provisional_schema") is True
        assert out["live_urls"], "mock must retain the real URL for later switch"
        assert out["type"] == "FeatureCollection" and out["count"] > 0
    elif not out.get("ok"):
        assert out.get("code") == "data_unavailable"


def test_mock_fixtures_are_valid_geojson_with_expected_geometry():
    from agent.tools.data.arcgis_mock import floodplain_fixture, septic_fixture

    septic = septic_fixture()
    flood = floodplain_fixture()
    assert septic and all(f["geometry"]["type"] == "Point" for f in septic)
    assert flood and all(f["geometry"]["type"] == "Polygon" for f in flood)
    assert all("OBJECTID" in f["properties"] for f in septic + flood)
    # fixtures overlap so the intersect demo is meaningful
    from shapely.geometry import shape

    poly_union = shape(flood[0]["geometry"])
    inside = sum(1 for f in septic if shape(f["geometry"]).intersects(poly_union))
    assert inside >= 1


def test_mock_bbox_and_objectid_filter():
    from agent.tools.data.arcgis import query_arcgis

    from agent.config import settings

    if not settings.ARCGIS_USE_MOCK:
        pytest.skip("mock mode disabled")
    west_only = query_arcgis("septic_systems", bbox="-84.0,41.0,-83.7,42.0")
    assert west_only["ok"] and west_only["count"] < 10
    one = query_arcgis("septic_systems", where="OBJECTID = 3")
    assert one["ok"] and one["count"] == 1
    bad = query_arcgis("septic_systems", bbox="nonsense")
    assert not bad["ok"]


def test_registry_marks_mock_backed_datasets():
    from agent.config import settings
    from agent.registry import build_registry

    reg = build_registry()
    if settings.ARCGIS_USE_MOCK:
        assert reg["septic_systems"].available
        assert reg["floodplains"].available
        assert reg["septic_systems"].extra["mock_backed"] is True
        assert "LCHD_SEPTIC" in reg["septic_systems"].extra["live_urls"][0]


def test_knowledge_index_contains_real_doi_entries():
    from agent.tools.knowledge.retrieval import search_knowledge_base

    out = search_knowledge_base("Maumee phosphorus flood nutrient loads")
    assert out["ok"] and out["count"] >= 1
    assert any("doi.org" in (h.get("url") or "") for h in out["hits"])
    assert out["full_text_available"] is True


def test_knowledge_search_returns_provenance():
    from agent.tools.knowledge.retrieval import search_knowledge_base

    out = search_knowledge_base("phosphorus Maumee total phosphorus")
    assert out["ok"] and out["count"] >= 1
    hit = out["hits"][0]
    assert hit["identifier"] and hit["source"]


# ------------------------------------------------------ orchestration ---
def _stub_registry():
    from agent.tools.registry import build_tool_registry

    reg = build_tool_registry()
    # Override network tools with deterministic fixtures.
    reg._tools["query_arcgis"] = Tool(
        "query_arcgis", "stub", {"properties": {}},
        lambda dataset, **kw: {"ok": True, "type": "FeatureCollection",
                               "features": (POLY if dataset == "floodplains" else POINTS)["features"],
                               "count": 2 if dataset == "septic_systems" else 1,
                               "dataset": dataset},
        category="data")
    return reg


def test_orchestrator_multistep_with_refs():
    orch = Orchestrator(_stub_registry())
    plan = _plan(
        PlanStep(id="septic", tool="query_arcgis", arguments={"dataset": "septic_systems"}, depends_on=[]),
        PlanStep(id="floodplains", tool="query_arcgis", arguments={"dataset": "floodplains"}, depends_on=[]),
        PlanStep(id="buffer", tool="buffer",
                 arguments={"input": "$floodplains", "distance": 2000, "unit": "meters"},
                 depends_on=["floodplains"]),
        PlanStep(id="result", tool="intersect",
                 arguments={"input_a": "$septic", "input_b": "$buffer"},
                 depends_on=["septic", "buffer"]),
    )
    resp = orch.execute(plan, query_id="q_test")
    assert resp["status"] == "completed"
    assert resp["count"] == 1  # only the nearby septic point survives
    assert resp["execution"]["tool_calls"] and not resp["execution"]["errors"]


def test_orchestrator_missing_ref_records_error():
    orch = Orchestrator(_stub_registry())
    plan = _plan(
        PlanStep(id="result", tool="intersect",
                 arguments={"input_a": "$ghost", "input_b": "$ghost2"},
                 depends_on=[]),
    )
    # bypass validator's gis-input rule by giving real deps shape; validator
    # would reject, so call execute directly to test runtime resilience
    resp = orch.execute(plan, query_id="q_test2")
    assert resp["status"] == "failed"
    assert resp["execution"]["errors"]


# ---------------------------------------------------------- end to end ---
# NOTE: these pin RulePlanner for determinism (no live-model flakiness).
# The live OpenAI planner loop is verified via demos/run_demo.py instead.

def _ruled_agent():
    from agent.agent import GeospatialAgent
    from agent.planner import RulePlanner

    agent = GeospatialAgent()
    agent.planner = RulePlanner()
    return agent


def test_e2e_maumee_summary_no_llm_needed():
    agent = _ruled_agent()
    resp = agent.ask("Summarize total phosphorus (TP) in the Maumee dataset")
    assert resp["status"] == "completed"
    assert "maumee" in resp.get("dataset", "").lower() or "TP" in resp.get("explanation", "")


def test_e2e_knowledge_query():
    agent = _ruled_agent()
    resp = agent.ask("What NCWQR publications discuss phosphorus implications?")
    assert resp["status"] == "completed"
    assert resp.get("sources")


def test_e2e_unsupported_dataset_honest():
    agent = _ruled_agent()
    resp = agent.ask("Show hospitals in this area")
    assert resp["status"] == "failed"
    assert resp["error"]["code"] == "invalid_geographic_query"
    assert "hospital" in resp["error"]["message"].lower()


def test_e2e_empty_query():
    from agent.agent import GeospatialAgent

    agent = GeospatialAgent()
    resp = agent.ask("   ")
    assert resp["status"] == "failed"


# ------------------------------------------------------------ grounding ---

def test_grounding_extract_and_check():
    from agent.grounding import check_markers, extract_markers

    assert extract_markers("Phosphorus rose [S1] while flow fell [S2][S1].") == ["S1", "S2"]
    check = check_markers("Claim [S1] and bogus [S9].", {"S1", "S2"})
    assert check["cited"] == ["S1"] and check["invalid"] == ["S9"]
    assert check_markers("No markers here.", {"S1"}) == {"cited": [], "invalid": []}


def test_grounding_strips_hallucinated_markers():
    from agent.grounding import strip_invalid_markers

    cleaned, removed = strip_invalid_markers("Real [S1], fake [S7].", {"S1"})
    assert "[S7]" not in cleaned and "[S1]" in cleaned and removed == 1


def test_knowledge_hits_carry_refs():
    from agent.tools.knowledge.retrieval import search_knowledge_base

    out = search_knowledge_base("Maumee phosphorus")
    assert out["ok"] and out["hits"]
    refs = [h["ref"] for h in out["hits"]]
    assert refs == [f"S{i}" for i in range(1, len(refs) + 1)]


def test_e2e_knowledge_response_has_references():
    agent = _ruled_agent()
    resp = agent.ask("What NCWQR publications discuss phosphorus implications?")
    assert resp["status"] == "completed"
    refs = resp.get("references") or []
    assert refs, "knowledge answers must carry structured references"
    assert all(r.get("ref", "").startswith("S") for r in refs)
    assert all(r.get("identifier") for r in refs)
