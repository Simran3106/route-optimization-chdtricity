"""
src/routing/routing.py

Data-Driven Geographical Bus Route Optimization for Chandigarh CTU Local Bus Network.
Implements:
  - Approach A: Reconstructed original-sequence road baseline (Dijkstra on OSM road graph)
  - Approach B: Constrained Local Search (geographically bounded 2-opt / swap / insertion)
  - Approach C: Demand-Aware Corridor-Constrained Genetic Algorithm (GA)

Evaluates routes across:
  1. Road distance (km)
  2. Estimated travel time (min, road-class speeds + stop dwell)
  3. Historical passenger-demand importance and disruption
  4. Estimated fleet requirements (F = ceil(C / H))
  5. Estimated operating cost (Rs, expenditure / vehicle-km scenario)
  6. Stop preservation (100%) and road-network feasibility

Primary dataset: data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV
Secondary dataset: data/passengerdata/performance_routes_clean.csv
Road network: data/roadnodes/tricity_road_network.graphml
"""

import argparse
import json
import math
import random
import re
import sys
import time
import traceback
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, replace
from functools import lru_cache
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

# Default urban road classification speeds in Chandigarh (km/h)
# References: Master Plan 2031 & Indian Road Congress (IRC) urban arterial guidelines.
DEFAULT_SPEEDS_KMH: Dict[str, float] = {
    "trunk": 50.0,
    "trunk_link": 40.0,
    "primary": 45.0,
    "primary_link": 35.0,
    "secondary": 40.0,
    "secondary_link": 30.0,
    "tertiary": 30.0,
    "tertiary_link": 25.0,
    "residential": 25.0,
    "living_street": 20.0,
    "unclassified": 25.0,
}
DEFAULT_GRAPHML = Path("data/roadnodes/tricity_road_network.graphml")
DEFAULT_MAX_SNAP_M = 500.0
DEFAULT_DWELL_TIME_SEC = 30.0  # 30 seconds dwell per intermediate stop
DEFAULT_LAYOVER_RATIO = 0.15   # 15% terminal turnaround / layover buffer


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class StopOccurrence:
    """Represents an individual ordered stop occurrence along a bus route chart."""
    occurrence_idx: int
    chart_no: int
    route: str
    direction: str
    original_order: int
    chart_label: str
    ctu_stop_id: str
    ctu_stop_name: str
    latitude: float
    longitude: float
    boardings: float
    alightings: float
    volume: float
    importance: float  # w_i = Boardings + Alightings
    osm_node: Optional[str] = None
    snap_distance_m: float = 0.0
    snap_exceeds_threshold: bool = False


@dataclass
class RouteEvaluation:
    """Evaluation summary for a specific route sequence and model."""
    route: str
    direction: str
    chart_no: int
    model: str
    routing_status: str
    distance_km: float
    estimated_travel_time_min: float
    stops_retained_pct: float
    historical_boardings_retained: float
    historical_alightings_retained: float
    demand_weighted_disruption: float
    historical_max_volume: Optional[float]
    historical_daily_ridership: Optional[float]
    historical_load_factor: Optional[float]
    estimated_fleet_requirement: Optional[int]
    modeled_operating_cost_rs: Optional[float]
    objective_value: float
    execution_time_s: float
    stop_sequence_order: List[int] = field(default_factory=list)
    historical_route_length_km: Optional[float] = None
    historical_on_road_fleet: Optional[float] = None
    historical_vehicle_km: Optional[float] = None
    historical_expenditure_rs: Optional[float] = None
    road_path_nodes: List[str] = field(default_factory=list)
    road_coordinates: List[Tuple[float, float]] = field(default_factory=list)  # (lat, lon)


# =============================================================================
# ROAD NETWORK AND DATA LOADING
# =============================================================================

def parse_wkt_linestring(geom_str: str) -> List[Tuple[float, float]]:
    """Parse WKT LINESTRING (lon lat, lon lat, ...) to [(lat, lon), ...]."""
    if not geom_str or "LINESTRING" not in geom_str:
        return []
    coords_part = geom_str.replace("LINESTRING", "").strip(" ()")
    points: List[Tuple[float, float]] = []
    for pair in coords_part.split(","):
        parts = pair.strip().split()
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                points.append((lat, lon))
            except ValueError:
                continue
    return points


