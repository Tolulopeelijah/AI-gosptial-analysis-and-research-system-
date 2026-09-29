"""Raster processing (rasterio + numpy).

Rasters chain through $step_id references: every raster result is a descriptor
``{"type": "raster", "path": ...}`` pointing at a GeoTIFF under
``data/processed/`` — arrays never enter prompts or JSON responses, only file
paths and metadata do. `raster_calculator` evaluates a strict AST allowlist
(no raw eval). Anything needing data you don't have returns a capability
error, never a fabricated grid.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from ..common import CapabilityError, ToolError, cap_int, parse_bbox, table

PROCESSED_DIR = "data/processed"


def _rio():
    from ..common import require_module

    return require_module("rasterio", "rasterio")


def _resolve(input: Any) -> str:
    if isinstance(input, dict) and input.get("type") == "raster" and input.get("path"):
        path = input["path"]
    elif isinstance(input, str):
        path = input
    else:
        raise ToolError("'input' must be a raster result reference or file path")
    if not os.path.exists(path):
        raise ToolError(f"raster file not found: {path}")
    return path


def _out_path(prefix: str) -> str:
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    return os.path.join(PROCESSED_DIR, f"{prefix}_{uuid.uuid4().hex[:8]}.tif")


def _describe(path: str, rio) -> Dict[str, Any]:
    with rio.open(path) as src:
        return {"path": path, "width": src.width, "height": src.height,
                "bands": src.count, "crs": str(src.crs),
                "transform": list(src.transform),
                "pixel_width": abs(src.transform.a),
                "pixel_height": abs(src.transform.e),
                "dtype": str(src.dtypes[0]),
                "nodata": src.nodata,
                "bounds": [src.bounds.left, src.bounds.bottom,
                           src.bounds.right, src.bounds.top]}


def load_raster(path: str):
    """Open a GeoTIFF and return its descriptor for downstream tools."""
    rio = _rio()
    if not os.path.exists(path):
        raise ToolError(f"raster file not found: {path}")
    desc = _describe(path, rio)
    return {"ok": True, "type": "raster", **desc}


def describe_raster(input: Any):
    """Metadata plus per-band statistics (nodata-masked)."""
    rio = _rio()
    import numpy as np

    path = _resolve(input)
    desc = _describe(path, rio)
    bands = []
    with rio.open(path) as src:
        for i in range(1, src.count + 1):
            arr = src.read(i, masked=True)
            data = arr.compressed()
            bands.append({"band": i,
                          "min": float(data.min()) if data.size else None,
                          "max": float(data.max()) if data.size else None,
                          "mean": float(data.mean()) if data.size else None,
                          "std": float(data.std()) if data.size else None,
                          "valid_pixels": int(data.size)})
    desc["bands_stats"] = bands
    return {"ok": True, **desc}


def clip_raster(input: Any, bbox: str):
    """Clip to a 'west,south,east,north' box (same CRS as the raster)."""
    rio = _rio()
    from rasterio.mask import mask
    from shapely.geometry import box as sbox

    path = _resolve(input)
    w, s, e, n = parse_bbox(bbox)
    with rio.open(path) as src:
        if str(src.crs) not in ("EPSG:4326", "OGC:CRS84") \
                and -180 <= w <= 180 and -180 <= e <= 180 \
                and -90 <= s <= 90 and -90 <= n <= 90:
            raise ToolError("bbox looks like lon/lat but the raster CRS is "
                            f"{src.crs}; reproject first or match CRS")
        out_arr, out_transform = mask(src, [sbox(w, s, e, n)], crop=True)
        meta = src.meta.copy()
    if out_arr.shape[1] == 0 or out_arr.shape[2] == 0:
        raise ToolError("clip box does not overlap the raster")
    meta.update({"height": out_arr.shape[1], "width": out_arr.shape[2],
                 "transform": out_transform})
    dest = _out_path("clip")
    with rio.open(dest, "w", **meta) as dst:
        dst.write(out_arr)
    return {"ok": True, "type": "raster", **_describe(dest, rio)}


def resample_raster(input: Any, scale_factor: float = 0.5,
                    method: str = "bilinear"):
    """Resample by a scale factor (0.5 = half resolution)."""
    rio = _rio()
    from rasterio.enums import Resampling

    methods = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear,
               "cubic": Resampling.cubic, "average": Resampling.average}
    if method not in methods:
        raise ToolError(f"method must be one of {', '.join(methods)}")
    if not (0 < scale_factor <= 4):
        raise ToolError("scale_factor must be within (0, 4]")
    path = _resolve(input)
    with rio.open(path) as src:
        new_w, new_h = max(1, int(src.width * scale_factor)), \
            max(1, int(src.height * scale_factor))
        data = src.read(out_shape=(src.count, new_h, new_w),
                        resampling=methods[method])
        transform = src.transform * src.transform.scale(
            src.width / new_w, src.height / new_h)
        meta = src.meta.copy()
        meta.update({"height": new_h, "width": new_w, "transform": transform})
    dest = _out_path("resampled")
    with rio.open(dest, "w", **meta) as dst:
        dst.write(data)
    return {"ok": True, "type": "raster", **_describe(dest, rio),
            "method": method}


def raster_statistics(input: Any):
    """Per-band count/min/max/mean/std (nodata-masked) as a table."""
    rio = _rio()
    import numpy as np

    path = _resolve(input)
    rows = []
    with rio.open(path) as src:
        for i in range(1, src.count + 1):
            data = src.read(i, masked=True).compressed()
            rows.append({"band": i, "pixels": int(data.size),
                         "min": float(data.min()) if data.size else None,
                         "max": float(data.max()) if data.size else None,
                         "mean": float(data.mean()) if data.size else None,
                         "std": float(data.std()) if data.size else None})
    _ = np
    return table(["band", "pixels", "min", "max", "mean", "std"], rows,
                 path=path)


def zonal_statistics(input: Any, zones: Dict[str, Any], operation: str = "mean",
                     band: int = 1):
    """Per-zone raster stats (count/min/max/mean/std/sum) for polygon zones."""
    rio = _rio()
    import numpy as np
    from rasterio.features import rasterize

    from ..common import valid_shapes

    if operation not in ("count", "min", "max", "mean", "std", "sum"):
        raise ToolError("operation must be count|min|max|mean|std|sum")
    path = _resolve(input)
    pairs = valid_shapes(zones, "zones")
    if not pairs:
        raise ToolError("no polygon zones")
    rows = []
    with rio.open(path) as src:
        arr = src.read(cap_int(band, 1, src.count, name="band"), masked=True)
        for i, (feat, geom) in enumerate(pairs):
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                raise ToolError(f"zone {i} is not polygonal")
            mask = rasterize([(geom, 1)], out_shape=arr.shape,
                             transform=src.transform, fill=0,
                             dtype="uint8").astype(bool)
            vals = arr.data[mask & ~arr.mask]
            if vals.size == 0:
                rows.append({"zone": i, "pixels": 0, operation: None})
                continue
            stat = {"count": int(vals.size), "min": float(vals.min()),
                    "max": float(vals.max()), "mean": float(vals.mean()),
                    "std": float(vals.std()), "sum": float(vals.sum())}
            rows.append({"zone": i, "pixels": int(vals.size),
                         operation: stat[operation]})
    _ = np
    return table(["zone", "pixels", operation], rows, operation=operation)


def raster_calculator(input_a: Any, expression: str, input_b: Any = None):
    """Band math with a strict AST allowlist: names a (and b), numpy calls
    sqrt/log/exp/sin/cos/abs/minimum/maximum/where, numbers, +-*/ comparisons.
    Anything else is rejected — no raw eval."""
    rio = _rio()
    import ast

    import numpy as np

    allowed_calls = {"sqrt", "log", "exp", "sin", "cos", "abs",
                     "minimum", "maximum", "where"}
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"bad expression: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "np"
                    and func.attr in allowed_calls):
                raise ToolError("only np.sqrt/log/exp/sin/cos/abs/minimum/"
                                "maximum/where calls allowed")
        elif isinstance(node, ast.Name) and node.id not in ("a", "b", "np"):
            raise ToolError(f"name '{node.id}' not allowed (use a, b, np.*)")
        elif isinstance(node, (ast.Attribute,)) and not (
                isinstance(node.value, ast.Name) and node.value.id == "np"):
            raise ToolError("attribute access not allowed")
        elif isinstance(node, (ast.Import, ast.ImportFrom, ast.Lambda,
                               ast.ListComp, ast.SetComp, ast.DictComp,
                               ast.GeneratorExp, ast.Await, ast.Yield)):
            raise ToolError("expression construct not allowed")
    path_a = _resolve(input_a)
    with rio.open(path_a) as src:
        a = src.read(1).astype("float64")
        meta = src.meta.copy()
        nodata_a = src.nodata
    env: Dict[str, Any] = {"a": a, "np": np}
    if input_b is not None:
        path_b = _resolve(input_b)
        with rio.open(path_b) as src:
            b = src.read(1).astype("float64")
            if b.shape != a.shape:
                raise ToolError(f"band shape mismatch {a.shape} vs {b.shape}")
        env["b"] = b
    try:
        # No builtins: validated AST + explicit namespace only. errstate
        # suppresses numpy's warning machinery, which otherwise tries to
        # __import__ warnings (unavailable in this namespace by design).
        safe_builtins = {"abs": abs, "min": min, "max": max, "round": round,
                         "float": float, "int": int, "len": len, "range": range}
        with np.errstate(all="ignore"):
            result = eval(compile(tree, "<raster-calculator>", "eval"),  # noqa: S307
                          {"__builtins__": safe_builtins}, env)
    except Exception as exc:
        raise ToolError(f"evaluation failed: {exc}") from exc
    out_arr = np.asarray(result, dtype="float64")
    if out_arr.shape != a.shape:
        raise ToolError("expression must return a same-shape array")
    fill = nodata_a if nodata_a is not None else -9999.0
    out_arr = np.where(np.isfinite(out_arr), out_arr, fill)
    meta.update({"count": 1, "dtype": "float64", "nodata": fill})
    dest = _out_path("calc")
    with rio.open(dest, "w", **meta) as dst:
        dst.write(out_arr, 1)
    return {"ok": True, "type": "raster", **_describe(dest, rio),
            "expression": expression}


def raster_reclassify(input: Any, mapping: str):
    """Reclassify by ranges: '0-10:1;10-20:2;20-*:3' (* = open end)."""
    rio = _rio()
    import numpy as np

    rules = []
    for part in str(mapping).split(";"):
        m = __import__("re").match(r"^\s*(-?[\d.]+|\*)\s*-\s*(-?[\d.]+|\*)\s*:\s*(-?[\d.]+)\s*$",
                                   part)
        if not m:
            raise ToolError(f"bad rule '{part}'; use 'lo-hi:value' ranges")
        lo = float("-inf") if m.group(1) == "*" else float(m.group(1))
        hi = float("inf") if m.group(2) == "*" else float(m.group(2))
        if lo >= hi:
            raise ToolError(f"empty range '{part}'")
        rules.append((lo, hi, float(m.group(3))))
    if not rules:
        raise ToolError("no rules given")
    path = _resolve(input)
    with rio.open(path) as src:
        a = src.read(1).astype("float64")
        meta = src.meta.copy()
    out = np.full(a.shape, np.nan)
    for lo, hi, val in rules:
        out[(a >= lo) & (a < hi)] = val
    meta.update({"count": 1, "dtype": "float64", "nodata": -9999.0})
    dest = _out_path("reclass")
    with rio.open(dest, "w", **meta) as dst:
        dst.write(np.nan_to_num(out, nan=-9999.0), 1)
    classes = sorted({v for _, _, v in rules})
    return {"ok": True, "type": "raster", **_describe(dest, rio),
            "classes": classes}


def _elevation(input: Any):
    rio = _rio()
    import numpy as np

    path = _resolve(input)
    with rio.open(path) as src:
        if src.count < 1:
            raise ToolError("empty raster")
        arr = src.read(1, masked=True).filled(np.nan).astype("float64")
        cellx, celly = abs(src.transform.a), abs(src.transform.e)
        if src.transform.b != 0 or src.transform.d != 0:
            raise ToolError("rotated rasters unsupported for terrain tools")
    return arr, cellx, celly


def _write_single(arr, template_path: str, prefix: str, rio) -> str:
    with rio.open(template_path) as src:
        meta = src.meta.copy()
    meta.update({"count": 1, "dtype": "float64", "nodata": -9999.0})
    dest = _out_path(prefix)
    with rio.open(dest, "w", **meta) as dst:
        dst.write(arr, 1)
    return dest


def raster_slope(input: Any, units: str = "degrees"):
    """Horn's slope from an elevation band (degrees or percent)."""
    import numpy as np

    if units not in ("degrees", "percent"):
        raise ToolError("units must be 'degrees' or 'percent'")
    rio = _rio()
    arr, cellx, celly = _elevation(input)
    dzdx = (np.roll(arr, -1, 1) - np.roll(arr, 1, 1)) / (2 * cellx)
    dzdy = (np.roll(arr, -1, 0) - np.roll(arr, 1, 0)) / (2 * celly)
    with np.errstate(invalid="ignore"):
        grad = np.sqrt(dzdx ** 2 + dzdy ** 2)
        out = np.degrees(np.arctan(grad)) if units == "degrees" else grad * 100.0
    out[[0, -1], :] = np.nan
    out[:, [0, -1]] = np.nan
    dest = _write_single(np.nan_to_num(out, nan=-9999.0), _resolve(input),
                         "slope", rio)
    return {"ok": True, "type": "raster", **_describe(dest, rio), "units": units}


