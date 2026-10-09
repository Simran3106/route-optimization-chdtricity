
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
# DISPLAY ROUTE IDENTIFIERS
# ============================================================

print("\nEXISTING BUS ROUTES")
print(routes_df["Routes No."].unique())

print("\nPERFORMANCE PARAMETERS")
print(performance_df["Route No"].unique())

print("\nROUTE-WISE DETAILS")
print(details_df["Route No"].unique())