"""Descriptive statistics and true spatial statistics (numpy only).

Moran's I, Local Moran (LISA), and Getis-Ord G* are implemented directly from
their definitions with inverse-distance weights over feature centroids — no
PySAL dependency, and every result reports the statistic, expectation,
z-score, and p-value approximation so numbers are interpretable, not bare.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..common import ToolError, table, valid_shapes


def _values(input: Dict[str, Any], field: str) -> List[float]:
    if input.get("type") == "table":
        rows = input.get("rows", [])
        vals = [r.get(field) for r in rows]
    else:
        vals = [(f.get("properties", {}) or {}).get(field)
                for f, _ in valid_shapes(input)]
    out = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not out:
        raise ToolError(f"no numeric values for field '{field}'")
    return out


def _np():
    from ..common import require_module

    return require_module("numpy", "numpy")


def calculate_mean(input: Dict[str, Any], field: str):
    np = _np()
    vals = _values(input, field)
    return table(["field", "n", "mean"],
                 [{"field": field, "n": len(vals), "mean": float(np.mean(vals))}])


def calculate_std(input: Dict[str, Any], field: str):
    np = _np()
    vals = _values(input, field)
    arr = np.asarray(vals)
    return table(["field", "n", "std", "variance"],
                 [{"field": field, "n": len(vals), "std": float(arr.std()),
                   "variance": float(arr.var())}])


def calculate_percentiles(input: Dict[str, Any], field: str,
                          percentiles: List[float] | None = None):
    np = _np()
    vals = _values(input, field)
    pcts = percentiles or [0, 25, 50, 75, 100]
    for p in pcts:
        if not (0 <= float(p) <= 100):
            raise ToolError("percentiles must be within 0..100")
    cuts = np.percentile(vals, pcts).tolist()
    return table(["percentile", "value"],
                 [{"percentile": float(p), "value": float(v)}
                  for p, v in zip(pcts, cuts)], field=field, n=len(vals))


def calculate_correlation(input: Dict[str, Any], field_x: str, field_y: str):
    np = _np()
    if input.get("type") == "table":
        rows = input.get("rows", [])
    else:
        rows = [dict(feat.get("properties", {}) or {})
                for feat, _ in valid_shapes(input)]
    pairs = [(r.get(field_x), r.get(field_y)) for r in rows]
    pairs = [(float(x), float(y)) for x, y in pairs
             if isinstance(x, (int, float)) and isinstance(y, (int, float))
             and not isinstance(x, bool) and not isinstance(y, bool)]
    if len(pairs) < 3:
        raise ToolError("correlation needs at least 3 paired numeric values")
    xs = np.asarray([p[0] for p in pairs])
    ys = np.asarray([p[1] for p in pairs])
    r = float(np.corrcoef(xs, ys)[0, 1])
    return table(["field_x", "field_y", "n", "pearson_r"],
                 [{"field_x": field_x, "field_y": field_y,
                   "n": len(pairs), "pearson_r": round(r, 4)}])


def _centroid_weights(input: Dict[str, Any]):
    """Inverse-distance weights (diagonal 0, rows standardised)."""
    np = _np()
    pairs = valid_shapes(input)
    if len(pairs) < 3:
        raise ToolError("spatial statistics need at least 3 features")
    cents = np.array([[g.centroid.x, g.centroid.y] for _, g in pairs])
    diff = cents[:, None, :] - cents[None, :, :]
    dist = np.sqrt((diff ** 2).sum(-1))
    with np.errstate(divide="ignore"):
        w = np.where(dist > 0, 1.0 / np.where(dist == 0, 1.0, dist), 0.0)
    row_sums = w.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return (w / row_sums), len(pairs)


def moran_i(input: Dict[str, Any], field: str):
    """Global Moran's I with z-score and normal-approximation p-value."""
    np = _np()
    vals = np.asarray(_values(input, field))
    if len(vals) != len(valid_shapes(input)):
        raise ToolError("every feature needs a numeric value for Moran's I")
    w, n = _centroid_weights(input)
    if n < 4:
        raise ToolError("global Moran's I needs at least 4 features "
                        "(randomisation variance divides by n-3)")
    z = vals - vals.mean()
    denom = float((z ** 2).sum())
    if denom == 0:
        raise ToolError("field is constant; Moran's I undefined")
    s0 = float(w.sum())
    i = float(n / s0 * (z @ w @ z) / denom)
    expected = -1.0 / (n - 1)
    # Randomisation variance (standard form).
    s1 = float(((w + w.T) ** 2).sum() / 2.0)
    s2 = float((((w.sum(axis=1) + w.sum(axis=0)) ** 2)).sum())
    m2 = denom / n
    m4 = float((z ** 4).sum()) / n
    b2 = m4 / (m2 ** 2) if m2 else 0.0
    var = (n * ((n ** 2 - 3 * n + 3) * s1 - n * s2 + 3 * s0 ** 2)
           - b2 * ((n ** 2 - n) * s1 - 2 * n * s2 + 6 * s0 ** 2)) \
        / ((n - 1) * (n - 2) * (n - 3) * s0 ** 2) - expected ** 2
    var = max(var, 1e-12)
    zscore = (i - expected) / math.sqrt(var)
    p = float(2 * (1 - 0.5 * (1 + math.erf(abs(zscore) / math.sqrt(2)))))
    return table(["field", "n", "moran_i", "expected", "z", "p_value",
                  "interpretation"],
                 [{"field": field, "n": n, "moran_i": round(i, 4),
                   "expected": round(expected, 4), "z": round(zscore, 3),
                   "p_value": round(p, 4),
                   "interpretation": "clustered" if zscore > 1.96 else
                   "dispersed" if zscore < -1.96 else "random"}])


