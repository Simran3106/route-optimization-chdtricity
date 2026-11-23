# Evaluation and validation

This reference describes the saved default Tricity experiment. For installation and execution, see the [README](../README.md). For the interface, see the [map guide](MAP_GUIDE.md). In the sections below, function names refer to [routing.py](../src/routing/routing.py) unless indicated.

## Experimental design

Every model works on the same directional chart and uses the same original stop occurrences, selected road nodes, directed graph, and distance-shortest road legs. The baseline keeps the historical ordering. Local Search starts there and tries feasible swaps, short reversals, and insertions, accepting a lower score. The GA starts with the baseline among its candidates, uses tournament selection, crossover, mutation, and elitism, and runs with a population of 50 for 60 generations per seed. The configured seeds are **42, 101, 2024, 7, and 999**. The exported GA row is the result with the lowest objective across seeds. Seeds are repeated searches on one chart, so the paired comparison counts the chart once.

A candidate must retain every original occurrence exactly once, preserve the first and last occurrences, meet the displacement limit (three positions by default), and connect every leg in the directed graph. Total distance may reach at most 1.25 times baseline distance by default. When enabled, the corridor check bounds complete candidate path segments relative to the reconstructed baseline. The saved run uses no optional corridor. These are **hard constraints** checked by `is_candidate_feasible` and `RouteCostMatrix._check_corridor`. Objective penalties rank candidates that meet those constraints. Fleet and cost are separate scenarios.

## Road distance and estimated bus time

For a sequence of \(N\) stop occurrences, let \(E\) be the directed road edges traversed across all \(N-1\) legs, counting repetitions. Let \(l_e\) be the GraphML edge length in metres and \(v_e\) the assigned road-class speed in metres per second.

$$
D_{\mathrm{km}} = \frac{\sum_{e\in E} l_e}{1000},
\qquad
T_{\mathrm{min}} = \frac{\sum_{e\in E} l_e/v_e + 30\max(N-2,0)}{60}.
$$

The same definitions apply to the baseline and the optimized sequences. `RoadNetwork._prepare_edge_attributes` sets edge times using road-class assumptions such as 50 km/h on trunk, 45 on primary, 40 on secondary, 30 on tertiary, and 25 on residential roads. `get_shortest_paths` selects paths by **distance**. `RouteCostMatrix.evaluate_sequence` sums distance and time along those paths, adding 30 seconds per intermediate occurrence. Lower distance means fewer modeled kilometres. Lower time means a faster modeled bus traversal. An adjacent pair sharing a snapped node contributes zero road length and drive time, while intermediate dwell still applies. Negative distances or times have no physical meaning. There is no measured traffic, passenger wait, or observed route travel time in either metric.

The [model CSV](../outputs/route_comparison.csv) exports `Distance (km)` and `Estimated Travel Time (min)`. The [GeoJSON](../outputs/optimized_paths.geojson) includes selected node sequences, geometry, and corresponding rounded metrics.

## Objective and its components

Let \(D_0\) and \(T_0\) denote the reconstructed baseline distance and time for the same chart. The implementation in `sequence_objective`, `objective_components`, `calculate_demand_disruption`, and `check_shortcut_stops` is:

$$
J = 0.5\frac{D}{D_0} + 0.2\frac{T}{T_0} +
    0.3\frac{P}{\max(N-1,1)} + 0.1S.
$$

These are default weights. The first three weights are configurable, finite, nonnegative, and must sum to one. The score is dimensionless. Distance and time use consistent units in each ratio. If the relevant baseline denominator is zero, that ratio uses **1**, so it contributes its configured weight. An unreachable sequence scores infinite in `sequence_objective`. A feasible baseline has zero disruption and typically starts at \(0.7+0.1S_0\) under default weights. It may have shortcut encounters.

| Component | Definition and interpretation | Model CSV field |
|---|---|---|
| Distance | Weighted ratio of modeled distance to baseline distance. A ratio of 1 is equal to baseline. A ratio above 1 means longer distance. | `Distance Component` |
| Time | Weighted ratio of estimated bus time to baseline time. A ratio above 1 means a longer modeled traversal time. | `Travel Time Component` |
| Disruption | Weighted normalized displacement, as defined below. Zero means the weighted positions are unchanged. With positive total demand, moved zero-weight stops can still yield zero. | `Demand-Weighted Disruption`, `Disruption Component` |
| Shortcut | \(S\) counts distinct required snapped nodes encountered as interior nodes of a leg before being served. The penalty is \(0.1S\). Zero means there were no such encounters. The raw count is recoverable by dividing the penalty by 0.1. | `Shortcut Penalty` |
| Combined score | Sum of the four components. Lower is preferred. A reduction can result from changes in any combination of the components. | `Objective Value` |

