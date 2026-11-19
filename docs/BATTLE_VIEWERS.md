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
