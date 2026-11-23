
from pathlib import Path
import pandas as pd
import osmnx as ox
import networkx as nx
from scipy.spatial import cKDTree
from pyproj import Transformer
import numpy as np

ROOT = Path(__file__).resolve().parents[2]

GRAPH_PATH = ROOT / "data/roadnodes/tricity_road_network.graphml"
MAPPED_PATH = ROOT / "data/busstop/stops_with_road_nodes.csv"

print("Loading road network...")
G = ox.load_graphml(GRAPH_PATH)

print("Finding largest strongly connected component...")

largest_scc = max(
    nx.strongly_connected_components(G),
    key=len
)

print("Largest component size:", len(largest_scc))

# Project graph to metres
G_projected = ox.project_graph(G)

# Only consider nodes in the largest SCC
valid_nodes = list(largest_scc)

node_coordinates = np.array([
    [
        G_projected.nodes[node]["x"],
        G_projected.nodes[node]["y"]
    ]
    for node in valid_nodes
])

# KD-tree for efficient nearest-node lookup
tree = cKDTree(node_coordinates)

# Convert latitude/longitude to projected coordinates
transformer = Transformer.from_crs(
    "EPSG:4326",
    G_projected.graph["crs"],
    always_xy=True
)

print("Loading mapped stops...")
stops = pd.read_csv(MAPPED_PATH)

problem_stops = [
    "Sector 7/19",
    "Behlana Old Airport"
]

for stop_name in problem_stops:
    matches = stops[
        stops["ctu_stop_name"] == stop_name
    ]

    for index, row in matches.iterrows():

        x, y = transformer.transform(
            row["longitude"],
            row["latitude"]
        )

        distance, nearest_index = tree.query([x, y])

        new_node = valid_nodes[nearest_index]

        print("\nStop:", stop_name)
        print("Old node:", row["nearest_node"])
        print("New node:", new_node)
        print("Distance:", round(distance, 2), "metres")

        # Do not automatically accept a distant mapping
        if distance <= 500:
            stops.at[index, "nearest_node"] = new_node
            stops.at[index, "distance_to_road_m"] = distance
            stops.at[index, "mapping_quality"] = "candidate"
            print("Mapping updated")
        else:
            print("Skipped: nearest connected node exceeds 500 m")

# Save updated mappings
stops.to_csv(MAPPED_PATH, index=False)

print("\nUpdated mapping saved:", MAPPED_PATH)
