"""Network, raster, sensing, climate, ecology, maps, knowledge, discovery.

Network and raster run fully offline on synthetic fixtures. Provider-backed
tools (STAC, weather, GBIF) are tested at the transport boundary with faked
responses; capability-error paths are tested for missing optionals.
"""

import json

import pytest

from agent.tools.network import network as N
from tests.conftest import FakeResponse


def test_network_full_flow(lines):
    net = N.build_network(lines)
    assert net["node_count"] == 4 and net["edge_count"] == 3
    assert net["units"] == "metres"
    path = N.shortest_path(net, -83.70, 41.60, -83.60, 41.65)
    assert path["count"] == 1
    assert 13000 < path["features"][0]["properties"]["length_m"] < 15000
    timing = N.travel_time(path, 30)
    assert timing["rows"][0]["minutes"] == pytest.approx(27.8, abs=0.5)
    area = N.service_area(net, -83.60, 41.60, 20, 40)
    assert area["features"][0]["properties"]["nodes_reached"] == 4
    small = N.service_area(net, -83.60, 41.60, 1, 40)
    assert small["count"] == 0  # budget too small: honest empty
    top = N.betweenness_centrality(net, 2)["rows"]
    assert top[0]["lon"] == pytest.approx(-83.6)
    with pytest.raises(Exception):
        N.build_network({"type": "FeatureCollection", "features": []})
    with pytest.raises(Exception):
        N.travel_time(path, 0)


def _dem(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    arr = (np.arange(10000, dtype="float64").reshape(100, 100) % 50)
    path = str(tmp_path / "dem.tif")
    with rasterio.open(path, "w", driver="GTiff", height=100, width=100,
                       count=1, dtype="float64", crs="EPSG:26917",
                       transform=from_origin(300000, 4650000, 30, 30)) as dst:
        dst.write(arr, 1)
    twin = str(tmp_path / "nir.tif")
    with rasterio.open(path) as src:
        meta = src.meta.copy()
    with rasterio.open(twin, "w", **meta) as dst:
        dst.write(arr * 2, 1)
    return path, twin


def test_raster_chain(tmp_path):
    from agent.tools.raster import raster as R

    dem, nir = _dem(tmp_path)
    assert R.load_raster(dem)["bands"] == 1
    stats = R.raster_statistics(dem)["rows"][0]
    assert stats["min"] == 0.0 and stats["max"] == 49.0
    assert stats["mean"] == pytest.approx(24.5)
    clipped = R.clip_raster(dem, "300000,4648500,301000,4649500")
    assert clipped["width"] < 100
    half = R.resample_raster(dem, 0.5)
    assert half["width"] == 50
    ndvi = R.raster_calculator(dem, "(a - b) / (a + b)", input_b=nir)
    assert ndvi["bands"] == 1
    zones = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {},
         "geometry": {"type": "Polygon", "coordinates": [[
             [300000, 4648000], [302000, 4648000], [302000, 4650000],
             [300000, 4650000], [300000, 4648000]]]}}]}
    zonal = R.zonal_statistics(dem, zones, "mean")
    assert zonal["rows"][0]["pixels"] > 0
    recl = R.raster_reclassify(dem, "0-10:1;10-*:2")
    assert recl["classes"] == [1.0, 2.0]
    slope = R.raster_slope(dem)
    assert slope["units"] == "degrees"
    with pytest.raises(Exception):
        R.raster_calculator(dem, "__import__('os').system('x')")
    with pytest.raises(Exception):
        R.raster_calculator(dem, "c + 1")
    with pytest.raises(Exception):
        R.clip_raster(dem, "-83.7,41.5,-83.4,41.7")  # CRS guard


