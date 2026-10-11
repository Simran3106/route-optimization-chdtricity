"""
Chart functions (no paths, no loops - those live in digitize_charts.py).

  render_page(pdf, page_number)        PDF page -> image (in memory)
  detect_chart_boxes(image)            -> chart boxes, top to bottom
  crop_charts(image, boxes)            -> list of chart crops
  digitize_chart(image, sr_no, n_stops, overlay_path=None)
                                       -> (DataFrame of stops, QA meta dict)
"""
import cv2
import pymupdf as fitz
import numpy as np
import pandas as pd

DPI = 300

# ---- digitiser calibration (validated on Routes 3 and 11) ----
CAPACITY_VALUE = 70
PLOT_LEFT = 0.0917           # fractions of crop width
PLOT_RIGHT = 0.9784
HALF_SLOT_FRAC = 0.26        # search window = +/- 26 % of a slot
FALLBACK_TOP = 0.2065        # fractions of crop height (last resort, flagged)
FALLBACK_BASELINE = 0.654


# ============================================================
# 1. RENDER PAGE + DETECT THE CHARTS (in memory)
# ============================================================

def render_page(pdf, page_number):
    """Render a 1-indexed PDF page as an OpenCV BGR image."""
    page = pdf.load_page(page_number - 1)
    zoom = DPI / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                          colorspace=fitz.csRGB, alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3)
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def _innermost(boxes):
    """For pages where the two charts sit inside one big outer frame:
    drop near-identical duplicates, then drop every box that contains another."""
    uniq = []
    for b in sorted(boxes, key=lambda b: b[2] * b[3], reverse=True):
        x, y, w, h = b
        dup = False
        for ox, oy, ow, oh in uniq:
            ix = min(x + w, ox + ow) - max(x, ox)
            iy = min(y + h, oy + oh) - max(y, oy)
            if ix > 0 and iy > 0 and ix * iy > 0.9 * (w * h + ow * oh - ix * iy):   # IoU > 0.9
                dup = True
                break
        if not dup:
            uniq.append(b)

    tol = 6
    keep = []
    for x, y, w, h in uniq:
        contains_other = any(
            (ox >= x - tol and oy >= y - tol and ox + ow <= x + w + tol
             and oy + oh <= y + h + tol and (ow, oh) != (w, h))
            for ox, oy, ow, oh in uniq
        )
        if not contains_other:
            keep.append((x, y, w, h))
    return sorted(keep, key=lambda b: b[1])


