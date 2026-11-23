# How do we decide which route is better?

A shorter route can still take longer on roads where we assume lower speeds, or it can change the stop order more than we want. We first check whether an order follows our rules. For orders that pass, we score the distance, estimated bus time, changes to the historical stop order, and early passes through required stop nodes. We use the same score for the baseline, Local Search and the Genetic Algorithm (GA).

## What we measure

**Road distance.** We add the lengths of the directed road links on each leg between stops, including any links traveled more than once, and divide by 1,000 to get kilometres. Dijkstra finds each leg by distance. The baseline uses the historical order, so its distance is the length of a reconstructed path. Lower is better if the goal is to travel fewer road kilometres.

**Estimated bus time.** For each link we divide its length by its assumed speed and add 30 seconds for every intermediate stop visit. For example, the graph assigns 45 km/h to primary roads and 25 km/h to residential roads. In the calculation below, lengths are in metres and speeds are in metres per second:

$$
T_{\mathrm{min}}=\frac{\sum_e(\mathrm{length}_e/\mathrm{speed}_e)+30\max(N-2,0)}{60}
$$

Here \(N\) is the number of stop visits. Two consecutive visits at the same snapped node add zero driving distance and time between them. The usual intermediate-stop allowance still applies. Lower estimated time means a faster modeled bus trip. We have no measured congestion or passenger journey times in this calculation.

**Stop-order disruption.** For each visit, we count how many positions it moves. Moving from position 3 to position 5 counts as two. We weight the movement by the historical number of boardings plus alightings at that visit, so the same move matters more at a busier stop. If \(w_i\) is that weight and \(p_i\) and \(p_i^0\) are the new and original positions:

$$
P=\frac{\sum_i w_i\lvert p_i-p_i^0\rvert}{\sum_i w_i}.
$$

If all weights are zero, we use the ordinary average of the movements. Lower disruption keeps the order closer to the historical list by this measure. A zero-weight stop can move without adding to the weighted score when other stops have positive weights. The weights describe activity at stops. They do not link any passenger’s boarding stop to their alighting stop.

**Shortcut penalty.** A shortest road leg can pass through the road node of another required stop before that stop is due to be visited. We count each distinct required node that is passed early inside a leg once and add **0.1** to the score per node. An early pass adds to the score. It does not by itself make an order infeasible.

## How we combine the measurements

The objective function is the rule for turning the measurements into one score. With the default weights:

$$
J=0.5\frac{D}{D_0}+0.2\frac{T}{T_0}+0.3\frac{P}{\max(N-1,1)}+0.1S.
$$

- \(D/D_0\) compares distance with the baseline for that chart. It has a weight of **0.5**.
- \(T/T_0\) compares estimated time with the same chart’s baseline. It has a weight of **0.2**.
- \(P/\max(N-1,1)\) scales the change in positions to the size of the stop list. It has a weight of **0.3**.
- \(S\) is the early-pass count. \(0.1S\) is the shortcut penalty.

Using ratios lets us combine kilometres, minutes and positions in one score. If baseline distance or time is zero, its ratio is set to one. The three adjustable weights must be finite, nonnegative and add up to one. A lower total score is better. A route can become longer and still score better when the other parts decrease enough.

The [comparison CSV](../outputs/route_comparison.csv) gives the total as `Objective Value` and the four parts as `Distance Component`, `Travel Time Component`, `Disruption Component` and `Shortcut Penalty`. It also gives `Distance (km)`, `Estimated Travel Time (min)` and `Demand-Weighted Disruption` before weighting.

## Which orders are allowed?

A **feasible** order passes the checks in [routing.py](../src/routing/routing.py). Both searches must keep every original visit exactly once, including repeats at the same location. The first and last stops stay fixed so the service still starts and ends at the same places. By default, a stop can move at most **three positions**, and the new distance cannot exceed **1.25 times** the baseline distance. These limits let us test nearby changes while keeping the result recognizable as the same service.

Every leg has to follow the direction of the road links. If the optional corridor is turned on, the full road paths also have to stay within the chosen distance of the baseline. The saved default run did not use that option. `Routing Status` records whether each model passed. A feasible result may be shorter, longer within the detour limit, or unchanged.

## How we compare the searches

For each chart, all three models use the same records, road graph, snapped nodes, rules and scoring formula. Local Search starts with the historical order. GA includes that order among its candidates and runs with **50 candidates**, **60 generations** and seeds **42, 101, 2024, 7 and 999**. We export the seed with the lowest score. We compare Local Search and GA once per chart.