For stop occurrence \(i\), \(w_i=\mathrm{Boardings}_i+\mathrm{Alightings}_i\), and \(p_i\) and \(p_i^0\) are optimized and historical sequence positions. With positive total observed activity:

$$
P = \frac{\sum_i w_i\lvert p_i-p_i^0\rvert}{\sum_i w_i}.
$$

When all weights are zero, the code takes the unweighted mean of absolute displacement. Lower \(P\) means the ordering stays closer to the historical chart in this measure. The unit is stop positions. Displacement and shortcut counts are nonnegative. They do not measure passenger delays or quantify who traveled between stops.

## Improvement, runtime, and paired comparisons

For metric \(M\) with a positive baseline \(M_0\), `improvement_pct` computes \(100(M_0-M)/M_0\). A positive result is a reduction, zero means equal, and negative means an increase. A zero baseline leaves the percentage blank. The CSV columns are `Distance Improvement (%)`, `Estimated Travel Time Improvement (%)`, and `Objective Improvement (%)`. An objective reduction can accompany a distance increase when other score components decrease enough to offset it.

`compare_algorithms` uses absolute tolerances of **0.000001 km** for distance and **0.00000001** units for objective. In paired results, subtract GA from Local Search on the same chart. A difference above tolerance is a GA win, a difference below negative tolerance is a loss, and values between are ties. For each algorithm against baseline, differences within tolerance are treated as unchanged and are zeroed before computing summary percentage statistics. Mean and median are across chart-level percentages with positive baseline denominators. The mean gives equal weight to each chart. The median shows the middle chart-level outcome and can be zero even when the mean is positive. Raw CSV improvement percentages may show very small nonzero differences that the summary treats as ties.

`Execution Time (s)` reports elapsed time for baseline evaluation, Local Search, or the selected GA seed. `GA Selected Seed` identifies the selected run, and `GA Total Across Seeds (s)` covers the GA stage across the configured seeds. The shared path matrix is prepared before these model timings. Lower runtime requires less elapsed time for that measured stage. Zero can occur after rounding short intervals, and negative durations have no intended interpretation. Timings depend on the machine and workload. In the [JSON summary](../outputs/comparison_summary.json), `paired` records wins, ties, losses, and charts with no GA advantage. `local_search` and `ga` record baseline comparisons, rankings, and runtime statistics.

## Source retention, snapping, and outcomes

- **Retention and historical fields.** Feasible models preserve all stop occurrences. `Stops Retained (%)` reports 100 for these models. `Historical Boardings Retained` and `Historical Alightings Retained` sum recorded counts for the retained occurrences. `Historical Maximum Volume` describes the original observations and is unavailable if the required observed volumes are incomplete. A zero recorded count represents no observed activity for that field. These values do not predict passenger flows on the reordered sequence. They are set by the model evaluation routines and exported alongside `Routing Status`, `Road Network`, and chart identifiers.
- **Snapping.** `RoadNetwork.snap_stop`, `nearby_nodes`, and `repair_stop_snaps` use approximate local geographic distances in metres. The stop CSV records `original_osm_node`, `osm_node`, `original_snap_distance_m`, `snap_distance_m`, `snap_reassignment_reason`, and `snap_exceeds_threshold`. Zero means the coordinates coincide with the node. A large distance calls for review, and negative distances have no meaning. The 500 m default bounds alternatives and warns about retained nearest snaps beyond that distance. The search considers up to eight nearby nodes around affected occurrences and chooses a connected complete assignment minimizing added snap distance. This verifies network reachability on the graph. Correct curbside access still requires field verification.
- **Processing.** `main` writes [chart_processing.csv](../outputs/chart_processing.csv) with `processed`, `infeasible`, `invalid_data`, or `runtime_error` for every chart. Processed charts also have `objective_outcome`, per-model improvement flags, recovery indicators, reassignment counts, and snap warnings. [chart_failures.csv](../outputs/chart_failures.csv) carries source lines and diagnostic text for failures. A header-only failure CSV means no failures were recorded. A processed but unchanged chart can reflect a baseline that neither search improved under the enabled constraints and tolerances.

