# nav-planner merged with main (gaze)

This record follows [nav-planner](2026-11-19-0040-nav-planner.md) and [its arenas](2026-11-19-0408-nav-planner-arenas.md). It covers `nav-planner` (2ef3b238) merged with `origin/main` 46431422 (gaze, cover sight, camera rotation) as merge commit 90c82d84, plus the scene fix below. The work ran on the Spark against `slop-trials-stdb` (SpacetimeDB 2.14.1, :3320). Every scene held `~/slop-mq/battle.lock`. There was no mind service and there were no model calls. `nav_belief` stays off by default.

## The merge

The only textual conflict was the test map helper in `living/rules/src/known.rs`. nav-planner's multi-line `Map` literal now carries main's new `cover: None`. `living/authority/src/known.rs` merged cleanly with both intents:

- Gaze's `ground_radius` is main's code unchanged. With `gaze_on`, the applied band's ground radius is capped by `ground_sight_m`. Without it, the old day/night inference applies.
- nav-planner's `mark` takes that radius. It buffers cells, which the planner reads at once, and persists one dirty block per actor every 5.5 s. The ground look cadence (`NOTICE_MS` in `brain.rs`) is unchanged on both sides.

No table, reducer or view changed, so the bindings were not regenerated.

## Checks

- Cargo: `living-rules` passed 337 tests with 16 ignored. The belief suite passed 7/7, and gaze's `gaze_bands_change_light_reach_field_and_ground_in_both_worlds`, `gaze_zoom_has_boundary_hysteresis` and `gaze_ceiling_applies_to_glow_and_keep` passed. `living-authority --lib` passed 40/40. `just living-check` passed all eight steps in 500 s, with game tests at 139 passed and 1 ignored.
- `core-nm-100337` (world seed, law off): `moves` passed 6/6. `verify_steering.py` passed 5/5 on `core-nm-100337-steering`, which published this run's module.
- `core-nm-gate-100337` (island): `closed_gate.py` passed 4/4. That covers both warm-ups, the gate physically shut, stale open memory at dispatch, and arrival.
- `player-gaze-nm-153601` (Cullet): `gaze.py` passed 26 checks, including "full-day Near gets scaled ground entitlement" (14.4 m). It ran without the SDK probe.
- `player-gaze-nm-r4-155139` (Cullet): `.local/navmerge/ground_near.py` is a supplementary driver archived with the evidence. It passed 4/4 on the persisted `known_ground` rows of a joined player's character standing still at (837.5, 457.5). Under daytime Near (ground 14.4, sight 28.8), the farthest marked cell centre was 16.1 m, with none past 17.4 m. Middle then reached 25.9 m. The rows went at death. The old inference would have taken Near's shorter sight for night and marked out to 24 m.
- The orphan guard paused no run. Every `doctor` before and after a scene showed ticks advancing.

## known_ground scene fixed

`scenes.py known_ground` failed on the merge with "nothing 30–40 m off in the open is marked". On pre-merge nav-planner (`core-nmb-2ef3-152739`) it failed with "open ground within 20 m is marked" (77 cells missing). On main 46431422 (`core-nmb-4643-152739`) it passed 10/10.

The cause is the scene, not the merge. It read rows 7 s after placing a resident, which assumed the old write-every-dirty-block-at-5-s flush. Under the paced queue, a newly seen block waits behind the resident's older dirty blocks. In `core-nm-kg-153601`, the first row (5.3 s) was the resident's pre-placement block. The spot's block landed at 11.7 s, after which every cell within 20 m was marked and none 30–40 m off.

The scene now gives its residents a wait graph and reads back each resident's earlier ground first. It then polls until the rows hold and settle (`known_settled`). The far check counts only cells marked at the spot. On the merge (`core-nm-r4-155139`) it passed 10/10, with the capped counts growing 5 → 35 → 65 → 95 at the write interval and 135 cells once uncapped.

## Not fixed: nav_belief (law on)

`scenes.py nav_belief` fails the same way on pre-merge nav-planner and on the merge (`core-nm-100337`, `core-nm-r4-155139`). It passes on main. The failing check is "over belief, the first leg goes straight on into the unseen (within 2 m of the line before the obstacle)". nav-planner's first leg is `[(53.5, 103.5), (53.5, 125.5)]`, 6.54 m off the line. Main's is `[(53.5, 125.5)]`, 0.0 m off. The other checks hold: the land-as-it-is walker turns (12.65 m), and the believer replans and arrives.

The cause is nav-planner's string pull. In `Search::advance`, it looks at most `2 × CHUNK` route cells ahead (`living/rules/src/known.rs`). Main pulled to the farthest open cell, so nav-planner keeps a staircase corner in open or unknown ground. This is law-on behaviour and was left as nav-planner shipped it.

## Not covered

- The updated `known_ground` scene was not rerun on main.
- No SDK probe ran for gaze. There was no full verify-core baseline, no crowd, chase or scale run, and no laptop camera wiring.
- Raw evidence is in `.local/living/verify/{core-nm-100337,core-nm-100337-steering,core-nm-gate-100337,player-gaze-nm-153601,player-gaze-nm-r4-155139,core-nm-r4-155139,core-nm-kg-153601,core-nmb-2ef3-152739,core-nmb-4643-152739}`, with logs in `.local/navmerge/`. Both are archived in `~/slop-evidence/nav-planner-merge-20261119.tar.zst`.