def local_moran(input: Dict[str, Any], field: str):
    """LISA: local Moran per feature with quadrant classification
    (HH/LH/LL/HL) and z-scores."""
    np = _np()
    vals = np.asarray(_values(input, field))
    if len(vals) != len(valid_shapes(input)):
        raise ToolError("every feature needs a numeric value")
    w, n = _centroid_weights(input)
    z = vals - vals.mean()
    m2 = float((z ** 2).sum()) / n
    lag = w @ z
    with np.errstate(divide="ignore", invalid="ignore"):
        ii = np.where(m2 > 0, z * lag / m2, 0.0)
    sd = float(np.sqrt(m2)) or 1.0
    rows = []
    for i in range(n):
        quad = ("HH" if z[i] > 0 and lag[i] > 0 else "LL" if z[i] <= 0 and lag[i] <= 0
                else "HL" if z[i] > 0 else "LH")
        rows.append({"feature": i, "value": float(vals[i]),
                     "local_moran": round(float(ii[i]), 4),
                     "lag_z": round(float(lag[i] / sd), 3), "quadrant": quad})
    return table(["feature", "value", "local_moran", "lag_z", "quadrant"], rows,
                 field=field)


def getis_ord(input: Dict[str, Any], field: str):
    """Getis-Ord G* z-score per feature (row-standardised inverse distance)."""
    np = _np()
    vals = np.asarray(_values(input, field))
    if len(vals) != len(valid_shapes(input)):
        raise ToolError("every feature needs a numeric value")
    w, n = _centroid_weights(input)
    with np.errstate(invalid="ignore"):
        w_star = w + np.eye(n) / max(n - 1, 1)
        w_star = w_star / w_star.sum(axis=1, keepdims=True)
    mean, var = float(vals.mean()), float(vals.var())
    sd = math.sqrt(var) or 1e-12
    rows = []
    for i in range(n):
        num = float((w_star[i] * vals).sum()) - mean
        den = sd * math.sqrt(max((n * float((w_star[i] ** 2).sum()) - 1) / max(n - 1, 1), 1e-12))
        g = num / den if den else 0.0
        rows.append({"feature": i, "value": float(vals[i]),
                     "g_star_z": round(g, 3)})
    return table(["feature", "value", "g_star_z"], rows, field=field)


