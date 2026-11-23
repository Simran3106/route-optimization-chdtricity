"""Build a Folium comparison of reconstructed and optimized CTU service charts."""

import argparse
import json
from html import escape
from pathlib import Path
from typing import Optional

import folium
import pandas as pd
from branca.element import MacroElement, Template

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

def load_stop_data(
    csv_path: Path,
    route_filter: Optional[str] = None,
    direction_filter: Optional[str] = None,
    chart_filter: Optional[int] = None,
) -> pd.DataFrame:
    """Load stop sequence data from either original CSV or optimized_routes.csv with optional filtering."""
    df = pd.read_csv(csv_path, dtype={"route": str, "ctu_stop_id": str})
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


METRICS = {
    "Distance (km)": "km", "Estimated Travel Time (min)": "min",
    "Objective Value": "Objective", "Distance Improvement (%)": "Dist. %",
    "Objective Improvement (%)": "Obj. %", "Demand-Weighted Disruption": "Disruption",
    "Shortcut Penalty": "Shortcut", "Routing Status": "Status",
}


def display(value, decimals=2):
    if pd.isna(value):
        return "\u2014"
    return f"{value:.{decimals}f}" if isinstance(value, (float, int)) else str(value)


def add_comparison_controls(map_, charts, metadata, initial):
    panel = MacroElement()
    panel._name = "CTUComparison"
    panel.charts = json.dumps(metadata).replace("<", chr(92) + "u003c")
    panel.layers = "{" + ",".join(
        f'{chart}: [{",".join(layer.get_name() for layer in layers)}]' for chart, layers in charts.items()
    ) + "}"
    panel.initial = initial
    panel._template = Template("""
    {% macro html(this, kwargs) %}
    <style>
    #ctu-panel {position:fixed; top:12px; right:12px; z-index:1000; background:#fff;
      padding:12px; border-radius:8px; box-shadow:0 2px 10px #0004;
      width:min(590px,88vw); max-height:48vh; overflow:auto; font:13px system-ui;}
    #ctu-panel fieldset {border:0; padding:5px 0; margin:4px 0;}
    #ctu-panel label {margin-right:8px; display:inline-block;}
    #ctu-panel select {margin-left:4px;}
    #ctu-metrics {width:100%; border-collapse:collapse; font-size:12px;}
    #ctu-metrics th, #ctu-metrics td {border-bottom:1px solid #ddd; padding:4px; text-align:right;}
    #ctu-metrics th:first-child, #ctu-metrics td:first-child {text-align:left;}
    </style>
    <section id="ctu-panel" aria-label="CTU chart comparison">
      <fieldset>
        <label>Route<select id="ctu-route"></select></label>
        <label>Direction<select id="ctu-direction"></select></label>
        <label>Chart<select id="ctu-chart"></select></label>
      </fieldset>
      <fieldset>
        <label style="color:#2442ad"><input type="checkbox" data-model="0" checked>Dashed baseline</label>
        <label style="color:#a24400"><input type="checkbox" data-model="1" checked>Local search</label>
        <label style="color:#18732a"><input type="checkbox" data-model="2" checked>Genetic algorithm</label>
      </fieldset>
      <table id="ctu-metrics"></table>
      <small>Times are estimated. S/E mark terminals. Stop popups list historical counts and model orders.</small>
    </section>
    {% endmacro %}
    {% macro script(this, kwargs) %}
    (() => {
      const map = {{ this._parent.get_name() }};
      const metadata = {{ this.charts | safe }};
      const layers = {{ this.layers | safe }};
      const route = document.getElementById('ctu-route');
      const direction = document.getElementById('ctu-direction');
      const chart = document.getElementById('ctu-chart');
      const toggles = [...document.querySelectorAll('#ctu-panel input[data-model]')];
      const metrics = document.getElementById('ctu-metrics');
      const numbers = Object.keys(metadata);
      let active;
      function options(select, values, desired) {
        select.replaceChildren(...values.map(value => new Option(value, value)));
        if (values.includes(desired)) select.value = desired;
      }
      function render(refit) {
        const next = chart.value;
        if (active !== next && active) layers[active].forEach(layer => map.removeLayer(layer));
        active = next;
        const [baseline, local, ga, stops] = layers[active];
        [baseline, local, ga].forEach((layer, i) => {
          if (map.hasLayer(layer)) map.removeLayer(layer);
          if (toggles[i].checked) layer.addTo(map);
        });
        if (!map.hasLayer(stops)) stops.addTo(map);
        const bounds = L.latLngBounds([]);
        layers[active].forEach(layer => bounds.extend(layer.getBounds()));
        if (refit && bounds.isValid()) map.fitBounds(bounds, {padding: [24, 24], maxZoom: 16});
        metrics.replaceChildren();
        for (const [i, row] of metadata[active].metrics.entries()) {
          const tr = metrics.insertRow();
          row.forEach(value => {
            const cell = document.createElement(i === 0 ? 'th' : 'td');
            cell.textContent = value;
            tr.append(cell);
          });
        }
      }
      function setCharts(desired) {
        options(chart, numbers.filter(n => metadata[n].route === route.value
                                         && metadata[n].direction === direction.value), desired);
        render(true);
      }
      function setDirections(desiredDirection, desiredChart) {
        options(direction, [...new Set(numbers.filter(n => metadata[n].route === route.value)
            .map(n => metadata[n].direction))], desiredDirection);
        setCharts(desiredChart);
      }
      const initial = String({{ this.initial }});
      options(route, [...new Set(numbers.map(n => metadata[n].route))], metadata[initial].route);
      route.addEventListener('change', () => setDirections(direction.value));
      direction.addEventListener('change', () => setCharts());
      chart.addEventListener('change', () => render(true));
      toggles.forEach(toggle => toggle.addEventListener('change', () => render(false)));
      setDirections(metadata[initial].direction, initial);
    })();
    {% endmacro %}
    """)
    panel.add_to(map_)


