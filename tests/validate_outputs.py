"""Check the saved default experiment without running either optimizer."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.routing.routing import (
    DEFAULT_DWELL_TIME_SEC,
    MODEL_NAMES,
    RoadNetwork,
    compare_algorithms,
    discover_charts,
    load_passenger_data,
)


def validate_outputs(directory=Path("outputs")):
    source = load_passenger_data(Path(
        "data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV"
    ))
    reports = pd.read_csv(directory / "chart_processing.csv")
    failures = pd.read_csv(directory / "chart_failures.csv")
    scores = pd.read_csv(directory / "route_comparison.csv").rename(columns={
        "Chart Number": "chart_no", "Model": "model", "Distance (km)": "distance_km",
        "Objective Value": "objective_value", "Execution Time (s)": "execution_time_s",
        "GA Total Across Seeds (s)": "ga_all_seeds_time_s",
    })
    stops = pd.read_csv(directory / "optimized_routes.csv", dtype={
        "route": str, "ctu_stop_id": str, "osm_node": str, "original_osm_node": str,
    })
    geo = json.loads((directory / "optimized_paths.geojson").read_text(encoding="utf-8"))
    summary = json.loads((directory / "comparison_summary.json").read_text(encoding="utf-8"))
    graph = RoadNetwork()

    assert len(reports) == len(discover_charts(source))
    assert set(reports.chart_no) == set(source.chart_no)
    assert reports.chart_no.is_unique
    assert reports.status.isin(["processed", "infeasible", "invalid_data", "runtime_error"]).all()
    processed = set(reports.loc[reports.status.eq("processed"), "chart_no"])
    assert set(failures.chart_no) == set(reports.chart_no) - processed
    assert failures.chart_no.is_unique
    assert failures.detail.notna().all()
    assert set(scores.chart_no) == processed
    assert scores.groupby("chart_no").model.apply(lambda values: set(values) == set(MODEL_NAMES.values())).all()
    assert not scores.duplicated(["chart_no", "model"]).any()
    assert scores["Routing Status"].eq("Feasible").all()
    components = ["Distance Component", "Travel Time Component", "Disruption Component", "Shortcut Penalty"]
    assert np.allclose(scores[components].sum(axis=1), scores.objective_value)
    assert scores["Modeled Round-Trip Fleet Requirement"].isna().all()
    pairs = compare_algorithms(scores)
    for metric, counts in pairs["paired"].items():
        assert summary["paired"][metric] == counts
    for method in ("local_search", "ga"):
        for metric in ("distance", "objective"):
            for status in ("improved", "unchanged", "worsened"):
                assert summary[method][metric][status] == pairs[method][metric][status]
            observed = pairs[method][metric]["mean_improvement_pct"]
            assert math.isclose(summary[method][metric]["mean_improvement_pct"], observed, abs_tol=1e-10)
            flag = f"{method}_{metric}_improved"
            assert int(reports[flag].eq(True).sum()) == pairs[method][metric]["improved"]
        assert math.isclose(summary[method]["execution_time_s"]["mean"],
                            pairs[method]["execution_time_s"]["mean"], abs_tol=.0005)
    assert math.isclose(summary["ga"]["all_seeds_time_s"]["sum"], pairs["ga"]["all_seeds_time_s"]["sum"])
    assert summary["processing"]["discovered"] == len(reports)
    assert summary["processing"]["processed"] == len(processed)

    features = {(f["properties"]["chart_no"], f["properties"]["model"]): f for f in geo["features"]}
    assert len(features) == len(geo["features"])
    models = scores.set_index(["chart_no", "model"]).sort_index()
    sequences = stops.groupby(["chart_no", "model"], sort=False)
    assert set(sequences.groups) == set(models.index)
    for (chart, model), sequence in sequences:
        assert sequence.optimized_stop_order.tolist() == list(range(1, len(sequence) + 1))
        historical = source.loc[source.chart_no.eq(chart)].sort_values("stop_order")
        ordered = sequence.sort_values("original_stop_order")
        assert list(ordered.original_stop_order) == list(historical.stop_order)
        assert ordered.ctu_stop_id.fillna("").tolist() == historical.ctu_stop_id.fillna("").tolist()
        numbers = ["latitude", "longitude", "Boardings", "Alightings", "Volume"]
        assert np.allclose(ordered[numbers], historical[numbers], equal_nan=True)
        observed_order = list(sequence.original_stop_order)
        assert observed_order[0] == historical.stop_order.iloc[0]
        assert observed_order[-1] == historical.stop_order.iloc[-1]
        original_positions = {value: pos for pos, value in enumerate(historical.stop_order)}
        assert max(abs(pos - original_positions[v]) for pos, v in enumerate(observed_order)) <= 3
        if model == MODEL_NAMES["baseline"]:
            assert observed_order == historical.stop_order.tolist()
        row = models.loc[chart, model]
        baseline = models.loc[chart, MODEL_NAMES["baseline"]]
        assert row.distance_km <= baseline.distance_km * 1.25 + 1e-9
        changed = sequence.osm_node.ne(sequence.original_osm_node)
        assert sequence.snap_reassignment_reason.notna().eq(changed).all()
        assert sequence.loc[changed, "snap_distance_m"].le(graph.max_snap_m).all()
        if (chart, model) not in features:
            assert row.distance_km == 0
            assert sequence.osm_node.nunique() == 1
            continue
        feature = features[chart, model]
        path = feature["properties"]["road_path_nodes"]
        assert path[0] == sequence.osm_node.iloc[0] and path[-1] == sequence.osm_node.iloc[-1]
        cursor = 0
        for node in sequence.osm_node:
            cursor = path.index(node, cursor)
        edges = [graph.adjacent_edges[u][v] for u, v in zip(path, path[1:])]
        distance_km = sum(edge["length_m"] for edge in edges) / 1000
        seconds = sum(edge["time_sec"] for edge in edges) + (len(sequence) - 2) * DEFAULT_DWELL_TIME_SEC
        assert math.isclose(row.distance_km, distance_km)
        assert abs(row["Estimated Travel Time (min)"] - seconds / 60) <= .0050001
        _, _, _, geometry = graph._describe_path(path)
        assert feature["geometry"]["coordinates"] == [[lon, lat] for lat, lon in geometry]
    assert (directory / "comparison.png").read_bytes().startswith(b"\x89PNG")
    print(f"Verified {len(reports)} chart statuses, {len(models)} model rows, "
          f"{len(stops)} stop rows and {len(features)} directed road paths.")


if __name__ == "__main__":
    validate_outputs()
