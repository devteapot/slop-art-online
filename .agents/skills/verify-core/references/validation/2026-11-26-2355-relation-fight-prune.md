# relation-fight-prune: index relation_fight.other and delete on retire

Branch `relation-fight-prune` from `origin/main` (`18564737a`), Spark (`aarch64`), private SpacetimeDB 2.14.1 containers (`slop-retfix-20261126` on `:3621`, `slop-retfix-grow-20261126` on `:3625`), builds via `~/slop-mq/build-slot` pinned to CPUs `0-4,10-14`, launches under `trial-activity.lock`. No paid model calls.

**SpacetimeDB 2.14.1 docs & source check:** Consulted [Tables](https://spacetimedb.com/docs/tables/), [Indexes](https://spacetimedb.com/docs/tables/indexes/), [Performance](https://spacetimedb.com/docs/tables/performance/), and [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/), verified against `spacetimedb-2.14.1/src/table.rs:1426-1455` (`RangedIndex::delete` calls `delete_by_index_scan_point_bsatn` / `delete_by_index_scan_range_bsatn` directly in one host syscall). Adding `#[index(btree)]` on `RelationFight.other` is a safe automatic migration without column append or visibility change; bindings regenerated via `LIVING_GENERATE_CMD="living/tools/generate_in_container.sh slop-retfix-20261126" just living-generate` (added `RelationFightIxCols.other`).

**Change:** Added `#[index(btree)]` on `RelationFight.other` (`living/authority/src/tables.rs`) and replaced the `relation_fight` cleanup in `act::retire` (`living/authority/src/act.rs`) with two indexed deletes: `ctx.db.relation_fight().by_pair().delete(id)` and `ctx.db.relation_fight().other().delete(id)`. Mind-side `Index` lookup covered in `verify-minds` record; privacy covered in `verify-client` record.

| Check | Result |
|---|---|
| `just living-check` | ok (all 8 steps; authority, mind+viewer, game, game-tests, authority-tests, viewer-wasm, rules-tests, script-gate) |
| `verify-core`: `relation_fight`, `notice_inplace`, `notice_delta`, direct prune check (`core-rf-w-20261126-225404`) | pass (`relation_fight` all stages pass; dead `other` rows 2→0 while living target kept; dead `actor` rows 1→0) |
| `verify-core`: `remains` (`core-rf-rem2-20261126-230823`) | pass 10/10 (first run `core-rf-rem-20261126-225404` hit a stochastic wander-heading flake 8/12, retained in archive) |
| `verify-core`: `seen_remains_gaze` (`core-rf-cul-20261126-230823`) | pass 7/7 |
| `det_compare` vs `main` (`rf-cullet`, Cullet 200 + 16 players, 1,800 ticks) | **identical** (`ticks_differ: 0`, 113 tables, 45,909 rows) |
| `det_compare` vs `main` (`rf-remains`, `--remains 1000`, 1,800 ticks) | **identical** (`ticks_differ: 0`, 113 tables, 57,879 rows) |
| Growth (3-min Cullet battle, ~245 deaths, 10 residents calling `mind_fight`, per-min `/v1/metrics`) | `main`: `relation_fight` rows `120 → 128 → 188 → 208` (135 dead-target rows at min 3); branch: `120 → 101 → 100 → 74` (0 dead-target rows, 0 dead-actor rows, 65,472 B flat) |

**Evidence archive:** `~/slop-evidence/relation-fight-prune-20261126.tar.zst` (+ `.sha256`).

**Not covered:** 30-min Gate 216 / 8-hour X925 cadence or sustained RSS measurements; Neo4j/paid-model trials.