## Historical operations and modeled scenarios

`match_performance_record` matches a unique route identifier, including any variant, and uses direction when explicitly available. The model CSV can carry historical daily ridership, load factor, administrative route length (km), on-road fleet (buses), vehicle-kilometres, and expenditure (Rs). These are source context and have no universal better direction as optimization metrics. Missing or invalid entries stay blank.

`apply_fleet_scenarios` and `evaluate_operational_scenarios` estimate \(\left\lceil1.15(T_{UP}+T_{DOWN})/H\right\rceil\) buses with a common verified positive headway \(H\) in minutes and 15% layover. The opt-in `--verified-headway-minutes` assumes the user has independently verified the headway. It requires one chart per direction for the route, matching reversed terminal IDs, feasible results for the same model, and a usable shared performance record. The value is recorded once per pair on the UP model row as `Modeled Round-Trip Fleet Requirement`. Lower indicates a smaller modeled requirement under those conditions. The saved values are blank.

The cost model allocates \(D_{\mathrm{km}} \times \text{historical expenditure} / \text{historical vehicle-km}\) in Rs per directional traversal. It requires positive compatible inputs, including an administrative route length and historical vehicle-km at least as large as that length. `Modeled Operating Cost per Traversal (Rs)` has 246 populated model rows. A lower value indicates a lower modeled allocation under the assumed historical rate. Neither scenario treats zero or negative required inputs as valid, and blanks represent unavailable scenarios. These figures do not establish realized savings, fleet redesign, or staffing requirements.

## Validation and final results

| Check | Evidence |
|---|---|
| Routing regression suite | [test_routing.py](../tests/test_routing.py) covers source and fixture integrity, graph direction, Dijkstra, snapping and alternative snapping, repeated occurrences, fixed terminals, displacement and detour constraints, corridor segments, objective consistency, GA repeatability, and operational scenarios. The recorded final audit log reports a pass. |
| Saved-output validator | [validate_outputs.py](../tests/validate_outputs.py) checks status accounting, the three rows per processed chart, stop retention and original fields, feasible permutations, fixed terminals, displacement and detour, snap records, directed edges and geometries, distance/time consistency, and aggregate metrics. It does not run the optimizers. |
| Map checks | The regression suite checks generated HTML controls. A separate Chrome smoke check during the final audit observed chart changes and independent layer visibility on the full map. These checks do not validate real-world roads or operating conditions. |

The saved run accounts for **118 processed charts, 354 model rows, 354 directed road paths, and 6,402 stop rows**. It recovered 31 charts with a disconnected nearest-node assignment and recorded 33 reassigned stop occurrences. There were zero residual disconnected charts, invalid records that blocked a chart, or runtime-error outcomes. The 34 distant stop occurrences and the reassigned locations still warrant field review.

| Saved result | Local Search | GA |
|---|---:|---:|
| Distance improved / unchanged / worsened | 57 / 58 / 3 | 58 / 58 / 2 |
| Objective improved / unchanged / worsened | 75 / 43 / 0 | 75 / 43 / 0 |
| Mean / median distance reduction | 1.394% / 0.000% | 1.684% / 0.000% |
| Mean / median objective reduction | 5.931% / 1.646% | 6.333% / 1.686% |
| Mean / median model execution time | 0.013 s / 0.009 s | 0.091 s / 0.085 s, selected seed |
| GA all-seed runtime | — | 50.73 s total, 0.411 s median per chart |

GA won/tied/lost **10/108/0** on objective and **9/108/1** on distance against Local Search. The frequent ties and zero median distance reductions support a limited practical advantage for GA on this experiment, with more measured search time. No statistical superiority has been established. Both methods lowered objective while increasing distance on charts **21** and **87**, and Local Search did so on chart **96**. On chart 87, GA improved objective by 26.98% with a 3.36% distance increase, while Local Search improved objective by 17.98% with a 2.58% distance increase. The shortcut penalty fell from 0.30 in the baseline to 0.10 under Local Search and 0.00 under GA, offsetting the higher distance, time, and disruption components. Historical observations and these algorithms do not establish passenger travel-time savings or global optimality.
