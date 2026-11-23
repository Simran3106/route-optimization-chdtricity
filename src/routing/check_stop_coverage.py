
from pathlib import Path
import pandas as pd
import osmnx as ox

ROOT = Path(__file__).resolve().parents[2]

graph_path = ROOT / "data/roadnodes/tricity_road_network.graphml"
stops_path = ROOT / "data/passengerdata/chart_data/chart_stops_mapped.csv"

# Load road network
G = ox.load_graphml(graph_path)

# Load CTU stops
stops = pd.read_csv(stops_path)

# Convert coordinates to numeric values
stops["latitude"] = pd.to_numeric(stops["latitude"], errors="coerce")
stops["longitude"] = pd.to_numeric(stops["longitude"], errors="coerce")

# Calculate graph boundaries
min_lat = min(data["y"] for _, data in G.nodes(data=True))
max_lat = max(data["y"] for _, data in G.nodes(data=True))
min_lon = min(data["x"] for _, data in G.nodes(data=True))
max_lon = max(data["x"] for _, data in G.nodes(data=True))

# Remove duplicate stops so each location is counted once
unique_stops = stops.dropna(subset=["latitude", "longitude"]).drop_duplicates(
    subset=["latitude", "longitude"]
).copy()

# Check whether each stop falls within the graph's bounding box
unique_stops["inside_graph_bounds"] = (
    unique_stops["latitude"].between(min_lat, max_lat)
    & unique_stops["longitude"].between(min_lon, max_lon)
)

inside = unique_stops["inside_graph_bounds"].sum()
outside = (~unique_stops["inside_graph_bounds"]).sum()

print("Unique stops with coordinates:", len(unique_stops))
print("Stops inside graph bounds:", inside)
print("Stops outside graph bounds:", outside)

if len(unique_stops) > 0:
    print("Coverage percentage:", round(inside / len(unique_stops) * 100, 2), "%")

print("\nSample stops outside graph bounds:")
print(
    unique_stops.loc[
        ~unique_stops["inside_graph_bounds"],
        ["ctu_stop_name", "latitude", "longitude"]
    ].head(20).to_string(index=False)
)
