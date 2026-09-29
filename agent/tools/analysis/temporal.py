"""Temporal GIS over tables and timestamped features.

Works with any row that carries a parseable datetime — a named column, or
`DateTime` by default (the Maumee convention). Outputs are tables; periods
are ISO date strings.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import ToolError, table


def _frame(input: Dict[str, Any], time_field: str | None):
    import pandas as pd

    if input.get("type") == "table":
        rows = input.get("rows", [])
        df = pd.DataFrame(rows)
    else:
        from ..common import valid_shapes

        df = pd.DataFrame([dict(feat.get("properties", {}) or {})
                           for feat, _ in valid_shapes(input)])
    if df.empty:
        raise ToolError("no rows to analyse")
    col = time_field or next((c for c in ("DateTime", "datetime", "date", "time")
                              if c in df.columns), None)
    if col is None:
        raise ToolError("no datetime column found; pass 'time_field'")
    df = df.copy()
    df["_t"] = pd.to_datetime(df[col], errors="coerce")
    bad = int(df["_t"].isna().sum())
    df = df.dropna(subset=["_t"]).sort_values("_t")
    if df.empty:
        raise ToolError("no parseable datetimes")
    return df, col, bad


def _clean(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    import pandas as pd

    out = []
    for r in rows:
        rec = {}
        for k, v in r.items():
            if k == "_t" or pd.isna(v):
                continue
            rec[k] = str(v) if hasattr(v, "isoformat") else v
        out.append(rec)
    return out


def filter_by_date(input: Dict[str, Any], date: str, time_field: str | None = None):
    """Rows on one calendar day (ISO date)."""
    import pandas as pd

    df, col, _ = _frame(input, time_field)
    day = pd.to_datetime(date).date()
    part = df[df["_t"].dt.date == day].drop(columns=["_t"])
    return table(list(part.columns), _clean(part.to_dict(orient="records")),
                 row_count=len(part), date=str(day))


def filter_by_time_range(input: Dict[str, Any], start: str, end: str,
                         time_field: str | None = None):
    """Rows within [start, end] (ISO datetimes, inclusive)."""
    import pandas as pd

    df, col, _ = _frame(input, time_field)
    lo, hi = pd.to_datetime(start), pd.to_datetime(end)
    if lo > hi:
        raise ToolError("start must not be after end")
    part = df[(df["_t"] >= lo) & (df["_t"] <= hi)].drop(columns=["_t"])
    return table(list(part.columns), _clean(part.to_dict(orient="records")),
                 row_count=len(part), start=str(lo), end=str(hi))


def aggregate_temporal(input: Dict[str, Any], field: str, freq: str = "ME",
                       operation: str = "mean", time_field: str | None = None):
    """Resample a numeric field to monthly (ME), yearly (YE), weekly (W), or
    daily (D) buckets with an aggregation."""
    import pandas as pd

    if freq not in ("D", "W", "ME", "YE"):
        raise ToolError("freq must be D|W|ME|YE")
    if operation not in ("mean", "sum", "min", "max", "count"):
        raise ToolError("operation must be mean|sum|min|max|count")
    df, col, _ = _frame(input, time_field)
    df["_y"] = pd.to_numeric(df[field], errors="coerce")
    if df["_y"].dropna().empty:
        raise ToolError(f"no numeric values for field '{field}'")
    res = df.groupby(pd.Grouper(key="_t", freq=freq))["_y"].agg(operation)
    rows = [{"period": str(idx),
             field: None if pd.isna(v) else float(v)}
            for idx, v in res.items()]
    return table(["period", field], rows, row_count=len(rows),
                 freq=freq, operation=operation)


def temporal_statistics(input: Dict[str, Any], field: str,
                        time_field: str | None = None):
    """Overall stats plus first/last timestamps and span in days."""
    import pandas as pd

    df, col, _ = _frame(input, time_field)
    s = pd.to_numeric(df[field], errors="coerce").dropna()
    if s.empty:
        raise ToolError(f"no numeric values for field '{field}'")
    span_days = (df["_t"].max() - df["_t"].min()).total_seconds() / 86400.0
    return table(["field", "n", "mean", "min", "max", "first", "last",
                  "span_days"],
                 [{"field": field, "n": int(s.count()),
                   "mean": float(s.mean()), "min": float(s.min()),
                   "max": float(s.max()), "first": str(df["_t"].min()),
                   "last": str(df["_t"].max()), "span_days": round(span_days, 1)}])


def detect_temporal_trend(input: Dict[str, Any], field: str,
                          time_field: str | None = None):
    """Least-squares trend of a numeric field over time (slope per day,
    R², direction)."""
    import pandas as pd

    from ..common import require_module

    np = require_module("numpy", "numpy")
    df, col, _ = _frame(input, time_field)
    df = df[[col, field, "_t"]].copy()
    df["_y"] = pd.to_numeric(df[field], errors="coerce")
    df = df.dropna(subset=["_y"])
    if len(df) < 3:
        raise ToolError("trend needs at least 3 dated numeric values")
    x = (df["_t"] - df["_t"].min()).dt.total_seconds().to_numpy() / 86400.0
    y = df["_y"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return table(["field", "n", "slope_per_day", "r_squared", "direction"],
                 [{"field": field, "n": len(df),
                   "slope_per_day": float(slope), "r_squared": round(float(r2), 4),
                   "direction": "increasing" if slope > 0 else
                   "decreasing" if slope < 0 else "flat"}])


TEMPORAL_SCHEMAS = {
    "filter_by_date": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "date": {"type": "string", "description": "ISO calendar day."},
        "time_field": {"type": "string", "description": "Datetime column (auto-detected)."}}},
        ["input", "date"]),
    "filter_by_time_range": ({"properties": {
        "input": {"description": "Result reference."},
        "start": {"type": "string"}, "end": {"type": "string"},
        "time_field": {"type": "string"}}}, ["input", "start", "end"]),
    "aggregate_temporal": ({"properties": {
        "input": {"description": "Result reference."},
        "field": {"type": "string"},
        "freq": {"type": "string", "description": "D|W|ME (default)|YE."},
        "operation": {"type": "string", "description": "mean (default)|sum|min|max|count."},
        "time_field": {"type": "string"}}}, ["input", "field"]),
    "temporal_statistics": ({"properties": {
        "input": {"description": "Result reference."},
        "field": {"type": "string"}, "time_field": {"type": "string"}}},
        ["input", "field"]),
    "detect_temporal_trend": ({"properties": {
        "input": {"description": "Result reference."},
        "field": {"type": "string"}, "time_field": {"type": "string"}}},
        ["input", "field"]),
}
