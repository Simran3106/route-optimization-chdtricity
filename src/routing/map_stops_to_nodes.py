
from pathlib import Path
import pandas as pd
import osmnx as ox
from pyproj import Transformer

# -----------------------------------
# STEP 1: Define file paths
# -----------------------------------

ROOT = Path(__file__).resolve().parents[2]

graph_path = ROOT / "data/roadnodes/tricity_road_network.graphml"

stops_path = (
    ROOT / "data/passengerdata/chart_data/chart_stops_mapped.csv"
)

output_path = ROOT / "data/busstop/stops_with_road_nodes.csv"

# -----------------------------------
# STEP 2: Load road network
# -----------------------------------

print("Loading Tricity road network...")

G = ox.load_graphml(graph_path)

print("Nodes:", len(G.nodes))
print("Edges:", len(G.edges))

# Project graph to a coordinate system measured in metres
G = ox.project_graph(G)

print("Projected CRS:", G.graph["crs"])

# -----------------------------------
# STEP 3: Load CTU bus stops
# -----------------------------------

print("\nLoading CTU bus stops...")

stops = pd.read_csv(stops_path)

stops["latitude"] = pd.to_numeric(
    stops["latitude"], errors="coerce"
)

stops["longitude"] = pd.to_numeric(
    stops["longitude"], errors="coerce"
)

# Remove records without valid coordinates
stops = stops.dropna(
    subset=["latitude", "longitude"]
).copy()

# Keep unique stop locations
stops = stops.drop_duplicates(
    subset=["latitude", "longitude"]
).copy()

print("Unique stops with coordinates:", len(stops))

# -----------------------------------
# STEP 4: Check graph boundaries
# -----------------------------------

# Convert graph bounds back to latitude/longitude
# by using the original geographic graph
G_geo = ox.load_graphml(graph_path)

min_lat = min(data["y"] for _, data in G_geo.nodes(data=True))
max_lat = max(data["y"] for _, data in G_geo.nodes(data=True))

min_lon = min(data["x"] for _, data in G_geo.nodes(data=True))
max_lon = max(data["x"] for _, data in G_geo.nodes(data=True))

stops["inside_graph_bounds"] = (
    stops["latitude"].between(min_lat, max_lat)
    & stops["longitude"].between(min_lon, max_lon)
)

inside = int(stops["inside_graph_bounds"].sum())
outside = int((~stops["inside_graph_bounds"]).sum())

print("Stops inside graph bounds:", inside)
print("Stops outside graph bounds:", outside)

# Keep all stops in the output, including those outside the graph
# Only attempt nearest-node mapping for stops inside bounds
mapped_stops = stops[
    stops["inside_graph_bounds"]
].copy()

# -----------------------------------
# STEP 5: Convert stop coordinates
# -----------------------------------

print("\nConverting coordinates...")

transformer = Transformer.from_crs(
    "EPSG:4326",
    G.graph["crs"],
    always_xy=True
)

xs, ys = transformer.transform(
    mapped_stops["longitude"].to_numpy(),
    mapped_stops["latitude"].to_numpy()
)

# -----------------------------------
# STEP 6: Find nearest road nodes
# -----------------------------------

print("Mapping stops to nearest road nodes...")

nodes, distances = ox.distance.nearest_nodes(
    G,
    X=xs,
    Y=ys,
    return_dist=True
)

mapped_stops["nearest_node"] = nodes

mapped_stops["distance_to_road_m"] = distances

# Flag stops that are far from a road node
MAX_DISTANCE = 500

mapped_stops["mapping_quality"] = mapped_stops[
    "distance_to_road_m"
].apply(
    lambda distance: (
        "review" if distance > MAX_DISTANCE
        else "candidate"
    )
)

# -----------------------------------
# STEP 7: Add outside stops back
# -----------------------------------

outside_stops = stops[
    ~stops["inside_graph_bounds"]
].copy()

outside_stops["nearest_node"] = pd.NA
outside_stops["distance_to_road_m"] = float("nan")
outside_stops["mapping_quality"] = "outside_graph"

result = pd.concat(
    [mapped_stops, outside_stops],
    ignore_index=True
)

# -----------------------------------
# STEP 8: Save results
# -----------------------------------

output_path.parent.mkdir(
    parents=True,
    exist_ok=True
)

result.to_csv(
    output_path,
    index=False
)

print("\nMapping completed!")

print("Total unique stops:", len(result))
print("Stops mapped:", len(mapped_stops))
print("Stops outside graph:", len(outside_stops))

print(
    "Mapped stops requiring review:",
    (mapped_stops["distance_to_road_m"] > MAX_DISTANCE).sum()
)

print("\nFirst 10 mapped stops:")

print(
    mapped_stops[
        [
            "ctu_stop_name",
            "nearest_node",
            "distance_to_road_m",
            "mapping_quality"
        ]
    ].head(10).to_string(index=False)
)

print("\nOutput saved at:", output_path)
