"""Registry, discovery, composability, and result contracts.

Proves the 120-tool surface is coherent: every tool is registered with
schema + metadata, discovery routes sensibly, $step_id chains compose across
modules, result envelopes validate, and the mock/live switch behaves.
"""

import pytest

from agent.orchestration import Orchestrator
from agent.plans import ExecutionPlan, PlanStep, validate_plan
from agent.tools.registry import build_tool_registry


def test_registry_count_and_metadata():
    reg = build_tool_registry()
    assert len(reg.names()) == 120
    for name in reg.names():
        tool = reg.get(name)
        assert tool.name == name
        assert isinstance(tool.description, str) and tool.description
        assert isinstance(tool.parameters.get("properties", {}), dict)
        assert isinstance(tool.required, list)
        meta = tool.metadata()
        for key in ("category", "requires", "network", "expensive",
                    "input_type", "output_type"):
            assert key in meta, f"{name} missing metadata '{key}'"
    # No duplicate registrations possible (register raises).
    from agent.tools import Tool

    with pytest.raises(ValueError):
        reg.register(Tool("buffer", "dup", {}, lambda: {}))


def test_category_coverage():
    from collections import Counter

    reg = build_tool_registry()
    counts = Counter(reg.get(n).category for n in reg.names())
    for category in ("data", "geometry", "gis", "analysis", "network",
                     "raster", "sensing", "environmental", "visualization",
                     "knowledge", "utility", "discovery"):
        assert counts[category] >= 2, f"thin category: {category}"


def test_discovery_routes():
    reg = build_tool_registry()
    found = reg.run("search_tools", {"query": "buffer floodplain"})
    assert found["ok"] and any(r["name"] == "buffer" for r in found["rows"])
    listed = reg.run("discover_tools", {"category": "network"})
    assert listed["ok"] and listed["row_count"] >= 5
    meta = reg.run("get_tool_metadata", {"name": "service_area"})
    assert meta["ok"] and meta["tool"]["category"] == "network"
    assert meta["tool"]["units"] == "minutes"
    with pytest.raises(Exception):
        from agent.tools.discovery import get_tool_metadata

        get_tool_metadata("teleport")
    with pytest.raises(Exception):
        from agent.tools.discovery import discover_tools

        discover_tools("astrology")


def test_unknown_tool_fails_structurally():
    reg = build_tool_registry()
    out = reg.run("nope", {})
    assert out["ok"] is False and "unknown tool" in out["error"]


def test_cross_module_chain_with_refs(points, poly):
    """create_bbox → buffer → intersect → count → style → map, all by $refs."""
    from agent.tools.registry import build_tool_registry as build

    orch = Orchestrator(build())
    # Dangling references fail at runtime with recorded errors.
    bad = ExecutionPlan(goal="bad", steps=[
        PlanStep(id="hit", tool="intersect",
                 arguments={"input_a": "$ghost", "input_b": "$box"},
                 depends_on=[]),
        PlanStep(id="box", tool="create_bbox",
                 arguments={"west": -83.7, "south": 41.5, "east": -83.4,
                            "north": 41.7}, depends_on=[]),
    ])
    resp = orch.execute(bad, query_id="q_bad")
    # Partial success by design (box layer lands), but the dangling $ghost
    # reference is recorded as a step error.
    assert any("ghost" in e.get("error", "") for e in resp["execution"]["errors"])

    plan2 = ExecutionPlan(goal="chain2", steps=[
        PlanStep(id="box", tool="create_bbox",
                 arguments={"west": -83.7, "south": 41.5, "east": -83.4,
                            "north": 41.7}, depends_on=[]),
        PlanStep(id="buf", tool="buffer",
                 arguments={"input": "$box", "distance": 1000, "unit": "meters"},
                 depends_on=["box"]),
        PlanStep(id="hit", tool="intersect",
                 arguments={"input_a": "$buf", "input_b": "$box"},
                 depends_on=["buf", "box"]),
        PlanStep(id="n", tool="count_features",
                 arguments={"input": "$hit"}, depends_on=["hit"]),
        PlanStep(id="styled", tool="style_layer",
                 arguments={"input": "$hit", "fill_color": "#d03b3b"},
                 depends_on=["hit"]),
        PlanStep(id="map", tool="create_map_result",
                 arguments={"layers": ["$hit", "$styled"]}, depends_on=["hit", "styled"]),
    ])
    resp2 = orch.execute(plan2, query_id="q_chain")
    assert resp2["status"] == "completed"
    assert resp2["count"] >= 1
    assert any("style" in layer for layer in resp2["results"])


def test_map_and_download_aggregation(points):
    orch = Orchestrator(build_tool_registry())
    plan = ExecutionPlan(goal="dl", steps=[
        PlanStep(id="pts", tool="create_bbox",
                 arguments={"west": -83.7, "south": 41.5, "east": -83.4,
                            "north": 41.7}, depends_on=[]),
        PlanStep(id="dl", tool="export_geojson",
                 arguments={"input": "$pts"}, depends_on=["pts"]),
    ])
    resp = orch.execute(plan, query_id="q_dl")
    assert resp["status"] == "completed"
    assert resp["downloads"][0]["mime"] == "application/geo+json"
    assert '"FeatureCollection"' in resp["downloads"][0]["content"]


def test_mock_flag_survives_new_tools():
    from agent.tools.data.arcgis import query_arcgis

    out = query_arcgis("septic_systems")
    assert out.get("mocked") is True
    assert out.get("provisional_schema") is True
    assert out.get("live_urls")


def test_result_envelopes(points, poly):
    from agent.tools.geometry import vector as V

    fc = V.union(poly)
    assert fc["ok"] and fc["type"] == "FeatureCollection"
    assert fc["crs"] == "EPSG:4326" and isinstance(fc["count"], int)
    from agent.tools.analysis import aggregation as A

    tbl = A.count_features(points)
    assert tbl["ok"] and tbl["type"] == "table"
    assert isinstance(tbl["columns"], list) and isinstance(tbl["rows"], list)
