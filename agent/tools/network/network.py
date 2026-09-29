"""Network analysis on line networks (own graph engine, no osmnx needed).

Graphs are plain dicts — ``{"type": "network", "nodes": {id: [x, y]},
"edges": [[u, v, length_m]], "crs", "directed": False}`` — so they ride the
existing $step_id mechanism untouched. Algorithms (Dijkstra, Brandes
betweenness, components) are implemented directly on the adjacency structure;
street geometry arrives via the Overpass roads query. Service areas are
convex hulls of reachable nodes — a documented approximation, not a
true street-polygon.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Dict, List, Optional, Tuple

from ..common import (ToolError, cap_int, collection, crs_of, table,
                      valid_shapes)


def _graph_of(obj: Dict[str, Any], name: str = "network") -> Dict[str, Any]:
    if not isinstance(obj, dict) or obj.get("type") != "network" \
            or not isinstance(obj.get("nodes"), dict) \
            or not isinstance(obj.get("edges"), list):
        raise ToolError(f"'{name}' must be a network built by build_network")
    return obj


def _adjacency(net: Dict[str, Any]) -> Dict[str, List[Tuple[str, float]]]:
    adj: Dict[str, List[Tuple[str, float]]] = {n: [] for n in net["nodes"]}
    for u, v, length in net["edges"]:
        if u in adj and v in adj:
            adj[u].append((v, float(length)))
            if not net.get("directed"):
                adj[v].append((u, float(length)))
    return adj


def _quant(x: float, y: float, tol: float) -> str:
    return f"{round(x / tol):d}:{round(y / tol):d}"


def build_network(input: Dict[str, Any], snap_tolerance_m: float = 5.0):
    """Build a routable graph from LineString features (metric snap)."""
    from ..common import metric_crs_for, reproject

    pairs = valid_shapes(input)
    lines = [g for _, g in pairs if g.geom_type in ("LineString", "MultiLineString")]
    if not lines:
        raise ToolError("build_network needs LineString features")
    if snap_tolerance_m <= 0:
        raise ToolError("snap tolerance must be positive")
    src = crs_of(input)
    metric = metric_crs_for(lines)
    nodes: Dict[str, List[float]] = {}
    edges: List[List[Any]] = []

    def node_id(x: float, y: float) -> str:
        key = _quant(x, y, snap_tolerance_m)
        if key not in nodes:
            nodes[key] = [x, y]
        return key

    for geom in lines:
        parts = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for part in parts:
            coords = [reproject_point(x, y, src, metric) for x, y in part.coords]
            for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                u, v = node_id(x1, y1), node_id(x2, y2)
                if u == v:
                    continue
                length = math.hypot(x2 - x1, y2 - y1)
                edges.append([u, v, round(length, 2)])
    # Drop isolated nodes (never touch an edge).
    used = {u for e in edges for u in e[:2]}
    nodes = {k: v for k, v in nodes.items() if k in used}
    return {"ok": True, "type": "network", "nodes": nodes, "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges),
            "crs": metric, "directed": False, "units": "metres"}


def reproject_point(x: float, y: float, src: str, dst: str) -> Tuple[float, float]:
    from pyproj import CRS, Transformer

    if src == dst:
        return x, y
    tx, ty = Transformer.from_crs(CRS(src), CRS(dst), always_xy=True).transform(x, y)
    return tx, ty


def _nearest_node(net: Dict[str, Any], x: float, y: float) -> str:
    best, best_d = "", float("inf")
    for nid, (nx, ny) in net["nodes"].items():
        d = math.hypot(nx - x, ny - y)
        if d < best_d:
            best, best_d = nid, d
    if not best:
        raise ToolError("network has no nodes")
    return best


def _dijkstra(adj, start: str, cutoff: Optional[float] = None):
    dist = {start: 0.0}
    prev: Dict[str, Optional[str]] = {start: None}
    heap = [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u] or (cutoff is not None and d > cutoff):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")) and (cutoff is None or nd <= cutoff):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    return dist, prev


def _snap_point(net: Dict[str, Any], lon: float, lat: float) -> Tuple[str, float, float]:
    src = "EPSG:4326"
    x, y = reproject_point(float(lon), float(lat), src, net.get("crs", src))
    return _nearest_node(net, x, y), x, y


def shortest_path(network: Dict[str, Any], from_lon: float, from_lat: float,
                  to_lon: float, to_lat: float):
    """Dijkstra shortest path between two lon/lat points (snapped to nodes).
    Returns the path as a LineString feature plus length and node hops."""
    net = _graph_of(network)
    start, _, _ = _snap_point(net, from_lon, from_lat)
    goal, _, _ = _snap_point(net, to_lon, to_lat)
    adj = _adjacency(net)
    dist, prev = _dijkstra(adj, start)
    if goal not in dist:
        return collection([], note="no route between snapped nodes")
    hops, node = [], goal
    while node is not None:
        hops.append(node)
        node = prev[node]
    hops.reverse()
    from shapely.geometry import LineString, mapping

    from ..common import reproject as _reproject

    line_m = LineString([tuple(net["nodes"][n]) for n in hops])
    line_wgs = _reproject(line_m, net.get("crs", "EPSG:4326"), "EPSG:4326")
    feat = {"type": "Feature",
            "properties": {"length_m": round(dist[goal], 1), "hops": len(hops)},
            "geometry": mapping(line_wgs)}
    return collection([feat], length_m=round(dist[goal], 1), nodes=hops)


def travel_time(input: Dict[str, Any], speed_kmh: float = 40.0):
    """Minutes to traverse a shortest_path result at a given speed."""
    if speed_kmh <= 0:
        raise ToolError("speed must be positive")
    feats = input.get("features", []) if isinstance(input, dict) else []
    if not feats:
        raise ToolError("travel_time needs a shortest_path result with features")
    length = feats[0].get("properties", {}).get("length_m")
    if length is None:
        raise ToolError("path result carries no length_m")
    minutes = float(length) / 1000.0 / float(speed_kmh) * 60.0
    return table(["length_m", "speed_kmh", "minutes"],
                 [{"length_m": length, "speed_kmh": speed_kmh,
                   "minutes": round(minutes, 2)}])


def service_area(network: Dict[str, Any], lon: float, lat: float,
                 minutes: float, speed_kmh: float = 40.0):
    """Reachable-nodes convex hull within a travel-time budget (documented
    approximation of a true network polygon)."""
    if minutes <= 0 or speed_kmh <= 0:
        raise ToolError("minutes and speed must be positive")
    net = _graph_of(network)
    start, _, _ = _snap_point(net, lon, lat)
    cutoff = float(minutes) / 60.0 * float(speed_kmh) * 1000.0
    adj = _adjacency(net)
    dist, _ = _dijkstra(adj, start, cutoff=cutoff)
    reached = [net["nodes"][n] for n in dist]
    if len(reached) < 3:
        return collection([], note="budget reaches fewer than 3 nodes")
    from shapely.geometry import MultiPoint

    from ..common import reproject as _reproject

    hull = MultiPoint(reached).convex_hull
    hull_wgs = _reproject(hull, net.get("crs", "EPSG:4326"), "EPSG:4326")
    from shapely.geometry import mapping

    feat = {"type": "Feature",
            "properties": {"minutes": minutes, "speed_kmh": speed_kmh,
                           "nodes_reached": len(reached)},
            "geometry": mapping(hull_wgs)}
    return collection([feat], approximation="convex hull of reachable nodes")


def betweenness_centrality(network: Dict[str, Any], top_n: int = 10):
    """Brandes betweenness over the largest component; top nodes with lon/lat."""
    net = _graph_of(network)
    adj = _adjacency(net)
    top_n = cap_int(top_n, 1, 500, name="top_n")
    if not adj:
        raise ToolError("network is empty")
    # Largest component only (betweenness across components is zero anyway).
    seen: set = set()
    stack, comp = [next(iter(adj))], set()
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        comp.add(u)
        stack.extend(v for v, _ in adj[u] if v not in seen)
    nodes = [n for n in comp]
    centrality = dict.fromkeys(nodes, 0.0)
    for s in nodes:
        stack_v: List[str] = []
        pred: Dict[str, List[str]] = {w: [] for w in nodes}
        sigma = dict.fromkeys(nodes, 0.0)
        sigma[s] = 1.0
        dist = dict.fromkeys(nodes, -1)
        dist[s] = 0
        queue = [s]
        for v in queue:
            stack_v.append(v)
            for w, weight in adj.get(v, []):
                if w not in comp:
                    continue
                if dist[w] < 0:
                    queue.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while stack_v:
            w = stack_v.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w]) if sigma[w] else 0.0
            if w != s:
                centrality[w] += delta[w]
    for n in centrality:
        centrality[n] /= 2.0
    ranked = sorted(centrality.items(), key=lambda kv: -kv[1])[:top_n]
    from ..common import reproject as _reproject

    rows = []
    for nid, score in ranked:
        x, y = net["nodes"][nid]
        lon, lat = _reproject_point(x, y, net.get("crs", "EPSG:4326"))
        rows.append({"node": nid, "betweenness": round(score, 3),
                     "lon": round(lon, 6), "lat": round(lat, 6)})
    return table(["node", "betweenness", "lon", "lat"], rows)


def _reproject_point(x: float, y: float, src: str):
    from pyproj import CRS, Transformer

    if src == "EPSG:4326":
        return x, y
    lon, lat = Transformer.from_crs(CRS(src), CRS("EPSG:4326"),
                                    always_xy=True).transform(x, y)
    return lon, lat


def download_street_network(bbox: str, road_class: str = "all",
                            max_features: int = 1000):
    """Fetch OSM roads for a bbox and build a routable network directly."""
    from ..data.osm import query_osm_roads

    roads = query_osm_roads(bbox, road_class=road_class,
                            max_features=max_features, want_geometry=True)
    if not roads.get("ok"):
        return roads
    net = build_network({"type": "FeatureCollection",
                         "features": roads.get("features", [])})
    if not net.get("ok"):
        return net
    net["bbox"] = roads.get("bbox")
    net["road_class"] = road_class
    return net


NETWORK_SCHEMAS = {
    "build_network": ({"properties": {
        "input": {"description": "Result reference with LineString features."},
        "snap_tolerance_m": {"type": "number", "description": "Default 5."}}},
        ["input"]),
    "download_street_network": ({"properties": {
        "bbox": {"type": "string"},
        "road_class": {"type": "string", "description": "Highway class or 'all'."},
        "max_features": {"type": "integer"}}}, ["bbox"]),
    "shortest_path": ({"properties": {
        "network": {"description": "Result reference to a built network."},
        "from_lon": {"type": "number"}, "from_lat": {"type": "number"},
        "to_lon": {"type": "number"}, "to_lat": {"type": "number"}}},
        ["network", "from_lon", "from_lat", "to_lon", "to_lat"]),
    "travel_time": ({"properties": {
        "input": {"description": "shortest_path result reference."},
        "speed_kmh": {"type": "number", "description": "Default 40."}}},
        ["input"]),
    "service_area": ({"properties": {
        "network": {"description": "Result reference to a built network."},
        "lon": {"type": "number"}, "lat": {"type": "number"},
        "minutes": {"type": "number"},
        "speed_kmh": {"type": "number", "description": "Default 40."}}},
        ["network", "lon", "lat", "minutes"]),
    "betweenness_centrality": ({"properties": {
        "network": {"description": "Result reference to a built network."},
        "top_n": {"type": "integer", "description": "Default 10."}}},
        ["network"]),
}
