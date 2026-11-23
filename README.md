# CTU Tricity Bus Route Optimization

This BTech Data Science minor project studies whether a different order of visiting the same CTU bus stops can reduce modeled road distance or improve a score that also accounts for estimated bus traversal time and disruption to the historical stop sequence. The study covers the Chandigarh, Mohali, and Panchkula road network. Road distance and stop-order stability matter when comparing service designs, especially when a shorter alignment would move stops with substantial recorded passenger activity.

The project compares a **reconstructed historical baseline**, **constrained Local Search**, and a **multi-seed Genetic Algorithm (GA)**. The baseline links consecutive survey stops along shortest directed road paths. Actual CTU driving geometry would require GPS or operational records. Local Search and GA start from the same historical sequence and use the same chart, snapped nodes, constraints, and scoring rules. Their comparison shows how often broader search improves on small local changes. The system exports metrics, stop sequences, road geometry, a summary figure, and an interactive Folium map.

[Map guide](docs/MAP_GUIDE.md) · [Evaluation and validation](docs/EVALUATION.md) · [Data sources and references](docs/data_sources.md)

## Quick start on Windows

Run the following in PowerShell from the repository root, the folder that contains `requirements.txt`. For a new checkout:

```powershell
git clone https://github.com/Simran3106/route-optimization-chdtricity
Set-Location .\route-optimization-chdtricity
```

For an existing checkout, use `Set-Location` with its path. Create and activate an isolated environment:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The local environment was verified with **Python 3.14.4**. Other interpreter versions were not tested for this documentation. If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python` in subsequent commands.

### Open the saved map

Opening the supplied HTML takes no Python computation. These examples use a standard Chrome installation directory:

```powershell
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
& $chrome (Resolve-Path .\outputs\route_map.html).Path
```

If Chrome is installed elsewhere, open the file from Chrome with **Ctrl+O** or update the executable path. To serve the same file locally, start the server in one PowerShell window and open the URL in another:

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory outputs
```

```powershell
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' 'http://127.0.0.1:8000/route_map.html'
```

Stop the server with **Ctrl+C**. The browser still needs access to external map assets and tiles.

### Run the model

```powershell
python -m src.routing.routing --all
python -m src.routing.routing --chart 2 --output-dir outputs/chart-2
python -m src.routing.routing --chart 3 --graphml data/roadnodes/chandigarh_road_network.graphml --output-dir outputs/chandigarh-chart-3
```

The first command recomputes the full Tricity experiment and writes to `outputs/`. It is the most expensive command because it loads the graph, prepares directed paths, and evaluates five GA seeds for every feasible chart. Use `--output-dir` to keep an experiment separate from the supplied results. The single-chart examples write to separate folders and still load the selected graph. Run the full experiment only when you need to regenerate results.

Route and direction filters are also available, for example `--route 3 --direction DOWN`. Use `python -m src.routing.routing --help` for supported parameters and defaults.

### Test, validate, or regenerate the map

```powershell
python -m tests.test_routing
python -m tests.validate_outputs
python -m src.visualisation.plot_bus_routes --csv outputs/optimized_routes.csv --geojson outputs/optimized_paths.geojson --out outputs/route_map.html
```

The test suite uses fixtures and small routing checks. The validator loads the default Tricity graph and checks the saved full-run artifacts. The visualization command renders the map from the supplied CSV and GeoJSON without running either optimizer. It reads `route_comparison.csv` beside the stop CSV and updates the duplicate under `outputs/maps/` when that directory exists.

## Dependencies

These minimum versions come from `requirements.txt`. The final column describes the package’s role in the manifest or application.

| Package | Minimum | Role |
|---|---:|---|
| NumPy | 1.24.0 | Coordinate distances and routing matrices |
| pandas | 2.0.0 | Reading, grouping, and exporting tabular data |
| NetworkX | 3.0 | Directed graph loading and connectivity |
| Folium | 0.14.0 | Interactive HTML map |
| Matplotlib | 3.7.0 | Static comparison figure |
| branca | 0.6.0 | HTML templates and controls for Folium |
| requests, beautifulsoup4 | 2.28.0, 4.11.0 | Data-ingestion utilities listed in the manifest |
| python-dateutil, typing_extensions | 2.8.2, 4.5.0 | Date and typing utilities listed in the manifest |

