# Bounded active-data retention for the living core

Status: **design note, 2026-11-26** (target architecture; nothing in this note is implemented yet beyond the `growth-fix` / `growth-fix-2` / `mind-sex-seen-keyed` baseline explicitly marked **Current**).

## Summary

The [performance contract](PERFORMANCE_CONTRACT.md) locks a sustained target of **2,000 simultaneously active characters** (including a **200-character local battle**) for **8 hours** within a **16 vCPU / 64 GB RAM** backend budget, with an immediate gate of **216 characters for 30 minutes**. Active memory must reach a bounded operating range without restarting services or silently deleting historical evidence ([AGENTS.md](../AGENTS.md), [AUDIT_AND_EXPERIMENTS.md](AUDIT_AND_EXPERIMENTS.md)).

The latest 21-minute interrupted Spark X925 relay run (`gate216-clean-remeasure`, commit `b324fb443`, [GATE216_GROWTH.md](GATE216_GROWTH.md) §9, archived in `~/slop-evidence/gate216-clean-remeasure-20261126.tar.zst`) ran Cullet with 100 scripted human fighters (~2 deaths/s, 3 s rejoin), 116 walkers, 64 seeded AI residents, and both `growth-fix` (`62fccc74b`) and `growth-fix-2` (`55c271265`) applied. Over 20–21 minutes, server RSS grew **824.3 → 973.6 MiB (+149.3 MiB)**, `jemalloc_allocated_bytes` grew **317.2 → 443.8 MiB (+126.6 MiB)**, and total `spacetime_table_size_bytes` grew **55.9 → 103.4 MiB (+47.4 MiB)** — the remaining ~79 MiB of jemalloc growth is B-tree index structures and allocator overhead. In the earlier 30-minute disturbed relay runs ([GATE216_GROWTH.md](GATE216_GROWTH.md) §8), server RSS grew **+155 to +198 MiB** while server cgroup memory (RSS + Linux page cache for WAL/commitlog writes) grew **+2.2 to +2.5 GiB (~75–85 MiB/min)**.

Per-minute inspection of every non-system table in `relay-1.table-rows.csv` and `relay-1.mem.jsonl` shows **four distinct growth classes** that are either unbounded today or bounded at constants too large for 2,000 characters over 8 hours:

1. **Per-observer familiarity/body-memory tables whose caps are sized for the pre-`seen_structures` era:** `familiar` (5.5k → 92.3k rows, +4,344/min) and `sex_seen` (5.3k → 92.0k rows, +4,336/min) track each other 1:1. `growth-fix-2` tied `sex_seen` to remains expiry (96 real min in Cullet; 240 real min in default `skills.rhai`) and `prune_familiar` (`FAMILIAR_LIMIT = 2,048`), so ~59 surviving residents can still accumulate ~121k rows each table before eviction begins — and 2,000 minded characters would reach **4.1M rows per table** (~1.2+ GiB with indexes).
2. **Tables intentionally kept unbounded for dead characters:** `skill_use` (2.6k → 58.4k rows, +2,791/min, +15.1 MiB raw), `character` (295 → 2,699, +120/min, 6 B-tree indexes), `sex` (295 → 2,699, +120/min), plus **`thought`, `persona`, and `background`** (0 growth in the no-mind Gate 216 fixture, but up to 60 × 16 KB `thought` rows per dead person in real minded worlds).
3. **Remains-driven row and blob growth:** `structure` (156 → 2,557, +120/min) and `rot` (28 → 2,429, +120/min) grow for the full `remains_h` window, and **`seen_structures`** stayed flat in row count (~231 rows) while growing **13× in bytes (63.9 → 847.0 KiB, +38 KiB/min)** because fragmented ID ranges over live remains defeat `COMPACT_AFTER = 64` and trigger 64-chunk walks on every subsequent look.
4. **Cross-reference leaks on death and high per-actor buffers:** `acquaintance` (0 → 295, +14.7/min via `remember_member` with no dead-target cleanup), `relation_fight` (454 → 831–977, dead `other` rows never deleted), `far_handle` (2,112 → 2,887, **missing from `act::forget_dead` entirely**), `experience` (15.0k → 37.2k rows, **32.2 MiB**, ~878 B/row; `WINDOW = 400` reaches ~950 MiB at 2,000 living characters), and `line_seen` + `experience_copy` (~7.0k rows / ~6.2 MiB each for 216 active players, duplicating `Experience` twice and leaking permanently for players who die and never rejoin).

### Overview of per-table recommendations

| Table | Current 21-min growth (`b324fb443`) | Current retention | Target retention rule | Target 2,000-char / 8 h active bound | Priority |
|---|---:|---|---|---:|---|
| `familiar` | 5.5k → 92.3k (+4,344/min; 4.3 MiB raw) | `FAMILIAR_LIMIT = 2,048`/actor; `forget_dead` on `actor` only | Cap strangers at 128/actor (`FAMILIAR_LIMIT = 256`), index `thing`, delete `FAM_CREATURE \| dead` at `expire_remains` | ≤ 512k rows (~45 MiB incl. indexes) | **P1 (Gate 216)** |
| `sex_seen` | 5.3k → 92.0k (+4,336/min; 2.9 MiB raw) | Deleted on observer death, `expire_remains`, or `prune_familiar` | Follow tightened `familiar` cap (spare known/related people); direct indexed `delete` syscalls | ≤ 256k–512k rows (~45 MiB incl. indexes) | **P1 (Gate 216)** |
| `skill_use` | 2.6k → 58.4k (+2,791/min; 15.9 MiB raw) | `USES_KEPT = 24`/actor alive; **unbounded** for dead | `skill_use_event` stream for exporters + 120 s post-death grace table (`dead_skill_use_due`), then indexed `actor().delete()` | ≤ 55k rows (~20 MiB incl. indexes) | **P1 (Gate 216)** |
| `seen_structures` | 190 → 233 rows, **64 → 847 KiB** (+38 KiB/min) | `compact()` at >64 pairs; deleted on `actor` death | Exclude transient `remains` (or bound intervals + watermark), rate-limit compaction | ≤ 16k rows (~8 MiB) | **P1 (Gate 216)** |
| `far_handle` | 2,112 → 2,887 (+39/min; 128 KiB) | `KEEP = 64`/actor; **leaked on death** | Add `ctx.db.far_handle().observer().delete(id)` to `act::forget_dead` | ≤ 128k rows (~14 MiB) | **P1 (Gate 216)** |
| `relation_fight` | 454 → 831 (max 977; 192 KiB) | Deleted on `actor` death; **dead `other` leaked** | Add `#[index(btree)]` on `other`; delete `other == dead` in `act::retire`; key in `living-mind` | ≤ 40k rows (~10 MiB) | **P1 (Gate 216)** |
| `structure` (`remains`) & `rot` | 156 → 2,557 & 28 → 2,429 (+120/min) | `remains_h` (96 min Cullet / 240 min default); infinite if holding `artifact` | Keep real-play `remains_h`; cap dense empty stranger remains per chunk; spill artifacts on rot | ~200–2k remains (~1 MiB) | **P2 (Scale)** |
| `experience` | 15.0k → 37.2k (+1,108/min; **32.2 MiB** raw) | `WINDOW = 400`/living char; deleted on consolidation & death | `WINDOW_MIND = 200`, `WINDOW_PLAYER = 128`; drop `living-mind` `iter()` scan via `Index` | ≤ 350k–400k rows (~350–450 MiB worst-case backlog) | **P2 (Scale)** |
| `thought`, `persona`, `background` | 0 in no-mind fixture (**huge** in minded worlds) | `MAX_THOUGHTS = 60` alive; **kept forever** for dead people | Keep 120 s post-death grace for `trials.py`, then delete via `actor` index; journals + Neo4j hold permanent history | ≤ 64k–120k live `thought` rows (~250 MiB) | **P2 (Scale)** |
| `character` & `sex` | 295 → 2,699 each (+120/min; 1.0 MiB raw) | **Kept forever** (`alive = false`) | Move unreferenced dead (no remains, no living kin, not `player.character`, no open record) to private `character_archive` (and/or external export); index `living-mind` cache | ≤ 5k–15k active rows (~8 MiB) | **P2 (Scale)** |
| `line_seen`, `experience_copy`, `act_outcome` | 6.3k → 7.0k & 6.1k → 7.0k (~12.7 MiB combined) | `LINES_SHOWN = 64`/player, cleared on next join; **leaked if never rejoins** | Deduplicate `line_seen` once `lines_table_on` is permanent; add 24–72 h disconnected death-screen TTL (`dead_player_due`) | ≤ 128k rows at 2k players (~140 MiB, halved after dedup) | **P2 (Scale)** |
| `acquaintance` | 0 → 295 (+14.7/min; 64 KiB) | Deleted on `observer` death; **dead `known` leaked** | Add `#[index(btree)]` on `known`; prune dead `known` without `relation` at `expire_remains`; key in `living-mind` | ≤ 100k rows (~12 MiB) | **P2 (Scale)** |
| `chronicle` | 1,383 → 3,725 (caps at 4,000; 703 KiB) | Trims 500 oldest when `> 4,000` (wraps every ~25 min at 2 deaths/s) | Keep 3,500–4,000 active tail; mirror to `chronicle_event` or incremental external audit exporter with gap detection | ≤ 4,000 rows (~0.8 MiB) | **P2 (Audit)** |

