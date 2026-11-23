# sides-mixed-defence: each side of the sides battle fixture mixes block and dodge

Follows [2026-11-22-0148-sides-battle-fix.md](2026-11-22-0148-sides-battle-fix.md). Branch `sides-mixed-defence` on main `9ed12f51d`. Spark (aarch64), a private server `slop-smd-20261122` (SpacetimeDB 2.14.1, `127.0.0.1:3381`, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), rustc 1.99.1, a private `CARGO_TARGET_DIR`, builds through `build-slot`, pinned to CPUs 0-4,10-14. No mind service, no model calls.

The change: `spawn_battle_sides` chose a fighter's side by creation order (`made % sides`) and its defence by id parity (`id % 2 == 0` dodges, else blocks). With consecutive ids one whole side blocked and the other whole side dodged. It now alternates block and dodge by the fighter's index in its own side (`made / sides`), so each side has both, within one. `spawn_battle` (no sides) is unchanged. Found by E4b (`docs/ATTENTION_E4.md` §7.4 on `heed-e4`): with heed off the low-id, blocking side broke 14 of 19; mixed, 4 of 6.

The scene gains one check, `each side mixes block and dodge within one (not one defence per side)`: each fighter's defence is read from its `brain` graph right after the spawn (`sides_battle-defence.json`).

`sides_battle` (`--seed cullet`, a fresh world each; 60 fighters in 2 sides, 60 s):

| Run | Module | Defence by side (block/dodge) | Uses (aimed) | Fallen by 30 s | Fallen by 60 s | Residents dead | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `core-smd-main-175523` | main's fixture (`lib.rs` from `origin/main` in the tree) | A 30/0, B 0/30 | 2,375 (1,554) | 2 | 16 | 0 of 64 | **FAIL** (the new check only; 11 others passed) |
| `core-smd-branch-175817` | the change | A 15/15, B 15/15 | 1,937 (1,241) | 17 | 21 | 0 of 64 | PASS, 12 of 12 |

- Every fallen fighter's cause is `killed by a stranger` in both runs. Launch and cleanup passed for both (databases paused, confirmed and deleted, module copies removed).
- `just living-check` passed on the branch in 1,374 s (authority, mind and viewer, game and its tests, authority tests, viewer wasm, rules tests, script gate; `.local/smd/check.log`). The reducer's signature is unchanged, so the bindings and verify-client `drive.py`'s argument list (`spawn_battle_sides: [0, 2]`) are unaffected.

Not covered: 3 or 4 sides (the index rule gives each side ⌈k/2⌉ dodgers of its k fighters); more replicates of who wins (E4b's §7.4 is the outcome evidence, on `heed-e4`); the scene inside a real gate run; other verify-core scenes (the change is the fixture's one line).

Evidence: `.local/living/verify/core-smd-main-175523/`, `core-smd-branch-175817/` (`launch.txt`, `sides_battle.txt`, `sides_battle-results.json`, `-summary.json`, `-defence.json`, `-uses.json`, `-dead.json`, `-spawned.json`, `cleanup.txt`), in the Spark worktree of `sides-mixed-defence`.
