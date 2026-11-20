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

## Addendum 4: `my_combat` as a per-viewer event table, `combat_feed` (views step 2, built 2026-11-20)

The second step of the views track (docs/COMBAT_PHASE.md, "Plan", step 2), approved by the GC with the name `combat_feed` and the rollout of step 1.

**What it costs today.** A player's combat feed lives in the private `combat_seen` table:
- the two characters in a blow, written at once;
- onlookers, written at their next frame and kept 300 ms (`frame::ONLOOKER_MS`);
- a refusal, kept 4 s;
- a death and its witnesses, kept 2 minutes for the death screen.

Players read it through the per-sender view `my_combat`. In 2.14.1 a view is re-run for every subscriber whenever anything in its read set changes, so every write to `combat_seen` re-runs every viewer's `my_combat`. The Spark measured 185–189 calls a second at 75–84 µs each at 216 viewers, and the largest view left at 16 viewers once step 1 is on.

**As built.**
- **The table:** `combat_feed` is a public event table with `combat_seen`'s columns in its order. `id` is the matching `combat_seen` row's id; `viewer` is indexed.
- **Its rule:** one row-level-security rule, `SELECT * FROM combat_feed WHERE viewer = :sender` (`frame::COMBAT_FEED_FILTER`).
- **Its rows:** with the `combat_feed_on` law on, `combat::feed_row`, the one place every feed row is written, also inserts the event row (`CombatFeed::of`).
- **`combat_seen` stays private and unchanged.** It is still the source of truth for the death screen, reconnect and the frame's expiry, and the view stays for the observer, tools and verify-player.
- **The law:** `combat_feed_on` is a value-only delivery law (`VALUE_ONLY`), off by default until `combat-defaults` (2026-11-20), **on since**, switched per world by its `law_override` row with no reinstall. Off writes no event rows: main's path exactly.

**The client contract** (the laptop's half, a later change set):
- with the law on, subscribe to `combat_feed` instead of `my_combat`;
- on connect or reconnect, read `my_combat` once (subscribe, take the rows, unsubscribe; the Rust SDK has no one-off query), so a death screen survives a reconnect;
- the shared `id` lets `combat::ingest`'s `seen_ids` merge both sources unchanged;
- switch make-before-break, as the tier switch does.

**SpacetimeDB documentation** (read 2026-11-20; the pages show version 2.0.0, the pinned server and crates are 2.14.1):
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/): rows are broadcast at commit and then deleted, never kept in the client cache (only `on_insert` fires), and views cannot read them. They cannot be the lookup side of a subscription join. Their inserts are still recorded in the commitlog. They need the v2 WebSocket protocol, which the 2.14.1 SDK uses, and the `event` flag cannot change after the first publish.
- [Row-level security](https://spacetimedb.com/docs/how-to/rls): "applies to event tables with the same semantics as regular tables". `:sender` is the requesting client's identity. The module owner bypasses RLS. The feature is experimental (`unstable`, already enabled in the authority crate for the cue tables).
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): distinct overlapping queries are processed and serialized separately. Unsubscribing is asynchronous and removes the rows. Neither page states a per-subscriber cost for RLS or views.
- The pinned `spacetimedb-bindings-macro` 2.14.1 accepts `event`, as the three cue tables do on main.