class RoadNetwork:
    """Encapsulates the Chandigarh OSM road graph, stop snapping, and routing."""

    def __init__(self, graphml_path: Path = DEFAULT_GRAPHML, max_snap_m: float = DEFAULT_MAX_SNAP_M):
        self.graphml_path = Path(graphml_path)
        self.max_snap_m = max_snap_m
        graph = nx.read_graphml(graphml_path, force_multigraph=True)
        if not graph.is_directed():
            raise ValueError("Road GraphML must be directed")
        crs = str(graph.graph.get("crs", "epsg:4326")).lower()
        if crs not in {"epsg:4326", "wgs84", "ogc:crs84"}:
            raise ValueError(f"Unsupported road coordinate reference system: {crs}")
        self.raw_graph = graph
        self._prepare_edge_attributes()
        graph.remove_nodes_from(list(nx.isolates(graph)))
        if not graph.number_of_edges():
            raise ValueError("Road GraphML contains no usable drivable edges")

        self.node_list = list(graph)
        try:
            self.node_coords = np.array(
                [(float(graph.nodes[n]["y"]), float(graph.nodes[n]["x"])) for n in self.node_list]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Road nodes require numeric WGS84 x/y coordinates") from exc
        if not (np.abs(self.node_coords) <= [90, 180]).all():
            raise ValueError("Road node coordinates fall outside WGS84 bounds")
        components = list(nx.strongly_connected_components(graph))
        self.main_scc = max(components, key=len)
        self.components = nx.condensation(graph, components)
        self.component_of = self.components.graph["mapping"]
        self.reachable_components = lru_cache(maxsize=1024)(
            lambda component: nx.descendants(self.components, component)
        )
        self.adjacent_edges = {
            u: {v: min(edges.values(), key=lambda edge: edge["length_m"]) for v, edges in neighbors.items()}
            for u, neighbors in graph.adj.items()
        }
        self.path_cache = OrderedDict()
        print(f"[RoadNetwork] {graphml_path}: {len(graph)} nodes, {graph.number_of_edges()} "
              f"drivable directed edges, {nx.number_weakly_connected_components(graph)} weak components")

    def can_reach(self, source: str, target: str) -> bool:
        if source not in self.component_of or target not in self.component_of:
            return False
        u, v = self.component_of[source], self.component_of[target]
        return u == v or v in self.reachable_components(u)

    def _prepare_edge_attributes(self):
        """Keep usable directed edges and derive travel time from road class."""
        unusable = []
        for u, v, key, edge in self.raw_graph.edges(keys=True, data=True):
            highway = re.findall(r"[a-z_]+", str(edge.get("highway", "")).lower())
            access = set(re.findall(r"[a-z_]+", str(edge.get("access", "")).lower()))
            if (not highway or any(kind not in DEFAULT_SPEEDS_KMH for kind in highway)
                    or access & {"no", "private", "military", "permit"}):
                unusable.append((u, v, key))
                continue
            try:
                length = float(edge.get("length", edge.get("length_m")))
            except (ValueError, TypeError):
                length = math.nan
            if not math.isfinite(length) or length <= 0:
                unusable.append((u, v, key))
                continue
            speed_ms = min(DEFAULT_SPEEDS_KMH[kind] for kind in highway) / 3.6
            edge["length_m"] = length
            edge["time_sec"] = length / speed_ms
        self.raw_graph.remove_edges_from(unusable)

    def snap_stop(self, lat: float, lon: float) -> Tuple[str, float]:
        """
        Snap a stop coordinate (lat, lon) to the nearest road-network node
        across the usable directed road graph. Returns (osm_node_id, distance_in_meters).
        """
        if not (abs(lat) <= 90 and abs(lon) <= 180):
            raise ValueError("Invalid stop coordinates")
        lat_arr = self.node_coords[:, 0]
        lon_arr = self.node_coords[:, 1]
        d_lat = (lat_arr - lat) * 111139.0
        d_lon = (lon_arr - lon) * 111139.0 * math.cos(math.radians(lat))
        dists = np.hypot(d_lat, d_lon)
        best_idx = int(np.argmin(dists))
        return self.node_list[best_idx], float(dists[best_idx])

    def get_shortest_path(self, u: str, v: str) -> Tuple[float, float, List[str], List[Tuple[float, float]]]:
        """
        Compute shortest path from node u to v on length_m.
        Returns (distance_m, travel_time_sec, node_sequence, list_of_lat_lon_points).
        """
        return self.get_shortest_paths(u, [v])[v]

    def get_shortest_paths(self, source, targets):
        """Run Dijkstra once per source until the uncached reachable targets are settled."""
        results = {}
        pending = set()
        for target in dict.fromkeys(targets):
            key = source, target
            if key in self.path_cache:
                self.path_cache.move_to_end(key)
                results[target] = self.path_cache[key]
            elif self.can_reach(source, target):
                pending.add(target)
            else:
                results[target] = math.inf, math.inf, [], []

        if not pending:
            return results
        adjacency = self.adjacent_edges
        distance = {source: 0.0}
        predecessor = {}
        queue = [(0.0, source)]
        while pending:
            current_distance, node = heappop(queue)
            if current_distance != distance[node]:
                continue
            if node in pending:
                path = [node]
                while path[-1] != source:
                    path.append(predecessor[path[-1]])
                path.reverse()
                result = self._describe_path(path)
                results[node] = result
                self.path_cache[source, node] = result
                if len(self.path_cache) > 8192:
                    self.path_cache.popitem(last=False)
                pending.remove(node)
                if not pending:
                    break
            for neighbor, edge in adjacency[node].items():
                candidate = current_distance + edge["length_m"]
                if candidate < distance.get(neighbor, math.inf):
                    distance[neighbor] = candidate
                    predecessor[neighbor] = node
                    heappush(queue, (candidate, neighbor))
        return results

    def _describe_path(self, path_nodes):
        if len(path_nodes) == 1:
            node = self.raw_graph.nodes[path_nodes[0]]
            return 0.0, 0.0, path_nodes, [(float(node["y"]), float(node["x"]))]

        total_length_m = 0.0
        total_time_sec = 0.0
        coords: List[Tuple[float, float]] = []

        for i in range(len(path_nodes) - 1):
            n1 = path_nodes[i]
            n2 = path_nodes[i + 1]
            best_edge = self.adjacent_edges[n1][n2]
            total_length_m += best_edge["length_m"]
            total_time_sec += best_edge["time_sec"]

            p1 = (float(self.raw_graph.nodes[n1]["y"]), float(self.raw_graph.nodes[n1]["x"]))
            p2 = (float(self.raw_graph.nodes[n2]["y"]), float(self.raw_graph.nodes[n2]["x"]))
            edge_pts = parse_wkt_linestring(best_edge.get("geometry"))
            if len(edge_pts) >= 2:
                if math.dist(edge_pts[-1], p1) < math.dist(edge_pts[0], p1):
                    edge_pts.reverse()
                edge_pts[0], edge_pts[-1] = p1, p2
            else:
                edge_pts = [p1, p2]
            coords.extend(edge_pts[1:] if coords else edge_pts)

        return total_length_m, total_time_sec, path_nodes, coords


class InvalidChart(ValueError):
    pass


class InfeasibleChart(ValueError):
    pass


def load_passenger_data(csv_path: Path) -> pd.DataFrame:
    """Load and validate the primary boarding-alighting dataset."""
    df = pd.read_csv(csv_path, dtype={"route": "string", "ctu_stop_id": "string"})
    df.columns = df.columns.str.strip()
    required = {"chart_no", "route", "direction", "stop_order", "chart_label",
                "ctu_stop_id", "ctu_stop_name", "latitude", "longitude",
                "Boardings", "Alightings", "Volume"}
    if missing := required - set(df.columns):
        raise ValueError(f"Primary passenger CSV missing required columns: {sorted(missing)}")

    df["route"] = df["route"].str.strip()
    df["direction"] = df["direction"].str.strip().str.upper()
    numeric = ["chart_no", "stop_order", "latitude", "longitude", "Boardings", "Alightings", "Volume"]
    for col in numeric:
        original = df[col]
        df[col] = pd.to_numeric(original, errors="coerce")
        df[f"_invalid_{col}"] = (original.notna() & df[col].isna()) | np.isinf(df[col])
    df["_source_line"] = np.arange(len(df)) + 2
    return df.sort_values(["chart_no", "stop_order"], kind="stable").reset_index(drop=True)


def discover_charts(df: pd.DataFrame) -> List[pd.DataFrame]:
    """Keep unidentified rows as individual invalid inputs for diagnostics."""
    known = [group for _, group in df.groupby("chart_no")]
    return known + [df.loc[[idx]] for idx in df.index[df["chart_no"].isna()]]


def validate_chart(df: pd.DataFrame) -> None:
    for col in ("chart_no", "stop_order"):
        values = df[col]
        if not (np.isfinite(values) & (values >= 1) & (values % 1 == 0)).all():
            raise InvalidChart(f"Missing or invalid {col}")
    if len(df) < 2 or df["stop_order"].duplicated().any():
        raise InvalidChart("Chart requires at least two uniquely ordered occurrences")
    if (df["route"].isna().any() or df["route"].eq("").any() or df["route"].nunique() != 1
            or not df["direction"].isin(["UP", "DOWN"]).all() or df["direction"].nunique() != 1):
        raise InvalidChart("Chart requires one route and one UP/DOWN direction")
    for col, bound in (("latitude", 90), ("longitude", 180)):
        if not df[col].abs().le(bound).all():
            raise InvalidChart(f"Missing or invalid {col}")
    for col in ("Boardings", "Alightings"):
        if not (np.isfinite(df[col]) & df[col].ge(0)).all():
            raise InvalidChart(f"Missing or invalid {col}; demand-weighted fitness unavailable")
    invalid_volume = df.get("_invalid_Volume", pd.Series(False, index=df.index))
    if invalid_volume.any() or np.isinf(df["Volume"]).any() or df["Volume"].lt(0).any():
        raise InvalidChart("Invalid historical Volume")


def load_performance_data(csv_path: Path) -> pd.DataFrame:
    """Load and clean secondary route performance data."""
    if not csv_path.exists():
        print(f"[warn] Performance CSV not found at {csv_path}")
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    if "Route No" in df.columns:
        df["Route_No_Std"] = df["Route No"].astype(str).str.strip().str.upper()
    return df


def extract_stop_occurrences(df: pd.DataFrame, road_net: RoadNetwork) -> List[StopOccurrence]:
    """Convert a route DataFrame slice into structured StopOccurrence objects with snapped nodes."""
    validate_chart(df)
    stops: List[StopOccurrence] = []
    for idx, row in enumerate(df.sort_values("stop_order").itertuples()):
        lat = float(row.latitude)
        lon = float(row.longitude)
        node_id, snap_dist = road_net.snap_stop(lat, lon)
        b = float(row.Boardings)
        a = float(row.Alightings)
        v = float(row.Volume)

        stop = StopOccurrence(
            occurrence_idx=idx,
            chart_no=int(row.chart_no),
            route=str(row.route),
            direction=str(row.direction),
            original_order=int(row.stop_order),
            chart_label=str(row.chart_label),
            ctu_stop_id=str(row.ctu_stop_id) if pd.notna(row.ctu_stop_id) else "",
            ctu_stop_name=str(row.ctu_stop_name) if pd.notna(row.ctu_stop_name) else str(row.chart_label),
            latitude=lat,
            longitude=lon,
            boardings=b,
            alightings=a,
            volume=v,
            importance=b + a,
            osm_node=node_id,
            snap_distance_m=snap_dist,
            snap_exceeds_threshold=snap_dist > road_net.max_snap_m,
        )
        stops.append(stop)
    return stops


# =============================================================================
# STOP-PAIRWISE DISTANCE CACHING FOR FAST EVALUATION
# =============================================================================

class RouteCostMatrix:
    """
    Precomputes and caches shortest road paths and travel times between all
    pairs of stop occurrences for a single route.
    """

    def __init__(self, stops: List[StopOccurrence], road_net: RoadNetwork, corridor_m: Optional[float] = None):
        self.stops = stops
        self.n = len(stops)
        self.road_net = road_net

        self.dist_matrix = np.full((self.n, self.n), float("inf"), dtype=np.float64)
        self.time_matrix = np.full((self.n, self.n), float("inf"), dtype=np.float64)
        self.path_nodes_cache: Dict[Tuple[int, int], List[str]] = {}
        self.path_coords_cache: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}

        self._precompute()
        self.corridor_m = corridor_m
        self.outside_corridor = set()
        if corridor_m is not None:
            _, reference = self.get_full_trajectory(list(range(self.n)))
            if reference:
                self._check_corridor(reference, corridor_m)

    def _check_corridor(self, reference, corridor_m):
        """Check candidate geometry vertices against baseline road segments in local metres."""
        scale = np.array([111139.0, 111139.0 * math.cos(math.radians(reference[0][0]))])
        points = (np.asarray(reference) - reference[0]) * scale
        starts = points[:-1] if len(points) > 1 else points
        vectors = np.diff(points, axis=0) if len(points) > 1 else np.zeros_like(points)
        squares = np.sum(vectors ** 2, axis=1)
        denominator = np.where(squares > 0, squares, 1)
        point_cache = {}
        for pair, coords in self.path_coords_cache.items():
            for coord in coords:
                if coord not in point_cache:
                    offsets = (np.asarray(coord) - reference[0]) * scale - starts
                    fraction = np.clip(np.sum(offsets * vectors, axis=1) / denominator, 0, 1)
                    residual = offsets - fraction[:, None] * vectors
                    point_cache[coord] = np.min(np.sum(residual ** 2, axis=1)) > corridor_m ** 2 + 1e-8
                if point_cache[coord]:
                    self.outside_corridor.add(pair)
                    break

    def _precompute(self):
        nodes = [stop.osm_node for stop in self.stops]
        for i, u in enumerate(nodes):
            paths = self.road_net.get_shortest_paths(u, nodes)
            for j, v in enumerate(nodes):
                dist_m, time_s, path_nodes, coords = paths[v]
                self.dist_matrix[i, j] = dist_m
                self.time_matrix[i, j] = time_s
                self.path_nodes_cache[(i, j)] = path_nodes
                self.path_coords_cache[(i, j)] = coords

    def evaluate_sequence(
        self,
        seq: List[int],
        dwell_time_sec: float = DEFAULT_DWELL_TIME_SEC,
    ) -> Tuple[float, float, bool]:
        """
        Evaluate road distance (m) and estimated travel time (s) for an ordered stop sequence.
        Returns (total_distance_m, total_time_sec, is_connected).
        """
        total_dist_m = 0.0
        total_time_sec = 0.0

        for k in range(len(seq) - 1):
            i = seq[k]
            j = seq[k + 1]
            d = self.dist_matrix[i, j]
            t = self.time_matrix[i, j]
            if math.isinf(d):
                return float("inf"), float("inf"), False
            total_dist_m += d
            total_time_sec += t

        n_intermediate = max(len(seq) - 2, 0)
        total_time_sec += n_intermediate * dwell_time_sec

        return total_dist_m, total_time_sec, True

    def get_full_trajectory(self, seq: List[int]) -> Tuple[List[str], List[Tuple[float, float]]]:
        """Combine full node list and road coordinates for a candidate stop sequence."""
        if not self.evaluate_sequence(seq)[2]:
            return [], []
        full_nodes: List[str] = []
        full_coords: List[Tuple[float, float]] = []

        for k in range(len(seq) - 1):
            i = seq[k]
            j = seq[k + 1]
            nodes = self.path_nodes_cache.get((i, j), [])
            coords = self.path_coords_cache.get((i, j), [])
            if not full_nodes:
                full_nodes.extend(nodes)
            else:
                full_nodes.extend(nodes[1:])
            if not full_coords:
                full_coords.extend(coords)
            else:
                full_coords.extend(coords[1:])

        return full_nodes, full_coords