RASTER_SCHEMAS = {
    "load_raster": ({"properties": {
        "path": {"type": "string", "description": "GeoTIFF file path."}}}, ["path"]),
    "describe_raster": ({"properties": {
        "input": {"description": "Raster result reference or path."}}}, ["input"]),
    "clip_raster": ({"properties": {
        "input": {"description": "Raster result reference or path."},
        "bbox": {"type": "string"}}}, ["input", "bbox"]),
    "resample_raster": ({"properties": {
        "input": {"description": "Raster result reference or path."},
        "scale_factor": {"type": "number", "description": "e.g. 0.5 halves."},
        "method": {"type": "string", "description": "nearest|bilinear|cubic|average."}}},
        ["input"]),
    "raster_statistics": ({"properties": {
        "input": {"description": "Raster result reference or path."}}}, ["input"]),
    "zonal_statistics": ({"properties": {
        "input": {"description": "Raster result reference or path."},
        "zones": {"description": "Polygon result reference."},
        "operation": {"type": "string", "description": "count|min|max|mean|std|sum."},
        "band": {"type": "integer", "description": "Default 1."}}},
        ["input", "zones"]),
    "raster_calculator": ({"properties": {
        "input_a": {"description": "Raster reference or path (band a)."},
        "input_b": {"description": "Optional second raster (band b)."},
        "expression": {"type": "string",
                       "description": "e.g. '(a - b) / (a + b)'. AST-validated."}}},
        ["input_a", "expression"]),
    "raster_reclassify": ({"properties": {
        "input": {"description": "Raster reference or path."},
        "mapping": {"type": "string", "description": "e.g. '0-10:1;10-*:2'."}}},
        ["input", "mapping"]),
    "raster_slope": ({"properties": {
        "input": {"description": "Elevation raster reference or path."},
        "units": {"type": "string", "description": "'degrees' (default) or 'percent'."}}},
        ["input"]),
}
