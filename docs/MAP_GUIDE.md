# Understanding the map

Open the [saved map](../outputs/route_map.html). It shows one recorded CTU service chart at a time, with three paths that visit the same stops. The **baseline** follows the historical stop order using shortest road paths. **Local Search** shows the order we found by trying small changes, and **Genetic Algorithm (GA)** shows the best-scoring order from five runs of a wider search.

## Choose what to see

1. Pick a **Route** by its service number or code.
2. Pick a **Direction** from the ones available for that route.
3. Pick a **Chart**. A chart is one recorded stop sequence with passenger counts for that route and direction. The map replaces the previous chart and zooms to the one you picked.
4. Check or uncheck the three path layers. Markers and the table stay visible even if you hide the lines.

| Checkbox | Line |
|---|---|
| **Dashed baseline** | Wide, dashed blue |
| **Local search** | Medium-width, solid orange |
| **Genetic algorithm** | Narrow, solid green |

Paths often share roads because they serve the same stops. Sometimes both searches find the same stop order. If one line covers another, show one layer at a time. Hover over a line to see its model name. You can pan and zoom as usual. Choosing a chart fits the view again.

**UP** and **DOWN** are labels in the passenger charts. For route **3**, the **UP** chart (1) goes from **Mauli Jagran** to **PGI(UP)**. The **DOWN** chart (2) goes from **PGI(UP)** to **Mauli Jagran**. The parenthetical text in **PGI(UP)** is part of the stop name. To find the direction for another route, use the recorded first and last stops.

## Read the stops and the table

Purple **S** and **E** mark the first and last stops. The numbered markers show the earliest original stop position at a location. An orange-brown marker shows that at least one non-terminal visit at that location moved in one of the models. Blue-gray marks the other numbered stops. A suffix such as **+1** means the chart records another visit at the same coordinates.

Hover over a marker to see the stop name. Click it to see the stop ID when available, coordinates, historical boardings and alightings, and the position in each order. The popup adds **(moved)** when the position changes and lists repeated visits separately. The marker uses the recorded coordinates, so it may sit a little away from the road line.

| Table label | How to read it |
|---|---|
| **Model** | Baseline, Local Search or Constrained GA. |
| **km** | Total road distance. A smaller value means a shorter path. |
| **min** | Estimated bus time, including time at intermediate stops. |
| **Objective** | The overall score. Lower is better under the rules we set. |
| **Dist. %** | How much distance fell relative to the baseline. A negative value means the route got longer. |
| **Obj. %** | How much the overall score fell. A negative value means the score got worse. |
| **Disruption** | How far stop positions moved on average, with more weight for stops with more recorded boardings and alightings. |
| **Shortcut** | The penalty for passing a required stop’s road node before its scheduled visit. |
| **Status** | Whether the route passes the checks. A feasible route can still have the same score as the baseline. |

The table rounds numbers for display. A dash means the value is unavailable. Use the [comparison CSV](../outputs/route_comparison.csv) to see the saved values.

## Try two examples

Choose route **3**, direction **DOWN**, chart **2**.

| Model | Distance | Distance reduction | Score reduction |
|---|---:|---:|---:|
| Baseline | 25.35 km | 0.00% | 0.00% |
| Local Search | 23.72 km | 6.43% | 4.55% |
| GA | 21.96 km | 13.40% | 21.33% |

The GA path is about **3.40 km shorter** than the baseline. The table’s **13.40%** means that distance fell by that share of the original modeled distance.

Now choose route **9C**, direction **UP**, chart **87**. The GA score falls by **26.98%**, while the road distance increases by **3.36%**. The score improves mainly because the new path avoids passing required stop nodes early. On an unchanged chart, neither search found a better score among the orders it tried. The baseline path may still be displayed with all three colors.

The paths are based on a road graph and the times use assumed speeds. The popups show historical counts. For more on these limits and how the scores work, see [How we evaluated our results](EVALUATION.md). If the background tiles are blank, check that the browser can reach OpenStreetMap. If the controls also fail, check access to the external Leaflet files. See the [README](../README.md) for opening or serving the map locally.