# =============================================================================
# DEMAND-WEIGHTED DISRUPTION & OBJECTIVE FUNCTION
# =============================================================================

def calculate_demand_disruption(stops: List[StopOccurrence], seq: List[int]) -> float:
    """
    Calculate historical demand-weighted sequence disruption:
        P = sum(w_i * |p_i^{new} - p_i^{old}|) / sum(w_i)
    where:
        w_i = Boardings_i + Alightings_i
        p_i^{old} = original occurrence index
        p_i^{new} = position in candidate sequence
    If total demand is zero, returns unweighted average displacement.
    """
    total_importance = sum(s.importance for s in stops)
    position_map = {occurrence_idx: pos for pos, occurrence_idx in enumerate(seq)}

    weighted_displacement = 0.0
    for old_pos, stop in enumerate(stops):
        new_pos = position_map.get(stop.occurrence_idx, old_pos)
        displacement = abs(new_pos - old_pos)
        if total_importance > 0:
            weighted_displacement += stop.importance * displacement
        else:
            weighted_displacement += displacement

    if total_importance > 0:
        return weighted_displacement / total_importance
    return weighted_displacement / len(stops)


def validate_weights(alpha: float, beta: float, gamma: float) -> None:
    weights = (alpha, beta, gamma)
    if not all(math.isfinite(w) and w >= 0 for w in weights) or not math.isclose(sum(weights), 1.0):
        raise ValueError("Objective weights must be finite, non-negative and sum to 1")


def calculate_objective(
    distance_m: float,
    baseline_dist_m: float,
    travel_time_sec: float,
    baseline_time_sec: float,
    disruption: float,
    n_stops: int,
    alpha: float = 0.5,
    beta: float = 0.2,
    gamma: float = 0.3,
) -> float:
    """
    Normalized multi-objective fitness function:
        min J = alpha * D_n + beta * T_n + gamma * P_n
    where:
        D_n = distance / baseline_distance
        T_n = time / baseline_time
        P_n = disruption / (n_stops - 1)
    """
    validate_weights(alpha, beta, gamma)
    if not all(map(math.isfinite, (distance_m, baseline_dist_m, travel_time_sec, baseline_time_sec))):
        return math.inf

    d_n = distance_m / baseline_dist_m if baseline_dist_m else 1.0
    t_n = travel_time_sec / baseline_time_sec if baseline_time_sec else 1.0
    max_disp = max(n_stops - 1, 1)
    p_n = disruption / max_disp

    return alpha * d_n + beta * t_n + gamma * p_n


def check_shortcut_stops(
    seq: List[int],
    cost_matrix: RouteCostMatrix,
    stops: List[StopOccurrence],
) -> int:
    """
    Critical feasibility check: Detects if the shortest drivable road path between
    two scheduled consecutive stops passes through another required stop node out of order.
    Returns the count of out-of-order shortcut violations.
    """
    required_nodes = {stop.osm_node for stop in stops}
    served_nodes = set()
    early_nodes = set()
    for u, v in zip(seq, seq[1:]):
        served_nodes.add(stops[u].osm_node)
        interior = cost_matrix.path_nodes_cache.get((u, v), [])[1:-1]
        early_nodes.update(node for node in interior if node in required_nodes and node not in served_nodes)
    return len(early_nodes)


def sequence_objective(seq, stops, cost_matrix, baseline_dist_m, baseline_time_s, alpha, beta, gamma):
    distance, travel_time, connected = cost_matrix.evaluate_sequence(seq)
    if not connected:
        return math.inf
    disruption = calculate_demand_disruption(stops, seq)
    return (calculate_objective(distance, baseline_dist_m, travel_time, baseline_time_s,
                                disruption, len(stops), alpha, beta, gamma)
            + 0.1 * check_shortcut_stops(seq, cost_matrix, stops))


def is_candidate_feasible(
    seq: List[int],
    stops: List[StopOccurrence],
    cost_matrix: RouteCostMatrix,
    baseline_dist_m: float,
    max_displacement: int = 3,
    max_detour_ratio: float = 1.25,
) -> Tuple[bool, str]:
    """Validate stop preservation and road-network constraints."""
    n = len(stops)
    if n < 2 or len(seq) != n:
        return False, "Stop count mismatch"

    if seq[0] != 0:
        return False, "Start terminal modified"
    if seq[-1] != n - 1:
        return False, "End terminal modified"

    if set(seq) != set(range(n)):
        return False, "Missing or duplicated stop occurrences"

    for pos, occ_idx in enumerate(seq):
        if abs(pos - occ_idx) > max_displacement:
            return False, f"Stop occurrence {occ_idx} displaced beyond {max_displacement} positions"

    dist_m, _, connected = cost_matrix.evaluate_sequence(seq)
    if not connected or math.isinf(dist_m):
        return False, "Disconnected road segments encountered"

    if dist_m > baseline_dist_m * max_detour_ratio + 1e-7:
        return False, f"Route exceeds the maximum detour ratio {max_detour_ratio}"
    if any(pair in cost_matrix.outside_corridor for pair in zip(seq, seq[1:])):
        return False, f"Road geometry exceeds the {cost_matrix.corridor_m:g} m baseline corridor"

    return True, "Feasible"


# =============================================================================
# APPROACH A: RECONSTRUCTED BASELINE
# =============================================================================

def evaluate_baseline(
    stops: List[StopOccurrence],
    cost_matrix: RouteCostMatrix,
    alpha: float = 0.5, beta: float = 0.2, gamma: float = 0.3,
) -> RouteEvaluation:
    """Evaluate Approach A: Reconstructed original-sequence road baseline."""
    t0 = time.time()
    seq = list(range(len(stops)))
    dist_m, time_s, connected = cost_matrix.evaluate_sequence(seq)
    nodes, coords = cost_matrix.get_full_trajectory(seq)

    total_b = sum(s.boardings for s in stops)
    total_a = sum(s.alightings for s in stops)
    max_v = max(s.volume for s in stops) if all(math.isfinite(s.volume) for s in stops) else None

    exec_time = time.time() - t0
    feasible, reason = is_candidate_feasible(seq, stops, cost_matrix, dist_m)
    status = "Feasible" if feasible else reason

    return RouteEvaluation(
        route=stops[0].route,
        direction=stops[0].direction,
        chart_no=stops[0].chart_no,
        model="Reconstructed_Baseline",
        routing_status=status,
        distance_km=dist_m / 1000.0,
        estimated_travel_time_min=time_s / 60.0,
        stops_retained_pct=100.0,
        historical_boardings_retained=total_b,
        historical_alightings_retained=total_a,
        demand_weighted_disruption=0.0,
        historical_max_volume=max_v,
        historical_daily_ridership=None,
        historical_load_factor=None,
        estimated_fleet_requirement=None,
        modeled_operating_cost_rs=None,
        objective_value=sequence_objective(seq, stops, cost_matrix, dist_m, time_s, alpha, beta, gamma),
        execution_time_s=exec_time,
        stop_sequence_order=seq,
        road_path_nodes=nodes,
        road_coordinates=coords,
    )


