# Data Sources and References

This document provides complete provenance, methodology descriptions, and bibliographic references for all datasets and academic literature utilized in the **Data-Driven Route Optimization for Chandigarh CTU Local Bus Network** project.

---

## 1. Official CTU and Route Information

- **Chandigarh Transport Undertaking (CTU) Official Portal**
  - URL: [https://chdctu.gov.in/](https://chdctu.gov.in/)
  - Details: Provides official administrative details, fare structures, depot locations (Depot I, II, III), operating divisions, and public transit notices for the Union Territory of Chandigarh and adjoining Tricity areas (Panchkula and Mohali).
- **Where Is My CTU – Bus Stop Directory**
  - URL: [https://whereismyctu.com/stops](https://whereismyctu.com/stops)
  - Details: Web directory mapping contemporary CTU bus stops, standardized stop names, and approximate coordinates across Chandigarh sectors and suburban terminals.

---

## 2. Passenger Boarding and Alighting Data (Primary Dataset)

- **Source File**: `data/passengerdata/chart_data/join_alightingsboardings_with_standard routes.CSV`
- **Origin & Institutional Context**:
  - Originates from the comprehensive urban public transport study conducted by the **CEPT Research and Development Foundation (CRDF)** in collaboration with the Chandigarh Administration and the Ministry of Housing and Urban Affairs (MoHUA).
  - Public Repository / MoHUA Reference: [MoHUA Technical Documentation](https://www.mohua.gov.in/static/uploads/2025/10/b94af0517f9846d279cd0b0bed2f98b9.pdf)
- **Methodology & Sampling Characteristics**:
  - The dataset comprises digitized passenger load profiles across **118 directional charts** covering **68 route identifiers** and **2,134 stop-level observation records**.
  - Observations capture sampled peak-hour trips collected via manual on-board conductor/enumerator survey charts during the study period.
  - Recorded attributes include:
    - `Boardings` ($B_i$): Number of passengers boarding the bus at stop occurrence $i$.
    - `Alightings` ($A_i$): Number of passengers alighting from the bus at stop occurrence $i$.
    - `Volume` ($V_i$): On-board passenger occupancy (section load) departing stop occurrence $i$.
- **Methodological Limitations & Usage Protocol**:
  - **Fixed Historical Benchmark**: The passenger records represent historical peak-hour trip samples, not continuous or real-time 2026 ridership.
  - Recorded zeros are valid survey observations. Missing or malformed boardings and alightings leave chart-level demand-weighted fitness unavailable. Missing volume remains blank and makes the chart maximum unavailable. Stop occurrences with missing source IDs retain a blank ID.
  - **Section Load Invariance**: Observed section loads (`Volume`) reflect the specific sequence of stops in the historical sample. Because an origin–destination (OD) passenger interchange matrix is unavailable, passenger section loads cannot be transferred to reordered stop sequences. Volume is used strictly for descriptive characterization of baseline passenger activity.

---

## 3. Route Performance Data (Secondary Dataset)

- **Source File**: `data/passengerdata/performance_routes_clean.csv`
- **Origin**: Operational performance audit compiled for 68 CTU local bus routes during the transport planning review.
- **Attributes Utilized**:
  - `Route No`: Identifier for cross-referencing route records.
  - `Morning Peak Headway` and `Afternoon Headway` are supplied without explicit units in the CSV header. Verify the source interval and shared directional meaning before enabling modeled fleet.
  - `Route Length (km)`: Historical administrative route length.
  - `Daily Ridership`: Total recorded daily passengers carried across the route.
  - `On road Fleet`: Historical number of operational buses allocated.
  - `Actual Veh. Km`: Total daily vehicle-kilometres operated.
  - `Total Expenditure (Rs)`: Daily route operating expenditure.
  - `Total Revenue (Rs)`: Daily route farebox revenue.
  - `Load Factor` & `Operating Ratio`: Fleet efficiency and cost-recovery indicators.
- **Methodological Usage & Scope Boundaries**:
  - The performance dataset is used **exclusively for post-optimization operational evaluation** (scenario fleet estimation and expenditure scaling). It is **not** used as an input to the route generation or stop sequencing algorithms.
  - Match a single exact route identifier, including any variant suffix. Historical figures are reported as service-level values.
  - The rate in rupees per vehicle-kilometre assumes expenditure and mileage cover the same reporting period. Positive route length and mileage at least as large as the administrative route length are required. Multiplying the rate by modeled directional kilometres yields a standardised cost for one traversal.
  - A fleet scenario requires unique compatible UP and DOWN charts, matching reversed terminal IDs, and a verified common peak interval in minutes. The cycle uses both directional times plus 15% layover. Results appear on the UP row only. Missing or incompatible inputs leave scenario values blank.

---

## 4. Bus Stop and Geographical Information

- **Bus Stop Datasets**:
  - `data/bustop/ctu_stops.csv`
  - `data/bustop/ctu_stops_directory.csv`
  - `data/bustop/ctu_stops_raw.csv`
- **Coordinate Reference**:
  - All bus stops are referenced using geographic coordinates on the **WGS 84 (EPSG:4326)** coordinate reference system.
  - Latitude and longitude values were mapped to street-level stop positions across Chandigarh's grid layout (V1 to V7 street hierarchy).

---

## 5. OpenStreetMap Road Network and OSMnx

- **Default file**. `data/roadnodes/tricity_road_network.graphml` covers Chandigarh, Mohali, and Panchkula. Graph metadata records a simplified WGS84 graph created with OSMnx 2.2.0 on 23 November 2026. The source has 54,469 nodes and 139,725 directed edges.
- **Optional file**. `data/roadnodes/chandigarh_road_network.graphml` covers Chandigarh and can be selected with `--graphml`.
- Both files store node longitude in `x`, latitude in `y`, edge lengths in metres in `length`, and optional WKT line geometry. Directed edge orientation preserves one-way links. The supported classes are trunk, primary, secondary and tertiary roads and their links, plus residential, living streets and unclassified roads. Explicitly restricted access links and invalid lengths are excluded.
- Stop snapping uses all usable nodes, including nodes outside the largest strongly connected component. Disconnected directed legs are recorded as chart failures. The map uses the selected edge geometry in traversal order.
- Sources and tools include [OpenStreetMap](https://www.openstreetmap.org/) and [OSMnx](https://osmnx.readthedocs.io/).

---

## 6. Relevant Research Literature

The optimization methodology, constraint formulation, and genetic algorithm architecture are grounded in published peer-reviewed transportation research literature:

1. **Guihaire, V., & Hao, J.-K. (2008).**  
   *Transit network design and scheduling: A global review.*  
   *Transportation Research Part A: Policy and Practice*, 42(10), 1251–1273.  
   DOI: [10.1016/j.tra.2008.03.011](https://doi.org/10.1016/j.tra.2008.03.011)

2. **Iliopoulou, C., & Kepaptsoglou, K. (2021).**  
   *A survey on the transit network design and frequency setting problem.*  
   *Public Transport*, 13(3), 441–488.  
   DOI: [10.1007/s12469-021-00284-y](https://doi.org/10.1007/s12469-021-00284-y)

3. **Fan, W., & Machemehl, R. B. (2006).**  
   *Optimal transit route network design problem with variable transit demand: Genetic algorithm approach.*  
   *Journal of Transportation Engineering*, 132(1), 40–51.  
   DOI: [10.1061/(ASCE)0733-947X(2006)132:1(40)](https://doi.org/10.1061/(ASCE)0733-947X(2006)132:1(40))

4. **Farahani, R. Z., Miandoabchi, E., Szeto, W. Y., & Rashidi, H. (2015).**  
   *Mathematical programming formulations for transit network design.*  
   *Transportation Research Part B: Methodological*, 77, 100–126.  
   DOI: [10.1016/j.trb.2015.03.006](https://doi.org/10.1016/j.trb.2015.03.006)

5. **Durán-Micco, J., & Vansteenwegen, P. (2021).**  
   *Approximate multi-objective optimization for integrated bus route design and service frequency setting.*  
   *Transportation Research Part B: Methodological*, 154, 30–54.  
   DOI: [10.1016/j.trb.2021.10.007](https://doi.org/10.1016/j.trb.2021.10.007)
