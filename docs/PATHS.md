# Walking routes

Since 2026-11-10 (`path-1`), anyone can walk to any reachable place on the island, including another town: a player's click, a mind's `goto` and a resident's graph go through the same rule. This fixes [soak defect D1](SOAK.md#d1-click-to-move-to-another-town-is-refused-no-path-there) and closes [rule gap 5 of the seeded lives](SEEDED_LIVES.md#knowing-a-way-rules--authority) ("long journeys for anyone without a seeded way").

## What was wrong

Three causes stopped long walks and most short ones. Evidence: the soak's own terrain and its 431 click-to-move outcomes, replayed with [`path_budget`](../living/tools/path_budget/src/main.rs) (`clicks` mode).

1. **The search budget.** `motion::start` called `Map::path` with a budget of 6,000 expansions. A* guided by straight-line distance floods the pocket in front of any obstacle across its way. On the island the obstacles are the towns' building rows (houses are `Wall` tiles in 3-tile bands up to about 90 m long, with streets beside them), rivers, lakes and the rock of the ranges. A route of 55 m that must go round such a row or a pond needed 12,000–384,000 expansions. This was the cause of 255 of the 319 short clicks refused with "no path there" (the replay finds a route for every one). It was also why all 165 clicks on other towns failed.
2. **The unreachable memo.** A refused target is remembered per character and tile for 15 s (`motion::no_path`). A driver whose player stood still against an obstacle sent the same hop again and was refused without a search. This accounts for another 22 refusals: the replay finds a path for them even at 6,000 expansions.
3. **The approach limit for acts.** A deliberate act (`human_act`, a mind's act) gave up after 90 s of approach (`APPROACH_MS`), "you could not get to it in time". At the rules' walking speed (2.6 m/s, 1.4× on roads) that is about 250–330 m. So even a walk with a route stopped after 90 s, short of every settlement except the hamlets nearest Brackenford (Coldwell is 452 m by road, Thornby 757 m). The soak did not see this, because its clicks were refused before they started.

Not a defect: **85 "destination unreachable" refusals** were hops into the sea or a lake, more than 12 m from any walkable tile (80 into water, 5 into rock). The soak driver hopped in straight lines toward a town, sometimes across a bay. `motion::start` takes the nearest walkable tile within 12 m of a click and refuses beyond that. That rule is unchanged.

The remaining 43 refusals start, in the replay, on a blocked tile: the start position is reconstructed from the driver's log and is off by up to a metre, and a few reconstructions fall outside the map. The replay cannot settle them. In the live run below, no click on land was refused.

## The rule

A walk is planned **leg by leg** (`living_rules::nav`, [nav.rs](../living/rules/src/nav.rs)), on three levels, so that no single search covers a whole journey:

- **Regions:** each 16-tile chunk splits into its 4-connected pockets of walkable tiles (a shut gate counts as blocked). A diagonal step in the tile search needs both orthogonal neighbours open, so this is exactly the tile search's connectivity. Regions in side-by-side chunks are linked where their tiles touch across the edge.
- **Areas:** each block of 8 × 8 chunks (128 m) splits into groups of regions joined inside the block. Areas in different blocks are linked where their regions are.
- **A leg:**
  1. A* over areas, from the start's area to the goal's: the whole way, a few hundred nodes across the island.
  2. A* over regions to the end of the first `area_m` (384 m) of that route, only through the route's blocks and their neighbours.
  3. The existing tile search (`Map::path`'s A* with string pulling) to the end of the first `leg_m` (64 m) of the region route, only through those regions' chunks and their neighbours.

  Each stretch's blocks or chunks hold a connected chain from its start to its end, so the lower search cannot fail. Its cost is bounded by the stretch, not by the journey.

**Costs and roads.** A link costs the straight distance between the two ends' representative tiles (the tile nearest the region's centroid, and for an area the region nearest the mean). The cost is divided by the road speed (`road_speed`, 1.4) in proportion to the road on the two ends, so a route takes a road where it saves time. The searches are guided by the straight distance at walking speed, which ignores the roads' speed-up. This is not an admissible estimate when roads are faster. A route can therefore be slightly slower than the fastest. In exchange, the search expanded about 40% fewer nodes (measured with regions only, before areas were added) for the same route lengths. Costs are integers, and ties are broken by cost so far and then by node, so a route is a pure function of the map, the start and the goal.

**Walking it.** `motion::start` plans the first leg and refuses the walk when there is no route ("no path there") or the goal is not walkable. The body's `path` holds only the current leg's corners. When the leg's end is within 16 m (`REPLAN_AHEAD_M`) and it is not the goal, the steering update plans the next leg from where the body is, so a walker never stops between legs. A leg that cannot be planned (a gate shut or a wall built since) ends the walk with "the way is blocked", as a blocked walk did before. Pursuits of a creature and the re-plan of a stuck walker use the same legs.

**Acts that walk.** `acts::overdue` no longer stops an act whose body is walking to a place (its steering goal is a point and it is moving). Such a walk lasts as long as its route, and steering ends it on arrival or when the way is blocked. An act approaching a creature, which can keep moving away, still gives up after `APPROACH_MS` (90 s).

**The region cache.** A chunk's regions and an area's block are worked out when a route first needs them and kept with the cached map (`Map::nav`). They are dropped when a tile or a gate in them changes: `Map::set`, `Map::put_chunk` (which also re-reads a rolled-back transaction's edits) and the new `Map::set_blocked`, which the authority now uses for gates. The tick works out 64 chunks ahead of time each tick (`motion::warm_routes`) until the whole map's are built: the 2048 m island takes 289 ticks, about 5 s after a module instance loads the map. A route never depends on the cache: a fresh map, a warm one and one built ahead of time give the same leg (test `routes_are_deterministic_and_follow_terrain_changes`).

**Connected ground** (2026-11-10). Once the warm-up has built every block's areas, its next slice labels each area with its connected component over the area links (`Map::warm_routes`, `label_components`). A route to ground of another component is refused at once ("no path there") instead of flooding every area up to the search's budget, and `Map::reachable(from, to)` answers the same in O(1) (`None` before the warm-up and between a change and the next slice: any tile or gate change drops the labels, and the next tick labels them again). A click off walkable ground takes the nearest walkable tile within 12 m of the walker's own ground (`Map::nearest_reachable`), not a nearer tile of a far shore. The labels change no route: a refused route was refused before too, after the search ran out. Test `ground_across_water_is_refused_at_once_once_warmed`.

**The search's hash.** The searches key their tables by tile, region and area numbers with a multiplicative hash. An area key keeps its block in the high bits and its area (mostly 0) in the low ones, and the table picks buckets by the hash's low bits, which a product takes from the key's low bits only, so area keys piled into a few buckets. `TileHasher::finish` folds the high half in: 40,000 area-key inserts and lookups took 58 ms before and 0.7 ms after (native release build on the dev-box; test `area_keys_spread_over_hash_buckets`).

## Measurements

### Fuel and time per call

Fuel is WASM instructions, so it does not depend on the machine or its load. It is measured with [`path_budget/fuel`](../living/tools/path_budget/fuel): the planner compiled to `wasm32-unknown-unknown` at the authority's profile, run under wasmtime 39.0.1 configured as SpacetimeDB 2.14.1 runs reducers (Cranelift at `OptLevel::Speed`, fuel and epoch interruption on, as [script_bench's host](../living/tools/script_bench/host/src/main.rs)). The terrain is the soak's own island (`path-world.json` in the soak evidence). Each walk starts at the soak's arrival point (512.5, 174.5) and goes to each settlement, re-planning 16 m before each leg's end, as `motion` does.

