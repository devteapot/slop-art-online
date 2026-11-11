# Perception: what a player's client receives

Started 2026-11-09. This note records how the living authority limits what a human player's client receives to what the player's character perceives now, plus the character's own state ([game brief](GAME_BRIEF.md#core-work-the-game-needs-engine-independent), core work 1; [island authority](ISLAND_AUTHORITY.md), "Perception-scoped subscriptions" and "A slimmer moving-body stream"). It covers the table audit, the SpacetimeDB documentation and source the design rests on, the design, the measured cost, the per-table decisions, the client change and the verification.

**Status (sixth change, 2026-11-11, branch `rules-offers`).** A player reads the trade offers addressed to its character, and its own, through a new view, `my_offers`; `trade_offer` stays private and gains a `to` index and a stored end, `until_ms` ([Offers](#offers-what-a-player-is-offered)).

**Status (seventh change, 2026-11-11, branch `fov-1`).** Sight may depend on facing: a world law, `fov_on` (off as shipped), gives `senses(a)` a field, and one pure function in the rules crate, `living_rules::sight::sees`, decides every look for the authority and the game client alike. What is heard but not seen reaches players (`heard_sounds`) and minds (their scene and a percept) coarsely, with no identity. `set_world_law` changes a law on a running world and records it ([The field of view](#the-field-of-view-seventh-change)).

**Status (fifth change, 2026-11-11, branch `fix-perceived-moving`).** What others perceive a creature doing is derived from its body when it moves under motion intent, so a walking player reads `walk → person`, not `wait`, as an AI character walking the same line reads `goto → person` ([Activity derived from the body](#activity-derived-from-the-body)). No table or view changed.

**Status (fourth change, 2026-11-10, branch `scale-1`).** Perceived state reaches each player once per frame through per-viewer copies, and every view reads a handful of keys ([Frames](#frames-what-others-do-reaches-a-player-once-per-frame)). Measured against the 216-character gate and verified as recorded in [Fourth change: measurements and verification](#fourth-change-measurements-and-verification); the gate's verdicts are in [gate 216](GATE_216.md#scale-change-frames-2026-11-10-branch-scale-1).

**Status (third change, 2026-11-09, uncommitted on the Mac checkout).** `scoped` is the default build. The game client reads only the perception views: the former patch is applied to `living/game`, merged by hand with the wolves and arid lands of `acbbda7` and the polish of `dc5e41b`, and deleted. The client draws what the projection gives (names or labels, health as a band or exact while appraised, dress from `folk`/`style`, residents resting indoors hidden), and its **V** key sends `appraise` ([Client change](#client-change)). `LIVING_PERCEPTION=open` remains for diagnostics ([Compatibility](#compatibility-the-living_perception-build-switch)). Verified as recorded in [Third change: verification](#third-change-verification).

**Status (second change, 2026-11-09).** Minds now perceive by the players' rule: sight by light and a clear sight line, in every perception path ([Minds see what their character sees](#minds-see-what-their-character-sees)). What one character perceives of another is a projection of its record through a law in the script, `perceived_of` ([What an observer perceives of a target](#what-an-observer-perceives-of-a-target)): `seen_characters` returns that projection (no controller, home or parents), minds' percepts and scenes use the same one, and a demonstration skill, `appraise`, reveals exact health for 20 s. Presence and the takeover of an offline player's character are in [player memory](PLAYER_MEMORY.md#presence-and-the-offline-character). Measured and verified as recorded in [Second change: measurements](#second-change-measurements) and [Second change: verification](#second-change-verification).

**Status (first change).** Implemented on branch `perception-1` and verified on scratch databases (`verify-*`) on the dev-box with SpacetimeDB 2.14.1, in its own container (`slop-perc-stdb`, port 3320). No lab or reference world was touched. The game client (`living/game`) was not edited then: its change was a patch (`docs/perception-client.patch`, deleted when it landed in the third change), described in [Client change](#client-change). Until it landed, the default build kept the tables the game client read public ([Compatibility](#compatibility-the-living_perception-build-switch)).

## Rules this follows

- **Perception is enforced on the authority** (AGENTS.md: "Spatial subscriptions are not permission boundaries by themselves"). A chunk window is a client's choice of what to subscribe to, so it bounds bandwidth, not knowledge. The perceived set is worked out by the authority with the rules' own sight.
- **Current perception, remembered knowledge and developer audit truth are separate paths.** Current perception is the `seen_*` views, recomputed from the world as it is. What a player remembers is its own `experience` window, places and know-how (`my_*`). Audit truth (minds' state, thoughts, beliefs, personas, the chronicle) is private, read by the database owner: the mind service and the lab observer.
- **One sight for every character.** The radius is `common::sight_for` (day 11 tiles, night 6, a torch at night 9), and a clear sight line (`perception::in_sight`). Since the second change it holds for players and minds alike: "we should only observe what the actual NPC can see" (the user, 2026-11-09). Since the sixth change it is one function in the rules crate, `living_rules::sight::sees`, which also reads the field of view when the world's law turns it on, and which the game client calls too.
- **What one perceives of another is decided by the rules, per observer.** Not a fixed public column set: the full record through `perceived_of(p)` in the script, a function of the observer, the target, what the observer knows and can do, and what a skill use revealed (the user, 2026-11-09).

## SpacetimeDB documentation consulted (2026-11-09)

Pinned: `spacetimedb = "=2.14.1"` and `spacetimedb-sdk = "=2.14.1"` in `living/Cargo.toml`; server image `clockworklabs/spacetime:v2.14.1`. The live docs' version selector reads 2.0.0, so every claim the design depends on was also checked in the `v2.14.1` server source (`github.com/clockworklabs/SpacetimeDB`, tag `v2.14.1`, commit `a0bf6be`) and the 2.14.1 crates in the cargo registry.

| Page | What it says | What follows here |
|---|---|---|
| [Views](https://spacetimedb.com/docs/functions/views/) | `ViewContext` "depends on who is querying it"; per-sender views mean "1,000 separate view computations" for 1,000 users; "views can only access table data through indexed lookups"; views "are reevaluated when SpacetimeDB detects something they read has since changed (the read set)", and "If a row outside that set changes, the view doesn't need to be re-evaluated"; views with arguments "cannot have a primary key" and allow no `WHERE` or joins on top. | Per-sender views, because what each player perceives differs. Each view reads only through point lookups, so its read set is the rows it returned (below). No arguments: the sender is the only input, and a viewer position as an argument would be a client's claim. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | Group subscriptions by lifetime; "subscribe to the new set before unsubscribing from the old one"; indexed predicates avoid processing rows twice. | The views are subscribed once per connection: they move with the character on the authority, so the client re-subscribes nothing as it walks. Only static data (`terrain_chunk`, `lot`) keeps chunk windows. |
| [Tables](https://spacetimedb.com/docs/tables/) and [access permissions](https://spacetimedb.com/docs/tables/access-permissions/) | Private tables are "Visible only to reducers and the database owner"; "Views can read from private tables and expose only the data appropriate for each client". The access page omits the owner. | Audit truth is private and the mind service and observer read it as the owner. Verified in source, below. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/) | "Make tables public only when clients need to access them"; private tables "Don't consume client bandwidth"; split tables by access pattern; "Be mindful of unbounded table growth". | `perceived` is private and changes only when someone comes into or goes out of sight; it holds one row per creature in sight per player. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | B-trees support equality and ranges; indexes "consume additional memory and slow down inserts and updates". | One new btree index, `perceived.viewer`, the view's lookup. No index on the hot `body` row was added. |

Verified in the `v2.14.1` source, not stated (or stated differently) in the docs:

- **Views re-run in full, inside the transaction that wrote what they read.** `refresh_views_then_commit_and_broadcast` and `call_views_with_tx` (`crates/core/src/host/wasm_common/module_host_actor.rs`) call every view whose read set the transaction touched before it commits; `materialize_view_arg_hash` (`crates/engine/src/relational_db.rs`) deletes the caller's previous rows and inserts the new ones. A view's cost is therefore part of the tick's transaction time, and grows with players × updates of what each one reads.
- **A view returning a query is not incremental in 2.14.1.** A `RawSql` result is run in the transaction and materialized like returned rows (`run_query_for_view`), despite the views page's "can be updated incrementally".
- **Only point lookups are tracked precisely.** `record_index_scan_range_inner` (`crates/datastore/src/locking_tx_datastore/mut_tx.rs`) records a point lookup as that key, and any range scan "conservatively … as a full table scan". A view that range-scanned `body` by chunk would re-run on every steering update in the world. The bindings' `filter(value)` on a btree index is a point scan (`is_point_scan`, `spacetimedb-2.14.1/src/table.rs`), and so is `find`.
- **View backing tables are ephemeral** (`test_view_tables_are_ephemeral_in_commitlog`): no commitlog writes. Re-inserting an identical row in the same transaction undeletes it (`insert_undelete`), so unchanged rows send no update.
- **Views may declare a primary key** (`#[view(…, primary_key = id)]`, `spacetimedb-bindings-macro-2.14.1/src/view.rs`), and the generated bindings then give `on_update` (`TableWithPrimaryKey`). A view returning a narrow product type still gives clients updates, not delete-and-insert pairs.
- **The owner reads private tables through SQL and subscriptions.** `owner_permissions` (`crates/lib/src/identity.rs`) grants `Read(Private)` only when the caller is the database owner, and subscription and SQL table resolution filter by it (`SchemaViewer`, `crates/engine/src/sql/ast.rs`). Anyone else gets an error naming a private table.
- **Bindings for private tables** need `spacetime generate --include-private` (`crates/cli/src/subcommands/generate.rs`); the mind service and observer use them.
- **Metrics:** a view call is reported under the per-reducer VM metrics with the view's name (`reducer_wasm_time_usec{reducer="seen_bodies"}`), `view_calls_triggered_by_reducer{reducer="tick"}` counts the views a reducer triggered, and `spacetime_reducer_plus_query_duration_sec{reducer="tick"}` covers the tick with its view refresh and subscription evaluation (a histogram whose smallest bucket is 5 ms, so only its sum and count resolve the 1–3 ms range).

Consulted again for the second change (2026-11-09):

| Page | What it says | What follows here |
|---|---|---|
| [Lifecycle reducers](https://spacetimedb.com/docs/functions/reducers/lifecycle/) (selector 2.0.0) | `#[reducer(client_connected)]` and `#[reducer(client_disconnected)]` take only the `ReducerContext`; client_connected "Runs for each distinct connection (WebSocket, HTTP call)" and "Receives the connection ID for the connection being opened"; "Failure disconnects the client"; client_disconnected "Runs when connection ends (close, timeout, error)". Restarts, crashes and republishing are not covered. | Presence keyed by `ConnectionId` (one row per open connection), counted per identity. HTTP calls are connections too, so a takeover waits for the `takeover_s` law. |
| [Reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context/) | `connection_id` is `Option<ConnectionId>`, "if available". | A connection event without one changes no row. |
| [Views](https://spacetimedb.com/docs/functions/views/) | A view returns rows of a product type (or a query) computed from what it reads. | `seen_characters` returns a narrow `SeenCharacter` type read from stored projections (below). |

Verified in the `v2.14.1` source (`crates/core/src/host/host_controller.rs`, `module_host.rs`; `spacetimedb-2.14.1/src/lib.rs`): "If an error occurs in the disconnect reducer, the client is still recorded as disconnected"; `call_identity_connected` inserts an `st_client` row, and at launch the host runs `call_identity_disconnected` for every dangling `st_client` row ("Disconnect dangling clients"), so "every client connection eventually has `client_disconnected` invoked", crashes included. Observed on a scratch world: an HTTP `join` ran both reducers around the call (presence `connections` 0 afterwards, a takeover pending). Not verified: whether connections survive a module republish without a disconnect (a world that updates in place gets presence rows at each player's next connection).

Not verified: how the per-sender views behave with thousands of subscribers (the docs warn of the cost; only 1–50 were measured), and whether 2.14.1 bounds a view's read set size.

## Audit

Every table, by what it holds. "Open" and "scoped" are the two builds ([Compatibility](#compatibility-the-living_perception-build-switch)); "owner" is the database owner's identity (the publisher: the mind service and the lab observer). Before this change, every table here was public except those marked as engine state.

| Table | Class | Open build | Scoped build | Who reads it |
|---|---|---|---|---|
| `world` | static world data | public | public | everyone (clock, size, seed; it also names the admin identity) |
| `land`, `settlement`, `lot`, `terrain_chunk` | static world data | public | public | game client (land, lots and terrain edits by chunk window), observer |
| `script` | static world data (the rules' Rhai source) | public | public | mind service, clients that predict |
| `skill_card`, `act_card` | static world data (cards derived from the script) | public | public | game client |
| `weather` | static world data (one sky for everyone) | public | public | game client |
| `gate` | static world data with live state | public | public | observer; a gate's state is visible from afar (it also names who last moved it) |
| `resource_node`, `structure` | static world data with live state | public | public | observer, game client; amounts and owners are readable beyond sight ([Open](#open)) |
| `body` | current perception | public | private → `seen_bodies` | game client; mind service none |
| `character` | current perception (who is there) | public | private → `seen_characters`, `my_characters` | game client, mind service (owner), observer (owner) |
| `fighter` | current perception (health band, the move under way) | public | private → `seen_fighters` | game client |
| `doing` | current perception (what someone is visibly doing) | public | private → `seen_doing` | game client |
| `vitals` | own private state (exact health and needs) | public | private → `my_vitals` | game client (own), observer (owner) |
| `experience` | own private state: what reached the character's senses, its memory window | public | private → `my_experience` | game client (own), mind service (owner, by controller), observer (owner, one character) |
| `place` | own private state: places the character knows | public | private → `my_places` | game client (compass), mind service (owner) |
| `inventory` | own private state: what the character (or a store) holds | public | private → `my_inventory` | game client (skill bar needs), observer, mind service (owner) |
| `know_how` | own private state: techniques the character knows | public | private → `my_know_how` | game client (skill bar), mind service (owner) |
| `activity` | own private state (the activity under way, its words and topic) | private | private | observer (owner); others see `doing` |
| `practice` | own private state (uses per skill) | private | private | rules only |
| `combat_seen` | own private state, through `my_combat` | private | private | game client (view) |
| `readiness` | own private state, through `my_readiness` | private | private | game client (view) |
| `skill_use` | own private state, through `my_skill_uses` | private | private | game client (view) |
| `deliberation` | a mind's own state, through `my_deliberations` | private | private | mind service (view) |
| `thought` | developer audit truth (model exchanges, raw replies) | private | private | observer (owner) |
| `persona`, `belief`, `judgment`, `relation` | developer audit truth (minds' projections) | private | private | mind service, observer (owner) |
| `brain`, `mind_state`, `mind_cursor`, `routine`, `routine_stat` | developer audit truth (behaviour graphs and their runtime) | private | private | mind service, observer (owner) |
| `genome`, `background` | developer audit truth (inborn genes, authored pasts) | private | private | mind service (owner) |
| `chronicle`, `stats` | developer audit truth (the world's event log, speech included; load counters) | private | private | observer, tools (owner) |
| `community`, `membership`, `join_request`, `bond_offer`, `trade_offer`, `expecting` | developer audit truth (social facts between characters; a player learns of them through its experiences, and since the sixth change reads the trade offers it is a party to through `my_offers`) | private | private | mind service, observer (owner) |
| `artifact` | developer audit truth (tablets and signs; reading one is an act, and its text reaches the reader as an experience) | private | private | observer (owner) |
| `perceived` | private engine state (new: who each player perceives) | private | private | the `seen_*` views |
| `projected` | private engine state (second change: what each player perceives of each creature in its scene, the `perceived_of` projection) | private | private | `seen_characters`, `seen_fighters` |
| `reveal` | own private state (what a skill use revealed to an observer, until when) | private | private | the projection, rules only |
| `acquaintance` | own private state (whose name a character was told) | private | private | the projection, rules only |
| `connection`, `presence` | private engine state (open connections; whether a played character's person is there, and who controls it) | private | private | the mind service (owner) |
| `skill_code` | private engine state (stable presentation codes per skill; clients read codes from `skill_card` and `act_card`) | private | private | rules only |
| `clock`, `steer`, `wake`, `infant_cry`, `familiar`, `rearing`, `act_queue`, `pasture`, `missile`, `tick_timer`, `slow_timer` | private engine state | private | private | rules only |

## Design

### The perceived set

`perception::sweep` runs in the tick (span `tick.perception`). Each living character a person controls (the combat module's `HUMANS` cache: not a mind's, not the database's) is swept every 200 ms, staggered by id. A sweep:

1. reads the character's body and its sight now (`sight_for`: the night and torch rules);
2. takes the creatures within sight + 1 tile from the per-tick chunk-body cache that minds' perception already fills (`common::creatures_near`), at their positions now along their segments;
3. keeps those within sight (a creature already perceived stays until it is 1 tile beyond: no flicker at the edge) and with a clear sight line on the cached map (`Map::sight_clear`: a grid traversal of the exact tiles between; rock, walls and shut gates hide, water, forest, drops and low things do not ([Drops](#drops-sight-across-ground-levels)); the two ends' own tiles never block);
4. compares with the player's `perceived` rows (point lookup on `perceived.viewer`) and inserts or deletes only the difference.

A join sweeps the newcomer at once (`perception::sweep_now`), so the world is there on the first frame. A death deletes the player's rows (`perception::forget`). A player's own character is never a `perceived` row: the views add it.

### The views

All are per-sender (`ViewContext`), take no arguments, declare `primary_key = id`, and read only through point lookups.

| View | Returns | Reads (its read set) |
|---|---|---|
| `seen_bodies` | [`Motion`](#the-moving-body-stream) rows of my living character and every creature I perceive | my characters (`character.controller`), my body (`body.id`), my `motion_seen` rows (`motion_seen.viewer`; [frames](#frames-what-others-do-reaches-a-player-once-per-frame), since the fourth change) |
| `seen_characters` | `SeenCharacter`: what I perceive of each creature in my scene, mine included (`id`, `name` when known else empty, `label`, `kind`, `stage`, `folk`, `style`, `own`, `band`, exact `hp`/`max_hp` or -1) | my `projected` rows (`projected.viewer`) only |
| `seen_fighters` | their `fighter` rows, with the band I perceive (the projection's; 255 when hidden) | my characters, my `fighter` row (`fighter.id`), my `fighter_seen` rows (`fighter_seen.viewer`; frames) |
| `seen_doing` | their `doing` rows | my characters, my `doing` row, my `doing_seen` rows (`doing_seen.viewer`; frames) |
| `my_characters` | my characters, the dead included (the death screen) | `character.controller` |
| `my_vitals` | my living characters' `vitals` | `character.controller`, `vitals.id` |
| `my_experience` | the newest `frame::LINES_SHOWN` (64) lines of my living character, or of my last character while none lives (since the fourth change; before, every character's 400-line window, the dead included) | `character.controller`, `line_seen.by_observer_shown` = (character, true): the released copies of the lines |
| `my_places`, `my_inventory`, `my_know_how` | my living characters' rows | `character.controller`, then `place.actor`, `inventory.owner`, `know_how.actor` |

"My characters" are the caller's characters with `ai = false`. A mind service's identity controls AI characters (`ai = true`), so these views return nothing to it; it reads the tables as the owner.

The existing `my_combat`, `my_readiness`, `my_skill_uses` and `my_deliberations` are unchanged in shape. Since the fourth change an onlooker's `my_combat` rows are written at its frame and stay 300 ms; the two involved get theirs at once and keep them 4 s, as before frames (1.5 s for a while lost a polling reader's events); only the one who died keeps its death and its witnesses for two minutes, until it joins again ([frames](#frames-what-others-do-reaches-a-player-once-per-frame)).

### Frames: what others do reaches a player once per frame

Fourth change (2026-11-09, branch `scale-1`; [gate 216](GATE_216.md)). In 2.14.1 a view re-runs in full whenever a row in its read set is written, inside the writing transaction, and its whole result is deleted and inserted again (`call_views_with_tx_at`, `materialize_view_arg_hash`). When the `seen_*` views read the perceived creatures' own `body`, `fighter` and band rows, every move, every blow and every band change re-ran the views of every player who saw it. In a crowd that is players × changes × rows: cubic in the crowd's size. The 216-character gate measured it: 100 players fighting in 9 m held 0.5 steps a second.

What changed is how perceived state is delivered, not who perceives it or what:

- **The views read per-viewer copies.** `motion_seen` (one row per creature a player perceives: its `Motion`) for `seen_bodies`; `fighter_seen` (the creature's `fighter` row with the band this viewer perceives) for `seen_fighters`; the band and exact health of `projected` for `seen_characters`; `combat_seen` for `my_combat`; and `line_seen` (released lines) for `my_experience`. A player's own body, fighter row and projection are read directly, so its own moves, the blows it takes and its outcomes reach it in their own transaction.
- **The tick writes a viewer's copies at its frame** (`frame::deliver`, span `tick.frames`, after the perception sweep). Writers of the truth mark what they changed (`frame::moved` in `motion.rs`, `frame::fought` in `combat.rs`, `frame::hurt` in `perception::health_moved`); a frame compares only the creatures in the viewer's scene that changed since its last frame and rewrites only the rows that differ. All of one viewer's copies are written in one transaction, so each of its views re-runs at most once per frame however many writes the frame covers.
- **The cadence.** A frame re-materializes about one row per creature in the scene per view it touches, so a viewer's interval grows with its scene: `interval(n) = clamp(n × 1000 / SCENE_ROWS_PER_S, FRAME_MIN_MS, FRAME_MAX_MS)` with 2,000 rows a second, 33 ms (30 Hz) and 100 ms (10 Hz). One step serves due viewers stalest first, up to `FRAME_ROWS_PER_TICK` (2,500) creatures of scene in all, so the work frames add to a step is bounded; when more is due, frames come less often instead of the tick running late (the delivery's back-pressure). Projections follow others' health at most every `BAND_MS` (1 s): the client draws health bars from `seen_fighters`, which carries the band at every frame; the exact health an appraisal reveals follows each second. A player's own projection follows at once.
- **Feeds.** An onlooker's `combat_seen` events are buffered for its frame and kept 300 ms once released (the client reads each row once, by id; a client stalled longer than that misses an onlooker's effect); the actor and the target get theirs at once and keep them 1.5 s (a refusal 4 s). A death reaches onlookers at once (it leaves `seen_bodies` with the body in the same update, which the client needs for the corpse). Experience lines are staged in `line_seen` with `shown = false` when written and released at the character's next frame (at most every 100 ms); `my_experience` reads `(observer, true)`, a point lookup on a two-column index, so neither a staged line nor any other `experience` write re-runs it.
- **What module memory holds.** Which creatures changed and each viewer's scene, last frame and buffered events live in the module instance (`thread_local`). 2.14.1 runs every reducer and view of a database in one instance (`WasmtimeModuleHost`: "Reducers are not executed concurrently"); a panic replaces it. A fresh instance compares each viewer's whole scene at its first frame after a sweep, so a lost mark costs one compare, not a stale row. Buffered onlooker events are lost with the instance; staged lines are not (they are rows).

Privacy is unchanged: every copy is a private table written only for viewers whose sweep put the creature in their scene, and every view still reads only through point lookups keyed by the sender or its characters.

### The moving-body stream

`seen_bodies` returns a narrow product type, `Motion`: `id`, `x`, `y`, `t_ms`, `vx`, `vy`, `heading`, `turn`, `turn_s`, `next_ms` (the segment's end, when steering looks again) and `speed` (the cruising speed of the movement, which tells walk from run). The client extrapolates with `living_rules::steer::pose` exactly as from a `body` row. It leaves out the path (16 B a corner), the chunk and the kind (on the creature's character row). That is 52 B of columns against `body`'s 70 B plus 16 B per path corner. No table was added and no column removed, so a running world updates in place: the view maps rows that are written anyway.

### Drops: sight across ground levels

Since 2026-11-11 (branch `drop-1`). A drop between two ground levels, a terrace's or a planned settlement's (docs/AUTHORED_PLANS.md), is its own terrain class, `Terrain::Drop` (tile byte 8), not `Wall` (7). Before, `terrace::paint_drops` painted it `Wall`, so on Cullet nobody on Mid Row saw anyone on Low Row a few metres below, while the client drew both plainly (docs/SMALL_CITY.md, the owner's answer to decision 6: what the screen shows of the ground and of people must agree).

- **The foot:** a drop blocks like a wall. `Terrain::walkable` is false for it, so steering (`Map::free`), straight walks (`line_clear`), A* (`Map::path`), regions, areas and connected ground (`nav.rs`), click targets (`nearest_reachable`) and building (`build wall`/`gate` need a walkable tile; a road is laid where one stands) all refuse it. Only roads, ramps and stairs join levels, as before. Generation keeps drops like walls: `land::connect_walled` never cuts a ford through one, roads and plazas painted later leave it alone.
- **The eye:** `Terrain::opaque` is true only for rock and walls. A drop is open air: `Map::sight_clear` and its per-chunk fast path pass over it, so every perception path (players' perceived sets, minds' scenes, graphs' `sees`, witnessed events, the combat feed) sees across it.
- **Missiles:** they follow the sight rule and fly over a drop (`Map::passable_missile`, which sight already shared). This is not a balance choice but the same physical rule as sight: the drop is open air, and the authority has no height (sight lines ignore height, docs/FLOORS.md "Verticality"), so it cannot tell a shot down a terrace from one up a retaining wall. Stopping missiles at a drop would make a visible target unshootable for no visible reason. If shooting up a wall should be harder, that is a height rule for the step in FLOORS.md where levels become layers, not a terrain class.
- **Low things** (same day): a lot or blocking prop below eye height (a cart) is `Terrain::Low` (9) on the hosted map, which blocks the foot and not the eye in the same way; what rises above the eye stays `Wall`. How high a thing rises comes from its own definition (its model's `height_m` in `data/buildings.json`); the eye height and per-kind overrides are land data, `LandParams.sight` ([island authority](ISLAND_AUTHORITY.md#sight-over-low-things-2026-11-11)). **Why land data and not a law:** which tiles block is decided when the land is hosted, in the rules crate, without the world's script, and the game client rebuilds the same hosted land for its own sight test (sight-2, `living/game/src/sightfield.rs`). The authority and the client must compute blocking from the same input, and the seed's land data is the input both have. A law could differ from what the client computes, and the client would draw people the authority hides, or hide people it perceives.
- **Since eye-2 (same day), a thing above the eye hides only where its model is solid at eye height.** The measure is `eye_cells` in the table, from the mesh in 1.2–1.8 m. A tile is `Wall` where a half-metre square of the model blocks at least `LandParams.sight.solid` (0.8) of the view, and `Low` elsewhere. So an open stall, a well under its roof and a fountain's basin are seen through, and a closed building is not ([island authority](ISLAND_AUTHORITY.md#sight-through-what-is-open-at-eye-height-2026-11-11)).
- **What a mind is told** (eye-2): a mind's scene lists the nearest drop and the nearest low thing under `terrain_near`, as it lists water, rock, roads and walls, and says what they are, with how they meet the foot and the eye. That comes from the class's own `walkable` and `opaque` (`Terrain::words`, `Terrain::passage`):
  - before: `"drop": "west 1"`, and no low thing at all;
  - now: `"drop": "west 1, a drop to ground at another level (stairs, ramps and roads join the levels): you can see past it but not walk through it"` and `"low": "south 1, something low or open in the way, such as a cart, a low wall or an open stall: you can see past it but not walk through it"`.

  It cannot say "the lower street": the authority keeps no heights, so it cannot tell up from down (verify-minds `drop`).
- **What stands on a drop hides:** a building's footprint or a blocking prop over a drop tile becomes `Wall` on the hosted map (`host::hosted_map`) where it hides (by drop-1's rule, when it rises above the eye; since eye-2, where it is solid at eye height). On the island no footprint does (4,116 drop tiles, none under a footprint).
- **Not modelled:** a retaining wall's face. Someone at the foot of a 4 m wall sees someone a few metres back on the level above, which the eye would not; the 2D authority sees over every drop both ways. The game client's top-down camera shows both, which is what the owner asked to agree.

#### Drops and low things: measurements (2026-11-11)

**Who is hidden on Brackenford's square** (the island's arrival square, seed 7 at 2048 m), from the arrival point, within 48 m, on the hosted tiles (`living/rules/examples/sight_census.rs`):

| Points | Before (drops and low things as `Wall`) | After (height rule, 1.6 m) | Stalls see-through (`hides_m {"market_stall": 0}`) |
| --- | --- | --- | --- |
| Every walkable tile centre (5,141) | 3,853 hidden | 3,853 | 2,554 (2,163 with wells at 0.95 m too) |
| People in a live island world (44 of 277 within 48 m, one `body` snapshot of `verify-core-bench-after`) | 29 hidden | 29 | 17 |

The square has no blocking thing below eye height: its stalls (2.6 m), its well (3.4 m) and its market cross (5.4 m) rise above it by their models' heights, so the height rule alone changes nothing there. On the plan-test land the change hides 2,288 of 3,461 points round its arrival, against 2,421 before (its drops). On Cullet's seed (`living/seeds/cullet.json`, plan-2's Wrack: seed 83 at 1024 m, 1,753 drop tiles, no low ones), from its arrival on the quay: 1,225 of 4,241 points within 48 m hidden, against 2,516 before; the Rows now see each other across their drops.

**Cost.** `living/tools/bench.py` on fresh `island` databases, one at a time on a private 2.14.1 server, before (main `fd2030c3`) and after (this change), each with a profiled span `brain.scene` round a graph's scene added for the measurement: 60 s at rest after a 15 s settle, then `spawn_skirmish(200, 12)` and 60 s, two repetitions each, interleaved. The dev-box was shared (load average about 21 on 32 cores from other builds), so differences under about 15% are noise.

| Window | Arm | Tick p50 / p99 (ms) | Graph evaluations/s | `brain.scene` p50 / p99 (ms), ms per s |
| --- | --- | --- | --- | --- |
| Rest | before | 1.51 / 3.37, 1.43 / 2.79 | 369, 371 | 0.023 / 0.092, 9.8; 0.021 / 0.086, 9.4 |
| Rest | after | 1.60 / 3.66, 1.79 / 3.64 | 373, 374 | 0.024 / 0.088, 10.2; 0.026 / 0.091, 11.3 |
| Skirmish (200) | before | 2.19 / 18.9, 3.04 / 24.7 | 802, 804 | 0.018 / 0.089, 16.0; 0.026 / 0.107, 22.4 |
| Skirmish (200) | after | 2.03 / 24.4, 2.26 / 40.1 | 809, 775 | 0.020 / 0.082, 17.3; 0.025 / 0.091, 19.3 |

No change shows outside the spread on the island, where only 61 tiles became low and the drops lie in terraced towns away from the arrival and the skirmish. The second after-skirmish p99 (40 ms) is a single window; the first was 24 ms. A battle on a terraced street, or at 48 m sight (Cullet), was not measured. Raw reports: `.local/drop1/bench/` in the `drop-1` worktree (git-ignored).

### Minds see what their character sees

Second change. Every path by which a mind, or a behaviour graph, learns about another creature now uses the rule players have, through one function, `perception::in_sight(map, eye, at, dist, sight)`: within the observer's own `sight_for` and with `Map::sight_clear` between. No second approximation was written.

| Path | Before | Now |
|---|---|---|
| Witnessed events (`perceive::witnessed`: fights, deaths, gifts, building, births…) | anyone within the base sight of the place (no torch, no sight line) | each onlooker within its own sight (a torch at night) and a clear line from where it stands to the place |
| A mind's scene (`perceive::scene_json`, the deliberation request) | creatures within sight | creatures within sight with a clear line (`perception::visible`; `perception::sensed` since the sixth change), each described by its projection |
| Behaviour graphs (`brain.rs` scene: `nearest`, `sees`, `visible_creature`, a resident noticing someone) | creatures within sight | the same `perception::visible` (`sensed` since the sixth change) |
| What an animal senses before attacking a person (`act.rs`, `sensed`) | creatures within sight, or smelled | seen with a clear line, or smelled (smell is unchanged) |
| A player's aimed act ("you cannot see them", `act.rs`) | `Map::line_clear` (a walking line: water blocked it) | `in_sight` (water does not block sight; the line the player's perceived set uses) |
| The combat feed (`combat::show`, `combat::died`: `my_combat` / `combat_seen`) | onlookers within their sight, no sight line | within their sight and a clear line |
| An infant's cry seen by a carer (`perceive::infant_cry`) | within the carer's sight | within its sight and a clear line |
| Speech, signals, smell | hearing and scent radii | unchanged: they are not sight |
| Resources, structures and terrain in a scene | within sight | unchanged: static world data, which a player's client also draws by chunk window ([Open](#open)) |

### What an observer perceives of a target

What one character perceives of another is not a fixed set of public columns. It is the target's full record through a law in the script, so skills and knowledge can reveal more.

- **The law.** `perceived_of(p)` in `living/scripts/skills.rhai` receives `p.observer` (`kind`, `knows`: its know-how), `p.target` (`kind`, `known`: the observer knows its name, `revealed`: the fields a skill use revealed and that still hold), `p.self` and `p.night`, and returns `#{ name: bool, health: "band" | "exact" | "none" }`. The shipped law: a name when known (animals know their own kind's), health as a band, exactly for oneself or while revealed. A script without the law gets the same rule from `Regard::default_for` (`living_rules::script`).
- **Rust's primitives** (`perception.rs`): the full record (character, vitals, the settlement round its home), whom the observer knows (`knows_name`: itself, parents, children, the other parent of its children, its community, or someone who told it their name (`acquaintance`); since town life layer 2 a mind's feelings about someone (`relation`) no longer count, so a mind can feel for a stranger it only saw without learning their name, docs/TOWN_LIFE.md), what still holds of a reveal (`reveal`), the perceived set and the sight line. `project(observer, target)` builds the projection: `name` (or empty), `label` (the name, or `a stranger`, `a child`, `a baby`, `an old stranger`, `a wolf`), `kind`, `stage`, `folk` and `style` (build and dress, from the settlement round the home: what the client drew from the home position), `band`, and exact `hp`/`max_hp` (to the whole point) or -1.
- **Introductions.** Saying one's own name tells it to everyone who hears (`perceive::speak` writes an `acquaintance` row per hearer). Being told a third person's name is not built.
- **Names at a death** (`fix-death-labels`, 2026-11-11). The dead's `membership` row goes at death, which would leave their community reading "a stranger was killed" and "the remains of a stranger". What decides is what was true at the moment of death: `act::die` first writes an `acquaintance` row for each other member of the dead's community (`perception::remember_member`), so those who knew the name keep it, in the death percept, at the remains and in the mind's `known_as`. A witnessed event's object reads it as done to them: the killer reads "a stranger was killed by you" (`perceive::rendered`, the text part of `iter-5`, which also gives a storage's owner "from your storage"; its salience floor was not taken).
- **Cadence.** The law's answer depends only on its input (`RegardIn`: kinds, know-how, known, revealed, self, night), so it is cached by that value per script revision: a world needs a handful of distinct inputs, and the law runs a few times per revision, not per observer × target. A player's projections are stored in `projected` rows. The sweep projects a creature when it comes into sight, and again only when an input changed: the viewer's knowledge epoch (bumped when it is told a name, when its mind's relations are projected, at a birth to its parents, when any community's members change), a reveal that holds or has just ended, and its own row (exact health). Health bands reach the rows through `perception::health_moved`, called where the fighter band is written (a blow, a heal, the 1 Hz follow-up), through the `projected.body` index. Nothing is re-projected on the 200 ms sweep otherwise.
- **Delivery.** Two options were weighed. A view computing the projection on refresh would have to read everything the law depends on (each target's `vitals`, `relation`, `membership`, `acquaintance` and `reveal` rows), so its read set would re-run it on every needs settle of anyone in sight, and it would run the projection per perceived row per refresh. A private per-viewer table that the update writes and the view reads by viewer costs a write only when a projection changes, and the view's read set is the viewer's own rows. The table was chosen; its cost in the crowd case is in [Second change: measurements](#second-change-measurements). It is a table of its own, not columns on `perceived`, so a band change re-runs `seen_characters` and `seen_fighters` for those who see it, not `seen_bodies` and `seen_doing`.
- **Minds use the same projection.** `common::label_for` is the projection's label, so every percept names others as the observer perceives them ("A stranger attacked you", "Wren said to you"), the act feedback a character gets of its own acts does too ("gave 3 berries to a stranger"), an activity's label (what anyone sees of it: the doer's feedback, onlookers' scenes) names a creature target by its kind ("wave → person"), not its name, and a mind's scene lists a creature's `name` only when known (else `who`: its label), its wound from the projected band, and `health: "34 of 60"` while an appraisal holds. The mind service tags people in experience lines with a name only where the authority's text already gives it (else `someone=#id`, keeping the id as the memory anchor). The chronicle and audit truth keep real names.
- **The death record** (since `feedback-1`). `character.cause` names a killer as the victim perceived them at the blow (`common::label_for` with the victim as observer): "killed by a stranger", "killed by a wolf", or a name the victim knew. It reaches the player's death screen through `my_characters`, so it says only what the character knew. The chronicle's `killing` and `death` rows keep real names as audit truth ([mind feedback](MIND_FEEDBACK.md#7-the-death-record-names-what-the-victim-knew)).
- **`appraise`.** A skill declared in `skills.rhai` like any other (`appraise_check`, `_duration` 1.5 s, `_done` → `#{ op: "reveal", what: "health", secs: 20.0 }`, `_shows` a gesture, `skill_io`, the catalog's help). The new effect `reveal` writes a `reveal` row (observer, target, what, until); the observer is told what it saw ("You look a stranger over: 100 of 100 health."). It is open to players (`human_act`) and minds (a graph leaf or a deliberate act) alike. Ended reveals are deleted once a second by an index range.

### Activity derived from the body

Fifth change (2026-11-11, branch `fix-perceived-moving`). Human-controlled and AI-controlled characters share physical rules, so the same body behaviour must be perceived the same way whoever controls it. Before this change it was not. A player who moves takes the controls (`player_controls` in `lib.rs`): its graph becomes `{"wait":60}` with the plan "moving yourself", and its body then moves by motion intent (`motion::intent`, steering goal `GOAL_DIRECTION`), not by a walking skill. What others perceived it doing was its `activity` row's label, which said `wait` while it walked. An AI character walking the same line at the same observer read `goto → person`. In the owner's play-test the residents therefore never saw the player walk up to them.

- **The rule** (`perception::doing_of`). What a creature is perceived doing is its activity's label, as before, except when its body is moving under motion intent and its activity is none or `wait`. Then the motion is what is seen (`perception::moving_label`): `walk` or `run` (the run input, `motion::FLAG_RUN`), then `→ <kind>` for the nearest creature its heading points at (within about 18°, among what the observer sees, the observer included), else the compass way it goes (`walk east`). The form is the one an activity's label has (`goto → person`): a kind, never a name. The rule reads the body and its steering, never the controller, so an AI body under motion intent would read the same. No AI body steers that way today; `verify-core` `scenes.py doing` checks that none does.
- **Where it is seen.** A mind's scene (`perceive::scene_json`, each creature's `doing`) and the first sight of someone (`brain.rs` `noticed`: "For the first time you see a stranger, 8 tiles east, walk → person."). These were the two places that put another creature's activity label into what a character perceives. A player's own `you.doing`, its `my_*` views and its graph and plan ("moving yourself") are unchanged. A player's client already received the same thing for both controllers: the body's motion in `seen_bodies`, and no `seen_doing` row for a walk (`doing` rows exist only for skills with an act card). No view's rows changed.
- **Facing.** Not added in this change. Since the sixth change a mind's scene carries `you.facing` while sight depends on facing ([The field of view](#the-field-of-view-seventh-change)); others' facing is still not listed.
- **Before and after** (`verify-player` `approach.py`; R is the resident, the walkers start 8 m out on the same line):

  | Walker | R's scene `doing`, before | after |
  |---|---|---|
  | player walking at R (`human_move`) | `wait` | `walk → person` |
  | player standing | `wait` | `wait` |
  | AI walking at R (`goto`) | `goto → person` | `goto → person` |
  | R's first sight of the player walking in | "…, 11 tiles west, wait." | "…, 8 tiles east, walk → person." |

- **Cost.** It is computed when a scene or a first-sight line is built. It reads, per creature listed, its `activity` row as before, plus the `steer` and `body` rows by primary key, only when the activity is none or `wait`. It writes nothing and adds no table, column, view or subscription. The 60 Hz path, the frames and the views' read sets are untouched.
- **SpacetimeDB documentation consulted (2026-11-11), against 2.14.1.** [Indexes](https://spacetimedb.com/docs/tables/indexes/): primary keys create an index for equality lookups, and `find` on one is the access pattern to use. [Performance](https://spacetimedb.com/docs/tables/performance/): prefer indexed lookups to scans, and split tables by access pattern so that updates touch fewer rows. [Views](https://spacetimedb.com/docs/functions/views/): a view re-runs when a row in its read set changes. The implications are three. Computing the label in the reducer that builds a scene, from rows read by key, costs three point lookups and changes no subscription. Putting it in a table or a column would add a write on the motion path, and a view re-run for every viewer whose read set holds it. Deriving it in a view would put `steer` and `body` in that view's read set. So the projection computes it.

### Offers: what a player is offered

Sixth change, 2026-11-11, branch `rules-offers`, on the Spark. In play-test 4 the owner's last line to a resident was "want to trade ?": a reply in the form of an offer would have reached the player only as one experience line, which the client did not draw, because `trade_offer` is private and no view carried it (the interface design, `docs/INTERFACE.md` on branch `design-interface`, §1 "Trade and offers" and §7 "`my_offers`").

**SpacetimeDB documentation and source consulted (2026-11-11).** The docs' selector reads 2.0.0. Claims were checked in the pinned `spacetimedb-2.14.1` and `spacetimedb-bindings-macro-2.14.1` crates (cargo registry) and against the server source findings recorded above for the fourth change.

| Source | What it says | What follows here |
|---|---|---|
| [Views](https://spacetimedb.com/docs/functions/views/) | "views can only access table data through indexed lookups (`.find()` and `.filter()` on indexed columns)"; "Full table scans create pessimistic read sets"; if any row in the read set changes, SpacetimeDB "must re-execute the entire view function"; `ViewContext` gives the caller's identity. | `my_offers` reads `trade_offer` only through two btree filters. It re-runs in full, so it stays small: one row per offer the caller is a party to. |
| Source: `spacetimedb-2.14.1/src/table.rs` `is_point_scan` | `B::POINT && B::COLS_PROVIDED == I::NUM_COLS_INDEXED`: a `filter(value)` on a one-column btree is a point scan, recorded as that key (`record_index_scan_point_inner`, fourth change). | `trade_offer().to().filter(me)` and `.from().filter(me)` are point reads. An offer between two others does not re-run my view. Measured below. |
| Source: `spacetimedb-2.14.1/src/lib.rs` `ViewContext` | Fields are `sender`, `db` (read-only), `from` and `env`. No timestamp. | A view cannot decide whether an offer has ended. The end is stored on the row (`until_ms`), and housekeeping deletes an ended offer. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | `#[index(btree)]` on a field; B-trees serve equality and ranges; indexes "slow down inserts and updates". | One index, `trade_offer.to`. The table holds at most one offer per character and is written once per offer. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations) | "Adding indexes" is a safe change; adding columns needs a default at the end (`AddColumns`, fourth change source check). Views are not listed. | `to`'s index and `#[default(0u64)] until_ms` at the end migrate a running world in place. Checked by an in-place update below. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | Make tables public only when clients need them; cleanup reducers for growth; "keep subscriptions small". | `trade_offer` stays private; a client subscribes `SELECT * FROM my_offers` once per connection. |

**The view.** `my_offers` (`perception.rs`, `primary_key = id`) returns, for the caller's living character (`living`, as the other `my_*` views), every `trade_offer` row addressed to it and the one it made (a new offer replaces the maker's earlier one, `act.rs` `Effect::Offer`). Its row, `MyOffer`:

| Column | Type | Meaning |
|---|---|---|
| `id` | `u64` | the offer (primary key: the bindings give updates) |
| `incoming` | `bool` | addressed to me (I may accept it), or mine |
| `from`, `to` | `u32` | character ids. The client names them through `seen_characters`; the row carries no name the caller may not know. |
| `give_item`, `give_qty` | `String`, `u32` | what `from` gives |
| `want_item`, `want_qty` | `String`, `u32` | what `from` wants of `to` |
| `at_ms` | `u64` | when it was made (world time, ms since the Unix epoch, as `experience.at_ms`) |
| `until_ms` | `u64` | it can be accepted while world time ≤ `until_ms` |

One view with a direction column rather than two views: the outgoing offer costs one more point read in the same refresh, and a client needs both to draw its own standing offer beside the ones made to it.

**The end of an offer.** `trade_offer` gains `until_ms`, set when the offer is made to `at_ms` + the `trade_window_s` law (180 s). `accept`, the mind's scene and housekeeping read it (`TradeOffer::ends_ms`); a law changed while an offer stands no longer changes that offer's end. Housekeeping (1 Hz) now deletes a trade offer as soon as it ends, not a minute later, so the row leaves `my_offers` within a second. A row written before the column (its default 0) is read through the law's window and given its end at the next housekeeping. `perceive.rs`'s "asked of you" now reads offers through the new `to` index instead of scanning the table. Bond offers are unchanged.

**Accept and decline.** Accepting is the existing `accept` act toward the maker (`from`), unchanged: refused with the rules' words when either side lacks the goods or the offer has ended, else the goods move both ways and the row goes. `accept_done` takes a proposal record of terms from the same person first, and the standing trade only when there is none. There is no decline act: an offer ends at `until_ms` or when its maker offers again.

**Data paths.** Writes: one insert per offer, a delete per accept, replacement or end. Each re-runs the `my_offers` of the players who are its maker or addressee (the previous addressee too when an offer is replaced), and nobody else's. Reads: two point reads plus the `living` lookup per refresh. Retained: at most one row per character, for at most `trade_window_s` plus one second. Subscribers: the two parties.

### The field of view (seventh change)

Seventh change (2026-11-11, branch `fov-1`). In two play-tests the owner said that what they see does not change with the way their character faces; in the third they switched to the cursor-facing control scheme after 90 seconds and stayed in it. Sight was a radius and a clear line, the same in every direction.

**The rule** (`living/rules/src/sight.rs`, pure; no `scripting` feature needed):

```rust
living_rules::sight::sees(map, eye, heading, at, dist, &senses, glow, kept) -> bool
```

- `senses` is `living_rules::sight::Senses { sight, hearing, field: Option<Field> }`, what the script's `senses(a)` returns (`script::Senses` is the same type). `Field { focal_deg, side_deg, side_share, near_m, margin_deg }`.
- `heading` is the observer's facing: `body.heading` at the instant (`common::heading_at`, the turn under way included, as `steer::pose` gives it).
- `glow` is the light on the target (the `glow` law; 0 without one). `kept` is `Some(keep_seen_m)` when the target is already seen.
- **Without a field** the answer is the old rule exactly: `dist <= max(sight, glow) (+ keep_seen_m when kept)` and `Map::sight_clear`. The rules test `without_a_field_the_answer_is_the_old_rule` compares the two over 311,040 cases (sights, glows, keeps, 360 directions, nine distances, three headings, a wall).
- **With a field**, how far one sees depends on the angle off facing (`sight::reach`, which a client draws the field from): `max(sight, glow)` within `focal_deg`; `max(sight × side_share, glow)` out to `side_deg`; nothing beyond; and all round within `min(near_m, sight)`. Someone already seen keeps `margin_deg` more on each angle and `keep_seen_m` more on each distance, so a creature at an edge does not flicker. A light on someone shows them only within the field: a torch behind you is not seen. The sight line is tested after, as before.
- **Hearing** stays all round.

**The law.** `senses(a)` returns `field: sight_field(a)` when `law("fov_on")` is true, and no `field` otherwise. Every value is a constant of `laws()`, so a seed's `rules` or `set_world_law` sets it:

| Law | Shipped | Meaning |
| --- | --- | --- |
| `fov_on` | false | sight depends on facing |
| `fov_focal_deg` | 70 | full sight within this many degrees either side of facing |
| `fov_side_deg` | 110 | side vision out to this angle |
| `fov_side_share` | 0.3333 | side vision reaches this share of sight |
| `fov_near_m` | 3 | all round within this distance |
| `fov_near_dark_m` | 2 | the same in the dark (`light_of(a)` is `night`: no torch) |
| `fov_margin_deg` | 10 | someone already seen stays seen this far past an edge |
| `heard_near_m`, `heard_close_m` | 5, 15 | a sound's distance bands: near, close, far out to hearing |
| `heard_linger_s` | 2 | a sound is kept this long after it was last heard |

`law(name)` is a new primitive for laws: the value in force, the script's `laws()` with the world's own values over it. Cullet's overlay replaces `senses` and carries the same `field` line (`living/seeds/worlds/cullet/laws.rhai`). When the field is on, `senses_law`'s description, which minds are told, says so ("One sees that far only within about 70 degrees either side of the way one faces, … one hears what is behind one, and turns to see it.").

**Facing** is one state, the body's heading as the authority holds it: steering sets it (the travel direction, kept while standing), and so do the `face` act and the turns of a strike, a guard and an aim. No second facing state was added. A player's facing input (`human_face`) is the last part of this change and is not in this section.

**Where it applies.** `perception::in_sight(ctx, map, observer, eye, heading, target, at, dist, w, now, kept)` asks the observer's senses and the target's glow and calls `sight::sees`. `perception::sensed` (what a graph's scene and a mind's scene see and hear, from one gather) and the players' sweep call `sight::sees` directly with the senses read once. Every path goes through it: players' perceived sets (`sweep_one`, with `kept` for those already perceived), minds' scenes and behaviour graphs (`sensed`), witnessed events (`perceive::witnessed`), a carer seeing a crying infant (`perception::sees`), the combat feed and the witnesses of a death (`combat::show`, `combat::died`), what a predator senses before it attacks (`act.rs`), and a player's aimed act ("you cannot see them", with `kept` when the target is in the player's perceived set). The chunk-body cache now holds each body's heading at the instant (`NearCreature.heading`), so onlookers' facing costs no extra lookup.

**What is not seen coming.** A graph's `threatened` condition (a hostile windup aimed at me) now holds, while the field is on, only when the one winding up is seen. Without a field it is as before: any windup aimed at me, seen or not. See [combat](COMBAT.md#backstabs-when-sight-depends-on-facing) for when a blow from behind lands unseen.

#### Heard, not seen

A creature within hearing (`senses(a).hearing`, all round, no sight line) and not seen appears coarsely, while the listener's senses have a field. Without a field nothing is told as heard, so a world with the law off perceives exactly as before. This follows the scent pattern: kind, rough direction and distance, never who.

- **Players: `heard_sounds`** (per-sender view, `primary_key = key`) returns `HeardSound { key: u64, kind, bearing: u8, band: u8 }`. `kind` is the `heard_as(kind)` law's word: "person", "deer", "wolf", or "creature" where the rules cannot tell. `bearing` is one of eight compass ways from the listener (0 north, clockwise). `band` is 0 near, 1 close, 2 far. `key` is derived from the listener, the creature and a secret salt (`hear_salt`, one private row drawn from the module's random source) in four-minute epochs. It is fixed when the sound starts and stays while it lasts, so a client can follow one sound, but it is not the character id and cannot be matched to one without the salt. The rows are kept in a private table `heard` (indexed by `viewer`; it holds the target, which the view leaves out), written at the 200 ms sweep only when a sound starts or its bearing or band changes, deleted at once when the creature comes into sight and `heard_linger_s` after it was last heard (module memory holds when; a fresh instance starts each row's linger at its first sweep). A death deletes the player's rows.
- **Minds' scenes** (`perceive::scene_json`) carry, while the field is on, `you.facing` (a compass way) and a list under `you hear (out of sight)`, in a person's words, with no id: `{"what": "a person", "where": "behind you, to the east", "how far": "near"}` (`sight::heard_words`; "something moving" for a creature). The mind service sends the scene as it is, so this is what a model reads.
- **Minds' percepts.** A body that hears something near and out of sight notices it when it begins (`brain.rs`, `SOUND_NEAR`): "You hear a person near, behind you, to the south-west." (kind `signal`, no subject, placed where the listener stands).
- **Behaviour graphs.** A new target, `"sound"`: toward the nearest thing heard and not seen (a point; the body does not learn who). `"speaker"` resolves, for a target the body acts on, toward the voice when the speaker is heard and not seen.
- **The habit** (`living/seeds/instincts.json`, people and the young): a branch labelled `turn to a sound`, after the danger, hunger and sleep branches. When someone spoke within 3 s, cannot be seen and is heard within 12 m, face the speaker. Standing, with a sound within 5 m, face the sound. It is an ordinary branch of the graph the character owns, keeps, changes or drops. Nothing is injected, and no guard limits what a character decides. With the law off `sound` never resolves, so the branch never acts; the plan text minds read includes it either way.

#### Changing a law on a running world: `set_world_law`

`set_world_law(name, value)` (admin only, like the other admin reducers; `value` is JSON text: `"true"`, `"0.5"`) changes any constant of `laws()`, of the law's own kind; another name or kind is refused with nothing written. The value is kept as the world's own (`world_law`, as a seed's `rules` are), and the reducer installs the world's script again with the values written at its end as a generated `fn world_law_values()` block (`script::with_world_laws`). The install is validated like `install_script` and given a new `script.revision`. **This is how clients learn it:** the game client already recompiles the `script` row when its revision changes, so `senses(a)` returns the field there at once; the authority's caches and the mind service do the same. Every install keeps the block from `world_law` (an `install_script` of the plain script no longer drops a world's own law values), and a seed's `rules` are written into it at creation.

Every change is recorded in `law_change` (private, kept for good: `name`, `old` (the value in force before), `new`, `at_ms`, `by` (the caller's identity), `revision`) and as a chronicle row of kind `law` ("the world's law fov_on changed from false to true (script revision 13)"), so a run's evidence says which laws were live when.

#### SpacetimeDB documentation consulted (2026-11-11)

Pinned 2.14.1 (`living/Cargo.toml`, `clockworklabs/spacetime:v2.14.1`). The live docs' version selector reads 2.0.0 (and 1.12.0); nothing here depends on a feature newer than what the earlier sections verified in the 2.14.1 source.

| Page | What it says | What follows here |
| --- | --- | --- |
| [Views](https://spacetimedb.com/docs/functions/views/) | `ViewContext` gives the caller; per-user views are computed and tracked per subscriber; views "can only access table data through indexed lookups"; a view is "reevaluated when SpacetimeDB detects something they read has since changed (the read set)" | `heard_sounds` is per sender and reads only `heard.viewer` (a point lookup), so it re-runs only when that player's rows change: at a sound's start, end, or bearing or band change, not at every sweep. It declares `primary_key = key` (allowed for views without arguments) so clients get updates. |
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) | rows "exist only for the duration of the transaction that created them"; "Event tables cannot currently be accessed within view functions" | Not used: a sound must linger and be read through a per-player view. A private table with a view is the pattern `perceived` already uses. |
| [Tables](https://spacetimedb.com/docs/tables/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions/) | private tables are "Visible only to reducers and the database owner"; "Views can read from private tables and expose only the data appropriate for each client" | `heard` holds the target and is private; the view leaves the target out. `hear_salt` and `law_change` are private (the owner reads `law_change` as evidence). |
| [Performance](https://spacetimedb.com/docs/tables/performance/) | prefer indexed lookups; split tables by access pattern; "Be mindful of unbounded table growth" | `heard` is bounded by the creatures within each player's hearing and empties as sounds stop; `law_change` grows by one row per admin change, kept on purpose. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | b-tree point lookups; indexes "slow down inserts and updates" | One index, `heard.viewer`. No index was added to a hot table. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) | adding tables and reducers is allowed | Three tables and one reducer are added; no column changes, so a running world updates in place. |
| [Reducers](https://spacetimedb.com/docs/functions/reducers/), [reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context) | every call has a caller identity (`ctx.sender`); no admin pattern is given | `set_world_law` checks the caller against `world.admin` (`require_admin`), as every admin reducer does. |

#### Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- | --- |
| Sight with a field | the observer's senses (per-moment cache), its body's heading (in the chunk-body cache for onlookers; one PK lookup for a graph scene), the target's glow | — | PK | — | per look, as before | — |
| Heard (players) | creatures within hearing from the chunk-body cache, the player's `heard` rows | `heard` insert, update or delete on change only | `heard.viewer`, PK | that player (`heard_sounds`) | each player every 200 ms (the sweep), only while the field is on | one row per creature heard per player, gone 2 s after it stops |
| Heard (minds) | creatures within hearing | a percept when a near sound begins | — | that mind | per scene, per graph evaluation, only while the field is on | experience rows as before |
| `set_world_law` | `world_law`, the script row | `world_law`, `script` (a new revision), `law_change`, `chronicle` | PK | every client of `script` | per admin call | one `law_change` row per call |

#### Cost: off against on (seventh change)

Tool: `living/tools/bench.py` with two additions for this change, `--law NAME=VALUE` (`set_world_law` before the window) and `graph_scenes` (behaviour graphs' scenes a second, and the creatures each one saw, from a line the module logs once a second while profiling, `common::note_scene`). There are no players and no minds in these worlds, so the costs are the graphs', the witnesses' and the feed's. Arms ran A B B A: off, on, on, off, each a fresh world, one at a time on the private server, with the dev-box's 1-minute load average recorded before each window.

**Island** (seed `island`, 277 people at rest): 60 s at rest after a 15 s settle, then `spawn_skirmish(200, 12)` and 60 s more. This measured the build before `perception::sensed` merged the sight and hearing gathers into one (a graph's scene gathered twice while the field was on); the code that ships is that build plus the merge.

| Window | Arm | Load | Tick p50 / p99 (ms) | Graph evaluations/s | `brain.scene` p50 / p99 (ms), ms per s | Scenes/s | Seen per scene, mean (max) | `housekeeping` p50 (ms) |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | ---: |
| Rest | off | 33.5 | 1.37 / 3.07 | 372 | 0.022 / 0.083, 9.4 | 358 | 3.14 (19) | 0.55 |
| Rest | on | 40.8 | 1.79 / 4.05 | 377 | 0.028 / 0.098, 12.3 | 362 | 2.13 (17) | 0.73 |
| Rest | on | 38.3 | 1.99 / 4.53 | 374 | 0.031 / 0.108, 13.4 | 361 | 2.03 (15) | 0.78 |
| Rest | off | 29.4 | 1.55 / 2.99 | 369 | 0.024 / 0.090, 10.4 | 363 | 2.94 (19) | 0.62 |
| Skirmish | off | 26.9 | 2.40 / 14.9 | 627 | 0.029 / 0.103, 18.2 | 556 | 15.9 (104) | 1.06 |
| Skirmish | on | 37.3 | 2.76 / 12.9 | 812 | 0.023 / 0.113, 22.6 | 741 | 18.0 (112) | 1.03 |
| Skirmish | on | 42.8 | 2.26 / 25.6 | 742 | 0.029 / 0.109, 22.6 | 692 | 17.0 (116) | 0.96 |
| Skirmish | off | 26.5 | 2.89 / 16.2 | 794 | 0.026 / 0.106, 21.7 | 712 | 23.3 (127) | 0.96 |

**Cullet** (`living/seeds/cullet.json`, sight 48 m by day; its seed has no people, so each world got `spawn_crowd(200)` on the forager repertoire): 60 s after a 15 s settle, then `spawn_skirmish(200, 12)` and 60 s more. This measured the build that ships, `perception::sensed` included.

| Window | Arm | Load | Tick p50 / p99 (ms) | Graph evaluations/s | `brain.scene` p50 / p99 (ms), ms per s | Scenes/s | Seen per scene, mean (max) | `housekeeping` p50 (ms) |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | ---: |
| Crowd | off | 23.1 | 1.05 / 2.20 | 260 | 0.079 / 0.197, 21.7 | 253 | 3.93 (13) | 0.36 |
| Crowd | on | 26.8 | 1.44 / 2.87 | 258 | 0.097 / 0.233, 27.0 | 254 | 2.38 (15) | 0.47 |
| Crowd | on | 30.2 | 1.09 / 2.35 | 261 | 0.080 / 0.218, 22.2 | 256 | 2.01 (12) | 0.38 |
| Crowd | off | 10.9 | 0.92 / 1.87 | 260 | 0.068 / 0.180, 19.7 | 258 | 3.44 (10) | 0.30 |
| Skirmish | off | 23.5 | 1.83 / 9.69 | 609 | 0.050 / 0.195, 33.1 | 539 | 29.8 (108) | 0.75 |
| Skirmish | on | 33.6 | 3.31 / 11.4 | 714 | 0.060 / 0.229, 49.0 | 654 | 22.4 (118) | 0.85 |
| Skirmish | on | 23.5 | 1.75 / 8.51 | 658 | 0.035 / 0.152, 27.5 | 617 | 23.5 (115) | 0.56 |
| Skirmish | off | 10.4 | 1.23 / 18.4 | 535 | 0.057 / 0.182, 31.3 | 458 | 30.4 (123) | 0.63 |

- **Fewer people in view.** At rest a graph's scene saw fewer creatures with the field on: 2.1 against 3.0 on the island, 2.0–2.4 against 3.4–3.9 on Cullet. On Cullet's 48 m sight the skirmish's scenes saw a quarter fewer (22–23 against 30). On the island the skirmish's counts (17–18 on, 16–23 off) are within the spread between its two "off" worlds.
- **No cost or saving shows outside the noise.** Cullet's scenes cost three to four times the island's (0.07–0.10 ms against 0.02–0.03 at p50), because 48 m of sight gathers more chunks. Within each world the "on" arms are within the spread of the "off" arms, and the one "on" window that stands out (Cullet's first skirmish, tick p50 3.3 ms) is matched by a higher `housekeeping` in the same window. On the island, at rest every phase of the tick was 25–40% slower in the two "on" windows, including phases the field does not touch (`housekeeping` 0.73–0.78 ms against 0.55–0.62, the need rates, motion). The load was higher during them (38–41 against 29–34), and `brain.scene` rose by the same ratio as `housekeeping`. A scene that sees a third fewer creatures did not get measurably cheaper: most of its cost is the gather of the creatures round it, which is unchanged (the field only skips the sight line for those out of reach). In the skirmish no difference shows outside the spread between arms.

#### Verification (seventh change)

On the dev-box, in a private SpacetimeDB 2.14.1 container (`fov1-stdb`, port 3318), scratch databases only. The host was shared with seven other workers (load average 17–60 on 32 cores throughout).

| Surface | What was driven | Result | Evidence (`.local/living/verify/`) |
| --- | --- | --- | --- |
| Rules | `cargo test -p living-rules`: the field's zones, the margin, `glow` in and out of the field, off giving the old answers (311,040 cases), the law and its block, Cullet's field | 163 of 163 (8 ignored) in `just living-check` | `.local/fov1/check*.log` |
| Core | `scenes.py fov` on the default seed (off, `set_world_law` refusals and record, facing east and west, a duel from behind with the 3 m ring and with a 0.5 m ring, witnesses by facing, off again); `tick`, `sight`, `senses`, `moves`, `death-names` | `fov` 18 of 18; the others pass (again after merging main `accf27c8`: `fov`, `sight`, `senses`) | `core-fov1-j/`, `core-fov1-m/` |
| Player | `scripts/fov.py`: the `face` act turning the body, heard and not seen, the heard row's columns and key, seen when faced, the field's edge and margin, `set_world_law` refused to a player, off again | 18 of 18 (again after merging main) | `player-fov1-d/`, `player-fov1-m/fov.json` |
| Client | `run.py` (the Rust SDK probe): the new private tables and view in the inventories, `set_world_law` admin only, the field of view over real subscriptions | 35 of 36 before merging main (the field of view 5 of 5; the one failure was presence, "one closed" read 0 connections, which this change does not touch); 36 of 36 after merging main `accf27c8` | `client-fov1-a/`, `client-fov1-m/results.md`, `field.json` |
| Minds | `verify_minds.py --case fov` with the fake model (the scene and the prompt: heard in words, no id, facing; the percept; the person instinct's habit turning the body) and `--case sight` | both pass (again after merging main) | `minds-fov1-h-fov/`, `minds-fov1-m-fov/result.json`, `sent-prompt.txt` |

`scenes.py doing` failed twice on one world after the `fov` and `senses` scenes. On that loaded host each admin CLI call took 1 to 14 s, so the walkers had finished their walks (activity `wait`) before the observer's scene was written. It reads activity labels, and no field was on. It failed the same way on `origin/main` (`6288f599`) on the same host.

### Compatibility: the `LIVING_PERCEPTION` build switch

`living/authority/build.rs` reads `LIVING_PERCEPTION` at build time:

- **`scoped`** (the default since the third change, and when the variable is unset): the nine tables behind the views (`body`, `character`, `fighter`, `doing`, `vitals`, `experience`, `place`, `inventory`, `know_how`) are private (`cfg_attr(not(open_tables), …)` in `tables.rs`), so a player receives only what the views return.
- **`open`** (`LIVING_PERCEPTION=open`): those nine are public again. It is for diagnostics, such as reading a table with an anonymous client, and for comparing against the scoped build. The views exist and are correct, but the tables beside them are not a boundary. The lab observer does not need it: it reads as the owner in both builds.

Developer audit truth is private in both. Table visibility is part of the module, so switching is a republish; 2.14.1's automatic migration allows "public → private" (`crates/schema/src/auto_migrate`), so a world can switch in place with `--keep-data`. The reverse, private → public, is a republish too. A world published from an `open` build before the third change becomes scoped at its next republish from the default build.

### The mind service and the observer

- **The mind service** connects with the CLI token, `LIVING_TOKEN` or `.local/living/token` (`living/mind/src/main.rs`), the publisher's identity: the database owner. Its subscriptions (`experience` by controller, `character`, `brain`, `persona`, `relation`, `judgment`, `place`, `know_how`, `community`, `membership`, `background`, `routine`, `routine_stat`, `genome`, `script`, offers, `my_deliberations`) keep working on private tables. Nothing in it changed.
- **The lab observer** (`living/viewer`) connected anonymously. It now passes the owner's token: `LIVING_TOKEN` or `.local/living/token` natively, and on the web the page's `#token=…` fragment, which the browser never sends to a server. Without one, its subscription fails with a message saying so. **The public observer** (`https://sos.carlid.dev`) had no token, so after this change it could show nothing of minds, bodies (in a scoped build) or the chronicle. It was retired on 2026-11-09 (its services are stopped and disabled; [living core](LIVING_CORE.md#running)).
- **The verification harness** reads SQL as the owner by default now (`verify.py sql`; `--anonymous` for public-only reads), and its observer screenshots pass the token in the fragment.
- **Bindings** are generated with `--include-private` (`just living-generate`), identical for both builds.

### Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| Perception sweep | the player's body, the shared chunk-body cache within sight + 1, the cached map, the player's `perceived` rows | `perceived` inserts and deletes on change only | `perceived.viewer`, PKs | — | each player every 200 ms, staggered across ticks | one row per creature in sight per player; deleted at death |
| `seen_*` refresh | as in the table above | the view's ephemeral rows (no commitlog) | point lookups | that player | at its frame when a copy changed; at once for its own body, fighter and projection; `seen_doing` when a `doing` row in its scene changes or someone comes or goes | — |
| Frames (fourth change) | the viewer's scene (module memory), the changed creatures' `body`, `fighter`, `vitals` rows, the viewer's copies by key | `motion_seen`, `fighter_seen` and `projected` updates when they differ; onlookers' `combat_seen` inserts and expired deletes; `line_seen` releases and trims | PKs (`frame::key(viewer, creature)`), `projected.by_viewer_body`, `line_seen.by_observer_shown` | that player | each player every 33–100 ms by its scene's size, at most 2,500 creatures of scene per step, stalest first | `motion_seen` and `fighter_seen`: one row per creature in a player's scene, deleted with the `perceived` row and at death; `line_seen` ≤ 64 per character (kept for the dead) |
| `my_*` refresh | the player's own rows | ephemeral rows | point lookups | that player | when the player's own rows change; `my_experience` at a frame that released lines | `experience` ≤ 400 rows per character, as before |
| Static windows | `terrain_chunk`, `lot` by chunk range | — | `lot.chunk`, PK | clients that subscribe | on edits | — |
| Projection (second change) | the target's character, vitals and the settlement round its home; the observer's know-how, relations, membership, acquaintances, reveals; the cached law | `projected` insert on coming into sight; update when it changes; delete with the `perceived` row and at the target's death | `projected.viewer`, `projected.body`, `acquaintance.by_pair`, `relation.by_pair`, `membership.member`, `reveal.observer` | that player (`seen_characters`, `seen_fighters`) | on entering sight, knowledge or reveal changes, band changes | one row per creature in a player's scene, own included |
| Minds' sight (second change) | per onlooker: its body, its sight, the cached map; per event or scene | — | PK, chunk-body cache | — | per witnessed event, per scene, per behaviour-graph scene | — |
| Reveals, acquaintances | — | `reveal` insert per appraisal, deleted when ended (index range on `until_ms`, 1 Hz); `acquaintance` insert per hearer of a self-introduction, and per other member of a community at a member's death (`membership.community`) | `reveal.observer`, `reveal.until_ms`, `acquaintance.observer`, `.by_pair` | — | per skill use, per introduction, per death in a community | acquaintances grow with introductions and with a community's dead (deleted with the observer at death) |
| Perceived activity (fifth change) | per creature in a scene or a first sight: its `activity` row, and `steer` and `body` when the activity is none or `wait` | — | PKs | — (a mind's scene, an experience line) | per scene, per first sight | — |

No routine action gained a whole-table scan. The sweep's cost is per player, not per world.

## Measurements

Measured on the dev-box (32 cores, Fedora; SpacetimeDB 2.14.1 in its own container), on fresh `verify-perc-bench` databases, seed `island`: 252–268 residents at the start (no minds, `rules.minds = false`), 24 deer, the wolves and the bold pack, plus the players. 60 Hz tick. Each run publishes the module fresh, joins N player identities over HTTP, places them with `place_at`, waits 20 s, then measures 60 s, at world hours 07:50–08:10 (day: sight 11 tiles). Tool: [`living/tools/perception_bench.py`](../living/tools/perception_bench.py) with [`living/tools/perception_load`](../living/tools/perception_load) (one Rust SDK connection per player, subscribing as the game client does). Raw reports (one JSON per run) are kept in the Mac checkout's git-ignored `.local/living/verify/perception-bench/m3/`.

- **base**: `0887d81` (origin/main), clients subscribing what the game client subscribes today (static tables, own rows by id, the ±5-chunk `body` window with its `character`, `fighter` and `doing` joins, the ±3 `terrain_chunk` and ±11 `lot` windows).
- **scoped**: this branch built with `LIVING_PERCEPTION=scoped`, clients subscribing the views (static tables and the `terrain_chunk` and `lot` windows unchanged).
- **open**: this branch's default build with today's client subscriptions (the compatibility path: the sweep runs, no view is subscribed).
- **spread**: players at lot doors round all six settlements in turn; **square**: within 6 m of the walled town's centre. Players stand still, or **walk** in small circles (a new `human_move` direction every 1.5 s each).

**Wire bytes** are what each player's connection received, counted by a TCP proxy between the load and the server. The server's own `spacetime_num_bytes_sent_to_clients_total` is unusable for the base: 2.14.1 counts a query update's bytes once however many clients share the query (`encode_v2_rows`, `crates/core/src/subscription/module_subscription_manager.rs`: "We only encode once, then we clone for other clients"), so 50 players in one window read as about 200 B/s each against 3.2 kB/s on the wire.

**Tick** columns: "code" is the tick reducer's own LogStopwatch span, as earlier benchmarks report it; "tx mean" is `spacetime_reducer_plus_query_duration_sec{reducer="tick"}` sum ÷ count, the tick with its view refresh and subscription evaluation; "tx > 5 ms" counts ticks in that histogram above its smallest bucket, of about 3,600. View calls per second are `view_calls_triggered_by_reducer` over all reducers; "view WASM" is the views' `reducer_wasm_time_usec`, without materializing their rows (that is in "tx mean").

| Run | Players | Host load | Tick code p50 / p95 / p99 / max (ms) | Tick tx mean (ms) | tx > 5 ms | Sweep (ms/s) | View calls/s | View WASM (ms/s) | Bodies held per player | Body updates/s per player | Wire B/s per player |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base, spread | 1 | 4.1 | 1.14 / 1.91 / 2.45 / 3.6 | 1.35 | 0 | — | — | — | 76 | 17.4 | 4,377 |
| scoped, spread | 1 | 6.3 | 1.25 / 2.03 / 2.50 / 4.1 | 1.44 | 0 | 0.5 | 1.1 | 0.02 | 4 | 0.1 | 95 |
| base, square | 1 | 6.9 | 1.29 / 2.28 / 2.95 / 5.3 | 1.58 | 2 | — | — | — | 77 | 15.2 | 3,971 |
| scoped, square | 1 | 10.8 | 1.60 / 2.71 / 3.87 / 12.1 | 1.96 | 26 | 0.6 | 4.3 | 0.2 | 13 | 1.7 | 446 |
| base, spread | 10 | 21.4 | 1.22 / 2.37 / 3.18 / 6.7 | 1.76 | 29 | — | — | — | 36 | 7.8 | 2,076 |
| scoped, spread | 10 | 15.6 | 1.79 / 3.06 / 3.88 / 7.6 | 2.20 | 21 | 1.7 | 14.9 | 0.69 | 4.2 | 0.5 | 154 |
| base, square | 10 | 28.0 | 1.58 / 2.66 / 3.57 / 7.9 | 2.11 | 25 | — | — | — | 84 | 15.3 | 4,085 |
| scoped, square | 10 | 24.4 | 1.10 / 1.80 / 2.23 / 2.9 | 1.25 | 0 | 1.3 | 39.6 | 0.72 | 11.4 | 1.1 | 402 |
| base, spread | 50 | 10.5 | 1.24 / 2.12 / 2.67 / 4.4 | 2.64 | 217 | — | — | — | 30 | 7.1 | 1,890 |
| scoped, spread | 50 | 7.2 | 1.28 / 2.19 / 2.75 / 4.6 | 1.57 | 0 | 3.3 | 46.1 | 1.01 | 2.4 | 0.4 | 101 |
| base, square | 50 | 6.5 | 1.37 / 2.38 / 2.96 / 4.7 | 1.78 | 3 | — | — | — | 120 | 12.3 | 3,191 |
| scoped, square | 50 | 8.7 | 1.37 / 2.32 / 2.87 / 4.6 | 1.66 | 11 | 5.0 | 72.8 | 1.95 | 30.4 | 0.1 | 128 |
| open, square | 50 | 5.3 | 1.26 / 2.23 / 2.84 / 4.3 | 1.53 | 0 | 6.4 | 0 | — | 124 | 15.5 | 4,288 |
| base, square, walk | 10 | 3.7 | 1.08 / 1.77 / 2.19 / 2.9 | 1.29 | 0 | — | — | — | 90 | 28.9 | 6,835 |
| scoped, square, walk | 10 | 3.6 | 1.11 / 1.85 / 2.26 / 3.4 | 1.37 | 0 | 1.7 | 155 | 2.8 | 11.3 | 5.5 | 1,771 |
| base, square, walk | 50 | 5.1 | 1.13 / 1.97 / 2.41 / 3.5 | 1.40 | 0 | — | — | — | 116 | 70.3 | 14,481 |
| scoped, square, walk | 50 | 5.0 | 1.22 / 2.15 / 2.63 / 4.4 | **2.77** | **402** | 4.5 | **1,896** | **48.1** | 30.4 | 23.3 | 5,317 |
| open, square, walk | 50 | 3.8 | 1.31 / 2.31 / 2.91 / 3.7 | 1.59 | 0 | 5.1 | 0 | — | 128 | 73.8 | 15,444 |

Host load is the dev-box's 1-minute load average when the run started. A GitHub Actions runner on the host pushed it to 10–28 during the 1- and 10-player square and spread runs, so their differences in either direction (scoped 1-square's 12 ms maximum, base 10-square's p99 3.57) are within that noise. Each configuration was run once in this matrix; an earlier pass of the same matrix on the pre-merge code (`m2`, partly discarded) gave the same picture.

What the numbers say:

- **At rest the views cost nothing measurable.** The tick's own p99 stays at 2.2–2.9 ms on a quiet host in both builds, against the 2.8 ms at rest the island has been measured at. The sweep costs 0.1 ms of work per second per player (13–25 µs a sweep); the views 0.02–2 ms/s at 1–50 players. 50 spread players cost the base more (tx mean 2.64 ms, 217 ticks over 5 ms) than the scoped build (1.57 ms, none): 50 distinct chunk windows are evaluated as 50 query sets on every tick that moves a body, while a view is re-run only for the players who perceive the change.
- **Bytes per player fall by 90–98% at rest** (1.9–4.4 kB/s → 0.1–0.45 kB/s), and by 63–74% when everyone in sight is walking (6.8 → 1.8 kB/s at 10, 14.5 → 5.3 kB/s at 50). The cut has two parts: what is sent is what is in sight (2–30 bodies instead of 30–124), and each row is the 52 B `Motion` row instead of the `body` row with its path.
- **The worst case measured: 50 players clustered in the square, all walking.** Each of the ~30 walkers a player sees changes steering several times a second, so most players' `seen_bodies` re-runs on most ticks (1,269 view calls/s from the tick, 627/s from the `human_move` calls themselves). The views' WASM is 48 ms/s; with materializing, the tick transaction's mean rises from 1.40 to 2.77 ms and 11% of ticks exceed 5 ms (none in the base). The tick's own code is unchanged (p99 2.63 ms). That is about 43 µs per view refresh in all, which predicts the cost elsewhere: refreshes per tick ≤ min(players, players perceiving a body that changed this tick).
- **Server CPU** was 0.11–0.22 cores at rest in both builds, 0.30 against 0.18 for the 50 walking. **Memory:** the world's module WASM memory was 74.8 MB in every run. The server container's memory grew from 2.8 to 3.8 GB over the matrix's ~40 publish-and-delete cycles of the bench database (service-wide allocator retention across databases, not one world's footprint; jemalloc resident about 1.7 GB).
- **Not measured:** night (sight 6 tiles: smaller sets, cheaper), a battle seen by many players, the 216-character gate with its observers and minds, and durations past a minute.

## Second change: measurements

On the Mac checkout (Apple M-series, 14 cores, Docker Desktop; SpacetimeDB 2.14.1 in the shared `sao-living_spacetimedb_1`), scratch databases only (`verify-bench-sight`, `verify-bench-crowd`, deleted after). Back to back, alternating builds: **base** is main at `972aefd` (a detached worktree), **change** this change before the sight fast path, **change2** this change as it stands (with `Map::sight_clear`'s open-chunk fast path and the sweep that skips unchanged scenes). Load on the host: another session's process used about 4 of the 14 cores throughout, and another worker's `verify-polish` world was live on the same server (the 1-minute load average was 5–15). Read single maxima and single p99s as indications; the spread between two runs of one build is as large as most differences below.

### The tick: at rest and a 200-character skirmish

`living/tools/bench.py` (60 s windows of the tick's own LogStopwatch spans, no subscribers), on a fresh database per window pair: 60 s at rest after a 15 s settle, then `spawn_skirmish(200, 12)` and 60 s from about 4 s later. Two seeds: `island` as shipped (`rules.minds = false`: residents live on their graphs, no percepts are written), and a scratch copy with minds on (`verify-island-minded`: residents are AI characters, so percepts, witnessed events and deliberation requests are written; no mind service connected). Raw reports: `.local/living/bench/tick/` (git-ignored).

"People" is the count alive at the window's end (the skirmish adds 200 and kills most). Tick times in ms.

| Seed | Window | Build | Run | People | Animals | Ticks/s | Evals/s | Experiences/s | p50 | p95 | p99 | Max | >16.7 ms | tick ms/s | combat ms/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| island | rest | base | 1 | 258 | 34 | 59.8 | 367.1 | 0.0 | 2.03 | 3.58 | 4.48 | 7.4 | 0 of 3604 | 125 | 2.0 |
| island | rest | base | 2 | 260 | 34 | 59.8 | 353.5 | 0.0 | 1.41 | 2.90 | 3.68 | 5.5 | 0 of 3604 | 93 | 0.2 |
| island | rest | base | 3 | 254 | 34 | 59.8 | 373.3 | 0.0 | 1.82 | 3.39 | 4.54 | 10.5 | 0 of 3604 | 115 | 4.0 |
| island | rest | base | 4 | 254 | 33 | 59.8 | 356.2 | 0.0 | 1.84 | 3.38 | 4.28 | 7.7 | 0 of 3604 | 116 | 2.2 |
| island | rest | change | 1 | 262 | 34 | 59.8 | 349.2 | 0.0 | 1.52 | 2.94 | 3.60 | 6.5 | 0 of 3605 | 98 | 0.2 |
| island | rest | change | 2 | 261 | 33 | 59.8 | 380.3 | 0.0 | 1.59 | 3.09 | 4.02 | 7.2 | 0 of 3604 | 103 | 3.0 |
| island | rest | change2 | 1 | 252 | 34 | 59.8 | 338.4 | 0.0 | 1.78 | 3.19 | 4.16 | 6.9 | 0 of 3604 | 111 | 0.3 |
| island | rest | change2 | 2 | 261 | 34 | 59.8 | 358.5 | 0.0 | 1.74 | 3.04 | 3.78 | 7.3 | 0 of 3605 | 109 | 0.2 |
| island | skirmish | base | 1 | 302 | 33 | 59.2 | 1137.7 | 0.0 | 3.27 | 9.61 | 13.23 | 24.4 | 11 of 3575 | 241 | 81.3 |
| island | skirmish | base | 2 | 308 | 34 | 59.4 | 1047.7 | 0.0 | 2.73 | 9.05 | 12.66 | 27.8 | 10 of 3585 | 209 | 54.7 |
| island | skirmish | base | 3 | 289 | 34 | 58.4 | 1000.9 | 0.0 | 3.07 | 10.35 | 18.00 | 50.5 | 45 of 3534 | 237 | 59.7 |
| island | skirmish | base | 4 | 263 | 33 | 58.6 | 931.3 | 0.0 | 3.36 | 9.77 | 16.13 | 29.1 | 29 of 3548 | 240 | 75.6 |
| island | skirmish | change | 1 | 295 | 34 | 57.3 | 861.6 | 0.0 | 2.44 | 12.33 | 19.66 | 35.3 | 65 of 3469 | 215 | 55.6 |
| island | skirmish | change | 2 | 277 | 30 | 57.4 | 915.1 | 0.0 | 2.51 | 11.31 | 23.42 | 93.3 | 74 of 3478 | 224 | 65.1 |
| island | skirmish | change2 | 1 | 298 | 34 | 59.2 | 993.2 | 0.0 | 3.21 | 9.95 | 14.31 | 21.0 | 15 of 3571 | 237 | 56.8 |
| island | skirmish | change2 | 2 | 283 | 34 | 58.2 | 976.2 | 0.0 | 2.69 | 10.82 | 18.29 | 70.4 | 50 of 3511 | 227 | 57.5 |
| verify-island-minded | rest | base | 1 | 267 | 34 | 59.8 | 362.5 | 35.9 | 1.90 | 3.48 | 4.31 | 7.5 | 0 of 3604 | 119 | 0.2 |
| verify-island-minded | rest | base | 2 | 262 | 34 | 59.8 | 365.8 | 40.3 | 2.06 | 3.81 | 4.76 | 8.9 | 0 of 3604 | 130 | 2.1 |
| verify-island-minded | rest | base | 3 | 265 | 34 | 59.8 | 360.0 | 35.6 | 1.79 | 3.21 | 4.12 | 6.7 | 0 of 3603 | 112 | 0.2 |
| verify-island-minded | rest | change | 1 | 254 | 34 | 59.8 | 342.9 | 34.2 | 1.77 | 3.46 | 4.29 | 14.4 | 0 of 3604 | 114 | 0.2 |
| verify-island-minded | rest | change | 2 | 257 | 34 | 59.8 | 358.1 | 40.2 | 1.57 | 2.99 | 3.81 | 5.6 | 0 of 3604 | 100 | 1.6 |
| verify-island-minded | rest | change2 | 1 | 254 | 34 | 59.8 | 343.4 | 35.1 | 2.18 | 3.88 | 4.70 | 7.1 | 0 of 3604 | 136 | 0.2 |
| verify-island-minded | skirmish | base | 1 | 310 | 34 | 57.7 | 971.0 | 9.0 | 2.69 | 11.50 | 23.16 | 48.9 | 67 of 3503 | 246 | 61.4 |
| verify-island-minded | skirmish | base | 2 | 292 | 34 | 58.6 | 917.1 | 9.6 | 3.03 | 9.63 | 16.68 | 44.4 | 36 of 3544 | 228 | 51.8 |
| verify-island-minded | skirmish | base | 3 | 312 | 34 | 59.0 | 1047.2 | 11.4 | 3.19 | 9.54 | 13.76 | 31.6 | 15 of 3559 | 236 | 61.6 |
| verify-island-minded | skirmish | change | 1 | 287 | 34 | 57.4 | 868.5 | 12.6 | 2.88 | 11.69 | 19.74 | 40.0 | 70 of 3481 | 231 | 59.1 |
| verify-island-minded | skirmish | change | 2 | 286 | 34 | 59.1 | 943.3 | 12.5 | 2.53 | 9.24 | 13.76 | 23.1 | 17 of 3570 | 200 | 51.1 |
| verify-island-minded | skirmish | change2 | 1 | 292 | 34 | 59.1 | 979.0 | 8.2 | 3.38 | 9.32 | 13.48 | 25.2 | 10 of 3568 | 235 | 52.9 |

What it says:

- **At rest the change costs nothing measurable** on either seed (p99 3.6–4.7 ms against 3.7–4.8 ms for base). The minds' sight lines (witnessed events, scenes, behaviour graphs) and the projection's labels run on events and evaluations that are rare at rest.
- **In the skirmish, the first version was slower**: on the shipped seed p99 19.7 and 23.4 ms against 12.7–18.0, 65–74 ticks over budget against 10–45, and 15% fewer behaviour-graph evaluations per second (the evaluation budget was spent on sight lines). A packed battle puts about 200 creatures in every fighter's sight, so each evaluation traced about 200 sight lines.
- **With the open-chunk fast path** (`Map::sight_clear` answers without a tile walk when no chunk the segment's box touches holds rock or wall and no shut gate lies in the box; the per-chunk table is built once and kept by `set` and `put_chunk`; a randomized test checks it against the walk) the skirmish is back within base's spread: p99 14.3 and 18.3 ms on the shipped seed, 13.5 ms with minds, evaluations 976–993/s against 931–1,138/s. This battle is on open ground north of the arrival point; a battle among walls (a town) still walks tiles, and was not measured.

### The crowd case: 50 players clustered and walking

`living/tools/perception_bench.py --mode scoped --players 50 --placement square --walk` (as in [Measurements](#measurements): 50 Rust SDK connections subscribing the views, walking in small circles in the walled town's square, 60 s after a 20 s settle), scoped builds of base and the change, each with its own `perception_load`. Raw reports: `.local/living/bench/crowd/`.

Builds: base; change (first version); change2; change3, the code as it stands.

| Build | Run | Tick code p50 / p95 / p99 / max (ms) | Tick tx mean (ms) | tx > 5 ms | tx > 10 ms | Sweep (ms/s) | View calls/s | seen_bodies / seen_characters / seen_fighters / seen_doing WASM (ms/s) | Wire B/s per player | Server CPU |
|---|---|---|---|---|---|---|---|---|---|---|
| base | 1 | 1.02 / 1.75 / 2.22 / 3.0 | 2.48 | 387 | 144 | 3.8 | 1633 | 27.0 / 4.2 / 1.8 / 3.2 | 4520 | 0.38 |
| base | 2 | 1.03 / 1.82 / 2.29 / 2.9 | 2.60 | 413 | 146 | 4.0 | 1688 | 27.6 / 4.1 / 1.8 / 4.6 | 4573 | 0.39 |
| base | 3 | 1.00 / 1.82 / 2.31 / 3.0 | 2.70 | 449 | 149 | 4.1 | 1753 | 30.4 / 4.6 / 1.9 / 4.7 | 4857 | 0.40 |
| change | 1 | 1.01 / 2.76 / 3.84 / 4.9 | 2.67 | 418 | 162 | 10.0 | 1700 | 27.8 / 2.8 / 3.5 / 4.8 | 4333 | 0.39 |
| change | 2 | 1.03 / 2.99 / 4.06 / 5.5 | 2.83 | 463 | 169 | 10.7 | 1736 | 30.2 / 2.9 / 3.5 / 5.0 | 4533 | 0.40 |
| change2 (sweep skips unchanged scenes) | 1 | 1.10 / 2.76 / 3.85 / 8.6 | 2.92 | 483 | 186 | 9.7 | 1764 | 32.0 / 3.0 / 3.7 / 4.5 | 4642 | 0.41 |
| change2 (sweep skips unchanged scenes) | 2 | 1.01 / 2.60 / 3.71 / 4.8 | 2.73 | 447 | 173 | 9.4 | 1726 | 28.7 / 2.9 / 3.6 / 5.2 | 4403 | 0.38 |
| change3 (as it stands: own row once a second) | 1 | 1.01 / 2.58 / 3.61 / 7.6 | 2.79 | 440 | 169 | 9.2 | 1774 | 30.8 / 2.9 / 3.8 / 5.1 | 4648 | 0.37 |
| change3 (as it stands: own row once a second) | 2 | 1.07 / 2.63 / 3.74 / 4.7 | 2.75 | 428 | 168 | 9.2 | 1704 | 28.9 / 2.9 / 3.6 / 4.2 | 4425 | 0.38 |

- **The first version** cost the tick's own code about 1.6 ms at p99 (2.2 → 3.8–4.1 ms) and the sweep 4 → 10 ms/s: every sweep re-read and re-projected the viewer's rows. `seen_characters` costs less than on main (2.8–2.9 against 4.1–4.2 ms/s of view WASM: it reads only the viewer's own projected rows, not the characters'), `seen_fighters` more (3.5 against 1.8: it now reads the projections), and the tick transaction's mean rose 0.2–0.3 ms.
- **As it stands** (change3: a sweep with no one coming or going and no input changed touches only the viewer's own row, and that row is projected again about once a second), the sweep is 9.2 ms/s against base's 3.8–4.1, the tick's own p99 3.6–3.7 ms against 2.2–2.3, and the tick transaction's mean 2.75–2.79 ms against 2.48–2.70 (ticks over 5 ms: 428–440 against 387–449). With everyone walking, someone comes into or goes out of each player's sight on nearly every sweep, so most of the remaining cost is projecting arrivals (3.3 a second per player) and reading the viewer's projected rows; the skip helps a crowd at rest, not this one. Bytes per player are unchanged (4.4–4.6 kB/s against 4.5–4.9).
- **Cost per player**, worst case measured: about 0.1 ms of sweep work per second more than main (about 20 µs a sweep). A cheaper `project` (fewer index reads per arrival: know-how, family and membership looked up once per sweep instead of per target) is the next step if a crowd of players needs it; not done.

## Second change: verification

On the Mac checkout, scratch `verify-*` databases on the shared 2.14.1 container, the fake model server for every mind (no paid call was made). Code: main `81b9dd8` plus this change (uncommitted). Evidence under the git-ignored `.local/living/verify/` (directories named below); benchmark reports under `.local/living/bench/`.

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Build | `set -o pipefail; just living-check` | exit 0; rules 100 passed (new: `what_one_perceives_of_another_is_the_law_s`, `appraising_reveals_health_for_a_while`, `sight_over_open_chunks_agrees_with_the_tile_walk`, `ids_written_as_strings_are_ids`); mind 49 passed (new: `experience_ids_written_as_strings_are_kept`; the cadence test now ends a session by the takeover) | `perc2/check.log` |
| Client, scoped | `verify-client` `run.py` with `LIVING_PERCEPTION=scoped`: the projection's columns, in sight, beyond sight and behind rock, presence (one, two, one, no connection; the takeover after 30 s; the handback on a new connection), the new private tables refused to players and anonymous clients | 29 PASS, no XFAIL (a first run stopped at the driver's table inventory, which lacked `projected`; fixed) | `client-perc2-scoped2/` (`client-perc2-scoped/` the stopped run) |
| Client, open | the same on the default build | 30 PASS and the known XFAIL (`experience` public in the open build) | `client-perc2-open/` |
| Game client | the updated client patch (`docs/perception-client.patch`, since applied and deleted), built in a temporary worktree at HEAD (release, no warnings), headless on the scoped island run: join, walk into the square, speak | digests match; 1–9 perceived bodies and characters as it walked in, `doing` rows, residents drawn in their towns' dress from `folk`/`style`, the speech bubble and log | `perc2/game/game.log`, `perc2/game/shots/` |
| Player | `verify-player` `appraise.py` (new) and `gesture.py` on a scoped island run; `combat.py --fresh` | appraise 10 of 10; gestures 10 of 10 after a driver fix (it placed the player where a stall's building hid the resident, so the wave at someone unseen was refused: the sight rule at work; the driver now picks a spot from which the player sees the resident); combat: see below | `player-perc2/` |
| Minds | `verify-minds`: `takeover` and `sight` (new), `roundtrip`, `acts`, `conversation`, `consolidation` | all pass, consolidation its known XFAIL; `takeover` passed on the third run after a driver fix (it looked for the plan's wait in the top-level graph, which the service writes as desires with a "current plan" routine) and an authority fix (a second takeover reinstalled the minds' graph before asking for a deliberation, and reinstalling counts as having just thought, so the request was refused by `think_min_s`) | `minds-perc2-*/`, `minds-perc2b-takeover/`, `minds-perc2c-takeover/` |
| Core | `verify-core` `cargo_checks.py`; scenes `tick`, `needs`, `seize`, `sight` (new), `skirmish` (island); `town.py` (island); `verify_mechanics.py`, `verify_steering.py` | all pass except town 20 of 21 (see below) | `core-perc2*/` |
| Knowledge | `verify-knowledge` `player_memory.py` (direct): switch off, switch on (provenance, projections, ids given as strings, the identity inferred), takeover (session end by presence, the past internalized before the first deliberation, `lived_under ai`), restart, recall, death | all pass on the fifth run (`knowledge-pmem-perc2e`); the earlier runs found what is fixed below and three driver gaps (a leak check that also matched the player's own words, a relation check made after the minds' consolidation had re-projected the relation, and a restart phase that still relied on idle detection) | `knowledge-pmem-perc2*/` |

Product fixes the runs led to, all in this change:

- **The takeover goes to the world's mind service on every seed.** It first used `common::mind_controller`, which on a seed with `rules.minds = false` (the island) is the database: an offline player's character would never have lived under a mind on the world people play.
- **A second takeover asks for a deliberation before it reinstalls the minds' graph.** Reinstalling counts as having just thought (`set_graph` with source `mind` stamps `deliberated_ms`), so the request was refused by `think_min_s` and the character did not think until something urgent happened.
- **An activity's label names a creature target by its kind**, not its name ("wave → person"): the label is what the doer is told of its act and what onlookers see in their scenes, so it leaked names the observer did not know.

Behaviour changes, expected (row evidence in `core-perc2/sight-*.json`, `minds-perc2-sight/`, `player-perc2/gesture.json`):

- Residents, animals and players' feeds no longer perceive creatures, fights or deaths behind rock, walls or shut gates within their sight radius ("a graph behind rock or a wall does not see it", "the resident behind the wall does not" witness the fight). Speech and smell still pass.
- An act at someone unseen is refused: `gesture.py` first placed its player where a stall's building hid the resident, and the wave was refused.
- Names follow knowledge: players and minds are told "a stranger said to you", "A stranger answers your greeting (nod).", "greeted a stranger" until someone says their name. Seeded residents still know their community and family. (Until town life layer 2, a mind's feelings about someone also counted as knowing their name; the first paid runs of woken residents showed a stranger's name reaching a whole town that way.)
- A mind's scene lists a stranger with `who` (its label) instead of `name`; its wound words come from the health band, so their thresholds moved slightly (barely alive under 20%, badly wounded under 40%, hurt under 65%; they were 15%, 35%, 60%).
- AI speakers now get a `said` experience for each line.
- A taken-over character's experience rows are no longer deleted at consolidation; a player's character keeps its 400-row window.

Not established either way: `town.py`'s "a resident faces someone who comes up behind them" failed in the full town run and in three solo runs on one world; on base (`972aefd`) the same scene passed once and failed on the next run on the same world, so it is the scene's known flakiness ([first change: verification](#verification)), not shown to be caused by this change. Not covered: batch mode of player memory, the paid tiers (no model was called), `verify-core`'s infant scene (about 30 minutes; the infant cry's sight check changed and is covered only by code reading), a battle among walls, and module republish with players connected (presence rows come at their next connection).

## Third change: the client lands

On main `acbbda7`, uncommitted. `git apply --3way docs/perception-client.patch` merged all nine files with `dc5e41b` (polish) and `acbbda7` (wolves, arid lands) without a textual conflict, but `acbbda7` added two reads of tables that are now private, which the patch did not know. They were resolved by hand:

| Where | `acbbda7` read | Now |
|---|---|---|
| `live.rs`, a rigged creature's size by life stage | `character().id().find(id)` | `seen_characters()` (the projection carries `stage`) |
| `combat.rs` `actions`, which drawn bodies are animals (their own clips, their death pose) | `body().id().find(id)` → `kind` | `seen_characters()` → `kind` |

Kept from both sides:
- the wolf model and clips (`bodies::spawn_beast`, `Beast`, `combat::animal_clip`, `combat::death`, the gait family);
- the corpse fix: it works from drawn entities, and in a scoped build a death takes the body out of `seen_bodies` in the same update as the `my_combat` `DEATH` row that keeps the corpse;
- the teleport snap (`SNAP_M`);
- the patch's `folk_of` from `seen_characters`, which replaces the settlement lookup round `home_x/home_y` that `acbbda7` still had.

New with this change:
- **V** sends `appraise` through `human_act`, at any creature within 6 m. Wave, nod and appraise are one table, `town::MY_ACTS`, and the headless script takes `gesture:appraise[:ID]`.
- `Actor.exact` and the nameplate's `hp / max` show while the projection carries `hp` (`ui/overhead.rs`). A plate stays up while it does.
- The death screen names the killer and the witnesses by the labels last perceived (`ui/live.rs`). Before, it took the killer from the authority's `cause` text, which named a wolf my character never knew, and the witnesses came out as "someone", because a death deletes the player's projected rows in the same update.
- `build.rs`: `scoped` by default, `open` on request.
- Harness:
  - `verify.py launch` honours `CARGO_TARGET_DIR` on the default seed (it published `living/target`'s module whatever it had built);
  - the recorded build defaults to `scoped`;
  - `verify_llm.py` and `verify_minds.py` run the mind binary they built (`MIND_BIN`).

## Third change: verification

On the Mac, scratch `verify-*` databases on the shared 2.14.1 container, the fake model server only, private `CARGO_TARGET_DIR`s. Evidence under `.local/living/verify/` (named below); photographs also in the session's scratchpad (`scoped-default/`).

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Build | `set -o pipefail; just living-check` | exit 0; rules 100 passed; the viewer's one linker warning (`__eh_frame`) is unchanged | `scoped-default/check.log` |
| Client, default (scoped) | `verify-client` `run.py`, no `LIVING_PERCEPTION` (recorded `perception scoped`) | 30 PASS, no XFAIL; the observer's query set as the owner, the anonymous base refused | `client-sd-scoped-181103/` |
| Client, open | the same with `LIVING_PERCEPTION=open` | 30 PASS and the known XFAIL (`experience` public in the open build) | `client-sd-open-181103/` |
| Game client | headless on a scoped island (`client-sd-game`), scenes set with admin `place_at`, `place_near`, `set_behavior` | see below | `client-sd-game/game*/` (photographs, `snap/*.json`, `game.log`, `driver.log`) |
| Player | `verify-player` on a scoped island: `gesture.py`, `appraise.py`, `combat.py --scene all` | gestures 10 of 10; appraise 10 of 10; combat 24 of 25: the bow's arrow struck a resident who walked into its path and the fire bolt the appraise scene's bystander, so the dummy took no damage; `--scene bow` alone passed | `player-sd/` |
| Minds | `verify-minds --case takeover` on the scoped build | pass: takeover after 30.0 s, the graph held and reinstalled, a reply in flight refused; mind tests 49 passed | `minds-sd-182208-takeover/` |

The game client, from the photographs and the game identity's own views at each one:
- digests match, and `live: cache body` is 1 at the arrival and 13–18 in a town square;
- residents are drawn in their towns' dress (fantasy, steampunk, cyberpunk; the giants' town was too foggy to judge);
- a resident is `a stranger` in the bubble and the log, and after its line "Well met. I'm Renferen." it is `Renferen` in both, with the same label in `seen_characters`;
- V/appraise shows `96 / 96` under Renferen's nameplate at 3 s and 13 s, and at 24 s the figure is gone and the row has `hp` -1;
- nobody is drawn 2–3 tiles away behind a stall's wall tiles, a fence or rock, while someone 4 tiles away in the open is, and owner truth puts them where the picture is empty;
- the wolf pack is drawn with its gaits and bite, and the nameplate reads `a wolf`;
- the HUD and the skill bar work from the views;
- the death screen reads "Killed by a wolf", seen by `a wolf` ×3, after the fix above.

`spacetime_active_queries` stayed at 20 for this client. Cost: [game brief](GAME_BRIEF.md#what-the-client-shows-of-others-2026-11-09).

Not covered:
- a browser screenshot of the lab observer (no Chromium on this Mac; its exact query set passed as the owner);
- the knowledge and core surfaces, whose code this change does not touch;
- a republish of a running world from `open` to `scoped` with `--keep-data`;
- players connected at a republish.

## Fourth change: measurements and verification

Branch `scale-1` from main `1693f3e`, 2026-11-09/10, on the dev-box (AMD Ryzen AI Max+ 395, 16 cores / 32 threads, Fedora 44), SpacetimeDB 2.14.1 in my own containers (`scale-stdb` for measurements, `scale-verify` for verification), scratch `verify-*` databases only, the fake model server for every mind (no model was called).

### SpacetimeDB documentation and source consulted (2026-11-10)

The live docs' selector reads 2.0.0; every claim the design rests on was checked in the `v2.14.1` source (tag `v2.14.1`, commit `a0bf6be`).

| Source | What it says | What follows here |
|---|---|---|
| [Views](https://spacetimedb.com/docs/functions/views/) | "If a row outside that set changes, the view doesn't need to be re-evaluated"; per-sender views are computed and tracked "separately for each subscriber"; views read "through indexed lookups"; "Full table scans create pessimistic read sets"; a view returning a query supports "incremental evaluation even when scanning full tables". | Views read per-viewer copies through one index point each. **The last claim does not hold in 2.14.1:** `run_query_for_view` records every table a query reads as a full scan ("This means we will rerun the view and query for any change to these tables") and re-materializes it, so query views were not used. |
| Source: `module_host.rs` `call_views_with_tx_at`, `relational_db.rs` `materialize_view_arg_hash` | Each view call made stale by a transaction is re-run once in it, and the sender's rows are deleted and inserted again. | One refresh per view per transaction: a viewer's copies are written in one transaction (its frame), so each view re-runs at most once per frame. |
| Source: `mut_tx.rs` `TableReadSet::views_for_index_seek`, `record_index_scan_point_inner`; `spacetimedb-2.14.1/src/table.rs` `is_point_scan` | A write re-runs a view only if the written row projects to a key that view read on that index; a filter giving every column of a multi-column index is a point. | `line_seen` is staged under `(observer, false)` and released under `(observer, true)`: a staged line re-runs nothing. |
| Source: `mut_tx.rs` `TableReadSet::remove_view_call` (line 562), `ViewReadSets::merge` | When a refreshed view commits, its old read set is removed by a `retain` over every key of every view in the database. | Measured as the hidden quadratic (11.4% of the server's CPU in a 100-fighter battle): every view now reads a handful of keys. |
| Source: `module_host.rs` `WasmtimeModuleHost` | "Reducers are not executed concurrently": one module instance runs every reducer and view; procedures use a pool. A panic replaces the instance. | Module memory (`thread_local`) can hold which creatures changed since a viewer's frame; a fresh instance compares whole scenes once. |
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) | "Event tables cannot currently be accessed within view functions"; per-client filtering is row-level security. | Not usable for the feed: RLS is not enforced in the 2.14.1 module bindings ([combat](COMBAT.md)), and a view cannot read them. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/) | "Make tables public only when clients need to access them"; "Break large tables into smaller, more focused tables"; "Be mindful of unbounded table growth". | The copies are private tables, one per view; rows are deleted with the perceived set, at death and by the frame; `line_seen` keeps 64 per character. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations); source `crates/schema/src/auto_migrate.rs` | `AddTable`, `AddColumns` (with defaults) and `AddIndex` are automatic. | The change adds four tables and one index (`projected.by_viewer_body`); a running world updates in place. |
| Source: `crates/durability/src/imp/local.rs` `Local::run`; `client-api/src/lib.rs` `DEFAULT_CONFIRMED_READS` | Group commit: the actor writes what is queued, then fsyncs; confirmed reads wait for the durable offset. | The 20–40 ms a confirmed read adds on this disk ([gate 216](GATE_216.md#durability-on-the-response-path-hypothesis-4-measured-not-decided)). |

### Measurements

The numbers are in [gate 216](GATE_216.md#scale-change-frames-2026-11-10-branch-scale-1): arm B (30 fighters, 186 walkers) back to back for each step of the change, the 100-fighter form back to back, and the full 30-minute gate. In short, for arm B's battle: 19.0 → 53.0 steps a second, the tick's transaction 39.4 → 7.6 ms, views' time with materializing 610 → 136 ms/s, move p95 at the client 212 → 132 ms. For 100 fighters: 1.0 → 5.5 steps a second, with the queue bounded. The per-refresh costs that set the design, from `view_total_time_usec` / `view_calls` and a `perf` profile of a symbolized 2.14.1 server:

| Cost | Before | After |
|---|---|---|
| `my_combat` per refresh, arm B battle | 940 µs (≈ 400 rows: every death any onlooker saw, two minutes each) | 170 µs |
| `my_experience` per refresh, arm B battle | 590 µs (every character's window); 855 µs with frames1's 64 lines, still per character | 250 µs (one window) |
| Read set dropped at each refresh (`remove_view_call`), 100 fighters | 11.4% of the server's CPU, plus about 3.5% comparing call keys (frames3, before `doing_seen` and line copies) | a handful of keys per view |

### Verification (2026-11-10)

On the dev-box, scratch `verify-*` databases in my own container `scale-verify` (2.14.1, port 3427; `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`s, the fake model server only. Evidence under the dev-box worktree's git-ignored `.local/living/verify/` (named below).

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Build | `set -o pipefail; just living-check` on the branch's code | exit 0; rules 109 passed; authority (wasm, island and default seed), mind, native and browser observer, game (release) built. | `.local/scale/check-final.log` |
| Client, scoped (default) | `verify-client` `run.py` | 30 PASS, no XFAIL. Two earlier runs stopped at the driver's inventories: the new private tables, and `judged` and `mind_judged` from the harness merge, which the driver did not know (fixed) | `client-scale-scoped-011217/` (`-010009`, `-011131` the stopped runs) |
| Client, open | the same with `LIVING_PERCEPTION=open` | 30 PASS and the known XFAIL (anonymous `experience` in the open build) | `client-scale-open-011435/` |
| Player | `verify-player` on an island world: `gesture.py`, `appraise.py`, `combat.py --fresh --scene all` | gestures 10 of 10, appraise 10 of 10, combat 21 of 25: block front and back, dodge and heal saw no blow from the graph attacker within their 4 s, with the full gate and three verification suites on the host (the flake [combat](COMBAT.md) recorded before this change). The three scenes alone on a fresh world: 5 of 5 | `player-scale-011445/`, `player-scale-def-014943/` |
| Core | `verify-core`: `cargo_checks.py` (rules 109, authority 10, mind 63, viewer sync 3), scenes `tick`, `needs`, `seize`, `sight`; `skirmish` and `town.py` on the island | all pass: skirmish 8 of 8, town 21 of 21 | `core-scale-20261110-011547*/` |
| Minds | `verify-minds` `--case sight --case takeover` (the minds share the perceived set) | both pass | `minds-scale-013708-sight/`, `-takeover/` |
| After merging main `fe6ec66` | `just living-check` (rules 112 passed); `verify-client` scoped; `verify-core` `sight`, `skirmish`, `town.py`; `verify-player` `gesture.py` | check exit 0; client 30 of 30 (permission matrix 206 calls, 63 private tables) after adding megacity's `create_floor` and `genesis_step` to the driver; sight 6 of 6, skirmish 8 of 8, gestures 10 of 10; town 19 of 21, the two failures the scenes known to be flaky (a resident facing someone who comes up behind, or speaks): alone, speak 2 of 2 and approach 1 of 2 | `client-scale-merge-scoped-*`, `core-scale-merge-*`, `player-scale-merge-*` |
| After merging main `0812ada`, with the game client's log change | `just living-check` (rules 116 passed); `verify-client` scoped; `verify-core` `tick`, `sight`, `skirmish`; `verify-player` `gesture.py`, `combat.py` | check exit 0; client 30 of 30 (206 calls, 63 private tables); tick 6, sight 6, skirmish 8, gestures 10 of their checks; combat 20 of 25, the five failing on main `0812ada` too, run from a worktree of it: the bow scene's arrow meets a wall and the graph attacker never reaches the player on the island the merged generator builds ([gate 216](GATE_216.md#after-merging-main-0812ada-path-1-rethink-1-two-client-arms)) | `client-scale-m2-scoped-*`, `core-scale-m2-*`, `player-scale-m2*`, `player-scale-main-124429/` |
| After merging main `8fd4f43` | `just living-check` (rules 116 passed); `verify-client` scoped; `verify-core` `sight`, `skirmish`, `town.py`; `verify-player` `gesture.py` | check exit 0; client 30 of 30; sight 6 of 6, skirmish 8 of 8, town 20 of 21 (the approach scene, known to be flaky), gestures 10 of 10 | `client-scale-m3-scoped-*`, `core-scale-m3-*`, `player-scale-m3-*` |
| After merging main `67cdb0a` | `just living-check` (rules 120 passed); `verify-client` scoped; `verify-core` `sight`, `skirmish`, `town.py`; `verify-player` `gesture.py` | check exit 0; client 30 of 30; sight 6 of 6, skirmish 8 of 8, town 20 of 21 (the approach scene, known to be flaky), gestures 10 of 10 | `client-scale-m4-scoped-*`, `core-scale-m4-*`, `player-scale-m4-*` |
| After merging main `3ff9e8a` (the final code; the arrival on the town's square) | `just living-check` (rules 121 passed); `verify-client` scoped; `verify-core` `sight`, `skirmish`, `town.py`; `verify-player` `gesture.py`, `combat.py` | check exit 0; client 30 of 30; sight 6, skirmish 8, town 21 of 21, gestures 10 of 10; combat 20 of 25, the same five failing on main `3ff9e8a` (the scenes' fixed offsets meet buildings round the new arrival) | `client-scale-m5-scoped-*`, `core-scale-m5-*`, `player-scale-m5-*`, `player-scale-main3ff-221038/` |

The verification skills were brought up to date for what this change touched (`maintain-verification-skill`, scoped to the features it changes, with the runs above as the live pass): `verify-client` (the driver's private-table and reducer inventories; it now runs against any local server named by `LIVING_STDB_URL`, as the other surface skills do; `features/perception.md` and `combat.md`: frames, the 64-line window, the feed's lifetimes) and `verify-player` (`features/combat.md`: the feed's lifetimes).

Not covered: the game client against the frames build (its views and their shapes are unchanged; the `my_experience` window change and its log patch are in [Client](#client-change-fourth-change)), a republish of a running world into this build with players connected, `verify-knowledge` (player memory reads `experience` as the owner, which this change does not touch), and the paid tiers (no model was called).

### Client change (fourth change)

No subscription changes: the views keep their names and row types, so `living/game/src/net.rs` and `live.rs` need no edit. Two behaviours change for the client:
- Others' motion, moves and visible acts arrive at the player's frame (every 33–100 ms; less often when a step's budget is spent) instead of in the transaction that wrote them. The client already extrapolates motion segments between rows.
- `my_experience` holds only the newest 64 lines of the current character. The chat log (`ui/live.rs`) rebuilds itself from those rows each frame, so in a long fight older speech would leave the log. The game now keeps the speech lines it has received, up to 200 (`ui/live.rs`, `Last::heard`; applied after merging main `0812ada`, on top of the player verbs' client change).

## Decisions per current-perception table

The choice for the four current-perception tables was between keeping them public (no view cost, but every position, health band and activity on the island readable by anyone subscribing to any chunk) and private behind the views. With the numbers above:

| Table | Changes | View cost measured | Decision |
|---|---|---|---|
| `body` | every steering update (the hot stream) | at rest 0.02–0.5 ms/s of view WASM; 50 clustered walkers 36.6 ms/s, tick tx mean +1.4 ms | **private behind `seen_bodies`** in the scoped build. At rest it is free and cuts bytes by over 90%; the clustered-walking cost is real and bounded (about 43 µs per refresh), and the 16.7 ms tick has room for it, but it is over today's p99 headroom: a crowd of players in one place needs the follow-up below before the 2,000-character target. |
| `character` | joins, deaths, life stages | 0.03–0.12 ms/s at rest, 5 ms/s walking (perceived sets changing) | **private behind `seen_characters` and `my_characters`**: rows rarely change, and the view re-runs mainly when someone comes into or goes out of sight. |
| `fighter` | each move's start, release and end; band changes at 1 Hz | 0.02–0.05 ms/s at rest, 2 ms/s walking | **private behind `seen_fighters`**. |
| `doing` | each shown skill's start and end | 0.4–1.4 ms/s at rest (residents' gestures and work), 4.4 ms/s walking | **private behind `seen_doing`**. |

All four are private in the default `scoped` build with the five own-state tables, and public only in a `LIVING_PERCEPTION=open` build.

The follow-up for crowds: the cost is one full view refresh per player per tick in which anything it sees moves. Two ways to cut it without giving up the boundary are a per-viewer refresh rate below the tick rate (the sweep could write a per-viewer frame at 10–20 Hz that the view reads instead of the bodies themselves; clients already extrapolate between segments), and splitting `seen_bodies` so a refresh rewrites only the rows that changed (2.14.1 rewrites the whole result). The first is built in the fourth change ([Frames](#frames-what-others-do-reaches-a-player-once-per-frame)); the second is not (a view with arguments per part would multiply view calls, and in a battle most parts change every frame).

## Client change

**Landed (third change).** The patch (`docs/perception-client.patch`, updated for the projection at `dc5e41b`) was applied to `living/game` on main at `acbbda7` and then deleted. `git apply --3way` merged it with `dc5e41b` and `acbbda7`; [what was resolved by hand](#third-change-the-client-lands) is recorded below. What it changed:

1. **Subscriptions** (`net.rs`). After the static `world`, `land`, `settlement`, subscribe once per connection (`PERCEIVED`):
   ```sql
   SELECT * FROM seen_bodies
   SELECT * FROM seen_characters
   SELECT * FROM seen_fighters
   SELECT * FROM seen_doing
   SELECT * FROM my_characters
   SELECT * FROM my_vitals
   SELECT * FROM my_experience
   SELECT * FROM my_places
   SELECT * FROM my_inventory
   SELECT * FROM my_know_how
   SELECT * FROM my_combat
   SELECT * FROM my_readiness
   SELECT * FROM skill_card
   ```
   plus `act_card` and `weather` (town life), and on a tile world `terrain_chunk` whole.
   - Drop `character WHERE controller = :sender` and the per-character subscription (`body`, `vitals`, `experience`, `place`, `inventory`, `know_how` by id): the views replace them.
   - The near window keeps only `SELECT * FROM terrain_chunk WHERE <id ranges>` (±3 chunks). Drop its `body` query and its `character`, `fighter` and `doing` joins. `BODY_CHUNKS` goes.
   - The far window (`lot`, ±11 chunks) is unchanged. A tile world's per-chunk window keeps `resource_node` and `structure` and drops `body`.
2. **Bodies.** `seen_bodies` rows are `Motion`, not `Body`. `net.rs` adds `body_of(conn, Motion) -> Body` (kind from `seen_characters`, empty path, chunk from `living_rules::map::chunk_of`), `bodies(conn)` and `find_body(conn, id)`, so the drawing code and `sync::Tracks` keep taking `Body`. `my_body()` uses `find_body`. The display clock (`body_t`) listens to `seen_bodies().on_insert` and `on_update`.
3. **Who I am.** `find_me()` reads `my_characters` (alive, not AI).
4. **Call sites:**
   - `conn.db.body()` → `crate::net::bodies` / `find_body` (`bodies.rs`, `live.rs`), or the kind from `seen_characters` (`combat.rs` target filter, `vfx.rs`, `camera.rs` talk partner);
   - `character()` → `seen_characters()`, chained with `my_characters()` where my dead character must stay (`ui/live.rs`, `hud.rs` names); "is this actor mine" → `my_characters().id().find(..).is_some()` (`combat.rs`);
   - `fighter()` → `seen_fighters()`; `doing()` → `seen_doing()` (`town.rs`); a resident's home for its dress → `seen_characters()` (`town.rs`); answered greetings → `my_experience()` (`town.rs`);
   - `vitals()` → `my_vitals()`, `experience()` → `my_experience()`, `place()` → `my_places()`, `inventory()` → `my_inventory()`, `know_how()` → `my_know_how()`;
   - the HUD's row counts → the views.
5. **The default build is `scoped`** (`build.rs`); republish the island world from it.
6. **The projection (second change).** `seen_characters` rows are `SeenCharacter`, not `Character`:
   - names drawn over others (nameplates, the HUD's names, the log's speakers, a death's witnesses, the target panel) are the row's `label` (the name when the player knows it, else `a stranger`, `a wolf`); an animal the player knows by name shows "<name> the <kind>";
   - build and dress come from the row's `folk` and `style` (`live.rs` `folk_of`), no longer from the settlement round `home_x/home_y`, which are not sent;
   - a resting resident is hidden indoors when its `doing` row says `indoors` (the authority decides it from the home it no longer sends), not by the client's distance to the home (`town.rs`; the client's `INDOORS_M` goes);
   - `ui/live.rs` keeps two maps, the perceived (`SeenCharacter`) and my own (`my_characters`, full `Character` rows, the death screen's cause and lifetime);
   - the target panel and the nameplates' health show the exact fraction when the row carries `hp` (an appraisal, oneself), else the projected band from `seen_fighters` (255, hidden, shows none);
   - `bodies.rs` draws every perceived body as living (a death takes it out of `seen_bodies`).

What the client sees changes: creatures appear when they come into sight (within ~200 ms) and leave when they go out of it or behind a wall, rather than at the edge of a ±88 m window. A creature that dies in sight leaves `seen_bodies` with its body row; the death animation still comes from `my_combat`.

## Verification

Free tiers only: scratch `verify-*` databases on the dev-box's own 2.14.1 container (`slop-perc-stdb`, port 3320, behind a `docker` name shim as in [island authority](ISLAND_AUTHORITY.md); the harness's hard-coded 3300 was patched to 3320 in the worktree only, not committed). No model was called: the minds ran against the fake model server. Code under test: this branch merged with origin/main `8f6ac72`; the benchmarks ran on the merge with `0887d81` (the commits between touch no authority, rules or bindings file). The branch was then merged with `694821c` (floors: rules land and settlement generation, no authority or bindings change); `just living-check` and the scoped `verify-client` suite were rerun on that final merge. Evidence was produced under `.local/living/verify/` in the dev-box worktree and copied to the Mac checkout's git-ignored `.local/living/verify/perception-evidence/` (tokens and harness state left out).

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Build | `just living-check` with a private `CARGO_TARGET_DIR`: authority WASM, mind, native and browser observer, game (release), rules tests | pass; rules 88 tests (the new `sight_is_stopped_by_walls_rock_and_shut_gates_only` among them) | `check.log` |
| Bindings | `spacetime generate --include-private` from the scoped and the open build, then after the merges | identical for both builds; unchanged by the merges | `living/bindings/src/generated/` |
| Client, scoped build | `verify-client` `run.py` with `LIVING_PERCEPTION=scoped` on the default seed: the observer as owner, refusals of 49 private tables to anonymous clients and players (WebSocket and HTTP SQL), the reducer matrix, the combat and town views, own-state views, two players in sight, beyond sight (20 tiles) and behind rock (3 tiles), reconnect, ad-hoc query | 24 PASS, no XFAIL: the two anonymous-privacy known issues (`experience`, `thought`) now pass; again 24 PASS on the final merge | `client-perc-scoped-132031/`, `client-perc-final-140954/` |
| Client, open build | the same suite on the default build | 24 PASS and 1 XFAIL: `experience` is still public in the compatibility build, by design; `thought` is private | `client-perc-open-132338/` |
| Game client | the patched client (the patch since applied and deleted), headless on a scoped island world: join, walk into the square, speak | digests match; `seen_bodies` held 1–9 bodies as it walked (8–9 in the square, 2–4 `doing` rows), 182 lots drawn; the HUD, skill bar, speech bubble and log from the views | `client-perc-game2/game.log`, `shots/` |
| Player | `verify-player` `combat.py` (all scenes) and `gesture.py` on scoped island worlds; `combat.py` also on the open build and on unchanged origin/main | gestures 9 of 9; combat 25 of 25 scoped, 25 of 25 open, 25 of 25 on main. A first scoped run gave 21 of 25: block, dodge and heal saw no blow within their 4 s while the mind suite and the game client ran on the host; those scenes alone and two full reruns passed | `player-perc-scoped/`, `player-perc-all/`, `player-perc-all-open/`, `player-perc-combat2/` |
| Minds | `verify-minds` on a scoped build: roundtrip, acts, conversation, consolidation, prune, reject, only, reconnect, level of detail | 8 pass and the known consolidation XFAIL (no-store projection, docs/LIVING_HANDOFF.md): the mind service reads everything it needs as the owner | `minds-perc-scoped*/` |
| Core | `verify-core` `town.py` (all scenes) on a scoped island world, for its player lookup through `my_characters` | 18 of 21 in the full run; the 3 failures (face on approach, face on speech, step aside) are residents' reactions this change does not touch. Rerun alone: approach and aside pass; speech failed 2 of 5 runs on this branch and 2 of 3 on unchanged origin/main, so it is flaky there too | `core-perc-town/`, `core-perc-town3/`, `core-perc-speak/`, `core-base-speak/` (main) |

The verification skills were brought up to date for what this change touched (`maintain-verification-skill`, scoped as for town life): `verify-client` (new `features/perception.md`; `visibility.md`, `subscriptions.md`, `triage.md`, `combat.md`, `town.md`, `game-client.md`, the README, `SKILL.md`; the driver's inventories, the owner-token observer path, the perception checks; the probe's views), `verify` (SQL as the owner by default, `--anonymous`; the doctor reads `stats` as the owner; the observer screenshot passes the token; the run records its build), `verify-player` (its scripts read their characters through `my_characters`; `combat.py` reads world truth as the owner and is executable again; the feature notes) and `verify-core` (`town.py`'s player lookup). Every touched feature was driven live above. The other features' maps were not re-read from source.

## Open

- **Minds see through walls:** closed by the second change ([Minds see what their character sees](#minds-see-what-their-character-sees)).
- **`seen_characters` returns the whole `character` row:** closed by the second change (the `perceived_of` projection; the client patch reads `folk`, `style` and `doing.indoors` instead of the home).
- **Resources, structures and terrain** are not filtered by the sight line, for minds or players (a player's client draws them by chunk window as public world data). A mind's scene lists resources and structures within its sight radius through walls. Making static world data perception-scoped is a separate change.
- **What the `perceived_of` law decides** is minimal: a name or a label, and health's precision. Activity, dress, a tracker's reading of where someone came from, and remembered (not only current) reveals are open; the law already receives the observer's know-how, so a skill-gated reading needs only new inputs and fields.
- **Introductions** cover saying one's own name. Being told a third person's name ("this is Wren") is not built. Labels are not distinct between strangers ("a stranger attacked a stranger").
- **World data with live state** (`resource_node` amounts, `structure.owner`, `gate.changed_by`) is public, readable beyond sight by chunk window.
- **The public observer** was retired on 2026-11-09.
- **The default build was `open`** until the client landed: closed by the third change (`scoped` is the default; `experience` and the other eight tables are public only in a `LIVING_PERCEPTION=open` build, whose verify-client run records that as its one `XFAIL`).
- **Scale:** measured to 50 players at rest and walking until the fourth change, which measured the 216-character gate with 30 and 100 players fighting in one place ([gate 216](GATE_216.md#scale-change-frames-2026-11-10-branch-scale-1)). A 100-player battle still does not hold 60 Hz; the next costs are named there.
