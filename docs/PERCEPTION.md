# Perception: what a player's client receives

Started 2026-11-09. This note records how the living authority limits what a human player's client receives to what the player's character perceives now, plus the character's own state ([game brief](GAME_BRIEF.md#core-work-the-game-needs-engine-independent), core work 1; [island authority](ISLAND_AUTHORITY.md), "Perception-scoped subscriptions" and "A slimmer moving-body stream"). It covers the table audit, the SpacetimeDB documentation and source the design rests on, the design, the measured cost, the per-table decisions, the client change and the verification.

**Status.** Implemented on branch `perception-1` and verified on scratch databases (`verify-*`) on the dev-box with SpacetimeDB 2.14.1, in its own container (`slop-perc-stdb`, port 3320). No lab or reference world was touched. The game client (`living/game`) was not edited: its change is the patch [perception-client.patch](perception-client.patch), described in [Client change](#client-change). Until it lands, the default build keeps the tables the game client reads public ([Compatibility](#compatibility-the-living_perception-build-switch)).

## Rules this follows

- **Perception is enforced on the authority** (AGENTS.md: "Spatial subscriptions are not permission boundaries by themselves"). A chunk window is a client's choice of what to subscribe to, so it bounds bandwidth, not knowledge. The perceived set is worked out by the authority with the rules' own sight.
- **Current perception, remembered knowledge and developer audit truth are separate paths.** Current perception is the `seen_*` views, recomputed from the world as it is. What a player remembers is its own `experience` window, places and know-how (`my_*`). Audit truth (minds' state, thoughts, beliefs, personas, the chronicle) is private, read by the database owner: the mind service and the lab observer.
- **One sight for every character.** The radius is `common::sight_for`, the one minds perceive by (day 11 tiles, night 6, a torch at night 9). Players also get a sight line; minds do not yet (see [Open](#open)).

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
| `seen_characters` | their `character` rows | the same, then `character.id` |
| `seen_fighters` | their `fighter` rows | the same, then `fighter.id` |
| `seen_doing` | their `doing` rows | the same, then `doing.id` |
| `my_characters` | my characters, the dead included (the death screen) | `character.controller` |
| `my_vitals` | my living characters' `vitals` | `character.controller`, `vitals.id` |
| `my_experience` | my characters' experience windows (≤ 400 rows each) | `character.controller`, `experience.observer` |
| `my_places`, `my_inventory`, `my_know_how` | my living characters' rows | `character.controller`, then `place.actor`, `inventory.owner`, `know_how.actor` |

"My characters" are the caller's characters with `ai = false`. A mind service's identity controls AI characters (`ai = true`), so these views return nothing to it; it reads the tables as the owner.

The existing `my_combat`, `my_readiness`, `my_skill_uses` and `my_deliberations` are unchanged.

### The moving-body stream

`seen_bodies` returns a narrow product type, `Motion`: `id`, `x`, `y`, `t_ms`, `vx`, `vy`, `heading`, `turn`, `turn_s`, `next_ms` (the segment's end, when steering looks again) and `speed` (the cruising speed of the movement, which tells walk from run). The client extrapolates with `living_rules::steer::pose` exactly as from a `body` row. It leaves out the path (16 B a corner), the chunk and the kind (on the creature's character row). That is 52 B of columns against `body`'s 70 B plus 16 B per path corner. No table was added and no column removed, so a running world updates in place: the view maps rows that are written anyway.

### Compatibility: the `LIVING_PERCEPTION` build switch

`living/authority/build.rs` reads `LIVING_PERCEPTION` at build time:

- **`open`** (the default): the nine tables today's game client reads (`body`, `character`, `fighter`, `doing`, `vitals`, `experience`, `place`, `inventory`, `know_how`) stay public, so main never breaks the game client of 2026-11-09. The views exist and are correct, but the tables beside them are not a boundary.
- **`scoped`**: those nine are private (`cfg_attr(not(open_tables), …)` in `tables.rs`), so a player receives only what the views return.

Developer audit truth is private in both. Table visibility is part of the module, so switching is a republish; 2.14.1's automatic migration allows "public → private" (`crates/schema/src/auto_migrate`), so a world can switch in place with `--keep-data`. Once the client patch lands, make `scoped` the default (one line in `build.rs`).

### The mind service and the observer

- **The mind service** connects with the CLI token, `LIVING_TOKEN` or `.local/living/token` (`living/mind/src/main.rs`), the publisher's identity: the database owner. Its subscriptions (`experience` by controller, `character`, `brain`, `persona`, `relation`, `judgment`, `place`, `know_how`, `community`, `membership`, `background`, `routine`, `routine_stat`, `genome`, `script`, offers, `my_deliberations`) keep working on private tables. Nothing in it changed.
- **The lab observer** (`living/viewer`) connected anonymously. It now passes the owner's token: `LIVING_TOKEN` or `.local/living/token` natively, and on the web the page's `#token=…` fragment, which the browser never sends to a server. Without one, its subscription fails with a message saying so. **The public observer** (`https://sos.carlid.dev`) has no token, so after this change it can show nothing of minds, bodies (in a scoped build) or the chronicle. Giving it the owner's token would hand admin rights to whoever opens the page: that is the user's call ([Open](#open)).
- **The verification harness** reads SQL as the owner by default now (`verify.py sql`; `--anonymous` for public-only reads), and its observer screenshots pass the token in the fragment.
- **Bindings** are generated with `--include-private` (`just living-generate`), identical for both builds.

### Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| Perception sweep | the player's body, the shared chunk-body cache within sight + 1, the cached map, the player's `perceived` rows | `perceived` inserts and deletes on change only | `perceived.viewer`, PKs | — | each player every 200 ms, staggered across ticks | one row per creature in sight per player; deleted at death |
| `seen_*` refresh | as in the table above | the view's ephemeral rows (no commitlog) | point lookups | that player | in the transaction that wrote a row it read: a perceived creature's steering update, fighter or doing change, someone coming into or going out of sight | — |
| `my_*` refresh | the player's own rows | ephemeral rows | point lookups | that player | when the player's own rows change | `experience` ≤ 400 rows per character, as before |
| Static windows | `terrain_chunk`, `lot` by chunk range | — | `lot.chunk`, PK | clients that subscribe | on edits | — |

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

## Decisions per current-perception table

The choice for the four current-perception tables was between keeping them public (no view cost, but every position, health band and activity on the island readable by anyone subscribing to any chunk) and private behind the views. With the numbers above:

| Table | Changes | View cost measured | Decision |
|---|---|---|---|
| `body` | every steering update (the hot stream) | at rest 0.02–0.5 ms/s of view WASM; 50 clustered walkers 36.6 ms/s, tick tx mean +1.4 ms | **private behind `seen_bodies`** in the scoped build. At rest it is free and cuts bytes by over 90%; the clustered-walking cost is real and bounded (about 43 µs per refresh), and the 16.7 ms tick has room for it, but it is over today's p99 headroom: a crowd of players in one place needs the follow-up below before the 2,000-character target. |
| `character` | joins, deaths, life stages | 0.03–0.12 ms/s at rest, 5 ms/s walking (perceived sets changing) | **private behind `seen_characters` and `my_characters`**: rows rarely change, and the view re-runs mainly when someone comes into or goes out of sight. |
| `fighter` | each move's start, release and end; band changes at 1 Hz | 0.02–0.05 ms/s at rest, 2 ms/s walking | **private behind `seen_fighters`**. |
| `doing` | each shown skill's start and end | 0.4–1.4 ms/s at rest (residents' gestures and work), 4.4 ms/s walking | **private behind `seen_doing`**. |

All four are behind the `LIVING_PERCEPTION=scoped` switch with the five own-state tables, and stay public in the default `open` build until the client patch lands.

The follow-up for crowds: the cost is one full view refresh per player per tick in which anything it sees moves. Two ways to cut it without giving up the boundary are a per-viewer refresh rate below the tick rate (the sweep could write a per-viewer frame at 10–20 Hz that the view reads instead of the bodies themselves; clients already extrapolate between segments), and splitting `seen_bodies` so a refresh rewrites only the rows that changed (2.14.1 rewrites the whole result). Neither is built.

## Client change

The patch [perception-client.patch](perception-client.patch) applies to `living/game` on main at `8f6ac72` (after the town-life client, `da219a7`), which this branch has merged, and builds against this branch's bindings (`cargo build --release -p living-game`, no warnings). Here is what it changes, to redo by hand if the client moves on first:

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
5. **After it lands:** build the authority with `LIVING_PERCEPTION=scoped` (or make it the default) and republish the island world.

What the client sees changes: creatures appear when they come into sight (within ~200 ms) and leave when they go out of it or behind a wall, rather than at the edge of a ±88 m window. A creature that dies in sight leaves `seen_bodies` with its body row; the death animation still comes from `my_combat`.

## Verification

Free tiers only: scratch `verify-*` databases on the dev-box's own 2.14.1 container (`slop-perc-stdb`, port 3320, behind a `docker` name shim as in [island authority](ISLAND_AUTHORITY.md); the harness's hard-coded 3300 was patched to 3320 in the worktree only, not committed). No model was called: the minds ran against the fake model server. Code under test: this branch as pushed, merged with origin/main `8f6ac72` (the benchmarks ran on the merge with `0887d81`; the commits since touch no authority, rules or bindings file). Evidence was produced under `.local/living/verify/` in the dev-box worktree and copied to the Mac checkout's git-ignored `.local/living/verify/perception-evidence/` (tokens and harness state left out).

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Build | `just living-check` with a private `CARGO_TARGET_DIR`: authority WASM, mind, native and browser observer, game (release), rules tests | pass; rules 88 tests (the new `sight_is_stopped_by_walls_rock_and_shut_gates_only` among them) | `check.log` |
| Bindings | `spacetime generate --include-private` from the scoped and the open build, then after the merges | identical for both builds; unchanged by the merges | `living/bindings/src/generated/` |
| Client, scoped build | `verify-client` `run.py` with `LIVING_PERCEPTION=scoped` on the default seed: the observer as owner, refusals of 49 private tables to anonymous clients and players (WebSocket and HTTP SQL), the reducer matrix, the combat and town views, own-state views, two players in sight, beyond sight (20 tiles) and behind rock (3 tiles), reconnect, ad-hoc query | 24 PASS, no XFAIL: the two anonymous-privacy known issues (`experience`, `thought`) now pass | `client-perc-scoped-132031/` |
| Client, open build | the same suite on the default build | 24 PASS and 1 XFAIL: `experience` is still public in the compatibility build, by design; `thought` is private | `client-perc-open-132338/` |
| Game client | the patched client (`perception-client.patch`), headless on a scoped island world: join, walk into the square, speak | digests match; `seen_bodies` held 1–9 bodies as it walked (8–9 in the square, 2–4 `doing` rows), 182 lots drawn; the HUD, skill bar, speech bubble and log from the views | `client-perc-game2/game.log`, `shots/` |
| Player | `verify-player` `combat.py` (all scenes) and `gesture.py` on scoped island worlds; `combat.py` also on the open build and on unchanged origin/main | gestures 9 of 9; combat 25 of 25 scoped, 25 of 25 open, 25 of 25 on main. A first scoped run gave 21 of 25: block, dodge and heal saw no blow within their 4 s while the mind suite and the game client ran on the host; those scenes alone and two full reruns passed | `player-perc-scoped/`, `player-perc-all/`, `player-perc-all-open/`, `player-perc-combat2/` |
| Minds | `verify-minds` on a scoped build: roundtrip, acts, conversation, consolidation, prune, reject, only, reconnect, level of detail | 8 pass and the known consolidation XFAIL (no-store projection, docs/LIVING_HANDOFF.md): the mind service reads everything it needs as the owner | `minds-perc-scoped*/` |
| Core | `verify-core` `town.py` (all scenes) on a scoped island world, for its player lookup through `my_characters` | 18 of 21 in the full run; the 3 failures (face on approach, face on speech, step aside) are residents' reactions this change does not touch. Rerun alone: approach and aside pass; speech failed 2 of 5 runs on this branch and 2 of 3 on unchanged origin/main, so it is flaky there too | `core-perc-town/`, `core-perc-town3/`, `core-perc-speak/`, `core-base-speak/` (main) |

The verification skills were brought up to date for what this change touched (`maintain-verification-skill`, scoped as for town life): `verify-client` (new `features/perception.md`; `visibility.md`, `subscriptions.md`, `triage.md`, `combat.md`, `town.md`, `game-client.md`, the README, `SKILL.md`; the driver's inventories, the owner-token observer path, the perception checks; the probe's views), `verify` (SQL as the owner by default, `--anonymous`; the doctor reads `stats` as the owner; the observer screenshot passes the token; the run records its build), `verify-player` (its scripts read their characters through `my_characters`; `combat.py` reads world truth as the owner and is executable again; the feature notes) and `verify-core` (`town.py`'s player lookup). Every touched feature was driven live above. The other features' maps were not re-read from source.

## Open

- **Minds see through walls.** Minds' percepts (`perceive::witnessed`, `scene_json`) and the combat feed's onlookers (`combat::show`) use the sight radius without a sight line. Players' bodies now need one. Giving every character the same sight line is a rules change for the labs as well, left for a decision.
- **`seen_characters` returns the whole `character` row**, including `controller` (which tells a player from a resident), `home_x/y` (the client picks dress from it), parents and cause of death. A narrower row needs the client to stop reading home for dress.
- **World data with live state** (`resource_node` amounts, `structure.owner`, `gate.changed_by`) is public, readable beyond sight by chunk window.
- **The public observer** has no token after this change (see above).
- **The default build is still `open`** until the client patch lands; until then `experience` and the other eight tables stay public, and the verify-client open-build run records that as its one `XFAIL`.
- **Scale:** measured to 50 players at rest and walking. The views' cost grows with players × perceived updates; a 200-character battle seen by many players was not measured.
