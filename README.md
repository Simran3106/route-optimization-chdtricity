# Data-Driven Route Optimization for Chandigarh CTU Local Bus Network

**BTech Computer Science / Data Science Minor Project**

This repository provides a complete, working geographical bus route optimization system for the Chandigarh Transport Undertaking (CTU) local bus network. The system evaluates and optimizes bus stop sequences and road alignments using historical boarding–alighting passenger data and the OpenStreetMap road network.

Optimization is performed using a **demand-aware, constrained Genetic Algorithm (GA)** supported by Dijkstra shortest-path calculations on the directed road network, benchmarked against a **reconstructed original-sequence baseline** and a **constrained local search** model.

---

## Objectives

1. **Geographical Stop Sequence Optimization**: Re-sequence intermediate bus stops to minimize road network distance and estimated traversal times while preserving route terminals and any configured corridor limit.
2. **Demand Preservation**: Incorporate historical sampled passenger boardings and alightings into a sequence-disruption penalty to prevent disruptive deviations from high-demand passenger clusters.
3. **Road-Network Feasibility**: Restrict all routing decisions to drivable, directed OpenStreetMap links, enforcing one-way constraints, avoiding disconnected road links, and penalizing premature encounters with required stop nodes.
4. **Operational Impact Evaluation**: Assess the consequences of proposed route alignments across road distance, travel time, passenger disruption, fleet requirements, and operational expenditure.

---

## Datasets

### Primary Dataset: Boarding–Alighting Observations
- **Path**: `data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV`
- **Scope**: 2,134 stop-level observation records across 118 directional charts representing 68 unique route identifiers.
- **Attributes**: `chart_no`, `route`, `direction`, `stop_order`, `chart_label`, `ctu_stop_id`, `ctu_stop_name`, `latitude`, `longitude`, `Boardings`, `Alightings`, `Volume`.
- **Role**: Serves as the immutable primary input for identifying existing routes, ordering stop sequences, geographic coordinate snapping, computing stop importance, evaluating demand disruption, and ensuring complete stop preservation.

### Road Network Graph
- **Default**. `data/roadnodes/tricity_road_network.graphml` covers Chandigarh, Mohali, and Panchkula.
- **Optional**. `data/roadnodes/chandigarh_road_network.graphml` can be selected with `--graphml`.
- Both files encode directed OpenStreetMap links, WGS84 node coordinates, metre lengths, road classes, and WKT geometry where available. The loader keeps supported roads with valid lengths and excludes links with explicit restricted access.

### Secondary Dataset: Route Performance Parameters
- **Path**: `data/passengerdata/performance_routes_clean.csv`
- **Scope**: Operational audit records for 68 CTU bus routes.
- **Attributes**: `Route No`, `Morning Peak Headway`, `Afternoon Headway`, `Route Length (km)`, `Daily Ridership`, `On road Fleet`, `Actual Veh. Km`, `Total Expenditure (Rs)`, `Load Factor`.
- **Role**: Utilized exclusively for supplementary operational scenario evaluation (fleet sizing and unit operating expenditure). This dataset is not used as an optimization input.

---

## Data Sources

A complete description of data provenance, survey methodologies, and bibliographic citations is provided in [docs/data_sources.md](docs/data_sources.md).

Key sources include:
- **CEPT Research and Development Foundation (CRDF)** / **Ministry of Housing and Urban Affairs (MoHUA)** historical public transit planning study.
- **Chandigarh Transport Undertaking (CTU)** official route directory and stop inventory.
- **OpenStreetMap** road network data extracted via OSMnx.
- Transportation research literature on Transit Network Design and Frequency Setting (TNDFSP) by Guihaire & Hao (2008), Iliopoulou & Kepaptsoglou (2021), and Fan & Machemehl (2006).

---

## Methodology

The optimization pipeline implements three comparative models:

```text
[Input Stop Sequence] 
          │
          ├──> Approach A: Reconstructed Original Baseline (Dijkstra on OSM road graph)
          │
          ├──> Approach B: Constrained Local Search (2-opt reversals, swaps, insertions)
          │
          └──> Approach C: Constrained Genetic Algorithm (Multi-seed GA + Dijkstra)
```

