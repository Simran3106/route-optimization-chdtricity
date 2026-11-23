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
  4. Dynamic Route Selection: Supports filtering to individual routes/charts via CLI
     or exploring individual routes cleanly via LayerControls without map clutter.

Usage:
  python -m src.visualisation.plot_bus_routes
  python -m src.visualisation.plot_bus_routes --route 3 --direction UP
  python -m src.visualisation.plot_bus_routes --chart 1 --out outputs/route_3_map.html
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
import pandas as pd
from branca.colormap import LinearColormap

MODEL_STYLES = {
    "Reconstructed_Baseline": {
        "label": "Baseline",
        "color": "#4363d8",  # rich blue
        "weight": 4,
        "opacity": 0.8,
        "dash_array": "6, 6",
    },
    "Constrained_Local_Search": {
        "label": "Local Search",
        "color": "#f58231",  # bright orange
        "weight": 4,
        "opacity": 0.85,
        "dash_array": None,
    },
    "Constrained_GA_Best": {
        "label": "Constrained GA",
        "color": "#3cb44b",  # vibrant green
        "weight": 5,
        "opacity": 0.95,
        "dash_array": None,
    },
}

DEFAULT_MODEL_STYLE = {
    "label": "Optimized Route",
    "color": "#911eb4",
    "weight": 4,
    "opacity": 0.8,
    "dash_array": None,
}

VOL_COLORS = ["#2c7bb6", "#ffffbf", "#d7191c"]   # blue -> yellow -> red
BRD_COLORS = ["#ffffb2", "#fd8d3c", "#800026"]   # pale yellow -> orange -> dark red


def load_stop_data(
    csv_path: Path,
    route_filter: Optional[str] = None,
    direction_filter: Optional[str] = None,
    chart_filter: Optional[int] = None,
) -> pd.DataFrame:
    """Load stop sequence data from either original CSV or optimized_routes.csv with optional filtering."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    if "optimized_stop_order" in df.columns:
        df["stop_order"] = df["optimized_stop_order"]
    elif "stop_order" not in df.columns and "original_stop_order" in df.columns:
        df["stop_order"] = df["original_stop_order"]

    for col in ["latitude", "longitude", "stop_order", "Boardings", "Alightings", "Volume", "chart_no"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["latitude", "longitude"]).copy()
    if "stop_order" not in df.columns:
        df["stop_order"] = range(1, len(df) + 1)
    else:
        df["stop_order"] = df["stop_order"].fillna(0).astype(int)

    df["route"] = df["route"].astype(str).str.strip()
    df["direction"] = df["direction"].astype(str).str.strip().str.upper()

    # Apply filters if provided
    if chart_filter is not None and "chart_no" in df.columns:
        df = df[df["chart_no"] == chart_filter].copy()
    if route_filter is not None:
        df = df[df["route"].str.upper() == str(route_filter).strip().upper()].copy()
    if direction_filter is not None:
        df = df[df["direction"].str.upper() == str(direction_filter).strip().upper()].copy()

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

    c_no_str = f"Chart #{int(row.chart_no)}<br>" if hasattr(row, "chart_no") and pd.notna(row.chart_no) else ""

    snap = getattr(row, "snap_distance_m", None)
    snap_str = ""
    if pd.notna(snap):
        flag = " (above threshold)" if getattr(row, "snap_exceeds_threshold", False) else ""
        snap_str = f"Road snap: {float(snap):.1f} m{flag}<br>"

    return f"""
    <div style="font-size:13px;min-width:210px;font-family:Arial,sans-serif">
      <b style="color:#111;font-size:14px">{row.ctu_stop_name}</b><br>
      <span style="color:#555">Stop ID: {row.ctu_stop_id}</span><br>
      {c_no_str}
      Route: {row.route} ({row.direction})<br>
      {model_str}
      Stop order: {int(row.stop_order)}<br>
      {orig_order_str}
      {snap_str}
      <hr style="margin:6px 0;border:none;border-top:1px solid #ddd">
      <b>Historical Sample Demand:</b><br>
      Boardings: <b>{fmt(row.Boardings)}</b><br>
      Alightings: <b>{fmt(row.Alightings)}</b><br>
      Volume (chart section load): <b>{fmt(row.Volume)}</b>
    </div>"""


def gradient_css(colors):
    return "linear-gradient(to right, " + ", ".join(colors) + ")"


def add_toggle_ui(m, vol_range, brd_range, capacity, chart_options: Optional[List[Tuple[int, str]]] = None):
    vol_note = f" (red &ge; {capacity:g})" if capacity else ""

    dropdown_html = ""
    if chart_options and len(chart_options) > 1:
        opts = "\n".join([f'<option value="{c_no}">{label}</option>' for c_no, label in chart_options])
        dropdown_html = f"""
        <div style="margin-bottom:10px;">
          <b>Select Route / Chart:</b><br>
          <select id="route-picker" style="width:100%;padding:4px;margin-top:4px;font-size:12px;" onchange="handleRouteSelect(this.value)">
            {opts}
          </select>
        </div>
        """

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
        font-family:Arial,sans-serif; font-size:13px; width:280px; line-height:1.4;
        max-height:85vh; overflow-y:auto;
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
      {dropdown_html}
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

      function handleRouteSelect(c_no) {{
        // Find Leaflet layer control inputs and toggle them
        var inputs = document.querySelectorAll('.leaflet-control-layers-selector');
        inputs.forEach(function(inp) {{
          var span = inp.nextElementSibling;
          if (span) {{
            var txt = span.textContent;
            var isMatch = txt.indexOf('Ch ' + c_no + ':') !== -1 || txt.indexOf('Chart ' + c_no + ':') !== -1;
            if (isMatch && !inp.checked) {{
              inp.click();
            }} else if (!isMatch && inp.checked && txt.indexOf('Ch ') !== -1) {{
              inp.click();
            }}
          }}
        }});
      }}
    </script>"""
    m.get_root().html.add_child(folium.Element(html))


