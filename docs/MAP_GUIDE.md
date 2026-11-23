# Interactive map guide

Open the [saved Folium comparison](../outputs/route_map.html) in Chrome. For PowerShell commands to open it directly or serve it through local HTTP, see the [README](../README.md). The saved HTML displays one historical CTU directional chart at a time. Each chart has a reconstructed path for the recorded stop order and up to two feasible alternatives from Local Search and the Genetic Algorithm (GA). The comparison uses directed road paths. Verified CTU driving geometry would require field or GPS observations.

## Select and compare a chart

1. Open the saved HTML. The full-run map starts on chart **1** for route **3**, direction **UP**.
2. Use **Route** to choose a route identifier. The available directions update when the route changes.
3. Use **Direction** to choose **UP** or **DOWN** where available. These labels come from the source charts. They carry no general northbound, southbound, inbound, or outbound meaning.
4. Use **Chart** to choose one of the chart numbers for that route and direction. The map replaces the previous chart and fits the selected chart’s bounds.
5. Use the three checkboxes to show or hide the corresponding paths. Their checked states carry over when you switch charts. Stop markers and the metric table remain visible when path layers are unchecked.
6. Compare the paths. To see the reconstructed alignment alone, leave only **Dashed baseline** checked. Then switch to **Local search** or **Genetic algorithm** to inspect an optimized alignment on its own.
7. Hover over a line to see its model label or over a stop marker to see its name. Click a stop marker to open its full details.
8. Read the table to compare the models. The table remains a three-model comparison regardless of which paths are visible.

## Map elements

The color-coded checkboxes identify the path styles.

| Checkbox | Path | Meaning |
|---|---|---|
| **Dashed baseline** | Wide dashed blue | Shortest directed road paths connecting the original stop sequence |
| **Local search** | Medium solid orange | Result from constrained local swaps, short reversals, and insertions |
| **Genetic algorithm** | Narrow solid green | Lowest-objective result from the configured GA seeds |

Different widths help reveal coincident paths. Shared links are common because all models serve the same stops and use the same road graph. Two different sequences can also produce very similar road paths. Layer toggles let you inspect each path independently. The map has standard pan, zoom, and scale controls. It has no separate reset or comparison-mode button. Selecting a chart fits its bounds again.

Purple **S** and **E** markers denote the original first and last occurrences. **SE** is possible when the start and end share coordinates. Other markers show the earliest original order at that location. An orange-brown marker indicates a moved non-terminal occurrence at those coordinates, and a blue-gray marker indicates no such move. A suffix such as **+1** indicates another historical occurrence at the same coordinates. Stop markers use the recorded coordinates, which can lie away from the snapped road geometry.

The popup groups co-located occurrences and lists their stop names, IDs where available, coordinates, original positions, positions by model, and historical boarding and alighting counts. **(moved)** identifies a change in position. The counts refer to the original observation. The map does not estimate new passenger volumes.

| Table label | What it shows |
|---|---|
| **Model** | Baseline, Local Search, or Constrained GA |
| **km**, **min** | Road distance and estimated bus traversal time |
| **Objective** | Combined score. Lower is preferred. |
| **Dist. %**, **Obj. %** | Distance and objective reductions relative to that chart’s baseline. A negative value means an increase. |
| **Disruption** | Historical demand-weighted displacement in stop positions |
| **Shortcut** | Penalty for passing distinct required stop nodes before a scheduled visit |
| **Status** | Model feasibility |

A dash indicates an unavailable value. The HTML embeds values from the comparison CSV, formatted for display. For exact numerical comparisons, consult the [model export](../outputs/route_comparison.csv).

## Worked example with route 3

For route **3**, choose **DOWN** and chart **2**. In the original passenger CSV, chart 2 starts at **PGI(UP)** and ends at **Mauli Jagran**. Chart 1, labeled **UP**, goes from **Mauli Jagran** to **PGI(UP)**. The parenthetical text in **PGI(UP)** belongs to the stop name.

| Model | Distance | Distance improvement | Objective improvement |
|---|---:|---:|---:|
| Baseline | 25.35 km | 0.00% | 0.00% |
| Local Search | 23.72 km | 6.43% | 4.55% |
| GA | 21.96 km | 13.40% | 21.33% |

On this chart, GA improves both distance and objective. Switch to route 3 UP, chart 1, to see a case in which both optimizers report the same distance and objective improvement. They start from the same baseline and may converge on the same feasible solution. A lower objective can also accompany a longer path. For example, route 9C UP, chart 87, has a GA objective improvement of 26.98% alongside a 3.36% increase in road distance.

## Limits and troubleshooting

The map shows historical stop coordinates and road-network reconstructions. Directed connectivity establishes a path in the graph. Confirming platform location and real bus access requires field evidence. The displayed minutes come from assumed road-class speeds plus dwell and do not measure passenger journey times.

If the background is blank but controls and paths appear, the browser may be unable to reach the OpenStreetMap tile service. If the map itself fails to initialize, check access to the external Leaflet assets as well. Serving the file through local HTTP can resolve local-file access issues. It does not replace external resources. If the page shows old values, confirm the path to the HTML and refresh with **Ctrl+F5**. The map reflects the CSV and GeoJSON from the time it was generated. For metric definitions and validation, see the [evaluation guide](EVALUATION.md).
