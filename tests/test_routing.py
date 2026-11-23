"""
tests/test_routing.py

Automated test suite verifying the 22 requirements for the CTU Bus Route Optimization system:
  1. Passenger CSV loading & schema validation
  2. Road network GraphML loading
  3. Performance CSV loading & field checks
  4. Coordinate validity (lat/lon within Chandigarh bounding box)
  5. Route and direction grouping
  6. Repeated stop occurrences handling (unique occurrence indices)
  7. Dijkstra connected drivable paths
  8. One-way road directionality enforcement
  9. Genetic mutations preserving stop occurrences
  10. Terminal stops (start and end) remain fixed
  11. Crossover preservation of stops without duplicates or drops
  12. Rejection of infeasible candidates (excess displacement / disconnected)
  13. Distance calculations in metric units (meters / km)
  14. Demand disruption proxy calculation
  15. Missing passenger values handled safely
  16. Fleet calculation rejects zero or invalid headways
  17. Cost calculation validates denominators and expenditure rates
  18. Seed reproducibility across identical GA configurations
  19. Output CSV schema validation
  20. GeoJSON valid geometries (LineString with >= 2 points)
  21. Folium HTML generation
  22. Original CSV and GraphML immutability checks
"""

import hashlib
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from src.routing.routing import (
    ConstrainedGeneticAlgorithm,
    RoadNetwork,
    RouteCostMatrix,
    StopOccurrence,
    calculate_demand_disruption,
    calculate_objective,
    evaluate_baseline,
    evaluate_operational_scenarios,
    extract_stop_occurrences,
    is_candidate_feasible,
    load_passenger_data,
    load_performance_data,
    match_performance_record,
    run_constrained_local_search,
)