| Target (soak names) | Legs | Warm leg fuel, p50 | Max | Most areas / regions / tiles expanded in a leg | Old first step: `Map::path` at 6,000 | Old result |
|---|---:|---:|---:|---|---:|---|
| town #0 (Brackenford) | 2 | 3.0 M | 3.0 M | 1 / 30 / 492 | 2.4 M | path |
| village #4 (Thornby) | 9 | 2.8 M | 18.4 M | 5 / 125 / 749 | 18.9 M | refused |
| town #6 (Kettlebridge) | 15 | 4.8 M | 7.6 M | 9 / 366 / 1,005 | 19.6 M | refused |
| giants #1 (Highshelf) | 22 | 5.8 M | 16.8 M | 89 / 668 / 2,240 | 19.6 M | refused |
| town #7 (Lanternquay) | 33 | 5.1 M | 7.9 M | 178 / 399 / 1,006 | 19.7 M | refused |
| village #3 (Elmwick) | 34 | 4.6 M | 14.2 M | 70 / 366 / 2,067 | 19.6 M | refused |
| small_folk #2 (Fernhollow) | 37 | 5.1 M | 8.6 M | 146 / 569 / 1,350 | 23.2 M | refused |
| village #5 (Reedmoor) | 42 | 5.2 M | 15.1 M | 211 / 458 / 2,067 | 19.7 M | refused |
| **All 194 legs** | | **4.9 M** | **18.4 M** (p99 15.6 M) | | | |

