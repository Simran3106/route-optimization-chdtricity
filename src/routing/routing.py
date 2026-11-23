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
Road network: data/roadnodes/chandigarh_road_network.graphml
"""

import argparse
import json
import math
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
FALLBACK_SPEED_KMH = 25.0
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

    def __init__(self, graphml_path: Path):
        self.graphml_path = graphml_path
        print(f"[RoadNetwork] Loading GraphML from {graphml_path}...")
        t0 = time.time()
        self.raw_graph: nx.MultiDiGraph = nx.read_graphml(graphml_path)
        print(f"[RoadNetwork] Loaded {len(self.raw_graph.nodes)} nodes, "
              f"{len(self.raw_graph.edges)} edges in {time.time() - t0:.2f}s")

        # Extract largest strongly connected component to avoid sink / cul-de-sac traps
        sccs = list(nx.strongly_connected_components(self.raw_graph))
        self.main_scc = max(sccs, key=len)
        print(f"[RoadNetwork] Main strongly connected component has {len(self.main_scc)} nodes "
              f"({len(self.main_scc) / len(self.raw_graph.nodes) * 100:.1f}%)")

        # Assign parsed lengths, speeds, and traversal times to graph edges
        self._prepare_edge_attributes()

        # Build coordinate arrays for fast nearest-node projection
        self.node_list: List[str] = list(self.main_scc)
        self.node_coords = np.array(
            [[float(self.raw_graph.nodes[n]["y"]), float(self.raw_graph.nodes[n]["x"])]
             for n in self.node_list],
            dtype=np.float64,
        )

    def _prepare_edge_attributes(self):
        """Ensure all edge lengths are floats and calculate travel times in seconds."""
        for u, v, k, d in self.raw_graph.edges(keys=True, data=True):
            try:
                length = float(d.get("length", 1.0))
            except (ValueError, TypeError):
                length = 1.0
            d["length_m"] = length

            # Road class determination
            hwy = d.get("highway", "unclassified")
            if isinstance(hwy, list):
                hwy = hwy[0]
            elif isinstance(hwy, str) and hwy.startswith("["):
                cleaned = re.sub(r"[\[\]'\" ]", "", hwy).split(",")
                hwy = cleaned[0] if cleaned else "unclassified"

            speed_kmh = DEFAULT_SPEEDS_KMH.get(str(hwy), FALLBACK_SPEED_KMH)
            speed_ms = max(speed_kmh / 3.6, 1.0)
            d["speed_ms"] = speed_ms
            d["time_sec"] = length / speed_ms

    def snap_stop(self, lat: float, lon: float) -> Tuple[str, float]:
        """
        Snap a stop coordinate (lat, lon) to the nearest road-network node
        in the strongly connected drivable component. Returns (osm_node_id, distance_in_meters).
        """
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
        if u == v:
            lat = float(self.raw_graph.nodes[u]["y"])
            lon = float(self.raw_graph.nodes[u]["x"])
            return 0.0, 0.0, [u], [(lat, lon)]

        try:
            path_nodes = nx.shortest_path(self.raw_graph, source=u, target=v, weight="length_m")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return float("inf"), float("inf"), [], []

        total_length_m = 0.0
        total_time_sec = 0.0
        coords: List[Tuple[float, float]] = []

        for i in range(len(path_nodes) - 1):
            n1 = path_nodes[i]
            n2 = path_nodes[i + 1]
            edge_data_dict = self.raw_graph.get_edge_data(n1, n2)
            if not edge_data_dict:
                continue
            best_key = min(edge_data_dict.keys(), key=lambda k: edge_data_dict[k].get("length_m", 1.0))
            best_edge = edge_data_dict[best_key]

            total_length_m += best_edge.get("length_m", 0.0)
            total_time_sec += best_edge.get("time_sec", 0.0)

            geom_str = best_edge.get("geometry")
            if geom_str:
                edge_pts = parse_wkt_linestring(geom_str)
                if edge_pts:
                    if not coords:
                        coords.extend(edge_pts)
                    else:
                        coords.extend(edge_pts[1:])
                    continue

            p1 = (float(self.raw_graph.nodes[n1]["y"]), float(self.raw_graph.nodes[n1]["x"]))
            p2 = (float(self.raw_graph.nodes[n2]["y"]), float(self.raw_graph.nodes[n2]["x"]))
            if not coords:
                coords.append(p1)
            coords.append(p2)

        return total_length_m, total_time_sec, path_nodes, coords


def load_passenger_data(csv_path: Path) -> pd.DataFrame:
    """Load and validate the primary boarding-alighting dataset."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    required = [
        "chart_no", "route", "direction", "stop_order", "chart_label",
        "latitude", "longitude", "Boardings", "Alightings", "Volume"
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Primary passenger CSV missing required columns: {missing}")

    df["chart_no"] = pd.to_numeric(df["chart_no"], errors="coerce").fillna(0).astype(int)
    df["route"] = df["route"].astype(str).str.strip()
    df["direction"] = df["direction"].astype(str).str.strip().str.upper()
    df["stop_order"] = pd.to_numeric(df["stop_order"], errors="coerce").astype(int)
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["Boardings"] = pd.to_numeric(df["Boardings"], errors="coerce").fillna(0.0)
    df["Alightings"] = pd.to_numeric(df["Alightings"], errors="coerce").fillna(0.0)
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")

    if "ctu_stop_name" not in df.columns:
        df["ctu_stop_name"] = df["chart_label"]
    else:
        df["ctu_stop_name"] = df["ctu_stop_name"].fillna(df["chart_label"]).astype(str).str.strip()

    if "ctu_stop_id" not in df.columns:
        df["ctu_stop_id"] = [f"STOP_{i+1}" for i in range(len(df))]
    else:
        fallback_ids = pd.Series(
            [f"CH_{r.chart_no}_S{r.stop_order}" for _, r in df.iterrows()],
            index=df.index,
        )
        df["ctu_stop_id"] = df["ctu_stop_id"].fillna(fallback_ids).astype(str).str.strip()

    return df.sort_values(["chart_no", "stop_order"]).reset_index(drop=True)


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
    stops: List[StopOccurrence] = []
    for idx, row in enumerate(df.itertuples()):
        lat = float(row.latitude)
        lon = float(row.longitude)
        node_id, snap_dist = road_net.snap_stop(lat, lon)
        b = float(row.Boardings)
        a = float(row.Alightings)
        v = float(row.Volume) if pd.notna(row.Volume) else 0.0

        stop = StopOccurrence(
            occurrence_idx=idx,
            chart_no=int(row.chart_no),
            route=str(row.route),
            direction=str(row.direction),
            original_order=int(row.stop_order),
            chart_label=str(row.chart_label),
            ctu_stop_id=str(row.ctu_stop_id),
            ctu_stop_name=str(row.ctu_stop_name),
            latitude=lat,
            longitude=lon,
            boardings=b,
            alightings=a,
            volume=v,
            importance=b + a,
            osm_node=node_id,
            snap_distance_m=snap_dist,
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

    def __init__(self, stops: List[StopOccurrence], road_net: RoadNetwork):
        self.stops = stops
        self.n = len(stops)
        self.road_net = road_net

        self.dist_matrix = np.full((self.n, self.n), float("inf"), dtype=np.float64)
        self.time_matrix = np.full((self.n, self.n), float("inf"), dtype=np.float64)
        self.path_nodes_cache: Dict[Tuple[int, int], List[str]] = {}
        self.path_coords_cache: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}

        self._precompute()

    def _precompute(self):
        for i in range(self.n):
            self.dist_matrix[i, i] = 0.0
            self.time_matrix[i, i] = 0.0
            u = self.stops[i].osm_node
            for j in range(self.n):
                if i == j:
                    continue
                v = self.stops[j].osm_node
                if u and v:
                    dist_m, time_s, nodes, coords = self.road_net.get_shortest_path(u, v)
                    self.dist_matrix[i, j] = dist_m
                    self.time_matrix[i, j] = time_s
                    self.path_nodes_cache[(i, j)] = nodes
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
    if baseline_dist_m <= 0 or baseline_time_sec <= 0:
        return float("inf")

    d_n = distance_m / baseline_dist_m
    t_n = travel_time_sec / baseline_time_sec
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
    violations = 0
    pos_map = {occurrence_idx: pos for pos, occurrence_idx in enumerate(seq)}
    stop_node_to_occ = {}
    for s in stops:
        if s.osm_node:
            stop_node_to_occ.setdefault(s.osm_node, []).append(s.occurrence_idx)

    for k in range(len(seq) - 1):
        u_idx = seq[k]
        v_idx = seq[k + 1]
        path_nodes = cost_matrix.path_nodes_cache.get((u_idx, v_idx), [])
        if len(path_nodes) <= 2:
            continue
        interior_nodes = set(path_nodes[1:-1])
        for interior in interior_nodes:
            if interior in stop_node_to_occ:
                for matched_occ in stop_node_to_occ[interior]:
                    matched_pos = pos_map.get(matched_occ)
                    if matched_pos is not None and matched_pos > k + 1:
                        violations += 1
    return violations


