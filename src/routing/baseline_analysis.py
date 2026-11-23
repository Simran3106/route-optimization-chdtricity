
from pathlib import Path
import pandas as pd
import numpy as np

# 1. Define project paths
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "passengerdata"
OUTPUT = DATA / "processed"
OUTPUT.mkdir(parents=True, exist_ok=True)

# 2. Load existing route information
routes = pd.read_csv(DATA / "existing_bus_routes.csv")

# Load detailed passenger loading information
details = pd.read_csv(DATA / "route_wise_details.csv")

# Load stop-level passenger data
stops = pd.read_csv(
    DATA / "chart_data" /
    "join_alightingsboardings_with_standard routes.CSV"
)

# 3. Normalize route IDs
def normalize(value):
    return str(value).strip().upper()

routes["route_id"] = routes["Routes No."].map(normalize)
details["route_id"] = details["Route No"].map(normalize)
stops["route_id"] = stops["route"].map(normalize)

# 4. Convert numeric columns
numeric_cols = [
    "Length (km)",
    "Travel Time (min)",
    "No of Buses",
    "Daily ridership",
    "Peak",
    "Off Peak"
]

for col in numeric_cols:
    routes[col] = pd.to_numeric(
        routes[col], errors="coerce"
    )

details["Load Factor (at max pass volume)"] = (
    pd.to_numeric(
        details["Load Factor (at max pass volume)"],
        errors="coerce"
    )
)

details["Headway (min)"] = pd.to_numeric(
    details["Headway (min)"], errors="coerce"
)

# 5. Calculate existing performance metrics
routes["ridership_per_bus"] = (
    routes["Daily ridership"] /
    routes["No of Buses"].replace(0, np.nan)
)

routes["avg_speed_kmph"] = (
    routes["Length (km)"] /
    (routes["Travel Time (min)"].replace(0, np.nan) / 60)
)

# 6. Aggregate detailed loading information
# Keep direction-specific records separately
direction_summary = (
    details.groupby(
        ["route_id", "Trip Direction"],
        as_index=False
    )
    .agg(
        max_load_factor=(
            "Load Factor (at max pass volume)", "max"
        ),
        mean_load_factor=(
            "Load Factor (at max pass volume)", "mean"
        ),
        mean_headway_min=("Headway (min)", "mean"),
        observations=("route_id", "size")
    )
)

direction_summary["potential_overload"] = (
    direction_summary["max_load_factor"] > 1
)

# Aggregate to one row per route for joining
route_loading = (
    direction_summary.groupby(
        "route_id", as_index=False
    )
    .agg(
        max_load_factor=("max_load_factor", "max"),
        mean_headway_min=("mean_headway_min", "mean"),
        potentially_overloaded=(
            "potential_overload", "max"
        )
    )
)

# 7. Merge using exact route IDs
baseline = routes.merge(
    route_loading,
    on="route_id",
    how="left",
    validate="one_to_one"
)

# 8. Identify route IDs with stop data
stop_ids = set(stops["route_id"])

baseline["has_stop_data"] = (
    baseline["route_id"].isin(stop_ids)
)

baseline["has_loading_data"] = (
    baseline["max_load_factor"].notna()
)

# 9. Sort by daily ridership
baseline = baseline.sort_values(
    "Daily ridership", ascending=False
)

# 10. Save results
baseline.to_csv(
    OUTPUT / "baseline_performance.csv",
    index=False
)

direction_summary.to_csv(
    OUTPUT / "direction_load_analysis.csv",
    index=False
)

# 11. Print results
print("\n=== CTU BASELINE ANALYSIS ===")

print("\nTotal existing routes:", len(routes))

print("\nRoutes with matching stop data:",
      baseline["has_stop_data"].sum())

print("\nRoutes with matching loading data:",
      baseline["has_loading_data"].sum())

print("\nTop 10 routes by daily ridership:")
print(
    baseline[
        ["route_id", "Daily ridership",
         "No of Buses", "ridership_per_bus",
         "avg_speed_kmph"]
    ].head(10).to_string(index=False)
)

print("\nPotentially overloaded route-directions:")
print(
    direction_summary[
        direction_summary["potential_overload"]
    ][
        ["route_id", "Trip Direction",
         "max_load_factor"]
    ].to_string(index=False)
)

print("\n=== FILES SAVED ===")
print(OUTPUT / "baseline_performance.csv")
print(OUTPUT / "direction_load_analysis.csv")
