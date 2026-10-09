
import pandas as pd
from pathlib import Path


# ============================================================
# STEP 1A: SET PROJECT ROOT
# ============================================================

PROJECT_ROOT = Path.cwd()

# If the notebook is running from the notebooks folder,
# move up one level to the project root.
if PROJECT_ROOT.name == "notebooks":
    PROJECT_ROOT = PROJECT_ROOT.parent


# ============================================================
# STEP 1B: VALIDATE ALL CSV DATASETS
# Check shape, missing values, and duplicate rows
# ============================================================

data_dir = PROJECT_ROOT / "data"

csv_paths = {
    "CTU Stops": data_dir / "bustop" / "ctu_stops.csv",
    "Existing Bus Routes": (
        data_dir / "passengerdata" / "existing_bus_routes.csv"
    ),
    "Performance Parameters": (
        data_dir / "passengerdata" / "performance_parameters.csv"
    ),
    "Route-wise Details": (
        data_dir / "passengerdata" / "route_wise_details.csv"
    ),
}

raw_datasets = {}

for dataset_name, file_path in csv_paths.items():

    print("\n" + "=" * 65)
    print(f"DATASET: {dataset_name}")
    print("=" * 65)

    # Confirm that the file exists
    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {file_path}"
        )

    # Load the original dataset
    df = pd.read_csv(file_path)
    raw_datasets[dataset_name] = df

    # Basic dataset information
    print("File:", file_path.relative_to(PROJECT_ROOT))
    print("Shape (rows, columns):", df.shape)
    print("Columns:", df.columns.tolist())

    # Check missing values
    missing_count = int(df.isna().sum().sum())

    print("\nMissing values by column:")
    print(df.isna().sum().to_string())

    print("Total missing values:", missing_count)

    # Check duplicate rows
    duplicate_count = int(df.duplicated().sum())
    print("\nDuplicate rows:", duplicate_count)

    # Display the validation result
    if missing_count == 0:
        print("Missing-value check: PASSED")
    else:
        print("Missing-value check: REQUIRES INVESTIGATION")

    if duplicate_count == 0:
        print("Duplicate-row check: PASSED")
    else:
        print("Duplicate-row check: REQUIRES INVESTIGATION")


# Convenient references to the original datasets
stops_raw = raw_datasets["CTU Stops"]
routes_raw = raw_datasets["Existing Bus Routes"]
performance_raw = raw_datasets["Performance Parameters"]
details_raw = raw_datasets["Route-wise Details"]


# ============================================================
# STEP 1C: PREPROCESS PERFORMANCE PARAMETERS
# Separate location-based group headings and aggregate row
# from individual route records
# ============================================================

# Identify the four location-based group headings
group_labels = {
    "CHANDIGARH TO MOHALI",
    "CHANDIGARH TO PANCHKULA",
    "CHANDIGARH TO ZIRAKPUR",
    "CHANDIGARH TO OUTSIDE",
}

labels = (
    performance_raw["Route No"]
    .astype(str)
    .str.strip()
    .str.upper()
)

group_mask = labels.isin(group_labels)

performance_groups = performance_raw[group_mask].copy()
performance_remaining = performance_raw[~group_mask].copy()


# Identify the aggregate Total/Average row separately
remaining_labels = (
    performance_remaining["Route No"]
    .astype(str)
    .str.strip()
    .str.upper()
)

total_mask = remaining_labels.isin({
    "TOTAL/AVERAGE",
    "TOTAL / AVERAGE",
    "TOTAL/ AVERAGE",
})

performance_total = performance_remaining[total_mask].copy()

# Individual route records only
performance_routes = performance_remaining[~total_mask].copy()


# ============================================================
# STEP 1D: VERIFY THE PREPROCESSING
# ============================================================

print("\n" + "=" * 65)
print("PERFORMANCE DATA PREPROCESSING RESULTS")
print("=" * 65)

print("Original records:", len(performance_raw))
print("Location-based group headings:", len(performance_groups))
print("Aggregate records:", len(performance_total))
print("Individual route records:", len(performance_routes))

print("\nGroup headings identified:")
print(performance_groups["Route No"].tolist())

print("\nAggregate row preserved separately:")
print(performance_total.to_string(index=False))

print("\nMissing values in individual route records:")
print(performance_routes.isna().sum().to_string())

print(
    "\nTotal missing values in individual route records:",
    int(performance_routes.isna().sum().sum())
)


print("\nIndividual route records preview:")
print(performance_routes.head().to_string(index=False))





# Inspect missing values in the aggregate row
print("Missing values in aggregate row:")

if performance_total.empty:
    print("No aggregate row was identified.")
else:
    missing_aggregate = performance_total.isna().sum()
    print(missing_aggregate[missing_aggregate > 0])

    print("\nAggregate row with missing values:")
    print(performance_total.to_string(index=False))

# Check missing values in individual route records
print("\nMissing values in individual route records:")
print(performance_routes.isna().sum())




# ============================================================
# STEP 1E: SAVE PREPROCESSED PERFORMANCE DATA
# ============================================================

output_dir = PROJECT_ROOT / "data" / "passengerdata"

performance_routes.to_csv(
    output_dir / "performance_routes_clean.csv",
    index=False
)

performance_groups.to_csv(
    output_dir / "performance_groups_clean.csv",
    index=False
)

performance_total.to_csv(
    output_dir / "performance_aggregate_clean.csv",
    index=False
)

print("Cleaned files saved in:", output_dir)
print("1. performance_routes_clean.csv")
print("2. performance_groups_clean.csv")
print("3. performance_aggregate_clean.csv")
