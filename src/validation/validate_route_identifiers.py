
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data/passengerdata")

routes_df = pd.read_csv(
    DATA_DIR / "existing_bus_routes.csv"
)

performance_df = pd.read_csv(
    DATA_DIR / "performance_routes_clean.csv"
)

details_df = pd.read_csv(
    DATA_DIR / "route_wise_details.csv"
)


# ============================================================
# PART 1: COMPARE ROUTE IDENTIFIERS
# ============================================================

existing_ids = set(
    routes_df["Routes No."].astype(str).str.strip()
)

performance_ids = set(
    performance_df["Route No"].astype(str).str.strip()
)

details_ids = set(
    details_df["Route No"].astype(str).str.strip()
)


# A. Initial summary
print("\n--- UNIQUE ROUTE IDENTIFIERS ---")
print("Existing bus routes:", len(existing_ids))
print("Performance parameters:", len(performance_ids))
print("Route-wise details:", len(details_ids))


# B. Existing routes vs performance
print("\n--- EXISTING ROUTES vs PERFORMANCE ---")
print("Common IDs:", len(existing_ids & performance_ids))
print("Only in existing routes:", sorted(existing_ids - performance_ids))
print("Only in performance:", sorted(performance_ids - existing_ids))


# C. Existing routes vs details
print("\n--- EXISTING ROUTES vs DETAILS ---")
print("Common IDs:", len(existing_ids & details_ids))
print("Only in existing routes:", sorted(existing_ids - details_ids))
print("Only in details:", sorted(details_ids - existing_ids))


# D. Performance vs details
print("\n--- PERFORMANCE vs DETAILS ---")
print("Common IDs:", len(performance_ids & details_ids))
print("Only in performance:", len(performance_ids - details_ids))
print("Only in details:", len(details_ids - performance_ids))


# ============================================================
# STEP 2C: INSPECT UNMATCHED ROUTE DETAILS
# ============================================================

existing_ids = set(
    routes_df["Routes No."].astype(str).str.strip()
)

details_ids = set(
    details_df["Route No"].astype(str).str.strip()
)

unmatched_details = sorted(details_ids - existing_ids)

'''
print("\nUnmatched route IDs and their descriptions:")

print(
    details_df[
        details_df["Route No"].astype(str).str.strip().isin(
            unmatched_details
        )
    ][["Route No", "Route Description", "Trip Direction", "Peak Hour"]]
    .drop_duplicates()
    .to_string(index=False)
)
'''


# ============================================================
# STEP 2D: CHECK POSSIBLE ROUTE CORRESPONDENCES
# ============================================================

# Show existing route numbers and their descriptions
print("\n--- EXISTING ROUTE DESCRIPTIONS ---")

print(
    routes_df[["Routes No.", "Description"]]
    .sort_values("Routes No.")
    .to_string(index=False)
)

# Show descriptions of unmatched detail identifiers
existing_ids = set(
    routes_df["Routes No."].astype(str).str.strip()
)

details_ids = set(
    details_df["Route No"].astype(str).str.strip()
)

unmatched_details = sorted(details_ids - existing_ids)

print("\n--- UNMATCHED DETAILS: ROUTE DESCRIPTIONS ---")

print(
    details_df[
        details_df["Route No"].astype(str).str.strip().isin(
            unmatched_details
        )
    ][["Route No", "Route Description"]]
    .drop_duplicates()
    .sort_values("Route No")
    .to_string(index=False)
)




import re

# ============================================================
# STEP 2E: MATCH BY BASE ID AND COMPARE DESCRIPTIONS
# ============================================================

def get_base_route(route_id):
    route_id = str(route_id).strip().upper()
    return re.sub(r"AC$", "", route_id)


def normalize_description(text):
    text = str(text).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


# Create route ID sets
performance_ids = set(
    performance_df["Route No"].astype(str).str.strip()
)

details_ids = set(
    details_df["Route No"].astype(str).str.strip()
)

# Prepare candidate matches by base ID
performance_ids_df = pd.DataFrame({
    "Performance ID": sorted(performance_ids)
})
details_ids_df = pd.DataFrame({
    "Details ID": sorted(details_ids)
})

performance_ids_df["Base ID"] = (
    performance_ids_df["Performance ID"].apply(get_base_route)
)
details_ids_df["Base ID"] = (
    details_ids_df["Details ID"].apply(get_base_route)
)

candidates = performance_ids_df.merge(
    details_ids_df,
    on="Base ID",
    how="inner"
)

# Keep pairs where the original IDs differ
candidates = candidates[
    candidates["Performance ID"] != candidates["Details ID"]
].copy()


# Attach existing route descriptions
existing_desc = routes_df[["Routes No.", "Description"]].copy()
existing_desc["Routes No."] = (
    existing_desc["Routes No."].astype(str).str.strip()
)

candidates = candidates.merge(
    existing_desc,
    left_on="Performance ID",
    right_on="Routes No.",
    how="left"
)


# Attach all directional descriptions from route-wise details
details_desc = details_df[
    ["Route No", "Route Description", "Trip Direction"]
].copy()

details_desc["Route No"] = (
    details_desc["Route No"].astype(str).str.strip()
)

results = candidates.merge(
    details_desc,
    left_on="Details ID",
    right_on="Route No",
    how="left"
)

# Normalize descriptions for comparison
results["Existing Description Normalized"] = (
    results["Description"].apply(normalize_description)
)
results["Details Description Normalized"] = (
    results["Route Description"].apply(normalize_description)
)

# Display candidates and their descriptions together
print("\n--- BASE-ID CANDIDATES WITH DESCRIPTION COMPARISON ---")

print(
    results[
        [
            "Performance ID",
            "Details ID",
            "Base ID",
            "Description",
            "Route Description",
            "Trip Direction"
        ]
    ].to_string(index=False)
)
