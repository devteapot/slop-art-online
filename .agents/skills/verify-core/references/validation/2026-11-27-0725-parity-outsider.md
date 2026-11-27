# outsider_parity: graph outsider/throng and heed candidate parity, off by default (branch `parity-outsider`)

Branch `parity-outsider` from `origin/main` (`82783e531`). Server: private `slop-parity-p1-stdb` (SpacetimeDB `v2.14.1`).

**Targeted maintenance pass** (`verify-core`, scoped to the change). Shape changes on this surface: world law `outsider_parity` (default `false`), new scene `outsider` in `scripts/scenes.py`, documented in `features/README.md` and `features/graphs.md`. No tables, views, reducers, or subscriptions changed.

| Run | Seed / Workload | Scenes / Checks | Result |
|---|---|---|---|
| `just living-check` | workspace | all 8 steps (incl. `outsider_parity_is_the_world_s_law`, `outsider_parity_requires_known_or_visible_affiliation`; 64 authority lib tests) | PASS |
| `det-outsider-cullet200` | Cullet 200 fighters + 16 players (law OFF vs `origin/main`) | 1,800 ticks, 113 tables, 46,624 rows | `identical: true` (0 ticks differ) |
| `det-outsider-cullet-guards` | Cullet town guards using `outsider` + 6 outsiders (law OFF vs `origin/main`) | 1,800 ticks, 113 tables, 13,520 rows | `identical: true` (0 ticks differ) |
| `outsider-on-vs-off` | Cullet town guards (3 unknown strangers + 1 introduced outsider) & `spawn_skirmish` (12 fighters) | OFF vs ON | Town OFF: 4 threats (3/3 unknown + known), 0 refusals; Town ON: 1 threat (0/3 unknown, 1/1 known, 3 guards wait), 0 refusals. Battle OFF: 237 combat skill uses, 2 deaths; Battle ON: 0 uses, 0 deaths |
| `core-parity-outsider-20261127-071523` | default (`world`) | `outsider` (6/6), `stranger_filter` (9/9), `relation_fight` (12/12), `heed` (18/18), `refusal` (4/4), `seize` (6/6), `sight` (6/6) | ALL PASS |
| `core-parity-island-20261127-072244` | `island` | `skirmish` (8/8) | PASS |

**Not covered:** the remaining scenes of the map; `living-mind` prompt changes (owned by `parity-prompts`); long-horizon scale runs. Evidence archived to `~/slop-evidence/parity-phase1-20261127.tar.zst`.