- **A leg costs less than a refusal used to.** Every warm leg, the longest included, takes less fuel than one refused 6,000-expansion search did (18.9–23.2 M). Every click on another town paid that before. The reducer's budget is 120 × 10⁹ fuel; the worst leg is 0.015% of it.
- **Time** in that wasmtime on the Mac (M4 Pro; 1-minute load average 19 from other agents): a warm leg takes 0.20 ms at p50, 0.64 ms at p99 and 0.90 ms at most. A refused 6,000-expansion search took 0.83–1.1 ms.
- **Before the cache is built** (the first seconds of a module instance), the first leg of a walk builds the regions and areas it touches. Cold first legs cost 29 M fuel to Brackenford and 635 M across the island (Reedmoor). The tick's warm-up removes this within about 5 s: 289 slices of 64 chunks, 919 M fuel in all, at most 7.3 M per slice (50 ms in all, at most 0.42 ms a slice). The cold first legs took 1.6 ms to Brackenford and up to 35 ms across the island.
- **Memory:** the whole 2048 m island has 12,861 regions in 16,384 chunks and 634 areas (`path_budget cache`). The measuring module (the map and a copy of its tiles) held 9 MiB with the map loaded and 16 MiB with every region and area built, so the cache and the searches' scratch take about 7 MiB. WASM memory only grows, so that is a high-water mark.

**Route quality** (native, [`path_budget legs`](../living/tools/path_budget/src/main.rs)): the walked length against the best path the plain tile search finds with an unlimited budget. Brackenford 1.006, Thornby 1.028, Kettlebridge 1.019, Highshelf 1.035, Lanternquay 1.024, Elmwick 1.001, Fernhollow 1.052, Reedmoor 1.060. Choosing `area_m`: 256 m made routes up to 11.5% longer, 384 m up to 6%, and 512 m bought little more (5%) for twice the region expansions. One level (regions only, no areas) gave the same lengths, but its warm legs reached 35 M fuel and cold first legs 962 M. Weighting the estimate instead (1.25–2×) was erratic: some routes expanded more nodes, and some came out 16% longer.

**The soak's clicks replayed** (`path_budget clicks`, 431 click-to-move requests with the outcome the soak saw): the 255 budget refusals and the 22 memo refusals all get a route. The 85 clicks into water are refused as before. 43 start on a blocked tile in the reconstruction (above). For the clicks that get a route, the walked length is p50 1.003 and p90 1.022 of the optimum.

### Walks from Brackenford

A scratch island world (`verify-player-path2`, seed `island`, this branch, `scoped` perception) on the worker's own SpacetimeDB 2.14.1 container. [`walk_times.py`](../living/tools/walk_times.py) used 16 fresh player identities, all at once. Each joined at the arrival point, clicked on Brackenford's square (152 m, 44–50 s), then clicked on its own settlement (`human_act` goto, a deliberate act). Times run from the click to the arrival the character experienced ("You did what you had decided: goto → …"). The walked length is summed from `body` samples every 2 s. "Road" is the shortest route along the land's roads between the two squares (`living_rules::ways`, the graph the carriers' stages use), on the same land (seed 7, 2048 m).

| Settlement | Straight | Road | Walked | Time | Walked ÷ road | Time ÷ (road ÷ 2.6 m/s) | Mean speed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Coldwell | 397 m | 452 m | 431 m | 2:20 | 0.95 | 0.81 | 3.07 m/s |
| Ashby | 417 m | 550 m | 549 m | 4:41 | 1.00 | 1.33 | 1.95 m/s |
| Thornby | 569 m | 757 m | 685 m | 3:46 | 0.91 | 0.78 | 3.02 m/s |
| Kettlebridge | 709 m | 888 m | 759 m | 4:25 | 0.85 | 0.78 | 2.86 m/s |
| Saltings | 804 m | 1,006 m | 940 m | 5:55 | 0.93 | 0.92 | 2.65 m/s |
| the North Light | 943 m | 1,145 m | 1,087 m | 6:50 | 0.95 | 0.93 | 2.64 m/s |
| Highshelf | 972 m | 1,795 m | 1,241 m | 7:33 | 0.69 | 0.66 | 2.73 m/s |
| Highfold | 1,020 m | 1,247 m | 1,081 m | 6:54 | 0.87 | 0.86 | 2.61 m/s |
| Lanternquay | 1,388 m | 1,822 m | 1,587 m | 9:20 | 0.87 | 0.80 | 2.83 m/s |
| Sootwood | 1,445 m | 2,128 m | 1,588 m | 8:21 | 0.75 | 0.61 | 3.17 m/s |
| Ferncross | 1,716 m | 2,695 m | 1,841 m | 11:17 | 0.68 | 0.65 | 2.72 m/s |
| Tanglewood | 1,750 m | 3,506 m | 1,928 m | 11:34 | 0.55 | 0.51 | 2.78 m/s |
| Fernhollow | 1,823 m | 3,894 m | 2,042 m | 12:56 | 0.52 | 0.52 | 2.63 m/s |
| Elmwick | 1,827 m | 2,509 m | 1,943 m | 12:49 | 0.77 | 0.80 | 2.52 m/s |
| Lakemead | 2,000 m | 2,871 m | 2,188 m | 13:31 | 0.76 | 0.74 | 2.70 m/s |
| Reedmoor | 2,054 m | 3,115 m | 2,257 m | 14:11 | 0.72 | 0.71 | 2.65 m/s |