def build_comparison_map(
    stops_df: pd.DataFrame,
    geojson_path: Optional[Path] = None,
    capacity: Optional[float] = None,
    default_chart_no: Optional[int] = None,
) -> folium.Map:
    """
    Build Folium map integrating actual road geometries from GeoJSON
    with demand-styled stop markers. Prevents visual clutter by organizing
    features by chart and enabling only the primary/default chart on initial render.
    """
    center_lat = float(stops_df["latitude"].mean()) if not stops_df.empty else 30.7333
    center_lon = float(stops_df["longitude"].mean()) if not stops_df.empty else 76.7794

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    vol_cmap, vol_min, vol_max = make_scale(stops_df["Volume"], VOL_COLORS, capacity)
    brd_cmap, brd_min, brd_max = make_scale(stops_df["Boardings"], BRD_COLORS)

    # 1. Index GeoJSON paths by chart_no
    geojson_by_chart: Dict[int, List[Dict[str, Any]]] = {}
    if geojson_path and geojson_path.exists():
        with open(geojson_path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        for feat in geojson_data.get("features", []):
            c_no = int(feat.get("properties", {}).get("chart_no", 0))
            geojson_by_chart.setdefault(c_no, []).append(feat)

    # 2. Identify available charts
    available_charts = sorted(list(set(stops_df["chart_no"].unique()) | set(geojson_by_chart.keys())))
    if not available_charts:
        available_charts = [1]

    # Select initial active chart (Route 3 UP / Chart 1 if present, else first chart)
    initial_chart = default_chart_no if default_chart_no in available_charts else (1 if 1 in available_charts else available_charts[0])

    chart_options: List[Tuple[int, str]] = []

    # 3. Build FeatureGroups per chart to eliminate map clutter
    for idx, c_no in enumerate(available_charts):
        # Find route label
        sub_stops = stops_df[stops_df["chart_no"] == c_no]
        if not sub_stops.empty:
            r_name = str(sub_stops["route"].iloc[0])
            r_dir = str(sub_stops["direction"].iloc[0])
        else:
            r_name = f"R{c_no}"
            r_dir = ""

        chart_label = f"Ch {c_no}: Route {r_name} {r_dir}"
        chart_options.append((c_no, chart_label))

        is_active_initial = (c_no == initial_chart)

        # Parent feature group for this chart
        fg_chart = folium.FeatureGroup(name=chart_label, show=is_active_initial)

        # Add road paths for this chart
        feats = geojson_by_chart.get(c_no, [])
        for feat in feats:
            props = feat.get("properties", {})
            m_key = props.get("model", "")
            d_km = props.get("distance_km", 0.0)
            t_min = props.get("estimated_travel_time_min", 0.0)
            disp = props.get("demand_weighted_disruption", 0.0)

            key = next((model for model in MODEL_STYLES if m_key.endswith(model)), m_key)
            style = MODEL_STYLES.get(key, DEFAULT_MODEL_STYLE)
            network = props.get("road_network", "")
            source = f" | {network}" if network else ""
            raw_coords = feat.get("geometry", {}).get("coordinates", [])
            lat_lon_coords = [[pt[1], pt[0]] for pt in raw_coords]

            if lat_lon_coords:
                folium.PolyLine(
                    locations=lat_lon_coords,
                    color=style["color"],
                    weight=style["weight"],
                    opacity=style["opacity"],
                    dash_array=style["dash_array"],
                    tooltip=(f"{style['label']} | Route {r_name} {r_dir} (Ch {c_no}) | "
                             f"Dist: {d_km:.2f} km | Time: {t_min:.1f} min | Disruption: {disp:.2f}{source}"),
                ).add_to(fg_chart)

        # Add stops for this chart (use GA_Best or single stop sequence to prevent duplicate icons)
        if "model" in sub_stops.columns:
            plot_stops = sub_stops[sub_stops["model"].isin(["Constrained_GA_Best", "Balanced_Constrained_GA_Best"])]
            if plot_stops.empty:
                plot_stops = sub_stops[sub_stops["model"] == "Reconstructed_Baseline"]
        else:
            plot_stops = sub_stops

        for row in plot_stops.itertuples():
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
            ).add_to(fg_chart)

        fg_chart.add_to(m)

    add_toggle_ui(m, (vol_min, vol_max), (brd_min, brd_max), capacity, chart_options)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def main():
    parser = argparse.ArgumentParser(description="Render interactive comparison map for bus route optimization")
    parser.add_argument("--csv", default="outputs/optimized_routes.csv",
                        help="Path to optimized routes CSV or standard stop CSV")
    parser.add_argument("--geojson", default="outputs/optimized_paths.geojson",
                        help="Path to optimized road paths GeoJSON")
    parser.add_argument("--out", default="outputs/route_map.html",
                        help="Output HTML path")
    parser.add_argument("--route", type=str, default=None,
                        help="Filter map to a specific route (e.g., '3')")
    parser.add_argument("--direction", type=str, default=None,
                        help="Filter map to a specific direction ('UP' or 'DOWN')")
    parser.add_argument("--chart", type=int, default=None,
                        help="Filter map to a specific chart number (e.g., 1)")
    parser.add_argument("--capacity", type=float, default=None,
                        help="Volume at which a stop is deemed overcrowded (default: max volume)")
    args = parser.parse_args()

    project_root = Path.cwd()
    csv_path = project_root / args.csv
    geojson_path = project_root / args.geojson
    out_path = project_root / args.out

    if not csv_path.exists():
        fallback_csv = project_root / "data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV"
        if fallback_csv.exists():
            print(f"[warn] {csv_path} not found. Using fallback primary CSV: {fallback_csv}")
            csv_path = fallback_csv
        else:
            raise FileNotFoundError(f"Neither {csv_path} nor {fallback_csv} could be found.")

    stops_df = load_stop_data(
        csv_path,
        route_filter=args.route,
        direction_filter=args.direction,
        chart_filter=args.chart,
    )
    print(f"[Map] Loaded {len(stops_df)} stop records from {csv_path}")

    geojson_to_use = geojson_path if geojson_path.exists() else None
    if geojson_to_use:
        print(f"[Map] Integrating road trajectories from {geojson_to_use}")
    else:
        print("[Map] GeoJSON road trajectories not found, rendering stops only.")

    m = build_comparison_map(
        stops_df,
        geojson_path=geojson_to_use,
        capacity=args.capacity,
        default_chart_no=args.chart,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"[Map] Successfully generated uncluttered interactive map -> {out_path.resolve()}")

    if (project_root / "outputs" / "maps").exists():
        m.save(str(project_root / "outputs" / "maps" / "route_map.html"))


if __name__ == "__main__":
    main()
