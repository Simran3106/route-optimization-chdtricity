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
   Stops are ordered by their historical `stop_order` and snapped to the nearest road network node on the selected usable directed graph. Consecutive stops are connected via Dijkstra shortest paths on the directed road network.
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
10. When `--corridor-m` is supplied, every candidate road-geometry vertex must lie within that distance of a baseline road segment, using a local metric approximation.

An inaccessible consecutive pair makes the chart infeasible. Multiple occurrences may share a snapped node, with zero driving distance between consecutive occurrences at that node. The snap warning threshold defaults to 500 m and can be changed with `--max-snap-m`. The baseline remains available to both optimizers when it satisfies the constraints.

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
2. **Estimated Travel Time ($T$, min)**: Road traversal time based on functional road-class speed limits (Trunk: 50 km/h, Primary: 45 km/h, Secondary: 40 km/h, Tertiary: 30 km/h, Residential: 25 km/h) plus a standardized dwell time of 30 seconds per intermediate stop.
3. **Demand-Weighted Disruption ($P$)**:
   $$P = \frac{\sum_i w_i |p_i^{\text{new}} - p_i^{\text{old}}|}{\sum_i w_i}$$
   where stop importance $w_i = B_i + A_i$. Measures displacement weighted by historical boarding and alighting activity. Recorded zero demand is valid. Missing or malformed boarding or alighting values make the chart invalid for the weighted analysis. An all-zero chart uses mean unweighted displacement.
4. **Modeled Round-Trip Fleet** uses $F=\lceil 1.15(T_{UP}+T_{DOWN})/H\rceil$. The 15% allowance represents terminal layover and turnaround. The estimate requires a unique pair with reversed matching terminal IDs and a verified shared peak interval $H$ in minutes. It appears once per route and model on the UP row. Enable it with `--verified-headway-minutes` after checking the source.
5. **Modeled Cost per Directional Traversal** multiplies modeled road distance by historical expenditure divided by historical vehicle-kilometres. This allocation assumes a constant average cost per vehicle-kilometre and requires a unique exact route match and positive, compatible historical inputs. Historical route length is a plausibility check. The scenario uses no inferred number of trips.

Distance and objective improvement use their respective baseline denominators and are reported in separate columns. Fleet and cost are operational scenarios evaluated after sequencing.

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
Open [outputs/route_map.html](file:///c:/Users/hppav/OneDrive/Documents/VSCODE/route-optimization-chdtricity/outputs/route_map.html) directly in any web browser to:
- Compare baseline, local search, and GA road trajectories.
- Toggle between passenger Volume and Boardings.
- Inspect stop-level popups with historical demand and sequence positions.

### 6. Run the Automated Verification Suite
To execute the comprehensive automated test suite verifying graph integrity, constraints, operators, and data immutability:
```bash
python -m tests.test_routing
```

---

## Experimental Results

The default Tricity run discovered 118 directional charts and processed 87. The remaining 31 had a disconnected directed road leg after snapping. Local search and GA each improved the objective on 50 charts. Road distance decreased on 37 charts under local search and 38 under GA. These counts describe the reconstructed road-network scenarios.

The five outputs include the model comparison CSV, stop sequence CSV, road-path GeoJSON, interactive map, and comparison figure. `chart_processing.csv` records every discovered chart, statuses, snap warnings, and model-specific improvement flags. `chart_failures.csv` identifies infeasible charts, invalid source rows, and runtime errors. An unchanged result means neither heuristic improved the baseline objective within the tested search.

## Limitations

1. **Sampled Historical Demand**: Passenger boardings and alightings originate from peak-hour sample survey charts, not continuous smart-card or real-time 2026 automated passenger counter (APC) data.
2. **Lack of Origin–Destination (OD) Matrix**: The dataset does not provide individual passenger trip origin-destination pairs. Consequently, passenger travel time savings and route section loads cannot be predicted for reordered sequences.
3. **Reconstructed Road Paths**: Baseline trajectories represent Dijkstra shortest paths connecting historical stop sequences on OpenStreetMap, which may differ from historical bus turning choices or operational diversions.
4. **Estimated Traversal Speeds**: Edge traversal times are derived from functional road-class speed guidelines rather than live traffic telemetry.
5. **Scenario Fleet and Cost Estimations**: Fleet scenarios assume a shared verified headway and use separately estimated directional times. The cost rate may include fixed overheads, so modeled per-traversal costs do not establish realized savings.

---

## References

For detailed source descriptions and complete bibliographic citations, refer to [docs/data_sources.md](docs/data_sources.md).
