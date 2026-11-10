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

- Offline: `cargo test -p living-rules nav::` (a long wall walked round in legs whose tile search stays within its corridor, unreachable and unwalkable goals refused, a shut gate closing the way and opening it again, roads taken where they are faster, routes identical from a cold, a warm and a pre-built cache).
- Costs on real terrain: `living/tools/path_budget` (its own workspace) on a `path-world.json` (terrain chunk rows, from and to): `legs` walks to each target leg by leg (expansions, time, length against the plain search's optimum), `clicks` replays click-to-move requests, `cache` counts the whole map's regions and areas. `path_budget/fuel` measures fuel per leg under SpacetimeDB 2.14.1's wasmtime configuration.
- Live, on an island run: `living/tools/walk_times.py --db verify-<run> --residents N --secs S` sends N residents walking to three far settlements each (admin `set_behavior`) and samples every body: walked distance, settlements reached, how many are moving. Run `living/tools/bench.py --db verify-<run>` meanwhile for the tick's cost (its `tick.routes` span is the warm-up). For players, see [verify-player](../../verify-player/features/player-character.md).

## Gotchas

- Pass an explicit `verify-core-*` database. The driver publishes and deletes it itself.
- It uses the admin CLI identity for `join` and `human_move`. Use `verify-player` for the player's own identity.
- A body row is an analytic segment. Its `x` and `y` alone are not the current position.
- The input-limit check changes `skills.rhai` only on its scratch database.
- A long walk is not all built by its first call: until the tick's warm-up has built the map's regions (about 5 s after a module instance loads the 2048 m island), a first leg builds what it touches, up to 635 M fuel across the island. Measure leg costs after the warm-up.
- Trajectories and math do not prove Bevy frame rate or visible smoothness. Use the future UI skill (not built; see `verify`).
