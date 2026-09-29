"""Climate and weather via the Open-Meteo API (no key required).

Provider adapter: all three tools share one request core against
api.open-meteo.com. `current_weather` and `daily_weather` fetch; 
`climate_statistics` composes over a daily_weather table, so statistics stay
testable offline. Units are metric unless requested otherwise.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import CapabilityError, ToolError, table

BASE_URL = "https://api.open-meteo.com/v1/forecast"


def _coords(lat: float, lon: float):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ToolError("lat/lon must be numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ToolError("coordinates out of range")
    return lat, lon


def _fetch(params: Dict[str, Any]) -> Dict[str, Any]:
    from ..common import http_get

    resp = http_get(BASE_URL, params=params, timeout=40)
    try:
        return resp.json()
    except Exception as exc:
        raise CapabilityError(f"Open-Meteo returned non-JSON: {exc}") from exc


def current_weather(lat: float, lon: float, temperature_unit: str = "celsius"):
    """Current temperature, humidity, precipitation, wind, weather code."""
    if temperature_unit not in ("celsius", "fahrenheit"):
        raise ToolError("temperature_unit must be celsius|fahrenheit")
    lat, lon = _coords(lat, lon)
    doc = _fetch({"latitude": lat, "longitude": lon,
                  "current": "temperature_2m,relative_humidity_2m,precipitation,"
                             "weather_code,wind_speed_10m",
                  "temperature_unit": temperature_unit,
                  "timezone": "auto"})
    cur = doc.get("current", {}) or {}
    if not cur:
        raise CapabilityError("no current weather in provider response")
    return table(["metric", "value", "unit"],
                 [{"metric": "temperature", "value": cur.get("temperature_2m"),
                   "unit": "°C" if temperature_unit == "celsius" else "°F"},
                  {"metric": "humidity_pct",
                   "value": cur.get("relative_humidity_2m"), "unit": "%"},
                  {"metric": "precipitation_mm",
                   "value": cur.get("precipitation"), "unit": "mm"},
                  {"metric": "wind_speed_kmh",
                   "value": cur.get("wind_speed_10m"), "unit": "km/h"},
                  {"metric": "weather_code", "value": cur.get("weather_code"),
                   "unit": "wmo"},
                  {"metric": "observed_at", "value": cur.get("time"),
                   "unit": "iso"}],
                 lat=lat, lon=lon, service="open-meteo")


def daily_weather(lat: float, lon: float, start: str, end: str,
                  temperature_unit: str = "celsius"):
    """Daily max/min temperature, precipitation sum, max wind for a date range
    (past ~3 months through +16 day forecast)."""
    from datetime import date

    if temperature_unit not in ("celsius", "fahrenheit"):
        raise ToolError("temperature_unit must be celsius|fahrenheit")
    lat, lon = _coords(lat, lon)
    try:
        assert date.fromisoformat(start) <= date.fromisoformat(end)
    except (ValueError, AssertionError):
        raise ToolError("start/end must be ISO dates with start <= end")
    doc = _fetch({"latitude": lat, "longitude": lon, "start_date": start,
                  "end_date": end, "temperature_unit": temperature_unit,
                  "daily": "temperature_2m_max,temperature_2m_min,"
                           "precipitation_sum,wind_speed_10m_max",
                  "timezone": "auto"})
    daily = doc.get("daily", {}) or {}
    dates = daily.get("time", []) or []
    rows = []
    for i, day in enumerate(dates):
        def at(key):
            vals = daily.get(key, []) or []
            return vals[i] if i < len(vals) else None

        rows.append({"date": day,
                     "temp_max": at("temperature_2m_max"),
                     "temp_min": at("temperature_2m_min"),
                     "precip_mm": at("precipitation_sum"),
                     "wind_max_kmh": at("wind_speed_10m_max")})
    return table(["date", "temp_max", "temp_min", "precip_mm", "wind_max_kmh"],
                 rows, row_count=len(rows), lat=lat, lon=lon,
                 temperature_unit=temperature_unit, service="open-meteo")


def climate_statistics(input: Dict[str, Any]):
    """Aggregate a daily_weather table: means/totals over the period."""
    rows = input.get("rows", []) if isinstance(input, dict) else []
    if not rows or "temp_max" not in (rows[0] or {}):
        raise ToolError("climate_statistics needs a daily_weather table")
    import statistics as _stats

    def col(key):
        return [r[key] for r in rows
                if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]

    tmax, tmin = col("temp_max"), col("temp_min")
    precip = col("precip_mm")
    out = [
        {"metric": "days", "value": len(rows)},
        {"metric": "mean_temp_max",
         "value": round(_stats.mean(tmax), 2) if tmax else None},
        {"metric": "mean_temp_min",
         "value": round(_stats.mean(tmin), 2) if tmin else None},
        {"metric": "total_precip_mm",
         "value": round(sum(precip), 2) if precip else None},
        {"metric": "wet_days",
         "value": sum(1 for v in precip if v and v > 0.2)},
    ]
    return table(["metric", "value"], out,
                 period=f"{rows[0].get('date')}..{rows[-1].get('date')}")


CLIMATE_SCHEMAS = {
    "current_weather": ({"properties": {
        "lat": {"type": "number"}, "lon": {"type": "number"},
        "temperature_unit": {"type": "string",
                             "description": "celsius (default) or fahrenheit."}}},
        ["lat", "lon"]),
    "daily_weather": ({"properties": {
        "lat": {"type": "number"}, "lon": {"type": "number"},
        "start": {"type": "string", "description": "ISO date."},
        "end": {"type": "string", "description": "ISO date."},
        "temperature_unit": {"type": "string"}}}, ["lat", "lon", "start", "end"]),
    "climate_statistics": ({"properties": {
        "input": {"description": "daily_weather table reference."}}}, ["input"]),
}