# =============================================================================
# APPROACH B: CONSTRAINED LOCAL SEARCH
# =============================================================================

def run_constrained_local_search(
    stops: List[StopOccurrence],
    cost_matrix: RouteCostMatrix,
    baseline_dist_m: float,
    baseline_time_s: float,
    alpha: float = 0.5,
    beta: float = 0.2,
    gamma: float = 0.3,
    max_displacement: int = 3,
    max_detour_ratio: float = 1.25,
    max_iterations: int = 150,
) -> RouteEvaluation:
    """
    Approach B: Constrained Local Search baseline using local 2-opt reversals,
    local swaps, and insertions within feasibility limits.
    """
    t0 = time.time()
    n = len(stops)
    best_seq = list(range(n))
    best_dist, best_time, _ = cost_matrix.evaluate_sequence(best_seq)
    best_disp = 0.0
    best_obj = sequence_objective(best_seq, stops, cost_matrix, baseline_dist_m,
                                  baseline_time_s, alpha, beta, gamma)

    improved = True
    iteration = 0

    while improved and iteration < max_iterations:
        improved = False
        iteration += 1

        candidates: List[List[int]] = []

        # 1. Local adjacent and 2-step swaps
        for i in range(1, n - 2):
            for j in range(i + 1, min(i + 3, n - 1)):
                cand = best_seq.copy()
                cand[i], cand[j] = cand[j], cand[i]
                candidates.append(cand)

        # 2. Local 2-opt short subsequence reversals
        for i in range(1, n - 3):
            for length in [2, 3]:
                if i + length < n - 1:
                    cand = best_seq.copy()
                    cand[i : i + length + 1] = reversed(cand[i : i + length + 1])
                    candidates.append(cand)

        # 3. Local insertion
        for i in range(1, n - 1):
            for delta in [-2, -1, 1, 2]:
                j = i + delta
                if 1 <= j < n - 1:
                    cand = best_seq.copy()
                    val = cand.pop(i)
                    cand.insert(j, val)
                    candidates.append(cand)

        # Evaluate candidate moves
        for cand in candidates:
            feasible, _ = is_candidate_feasible(
                cand, stops, cost_matrix, baseline_dist_m, max_displacement, max_detour_ratio
            )
            if not feasible:
                continue

            c_obj = sequence_objective(cand, stops, cost_matrix, baseline_dist_m,
                                       baseline_time_s, alpha, beta, gamma)
            if c_obj < best_obj - 1e-10:
                c_dist, c_time, _ = cost_matrix.evaluate_sequence(cand)
                c_disp = calculate_demand_disruption(stops, cand)
                best_seq = cand
                best_obj = c_obj
                best_dist = c_dist
                best_time = c_time
                best_disp = c_disp
                improved = True
                break

    feasible, reason = is_candidate_feasible(
        best_seq, stops, cost_matrix, baseline_dist_m, max_displacement, max_detour_ratio
    )
    nodes, coords = cost_matrix.get_full_trajectory(best_seq)
    exec_time = time.time() - t0

    return RouteEvaluation(
        route=stops[0].route,
        direction=stops[0].direction,
        chart_no=stops[0].chart_no,
        model="Constrained_Local_Search",
        routing_status="Feasible" if feasible else reason,
        distance_km=best_dist / 1000.0,
        estimated_travel_time_min=best_time / 60.0,
        stops_retained_pct=100.0,
        historical_boardings_retained=sum(s.boardings for s in stops),
        historical_alightings_retained=sum(s.alightings for s in stops),
        demand_weighted_disruption=best_disp,
        historical_max_volume=max(s.volume for s in stops) if all(math.isfinite(s.volume) for s in stops) else None,
        historical_daily_ridership=None,
        historical_load_factor=None,
        estimated_fleet_requirement=None,
        modeled_operating_cost_rs=None,
        objective_value=best_obj,
        execution_time_s=exec_time,
        stop_sequence_order=best_seq,
        road_path_nodes=nodes,
        road_coordinates=coords,
    )


# =============================================================================
# APPROACH C: CONSTRAINED GENETIC ALGORITHM (GA)
# =============================================================================

class ConstrainedGeneticAlgorithm:
    """
    Corridor-constrained, demand-aware Genetic Algorithm for bus route stop re-sequencing.
    """

    def __init__(
        self,
        stops: List[StopOccurrence],
        cost_matrix: RouteCostMatrix,
        baseline_dist_m: float,
        baseline_time_s: float,
        pop_size: int = 50,
        n_generations: int = 60,
        crossover_prob: float = 0.8,
        mutation_prob: float = 0.35,
        elitism_count: int = 3,
        tournament_size: int = 3,
        alpha: float = 0.5,
        beta: float = 0.2,
        gamma: float = 0.3,
        max_displacement: int = 3,
        max_detour_ratio: float = 1.25,
        random_seed: int = 42,
    ):
        self.stops = stops
        self.cost_matrix = cost_matrix
        self.n = len(stops)
        self.baseline_dist_m = baseline_dist_m
        self.baseline_time_s = baseline_time_s
        self.pop_size = pop_size
        self.n_generations = n_generations
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        self.elitism_count = elitism_count
        self.tournament_size = tournament_size
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.max_displacement = max_displacement
        self.max_detour_ratio = max_detour_ratio
        self.random_seed = random_seed
        self.rng = random.Random(random_seed)
        validate_weights(alpha, beta, gamma)
        self._cached_fitness = lru_cache(maxsize=4096)(self._fitness)

    def _fitness(self, seq: List[int]) -> float:
        """Evaluate fitness (lower objective is better). Infeasible returns inf."""
        feasible, _ = is_candidate_feasible(
            seq, self.stops, self.cost_matrix, self.baseline_dist_m,
            self.max_displacement, self.max_detour_ratio
        )
        if not feasible:
            return float("inf")

        return sequence_objective(seq, self.stops, self.cost_matrix, self.baseline_dist_m,
                                  self.baseline_time_s, self.alpha, self.beta, self.gamma)

    def _init_population(self) -> List[List[int]]:
        """Initialize population with baseline, small local swaps, and valid permutations."""
        pop: List[List[int]] = [list(range(self.n))]

        attempts = 0
        while len(pop) < self.pop_size and attempts < self.pop_size * 20:
            attempts += 1
            cand = list(range(self.n))
            n_swaps = self.rng.randint(1, 3)
            for _ in range(n_swaps):
                if self.n > 3:
                    i = self.rng.randint(1, self.n - 2)
                    delta = self.rng.choice([-1, 1])
                    j = i + delta
                    if 1 <= j < self.n - 1:
                        cand[i], cand[j] = cand[j], cand[i]

            if is_candidate_feasible(
                cand, self.stops, self.cost_matrix, self.baseline_dist_m,
                self.max_displacement, self.max_detour_ratio
            )[0]:
                if cand not in pop:
                    pop.append(cand)

        while len(pop) < self.pop_size:
            pop.append(list(range(self.n)))

        return pop

    def _tournament_select(self, pop: List[List[int]], fitnesses: List[float]) -> List[int]:
        candidates = self.rng.sample(range(len(pop)), min(len(pop), self.tournament_size))
        best_idx = min(candidates, key=lambda idx: fitnesses[idx])
        return pop[best_idx].copy()

    def _crossover_order(self, p1: List[int], p2: List[int]) -> Tuple[List[int], List[int]]:
        """Order-preserving crossover (OX) with pinned start and end terminals."""
        if self.n <= 3 or self.rng.random() > self.crossover_prob:
            return p1.copy(), p2.copy()

        interior_len = self.n - 2
        idx1 = self.rng.randint(1, interior_len)
        idx2 = self.rng.randint(1, interior_len)
        if idx1 > idx2:
            idx1, idx2 = idx2, idx1

        def make_child(parent_a: List[int], parent_b: List[int]) -> List[int]:
            child = [None] * self.n
            child[0] = 0
            child[-1] = self.n - 1

            child[idx1 : idx2 + 1] = parent_a[idx1 : idx2 + 1]
            copied = set(child[idx1 : idx2 + 1])

            b_interior = [x for x in parent_b if x not in (0, self.n - 1) and x not in copied]
            fill_ptr = 0
            for pos in range(1, self.n - 1):
                if child[pos] is None:
                    if fill_ptr < len(b_interior):
                        child[pos] = b_interior[fill_ptr]
                        fill_ptr += 1
            return child

        c1 = make_child(p1, p2)
        c2 = make_child(p2, p1)

        f1 = is_candidate_feasible(c1, self.stops, self.cost_matrix, self.baseline_dist_m, self.max_displacement, self.max_detour_ratio)[0]
        f2 = is_candidate_feasible(c2, self.stops, self.cost_matrix, self.baseline_dist_m, self.max_displacement, self.max_detour_ratio)[0]

        res1 = c1 if f1 else p1.copy()
        res2 = c2 if f2 else p2.copy()
        return res1, res2

    def _mutate(self, ind: List[int]) -> List[int]:
        """Apply constrained local mutations: swap, short reversal, or insertion."""
        if self.rng.random() > self.mutation_prob or self.n <= 3:
            return ind

        cand = ind.copy()
        mutation_type = self.rng.choice(["swap", "reversal", "insertion"])

        if mutation_type == "swap":
            i = self.rng.randint(1, self.n - 2)
            delta = self.rng.choice([-1, 1])
            j = i + delta
            if 1 <= j < self.n - 1:
                cand[i], cand[j] = cand[j], cand[i]

        elif mutation_type == "reversal":
            length = self.rng.choice([2, 3])
            i = self.rng.randint(1, max(1, self.n - 2 - length))
            j = i + length
            if j < self.n - 1:
                cand[i : j + 1] = reversed(cand[i : j + 1])

        elif mutation_type == "insertion":
            i = self.rng.randint(1, self.n - 2)
            delta = self.rng.choice([-1, 1])
            j = i + delta
            if 1 <= j < self.n - 1:
                val = cand.pop(i)
                cand.insert(j, val)

        if is_candidate_feasible(
            cand, self.stops, self.cost_matrix, self.baseline_dist_m,
            self.max_displacement, self.max_detour_ratio
        )[0]:
            return cand
        return ind

    def run(self) -> Tuple[List[int], float, List[float]]:
        pop = self._init_population()
        fitnesses = [self._cached_fitness(tuple(ind)) for ind in pop]
        history: List[float] = []

        best_idx = int(np.argmin(fitnesses))
        best_ind = pop[best_idx].copy()
        best_fit = fitnesses[best_idx]
        history.append(best_fit)

        for gen in range(self.n_generations):
            sorted_indices = np.argsort(fitnesses)
            new_pop: List[List[int]] = [pop[idx].copy() for idx in sorted_indices[: self.elitism_count]]

            while len(new_pop) < self.pop_size:
                p1 = self._tournament_select(pop, fitnesses)
                p2 = self._tournament_select(pop, fitnesses)
                c1, c2 = self._crossover_order(p1, p2)
                c1 = self._mutate(c1)
                c2 = self._mutate(c2)
                new_pop.append(c1)
                if len(new_pop) < self.pop_size:
                    new_pop.append(c2)

            pop = new_pop
            fitnesses = [self._cached_fitness(tuple(ind)) for ind in pop]

            gen_best_idx = int(np.argmin(fitnesses))
            if fitnesses[gen_best_idx] < best_fit:
                best_fit = fitnesses[gen_best_idx]
                best_ind = pop[gen_best_idx].copy()
            history.append(best_fit)

        return best_ind, best_fit, history


