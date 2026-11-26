# seen-structures-remains: exact gap-bridging, remains-only cap, and compaction rate-limiting

Branch `seen-structures-remains` from `origin/main` (`18564737a`), Spark (`aarch64`), private SpacetimeDB 2.14.1 containers (`slop-retfix-20261126` on `:3621`, `slop-retfix-grow-20261126` on `:3625`), builds via `~/slop-mq/build-slot` pinned to CPUs `0-4,10-14`, launches under `trial-activity.lock`. No paid model calls.

**SpacetimeDB 2.14.1 docs & source check:** Consulted [Tables](https://spacetimedb.com/docs/tables/), [Indexes](https://spacetimedb.com/docs/tables/indexes/), [Performance](https://spacetimedb.com/docs/tables/performance/), and [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) against pinned `spacetimedb = "=2.14.1"`. No table, column, index, view, or visibility changed (`SeenStructures` schema untouched).

**Change:** In `living/authority/src/seen_structures.rs`, `compact_live` runs at `> COMPACT_AFTER` (64) pairs and performs exact gap-bridging across dead/other-block/skip gaps where no unseen live structure lies between consecutive seen live structures. When interleaved live remains still exceed `MAX_PAIRS` (128, 2 KiB of `ranges`), oldest remains-only intervals are trimmed to `TRIM_TO` (96) while protecting every interval holding a permanent structure. `NEXT_COMPACT` (`BTreeMap`, no `RandomState`) rate-limits 64-chunk compaction walks above `COMPACT_AFTER` to at most once per `COMPACT_STEP` (16) new pairs and is cleared in `act::forget_dead` (`seen_structures::forget`). Empty rows after compaction are deleted.

| Check | Result |
|---|---|
| `just living-check` | ok in 100 s (`authority` 37 s, `authority-tests` 61 s: 63/63 incl. 3 new `seen_structures::tests`; other 6 steps stamped after full pass in 1,111 s) |
| `verify-core`: `seen_remains`, `notice_inplace`, `notice_delta` (`core-ss2-w-20261127-002158`) | pass (`notice_inplace` 0 diff; `notice_delta` 0 diff) |
| `verify-core`: `remains` (`core-ss2-rem-20261127-002158`) | pass (10/10) |
| `verify-core`: `seen_remains_gaze` (`core-ss2-cul-20261127-002158`) | pass (7/7) |
| `det_compare` vs `main` (`ss2-cullet`, Cullet 200 + 16 players, 1,800 ticks) | **identical** (`ticks_differ: 0`, 113 tables, 45,909 rows) |
| `det_compare` self-control (`ss2-remains-self`, `--remains 1000`, 1,800 ticks) | **identical** (`ticks_differ: 0`, 113 tables, 57,879 rows) |
| `det_compare` vs `main` (`ss2-remains`, `--remains 1000`, 1,800 ticks) | 111/113 tables identical; 6/183 `seen_structures` rows capped and 8/14,490 `experience` counted-remains lines (same row count/timestamps, 3 walkers) recounted trimmed stranger remains; 0 divergence in combat/deliberations/decisions |
| Growth (3-min Cullet fragmented-remains battle, per-min `/v1/metrics`) | `main`: resident max pairs `53 → 131 → 206 → 281` (bytes `65 → 107 → 112 → 93 KiB`, 1,763 B/row at min 3); branch: max pairs `53 → 124 → 119 → 113` (capped ≤ 128, bytes `65 → 105 → 98 → 84 KiB`) |

**Evidence archive:** `~/slop-evidence/seen-structures-remains-20261126.tar.zst` (+ `.sha256`).

**Not covered:** 30-min Gate 216 / 8-hour X925 cadence or sustained RSS measurements; mind/LLM/Neo4j/client-UI surfaces (no schema or subscription change).
