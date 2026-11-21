# Navigation arena rerun

The authority was built from `nav-planner` at `62defaea` on Spark and published to `slop-move-stdb` 2.14.1 at loopback port 3361. The report uses the final scanner. See the [implementation and initial validation](2026-11-19-0040-nav-planner.md) and the [release targets](../../../../../docs/MOVEMENT_MIND.md#4-measures-the-navigation-arenas).

Every arena held `~/slop-mq/battle.lock`. Fourteen fresh island worlds drove two controller arms each, five subjects per arm, for 300 scored walks. N1 had three walks per subject. N2 had one scored walk following its warm-up. The arena used `mind_act` and genuine player identities with `human_act`. The trial server and reference worlds were outside the run. No mind service connected to the scratch worlds and there were zero model calls. Every matrix launcher returned zero, and the owned databases were paused and deleted after capture.

## Closed-gate scene

The standalone scene passed 4/4, including two successful warm-up crossings, a physically closed gate, stale open memory at dispatch, and arrival. The orphan guard paused the world during its second warm-up because it watched the short-lived build-slot shell. It was re-armed for the persistent driver shell against the same database identity and epoch, and the scene resumed before the scored walk. The matrix launched from persistent driver shells and applied the build slot to Cargo alone. The scene's scored walk took 91.59 s, with six ground writes and 845 ms latency from the geometric sight estimate. The 40-test authority library suite subsequently passed in full.

## Walks

Arrival means reaching within 2.5 m inside 3× the true optimum. The ratio columns summarize physically arrived walks with usable optimal-time estimates, including walks outside 3×. The belief optimum uses the persisted snapshot at dispatch and can lag buffered observations. Each N1 stimulus uses the pre-call authority clock sample. Each closed-gate N2 stimulus uses the same geometric sight estimate in both law states. Latency percentiles use qualifying body-segment responses and leave unanswered stimuli in their own column. Reopening arms have no gate-latency stimulus.

| Arm | Arrival within 3× | Belief p50 / p90 | True p50 / p90 | Stalls/10 min / longest s | Latency p50 / p95 ms | Unanswered / stimuli | Known-ground rows/s mean / max | Could not get there |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n1-a-off-body` | 15/15 | 0.874 / 1.097 | 1.051 / 1.122 | 0 / 0 | 118.5 / 1790.85 | 1/15 | 0.168 / 0.172 | 0 |
| `n1-a-on-body` | 15/15 | 0.989 / 1.089 | 1.089 / 1.237 | 0 / 0 | 67 / 1192.85 | 3/15 | 0.165 / 0.171 | 0 |
| `n1-a-off-click` | 15/15 | 0.863 / 1.044 | 1.016 / 1.071 | 0 / 0 | 21.5 / 1799.7 | 1/15 | 0.165 / 0.171 | 0 |
| `n1-a-on-click` | 15/15 | 1.003 / 1.017 | 1.119 / 1.226 | 0 / 0 | 65.5 / 1926.55 | 3/15 | 0.169 / 0.176 | 0 |
| `n1-b-off-body` | 15/15 | 0.86 / 1.017 | 1.028 / 1.06 | 0 / 0 | 277 / 683.7 | 0/15 | 0.167 / 0.175 | 0 |
| `n1-b-on-body` | 15/15 | 0.873 / 0.975 | 1.012 / 1.082 | 0 / 0 | 195 / 580.5 | 0/15 | 0.169 / 0.176 | 0 |
| `n1-b-off-click` | 15/15 | 0.841 / 0.952 | 0.988 / 1.053 | 0 / 0 | 22 / 1850.9 | 0/15 | 0.163 / 0.172 | 0 |
| `n1-b-on-click` | 15/15 | 0.865 / 0.945 | 0.989 / 1.072 | 0 / 0 | 23 / 1867.2 | 0/15 | 0.168 / 0.175 | 0 |
| `n1-c-off-body` | 15/15 | 1.122 / 1.318 | 1.067 / 1.13 | 0 / 0 | 192 / 544 | 0/15 | 0.166 / 0.172 | 0 |
| `n1-c-on-body` | 14/15 | 1.21 / 1.646 | 1.205 / 1.339 | 0 / 0 | 251 / 874.3 | 0/15 | 0.16 / 0.171 | 0 |
| `n1-c-off-click` | 15/15 | 1.101 / 1.339 | 1.078 / 1.122 | 0 / 0 | 215 / 828.2 | 0/15 | 0.162 / 0.167 | 0 |
| `n1-c-on-click` | 14/15 | 1.181 / 2.134 | 1.181 / 2.307 | 0 / 0 | 118 / 670 | 0/15 | 0.158 / 0.17 | 0 |
| `n1-d-off-body` | 15/15 | 0.887 / 0.969 | 1.022 / 1.073 | 0 / 0 | 275 / 485 | 0/15 | 0.165 / 0.17 | 0 |
| `n1-d-on-body` | 15/15 | 1.04 / 1.157 | 1.214 / 1.405 | 0 / 0 | 51 / 394.7 | 0/15 | 0.168 / 0.173 | 0 |
| `n1-d-off-click` | 15/15 | 0.876 / 0.951 | 1.027 / 1.081 | 0 / 0 | 15 / 504.7 | 0/15 | 0.169 / 0.173 | 0 |
| `n1-d-on-click` | 15/15 | 1.009 / 1.057 | 1.156 / 1.245 | 0 / 0 | 105 / 810.2 | 0/15 | 0.166 / 0.172 | 0 |
| `n2-a-off-body` | 5/5 | 1.099 / 1.119 | 1.052 / 1.101 | 0 / 0 | 1880 / 1904.35 | 1/5 | 0.121 / 0.147 | 0 |
| `n2-a-on-body` | 5/5 | 1.2 / 1.232 | 1.176 / 1.2 | 0 / 0 | 42 / 42 | 4/5 | 0.084 / 0.107 | 0 |
| `n2-a-off-click` | 5/5 | 1.118 / 1.148 | 1.098 / 1.115 | 0 / 0 | 1923.5 / 1948.95 | 1/5 | 0.174 / 0.176 | 0 |
| `n2-a-on-click` | 5/5 | 1.067 / 1.153 | 1.141 / 1.191 | 0 / 0 | 349 / 1708.65 | 1/5 | 0.142 / 0.161 | 0 |
| `n2-b-off-body` | 5/5 | 1.111 / 1.127 | 1.09 / 1.116 | 0 / 0 | 1888.5 / 1977.05 | 1/5 | 0.135 / 0.17 | 0 |
| `n2-b-on-body` | 5/5 | 1.175 / 1.184 | 1.133 / 1.156 | 0 / 0 | — / — | 5/5 | 0.139 / 0.158 | 0 |
| `n2-b-off-click` | 5/5 | 1.1 / 1.114 | 1.099 / 1.117 | 0 / 0 | 1923 / 1965.2 | 0/5 | 0.169 / 0.174 | 0 |
| `n2-b-on-click` | 5/5 | 1.205 / 1.379 | 1.246 / 1.344 | 0 / 0 | — / — | 5/5 | 0.092 / 0.105 | 0 |
| `n2-c-off-body` | 5/5 | 1.049 / 1.073 | 1.057 / 1.073 | 0 / 0 | — / — | 0/0 | 0.139 / 0.154 | 0 |
| `n2-c-on-body` | 5/5 | 1.164 / 1.207 | 1.184 / 1.216 | 0 / 0 | — / — | 0/0 | 0.125 / 0.154 | 0 |
| `n2-c-off-click` | 5/5 | 1.103 / 1.124 | 1.109 / 1.128 | 0 / 0 | — / — | 0/0 | 0.115 / 0.141 | 0 |
| `n2-c-on-click` | 5/5 | 1.106 / 1.212 | 1.165 / 1.242 | 0 / 0 | — / — | 0/0 | 0.17 / 0.172 | 0 |

The two walks outside 3× were the first town approach by body 314 and player 319 in the terraced town. They arrived after 253.6 and 251.6 s, respectively, at 3.583× and 3.627× their true optima. The offset-coordinate arms finished 4.26–5.96 m from the actual destination, consistent with following the supplied coordinates.

## Release targets

“Met” for N2-a body latency describes one response out of five. N2-b had no measurable law-on p95. The six law-on N1 arms that missed the true-time target had p50 below the committed lower bound of 1.2. All eight were below the p90 ceiling of 3.0.

| Law-on arm | Arrival | Belief time | True time | Stalls | Latency | Known-ground writes |
| --- | --- | --- | --- | --- | --- | --- |
| `n1-a-on-body` | met | met | missed | met | missed | met |
| `n1-a-on-click` | met | met | missed | met | missed | met |
| `n1-b-on-body` | met | met | missed | met | missed | met |
| `n1-b-on-click` | met | met | missed | met | missed | met |
| `n1-c-on-body` | missed | missed | met | met | missed | met |
| `n1-c-on-click` | missed | missed | missed | met | missed | met |
| `n1-d-on-body` | met | met | met | met | missed | met |
| `n1-d-on-click` | met | met | missed | met | missed | met |
| `n2-a-on-body` | met | met | met | met | met | met |
| `n2-a-on-click` | met | met | met | met | missed | met |
| `n2-b-on-body` | met | met | met | met | unavailable | met |
| `n2-b-on-click` | met | missed | met | met | unavailable | met |
| `n2-c-on-body` | met | met | — | met | — | met |
| `n2-c-on-click` | met | met | — | met | — | met |

## Ground writes and exits

Every arm stayed below 0.2 known-ground rows per subject-second. The highest observed subject rate was 0.176 in each law state. Across 2,524 observed gaps between row timestamps, the minimum gap was 5.900 s, and none was shorter than 5.5 s. The audit includes gaps from the initial subscription snapshot to later updates. The cadence limit applies per exploring character, including when multiple blocks are dirty.

The terminal “could not get there” breakdown was empty in both law states across all scored walks. A retained live warm-up trace contains two instances of `belief_collision_after_replan` for actor 314 in N2-a-on-body. Warm-ups are outside the scored denominators. The archived original failure counts do not identify their terminal planner exits.

## Motion and fuel

The profiling window was 90 seconds per arm. Motion normalization uses the count of retained `tick.motion` spans and the measured tick rate. The retained fraction was 15.4–17.4% of the requested windows. Each pair matched measured population, with variation in resident activity. Six of fourteen pairs exceeded the 2× motion guard.

| Variant / controller | Off people / animals | On people / animals | Sampled motion ms/s off / on | Motion p99 ms off / on | On/off sampled motion |
| --- | ---: | ---: | ---: | ---: | ---: |
| n1-a-body | 282 / 33 | 282 / 33 | 5.29 / 25.84 | 0.411 / 2.576 | 4.88 |
| n1-a-click | 287 / 33 | 287 / 33 | 5.35 / 10.17 | 0.367 / 0.775 | 1.9 |
| n1-b-body | 282 / 33 | 282 / 33 | 4.7 / 28.44 | 0.333 / 2.486 | 6.05 |
| n1-b-click | 287 / 33 | 287 / 33 | 5.7 / 5.99 | 0.53 / 0.446 | 1.05 |
| n1-c-body | 282 / 33 | 282 / 33 | 6.39 / 16.66 | 0.572 / 1.149 | 2.61 |
| n1-c-click | 287 / 33 | 287 / 33 | 6.89 / 5.7 | 0.588 / 0.722 | 0.83 |
| n1-d-body | 282 / 33 | 282 / 33 | 5.95 / 12.04 | 0.52 / 0.854 | 2.02 |
| n1-d-click | 287 / 33 | 287 / 33 | 6.27 / 9.4 | 0.493 / 0.755 | 1.5 |
| n2-a-body | 282 / 33 | 282 / 33 | 3.78 / 3.68 | 0.257 / 0.441 | 0.97 |
| n2-a-click | 287 / 33 | 287 / 33 | 7.67 / 12.3 | 0.619 / 0.892 | 1.6 |
| n2-b-body | 282 / 33 | 282 / 33 | 4.02 / 47.52 | 0.347 / 3.621 | 11.82 |
| n2-b-click | 287 / 33 | 287 / 33 | 7.8 / 2.56 | 1.013 / 0.321 | 0.33 |
| n2-c-body | 282 / 33 | 282 / 33 | 4.55 / 8.12 | 0.41 / 0.895 | 1.78 |
| n2-c-click | 287 / 33 | 287 / 33 | 3.29 / 12.3 | 0.303 / 0.89 | 3.74 |

The fuel fixture replayed both planners on each of the 300 captured dispatch snapshots, using the authority's shared rules and warmed true-map regions. It measures first-leg WASM instructions and includes all resumed slices of that leg. Database access, later legs and live changes during each walk are outside the meter. Values are millions of fuel.

| Live captures | Dispatch pairs | Off p50 / max | On p50 / max | On max slice | Off / on above 20M |
| --- | ---: | ---: | ---: | ---: | ---: |
| N1 | 240 | 2.78 / 5.69 | 2.79 / 8.43 | 5.68 | 0 / 0 |
| N2, closed | 40 | 24.12 / 28.78 | 8.36 / 12.41 | 10.52 | 40 / 0 |
| N2, reopened | 20 | 7.71 / 9.73 | 8.60 / 12.40 | 10.50 | 0 / 0 |

The separate replay of archived order snapshots retained an N1 law-on case at 22.00M. The 20M bound is confirmed for the new first-leg sample alone.

## Evidence and coverage

The source captures, fixture state, raw subscriptions, planner-exit records, normalized reports and fuel replay inputs are under `.local/living/nav-planner/` and `.local/living/verify/core-nav-planner-*`. The archive is `~/slop-evidence/nav-planner-2026-11-19.tar.zst`, with a matching `.sha256`.

Coverage includes N1, all N2 arms, the closed-gate scene and the rules-level hidden-gate pair. Outside coverage are N3 and N4, a live matched-start shortcut or identical-belief pair, later-leg fuel, and the sustained performance contract. The release gate remains unmet because of the terraced-town arrival and ratio misses, response latency, and motion cost. The shipped law defaults to off.
