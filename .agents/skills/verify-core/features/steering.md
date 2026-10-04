# Steering locomotion

## Sub-features

- Consecutive walks preserve momentum without a standing row between them.
- Arrival slows before stopping.
- A follower keeps a distance and keeps up.
- Direction input moves, turns and stops a player body.
- Excess movement-input changes are refused.
- The `living/viewer/src/sync.rs` tests are all this skill covers of the viewer. Its sync math blends late rows, handles jumps and keeps display time continuous.

## How to get to it (user POV)

Characters follow graph targets or player direction input. Observers extrapolate movement segments. Authority movement lives in `living/authority/src/motion.rs`, shared math in `living/rules/src/steer.rs`, and viewer synchronization in `living/viewer/src/sync.rs:62,178`.

## Driving it with verify_steering.py and Cargo

Run the existing driver through the recorder using [SKILL.md](../SKILL.md). It subscribes to body rows and performs five checks. Keep body updates and calls in `stdb-actions.jsonl`, and speeds, follower distances and input refusals in `steering.txt`. `cargo_checks.py` also runs the three viewer `sync::tests`.

## Gotchas

- Pass an explicit `verify-core-*` database. The driver publishes and deletes it itself.
- It uses the admin CLI identity for `join` and `human_move`. Use `verify-player` for the player's own identity.
- A body row is an analytic segment. Its `x` and `y` alone are not the current position.
- The input-limit check changes `skills.rhai` only on its scratch database.
- Trajectories and math do not prove Bevy frame rate or visible smoothness. Use the future UI skill (not built; see `verify`).
