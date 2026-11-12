# Steering locomotion

## Sub-features

- Consecutive walks preserve momentum without a standing row between them.
- Arrival slows before stopping.
- A follower keeps a distance and keeps up.
- Direction input moves, turns and stops a player body.
- Excess movement-input changes are refused.
- Long walks go leg by leg (`living_rules::nav`, [docs/PATHS.md](../../../../docs/PATHS.md)): a route over areas, then regions, then tiles for the next 64 m. The body's path holds one leg, and steering plans the next 16 m before its end. "No path there" means the place cannot be reached at all.
- A deliberate act walking to a place lasts as long as its route (`acts::overdue`). An approach to a creature still gives up after 90 s.
- The `living/viewer/src/sync.rs` tests are all this skill covers of the viewer. Its sync math blends late rows, handles jumps and keeps display time continuous.

## How to get to it (user POV)

Characters follow graph targets or player direction input. Observers extrapolate movement segments. Authority movement lives in `living/authority/src/motion.rs`, shared math in `living/rules/src/steer.rs`, routes in `living/rules/src/nav.rs`, and viewer synchronization in `living/viewer/src/sync.rs:62,178`.

## Driving it with verify_steering.py and Cargo

Run the existing driver through the recorder using [SKILL.md](../SKILL.md). It subscribes to body rows and performs five checks. Keep body updates and calls in `stdb-actions.jsonl`, and speeds, follower distances and input refusals in `steering.txt`. `cargo_checks.py` also runs the three viewer `sync::tests`.

## Driving long walks

- Offline: `cargo test -p living-rules nav::` (a long wall walked round in legs whose tile search stays within its corridor, unreachable and unwalkable goals refused, a shut gate closing the way and opening it again, roads taken where they are faster, routes identical from a cold, a warm and a pre-built cache; since 2026-11-10 ground across water refused at once once warmed, the island walk (264,326)→(904,456) arriving along its kept route where legs searched afresh turned back forever, 40 random reachable island pairs arriving, and a walk ending after 10 legs without headway).
- A walk to a place keeps its area route in the private `walk_route` table between legs (docs/PATHS.md, "A walk keeps its route"): one row per body walking to a place, gone when it arrives. A walk that gets no nearer for 10 legs ends with "you were getting no nearer: the way kept turning back".
- Costs on real terrain: `living/tools/path_budget` (its own workspace) on a `path-world.json` (terrain chunk rows, from and to): `legs` walks to each target leg by leg (expansions, time, length against the plain search's optimum), `clicks` replays click-to-move requests, `cache` counts the whole map's regions and areas. `path_budget/fuel` measures fuel per leg under SpacetimeDB 2.14.1's wasmtime configuration.
- Live, on an island run: `living/tools/walk_times.py --db verify-<run> --residents N --secs S` sends N residents walking to three far settlements each (admin `set_behavior`) and samples every body: walked distance, settlements reached, how many are moving. Run `living/tools/bench.py --db verify-<run>` meanwhile for the tick's cost (its `tick.routes` span is the warm-up). For players, see [verify-player](../../verify-player/features/player-character.md).

## Flight

- Live, on a `stage1-acts` run: `scenes.py flee` holds every graph on `wait`, puts a wolf 6 tiles from a deer and gives the deer the graph `flee` the wolf. It checks that the deer's `steer` row runs from the wolf itself (`goal` 4, `target` the wolf's id), that the distance sampled about every 0.5 s never falls, and that the flight ends about `flee_clear` (a law, 9) tiles farther than it began. A deer told "cornered" is put back on `wait` and the next deer is tried. Before 2026-11-10 the goal ran from a point 9 tiles beyond the deer, so the deer ran at the wolf.

- Since `flee-open` (2026-11-12, [docs/MOVEMENT_MIND.md](../../../../docs/MOVEMENT_MIND.md)) a flight takes open ground (`steer::flee_way`): straight away while that way is open as far as it still has to go, else toward the reachable ground within sight that gains most distance soonest without running past the threat (a small Dijkstra over the tiles within sight, at most 16 m). The same for `flee`, `back_off` and a band backing off. Offline: `cargo test -p living-rules a_flight_looks_for_open_ground` (open field straight away, a wall, an inside corner and a dead-end pocket run with the body's own steering, boxed in cornered; the straight-away rule is stuck in the corner and the pocket). Live: `scenes.py flee_wall` (default seed) finds up to four inside corners with an open side on the map (`wall_spots`), puts a person 5 m from another with the corner straight away, and has it flee: no flight "cornered", each ends at least 6 m farther (a graph's flee step also ends once the threat is out of sight, 11 m by day), none closes on the threat by more than a metre between samples. Evidence: `flee_wall-flights.json` (spot, way, the steer row, the track, what it was told).

## Moving as a law

Since `laws-2` (2026-11-11) a creature's run, flight and step aside (as shares of its walk), its turn rate, the speed it keeps in sharp turns and its separation from others are the script's per-creature `motion(a)` law (docs/WORLD_RULES.md, "Laws"), asked through `common::moves_of`. `scenes.py moves` on a default-seed run: a person walks off (its cruising speed in `body.speed` is its walk), flees a second person with `run: false` (1.15 times that) and by default (a run since `stamina-1`, the `run_share` law times; [breath.md](breath.md)), then turns on the spot to face someone placed behind it (`body.turn` ±6 rad/s). An installed overlay with a flight of 2 and turning at 3 shows both changed; the shipped script is installed again at the end. Evidence: `moves-*.json`.

## Admin placement