# =============================================================================
# OPERATIONAL FLEET AND COST EVALUATION
# =============================================================================

def match_performance_record(
    route: str,
    direction: str,
    df_perf: pd.DataFrame,
) -> Optional[pd.Series]:
    """Match an exact, unique route identifier and an explicit direction if present."""
    if "Route_No_Std" not in df_perf:
        return None
    match = df_perf[df_perf["Route_No_Std"].eq(route.strip().upper())]
    if "Direction" in match:
        match = match[match["Direction"].str.strip().str.upper().eq(direction)]
    return match.iloc[0] if len(match) == 1 else None


def performance_number(row: pd.Series, field: str) -> Optional[float]:
    value = pd.to_numeric(row.get(field), errors="coerce")
    return float(value) if pd.notna(value) and math.isfinite(value) and value >= 0 else None


def evaluate_operational_scenarios(
    eval_record: RouteEvaluation,
    perf_row: Optional[pd.Series],
    layover_ratio: float = DEFAULT_LAYOVER_RATIO,
    *,
    reverse: Optional[RouteEvaluation] = None,
    verified_headway_min: Optional[float] = None,
) -> Tuple[Optional[int], Optional[float]]:
    """Model cycle fleet and the allocated cost of one directional traversal."""
    if perf_row is None or eval_record.routing_status != "Feasible":
        return None, None
    fleet = None
    if (reverse is not None and reverse.routing_status == "Feasible"
            and reverse.route == eval_record.route and reverse.direction != eval_record.direction
            and reverse.model == eval_record.model and verified_headway_min is not None
            and math.isfinite(verified_headway_min) and verified_headway_min > 0
            and math.isfinite(layover_ratio) and layover_ratio >= 0):
        times = (eval_record.estimated_travel_time_min, reverse.estimated_travel_time_min)
        if all(math.isfinite(t) and t > 0 for t in times):
            fleet = math.ceil(sum(times) * (1 + layover_ratio) / verified_headway_min)

    vehicle_km = performance_number(perf_row, "Actual Veh. Km")
    expenditure = performance_number(perf_row, "Total Expenditure (Rs)")
    route_length = performance_number(perf_row, "Route Length (km)")
    distance = eval_record.distance_km
    cost = None
    if (route_length and vehicle_km and vehicle_km >= route_length and expenditure
            and math.isfinite(distance) and distance > 0):
        cost = distance * expenditure / vehicle_km
    return fleet, cost


def apply_fleet_scenarios(evaluations, stops_by_chart, passenger_data, performance_data):
    """Record a cycle once per model for a unique, terminal-compatible UP/DOWN pair."""
    chart_counts = passenger_data.groupby(["route", "direction"])["chart_no"].nunique()
    by_service = {(r.route, r.direction, r.model): r for r in evaluations}
    for up in evaluations:
        if up.direction != "UP" or any(chart_counts.get((up.route, d), 0) != 1 for d in ("UP", "DOWN")):
            continue
        down = by_service.get((up.route, "DOWN", up.model))
        perf = match_performance_record(up.route, "UP", performance_data)
        if down is None or perf is None or "Direction" in perf:
            continue
        up_stops = stops_by_chart[(up.route, up.direction, up.chart_no)]
        down_stops = stops_by_chart[(down.route, down.direction, down.chart_no)]
        terminals = (up_stops[0].ctu_stop_id, up_stops[-1].ctu_stop_id)
        if not all(terminals) or terminals != (down_stops[-1].ctu_stop_id, down_stops[0].ctu_stop_id):
            continue
        headway = performance_number(perf, "Morning Peak Headway")
        up.estimated_fleet_requirement, _ = evaluate_operational_scenarios(
            up, perf, reverse=down, verified_headway_min=headway
        )


# =============================================================================
# PIPELINE COORDINATOR: OPTIMIZING A SINGLE ROUTE-CHART
# =============================================================================