1. **Approach A — Reconstructed Original-Sequence Baseline**:
   Stops are ordered by their historical `stop_order` and snapped to the nearest road network node on the selected usable directed graph. The historical stop order is checked across the complete sequence before routing. Consecutive stops are connected by shortest-distance Dijkstra paths. This reconstructs a modeled alignment from the survey stops; actual CTU driving geometry would require independent records.
2. **Approach B — Constrained Local Search**:
   An iterative first-improvement hill-climbing heuristic applying local adjacent swaps, short 2-opt subsequence reversals (length 2 to 3), and localized insertions within strict displacement limits.
3. **Approach C — Demand-Aware Constrained Genetic Algorithm**:
   A population-based metaheuristic exploring feasible permutations using cached Dijkstra paths and stop-pair distance and time matrices.

---

## Optimization Model

### Chromosome Representation
Each candidate solution is represented as an ordered sequence of unique stop occurrence indices:
$$\mathbf{s} = [0, \pi(1), \pi(2), \dots, \pi(N-2), N-1]$$
- Stop occurrences are uniquely indexed to distinguish multiple visits to the same physical stop (e.g., repeated station approaches).
- Start terminal ($s_0$) and end terminal ($s_{N-1}$) remain strictly pinned.

### Hard Route Constraints
Every candidate route must satisfy:
1. Start terminal preserved ($s_0 = 0$).
2. End terminal preserved ($s_{N-1} = N-1$).
3. All stop occurrences retained without omission or duplication (100% stop retention).
4. Unmodified stop coordinates and identifiers.
5. Continuous drivable road connectivity on directed links.
6. One-way restrictions respected.
7. Disconnected road segments avoided.
8. Maximum sequence displacement limited ($|p_i^{new} - p_i^{old}| \le K_{\max}$, default $K_{\max} = 3$).
9. Detour ratio bound ($D \le 1.25 \times D_{\text{baseline}}$).
10. When `--corridor-m` is supplied, each candidate road segment must be certified inside the union of metric buffers around the baseline segments. Subdivision certifies coverage of complete subsegments. An ambiguous boundary case is conservatively rejected.

The initial snap uses the nearest usable node regardless of component. If a leg is unreachable, collect up to eight nearby nodes per occurrence at the failure and its immediate neighbors. A layered minimum-cost search chooses the smallest total added snap distance over assignments that connect the complete original sequence. When no assignment is found in this bounded search, the chart is recorded as disconnected. The selected node represents a graph-connected hypothesis and requires field validation of platform side and bus access. Multiple occurrences may share a snapped node, with zero driving distance between consecutive occurrences at that node. `--max-snap-m` defaults to 500 m and caps alternative snaps. Original nearest nodes farther away remain eligible and are flagged for review. The baseline remains available to both optimizers when it satisfies the constraints.

### Fitness Function
The multi-objective fitness minimizes normalized road distance, estimated travel time, and demand disruption:
$$\min J = \alpha D_n + \beta T_n + \gamma P_n + 0.1S$$
where:
- $D_n = \frac{D}{D_{\text{baseline}}}$: Normalized road distance.
- $T_n = \frac{T}{T_{\text{baseline}}}$: Normalized estimated travel time.
- $P_n = \frac{P}{N - 1}$: Normalized demand-weighted sequence disruption.
- $S$ counts distinct required road nodes first encountered inside a leg before a scheduled visit. Passing an already served node or sharing a leg endpoint incurs no penalty. The same rule applies to all three models.
- $\alpha, \beta, \gamma \ge 0$: Configurable weights that sum to one ($\alpha=0.5, \beta=0.2, \gamma=0.3$ by default).

