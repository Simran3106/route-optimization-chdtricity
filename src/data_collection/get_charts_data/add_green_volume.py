"""
Adds a `Volume` column (green line value at each stop) to digitized_all.csv.

Reads the EXISTING overlay images (digitization_overlays/chart_<sr_no>.png):
  - yellow lines in the overlay = top of scale and zero baseline (already calibrated)
  - stop positions = same formula as the digitiser
No PDF, no chart detection, no scale detection is repeated. Nothing existing is modified.

RUN FROM THE PROJECT ROOT:
    python src/data_collection/get_charts_data/add_green_volume.py

OUTPUT: data/passengerdata/chart_data/digitized_all_with_volume.csv
"""
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from chart_functions import PLOT_LEFT, PLOT_RIGHT

CHART_DIR = Path("data/passengerdata/chart_data")
IN_CSV = CHART_DIR / "digitized_all.csv"
OVERLAY_DIR = CHART_DIR / "digitization_overlays"
OUT_CSV = CHART_DIR / "digitized_all_with_volume.csv"

# same as digitize_charts.py: (y_min, y_max, step); only y_max is used here
AXIS_OVERRIDES = {46: 120, 77: 120, 106: 100, 115: 120, 116: 140}
DEFAULT_Y_MAX = 100


def yellow_rows(img):
    """Rows of the two yellow guide lines the overlay drew (top and zero baseline)."""
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    yellow = (b < 150) & (g > 200) & (r > 200) & (abs(g - r) < 40)
    rows = np.where(yellow.mean(axis=1) > 0.5)[0]
    return int(rows.min()), int(rows.max())


def green_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([36, 60, 80]), np.array([85, 255, 255]))


def side_fit(mask, center, slot, side, t, b):
    """Fit the green segment beside a stop, outside the bars (they cover the line)."""
    w = mask.shape[1]
    x_lo, x_hi = sorted((round(center + side * 0.28 * slot), round(center + side * 0.46 * slot)))
    x_lo, x_hi = max(0, x_lo), min(w, x_hi + 1)
    ys, xs = np.where(mask[t:b + 1, x_lo:x_hi] > 0)
    if len(ys) < 8 or np.ptp(xs) < 4:
        return None
    return tuple(np.polyfit(xs + x_lo, ys + t, 1))        # slope, intercept


def read_volume(mask, center, slot, t, b, y_max):
    fits = [f for f in (side_fit(mask, center, slot, -1, t, b),
                        side_fit(mask, center, slot, +1, t, b)) if f is not None]
    if fits:
        y = float(np.mean([m * center + c for m, c in fits]))
        if len(fits) == 2:
            (m1, c1), (m2, c2) = fits
            if abs(m1 - m2) > 0.05:                       # a corner: use the vertex
                xv = (c2 - c1) / (m1 - m2)
                if abs(xv - center) <= 0.12 * slot:
                    y = m1 * xv + c1
    else:                                                 # fallback: pixels at the centre
        x1, x2 = max(0, round(center) - 3), min(mask.shape[1], round(center) + 4)
        yy, _ = np.where(mask[t:b + 1, x1:x2] > 0)
        if len(yy) < 3:
            return np.nan
        y = float(np.median(yy)) + t
    return float(np.ceil(max(0.0, min(y_max, (b - y) / (b - t) * y_max))))


def main():
    df = pd.read_csv(IN_CSV)
    volumes = {}
    for sr_no, g in df.groupby("sr_no"):
        path = OVERLAY_DIR / f"chart_{int(sr_no)}.png"
        img = cv2.imread(str(path))
        if img is None:
            print(f"sr_no {sr_no}: overlay not found ({path.name}) - Volume left empty")
            continue
        t, b = yellow_rows(img)
        w = img.shape[1]
        n = len(g)
        slot = w * (PLOT_RIGHT - PLOT_LEFT) / n
        mask = green_mask(img)
        y_max = AXIS_OVERRIDES.get(int(sr_no), DEFAULT_Y_MAX)
        for stop_no in g["stop_no"]:
            c = w * PLOT_LEFT + slot * (int(stop_no) - 0.5)
            volumes[(sr_no, stop_no)] = read_volume(mask, c, slot, t, b, y_max)

    df["Volume"] = [volumes.get((s, k), np.nan) for s, k in zip(df["sr_no"], df["stop_no"])]
    df.to_csv(OUT_CSV, index=False)
    print(f"Saved {OUT_CSV}  ({len(df)} rows, {df['sr_no'].nunique()} charts)")


if __name__ == "__main__":
    main()