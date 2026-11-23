# Data-Driven Route Optimization for Chandigarh CTU Local Bus Network

**BTech Computer Science / Data Science Minor Project**

This repository provides a complete, working geographical bus route optimization system for the Chandigarh Transport Undertaking (CTU) local bus network. The system evaluates and optimizes bus stop sequences and road alignments using historical boarding–alighting passenger data and the OpenStreetMap road network.

Optimization is performed using a **demand-aware, corridor-constrained Genetic Algorithm (GA)** supported by Dijkstra shortest-path calculations on the directed road network, benchmarked against a **reconstructed original-sequence baseline** and a **constrained local search** model.

---

## Objectives

1. **Geographical Stop Sequence Optimization**: Re-sequence intermediate bus stops to minimize road network distance and estimated traversal times while strictly preserving route terminals and corridor boundaries.
2. **Demand Preservation**: Incorporate historical sampled passenger boardings and alightings into a sequence-disruption penalty to prevent disruptive deviations from high-demand passenger clusters.
3. **Road-Network Feasibility**: Restrict all routing decisions to drivable, directed OpenStreetMap links, enforcing one-way constraints, avoiding disconnected road links, and preventing out-of-order shortcut traversals.
4. **Operational Impact Evaluation**: Assess the consequences of proposed route alignments across road distance, travel time, passenger disruption, fleet requirements, and operational expenditure.

---

## Datasets

### Primary Dataset: Boarding–Alighting Observations
- **Path**: `data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV`
- **Scope**: 2,134 stop-level observation records across 118 directional charts representing 68 unique route identifiers.
- **Attributes**: `chart_no`, `route`, `direction`, `stop_order`, `chart_label`, `ctu_stop_id`, `ctu_stop_name`, `latitude`, `longitude`, `Boardings`, `Alightings`, `Volume`.
- **Role**: Serves as the immutable primary input for identifying existing routes, ordering stop sequences, geographic coordinate snapping, computing stop importance, evaluating demand disruption, and ensuring complete stop preservation.

### Road Network Graph
- **Path**: `data/roadnodes/chandigarh_road_network.graphml`
- **Scope**: Directed `MultiDiGraph` extracted from OpenStreetMap using OSMnx, comprising 12,148 nodes and 31,166 edges.
- **Attributes**: Geodesic edge lengths (`length_m`), functional road classifications (`highway`), one-way directionality, and curvilinear road geometries (WKT `geometry`). The primary strongly connected component encompasses 11,960 nodes (98.5%), preventing cul-de-sac and dead-end traps during stop snapping.

### Secondary Dataset: Route Performance Parameters
- **Path**: `data/passengerdata/performance_routes_clean.csv`
- **Scope**: Operational audit records for 68 CTU bus routes.
- **Attributes**: `Route No`, `Morning Peak Headway`, `Afternoon Headway`, `Route Length (km)`, `Daily Ridership`, `On road Fleet`, `Actual Veh. Km`, `Total Expenditure (Rs)`, `Load Factor`.
- **Role**: Utilized exclusively for supplementary operational scenario evaluation (fleet sizing and unit operating expenditure). This dataset is not used as an optimization input.

---

## Data Sources