### Genetic Operators
- **Selection**: Tournament selection (size $k = 3$).
- **Crossover**: Order-preserving crossover (OX) adapted for fixed terminals.
- **Mutation**: Neighborhood swaps, 2-opt reversals, and bounded insertions applied with probability $p_m = 0.35$.
- **Elitism**: Top 3 feasible candidates preserved across generations.
- **Reproducibility**: Multi-seed execution across fixed seeds (`[42, 101, 2024, 7, 999]`).

---

## Evaluation Metrics

1. **Road Distance ($D$, km)**: Sum of directed road edge lengths along Dijkstra shortest paths connecting consecutive stops.
2. **Estimated Travel Time ($T$, min)**: Road traversal time based on assumed road-class speeds (Trunk: 50 km/h, Primary: 45 km/h, Secondary: 40 km/h, Tertiary: 30 km/h, Residential: 25 km/h) plus a standardized dwell time of 30 seconds per intermediate stop.
3. **Demand-Weighted Disruption ($P$)**:
   $$P = \frac{\sum_i w_i |p_i^{\text{new}} - p_i^{\text{old}}|}{\sum_i w_i}$$
   where stop importance $w_i = B_i + A_i$. Measures displacement weighted by historical boarding and alighting activity. Recorded zero demand is valid. Missing or malformed boarding or alighting values make the chart invalid for the weighted analysis. An all-zero chart uses mean unweighted displacement.
4. **Modeled Round-Trip Fleet** uses $F=\lceil 1.15(T_{UP}+T_{DOWN})/H\rceil$. The 15% allowance represents terminal layover and turnaround. The estimate requires a unique pair with reversed matching terminal IDs and a verified shared peak interval $H$ in minutes. It appears once per route and model on the UP row. Enable it with `--verified-headway-minutes` after checking the source.
5. **Modeled Cost per Directional Traversal** multiplies modeled road distance by historical expenditure divided by historical vehicle-kilometres. This allocation assumes a constant average cost per vehicle-kilometre and requires a unique exact route match and positive, compatible historical inputs. Historical route length is a plausibility check. The scenario uses no inferred number of trips.

Distance, estimated bus time, and objective improvements use their respective baseline denominators. The model table exposes four weighted objective components including the shortcut penalty. A zero distance or time denominator contributes the respective weight and leaves the corresponding improvement percentage blank. The summary uses absolute tolerances of 0.000001 km and 0.00000001 objective units for paired and baseline comparisons. Runtime excludes shared path matrix construction. The GA columns show both the selected-seed runtime and time across all seeds. Fleet and cost are operational scenarios evaluated after sequencing.

---

## Project Structure

```text
route-optimization-chdtricity/
├── data/
│   ├── bustop/
│   │   ├── ctu_stops.csv
│   │   ├── ctu_stops_directory.csv
│   │   └── ctu_stops_raw.csv
│   ├── passengerdata/
│   │   ├── chart_data/
│   │   │   └── join_alightingsboardings_with_standard routes.CSV
│   │   └── performance_routes_clean.csv
│   └── roadnodes/
│       ├── chandigarh_road_network.graphml
│       └── tricity_road_network.graphml
├── docs/
│   └── data_sources.md
├── notebooks/
│   └── exploration.ipynb
├── outputs/
│   ├── route_comparison.csv
│   ├── optimized_routes.csv
│   ├── optimized_paths.geojson
│   ├── route_map.html
│   └── comparison.png
├── src/
│   ├── data_collection/
│   ├── preprocessing/
│   ├── routing/
│   │   └── routing.py
│   ├── validation/
│   └── visualisation/
│       └── plot_bus_routes.py
├── tests/
│   └── test_routing.py
├── .gitignore
├── README.md
└── requirements.txt
```

---

## Dependencies and Installation