def optimize_route_chart(
    chart_df: pd.DataFrame,
    road_net: RoadNetwork,
    df_perf: pd.DataFrame,
    alpha: float = 0.5,
    beta: float = 0.2,
    gamma: float = 0.3,
    max_displacement: int = 3,
    max_detour_ratio: float = 1.25,
    ga_seeds: List[int] = [42, 101, 2024, 7, 999],
    pop_size: int = 50,
    n_generations: int = 60,
    corridor_m: Optional[float] = None,
    stops: Optional[List[StopOccurrence]] = None,
) -> Tuple[List[RouteEvaluation], Dict[str, Any]]:
    """
    Executes Baseline, Constrained Local Search, and multi-seed Constrained GA
    for one directional chart.
    """
    validate_weights(alpha, beta, gamma)
    if stops is None:
        stops = extract_stop_occurrences(chart_df, road_net)
    route_name = stops[0].route
    direction = stops[0].direction
    chart_no = stops[0].chart_no

    print(f"\n=======================================================")
    print(f"OPTIMIZING ROUTE {route_name} {direction} (Chart {chart_no}) | {len(stops)} stops")
    print(f"=======================================================")

    for first, second in zip(stops, stops[1:]):
        if not road_net.can_reach(first.osm_node, second.osm_node):
            raise InfeasibleChart(
                f"Disconnected directed leg from stop order {first.original_order} ({first.osm_node}) "
                f"to {second.original_order} ({second.osm_node})"
            )
    cost_matrix = RouteCostMatrix(stops, road_net, corridor_m)

    # 1. Approach A: Baseline
    base_eval = evaluate_baseline(stops, cost_matrix, alpha, beta, gamma)
    if base_eval.routing_status != "Feasible":
        raise InfeasibleChart(base_eval.routing_status)
    print(f"[Approach A - Baseline] Distance: {base_eval.distance_km:.2f} km | "
          f"Est. Time: {base_eval.estimated_travel_time_min:.1f} min | Status: {base_eval.routing_status}")

    perf_row = match_performance_record(route_name, direction, df_perf)
    # 2. Approach B: Local Search
    ls_eval = run_constrained_local_search(
        stops, cost_matrix,
        baseline_dist_m=base_eval.distance_km * 1000.0,
        baseline_time_s=base_eval.estimated_travel_time_min * 60.0,
        alpha=alpha, beta=beta, gamma=gamma,
        max_displacement=max_displacement,
        max_detour_ratio=max_detour_ratio,
    )
    print(f"[Approach B - Local Search] Distance: {ls_eval.distance_km:.2f} km "
          f"({(1 - ls_eval.distance_km / base_eval.distance_km) * 100 if base_eval.distance_km else 0:+.2f}%) | "
          f"Disruption: {ls_eval.demand_weighted_disruption:.2f} | Obj: {ls_eval.objective_value:.4f}")

    # 3. Approach C: Constrained Genetic Algorithm across multiple random seeds
    ga_evaluations: List[RouteEvaluation] = []
    ga_histories: List[List[float]] = []

    for seed in ga_seeds:
        t_ga = time.time()
        ga = ConstrainedGeneticAlgorithm(
            stops=stops,
            cost_matrix=cost_matrix,
            baseline_dist_m=base_eval.distance_km * 1000.0,
            baseline_time_s=base_eval.estimated_travel_time_min * 60.0,
            pop_size=pop_size,
            n_generations=n_generations,
            alpha=alpha, beta=beta, gamma=gamma,
            max_displacement=max_displacement,
            max_detour_ratio=max_detour_ratio,
            random_seed=seed,
        )
        best_seq, best_obj, hist = ga.run()
        ga_histories.append(hist)

        d_m, t_s, _ = cost_matrix.evaluate_sequence(best_seq)
        feasible, reason = is_candidate_feasible(
            best_seq, stops, cost_matrix, base_eval.distance_km * 1000,
            max_displacement, max_detour_ratio
        )
        disp = calculate_demand_disruption(stops, best_seq)
        nodes, coords = cost_matrix.get_full_trajectory(best_seq)
        exec_time = time.time() - t_ga

        eval_record = RouteEvaluation(
            route=route_name,
            direction=direction,
            chart_no=chart_no,
            model=f"Constrained_GA_seed{seed}",
            routing_status="Feasible" if feasible else reason,
            distance_km=d_m / 1000.0,
            estimated_travel_time_min=t_s / 60.0,
            stops_retained_pct=100.0,
            historical_boardings_retained=base_eval.historical_boardings_retained,
            historical_alightings_retained=base_eval.historical_alightings_retained,
            demand_weighted_disruption=disp,
            historical_max_volume=base_eval.historical_max_volume,
            historical_daily_ridership=base_eval.historical_daily_ridership,
            historical_load_factor=base_eval.historical_load_factor,
            estimated_fleet_requirement=None,
            modeled_operating_cost_rs=None,
            objective_value=best_obj,
            execution_time_s=exec_time,
            stop_sequence_order=best_seq,
            road_path_nodes=nodes,
            road_coordinates=coords,
        )
        ga_evaluations.append(eval_record)

    # Pick overall best GA candidate
    best_ga = min(ga_evaluations, key=lambda r: r.objective_value)
    best_ga.model = "Constrained_GA_Best"

    # GA multi-seed statistics
    ga_objs = [r.objective_value for r in ga_evaluations]
    ga_dists = [r.distance_km for r in ga_evaluations]
    ga_runtimes = [r.execution_time_s for r in ga_evaluations]

    stats = {
        "best_objective": float(np.min(ga_objs)),
        "mean_objective": float(np.mean(ga_objs)),
        "std_objective": float(np.std(ga_objs)),
        "best_distance_km": float(np.min(ga_dists)),
        "mean_distance_km": float(np.mean(ga_dists)),
        "std_distance_km": float(np.std(ga_dists)),
        "mean_runtime_s": float(np.mean(ga_runtimes)),
        "convergence_histories": ga_histories,
    }

    print(f"[Approach C - GA Best] Distance: {best_ga.distance_km:.2f} km "
          f"({(1 - best_ga.distance_km / base_eval.distance_km) * 100 if base_eval.distance_km else 0:+.2f}%) | "
          f"Disruption: {best_ga.demand_weighted_disruption:.2f} | Obj: {best_ga.objective_value:.4f}")
    print(f"                      Mean Obj: {stats['mean_objective']:.4f} (std: {stats['std_objective']:.4f}) | "
          f"Avg Runtime: {stats['mean_runtime_s']:.2f}s")

    all_results = [base_eval, ls_eval, best_ga]
    if perf_row is not None:
        fields = {
            "historical_daily_ridership": "Daily Ridership",
            "historical_load_factor": "Load Factor",
            "historical_route_length_km": "Route Length (km)",
            "historical_on_road_fleet": "On road Fleet",
            "historical_vehicle_km": "Actual Veh. Km",
            "historical_expenditure_rs": "Total Expenditure (Rs)",
        }
        for result in all_results:
            for attr, column in fields.items():
                setattr(result, attr, performance_number(perf_row, column))
            _, result.modeled_operating_cost_rs = evaluate_operational_scenarios(result, perf_row)
    return all_results, stats


# =============================================================================
# EXPORT AND ARTIFACT GENERATION
# =============================================================================