def stop_popup(rows, terminal_order):
    items = []
    for original, occurrences in rows.groupby("original_stop_order", sort=True):
        row = occurrences.iloc[0]
        label = "Start" if original == terminal_order[0] else "End" if original == terminal_order[1] else "Stop"
        name = escape(str(row.ctu_stop_name))
        stop_id = escape(str(row.ctu_stop_id)) if pd.notna(row.ctu_stop_id) else "\u2014"
        orders = []
        for item in occurrences.itertuples():
            model = MODEL_STYLES.get(item.model, {}).get("label", "Historical")
            changed = " (moved)" if item.stop_order != original else ""
            orders.append(f"{model} #{item.stop_order}{changed}")
        items.append(
            f"<b>{label} #{original} | {name}</b> ({stop_id})<br>"
            f"{row.latitude:.6f}, {row.longitude:.6f}<br>{' | '.join(orders)}<br>"
            f"Historical boardings {display(row.Boardings, 0)} | alightings {display(row.Alightings, 0)}"
        )
    return "<hr>".join(items)


def build_comparison_map(
    stops_df: pd.DataFrame,
    geojson_path: Optional[Path] = None,
    capacity: Optional[float] = None,
    default_chart_no: Optional[int] = None,
    comparison_path: Optional[Path] = None,
) -> folium.Map:
    """Show one chart at a time, with three independently controllable road layers."""
    if stops_df.empty:
        raise ValueError("No stop records match the selected filters")
    m = folium.Map(location=[stops_df.latitude.mean(), stops_df.longitude.mean()],
                   zoom_start=12, control_scale=True)
    stops_df = stops_df.copy()
    if "original_stop_order" not in stops_df:
        stops_df["original_stop_order"] = stops_df["stop_order"]
    if "model" not in stops_df:
        stops_df["model"] = "Historical"
    groups = stops_df.groupby("chart_no")
    path_groups = {}
    if geojson_path and geojson_path.exists():
        for feature in json.loads(geojson_path.read_text(encoding="utf-8"))["features"]:
            props = feature["properties"]
            path_groups[props["chart_no"], props["model"]] = feature["geometry"]["coordinates"]
    comparison = {}
    if comparison_path and comparison_path.exists():
        values = pd.read_csv(comparison_path)
        comparison = values.set_index(["Chart Number", "Model"]).to_dict("index")

    charts, metadata = {}, {}
    for chart_no, stops in groups:
        chart_no = int(chart_no)
        layers = []
        metrics = [["Model", *METRICS.values()]]
        prefix = "Balanced_" if stops["model"].str.startswith("Balanced_").any() else ""
        stops = stops[stops["model"].str.startswith(prefix)] if prefix else stops
        stops = stops.assign(model=stops["model"].str.removeprefix(prefix))
        for (model, style), weight in zip(MODEL_STYLES.items(), (11, 7, 3)):
            layer = folium.FeatureGroup(show=False, control=False).add_to(m)
            layers.append(layer)
            coords = path_groups.get((chart_no, prefix + model), [])
            if len(coords) >= 2:
                folium.PolyLine([(lat, lon) for lon, lat in coords], color=style["color"],
                                weight=weight, opacity=0.9, dash_array=style["dash_array"],
                                tooltip=style["label"], smooth_factor=0).add_to(layer)
            row = comparison.get((chart_no, prefix + model), {})
            metrics.append([style["label"], *[display(row.get(column), 4 if "Objective" in column else 2)
                                              for column in METRICS]])
        markers = folium.FeatureGroup(show=False, control=False).add_to(m)
        layers.append(markers)
        terminal_order = (stops.original_stop_order.min(), stops.original_stop_order.max())
        for (lat, lon), colocated in stops.groupby(["latitude", "longitude"]):
            orders = set(colocated.original_stop_order)
            terminal = ("S" if terminal_order[0] in orders else "") + ("E" if terminal_order[1] in orders else "")
            text = terminal or str(min(orders))
            if len(orders) > 1:
                text += f"+{len(orders)-1}"
            moved = (colocated.stop_order != colocated.original_stop_order).any()
            color = "#623297" if terminal else "#a34b00" if moved else "#28475e"
            icon = folium.DivIcon(html=f'<div class="stopdot" style="background:{color};color:white;'
                                      f'border:2px solid white;border-radius:50%;width:24px;line-height:23px;'
                                      f'text-align:center;font-size:11px">{text}</div>',
                                  icon_size=(28, 28), icon_anchor=(14, 14))
            names = ", ".join(str(name) for name in colocated.ctu_stop_name.unique())
            folium.Marker((lat, lon), icon=icon, tooltip=escape(names),
                          popup=folium.Popup(stop_popup(colocated, terminal_order), max_width=420)).add_to(markers)
        first = stops.iloc[0]
        charts[chart_no] = layers
        metadata[chart_no] = {"route": str(first.route), "direction": str(first.direction),
                              "metrics": metrics}
    initial = default_chart_no if default_chart_no in charts else next(iter(charts))
    add_comparison_controls(m, charts, metadata, initial)
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
                        help="Legacy option retained for CLI compatibility")
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
        comparison_path=csv_path.with_name("route_comparison.csv"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"[Map] Successfully generated uncluttered interactive map -> {out_path.resolve()}")

    if (project_root / "outputs" / "maps").exists():
        m.save(str(project_root / "outputs" / "maps" / "route_map.html"))


if __name__ == "__main__":
    main()