The project uses standard scientific Python packages managed via [requirements.txt](file:///c:/Users/hppav/OneDrive/Documents/VSCODE/route-optimization-chdtricity/requirements.txt). No proprietary or specialized solver licenses are required.

### System Requirements
- **Python**: Version 3.10, 3.11, 3.12, 3.13, or 3.14.
- **Operating System**: Windows 10/11, Ubuntu/Linux, or macOS.
- **Hardware**: Standard laptop (4GB+ RAM, no GPU required).

### Dependency Manifest (`requirements.txt`)
The dependencies are categorized into:
- **Core Data Processing**: `numpy>=1.24.0`, `pandas>=2.0.0`
- **Graph & Road Network Analysis**: `networkx>=3.0`
- **Geospatial Visualization & Mapping**: `folium>=0.14.0`, `matplotlib>=3.7.0`, `branca>=0.6.0`
- **Data Ingestion & Utilities**: `requests>=2.28.0`, `beautifulsoup4>=4.11.0`, `python-dateutil>=2.8.2`

### Step-by-Step Setup Guide

#### 1. Clone or Open the Repository
```bash
git clone https://github.com/hppav/route-optimization-chdtricity.git
cd route-optimization-chdtricity
```

#### 2. Create a Virtual Environment
Create an isolated environment named `.venv`:
```bash
python -m venv .venv
```

#### 3. Activate the Virtual Environment
- **On Windows (PowerShell)**:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
  *(If script execution is disabled in PowerShell, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first).*
- **On Windows (Command Prompt `cmd`)**:
  ```cmd
  .\.venv\Scripts\activate.bat
  ```
- **On Linux / macOS (Bash/Zsh)**:
  ```bash
  source .venv/bin/activate
  ```

#### 4. Download and Install Dependencies
Upgrade pip and install all required libraries using the provided `requirements.txt`:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### 5. Verify Installation
Run the automated test suite to ensure all dependencies and datasets load without error:
```bash
python -m tests.test_routing
```
*(All 22 test cases should report `[PASS]` and output `ALL 22 TESTS PASSED SUCCESSFULLY!`).*

---

## Step-by-Step Usage Guide

All commands are runnable from the project root directory.

### 1. Optimize a Specific Route and Direction
To run the optimization for a single route-direction such as Route 11 UP:
```bash
python -m src.routing.routing --route 11 --direction UP
```
This command runs:
- **Approach A**: Reconstructed original-sequence road baseline.
- **Approach B**: Constrained Local Search.
- **Approach C**: Constrained Genetic Algorithm across 5 random seeds (`42, 101, 2024, 7, 999`).
- Generates all evaluation metrics, CSVs, GeoJSON paths, comparison figure, and Folium interactive map.

### 2. Process All Directional Charts

```bash
python -m src.routing.routing --all
python -m src.routing.routing --chart 3 --graphml data/roadnodes/chandigarh_road_network.graphml
```

Run from the repository root. The default command discovers all 118 charts in the primary CSV. Use `--output-dir` to preserve previous results. Record the graph file, input CSVs, weights, constraints, population size, generations, and seeds with each experiment. The default GA runs 60 generations with a population of 50 for each of five fixed seeds.

### 3. Run Multi-Objective Sensitivity Analysis
To evaluate how different objective weightings alter the optimal stop sequence (Distance-Focused vs. Balanced vs. Demand-Preservation-Focused):
```bash
python -m src.routing.routing --route 11 --direction UP --sensitivity
```

### 4. Custom Parameter Configuration (Optional)
GA parameters, objective weights, and displacement constraints can be customized via optional CLI flags:
```bash
python -m src.routing.routing --route 11 --direction UP --alpha 0.6 --beta 0.2 --gamma 0.2 --max-displacement 2 --pop-size 60 --generations 80
```
- `--alpha`: Weight for normalized road distance (default: `0.5`).
- `--beta`: Weight for normalized estimated travel time (default: `0.2`).
- `--gamma`: Weight for normalized demand disruption (default: `0.3`).
- `--max-displacement`: Maximum allowed stop position shift (default: `3`).
- `--max-detour-ratio`: Maximum allowable detour ratio relative to baseline (default: `1.25`).
- `--pop-size`: Genetic Algorithm population size (default: `50`).
- `--generations`: Number of generations (default: `60`).
- `--seeds`: List of random seeds (default: `42 101 2024 7 999`).

### 5. Generate and View the Interactive Folium Map
To generate or re-render the interactive map from exported routes:
```bash
python -m src.visualisation.plot_bus_routes --csv outputs/optimized_routes.csv --geojson outputs/optimized_paths.geojson --out outputs/route_map.html
```
Open [outputs/route_map.html](outputs/route_map.html) in a browser. In PowerShell, run `Start-Process .\outputs\route_map.html`. The map uses external Leaflet assets and OpenStreetMap tiles.
- Select route, direction, and chart. Each selection replaces the previous chart.
- Toggle the blue dashed baseline, orange local search, and green GA layers independently. Nested stroke widths retain visible color around coincident paths without changing the geometry.
- Check the values loaded from the comparison CSV. Terminal markers show S or E, and co-located stop occurrences share a popup that lists every occurrence and model order. Historical boardings and alightings remain survey observations.

### 6. Run the Automated Verification Suite
To execute the comprehensive automated test suite verifying graph integrity, constraints, operators, and data immutability:
```bash
python -m tests.test_routing
python -m tests.validate_outputs
```

The second command checks the saved default Tricity output without running optimization.

---

## Experimental Results

The default Tricity run processed all **118** directional charts, including the **31** that failed under nearest-node snapping in the earlier run. There were no disconnected charts after repair, invalid charts, or runtime errors. The bounded search changed 33 stop occurrences. Another 34 occurrences exceeded the 500 m snap warning and require review.

| Metric across 118 paired charts | Local search | GA |
|---|---:|---:|
| Mean / median distance reduction | 1.394% / 0.000% | 1.684% / 0.000% |
| Mean / median objective reduction | 5.931% / 1.646% | 6.333% / 1.686% |
| Distance improved / unchanged / worsened | 57 / 58 / 3 | 58 / 58 / 2 |
| Objective improved / unchanged / worsened | 75 / 43 / 0 | 75 / 43 / 0 |
| Mean / median reported runtime | 0.013 / 0.009 s | 0.091 / 0.085 s (selected seed) |

GA won/tied/lost **10/108/0** against local search on objective and **9/108/1** on distance. All GA seeds together took 50.73 s across the batch, with a median of 0.411 s per chart. Chart 64 had the largest GA distance reduction (14.99%). Both methods increased distance while lowering objective on charts 21 and 87. Local search also did so on chart 96. On chart 87, GA yielded a lower objective and traveled farther than local search. These comparisons apply to the modeled network and assumptions.

The model CSV, stop CSV, road-path GeoJSON, interactive map, and comparison figure describe processed charts. `comparison_summary.json` gives coverage, paired wins and ties, top charts, rankings, and runtime. `chart_processing.csv` records every discovered chart, statuses, snap warnings, and model-specific improvement flags. `chart_failures.csv` identifies infeasible charts, invalid source rows, and runtime errors. An unchanged objective outcome means neither heuristic improved the baseline objective within the stated tolerance. A lower objective can accompany a longer road route. Local search and GA are heuristics and neither establishes global optimality.

## Limitations

1. **Sampled Historical Demand**: Passenger boardings and alightings originate from peak-hour sample survey charts, not continuous smart-card or real-time 2026 automated passenger counter (APC) data.
2. **Lack of Origin–Destination (OD) Matrix**: The dataset does not provide individual passenger trip origin-destination pairs. Consequently, passenger travel time savings and route section loads cannot be predicted for reordered sequences.
3. **Reconstructed Road Paths**: Baseline trajectories represent Dijkstra shortest paths connecting historical stop sequences on OpenStreetMap, which may differ from historical bus turning choices or operational diversions.
4. **Estimated Traversal Speeds**: Edge traversal times use assumed speeds by road class and fixed dwell. Field verification would require bus trajectory and dwell observations.
5. **Scenario Fleet and Cost Estimations**: Fleet scenarios assume a shared verified headway and use separately estimated directional times. The cost rate may include fixed overheads, so modeled per-traversal costs do not establish realized savings.

---

## References

For detailed source descriptions and complete bibliographic citations, refer to [docs/data_sources.md](docs/data_sources.md).