**Data paths.**
- **Writes:** with the law on, one event row per feed row, to one viewer. Nothing is retained, so no table grows; the commitlog records each insert, as it does the cue tables'.
- **Reads:** no new reads. The law is read through the per-transaction law cache in `feed_row`.
- **Subscriptions:** a client on `combat_feed` drops the per-sender view, so no view re-runs for its feed. The observer and the mind service subscribe nothing new (`drive.py`'s owner guard names `combat_feed`).

**Safeguards.**
- **`combat_feed.py`** (verify-client), 17 checks:
  - isolation for players A, B and C, the anonymous connection, a peek by identity, a by-name subscribe-all, `SELECT * FROM *`, and the SDK's `subscribe_to_all_tables` (refused whole for a player);
  - the event rows and the `my_combat` rows are the same rows: ids and every field;
  - the GC's death-screen check: the killer, skill, damage, time, place and witnesses by the event rows alone equal what the view shows, and what a new connection's one read of `my_combat` shows;
  - the law off by row: no event row, the view still delivering, no reinstall.
- **The negative:** built without the rule, 8 of the 17 checks fail (one-off, recorded in the validation record).
- **The gate case `combat_feed`** (client group), plus `combat.rs` in `COPY_PRIVACY_PATHS`.
- **`RLS_TABLES` and the owner guard** in `drive.py`, and the pin list (docs/TICK_RATE.md).
- **At battle density:** `gate-load` checks every `combat_feed` row against its viewer, and `battle_viewers.py --combat-feed --privacy` runs it with the side probes.

**Measurement.** Dev-box, `sg-stdb` v2.14.1 (no core pinning: the dev-box has one core type). Cullet module `cf-cullet` from `03cc00683` (rustc 1.99.1, no sccache). 200 fighters, keep-alive every 0.5 s, paused placement, the battle after placing, tiers and cues, both copy tables on (the new defaults) with the viewers on them. 20 s warm-up, 60 s window, L0 (`--detail --no-profile`: server metrics, no spans). Two runs per arm, alternating base and feed; the 1-minute load was below 4 at each start (2.3–4.4 within the windows). No viewer died in any window.
- **base:** `combat_feed_on` off, viewers on `my_combat`.
- **feed:** on, viewers on `combat_feed`.

| Arm | Ticks/s | Views ms/s (of which `my_combat`) | Tick WASM ms/s | Whole tick call ms/s | DB thread CPU ms/s |
|---|---|---|---|---|---|
| base, 16 viewers, 10 m ring | 58.8 / 58.8 | 79.3 / 77.4 (42.6 / 41.5) | 369 / 364 | 490 / 482 | 498 / 491 |
| feed, 16 viewers, 10 m ring | 59.3 / 59.8 | 44.4 / 43.1 (0) | 381 / 369 | 470 / 456 | 476 / 462 |
| base, 216 viewers, 26–32 m ring | 19.9 / 21.1 | 78.0 / 75.1 (18.0 / 17.0) | 570 / 552 | 798 / 777 | 832 / 812 |
| feed, 216 viewers, 26–32 m ring | 19.6 / 22.2 | 64.5 / 62.2 (0) | 582 / 573 | 795 / 782 | 822 / 810 |

- **16 viewers, the dense case:** views fall by about 35 ms/s (`my_combat` 42 → 0) and tick WASM rises about 8 ms/s (the event inserts), so the database thread does about 26 ms/s less (about 1.6 ms/s per viewer, near the Spark's expected −37 ms/s of views).
- **216 viewers on the wider ring:** `my_combat` cost only 17–18 ms/s (145–150 re-runs a second at about 20 ticks a second: it is re-run only for viewers whose rows changed). The feed wrote 5,208 event rows a second (one per `combat_seen` row), about 3.3 µs of tick WASM each (+17 ms/s). The database thread is within the runs' spread (−6 ms/s), and ticks/s too.
- **So the step pays at battle density close in, and is about neutral where the tick rate is already low.** The insert per row (one indexed event row with a string per feed row) is the remaining cost.
- **Not measured:** the commitlog. Event inserts are recorded there (the event-tables docs), so the feed roughly doubles the combat feed's share of written WAL at 216 (5,208 more inserts a second); `battle_viewers.py` does not measure WAL. (Measured since: [rollout step 2](#commitlog-growth-with-combat_feed_on-measured-2026-11-20), about 96 bytes per event row, +5% of the commitlog at 216.)
- **Privacy at density with the feed:** `--privacy --combat-feed` (16 viewers, 10 m ring) passed 15 of 15. The viewers checked 97,354 `combat_feed` rows besides 172,076 body and 60,410 character copies, 0 foreign.

## Addendum 5: `seen_fighters_*` as a copy table, `seen_fighter_copy` (views step 3, built 2026-11-20)

The third step of the views track. The GC's decisions: fighters only (`seen_doing_*` cost 0.6 ms/s and stay views), and the Spark's two exact items in the same step. The second, the frames taking the sweep's health readings, waits for the Spark's review of the call shape and is not in this build.

**As built.** Step 1's mechanism, for the fighter copies.
- **The table:** `seen_fighter_copy` (public; `id`, `viewer` indexed, `body`, `near`, `fighter`), with the row-level-security rule `SELECT * FROM seen_fighter_copy WHERE viewer = :sender` (`frame::SEEN_FIGHTER_COPY_FILTER`). It replaces the private `fighter_seen` (far) and `fighter_near` (near) for a viewer whose copies are public (`copy_state.fighters`, a new column with a default).
- **A primary key, unlike `seen_body_copy`.** `id` is the private copy's key (the viewer's character and the creature). Fighter copies change often (a move, a band). The first, keyless build made every change a delete and an insert on three indexes: it cost 24–43 ms/s more tick WASM, and nothing net at 16 viewers. With the key a change is one in-place update, the `(viewer, body)` index is gone, and the law's moves need no player lookup.
- **One writer:** `frame::show_fighter` writes the copy where it is. A creature leaving sight, or a viewer forgetting its scene, drops it there too.
- **The views:** `seen_fighters`, `_near` and `_far` read the public rows first (by `viewer`, or `(viewer, near)` for the tiers) and show the same either way.
- **The law:** `fighter_tables_on`, value-only (Delivery), off by default until `combat-defaults` (2026-11-20), **on since**, its `law_override` row the kill switch. On, each viewer's frame moves its copies whole (`frame::fighters_to_public`). Off, the first tick moves every public copy back (`frame::all_private_fighters`, span `tick.fighters_private`). `all_full` forgets the law's last value, as for the other two.

**Data paths.** The same rows as the private copies, written where the viewer's copies are: one update per change, an insert per newcomer, a delete per departure. No new reads: `show_fighter` finds the copy by its key in either table. The only extra row a viewer holds is its `copy_state` row, already there for the other copy tables. The table is delivered by RLS to each row's viewer.

**Safeguards.**
- **`motion_tables.py`** covers the fighter table with the other two (34 checks): B strikes A once so both have fighter rows; isolation by subscription, SQL and subscribe-all both ways; A's table equal to `seen_fighters` and its near flags to the fighter tier views; the private fighter tables empty of A's while on; the switch off and on through an override row with no reinstall.
- **The negative:** built without the rule, 5 of the 34 fail. They are the fighter isolation checks, both of C's subscribe-alls, and the "on again" comparison (one-off, recorded in the validation record).
- **At battle density:** `battle_viewers.py --privacy --fighter-tables` (16 viewers, 10 m ring, 200 fighters) passed 17 of 17. The viewers checked 195,243 fighter rows besides 154,365 body and 55,719 character copies, 0 foreign. The paused snapshots compared each sampled viewer's fighter table with its views, before and after the switch.
- **The inventory:** `RLS_TABLES` and the owner guard name it, and the pin list (docs/TICK_RATE.md).

**Measurement** (dev-box, `sg-stdb` v2.14.1, no core pinning; Cullet module from this branch; 200 fighters, keep-alive every 0.5 s, paused placement, the battle after placing, tiers and cues, both copy tables on with the viewers on them; L0, 20 s warm-up, 60 s window; two runs per arm, interleaved; the 1-minute load below 4 at each start; no viewer died in any window):

| Arm | Ticks/s | Views ms/s (fighter views) | Tick WASM ms/s | Whole tick call ms/s | DB thread CPU ms/s |
|---|---|---|---|---|---|
| base, 16 viewers, 10 m ring | 58.9 / 58.4 | 84.2 / 79.2 (29.7 / 28.4) | 357 / 363 | 484 / 486 | 492 / 494 |
| fighter table, 16 viewers, 10 m ring | 58.8 / 59.0 | 58.7 / 58.4 (0) | 364 / 375 | 462 / 472 | 470 / 481 |
| base, 216 viewers, 26–32 m ring | 21.2 / 20.1 | 77.2 / 81.3 (50.2 / 53.6) | 544 / 548 | 775 / 788 | 810 / 823 |
| fighter table, 216 viewers, 26–32 m ring | 23.8 / 24.3 | 30.8 / 31.6 (0) | 576 / 583 | 738 / 749 | 774 / 785 |
| 0 viewers (the battle alone) | 60.0 | 0 | 272 | 282 | 282 |

- **16 viewers:** the database thread does about 17.5 ms/s less, about 1.1 ms/s per viewer, which is about 12 µs/s a pair at the 90 creatures each sees (the addendum's expected 11–14).
- **216 viewers:** about 37 ms/s less (−4.5%), which is about 2.9 µs/s a pair at 59 seen each and about 22 ticks/s, and **16% more ticks a second**.
- **The keyless build, for the record:** 0 and −22 ms/s.
- **Per viewer by subtraction:** the 0-viewer arm (`battle_viewers.py` gave it no battle under `--battle-after-placing` before this branch; fixed) puts a viewer at about 13.2 ms/s on base and 12.1 with the fighter table at 16 viewers. That includes the AI's extra work fighting the viewers on the 10 m ring, as the Spark's 12.1–13.1 do.

**Rollout:** as step 1. The authority merges with the law off. The laptop's client reads `seen_fighter_copy` while the law is on, make-before-break both ways, merging the copy's `fighter` rows as the view's. The default flips with it in one change set, which also runs `cargo test -p living-game`.

**The client half (both steps), built 2026-11-20 (`combat-switches`, laptop).** The defaults flip on top of it in one change set, `combat-defaults` (dev-box, 2026-11-20): `fighter_tables_on` and `combat_feed_on` both `true` in `skills.rhai`'s law block and `Laws::default`, the commitlog measurement (checklist item 0) having cleared `combat_feed_on`. `net::Feed` gains two flags, `fighter_table` and `combat_feed`, chosen by `fighter_tables_on` and `combat_feed_on` through `perception_law` as the copy tables are, so 32 sets.
- **The fighters.** `seen_fighter_copy` replaces the fighter views (`seen_fighters`, or its tiers). The reads (`net::find_fighter`, `fighters`) move once the table holds my scene. Leaving, the rows are kept and its deletes ignored until the views are in. The fighter cue table stays with the tiers.
- **The combat feed.** `combat_feed` replaces `my_combat`, which moved from the base set into the perception set. Nothing waits on the event table: `net::take_combat` hands `combat::ingest` the view's cached rows and every event row, merged by `combat_seen`'s id. Ids are forgotten by time (60 s past expiry), so a switch back cannot replay a death. A connection whose first set takes the feed reads `my_combat` once (subscribe, copy the rows when applied, unsubscribe).
- **Nothing in the client depends on the defaults.** The tests read the shipped values: `SHIPPED_TIERED`/`SHIPPED_UNTIERED`, with the two new laws taken from the shipped script by `shipped()`.
- **Proofs:** verify-ui `combat-switches`, `combat-switches-death` (dev-box's death-screen equality, on the client), `combat-switches-ui` and `combat-switches-cost`; see `.agents/skills/verify-ui/features/combat-switches.md` and its validation record. Documentation read: [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) (subscribe the new set before unsubscribing the old; unsubscribing is asynchronous) and [access permissions](https://spacetimedb.com/docs/tables/access-permissions) (it covers table visibility and views, not row-level security, which is on the [RLS page](https://spacetimedb.com/docs/how-to/rls) cited above). Both pages show version 2.0.0; the pins are 2.14.1.

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

### Step 2: `combat_feed` (views step 2)

The same rollout as step 1, in two change sets:

| Part | What | Who |
|---|---|---|
| 1. The authority | `combat_feed`, its rule and the `combat_feed_on` law, **off** by default (`combat-feed`). With the law off nothing changes: no event row is written, and clients read `my_combat` as now. The gate's `combat_feed` case, and `copy_privacy` (it touches `combat.rs`). | dev-box |
| 2. The client switch | The game client subscribes to `combat_feed` while the law is on (read from the law, as the copy tables are), reads `my_combat` once on connect or reconnect (subscribe, take the rows, unsubscribe), merges both by `id` (`combat::ingest`'s `seen_ids`), and switches make-before-break both ways. | laptop, when its slot allows |
| 3. The default | `combat_feed_on: true` in `skills.rhai`'s law block and `Laws::default`, in one change set with part 2. The script and law-override tests follow, as for step 1, and `cargo test -p living-game` (a default flip reaches the client's own tests: `bv-defaults-on`'s first gate). **Before it (the GC, 2026-11-20): the commitlog growth at 216 viewers**, law on against off, measured alongside part 2: event inserts are written to the commitlog (about 5,200 a second at 216 on the 26–32 m ring), and the 216 arm measured CPU only. | dev-box, with the laptop's part 2 |

**The window's checklist** for part 3 (whoever stages the play-test):

0. Before the flip is merged: the commitlog growth at 216 viewers measured (the replica's commitlog bytes over a window, `combat_feed_on` on against off, the same fixture as Addendum 4's 216 arm), and recorded here beside the CPU numbers. **Done 2026-11-20:** [the commitlog growth](#commitlog-growth-with-combat_feed_on-measured-2026-11-20), below.
1. The owner is not in a session.
2. Main contains parts 1–3, and the gate's `combat_feed` and `copy_privacy` cases passed on that merge.
3. In the world, `combat_feed_on` reads on (the default, or its `law_override` row), and the client subscribes to `combat_feed`: `combat_feed.py` against the world, or a verify-client probe.
4. verify-ui: a fight, a death screen, and a reconnect while dead (the screen is still there) pass with the law on.
5. The kill switch: `set_world_law combat_feed_on false`; the client goes back to `my_combat` with nothing missing, and the `script` row's revision is unchanged. Then on again.
6. Note the views ms/s and `my_combat`'s share in the play-test notes, against the last play-test.

If a check fails, switch the law off by row and leave the world running; the client follows the law.

#### Commitlog growth with `combat_feed_on` (measured 2026-11-20)

The checklist's item 0, for the GC. **The feed adds about 96 bytes of commitlog per event row, about +5% of the commitlog at 216 viewers (+0.44 MB/s, +1.6 GB an hour raw) and +3% at 16; after zstd it adds nothing measurable.** The large number is the battle's own commitlog with the law off, about 30 GB an hour raw at 216 viewers. Retention for a running world is missing, and that gap was already there before the feed.

**Setup.**
- **Fixture.** Addendum 4's, on main `58e156bd1` plus `battle_viewers.py --clog` (`8e4ce4c7c`): Cullet module `cl-cullet` (sha256 `27c0302b25f6…`, rustc 1.99.1, no sccache), `sg-stdb` v2.14.1.
- **Battle.** 200 fighters with keep-alive every 0.5 s, paused placement, and the battle starting after placing. Tiers and cues on, both copy tables on (the defaults) with the viewers on them.
- **Window.** 20 s warm-up, then a 60 s window, at L0. Two runs per arm, alternating base and feed.
- **Conditions.** Unpinned (the dev-box's rootless podman has no cpuset controller). The 1-minute load was 2.4–3.9 at each start. No viewer died in any run.
- **Arms.** base: `combat_feed_on` off, viewers on `my_combat`. feed: on, viewers on `combat_feed`.
- **What is measured.** The replica's `clog/` directory on disk (`du -sb`, segments plus `.stdb.ofs` indexes) at the window's start and end. That is segment growth, not retained WAL; no window reached the 1 GiB segment rotation. Per-table row rates come from the server's metrics. View tables are left out: views are ephemeral and never logged.

| Arm | Population | Ticks/s | Commitlog MB/s (runs) | GB/h raw | `combat_feed` rows/s | zstd -3 of the whole log | GB/h at zstd -3 |
|---|---|---|---|---|---|---|---|
| base, 16 viewers, 10 m ring | 16 viewers, 200 fighters, ~150 alive | 58.9 / 58.9 | 2.134 / 2.175 | 7.68 / 7.83 | 0 | 0.113 / 0.114 | 0.87 / 0.89 |
| feed, 16 viewers, 10 m ring | the same | 59.6 / 59.2 | 2.115 / 2.209 | 7.61 / 7.95 | 835 / 850 | 0.108 / 0.109 | 0.82 / 0.87 |
| base, 216 viewers, 26–32 m ring | 216 viewers, 200 fighters, ~350 alive | 20.1 / 21.9 | 8.627 / 8.262 | 31.06 / 29.74 | 0 | 0.096 / 0.096 | 2.99 / 2.84 |
| feed, 216 viewers, 26–32 m ring | the same | 20.2 / 24.3 | 8.752 / 8.752 | 31.51 / 31.51 | 4,596 / 4,484 | 0.092 / 0.091 | 2.90 / 2.88 |

**The difference.**
- **Raw, arm means.**
  - 216 viewers: feed 8.752 MB/s against base 8.444 MB/s, so +0.31 MB/s (+1.1 GB/h, +3.6%).
  - 16 viewers: feed 2.162 MB/s against base 2.155 MB/s, inside the runs' spread.
  - These means mix in how hard each window's battle happened to be. The feed runs at 216 made about 1.5% fewer other durable row changes than the base runs.
- **Per row, which is the figure to use.**
  - The base runs write 106.8 bytes (216) and 109.8 bytes (16) of commitlog per durable row insert or delete, the same within 0.3% across their runs.
  - Subtracting that rate from each feed run leaves 91–101 bytes per `combat_feed` row at 216 and 77–96 at 16.
  - That matches the row's BSATN encoding: 94 bytes with an empty `note` (the identity is 32).
  - So the feed costs **about +0.44 MB/s at 216 (4,500 rows/s, +1.6 GB/h raw, +5.2%)** and **about +0.07 MB/s at 16 (840 rows/s, +0.26 GB/h, +3.4%)**.
- **Compressed.**
  - The feed rows compress well. The feed arms' whole logs compress to 0.091–0.092 at zstd -3, against base's 0.096.
  - At zstd -3: 2.89 GB/h with the feed against 2.92 GB/h without at 216, and 0.85 against 0.88 at 16.
  - At zstd -6, the archive level: 0.080–0.084 of raw, 2.5–2.6 GB/h at 216.
  - The ratios are of each run's whole log (placement, warm-up, window and wind-down), read after the world was deleted.

**What 2.14.1 does with it, from the versioned source** (`v2.14.1`, `a0bf6be`):
- **Event inserts are logged.** `committed_state.rs` merges an event table's inserts into the transaction data "for subscriptions and the commitlog" without keeping them. Only view (ephemeral) tables are left out of the log (`traits.rs`).
- **When compression happens.** Segments rotate at 1 GiB (`DEFAULT_MAX_SEGMENT_SIZE`). A snapshot is taken every 1,000,000 logged transactions (`SNAPSHOT_FREQUENCY`). After each snapshot, the standalone server (`LocalPersistenceProvider`) compresses the sealed segments older than it with zstd at the default level (`snapshot_watching_commitlog_compressor`, `fs-utils/compression.rs`). Nothing is ever deleted.
- **How long that takes here.**
  - 216 viewers: at 362–372 transactions a second, a snapshot comes at most every 45 minutes or so, so about 23 GB of raw log builds up before the first compression.
  - 16 viewers: at about 180 a second, about every 93 minutes, about 12 GB.
  - The segment holding the snapshot stays raw.
  - These 60 s windows did not reach a snapshot or a rotation, so the compression was read from source, not seen on disk.

**Does trial retention cover it?**
- **For trial and verification worlds, yes.**
  - `trials.py run` and `battle_diag.py` pause the world, stream its `clog/` to a `.tar.zst` under `~/slop-evidence/`, test it, and delete only after the archive succeeds ([TRIAL_DISK.md](TRIAL_DISK.md#retention-on-the-trial-server)).
  - The feed changes the archive by nothing measurable: about 2.5 GB per hour of a 216-viewer battle at zstd -6 either way.
- **What is missing, none of it new with the feed:**
  1. **A running world.** SpacetimeDB 2.14.1 has no online commitlog retention or size cap. A world that holds a 216-viewer battle grows by about 31 GB an hour raw, then about 3 GB an hour once its snapshots compress the sealed segments. Nothing removes old segments except the manual offline procedure ([TRIAL_DISK.md](TRIAL_DISK.md#offline-snapshot-and-commitlog-pruning)): stop the server, take a cold backup, keep the latest snapshot and its covering segment onward, and test recovery on a copy. A play-test or a long-running world needs a disk budget per battle hour, or a scheduled maintenance window, before it runs battles of this size for hours.
  2. **The hourly volume check.** `trial_volume_size.sh` samples hourly. A 216-viewer battle can add about 31 GB between two readings before its first snapshot, so the alarm's budget needs that much headroom, or a shorter interval while a battle runs.
  3. **Deleted scratch worlds.** `battle_viewers.py` and plain verification cleanup (without `--archive-commitlog`) delete the database but leave its replica directory. Only recycling the scratch volume frees it. This series left 8 replicas with 4.1 GB of commitlog on `sg-stdb`.
- **For the flip:** the feed's own share (+5% raw, about 0% compressed) needs nothing beyond what base already needs. Item 0 is met. The running-world gap stands with the law on or off.

**Not covered.**
- A run long enough to see the snapshot and compression on disk: at least 1,000,000 transactions, about 46 minutes at 216.
- Snapshots' own size.
- A world with long `note` strings: refusals carry text, so the row grows with it.
- Pinned cores.

**Evidence.** `~/archive/worktree-evidence-20261120/combat-feed-clog-local.tar.gz` on the dev-box. It holds the series script and log, each run's `battle-viewers.json`, metrics and tick files, the per-table rates (`derived.json`, `derived.txt`), the zstd sizes per replica (`zstd.txt`) and the module.
