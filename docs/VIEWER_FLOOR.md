# The viewer floor: what a player costs the authority before anyone is attended

Status: **measurement and design note**, 2026-11-22, dev-box. Nothing here is built on main. The measuring code is on branch `viewer-floor` (from `attention-e2`), never for main; this note goes to main alone on the docs-only branch `viewer-floor-doc`.

## Bottom line

**With every plausible cut, 216 viewers at 60 Hz in a 200-fighter battle does not fit on either host.**
- **The ceiling:** 600 ms/s of the database thread for the whole tick.
- **Measured on dev-box, at the contract's density** (26–32 m ring, about 70 in sight, uninstrumented): each viewer costs **2.4 ms/s** with attention at a ceiling of 16, of which the 16 attended are 1.1. That is with the plausible cuts made and the game client's own views counted.
- **The largest viewer count that fits at 60 Hz is about 90** (86–103 over the hosts and runs) on dev-box and on the Spark's fast X925 cores alike: X925 runs the AI battle cheaper, but each viewer about 16% dearer.
- **About 115** (104–125) if the fighters think at 10 Hz instead of 15 (`combat_eval_hz`, an owner's decision measured on the Spark).
- **About 165** if nobody is attended as an individual (everyone is crowd), which is not a playable game.
- **216 needs about 1.0–1.3 ms/s a viewer, everything included.** That is reached only on paper, with the planned per-individual work, hearing as buckets, the fight feed trimmed to the attended, lines as a table and the 10 Hz fighters all landing at once.
- **The structural answer is to take per-viewer work off the one database thread.** SpacetimeDB 2.14.1 runs a database's reducers, views and subscription evaluation on one thread. So either the viewer work leaves the authority's tick, or a battle of that size is split across databases.

## 1. In short

- **The floor is E2's less profiling, and it is not all delivery.** At 16 viewers in the dense ring: 4.59 ms/s a viewer at L1, **4.10 uninstrumented**. L1's own counters add about 0.5 (§3.1). Of the L1 figure:
  - about 2.8 is delivery;
  - about 1.1 is the viewer being a character in the battle (an AI in its place pays the same);
  - about 0.3 is the test harness: keep-alive moves, the keeper's heals and SQL.
- **The largest delivery parts and their measured cuts** (dense ring, L1, ms/s a viewer):

  | Part | Cost | Measured cut |
  |---|---:|---|
  | Fight feed (every blow in sight, attended or not) | 0.74 | the whole of it, as a bound, with the feed off |
  | Hearing | 0.49 | −0.27 at 1 Hz; −0.49 with hearing off, as a bound |
  | `my_experience` view (64 lines re-run whole about twice a second) | 0.40 | −0.25 with lines every 1 s |
  | Sight | 0.24 | none worth having |
  | Frames' per-tick and per-frame bookkeeping | ≈0.3 | none: fewer frames for an empty scene saved nothing |

- **A real client pays more than the fixture did.** The game subscribes `heard_sounds`, a per-user view re-run whole on every heard row written. That is **0.83 ms/s a viewer in the dense ring** and 0.13 at the contract's density (§3.3). A real player's moves also cost about 290 µs each.
- **The plausible cuts together:** 3.05 ms/s a viewer in the dense ring (L1, from 4.59). At the contract's density, uninstrumented: **1.29**, from 1.78 (§7).
- **Attention at 16 adds 1.07 ms/s a viewer at the contract's density**, measured clean at 64 viewers: 2.36 against 1.29.
- **SpacetimeDB 2.14.1 (source and probe):**
  - row-level security on an indexed `viewer` costs no term per subscriber who does not receive the row; this corrects E2 §3.3;
  - a per-user view is re-run whole for its owner on every write it read, and costs by the rows it returns, so per-viewer views are the dearest way to deliver;
  - one database thread does reducers, views and subscription evaluation (§5).
- **Hearing is per-viewer state, not per-viewer geometry.** Buckets per bearing and band in place of rows per creature would cut it from 0.49 to about 0.07–0.18 a viewer (bounded) and remove `heard_sounds`. That is a design change to what a player is told (§4).
- **Hosts:** the per-viewer budget at 216 is about 1.03 ms/s on dev-box and about 1.05 in dev-box terms on X925 (§6).

## 2. Method

### 2.1 The fixture

- **The battle:** E2's ([ATTENTION_E2_COST.md](ATTENTION_E2_COST.md) §1.1), unchanged: `living/tools/battle_viewers.py` on Cullet; 200 AI fighters (`spawn_battle`) kept at 200 (`--keep-fighters 1`); viewers as player characters kept alive (`--keep-alive 0.5`); paused placement, the battle after placing; tiers, cues and every copy table on (the shipped delivery defaults); 20 s warm-up, 60 s window; a fresh world per run.
- **The floor arm:** E2's prototype with attention on and a ceiling of 0, nearest-first, no crowd rows: every viewer sees the battle and attends no one. That is E2's `db-p0n0nocrowd`.
- **Sets:**
  - a: 16 viewers, 12 arms;
  - b: 216 viewers;
  - c: the plausible cuts at 16 and 216;
  - d: clean, at 64 and 128 viewers;
  - e: the game client's views;
  - plus the probe (M1, §5).
- **Rings:** 16 viewers on a 10 m ring (dense: 108–120 in sight); 216 viewers on the 26–32 m ring (about 70 in sight; the host saturates); set d: 64 and 128 viewers on the 26–32 m ring (see §7).
- **Profiling levels:** L0 (`--no-profile`: server metrics and thread CPU only), L1 (`--full-log`: phase spans and `diag` counters, what E2 used), L2 (L1 plus `profile_detail`, the detail spans; one run each, for shares only).
- **Cost per viewer:** the database thread's ms/s (the `wasm-*` thread's CPU), less the 0-viewer arm **at the same profiling level**, over the viewers. Its parts come from the server's own metrics (`spacetime_txn_cpu_time_sec` by reducer and transaction type, `view_total_time_usec` by view) and from the tick's phase spans.
- **Runs:** two per arm, interleaved within a set; ranges are over the runs. A run waits for a 1-minute load under 4 and records the load and the busiest processes at its start and end. Every world is deleted after its run and the server's leftover replica directories are cleared (SpacetimeDB 2.14.1 keeps them).

