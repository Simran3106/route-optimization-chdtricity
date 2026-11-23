
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "passengerdata" / "processed"

# Load the baseline generated in Step 2B
df = pd.read_csv(DATA / "baseline_performance.csv")

# Keep routes for which we have usable loading data
valid = df[
    df["has_loading_data"].fillna(False).astype(bool)
].copy()

# Flag potential overcrowding
valid["overloaded"] = valid["max_load_factor"] > 1.0

# Rank routes by reported maximum load factor
valid = valid.sort_values(
    ["overloaded", "max_load_factor"],
    ascending=[False, False]
)

columns = [
    "route_id",
    "Daily ridership",
    "Length (km)",
    "avg_speed_kmph",
    "max_load_factor",
    "mean_headway_min",
    "has_stop_data",
    "overloaded"
]

result = valid[columns]

# Save analysis
result.to_csv(
    DATA / "optimization_candidates.csv",
    index=False
)

print("\n=== CTU OPTIMIZATION CANDIDATES ===")

print("\nRoutes with loading data:", len(valid))

print(
    "Potentially overloaded routes:",
    int(valid["overloaded"].sum())
)

print("\nTop 15 candidates:")
print(result.head(15).to_string(index=False))

print("\nSaved optimization_candidates.csv")
