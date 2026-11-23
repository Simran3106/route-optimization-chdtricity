
import osmnx as ox
from pathlib import Path

print("Downloading expanded Tricity road network...")

# Approximate coverage, including the outlying stops shown
north = 30.83
south = 30.55
east = 76.95
west = 76.60

G = ox.graph_from_bbox(
    (west, south, east, north),
    network_type="drive",
    simplify=True
)

print("Download completed!")
print("Nodes:", len(G.nodes))
print("Edges:", len(G.edges))

output_dir = Path("data/roadnodes")
output_dir.mkdir(parents=True, exist_ok=True)

output_file = output_dir / "tricity_road_network.graphml"

ox.save_graphml(G, filepath=output_file)

print("Saved at:", output_file)