### 2.2 The measuring switches (branch `viewer-floor`, all off by default)

Value-only laws read at the next tick, each a measuring switch, not a proposal:

| Law | What it does | Stands for |
|---|---|---|
| `sweep_keep_memory` (exists on main, off) | the sweep keeps each viewer's `heard` rows and the creatures' health readings in module memory (docs/COMBAT_PHASE.md Part C) | module memory for the sweep's reads |
| `vf_lines_ms` | a player's experience lines released at most this often (0: the built-in 100 ms) | fewer `my_experience` re-evaluations |
| `vf_hear_every` | `heard` worked out at every Nth sweep (1: every sweep, as on main; 0: never) | hearing at a lower rate; 0 is the bound of hearing's whole cost |
| `vf_frame_idle_ms` | an empty scene framed at most this often | fewer frames for a viewer attending no one |
| `vf_feed_off` | no fight event shown to any player | the bound of the fight feed's cost (a feed trimmed to the attended costs between) |

Detail spans were added inside the frames (`frame.one`, `frame.copy_state`, `frame.scene`, `frame.feed`, `frame.lines`, `frame.senses`, `frame.earshot`, `frames.schedule`, `frames.engaged`), behind `profile_detail` like every detail span.

**Off is off.** `det_compare.py`'s player mode (16 players on a 10 m ring, 200 fighters, 1,800 ticks, every table every tick): main `a6375a70e` against `vf-cullet` (`33fec52db`'s authority) with every switch off: **identical** (113 tables, 44,762 rows). Negative control, `vf_hear_every=0`: the law tables differ from tick 3, `heard` and `hear_salt` from tick 4 (the first sweep), as they must.

### 2.3 Host and discipline

