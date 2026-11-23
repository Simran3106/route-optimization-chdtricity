
from pathlib import Path
import pandas as pd
import networkx as nx
import osmnx as ox

ROOT = Path(__file__).resolve().parents[2]

GRAPH_PATH = (
    ROOT / "data/roadnodes/tricity_road_network.graphml"
)

STOPS_PATH = (
    ROOT / "data/passengerdata/chart_data/chart_stops_mapped.csv"
)

MAPPED_PATH = (
    ROOT / "data/busstop/stops_with_road_nodes.csv"
)

OUTPUT_DIR = ROOT / "data/passengerdata/processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("Loading road network...")
G = ox.load_graphml(GRAPH_PATH)

print("Loading CTU stop data...")
stops = pd.read_csv(STOPS_PATH)
mapped = pd.read_csv(MAPPED_PATH)

# Standardize stop coordinates
for df in (stops, mapped):
    df["latitude"] = pd.to_numeric(
        df["latitude"], errors="coerce"
    )
    df["longitude"] = pd.to_numeric(
        df["longitude"], errors="coerce"
    )

# Join by coordinates, matching the mapping script
# that retained unique coordinate pairs.
node_lookup = mapped[
    ["latitude", "longitude", "nearest_node", "mapping_quality"]
].drop_duplicates(subset=["latitude", "longitude"])

stops = stops.merge(
    node_lookup,
    on=["latitude", "longitude"],
    how="left",
    validate="many_to_one"
)

# Only use mapped candidate stops
stops = stops[
    (stops["mapping_quality"] == "candidate")
    & stops["nearest_node"].notna()
].copy()

stops["nearest_node"] = stops["nearest_node"].astype("int64")
stops["stop_order"] = pd.to_numeric(
    stops["stop_order"], errors="coerce"
)

stops = stops.dropna(subset=["stop_order", "route", "direction"])

# Keep route identifiers as strings
stops["route"] = stops["route"].astype(str).str.strip()
stops["direction"] = stops["direction"].astype(str).str.strip()

results = []
failed_segments = []

print("Calculating shortest paths...")

# Process each route and direction separately
for (route, direction), group in stops.groupby(
    ["route", "direction"]
):
    group = group.sort_values("stop_order")

    if len(group) < 2:
        continue

    route_path = []
    route_distance_m = 0
    failed = 0

    records = group.to_dict("records")

    for i in range(len(records) - 1):
        start = int(records[i]["nearest_node"])
        end = int(records[i + 1]["nearest_node"])

        try:
            if start == end:
                segment_path = [start]
                segment_distance = 0
            else:
                segment_path = nx.shortest_path(
                    G, source=start, target=end, weight="length"
                )
                segment_distance = nx.shortest_path_length(
                    G, source=start, target=end, weight="length"
                )

            if route_path:
                route_path.extend(segment_path[1:])
            else:
                route_path.extend(segment_path)

            route_distance_m += segment_distance

        except (nx.NetworkXNoPath, nx.NodeNotFound):
            failed += 1
            failed_segments.append({
                "route": route,
                "direction": direction,
                "from_stop": records[i].get("ctu_stop_name"),
                "to_stop": records[i + 1].get("ctu_stop_name")
            })

    results.append({
        "route": route,
        "direction": direction,
        "mapped_stops": len(group),
        "successful_segments": len(group) - 1 - failed,
        "failed_segments": failed,
        "calculated_distance_km": round(route_distance_m / 1000, 3),
        "road_node_count": len(route_path),
        "complete": failed == 0
    })

results_df = pd.DataFrame(results)
failed_df = pd.DataFrame(
    failed_segments,
    columns=["route", "direction", "from_stop", "to_stop"]
)

results_df.to_csv(
    OUTPUT_DIR / "reconstructed_routes.csv",
    index=False
)

failed_df.to_csv(
    OUTPUT_DIR / "failed_route_segments.csv",
    index=False
)

print("\nRoute reconstruction completed!")
print("Route-directions processed:", len(results_df))
print("Complete route-directions:", results_df["complete"].sum()
      if not results_df.empty else 0)
print("Failed segments:", len(failed_df))

print("\nSample results:")
print(results_df.head(10).to_string(index=False))

print("\nFiles saved in:", OUTPUT_DIR)

