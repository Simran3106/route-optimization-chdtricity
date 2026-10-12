
"""
Apply stop decisions from stops_to_decide.xlsx
and generate chart_stops_mapped.csv.
"""

import math
import re
from pathlib import Path

import pandas as pd


# Project root: route-optimization-chdtricity
ROOT = Path(__file__).resolve().parents[2].parent

# Input folders
BUSSTOP_DIR = ROOT / "data" / "bustop"
CHART_DIR = ROOT / "data" / "passengerdata" / "chart_data"

# Input files
CTU = BUSSTOP_DIR / "ctu_stops.csv"
LABELS = CHART_DIR / "chart_labels_extracted.csv"

# Support either workbook filename
BOOK = CHART_DIR / "stops_to_decide.xlsx"
if not BOOK.exists():
    BOOK = CHART_DIR / "stops_to_decide (2).xlsx"

# Output file
OUT = CHART_DIR / "chart_stops_mapped.csv"


def base(name):
    """Remove a trailing Up/Down tag from a CTU stop name."""
    b = str(name).strip()
    for _ in range(3):
        b = re.sub(
            r"\s*-?\s*\(?\b(?:up|down)\b\)?\s*$",
            "",
            b,
            flags=re.I,
        ).strip()
    return b


def km(a, b):
    """Calculate distance in kilometres between two coordinates."""
    la1, lo1, la2, lo2 = map(
        math.radians, [a[0], a[1], b[0], b[1]]
    )
    x = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1)
        * math.cos(la2)
        * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(min(1, math.sqrt(x)))


# Load CTU stop master
ctu = pd.read_csv(CTU)
ctu["key"] = ctu["stop_name"].map(
    lambda n: base(n).lower()
)
by_key = {
    k: g for k, g in ctu.groupby("key")
}


def sheet(name):
    return pd.read_excel(BOOK, sheet_name=name)


def split(cell):
    if pd.isna(cell):
        return []
    return [
        x.strip()
        for x in str(cell).split(",")
        if x.strip()
    ]


# Map chart labels to standard CTU stop names
label_to = {}

for _, r in sheet("Done automatically").iterrows():
    for label in split(r["Chart label(s) as written"]):
        label_to[label] = r["CTU stop name"]

for _, r in sheet("Decide").iterrows():
    choice = r["CHOICE (edit this)"]

    for label in split(r["Chart label(s) as written"]):
        if (
            pd.notna(choice)
            and str(choice).strip()
            and str(choice).strip().upper() != "NONE"
        ):
            label_to[label] = str(choice).strip()


# Coordinates manually entered for stops not in CTU
manual = {}

for _, r in sheet("Not in CTU").iterrows():
    lat = r["latitude (optional)"]
    lon = r["longitude (optional)"]

    if pd.notna(lat) and pd.notna(lon):
        for label in split(r["Chart label(s) as written"]):
            manual[label] = (float(lat), float(lon))


# Load extracted chart stop sequences
lab = pd.read_csv(LABELS)
rows = []

for chart_no, g in lab.groupby("chart_no", sort=True):
    g = g.sort_values("stop_order")

    # Determine the possible coordinate source for each stop
    pts = []

    for _, r in g.iterrows():
        label = r["chart_label"]
        standard_name = label_to.get(label)

        if (
            standard_name is not None
            and base(standard_name).lower() in by_key
        ):
            candidates = by_key[base(standard_name).lower()]
            pts.append(("ctu", candidates))
        elif label in manual:
            pts.append(("manual", manual[label]))
        else:
            pts.append(("none", None))

    # Approximate coordinates used to identify the correct
    # Up/Down copy of a CTU stop from neighbouring stops
    cent = []

    for kind, data in pts:
        if kind == "ctu":
            cent.append(
                (
                    data["latitude"].mean(),
                    data["longitude"].mean(),
                )
            )
        elif kind == "manual":
            cent.append(data)
        else:
            cent.append(None)

    def anchor(i, step):
        j = i + step
        while 0 <= j < len(cent):
            if cent[j] is not None:
                return cent[j]
            j += step
        return None

    # Create one output row per chart stop
    for i, ((kind, data), (_, r)) in enumerate(
        zip(pts, g.iterrows())
    ):
        out = {
            "chart_no": chart_no,
            "route": r["route"],
            "direction": r["direction"],
            "stop_order": r["stop_order"],
            "chart_label": r["chart_label"],
            "ctu_stop_id": "",
            "ctu_stop_name": "",
            "latitude": None,
            "longitude": None,
        }

        if kind == "ctu":
            previous = anchor(i, -1)
            following = anchor(i, 1)

            best = None

            for _, candidate in data.iterrows():
                point = (
                    candidate["latitude"],
                    candidate["longitude"],
                )

                if previous is not None and following is not None:
                    cost = (
                        km(previous, point)
                        + km(point, following)
                        - km(previous, following)
                    )
                elif previous is not None or following is not None:
                    neighbour = (
                        previous
                        if previous is not None
                        else following
                    )
                    cost = km(neighbour, point)
                else:
                    cost = 0

                if best is None or cost < best[0]:
                    best = (cost, candidate)

            candidate = best[1]

            out.update(
                ctu_stop_id=candidate["stop_id"],
                ctu_stop_name=candidate["stop_name"],
                latitude=candidate["latitude"],
                longitude=candidate["longitude"],
            )

        elif kind == "manual":
            out.update(
                latitude=data[0],
                longitude=data[1],
            )

        rows.append(out)


# Save output WITHOUT the how_matched column
res = pd.DataFrame(rows)
res.to_csv(OUT, index=False)

print("Saved:", OUT)
print("Total stop records:", len(res))
print(
    "Stops with coordinates:",
    int(res["latitude"].notna().sum()),
    "of",
    len(res),
)
print("Columns:", ", ".join(res.columns))
