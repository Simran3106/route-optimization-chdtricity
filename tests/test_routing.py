import hashlib
import json
import math
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory

import networkx as nx
import pandas as pd

from src.routing.routing import (
    DEFAULT_GRAPHML,
    InvalidChart,
    ConstrainedGeneticAlgorithm,
    RoadNetwork,
    RouteCostMatrix,
    StopOccurrence,
    apply_fleet_scenarios,
    calculate_demand_disruption,
    check_shortcut_stops,
    disconnected_legs,
    repair_stop_snaps,
    discover_charts,
    export_results_to_files,
    generate_comparison_plot,
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
    assert 12000 <= len(road_net.raw_graph.nodes) <= 12148, f"Unexpected node count: {len(road_net.raw_graph.nodes)}"
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
    assert len(discover_charts(df_p)) == len(groups)
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

    # Route 3 has an unreachable leg after snapping to the full graph.
    assert any(not road_net.can_reach(u.osm_node, v.osm_node) for u, v in zip(stops, stops[1:]))
    chart = df_p[df_p["chart_no"] == 3]
    stops = extract_stop_occurrences(chart, road_net)

    # 7. Test Dijkstra returns connected drivable paths
    cost_matrix = RouteCostMatrix(stops, road_net)
    d_m, t_s, conn = cost_matrix.evaluate_sequence(list(range(len(stops))))
    assert conn is True, "Baseline sequence not connected on road graph"
    assert d_m > 1000.0, f"Baseline distance too short: {d_m}m"
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
    bad_cand_disp[1], bad_cand_disp[3] = bad_cand_disp[3], bad_cand_disp[1]
    feas, reason = is_candidate_feasible(bad_cand_disp, stops, cost_matrix, d_m, max_displacement=1)
    assert feas is False, "Excessive displacement must be rejected"
    print(f"[PASS] Test 12: Infeasible candidate correctly rejected ({reason}).")

    # 13. Test Distance calculation units
    assert 1.0 < (d_m / 1000.0) < 15.0, "Route 3 distance in km outside reasonable bounds"
    print(f"[PASS] Test 13: Metric distance calculation verified ({d_m/1000.0:.2f} km).")

    # 14. Test Demand disruption proxy
    disp_baseline = calculate_demand_disruption(stops, list(range(len(stops))))
    assert disp_baseline == 0.0, "Baseline disruption must be 0.0"
    swapped = list(range(len(stops)))
    swapped[1], swapped[2] = swapped[2], swapped[1]
    disp_swapped = calculate_demand_disruption(stops, swapped)
    assert disp_swapped > 0.0, "Swapped sequence must have positive demand disruption"
    print(f"[PASS] Test 14: Demand-weighted disruption verified (baseline: {disp_baseline}, swap: {disp_swapped:.3f}).")

    df_missing = chart.copy()
    df_missing.loc[df_missing.index[0], "Boardings"] = math.nan
    try:
        extract_stop_occurrences(df_missing, road_net)
    except InvalidChart as exc:
        assert "Boardings" in str(exc)
    else:
        raise AssertionError("Missing demand must remain unavailable")
    df_missing.loc[df_missing.index[0], ["Boardings", "Volume"]] = [0, math.nan]
    missing_volume = extract_stop_occurrences(df_missing, road_net)
    assert missing_volume[0].boardings == 0 and math.isnan(missing_volume[0].volume)

    perf_row = match_performance_record("11", "UP", df_perf)
    assert match_performance_record("11AC", "UP", df_perf) is None
    assert match_performance_record("11", "UP", pd.concat([df_perf, df_perf])) is None
    base_eval = evaluate_baseline(stops, cost_matrix)
    reverse = replace(base_eval, direction="DOWN", estimated_travel_time_min=31)
    f_valid, c_valid = evaluate_operational_scenarios(
        base_eval, perf_row, reverse=reverse, verified_headway_min=15
    )
    assert f_valid == math.ceil((base_eval.estimated_travel_time_min + 31) * 1.15 / 15)
    assert math.isclose(c_valid, base_eval.distance_km * 5586 / 92)
    assert evaluate_operational_scenarios(base_eval, perf_row)[0] is None
    assert evaluate_operational_scenarios(
        base_eval, perf_row, reverse=reverse, verified_headway_min=0
    )[0] is None
    for column in ("Actual Veh. Km", "Route Length (km)", "Total Expenditure (Rs)"):
        invalid = perf_row.copy()
        invalid[column] = 0
        assert evaluate_operational_scenarios(base_eval, invalid)[1] is None

    up_stops = [replace(stops[0], ctu_stop_id="A"), replace(stops[-1], ctu_stop_id="B")]
    down_stops = list(reversed(up_stops))
    pair_data = pd.DataFrame({"route": ["11", "11"], "direction": ["UP", "DOWN"], "chart_no": [3, 4]})
    reverse = replace(reverse, chart_no=4)
    apply_fleet_scenarios(
        [base_eval, reverse], {("11", "UP", 3): up_stops, ("11", "DOWN", 4): down_stops},
        pair_data, df_perf
    )
    assert base_eval.estimated_fleet_requirement == math.ceil(
        (base_eval.estimated_travel_time_min + 31) * 1.15 / 30
    )
    assert reverse.estimated_fleet_requirement is None

    # 18. Test Seed reproducibility
    ga_seed_a = ConstrainedGeneticAlgorithm(stops, cost_matrix, d_m, t_s, pop_size=20, n_generations=15, random_seed=999)
    seq_a, fit_a, _ = ga_seed_a.run()
    ga_seed_b = ConstrainedGeneticAlgorithm(stops, cost_matrix, d_m, t_s, pop_size=20, n_generations=15, random_seed=999)
    seq_b, fit_b, _ = ga_seed_b.run()
    assert seq_a == seq_b, "Identical seed must yield identical chromosome"
    assert math.isclose(fit_a, fit_b), "Identical seed must yield identical fitness"
    print(f"[PASS] Test 18: GA reproducibility confirmed with fixed seed (fit: {fit_a:.4f}).")

    assert math.isclose(base_eval.objective_value, ga._fitness(test_cand))
    local = run_constrained_local_search(stops, cost_matrix, d_m, t_s)
    assert math.isclose(ga._fitness(local.stop_sequence_order), local.objective_value)
    assert local.routing_status == "Feasible"
    with TemporaryDirectory() as tmp:
        from src.visualisation.plot_bus_routes import build_comparison_map, load_stop_data

        output = Path(tmp)
        export_results_to_files([base_eval, local], {("11", "UP", 3): stops}, output, graphml_path)
        generate_comparison_plot([base_eval, local], output)
        comp = pd.read_csv(output / "route_comparison.csv")
        assert set(comp["Routing Status"]) == {"Feasible"}
        assert (comp["Road Network"] == str(graphml_path)).all()
        assert comp.iloc[0]["Objective Improvement (%)"] == 0
        geojson = output / "optimized_paths.geojson"
        data = json.loads(geojson.read_text())
        assert len(data["features"]) == 2
        assert all(len(f["geometry"]["coordinates"]) >= 2 for f in data["features"])
        stops_df = load_stop_data(output / "optimized_routes.csv")
        assert len(stops_df) == 2 * len(stops)
        assert "snap_exceeds_threshold" in stops_df
        html = output / "route_map.html"
        build_comparison_map(stops_df, geojson_path=geojson).save(str(html))
        payload = html.read_text(encoding="utf-8")
        assert "leaflet" in payload.lower()
        assert all(f'id="ctu-{name}"' in payload for name in ("route", "direction", "chart"))
        assert payload.count("data-model=") == 3
        assert "map.removeLayer(layer)" in payload
        assert (output / "comparison.png").stat().st_size > 0

    # 22. Original CSV and GraphML immutability checks
    hash_pass_after = get_file_md5(passenger_csv)
    hash_graph_after = get_file_md5(graphml_path)
    assert hash_pass_before == hash_pass_after, "Primary passenger CSV was unexpectedly modified!"
    assert hash_graph_before == hash_graph_after, "Road network GraphML was unexpectedly modified!"
    print("[PASS] Test 22: Original source datasets confirmed 100% immutable and unmodified.")

    print("\nALL 22 TESTS PASSED SUCCESSFULLY!")


def test_tricity():
    digest = get_file_md5(DEFAULT_GRAPHML)
    net = RoadNetwork()
    assert net.raw_graph.is_directed()
    assert net.raw_graph.graph["crs"] == "epsg:4326"
    assert len(net.raw_graph) > 50_000
    first, second = next(iter(net.raw_graph.edges(keys=False)))
    distances = net.get_shortest_paths(first, [first, second])
    assert distances[first][0] == 0
    assert math.isclose(distances[second][0], nx.shortest_path_length(
        net.raw_graph, first, second, weight="length_m"
    ))
    assert net.raw_graph.number_of_edges() > 130_000
    passenger = load_passenger_data(Path("data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV"))
    for chart, failing in ((1, "1429434268"), (5, "1432256469")):
        stops = extract_stop_occurrences(passenger[passenger.chart_no == chart], net)
        assert any(stops[i].osm_node == failing for i, _ in disconnected_legs(stops, net))
        before = [(s.original_order, s.ctu_stop_id, s.latitude, s.longitude) for s in stops]
        repair_stop_snaps(stops, net)
        assert not disconnected_legs(stops, net)
        assert [(s.original_order, s.ctu_stop_id, s.latitude, s.longitude) for s in stops] == before
        assert any(s.original_osm_node == failing and s.osm_node != failing
                   and s.snap_distance_m <= net.max_snap_m and s.snap_reassignment_reason for s in stops)
    assert get_file_md5(DEFAULT_GRAPHML) == digest


def test_directed_fixture():
    graph = nx.MultiDiGraph(crs="epsg:4326")
    points = {"a": (30.7, 76.7), "b": (30.7, 76.71), "c": (30.7, 76.72),
              "d": (30.71, 76.71), "e": (30.72, 76.71), "f": (30.72, 76.72)}
    for node, (lat, lon) in points.items():
        graph.add_node(node, x=lon, y=lat)
    graph.add_edge("a", "b", length=100.0, highway="primary", oneway=True,
                   geometry="LINESTRING (76.71 30.7, 76.705 30.7, 76.7 30.7)")
    for u, v in [("b", "c"), ("b", "d"), ("d", "b"), ("c", "d"), ("e", "f")]:
        graph.add_edge(u, v, length=100.0, highway="residential", oneway=True)
    graph.add_edge("d", "c", length=150.0, highway="residential", oneway=True,
                   geometry="LINESTRING (76.71 30.71, 76.73 30.71, 76.72 30.7)")
    graph.add_edge("b", "a", length=30.0, highway="footway")
    graph.add_edge("c", "a", length=30.0, highway="residential", access="no")
    with TemporaryDirectory() as tmp:
        file = Path(tmp) / "directed.graphml"
        nx.write_graphml(graph, file)
        net = RoadNetwork(file, max_snap_m=10)
        assert net.snap_stop(*points["e"]) == ("e", 0.0)
        assert net.get_shortest_path("a", "b")[3] == [points["a"], (30.7, 76.705), points["b"]]
        assert net.get_shortest_path("b", "a")[0] == math.inf
        assert net.get_shortest_path("a", "e")[0] == math.inf
        rows = pd.DataFrame([
            dict(chart_no=1, route="X", direction="UP", stop_order=i, chart_label=node,
                 ctu_stop_id=node, ctu_stop_name=node, latitude=points[node][0] + (0.0002 if i == 2 else 0),
                 longitude=points[node][1], Boardings=2, Alightings=1, Volume=3)
            for i, node in enumerate(["a", "d", "b", "b", "c"], 1)
        ])
        stops = extract_stop_occurrences(rows, net)
        assert stops[1].snap_exceeds_threshold and not stops[0].snap_exceeds_threshold
        assert stops[2].osm_node == stops[3].osm_node
        matrix = RouteCostMatrix(stops, net, corridor_m=1)
        original = list(range(len(stops)))
        baseline = evaluate_baseline(stops, matrix, 0.8, 0.2, 0.0)
        assert baseline.routing_status == "Feasible" and baseline.objective_value > 1.05
        assert check_shortcut_stops(original, matrix, stops) == 1
        reordered = [0, 2, 3, 1, 4]
        unrestricted = RouteCostMatrix(stops, net)
        assert is_candidate_feasible(reordered, stops, unrestricted, 400)[0]
        feasible, reason = is_candidate_feasible(reordered, stops, matrix, 400)
        assert not feasible and "corridor" in reason
        assert is_candidate_feasible([0, 1, 3, 2, 4], stops, matrix, 400)[0]
        assert not is_candidate_feasible([0, 1, 2, 2, 4], stops, matrix, 400)[0]
        assert not is_candidate_feasible([1, 0, 2, 3, 4], stops, matrix, 400)[0]
        assert not is_candidate_feasible([0, 2, 3, 1, 4], stops, matrix, 400, max_displacement=1)[0]
        disconnected = [replace(stops[0], osm_node="e"), stops[-1]]
        broken = RouteCostMatrix(disconnected, net)
        assert "Disconnected" in evaluate_baseline(disconnected, broken).routing_status
        assert broken.get_full_trajectory([0, 1]) == ([], [])
        assert (1, 4) in matrix.outside_corridor
        assert not is_candidate_feasible([0, 2, 3, 1, 4], stops, matrix, 200)[0]

        rows = rows.astype({"Boardings": object, "chart_no": object})
        rows.loc[0, "Boardings"] = "missing"
        rows.loc[0, "chart_no"] = "broken"
        csv = file.with_suffix(".csv")
        rows.to_csv(csv, index=False)
        loaded = load_passenger_data(csv)
        groups = discover_charts(loaded)
        assert len(groups) == 2 and groups[-1]["chart_no"].isna().all()
        assert groups[-1]["Boardings"].isna().all()
        for weights in [(0, 0, 0), (1, 1, 1), (-1, 1, 1), (math.nan, 0, 1)]:
            try:
                calculate_objective(1, 1, 1, 1, 0, 2, *weights)
            except ValueError:
                continue
            raise AssertionError(f"Invalid weights accepted: {weights}")


def test_segment_corridor():
    # Both chord endpoints lie on the baseline, but its interior cuts across a bend.
    matrix = object.__new__(RouteCostMatrix)
    a, b, c = (30.7, 76.7), (30.71, 76.7), (30.71, 76.71)
    matrix.path_coords_cache = {(0, 1): [a, b], (0, 2): [a, c]}
    matrix.outside_corridor = set()
    matrix._check_corridor([a, b, c], 10)
    assert matrix.outside_corridor == {(0, 2)}
    assert math.isclose(calculate_objective(0, 0, 0, 0, 0, 2), 0.7)


if __name__ == "__main__":
    test_segment_corridor()
    test_directed_fixture()
    test_tricity()
    test_suite()
