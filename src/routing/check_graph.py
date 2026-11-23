from pathlib import Path
import osmnx as ox

ROOT = Path(__file__).resolve().parents[2]

graph_path = ROOT / "data" / "roadnodes" / "chandigarh_road_network.graphml"

G = ox.load_graphml(graph_path)

print("Nodes:", len(G.nodes))
print("Edges:", len(G.edges))
print("CRS:", G.graph.get("crs"))

latitudes = [data["y"] for _, data in G.nodes(data=True)]
longitudes = [data["x"] for _, data in G.nodes(data=True)]

print("Latitude range:", min(latitudes), max(latitudes))
print("Longitude range:", min(longitudes), max(longitudes))