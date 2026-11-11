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

## Moving as a law

Since `laws-2` (2026-11-11) a creature's run, flight and step aside (as shares of its walk), its turn rate, the speed it keeps in sharp turns and its separation from others are the script's per-creature `motion(a)` law (docs/WORLD_RULES.md, "Laws"), asked through `common::moves_of`. `scenes.py moves` on a default-seed run: a person walks off (its cruising speed in `body.speed` is its walk), flees a second person (1.15 times that), then turns on the spot to face someone placed behind it (`body.turn` ±6 rad/s). An installed overlay with a flight of 2 and turning at 3 shows both changed; the shipped script is installed again at the end. Evidence: `moves-*.json`.

## Gotchas

- Pass an explicit `verify-core-*` database. The driver publishes and deletes it itself.
- It uses the admin CLI identity for `join` and `human_move`. Use `verify-player` for the player's own identity.
- A body row is an analytic segment. Its `x` and `y` alone are not the current position.
- The input-limit check changes `skills.rhai` only on its scratch database.
- A long walk is not all built by its first call: until the tick's warm-up has built the map's regions (about 5 s after a module instance loads the 2048 m island), a first leg builds what it touches, up to 635 M fuel across the island. Measure leg costs after the warm-up.
- Trajectories and math do not prove Bevy frame rate or visible smoothness. Use the future UI skill (not built; see `verify`).
