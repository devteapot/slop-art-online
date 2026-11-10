# Perception: what a player's client receives

Started 2026-11-09. This note records how the living authority limits what a human player's client receives to what the player's character perceives now, plus the character's own state ([game brief](GAME_BRIEF.md#core-work-the-game-needs-engine-independent), core work 1; [island authority](ISLAND_AUTHORITY.md), "Perception-scoped subscriptions" and "A slimmer moving-body stream"). It covers the table audit, the SpacetimeDB documentation and source the design rests on, the design, the measured cost, the per-table decisions, the client change and the verification.

**Status (third change, 2026-11-09, uncommitted on the Mac checkout).** `scoped` is the default build. The game client reads only the perception views: the former patch is applied to `living/game`, merged by hand with the wolves and arid lands of `acbbda7` and the polish of `dc5e41b`, and deleted. The client draws what the projection gives (names or labels, health as a band or exact while appraised, dress from `folk`/`style`, residents resting indoors hidden), and its **V** key sends `appraise` ([Client change](#client-change)). `LIVING_PERCEPTION=open` remains for diagnostics ([Compatibility](#compatibility-the-living_perception-build-switch)). Verified as recorded in [Third change: verification](#third-change-verification).

**Status (second change, 2026-11-09).** Minds now perceive by the players' rule: sight by light and a clear sight line, in every perception path ([Minds see what their character sees](#minds-see-what-their-character-sees)). What one character perceives of another is a projection of its record through a law in the script, `perceived_of` ([What an observer perceives of a target](#what-an-observer-perceives-of-a-target)): `seen_characters` returns that projection (no controller, home or parents), minds' percepts and scenes use the same one, and a demonstration skill, `appraise`, reveals exact health for 20 s. Presence and the takeover of an offline player's character are in [player memory](PLAYER_MEMORY.md#presence-and-the-offline-character). Measured and verified as recorded in [Second change: measurements](#second-change-measurements) and [Second change: verification](#second-change-verification).

**Status (first change).** Implemented on branch `perception-1` and verified on scratch databases (`verify-*`) on the dev-box with SpacetimeDB 2.14.1, in its own container (`slop-perc-stdb`, port 3320). No lab or reference world was touched. The game client (`living/game`) was not edited then: its change was a patch (`docs/perception-client.patch`, deleted when it landed in the third change), described in [Client change](#client-change). Until it landed, the default build kept the tables the game client read public ([Compatibility](#compatibility-the-living_perception-build-switch)).

## Rules this follows

- **Perception is enforced on the authority** (AGENTS.md: "Spatial subscriptions are not permission boundaries by themselves"). A chunk window is a client's choice of what to subscribe to, so it bounds bandwidth, not knowledge. The perceived set is worked out by the authority with the rules' own sight.
- **Current perception, remembered knowledge and developer audit truth are separate paths.** Current perception is the `seen_*` views, recomputed from the world as it is. What a player remembers is its own `experience` window, places and know-how (`my_*`). Audit truth (minds' state, thoughts, beliefs, personas, the chronicle) is private, read by the database owner: the mind service and the lab observer.
- **One sight for every character.** The radius is `common::sight_for` (day 11 tiles, night 6, a torch at night 9), and a clear sight line (`perception::in_sight`). Since the second change it holds for players and minds alike: "we should only observe what the actual NPC can see" (the user, 2026-11-09).
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
| `community`, `membership`, `join_request`, `bond_offer`, `trade_offer`, `expecting` | developer audit truth (social facts between characters; a player learns of them through its experiences) | private | private | mind service, observer (owner) |
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
3. keeps those within sight (a creature already perceived stays until it is 1 tile beyond: no flicker at the edge) and with a clear sight line on the cached map (`Map::sight_clear`: a grid traversal of the exact tiles between; rock, walls and shut gates hide, water and forest do not; the two ends' own tiles never block);
4. compares with the player's `perceived` rows (point lookup on `perceived.viewer`) and inserts or deletes only the difference.

A join sweeps the newcomer at once (`perception::sweep_now`), so the world is there on the first frame. A death deletes the player's rows (`perception::forget`). A player's own character is never a `perceived` row: the views add it.

### The views

All are per-sender (`ViewContext`), take no arguments, declare `primary_key = id`, and read only through point lookups.

| View | Returns | Reads (its read set) |
|---|---|---|
| `seen_bodies` | [`Motion`](#the-moving-body-stream) rows of my living character and every creature I perceive | my characters (`character.controller`), my `perceived` rows (`perceived.viewer`), those bodies (`body.id`) |
| `seen_characters` | `SeenCharacter`: what I perceive of each creature in my scene, mine included (`id`, `name` when known else empty, `label`, `kind`, `stage`, `folk`, `style`, `own`, `band`, exact `hp`/`max_hp` or -1) | my `projected` rows (`projected.viewer`) only |
| `seen_fighters` | their `fighter` rows, with the band I perceive (the projection's; 255 when hidden) | my `projected` rows, then `fighter.id` |
| `seen_doing` | their `doing` rows | the same, then `doing.id` |
| `my_characters` | my characters, the dead included (the death screen) | `character.controller` |
| `my_vitals` | my living characters' `vitals` | `character.controller`, `vitals.id` |
| `my_experience` | my characters' experience windows (≤ 400 rows each) | `character.controller`, `experience.observer` |
| `my_places`, `my_inventory`, `my_know_how` | my living characters' rows | `character.controller`, then `place.actor`, `inventory.owner`, `know_how.actor` |

"My characters" are the caller's characters with `ai = false`. A mind service's identity controls AI characters (`ai = true`), so these views return nothing to it; it reads the tables as the owner.

The existing `my_combat`, `my_readiness`, `my_skill_uses` and `my_deliberations` are unchanged.

### The moving-body stream

`seen_bodies` returns a narrow product type, `Motion`: `id`, `x`, `y`, `t_ms`, `vx`, `vy`, `heading`, `turn`, `turn_s`, `next_ms` (the segment's end, when steering looks again) and `speed` (the cruising speed of the movement, which tells walk from run). The client extrapolates with `living_rules::steer::pose` exactly as from a `body` row. It leaves out the path (16 B a corner), the chunk and the kind (on the creature's character row). That is 52 B of columns against `body`'s 70 B plus 16 B per path corner. No table was added and no column removed, so a running world updates in place: the view maps rows that are written anyway.

### Minds see what their character sees

Second change. Every path by which a mind, or a behaviour graph, learns about another creature now uses the rule players have, through one function, `perception::in_sight(map, eye, at, dist, sight)`: within the observer's own `sight_for` and with `Map::sight_clear` between. No second approximation was written.

| Path | Before | Now |
|---|---|---|
| Witnessed events (`perceive::witnessed`: fights, deaths, gifts, building, births…) | anyone within the base sight of the place (no torch, no sight line) | each onlooker within its own sight (a torch at night) and a clear line from where it stands to the place |
| A mind's scene (`perceive::scene_json`, the deliberation request) | creatures within sight | creatures within sight with a clear line (`perception::visible`), each described by its projection |
| Behaviour graphs (`brain.rs` scene: `nearest`, `sees`, `visible_creature`, a resident noticing someone) | creatures within sight | the same `perception::visible` |
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
- **Cadence.** The law's answer depends only on its input (`RegardIn`: kinds, know-how, known, revealed, self, night), so it is cached by that value per script revision: a world needs a handful of distinct inputs, and the law runs a few times per revision, not per observer × target. A player's projections are stored in `projected` rows. The sweep projects a creature when it comes into sight, and again only when an input changed: the viewer's knowledge epoch (bumped when it is told a name, when its mind's relations are projected, at a birth to its parents, when any community's members change), a reveal that holds or has just ended, and its own row (exact health). Health bands reach the rows through `perception::health_moved`, called where the fighter band is written (a blow, a heal, the 1 Hz follow-up), through the `projected.body` index. Nothing is re-projected on the 200 ms sweep otherwise.
- **Delivery.** Two options were weighed. A view computing the projection on refresh would have to read everything the law depends on (each target's `vitals`, `relation`, `membership`, `acquaintance` and `reveal` rows), so its read set would re-run it on every needs settle of anyone in sight, and it would run the projection per perceived row per refresh. A private per-viewer table that the update writes and the view reads by viewer costs a write only when a projection changes, and the view's read set is the viewer's own rows. The table was chosen; its cost in the crowd case is in [Second change: measurements](#second-change-measurements). It is a table of its own, not columns on `perceived`, so a band change re-runs `seen_characters` and `seen_fighters` for those who see it, not `seen_bodies` and `seen_doing`.
- **Minds use the same projection.** `common::label_for` is the projection's label, so every percept names others as the observer perceives them ("A stranger attacked you", "Wren said to you"), the act feedback a character gets of its own acts does too ("gave 3 berries to a stranger"), an activity's label (what anyone sees of it: the doer's feedback, onlookers' scenes) names a creature target by its kind ("wave → person"), not its name, and a mind's scene lists a creature's `name` only when known (else `who`: its label), its wound from the projected band, and `health: "34 of 60"` while an appraisal holds. The mind service tags people in experience lines with a name only where the authority's text already gives it (else `someone=#id`, keeping the id as the memory anchor). The chronicle and audit truth keep real names.
- **`appraise`.** A skill declared in `skills.rhai` like any other (`appraise_check`, `_duration` 1.5 s, `_done` → `#{ op: "reveal", what: "health", secs: 20.0 }`, `_shows` a gesture, `skill_io`, the catalog's help). The new effect `reveal` writes a `reveal` row (observer, target, what, until); the observer is told what it saw ("You look a stranger over: 100 of 100 health."). It is open to players (`human_act`) and minds (a graph leaf or a deliberate act) alike. Ended reveals are deleted once a second by an index range.

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
| `seen_*` refresh | as in the table above | the view's ephemeral rows (no commitlog) | point lookups | that player | in the transaction that wrote a row it read: a perceived creature's steering update, fighter or doing change, someone coming into or going out of sight | — |
| `my_*` refresh | the player's own rows | ephemeral rows | point lookups | that player | when the player's own rows change | `experience` ≤ 400 rows per character, as before |
| Static windows | `terrain_chunk`, `lot` by chunk range | — | `lot.chunk`, PK | clients that subscribe | on edits | — |
| Projection (second change) | the target's character, vitals and the settlement round its home; the observer's know-how, relations, membership, acquaintances, reveals; the cached law | `projected` insert on coming into sight; update when it changes; delete with the `perceived` row and at the target's death | `projected.viewer`, `projected.body`, `acquaintance.by_pair`, `relation.by_pair`, `membership.member`, `reveal.observer` | that player (`seen_characters`, `seen_fighters`) | on entering sight, knowledge or reveal changes, band changes | one row per creature in a player's scene, own included |
| Minds' sight (second change) | per onlooker: its body, its sight, the cached map; per event or scene | — | PK, chunk-body cache | — | per witnessed event, per scene, per behaviour-graph scene | — |
| Reveals, acquaintances | — | `reveal` insert per appraisal, deleted when ended (index range on `until_ms`, 1 Hz); `acquaintance` insert per hearer of a self-introduction | `reveal.observer`, `reveal.until_ms`, `acquaintance.observer`, `.by_pair` | — | per skill use, per introduction | acquaintances grow with introductions (deleted with the observer at death) |

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

## Decisions per current-perception table

The choice for the four current-perception tables was between keeping them public (no view cost, but every position, health band and activity on the island readable by anyone subscribing to any chunk) and private behind the views. With the numbers above:

| Table | Changes | View cost measured | Decision |
|---|---|---|---|
| `body` | every steering update (the hot stream) | at rest 0.02–0.5 ms/s of view WASM; 50 clustered walkers 36.6 ms/s, tick tx mean +1.4 ms | **private behind `seen_bodies`** in the scoped build. At rest it is free and cuts bytes by over 90%; the clustered-walking cost is real and bounded (about 43 µs per refresh), and the 16.7 ms tick has room for it, but it is over today's p99 headroom: a crowd of players in one place needs the follow-up below before the 2,000-character target. |
| `character` | joins, deaths, life stages | 0.03–0.12 ms/s at rest, 5 ms/s walking (perceived sets changing) | **private behind `seen_characters` and `my_characters`**: rows rarely change, and the view re-runs mainly when someone comes into or goes out of sight. |
| `fighter` | each move's start, release and end; band changes at 1 Hz | 0.02–0.05 ms/s at rest, 2 ms/s walking | **private behind `seen_fighters`**. |
| `doing` | each shown skill's start and end | 0.4–1.4 ms/s at rest (residents' gestures and work), 4.4 ms/s walking | **private behind `seen_doing`**. |

All four are private in the default `scoped` build with the five own-state tables, and public only in a `LIVING_PERCEPTION=open` build.

The follow-up for crowds: the cost is one full view refresh per player per tick in which anything it sees moves. Two ways to cut it without giving up the boundary are a per-viewer refresh rate below the tick rate (the sweep could write a per-viewer frame at 10–20 Hz that the view reads instead of the bodies themselves; clients already extrapolate between segments), and splitting `seen_bodies` so a refresh rewrites only the rows that changed (2.14.1 rewrites the whole result). Neither is built.

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
- **Scale:** measured to 50 players at rest and walking. The views' cost grows with players × perceived updates; a 200-character battle seen by many players was not measured.