def hotspot_analysis(input: Dict[str, Any], field: str, threshold: float = 1.96):
    """Classify features as hotspot/coldspot/not-significant from G*."""
    out = getis_ord(input, field)
    rows = []
    for r in out["rows"]:
        z = r["g_star_z"]
        label = ("hotspot" if z >= threshold else
                 "coldspot" if z <= -threshold else "not_significant")
        rows.append({**r, "class": label, "threshold": threshold})
    hot = sum(1 for r in rows if r["class"] == "hotspot")
    cold = sum(1 for r in rows if r["class"] == "coldspot")
    return table(["feature", "value", "g_star_z", "class", "threshold"], rows,
                 field=field, hotspots=hot, coldspots=cold)


def kernel_density(input: Dict[str, Any], cell_meters: float = 1000.0,
                   bandwidth_meters: float = 3000.0):
    """Gaussian KDE over input points on a metric grid; returns grid cell
    polygons with density values (cells with ~zero density omitted)."""
    from shapely.geometry import mapping

    from ..common import (collection, crs_of, metric_crs_for, reproject,
                          to_meters, to_wgs_feature)

    np = _np()
    pairs = valid_shapes(input)
    pts = [g for _, g in pairs if g.geom_type == "Point"]
    if len(pts) < len(pairs):
        raise ToolError("kernel_density needs point features")
    if len(pts) < 2:
        raise ToolError("kernel_density needs at least 2 points")
    cell = to_meters(cell_meters, "meters")
    bw = to_meters(bandwidth_meters, "meters")
    src = crs_of(input)
    metric = metric_crs_for(pts)
    mp = np.array([[p.x, p.y] for p in
                   (reproject(g, src, metric) for g in pts)])
    minx, miny = mp.min(axis=0) - bw
    maxx, maxy = mp.max(axis=0) + bw
    xs = np.arange(minx, maxx, cell)
    ys = np.arange(miny, maxy, cell)
    if len(xs) == 0 or len(ys) == 0 or len(xs) * len(ys) > 40000:
        raise ToolError("grid degenerate or too large; adjust cell/bandwidth")
    gx, gy = np.meshgrid(xs, ys)
    grid = np.stack([gx.ravel(), gy.ravel()], axis=1)
    diff = grid[:, None, :] - mp[None, :, :]
    dens = np.exp(-(diff ** 2).sum(-1) / (2 * bw ** 2)).sum(axis=1)
    dens = dens / (len(mp) * 2 * math.pi * bw ** 2) * 1e6  # per km²
    feats = []
    from shapely.geometry import box as sbox

    for (cx, cy), d in zip(grid.tolist(), dens.tolist()):
        if d < 1e-9:
            continue
        cell_poly = sbox(cx, cy, cx + cell, cy + cell)
        feats.append(to_wgs_feature(cell_poly, {"density_per_km2": round(d, 4)},
                                    metric))
    return collection(feats, cell_m=cell, bandwidth_m=bw,
                      points=len(pts), units="density_per_km2")


STATISTICS_SCHEMAS = {
    "calculate_mean": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "field": {"type": "string"}}}, ["input", "field"]),
    "calculate_std": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "field": {"type": "string"}}}, ["input", "field"]),
    "calculate_percentiles": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "field": {"type": "string"},
        "percentiles": {"description": "Array within 0..100 (default quartiles)."}}},
        ["input", "field"]),
    "calculate_correlation": ({"properties": {
        "input": {"description": "Result reference (features or table)."},
        "field_x": {"type": "string"}, "field_y": {"type": "string"}}},
        ["input", "field_x", "field_y"]),
    "moran_i": ({"properties": {
        "input": {"description": "Result reference (polygon/point features)."},
        "field": {"type": "string"}}}, ["input", "field"]),
    "local_moran": ({"properties": {
        "input": {"description": "Result reference."},
        "field": {"type": "string"}}}, ["input", "field"]),
    "getis_ord": ({"properties": {
        "input": {"description": "Result reference."},
        "field": {"type": "string"}}}, ["input", "field"]),
    "hotspot_analysis": ({"properties": {
        "input": {"description": "Result reference."},
        "field": {"type": "string"},
        "threshold": {"type": "number", "description": "z threshold (default 1.96)."}}},
        ["input", "field"]),
    "kernel_density": ({"properties": {
        "input": {"description": "Result reference with points."},
        "cell_meters": {"type": "number"}, "bandwidth_meters": {"type": "number"}}},
        ["input"]),
}