A complete description of data provenance, survey methodologies, and bibliographic citations is provided in [docs/data_sources.md](file:///c:/Users/hppav/OneDrive/Documents/VSCODE/route-optimization-chdtricity/docs/data_sources.md).

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
          └──> Approach C: Corridor-Constrained Genetic Algorithm (Multi-seed GA + Dijkstra)
```

1. **Approach A — Reconstructed Original-Sequence Baseline**:
   Stops are ordered by their historical `stop_order` and snapped to the nearest road network node in the primary strongly connected component. Consecutive stops are connected via Dijkstra shortest paths on the directed road network.
2. **Approach B — Constrained Local Search**:
   An iterative first-improvement hill-climbing heuristic applying local adjacent swaps, short 2-opt subsequence reversals (length 2 to 3), and localized insertions within strict displacement limits.
3. **Approach C — Demand-Aware Corridor-Constrained Genetic Algorithm**:
   A population-based metaheuristic exploring candidate permutations under strict geographical and service constraints.

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
10. Shortcut penalty: detects and penalizes paths passing scheduled future stops out of order.
11. Reconstructed original sequence retained as an elitist fallback candidate.

### Fitness Function
The multi-objective fitness minimizes normalized road distance, estimated travel time, and demand disruption:
$$\min J = \alpha D_n + \beta T_n + \gamma P_n$$
where:
- $D_n = \frac{D}{D_{\text{baseline}}}$: Normalized road distance.
- $T_n = \frac{T}{T_{\text{baseline}}}$: Normalized estimated travel time.
- $P_n = \frac{P}{N - 1}$: Normalized demand-weighted sequence disruption.
- $\alpha, \beta, \gamma \ge 0$: Configurable non-negative weights ($\alpha=0.5, \beta=0.2, \gamma=0.3$ by default).

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
   where stop importance $w_i = B_i + A_i$. Measures displacement weighted by historical boarding and alighting activity.
4. **Estimated Fleet Requirement ($F$)**:
   $$F = \left\lceil \frac{C}{H} \right\rceil$$
   where $C$ is the round-trip cycle time including layover buffer (15%) and $H$ is the peak headway from matched performance data.
5. **Modeled Operating Cost Scenario ($C_{\text{scenario}}$, Rs)**:
   $$c_{\text{km}} = \frac{\text{Total Expenditure}}{\text{Actual Vehicle-Km}}, \quad C_{\text{scenario}} = \text{Trips} \times D \times c_{\text{km}}$$

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
│       └── chandigarh_road_network.graphml
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
To run the optimization for a single route-direction (e.g., Route 3 UP, which starts from Mauli Jagran and terminates at PGI):
```bash
python -m src.routing.routing --route 3 --direction UP
```
This command runs:
- **Approach A**: Reconstructed original-sequence road baseline.
- **Approach B**: Constrained Local Search.
- **Approach C**: Constrained Genetic Algorithm across 5 random seeds (`42, 101, 2024, 7, 999`).
- Generates all evaluation metrics, CSVs, GeoJSON paths, comparison figure, and Folium interactive map.

### 2. Batch Optimize Representative CTU Routes
To run batch optimization across all 5 representative routes (Route 3 UP, Route 11 UP, Route 17 UP, Route 18 UP, and Route 143 UP):
```bash
python -m src.routing.routing --all
```
Outputs are compiled into [outputs/route_comparison.csv](file:///c:/Users/hppav/OneDrive/Documents/VSCODE/route-optimization-chdtricity/outputs/route_comparison.csv).

### 3. Run Multi-Objective Sensitivity Analysis
To evaluate how different objective weightings alter the optimal stop sequence (Distance-Focused vs. Balanced vs. Demand-Preservation-Focused):
```bash
python -m src.routing.routing --route 3 --direction UP --sensitivity
```

### 4. Custom Parameter Configuration (Optional)
GA parameters, objective weights, and displacement constraints can be customized via optional CLI flags:
```bash
python -m src.routing.routing --route 3 --direction UP --alpha 0.6 --beta 0.2 --gamma 0.2 --max-displacement 2 --pop-size 60 --generations 80
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

The optimization models were evaluated across five representative directional charts covering varying route lengths, stop counts, and historical passenger activity levels.

### Summary Evaluation Table

| Route | Direction | Chart | Model | Distance (km) | Est. Time (min) | Disruption | Est. Fleet | Modeled Cost (Rs) | Objective | Status |
|:---:|:---:|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **3** | UP | 1 | Reconstructed Baseline | 30.443 | 63.87 | 0.000 | 4 | 20,266.13 | 1.0000 | Connected |
| **3** | UP | 1 | Constrained Local Search | 27.149 | 58.91 | 0.267 | 4 | 18,072.93 | 0.6354 | Feasible (-10.8%) |
| **3** | UP | 1 | Constrained GA Best | 24.708 | 53.97 | 0.640 | 3 | 16,448.14 | 0.5868 | Feasible (-18.8%) |
| **11** | UP | 3 | Reconstructed Baseline | 6.110 | 14.14 | 0.000 | 2 | 4,806.78 | 1.0000 | Connected |
| **11** | UP | 3 | Constrained Local Search | 6.110 | 14.14 | 0.000 | 2 | 4,806.78 | 0.7000 | Optimal (0.0%) |
| **11** | UP | 3 | Constrained GA Best | 6.110 | 14.14 | 0.000 | 2 | 4,806.78 | 0.7000 | Optimal (0.0%) |
| **17** | UP | 5 | Reconstructed Baseline | 21.722 | 47.86 | 0.000 | 12 | 106,481.93 | 1.0000 | Connected |
| **17** | UP | 5 | Constrained Local Search | 21.722 | 47.86 | 0.000 | 12 | 106,481.93 | 0.7000 | Optimal (0.0%) |
| **17** | UP | 5 | Constrained GA Best | 21.722 | 47.86 | 0.000 | 12 | 106,481.93 | 0.7000 | Optimal (0.0%) |
| **18** | UP | 7 | Reconstructed Baseline | 15.123 | 33.26 | 0.000 | 5 | 41,186.34 | 1.0000 | Connected |
| **18** | UP | 7 | Constrained Local Search | 15.123 | 33.26 | 0.000 | 5 | 41,186.34 | 0.7000 | Optimal (0.0%) |
| **18** | UP | 7 | Constrained GA Best | 15.123 | 33.26 | 0.000 | 5 | 41,186.34 | 0.7000 | Optimal (0.0%) |
| **143** | UP | 15 | Reconstructed Baseline | 25.330 | 57.90 | 0.000 | 5 | 16,863.18 | 1.0000 | Connected |
| **143** | UP | 15 | Constrained Local Search | 25.330 | 57.90 | 0.000 | 5 | 16,863.18 | 0.7000 | Optimal (0.0%) |
| **143** | UP | 15 | Constrained GA Best | 25.330 | 57.90 | 0.000 | 5 | 16,863.18 | 0.7000 | Optimal (0.0%) |

### Key Experimental Insights
1. **Geometric Redundancies vs. Corridor Linearity**:
   - For **Route 3 UP**, the existing stop sequence contains circuitous detours around the Railway Crossing, Grain Market, and General Hospital corridors. The Constrained GA identified a re-sequencing that reduces road distance by **18.84%** (from 30.44 km to 24.71 km) with modest disruption ($P = 0.64$).
   - For **Routes 11, 17, 18, and 143**, the baseline sequences are already topologically aligned along linear arterial corridors (Madhya Marg, Jan Marg, Dakshin Marg). Under strict neighborhood and displacement constraints, no re-ordering can reduce road distance without violating corridor bounds. The algorithm correctly retains the baseline sequence as the optimal configuration.
2. **Sensitivity Analysis Findings (Route 3 UP)**:
   - **Distance-Focused** ($\alpha=0.8, \beta=0.1, \gamma=0.1$): GA selects the 24.71 km sequence (Objective: 0.7378).
   - **Balanced** ($\alpha=0.5, \beta=0.2, \gamma=0.3$): GA selects the 24.71 km sequence (Objective: 0.5868).
   - **Demand-Preservation-Focused** ($\alpha=0.2, \beta=0.1, \gamma=0.7$): GA prioritizes low passenger displacement and selects the 27.15 km sequence with minimal disruption ($P = 0.27$, Objective: 0.2823).

---

## Limitations

1. **Sampled Historical Demand**: Passenger boardings and alightings originate from peak-hour sample survey charts, not continuous smart-card or real-time 2026 automated passenger counter (APC) data.
2. **Lack of Origin–Destination (OD) Matrix**: The dataset does not provide individual passenger trip origin-destination pairs. Consequently, passenger travel time savings and route section loads cannot be predicted for reordered sequences.
3. **Reconstructed Road Paths**: Baseline trajectories represent Dijkstra shortest paths connecting historical stop sequences on OpenStreetMap, which may differ from historical bus turning choices or operational diversions.
4. **Estimated Traversal Speeds**: Edge traversal times are derived from functional road-class speed guidelines rather than live traffic telemetry.
5. **Scenario Fleet and Cost Estimations**: Fleet sizing assumes uniform headway and symmetric return cycles. Operating costs assume linear scaling of average expenditure per vehicle-kilometre, which includes fixed depot and administrative overheads.

---

## References

For detailed source descriptions and complete bibliographic citations, refer to [docs/data_sources.md](file:///c:/Users/hppav/OneDrive/Documents/VSCODE/route-optimization-chdtricity/docs/data_sources.md).