For distance, estimated time and objective, the improvement percentage is:

$$
100\times\frac{\text{baseline value}-\text{model value}}{\text{baseline value}}.
$$

Positive means a reduction, zero means equal and negative means an increase. The percentage stays blank when the baseline is zero. We count differences within **0.000001 km** for distance or **0.00000001** for objective as ties. The summary treats those differences as zero when averaging chart percentages. The mean gives every chart equal weight. The median is the middle result, so it can be zero even when some charts improve a lot.

**Runtime** tells us how long each measured model step took in seconds. The shared road paths are prepared before these timings. `Execution Time (s)` reports the selected seed for GA. `GA Selected Seed` tells us which seed won, and `GA Total Across Seeds (s)` records the time across all five searches. Lower means less time on this run. Speed on another machine can differ.

## Passenger and operating figures

The comparison CSV reports the percentage of original stop visits kept and the sums of their historical boardings and alightings. The maximum observed `Volume` describes the historical sequence and stays blank if observations are incomplete. We also carry through available historical operating figures. These describe the source data and do not affect the search score.

- **Fleet.** The saved fleet column is blank. The optional estimate requires compatible UP and DOWN charts with reversed terminal IDs and a verified shared headway, meaning minutes between buses. It adds both estimated bus times, allows 15% extra for layover, divides by the headway and rounds up to a whole bus. A lower value would mean a smaller modeled requirement under those assumptions.
- **Cost.** For a usable route-performance match, we divide historical expenditure by historical vehicle-kilometres and multiply by the modeled route distance. The result is in rupees for one traversal and is present for **246 model rows**. Lower means a smaller allocation under that historical rate. The result does not measure money actually saved.

## Validation

The [routing tests](../tests/test_routing.py) check directed paths, stop matching and alternative matching, repeated visits, fixed terminals, stop movement, detour, the optional corridor, score calculations and consistent GA results with the same seed. They also check basic map controls in generated HTML. The recorded final audit reports that these tests passed.

The [saved-output checker](../tests/validate_outputs.py) checks that each processed chart has three model rows, maintains the original stops and terminal visits, passes the default movement and detour limits, and follows the directed graph. It checks that the exported paths match the geometry of the selected road links, that distance and time agree with those links, and that the saved totals agree with the results.

Matching a stop to a road node is called **snapping**. On 31 charts, the nearest matches left at least one leg disconnected. We tried a small set of nearby alternatives and chose matches that connected the full historical order with the least added snap distance among those tested. That recovered all 31 charts and changed 33 stop matches. The [processing log](../outputs/chart_processing.csv) records recoveries and warnings, and the [failed-chart log](../outputs/chart_failures.csv) records any charts that could not be processed. In the final run it has only a header. The stop CSV records the original and selected nodes and their distances from the stop. The default 500 m distance bounds alternative snaps and flags farther nearest snaps. The 34 visits flagged for distance, as well as the reassigned matches, need field checks before using them for service planning.

## What the final results tell us

The saved run processed **118 charts**, with **354 model results, 354 road paths and 6,402 stop rows**. The table uses the [saved CSV and JSON results](../outputs/comparison_summary.json).

| Result compared with the baseline | Local Search | GA |
|---|---:|---:|
| Score improved / unchanged / worsened | 75 / 43 / 0 | 75 / 43 / 0 |
| Distance shorter / unchanged / longer | 57 / 58 / 3 | 58 / 58 / 2 |
| Mean / median distance reduction | 1.39% / 0.00% | 1.68% / 0.00% |
| Mean / median score reduction | 5.93% / 1.65% | 6.33% / 1.69% |
| Mean / median measured time per chart | 0.013 s / 0.009 s | 0.091 s / 0.085 s for the selected seed |

GA won, tied and lost **10/108/0** on the objective and **9/108/1** on road distance against Local Search. GA did a little better on average and spent **50.73 seconds** across all seeds in the full run, excluding shared path preparation. The large number of ties makes Local Search a useful comparison. On 43 charts both methods ended with the same score as the baseline within tolerance. The original order may already work well, or neither search may have found a better allowed order.

On chart **87**, GA removed a shortcut penalty of **0.30** and lowered the overall score by **26.98%**, even though distance went up **3.36%**. That trade-off is why we report distance and objective separately. We found useful changes on the road graph under our rules. We cannot conclude that the routes are globally optimal or that passengers, buses or the operator would see the same gains in service.