- **Every walk arrived.** All 16 ended on the clicked point (0.0 m left), including the 2 km walks to Reedmoor and Lakemead and the walks the soak could not start at all. No walk was refused or gave up.
- **Walks are shorter than the roads.** The routes go cross-country wherever that is shorter, so they walk 0.52–1.00 of the road's length. The long ones gain most: the roads to the small folk and Tanglewood go round the central range (FIRST_WORLD's "the island about twice as far across as it is"), and the routes do not. Against the straight line, the walks are 1.06–1.32 times longer.
- **Speed:** 2.5–3.2 m/s on average, the rules' walk (2.6 m/s) sped up on roads. Ashby's walker was slower: its body's `speed` was 1.70 m/s, its own state, and no stop shows in its track.
- **The expedition** in [FIRST_WORLD](FIRST_WORLD.md#expedition-2026-11-09) measured the game client following the roads: time was the road length over the speed to within 1.5%. Its road lengths are from before the hamlets were placed (town → giants 1,997 m then, 1,795 m now).

**Short clicks** in the same run: one more identity made 40 clicks 30–60 m away in random directions around Brackenford's west side. 38 arrived on the clicked point. 8 of those walked round something on the way, at 1.4–5 times the straight distance (39 m straight and 198 m walked at most): these are the clicks the old 6,000-expansion search refused. The other 2 were refused with "destination unreachable": both were in the sea, 26 and 29 m from the shore (the 12 m rule, unchanged).

### The tick with many walkers

Four arms, one after another, each a fresh island world (seed `island`, 277 people and 34 animals) on the worker's own container `path-stdb` (SpacetimeDB 2.14.1, Docker Desktop on the Mac's M4 Pro, 1-minute load average 3.7–4.5). There were no minds, no subscribers and no players. Each arm measured a 300 s window of [`bench.py`](../living/tools/bench.py), starting 40 s after publishing, so the route warm-up had finished. "150 walking": `walk_times.py --residents 150` gave 150 adult residents a graph of `goto`s to three settlements at least 600 m from home (admin `set_behavior`) 60 s before the window. The base is `origin/main` at `fe6ec66`, built from its own worktree.

| Arm | Ticks/s | Steering updates/s | Tick p50 | p95 | p99 | Max | Over 16.7 ms | `tick.motion` p99 / max | `tick.motion` ms/s | `tick.slots` p99 / max | Walkers moving | Walked in 7 min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base, at rest | 60.0 | 82.7 | 0.83 | 1.55 | 3.02 | 7.23 | 0 of 15,022 | 0.28 / 0.66 | 2.6 | 0.91 / 3.37 | – | – |
| this change, at rest | 60.0 | 84.6 | 0.87 | 1.56 | 1.94 | 3.25 | 0 of 13,694 | 0.31 / 1.87 | 2.6 | 0.96 / 1.94 | – | – |
| **this change, 150 walking** | 60.0 | 149.9 | **0.56** | **1.26** | **1.64** | **3.42** | **0 of 14,689** | **0.85 / 2.11** | **5.5** | 0.70 / 1.26 | **150 of 150** at every sample | **165 km**, 65 settlements reached |
| base, 150 told to walk | 59.9 | 42.1 | 0.67 | 2.95 | **5.00** | **33.4** | **4 of 16,213** | 0.24 / 1.67 | 1.9 | **4.56 / 30.7** | 15, then 0 | 5 m |

Times are in ms. The sample counts are the tick spans the module logged in each window.