---

## 1. SpacetimeDB 2.14.1 documentation and versioned-source check

The authority and mind service pin `spacetimedb = "=2.14.1"` and `spacetimedb-sdk = "=2.14.1"` (`living/Cargo.toml`), running against `clockworklabs/spacetime:v2.14.1`. Official documentation consulted on 2026-11-26 and verified against the pinned `2.14.1` crate sources in the local Cargo registry (`~/.cargo/registry/src/.../spacetimedb*-2.14.1/`) and existing 2.14.1 server-source checks in [GATE216_GROWTH.md](GATE216_GROWTH.md) §6, [ATTENTION_BUDGET.md](ATTENTION_BUDGET.md), and [TICK_RATE.md](TICK_RATE.md):

| Doc page / source | Verified 2.14.1 behavior | Design implication for bounded retention |
|---|---|---|
| [Tables](https://spacetimedb.com/docs/tables/) & [Performance](https://spacetimedb.com/docs/tables/performance/) | Current web docs document tiered storage (`cache_policy = required_on_disk` / `no_requirement`) and the archive-table pattern ("Move old records to an archive table while keeping the same schema"). **Version check:** grepping `spacetimedb-2.14.1`, `spacetimedb-bindings-macro-2.14.1`, and `spacetimedb-lib-2.14.1` confirms **`cache_policy` does NOT exist in 2.14.1**. | In 2.14.1, **every table and every index is 100% RAM-resident for the database's life**. Moving rows to a second in-DB table only saves subscription/view/scan cost — **it does NOT free server RAM** until rows are exported out-of-band and deleted from SpacetimeDB (or until a future SpacetimeDB upgrade introduces working tiered storage). |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) & `spacetimedb-2.14.1/src/table.rs:1088,1426` | `RangedIndex::delete` dispatches directly to `delete_by_index_scan_point_bsatn` (for exact keys) or `delete_by_index_scan_range_bsatn` (for ranges like `..=now`) in one host syscall without copying rows into WASM. Non-unique B-tree keys hold up to 512 rows in a `SmallVec` and spill to a `HashSet` above 512 (`same_key_entry.rs`, [GATE216_GROWTH.md](GATE216_GROWTH.md) §6). | Prefer `ctx.db.<table>().<idx>().delete(key_or_range)` over `filter().map(id).collect()` + per-row `id().delete()`. Every extra B-tree index costs heap RAM (~60–120 B/entry in jemalloc), so add secondary indexes only on bounded tables where they eliminate scans or enable O(k) cleanup. |
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) & `spacetimedb-2.14.1/src/table.rs:88-101` | Supported in 2.14.1 (`#[spacetimedb::table(..., event)]`, already used by `combat_feed`, `seen_body_cue`, `seen_fighter_cue`, `seen_doing_cue`). Rows exist only within the inserting transaction, are broadcast to matching subscribers, recorded in the commit log, and hold **zero active RAM** after commit. Cannot be queried later by SQL or views. | Ideal for streaming audit records (`skill_use_event`, `chronicle_event`) to an external collector without growing active RAM. Never rely on event tables alone for reconnect recovery or polling tools that attach late; pair with a small bounded active table or grace window. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) & `living/authority/src/tables.rs:72,2327` | Adding new tables and adding B-tree indexes are safe automatic migrations with no client disconnect. Appending a column (`AddColumns`) rewrites the whole table and disconnects every client (and `Vec`/non-constant defaults are rejected in 2.14.1). Adding an RLS rule disconnects every client once at publish ([ATTENTION_BUDGET.md](ATTENTION_BUDGET.md)). | **Never append columns to existing tables for retention metadata** (such as `expires_ms` or `archived`). Use new small private scheduling tables (`dead_skill_use_due`, `dead_thought_due`, `dead_player_due`) and new B-tree indexes on existing columns (`familiar.thing`, `relation_fight.other`, `acquaintance.known`). |
| [Views](https://spacetimedb.com/docs/functions/views/) & `living/authority/src/frame.rs:4-15` | Views re-run in full inside the writing transaction when any row in their read set changes; dropping an old read set scans every view's read set in the database. | Keep per-player views (`my_skill_uses`, `my_experience`, `my_characters`) reading single-key point lookups on small, bounded tables, or replace hot views with RLS-filtered public copy tables (`experience_copy`). |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) & `spacetimedb-sdk-2.14.1/src/client_cache.rs:445-448` | `TableHandle::iter()` locks the SDK client cache mutex and **clones every row in the cached table into a `Vec`** on every call. Generated 2.14.1 Rust bindings expose `.find()` only on primary-key and unique columns, never on secondary B-tree indexes. | Any table subscribed by `living-mind` (`character`, `sex_seen`, `experience`, `acquaintance`, `relation_fight`, `routine`) or `living-viewer` (`thought`, `chronicle`) must be both **bounded in active size** AND **read via callback-maintained keyed maps** (like `mind-sex-seen-keyed` `fa2dbc3a6`), never `conn.db.<table>().iter()`. |

### Active RAM vs retained WAL vs cumulative writes

`AGENTS.md` and `PERFORMANCE_CONTRACT.md` require separating three distinct resource curves:

1. **Active RAM (authority tables + B-tree indexes + WASM linear memory):** In the 21-minute clean remeasure (`relay-1.mem.jsonl`), WASM linear memory stayed flat at **178.50 MiB**, while `spacetime_table_size_bytes` grew **+47.41 MiB** (55.94 → 103.36 MiB) and `jemalloc_allocated_bytes` grew **+126.64 MiB** (317.20 → 443.84 MiB; `jemalloc_resident_bytes` 618.66 → 772.90 MiB, +154.23 MiB). Roughly **1.6–2.7×** raw table bytes are consumed in jemalloc once B-tree index nodes, `SameKeyEntry` buckets, and allocator fragmentation are included. Every retention rule in this note targets **this** curve so active RAM reaches a flat plateau well inside the 64 GB budget.
2. **Cumulative WAL / commitlog writes (disk I/O and Linux page cache):** Every insert, update, and delete — including deletes performed by retention cleanup and inserts into event tables — appends to SpacetimeDB's commitlog. In the 30-minute runs ([GATE216_GROWTH.md](GATE216_GROWTH.md) §8), server cgroup memory rose **+2.2 to +2.5 GiB** (~75–85 MiB/min) even though server RSS rose only +155–198 MiB; the difference is Linux page cache backing commitlog segments. Deleting rows after a grace window bounds active RAM, **not** cumulative writes; reducing unnecessary churn (e.g., not rewriting bloated `seen_structures` blobs every look, not duplicating `Experience` in both `line_seen` and `experience_copy`) reduces both.
3. **Retained WAL size on disk:** Bounded separately by SpacetimeDB snapshot/checkpointing and commitlog compaction/truncation, plus archiving cold evidence off the database host (`~/slop-evidence` / audit store). Retention measurements must report **table bytes, jemalloc allocated/resident, server RSS, cgroup memory (separating page cache), and on-disk WAL bytes** independently.

---

## 2. Three-layer evidence boundary

Per [AGENTS.md](../AGENTS.md) and [AUDIT_AND_EXPERIMENTS.md](AUDIT_AND_EXPERIMENTS.md), active-data retention must never blur three distinct layers:

| Layer | Purpose | Durable home | Allowed to expire / forget? |
|---|---|---|---|
| **Current perception & live state** | What a living body sees, hears, feels, or is doing right now (`perceived`, `projected`, `combat_seen`, `experience`, `familiar`, `sex_seen`, `line_seen`, `seen_structures`, `far_handle`, `structure` remains) | Authority RAM (SpacetimeDB active tables) | **Yes** — bounded to living actors and explicit recency/expiry rules. |
| **Remembered character knowledge** | What an AI mind internalized from lived experience (concepts, beliefs, relationships, autobiographical episodes, formative thoughts) | Neo4j personal memory graph (`living/mind/src/memory.rs`) + mind projections (`relation`, `persona`, `place`) while alive | **Lossy by design** (fading/consolidation), and persists in Neo4j after death for audit inspection without being restored to new characters. |
| **Developer audit truth** | Exact causal trace: every world event, skill attempt/outcome, model exchange, death, and chronicle entry ([AUDIT_AND_EXPERIMENTS.md](AUDIT_AND_EXPERIMENTS.md) "Causal record contract") | Out-of-DB append-only evidence pipeline: `living-mind` JSONL journals (`llm.rs`), `trials.py` JSONL streams (`uses.jsonl`, `experiences.jsonl`, `thoughts.jsonl`, `chronicle.jsonl`), and (target for long worlds) an incremental audit exporter subscribed to authority event/table streams | **Never silently dropped.** Any buffer overflow or exporter lag must emit an explicit gap record/counter. |

**Rule of thumb:** Authority active tables should hold **only what live simulation rules, active player views, or a short polling grace window need**. Historical durability over 8-hour runs and multi-month persistent worlds belongs in the append-only audit stream and Neo4j/journal archives, not in RAM-resident SpacetimeDB tables.

---

## 3. Per-table analysis and retention design

### 3.1 `familiar` and `sex_seen` (coupled observer memory)

#### Numbers (Current vs Target)

| Metric | Current (21-min clean remeasure, `b324fb443`) | Current (projected 2,000 minded chars, 8 h) | Target (2,000 minded chars, 8 h) |
|---|---:|---:|---:|
| `familiar` rows | 5,455 → 92,329 (+4,344/min) | up to **4,096,000** (`2,000 × 2,048`) | **≤ 512,000** (`2,000 × 256` cap) |
| `familiar` raw bytes (`~49 B/row`) | 0.31 → 4.31 MiB (+4.00 MiB) | ~192 MiB raw / **~650 MiB** incl. 3 indexes | ~24 MiB raw / **~45–75 MiB** incl. indexes |
| `sex_seen` rows | 5,264 → 91,975 (+4,336/min) | up to **4,096,000** (`2,000 × 2,048`) | **≤ 256,000–512,000** (strangers capped at 128) |
| `sex_seen` raw bytes (`~33 B/row`) | 0.19 → 2.87 MiB (+2.68 MiB) | ~129 MiB raw / **~600 MiB** incl. 4 indexes | ~8–16 MiB raw / **~35–65 MiB** incl. indexes |
| `living-mind` SDK cache (`sex_seen`) | 92k rows replicated over WS | 4.1M rows replicated to mind RAM | ≤ 256k–512k rows (keyed in `Index`, `fa2dbc3a6`) |

**Why both still grew to 92k rows after `growth-fix-2` (`55c271265`):** `seen_structures` already moved structures out of `familiar`, so `familiar - sex_seen` stayed nearly constant (191 at min 0 → 354 at min 20 — almost every row in `familiar` is a `FAM_CREATURE` row written by one of Cullet's ~59 surviving AI residents watching the plaza). `growth-fix-2` deletes `sex_seen` when (a) the dead person's remains expire (`expire_remains`), or (b) `prune_familiar` evicts the `FAM_CREATURE` row. In Cullet, `remains_h = 48` (96 real minutes; default `skills.rhai` is 120 game hours = 240 real minutes), so zero remains expired in 21 minutes. Meanwhile `FAMILIAR_LIMIT = 2,048` (`brain.rs:99`, sized when structures still lived in `familiar`) allowed 59 residents × 2,048 = ~121k rows before eviction even started — bending the curve only around minute 18 (86.7k → 90.9k → 92.3k).

1. **What each row evidences and where it must survive:**
   - `familiar`: pure perception-novelty gate ("have I seen this creature/region/artifact recently enough not to emit another first-sight percept?"). Not developer audit truth; the actual first-sight percept is recorded in `experience` (and `experiences.jsonl`).
   - `sex_seen`: remembered body-sex observation ("`observer` made out `known` at full sight and saw their sex"). Not audit truth (true body sex is in `sex` / `character_archive`; what a prompt stated is recorded in the mind JSONL journal).
2. **Retention rule, scaling, and index costs:**
   - **Lower `FAMILIAR_LIMIT` from `2,048` to `256`** per actor (since structures no longer live in `familiar`), and check `prune_familiar` every **16** new inserts instead of 64. Keep `FAMILIAR_KEEP_MS = 60_000` and `SEEN_MS = 90_000` so nobody currently in sight is re-announced as a stranger.
   - **Spare named/known people in `prune_familiar`:** when evicting over the limit, evict `FAM_CREATURE` rows for unnamed strangers (no `relation`, `acquaintance`, family, or shared community) first, oldest `last_ms` first, and drop the paired `sex_seen` row via `ctx.db.sex_seen().by_pair().delete((me, known))` (single point-delete syscall instead of `filter().collect()` + per-id delete).
   - **Add `#[index(btree)]` on `familiar.thing`** (safe automatic migration in 2.14.1, no column append). In `tick::expire_remains`, alongside `sex::forget_known(ctx, st.owner)`, execute `ctx.db.familiar().thing().delete(FAM_CREATURE | st.owner as u64)` and change `sex::forget_known` (`sex.rs:67`) and `sex::forget` (`sex.rs:81`) to single-syscall `ctx.db.sex_seen().known().delete(known)` and `.observer().delete(id)`.
   - **Scaling & tick cost:** At 2,000 minded characters × 256 cap, `familiar` ≤ 512k rows and `sex_seen` ≤ 512k rows (typically <150k in normal play because most characters aren't watching 256 people). `prune_familiar` reads/sorts at most ~272 rows per actor (vs >2,048 today — an 8× reduction in WASM sort work when active) once per 16 new encounters; `expire_remains` runs at 1 Hz and deletes at most O(k) rows per expiring remains through indexed point deletes.
3. **Read-path costs under the bound:**
   - **Authority:** `familiar().by_actor_thing()` and `sex_seen().by_pair()` stay O(log N) point lookups on ~8× smaller trees.
   - **Mind service (`living-mind`):** Subscribes `SELECT * FROM sex_seen` (`main.rs:255`) and looks up pairs in O(1) via `Index::sex_seen_id` + `id().find()` since `fa2dbc3a6`. Does not subscribe to `familiar`. Bounding `sex_seen` cuts initial subscription snapshot size and WS churn by 8–16×.
   - **Player views/subscriptions:** None (both tables are private).
   - **Tools:** `battle_diag.py --familiar` runs `SELECT actor, thing FROM familiar` explicitly when requested; 8× fewer rows.
4. **What minds or players would notice (truthfulness):**
   - Players see nothing directly (both tables are AI-only).
   - A mind that watched >256 passing strangers in a plaza and later receives a prompt mentioning stranger #12 from 15 minutes ago (no longer in sight, never named, no relation) loses its `sex_seen` row and sees `"a stranger (#12)"` instead of `"a stranger (#12, a woman)"`. This is **truthful forgetting** — it never invents a sex, never drops known relations/community/family, and immediately re-learns the sex if it makes them out again (`sex::remember`). If a forgotten living stranger re-enters sight after `SEEN_MS`, the character may emit a new first-sight percept, which matches forgetting an unplaced face in a huge crowd.
5. **Measurement & `det_compare` expectations:**
   - Measure `familiar` and `sex_seen` rows/bytes and `jemalloc_allocated_bytes` in the 30-min Gate 216 fixture.
   - `det_compare` (30 s, 200 fighters): **will differ** once any observer exceeds 256 new sightings (expected rule change); validate with a `verify-core` `sex_seen_bound` extension testing stranger eviction vs known-person sparing and a 2-copy self-control `det_compare` to prove determinism.
6. **Built (branch `familiar-cap`, 2026-11-26/27): two value-only laws, main's behaviour until they are set.**
   - `familiar_limit` (2,048 as shipped) is the cap `brain::prune_familiar` reads at each check; the check runs every `familiar_limit / 32` new rows (8 to 64; 64 as shipped). `familiar_regard` (off as shipped) changes what goes first: unnamed strangers, the oldest first, then places and things; never someone the character knows by name (`perception::knows_name`: family, community, an introduction) or has a `relation`/`relation_fight` row about. Under `familiar_regard` a dead creature's rows go for everyone when its remains are gone (`tick::expire_remains`, by the new `#[index(btree)]` on `familiar.thing`), or at its death when it leaves none, and a cue on someone not remembered is refused "you do not remember seeing #N" ("you have never seen #N" was untrue after forgetting). `sex::forget*` are single indexed deletes now (the same rows). No column was added; no new table. Two laws, not one: a cap alone at 2,048 would still have changed the order of eviction past 2,048 rows, so `familiar_regard` keeps the order main's until it is set.
   - **The data the cap is drawn from** (familiar_census.py: rows per character by what they are of and how the observer stands with them; Cullet, 64 residents; private servers pinned to the A725 cores):
     - *Town, instinct, 15 min:* per resident p50 32, p99 58, max 60; **no unnamed strangers** (Cullet's residents share communities); community and family ≤ 40, regions ~37%.
     - *Town, minded (fake model), the `strangers` trial's world (64 minded residents and a silent newcomer, 20 min):* cap 128 against the default: first sights 945 against 968, **0 re-introductions** in both, no "again after a long time", no cue fired in either (the fake model writes no cues).
     - *Battle, two sides (`spawn_battle_sides`, residents left be, as the 216 gate's watchers), the living held at 264 for 15 min:* default: `familiar` 25.1k rows and stays there (per resident p50 469, max 533; 92–94% unnamed strangers, 42% about the dead). Cap 128 + regard: peaks at 13.8k, falls to 9.9k as out-of-view strangers go (p50 142, max 258; the dead 1.4%); spared (family, community, acquaintances, relations) ≤ 58 per resident, all kept.
     - *Battle, two sides, waves of 40 every 30 s (the crowd grows to ~530):* default +4.5k rows a minute (the 216 gate measured +4.3k), 54.7k at 11.75 min; cap 128: 26.5k, tracking the crowd still in view, which is never forgotten.
     - *Town, minded, census (the same world, default laws, 18.5 min):* per resident p50 38, p99 73, **max 75 and rising**, about 2 rows a minute at the top: regions (39%: Cullet's land is some 1,500 chunks, so places are not few), community and family ≤ 43, the one stranger (the newcomer).
     - *Battle, held, at cap 256 against the default (side by side, 15 min):* default 31.2k rows and creeping up (p50 605, max 653; the dead 53%); cap 256 + regard **flat at 14.6k from minute 2.5** (p50 259, max 263: the cap and its check's slack; the dead 11.7%); 1,042 re-introductions of 10,828 first sights (9.6%), none of a known person; no `sex_seen` pair without its `familiar` row.
   - **Recommended: `familiar_limit` 256 with `familiar_regard` on.** What a town needs sets it: the most active minded resident held 75 rows after 18.5 minutes and gained about 2 a minute, so about 134 by the end of one Cullet day (48 min), most of them places; 256 is twice that, so a town resident re-discovers no place and forgets no one in a day or two of play. 128 (twice the instinct town's 60, measured below) would make the most active residents start forgetting places within the first day. In a battle the cap value changes little: whenever the crowd in view is larger than the cap, every stranger out of view more than 90 s goes either way (re-introductions 9.2% at 128, 9.6% at 256). At 2,000 characters, 256 bounds `familiar` and `sex_seen` at about 528k rows each beyond what is in view (against 4.1M at 2,048), the design's ≤ 512k target; at 128 about 272k. The figure happens to match the design note's 256; it is drawn here from the town's measured need, not taken from it.
   - **What changes (measured at 128 and 256):** a stranger out of view more than 90 s may be forgotten, and seen again is a first sight again ("For the first time you see a stranger …"): 713 of 7,733 first sights (9%) at 128 and 1,042 of 10,828 (9.6%) at 256 in the held battles, 1,927 of 13,920 (14%) at 128 in the growing one, 0 in the minded town at 128 (so none at 256); none of a known person (an end-of-run audit). In the minded island battle at 128 (100 fighters + 116 walkers, fake model, 8 min; fighters held at 135 rows; at 256 none of them would have reached the cap, the most was 193) the minds' prompts carried 6,793 first-sight lines against 6,456 (+5%) and as many strangers' sexes (17,172 against 17,140). Truthfulness: an evicted stranger's `sex_seen` pair goes with the row (no prompt states a forgotten body's sex), "again after a long time" needs a row, and the cue refusal says what is true. `sex_seen` pairs written by a mind's scene (`perceive.rs`, anyone made out in sight) without a `familiar` row sit outside the cap: 0–35 of 9k–54k at the end of the battles; they are true, and go with remains or the observer's death (a follow-up could bound them with the cap).
   - **`det_compare` with the laws as shipped: identical** to main `e0480aab8` (Cullet 200 + 16 players, 1,800 ticks, 113 tables, 45,710 rows; each copy with its own build's script).
   - **The shipped script's size:** `skills.rhai` with Cullet's laws and the pre-split status law is within ~350 bytes of `MAX_SOURCE` (256 KiB) in `the_shipped_parts_joined_are_the_law_before_the_split` (main ~660); the two laws' words were cut to fit. The next law added to the shipped script will need room made.

---

### 3.2 `skill_use`

#### Numbers (Current vs Target)

| Metric | Current (21-min clean remeasure, `b324fb443`) | Current (projected 216-rate / 8 h) | Target (2,000 chars, 200-char battle, 8 h) |
|---|---:|---:|---:|
| Active rows | 2,570 → 58,386 (+2,791/min) | **~1,340,000** (unbounded) | **≤ 55,000** (`2,000 × 24` + 120 s dead grace) |
| Raw table bytes (`~271 B/row`) | 0.75 → 15.86 MiB (+15.11 MiB) | **~346 MiB** raw (~500 MiB incl. indexes) | **~14 MiB** raw (~20 MiB incl. indexes) |
| Writes / deletes per sec | ~100–300 inserts/updates/s; 0 dead deletes | linear growth forever | +1 indexed `actor().delete()` per dead char after 120 s |

1. **What each row evidences and where it must survive:**
   - Every combat skill attempt's full causal chain: `at_ms`, `source` (`player`/`graph`/`act`), aim/target, `accepted_ms`, `released_ms`, `outcome`, `outcome_ms` ([AUDIT_AND_EXPERIMENTS.md](AUDIT_AND_EXPERIMENTS.md) "Skill attempt" & "Actual result").
   - **Readers today:**
     - **Authority:** `combat::attempt` (trims living actor to `USES_KEPT = 24`), `open_use`/`accepted`/`released`/`outcome`, and `my_skill_uses` view (`combat.rs:843`, reads **living** player character only).
     - **Mind service:** Does **not** subscribe to or read `skill_use`.
     - **Player clients / probes:** `gate_load` and `latency_probe` subscribe `my_skill_uses` for correlation while the player's character lives.
     - **Tools:** `trials.py` streams `skill_use` during runs (`record.uses` → `uses.jsonl`, `record.gestures` → `gestures.jsonl`) AND reads `SELECT * FROM skill_use WHERE actor = S` in `final()` (`trials.py:2022`). `arena_report.py` reads `uses.jsonl` offline (not the DB). `battle_diag.py` and `island_fight.py` query `skill_use` via SQL during/after runs.
   - **Where evidence must survive:** In the **external audit stream** (`uses.jsonl` for trials; an event-driven JSONL/Parquet archive stream for 8-hour and persistent worlds), NOT indefinitely in active SpacetimeDB RAM.
2. **Retention rule, scaling, and index costs:**
   - **Add two new private/public-owner tables (no column changes on `skill_use`):**
     1. **`dead_skill_use_due { #[primary_key] actor: u32, #[index(btree)] due_ms: u64 }`** (private): inserted by `act::retire` with `due_ms = now + SKILL_USE_GRACE_MS` (default `120_000` ms, law-configurable; `0` disables grace in synthetic load fixtures if desired, or `u64::MAX` preserves current unbounded behavior for legacy single-fight scripts).
     2. **`skill_use_event` (`#[spacetimedb::table(accessor = skill_use_event, event)]`, private to owner, zero active RAM):** emitted on terminal transitions (refusal, outcome committed, or death cancellation) so an external audit exporter or live `trials.py` captures 100% of completed uses at commit time with zero polling misses and zero retained RAM.
   - **Housekeeping pass (1 Hz):** query `ctx.db.dead_skill_use_due().due_ms().filter(..=now).take(64)` (bounded per-second batch so a mass casualty wave never spikes a single housekeeping call), delete `ctx.db.skill_use().actor().delete(actor)` (one indexed point-delete syscall removing ≤ 24 rows), and delete the `dead_skill_use_due` row.
   - **Scaling & cost:** At 2,000 living characters + 200-char battle (even at 2 deaths/s), active rows plateau at `≤ 48,000 + (120 × 2 × 24) ≈ 53,760` rows (~14.5 MiB raw, ~20 MiB incl. `id` + `actor` indexes). At 2 deaths/s, housekeeping does 2 point-range reads + 2 `actor().delete()` calls per second (~20–40 µs/s total).
3. **Read-path costs under the bound:**
   - **Authority:** `open_use` and `attempt` read `skill_use.actor` (≤ 24 rows); cost is unchanged and flat forever.
   - **Mind service:** Zero (unsubscribed).
   - **Players (`my_skill_uses`):** Only ever reads `perception::living(ctx)`, so dead rows were already invisible to players.
   - **Tools:** `trials.py` stops within seconds of subject death and writes `final.json`, well inside the 120 s grace window (and already streams `uses.jsonl` during the run). Long-running `island_fight.py` / 8-hour runs consume `skill_use_event` (or poll with `id > cursor` faster than 120 s) so zero outcomes are lost.
4. **What minds or players would notice (truthfulness):**
   - **Nothing.** Neither minds nor human players can ever read a dead character's `skill_use` rows. Audit tooling must treat `skill_use` SQL queries on worlds older than 120 s as a live tail (matching [AUDIT_AND_EXPERIMENTS.md](AUDIT_AND_EXPERIMENTS.md) "Historical durability") and read full history from the exported `uses.jsonl` / audit archive.
5. **Measurement & `det_compare` expectations:**
   - Measure `skill_use` rows/bytes and `dead_skill_use_due` count over 30 min (plateau by minute 2.5 at ~5.5k–6k rows vs 82k today — saving ~21 MiB raw / ~35 MiB jemalloc in 30 min).
   - `det_compare` (30 s): **100% identical** on `skill_use` (grace window is 120 s > 30 s; only the new `dead_skill_use_due` table is added, which can be verified separately in a 150 s `verify-core` scene).
6. **Built (branch `skill-use-drain`, 2026-11-26; [COMBAT.md](COMBAT.md#skill-uses-kept-sent-and-drained-2026-11-26)):**
   - As designed: `skill_use_event` (private event table; `why` "outcome" at each outcome written or amended, "trimmed"/"drained" for a row that never had one), `dead_skill_use_due` (private; written at death, drained by `due_ms` at 1 Hz, at most 64 a call, by `skill_use().actor().delete`), grace 120 s (a constant, not a law: nothing in the world reads the dead's rows). Living characters keep their last 24: the rules read them (`combat::open_use`, `act::dodge_too_early`) and a player sees its own (`my_skill_uses`). `trials.py` keeps a dead subject's uses for `final.json` when a run goes on past the grace (`life.stop_on_death` false).
   - **Growth, measured** (Cullet, `spawn_battle` 200 then 40 more every 30 s among the residents, 10 min, ~1.5 deaths/s; both arms side by side on one private server pinned to the A725 cores, ~50 ticks/s under host load): `skill_use` rows at 2 / 4 / 6 / 8 / 9.75 min, main 8,300 / 12,137 / 15,795 / 19,378 / 22,695 (about +1,800 a minute, linear); branch 8,141 / 7,231 / 6,746 / 6,563 / 6,643 (flat), with 160–225 dead waiting out their grace.
   - **`det_compare` against main: identical** (Cullet, 200 fighters + 16 players, 1,800 ticks, 113 tables, 45,710 rows).

---

### 3.3 `structure` (`remains`), `rot`, and `seen_structures`

#### Numbers (Current vs Target)

| Metric | Current (21-min clean remeasure, `b324fb443`) | Current (projected 96 min Cullet / 2,000-char 8 h) | Target (2,000 chars, 200-char battle, 8 h) |
|---|---:|---:|---:|
| `structure` rows | 156 → 2,557 (+120/min) | ~11,650 remains at min 96 (2 deaths/s) | ~200–2,000 remains (capped per dense chunk) |
| `rot` rows | 28 → 2,429 (+120/min) | ~11,520 at min 96 | tracks active remains 1:1 |
| `seen_structures` rows | 190 → 233 (flat) | ~8,000 rows at 2,000 minded chars | ~8,000 rows (permanent structures only) |
| `seen_structures` bytes | **63.9 → 847.0 KiB (+38 KiB/min, 3.7 KB/row!)** | **~500+ MiB** if 2,000 chars see fragmented remains + repeated 64-chunk compactions! | **≤ 8 MiB** (<1 KB/row, bounded intervals) |

**Hidden defect uncovered by per-minute byte metrics:** `seen_structures` (`seen_structures.rs`) stores sorted inclusive `[start, end]` ID pairs per `(actor, 128 m block)`. When residents walk near a plaza accumulating 120 remains/min, each resident sees a different subset of remains IDs, fragmenting `ranges` beyond `COMPACT_AFTER = 64` pairs. `compact()` only removes *expired* structure IDs — while those thousands of remains are still live (for 96–240 real min), `compact()` **cannot** reduce the interval count below 64, so (a) `ranges` grows linearly in bytes every minute (+38 KiB/min for just 59 residents!), and (b) **every subsequent look walks all 64 chunks in the 128 m block** (`for dy in 0..8 { for dx in 0..8 { chunk_structures(ctx, chunk) } }`) trying to compact again!

1. **What each row evidences and where it must survive:**
   - `structure` (`remains`) & `rot`: physical world state (a corpse holding dropped inventory/carcass/artifacts until decay). The death itself is recorded in `chronicle`, witness `experience`, and `character`.
   - `seen_structures`: pure perception-novelty cache ("which structures in this 128 m block has this AI already noticed?"). Zero audit value.
2. **Retention rule, scaling, and index costs:**
   - **Fix `seen_structures` immediately (P1):**
     - **Option A (cleanest, recommended):** Store only **non-remains** (built/world) structures in `seen_structures` (whose IDs are scarce and long-lived, so `ranges` stays tiny: a few pairs per block). For `remains`, track a single `u64` high-water mark per `(actor, block)` (or use `last_look.max_structure` + a bounded per-actor ring of ≤ 64 recent remains IDs in a separate small table or module-memory + small cap). A resident notices newly fallen remains in sight once and never builds multi-kilobyte interval vectors over thousands of corpses.
     - **Option B (fallback if exact per-remains memory is kept):** Hard-cap `seen_structures.ranges` at `MAX_PAIRS = 64` (dropping the oldest/lowest intervals when compaction cannot shrink below 64) AND store a cooldown/last-compacted count so `compact()` runs at most once per 64 newly added IDs instead of on every look.
   - **Bound extreme corpse density without breaking permanent death (P2):**
     - Keep the `remains_h` law for normal play (in a real 200-character battle with permanent death, at most ~200 corpses exist — not the 3,000–11,500 generated by the Gate 216 fixture's 3 s artificial rejoins).
     - Add a **per-chunk empty-remains cap** (law `max_empty_remains_per_chunk`, e.g. 64): when a new corpse falls in a chunk already holding >64 empty non-artifact remains (no items, no artifacts), expire the oldest empty remains in that chunk immediately via `expire_remains`'s cleanup path. Corpses carrying loot or artifacts are untouched.
     - **Artifact-bearing remains (`tick.rs:310`):** Currently `rot` is deleted and the corpse stays in `structure` forever if it holds an artifact. To bound `structure` on multi-month worlds, either re-insert a low-frequency `rot` retry (e.g. +24 game hours) so once the artifact is taken the corpse expires, or convert decayed artifact-bearing remains into a compact `cache`/`tablet_pile` or bounded artifact-ground rule.
3. **Read-path costs under the bound:**
   - **Authority:** Eliminates the 64-chunk `compact()` storms in `seen_structures.rs:56-67` and keeps `common::chunk_structures` small even in protracted plaza battles.
   - **Mind service:** Unsubscribed from `structure`, `rot`, and `seen_structures`.
   - **Player clients / viewer:** `structure` is **`public`** (`tables.rs:710`), so every connected client replicates every `remains` row in the world! Capping dense empty remains (and eventually moving `remains` out of the global public `structure` table to a chunk/viewer-scoped surface) directly bounds client subscription traffic and client RAM.
   - **Tools:** `trials.py` queries `SELECT * FROM structure WHERE owner = S`; unaffected for living or recently dead subjects.
4. **What minds or players would notice (truthfulness):**
   - Under `seen_structures` Option A (remains high-water mark), a resident walking into an old battlefield notices remains once when entering; if they leave and return before remains rot, at most a bounded recent tail is re-checked, or a single summary line ("many remains lie here") is emitted — never fabricating who died.
   - Under the per-chunk empty-remains cap (64 empty corpses in one 16×16 m chunk), only looted/empty bodies from massive artificial churn disappear early; real 200-character battles spread over multiple chunks rarely hit 64 empty corpses in one chunk.
5. **Measurement & `det_compare` expectations:**
   - Track `seen_structures` `spacetime_table_size_bytes` (should stay flat at ~64–128 KiB instead of climbing to 847 KiB in 21 min) and `noticed.structures` span latency.
   - `det_compare` (1,500-remains fixture): Option B with no >64-pair trigger is identical; Option A changes `seen_structures` table contents (expected) and should be verified with `notice_delta_check` and a new `verify-core` scene proving remains are still noticed once without re-spamming.

---

### 3.4 `character` and `sex`

#### Numbers (Current vs Target)

| Metric | Current (21-min clean remeasure, `b324fb443`) | Current (projected 216-rate / 8 h) | Target (2,000 active chars, 8 h) |
|---|---:|---:|---:|
| `character` rows | 295 → 2,699 (+120.2/min) | **~58,000** (unbounded over months) | **~2,000–5,000** active (+ archive/export) |
| `character` bytes (`~348 B/row`, 6 indexes) | 0.12 → 0.94 MiB (+0.81 MiB) | ~20 MiB raw / **~65 MiB** incl. 6 indexes | ~2 MiB raw / **~6 MiB** incl. indexes |
| `sex` rows | 295 → 2,699 (+120.2/min) | **~58,000** (unbounded) | **~2,000–5,000** active (follows `character`) |
| `living-mind` `character().iter()` cost | 5 call sites cloning 2.7k rows under lock | cloning **58k+ rows** per call (multi-ms stalls!) | **O(1)** via callback `Index` + smaller active table |

1. **What each row evidences and where it must survive:**
   - `character`: identity, name, species, controller, `alive`, `born_ms`, `died_ms`, `cause`, `parent_a`, `parent_b`, `stage`.
   - `sex`: immutable body sex (`1` female, `2` male) used for look assignment, scenes, kin words ("mother"/"father" even for dead parents), and `my_sex`.
   - **Readers of dead rows:**
     - `my_characters` view (`perception.rs:2611`): reads the player's last dead character via `player.character` until they rejoin.
     - `common::label_for` / `named_at` / `sex::of`: reads dead parents' `character` and `sex` rows for kin words, and dead remains owners until `expire_remains`.
     - `living-mind`: subscribes `SELECT * FROM character` and `SELECT * FROM sex`, reads `character().id().find()` for labels/kin, AND calls `conn.db.character().iter()` at `mind.rs:578, 690, 701, 1190, 2972`.
     - `trials.py`: queries `SELECT * FROM character WHERE id = ...` for cast members and `SELECT * FROM character` in `census_s`.
2. **Retention rule, scaling, and index costs:**
   - **Step 1 — Fix `living-mind` read path first (no schema change):** Add callback-maintained maps in `mind::Index` for (a) `living_ai: BTreeSet<u32>`, (b) `children_by_parent: HashMap<u32, Vec<u32>>`, and (c) `by_name: HashMap<String, Vec<u32>>`, eliminating every `conn.db.character().iter()` clone in `living/mind/src/mind.rs`.
   - **Step 2 — Cold archival of unreferenced dead characters (for 8 h / multi-month worlds):**
     - Introduce a private `dead_character_due { #[primary_key] id: u32, #[index(btree)] due_ms: u64 }` queue (new table) populated when a dead character's remains expire (or immediately at death if no remains were created) with a grace delay (e.g. 5 min).
     - When due, housekeeping checks if `id` is still referenced by **any** active root:
       1. `player` row (player still on death screen) — check via new `#[index(btree)]` on `player.character`;
       2. living child (`character().parent_a().filter(id)` or `parent_b().filter(id)` has any `c.alive`);
       3. living `structure` (`remains`) or open `record_party`.
     - If **unreferenced**: emit a `character_archive_event` (for external audit export) and optionally move a compact row `{ id, name, kind, sex, born_ms, died_ms, cause, parent_a, parent_b }` into a private unsubscribed `character_archive` table (only if in-DB historical SQL is needed; for true bounded RAM in 2.14.1, **export externally and delete from `character` and `sex`** once archived, while `census.dead_people` preserves the exact world death total).
   - **Scaling & cost:** Active `character` + `sex` stay bounded at `O(N_living + N_recent_dead + N_living_parents)` ≈ **2,000–5,000 rows** (~6–8 MiB incl. indexes) even across 8 hours of high-churn battles or months of persistent generations. Reference checks use existing B-tree indexes (`parent_a`, `parent_b`, `record_party.party`, plus new `player.character`).
3. **Read-path costs under the bound:**
   - **Authority:** All hot paths already use `character.alive = true` or PK `id`. `housekeeping` and `backfill_sex` stay O(N_active).
   - **Mind service:** Initial subscription snapshot and `Index` memory stay proportional to active population + living lineage, not cumulative historical deaths.
   - **Player clients:** `my_characters` is already single-row via `player`. Under `open_tables` builds (`living/viewer` / dev), `character` is `public`, so bounding active `character` also bounds dev-client memory.
   - **Tools:** `trials.py` reads active cast and streams `census`/`final.json` within minutes; archived dead characters are preserved in the external audit archive.
4. **What minds or players would notice (truthfulness):**
   - **Living players:** Never lose their death screen (`player.character` pins the row until rejoin).
   - **Minds:** Never lose kin words for dead parents (living children pin their parents' `character` and `sex` rows), never lose names while remains lie on the ground, and Neo4j already stores the names of dead people a mind knew personally (`Memory` / `Concept` nodes). If a very old experience or relation still references an archived stranger ID, `known_as` (`mind.rs:633`) already falls back truthfully to `"someone"`.
5. **Measurement & `det_compare` expectations:**
   - Track `character` and `sex` row counts (should plateau after `remains_h + grace` instead of growing linearly at +120/min).
   - Step 1 (`living-mind` `Index`) does not touch the authority (`det_compare` N/A; verify with `verify-minds`). Step 2 does not trigger inside a 30 s `det_compare` window (grace > 30 s); test archival and reference pinning with a dedicated `verify-core` scene.

---

### 3.5 `experience`

#### Numbers (Current vs Target)

| Metric | Current (21-min clean remeasure, `b324fb443`) | Current (projected 2,000 living chars, worst-case backlog) | Target (2,000 living chars, 8 h) |
|---|---:|---:|---:|
| Active rows | 15,040 → 37,200 (max 38,145) | **800,000** (`2,000 × 400`) | **≤ 350,000–400,000** (`WINDOW_MIND = 200`, `WINDOW_PLAYER = 128`) |
| Raw table bytes (`~878 B/row`) | 11.74 → **32.24 MiB** (+20.51 MiB) | **~670 MiB** raw / **~950 MiB** incl. 3 indexes | ~290–335 MiB raw / **~420–480 MiB** worst-case; **<50 MiB** steady-state with active consolidation |
| `living-mind` SDK cache | Replicates all AI + player experiences (`player_memory`) | 800k rows cloned on `mind.rs:1629` `iter()` | Zero `iter()` clones (`Index` callback map) |

1. **What each row evidences and where it must survive:**
   - Unconsolidated sensory inbox of a living character (sights, speech, combat outcomes, results). Already treated as a transient buffer (`perceive.rs:11`, `WINDOW = 400`, deleted on death by `forget_dead` and on consolidation by `mind_consolidated` at `mind.rs:856`).
   - **Audit survival:** `trials.py` streams `experience` incrementally to `experiences.jsonl` (`id > cursor`). Minds record integrated experiences in Neo4j and in consolidation JSONL journals, explicitly logging dropped/trimmed counts (`llm.rs:1344`). For 8-hour runs, an external audit exporter should subscribe to `experience` (or a thin `experience_event` mirror) if full raw percept history is desired.
2. **Retention rule, scaling, and index costs:**
   - **Split `WINDOW` by controller type:**
     - AI characters (`c.ai == true`): `WINDOW_MIND = 200` (consolidation runs every few dozen experiences; 200 gives ~5× headroom during brief LLM rate-limit bursts while halving worst-case RAM).
     - Human-played characters (`!c.ai`): `WINDOW_PLAYER = 128` (players already see `LINES_SHOWN = 64` via `experience_copy`; 128 is ample buffer for asynchronous `player_memory` consolidation).
     - Instinct-only crowd bodies already skip `experience` writes (`perceive.rs:53`).
   - **Add a time-based trim fallback for stalled/unattached minds:** If `living-mind` is disconnected or `LIVING_ONLY` excludes a character, its `experience` buffer currently sits at 400 rows forever (which is why 116 walkers + 59 residents held 37.2k rows / 32.2 MiB in the no-mind Gate 216 fixture!). Keep the per-character cap (`128`/`200`), and optionally trim rows older than `EXPERIENCE_TTL_MS` (e.g. 30 real minutes) on insert check so idle/unconsolidated characters don't hold stale rows indefinitely.
   - **Eliminate `conn.db.experience().iter()` in `mind.rs:1629`:** `living-mind` already maintains `index.experience_in` / `experience_out` callbacks (`main.rs:269-295`); read player-memory backlog through `Index` instead of cloning the whole `experience` table!
   - **Cost:** Same O(log N) `observer().filter()` on `id % 32 == 0` (`det::window_due`), sorting ≤ 232 IDs instead of ≤ 432.
3. **Read-path costs under the bound:**
   - **Authority:** `perceive::told` trims half as many IDs when due; `mind_consolidated` deletes only unconsolidated tail.
   - **Mind service:** Cuts peak SDK cache RAM in half during LLM outages and eliminates the `iter()` clone lock stall in `mind.rs:1629`.
   - **Players:** Do not read `experience` directly (they read `experience_copy` / `my_experience`, capped at 64).
   - **Tools:** `trials.py` samples every few seconds (`id > cursor`), well inside 128–200 rows.
4. **What minds or players would notice (truthfulness):**
   - During normal operation (consolidation keeping up), **nothing changes** (inboxes stay <50 rows).
   - During a prolonged LLM outage (>200 percepts before consolidation catches up), older unconsolidated percepts drop sooner; `mind_consolidated` and `trials.py` already track and report exact dropped-before-consolidation counts truthfully (no silent amnesia).
5. **Measurement & `det_compare` expectations:**
   - Measure `experience` rows/bytes in Gate 216 (drops from ~37k / 32.2 MiB to ~16k / 14 MiB — an immediate **~18 MiB raw / ~25 MiB jemalloc** win on Gate 216 alone!).
   - `det_compare`: **will differ** whenever any actor exceeds 128/200 experiences in 30 s (expected); validate with `verify-minds` consolidation and overflow tests.

---

### 3.6 `line_seen`, `experience_copy`, and `act_outcome`

#### Numbers (Current vs Target)

| Metric | Current (21-min clean remeasure, `b324fb443`) | Current (projected 2,000 active + 10k departed players, 8 h) | Target (2,000 active players, 8 h) |
|---|---:|---:|---:|
| `line_seen` rows & bytes (`~895 B/row`) | 6,290 → 7,034 (~6.2 MiB) | `64 × (2,000 + 10,000)` = **768k rows (~655 MiB)** if players quit dead! | **≤ 4,000** staged-only rows (~3.5 MiB) after dedup |
| `experience_copy` rows & bytes (`~917 B/row`) | 6,090 → 6,950 (~6.3 MiB) | **768k rows (~670 MiB)** if players quit dead | **≤ 128,000** rows (~112 MiB raw, active players only) |
| `act_outcome` rows & bytes (`~612 B/row`) | 1,289 → 767 (~0.44 MiB) | unbounded for quit-dead players | **≤ 128,000** rows (capped at 64/active player; TTL on quit) |

1. **What each row evidences and where it must survive:**
   - Pure human-player UI presentation buffers (last 64 experience lines + structured act/death outcome codes for the player's current character or death screen). Zero developer audit value (`trials.py` reads `experience`, not `line_seen` or `experience_copy`, per [GATE216_GROWTH.md](GATE216_GROWTH.md) §4.2).
2. **Retention rule, scaling, and index costs:**
   - **Rule A — Disconnected death-screen TTL (fixes abandoned-player leak):** Add a private `dead_player_due { #[primary_key] viewer: Identity, #[index(btree)] due_ms: u64 }` table. When a player's character dies (or when they disconnect while on the death screen), schedule `due_ms = now + DEATH_SCREEN_TTL_MS` (e.g. 24 real hours for persistent play; 5 min when `presence` shows no connection in soak tests). Cancel the row if they reconnect or join a new character (`set_player`). When due in housekeeping (batched ≤ 64/s via `due_ms` range), delete `line_seen` (`by_observer_shown`), `experience_copy` (`viewer`), `act_outcome` (`observer`), and `lines_state` (`viewer`).
   - **Rule B — Deduplicate `line_seen` vs `experience_copy` (cuts player line RAM in half!):** Currently every shown line is stored **twice** (~895 B in `line_seen` AND ~917 B in `experience_copy` = ~1.8 KB/line). Once `lines_table_on` is the sole shipped path (retiring the legacy `my_experience` view), `line_seen` only needs to stage unreleased (`shown == false`) lines until the next frame (~0–2 rows/player) and delete them on release into `experience_copy`, saving **~115 MiB** at 2,000 players and cutting per-line WAL writes in half!
3. **Read-path costs under the bound:**
   - **Authority:** `frame::release_lines` does half the inserts/updates/deletes once deduplicated; `dead_player_due` costs 1 indexed range check/s.
   - **Mind service:** Unsubscribed.
   - **Player clients:** Identical RLS-filtered `experience_copy` stream (`viewer = :sender`).
   - **Tools:** None read `line_seen` or `experience_copy`.
4. **What minds or players would notice (truthfulness):**
   - Active players notice nothing. A player who dies, closes the game, and returns >24 hours later sees a clean character-creation prompt (or death summary from `my_characters` if still within character archival grace) rather than 64 day-old log lines; no false state is shown.
5. **Measurement & `det_compare` expectations:**
   - Rule A has zero effect within 30 s (`det_compare` identical). Rule B changes `line_seen` hashes intentionally (validated via `verify-player` `outcomes.py`, `combat.py`, and `verify-client` `lines_table`).

---

### 3.7 `thought`, `persona`, and `background` (dead people's mind records)

#### Numbers (Current vs Target)

| Metric | Current (Gate 216 no-mind fixture) | Current (projected real minded world: 2,000 chars, 8 h, e.g. 1,000 deaths) | Target (2,000 chars, 8 h) |
|---|---:|---:|---:|
| `thought` rows (up to 16 KB `detail`, avg ~3–6 KB) | 0 (no mind running) | live (`≤ 120k`) + dead (**60k+ unbounded**) = **540–1,080 MiB!** | **≤ 64k–120k** live rows only (**~190–360 MiB** bounded) |
| `persona` rows (`~1 KB/row`) | 0 (no mind running) | live + dead (**unbounded**) | **≤ 2,000** live (+ 120 s dead grace) |
| `background` rows (`~5.9 KB/row`) | 64 (0.36 MiB) | kept forever for dead seeded residents | **≤ N_living_seeded** (deleted on archive) |

1. **What each row evidences and where it must survive:**
   - `thought`: summary + raw model exchange (`detail` up to 16 KB), latency, tokens, model, and journal `reference` for each deliberation/consolidation/error. **Already written durably in full to `living-mind`'s per-character JSONL journals (`llm.rs`)**, and streamed by `trials.py` to `thoughts.jsonl` / `thoughts_all.jsonl`. In-DB `thought` exists for the live browser observer (`living/viewer`, which subscribes `SELECT * FROM thought`) and `trials.py` `final.json`.
   - `persona`: current identity projection (`narrative`, `values`, `goals`, `traits`, `mood`). Full historical trajectory lives in Neo4j (`Concept {key: 'self'}`) and `mind_rows.jsonl`.
   - `background`: seeded origin JSON (~6 KB/resident), read by `living-mind` during early life/genesis; preserved in the world seed file.
2. **Retention rule, scaling, and index costs:**
   - **Extend `act::retire`'s animal cleanup to dead people after a short grace window:** Today `act.rs:2707-2711` deletes `persona` and `thought` only for `c.kind != "person"`. Instead, on a person's death, schedule `dead_mind_due { #[primary_key] actor: u32, #[index(btree)] due_ms: u64 }` (new private table, `due_ms = now + 120_000` ms, law-configurable; can share a single `dead_cleanup_due` table with `skill_use`!).
   - When due in housekeeping (batched ≤ 32/s):
     - `ctx.db.thought().actor().delete(actor)` (one indexed point-delete syscall);
     - `ctx.db.persona().id().delete(actor)` (PK delete);
     - `ctx.db.background().id().delete(actor)` (PK delete — or keep until `character_archive`).
   - **Also bound live `thought` size for 2,000 minded characters:** Consider lowering `MAX_THOUGHTS` (`mind.rs:116`) from `60` to `24` (or capping `thought.detail` in SpacetimeDB to `2_048` bytes while keeping the full raw prompt/reply in the mind JSONL journal linked by `thought.reference`!). Dropping `MAX_THOUGHTS` 60 → 24 and `detail` 16 KB → 2 KB shrinks worst-case live `thought` RAM at 2,000 minds from **~700+ MiB** to **<96 MiB**!
3. **Read-path costs under the bound:**
   - **Authority:** Never reads `thought` except on trim/delete; `persona` and `background` are PK lookups only.
   - **Mind service:** Subscribes `SELECT * FROM persona` and `SELECT * FROM background` (does NOT subscribe `thought`). Deleting dead people's rows keeps both caches strictly proportional to living population.
   - **Browser observer (`living/viewer`):** Subscribes `SELECT * FROM thought` (`net.rs:29`). Without dead-person cleanup, `living/viewer` OOMs in long minded worlds; with cleanup + detail cap, viewer memory stays flat.
   - **Tools:** `trials.py` reads `thought` incrementally during the run and snapshots `final.json` immediately at stop (well inside the 120 s grace window); `animal_minds.py`, `arrive_report.py`, and `arena_report.py` read journals and `thoughts.jsonl`.
4. **What minds or players would notice (truthfulness):**
   - **Nothing.** Dead characters do not think, and living characters cannot read anyone else's `thought`, `persona`, or `background`. Developers inspecting a long-dead character in the observer see an explicit pointer to the mind journal / Neo4j archive rather than stale in-DB rows.
5. **Measurement & `det_compare` expectations:**
   - Validate in a minded soak (e.g. `verify-minds` + fake model server with permanent death): verify `thought`, `persona`, and `background` return to baseline 120 s after deaths while JSONL journals and Neo4j retain 100% of episodes.
   - `det_compare` (no-mind 30 s battle): identical (`thought` has 0 rows; grace > 30 s).

---

### 3.8 Reference leaks and rolling/permanent audit tables

| Table | Current 21-min growth (`b324fb443`) | Current retention defect | Target retention rule & index | Target 2,000-char / 8 h bound |
|---|---:|---|---|---:|
| `far_handle` | 2,112 → 2,887 (+39/min) | **Not deleted in `act::forget_dead`!** Dead observers leak up to 64 rows forever. | Add `ctx.db.far_handle().observer().delete(id)` in `act::forget_dead` (index `observer` already exists). | ≤ 128k rows (~14 MiB) |
| `relation_fight` | 454 → 831 (max 977) | `act::retire` deletes `actor == dead`, **never `other == dead`**. Survivors accumulate dead enemies forever; `living-mind` scans with `.iter()` (`mind.rs:2201`). | Add `#[index(btree)]` on `other`; call `ctx.db.relation_fight().other().delete(id)` in `act::retire`; index by `actor` in `mind::Index`. | ≤ 40k rows (~10 MiB) |
| `acquaintance` | 0 → 295 (+14.7/min) | `remember_member` inserts `N_members` rows per community death; `known == dead` never cleaned; `living-mind` scans with `.iter()` (`mind.rs:687,697`). | Add `#[index(btree)]` on `known`; at `expire_remains`, delete `acquaintance(observer, dead)` where observer has no `relation` with `dead` (Neo4j keeps named memories!); index in `mind::Index`. | ≤ 100k rows (~12 MiB) |
| `chronicle` | 1,383 → 3,725 (caps 4,000) | Active table is already bounded (~703 KiB), **but wraps every ~25 min at 2 deaths/s**, silently losing audit history if unexported! | Keep 3,500–4,000 active tail; emit `chronicle_event` (zero active RAM) or require continuous external audit drain with explicit gap reporting (`AUDIT_AND_EXPERIMENTS.md`). | ≤ 4,000 rows (~0.8 MiB) |
| `record` & `record_party` | 0 in Gate 216 | Records with `due_ms == u64::MAX` whose individual parties all die stay forever; `records::stance` scans all `record_party`. | In `records::on_death`, close/schedule expiry for personal (non-community) records when no living party remains (`due_ms = now + grace`). | O(N_living × `MAX_OPEN`) |
| `artifact`, `law_change`, `ground_edit` | Static / tiny in Gate 216 | Intentionally permanent world state / admin audit log. | Keep permanent; monitor counts in metrics (`ground_edit` and `law_change` are tiny; `artifact` should not pin `remains` forever — see §3.3). | <10k rows (<5 MiB) |

**Truthfulness check for reference cleanups:**
- `far_handle` (dead observer): invisible to every living character; 100% pure leak fix.
- `relation_fight` (`other == dead`): a dead character cannot be attacked or fought (`act::damage` refuses `!vc.alive`); Neo4j still remembers past enmity. No mind prompt or graph rule changes meaningfully once the enemy is dead (if a mind wants to remember they hated a dead person, `relation` and Neo4j carry that).
- `acquaintance` (`known == dead` after remains expire): while the dead community member's remains lie on the ground, survivors still name them at the corpse and in the death percept. Once remains are gone, survivors who had an actual `relation` keep the name in authority + Neo4j; survivors who had no personal `relation` fall back to Neo4j memory (if they ever cared) without keeping an `O(N_living × N_dead_members)` authority table forever.

### 3.9 `living-mind` SDK 2.14.1 `iter()` audit (cross-cutting read-path risk)

Because `spacetimedb-sdk-2.14.1` `TableHandle::iter()` locks the client cache and clones every row into a `Vec` (`client_cache.rs:445-448`), bounding authority tables is only half the work — `living-mind` also holds hot `iter()` calls on subscribed tables that scale with population:

| Table | `living-mind` `iter()` call sites (`living/mind/src/`) | Impact at 2,000 characters | Fix |
|---|---|---|---|
| `character` | `mind.rs:578, 690, 701, 1190, 2972` | Clones 2k–58k rows per check/turn | Callback-maintained maps in `mind::Index` (living AI set, children by parent, name map) |
| `experience` | `mind.rs:1629` (`player_memory` drain) | Clones up to 400k–800k rows! | Read from existing `Index` experience map (`main.rs:269-295`) |
| `acquaintance` | `mind.rs:687, 697` (`knows_name`) | Clones up to 100k rows on every name check | Add `(observer -> HashSet<known>)` to `mind::Index` |
| `relation_fight` | `mind.rs:2201` | Clones up to 40k rows per deliberation | Add `(actor -> Vec<id>)` to `mind::Index` |
| `routine` / `know_how` / `relation` / `place` / `seen_stock` / `cue` / `membership` | `mind.rs:685, 705, 794, 865, 879, 2085, 2097, 2143, 2149, 2150, 2197, 2264, 2281, 2282, 2412, 3028` | 2,000 × 10–40 rows = 20k–80k rows cloned per deliberation prompt | Extend `mind::Index` pattern from `fa2dbc3a6` to per-actor buckets (`actor -> Vec<pk>`) |

---

## 4. Implementation order and measurement plan

### Phase 1: Immediate gate (216 characters, 30 minutes)

Execute in three small, independently verifiable commits/PRs:

1. **PR 1 — Leak fixes & `seen_structures` bound (zero/minimal rule surface):**
   - `act::forget_dead`: delete `far_handle` by `observer`.
   - `relation_fight`: add `#[index(btree)]` on `other`, delete in `act::retire`.
   - `seen_structures`: exclude transient `remains` (or cap intervals + rate-limit `compact()`).
   - **Expected Gate 216 gain:** stops `seen_structures` 38 KiB/min blob growth and eliminates recurring 64-chunk compaction walks; eliminates `far_handle` and `relation_fight` dead leaks.
2. **PR 2 — `familiar` + `sex_seen` cap tightening & indexed deletes:**
   - Lower `FAMILIAR_LIMIT` to `256` (evicting unnamed strangers first, checking every 16 inserts); add `#[index(btree)]` on `familiar.thing`; delete `FAM_CREATURE | dead` in `expire_remains`; switch `sex::forget*` to direct `delete()` syscalls.
   - **Expected Gate 216 gain:** cuts `familiar` + `sex_seen` from **~185k combined rows** (at 21 min) to **≤ 15–20k rows** — saving **~50–70 MiB of jemalloc heap** (raw tables + 7 B-tree indexes).
3. **PR 3 — `skill_use` post-death grace window + `skill_use_event`:**
   - Add `dead_skill_use_due` (120 s default grace, law-configurable) + `skill_use_event` (owner-private event table) + 1 Hz batched housekeeping delete via `skill_use().actor().delete(actor)`.
   - Update `trials.py` (if needed for runs >120 s past a secondary actor's death) to keep reading `uses.jsonl` as authoritative.
   - **Expected Gate 216 gain:** caps `skill_use` at **~5.5k rows (~1.5 MiB)** instead of 82k rows (22 MiB raw / ~35 MiB jemalloc at 30 min).

### Phase 2: Scale & 8-hour sustained gate (2,000 characters, 200-char battle, 8 hours)

4. **PR 4 — `experience` window tuning + `living-mind` `Index` coverage:**
   - Set `WINDOW_MIND = 200`, `WINDOW_PLAYER = 128`, optional `EXPERIENCE_TTL_MS` fallback; eliminate remaining `conn.db.*.iter()` clones in `living-mind` (`character`, `experience`, `acquaintance`, `relation_fight`, per-actor tables).
   - **Expected Gate 216 gain:** cuts `experience` from 32.2 MiB → ~14 MiB (~25 MiB jemalloc).
   - **Expected 2,000-char gain:** caps worst-case `experience` backlog at <480 MiB and eliminates multi-ms SDK mutex stalls in `living-mind`.
5. **PR 5 — Mind dead-person cleanup (`thought`, `persona`, `background`) + external audit exporter:**
   - Add dead-person cleanup to the 120 s grace queue (`thought`, `persona`, `background`); optionally cap live `MAX_THOUGHTS` / `detail` size in SpacetimeDB (keeping full text in JSONL journals).
   - Add `chronicle_event` (or continuous external audit exporter draining `chronicle`, `skill_use_event`, and `character_archive_event` to compressed JSONL with explicit gap counters).
6. **PR 6 — Cold archival & remaining long-world bounds:**
   - Unreferenced dead `character` + `sex` archival/export (`dead_character_due` + `player.character` index).
   - `acquaintance` dead-target pruning (`#[index(btree)]` on `known`).
   - `line_seen` / `experience_copy` deduplication + `dead_player_due` disconnected death-screen TTL.
   - Per-chunk empty-remains cap (`max_empty_remains_per_chunk`) and artifact-remains rot retry.

### Measurement protocol (per PR)

For every PR, run and record on a clean host (no outside contention on pinned server cores):

1. **Verification skills (free tier, scratch DBs):**
   - `verify-core` (including new scenes for `dead_skill_use_due`, `familiar`/`sex_seen` stranger eviction vs known-person sparing, `seen_structures` remains noticing, and `dead_character_due` pinning).
   - `verify-client` (confirm all new private tables are listed and refused to non-owner clients; confirm zero unexpected disconnects — no column appends, no new RLS rules).
   - `verify-player` (confirm `my_skill_uses`, `my_experience`, `my_characters` death screen and rejoin).
   - `verify-minds` (confirm `Index` lookups, `known_sex` truthful fallback, `player_memory` consolidation, and dead-person journal durability).
   - Run `maintain-verification-skill` on any surface whose table/index inventory changes (`AGENTS.md`).
2. **Determinism (`det_compare.py`):**
   - Run a **self-control** (candidate vs byte-identical copy of itself, 1,800 ticks, 200 fighters + 16 players + `--remains 1500`) for every PR — must be **100% identical** across all 1,800 ticks.
   - Run **base vs candidate**:
     - PR 1 (`far_handle` / `relation_fight`): differs only on those two tables when deaths occur (verify all other 111+ tables identical).
     - PR 2 (`familiar` / `sex_seen` cap): differs once an observer crosses 256 sightings (expected rule change).
     - PR 3 (`skill_use` 120 s grace): **identical** on all existing tables over a 30 s (1,800-tick) run!
     - PR 4 (`experience` window): differs only if an actor exceeds 128/200 percepts in 30 s.
3. **Growth & cadence gauges (30-min Gate 216, then 8-hour scale runs):**
   - Record per-minute `spacetime_num_table_rows` and `spacetime_table_size_bytes` for every table, `jemalloc_allocated_bytes`, `jemalloc_resident_bytes`, `spacetime_worker_wasm_memory_bytes`, server process RSS, server cgroup memory (anonymous vs page cache), and **on-disk WAL/commitlog bytes** (distinguishing retained WAL from cumulative writes).
   - Acceptance for Phase 1 on Gate 216 (30 min): after minute 5 warm-up, **zero linear table-row or table-byte growth** in `familiar`, `sex_seen`, `skill_use`, `seen_structures`, `far_handle`, `relation_fight`, `line_seen`, `experience_copy`; flat `jemalloc_allocated_bytes` slope (<1 MiB/10 min from remaining `character`/`structure` until Phase 2); tick cadence ≥ 59.9 ticks/s and p99 within the session idle bound (`marker_steps.py`).
   - Acceptance for Phase 2 (2,000 characters, 200-char battle, 8 hours): flat active RSS plateau well inside the 64 GB reference budget across all 8 hours with zero restarts, zero lost subscriptions, and 100% of audit records verified present in the external archive stream.
