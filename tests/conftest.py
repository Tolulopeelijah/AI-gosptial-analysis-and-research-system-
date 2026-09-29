"""Shared deterministic fixtures for the GIS capability tests."""

import pytest


@pytest.fixture()
def points():
    return {
        "type": "FeatureCollection",
        "crs": "EPSG:4326",
        "features": [
            {"type": "Feature", "properties": {"id": 1, "v": 10},
             "geometry": {"type": "Point", "coordinates": [-83.55, 41.60]}},
            {"type": "Feature", "properties": {"id": 2, "v": 20},
             "geometry": {"type": "Point", "coordinates": [-83.56, 41.61]}},
            {"type": "Feature", "properties": {"id": 3, "v": 30},
             "geometry": {"type": "Point", "coordinates": [-83.00, 41.00]}},
        ],
    }


@pytest.fixture()
def poly():
    return {
        "type": "FeatureCollection",
        "crs": "EPSG:4326",
        "features": [
            {"type": "Feature", "properties": {"zone": "Z"},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [-83.70, 41.50], [-83.40, 41.50], [-83.40, 41.70],
                 [-83.70, 41.70], [-83.70, 41.50]]]}},
        ],
    }


@pytest.fixture()
def small_table():
    rows = [{"DateTime": f"2020-01-0{d}", "v": d * 10} for d in range(1, 8)]
    return {"ok": True, "type": "table", "dataset": "test",
            "columns": ["DateTime", "v"], "rows": rows, "row_count": 7}


@pytest.fixture()
def lines():
    return {
        "type": "FeatureCollection",
        "crs": "EPSG:4326",
        "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString",
                          "coordinates": [[-83.70, 41.60], [-83.60, 41.60],
                                          [-83.50, 41.60]]}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString",
                          "coordinates": [[-83.60, 41.60], [-83.60, 41.65]]}},
        ],
    }


class FakeResponse:
    """Minimal requests.Response stand-in for provider tests."""

    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
