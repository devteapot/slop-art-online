# nav-planner: straightening to the farthest cell in line

This record follows [the nav-planner merge](2026-11-19-1501-nav-planner-merge.md), which left `scenes.py nav_belief` (law on) red on the branch and green on main. It covers branch `nav-planner` at 8c5cc724, the fix on top of 8018c2c3. Main was then at 8851982d and merged cleanly.

The scenes ran on a private scratch server, `slop-navmerge-stdb` (`clockworklabs/spacetime:v2.14.1`, 127.0.0.1:3393), so they did not need the battle lock. There was no mind service and there were no model calls. `nav_belief` stays off by default.

## The fix

nav-planner straightened its tile route only `2 × CHUNK` (32) route cells ahead, so a long open or unseen stretch kept a staircase corner. In `nav_belief` the first leg was `[(53.5, 103.5), (53.5, 125.5)]`, 6.54 m off the line.

`Search` now has a third suspended stage after the coarse and corridor frontiers, `Pull` (`living/rules/src/known.rs`). From each anchor it takes the farthest route cell in a straight line over the belief, scanning from the route's end down as main's planner did, and it keeps its place across steering updates. Each `line_open` check is charged to the slice's budget by length, at 16 samples per pop. The cell next to an anchor needs no check. Connected regions, both frontiers, exit reasons and the buffered, paced ground are unchanged.

## Checks

- `cargo test -p living-rules known::` passed 8/8. The new `straightening_reaches_the_farthest_cell_in_line` covers an open diagonal route of more than 32 cells as one straight leg, the same result at one pop per update, and a seen wall leaving only the corners it needs. With the old window reimposed, it fails: `[(39.5, 39.5), (46.5, 46.5)]` against `[(46.5, 46.5)]`.
- `just living-check` passed all eight steps (510 s), with rules at 338 passed and 16 ignored. `living-authority --lib` passed 40/40.
- `core-nm-r6-171241` (world seed) passed `nav_belief` 5/5. The first leg over belief was `[(53.5, 125.5)]`, 0.0 m off, as on main. The land-as-it-is walker turned (12.65 m), and the believer replanned 8 times and arrived. In law-off checks on the same run, `moves` passed 6/6 and `known_ground` 10/10, and `core-nm-r6-171241-steering` passed 5/5.
- `core-nm-gate-r6-171241` (island) passed `closed_gate.py` 4/4.
- `player-gaze-nm-r6-171241` (Cullet) passed `gaze.py` 26/26. The supplementary `ground_near.py` passed 4/4: under daytime Near the farthest marked cell was 16.3 m, and under Middle 25.9 m.
- Every `doctor` after a scene showed ticks advancing, and no orphan guard paused a run.

## First-leg fuel

nav-planner's Wasmtime harness (`living/tools/path_budget/fuel`, `pb-host --arena`) replayed the 280 archived order snapshots from `~/slop-evidence/nav-planner-2026-11-19.tar.zst` (`baseline-optimized`) against that archive's own fuel lines. Values are millions of fuel.

| Snapshots | On p50 / max total, before → after | Largest slice, before → after | Most slices, before → after |
| --- | ---: | ---: | ---: |
| N1 (240) | 2.92 / 22.00 → 4.39 / 22.20 | 5.47 → 5.47 | 6 → 7 |
| N2 (40) | 8.07 / 12.41 → 9.37 / 13.69 | 10.49 → 10.49 | 4 → 5 |

144 first legs have fewer corners. The off (map) planner's fuel was identical on 272 of 280 snapshots; the other 8 differ by under 0.1% with the same results, which fits main's `map.rs` cover changes.

## known_ground on main

On current main (8851982d), the updated scene needed one more change: the "5 a look" rate now counts only cells new since placement. Resident `r` had 65 cells round its new spot from before, which main had already persisted. With that change, the scene passed 10/10 on main (`core-nm-kg2-main-173223`) and on the branch (`core-nm-kg2-branch-172931`). Main's first run (`core-nm-mainkg-172624`, 9/10) is kept in the evidence.

## Not covered

- The live N1/N2 arenas were not rerun, so motion ms/s and latency are unmeasured; fuel covers planner instructions only.
- No crowd, chase or scale run, and no SDK probe for gaze.
- Evidence is in `.local/living/verify/{core-nm-r6-171241,core-nm-r6-171241-steering,core-nm-gate-r6-171241,player-gaze-nm-r6-171241,core-nm-mainkg-172624,core-nm-kg2-branch-172931,core-nm-kg2-main-173223}`, with fuel lines in `.local/navmerge/fuel/after/`. All of it is archived in `~/slop-evidence/nav-planner-straighten-20261119.tar.zst`.