def export_results_to_files(
    evaluations: List[RouteEvaluation],
    all_stops_data: Dict[Tuple[str, str, int], List[StopOccurrence]],
    output_dir: Path,
    graphml_path: Path = DEFAULT_GRAPHML,
):
    """
    Exports:
      1. outputs/route_comparison.csv
      2. outputs/optimized_routes.csv
      3. outputs/optimized_paths.geojson
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    graph_source = str(graphml_path)
    baselines = {(r.chart_no, r.model.removesuffix("Reconstructed_Baseline")): r
                 for r in evaluations if r.model.endswith("Reconstructed_Baseline")}
    rows = []
    for r in evaluations:
        profile = re.sub(r"(Reconstructed_Baseline|Constrained_Local_Search|Constrained_GA_Best)$", "", r.model)
        baseline = baselines.get((r.chart_no, profile))
        rows.append({
            "Route": r.route,
            "Direction": r.direction,
            "Chart Number": r.chart_no,
            "Model": r.model,
            "Routing Status": r.routing_status,
            "Road Network": graph_source,
            "Distance Improvement (%)": improvement_pct(baseline.distance_km, r.distance_km) if baseline else None,
            "Objective Improvement (%)": improvement_pct(baseline.objective_value, r.objective_value) if baseline else None,
            "Distance (km)": round(r.distance_km, 3) if r.distance_km is not None else None,
            "Estimated Travel Time (min)": round(r.estimated_travel_time_min, 2) if r.estimated_travel_time_min is not None else None,
            "Stops Retained (%)": r.stops_retained_pct,
            "Historical Boardings Retained": r.historical_boardings_retained,
            "Historical Alightings Retained": r.historical_alightings_retained,
            "Demand-Weighted Disruption": round(r.demand_weighted_disruption, 3),
            "Historical Maximum Volume": r.historical_max_volume,
            "Historical Daily Ridership": r.historical_daily_ridership,
            "Historical Load Factor": round(r.historical_load_factor, 3) if r.historical_load_factor is not None else None,
            "Historical Route Length (km)": r.historical_route_length_km,
            "Historical On-Road Fleet": r.historical_on_road_fleet,
            "Historical Vehicle-km": r.historical_vehicle_km,
            "Historical Expenditure (Rs)": r.historical_expenditure_rs,
            "Modeled Round-Trip Fleet Requirement": r.estimated_fleet_requirement,
            "Modeled Operating Cost per Traversal (Rs)": round(r.modeled_operating_cost_rs, 2) if r.modeled_operating_cost_rs is not None else None,
            "Objective Value": round(r.objective_value, 4),
            "Execution Time (s)": round(r.execution_time_s, 3),
        })
    comp_df = pd.DataFrame(rows)
    comp_path = output_dir / "route_comparison.csv"
    comp_df.to_csv(comp_path, index=False)
    print(f"[Export] Saved comparison table -> {comp_path}")

    if (output_dir / "results").exists():
        comp_df.to_csv(output_dir / "results" / "route_comparison.csv", index=False)

    seq_rows = []
    for r in evaluations:
        key = (r.route, r.direction, r.chart_no)
        stops = all_stops_data.get(key, [])
        if not stops:
            continue
        for new_pos, occ_idx in enumerate(r.stop_sequence_order, start=1):
            s = stops[occ_idx]
            seq_rows.append({
                "route": r.route,
                "direction": r.direction,
                "chart_no": r.chart_no,
                "model": r.model,
                "optimized_stop_order": new_pos,
                "original_stop_order": s.original_order,
                "chart_label": s.chart_label,
                "ctu_stop_id": s.ctu_stop_id,
                "ctu_stop_name": s.ctu_stop_name,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "Boardings": s.boardings,
                "Alightings": s.alightings,
                "Volume": s.volume,
                "osm_node": s.osm_node,
                "snap_distance_m": round(s.snap_distance_m, 2),
                "snap_exceeds_threshold": s.snap_exceeds_threshold,
                "road_network": graph_source,
            })
    opt_df = pd.DataFrame(seq_rows)
    opt_path = output_dir / "optimized_routes.csv"
    opt_df.to_csv(opt_path, index=False)
    print(f"[Export] Saved stop sequences -> {opt_path}")

    geojson_features = []
    for r in evaluations:
        if len(r.road_coordinates) < 2:
            continue
        coords_lon_lat = [[pt[1], pt[0]] for pt in r.road_coordinates]
        feature = {
            "type": "Feature",
            "properties": {
                "route": r.route,
                "direction": r.direction,
                "chart_no": r.chart_no,
                "model": r.model,
                "road_network": graph_source,
                "distance_km": round(r.distance_km, 3),
                "estimated_travel_time_min": round(r.estimated_travel_time_min, 2),
                "demand_weighted_disruption": round(r.demand_weighted_disruption, 3),
                "objective_value": round(r.objective_value, 4),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coords_lon_lat,
            },
        }
        geojson_features.append(feature)

    geojson_obj = {
        "type": "FeatureCollection",
        "features": geojson_features,
        "road_network": graph_source,
    }
    geojson_path = output_dir / "optimized_paths.geojson"
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(geojson_obj, f, indent=2)
    print(f"[Export] Saved GeoJSON paths -> {geojson_path}")


def generate_comparison_plot(
    evaluations: List[RouteEvaluation],
    output_dir: Path,
):
    """
    Generates comparison.png.
    If <= 8 routes: compares Distance, Time, and Disruption side-by-side.
    If > 8 routes (full network): plots improvement distribution, Pareto trade-off,
    and top-performing route distance reductions.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([asdict(r) for r in evaluations])
    if df.empty:
        return

    df = df[df["model"].isin(["Reconstructed_Baseline", "Constrained_Local_Search", "Constrained_GA_Best"])]
    charts = df["chart_no"].unique()

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    if len(charts) <= 8:
        # Pilot / Single-route mode: 3 bar charts
        models = ["Reconstructed_Baseline", "Constrained_Local_Search", "Constrained_GA_Best"]
        labels = ["Baseline", "Local Search", "Constrained GA"]
        colors = ["#7f7f7f", "#ff7f0e", "#2ca02c"]

        x = np.arange(len(charts))
        width = 0.25

        # 1. Distance
        for idx, (m, lbl, col) in enumerate(zip(models, labels, colors)):
            vals = []
            for c_id in charts:
                sub = df[(df["chart_no"] == c_id) & (df["model"] == m)]
                vals.append(sub["distance_km"].values[0] if not sub.empty else 0.0)
            axes[0].bar(x + (idx - 1) * width, vals, width=width, label=lbl, color=col)

        axes[0].set_title("Road Network Distance (km)", fontsize=11, fontweight="bold")
        axes[0].set_xticks(x)
        axes[0].set_xticklabels([f"Ch-{c}" for c in charts])
        axes[0].set_ylabel("Distance (km)")
        axes[0].grid(axis="y", linestyle="--", alpha=0.5)

        # 2. Time
        for idx, (m, lbl, col) in enumerate(zip(models, labels, colors)):
            vals = []
            for c_id in charts:
                sub = df[(df["chart_no"] == c_id) & (df["model"] == m)]
                vals.append(sub["estimated_travel_time_min"].values[0] if not sub.empty else 0.0)
            axes[1].bar(x + (idx - 1) * width, vals, width=width, label=lbl, color=col)

        axes[1].set_title("Estimated Travel Time (min)", fontsize=11, fontweight="bold")
        axes[1].set_xticks(x)
        axes[1].set_xticklabels([f"Ch-{c}" for c in charts])
        axes[1].set_ylabel("Minutes")
        axes[1].grid(axis="y", linestyle="--", alpha=0.5)

        # 3. Disruption
        for idx, (m, lbl, col) in enumerate(zip(models, labels, colors)):
            vals = []
            for c_id in charts:
                sub = df[(df["chart_no"] == c_id) & (df["model"] == m)]
                vals.append(sub["demand_weighted_disruption"].values[0] if not sub.empty else 0.0)
            axes[2].bar(x + (idx - 1) * width, vals, width=width, label=lbl, color=col)

        axes[2].set_title("Demand-Weighted Disruption", fontsize=11, fontweight="bold")
        axes[2].set_xticks(x)
        axes[2].set_xticklabels([f"Ch-{c}" for c in charts])
        axes[2].set_ylabel("Weighted Stop Displacement")
        axes[2].grid(axis="y", linestyle="--", alpha=0.5)
        axes[2].legend(loc="upper right")

    else:
        # Full-dataset network mode (>8 charts)
        # Compute improvements per chart
        chart_data = []
        for c_id in charts:
            sub_b = df[(df["chart_no"] == c_id) & (df["model"] == "Reconstructed_Baseline")]
            sub_ga = df[(df["chart_no"] == c_id) & (df["model"] == "Constrained_GA_Best")]
            sub_ls = df[(df["chart_no"] == c_id) & (df["model"] == "Constrained_Local_Search")]
            if not sub_b.empty and not sub_ga.empty:
                b_dist = sub_b["distance_km"].values[0]
                ga_dist = sub_ga["distance_km"].values[0]
                ls_dist = sub_ls["distance_km"].values[0] if not sub_ls.empty else b_dist
                r_name = sub_b["route"].values[0]
                r_dir = sub_b["direction"].values[0]
                imp_pct = ((b_dist - ga_dist) / b_dist) * 100.0 if b_dist > 0 else 0.0
                disp = sub_ga["demand_weighted_disruption"].values[0]
                chart_data.append({
                    "chart_no": c_id, "route": r_name, "direction": r_dir,
                    "b_dist": b_dist, "ls_dist": ls_dist, "ga_dist": ga_dist,
                    "imp_pct": imp_pct, "disruption": disp
                })

        cdf = pd.DataFrame(chart_data)

        # Panel 1: Histogram of Distance Improvement Percentage
        axes[0].hist(cdf["imp_pct"], bins=15, color="#1f77b4", edgecolor="black", alpha=0.8)
        axes[0].axvline(0, color="gray", linestyle="--", linewidth=1.5)
        axes[0].set_title(f"Distance Reduction Distribution (N={len(cdf)})", fontsize=11, fontweight="bold")
        axes[0].set_xlabel("Distance Improvement (%)")
        axes[0].set_ylabel("Number of Directional Charts")
        axes[0].grid(axis="y", linestyle="--", alpha=0.5)

        # Panel 2: Distance Reduction vs. Disruption Scatter Plot
        scatter = axes[1].scatter(cdf["imp_pct"], cdf["disruption"], color="#2ca02c", edgecolors="black", s=45, alpha=0.85)
        axes[1].set_title("Distance Reduction vs. Disruption", fontsize=11, fontweight="bold")
        axes[1].set_xlabel("Distance Improvement (%)")
        axes[1].set_ylabel("Demand-Weighted Disruption")
        axes[1].grid(True, linestyle="--", alpha=0.5)

        # Panel 3: Top Improved Charts Bar Comparison
        top_improved = cdf[cdf["imp_pct"] > 0].nlargest(5, "imp_pct")
        if not top_improved.empty:
            tx = np.arange(len(top_improved))
            twidth = 0.25
            axes[2].bar(tx - twidth, top_improved["b_dist"], width=twidth, label="Baseline", color="#7f7f7f")
            axes[2].bar(tx, top_improved["ls_dist"], width=twidth, label="Local Search", color="#ff7f0e")
            axes[2].bar(tx + twidth, top_improved["ga_dist"], width=twidth, label="GA Best", color="#2ca02c")
            axes[2].set_title("Top 5 Improved Routes (km)", fontsize=11, fontweight="bold")
            axes[2].set_xticks(tx)
            axes[2].set_xticklabels([f"R{r.route} {r.direction}" for _, r in top_improved.iterrows()], rotation=15, ha="right", fontsize=9)
            axes[2].set_ylabel("Distance (km)")
            axes[2].grid(axis="y", linestyle="--", alpha=0.5)
            axes[2].legend(loc="upper right")

    plt.suptitle("CTU Local Bus Route Optimization - Empirical Model Comparison", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()

    plot_path = output_dir / "comparison.png"
    plt.savefig(plot_path, dpi=200, bbox_inches="tight")
    print(f"[Export] Saved comparison plot -> {plot_path}")

    if (output_dir / "figures").exists():
        plt.savefig(output_dir / "figures" / "comparison.png", dpi=200, bbox_inches="tight")
    plt.close()


# =============================================================================
# CLI INTERFACE
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Data-Driven Geographical Bus Route Optimization for Chandigarh CTU Local Bus Network"
    )
    parser.add_argument("--route", type=str, default=None, help="Route identifier (e.g., '3', '11', '17')")
    parser.add_argument("--direction", type=str, default=None, help="Direction ('UP' or 'DOWN')")
    parser.add_argument("--chart", type=int, default=None, help="Specific chart number to optimize")
    parser.add_argument("--all", action="store_true", help="Process every directional chart")
    parser.add_argument("--perf-csv", type=str,
                        default="data/passengerdata/performance_routes_clean.csv",
                        help="Path to performance parameters CSV")
    parser.add_argument("--graphml", type=str,
                        default=str(DEFAULT_GRAPHML),
                        help="Path to road network GraphML")
    parser.add_argument("--output-dir", type=str, default="outputs", help="Output directory")

    parser.add_argument("--max-snap-m", type=float, default=DEFAULT_MAX_SNAP_M,
                        help="Flag stop snaps beyond this distance in metres")
    parser.add_argument("--corridor-m", type=float, default=None,
                        help="Maximum distance of route geometry vertices from the baseline road path")
    parser.add_argument("--verified-headway-minutes", action="store_true",
                        help="Use peak headways after confirming units and a shared directional interval")

    # GA & Sensitivity parameters
    parser.add_argument("--alpha", type=float, default=0.5, help="Distance weight in objective")
    parser.add_argument("--beta", type=float, default=0.2, help="Travel time weight in objective")
    parser.add_argument("--gamma", type=float, default=0.3, help="Demand disruption weight in objective")
    parser.add_argument("--max-displacement", type=int, default=3, help="Max stop position displacement")
    parser.add_argument("--max-detour-ratio", type=float, default=1.25, help="Max allowed detour ratio")
    parser.add_argument("--pop-size", type=int, default=50, help="GA population size")
    parser.add_argument("--generations", type=int, default=60, help="GA generations")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 101, 2024, 7, 999],
                        help="Random seeds for GA evaluation")
    parser.add_argument("--sensitivity", action="store_true",
                        help="Run multi-objective weight sensitivity analysis (Distance-focused, Balanced, Demand-focused)")

    args = parser.parse_args()
    try:
        validate_weights(args.alpha, args.beta, args.gamma)
    except ValueError as exc:
        parser.error(str(exc))
    if (not math.isfinite(args.max_snap_m) or args.max_snap_m < 0
            or (args.corridor_m is not None and (not math.isfinite(args.corridor_m) or args.corridor_m < 0))
            or not math.isfinite(args.max_detour_ratio) or args.max_detour_ratio < 1
            or args.max_displacement < 0 or args.pop_size < 1 or args.generations < 0):
        parser.error("Invalid routing constraints or GA configuration")
    return args


