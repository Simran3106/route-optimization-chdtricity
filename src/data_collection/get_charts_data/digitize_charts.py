"""
Full automation: PDF pages 17-75 -> one CSV of boardings / alightings per stop.
Uses the functions in chart_functions.py (same folder).

RUN FROM THE PROJECT ROOT (the folder that contains data/, docs/, src/):
    python src/data_collection/get_charts_data/digitize_charts.py

INPUT
    docs/PASSENGER DATA.pdf
    data/passengerdata/chart_stops_editable.csv

OUTPUT
    data/passengerdata/digitized_all.csv      sr_no, stop_no, Boardings, Alightings,
                                              Low Confidence, Capacity Check
    data/passengerdata/digitized_qa_flags.csv charts that need a look at the overlay
    data/passengerdata/digitization_overlays/chart_<sr_no>.png   (if SAVE_OVERLAYS)
    data/passengerdata/digitization_log.txt   skipped pages / errors
"""
from pathlib import Path

import cv2
import pymupdf as fitz
import pandas as pd

from chart_functions import (
    crop_charts,
    detect_chart_boxes,
    digitize_chart,
    render_page,
)

# ============================================================
# SETTINGS  (edit here only)
# ============================================================

PDF_PATH = Path("docs/PASSENGER DATA.pdf")
STOPS_CSV = Path("data/passengerdata/chart_data/chart_stops_editable.csv")
OUT_CSV = Path("data/passengerdata/chart_data/digitized_all.csv")
QA_CSV = Path("data/passengerdata/chart_data/digitized_qa_flags.csv")
LOG_TXT = Path("data/passengerdata/chart_data/digitization_log.txt")
OVERLAY_DIR = Path("data/passengerdata/chart_data/digitization_overlays")
DEBUG_DIR = Path("data/passengerdata/chart_data/digitization_debug")   # only used if detection fails

# PDF pages to process. Test first with e.g. [17, 18], then use the full range.
PAGES = list(range(17, 76))          # 17..75
# PAGES = [17, 18]

SAVE_OVERLAYS = True                 # one small PNG per chart, for spot-checking

# ---- column names in chart_stops_editable.csv (change here if the CSV changes) ----
SR_COL = "sr_no"          # chart serial, 1..118, in PDF order (UP, DOWN, UP, DOWN...)
STOPS_COL = "n_stops"     # number of stops (bar slots) in that chart
PAGE_COL = "pdf_page"     # page number written in the CSV
PDF_PAGE_OFFSET = 10      # real PDF page = pdf_page (CSV) + 10   (CSV 7 -> PDF 17)

# ---- charts whose y axis is NOT 0..100 with a gridline every 10 ----
# sr_no: (y_min, y_max, gridline step)   -> read from the axis labels of each chart
AXIS_OVERRIDES = {
    46: (0, 120, 20),      # 205AC DOWN
    77: (0, 120, 20),      # 212 UP   (page 55)
    106: (-20, 100, 20),   # 26AC DOWN
    115: (0, 120, 20),     # 216AC UP
    116: (0, 140, 20),     # 216AC DOWN
}
DEFAULT_AXIS = (0, 100, 10)


# ============================================================
# 3. MAIN LOOP
# ============================================================

def main():
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_PATH.resolve()}  "
                                f"(run this script from the project root)")
    if not STOPS_CSV.exists():
        raise FileNotFoundError(f"CSV not found: {STOPS_CSV.resolve()}")

    stops = pd.read_csv(STOPS_CSV, encoding="utf-8-sig")
    for col in (SR_COL, STOPS_COL, PAGE_COL):
        if col not in stops.columns:
            raise KeyError(f"Column '{col}' missing in {STOPS_CSV.name}. "
                           f"Update the column names at the top of this script.")
    if stops[SR_COL].duplicated().any() or stops[[SR_COL, STOPS_COL, PAGE_COL]].isna().any().any():
        raise ValueError("sr_no must be unique and sr_no / n_stops / pdf_page must have no blanks.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    if SAVE_OVERLAYS:
        OVERLAY_DIR.mkdir(parents=True, exist_ok=True)

    frames, metas, log = [], [], []

    with fitz.open(PDF_PATH) as pdf:
        for page in PAGES:
            # charts that the CSV says belong to this PDF page, top (UP) to bottom (DOWN)
            rows = stops[stops[PAGE_COL] + PDF_PAGE_OFFSET == page].sort_values(SR_COL)
            print(f"\nPDF page {page}: sr_no {list(rows[SR_COL])}")

            if rows.empty:
                msg = f"page {page}: no rows in CSV for this page - skipped"
                print("  " + msg); log.append(msg)
                continue

            image = render_page(pdf, page)
            boxes = detect_chart_boxes(image)

            if len(boxes) != len(rows):          # charts inside one big outer frame
                nested_boxes = detect_chart_boxes(image, nested=True)
                if len(nested_boxes) == len(rows):
                    boxes = nested_boxes
                    log.append(f"page {page}: charts found with nested-frame detection - check overlays")
                    print("  (nested-frame detection used)")

            if len(boxes) != len(rows):
                dbg = image.copy()
                for x, y, w, h in boxes:
                    cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 0, 255), 4)
                cv2.imwrite(str(DEBUG_DIR / f"debug_page_{page:03d}.png"), dbg)
                msg = (f"page {page}: found {len(boxes)} charts, CSV expects {len(rows)} "
                       f"(sr_no {list(rows[SR_COL])}) - skipped, see debug_page_{page:03d}.png")
                print("  " + msg); log.append(msg)
                continue

            crops = crop_charts(image, boxes)
            for (_, row), crop in zip(rows.iterrows(), crops):
                sr_no, n_stops = int(row[SR_COL]), int(row[STOPS_COL])
                overlay = OVERLAY_DIR / f"chart_{sr_no}.png" if SAVE_OVERLAYS else None
                try:
                    df, meta = digitize_chart(crop, sr_no, n_stops, overlay,
                                              AXIS_OVERRIDES.get(sr_no, DEFAULT_AXIS))
                except Exception as e:                       # one bad chart must not stop the run
                    msg = f"sr_no {sr_no} (page {page}): ERROR {e!r}"
                    print("  " + msg); log.append(msg)
                    continue
                frames.append(df)
                metas.append(meta)
                flag = ("" if (not meta["Scale Source"].startswith("FALLBACK")
                               and meta["Capacity Check"]) else "   <<< CHECK")
                print(f"  sr_no {sr_no}: {n_stops} stops | {meta['Scale Source']} | "
                      f"capacity {meta['Capacity Reads']}{flag}")

    # ---------------- results ----------------
    if not frames:
        raise RuntimeError("No charts were digitised - see the messages above.")

    result = pd.concat(frames, ignore_index=True)
    result.to_csv(OUT_CSV, index=False)

    meta_df = pd.DataFrame(metas)
    qa = meta_df[meta_df["Scale Source"].str.startswith("FALLBACK")
                 | ~meta_df["Capacity Check"]
                 | (meta_df["Low Confidence Stops"] > 0)]
    qa.to_csv(QA_CSV, index=False)

    LOG_TXT.write_text("\n".join(log) if log else "No problems.", encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Charts digitised : {len(meta_df)}")
    print(f"Rows written     : {len(result)}  ->  {OUT_CSV}")
    print(f"Charts to check  : {len(qa)}  ->  {QA_CSV}")
    print(f"Skipped / errors : {len(log)}  ->  {LOG_TXT}")
    if len(qa):
        print("Check overlays for sr_no:", list(qa["sr_no"]))


if __name__ == "__main__":
    main()