Since `fix-place-free` (2026-11-11) the test-support reducers `place_near(id, near)` and `place_at(id, x, y)` (admin only, signatures unchanged) put a body on the nearest free walkable tile: walkable, and no other body standing on it (bodies of the chunks around the point, through the `body.chunk` index), within 6 m (`PLACE_RADIUS` in `living/authority/src/lib.rs`, `Map::nearest_free` in `living/rules/src/map.rs`). `place_near` keeps the exact point 1 m east of the target when that tile qualifies, else takes the nearest free tile centre of ground walkable from the target (once routes are warm); `place_at` takes the nearest free tile's centre. With none in the radius both refuse with `no free walkable tile within 6 m of (x, y)` and the body stays. Before, `place_near` could put a body inside an obstacle (goto and give then failed: "could not get there", "the way is blocked") and `place_at` put two bodies on one tile (nearest walkable within 12 tiles, occupancy ignored).

`scenes.py placement` on a default-seed run: a target beside an obstacle more than 10 m from every body; `place_near` lands on a walkable tile and the body then walks 5 m (`goto`); a second `place_near` takes another tile; two `place_at` requests 1.9 m apart that the old snapping put on one tile (the scene recomputes it, `old_snap`) land on two; a request with no walkable tile within 6 m (deep water or rock, else off the map) is refused. Evidence: `placement-spots.json`, `placement-near-uses.json`, `placement-actions.jsonl`. Run it last on a shared run: its bodies stay, and `open_line` (used by `moves`, `say` and others) does not avoid bodies, so a crowded line can fail `moves`' turn check.

## Movement intents

Since `move-intents` (2026-11-12, docs/COMBAT_MIND.md §3.3) a graph leaf or a one-off act may say how to move relative to a creature: `keep_distance` (`min`/`max`, a band; with neither, the distance it starts at ±1 m), `close_in` (`distance`, default 1), `circle` (`radius`, default the distance it starts at; `side` `left`/`right` as one faces it), `back_off` (`distance`, default 4; from a creature or a place) and `follow` (`distance`, default its reach 2), each with `run` and, for the held ones (`keep_distance`, `circle`, `follow`: `moment` skills, graph only), `qty` seconds (default the `follow_s` law). The grammar is `living_rules::steer::Spacing` (checked in `normalize::spacing` and again in `act::intent_check` for a player's node); the specs are in `skills.rhai` (`keep_distance_spec`…, their speeds from the `motion` law). Steering (`living/authority/src/motion.rs`): `keep_distance` is goal 5 (`GOAL_BAND`, `keep` the near edge, `far` the far one), `circle` goal 6 (`GOAL_ORBIT`, `far` the side), `close_in`/`follow` goal 2, `back_off` goal 4, all with flag 128 (`FLAG_SIGHT`). Each steering update re-aims at the target as the one sight rule (`perception::in_sight`, kept margins) or scent sees it now, and faces it as a held look does (within `look_walk_deg` while walking); unseen, it goes by the last-seen place (`gx`/`gy`) and ends "lost sight of them" once `lost_after_s` (a law, 2 s) has passed since steering found it out of sight (`steer.unseen_ms`). A graph leaf whose target drops out of sight stays under that rule instead of failing at its next evaluation. Speeds are the body's walk, and `run_share` times it with `run: true` (breath drains as for any run); a pursuit that slows near its distance keeps at least the speed its target draws away at (since `fix-pursuit-speed`, 2026-11-12, every pursuit: an approach to strike too, for every controller; before, only the intents).

`scenes.py intents` (default seed, about 3 min; the faster walker of two people holds and follows): `keep_distance` 3–6 m against a walker coming at it (never nearer than 2 m; it backs off over 10 m; stands in the band facing it), re-aiming when the walker goes back the other way (a 2.5–4.5 m band); `close_in` with `run: true` at `run_share` times its own walk, draining breath, ending within its distance; `back_off` to 7 m, then standing facing what it backed from; `follow` 3 m out and back; `circle` 4 m left (within 0.8 m, over half a turn the right way, facing the centre within the walking limit), the centre moved 3 m and followed, then right; a target taken out of sight ends a `keep_distance` after `lost_after_s` with "lost sight of them"; a mind's one-off `close_in` toward someone out of sight, a `circle` of oneself and a band upside down are refused. Evidence: `intents-*.json`.

`scenes.py intents_cost` (`N` holders, default 16, `SECONDS` per window, default 20): the module's profiling on, `tick.motion` span time and `stats.motions` with everyone standing, then half circling a still partner and half holding a band from a partner walking back and forth. Evidence: `intents_cost-cost.json` (and its line in the log).

People walk at their own pace (genes): a body cannot keep away from, or keep up with, a faster one at a walk, as a player cannot; at night (6 m sight) a band past 6 m loses its target. The scene picks the faster person and bands within night sight for that reason.

## Gotchas

- Scenes that `place_at` two bodies on one point (`sight`, `drop`, speech `ways`) now get two neighbouring tiles; all passed on 2026-11-11 (`core-place-20261111-205914*`).
- Pass an explicit `verify-core-*` database. The driver publishes and deletes it itself.
- It uses the admin CLI identity for `join` and `human_move`. Use `verify-player` for the player's own identity.
- A body row is an analytic segment. Its `x` and `y` alone are not the current position.
- The input-limit check changes `skills.rhai` only on its scratch database.
- A long walk is not all built by its first call: until the tick's warm-up has built the map's regions (about 5 s after a module instance loads the 2048 m island), a first leg builds what it touches, up to 635 M fuel across the island. Measure leg costs after the warm-up.
- Trajectories and math do not prove Bevy frame rate or visible smoothness. Use the future UI skill (not built; see `verify`).
