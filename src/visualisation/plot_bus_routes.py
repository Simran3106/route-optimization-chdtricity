"""
src/visualisation/plot_bus_routes.py

Interactive Folium map for CTU bus route optimization.
Visualizes:
  1. Actual road-network trajectories (from GeoJSON) for:
     - Approach A: Reconstructed original-sequence road baseline
     - Approach B: Constrained Local Search
     - Approach C: Constrained Genetic Algorithm (GA)
  2. Stop occurrences colored and sized by historical demand (Volume / Boardings toggle)
  3. Detailed popups showing stop ID, name, sequence order, boardings, alightings, and volume
  4. Layer controls to toggle individual model trajectories and stop groups

Usage:
  python -m src.visualisation.plot_bus_routes
  python -m src.visualisation.plot_bus_routes --geojson outputs/optimized_paths.geojson --out outputs/route_map.html
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import folium
import pandas as pd
from branca.colormap import LinearColormap

REQUIRED_COLUMNS = [
    "route", "direction", "ctu_stop_id", "ctu_stop_name",
    "latitude", "longitude", "Boardings", "Alightings", "Volume",
]

MODEL_STYLES = {
    "Reconstructed_Baseline": {
        "label": "Approach A: Reconstructed Baseline",
        "color": "#4363d8",  # rich blue
        "weight": 4,
        "opacity": 0.8,
        "dash_array": "6, 6",
    },
    "Constrained_Local_Search": {
        "label": "Approach B: Constrained Local Search",
        "color": "#f58231",  # bright orange
        "weight": 4,
        "opacity": 0.85,
        "dash_array": None,
    },
    "Constrained_GA_Best": {
        "label": "Approach C: Constrained Genetic Algorithm (GA)",
        "color": "#3cb44b",  # vibrant green
        "weight": 5,
        "opacity": 0.95,
        "dash_array": None,
    },
}

DEFAULT_MODEL_STYLE = {
    "label": "Optimized Route",
    "color": "#911eb4",  # purple
    "weight": 4,
    "opacity": 0.8,
    "dash_array": None,
}

VOL_COLORS = ["#2c7bb6", "#ffffbf", "#d7191c"]   # blue -> yellow -> red
BRD_COLORS = ["#ffffb2", "#fd8d3c", "#800026"]   # pale yellow -> orange -> dark red


def load_stop_data(csv_path: Path) -> pd.DataFrame:
    """Load stop sequence data from either original CSV or optimized_routes.csv."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    # Map order column
    if "optimized_stop_order" in df.columns:
        df["stop_order"] = df["optimized_stop_order"]
    elif "stop_order" not in df.columns and "original_stop_order" in df.columns:
        df["stop_order"] = df["original_stop_order"]

    for col in ["latitude", "longitude", "stop_order", "Boardings", "Alightings", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["latitude", "longitude"]).copy()
    if "stop_order" not in df.columns:
        df["stop_order"] = range(1, len(df) + 1)
    else:
        df["stop_order"] = df["stop_order"].fillna(0).astype(int)

    df["route"] = df["route"].astype(str).str.strip()
    df["direction"] = df["direction"].astype(str).str.strip().str.upper()
    return df


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
    html = f"""
    <div class="stopdot" style="--vol:{vol_col};--brd:{brd_col};
         width:{size}px;height:{size}px;line-height:{size - 4}px;">{number}</div>"""
    return folium.DivIcon(html=html, icon_size=(size, size), icon_anchor=(size // 2, size // 2))


def popup_html(row) -> str:
    orig_order_str = ""
    if hasattr(row, "original_stop_order") and pd.notna(row.original_stop_order):
        orig_order_str = f"Original stop order: {int(row.original_stop_order)}<br>"

    model_str = ""
    if hasattr(row, "model") and pd.notna(row.model):
        model_str = f"Model: {row.model}<br>"

    return f"""
    <div style="font-size:13px;min-width:210px;font-family:Arial,sans-serif">
      <b style="color:#111;font-size:14px">{row.ctu_stop_name}</b><br>
      <span style="color:#555">Stop ID: {row.ctu_stop_id}</span><br>
      Route: {row.route} ({row.direction})<br>
      {model_str}
      Stop order: {int(row.stop_order)}<br>
      {orig_order_str}
      <hr style="margin:6px 0;border:none;border-top:1px solid #ddd">
      <b>Historical Sample Demand:</b><br>
      Boardings: <b>{fmt(row.Boardings)}</b><br>
      Alightings: <b>{fmt(row.Alightings)}</b><br>
      Volume (chart section load): <b>{fmt(row.Volume)}</b>
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
        padding:12px 14px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,.35);
        font-family:Arial,sans-serif; font-size:13px; width:260px; line-height:1.4;
      }}
      #modebox button {{
        padding:6px 12px; margin-right:6px; border:1px solid #777; border-radius:4px;
        background:#f0f0f0; cursor:pointer; font-size:12px; font-weight:bold;
      }}
      body.mode-vol #btn-vol, body.mode-brd #btn-brd {{ background:#1a237e; color:white; border-color:#1a237e; }}
      .grad {{ height:12px; border-radius:3px; margin:6px 0 2px; }}
      .lbls {{ display:flex; justify-content:space-between; font-size:11px; }}
      body.mode-vol #leg-brd, body.mode-brd #leg-vol {{ display:none; }}
      .legend-box {{ margin-top:10px; border-top:1px solid #eee; padding-top:8px; font-size:12px; }}
      .legend-item {{ display:flex; align-items:center; margin-bottom:4px; }}
      .legend-color {{ width:22px; height:6px; margin-right:8px; border-radius:2px; display:inline-block; }}
    </style>
    <div id="modebox">
      <b>Color Stops By</b><br><br>
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
      <div style="margin-top:6px;font-size:11px;color:#555">Bigger circle = higher demand</div>
      <div class="legend-box">
        <b>Road Alignments:</b><br>
        <div class="legend-item"><span class="legend-color" style="background:#4363d8;border-top:2px dashed #4363d8;height:0;"></span>Baseline (reconstructed)</div>
        <div class="legend-item"><span class="legend-color" style="background:#f58231;"></span>Local Search</div>
        <div class="legend-item"><span class="legend-color" style="background:#3cb44b;height:8px;"></span>Constrained GA (Best)</div>
      </div>
    </div>
    <script>
      function setMode(m) {{
        document.body.classList.remove('mode-vol', 'mode-brd');
        document.body.classList.add('mode-' + m);
      }}
      setMode('vol');
    </script>"""
    m.get_root().html.add_child(folium.Element(html))


def build_comparison_map(
    stops_df: pd.DataFrame,
    geojson_path: Optional[Path] = None,
    capacity: Optional[float] = None,
) -> folium.Map:
    """
    Build Folium map integrating actual road geometries from GeoJSON
    with demand-styled stop markers.
    """
    center_lat = float(stops_df["latitude"].mean())
    center_lon = float(stops_df["longitude"].mean())

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    vol_cmap, vol_min, vol_max = make_scale(stops_df["Volume"], VOL_COLORS, capacity)
    brd_cmap, brd_min, brd_max = make_scale(stops_df["Boardings"], BRD_COLORS)
    add_toggle_ui(m, (vol_min, vol_max), (brd_min, brd_max), capacity)

    # 1. Road-network Trajectories from GeoJSON
    if geojson_path and geojson_path.exists():
        with open(geojson_path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)

        features = geojson_data.get("features", [])
        for feat in features:
            props = feat.get("properties", {})
            model_key = props.get("model", "")
            r_num = props.get("route", "")
            r_dir = props.get("direction", "")
            d_km = props.get("distance_km", 0.0)
            t_min = props.get("estimated_travel_time_min", 0.0)
            disp = props.get("demand_weighted_disruption", 0.0)

            style = MODEL_STYLES.get(model_key, DEFAULT_MODEL_STYLE)
            group_name = f"{style['label']} ({d_km:.2f} km, {t_min:.1f} min)"
            is_shown = (model_key in ["Constrained_GA_Best", "Reconstructed_Baseline"])

            fg_road = folium.FeatureGroup(name=group_name, show=is_shown)

            # Coordinates in GeoJSON are [lon, lat], folium PolyLine expects [lat, lon]
            raw_coords = feat.get("geometry", {}).get("coordinates", [])
            lat_lon_coords = [[pt[1], pt[0]] for pt in raw_coords]

            if lat_lon_coords:
                folium.PolyLine(
                    locations=lat_lon_coords,
                    color=style["color"],
                    weight=style["weight"],
                    opacity=style["opacity"],
                    dash_array=style["dash_array"],
                    tooltip=(f"{model_key} | Route {r_num} {r_dir} | "
                             f"Distance: {d_km:.2f} km | Est. Time: {t_min:.1f} min | "
                             f"Disruption: {disp:.2f}"),
                ).add_to(fg_road)

            fg_road.add_to(m)

    # 2. Stop Markers Group
    # Group by model or use baseline stops
    if "model" in stops_df.columns:
        # Show stops for GA_Best by default, and provide groups for others
        models = stops_df["model"].unique()
    else:
        models = ["Stops"]

    for m_name in models:
        sub_df = stops_df[stops_df["model"] == m_name] if "model" in stops_df.columns else stops_df
        style = MODEL_STYLES.get(m_name, DEFAULT_MODEL_STYLE)
        fg_stops = folium.FeatureGroup(name=f"Stops - {style['label']}", show=(m_name == "Constrained_GA_Best" or len(models) == 1))

        for row in sub_df.itertuples():
            vcol = color_of(vol_cmap, row.Volume)
            bcol = color_of(brd_cmap, row.Boardings)
            size = max(size_of(row.Volume, vol_min, vol_max),
                       size_of(row.Boardings, brd_min, brd_max))

            folium.Marker(
                [row.latitude, row.longitude],
                icon=stop_icon(int(row.stop_order), vcol, bcol, size),
                popup=folium.Popup(popup_html(row), max_width=300),
                tooltip=(f"{int(row.stop_order)}. {row.ctu_stop_name} | "
                         f"Vol: {fmt(row.Volume)} | Board: {fmt(row.Boardings)} | Alight: {fmt(row.Alightings)}"),
            ).add_to(fg_stops)

        fg_stops.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


def main():
    parser = argparse.ArgumentParser(description="Render interactive comparison map for bus route optimization")
    parser.add_argument("--csv", default="outputs/optimized_routes.csv",
                        help="Path to optimized routes CSV or standard stop CSV")
    parser.add_argument("--geojson", default="outputs/optimized_paths.geojson",
                        help="Path to optimized road paths GeoJSON")
    parser.add_argument("--out", default="outputs/route_map.html",
                        help="Output HTML path")
    parser.add_argument("--capacity", type=float, default=None,
                        help="Volume at which a stop is deemed overcrowded (default: max volume)")
    args = parser.parse_args()

    project_root = Path.cwd()
    csv_path = project_root / args.csv
    geojson_path = project_root / args.geojson
    out_path = project_root / args.out

    if not csv_path.exists():
        # Fallback to primary boarding CSV if optimization hasn't run yet
        fallback_csv = project_root / "data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV"
        if fallback_csv.exists():
            print(f"[warn] {csv_path} not found. Using fallback primary CSV: {fallback_csv}")
            csv_path = fallback_csv
        else:
            raise FileNotFoundError(f"Neither {csv_path} nor {fallback_csv} could be found.")

    stops_df = load_stop_data(csv_path)
    print(f"[Map] Loaded {len(stops_df)} stop records from {csv_path}")

    geojson_to_use = geojson_path if geojson_path.exists() else None
    if geojson_to_use:
        print(f"[Map] Integrating road trajectories from {geojson_to_use}")
    else:
        print("[Map] GeoJSON road trajectories not found, rendering stops only.")

    m = build_comparison_map(stops_df, geojson_path=geojson_to_use, capacity=args.capacity)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"[Map] Successfully generated interactive map -> {out_path.resolve()}")

    # Also save to outputs/maps/route_map.html if maps directory exists
    maps_dir = project_root / "outputs" / "maps"
    if maps_dir.exists():
        m.save(str(maps_dir / "route_map.html"))


if __name__ == "__main__":
    main()