Modules such as `pathlib`, `json`, `argparse`, and `http.server` come with Python. OSMnx prepared the supplied graph, and the current routing command reads it through NetworkX.

## Repository at a glance

```text
requirements.txt                    Installation manifest
README.md                           Main documentation
docs/
  data_sources.md                   Provenance and references
  MAP_GUIDE.md                      Interactive map instructions
  EVALUATION.md                     Metrics, methods, and validation
src/
  routing/routing.py                 Validation, snapping, routing, optimization, exports
  visualisation/plot_bus_routes.py   Folium map builder and CLI
tests/
  test_routing.py                   Routing and map regression fixtures
  validate_outputs.py               Checks the saved default experiment
data/
  passengerdata/
    chart_data/join_alightingsboardings_with_standard routes.CSV
    performance_routes_clean.csv
  roadnodes/
    tricity_road_network.graphml
    chandigarh_road_network.graphml
outputs/
  route_comparison.csv              One result per chart and model
  optimized_routes.csv              Ordered stops and snap diagnostics
  optimized_paths.geojson           Directed road paths and node sequences
  chart_processing.csv              One processing outcome per chart
  chart_failures.csv                Failure details and source lines
  comparison_summary.json           Aggregate results, paired comparisons, and timings
  comparison.png                    Static comparison figure
  route_map.html                    Interactive comparison
```

## Final inputs

| Source input | Role |
|---|---|
| [Historical CTU passenger charts](data/passengerdata/chart_data/join_alightingsboardings_with_standard%20routes.CSV) | 2,134 recorded stop occurrences across 118 directional charts and 68 route identifiers. `chart_no`, `route`, `direction`, and `stop_order` identify the historical sequence. Stop IDs, names, locations, `Boardings`, `Alightings`, and `Volume` are carried through as source observations. |
| [Route performance](data/passengerdata/performance_routes_clean.csv) | Provides historical operating fields and inputs for conditional fleet and per-traversal cost scenarios. These scenarios are outside the optimizer’s objective. |
| [Tricity graph](data/roadnodes/tricity_road_network.graphml) | Default directed road graph. Link lengths and geometries support routing across Chandigarh, Mohali, and Panchkula. |
| [Chandigarh graph](data/roadnodes/chandigarh_road_network.graphml) | Optional city-only graph selected with `--graphml`. |

The pipeline derives snapped nodes, model stop orders, paths, scores, and comparisons from these inputs. Boarding plus alighting counts provide a proxy for stop importance. The project has no origin–destination matrix. Historical `Volume` describes the recorded sequence and is carried forward without recalculation.

**UP** and **DOWN** are dataset labels. For route 3, chart 1 (UP) starts at Mauli Jagran and ends at the recorded stop **PGI(UP)**. Chart 2 (DOWN) reverses those two terminals. The labels do not imply compass directions across the network.

## Methodology

1. **Validate and group.** Check source records and group stop occurrences by directional chart. Repeated visits remain separate occurrences even at the same coordinates.
2. **Snap and reconstruct.** Assign the nearest usable road node first. If an original leg is unreachable, test a bounded set of nearby nodes around the failed leg. The chosen alternative minimizes added snap distance among the tested assignments that connect the entire historical sequence. Compute shortest directed paths by road length and use them to reconstruct the baseline.
3. **Search feasible sequences.** Local Search tries nearby swaps, short reversals, and insertions. The GA combines and mutates candidate sequences across five seeded runs and exports the best objective found. Both preserve the first and last occurrences and every original occurrence. Defaults allow at most three positions of displacement and a distance no more than 1.25 times the baseline. Every leg must be reachable on the directed graph. An optional corridor bounds the candidate road paths relative to the reconstructed baseline.
4. **Evaluate and export.** Compare distance, estimated bus time, stop-order disruption, and early stop-node encounters. Save the model metrics and stop and path details, record the status of each chart, and build the figure and interactive comparison.

