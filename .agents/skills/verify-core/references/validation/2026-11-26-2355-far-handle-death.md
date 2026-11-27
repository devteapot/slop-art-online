# far-handle-death: delete dead observer's far_handle rows in act::forget_dead

Branch `far-handle-death` from `origin/main` (`18564737a`), Spark (`aarch64`), private SpacetimeDB 2.14.1 containers (`slop-retfix-20261126` on `:3621`, `slop-retfix-grow-20261126` on `:3625`), builds via `~/slop-mq/build-slot` pinned to CPUs `0-4,10-14`, launches under `trial-activity.lock`. No paid model calls.

**SpacetimeDB 2.14.1 docs & source check:** Consulted [Tables](https://spacetimedb.com/docs/tables/), [Indexes](https://spacetimedb.com/docs/tables/indexes/), and [Performance](https://spacetimedb.com/docs/tables/performance/), verified against `spacetimedb-2.14.1/src/table.rs:1426-1446` (`RangedIndex::delete` dispatches directly to `delete_by_index_scan_point_bsatn` in one host syscall). `FarHandle` already has `#[index(btree)] pub observer: u32` (`living/authority/src/tables.rs:1004-1005`), so no column, index, table, view, or visibility changed.

**Change:** Added `ctx.db.far_handle().observer().delete(id);` in `act::forget_dead` (`living/authority/src/act.rs:2656`) and documented it on `FarHandle` (`living/authority/src/tables.rs:996`).

| Check | Result |
|---|---|
| `just living-check` | ok in 181 s (`authority` 46 s, `authority-tests` 134 s: 59/59; unchanged steps stamped) |
| `verify-core`: `notice_inplace`, `notice_delta` (`core-fh-w-20261126-221958`) | pass (`notice_inplace` 12,390 checked / 0 diff; `notice_delta` 28,081 checked / 0 diff) |
| `verify-core`: `remains` (`core-fh-rem-20261126-221958`) | pass (10/10) |
| `verify-core`: `seen_remains_gaze` + direct `far_handle` death check (`core-fh-cul-20261126-221958`) | pass (7/7; killed observer #25 dropped 8→0 `far_handle` rows while living observer #27 stayed 7→7; 0 dead-observer rows leaked) |
| `det_compare` vs `main` (`fh-cullet`, Cullet 200 + 16 players, 1,800 ticks) | 111/113 tables identical across all 1,800 ticks; first diff tick 1250 when first observer with `far_handle` dies (`far_handle` 2,370→2,305, −65 dead-observer rows); `experience` identical row count (10,266) and content, differing only by `det.rs`/`det_compare.py` `far_handle` rank shift |
| `det_compare` self-control (`fh-self`, Cullet 200 + 16 players, 1,800 ticks) | **identical** (`ticks_differ: 0`, 113 tables, 45,844 rows) |
| `det_compare` vs `main` (`fh-remains`, `--remains 1000`, 1,800 ticks) | **identical** (`ticks_differ: 0`, 113 tables, 57,879 rows) |
| Growth (4-min Cullet battle, ~341 deaths, per-min `/v1/metrics`) | `main`: `far_handle` rows `0 → 2,643 → 3,106 → 3,154 → 3,155` (2,963 dead-observer rows at min 4, 130,944 B); branch: `3 → 2,285 → 2,038 → 1,344 → 832` (0 dead-observer rows at min 4, bounded to living observers) |

**Evidence archive:** `~/slop-evidence/far-handle-death-20261126.tar.zst` (+ `.sha256`).

**Not covered:** 30-min Gate 216 / 8-hour X925 cadence or sustained RSS measurements; mind/LLM/Neo4j/client-UI surfaces (no schema or subscription change).
