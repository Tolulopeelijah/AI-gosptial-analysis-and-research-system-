"""Data access: registry tools, filters, uploads, and provider parsing.

Live network calls are never made here: provider responses are faked at the
transport boundary (monkeypatched), so these tests prove request building,
validation, and response parsing — the honest offline-testable surface.
"""

import pytest

from agent.tools.data import datasets as D
from tests.conftest import FakeResponse


def test_search_and_schema():
    hits = D.search_datasets("flood")
    assert hits["count"] >= 1
    assert hits["hits"][0]["dataset"] == "floodplains"
    with pytest.raises(Exception):
        D.search_datasets("  ")
    schema = D.get_dataset_schema("maumee_water_quality")
    assert any(f["name"].startswith("Value [TP]") for f in schema["fields"])
    with pytest.raises(Exception):
        D.get_dataset_schema("nope")


def test_extent_and_download_mock():
    extent = D.get_dataset_extent("maumee_water_quality")
    assert extent["temporal"][0].startswith("1975")
    assert extent["spatial"] is None
    dl = D.download_dataset("septic_systems")
    assert dl["ok"] and dl["download"] is True
    assert dl["mocked"] is True
    with pytest.raises(Exception):
        D.download_dataset("maumee_water_quality")


def test_filter_and_sample(points):
    kept = D.filter_features(points, "v > 15")
    assert kept["count"] == 2
    kept = D.filter_features(points, "id = 1 AND v >= 10")
    assert kept["count"] == 1
    kept = D.filter_features(points, "zone LIKE '%x%'")
    assert kept["count"] == 0
    with pytest.raises(Exception):
        D.filter_features(points, "not a filter;;;")
    sample = D.sample_features(points, n=2, seed=7)
    assert sample["count"] == 2
    again = D.sample_features(points, n=2, seed=7)
    assert [f["properties"]["id"] for f in sample["features"]] == \
        [f["properties"]["id"] for f in again["features"]]


def test_geocode_validation_and_parsing(monkeypatch):
    from agent.tools.data import geocoding as G

    with pytest.raises(Exception):
        G.geocode("   ")
    with pytest.raises(Exception):
        G.reverse_geocode(999, 0)

    payload = [{"display_name": "Toledo, Ohio, USA", "lat": "41.65",
                "lon": "-83.53", "type": "city", "class": "place",
                "osm_type": "node", "osm_id": 1,
                "address": {"city": "Toledo", "state": "Ohio",
                            "country": "United States"}}]
    reverse_doc = {"display_name": "Toledo, Ohio, USA", "type": "city",
                   "class": "place", "osm_type": "node", "osm_id": 1,
                   "address": {"city": "Toledo", "state": "Ohio",
                               "country": "United States"}}

    def fake_geocoder(url, params=None, **kwargs):
        if "/reverse" in str(url):
            return FakeResponse(reverse_doc)
        return FakeResponse(payload)

    monkeypatch.setattr("agent.tools.data.geocoding.http_get", fake_geocoder)
    res = G.geocode("Toledo")
    assert res["count"] == 1
    assert res["features"][0]["geometry"]["coordinates"] == [-83.53, 41.65]
    assert res["features"][0]["properties"]["city"] == "Toledo"
    resolved = G.resolve_location("41.65, -83.53")
    assert resolved["resolved_as"] == "coordinates"


def test_overpass_parsing(monkeypatch, points):
    from agent.tools.data import osm as O

    doc = {"elements": [
        {"type": "node", "id": 1, "lat": 41.6, "lon": -83.55,
         "tags": {"amenity": "hospital", "name": "St. Test"}},
        {"type": "way", "id": 2,
         "center": {"lat": 41.61, "lon": -83.56},
         "tags": {"highway": "residential"}}]}
    monkeypatch.setattr("agent.tools.common.http_get",
                        lambda *a, **k: FakeResponse(doc))
    pois = O.query_osm_pois("-83.7,41.5,-83.4,41.7")
    assert pois["count"] == 2
    assert pois["features"][0]["properties"]["tag:amenity"] == "hospital"
    with pytest.raises(Exception):
        O.query_osm_pois("nonsense")
    with pytest.raises(Exception):
        O.query_osm_roads("-83.7,41.5,-83.4,41.7", road_class="hyperloop")


def test_boundaries_parsing(monkeypatch):
    from agent.tools.data import boundaries as B

    poly = {"type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    payload = [{"display_name": "Lucas County, Ohio", "type": "county",
                "class": "boundary", "osm_id": 9, "geojson": poly,
                "address": {"county": "Lucas County", "state": "Ohio",
                            "country": "United States"}}]
    monkeypatch.setattr("agent.tools.data.boundaries.http_get",
                        lambda *a, **k: FakeResponse(payload))
    res = B.get_admin_boundary("Lucas County, Ohio")
    assert res["count"] == 1
    assert res["features"][0]["geometry"]["type"] == "Polygon"
    hier = B.get_admin_hierarchy("Lucas County")
    assert [r["level"] for r in hier["rows"]] == ["country", "state", "county"]
    with pytest.raises(Exception):
        B.get_admin_boundary("")


def test_wfs_and_wms_validation(monkeypatch):
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"a": 1},
         "geometry": {"type": "Point", "coordinates": [0, 0]}}]}
    monkeypatch.setattr("agent.tools.data.datasets.http_get",
                        lambda *a, **k: FakeResponse(doc))
    res = D.query_wfs("https://example.com/wfs", "test:layer")
    assert res["count"] == 1 and res["service"] == "WFS"
    caps = "<WMS_Capabilities><Layer><Name>flood</Name></Layer></WMS_Capabilities>"
    monkeypatch.setattr("agent.tools.data.datasets.http_get",
                        lambda *a, **k: FakeResponse(text=caps))
    url = D.wms_getmap("https://example.com/wms", "flood",
                       "-83.7,41.5,-83.4,41.7")
    assert url["map_url"].startswith("https://example.com/wms?")
    assert "layers=flood" in url["map_url"]
    with pytest.raises(Exception):
        D.wms_getmap("https://example.com/wms", "missing",
                     "-83.7,41.5,-83.4,41.7")
