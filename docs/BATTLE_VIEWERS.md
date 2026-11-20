# Battle viewers: the per-viewer cost of a dense battle (design note)

Status: a design note for the reviewer, 2026-11-19 (branch `frame-views`, dev-box). Nothing here is built. It follows the frame-views series ([Tick rate](TICK_RATE.md#post-review-series-acceptance)): a 200-fighter battle runs at 60 ticks a second with no player watching, 53.7 with 16 players inside it and 2.8 with 216 player fighters (the contract's case). The cost is per player viewer, as tick-rate found. Tiers and cues did not move it.

## Where the time goes (main, 216 player fighters within 9 m, 120 s)

The tick's whole call is 836 ms a wall second at 2.8 ticks a second, about 300 ms a tick. Its own WASM is 252 ms/s: perception sweeps 109, activity 50, fold 42, wakes 31, frames 15. Per-viewer views re-run inside the tick's transaction take about 540 ms/s:

| View | Calls/s | ms/s with materialization | µs a call | Rows a call |
|---|---:|---:|---:|---:|
| `seen_characters` | 549 | 257 | 468 | about 216 |
| `seen_bodies` | 458 | 125 | 274 | about 215 |
| `my_combat` | 556 | 74 | 133 | the onlooker feed |
| `seen_fighters` | 344 | 53 | 153 | about 200 |

Three costs grow with viewers × crowd (V × C, about 47,000 pairs here):

1. **View rebuilds.** In 2.14.1 a per-sender procedural view re-runs whole when any row it read changed (`materialize_view_arg_hash` deletes and re-inserts the sender's whole result), and its old read set is dropped by walking every view's read set (`remove_view_call`). A refresh costs the scene, not the change.
2. **Sweeps.** Each player's sight and projection over everyone in sight every 200 ms (`perception::sweep_one`): at 60 ticks a second, 216 sweeps of about 216 creatures each, about 1,080 a second. At the measured cost per sweep (0.4–0.5 ms here) that alone is about half the database thread.
3. **Copy writes.** Every change of a creature is copied into each of its viewers' rows at their frames: C changes × V viewers, each an index update, a commitlog record and, today, a view refresh.

## Options, costed

Documentation read for this note: [views](https://spacetimedb.com/docs/functions/views/) (shared anonymous views, "entities in region X", views with arguments; per-sender views cost one computation and one change-tracking set per subscriber), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [their semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics) (one delta per transaction per client; overlapping queries cost twice), [performance](https://spacetimedb.com/docs/tables/performance/), [row-level security](https://spacetimedb.com/docs/how-to/rls) (experimental; the docs prefer views), [event tables](https://spacetimedb.com/docs/tables/event-tables/). Source: the `v2.14.1` tag (`a0bf6be`), as in [Tick rate](TICK_RATE.md#spacetimedb-documentation-and-source-consulted-1).

### A. Shared views per cell or region

An anonymous view with an argument (a cell) is materialized once per argument and shared by every subscriber who passes it (views docs, "Views with Arguments"; 2.14.1 `ViewCallInfo` keyed by view and argument hash, no sender). 216 viewers in one battle cell would share one materialization, refreshed once per change instead of once per viewer.

- **Cost:** one rebuild of the cell's result per transaction that touches it (about 200 rows), then subscription evaluation of the delta for each subscriber (search-argument pruning per argument). From V × C rows a frame round to C rows per tick.
- **Against it: perception.** A cell view shows every creature in the cell to every subscriber, whatever each one can see: walls, the field of view, night, a far label (`someone too far away to make out`). AGENTS.md: spatial subscriptions are not permission boundaries; perception is enforced on the authority. A shared view can only carry what everyone in its scope may know: for bodies, nothing a wall or a facing hides. In an open-field battle that is most of it, but the authority cannot know a client stays in its lane.
- **Usable for:** public, sight-independent facts (weather, a structure's state) and possibly aggregates that reveal nothing per creature (a crowd's count and extent per cell, see C). Not for bodies.

### B. Per-viewer copies subscribed as tables, not views (row-level security)

The copies are already per viewer, keyed by `viewer`. Made public with a row-level-security rule `WHERE viewer = :sender` (as the cue tables are), a client subscribes `SELECT * FROM motion_seen` directly, and 2.14.1 evaluates only the changed rows: the RLS equality is a search argument, so each written copy row is matched to its one viewer's query through a delta index (`search_args`, `DeltaTableIndexes`). No view, no rebuild, no read set.

- **Cost:** per changed copy row, one query evaluation and one encoded row. The view rebuild cost (about 540 ms/s in the battle; 160 ms/s of scene views on Cullet at 216 walkers) becomes about the copies' delta, which the frames already write. The read-set walk shrinks by the views removed (216 × the views moved).
- **Applies to:** `motion_seen`/`motion_near`, `fighter_*`, `doing_*`, and `projected` (`seen_characters` is a projection of its rows: the client would read `projected` itself, or a projected table shaped as the client row), `combat_seen` (`my_combat`), `line_seen` (`my_experience`).
- **Against it:** RLS is experimental (accepted conditionally for the cues, with a gate and a kill switch); this puts the whole perception boundary on it. Every table moved needs the cue tables' safeguards: the isolation check on each table in the gate, the subscribe-all guard (the owner bypasses RLS), the upgrade note. Adding RLS rules disconnects every client once. Columns a client must not see (a copy's private fields) need a client-shaped table.
- **Evidence it is cheap:** the post-review series' "cues off" arm (the RLS subscriptions to the cue tables, no rows) cost nothing measurable; the cue rows themselves cost about 1 µs of evaluation each.

### C. A bounded far tier, with aggregated crowd rows

Copies for the nearest N and the engaged (the near tier, `NEAR_MAX` 32), and for the rest of a dense crowd one row per cell or sector per viewer: a count, a centre and spread, a dominant motion (what a renderer draws as a crowd), computed from what the viewer perceives.

- **Cost:** per viewer, N + a few aggregate rows instead of C: at 216 × 216 the copies and their views shrink about 6 times at N 32. Sweeps still decide sight for each creature, but could stop projecting the aggregated ones (the sweep's projection is about half its cost, `perception::kept_sweep`).
- **Against it:** a client would not see individual far fighters in a dense battle (only a crowd). A game-design call: the contract asks for a 200-character battle at 60 Hz, not that every one is drawn individually by every player. The minds are untouched (they read the tables as the owner).

### D. A far cadence that follows density

Far frames every `interval(far)`, clamped up to a density-driven bound (for example 250 ms past 64 in sight, 500 ms past 128), so each viewer's far view re-runs less often in a crowd.

- **Cost:** cuts rebuilds in proportion, but each rebuild still costs the whole far scene, and sweeps and copy writes are unchanged. The frames' budget already does this under load (it shrinks after missed boundaries); in the battle the tick is far past what the budget controls (sweeps and the views of whatever does refresh). A help, not a fix.

### E. What 2.14.1 makes cheap, from the source

- Event tables: no view, no read set, delta-only evaluation (the cues).
- RLS search arguments with delta indexes: per-row matching to one subscriber (B).
- Anonymous views shared per argument (A).
- Not cheap: per-sender procedural views (whole rebuild), the read-set walk (every view's set per refresh), query-builder views (in 2.14.1 table-wide dependencies, the same materialization).

## Recommendation

1. **B first, measured on one stream:** move `motion_*` (the bodies) to RLS-filtered table subscriptions behind a law (like the cues), keeping the views during the transition, and measure the battle sweep (0, 1, 4, 16, 216 viewers) and Cullet at 216 against main. If the view cost goes as expected, move `fighter_*`, `doing_*`, `projected`, `combat_seen` the same way. Expected: the battle's ~540 ms/s of views falls to the copies' deltas; on Cullet the frames' budget no longer pays per-refresh fixed costs, so far freshness should improve too.
2. **Then the sweep's V × C** (about half the thread at 216 × 216 and 60 Hz): density-adaptive sweep cadence and projection only for creatures whose projection can have changed (the kept sweep already avoids re-projecting most; what remains is sight).
3. **C if needed** after 1 and 2, as a design decision for the owner (crowds drawn as crowds).
4. **A** only for public, sight-independent data.

Each step: its own branch, the battle sweep and the 216 Cullet series as the acceptance, the perception-content proofs (`sweep_rows`, `look_rows`, `cues.py`-style isolation per moved table).

## Not known yet

- The per-row cost of RLS table subscriptions at 216 × 216 under a battle's change rate (the cue arms measured about 4,000–9,000 rows a second; a battle's copies are tens of thousands).
- How much of the tick's 300 ms in the battle is the commit and the subscription evaluation (the whole-call residual) once views are gone.
- Whether 2.14.1's `remove_view_call` walk falls with fewer views as expected (it scales with all views' read sets).

## Addendum: B on the motion stream (design, not built)

Status: 2026-11-19, branch `battle-views` (cut from `origin/main` `3df6e1f10`), for the reviewer and the dev-box coordinator before any building. Approved direction: B first, the motion stream only, behind a law, with the cue tables' safeguards.

### What 2.14.1 allows (versioned source, `v2.14.1` `a0bf6be`)

- Changing a table's access is an automatic migration with no disconnect (`auto_migrate.rs`, `ChangeAccess`; `engine/src/update.rs`, `alter_table_access`), but adding, removing or changing an RLS rule disconnects every client once (`ensure_disconnect_all_users` when `changed`). Adding a table does not disconnect; appending a column does (frame-views' rule). So the motion stream gets a **new** public table with its RLS rule in the same publish; the existing private tables stay unchanged.
- Module code, reducers and views alike, reads tables unfiltered (the host's `instance_env` has no RLS path; RLS is applied in subscription compilation and SQL, `core/src/subscription`, `sql/execute.rs`). Views can therefore keep reading the copies wherever they live.
- An RLS rule `viewer = :sender` compiles to a search argument with delta-index pruning, so a changed row is matched to its one viewer's query, not evaluated per subscriber (frame-views reading of `subscription.rs`; measured on the cue tables at about 1 µs a row). The owner bypasses RLS. The SDK's `subscribe_to_all_tables` names every public table and is filtered; the server's `SELECT * FROM *` is filtered too (cues.py, both ways).
- Documentation: [RLS](https://spacetimedb.com/docs/how-to/rls) (experimental; the docs prefer views), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics), [views](https://spacetimedb.com/docs/functions/views/), [indexes](https://spacetimedb.com/docs/tables/indexes/), [performance](https://spacetimedb.com/docs/tables/performance/).

### The table and where the copies live

One new public table, `seen_body_copy`, RLS `SELECT * FROM seen_body_copy WHERE viewer = :sender`:

| Column | Type | Note |
|---|---|---|
| `id` | `u64`, primary key | the copy key `frame::key(viewer, body)`, as the private copies |
| `viewer` | `Identity`, btree | the RLS column; the frames' per-viewer lookups |
| `near` | `bool` | the tier; btree `(viewer, near)` for the tier views' read sets |
| `moving` | `Moving` | exactly the row `seen_bodies` returns today (nothing a view hides is in it) |

One table, not two: table subscriptions have no read sets, so the tier needs no table of its own, and a tier change becomes one update instead of a delete and an insert. The `(viewer, near)` index keeps the views' tier separation (2.14.1 tracks a view's read set per index key, `views_for_index_seek`).

**A viewer's motion copies are all private or all public**, never mixed: a viewer's copies move between `motion_seen`/`motion_near` and `seen_body_copy` in one transaction. So the views need no route row: `seen_bodies_near` seeks `seen_body_copy` by `(sender, true)` and, when that is empty, reads `motion_near` by `sender` as today (and the same for far and the untiered view). With the law off, the only addition is one empty index seek per view call; this is what "off equals main" has to measure.

### The law: `motion_tables_on`

A value-only law under the Spark's override layer, in the delivery-only class with `cue_transport_on` and `near_tier_on`: read once per tick from the layer's snapshot, stable within the tick, no Rhai, validation, script row or cache dependency; default **off** until acceptance; a `law_about` line in `skills.rhai` like the other two. The views never read it (they follow the rows).

- **On:** each viewer's next frame moves its copies into `seen_body_copy` and writes there from then on. Spread over one frame round; the frames' row budget counts the moved rows.
- **Off (the kill switch):** the tick that first sees it off moves every public copy back to the private tables in that one transaction, so a leak through a changed RLS stops at once. A one-off burst: about 9,000 rows on Cullet at 216, about 47,000 in the 216-viewer battle. A stall of that one tick is accepted for a kill switch.
- **Code path with the law off:** a world that has never had it on writes nothing to `seen_body_copy`; the frame checks one bool. `frame::tests` gains: law off writes no public copy and takes main's path; a flip on moves a viewer's copies whole; a flip off empties the table in one tick; tiers in the public table match the private tiers.
- **Module memory:** `Viewer::public` (whether this viewer's copies are public); a fresh instance learns it at the viewer's first, full frame from whether `seen_body_copy` holds any of its rows.

### Clients

Views stay for the transition (old clients, verify-player's SQL, gate-load without the new flag), and stay correct with the law on or off. A client on tables subscribes `seen_body_copy` and `my_body` in place of `seen_bodies_near`/`_far`; the cue rule is unchanged (a cue stands until that creature's next copy row, now a `seen_body_copy` insert, update or delete). With the law off, the table is empty and such a client falls back to the tier views, as the laptop's client already switches on the delivery laws. The authority can merge alone with the law off; the laptop's client change follows, and the law goes on after both.

### Data paths

- **Written:** per viewer, the same copies as today, moved, not doubled; written at frames (far 33–100 ms, near at most every 500 ms, cues between). Tier change: one update. Indexes: pk, `viewer`, `(viewer, near)`.
- **Read:** frames by pk; views by `(viewer, near)` or `viewer`; subscriptions by the RLS search argument.
- **Recipients:** the one viewer (RLS); the owner only if it subscribed, which the guard forbids.
- **Retained:** the current scene only; rows go when a creature leaves sight. Growth bounded by sight, as today; commitlog the same rows, a little less for tier changes; the off flip adds one burst.

### Safeguards, each for `seen_body_copy`

1. **Isolation gate:** verify-client `scripts/motion_tables.py`, scene-gate case `motion_tables` in the `client` group, built on `cues.py`'s harness. A, B, C and an anonymous connection subscribe `seen_body_copy` from the start (the initial rows checked, not only deltas), subscribe all by name, `SELECT * FROM *`, B queries `WHERE viewer = 0x<A>`, and B's SQL asks for A's rows. Every probe must be accepted: a rejected subscription fails the check, not passes it vacuously. Every row names its receiver; C and anonymous get none of A's or B's; A's rows equal `seen_bodies` (union) and its tiers equal the tier views. Then the law goes off: within one tick the table is empty to the owner's SQL and the views still give the same scene; it goes back on and the rows return. The law is put back as the world had it.
2. **Owner subscribe-all guard:** `drive.py`'s source guard names `seen_body_copy` among the tables an owner program (mind, viewer) must not name; the route proof (the SDK's subscribe-all and `SELECT * FROM *` as a player) is in `motion_tables.py`, as in `cues.py`.
3. **Kill switch off equals main, measured:** Cullet 216 paired arms, law off against main (`3df6e1f10`), and the 16-viewer battle; the frame test above.
4. **Version-pin notes:** `seen_body_copy` added to TICK_RATE's list of every RLS-filtered table, the upgrade checklist (run the isolation gate on a new SpacetimeDB before the law goes on; on a failure, law off), and the one-time disconnect when the rule is published.
5. **RLS evaluation cost at 216:** subscription update CPU ms/s, rows/s and µs a row, law on with players on the table against law off with players on the views (Cullet 216, and the 216-viewer battle).

`maintain-verification-skill` on verify-client in the same change: `features/perception.md`, `permissions.md`, `visibility.md`, the public and private inventories in `drive.py`, `SKILL.md`, the gate case; and verify-core's frame notes for the law.

### Measurement

Baseline: the Spark's `battle-remeasure` tables (merged main, frame-views defaults and both laws off, at 0 and 216 viewers), not re-run here. Arms here, on my own scratch server `bv-stdb` (volume `bv-stdb-data`, 127.0.0.1:3344, v2.14.1), in a quiet window you set, with the gate lock and loads recorded:

- **Battle** (200 fighters, `battle_viewers.py`): 1, 4, 16 and 216 viewers, each with the motion law off (players on views) and on (players on the table). One run per arm, 120 s.
- **Cullet 216** (7 clusters of 31, `look_cost.py`): main, law off, law on (players on the table), three runs each, interleaved.
- **Reported:** ticks/s (server counter), late share, two-slot gaps, top phases, motion and scene view ms/s, subscription update CPU, rows/msgs/kB a second, commitlog bytes, WASM memory, near and far freshness (SDK and `frame staleness`), the off flip's burst tick.
- gate-load gains `--motion-tables` (subscribe `seen_body_copy` in place of the motion views).

**Expected, from the series:** on Cullet 216 the motion views cost 106–165 ms/s (about the whole of the scene views' 110–170 ms/s), and a table subscriber should pay roughly its rows' evaluation instead (about 1 µs a row at about 20,000 rows/s in total); the frames' budget, which pays that refresh, should loosen, so far freshness should improve. In the battle the motion views are 125 of about 836 ms/s, so the 216-viewer battle will stay far from 60 ticks/s; the 4- and 16-viewer arms show the mechanism, and `seen_characters` (257 ms/s) is the next stream by cost.

### Not in this step, and (C)

Fighters, doing, `projected`/`seen_characters`, `combat_seen` follow the same pattern only after this one is measured. The sweep's V × C (recommendation 2) is untouched. Option C (a bounded far tier with crowd rows per cell) stays as sketched above, ready as a design decision for the owner if B and the sweep work are not enough.

## Addendum 2: `seen_characters` on the same mechanism, and a slimmer row (design, not built)

Status: 2026-11-19, branch `battle-views`. The GC approved it; built the same day as designed (`seen_character_copy`, `characters_table_on`, `perception::proj_*`; docs/PERCEPTION.md "Projections mirrored as a table"). The slimmer `seen_body_copy` row was built at 98 B (the counts below said 97; the exact sum is 98). It follows the motion stream's series (`.local/bv/evidence/20261119-190200-series/bv-report.md`): on Cullet 216 the table removed the motion views (84 ms/s on main) and two-slot gaps (68–125 on main, 0–1 on), at no visible update-CPU cost, but per-player bytes rose about 40%. `seen_characters` is the next stream by cost: 257 ms/s in the 216-player-fighter battle (468 µs a call, about 216 rows), about 90 ms/s on Cullet 216.

### What `seen_characters` reads, from source

`seen_characters` (`perception.rs`) maps the viewer's `projected` rows (private; `id` auto-increment, `viewer`, `body`, `own`, then exactly the `SeenCharacter` fields: name, label, kind, stage, folk, style, band, hp, max_hp, look) one to one. `projected` is written at 14 sites in the authority: the sweep (a creature comes into sight, whom the viewer knows changes, a reveal starts or stops, its own row), the frames' bands (`frame::show_band`, at most every `BAND_MS`, 1 s), `look.rs`'s relook (every viewer's row of one body) and the deaths and forgets; it is read at about 20 sites (the sweep's projection checks, the frames' band, the looks). Nothing outside the authority reads it.

### Design: a mirror, not a move

Unlike the motion copies, `projected` stays where it is: it is the authority's own working state, read in many places, and moving it would put every one of those reads behind a "which table" test. With a new law `characters_table_on` (value-only, delivery class, read once per tick, off by default), every write of a `projected` row is also written to a new public table `seen_character_copy` (`id` = the projected row's id, `viewer` with the RLS rule `viewer = :sender`, and `row`: the `SeenCharacter` the view returns). One helper takes the 14 write sites (`perception::put_projected`, `drop_projected`), so no site can write one table and not the other.

- **Whole per viewer.** With the law on, a viewer's next frame fills its mirror from its `projected` rows in one transaction (all of them, or none yet); from then on the helper keeps it in step. A client never sees a partial set.
- **The kill switch.** Off: the first tick that sees it deletes every mirror row in one transaction. Nothing moves back (`projected` is still whole), so it is simpler and cheaper than the motion switch: one delete per row.
- **The view is unchanged** (`seen_characters` still reads `projected`), so a client on the view, SQL readers and the minds see exactly what they see now, with the law on or off. With the law off the only addition is one `if` per write.
- **Cost model.** Each `projected` write becomes two (the mirror row is about the view row plus 40 B). The writes are rare compared with motion: on entry, on a knowledge or reveal change, and bands at most once a second per pair. Against that, a client on the table re-runs no `seen_characters` view (468 µs a call at 216 rows in the battle). Expected: in the battle the 257 ms/s of the view falls to the mirror writes (an estimate: on the order of 10,000–20,000 band writes a second while everyone is hurt, at a few µs each, 20–60 ms/s), and the subscription evaluation of those rows (about 1 µs a row, as measured on the cue and copy tables).
- **Privacy.** The mirror row is the view's row, nothing more (no controller, no home: what `SeenCharacter` already omits). The same safeguards as `seen_body_copy`: an isolation script (extend `motion_tables.py` into `perception_tables.py`, both tables, including the mutation proof without the rule), the scene-gate case, `RLS_TABLES` and the owner guard in `drive.py`, the pin list, and the rollout rule.
- **Rollout.** Its RLS rule disconnects every client once when published. The reviewer's plan merges the motion change alone first; this rule would then be a second disconnect at its own merge window (mind service restarted, never during a play-test). Landing both rules in one publish would cost one disconnect instead of two; the reviewer's call.
- **Measurement.** Cullet 216 (main, law off, law on with players on the table) and the 216-player-fighter battle (`look_cost.py --battle 216`), where the view costs most; the kill switch timed with the control law change, as for motion.

### A slimmer `seen_body_copy` row (and the same for the mirror)

The row is the 64 B `Moving` plus the copy key (8 B), the viewer's identity (32 B) and `near` (1 B). What 2.14.1 allows:

- **The identity has to stay.** `:sender` is an `Identity`, so the RLS column is 32 B. A rule that joins a smaller key (`… JOIN player ON seen_body_copy.viewer_char = player.character WHERE player.identity = :sender`) is accepted (RLS rules expand into join trees, `expr/src/rls.rs`), but it loses the per-row pruning: search arguments are taken only from point scans and equality filters on the table that is read (`physical-plan/src/plan.rs`, `search_args`), so the `:sender` argument would sit on `player`, and every changed copy row would be evaluated against every subscriber's query: the V × C cost this work removes. Not proposed.
- **Compression does not help these messages.** The SDK asks for Brotli by default, but the server compresses only messages (and query updates) over 1 KiB (`client/messages.rs`, `decide_compression`; the SDK's `with_compression` notes the threshold). A player's messages on Cullet average about 420 B (24.6 a second, 10.4 kB/s), so most go uncompressed.
- **What can go, safely:** the duplicate creature id inside `moving` (4 B; it is the key's low 32 bits), and the 8 B key replaced by a 4 B copy id (an auto-increment `u32` per (viewer, creature) pair, the pair found by the `(viewer, body)` index the frames already need, with `body` replacing the moved-out id). Net 105 → 97 B, about −8% a row; a guess of about −5% of the player's bytes. Folding `near` into the key saves 1 B more at the cost of the tier views' index; not worth it.
- **Fewer rows instead of smaller ones:** the near tier's copies follow every 500 ms behind cues; the far tier's at each frame. Most of the bytes are far-tier updates (each an old and a new row). A far cadence that follows the far tier's size (option D above) would cut bytes in proportion, and the cues keep what matters fresh. That is a separate measured step.

So the honest answer to "cut the 40 B" is: about 8 B can go without a cost; the 32 B identity is what row-level security in 2.14.1 needs on each row to stay per-row cheap. Before the law goes on: build the 97 B row, and report kB per player against main on Cullet 216, as asked.

## Addendum 3: the copy tables' privacy at battle density (copy-privacy, built 2026-11-20)

The table arms' privacy proofs that the Spark's diagnosis listed as still to run (docs/COMBAT_PHASE.md, "Evidence and coverage"), required by the GC before the default-on flip (Rollout, part 2). `motion_tables.py` proves isolation in a small scene (three players, a stranger); this proves it where the tables will run: a battle, hundreds of viewers, thousands of copy rows a second, copies moving between tiers, viewers dying and joining again. Tooling only: no table, law, reducer or rule changes, so `RLS_TABLES`, the owner guard, the pin list and the laws are unchanged.

- **Every row a viewer receives** (`gate-load`): each `seen_body_copy` and `seen_character_copy` row a viewer's connection receives, its initial rows and every insert and update, is checked against the connection's own identity, from the connection on, across deaths and rejoins. Each player reports the rows received and the foreign ones (`privacy`), and on stdin `held` prints the copies each holds now.
- **`battle_viewers.py --privacy`** (with `--motion-tables --character-tables` and both laws on) adds, during the measured window, through the verify-client probe:
  - (a) an anonymous connection on both tables;
  - (b) a spectator player (its own identity, joined, not a viewer) subscribing every public table by name, `SELECT * FROM *`, and the SDK's own `subscribe_to_all_tables` (the GC's addition). That helper names every table of the generated bindings, private ones included, so the server refuses it whole for a player (`no such table: acquaintance … may be marked private`): the check requires that refusal (or, were it accepted, no foreign row);
  - (c) a viewer subscribing another viewer's rows by identity, and viewers' own SQL (only their rows, one that sees bodies now) and their SQL for another's (none).

  After the window, (d) paused, eight sampled viewers (those that died and joined again first; with the keep-alive none died in these arms, so the sample is spread over the ring) compare, each through its own connection, `seen_body_copy` with `seen_bodies`, its `near` flags with the tier split, and `seen_character_copy` with `seen_characters`; (e) the kill switch with every viewer connected: both laws off by row, both tables empty to the owner and in every viewer's cache; on again, the owner's counts every 0.5 s for 10 s, then paused, the same comparison. Last, every viewer's run-long count: no foreign row, and rows of both tables received (not vacuous). 14 checks; `<out>/privacy-v<count>.json`, exit 1 on a failed one.
- **The negatives** (one-off proofs, GC): the same 16-viewer arm on Cullet modules built without `SEEN_BODY_COPY_FILTER`, then without `SEEN_CHARACTER_COPY_FILTER`, fails 8 and 9 of the 14 checks: every isolation check, the viewers' own counts and both snapshots; the refused SDK helper stays refused. They are not gate cases.
- **The gate case `copy_privacy`** runs `--privacy` at 16 viewers round a 60-fighter battle (26–32 m ring, keep-alive, 30 s window) on the island module the case's own run launched, only when a merge touches `frame.rs`, `perception.rs`, `tables.rs` or the drivers (`COPY_PRIVACY_PATHS` in `scene_gate.py`; named with `--cases`, always).

**Results** (dev-box, `sg-stdb` v2.14.1, Cullet modules built from `origin/main` `8031d785d`, 200 fighters, keep-alive 0.5 s, paused placement, the battle after placing, every third viewer sampled for freshness; host load at each start below 4):

| Arm | Checks | Copy rows the viewers checked (body / character) | Foreign | Ticks/s | Viewer deaths (window) |
|---|---|---:|---:|---:|---:|
| 16 viewers, 10 m ring, 60 s | 14 / 14 | 156,144 / 55,043 | 0 | 58.2 | 0 |
| 216 viewers, 26–32 m ring, 60 s | 14 / 14 | 517,488 / 521,565 | 0 | 16.4 | 0 |
| 16 viewers, no body-copy rule | 6 / 14 (fails as it must) | | > 0 | | |
| 16 viewers, no mirror rule | 5 / 14 (fails as it must) | | > 0 | | |

Evidence: `.local/cp/runs/` on the dev-box (worktree, archived with the branch). Not covered: real game clients (the laptop's client switch has its own verify-ui proofs), reconnect storms, the 30-minute gate.

## Rollout: one change set, one play-test window (decided 2026-11-20; merged, defaults on)

**Where it stands.** Merged, defaults on: `bv-defaults-on` (dev-box) on the laptop's client switch (`battle-views-client`), gated as one change set after the copy tables' privacy proofs passed at battle density (Addendum 3, the GC's condition). `motion_tables_on` and `characters_table_on` are **on** in both default sets (`living/scripts/skills.rhai`'s law block and `Laws::default`); a world turns either off by its `law_override` row (the kill switch), and with both off the authority and the client take main's old path (`frame::tests::both_delivery_laws_off_take_main_s_path`, through overrides; `law_override_check` turns `motion_tables_on` off and back). Both copy tables were on main since `a407be01a` (battle-views), behind the two laws, off by default until this change. The laws are measured on (216 battle with keep-alive, 0 deaths: ticks 9.56 → 14.12/s; Cullet 216: far pairs p90 250–367 → 67 ms, `seen_characters` view 67.7 → 0 ms/s, kB/player +36% and +10%; the kill switch by override row 51 ms against a 2,333 ms reinstall; evidence `~/archive/worktree-evidence-20261120/battle-views-local.tar.gz` on the dev-box). No separate laws-on window is run before the client reads the tables: with no client on them, laws-on only costs bytes.

**One change set, so the next play-test after 11 gets all three at once:**

| Part | What | Who |
|---|---|---|
| 1. The client switch | The game client subscribes `seen_body_copy` and `seen_character_copy` while the law is on (read from the `law_override` rows), and main's untiered/tier queries while it is off, switching make-before-break as frame-views' tier switch does. Queued after feed-scope's client half. | laptop (Opus) |
| 2. The defaults | `motion_tables_on: true` and `characters_table_on: true` in both default sets: the law block of `living/scripts/skills.rhai` (about line 160) and `Laws::default` in `living/rules/src/script.rs` (about line 830). The both-off test keeps covering the off path through overrides. `living-check` and the scene gate (`cues`, `motion_tables`) on the merge. | dev-box |
| 3. The play-test build | Built from a main that has 1 and 2. A fresh world's genesis has no clients to disconnect, so the RLS rules cost nothing there; an *update* of an existing world disconnects every client once and needs a mind restart (never during an owner session). Island `init` fuel: with staged genesis on main, no concern; without it, check the guard's headroom first (98.6% on 2026-11-20). | laptop stages it |

**The window's checklist** (whoever stages the play-test):

1. The owner is not in a session (on the laptop, `.local/build-slots/session` is absent).
2. Main contains parts 1 and 2; the gate's `cues` and `motion_tables` cases passed on that merge.
3. Publish the play-test world from that build. For an existing world: one disconnect, then restart the mind service.
4. In the world, confirm both laws read on (`law_override` rows, or the defaults), and that clients subscribe the copy tables: `motion_tables.py` against the world's own identity, or a verify-client probe.
5. verify-ui: camera, talk and far scenarios pass with the laws on.
6. The kill switch: `set_world_law` `motion_tables_on` `false` (then `characters_table_on`), and within one tick the copies are back or gone, nothing split, the `script` row's revision unchanged; then on again. Record the tick times.
7. Note kB/s per player and near p90 in the play-test's notes, against play-test 11.

If a check fails, switch the law off by row (step 6) and leave the world running; the client follows the law.
