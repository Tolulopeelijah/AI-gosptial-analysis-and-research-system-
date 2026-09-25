"""Controlled query interface for the local NCWQR Maumee XLSX dataset.

Verified workbook structure (inspected, not assumed):
  sheets: ["ReadMe", "Maumee_samples"]
  Maumee_samples: DateTime + 10 parameters x (Qualifiers, Value); 22,753 rows
  spanning 1975-01-10 to 2025-09-30; station-level time-series, i.e. NO
  per-row coordinates. Geographic use = station-level reference only.

The tool returns small tabular summaries (never the whole workbook).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

DEFAULT_MAX_ROWS = 200


@lru_cache(maxsize=1)
def _load_frame():
    from ...config import settings

    import pandas as pd

    path = settings.MAUMEE_XLSX_PATH
    if not path:
        raise FileNotFoundError("no Maumee XLSX file found under data/")
    df = pd.read_excel(path, sheet_name="Maumee_samples")
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    return df


def _value_col(parameter: str) -> str:
    from ...registry import MAUMEE_PARAMETERS

    codes = [p["code"] for p in MAUMEE_PARAMETERS]
    if parameter not in codes:
        raise ValueError(
            f"unknown parameter '{parameter}'; valid: {', '.join(codes)}"
        )
    matches = [c for c in _load_frame().columns if c.startswith(f"Value [{parameter}]")]
    if not matches:
        raise ValueError(f"parameter '{parameter}' has no Value column")
    return matches[0]


def query_maumee(
    parameter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    operation: str = "records",
    max_rows: int = DEFAULT_MAX_ROWS,
    top_n: int = 3,
) -> Dict[str, Any]:
    """Query Maumee water-quality observations.

    operation: 'records' (recent rows), 'summary' (count/mean/min/max with
    the datetimes of min and max), 'extremes' (top-N highest records with
    datetimes, plus the lowest — answers "when was X highest/lowest"),
    'daily' (daily means, capped), 'schema' (columns + date range).
    """
    from ...registry import MAUMEE_PARAMETERS

    import pandas as pd

    try:
        df = _load_frame()
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "code": "data_unavailable"}

    if operation == "schema":
        return {
            "ok": True,
            "type": "table",
            "dataset": "maumee_water_quality",
            "columns": list(df.columns),
            "row_count": len(df),
            "date_range": [str(df["DateTime"].min()), str(df["DateTime"].max())],
            "parameters": [p["code"] for p in MAUMEE_PARAMETERS],
            "note": "Station-level time-series; no per-row coordinates.",
            "rows": [],
        }

    frame = df
    if start_date:
        frame = frame[frame["DateTime"] >= pd.to_datetime(start_date)]
    if end_date:
        frame = frame[frame["DateTime"] <= pd.to_datetime(end_date)]

    cols = ["DateTime"]
    if parameter:
        cols.append(_value_col(parameter))
    else:
        cols += [c for c in df.columns if c.startswith("Value [")]

    if operation == "summary":
        out: List[Dict[str, Any]] = []
        targets = [_value_col(parameter)] if parameter else [
            c for c in df.columns if c.startswith("Value [")
        ]
        for col in targets:
            s = frame[col].dropna()
            row: Dict[str, Any] = {
                "column": col,
                "n": int(s.count()),
                "missing": int(frame[col].isna().sum()),
                "mean": float(s.mean()) if len(s) else None,
                "min": float(s.min()) if len(s) else None,
                "max": float(s.max()) if len(s) else None,
            }
            if len(s):
                # Datetimes of extremes — this is what answers "when".
                dts = frame.loc[s.index, "DateTime"]
                row["min_date"] = str(dts.loc[s.idxmin()])
                row["max_date"] = str(dts.loc[s.idxmax()])
            else:
                row["min_date"] = row["max_date"] = None
            out.append(row)
        return {
            "ok": True,
            "type": "table",
            "dataset": "maumee_water_quality",
            "columns": ["column", "n", "missing", "mean", "min", "max",
                        "min_date", "max_date"],
            "rows": out,
            "row_count": len(out),
        }

    if operation == "extremes":
        top_n = max(1, min(int(top_n), 50))
        targets = [_value_col(parameter)] if parameter else [
            c for c in df.columns if c.startswith("Value [")
        ]
        out = []
        for col in targets:
            sub = frame[["DateTime", col]].dropna(subset=[col])
            if sub.empty:
                continue
            top = sub.nlargest(top_n, col)
            lowest = sub.nsmallest(1, col).iloc[0]
            for rank, (_, r) in enumerate(top.iterrows(), 1):
                out.append({
                    "column": col,
                    "rank": rank,
                    "DateTime": str(r["DateTime"]),
                    "value": float(r[col]),
                    "note": "highest" if rank == 1 else f"top-{rank}",
                })
            out.append({
                "column": col,
                "rank": None,
                "DateTime": str(lowest["DateTime"]),
                "value": float(lowest[col]),
                "note": "lowest",
            })
        return {
            "ok": True,
            "type": "table",
            "dataset": "maumee_water_quality",
            "columns": ["column", "rank", "DateTime", "value", "note"],
            "rows": out,
            "row_count": len(out),
        }

    if operation == "daily" and parameter:
        col = _value_col(parameter)
        daily = (
            frame[["DateTime", col]]
            .dropna()
            .assign(DateTime=lambda d: pd.to_datetime(d["DateTime"]).dt.date)
            .groupby("DateTime", as_index=False)[col]
            .mean()
        )
        rows = daily.tail(max_rows).to_dict(orient="records")
        rows = [{k: str(v) for k, v in r.items()} for r in rows]
        return {
            "ok": True,
            "type": "table",
            "dataset": "maumee_water_quality",
            "columns": ["DateTime", col],
            "rows": rows,
            "row_count": len(daily),
            "returned": len(rows),
        }

    max_rows = max(1, min(int(max_rows), 1000))
    tail = frame[cols].tail(max_rows)
    rows = tail.to_dict(orient="records")
    clean = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in rows]
    # JSON-safe datetimes
    for r in clean:
        if r.get("DateTime") is not None:
            r["DateTime"] = str(r["DateTime"])
    return {
        "ok": True,
        "type": "table",
        "dataset": "maumee_water_quality",
        "columns": cols,
        "rows": clean,
        "row_count": len(frame),
        "returned": len(clean),
    }


QUERY_MAUMEE_SCHEMA = {
    "properties": {
        "parameter": {
            "type": "string",
            "description": (
                "Parameter code: FLOW (flow), TSS (total suspended solids), "
                "TP (total phosphorus), SRP (soluble/dissolved reactive phosphorus), "
                "NO23 (nitrite+nitrate/nitrogen), TKN (Kjeldahl nitrogen), "
                "CL (chloride), SO4 (sulfate), SI (silica), COND (conductivity). "
                "USE THIS TOOL for any question about measured values, maxima/minima, "
                "dates of records, trends, or summaries in the Maumee record — "
                "do NOT use the knowledge base for these. Omit for all value columns."
            ),
        },
        "start_date": {"type": "string", "description": "ISO date lower bound."},
        "end_date": {"type": "string", "description": "ISO date upper bound."},
        "operation": {
            "type": "string",
            "description": (
                "'records' (recent rows), 'summary' (stats incl. min/max dates), "
                "'extremes' (top-N highest records with datetimes + the lowest — "
                "use for 'highest', 'lowest', 'maximum', 'when was X highest/lowest', "
                "'peak', 'record' questions), 'daily' (daily means), 'schema'."
            ),
        },
        "max_rows": {
            "type": "integer",
            "description": "Max rows returned (default 200, cap 1000).",
        },
        "top_n": {
            "type": "integer",
            "description": "Top-N highest records for 'extremes' (default 3, cap 50).",
        },
    }
}
QUERY_MAUMEE_REQUIRED: List[str] = []