## Evaluation overview

| Metric | Meaning and units | Interpretation |
|---|---|---|
| Road distance | Sum of directed road-link lengths, km | Lower is shorter |
| Estimated travel time | Modeled driving time plus standard dwell, min | Lower is a faster modeled bus traversal |
| Objective score | Weighted sum of normalized distance, time, displacement, and shortcut penalty | Lower is preferred |
| Distance and objective improvement | Percentage reduction relative to the chart baseline | Positive is an improvement for that metric |
| Historical demand-weighted displacement | Mean change in stop-order position, weighted by historical passenger activity | Lower preserves more of the ordering |
| Shortcut count and penalty | Distinct required road nodes passed before a scheduled visit, valued at 0.1 objective units per node | Lower is preferred |
| Feasibility | Result of permutation, terminal, connectivity, displacement, detour, and optional corridor checks | A feasible route satisfies the enabled checks |
| Local Search and GA runtime | Model execution seconds, with GA selected-seed and all-seed measurements | Lower uses less time on that run |
| GA wins, ties, and losses | Per-chart GA performance compared with Local Search, counted separately for distance and objective | More wins indicate more chart-level advantages |

Fleet and cost fields are conditional operational scenarios. Fleet requires a compatible directional pair and verified shared headway. Cost is an allocation per directional traversal for a usable performance match. Blank means unavailable. See [the evaluation reference](docs/EVALUATION.md) for formulas and tolerances.

## Final Tricity results

All **118 directional charts** were processed. There were **0 invalid-data, 0 disconnected or infeasible, and 0 runtime-error** outcomes. The diagnostic records show **31 nearest-assignment failures recovered** by alternative snapping and 33 changed stop occurrences. The run produced 354 model rows and 354 road paths.

| Compared with the reconstructed baseline | Local Search | GA |
|---|---:|---:|
| Charts with improved objective | 75 | 75 |
| Charts with reduced road distance | 57 | 58 |
| Mean road-distance improvement | 1.394% | 1.684% |
| Median road-distance improvement | 0.000% | 0.000% |
| Mean objective improvement | 5.931% | 6.333% |

GA won/tied/lost **10/108/0** on objective and **9/108/1** on road distance against Local Search. These counts describe the saved experiment. Both methods tied on most charts. The [comparison summary](outputs/comparison_summary.json) contains the detailed counts and timings.

## Use the map

In the [interactive map](outputs/route_map.html), choose **Route**, **Direction**, and **Chart**. The baseline is dashed blue, Local Search is orange, and GA is green. Use the checkboxes to view one path at a time when shared road links overlap. Click stop markers to inspect survey counts and the stop’s position in each model. **S** and **E** mark terminals. The comparison table shows distance, time, objective, and other metrics for the selected chart. The [map guide](docs/MAP_GUIDE.md) walks through a saved example.

## Limitations and future scope

The baseline and candidates are modeled alignments. Road-class speeds and fixed dwell approximate bus time, and graph connectivity alone does not verify the correct boarding platform or bus access. Reassigned nodes and the 34 stop occurrences with snap warnings warrant field review. Passenger-time savings require trip and service data absent from these charts. Fleet and cost scenarios require operational verification. Local Search and GA provide heuristic solutions without a guarantee of global optimality. GPS traces, verified stop locations, and observed travel times would support stronger validation.

## Troubleshooting

| Problem | What to check |
|---|---|
| Missing module or wrong Python | Check `Get-Command python` and `python -m pip --version`. Install into the active environment or use `.\.venv\Scripts\python.exe` explicitly. |
| Files or modules cannot be found | Confirm the working directory contains `requirements.txt` and that the listed CSV and GraphML files are present. |
| Background tiles are blank | Check access to the browser’s external map and tile resources. A local server helps with local file access. |
| HTML still shows an older run | Open the HTML from the directory used for the latest run, regenerate it from matching exports if needed, and refresh Chrome with **Ctrl+F5**. |
| Optimization is taking a long time | Let the graph and chart processing finish or use a single chart in a separate output folder. Use the supplied HTML for a demo. |