- **150 walkers cost the tick little.** Every leg re-plan runs inside `tick.motion`. With 150 people walking cross-country without a break, that span's p99 rose from 0.31 to 0.85 ms (2.1 ms at most), and its work from 2.6 to 5.5 ms a second. The whole tick's p99 was 1.64 ms, under the rest arms'. The walkers' simple graphs replaced their town life, so evaluations cost less (`tick.slots`), which more than paid for the routes. `tick.routes` (the warm-up, done before the window) was 0.012 ms at most.
- **The old search hurt the tick when it failed.** On the base, the same 150 walk orders moved nobody. Each resident's `goto` leaf was refused ("no path there") and tried again at its next evaluations: refused from the memo for 15 s, then searched again, each search 6,000 expansions (about 19 M fuel, 1 ms). The evaluations' span reached 4.56 ms at p99 and 30.7 ms at most, and 4 ticks ran over 16.7 ms. The branch's walking arm ran the same graphs, and its evaluations' p99 was 0.70 ms. The refused searches are the likely difference, but the spans do not separate them.
- **Not measured:** 2,000 characters, players over WebSockets, subscribers. These arms establish only that routing does not hurt the tick at the island's population with half its adults walking.

## Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| A walk starts (`motion::start`, from `human_act`, a mind's act, a graph's `goto`) | the cached map and its regions | `body` (the first leg's corners, as before), `steer` | `body.id`, `steer.id` | `body` subscribers of that chunk (unchanged) | per walk | none: the leg's corners replace the old path, and a leg is shorter than a whole route was |
| The next leg (a steering update 16 m before a leg's end) | the cached map and its regions | the same `body` row write that update made anyway | `body.next_ms` (the due range, unchanged) | as above | about one per 50 m walked | none |
| Warm-up (`motion::warm_routes`, in the tick) | the cached map | — | — | — | 64 chunks a tick until done, once per map load | about 7 MiB of module memory at 2048 m (high-water mark), then flat |
| A tile or gate changes | as before | as before | as before | as before | rare | that chunk's regions and its block's areas are dropped and rebuilt on demand |

No table, column, reducer, view or subscription changed. `body.path` holds fewer corners than before, because only the current leg is planned.

## SpacetimeDB documentation consulted

2026-11-10. The live pages' version selector shows 2.0.0; the server, crates and bindings are pinned at 2.14.1.

- [Reducers](https://spacetimedb.com/docs/functions/reducers/): "Relying on global variables, static variables, or module-level state to persist across reducer calls is undefined behavior"; "SpacetimeDB may run each reducer in a fresh WASM or JS instance"; "Instance memory is not persisted across restarts"; "If you modify global state and then roll back the transaction, the modified value may remain for subsequent transactions"; "SpacetimeDB may re-execute your reducer with the same arguments".
  - **Implication:** the regions follow the map cache's existing pattern ([island authority](ISLAND_AUTHORITY.md#open-risks)). They are a pure cache: a route is computed from the map and never from whether the cache is warm. A fresh instance rebuilds them (or a route builds what it needs, at the cold cost above). They are derived only from the cached map, whose rolled-back edits are re-read by the next transaction through `put_chunk`, which drops the regions it touches. The existing risk remains: two instances running reducers concurrently would each keep their own patches.
- [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/): a busy database skips missed ticks and schedules the next future one. **Implication:** the warm-up is bounded per tick (at most 7.3 M fuel), so it cannot make the tick miss its slot. A skipped tick only delays the warm-up.
- [Performance](https://spacetimedb.com/docs/tables/performance/): prefer indexed lookups and batching. It says nothing about computation inside reducers. **Implication:** none of the planning reads a table: it runs on the map already in module memory. The per-call cost is measured above.
- The per-reducer energy budget comes from the 2.14.1 source, as cited in [floors](FLOORS.md): `FunctionBudget::DEFAULT_BUDGET`, 120 × 10⁹ fuel.

## Limits and what is not covered

- **Roads are preferred only as far as regions show them.** A region's road share is its share of road tiles, and the island's roads are 3–4 tiles wide in a 16-tile chunk. A road through open country therefore speeds a region up by only about 10%. Routes go cross-country where that is shorter, and the tile search inside a stretch is uniform-cost. Walks are often shorter than the road between two places, not longer.
- **The search limits:** each level stops after 40,000 expanded nodes (`RouteSpec::max_nodes`). The island has 634 areas and 12,861 regions. An 8192 m megacity floor has 4,096 blocks; nothing there was measured.
- **A blocked start** (a body standing on a blocked tile, more than one tile into it) has no route. Bodies are kept 0.25 m clear of obstacles, so this needs a wall built or a gate shut where someone stands.
- **The observer's path overlay** (`living/viewer/src/map.rs`, the selected body) draws `body.path`, which is now the current leg. Its end marker is the leg's end, not the destination.
- **A mind's `goto` act** goes through the same `acts::submit` and `motion::start` as a player's `human_act`, and the residents' graph walks above go through `motion::start` too. No run started the real mind service to issue a far `goto` (`verify-minds` was not run).
