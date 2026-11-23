
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "passengerdata"

# Load the three datasets
routes = pd.read_csv(DATA / "existing_bus_routes.csv")
details = pd.read_csv(DATA / "route_wise_details.csv")
stops = pd.read_csv(
    DATA / "chart_data" /
    "join_alightingsboardings_with_standard routes.CSV"
)

# Standardize route numbers
def normalize(value):
    return str(value).strip().upper()

existing = set(routes["Routes No."].map(normalize))
detailed = set(details["Route No"].map(normalize))
stop_routes = set(stops["route"].map(normalize))

# Compare route identifiers
common = existing & detailed & stop_routes

print("\n=== ROUTE MATCHING REPORT ===")

print("\n1. Routes present in all three datasets:")
print(len(common), sorted(common))

print("\n2. Existing routes missing from stop data:")
unmatched = existing - stop_routes
print(len(unmatched), sorted(unmatched))

print("\n3. Routes in stop data but not existing data:")
print(sorted(stop_routes - existing))

print("\n4. Possible AC route variants:")
for route in sorted(unmatched):
    candidate = route + "AC"
    if candidate in stop_routes:
        print(f"{route} -> {candidate}")

# Save the exact matched identifiers
output = DATA / "processed"
output.mkdir(parents=True, exist_ok=True)

pd.DataFrame({
    "route_id": sorted(common)
}).to_csv(
    output / "matched_routes.csv",
    index=False
)

print("\nSaved matched_routes.csv")