- **Host:** dev-box (AMD Ryzen AI Max+ 395, 16 cores, 32 threads, up to 5.1 GHz), scratch servers `vf-stdb` (series) and `vf-probe` (the probe), SpacetimeDB 2.14.1 (`clockworklabs/spacetime:v2.14.1`), each its own volume, started through `systemd-run --user --scope`; unpinned (the dev-box's rootless podman has no cpuset controller).
- **Builds** through `gate_pause.sh` at `-j 8`. No gate ran during any measured window. The `flake-scope` gate (batch 45) ran 05:45–05:56 UTC. A 216-subscriber pre-check of the probe overlapped its first minutes; that pre-check is not used. The full probe and every series started after the gate.
- **Two incidents, both without effect on the numbers:**
  - the first start of set a failed in seconds (the systemd unit had no `docker` on its `PATH`); no battle ran, and those directories are kept apart (`failed/runs-nodocker`);
  - I added set c to `series.sh` while set b was running; bash read the new lines and ran set c's four runs right after set b (all exit 0, same module and harness, laws recorded), then stopped on a syntax error before set c's single L0 run. The four runs are used; the L0 run was dropped.

## 3. The floor, part by part

All figures in this section: 16 viewers on the 10 m ring, the floor arm, ms/s per viewer against the 0-viewer arm at the same level, two runs (the L2 split is one run, used for shares only).

### 3.1 The total, and what profiling adds

| Level | Floor, ms/s per viewer | Module memory, lines every 1 s, hearing at 1 Hz, idle frames | The same without idle frames, with the feed off ("plausible cuts") |
|---|---:|---:|---:|
| L1 (E2's level) | **4.59** (4.26–4.92) | 4.01 (3.87–4.15) | 3.05 (2.86–3.24) |
| L0 (no profiling) | **4.10** (3.69–4.50) | 3.50 (3.47–3.53) | – |
| L2 (detail spans, 1 run) | 7.23 | 6.73 | – |

- **L1 inflates the per-viewer floor by about 0.5 ms/s (11–13%)**: two independent pairs agree (4.59 against 4.10, 4.01 against 3.50). Its counters and the frames' cadence log line run per viewer. E2's floor of 4.3–5.0 ms/s per viewer, measured at L1, is about **3.8–4.5 uninstrumented**. L2 nearly doubles it, so L2 gives shares only.
- **An unexplained offset:** the 0-viewer arm itself ran higher at L0 than at L1 (377.6 over four runs, 370–392, against 361.9 over two, 356–368), though interleaved in set a. One L0 run (392) stands apart; without it the L0 mean is 372.9. Each level is compared with its own 0-viewer arm, so the per-viewer figures do not depend on the offset, but its cause is not known.

### 3.2 The parts (L1, ms/s per viewer)

Each part's cost, what it does for a viewer, why it does not shrink when the viewer attends fewer, and the measured effect of the smallest change. "Measured" means an arm of this series; "bounded" means derived from measured pieces with the arithmetic shown; anything else is marked an estimate.

| Part | ms/s | What it does per viewer | Why constant in the attended count | Smallest change | Effect (kind) |
|---|---:|---|---|---|---|
| **Sweep: hearing** | 0.49 | at each 5 Hz sweep, reads the viewer's ~105 `heard` rows (50 µs), works out bearing and band for the ~52 creatures within 9 m and out of sight, writes ~15 rows (about 100 inserts and deletes a viewer-second) | hearing covers everyone unseen within 9 m, attended or not | hearing at 1 Hz (`vf_hear_every=5`) | sweep −0.32, total −0.27 (measured); hearing off entirely −0.49 sweep, −0.84 total (bound) |
| **Sweep: sight** | 0.24 | the one sight rule over ~250 candidates gathered within reach | sight decides who is in sight before attention chooses among them | none worth having (E2: a 1 Hz throng sight saved nothing) | – |
| **Sweep: the rest** | 0.36 | the gather, the viewer's own rows, the change test and health reads for projections, the gaze band, the resources look | per viewer per sweep | module memory for the reads (`sweep_keep_memory`) | sweep −0.17, total −0.26 (measured); nothing on top of hearing at 1 Hz |
| **Frames: the fight feed** | 0.30 | at every frame (~27 a viewer-second), one `combat_seen` row and one `combat_feed` event row for every fight event in sight since the last frame, and the expired rows deleted: ~84 events a viewer-second, ~250 row writes | the feed shows every blow in sight, attended or not (`combat::show` uses sight, not the scene) | trim the feed to the attended and to blows on the viewer | the bound (`vf_feed_off`): frames −0.25, the feed's whole cost −0.74 with its tick part (measured) |
| **Frames: lines** | 0.15 | releases the viewer's staged experience lines every 100 ms (~5 lines a viewer-second) | lines come from everything witnessed | release every 1 s (`vf_lines_ms=1000`) | frames −0.08 (measured) |
| **Frames: earshot, senses, copy state** | 0.10 | earshot every 250 ms (a gather of everyone within a shout), senses every 250 ms, three copy-state reads a frame | per viewer per frame | – | – |
| **Frames: scheduling and the engagement map** | 0.12 | every tick: each viewer's frame due-check (a copy-state read per viewer) and the engagement map | per viewer per tick | – | – (no frame at all for an empty scene saved nothing: `vf_frame_idle_ms`, measured +0.07, within noise) |
| **Cues** | 0.04 | cue rows for near and engaged creatures | none while nobody is attended | – | – |
| **Views** | 0.47 | `my_experience` 0.40 (re-run whole about 2 times a viewer-second, about 190 µs a call: 64 lines materialized and diffed), `my_body` 0.05, the rest 0.02 | a line comes for everything witnessed; the view is per viewer | lines every 1 s | views −0.25 (measured); lines as a keyed table with a `viewer = :sender` rule instead of a view: about 5 line writes a viewer-second at the probe's 7–15 µs a row, **0.04–0.08** in place of 0.40 (bounded) |
| **Subscription evaluation** | 0.16 | evaluating the tick's writes against the viewer's subscriptions (`txn_type="Update"`) | follows the rows written for the viewer: the feed is half of it | the feed trimmed | −0.08 with the feed off (measured) |
| **The fight feed in the tick** | ≈0.45 | `combat::show` for every fight event: a gather of everyone within sight of the event and a sight check for each player there (in `tick.combat` and `tick.activity`) | as the feed above | as above | in the −0.74 above (measured) |
| **The viewer as a character** | ≈1.1 | the viewer is a character in the battle: its witness lines (fold, 0.48: onlookers' lines are written for every fight it sees), its own evaluations (wakes 0.16, slots 0.08), its body (0.08), its acts and the blows it takes (activity, about 0.3 after the feed's share) | an AI fighter in its place pays the same | not delivery: these are the AI tick's costs per character | – |
| **Harness** | ≈0.30 | the keep-alive's moves (`human_move`, 0.20: 0.67 a viewer-second at about 290 µs each), the keeper's heals (`admin_set_vitals`, 0.05), its SQL calls and their connections (about 0.05) | – | – | not a cost a real client pays at these rates (below) |
| **Housekeeping** | 0.05 | the 1 Hz housekeeping's share per character | per character | – | – |
| **Unspanned remainder** | ≈0.2 | the tick's commit and what no span covers | – | – | – |

The parts add to about 4.6 against the measured 4.59. The fight feed's two halves are measured together (−0.74); their split (0.30 in the frames, ≈0.45 in the tick) is from the L2 shares.

### 3.3 Real client or harness?

- **Harness, not game cost (about 0.3 ms/s per viewer):** the keeper's heals and its SQL polling (`admin_set_vitals`, `/Sql` and their connections), and the profiling (0.5 at L1). The keep-alive's moves are a harness rate, but a real player's input has a real price: **about 290 µs of database thread per `human_move` at 16 viewers** (165 µs at 216 on the saturated host). A player issuing 2 moves a second costs about 0.6 ms/s per viewer on top of everything here, outside the floor. Not measured as such: the input rate of real play.
- **The viewer as a character (about 1.1 ms/s):** real, but not delivery. 216 players in the battle are 216 more characters; the contract counts them as characters too. They are kept apart in §7.
- **Game cost the fixture does not pay:** the game client subscribes views the load tool does not (`living/game/src/net.rs` against `gate_load`'s base): `heard_sounds`, `my_earshot`, `my_senses`, `my_act_outcomes`, `my_offers`, `my_known_names`, `my_records`, `speech_card`, `cover_law`. `heard_sounds` is a per-user view over the viewer's ~105 `heard` rows, re-run whole whenever one of them is written (several times a viewer-second in a battle). Set e measured them with the game's subscriptions (`--game-views`):

| Arm | `heard_sounds` ms/s a viewer | its calls a viewer-second | µs a call |
|---|---:|---:|---:|
| Dense ring, floor (L1) | **0.83** | 4.9 | 168 |
| Dense ring, plausible cuts (hearing at 1 Hz) | 0.18 | 1.0 | 182 |
| Contract density, floor (L0, 64 viewers) | 0.13 | 2.8 | 44 |
| Contract density, plausible cuts | 0.05 | 0.9 | 52 |

The other added views cost little (`my_earshot` 0.002–0.02). **A foreign `git` process** (PID 512126, not mine, up to 7.6 GB RSS) ran through set e, 08:00–08:16 UTC. Set e's totals rose in parts that subscriptions cannot touch (the AI's combat and wakes), so only its view metrics are used, not its totals.


## 4. Hearing: per viewer, or per sound, or per cell?

**What hearing is now.** For each player, at each 5 Hz sweep, from the sweep's own gather (shared with sight): every creature within the hearing reach (9 m for people) and out of sight. Each becomes a private `heard` row keyed by a salted (listener, creature) key, with the creature's kind label, a compass bearing (8 ways) and a band (within 5 m, 15 m, beyond); a row is written when it starts or its bearing or band changes, and goes when the creature comes into sight or 2 s after it was last heard (`perception::hear`). The client reads them through `heard_sounds`. In the dense battle that is ~52 creatures heard a sweep, ~105 rows held, and about 100 inserts and deletes a viewer-second.

**Is it per-viewer work that could be per-sound or per-cell?**
- **Per sound: no saving in a battle.** Every fighter is audible all the time, so listing sounds per source and fanning them out to listeners gives the same (listener, creature) pairs. It would pay only in a quiet world.
- **Per cell, as geometry: no saving either.** A shared per-tick grid of who is audible where still leaves each listener a pass over the creatures within 9 m; that pass is not the cost. The gather is shared already and costs about 5 µs a sweep (L2, `sight.gather`).
- **What costs is the per-viewer state:** reading ~105 rows a sweep (`hear.read`, 50 µs, about half of hearing) and writing ~100 rows a viewer-second, plus, for a real client, `heard_sounds` re-run whole on each write (§3.3).
- **The shape that removes most of it: per (bearing, band) bucket, not per creature.** What a player is told is already only a bearing and a band. Up to 24 buckets a viewer (8 bearings × 3 bands), each a count by kind, kept in module memory and written as keyed rows with a `viewer = :sender` rule only when a count changes, as E2's crowd rows are. Per sweep: a count over the heard creatures in the gather loop (no table read); per second: the bucket changes, a few to ten a viewer.
  - **Bound:** the in-memory count is part of a gather that costs about 5 µs a sweep (≤0.03 ms/s); 5–10 bucket writes a viewer-second at the probe's 7–15 µs per row cost 0.04–0.15 ms/s. Hearing would fall from 0.49 to about **0.07–0.18 ms/s**, and `heard_sounds` (a view) would go.
  - **What changes for the player:** an unseen creature is a count in a direction, not an individual with a key; the kind label survives as a count by kind. Lingering moves to the bucket. This is a design change to how hearing is shown (docs/PERCEPTION.md), the owner's call, not a refactor.
- **The cheap, measured step:** hearing at 1 Hz (`vf_hear_every=5`): −0.27 ms/s per viewer in total, at the price of an unseen creature's sound appearing up to 1 s late.

## 5. What SpacetimeDB 2.14.1 makes cheap or impossible

### 5.1 The probe (M1): one written row, four ways to a viewer

A standalone module (`living/tools/sub_probe`, driver `living/tools/sub_probe.py`) on its own server. Every connecting client is a subscriber (an anonymous `spacetime subscribe` in the container, one tokio worker each), subscribed to all four sources at once; `setup` gives each subscriber 50 rows in each table (a motion copy's size); a 60 Hz scheduled reducer then updates 50 random rows a tick (3,000 a second; 10 a tick for the public table) in one mode's table. A 20 s window per arm, against the tick-only arm (same tick, no writes) of the same block. Database-thread µs **per written row**, and of that the subscription evaluation (the `Update` transaction that follows each commit):

| Subscribers | Row-level security, `viewer` indexed | ... of which evaluation | Row-level security, `viewer` not indexed | ... of which evaluation (rows scanned/s) | Per-user view returning 50 rows | ... of which the view | Public table, everyone gets every row: send threads |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.2 | 1.5 | 5.8 | 1.5 (26 k) | 13.2 | 4.8 | +8 ms/s |
| 16 | 6.8 | 3.1 | 10.8 | 8.0 (372 k) | 38.6 | 31.8 | +23 ms/s |
| 64 | 7.2 | 4.2 | 15.5 | 13.6 (844 k) | 63.5 | 57.2 | +53 ms/s |
| 216 (4 runs) | 9.2–14.5 | 4.9–7.3 | 18.8–25.3 | 15.6–19.7 (1.08 M) | 96–102 | 85–90 | +250–294 ms/s |

Probe runs at host load 1.4–10 (the 216 block's later repeats at 4–10); 1, 16 and 64 subscribers are one run each.

What it shows:
- **An indexed `viewer = :sender` rule costs no term per subscriber who does not receive the row.** The evaluation per row grows from 1.5 to about 5–7 µs only because 50 rows a tick reach more distinct viewers (each viewer with a changed row is one query evaluated). The source says why (below).
- **The same rule on an unindexed column scans the transaction's whole delta once per subscriber with a match**: about 1.1 million rows a second at 216, and 15–20 µs a row.
- **A per-user view is re-run whole for its owner on every write to a row it read**, and its cost is the rows it returns: 50 rows a call, about 35–95 µs a call (at 216, 2,688 calls a second for 3,000 writes). This is `my_experience`'s cost in the game (§3.3).
- **A public table read by everyone** is cheap on the database thread and expensive on the send threads, which other databases on the host share.

### 5.2 The source (SpacetimeDB `v2.14.1`, the pinned server; read, not inferred)

Read from a clone of `clockworklabs/SpacetimeDB` at tag `v2.14.1` (`a0bf6be`); paths are in that tree.

- **Row-level security is applied by rewriting the subscription** (`crates/expr/src/rls.rs`, `resolve_views_for_sub`): the client's `SELECT * FROM t` becomes the rule's query with `:sender` bound to its identity.
- **Equality filters become search arguments** (`crates/physical-plan/src/plan.rs`, `search_args`: an index point scan or an equality filter yields `(table, column, value)`). The subscription manager keeps them in `SearchArguments` (`crates/core/src/subscription/module_subscription_manager.rs`, about lines 257–345) and, for each changed row, looks up only the queries whose argument matches the row's value (`queries_for_table_update`, about line 1301). Queries without one are evaluated for every change to their table (`tables`).
- **The delta is indexed for the queries' indexes** (`crates/core/src/subscription/tx.rs`, `DeltaTableIndexes`): a matching query reads only its own rows of the transaction's changes when its column has an index; without one, it filters the whole delta (the probe's unindexed arm).
- **Evaluation is single-threaded on the database's thread** (`eval_updates_sequential`: "we removed rayon and switched to a single-threaded execution"), in a read transaction metered as `txn_type="Update"` (`module_subscription_actor.rs`, `commit_tx_downgrade(tx, Workload::Update)`); serializing and sending go to a separate send worker.
- **Views are re-run whole, inside the writing transaction.** A view call records its reads (`crates/datastore/src/locking_tx_datastore/mut_tx.rs`, `ViewReadSets`: a point index read is kept per key; a range or a scan counts as the whole table), and a transaction that writes a row in a read set re-runs that call before it commits (`call_views_with_tx`). The result is then diffed against the stored one. There is no incremental maintenance of procedural views.
- **Query-builder views are not incremental in 2.14.1 either.** The docs (2.0.0) say query-builder views "can be updated incrementally"; in the pinned source a view's query is compiled and run whole at each refresh (`run_query_for_view`, which also refuses parameterized SQL). I did not measure one.
- **Every copy table the game uses has a btree on `viewer`** (`seen_body_copy`, `seen_fighter_copy`, `seen_character_copy`, the cue tables, `combat_feed`, E2's `seen_crowd`), so the cheap path applies to all of them.

### 5.3 The documentation (spacetimedb.com, version 2.0.0 on 2026-11-22; the pinned version is 2.14.1)

- [Views](https://spacetimedb.com/docs/functions/views/): per-user (`ViewContext`) views are computed "separately for each subscriber"; procedural views are re-run whole ("If any row in that read set changes ... SpacetimeDB must re-execute the entire view function"); keep read sets small; prefer shared data ("entities in region X") to per-user data. Agrees with the source, except the claim of incremental query-builder views (above).
- [Row-level security](https://spacetimedb.com/docs/how-to/rls): "an experimental, unstable feature ... Use Views Instead"; `:sender` is bound to the client's identity; nothing on cost. The probe and the source show that, for this access pattern, the rule on an indexed column is the cheapest of the four ways measured, and a per-user view the dearest.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): updates are pushed when matching rows change; nothing on evaluation cost or many subscribers.
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/): rows exist only for their transaction, are not cached by clients, and are still recorded in the commitlog; they cannot be read by views.
- [Performance](https://spacetimedb.com/docs/tables/performance/) and [indexes](https://spacetimedb.com/docs/tables/indexes/): prefer indexed lookups; index what you filter on; a multi-column index serves a leftmost prefix.

### 5.4 Correction to E2

[ATTENTION_E2_COST.md](ATTENTION_E2_COST.md) §3.3 guessed that each `seen_crowd` write is checked against every subscriber's rule, so that a write costs more as viewers grow. **The source and the probe say no** for an indexed `viewer` (which `seen_crowd` has): a write evaluates only its own viewer's query. The higher per-write figure E2 read at 216 viewers came from a saturated host, where per-tick arithmetic does not separate costs cleanly. The correction is made in that note's §3.3 on the same docs branch as this note.


## 6. The host: budgets on dev-box and on the Spark's fast cores

**The budget.** The whole tick call gets at most about **600 ms/s** of the database thread (docs/COMBAT_PHASE.md, "Budget": 10 ms a tick at 60 Hz). That leaves room for players' reducers, subscription evaluation and spikes. The viewers get what the AI battle leaves: B = 600 − R, where R is the 0-viewer sustained battle (200 fighters, `--keep-fighters 1`). The per-viewer budget at 216 is B / 216.

**The Spark's fast cores.** The Spark's recorded placement (docs/COMBAT_PHASE.md, "Fixture and method", "battle-laws"): its server pinned to the ten Cortex-X925 cores (`--cpuset-cpus 5-9,15-19`, 3.9 GHz). Unpinned runs swing 40–50% because the thread lands on the A725 cores. This series ran on dev-box only; dev-box has no cpuset controller and ran unpinned on uniform Zen 5 cores. X925 is placed against dev-box by the two arms both hosts ran on the same fixture, attention off, L1, sustained:
- **The AI-only battle:** X925 337–339 ms/s against dev-box 362–372, a ratio of **0.91–0.93**.
- **16 viewers on the 10 m ring, per viewer:** X925 11.6–14.0 ms/s (COMBAT_PHASE "battle-laws", sustained, as shipped) against dev-box 11.08 (E2 `b-off`), a ratio of **1.05–1.26**, central 1.16.
- The X925 runs used main `1511d5e8` with the battle laws; dev-box used `a6375a70e`. The AI's exact trims are in both. The ratio carries that difference too: an estimate, not a same-build comparison.

| Host | R, ms/s | B = 600 − R | Per-viewer budget at 216 | In dev-box terms |
|---|---:|---:|---:|---:|
| dev-box (L0, 4 runs, 370–392) | 377.6 | 222 | **1.03** | 1.03 |
| dev-box, fighters at 10 Hz (estimate: X925's −17% applied) | ≈313 | ≈287 | 1.33 | 1.33 |
| X925, pinned (L1, 2 runs) | 338 | 262 | 1.21 | **1.05** (0.96–1.15) |
| X925, fighters at 10 Hz (`combat_eval_hz` 10, L1, 2 runs) | 283 | 317 | 1.47 | 1.27 (1.16–1.40) |

**So the gate is not decided by the host.** X925's cheaper AI tick is offset by its dearer per-viewer work, and the two hosts' per-viewer budgets agree within about 5%. The Spark's AI trims are what move the budget: 10 Hz fighters are worth about +25%.

## 7. The bottom line, worked out

### 7.1 Clean per-viewer costs at the contract's density (set d)

Unsaturated, L0, 26–32 m ring (about 70 in sight), 2 runs each, against four 0-viewer L0 runs. Every arm includes the viewer as a character and the keep-alive's moves (0.15–0.18 of it).

| Arm | Viewers | Ticks/s | ms/s a viewer | Plus the game's views (§3.3) |
|---|---:|---:|---:|---:|
| Floor (attention on, ceiling 0, as today otherwise) | 64 | 58.6–59.0 | 1.78 (1.70–1.87) | 1.91 |
| Plausible cuts (module memory, lines every 1 s, hearing at 1 Hz, feed off as the trimmed feed's bound) | 64 | 59.2–59.4 | 1.29 (1.20–1.38) | 1.34 |
| Plausible cuts plus `heed` with holds at ceiling 16, crowd rows on | 64 | 59.1–59.3 | **2.36** (2.27–2.45) | **2.41** |
| The same | 128 | **45.1–48.1** (saturated: 621–640 ms/s) | – | – |

On the far ring at 216 (L1, saturated, shares only), the plausible-cut arm's 1.26 ms/s a viewer splits as:
- **delivery about 0.75:** sweep 0.51, frames 0.11, views 0.11, evaluation 0.02;
- **the viewer as a character about 0.42:** fold 0.12, activity 0.16, wakes 0.09, motion and slots 0.05;
- **the keep-alive 0.11.**

### 7.2 The largest viewer count at 60 Hz in a 200-fighter battle

N = B / f, with f the per-viewer cost (§7.1, with the game's views) scaled by host. Ranges come from the per-viewer run ranges and, on X925, the 1.05–1.26 ratio.

| Configuration | dev-box | dev-box, fighters at 10 Hz (estimate) | X925 | X925, fighters at 10 Hz |
|---|---:|---:|---:|---:|
| Plausible cuts plus attention at 16 (the playable case) | **92** (89–95) | ≈119 | **93** (86–103) | **113** (104–125) |
| Floor as today, nobody attended | 116 (111–121) | ≈150 | 118 (109–130) | 143 (132–158) |
| Plausible cuts, nobody attended | 166 (155–178) | ≈214 | 168 (155–186) | 204 (188–225) |

- The 128-viewer run confirms the first row: 128 × 2.36 + 378 ≈ 680 ms/s, beyond 600. It ran at 46.6 ticks/s.
- **If the tick could take the whole thread** (1,000 ms/s, no room for players' reducers or spikes), the playable case would reach about 258 on dev-box. That is not a 60 Hz contract: 216 players' own moves, at about 0.2–0.3 ms each, need part of that room, and the tick's p99 would pass 16.7 ms.

### 7.3 What 216 would take

216 needs f ≤ 1.03 ms/s (dev-box), ≤ 1.05 (X925 in dev-box terms) or ≤ 1.27–1.33 with 10 Hz fighters. From 2.41 today with the plausible cuts:

| Step (all estimates unless marked) | f after |
|---|---:|
| Today with plausible cuts and attention 16, with game views (measured) | 2.41 |
| Attended cost halved: v2's planned per-individual work, the attended 1.07 → about 0.55 | ≈1.9 |
| Hearing as buckets, `heard_sounds` gone (contract density: the sweep's hearing share plus 0.05) | ≈1.75 |
| Lines as a keyed table in place of `my_experience` (0.08 → 0.02) | ≈1.7 |
| The keep-alive removed (harness; a real player's input costs about as much at 0.5–1 move a second) | ≈1.55 |
| Remaining: the viewer as a character (≈0.42), sight (≈0.15), frames' bookkeeping (≈0.1), the attended (≈0.55), the rest | – |

**Even all of it lands at about 1.5 ms/s a viewer, not ≤1.3.** On dev-box that is about 150 viewers; with 10 Hz fighters on X925, about 210. So 216 at 60 Hz on one database thread needs, beyond every cut here, a cheaper character (the AI's per-character costs) or a smaller attended cost than v2 plans. The alternative is the structural one: per-viewer delivery off the database thread, or the battle split across databases.

### 7.4 Assumptions

- **The fixture's density:**
  - the contract's 216 is the 26–32 m ring, about 70 in sight;
  - at 10 m (110–128 in sight) every viewer costs about twice as much. The dense limit is **about 50**: the dense plausible-cut arm (3.05 at L1, about 2.55 without profiling), plus `heard_sounds` (0.18) and E2's dense attended cost at 16 (about 2.0 at L1), comes to about 4.5 ms/s a viewer. That is an estimate from measured pieces.
- **The "plausible cuts" are measured as switches.** Their real versions (feed trimmed to the attended, lines as a table, buckets) are bounded, not built. The feed-off arm is the bound of a trimmed feed; a trimmed feed costs a little more.
- **Attention is E2's prototype with `heed` at `aa3d4d9e2`** and crowd rows on; capacity is the ceiling (no Rhai law).
- **Players' input is not in the floor** beyond the keep-alive's 0.67 moves a viewer-second.
- **X925 is scaled, not run** (§6). The 10 Hz-fighter figures on dev-box apply X925's measured −17% to dev-box's reference.

## 8. What was not measured

- **A run on X925.** The Spark's numbers are from its recorded series (docs/COMBAT_PHASE.md), on another build, scaled by two shared arms (§6).
- **The real versions of the cuts.** The feed trimmed to the attended, lines as a keyed table and hearing as buckets are bounded from measured pieces (the feed-off and hearing-off arms, the probe's per-row costs), not built.
- **Players' input at real rates:** `human_move` costs about 290 µs at 16 viewers and 165 at 216 (saturated). Real play's command rate is unknown here.
- **The 0-viewer L0 offset:** the 0-viewer arm ran higher at L0 than at L1 (§3.1). Unexplained; the per-viewer figures each use their own level's reference, and set d's four L0 references (370–392) bound it.
- **Set e's totals** (a foreign `git` process ran through it; only its view metrics are used).
- **The probe at 1, 16 and 64 subscribers** is one run each; 216 is four.
- **Dirty trees:** set d logged `dirty=1` (the `--game-views` edit to `battle_viewers.py` and gate-load, uncommitted then, unused by set d: its gate-load binary was built before the edit). Every other set logged `dirty=0`.
- **Not separated within L0:** profiling's 0.5 is the L1−L0 difference in totals; which parts it inflates is not split.
- **Tick latency at the fitting counts** (p99 against 16.7 ms) was not measured at L0. The L1 dense runs' tick p99 was 11.3–12.3 ms.
- **Memory:** WASM memory and RSS were recorded per run, not analysed; E2 found WASM memory flat.

## Evidence

- **Code** (branch `viewer-floor`, never for main):
  - `33fec52db`: the switches and frame spans;
  - `be20e52cb`: the probe fixes;
  - `231499862`: `--game-views`, and `e2_report` reading L0 runs.
  - The series module `vf-cullet` is `0b1d6e741f80` (the authority at `33fec52db`); main's module for the off-equals-main check is `cde8d300c340` (`a6375a70e`).
- **Runs** (dev-box, worktree `t3-b749c655`, `.local/vf/`):
  - `runs/` holds every arm's run directory: `battle-viewers.json`, `v<n>/metrics.json`, `threads.json`, the module log at L1 and L2, `procs-*.txt` and `rss.json`;
  - `runs/series.log` holds each set's module hash, commit, dirty count and each run's load;
  - `tables.json` (`vf_tables.py`) holds every figure in §3 and §7;
  - `f-L2-r1-spans.json` and `f-all-L2-r1-spans.json` hold the L2 splits;
  - `probe/` and `probe-all.json` hold the probe;
  - `det-off/` and `det-negative/` hold the off-equals-main check and its control;
  - the scripts: `series.sh`, `series-d.sh`, `series-e.sh`, `probe.sh`, `det.sh`, `build.sh`;
  - `failed/runs-nodocker/` holds set a's first start (no battle ran).
- **The SpacetimeDB source:** a clone of `clockworklabs/SpacetimeDB` at `v2.14.1` (`a0bf6be`) in `.local/vf/stdb`, used for reading only.
- **Archived** to `~/archive/worktree-evidence-20261122/viewer-floor.tar.zst` (286 MB, sha256 `cd91eff29d31…`, in full in the `.sha256` beside it; build trees, the SpacetimeDB clone and the extracted E2 runs left out: E2's are in `attention-e2.tar.zst`).
- **Related:**
  - [ATTENTION_E2_COST.md](ATTENTION_E2_COST.md) (E2; its §3.3 is corrected here, §5.4);
  - [ATTENTION_BUDGET.md](ATTENTION_BUDGET.md) v2;
  - docs/COMBAT_PHASE.md (the budget, the X925 placement and its sustained series);
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md).