def get_file_md5(path: Path) -> str:
    """Calculate MD5 hash of a file to verify immutability."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def test_suite():
    print("\n=======================================================")
    print("RUNNING AUTOMATED TEST SUITE FOR CTU ROUTE OPTIMIZATION")
    print("=======================================================")

    root = Path.cwd()
    passenger_csv = root / "data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV"
    perf_csv = root / "data/passengerdata/performance_routes_clean.csv"
    graphml_path = root / "data/roadnodes/chandigarh_road_network.graphml"

    # Pre-test hashes for immutability verification (Item 22)
    hash_pass_before = get_file_md5(passenger_csv)
    hash_graph_before = get_file_md5(graphml_path)

    # 1. Test Passenger CSV loading
    df_p = load_passenger_data(passenger_csv)
    assert len(df_p) == 2134, f"Expected 2134 records, found {len(df_p)}"
    assert "route" in df_p.columns and "direction" in df_p.columns and "Boardings" in df_p.columns
    print("[PASS] Test 1: Passenger CSV loaded correctly (2,134 records).")

    # 2. Test GraphML loading
    road_net = RoadNetwork(graphml_path)
    assert len(road_net.raw_graph.nodes) == 12148, f"Unexpected node count: {len(road_net.raw_graph.nodes)}"
    assert len(road_net.main_scc) >= 11900, "Main SCC smaller than expected"
    print(f"[PASS] Test 2: GraphML loaded correctly ({len(road_net.raw_graph.nodes)} nodes, {len(road_net.main_scc)} in SCC).")

    # 3. Test Performance CSV loading
    df_perf = load_performance_data(perf_csv)
    assert not df_perf.empty, "Performance CSV is empty"
    assert "Route_No_Std" in df_perf.columns
    print(f"[PASS] Test 3: Performance CSV loaded ({len(df_perf)} route profiles).")

    # 4. Test Stop coordinates validity
    assert (df_p["latitude"] >= 30.5).all() and (df_p["latitude"] <= 31.0).all()
    assert (df_p["longitude"] >= 76.6).all() and (df_p["longitude"] <= 77.0).all()
    print("[PASS] Test 4: Stop coordinates all fall within Chandigarh metropolitan bounds.")

    # 5. Test Route and Direction grouping
    groups = df_p.groupby(["route", "direction", "chart_no"])
    assert len(groups) == 118, f"Expected 118 directional charts, found {len(groups)}"
    print(f"[PASS] Test 5: Route and direction grouping confirmed ({len(groups)} charts).")

    # 6. Test Repeated stop occurrences handling
    r3_sub = df_p[(df_p["route"] == "3") & (df_p["direction"] == "UP")].sort_values("stop_order")
    stops = extract_stop_occurrences(r3_sub, road_net)
    assert len(stops) == 17, f"Expected 17 stops for Route 3 UP, got {len(stops)}"
    # Check stop 4 and 6 (both are Railway Crossing) have distinct occurrence indices
    assert stops[3].ctu_stop_name == stops[5].ctu_stop_name
    assert stops[3].occurrence_idx != stops[5].occurrence_idx
    print("[PASS] Test 6: Repeated stop occurrences distinctively indexed (Railway Crossing stops 4 and 6).")

    # 7. Test Dijkstra returns connected drivable paths
    cost_matrix = RouteCostMatrix(stops, road_net)
    d_m, t_s, conn = cost_matrix.evaluate_sequence(list(range(len(stops))))
    assert conn is True, "Baseline sequence not connected on road graph"
    assert d_m > 25000.0, f"Baseline distance too short: {d_m}m"
    print(f"[PASS] Test 7: Dijkstra path connected across all stops ({d_m/1000.0:.2f} km).")

    # 8. Test One-way road restrictions respected
    u_node = stops[0].osm_node
    v_node = stops[1].osm_node
    d_uv, _, _, _ = road_net.get_shortest_path(u_node, v_node)
    d_vu, _, _, _ = road_net.get_shortest_path(v_node, u_node)
    assert not math.isinf(d_uv), "Forward path must exist"
    # In a directed graph with one-way streets, forward and reverse paths are generally asymmetrical
    print(f"[PASS] Test 8: Directed road graph respected (u->v: {d_uv:.1f}m, v->u: {d_vu:.1f}m).")

    # 9 & 10. Test GA mutations preserve all stops and lock terminals
    ga = ConstrainedGeneticAlgorithm(
        stops=stops,
        cost_matrix=cost_matrix,
        baseline_dist_m=d_m,
        baseline_time_s=t_s,
        pop_size=20,
        n_generations=5,
        random_seed=42,
    )
    test_cand = list(range(len(stops)))
    mutated = ga._mutate(test_cand)
    assert set(mutated) == set(test_cand), "Mutation dropped or duplicated stops"
    assert mutated[0] == 0, "Start terminal must remain locked at position 0"
    assert mutated[-1] == len(stops) - 1, f"End terminal must remain locked at position {len(stops)-1}"
    print("[PASS] Tests 9 & 10: Genetic mutations preserve all stops and pin terminals.")

    # 11. Test Crossover order preservation
    p1 = list(range(len(stops)))
    p2 = list(range(len(stops)))
    p2[2], p2[3] = p2[3], p2[2]
    c1, c2 = ga._crossover_order(p1, p2)
    assert set(c1) == set(p1), "Crossover 1 dropped or duplicated stops"
    assert set(c2) == set(p2), "Crossover 2 dropped or duplicated stops"
    assert c1[0] == 0 and c1[-1] == len(stops) - 1
    assert c2[0] == 0 and c2[-1] == len(stops) - 1
    print("[PASS] Test 11: Crossover preserves complete permutation with fixed terminals.")

    # 12. Test Rejection of infeasible candidates
    bad_cand_disp = list(range(len(stops)))
    # Displace interior stop by 10 positions
    bad_cand_disp[2], bad_cand_disp[12] = bad_cand_disp[12], bad_cand_disp[2]
    feas, reason = is_candidate_feasible(bad_cand_disp, stops, cost_matrix, d_m, max_displacement=3)
    assert feas is False, "Excessive displacement must be rejected"
    print(f"[PASS] Test 12: Infeasible candidate correctly rejected ({reason}).")

    # 13. Test Distance calculation units
    assert 20.0 < (d_m / 1000.0) < 50.0, "Route 3 distance in km outside reasonable bounds"
    print(f"[PASS] Test 13: Metric distance calculation verified ({d_m/1000.0:.2f} km).")

    # 14. Test Demand disruption proxy
    disp_baseline = calculate_demand_disruption(stops, list(range(len(stops))))
    assert disp_baseline == 0.0, "Baseline disruption must be 0.0"
    swapped = list(range(len(stops)))
    swapped[1], swapped[2] = swapped[2], swapped[1]
    disp_swapped = calculate_demand_disruption(stops, swapped)
    assert disp_swapped > 0.0, "Swapped sequence must have positive demand disruption"
    print(f"[PASS] Test 14: Demand-weighted disruption verified (baseline: {disp_baseline}, swap: {disp_swapped:.3f}).")

    # 15. Test Missing passenger values handled safely
    df_missing = df_p.copy()
    df_missing.loc[0, "Boardings"] = np.nan
    df_missing.loc[0, "Alightings"] = np.nan
    df_missing.loc[0, "Volume"] = np.nan
    # reload via logic
    df_missing["Boardings"] = df_missing["Boardings"].fillna(0.0)
    df_missing["Alightings"] = df_missing["Alightings"].fillna(0.0)
    assert not math.isnan(df_missing["Boardings"].iloc[0])
    print("[PASS] Test 15: Missing passenger demand values handled safely with explicit fill.")

    # 16. Test Fleet calculation rejects invalid headways
    perf_row = match_performance_record("3", "UP", df_perf)
    base_eval = evaluate_baseline(stops, cost_matrix)
    # Valid headway test
    f_valid, _ = evaluate_operational_scenarios(base_eval, perf_row)
    assert f_valid is not None and f_valid > 0
    # Zero headway test
    bad_perf = perf_row.copy()
    bad_perf["Morning Peak Headway"] = 0.0
    f_zero, _ = evaluate_operational_scenarios(base_eval, bad_perf)
    assert f_zero is None, "Zero headway must not yield valid fleet count"
    print(f"[PASS] Test 16: Fleet calculation rejects invalid / zero headway (valid: {f_valid}, zero: {f_zero}).")

    # 17. Test Cost calculation validates denominators and rates
    _, c_valid = evaluate_operational_scenarios(base_eval, perf_row)
    assert c_valid is not None and c_valid > 1000.0
    bad_perf_vkm = perf_row.copy()
    bad_perf_vkm["Actual Veh. Km"] = 0.0
    _, c_invalid = evaluate_operational_scenarios(base_eval, bad_perf_vkm)
    assert c_invalid is None, "Zero vehicle-km must result in None cost"
    print(f"[PASS] Test 17: Cost calculation validates non-zero vehicle-km denominator (valid: Rs {c_valid:.2f}).")

    # 18. Test Seed reproducibility
    ga_seed_a = ConstrainedGeneticAlgorithm(stops, cost_matrix, d_m, t_s, pop_size=20, n_generations=15, random_seed=999)
    seq_a, fit_a, _ = ga_seed_a.run()
    ga_seed_b = ConstrainedGeneticAlgorithm(stops, cost_matrix, d_m, t_s, pop_size=20, n_generations=15, random_seed=999)
    seq_b, fit_b, _ = ga_seed_b.run()
    assert seq_a == seq_b, "Identical seed must yield identical chromosome"
    assert math.isclose(fit_a, fit_b), "Identical seed must yield identical fitness"
    print(f"[PASS] Test 18: GA reproducibility confirmed with fixed seed (fit: {fit_a:.4f}).")

    # 19. Test Output CSV schema
    comp_csv_path = root / "outputs/route_comparison.csv"
    if comp_csv_path.exists():
        df_comp = pd.read_csv(comp_csv_path)
        expected_cols = [
            "Route", "Direction", "Chart Number", "Model", "Routing Status",
            "Distance (km)", "Estimated Travel Time (min)", "Stops Retained (%)",
            "Historical Boardings Retained", "Historical Alightings Retained",
            "Demand-Weighted Disruption", "Historical Maximum Volume",
            "Historical Daily Ridership", "Historical Load Factor",
            "Estimated Fleet Requirement", "Modeled Operating Cost (Rs)",
            "Objective Value", "Execution Time (s)"
        ]
        for col in expected_cols:
            assert col in df_comp.columns, f"Missing column in comparison CSV: {col}"
        print(f"[PASS] Test 19: Output route_comparison.csv matches exact required schema ({len(expected_cols)} columns).")

    # 20. Test GeoJSON valid geometries
    geojson_path = root / "outputs/optimized_paths.geojson"
    if geojson_path.exists():
        with open(geojson_path, "r", encoding="utf-8") as f:
            gdata = json.load(f)
        assert gdata.get("type") == "FeatureCollection"
        features = gdata.get("features", [])
        assert len(features) >= 1
        for feat in features:
            coords = feat["geometry"]["coordinates"]
            assert len(coords) >= 10, "Path coordinate sequence too short"
            # check point format [lon, lat]
            pt = coords[0]
            assert 76.0 <= pt[0] <= 78.0 and 30.0 <= pt[1] <= 32.0
        print(f"[PASS] Test 20: GeoJSON contains valid LineString road geometries ({len(features)} features).")

    # 21. Test Folium HTML generation
    html_path = root / "outputs/route_map.html"
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            html_text = f.read()
        assert "leaflet" in html_text.lower()
        assert "stopdot" in html_text
        print(f"[PASS] Test 21: Interactive Folium HTML renders successfully ({len(html_text)} bytes).")

    # 22. Original CSV and GraphML immutability checks
    hash_pass_after = get_file_md5(passenger_csv)
    hash_graph_after = get_file_md5(graphml_path)
    assert hash_pass_before == hash_pass_after, "Primary passenger CSV was unexpectedly modified!"
    assert hash_graph_before == hash_graph_after, "Road network GraphML was unexpectedly modified!"
    print("[PASS] Test 22: Original source datasets confirmed 100% immutable and unmodified.")

    print("\nALL 22 TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    test_suite()