def improvement_pct(baseline: float, candidate: float) -> Optional[float]:
    return 100 * (baseline - candidate) / baseline if baseline > 0 else None


def main():
    args = parse_args()

    project_root = Path.cwd()
    passenger_csv = project_root / "data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV"
    perf_csv = project_root / args.perf_csv
    graphml_path = project_root / args.graphml
    output_dir = project_root / args.output_dir

    if not passenger_csv.exists():
        sys.exit(f"Error: Passenger CSV not found at {passenger_csv}")
    if not graphml_path.exists():
        sys.exit(f"Error: Road network GraphML not found at {graphml_path}")

    df_passenger = load_passenger_data(passenger_csv)
    df_perf = load_performance_data(perf_csv)
    road_net = RoadNetwork(graphml_path, args.max_snap_m)

    if args.chart is not None:
        target_df = df_passenger[df_passenger["chart_no"] == args.chart]
        if target_df.empty:
            sys.exit(f"Error: Chart number {args.chart} not found.")
        target_groups = [target_df]
    elif args.route is not None:
        route_str = str(args.route).strip()
        matched = df_passenger[df_passenger["route"].str.upper() == route_str.upper()]
        if args.direction:
            matched = matched[matched["direction"].str.upper() == args.direction.strip().upper()]
        if matched.empty:
            sys.exit(f"Error: No records found for Route {args.route} {args.direction or ''}")
        target_groups = [g for g in discover_charts(df_passenger) if g.index.isin(matched.index).any()]
    elif args.all:
        # Dynamically discover and process EVERY chart in the primary dataset (all 118 directional charts)
        target_groups = discover_charts(df_passenger)
        print(f"\n[Batch Mode] Dynamically discovered {len(target_groups)} directional charts across the CTU bus network.")
    else:
        sub = df_passenger[(df_passenger["route"] == "3") & (df_passenger["direction"] == "UP")]
        c_num = sub["chart_no"].iloc[0]
        target_groups = [sub[sub["chart_no"] == c_num]]

    all_evaluations: List[RouteEvaluation] = []
    all_stops_dict: Dict[Tuple[str, str, int], List[StopOccurrence]] = {}

    profiles = [("", args.alpha, args.beta, args.gamma)]
    if args.sensitivity:
        profiles = [
            ("Distance_Focused_", 0.8, 0.1, 0.1),
            ("Balanced_", 0.5, 0.2, 0.3),
            ("Demand_Preservation_Focused_", 0.2, 0.1, 0.7),
        ]

    report = []
    failures = []
    for idx, chart in enumerate(target_groups, start=1):
        first = chart.iloc[0]
        record = {"chart_no": first.chart_no, "route": first.route, "direction": first.direction,
                  "road_network": args.graphml}
        print(f"[{idx}/{len(target_groups)}] Chart {first.chart_no}: {first.route} {first.direction}")
        try:
            stops = extract_stop_occurrences(chart, road_net)
            far = [f"{s.original_order} ({s.snap_distance_m:.1f} m)" for s in stops if s.snap_exceeds_threshold]
            if far:
                print(f"[Snapping] Stops beyond {args.max_snap_m:g} m: {', '.join(far)}")
            chart_results = []
            for prefix, alpha, beta, gamma in profiles:
                results, _ = optimize_route_chart(
                    chart, road_net, df_perf, alpha=alpha, beta=beta, gamma=gamma,
                    max_displacement=args.max_displacement, max_detour_ratio=args.max_detour_ratio,
                    ga_seeds=args.seeds, pop_size=args.pop_size, n_generations=args.generations,
                    corridor_m=args.corridor_m, stops=stops,
                )
                for result in results:
                    result.model = prefix + result.model
                chart_results.extend(results)
            all_evaluations.extend(chart_results)
            key = (stops[0].route, stops[0].direction, stops[0].chart_no)
            all_stops_dict[key] = stops
            baseline, local, ga = chart_results[3:6] if args.sensitivity else chart_results
            record.update(
                status="improved" if min(ga.objective_value, local.objective_value)
                < baseline.objective_value - 1e-10 else "unchanged",
                ga_objective_improved=ga.objective_value < baseline.objective_value - 1e-10,
                local_search_objective_improved=local.objective_value < baseline.objective_value - 1e-10,
                ga_distance_improved=ga.distance_km < baseline.distance_km - 1e-9,
                local_search_distance_improved=local.distance_km < baseline.distance_km - 1e-9,
                max_snap_distance_m=max(s.snap_distance_m for s in stops),
                distant_snap_count=len(far),
            )
        except Exception as exc:
            if isinstance(exc, InvalidChart):
                status = "invalid_data"
            elif isinstance(exc, InfeasibleChart):
                status = "infeasible"
            else:
                status = "runtime_error"
            record["status"] = status
            detail = str(exc) if status != "runtime_error" else traceback.format_exc()
            failures.append({**record, "source_lines": ",".join(map(str, chart["_source_line"])),
                             "detail": detail})
            print(f"[{status}] {exc}")
        report.append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report).to_csv(output_dir / "chart_processing.csv", index=False)
    pd.DataFrame(failures, columns=["chart_no", "route", "direction", "road_network", "status",
                                   "source_lines", "detail"]).to_csv(output_dir / "chart_failures.csv", index=False)
    tally = pd.Series([row["status"] for row in report]).value_counts()
    print(f"Discovered: {len(report)} | Processed: {int(tally.get('improved', 0) + tally.get('unchanged', 0))}")
    for status in ("improved", "unchanged", "infeasible", "invalid_data", "runtime_error"):
        print(f"{status}: {tally.get(status, 0)}")
    for model in ("ga", "local_search"):
        for metric in ("distance", "objective"):
            key = f"{model}_{metric}_improved"
            print(f"{key}: {sum(row.get(key, False) for row in report)}")

    if not all_evaluations:
        sys.exit("No feasible charts to export. See chart_failures.csv.")
    if args.verified_headway_minutes:
        apply_fleet_scenarios(all_evaluations, all_stops_dict, df_passenger, df_perf)
    export_results_to_files(all_evaluations, all_stops_dict, output_dir, Path(args.graphml))
    plot_evaluations = all_evaluations
    if args.sensitivity:
        plot_evaluations = [replace(r, model=r.model.removeprefix("Balanced_"))
                            for r in all_evaluations if r.model.startswith("Balanced_")]
    generate_comparison_plot(plot_evaluations, output_dir)

    # Generate interactive Folium comparison map
    try:
        from src.visualisation.plot_bus_routes import build_comparison_map, load_stop_data
        opt_routes_path = output_dir / "optimized_routes.csv"
        geojson_path = output_dir / "optimized_paths.geojson"
        html_path = output_dir / "route_map.html"
        if opt_routes_path.exists():
            stops_df = load_stop_data(opt_routes_path)
            folium_map = build_comparison_map(stops_df, geojson_path=geojson_path)
            folium_map.save(str(html_path))
            print(f"[Export] Saved interactive map -> {html_path}")
            if (output_dir / "maps").exists():
                folium_map.save(str(output_dir / "maps" / "route_map.html"))
    except Exception as e:
        sys.exit(f"Interactive map generation failed: {e}")

    print("\nOptimization completed successfully.")


if __name__ == "__main__":
    main()