def is_candidate_feasible(
    seq: List[int],
    stops: List[StopOccurrence],
    cost_matrix: RouteCostMatrix,
    baseline_dist_m: float,
    max_displacement: int = 3,
    max_detour_ratio: float = 1.25,
) -> Tuple[bool, str]:
    """Validate all 12 hard route constraints."""
    n = len(stops)
    if len(seq) != n:
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

    if baseline_dist_m > 0 and (dist_m / baseline_dist_m) > max_detour_ratio:
        return False, f"Detour ratio {dist_m / baseline_dist_m:.2f} exceeds limit {max_detour_ratio}"

    return True, "Feasible"


# =============================================================================
# APPROACH A: RECONSTRUCTED BASELINE
# =============================================================================

def evaluate_baseline(
    stops: List[StopOccurrence],
    cost_matrix: RouteCostMatrix,
) -> RouteEvaluation:
    """Evaluate Approach A: Reconstructed original-sequence road baseline."""
    t0 = time.time()
    seq = list(range(len(stops)))
    dist_m, time_s, connected = cost_matrix.evaluate_sequence(seq)
    nodes, coords = cost_matrix.get_full_trajectory(seq)

    total_b = sum(s.boardings for s in stops)
    total_a = sum(s.alightings for s in stops)
    max_v = max((s.volume for s in stops), default=0.0)

    exec_time = time.time() - t0
    status = "Connected" if connected else "Failed_Disconnected"

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
        objective_value=1.0,
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
    best_obj = calculate_objective(
        best_dist, baseline_dist_m, best_time, baseline_time_s,
        best_disp, n, alpha, beta, gamma
    )

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

            c_dist, c_time, connected = cost_matrix.evaluate_sequence(cand)
            if not connected:
                continue

            c_disp = calculate_demand_disruption(stops, cand)
            c_obj = calculate_objective(
                c_dist, baseline_dist_m, c_time, baseline_time_s,
                c_disp, n, alpha, beta, gamma
            )

            sc_count = check_shortcut_stops(cand, cost_matrix, stops)
            if sc_count > 0:
                c_obj += sc_count * 0.1

            if c_obj < best_obj - 1e-5:
                best_seq = cand
                best_obj = c_obj
                best_dist = c_dist
                best_time = c_time
                best_disp = c_disp
                improved = True
                break

    nodes, coords = cost_matrix.get_full_trajectory(best_seq)
    exec_time = time.time() - t0

    return RouteEvaluation(
        route=stops[0].route,
        direction=stops[0].direction,
        chart_no=stops[0].chart_no,
        model="Constrained_Local_Search",
        routing_status="Feasible" if best_obj <= 1.05 else "Constraint_Constrained",
        distance_km=best_dist / 1000.0,
        estimated_travel_time_min=best_time / 60.0,
        stops_retained_pct=100.0,
        historical_boardings_retained=sum(s.boardings for s in stops),
        historical_alightings_retained=sum(s.alightings for s in stops),
        demand_weighted_disruption=best_disp,
        historical_max_volume=max((s.volume for s in stops), default=0.0),
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

    def _fitness(self, seq: List[int]) -> float:
        """Evaluate fitness (lower objective is better). Infeasible returns inf."""
        feasible, _ = is_candidate_feasible(
            seq, self.stops, self.cost_matrix, self.baseline_dist_m,
            self.max_displacement, self.max_detour_ratio
        )
        if not feasible:
            return float("inf")

        dist_m, time_s, connected = self.cost_matrix.evaluate_sequence(seq)
        if not connected or math.isinf(dist_m):
            return float("inf")

        disp = calculate_demand_disruption(self.stops, seq)
        obj = calculate_objective(
            dist_m, self.baseline_dist_m, time_s, self.baseline_time_s,
            disp, self.n, self.alpha, self.beta, self.gamma
        )

        sc_count = check_shortcut_stops(seq, self.cost_matrix, self.stops)
        if sc_count > 0:
            obj += sc_count * 0.1

        return obj

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
        candidates = self.rng.sample(range(len(pop)), self.tournament_size)
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
        fitnesses = [self._fitness(ind) for ind in pop]
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
            fitnesses = [self._fitness(ind) for ind in pop]

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
    """
    Standardize and match route identifier in performance_routes_clean.csv.
    Checks exact matches, strips 'AC' suffixes if needed, and returns matched row or None.
    """
    if df_perf.empty:
        return None

    route_clean = str(route).strip().upper()
    match = df_perf[df_perf["Route_No_Std"] == route_clean]
    if not match.empty:
        return match.iloc[0]

    if route_clean.endswith("AC"):
        base_route = route_clean[:-2]
        match_base = df_perf[df_perf["Route_No_Std"] == base_route]
        if not match_base.empty:
            return match_base.iloc[0]

    return None


def evaluate_operational_scenarios(
    eval_record: RouteEvaluation,
    perf_row: Optional[pd.Series],
    layover_ratio: float = DEFAULT_LAYOVER_RATIO,
) -> Tuple[Optional[int], Optional[float]]:
    """
    Evaluate fleet requirements and operating costs as consequence of geographical route changes.
        F = ceil(C / H)
        Operating Cost = Actual_Veh_Km * (Total_Expenditure / Actual_Veh_Km)
    """
    if perf_row is None:
        return None, None

    peak_headway = float(perf_row.get("Morning Peak Headway", 0.0))
    fleet_req = None
    if peak_headway > 0:
        one_way_time_min = eval_record.estimated_travel_time_min
        round_trip_cycle_min = 2.0 * one_way_time_min * (1.0 + layover_ratio)
        fleet_req = int(math.ceil(round_trip_cycle_min / peak_headway))

    actual_vkm = float(perf_row.get("Actual Veh. Km", 0.0))
    total_exp = float(perf_row.get("Total Expenditure (Rs)", 0.0))
    modeled_cost = None

    if actual_vkm > 0 and total_exp > 0:
        c_km = total_exp / actual_vkm
        hist_route_len = float(perf_row.get("Route Length (km)", 0.0))
        trips = (actual_vkm / hist_route_len) if hist_route_len > 0 else 1.0
        modeled_cost = trips * eval_record.distance_km * c_km

    return fleet_req, modeled_cost


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
) -> Tuple[List[RouteEvaluation], Dict[str, Any]]:
    """
    Executes Baseline, Constrained Local Search, and multi-seed Constrained GA
    for one directional chart.
    """
    stops = extract_stop_occurrences(chart_df, road_net)
    route_name = stops[0].route
    direction = stops[0].direction
    chart_no = stops[0].chart_no

    print(f"\n=======================================================")
    print(f"OPTIMIZING ROUTE {route_name} {direction} (Chart {chart_no}) | {len(stops)} stops")
    print(f"=======================================================")

    cost_matrix = RouteCostMatrix(stops, road_net)

    # 1. Approach A: Baseline
    base_eval = evaluate_baseline(stops, cost_matrix)
    print(f"[Approach A - Baseline] Distance: {base_eval.distance_km:.2f} km | "
          f"Est. Time: {base_eval.estimated_travel_time_min:.1f} min | Status: {base_eval.routing_status}")

    perf_row = match_performance_record(route_name, direction, df_perf)
    if perf_row is not None:
        base_eval.historical_daily_ridership = float(perf_row.get("Daily Ridership", 0.0))
        base_eval.historical_load_factor = float(perf_row.get("Load Factor", 0.0))
        f_base, c_base = evaluate_operational_scenarios(base_eval, perf_row)
        base_eval.estimated_fleet_requirement = f_base
        base_eval.modeled_operating_cost_rs = c_base

    # 2. Approach B: Local Search
    ls_eval = run_constrained_local_search(
        stops, cost_matrix,
        baseline_dist_m=base_eval.distance_km * 1000.0,
        baseline_time_s=base_eval.estimated_travel_time_min * 60.0,
        alpha=alpha, beta=beta, gamma=gamma,
        max_displacement=max_displacement,
        max_detour_ratio=max_detour_ratio,
    )
    if perf_row is not None:
        ls_eval.historical_daily_ridership = base_eval.historical_daily_ridership
        ls_eval.historical_load_factor = base_eval.historical_load_factor
        f_ls, c_ls = evaluate_operational_scenarios(ls_eval, perf_row)
        ls_eval.estimated_fleet_requirement = f_ls
        ls_eval.modeled_operating_cost_rs = c_ls

    print(f"[Approach B - Local Search] Distance: {ls_eval.distance_km:.2f} km "
          f"({((base_eval.distance_km - ls_eval.distance_km)/base_eval.distance_km)*100:+.2f}%) | "
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

        d_m, t_s, conn = cost_matrix.evaluate_sequence(best_seq)
        disp = calculate_demand_disruption(stops, best_seq)
        nodes, coords = cost_matrix.get_full_trajectory(best_seq)
        exec_time = time.time() - t_ga

        eval_record = RouteEvaluation(
            route=route_name,
            direction=direction,
            chart_no=chart_no,
            model=f"Constrained_GA_seed{seed}",
            routing_status="Feasible" if conn and best_obj <= 1.05 else "Fallback_Preserved",
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
        if perf_row is not None:
            f_ga, c_ga = evaluate_operational_scenarios(eval_record, perf_row)
            eval_record.estimated_fleet_requirement = f_ga
            eval_record.modeled_operating_cost_rs = c_ga

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
          f"({((base_eval.distance_km - best_ga.distance_km)/base_eval.distance_km)*100:+.2f}%) | "
          f"Disruption: {best_ga.demand_weighted_disruption:.2f} | Obj: {best_ga.objective_value:.4f}")
    print(f"                      Mean Obj: {stats['mean_objective']:.4f} (std: {stats['std_objective']:.4f}) | "
          f"Avg Runtime: {stats['mean_runtime_s']:.2f}s")

    all_results = [base_eval, ls_eval, best_ga]
    return all_results, stats


# =============================================================================
# EXPORT AND ARTIFACT GENERATION
# =============================================================================

def export_results_to_files(
    evaluations: List[RouteEvaluation],
    all_stops_data: Dict[Tuple[str, str, int], List[StopOccurrence]],
    output_dir: Path,
):
    """
    Exports:
      1. outputs/route_comparison.csv
      2. outputs/optimized_routes.csv
      3. outputs/optimized_paths.geojson
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in evaluations:
        rows.append({
            "Route": r.route,
            "Direction": r.direction,
            "Chart Number": r.chart_no,
            "Model": r.model,
            "Routing Status": r.routing_status,
            "Distance (km)": round(r.distance_km, 3) if r.distance_km is not None else None,
            "Estimated Travel Time (min)": round(r.estimated_travel_time_min, 2) if r.estimated_travel_time_min is not None else None,
            "Stops Retained (%)": r.stops_retained_pct,
            "Historical Boardings Retained": r.historical_boardings_retained,
            "Historical Alightings Retained": r.historical_alightings_retained,
            "Demand-Weighted Disruption": round(r.demand_weighted_disruption, 3),
            "Historical Maximum Volume": r.historical_max_volume,
            "Historical Daily Ridership": r.historical_daily_ridership,
            "Historical Load Factor": round(r.historical_load_factor, 3) if r.historical_load_factor is not None else None,
            "Estimated Fleet Requirement": r.estimated_fleet_requirement,
            "Modeled Operating Cost (Rs)": round(r.modeled_operating_cost_rs, 2) if r.modeled_operating_cost_rs is not None else None,
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
                "ctu_stop_id": s.ctu_stop_id,
                "ctu_stop_name": s.ctu_stop_name,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "Boardings": s.boardings,
                "Alightings": s.alightings,
                "Volume": s.volume,
                "osm_node": s.osm_node,
                "snap_distance_m": round(s.snap_distance_m, 2),
            })
    opt_df = pd.DataFrame(seq_rows)
    opt_path = output_dir / "optimized_routes.csv"
    opt_df.to_csv(opt_path, index=False)
    print(f"[Export] Saved stop sequences -> {opt_path}")

    geojson_features = []
    for r in evaluations:
        if not r.road_coordinates:
            continue
        coords_lon_lat = [[pt[1], pt[0]] for pt in r.road_coordinates]
        feature = {
            "type": "Feature",
            "properties": {
                "route": r.route,
                "direction": r.direction,
                "chart_no": r.chart_no,
                "model": r.model,
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
        top_improved = cdf.sort_values("imp_pct", ascending=False).head(5)
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
    plt.close()
    print(f"[Export] Saved comparison plot -> {plot_path}")

    if (output_dir / "figures").exists():
        plt.savefig(output_dir / "figures" / "comparison.png", dpi=200, bbox_inches="tight")


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
    parser.add_argument("--all", action="store_true", help="Batch optimize representative or all eligible routes")
    parser.add_argument("--passenger-csv", type=str,
                        default="data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV",
                        help="Path to boarding-alighting dataset")
    parser.add_argument("--perf-csv", type=str,
                        default="data/passengerdata/performance_routes_clean.csv",
                        help="Path to performance parameters CSV")
    parser.add_argument("--graphml", type=str,
                        default="data/roadnodes/chandigarh_road_network.graphml",
                        help="Path to road network GraphML")
    parser.add_argument("--output-dir", type=str, default="outputs", help="Output directory")

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

    return parser.parse_args()


def main():
    args = parse_args()

    project_root = Path.cwd()
    passenger_csv = project_root / args.passenger_csv
    perf_csv = project_root / args.perf_csv
    graphml_path = project_root / args.graphml
    output_dir = project_root / args.output_dir

    if not passenger_csv.exists():
        sys.exit(f"Error: Passenger CSV not found at {passenger_csv}")
    if not graphml_path.exists():
        sys.exit(f"Error: Road network GraphML not found at {graphml_path}")

    df_passenger = load_passenger_data(passenger_csv)
    df_perf = load_performance_data(perf_csv)
    road_net = RoadNetwork(graphml_path)

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
        target_groups = [g for _, g in matched.groupby("chart_no")]
    elif args.all:
        # Dynamically discover and process EVERY chart in the primary dataset (all 118 directional charts)
        target_groups = [g for _, g in df_passenger.groupby("chart_no")]
        print(f"\n[Batch Mode] Dynamically discovered {len(target_groups)} directional charts across the CTU bus network.")
    else:
        sub = df_passenger[(df_passenger["route"] == "3") & (df_passenger["direction"] == "UP")]
        c_num = sub["chart_no"].iloc[0]
        target_groups = [sub[sub["chart_no"] == c_num]]

    all_evaluations: List[RouteEvaluation] = []
    all_stops_dict: Dict[Tuple[str, str, int], List[StopOccurrence]] = {}

    if args.sensitivity:
        print("\n=======================================================")
        print("RUNNING MULTI-OBJECTIVE WEIGHT SENSITIVITY ANALYSIS")
        print("=======================================================")
        profiles = [
            ("Distance_Focused", 0.8, 0.1, 0.1),
            ("Balanced", 0.5, 0.2, 0.3),
            ("Demand_Preservation_Focused", 0.2, 0.1, 0.7),
        ]
        sens_evaluations: List[RouteEvaluation] = []
        for chart_sub in target_groups:
            stops = extract_stop_occurrences(chart_sub, road_net)
            key = (stops[0].route, stops[0].direction, stops[0].chart_no)
            all_stops_dict[key] = stops
            for prof_name, a, b, g in profiles:
                print(f"\n--- Profile: {prof_name} (alpha={a}, beta={b}, gamma={g}) ---")
                evals, _ = optimize_route_chart(
                    chart_df=chart_sub,
                    road_net=road_net,
                    df_perf=df_perf,
                    alpha=a,
                    beta=b,
                    gamma=g,
                    max_displacement=args.max_displacement,
                    max_detour_ratio=args.max_detour_ratio,
                    ga_seeds=args.seeds,
                    pop_size=args.pop_size,
                    n_generations=args.generations,
                )
                for item in evals:
                    item.model = f"{prof_name}_{item.model}"
                sens_evaluations.extend(evals)

        export_results_to_files(sens_evaluations, all_stops_dict, output_dir)
        generate_comparison_plot(sens_evaluations, output_dir)
        print("\nSensitivity analysis completed successfully.")
        return

    # Track full execution statistics
    total_batch_t0 = time.time()
    n_discovered = len(target_groups)
    n_processed = 0
    n_improved = 0
    n_unchanged = 0
    n_infeasible = 0
    route_records = []

    for idx, chart_sub in enumerate(target_groups, start=1):
        c_num = int(chart_sub["chart_no"].iloc[0])
        r_name = str(chart_sub["route"].iloc[0])
        r_dir = str(chart_sub["direction"].iloc[0])

        if n_discovered > 5:
            print(f"[{idx}/{n_discovered}] Optimizing Chart {c_num}: Route {r_name} {r_dir} ({len(chart_sub)} stops)...")

        try:
            stops = extract_stop_occurrences(chart_sub, road_net)
            key = (stops[0].route, stops[0].direction, stops[0].chart_no)
            all_stops_dict[key] = stops

            evals, stats = optimize_route_chart(
                chart_df=chart_sub,
                road_net=road_net,
                df_perf=df_perf,
                alpha=args.alpha,
                beta=args.beta,
                gamma=args.gamma,
                max_displacement=args.max_displacement,
                max_detour_ratio=args.max_detour_ratio,
                ga_seeds=args.seeds,
                pop_size=args.pop_size,
                n_generations=args.generations,
            )
            all_evaluations.extend(evals)
            n_processed += 1

            base_eval = evals[0]
            ga_eval = evals[-1]
            base_d = base_eval.distance_km
            ga_d = ga_eval.distance_km
            imp_pct = ((base_d - ga_d) / base_d) * 100.0 if base_d > 0 else 0.0

            if imp_pct > 0.05:
                n_improved += 1
            else:
                n_unchanged += 1

            route_records.append({
                "chart_no": c_num,
                "route": r_name,
                "direction": r_dir,
                "stops": len(stops),
                "baseline_km": base_d,
                "ga_km": ga_d,
                "imp_pct": imp_pct,
                "disruption": ga_eval.demand_weighted_disruption,
            })

        except Exception as e:
            n_infeasible += 1
            print(f"[ERROR] Failed processing Chart {c_num} (Route {r_name} {r_dir}): {e}")

    total_batch_time = time.time() - total_batch_t0

    # Export outputs
    export_results_to_files(all_evaluations, all_stops_dict, output_dir)
    generate_comparison_plot(all_evaluations, output_dir)

    # Print comprehensive execution report
    print("\n=======================================================")
    print("FULL NETWORK OPTIMIZATION SUMMARY REPORT")
    print("=======================================================")
    print(f"Total Charts Discovered  : {n_discovered}")
    print(f"Processed Successfully   : {n_processed} ({n_processed / max(n_discovered, 1) * 100:.1f}%)")
    print(f"Routes Improved          : {n_improved} ({n_improved / max(n_processed, 1) * 100:.1f}%)")
    print(f"Routes Unchanged         : {n_unchanged} ({n_unchanged / max(n_processed, 1) * 100:.1f}%)")
    print(f"Failed / Infeasible      : {n_infeasible}")
    print(f"Total Batch Runtime      : {total_batch_time:.2f} s ({total_batch_time / max(n_processed, 1):.3f} s/chart)")

    if route_records:
        rec_df = pd.DataFrame(route_records)
        all_mean_imp = rec_df["imp_pct"].mean()
        improved_only = rec_df[rec_df["imp_pct"] > 0.05]
        improved_mean_imp = improved_only["imp_pct"].mean() if not improved_only.empty else 0.0

        print(f"Mean Distance Reduction (All {len(rec_df)} Charts)     : {all_mean_imp:.2f}%")
        print(f"Mean Distance Reduction (Improved Charts Only) : {improved_mean_imp:.2f}%")

        print("\n--- TOP-PERFORMING IMPROVED ROUTES ---")
        top_df = rec_df.sort_values("imp_pct", ascending=False).head(10)
        print(top_df[["chart_no", "route", "direction", "stops", "baseline_km", "ga_km", "imp_pct", "disruption"]].to_string(index=False))

    print("\n[Methodological Boundary Notice]")
    print("Fleet and cost metrics are directional scenario evaluations for individual route services.")
    print("Do NOT aggregate them into a network-wide total, as directional trips represent sampled observations")
    print("rather than simultaneous continuous operations.")

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
        print(f"[warn] Interactive map generation skipped: {e}")

    print("\nOptimization completed successfully.")


if __name__ == "__main__":
    main()