def detect_chart_boxes(image, nested=False):
    """Return chart boxes (x, y, w, h) sorted top to bottom.
    nested=True: use when both charts are inside one big connected outer frame
    (the normal mode only sees that frame and rejects it)."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, width // 25), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, height // 40)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    lines = cv2.add(horizontal, vertical)
    closing = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    joined = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, closing)
    mode = cv2.RETR_LIST if nested else cv2.RETR_EXTERNAL
    contours, _ = cv2.findContours(joined, mode, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.45 or h < height * 0.08 or h > height * 0.45:
            continue
        if w / h < 1.3 or w > width * 0.95:
            continue
        candidates.append((x, y, w, h))

    if nested:
        return _innermost(candidates)

    candidates.sort(key=lambda b: b[1])
    merged = []
    for x, y, w, h in candidates:
        dup = None
        for i, (ox, oy, ow, oh) in enumerate(merged):
            overlap_y = min(y + h, oy + oh) - max(y, oy)
            overlap_x = min(x + w, ox + ow) - max(x, ox)
            if overlap_y > 0.5 * min(h, oh) and overlap_x > 0.5 * min(w, ow):
                dup = i
                break
        if dup is None:
            merged.append((x, y, w, h))
        else:
            ox, oy, ow, oh = merged[dup]
            left, top = min(x, ox), min(y, oy)
            right, bottom = max(x + w, ox + ow), max(y + h, oy + oh)
            merged[dup] = (left, top, right - left, bottom - top)

    merged.sort(key=lambda b: b[1])
    return merged


def crop_charts(image, boxes):
    """Crop each box (8 px padding, same as the validated extractor)."""
    height, width = image.shape[:2]
    pad = 8
    crops = []
    for x, y, w, h in boxes:
        crops.append(image[max(0, y - pad):min(height, y + h + pad),
                           max(0, x - pad):min(width, x + w + pad)])
    return crops


# ============================================================
# 2. DIGITISER (same logic as digitize_stops.py)
# ============================================================

def _group(values, gap=3):
    groups = []
    for v in values:
        if not groups or v > groups[-1][-1] + gap:
            groups.append([int(v)])
        else:
            groups[-1].append(int(v))
    return [sum(g) / len(g) for g in groups]


def _band(image):
    w = image.shape[1]
    return round(w * PLOT_LEFT), round(w * PLOT_RIGHT)


def find_capacity_row(image):
    h = image.shape[0]
    x1, x2 = _band(image)
    black = image[:, x1:x2].max(axis=2) < 60
    rows = np.where(black.mean(axis=1) > 0.25)[0]
    rows = rows[(rows > h * 0.05) & (rows < h * 0.95)]
    groups = _group(rows, gap=6)
    return groups[0] if groups else None


def _grid_rows(gray, x1, x2, thr):
    h = gray.shape[0]
    band = gray[:, x1:x2] < thr
    rows = np.where(band.mean(axis=1) > 0.55)[0]
    rows = rows[(rows > h * 0.05) & (rows < h * 0.95)]
    return _group(rows)


def find_vertical_scale(image, axis=(0, 100, 10)):
    """axis = (y_min, y_max, step) of the chart's y axis.
    Return (top_y [= y_max line], baseline_y [= 0 line], source)."""
    y_min, y_max, step = axis
    n_lines = (y_max - y_min) // step + 1          # gridlines expected
    zero_idx = y_max // step                       # index of the 0 line, counted from the top
    cap_idx = (y_max - CAPACITY_VALUE) / step      # capacity line, counted from the top

    h = image.shape[0]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x1, x2 = _band(image)

    for thr in (240, 245, 250):                         # a. exactly the expected gridlines
        lines = _grid_rows(gray, x1, x2, thr)
        if len(lines) == n_lines:
            return lines[0], lines[zero_idx], f"gridlines (thr {thr})"

    lines = _grid_rows(gray, x1, x2, 250)               # b. regular-grid fit
    if len(lines) >= 4:
        ys = np.array(lines)
        s0 = float(np.median(np.diff(ys)))
        k = np.round((ys - ys[0]) / s0).astype(int)
        if len(set(k)) == len(k) and k.max() <= n_lines - 1:
            slope, intercept = np.polyfit(k, ys, 1)
            resid = np.abs(ys - (intercept + slope * k)).max()
            if resid < 3:
                if k.max() == n_lines - 1:
                    return intercept, intercept + zero_idx * slope, "grid fit"
                cap = find_capacity_row(image)
                if cap is not None:
                    top = cap - cap_idx * slope
                    return top, top + zero_idx * slope, "capacity anchor (+grid spacing)"

    cap = find_capacity_row(image)                      # c. capacity anchor
    if cap is not None and len(lines) >= 2:
        s = float(np.median(np.diff(lines)))
        if s > 5:
            top = cap - cap_idx * s
            return top, top + zero_idx * s, "capacity anchor"

    return (h * FALLBACK_TOP, h * FALLBACK_BASELINE,    # d. fallback (only right for 0..100)
            f"FALLBACK ({len(lines)} gridlines found)")


def make_masks(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([90, 60, 50]), np.array([135, 255, 255]))
    soft_blue = cv2.inRange(hsv, np.array([90, 25, 50]), np.array([135, 255, 255]))
    red = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([0, 70, 50]), np.array([12, 255, 255])),
        cv2.inRange(hsv, np.array([165, 70, 50]), np.array([180, 255, 255])),
    )
    return blue, soft_blue, red


def _window(center, half, width):
    return max(0, round(center) - half), min(width, round(center) + half + 1)


def _to_value(top_y, top, base, y_max):
    v = (base - top_y) / (base - top) * y_max
    return int(round(max(0, min(y_max, v))))


def estimate_blue(mask, soft, center, half, width, top, base, y_max):
    """Returns (value, low_confidence)."""
    x1, x2 = _window(center, half, width)
    t, b = int(round(top)), int(round(base))
    roi = mask[t:b + 1, x1:x2]
    active = np.count_nonzero(roi, axis=1) >= 2
    n = len(active)

    lo = max(0, n - 7)
    near = np.where(active[lo:])[0]
    if len(near) > 0:
        start = lo + near[-1]
        top_idx, gap, j = start, 0, start - 1
        while j >= 0:
            if active[j]:
                top_idx, gap = j, 0
            else:
                gap += 1
                if gap > 3:
                    break
            j -= 1
        if start - top_idx >= 3:
            return _to_value(t + top_idx, top, base, y_max), False

    soft_px = np.count_nonzero(soft[b - 6:b + 1, x1:x2])
    if soft_px >= 8:
        return 1, True
    return 0, False


def estimate_red(mask, center, half, width, top, base, y_max):
    x1, x2 = _window(center, half, width)
    t, b = int(round(top)), int(round(base))
    roi = mask[t:b + 1, x1:x2]
    ys, _ = np.where(roi > 0)
    if len(ys) < 4:
        return 0
    return _to_value(int(ys.min()) + t, top, base, y_max)


def digitize_chart(image, sr_no, n_stops, overlay_path=None, axis=(0, 100, 10)):
    """Returns (DataFrame of stops, meta dict for QA)."""
    h, w = image.shape[:2]
    y_max = axis[1]
    top, base, source = find_vertical_scale(image, axis)
    blue, soft, red = make_masks(image)

    t, b = int(round(top)), int(round(base))
    for m in (blue, soft, red):
        m[:t, :] = 0
        m[b + 1:, :] = 0

    slot = w * (PLOT_RIGHT - PLOT_LEFT) / n_stops
    centers = w * PLOT_LEFT + slot * (np.arange(n_stops) + 0.5)
    half = max(3, round(slot * HALF_SLOT_FRAC))

    cap_row = find_capacity_row(image)
    cap_value = (None if cap_row is None
                 else round((base - cap_row) / (base - top) * y_max, 1))
    cap_ok = cap_value is not None and abs(cap_value - CAPACITY_VALUE) <= 4

    records = []
    for seq, c in enumerate(centers, start=1):
        board, low = estimate_blue(blue, soft, c, half, w, top, base, y_max)
        alight = estimate_red(red, c, half, w, top, base, y_max)
        records.append({
            "sr_no": sr_no,
            "stop_no": seq,
            "Boardings": board,
            "Alightings": alight,
            "Low Confidence": low,
            "Capacity Check": cap_ok,
        })

    if overlay_path is not None:
        dbg = image.copy()
        f = cv2.FONT_HERSHEY_SIMPLEX
        for y in (t, b):
            cv2.line(dbg, (0, y), (w - 1, y), (0, 255, 255), 1)
        for rec, c in zip(records, centers):
            x = round(c)
            cv2.line(dbg, (x, t), (x, b), (255, 0, 255), 1)
            cv2.putText(dbg, str(rec["stop_no"]), (x - 8, max(15, t - 30)),
                        f, 0.5, (255, 0, 255), 1, cv2.LINE_AA)
            cv2.putText(dbg, str(rec["Boardings"]), (x - 18, max(15, t - 12)),
                        f, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(dbg, str(rec["Alightings"]), (x + 2, max(15, t - 12)),
                        f, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.imwrite(str(overlay_path), dbg)

    df = pd.DataFrame(records)
    meta = {
        "sr_no": sr_no,
        "n_stops": n_stops,
        "Scale Source": source,
        "Axis": f"{axis[0]}..{axis[1]} step {axis[2]}",
        "Capacity Reads": cap_value,
        "Capacity Check": cap_ok,
        "Low Confidence Stops": int(df["Low Confidence"].sum()),
    }
    return df, meta