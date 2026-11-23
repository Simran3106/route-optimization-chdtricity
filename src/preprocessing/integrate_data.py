
from pathlib import Path
import pandas as pd
# Project root (two levels above this script)
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "passengerdata"
OUTPUT = DATA / "processed"
OUTPUT.mkdir(parents=True, exist_ok=True)

# 1. Load the datasets
routes = pd.read_csv(DATA / "existing_bus_routes.csv")
details = pd.read_csv(DATA / "route_wise_details.csv")
stops = pd.read_csv(
    DATA / "chart_data" /
    "join_alightingsboardings_with_standard routes.CSV"
)

print("Existing routes:", routes.shape)
print("Route details:", details.shape)
print("Stop records:", stops.shape)

# 2. Standardize route identifiers
def normalize_route(value):
    return str(value).strip().upper()

routes["route_id"] = routes["Routes No."].map(normalize_route)
details["route_id"] = details["Route No"].map(normalize_route)
stops["route_id"] = stops["route"].map(normalize_route)

# 3. Check missing values
print("\nMissing values in stop data:")
print(stops.isnull().sum())

# 4. Check matching route identifiers
existing_ids = set(routes["route_id"])
detail_ids = set(details["route_id"])
stop_ids = set(stops["route_id"])

print("\nRoutes in existing dataset:", len(existing_ids))
print("Routes in details dataset:", len(detail_ids))
print("Routes in stops dataset:", len(stop_ids))

print("Existing routes without stop data:",
      sorted(existing_ids - stop_ids))

print("Existing routes without detailed data:",
      sorted(existing_ids - detail_ids))

# 5. Aggregate stop-level passenger activity
stop_summary = (
    stops.groupby("route_id", as_index=False)
    .agg(
        total_boardings=("Boardings", "sum"),
        total_alightings=("Alightings", "sum"),
        stop_records=("stop_order", "count")
    )
)

# 6. Join route-level information
summary = routes.merge(
    stop_summary,
    on="route_id",
    how="left",
    validate="one_to_one"
)

# 7. Save output
output_file = OUTPUT / "route_baseline_summary.csv"
summary.to_csv(output_file, index=False)

print("\nSaved:", output_file)
print(summary[
    ["route_id", "Length (km)", "Daily ridership",
     "total_boardings", "total_alightings"]
].head(10))
