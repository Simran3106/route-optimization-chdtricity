
from pathlib import Path
import pandas as pd

# Project root
ROOT = Path(__file__).resolve().parents[2].parent
CHART_DIR = ROOT / "data" / "passengerdata" / "chart_data"

# Input files
MAPPED_FILE = CHART_DIR / "chart_stops_mapped.csv"
PASSENGER_FILE = CHART_DIR / "digitized_all_with_volume.csv"

# Output file
OUTPUT_FILE = CHART_DIR / "join_alightingsboardings_with_standard routes.csv"

# Load data
mapped = pd.read_csv(MAPPED_FILE)
passenger = pd.read_csv(PASSENGER_FILE)

# Check required join keys
mapped_keys = ["chart_no", "stop_order"]
passenger_keys = ["sr_no", "stop_no"]

for col in mapped_keys:
    if col not in mapped.columns:
        raise ValueError(f"Missing column in mapped file: {col}")

for col in passenger_keys:
    if col not in passenger.columns:
        raise ValueError(f"Missing column in passenger file: {col}")

# Keep only the passenger data you need
passenger_columns = [
    "sr_no",
    "stop_no",
    "Boardings",
    "Alightings",
    "Volume",
]

for col in ["Boardings", "Alightings"]:
    if col not in passenger.columns:
        raise ValueError(
            f"Missing column: {col}. Available columns: "
            f"{passenger.columns.tolist()}"
        )

passenger = passenger[passenger_columns].copy()

# Standardise join-key types
mapped["chart_no"] = pd.to_numeric(
    mapped["chart_no"], errors="raise"
).astype(int)

mapped["stop_order"] = pd.to_numeric(
    mapped["stop_order"], errors="raise"
).astype(int)

passenger["sr_no"] = pd.to_numeric(
    passenger["sr_no"], errors="raise"
).astype(int)

passenger["stop_no"] = pd.to_numeric(
    passenger["stop_no"], errors="raise"
).astype(int)

# Check for duplicate keys before joining
if mapped.duplicated(mapped_keys).any():
    raise ValueError(
        "Mapped file has duplicate chart_no + stop_order keys."
    )

if passenger.duplicated(passenger_keys).any():
    raise ValueError(
        "Passenger file has duplicate sr_no + stop_no keys."
    )

# Preserve the original mapped-file order
mapped["_original_order"] = range(len(mapped))

# Join passenger data to the mapped stop records
final = mapped.merge(
    passenger,
    left_on=["chart_no", "stop_order"],
    right_on=["sr_no", "stop_no"],
    how="left",
    validate="one_to_one",
    indicator=True,
    sort=False,
)

# Confirm every mapped stop received a passenger-data match
unmatched = final["_merge"] != "both"

if unmatched.any():
    print("ERROR: Some stops did not match passenger data.")
    print(
        final.loc[
            unmatched,
            ["chart_no", "stop_order", "_merge"]
        ].to_string(index=False)
    )
    raise ValueError(
        f"{int(unmatched.sum())} stop records were unmatched. "
        "Output was not saved."
    )

# Restore original order and remove join-only columns
final = final.sort_values("_original_order")

final = final.drop(
    columns=[
        "_original_order",
        "_merge",
        "sr_no",
        "stop_no",
    ]
)

# Save final dataset
final.to_csv(OUTPUT_FILE, index=False)

print("\nJOIN SUCCESSFUL")
print("Output:", OUTPUT_FILE)
print("Mapped rows:", len(mapped))
print("Passenger rows:", len(passenger))
print("Final rows:", len(final))
print("Final columns:", final.columns.tolist())
print("Boardings missing:", int(final["Boardings"].isna().sum()))
print("Alightings missing:", int(final["Alightings"].isna().sum()))
