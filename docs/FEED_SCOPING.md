# Public-feed scoping

Design for coordinator review, 2026-11-19. The production change follows approval and the cost gate below. Audited against `origin/main` at `5ccbeacf`, including R1/R2 from merge `0bd9c490`. See [camera §4–§5](CAMERA.md), [cover sight](COVER_SIGHT.md), [seen structures and counted remains](SEEN_REMAINS.md#composition-with-cover-sight-and-gaze), and [perception](PERCEPTION.md).

## Inventory and disclosure

| Authority source | Current game subscription | Proposed disclosure |
| --- | --- | --- |
| `structure` | Moving chunk window on land and tile maps | Private canonical rows. Public architecture projection limited to stable map geometry and neutral kind. Live objects and dynamic fixtures through sight. |
| `gate` | Whole table in land mode, publicly queryable in either mode | Private canonical rows. Public gate aperture and geometry from the structure/map projection. Open/shut is sight-scoped. Keep raw community, changer and timestamp private. |
| `terrain_chunk` | Whole table in tile mode. Moving window for land corrections, over terrain regenerated from `land` | Public base and structural map changes such as roads, walls, bridges and clearings per the owner's map rule. Publish tile geometry only. Keep the edit log, actor, time and revision history private. Any dynamic gate or temporary object encoded in tile bytes needs its own private overlay. |
| `resource_node` | Moving chunk window in both modes | Split public landmarks (e.g. a tree trunk used by cover geometry) from live amount, depletion, regrowth timing and shared-pool linkage. Treat live stock as a perception leak and resolve it at cutover or call it out as a separately gated exposure. |
| `land`, `settlement`, `lot` | Whole `land`/`settlement`, wider moving lot window in land mode | Public map and authored geometry after checking JSON recipes and lot links for live or private IDs. The full named recipe is already private in `land_plan`. The current `public_params` renames plan keys but retains typed structure positions, fuel and stock where authored. Strip mutable structure placements and private initial state from the public recipe while preserving geometry digests. The public `lot.structure` column also links to a raw structure ID. Replace it with a map identifier or omit the link. |
| `world`, `cover_law` | Whole tables at bootstrap | Public world and cover policy metadata. No per-character perception settings. |
| `speech_card`, `skill_card`, `act_card`, `weather`, `script` | Session subscriptions. Client selects `skills` from `script`. | Public rules and world-level weather. Audit every public script row for authored instance facts. The query on its name is a client filter. |
| `genesis` | No game subscription | Public generation progress. |
| `seen_bodies`, `seen_characters`, `seen_fighters`, `seen_doing`, `heard_sounds` | Session subscriptions | Existing perception projections. Preserve the separate hearing rule and audit labels and cues for indirect location disclosure. |
| `my_body`, `my_fighter`, `my_doing`, `my_characters`, `my_vitals`, `my_experience`, `my_places`, `my_inventory`, `my_know_how`, `my_combat`, `my_readiness`, `my_offers`, `my_known_names`, `my_earshot`, `my_records`, `my_senses`, `my_act_outcomes` | Session subscriptions | Existing sender-scoped own-character views. Ensure stories, combat, act outcomes and memory only carry facts the existing sensory or action rules permitted. |

In a scoped build, the unconditional public base tables are those listed above. The diagnostic `open_tables` build also exposes `character`, `body`, `vitals`, `inventory`, `audience`, `experience`, `know_how`, `place`, `fighter` and `doing`. Ship the scoped profile. A player can query any public table outside the SDK's window. The database owner can subscribe to private truth, so players need independent identities and the lab observer and mind service keep their credentials on the trusted side.

### Structure kinds

| Class | Kinds and details |
| --- | --- |
| Public shell or footprint | `shelter`, `house`, `hall`, `workshop`, `market`, `inn`, and fixed `smokehouse` or `furnace` architecture. A `gate` frame is public. Walls, roads, bridges and clearings are tile edits, not structure rows. A building lot is a map feature. |
| Public shell only when part of a fixed building plan | Cullet's `store`, `peat_barn`, `yard_store` and `house_store`. Publish the building shell where represented by a lot or explicit architecture. Its storage entity, contents and use are private. A house store inside a house adds no geometry. |
| Sight-scoped objects and fixture state | `remains`, `storage` (including caches), `sign`, `trap`, `bush_patch`, `campfire`, `hearth`, `oven`, `lamp`. Treat `bush_patch`'s live structure separately from public static brush geometry. Lit/out, visible fuel, gate open/shut and similar state belong here even when the shell is public. |
| Items and artifacts | Dropped items and loose tablets are sight-scoped if represented by a world object. Today tablets are private artifact rows held by a creature or structure, and posted signs are structure rows backed by a private artifact. Expose presence where the actor can see it. Keep text and contents behind the existing reading and inspection rules. Carried items retain their own access rules. |

Use an explicit allowlist for map disclosure, with unknown script or seed kinds private by default. `Structure.kind` is a string and seed rows and scripts can extend the catalog. Separate map identifiers from actor IDs and interaction handles. The raw `owner`, `built_ms`, and `lit_until_ms` fields currently travel even for architecture. Keep them private and send a viewer-specific owner label only where the existing owner-knowledge rule permits it.

## One sight rule

Use `living_rules::sight::sees` with precomputed observer senses and facing, over `Map::sight_clear` for solids and 2.5D cover. The geometry call alone omits gaze bands, facing and light. Use the same object anchors and endpoint rules in all three callers. A gate should be observable at its aperture even when its own shut geometry blocks the ray beyond it. Check that the shared destination-cell exemption makes this work and still hides a gate behind intervening cover. Resolve self-lit fixtures with the shared reach and glow rules where applicable. A dark object cannot borrow another target's glow. Retention may use the same range and angle margins as people if supplied consistently. Hard cover always wins.

- **Noticing.** Filter mutable candidates in both paths in `brain.rs` (the regular list and the in-place/delta path) before marking, familiarity checks or counting. Audit the shared list's behavior-graph consumers for equivalent visibility. An old look disc plus maximum ID can prove **radius** membership only. Keep C2's disc shortcut for static candidates. For a mutable candidate, use previous actual visibility or established historical membership after the current sight test. A previously screened body can become visible without leaving the previous disc.
- **Mind scene.** In `perceive.rs`, filter before sorting/grouping where practical and before applying the ten-slot limit, calculating state, or reading contents/owner labels. In R2 apply the filter in `select_scene_structures` before folding anonymous remains into counts or selecting a nearest representative. Extend the transaction-local selection cache key to cover changes in observer facing, senses and map/gate revisions at otherwise equal position and radius. Named and readable exceptions still require visibility. Keep the mind service's trusted transport distinct from the scoped scene delivered to a model.
- **Player.** On the existing phased 200 ms player perception sweep, use the same sight helper and cached chunk candidate lists, then write the live diff. Run the same path on join or reacquisition. On loss, delete the live projection at the next sweep. Track the age from the authority sight sample to SDK application and use that to bound the effective disappearance delay. A scoped gate state can affect local Shade geometry. For a gate outside current sight, use last-seen state or an explicit unknown display; do not ask the authority for current state to predict movement. Authority collision remains final. Recheck direct act target resolution on the authority. Guessed IDs and different error messages for hidden versus absent objects must not become a second feed. When an action can legitimately discover an obstruction by contact, return only the information that action reveals.
- **R1/R2.** Only IDs that pass the current test enter `seen_structures` ranges, the R2 count or first-sight words. `seen_structures` answers “ever seen”, so it can suppress repeating a notice after reacquisition. It cannot supply current visibility or the state of a now-hidden object. Old ranges and legacy familiarity from the radius-only rule are unverified for mutable objects. Never turn them into last-seen position or state. On cutover re-establish mutable familiarity from actual sightings (a new namespace or generation avoids falsely treating old ranges as proof). Disconnected, dead or replaced characters must not leak their set to a different character under the same identity.

## Delivery and memory

Choose **private per-viewer copies exposed by a sender-scoped view**. Keep the canonical object truth private. Copy the minimum perceived payload under an indexed `(viewer, object)` key, with an equality index on viewer, and bind rows to the current character. Diff by payload with no observation timestamp that would force a write every sweep. Store the last position, description and observed state in separate private character-keyed memory only when learned or changed. Reuse the existing `remembered` gate storage. Sample gates using the object's sight reach before the broader ground marking radius is substituted. Build last-seen gate coordinates and state from remembered data alone so deletion or relocation of the current gate cannot update belief from across cover. A remembered corpse may remain after its source rots behind cover; only a witnessed absence updates that memory. Evict old mutable memories under an explicit bound and clean up at character death. Provide a separate owner-scoped memory view if needed for presentation. A reconnect reads the current visible rows and remembered snapshots independently.

Let `V` be the number of observers, `C` local candidates per sweep, `K` mean visible objects, and `D` entries, exits and payload changes per sweep. Spatially indexed candidate reads are O(C) per observer. Projected state is O(VK) rows, and the intended copy write count is O(D) per sweep. Instrument private copy writes and view materialization independently.

| Mechanism | Evaluation and writes | Reconnect and access |
| --- | --- | --- |
| Sender-scoped view reading canonical state directly | No explicit copies, but each invalidated sender and argument set reruns relevant reads and rematerializes its result. Movement, gaze, light and map depend on many inputs, including time without row changes. A v2.14.1 view isn't the reducer's shared cover/map context. A broad chunk scan multiplies invalidation work, and a timed view still needs an authority-driven change. | Initial view result and subsequent deltas. Private bases and `ctx.sender()` preserve the boundary. A public base remains independently readable. |
| Private copy + sender view, as in `motion_seen` | O(D) application writes. Each touched viewer reruns its whole indexed O(K) result once per transaction, even if only one copy changed. No refresh for another viewer's key or a no-op sweep. Measure internal remove/reinsert work and wire deltas separately. Batch changes for one viewer in one reducer. | SDK first result restores durable current rows. Refresh on join/resume and remove stale rows on observer loss/death. Test nonowner SQL and WebSocket as well as an owner truth control. |
| RLS on public per-viewer copies | O(D) writes with indexed viewer and `viewer = :sender` as the rule. Deltas evaluated by subscription machinery without a Rust view rematerializing O(K). A rule over joins or broad public tables would have a different cost. Rust needs `unstable`. Held experiment [f9d909769](https://github.com/devteapot/slop-art-online/commit/f9d90976928f28846248d9b32d7438ee22800e26) tried this for fast cues; require its coordinator review and live nonowner tests before reconsidering. | Durable RLS rows could restore current state. The owner bypasses RLS, so an owner subscribe-all can receive every viewer's row. Changing RLS disconnects clients in v2.14.1. Rust main already enables `unstable` for procedures, which does not itself install any RLS rules. |
| Event tables | One inserted event per recipient change, including explicit disappearance. No retained rows. Subscription evaluation still occurs. Views cannot read event tables. Without a verified RLS boundary, public events expose every cue. | There is no initial snapshot or replay. An insert still enters the commitlog. The tag's server-side wildcard omits event tables, while the Rust SDK helper emits a query for each generated table name and can include events. An owner using that helper receives every filtered cue. A durable snapshot plus ordering/reconciliation would be required for missed updates and reconnect. Skip for low-rate props. |

SpacetimeDB guidance consulted: [tables](https://spacetimedb.com/docs/tables/), [performance](https://spacetimedb.com/docs/tables/performance/), [indexes](https://spacetimedb.com/docs/tables/indexes/), [views](https://spacetimedb.com/docs/functions/views/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [RLS](https://spacetimedb.com/docs/rls/), [event tables](https://spacetimedb.com/docs/tables/event-tables/). Against the pinned v2.14.1, [point-read tracking](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/datastore/src/locking_tx_datastore/mut_tx.rs#L488), [view rematerialization](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/relational_db.rs#L1822), and [the owner RLS subscription test](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/subscription/module_subscription_actor.rs#L3613) support the cost and access model above. Test the shipped Rust module and server together. The held branch's follow-up proved both subscribe-all paths for a third player and fenced the owner subscribers with explicit query lists. Its review also moved near copies to new tables instead of appending a tier column and added a cue kill switch. The measured refresh overhead of even empty view subscriptions argues for a single view here. [Frame-views review and follow-up](https://github.com/devteapot/slop-art-online/commit/d8da955f3d1a922452dd8eebf0517a8c9d429849), [subscribe-all proof](https://github.com/devteapot/slop-art-online/commit/802116deff216758e12590a14c916d752c93e3bc), [server wildcard](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/subscription/subscription.rs#L26), [Rust SDK helper](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/subscription.rs#L200).

## Migration and operating policy

Use new tables/views. Appending columns to existing persistent tables triggers `AddColumns` and `DisconnectAllUsers` in [2.14.1 automatic migration](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/schema/src/auto_migrate.rs#L294). Changing a public table to private can break old subscriptions. The [2.14.1 planner](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/schema/src/auto_migrate.rs#L791) schedules access change without a disconnect step at that site. Verify both an existing nonowner subscription across the publish and a new connection. Arrange a controlled reconnect if the runtime keeps serving an old plan. Stage a versioned bootstrap and bounded idempotent backfill of public architecture and private projections. Preserve existing IDs for internal act targeting. Regenerate bindings. In the build phase, verify visibility changes and any disconnect behavior on an owned scratch database before planning the live cutover.

Ship the per-world law off. Gate the added sweep work, mutable sight changes and new feed population behind it for measurement. A Rhai law cannot change table access. Privacy begins with a coordinated schema and client cutover that closes every public alias in a scoped world. A shadow benchmark can leave the legacy feeds open, and must be labeled accordingly. After cutover, a rollback of the law should fail closed for mutable state. No runtime fallback should re-expose current authority rows.

Survey depends on this boundary and the distinction between known map and mutable state. Its own rules and budget are deferred.

## Measurement probe

[Scratch patch](FEED_SCOPING_PROBE.patch) applies to the authority and SDK workload from the audited main revision. Apply it in a scratch checkout with `git apply docs/FEED_SCOPING_PROBE.patch`. It adds the off-by-default `feed_scope_probe` world law, a private diffed copy table, a sender view, the same mutable sight predicate at player/brain/scene call sites and a cost driver. In the experiment the administrator sets the law explicitly. Build the authority and regenerate bindings using the 2.14.1 generator, then build `living/tools/gate_load` under the private target and build slot. Run `python3 living/tools/feed_scope_cost.py --help` for the arm driver. The driver requires the isolated server and acquires the shared battle lock before creating a database.

The probe's payload includes IDs, kind, position, gate state and the stored fire expiry for a cost sample. The production payload needs viewer-appropriate fire state and a separate remembered projection. The probe uses the world observer's senses and 2.5D ray with no extra light on the target or retention margin. Its local gather reads cached structures and point-looks up the gates that passed the ray. It keeps legacy public subscriptions open in both arms and sends no production map or memory rows. That makes it an incremental cost test with duplicate legacy traffic. Cutover bandwidth and privacy require a later test with the legacy feeds closed.

## Cost gate

Use fresh interleaved off/on runs from the same build and layout with the law as the only arm change. Keep cover geometry, ambient census, light/gaze, tick instrumentation, start clock, offered activities, clients and probe cadence matched. Reuse the recorded cover acceptance fixtures as setup evidence. Their results measure cover and cannot be counted as feed-scoping runs.

- Cullet 216, with the acceptance split of 64 residents and 152 independent real SDK clients walking in the seven clusters. Run at least two per arm per field (Round and Middle). Subscribe with independent player identities using the cover acceptance's SDK workload and the candidate view. Record aggregate database bandwidth divided by the connected clients, with no other subscribers. On/off is the incremental estimate for this fixture. Keep the other workloads absent.
- Wooded battle, at least four per arm. Use the same 96 local fighters as the fixed-count acceptance fixture, with no refill or model calls. Control action pressure (including any reduced-damage fixture), record offered and actual action rates and retain census samples throughout. Discard a window only for a predefined mismatch such as lost census, a paused world or missing tick logs, preserving that run's evidence. Keep the prop density, removals and state churn comparable. Include real SDK witnesses with a stated count and position; no aggregate without a valid client denominator.
- Log load averages, memory, free disk, service version, instance PID, duration and start/end tick advancement per arm under `flock ~/slop-mq/battle.lock`. Exclude warm-up, initial snapshot and reconnect from steady-state rates. Use an explicit reconnect trial with the same identity and time to applied current projection. Keep the reconnect outside the bandwidth window. Sample authority WASM linear memory or the attributable server WASM metric, separately from service RSS. Count inserts, updates and deletes at the copy diff, and sample view-call and WebSocket-byte counter deltas. Record tick body time and whole transaction time because view refresh happens outside the tick body.
- Sum the non-overlapping sight spans per elapsed second. Include local candidate enumeration and use the same structure notice/scene timing boundaries in both arms. Compare each on sample to 1.15 times the same workload's off mean. Ticks/s must be at least the lowest off value. The share of tick bodies over 16.7 ms must be at most the highest off value, using the cover acceptance definition. [Standing cost rule](COVER_SIGHT.md#switch-on-gate-standing-rule-2026-11-19), [tick metric definitions](TICK_RATE.md), [performance contract](PERFORMANCE_CONTRACT.md).

### Spark measurement, 2026-11-19

The run window was 30 seconds after warm-up on each fresh scratch database, at matched starting daylight. In Cullet, 64 seeded residents and 152 independent SDK clients gave 216 live characters at both sampled endpoints. The SDK clients walked in seven clusters at 1.5 s intent intervals with the land game queries, the workload's `my_skill_uses` query, and terrain, lot, resource and structure windows opened after placement. The extra `my_feed_probe` subscription was requested in both arms. No model service or observer joined. One early publish was rejected because the scratch law needed a Rhai description. The server returned no named database and the corrected module was used for the whole measured series.

The wooded fixture used the archived cover-acceptance land around (276, 224), 310 ambient characters, 96 fighters, 48 staged remains and eight walking SDK witnesses. The fighter cast was intact at the endpoints, and all 96 body anchors were within 16 m of the battle centre in each of five census samples per arm. Attacks used the reduced-damage settings from the acceptance fixture. Accepted skill uses per second by off/on pair were 70.07/70.27, 66.40/27.57, 20.03/6.43 and 8.00/7.47. Fighter density held across the series and action pressure varied. The first pair had closely matched action rates.

The wooded CLI tail captured around 500 of the roughly 1,600–1,800 tick profiles per run. The table uses the full retained server module logs, cut to the recorded profiling timestamps. Recovered tick counts agree with the independently sampled authority tick counts within six ticks in every battle window. The archive preserves the truncated results as well as the corrected ones and the recovery script. Recover complete logs before using the woods driver output to judge the budget.

Tick ms is the mean tick reducer-body stopwatch and late share uses those body samples strictly over 16.7 ms. Ticks/s is the delta of authority tick counters divided by their authority-time interval. Sight totals sum the existing creature sight and mind sensing spans, both arms' local structure selection/notice spans, and the added player structure scan when enabled. Copy writes count inserts, updates and deletes in per-second diagnostic reports. Bandwidth is the aggregate per-database counter delta divided by elapsed time and SDK count, in decimal kB. Reconnect measures one retained nonowner SDK identity from connection start to application of the probe view on loopback. WASM is the per-database worker memory gauge at the beginning and end of the window.

| Workload | Arm | Runs | Sight ms/s | Tick ms | Ticks/s | Late % | Copy writes/s | kB/s/client | Reconnect ms | WASM MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cullet 216 Round | off | 2 | 31.99–33.21 | 2.78–3.04 | 59.03–59.10 | 0.00–0.00 | 0.0–0.0 | 7.17–7.58 | 45.9–83.3 | 188.9–188.9 |
| Cullet 216 Round | on | 2 | 33.24–41.69 | 2.53–3.15 | 59.12–59.30 | 0.00–0.00 | 113.7–117.1 | 7.46–8.65 | 45.0–51.0 | 186.4–186.4 |
| Cullet 216 Middle | off | 2 | 27.48–28.20 | 2.87–2.97 | 58.58–58.75 | 0.00–0.00 | 0.0–0.0 | 6.26–6.32 | 9.2–29.5 | 186.4–189.1 |
| Cullet 216 Middle | on | 2 | 45.48–45.97 | 4.24–4.25 | 56.76–57.22 | 0.00–0.00 | 221.3–227.3 | 5.30–5.50 | 13.5–56.9 | 186.4–186.4 |
| Wooded battle | off | 4 | 4.72–5.68 | 5.79–7.04 | 56.41–58.07 | 1.32–2.83 | 0.0–0.0 | 9.53–10.11 | 21.5–62.2 | 125.9–126.2 |
| Wooded battle | on | 4 | 4.97–7.03 | 5.01–8.02 | 54.22–59.50 | 0.39–4.79 | 52.6–58.0 | 10.29–10.66 | 49.2–58.5 | 125.6–126.5 |

**Verdict. Keep the law off.** No workload met the complete budget.

| Workload | Worst on sight vs. off mean | Ticks/s floor | Late-share ceiling |
| --- | ---: | ---: | ---: |
| Cullet Round | +27.9% vs. +15% allowed | Pass, 59.03 | Pass, 0.00% |
| Cullet Middle | +65.1% vs. +15% allowed | Fail, 58.58 | Pass, 0.00% |
| Wooded battle | +32.5% vs. +15% allowed | Fail, 56.41 | Fail, 2.83% |

The added player structure scan in Cullet took 5.19–6.95 ms/s in Round and 7.86–7.91 ms/s in Middle. These spans exceed the respective 4.89 and 4.18 ms/s headroom on their own. Host load varied, with Middle starting at a one-minute load of 12.4–15.1 off and 19.6–32.2 on. The wooded pair at about 70 accepted skill uses/s had higher sight time and late share with the law on despite a lower starting load. Treat the other battle pairs as samples at different action pressure. Lower aggregate bytes in Cullet Middle do not establish a bandwidth saving from closing the public feeds because the probe kept them subscribed.

The next design iteration should keep the indexed copy/view boundary and reduce candidate work before adding writes. Build a chunk-local mutable candidate list and share the actor's validated structure look where pose, senses, structure revisions and cover/gate revisions match. Preserve the full geometric test and run the same cost gate on the revised path.

Evidence is archived in `~/slop-evidence/feed-scoping-2026-11-19.tar.zst` with its `.sha256` sidecar. It includes the exact wooded seed, per-run host load, census, counters, raw samples, and the failed initial publish. The dedicated databases were paused and deleted by the harness. The lowest recorded starting MemAvailable and disk free during profiled windows were 100.4 GiB and 172.9 GiB.

### Coverage limits

The probe exercises the indexed copy/view delivery, player sweeps, structure noticing and mind-scene selection on the real authority. It leaves the public source feeds accessible. The production schema cutover, direct nonowner denial and reconnect across that cutover, remembered object delivery, live stock and transient terrain projections, added illumination from objects, and the full game client's presentation were outside these runs. The local SDK reconnect number measures the probe snapshot only. These 30-second windows also leave the 30-minute and eight-hour performance gates open.

## Authority shapes

Checkpoint for branch `feed-scope`, 2026-11-19, against `origin/main` at `f93f05ad`. These shapes are for laptop review. No code is written until the coordinator gives the go. Everything here is new tables and views: no column is appended to an existing table (2.14.1 `AddColumns` rewrites the table and disconnects every client), and no existing table changes its access. A table whose rows must stop being public gets a new private canonical table and a public projection, and its rows move at the world's cutover.

### The law and the stage

- **Laws:** `feed_scope_on` (bool, default `false`) and `feed_scope_grace_s` (default `10`), as typed scalar laws with `laws_about` entries, like `cover_sight_on`.
- **`feed_scope`** (**public**, one row, `id = 0`): `{ id: u8 #pk, stage: u8, since_ms: u64 }`. This is the only thing a client reads to choose its subscriptions. It carries no per-character settings. With the row absent, the stage is 0.

| Stage | When | Canonical rows | Added authority work | Legacy public feeds |
| ---: | --- | --- | --- | --- |
| 0 | Law off, never cut over | `structure`, `gate`, `resource_node` and `lot.structure`, as on main | None. No new rows are written, and the new views read empty tables. | Open, as on main |
| 1 | Law turned on | Still the legacy tables | Map projections backfilled. The shared sight test runs for noticing, scenes, R1/R2 and the player sweep. Copies, memory and owner labels are written. | Still open, labelled **shadow**, the only state where both exist |
| 2 | `feed_scope_grace_s` after stage 1, in housekeeping | Private `*_held` tables. The legacy tables are emptied, and `lot.structure` is written 0. | As stage 1 | **Closed for every moved row.** The legacy tables stay in the schema and stay empty. |

- **Stage 2 is latched.** If the law goes off after the move, the world stays at stage 2 and logs a warning. This fails closed: no fallback re-exposes current rows. Law off during stage 1 returns to stage 0. That clears the copies, the owner labels and the map projections, and keeps characters' memories.
- **The move from stage 1 to 2** is one transaction. It copies every row with its id, deletes the legacy rows, writes `lot.structure = 0` and seeds the id allocators. Its time is measured on a scratch Cullet and a wooded battle. If one transaction breaks the tick budget, the move goes chunk by chunk, with the accessors reading both tables until it ends. I would report that before building it.
- **Access goes through accessors.** All authority code reads and writes structures, gates and resources through accessors in `common` that dispatch on the stage, cached per transaction. That is `chunk_structures`, `structure(id)`, `insert_structure`, `update`, `delete`, and the same for gates and resource nodes. There are about 34 call sites today, and only these accessors touch the tables.

### Private canonical tables (stage 2)

| Table | Fields | Indexes | Notes |
| --- | --- | --- | --- |
| `structure_held` | The `Structure` row type itself (a second `#[table]` on the same struct, which 2.14.1 supports): `id`, `kind`, `x`, `y`, `chunk`, `owner`, `built_ms`, `lit_until_ms` | pk `id`, btree `chunk` | Every structure, architecture included, so `owner`, `built_ms` and `lit_until_ms` are never public. Ids are kept from `structure`, so internal act targets, minds and logs are unchanged. The column's `auto_inc` is never used: every insert carries an id from `id_seq`. No owner index (it would change the `structure` table's schema too); owner labels read `owned_by`. |
| `gate_held` | The `Gate` row type | pk `id` | Open/shut, community, changer and time stay private. |
| `resource_held` | The `ResourceNode` row type | pk `id`, btree `chunk` | Amount, max, regrowth and pool stay private. Ids from `id_seq`. |
| `owned_by` | `{ structure: u64 #pk, owner: u32, kind: String }` | pk, btree `owner` | Allowlisted architecture with an owner, from stage 1, for owner labels. |
| `id_seq` | `{ name: String #pk, next: u64 }` with rows `structure` and `resource` | pk | Allocates ids after the move. The 2.14.1 docs do not say whether an explicit insert advances an auto_inc sequence, so we don't rely on one. |
| `lot_door` | `{ lot: u32 #pk, structure: u64 }` | pk | The door link that `lot.structure` held. It is read in seed and island code. |

### Public map projections (stage ≥ 1)

| Table | Fields | Indexes | Contents |
| --- | --- | --- | --- |
| `map_structure` | `{ id: u64 #pk, kind: String, x: f32, y: f32, chunk: u32 }` | btree `chunk` | Allowlisted architecture only: `shelter`, `house`, `hall`, `workshop`, `market`, `inn`, `smokehouse`, `furnace` and `gate` (the frame). There is no owner, time or fuel. A kind the allowlist does not name, including any kind a seed or script adds, is private. `id` is the structure id, which is stable for the row's life. A gate's aperture is its tile, `(floor(x), floor(y))`, as `gate.x`/`gate.y` are today. |
| `map_resource` | `{ id: u64 #pk, kind: String, x: f32, y: f32, chunk: u32 }` | btree `chunk` | Every resource node, as a landmark only: no amount, max, regrowth, `at_ms` or pool. A tree trunk used by cover keeps its public anchor. |

- The projections are written on insert and delete of the canonical row, and on a kind change. A moved kind never enters them.
- `terrain_chunk`, `land`, `settlement`, `lot` (with `structure` = 0 from stage 2), `world`, `cover_law` and the rule tables are unchanged. `land.params` is not touched: that is the follow-up agreed with the laptop.

### What a viewer sees now: copies and `my_things`

- **`thing_seen`** (**private**), one row per thing a viewer's character sees: `{ id: u64 #pk #auto_inc, viewer: Identity, character: u32, thing: SeenThing }`, with a btree on `viewer`, as `motion_seen` has.
- **`SeenThing`** (SpacetimeType): `{ key: u64, class: u8, id: u64, kind: String, x: f32, y: f32, open: Option<bool>, lit: bool, owner: u32, left: Option<u32>, max: Option<u32> }`.
  - `class`: 1 is a structure and 0 is a resource, the client's own `scene.things` key.
  - `key` is `class << 56 | id`.
  - `open`: gates only.
  - `lit`: whether a fire reads as burning (a kind that `burns` while it has fuel, a campfire always), false for anything else. Fuel is not seen at a glance (the GC's decision at the go): it is found by looking a fire over (`inspect`, below).
  - `owner`: 0 unless the `owner_shown` law grants this viewer the owner (`common::owner_label`).
  - `left` and `max`: resources only, the whole units on the node now and its full stock, so the client draws a depleted node from `left / max` (laptop review).
- **The sweep (iteration 2):** candidates come from 64 m cells (4 × 4 chunks; a player's gather disc touches at most 3 × 3), each built from the chunk lists with what a test and a payload need (place, kind, light, `burns`, fire, expiry, owner, pool) and invalidated with the chunk caches. A seen thing's payload (lit, gate open, `left`/`max`) is worked out once per transaction and shared by every viewer swept in it; a full node is skipped before any ray. Each player's copies stay in module memory between the tick's sweeps (key → row id and payload), dropped with the perception sweep's memory when ticks do not follow on, and not kept from a sweep outside the tick (join, reclaim). A mind's look comes from its scene's own sensing (senses, facing, map). Remembered places are re-checked on a chunk change or every 5 s, not every sweep.
- **What gets a copy:**
  - every moved kind in sight;
  - allowlisted kinds that carry state, namely gates and burning kinds, so their state is seen only in sight;
  - resource nodes in sight with `left` below their max. A node seen at full stock has no copy, and the client draws the landmark full.
- **No text and no contents.** Sign text and storage contents stay behind reading and inspection.
- **Writes:** the copies are diffed by payload and carry no observation time, so a sweep where nothing changed writes nothing. All of one viewer's inserts, updates and deletes happen in its sweep's transaction, so its view refreshes once per sweep.
- **`my_things`** (**public view**, `primary_key = key`): `thing_seen.viewer().filter(ctx.sender()).map(|r| r.thing)`. That is one index key, the same read set as `seen_bodies`. A copy is never kept past its character: copies are deleted at death and at the hand-over to the minds (`perception::forget`), and replaced at reclaim and at join (`sweep_now`).
- **Where they are written:** in `perception::sweep_one`, in the same candidate pass as people.
  - That pass's gather radius, senses, heading, map and cover/gaze/light context are reused, not rebuilt as the probe's `Look::new` did.
  - Candidates come from new chunk-local lists of mutable structures and of depleted resources. These are cached per transaction beside `chunk_structures`, so architecture and full nodes are not tested.
  - Visibility is the same `living_rules::sight::sees` call as for creatures, with the object anchor and the retention margin for things already seen, and the target's glow for a self-lit fire.

### Owner labels for architecture: `my_owners`

- **`owner_seen`** (**private**): `{ id: u64 #pk #auto_inc, viewer: Identity, structure: u64, owner: u32 }`, with a btree on `viewer`. It holds the architecture whose owner the `owner_shown` law grants the viewer: their own, a known name's, or a kind that `shows_owner`.
- **When it is written:** at the sweep, only when the viewer's knowledge epoch changed (the sweep's existing `PROJECTED` epoch check), and in the reclaim or join `sweep_now`. The rows come from `structure_held.owner` index reads for the known names, so a sweep where nothing changed writes nothing.
- **`my_owners`** (**public view**, `primary_key = structure`): returns `{ structure: u64, owner: u32 }` by viewer. The client names the owner from `my_known_names`, as `looks::structure_name` does now.

### Remembered vs current

- **Gates** keep the existing private `remembered` rows (`kind = 1`: `target`, `x`, `y`, `state`, `seen_ms`), bounded at 512 per character and deleted at death. They are now written only by a sighting that passes the shared test, and `known::belief` takes a gate's tile from the memory row, not the live `gate` row.
- **Other moved things** go in **`remembered_thing`** (**private**): `{ id: u64 #pk #auto_inc, observer: u32, target: u64, kind: String, x: f32, y: f32, chunk: u32, open: Option<bool>, lit: bool, seen_ms: u64 }`. It has btrees on `observer`, `(observer, target)` and `(observer, chunk)` (the last for checking remembered places in sight, at most every 5 s per chunk and character).
  - **Written:** at the first sighting, and when the seen position or state changes, by the same test, in a player's sweep and in a mind's noticing pass. Both controllers keep the same memory.
  - **Deleted:** only when the thing is absent from a sighting of its remembered anchor (a witnessed absence), at death, or when the 256-per-character bound evicts the oldest `seen_ms` first.
  - A remains rotted behind cover stays remembered.
  - Old radius-only familiarity is never turned into memory.
- **Resource depletion** stays in the existing `seen_stock`, which both controllers already write.
- **`my_remembered_things`** (**public view**, `primary_key = key`): `living(ctx)`, then returns `RememberedSeen { key, class: 1, id, kind, x, y, open, lit, seen_ms }` (`lit` as last seen, so the view carries no fuel) from `remembered` (gates, `kind = "gate"`, `open = state == 1`) and `remembered_thing`. It reads by `observer` index.
- **`my_stock`** (**public view**, `primary_key = id`): the living character's `seen_stock` rows (`kind`, `x`, `y`, `count`, `nodes`, `seen_ms`, `gone_ms`).
- **How the client tells them apart:** a thing in `my_things` is live. A key in `my_remembered_things` and not in `my_things` is last-seen, so the client draws it as remembered, with its stored state and `seen_ms`, not as gone. A key in neither is unknown.
- The two views are separate tables in the client cache, so there is never a flag to misread.
- **Gates in the sightfield:** a gate that is shut, live or remembered, blocks in Shade. One the viewer never saw is drawn open, or as the client's explicit unknown, and the authority's collision still decides.
- `seen_ms` is when that state was last learned or changed, not refreshed while in sight. That would write every sweep. The client has its own leave-sight time while it is connected.

### Fuel and contents: the `inspect` skill

- **`inspect`** (`living/scripts/skills.rhai`: `inspect_spec`, `inspect_check`, `inspect_done` with the `inspect` effect, `inspect_shows`, `inspect_ui` with the label "Look over", on a thing's wheel). A fire that burns fuel or a container (a kind that `holds`, remains, a trap) within 2 m, 1 s. Listed in a world's skill lists only where some structure kind `burns` (Cullet), so the shipped world's prompts are unchanged; a scoped world's scene names it for a container not looked into. The same for players and minds.
- **Contents (the GC's decision at iteration 2, minds match players):** in a scoped world a mind's scene shows a container's presence and kind (`"kind": "storage"`), never its contents. Its `inside` field says `"not looked into: inspect it (or take from it) to see what it holds"`, or what was inside when the character last looked (`"3 berries when you looked inside, <time>"`). Looking inside is `inspect`, or reaching a container to take from it or store in it (whether the act then goes ahead or not: an empty cache is known empty). **`contents_seen`** (**private**): `{ id, observer, target, items: Vec<ItemCount { item, qty }>, seen_ms }`, at most 32 per character, gone at death; **`my_contents_seen`** (public view) for a player. A graph's `{"nearest": {"kind": …, "holds": X}}` in a scoped world counts a container known to hold X or not yet looked into, never one found without it, so instinct graphs (wolves and scavengers at remains, residents at stores) still go and look, and an empty one is not revisited. At stage 0 scenes and `holds` are as on main.
- **`fuel_seen`** (**private**): `{ id: u64 #pk #auto_inc, observer: u32, target: u64, left: f32, seen_ms: u64 }`, btrees on `observer` and `(observer, target)`. `left` is the hours of burning left at the look (0 when out). At most 32 per character, the oldest look first; gone at death.
- **`my_fuel_seen`** (**public view**, `primary_key = id`): the living character's rows.
- The actor is told "You look the hearth over: about 4 hours of fuel left on it." A mind's scene shows a fire as `"state": "burning"` or `"out"`, and, once it has looked, `"fuel": "about N hours of … left on it when you looked it over, <time>"`. In a world at stage 0 the scene keeps its old wording with the hours.

### The look and act path for moved kinds

- **What the client looks at and inspects:** the client's `things()`/`toward()` list and target facts are built from `my_things` (live), `map_structure`/`map_resource` (architecture and landmarks) and `my_remembered_things`.
- **A remembered target that is no longer in sight** shows its title as last seen, with no live facts and no choices except going to its place. This follows how a creature that is no longer perceived gets no choices.
- **The authority's check (as built):** an act's target is resolved from the actor's scene list (`brain.rs` `visible_thing`, through `resolve_for`, for `human_act`, deliberate acts and graphs alike), and that list holds a sight-scoped thing only when the sight test sees it now. A remembered thing is not a target until it is in sight again; the client offers going to its place. A guessed id, a hidden thing and an absent one fail alike (verify-player: outcome code `unseen` for both).
- Performing the act still needs reach at arrival against the canonical row. A remembered thing that has gone fails there as it does today, and that contact is what reveals it.
- Minds go through the same check, against their own scene and memory.
- Text and contents are still read only through the existing read and inspect acts.

### Noticing, mind scenes, R1/R2

- `brain.rs` covers both the list path and the delta path, `perceive.rs::select_scene_structures` and `known::remember_gates`. From stage 1, all of them filter mutable candidates with the same `sees` call and the observer context already built by that pass, before marking, familiarity, counting, grouping and the ten-slot limit.
- Static candidates keep the C2 disc shortcut. A mutable candidate is always tested.
- **`seen_structures_scoped`** (**private**), shaped as `seen_structures`: `{ id #pk #auto_inc, actor: u32, block: u32, ranges: Vec<u64> }`, btree `(actor, block)`. It holds mutable ids that passed the test from stage 1. The old `seen_structures` keeps architecture only, so old radius-only ranges never prove a sighting.
- Legacy recognition does not count for a sight-scoped kind (as built): its newness reads `seen_structures_scoped` alone, never `familiar` rows or the old ranges, so legacy familiarity is relearned from real sightings without a backfill that deletes rows.
- The scene's transaction cache key gains facing and a gate revision (bumped by every gate opened or shut). Senses do not change within one transaction for one observer.
- Gates are sampled with the observer's own sight, not the ground-marking radius, and `known::belief` takes a gate's tile from the memory row.

### Client subscriptions

| | Stage 0 (law off, as main) | Stage ≥ 1 (scoped) |
| --- | --- | --- |
| Static | `cover_law`, `world`, `land`, `settlement`, **+ `feed_scope`** | The same |
| Perceived | As main | As main **+ `my_things`, `my_remembered_things`, `my_owners`, `my_stock`** |
| Land base | `gate` | No `gate` |
| Tiles base | `terrain_chunk` | `terrain_chunk` |
| Near window | `terrain_chunk` (land), `resource_node`, `structure` by chunk | `terrain_chunk` (land), **`map_resource`, `map_structure`** by chunk |
| Lot window | `lot` by chunk | `lot` by chunk (`structure` is 0 from stage 2) |

Stage 1 exists so a client can switch while the legacy rows are still there. A live switch goes like this:

1. The client sees `feed_scope.stage` go from 0 to 1.
2. It subscribes the scoped set: the four views plus the map windows over the same chunks.
3. On that set's `on_applied`, it unsubscribes the legacy queries (`gate`, `structure` and `resource_node` windows), make-before-break as in frame-views and the 2.0 subscription guidance.
4. Until `on_applied`, it keeps drawing from the legacy rows, so nothing pops.

- `feed_scope_grace_s` is that window. A client still on legacy queries when stage 2 lands sees its rows deleted, which fails closed.
- Turning the law off during stage 1 runs the reverse: subscribe legacy first, then drop the scoped set.
- A client connecting at stage 2 subscribes only the scoped set.

### Reconnect

The snapshot order is:

1. **Static,** including `feed_scope`, which gives the stage.
2. **Base:** perceived plus the four views and the land queries, in one subscription so they apply together.
3. **Windows,** after the body is known.

- **Within the presence grace,** the character is still the person's and its copies are still stored. The base subscription's first result is the last sweep's rows, and the next sweep, at most 200 ms on the character's phase, corrects them.
- **After a hand-over to the minds,** the copies were deleted at the hand-over. Reclaim runs `sweep_now` in its own transaction, so the reclaim's result and the rows arrive together. At join, `sweep_now` runs in the join reducer, as for people.
- **The client waits** for the base `on_applied` before drawing scoped things. After reclaim or join it also waits for the reducer's result before taking an empty `my_things` as "nothing in sight".
- Memory (`my_remembered_things`, `my_stock`) and owner labels are stored rows, so they arrive in the first result whatever the presence state.

### Cutaway and scenery fade

They do not key off structure ids:

- The cutaway fades `Occluder` entities built from `lot` rows and island kit parts, plus `Landmark`s.
- `Indoors(lot)` is found from a thing's position (`island::indoors_of`).
- Trees fade by the `Tree` entities of the island forest.
- `scene.things` keys on `(class, id)`.

Structure and resource ids are kept through the move, and `my_things`, `map_structure` and `map_resource` carry the same ids, so the client's keys are unchanged and needs no mapping. Two changes: `lot.structure` becomes 0 from stage 2, and the client never read it; and on land worlds, `LAND_DRAWS` kinds still come from lots, so `map_structure` is used for verbs and the gate tiles.

### Residual and open points for review

Settled at the go (GC and laptop, 2026-11-19):

- **Ids still show creation order: a known low-value leak, accepted for now.** A newly seen remains id says how many structures were made since. The future fix is per-viewer handles: each viewer's copies carry an opaque handle, resolved to the structure on the authority for that viewer's acts, the same for both controllers.
- **Fuel:** lit or out only in sight; the fuel left through `inspect` (above).
- **Full resources as landmarks:** agreed. Copies cover depleted nodes in sight only (O(depleted nodes in sight) writes).
- **Fast stages for tests:** `feed_scope_grace_s` may be 0 or 1. Housekeeping steps the stage once a second, so a scratch world reaches stage 1 within about a second of the law and stage 2 a second or two later.

Still open, outside this build:

- (Settled at iteration 2: minds see a container's presence and kind only, as players do; above.)
- Owner labels on a copy are worked out when the thing comes into sight and when the viewer's knowledge changes; a storage claimed by someone else while in view keeps its old label until it leaves sight.
- `land.params` is the separate follow-up agreed with the laptop.

### Proof and acceptance

As briefed:

- verify-client: nonowner denial by SQL and WebSocket, an owner truth control, and reconnect restoring the copies;
- verify-core: a body behind a hedge, its sighting, memory after leaving sight, and gate state seen only in sight;
- verify-player and verify-minds: the mind's scene matches;
- law off identical to main;
- the `COVER_SIGHT.md` budget: Cullet 216 at Round and Middle, 2 or more runs per arm, and the wooded battle at 96 fighters, 4 runs per arm, under `battle.lock`.

The measured on arm is stage 2, with the legacy feeds closed. Stage 1 is measured only as a labelled shadow.

SpacetimeDB documentation consulted for these shapes:

- [tables and visibility](https://spacetimedb.com/docs/tables/): private tables are readable only by reducers and the owner;
- [access permissions](https://spacetimedb.com/docs/tables/access-permissions): views over private tables filtered by `ctx.sender()`;
- [views](https://spacetimedb.com/docs/functions/views/): re-evaluated per subscriber when the read set changes; index lookups only; `primary_key` gives update deltas;
- [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): subscribe before unsubscribing; `on_applied` fires once the initial rows are cached;
- [auto-increment](https://spacetimedb.com/docs/tables/auto-increment): an explicit nonzero value is used as given, and whether the sequence advances is not stated.

These pages are from the 2.0 docs. The pinned 2.14.1 crate source (`spacetimedb-2.14.1`, `spacetimedb-bindings-macro-2.14.1`) matches the view `primary_key` form this repository already uses. The access-change and `AddColumns` behaviour is the 2.14.1 planner cited above, to be checked on an owned scratch database during the build.

## Build measurement, 2026-11-19 (branch `feed-scope`)

The cost gate above, on the built authority at `0f604656` (law off: stage 0 with the legacy client set; law on: stage 2 with the scoped set, `living/tools/feed_scope_cost.py`), on a private server (`slop-feedscope-bench`), under `~/slop-mq/battle.lock` (held 21:35–22:45 CET), 30 s profiled windows, interleaved off/on. Cullet: 64 residents and 152 walking SDK clients (216 live), two runs per arm per field. Wooded battle: the archived cover-acceptance land, 96 fighters with reduced-damage spears round (276, 224), 48 staged remains, 8 walking SDK witnesses, four runs per arm. Sight is the sum of `sight.player_candidates`, `scene.sensed`, `sight.structure_notice`, `sight.structure_brain_list`, `sight.structure_scene` (all timed in both arms) and, on, `sight.player_things` (the copies' candidate pass and payload).

| Workload | Arm | Runs | Sight ms/s | Tick ms | Ticks/s | Late % | Copy writes/s | Memory writes/s | kB/s/client | Reconnect ms | Load 1-min at start |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cullet Round | off | 2 | 32.57–34.92 | 2.83–3.15 | 59.05–59.17 | 0.00 | 0 | 0 | 7.37–7.38 | 45.4–61.9 | 5.4–16.0 |
| Cullet Round | on | 2 | 48.76–49.32 | 2.93–2.98 | 58.98–59.15 | 0.00 | 129.7–136.3 | 10.7–11.7 | 6.88–7.18 | 46.3–49.6 | 4.0 |
| Cullet Middle | off | 2 | 23.87–33.30 | 2.50–3.58 | 57.49–58.93 | 0.00 | 0 | 0 | 5.64–6.47 | 48.7–65.3 | 5.5–6.3 |
| Cullet Middle | on | 2 | 41.40–51.40 | 2.96–3.75 | 55.15–58.36 | 0.00 | 260.9–263.6 | 11.4–11.9 | 5.21–6.07 | 45.4–59.0 | 4.1 |
| Wooded battle | off | 4 (+4 retries) | 4.54–5.17 | 5.53–6.84 | 55.32–58.94 | 0.57–3.23 | 0 | – | – | – | 2.5–6.0 |
| Wooded battle | on | 4 (+4 retries) | 5.45–7.80 | 5.43–9.61 | 51.54–59.05 | 0.85–7.31 | 43.1–57.9 | – | 10.36–10.54 (2 runs) | 57.5–57.7 (2 runs) | 2.2–5.1 |

**Verdict: keep the law off.** No workload meets the budget.

| Workload | Worst on sight vs. off mean | Ticks/s floor | Late-share ceiling |
| --- | ---: | --- | --- |
| Cullet Round | +46.2% (off mean 33.74) vs +15% allowed | Fail, 58.98 vs 59.05 | Pass, 0.00% |
| Cullet Middle | +79.8% (off mean 28.59) | Fail, 55.15 vs 57.49 | Pass, 0.00% |
| Wooded battle | +60.2% (off mean 4.87) | Fail, 51.54 vs 55.32 | Fail, 7.31% vs 3.23% |

Where it goes. In Cullet, `sight.player_things` alone is 16.5–22.0 ms/s for about 7,500 candidate tests a second: 2.2–2.9 µs a test, against about 1 µs a test for people in the same sweep (`sight.player_candidates`). The ray is not the cost; the work round it is, per candidate and per seen thing at every 200 ms sweep: the viewer's copies read and keyed, the payload rebuilt (`act::fire_state` through the script and the world row, a gate's point lookup, the owner check), and for a depleted node `stock_of` and `amount_now` (the season's regrowth). The probe's scan, which built no payload, was 5.2–7.9 ms/s. In the woods the increment is `sight.player_things` 0.85 ms/s for eight witnesses, plus noticing (+0.34) and the scene list (+0.10) from building each mind's look and testing its sight-scoped candidates, about +1.3 ms/s against 0.73 allowed.

Next iteration (before another series): build each seen thing's payload once per transaction, shared by every viewer swept in it (lit, open, `left`/`max` per structure or node and transaction), and the chunk lists with each candidate's light so the test reads no script; keep the viewer's previous copies in module memory keyed by the sweep (as `KEPT` does for people), reading the table only after a gap; and give a mind's look the noticing pass's own senses and facing instead of reading them again. The ray test and its inputs stay as they are. Then the same series.

Validity notes. Three Cullet off runs started above the brief's one-minute load of 6 (Round 16.0, Middle 6.3 and 5.5): the first series' load wait gave up after 30 minutes and measured anyway. The driver now never measures above the limit. In the woods the server wrote the module log late: 15 of 16 runs failed the driver's completeness check when it read the log 2 s after the window. Their windows were re-read from the replica logs afterwards (`.local/feedscope/recover.py`; the counts agree with the expected ticks). Ticks/s for those comes from the tick span count over the window, and their action rate and census were not kept. The two woods on runs that completed in the driver held 96 of 96 fighters, 414 live, and 66.4–69.4 accepted skill uses/s. The driver now reads the log until the window is complete. The 30-minute and 8-hour gates and the client's presentation stay open. Evidence: `~/slop-evidence/feed-scope-2026-11-19.tar.zst` (with `.sha256`), runs `fc-s1-*`, `feedcost-s1.jsonl`, `woods-recovered.json`.

## Iteration 2 status (paused 2026-11-20, WIP)

Built and verified on a private server (records in each surface skill's `references/validation/*-feed-scope-2.md`):

- **Cost fixes:** the player thing sweep reads 64 m candidate cells that carry each candidate's light; each seen thing's payload is built once per transaction; copies stay in module memory between tick sweeps; a mind's look comes from its scene's own sensing. Also: remembered-thing writes skip unchanged sightings, and noticing skips known stateless sight-scoped things.
- **Minds match players on contents:** a scoped scene shows kind and `inside`; contents come only from `inspect`, take or store (`contents_seen`, `my_contents_seen`); `holds` counts known-to-hold or not-yet-looked.
- **Scenes:** verify-minds `chest` passes; verify-core body 26/26 and gate 18/18, verify-client feed scope 40/40, verify-player 9/9; the scene gate (13 cases, law off) passes.

Partial re-measure, series `s3` (Cullet Middle only, 2 runs per arm, loads at start 2.2–3.4, stopped by the pause before Round):

| Arm | Sight ms/s | `sight.player_things` | Thing tests/s | Ticks/s | Late % |
| --- | ---: | ---: | ---: | ---: | ---: |
| off | 23.98–27.98 | – | – | 56.33–59.07 | 0.00 |
| on | 30.74–38.83 | 5.42–7.27 | 7,477–7,701 | 52.80–55.81 | 0.00–0.06 |

The per-test cost is now 0.72–0.94 µs, close to people's ~1 µs (it was 2.2–2.9 µs). Middle still fails the budget: +49.5% against the off mean of 25.98, and ticks/s fall below the lowest off run. The bound is now the number of tests. About 7,500 thing tests a second sit beside about 29,000 people tests, so at equal cost per test the feature adds about a quarter to player sight. That cannot fit +15% unless fewer things are tested each second. The options are a slower re-acquire rate for unseen candidates (latency, an owner's feel call) or a narrower candidate set.

Left: Round and the wooded battle in a low-load window (`living/tools/feed_scope_cost.py --series <s> [--reclaim-closed]`), the verify-client `run.py` suite on this iteration, and the GC's call on the test-rate trade-off.

## Iteration 3 status (paused 2026-11-20, WIP)

Branch merged with `origin/main` at `16f50c0c` (rustc 1.99.1); the authority builds. Written, not yet verified or measured:

- **Cadence (the GC's option (a), refined):** a thing the viewer sees now (it holds a copy), and a not-yet-seen thing within `feed_scope_near_m` (default 10 m), is tested at every sweep. A not-yet-seen thing beyond that is tested once every `feed_scope_far_s` (default 1 s) per viewer. Both are value-only laws (`law_override`, `set_world_law`). "Seen" means in sight now: a thing that left sight and comes back beyond the radius takes the slow path again.
- **Pop-in probe:** `feed_scope_popin_probe` (diagnostic, off) tests the far ones at every sweep too, only to time them. Each far thing's first sighting logs `feed scope pop-in: <ms> ms at <m> m` (the extra delay; 0 when it was taken at its first sighting), and one that leaves sight before it is taken logs `… missed`. The cost series is to add a probe arm per workload and read p50/p90/max from these lines.
- **Stage 1 → 0:** `revert` now only sets stage 0, and the scoped rows (`map_structure`, `map_resource`, `thing_seen`, `owner_seen`, `owned_by`) go at the next housekeeping step (`clear`). A `begin` within that step clears the leftovers first.

Left:
- `just living-check`;
- the genesis fuel gate (island `init` ≤ 118.441e9);
- the feed-scope scenes on a private server;
- the cost driver's probe arm and pop-in parsing;
- the series (Cullet Round and Middle, 2 runs per arm; woods, 4 runs per arm), with a stop-and-report if Middle is still above +15%.