def test_sensing_indices(tmp_path):
    from agent.tools.remote_sensing import sensing as S
    from agent.tools.raster import raster as R

    dem, nir = _dem(tmp_path)
    ndvi = S.calculate_ndvi(nir, dem)
    assert ndvi["index"] == "NDVI" and ndvi["range"] == "[-1, 1]"
    vals = R.raster_statistics(ndvi)["rows"][0]
    assert -1.0 <= vals["min"] <= vals["max"] <= 1.0
    assert S.calculate_ndwi(nir, dem)["index"] == "NDWI"
    assert S.calculate_ndbi(nir, dem)["index"] == "NDBI"
    with pytest.raises(Exception):
        S.stac_search("nonsense", "2024-01-01", "2024-02-01")
    with pytest.raises(Exception):
        S.stac_search("-83.7,41.5,-83.4,41.7", "2024-02-01", "2024-01-01")


def test_stac_parsing(monkeypatch):
    import requests

    from agent.tools.remote_sensing import sensing as S

    doc = {"features": [{"id": "S2A_1",
                         "properties": {"datetime": "2024-06-01T00:00:00Z",
                                        "eo:cloud_cover": 5.0},
                         "assets": {"red": {"href": "https://example.com/red.tif"},
                                    "nir": {"href": "https://example.com/nir.tif"}}}]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(doc))
    res = S.stac_search("-83.7,41.5,-83.4,41.7", "2024-06-01", "2024-06-30")
    assert res["count"] == 1
    assert res["items"][0]["asset_hrefs"]["red"].endswith("red.tif")


def test_climate_offline_and_parsing(monkeypatch):
    from agent.tools.environmental import climate as C

    doc = {"daily": {"time": ["2024-06-01", "2024-06-02"],
                     "temperature_2m_max": [25.0, 27.0],
                     "temperature_2m_min": [15.0, 16.0],
                     "precipitation_sum": [0.0, 5.0],
                     "wind_speed_10m_max": [10.0, 12.0]}}
    monkeypatch.setattr("agent.tools.common.http_get",
                        lambda *a, **k: FakeResponse(doc))
    daily = C.daily_weather(41.65, -83.53, "2024-06-01", "2024-06-02")
    assert daily["row_count"] == 2
    stats = C.climate_statistics(daily)
    by_metric = {r["metric"]: r["value"] for r in stats["rows"]}
    assert by_metric["mean_temp_max"] == 26.0
    assert by_metric["total_precip_mm"] == 5.0
    assert by_metric["wet_days"] == 1
    with pytest.raises(Exception):
        C.daily_weather(41.65, -83.53, "2024-06-02", "2024-06-01")
    # The faked transport returns a daily doc with no "current" member:
    # current_weather must fail structurally, never with KeyError/None math.
    with pytest.raises(Exception):
        C.current_weather(41.65, -83.53)


def test_ecology_offline(monkeypatch):
    from agent.tools.environmental import ecology as E

    match = {"scientificName": "Quercus alba", "usageKey": 123,
             "rank": "SPECIES", "status": "ACCEPTED", "matchType": "EXACT"}
    occ = {"count": 2, "results": [
        {"decimalLongitude": -83.5, "decimalLatitude": 41.6,
         "scientificName": "Quercus alba", "taxonKey": 123,
         "basisOfRecord": "OBSERVATION", "year": 2020,
         "country": "US", "key": 1},
        {"decimalLongitude": -83.6, "decimalLatitude": 41.61,
         "scientificName": "Acer rubrum", "taxonKey": 124,
         "basisOfRecord": "OBSERVATION", "year": 2021,
         "country": "US", "key": 2}]}
    calls = {"n": 0}

    def fake_match(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse(match)

    monkeypatch.setattr("agent.tools.common.http_get", fake_match)
    matched = E.gbif_match_species("Quercus alba")
    assert matched["rows"][0]["usageKey"] == 123
    assert calls["n"] == 1
    # Occurrences by numeric key skip matching and go straight to search.
    import agent.tools.common as common

    monkeypatch.setattr(common, "http_get", lambda *a, **k: FakeResponse(occ))
    got = E.gbif_occurrences("123", limit=10)
    assert got["count"] == 2
    rich = E.species_richness(got)
    assert rich["richness"] == 2
    assert rich["rows"][0]["records"] == 1
