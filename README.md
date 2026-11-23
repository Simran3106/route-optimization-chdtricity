# CTU Tricity Bus Route Optimization

This project focuses on improving CTU bus routes in Chandigarh, Mohali and Panchkula. We wanted to see whether a bus could visit the same stops in a different order and travel fewer kilometres. We also wanted to see how much each change would disturb the recorded order, especially at stops where many people boarded or got off.

We used historical CTU passenger charts and a map of the Tricity road network. For each chart, we rebuilt the recorded stop order using roads from the map. We call this the **baseline**. We then tried two ways to change the order, **Local Search** and a **Genetic Algorithm (GA)**. We compared both with the baseline under the same rules and put all three paths on an interactive map.

## How to install and run

Open PowerShell in the project folder, where `requirements.txt` is located. If you need a copy of the repository, run:

```powershell
git clone https://github.com/Simran3106/route-optimization-chdtricity
Set-Location .\route-optimization-chdtricity
```

Create an environment and install the packages. We verified Python 3.14.4 locally.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python`. If imports or files are missing, check that you are using that interpreter from the project folder.

```powershell
# Run one chart and keep the supplied results in place
python -m src.routing.routing --chart 2 --output-dir outputs/chart-2

# Run the full Tricity experiment and write results to outputs/
python -m src.routing.routing --all

# Run the tests or check the saved full-run results
python -m tests.test_routing
python -m tests.validate_outputs
```

The full run takes longer because it searches every chart with five GA seeds. Run the saved-output check before replacing the supplied full-run results with a different experiment. To use the Chandigarh-only road graph, add `--graphml data/roadnodes/chandigarh_road_network.graphml` and use a separate output folder.

To view the existing map, open [route_map.html](outputs/route_map.html) in Chrome or run:

```powershell
Start-Process .\outputs\route_map.html
```

That command uses the default browser. If local file access causes trouble, run the server below and open [the map on localhost](http://127.0.0.1:8000/route_map.html). Stop the server with **Ctrl+C**.

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory outputs
```

The saved map opens without running the model. To rebuild the map from the saved stop, path and comparison files:

```powershell
python -m src.visualisation.plot_bus_routes --csv outputs/optimized_routes.csv --geojson outputs/optimized_paths.geojson --out outputs/route_map.html
```

## Data we used

| Input | What it gives us |
|---|---|
| [Historical passenger charts](data/passengerdata/chart_data/join_alightingsboardings_with_standard%20routes.CSV) | 2,134 stop records across 118 directional charts. Each chart gives us a route, direction, stop order, locations and observed passenger counts. We add boardings and alightings to give each stop a weight in the score. |
| [Tricity road network](data/roadnodes/tricity_road_network.graphml) | Roads, directions, lengths and shapes. These tell us which road links a modeled bus can follow. A [Chandigarh-only graph](data/roadnodes/chandigarh_road_network.graphml) is also available. |
| [Route performance data](data/passengerdata/performance_routes_clean.csv) | Historical figures such as operating expenditure and vehicle-kilometres. We use the available figures to estimate operating scenarios after choosing a stop order. |

We keep the recorded passenger counts and historical `Volume`. We do not recalculate passenger loads after reordering stops because the charts do not tell us where individual passengers got on and off. See [Data sources](docs/data_sources.md) for the source notes and references.

## How our project works

1. **Read the stop lists.** We group records by chart and sort the stops in the recorded order. If the same location appears twice, we keep both visits.
2. **Connect the stops to roads.** We match each stop to a nearby road node. If the nearest choices leave a gap, we try nearby alternatives and check the whole sequence again. We use **Dijkstra’s algorithm** to find the shortest path by road distance between consecutive stops. The roads are directed, so the bus has to follow each link in an allowed direction.
3. **Build the baseline.** We connect the stops in their historical order and add up the distance and estimated time. This gives both search methods the same starting point.
4. **Try Local Search.** We swap stops, reverse a short part of the sequence or move a stop to a nearby position. When a valid change lowers the score, we keep it and search again from there.
5. **Try a Genetic Algorithm.** We keep a group of possible orders, use better-scoring orders to create new ones, and introduce small changes. We repeat the search with five seeds and keep the result with the lowest score.
6. **Check the rules and compare.** Both searches must keep every visit and the original first and last stops. Fixing the terminals keeps the same endpoints for the service. The default rules also limit how far a stop can move in the list and how much distance the route can add. We save the model results and draw the paths on the map.

## Project files

| File or folder | What it contains |
|---|---|
| `src/routing/routing.py` | Reads the inputs, connects stops to roads, searches stop orders and saves the results. |
| `src/visualisation/plot_bus_routes.py` | Builds the interactive map from the exported stops, paths and scores. |
| `tests/` | Checks routing rules, search behavior and the saved outputs. |
| `data/` | Passenger charts, performance figures and road graphs. |
| `outputs/route_comparison.csv` | Distance, time, scores and other results for each model and chart. |
| `outputs/optimized_routes.csv` and `outputs/optimized_paths.geojson` | Stop orders, road-node matches and the road paths. |
| `outputs/chart_processing.csv` and `outputs/chart_failures.csv` | Which charts were processed, which needed a different road-node match and any failures. |
| `outputs/comparison_summary.json` and `outputs/comparison.png` | Totals, method comparisons, timings and the summary figure. |
| `outputs/route_map.html` | Interactive view of the three models. |

## Results

We processed all **118 charts**, including **31** whose initial road-node matches left a gap. The final run recorded no disconnected charts, invalid charts or runtime errors.

| Compared with the baseline for each chart | Local Search | GA |
|---|---:|---:|
| Charts with a lower score | 75 | 75 |
| Charts with a shorter road distance | 57 | 58 |
| Mean distance reduction | 1.39% | 1.68% |
| Median distance reduction | 0.00% | 0.00% |
| Mean score reduction | 5.93% | 6.33% |

GA scored better than Local Search on 10 charts and tied it on 108. For distance it was shorter on nine charts, tied on 108 and was longer on one. The two methods often found equally good solutions by these measures. On 43 charts neither found a better score under the rules and search settings we used.

For example, route **3 DOWN**, chart **2**, went from **25.35 km** in the baseline to **23.72 km** with Local Search and **21.96 km** with GA. A shorter distance and a lower score are separate results. A route can score better because other parts of the score improve. See the [saved summary](outputs/comparison_summary.json) for the full comparison.

## Understanding the map

Choose a **Route**, **Direction** and **Chart** in the [interactive map](outputs/route_map.html). The dashed blue line shows the baseline, orange shows Local Search, and green shows GA. Toggle paths to see where they differ and click stops to compare the visit order. **UP** and **DOWN** come from the passenger charts. Their meaning depends on the route. See the [map guide](docs/MAP_GUIDE.md) for a walkthrough.

## How we judge a route

We look at **distance**, **estimated bus time**, and **how much the stop order changes**. We combine these with a penalty for passing a required stop node before its visit. This gives us the **objective score**. Lower scores are better among routes that pass our rules. The [evaluation guide](docs/EVALUATION.md) explains the calculation, the checks and what the results mean.

## Limitations

We rebuilt the baseline from stop records and road links. Verifying the roads CTU buses actually used would require GPS traces or operating records. Travel times come from assumed road speeds and a fixed time at intermediate stops. The road-node matches also need field checks for the correct boarding locations and bus access.

The passenger charts describe historical activity at stops. They cannot tell us how much journey time individual passengers would save. Fleet values are blank in the saved run because they require a verified shared bus interval. Cost figures are estimates for one traversal. Both searches can find useful alternatives, but neither guarantees the best possible stop order.
