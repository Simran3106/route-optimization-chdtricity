import osmnx as ox
from pathlib import Path

print("OSMnx version:", ox.__version__)
print("Downloading Chandigarh road network...")

# Download the road network for Chandigarh
G = ox.graph_from_place(
    "Chandigarh, India",
    network_type="drive"
)

print("Download completed!")
print("Number of nodes:", len(G.nodes))
print("Number of edges:", len(G.edges))

# Create output directory
output_dir = Path("data/osm")
output_dir.mkdir(parents=True, exist_ok=True)

# Save the road network
output_file = output_dir / "chandigarh_road_network.graphml"

ox.save_graphml(G, filepath=output_file)
print("Road network saved at:", output_file)
