"""
plot_bus_routes.py  ->  put in src/visualisation/

Interactive Folium map from the final stop-level CSV.
Stops are coloured AND sized by demand. Use the toggle (bottom-left of map)
to switch between:
    1. Volume     (blue = low, red = overcrowded)
    2. Boardings  (pale yellow = few, dark red = highest boardings)

Usage (from project root):
    python src/visualisation/plot_bus_routes.py
    python src/visualisation/plot_bus_routes.py --capacity 60      # >=60 = fully red
    python src/visualisation/plot_bus_routes.py --csv data/final/stops.csv --out outputs/bus_map.html
"""

import argparse
from pathlib import Path

import folium
import pandas as pd
from branca.colormap import LinearColormap

REQUIRED = [
    "route", "direction", "stop_order", "ctu_stop_id", "ctu_stop_name",
    "latitude", "longitude", "Boardings", "Alightings", "Volume",
]

# Route line colours (thin lines only; stop colours now come from the metric)
LINE_COLORS = [
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
    "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
]

VOL_COLORS = ["#2c7bb6", "#ffffbf", "#d7191c"]   # blue -> yellow -> red
BRD_COLORS = ["#ffffb2", "#fd8d3c", "#800026"]   # pale -> orange -> dark red


def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing columns: {missing}")

    for col in ["latitude", "longitude", "stop_order", "Boardings", "Alightings", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    n_before = len(df)
    df = df.dropna(subset=["latitude", "longitude", "stop_order"]).copy()
    dropped = n_before - len(df)
    if dropped:
        print(f"[warn] Dropped {dropped} rows with missing lat/lon/stop_order")

    df["route"] = df["route"].astype(str).str.strip()
    df["direction"] = df["direction"].astype(str).str.strip().str.upper()
    return df.sort_values(["route", "direction", "stop_order"])


def fmt(v):
    return "n/a" if pd.isna(v) else f"{v:,.0f}"


def make_scale(series: pd.Series, colors, vmax_override=None):
    vals = series.dropna()
    vmin = float(vals.min()) if len(vals) else 0.0
    vmax = float(vmax_override) if vmax_override else (float(vals.max()) if len(vals) else 1.0)
    if vmax <= vmin:
        vmax = vmin + 1
    return LinearColormap(colors, vmin=vmin, vmax=vmax), vmin, vmax


def color_of(cmap, val, fallback="#999999"):
    return fallback if pd.isna(val) else cmap(val)


def size_of(val, vmin, vmax, lo=22, hi=40):
    if pd.isna(val):
        return lo
    t = min(max((val - vmin) / (vmax - vmin), 0), 1)
    return int(lo + (hi - lo) * t)


def stop_icon(number, vol_col, brd_col, size) -> folium.DivIcon:
    """Marker with both colours stored as CSS variables; the toggle picks which one shows."""
    html = f"""
    <div class="stopdot" style="--vol:{vol_col};--brd:{brd_col};
         width:{size}px;height:{size}px;line-height:{size - 4}px;">{number}</div>"""
    return folium.DivIcon(html=html, icon_size=(size, size), icon_anchor=(size // 2, size // 2))


def popup_html(row) -> str:
    return f"""
    <div style="font-size:13px;min-width:190px">
      <b>{row.ctu_stop_name}</b><br>
      Stop ID: {row.ctu_stop_id}<br>
      Route: {row.route} ({row.direction})<br>
      Stop order: {int(row.stop_order)}<hr style="margin:4px 0">
      Boardings: {fmt(row.Boardings)}<br>
      Alightings: {fmt(row.Alightings)}<br>
      Volume (chart green line): {fmt(row.Volume)}
    </div>"""


def gradient_css(colors):
    return "linear-gradient(to right, " + ", ".join(colors) + ")"


def add_toggle_ui(m, vol_range, brd_range, capacity):
    vol_note = f" (red &ge; {capacity:g})" if capacity else ""
    html = f"""
    <style>
      .stopdot {{
        border:2px solid white; border-radius:50%; color:#111; text-align:center;
        font-size:11px; font-weight:bold; box-shadow:0 0 3px rgba(0,0,0,.7);
        box-sizing:border-box;
      }}
      body.mode-vol .stopdot {{ background: var(--vol) !important; }}
      body.mode-brd .stopdot {{ background: var(--brd) !important; }}
      #modebox {{
        position:fixed; bottom:24px; left:12px; z-index:9999; background:white;
        padding:10px 12px; border-radius:8px; box-shadow:0 1px 6px rgba(0,0,0,.4);
        font-family:Arial,sans-serif; font-size:13px; width:250px;
      }}
      #modebox button {{
        padding:6px 10px; margin-right:4px; border:1px solid #888; border-radius:5px;
        background:#eee; cursor:pointer; font-size:12px;
      }}
      body.mode-vol #btn-vol, body.mode-brd #btn-brd {{ background:#333; color:white; }}
      .grad {{ height:12px; border-radius:3px; margin:6px 0 2px; }}
      .lbls {{ display:flex; justify-content:space-between; font-size:11px; }}
      body.mode-vol #leg-brd, body.mode-brd #leg-vol {{ display:none; }}
    </style>
    <div id="modebox">
      <b>Colour stops by</b><br><br>
      <button id="btn-vol" onclick="setMode('vol')">Volume</button>
      <button id="btn-brd" onclick="setMode('brd')">Boardings</button>
      <div id="leg-vol" style="margin-top:10px">
        Volume{vol_note}
        <div class="grad" style="background:{gradient_css(VOL_COLORS)}"></div>
        <div class="lbls"><span>{vol_range[0]:,.0f} (low)</span><span>{vol_range[1]:,.0f} (overcrowded)</span></div>
      </div>
      <div id="leg-brd" style="margin-top:10px">
        Boardings
        <div class="grad" style="background:{gradient_css(BRD_COLORS)}"></div>
        <div class="lbls"><span>{brd_range[0]:,.0f} (few)</span><span>{brd_range[1]:,.0f} (highest)</span></div>
      </div>
      <div style="margin-top:6px;font-size:11px;color:#555">Bigger circle = higher value</div>
    </div>
    <script>
      function setMode(m) {{
        document.body.classList.remove('mode-vol', 'mode-brd');
        document.body.classList.add('mode-' + m);
      }}
      setMode('vol');
    </script>"""
    m.get_root().html.add_child(folium.Element(html))


def build_map(df: pd.DataFrame, capacity=None) -> folium.Map:
    m = folium.Map(
        location=[df["latitude"].mean(), df["longitude"].mean()],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    vol_cmap, vol_min, vol_max = make_scale(df["Volume"], VOL_COLORS, capacity)
    brd_cmap, brd_min, brd_max = make_scale(df["Boardings"], BRD_COLORS)
    add_toggle_ui(m, (vol_min, vol_max), (brd_min, brd_max), capacity)

    # Layer: all unique stops (plain dots), hidden by default
    all_stops = folium.FeatureGroup(name="All stops (unique)", show=False)
    for row in df.drop_duplicates("ctu_stop_id").itertuples():
        folium.CircleMarker(
            [row.latitude, row.longitude], radius=3, color="#444",
            fill=True, fill_opacity=0.8, tooltip=row.ctu_stop_name,
        ).add_to(all_stops)
    all_stops.add_to(m)

    # One group per route + direction
    for i, ((route, direction), g) in enumerate(df.groupby(["route", "direction"], sort=True)):
        line_color = LINE_COLORS[i % len(LINE_COLORS)]
        fg = folium.FeatureGroup(name=f"Route {route} - {direction}", show=(i == 0))

        coords = g[["latitude", "longitude"]].values.tolist()
        if len(coords) > 1:
            folium.PolyLine(
                coords, color=line_color, weight=3, opacity=0.5,
                tooltip=f"Route {route} {direction} (straight-line, not road path)",
            ).add_to(fg)

        for row in g.itertuples():
            vcol = color_of(vol_cmap, row.Volume)
            bcol = color_of(brd_cmap, row.Boardings)
            # size follows the active-looking metric: use the larger relative signal of the two
            size = max(size_of(row.Volume, vol_min, vol_max),
                       size_of(row.Boardings, brd_min, brd_max))
            folium.Marker(
                [row.latitude, row.longitude],
                icon=stop_icon(int(row.stop_order), vcol, bcol, size),
                popup=folium.Popup(popup_html(row), max_width=280),
                tooltip=(f"{int(row.stop_order)}. {row.ctu_stop_name} | "
                         f"Vol {fmt(row.Volume)} | Board {fmt(row.Boardings)}"),
            ).add_to(fg)

        fg.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv",
                   default="data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV",
                   help="Path to final stop-level CSV")
    p.add_argument("--out", default="outputs/bus_routes_map.html")
    p.add_argument("--capacity", type=float, default=None,
                   help="Volume at/above which a stop counts as overcrowded (fully red). "
                        "Default: highest volume in the data.")
    args, _unknown = p.parse_known_args()

    df = load_data(Path(args.csv))
    print(f"Loaded {len(df)} rows | {df['route'].nunique()} routes | "
          f"{df['ctu_stop_id'].nunique()} unique stops")

    m = build_map(df, capacity=args.capacity)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out))
    print(f"Saved -> {out.resolve()}  (open in a browser)")


if __name__ == "__main__":
    main()