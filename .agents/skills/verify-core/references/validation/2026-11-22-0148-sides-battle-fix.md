# sides-battle-fix: the sides battle fixture's stances never fall due; the `sides_battle` scene

Branch `sides-battle-fix` on main `ca48edd56`. Laptop (macOS aarch64), the local server `sao-living_spacetimedb_1` (SpacetimeDB 2.14.1, `127.0.0.1:3300`), rustc 1.99.1, `CARGO_TARGET_DIR` `~/.cache/sides-battle-target`, builds through `build-slot` with `BUILD_SLOTS=1`. No mind service, no model calls.

The change: `spawn_battle_sides` writes its `enemy` stance records due `u64::MAX` (never), not 0. Record housekeeping drops every record with `due_ms <= now`, so before the fix the stances were gone within a second and the battle stalled.

`sides_battle` (new; `--seed cullet`, a fresh world each; 60 fighters in 2 sides, 60 s):

| Run | Module | Uses (accepted, aimed) | Fallen by 30 s | Fallen by 60 s | Residents dead | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `core-sbmain-20261122-023818` | main's fixture (the one-line fix reverted in the tree) | 78 (78, 45) | 0 | 0 | 0 of 64 | **FAIL** |
| `core-sbfix-20261122-024035` | the fix | 2,276 (2,276, 1,496) | 4 (first at 5.7 s) | 14 | 0 of 64 | PASS |
| `core-sbfix2-20261122-024223` | the fix | 2,432 (2,432, 1,595) | 6 (first at 18.3 s) | 16 | 0 of 64 | PASS |

- Main's run failed two checks: `the enemy stance records outlive record housekeeping` (none left 3 s after the spawn) and `fighters fall within 30 s`. Its other checks passed: fighters created, two side communities, every fighter a member, every use seen, uses aimed at someone, none at a resident, the fighter's own side or anyone outside the battle, no resident dead.
- Both runs with the fix passed all 11 checks. Every fallen fighter's cause is `killed by a stranger`.
- Launch and doctor passed for all three. All three were cleaned up (databases deleted, module copies removed).
- Cargo: `cargo test -p living-authority --lib` 44 passed; `cargo test -p living-rules` 362 passed, 17 ignored (`.local/sides-battle-fix/cargo-tests.txt`).
- Scene gate: `python3 living/tools/scene_gate_selftest.py` passes its plan checks, including the two new ones (a `lib.rs` diff runs `sides_battle`; an `act.rs` diff does not). It then stops in `check_render_set` (`own-clips.glb without its .clips.json sidecar`), the same on a clean `origin/main` checkout (169 checks ok there, 171 here), so this change did not cause it.

Not covered: the scene inside a real gate run (`just living-merge --scenes`); 3 or 4 sides; the 200-fighter density of the E1b stills (corroborated there by the laptop's attention-E1b run with the records set to never expire by owner SQL: 56–64 fallen at 40 s, 83–92 at 52 s, no resident dead); the other verify-core scenes.

Evidence: `.local/living/verify/core-sbmain-20261122-023818/`, `core-sbfix-20261122-024035/`, `core-sbfix2-20261122-024223/` (each `launch.txt`, `doctor.txt`, `sides_battle.txt`, `sides_battle-results.json`, `sides_battle-summary.json`, `sides_battle-uses.json`, `sides_battle-dead.json`, `sides_battle-spawned.json`, `cleanup.txt`), in the `sides-battle-fix` worktree on the laptop.
