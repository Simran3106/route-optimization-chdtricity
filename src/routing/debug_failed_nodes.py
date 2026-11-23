
from pathlib import Path
import pandas as pd
import networkx as nx
import osmnx as ox

ROOT = Path(__file__).resolve().parents[2]

graph_path = ROOT / "data/roadnodes/tricity_road_network.graphml"
mapped_path = ROOT / "data/busstop/stops_with_road_nodes.csv"

print("Loading graph...")
G = ox.load_graphml(graph_path)

print("Loading mapped stops...")
stops = pd.read_csv(mapped_path)

problem_stops = [
    "Sector 7/19",
    "Behlana Old Airport",
    "Sector 26/27",
    "Sector 8/18",
    "Hallo Majra (UP)",
    "Zirakpur (Up)"
]

# Directed graph: check strongly connected components
components = list(nx.strongly_connected_components(G))
component_lookup = {}

for i, component in enumerate(components):
    for node in component:
        component_lookup[node] = i

print("\nLargest strongly connected component size:",
      max(len(c) for c in components))

for name in problem_stops:
    matches = stops[stops["ctu_stop_name"] == name]

    if matches.empty:
        print("\nStop not found:", name)
        continue

    for _, row in matches.iterrows():
        if pd.isna(row["nearest_node"]):
            print("\nStop not mapped:", name)
            continue

        node = int(row["nearest_node"])

        print("\nStop:", name)
        print("Nearest node:", node)
        print("Distance to node:", row["distance_to_road_m"])
        print("Component:", component_lookup.get(node))
        print("Outgoing edges:", G.out_degree(node))
        print("Incoming edges:", G.in_degree(node))
