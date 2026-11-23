# sides-layout-seed: the sides melee on a fixed layout, and its stance worded for minds

Follows [2026-11-22-1700-sides-mixed-defence.md](2026-11-22-1700-sides-mixed-defence.md). Branch `sides-layout-seed`: `origin/sides-mixed-defence` (`9077ff608`, not yet on main) with `origin/main` `5b13f1ba7` merged in (`34e236804`). Spark (aarch64), a private server `slop-layoutseed-20261123` (SpacetimeDB 2.14.1, `127.0.0.1:3591`, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), a private `CARGO_TARGET_DIR`, builds through `build-slot`, pinned to CPUs 0-4,10-14. No model calls (verify-minds used the fake model).

The change:
- A new admin reducer `spawn_battle_sides_layout(n, sides, layout_seed, deal)`: `spawn_battle_sides`' fixture with the places drawn from a splitmix64 stream seeded `layout_seed` (not the reducer's timestamp-seeded draws) and dealt in groups of `sides` (slot `k` of group `j` to side `(k + deal) % sides`). With two sides, deal 1 mirrors deal 0. `spawn_battle_sides` is unchanged: `git diff 34e236804 -- living/authority/src/lib.rs` removes no line.
- The script's `record_text` words a stance of any kind (a `holder` and a `toward` party, a `label`): "your people, Side A, hold Side B as enemy" / "Side B holds your people, Side A, as enemy", the `why` only when the terms carry one. The fixture's `stance` records read "stance: open" before.
- Drivers: `battle_viewers.py --sides N --layout-seed S [--swap | --deal D]`; `det_compare.py prepare --sides N [--layout-seed S --deal D]`; verify-core scene `sides_layout`; verify-minds case `battle-stance`; the scene gate runs `sides_layout` after `sides_battle`.

| Proof | Run | Result |
| --- | --- | --- |
| `sides_battle` (the old fixture, unchanged) | `core-lseed-010129` (Cullet) | PASS 12/12: A 15/15, B 15/15 block/dodge; 1,901 uses (1,218 aimed), 15 fallen by 30 s, 24 by 60 s, 0 of 64 residents dead |
| `sides_layout` (the same world, paused) | `core-lseed-010129` | PASS 12/12: 30 of 30 pairs mirrored (A1 at (538.0523, 742.71405) with deal 0, B1 there with deal 1), same defence on each place, 15/15 per side, seed 1001 deal 0 twice identical, seed 1002 shares no place, 61 fighters refused |
| det_compare, base `34e236804` against the branch, each with its own shipped script (`--scripts`), template staged by the base with `spawn_battle_sides(60, 2)` (default seed) | `.local/sides-layout/det/run1` | identical: 3,600 ticks, 113 tables, 31,152 rows |
| verify-minds `battle-stance` (fake model) | `minds-lseed-014541-battle-stance` | PASS: a consolidation request's dealings read "- your people, Side A, hold Side B as enemy" and "- Side B holds your people, Side A, as enemy", no "stance: open" |
| verify-minds `dealings` (regard wording unchanged) | `minds-lseed-013816-dealings` | PASS |
| verify-client (the reducer inventory; non-admin calls refused) | `client-lseed-20261123-014625` | exit 0; `spawn_battle_sides_layout` "admin only" (HTTP 530) for all four non-admin identities |
| `just living-check` | `.local/sides-layout/check.log` | ok in 2,444 s |
| rules unit test `agreements_and_demands_are_rules_on_records` (the stance wording, with and without `why`) and the install probe (a `stance` record in `check::records()`) | in living-check | pass |

The first two `battle-stance` attempts failed in the driver, not the rules: a held-still fighter is never asked, and on main the fixture's fighters have no mind at all (E5 minded them with heed-e4's `sides_minded` law). The case now uses a minded adult who founds `Side A`, which the fixture takes for its side.

Not covered: 3 or 4 sides with the layout reducer (the deal rotates; only 2 sides were driven); a fighting run of the layout fixture (the scene stays paused; its fighters' graph, spears, memberships and stance records are `spawn_battle_sides`' code, and `sides_battle` runs that fight); `battle_viewers.py` end to end with `--layout-seed` (its arguments and the call it makes were checked offline: the refusals, and `spawn_battle_sides_layout [60, 2, 1001, 1]` for `--swap`); real-mind battles with the new wording (E-series runs need heed-e4's `sides_minded`).

Evidence: `.local/living/verify/core-lseed-010129/` (`sides_battle*`, `sides_layout*`, `sides_layout-seed1001-deal0.json` and the others), `.local/sides-layout/` (`det/`, `check.log`, `minds*.txt`, `client.txt`), in the Spark worktree of `sides-layout-seed`.
