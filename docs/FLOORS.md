# Floors: a world of stacked worlds

Started 2026-11-09 from the user's idea: a world of stacked floors, each a separate world with its own setting, at least the island's size, joined so characters can leave one and arrive on another. This note is the design and its evaluation. It also records the first prototype: the generator of the hardest floor, a megacity filling a 4096 m land ([prototype](#prototype-the-megacity-floor)).

**Status.**
- **Built on branch `floors-1`, rules crate only:**
  - the city planner (`living_rules::settle::metro`) and its seed, [`living/seeds/floor-megacity.json`](../living/seeds/floor-megacity.json);
  - the floor-law composition proof (`living_rules::floors`);
  - a preview tool (`living/rules/examples/floor_preview.rs`).
- **Measured.** Natively, as WASM under wasmtime, and inside the authority on scratch databases on the dev-box.
- **Design only.** Everything in the authority, the mind service and `living/game` below, until the perception, town-life, damage-rule and assets work lands.
- **Not touched.** The lab worlds and the paused reference worlds.
- **Built on branch `megacity-1` (2026-11-09):**
  - staged land generation in the rules (`living_rules::land::Gen`), with fuel per step measured by `living/tools/land_fuel`;
  - the seed passed at runtime: a floor module (`LIVING_SEED=none`), `create_floor` and the scheduled `genesis_step` in the authority (`authority/src/floor.rs`), and `just living-floor`;
  - a second, detailed pass of the city generator, and the city kit (`living/tools/blender/city.py`).

  See [staged generation and the largest floor](#staged-generation-and-the-largest-floor) and [the megacity, second pass](#the-megacity-second-pass).

**Key decisions proposed:**
1. One SpacetimeDB database per floor, all from one module build. A floor is a seed plus a law overlay, not a fork.
2. A small **tower** database holds the floor directory and the transit ledger. Characters move between floors by idempotent tickets carried by SpacetimeDB 2.14.1's inter-database calls: outbox tables, exactly once, atomic with the sending transaction.
3. A character is a **soul** with a global id. Its body is local to a floor. What travels is decided per table, not by copying the whole row set.
4. World rules become Rhai laws, like skills. Rust exposes primitives and runs them. Laws come in three cadences: compile-time tables, event laws and hot paths fed by cached numbers.
5. Floors are linked in the world by a gate on each floor. Progression comes from each floor's initial state, the world preset, never from a scripted quest.
6. Build in this order: the floor generator at scale, then laws as data, then transit, then zones within a floor, and zones only if measurement says a floor cannot hold its population.

## SpacetimeDB documentation consulted (2026-11-09)

- **Pinned.** `spacetimedb = "=2.14.1"`, `spacetimedb-sdk = "=2.14.1"`; server image `clockworklabs/spacetime:v2.14.1`.
- **How it was checked.** The live pages' version selector reads 2.0.0, so every claim was checked against the docs folder and source at tag [`v2.14.1`](https://github.com/clockworklabs/SpacetimeDB/tree/v2.14.1). Source paths below are relative to that tag.
- **Labels.** **[V]** means verified in 2.14.1 docs or source; **[C]** means the current website only; **[A]** means not found, or an inference.

| Question | Finding | Implication here |
|---|---|---|
| Many databases per host | **[V]** The same module can be published to many databases, each with its own data, addressed by name or identity (`docs/docs/00200-core-concepts/00100-databases.md`; HTTP `/v1/database/:name_or_identity`, `docs/docs/00300-resources/00200-http-api/00300-database.md`). **[A]** No per-host limit was found in standalone (`crates/standalone/src/lib.rs:191-201`), and no idle unload. | A floor is a database (`floor-<id>`). Several floors share one host process. An idle floor still costs its memory (below). |
| A module reaching another database | **[V]** **Inter-database communication (IDC)** exists in 2.14.1 ([docs](https://spacetimedb.com/docs/databases/inter-database-communication), `docs/docs/00200-core-concepts/00100-databases/00650-inter-database-communication.md`, `crates/core/src/host/idc_actor.rs`).<br>**How it works:** a reducer inserts a row into an `#[table(outbox(remote::reducer))]` table. After that transaction is durable, the server calls the reducer on the target database. An optional `#[reducer(on_result(...))]` runs back in the sender.<br>**Guarantees:** atomic with the sending transaction, exactly once, in order per outbox and target, authenticated.<br>**Limits:** same server or cluster only; outbox rows cannot be updated or deleted; an undeliverable target blocks later calls through that outbox to that database; the receiver's `client_connected`/`client_disconnected` run around every call, with no JWT. | Transit needs no relay service when floors share a server. A relay is needed only for floors on different hosts. |
| Procedures and HTTP | **[V]** `ctx.http`, `with_tx` and `sleep_until` exist, with a 30 s default HTTP timeout clamped to 180 s (`crates/core/src/host/instance_env.rs:1171-1182`).<br>Outbound HTTP refuses loopback and private ranges (`instance_env.rs:1185-1272`), so a procedure cannot call a database on the same host over HTTP.<br>Reducers do no outbound IO. The tag docs mark Rust procedures `unstable`, but the 2.14.1 crate exports them ungated (`spacetimedb-2.14.1/src/lib.rs:783`). | Use IDC on one host and a trusted relay across hosts. Procedures are not the transit path. |
| Scheduled reducers | **[V]** Schedule tables drive reducers and procedures (`spacetimedb-2.14.1/src/lib.rs:770-780`). | Retries, ticket expiry and staged world generation can run as scheduled reducers. |
| Identities and tokens | **[V]** `POST /v1/identity` issues a token signed by the host's key (`docs/docs/00300-resources/00200-http-api/00200-identity.md`). The identity is derived from the token's `iss` and `sub` (`JwtClaims::identity`), so **one token is the same identity on every database of a host**. **[A]** It differs across hosts with different keys.<br>OIDC issuers are accepted through JWKS (`crates/core/src/auth/token_validation.rs:82-115`). The audience is not checked; modules check `ctx.sender_auth().jwt()` themselves.<br>In an IDC call, `ctx.sender` is the sending database's identity. | A player keeps one identity across the floors of a host with no extra login. Floors trust the tower by its database identity, kept in an allow-list row. Multi-host floors need an OIDC issuer that every host accepts. |
| Client connection switching | **[V]** Each `DbConnection` has its own cache and subscriptions (`spacetimedb-sdk-2.14.1/src/db_connection.rs:78-79`), and `with_database_name` is set per builder (`:1067`). `disconnect()` ends only that connection. The Rust SDK has no automatic reconnect (`docs/docs/00200-core-concepts/00600-clients/00300-connection.md:320-340`). **[A]** The docs give no guidance on holding several connections. | The client opens floor B's connection with the same token while floor A's is still open, then drops A. |
| WASM memory limits | **[V]** Table rows live in the host datastore's pages, **outside** the module's linear memory (`crates/table/src/page.rs`, `crates/datastore/src/locking_tx_datastore/`). The module copies BSATN rows through host calls (`crates/bindings-sys/src/lib.rs:323,370`).<br>No limit below wasm32's 4 GiB is configured: no `memory_reservation`, `static_memory_*`, `ResourceLimiter` or pooling allocator in `crates/core/src/host/wasmtime/mod.rs:91-127`. The V8 1 GiB heap limit (`config.rs:371-375`) applies only to TypeScript modules.<br>**wasm64 / memory64 is not supported:** host ABI pointers are `u32` (`wasmtime/mod.rs:222-248`), the CLI builds `wasm32-unknown-unknown` (`crates/cli/src/tasks/rust.rs:18`), and wasmtime 39 is used without memory64. **[A]** No roadmap item was found ([wasmtime memory64 tracking](https://github.com/bytecodealliance/wasmtime/issues/11816)). | See [the 4 GiB question](#the-4-gib-question). |
| Instances per database | **[V]** One main reducer/view instance per database on its own executor (`crates/core/src/host/module_host.rs:464-476,1977`), plus up to `procedure-instance-pool-size` procedure instances (default: CPU count; `module_host.rs:1978-1983`, `config.rs:381-383`). Each instance has its own linear memory and thread-locals.<br>`spacetime_worker_wasm_memory_bytes{database_identity}` sums linear memory across a database's instances (`crates/core/src/worker_metrics/mod.rs:646-649`). | Module caches (the map, compiled scripts) exist once per instance. Floors should not use procedures in hot paths, or each pool instance rebuilds them. |
| Reducer budget | **[V]** Every reducer gets `FunctionBudget::DEFAULT_BUDGET`, 120 × 10⁹ fuel; one fuel unit is one WASM instruction (`crates/client-api-messages/src/energy.rs:133-142`). Standalone's `NullEnergyMonitor` always returns that default (`crates/core/src/energy.rs:27-35`), so it cannot be raised there. The comment "roughly 1 minute" assumes 2 G instructions per second. | **Measured:** the dev-box runs that budget out in **5.2 s** of generation. A 4096 m floor cannot be generated in one reducer ([scale](#scale)). |
| Execution model | **[V]** A database's reducers run one at a time on its executor (`module_host.rs:464-476`); a scheduled tick blocks other reducers while it runs. Different databases have different executors. | One floor's tick is bound to one core. Floors on one host run in parallel. See [zones](#zones-within-a-floor-later). |
| Per-database resources | **[V]** Each replica has its own commit log and snapshots (`crates/paths/src/server.rs:57,133-138`). A page pool is shared host-wide, 8 GiB by default (`crates/standalone/src/subcommands/start.rs:80`). **[C]** [Maincloud limits](https://spacetimedb.com/limits) (8 GB module memory) apply to Maincloud only. | Retained WAL and snapshots grow per floor and must be reported per floor (performance contract). |
| Event tables, views | **[V]** Event-table rows exist only within their transaction (`docs/docs/00200-core-concepts/00300-tables/00550-event-tables.md`). Views read only their own database. | A departure needs a durable row, not an event. No cross-floor view exists; the tower is the directory. |

Also relied on: [table design](https://spacetimedb.com/docs/tables/) ("organize data by access pattern"), [performance](https://spacetimedb.com/docs/tables/performance/) (bounded growth, targeted subscriptions), [indexes](https://spacetimedb.com/docs/tables/indexes/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) ("subscribe to the new set before unsubscribing from the old one"). These are the same pages [ISLAND_AUTHORITY.md](ISLAND_AUTHORITY.md) cites. Nothing here changes their storage decisions inside a floor.

## One database per floor

### Floors, the module and the seed

Every floor runs the same `living-authority` build. What differs is data:
- the seed: map kind, size and parameters, settlements, people and the world preset;
- the law overlay (below);
- the floor's id.

**Gap (closed on `megacity-1` for the seed; the `rules` flags remain compile-time).** A floor module is built with `LIVING_SEED=none`, and the admin's `create_floor(seed_json)` gives it its seed ([below](#staged-generation-and-the-largest-floor)). Before that change:

**The seed was compiled into the module.** `build.rs` copies `seeds/$LIVING_SEED.json` into the build, and `seed::seed` reads it with `include_str!` in `init` (`authority/src/seed.rs:13`). So each lab arm, and each floor, would be a different build. The seed's `rules` flags (`MINDS`, `YIELD_SHIELD`, `CRY_PROMPTS_CARERS`) are compile-time constants too (`build.rs:36-48`, `rules_flags.rs`).

**Proposal:**
- `init` creates an empty, paused world.
- An admin-only `create_floor(seed_json, overlay_rhai)` reducer, called once by the tower (or by `just` for labs), parses the seed, installs the composed script and starts generation.
- The `rules` flags become laws (below).
- Labs keep working: `just living-reset` calls `create_floor` with the selected seed instead of compiling it in.
- The module and the seed's digest are recorded on the `world` row, so the published module plus that row fully determine the floor, as today.

### The tower

A small database, also published from its own small module, `living-tower`:

| Table | Key | Content | Written | Read by |
|---|---|---|---|---|
| `floor` | `id: u16` | name, database identity, host URL, seed digest, law-overlay digest, gate positions, status (`creating`, `open`, `closed`), population | at floor creation; status changes | clients (directory), relays |
| `soul` | `id: u64` | the global character identity: current floor, controller `Identity`, alive, created_ms | at first creation; each completed transit | floors (through IDC), clients (own row) |
| `ticket` | `id: u64` | soul, from floor, to floor, gate, state, payload digest, created/updated ms | each transit step | floors, relays |
| `trusted_floor` | database identity | allow-list for IDC callers | at floor creation | the tower's reducers |

Each floor keeps a mirror `tower` row (the tower's identity) and its own `ticket` rows for travellers leaving or arriving.

### Leaving floor A, arriving on floor B

A character steps into floor A's gate and uses a `travel` skill. That makes it a skill like any other, with its requirements, cost and refusal in the script: a gate may demand a token, a fee or know-how as floor A's laws say.

1. **Depart (floor A, one transaction).** `travel` succeeds, and floor A:
   - writes a `departure` ticket row (state `leaving`) and the traveller's **payload** (below), serialised with a digest;
   - removes the body from play: no `body`, `steer`, `activity` or `vitals` rows. The `character` row stays, marked `away` with the ticket id. The character can be neither seen, hit nor killed;
   - inserts an outbox row: `tower.transit(ticket, payload)`.

   IDC makes this atomic: either all of it commits and the call is sent, or nothing happened.
2. **Route (tower).** `transit` checks:
   - the caller is floor A (`trusted_floor`);
   - the ticket id is new, so a replay is a no-op that returns the first result;
   - floor B is `open`.

   It records the ticket as `routed` and inserts an outbox row: `floor_b.arrive(ticket, payload)`.
3. **Arrive (floor B).** `arrive` checks the ticket is new, verifies the payload digest, and creates the character from the payload at its gate (a new local `u32` id mapped to the soul). It returns the local id. Its `on_result` in the tower marks the ticket `arrived` and updates `soul.floor`. That result is sent back to floor A, which marks the `character` row `left` and drops its `away` state.
4. **Refusal or failure.** If floor B refuses (closed, full, the payload invalid) or `arrive` fails, the tower's `on_result` sees an error. It marks the ticket `refused` and calls `floor_a.return_traveller(ticket)`. Floor A restores the body at its gate from the payload it kept, so nothing is lost.

**Crash recovery and duplication:**
- Every step is a durable row plus an outbox row in one transaction, so a crash between steps leaves a state the next step resumes from.
- IDC guarantees exactly-once delivery per outbox and target. Tickets are idempotent anyway: `arrive` and `transit` look the ticket up first. That also covers a relay retrying across hosts.
- The traveller exists in play on at most one floor at any time. On A it is `away` until B confirms; on B it exists only after `arrive` commits.
- A **stuck ticket** (B unreachable): IDC holds undeliverable calls and blocks later calls through that outbox to that database. So the tower keeps **one outbox per destination floor**, and a scheduled sweep reports tickets older than a deadline. The documented guarantee does not include cancelling a pending call, so an operator returns the traveller by hand after fixing or closing floor B. No timeout silently moves anyone.
- **Cross-host floors.** IDC is same-server or same-cluster only. A relay service (a process like the mind service, holding a trusted identity on both hosts) moves tickets by the same idempotent steps.

**Death rules:**
- Death stays permanent.
- A character in transit has no body, so it cannot die in transit.
- If floor A or B is wiped (`living-reset`) while a ticket is open, the ticket's payload in the tower is the only copy. The operator decides; the default is to restore the traveller on its origin floor.
- A soul has one death. When it dies on floor B, the tower's `soul.alive` turns false (an IDC call from B). No floor can bring it back, and a new character with the same controller is a new soul with nothing inherited (WORLD_VISION, mortality).

### What travels and what stays

**Working rule (the user, 2026-11-09): only identity and mind travel.** A traveller keeps who they are — their soul (global id), name, persona and the mind's memories, which include the people, places and techniques they remember — and nothing else. On arrival they get floor B's defaults for a newcomer: a fresh body (health and needs as a newcomer has them), the floor's newcomer kit, its default skills and know-how, and the floor's instincts as a starting graph, which the mind then revises. What they remember knowing stays a memory: a fire bolt learned on floor A is remembered on floor B, and whether it can be relearned there is floor B's laws' business. Possessions, property, memberships, relations rows and experiences stay on the floor they belong to. We will refine this once floors exist ("then we figure it out"); the table below is the earlier proposal, kept for the open questions it raises.


Per-character state today, from `authority/src/tables.rs` (all keyed by a floor-local `u32` character id, `#[auto_inc]` per database):

| State | Table(s) today | Travels? | How |
|---|---|---|---|
| Body: kind, life stage, age, genes, ways of moving | `character` (stage, born_ms, birth_age_days, parents), `genome` | yes | Payload. Age is carried as elapsed life, not as a timestamp, since floors may differ in day length. |
| Health and needs | `vitals` | yes | Payload, as they are at the gate. |
| What it carries | `inventory` (owner = creature id), `artifact` held | yes | Payload of carried stacks and held artifacts. Items unknown to floor B's laws arrive inert (named, with no skill uses), not deleted. |
| What it owns on the floor | `structure.owner`, lots, stores, `inventory` of structures | **stays** | Ownership stays on the floor, keyed by soul, and resumes if it returns. |
| Know-how | `know_how`, `practice` | yes | Payload. A floor's laws decide what know-how *does* there: fire bolt may be useless where magic is not a law. |
| Behaviour graph, ways | `brain`, `mind_state` | yes | Payload. They reference skills by name, so a skill missing on floor B fails its checks (an honest failure the mind learns from). |
| Relations | `relation (actor, other)` with local ids | partly | Rows are re-keyed by soul pairs. Relations with souls present on floor B are recreated there; the rest travel in the payload and in the mind's memory, and are recreated when both meet again. |
| Memberships, reputation in a community | `membership`, `community` | **stays** | Communities are floor-local. What others think of you is in their memories and relation rows, which do not move with you. |
| Memories (the mind's) | Neo4j `:Concept {run, actor, key}` (`mind/src/memory.rs:4,160-161`) | yes, without copying | **Gap:** memory is keyed by `(run, actor)`. `run` comes from the seed (`LIVING_RUN`, else the seed's `run`; `mind/src/main.rs:69-70`) and `actor` is the local id, so moving floors would lose memory. Proposal: key by `(realm, soul)`, where `realm` is the tower's world-of-floors id. The mind on floor B reads the same graph. |
| Projections of the mind | `belief`, `judgment`, `place`, `thought`, `persona` | partly | Persona travels. Places and beliefs about floor A stay in memory, not as floor-B rows (a `place` row names floor-A coordinates). |
| Experiences, chronicle | `experience`, `chronicle` | **stays** | History of the floor. |

**Rule.** The payload is a versioned, typed struct in `living_rules`, one schema for every floor. A floor rejects a payload whose version it does not know. That avoids silent partial copies.

### The client switching floors

- **Connections.** The client holds one `DbConnection` per floor it is on (`net.rs` builds one today; `clock::endpoint()` reads `LIVING_SERVER`/`LIVING_DB`). The token file is keyed by database name (`net.rs:182-188`). On one host the same token works for every floor, so the file should be keyed by host instead.
- **What the player sees:**
  1. They walk into the gate and use `travel`.
  2. The gate's own effect plays (light, a lift, a door) while the client opens floor B's connection and subscribes its static rows (`world`, `land`, `settlement`), then its windows around the gate.
  3. It starts regenerating B's land on a worker thread. Measured: 1.4–1.5 s for the island, 7.3 s natively for the 4096 m megacity on the dev-box, so the gate needs a load screen at that size or a cached land (below).
  4. When B's `character WHERE controller = :sender` row appears alive, the camera cuts to the arrival gate.
  5. A's connection is dropped after the switch, subscribe-before-unsubscribe applied across connections.
- **Failure.** If the ticket is refused, A's body reappears at A's gate and the client stays on A.
- **Cache.** A land's tiles and derived geometry are a pure function of seed, size, params and the generator's version, so the client can cache the result on disk under its digests. A second visit then loads instead of regenerating. The digests already prove a cache entry still matches.

### Minds following a character

- **Today.** One mind process serves one database and one `run` (`mind/src/main.rs:99-144`), with a single connection; it exits on disconnect.
- **Proposal.** One mind process per floor (or one process with a connection per floor), all on one Neo4j, memory keyed by `(realm, soul)`. A mind does not move: when a minded character arrives on B, B's mind service sees a new `ai = true` character whose soul it knows, and loads that soul's memory.
- The **arrival** is itself an `experience` ("I came through the gate to …"), written by floor B, so the mind's own account of the journey comes from the rules, not from a prompt.
- Journals stay per run and floor (`.local/living/journal/<run>`), so exact model exchanges remain inspectable per floor.

## Mechanics that change between floors

### The principle

**World rules are Rhai, the same as skills. Rust exposes primitives and runs them.**
- **Rhai holds the laws.** Needs and their rates, movement speeds by kind, gait and terrain, sight by light and weather, reach and separation, day and season length, the pace of life and aging, decay, healing, falls, cold, and anything else a floor might change.
- **Rust holds the primitives.** Move along a path at a speed, sense within a radius, apply damage, drain a need, spawn, kill. It also holds scheduling, storage and the performance-critical loops.

`skills.rhai` already does part of this:
- `laws()` fills `Laws` once per script revision (`rules/src/script.rs:566-605`), and the authority caches it per revision (`authority/src/common.rs:299-311`);
- `rates(a)` sets needs drain, and `move_speed(a)` speed by kind and stage;
- dodge, lunge and cooldowns come from the script;
- combat shapes and the skill bar are read once per compile (`read_shapes`, `read_shows`, `script.rs:356-357`).

A script can already be swapped at runtime per database (`install_script`, `authority/src/lib.rs:92-107`). So one build can serve floors with different laws once the remaining constants move behind law functions.

### Cadence: what a law costs

Calling Rhai per character every tick is costly. Measured natively on the dev-box (`floors::tests::law_call_cost`, release):

| Call | Time per call |
|---|---|
| `rates(a)` | 11.4 µs |
| `move_speed(a)` | 7.6 µs |
| `num_of("lunge", "person")` (string argument) | 0.4 µs |
| a cached `Laws` field | 0.4 ns |

Most of a per-character call is building the facts map (`script.rs:690-694`), not the law's arithmetic. The WASM authority runs about 1.3–1.6× slower than native on this generator; that ratio is not measured for Rhai calls. So every law gets one of three cadences:
1. **C: constants and tables, read once per script compile and cached,** as combat shapes and the bar already are. Examples: speeds by kind and stage, sight radii by light, day length, reach, lunge and cooldown by skill.
2. **E: event laws, called when something happens.** Examples: a fall, a death, a meal, a hit, a season change, arrival through a gate.
3. **H: hot per-tick paths** (steering, perception, needs). Rust runs them on numbers the laws produced at compile time or at an event, and recomputes only when an input changes.

**`rates()` already runs per change, not per tick.** The authority reruns it only when a 13-bit `rate_key` changes (`authority/src/brain.rs:151-172`). The key is built in Rust from thresholds that copy the script's (hunger 100/70, energy 15/0), so a floor that changes those thresholds in Rhai would not be re-evaluated at the right moment.
- **Fix.** `rates_key(a)` becomes a law too, returning the inputs that matter, and the key ignores stage, kind and genes today (so an elder's slowdown waits for another change).
- **On the 40% figure.** This note found no measurement attributing about 40% of the 200-character skirmish's tick to `rates()`. [COMBAT.md](COMBAT.md) attributes 62.6 ms of work per second to `tick.combat`, against 31 ms/s for the 1 Hz evaluations; about 37% of the named spans by this note's arithmetic. The Rhai calls inside combat cadence (`combat_cooldown`, `combat_recover`, `lunge`, `yield_ms`, each per move start, hit or release: `authority/src/combat.rs:176,187`, `act.rs:57,581,738,1106`) take only a skill or kind string. They can be **C** tables read once per compile.
- **Estimate.** At 0.4–8 µs each natively, and assuming 200 fighters starting about 2 moves a second with two lookups each, that is 0.3–6 ms of work per second natively. Moving it to tables removes all but nanoseconds. That is an estimate, not a measurement. A span around those calls in the skirmish benchmark would settle it.

**Toward 2,000 characters:**
- `rates()` per evaluation at 1 Hz would be about 2,000 × 11.4 µs = 23 ms of work per second natively, roughly 2% of a core, before the WASM factor.
- The key cache already cuts most of that.
- The larger per-tick costs at that population are motion, slots and wakes (see [population](#populations-per-floor)), not Rhai.

### Inventory: what is static today, where it lives, and its law

| Law | Today | Where | Cadence | Law function |
|---|---|---|---|---|
| Needs drain (hunger, energy, health) | Rhai | `skills.rhai:98-136` `rates(a)` ← `authority/src/brain.rs:172` | H (per change) | `rates(a)` plus a new `rates_key(a)` |
| Need thresholds for the rate key | Rust inline (copies Rhai) | `authority/src/brain.rs:151-163` | H | `rates_key(a)` |
| Need caps 0..100 | Rust inline | `authority/src/common.rs:521-522`, `act.rs:1068-1069` | C | `laws().need_max` |
| Healing (tend, heal, eating) | Rhai | `skills.rhai:706-708,869,193` | E | unchanged; a floor scales it in its overlay |
| Walk speed by kind and stage | Rhai | `skills.rhai:140-145` `move_speed(a)` | E (move start) | table: `speeds()` read per compile, factors by stage and energy |
| Run, road speed | `Laws` | `script.rs:288,299` → `steer.rs:78,153`, `motion.rs:701` | C | `laws()` (exists) |
| Terrain path cost | Rust inline (flat 10/14) | `rules/src/map.rs:277` | H | `laws().terrain_cost` table by tile class (C) |
| Walkable tile classes | Rust inline | `map.rs:42-44` | H | stays Rust (it is the primitive); a floor's law can add costs, not redefine walking |
| Sight day/night/torch, hearing | `Laws`, plus Rust bypasses | `rules/src/lib.rs:43-45`; `Laws` `script.rs:219-221`; bypasses `authority/src/brain.rs:646`, `act.rs:1167`, `combat.rs:106,492`, `motion.rs:361`; `rules/src/graph.rs:266`, `normalize.rs:622`; prompt text "~9 tiles" `mind/src/prompts.rs:76` | C, recomputed on a light or weather change | `laws()`; remove the bypasses; the prompt reads the law |
| Separation, crowding | `Laws` | `script.rs:293-294` → `motion.rs:217-243` | C | `laws()` (exists) |
| Reach per skill | Rhai, read per compile (since `rules-2`) | `<skill>_spec()` in `skills.rhai` ([world rules](WORLD_RULES.md)) | C | done: a floor redefines a skill's spec, with its description |
| Lunge, cooldown, recover, yield | Rhai, called per use | `skills.rhai:487`; `authority/src/combat.rs:176,187`, `act.rs:57,581,738,1106` | E → C | tables per compile |
| Fire and shelter warmth radius | `Laws` | `script.rs:280-281` → `act.rs:131-152` | C | `laws()` (exists) |
| Cold | Rhai boolean | `skills.rhai:83-85,134-136` | H (per change) | `cold(a)` (exists); a floor overrides it |
| Temperature | none | none | none | a floor's `cold(a)` and weather laws (below) |
| Falls | none (worldgen's 0.8 m climb only, `settle/terrace.rs:429`) | none | E | `fall(a, drop_m)` (new primitive: the authority needs height as a rule) |
| Day length | Rust const, `world.day_ms` at init | `rules/src/lib.rs:26`; `authority/src/lib.rs:33` | C | `laws().day_ms` |
| Night hours | Rust inline 6..20 | `rules/src/lib.rs:40` | C | `laws().dawn_h`, `dusk_h` |
| Year and seasons | Rust const + `world.year_days` | `rules/src/lib.rs:64-90`; `authority/src/common.rs:650-674` | C, E at a season change | `laws().year_days`, `seasons()` |
| Life stages, lifespan, gestation | species data | `rules/src/life.rs:38-60,91,115-135` | E (1 Hz) | species data stays; `laws().life_pace` scales it |
| Spoilage | Rhai | `skills.rhai:51-66` → `authority/src/tick.rs:179,187`; storage ÷3 inline `tick.rs:184` | E (1 Hz) | `spoil_rate` (exists); the storage factor a law |
| Remains and structure decay | none: remains never decay | `authority/src/act.rs:2021` | E (1 Hz) | `decay(kind, age)` (new) |
| Regrowth | Rhai, stored at spawn | `skills.rhai:554-564`; `authority/src/seed.rs:987,1035,1263` | E | exists |
| Steering constants | Rust inline | `rules/src/steer.rs:78,142,155,163`; `authority/src/motion.rs:41,43,272-394,516` | H | stay Rust (engine feel, not world law) unless a floor needs them |
| Tick rates (60 Hz, 1 Hz, 15 Hz fights, 1/60 slots) | Rust inline | `authority/src/lib.rs:68-69`, `tick.rs:28,77,85` | none | engine, not law |
| Seed `rules` flags (`MINDS`, `YIELD_SHIELD`, `CRY_PROMPTS_CARERS`) | compile-time | `authority/build.rs:36-48` → `rules_flags.rs` | C | `laws()` fields |
| Dead laws | `Laws.gestation_days` (no reader), `ADULT_DAYS` (no reader) | `script.rs:282`, `rules/src/lib.rs:48` | none | remove |

### How a floor overrides laws

**Composition (built: `living_rules::floors`):**
- A floor's overlay is Rhai source: functions that replace base functions of the same name, or add new ones.
- `floors::compose(base, overlay)` renames each replaced base definition `fn NAME(` to `fn base_NAME(`, then appends the overlay.
- Rhai resolves functions by name at call time, so the engine and the base script's own callers reach the floor's version. An overlay can build on the base:

  ```rhai
  // A frozen floor: cold by day too, away from fire and shelter; blizzards shorten sight.
  fn cold(a) {
      a.actor.kind == "person" && !a.actor.near_fire && !a.actor.near_shelter && inv(a, "cloak") == 0
  }
  fn laws() {
      let l = base_laws();
      l.sight_day = 7.0;
      l.fire_warmth = 5.0;
      l
  }
  ```

- **Test** (`floors::tests::one_build_two_floors_two_sets_of_laws`): one build, two composed scripts.
  - Laws: sight 11 → 7, fire warmth 3.5 → 5; untouched laws keep the base's values.
  - The base's `rates(a)` reaches the floor's `cold(a)`: a person away from fire by day heals on the base and loses health on the frozen floor; by a fire the two agree.
  - Overlays can add functions, cannot define `base_` names, and must compile.

**Versioning:**
- The `script` row holds the composed source, its revision, and two digests: the base's and the overlay's.
- The authority caches per revision, as now.
- The mind service already reads the installed script row and recompiles once per revision (`mind/src/mind.rs:909-911`, `prompts.rs:82-112`), so it sees the floor's laws.
- **Client numbers.** A public `law_card` row, written by the authority at each install like `skill_card` (`authority/src/combat.rs:513-547`), carries the numbers clients need: speeds by kind and gait, sight by light, day length, season, warmth radii. The client never runs the script.
- **Editing laws in play** (gods, WORLD_VISION) is installing a new overlay revision through an authorized skill, so it uses the same path.

**Gap (closed 2026-11-09).** The script cap. `MAX_SOURCE` was 64 KiB, and `skills.rhai` is already 56.9 KB, so an overlay composed as source had about 7 KB of room. Since `rhai-1` it is 256 KiB ([script engines](SCRIPT_ENGINES.md#what-changed-on-rhai-1)): compile time and memory grow about linearly with the source, and an install is rare. If overlays outgrow it, `Scripts` can compile the base and the overlay as two ASTs and merge them (Rhai's `AST::merge` gives later functions precedence), keeping each part under the cap.

### Technology and magic without forking the engine

Combat and town life already declare skills by traits in the script (`<skill>_shows()`, shapes), and the engine picks primitives by trait, never by skill name. A floor differs in technology by its overlay and its seed:
- **Skills it adds.** A cyberpunk floor's `hack`, `repair_drone`, `ride`; a fantasy floor's `fire_bolt`.
- **Skills it refuses.** An overlay's `fire_bolt_check(a)` returns "nothing answers here".
- **Items its laws know.**

Know-how that travels still exists; it just fails its checks honestly where its laws are absent. No floor flag, no `if floor == …` in Rust.

### Five laws wired end to end on paper

1. **Sky islands where falls hurt.**
   - **Today.** No rule reads height (movement is flat; `Land::height` is presentation), and terraces wall drops over 0.8 m.
   - **Needed:**
     - a primitive in the authority, `fall(a, drop_m)`, called when a move segment crosses an edge whose height difference exceeds `laws().climb_m`. The authority keeps the `Land`'s heights, about 9 MB at 2048 m (ISLAND_AUTHORITY);
     - an event law, `fall_hurt(a, drop_m)`, returning damage;
     - the sky floor's tiles marking island edges as walkable `Drop` edges rather than walls.
   - **Changes.** Walking off an edge is possible and hurts or kills by the floor's law; a glide skill's `_check` reduces it.
   - **Verified by.** `verify-core` scenes. Push a character off a 6 m edge on a scratch floor and assert the `vitals.hp` drop equals `fall_hurt(6)`; a base-floor run never calls it.
2. **A frozen floor where cold drains health away from fire and shelter.**
   - **Today.** `cold(a)` is a Rhai boolean, night-only.
   - **Change.** The overlay above, plus a `rates_key` law that includes the cold inputs (near fire or shelter, cloak), so the rate is recomputed when someone walks away from the fire, not on the next unrelated key change.
   - **Readers.** `authority/src/brain.rs:172` (rates), `act.rs:131-152` (warmth radii from `laws()`).
   - **Verified by.** `floors::tests` (done, rules only), then a `verify-core` needs scene: the hp slope by day away from fire is negative on the frozen floor and positive on the base.
3. **A floor without magic, or with tech skills instead.**
   - **Change.** The overlay refuses `fire_bolt` in `fire_bolt_check` and adds `hack_check`/`hack_done` with `_shows()` traits. Seeds hand out the matching know-how; `skill_card` lists what exists on the floor.
   - **Readers.** `act::begin` → `Scripts::check`, the skill bar (`combat::cards`).
   - **Verified by.** `verify-player`. A newcomer who knows `fire_bolt` is refused on the tech floor, with the script's reason, and succeeds on the base floor; `skill_card` differs between the two.
4. **A different day or season length.**
   - **Change.** `laws().day_ms` and `year_days` replace `DEFAULT_DAY_MS` and the seed's `year_days`. `hour_of`/`day_of` take the law; `is_night` takes `dawn_h`/`dusk_h`.
   - **Readers.** `authority/src/lib.rs:33` (world row), every `hour_of` caller, weather, town-life schedules (residents' hours come from their graphs, so they keep hours, not minutes).
   - **What travels.** Age crosses floors as elapsed life, so a long-day floor does not age a visitor faster.
   - **Verified by.** `verify-core` tick scene. Two scratch floors with 12-minute and 30-minute days report hours that advance at those rates; `law_card.day_ms` matches.
5. **Slower or faster healing, hunger or decay.**
   - **Change.** An overlay scales `rates(a)` (`let r = base_rates(a); r.hunger *= 0.5; r`) and `spoil_rate`, and adds `decay(kind, age)` for remains (new event law; remains never decay today).
   - **Readers.** `brain.rs:172`; `tick.rs:179,187`; a new 1 Hz remains sweep by index.
   - **Verified by.** `floors::tests`-style rules tests for the numbers, `verify-core` needs and spoil scenes for the effect.

## What links the floors in the world

Each floor has a **gate**: a structure its generator places like a landmark, with a `travel` skill whose requirements are that floor's laws. On the megacity floor it would be a tower at the core. On the fantasy island it would be a ring of standing stones above the giants' shelf. Its look is the floor's, and its function is shared.

**No prescribed narrative.** The gate is a fact of the world, not a quest marker:
- Nothing tells a character where it leads.
- What gates do, who guards them, what it costs and what lies beyond are learned by using them, by rumour, by tablets and by people who came through.
- Progression comes from each floor's initial state, the **world preset** idea the trials use: a gated know-how ladder, growing pressure, ruins with tablets, social hooks, frontiers. Some floors are harder to reach (a gate that needs a token found on another floor, a fee in a currency only one floor mints). Some are harder to survive (the frozen floor without fire know-how).
- A preset is seed data, so it changes without code. Its resolved configuration is recorded with the run (AUDIT_AND_EXPERIMENTS).

## Floor suggestions

The three the user named, then six more. Each needs mechanics or generation the others do not, which is the point: each floor tests a different part of the engine.

| Floor | Setting and geography | Signature mechanics | Why it adds something |
|---|---|---|---|
| **The island of giants and small folk** (fantasy, exists) | The current 2048 m island grown to 3–4 km: ranges, rivers, the walled town, villages, the giants' high shelf and the small folk's forest hollow. | Body size as a rule (reach, separation, speed, sight by size); magic skills. | The baseline floor. It forces body size into the rules, the biggest gap the island already shows. |
| **The foundry valley** (steampunk) | A long river valley under smog: terraced brick towns on both slopes, mills on the river, a canal and rail line, mines in the head of the valley, an airship mast. | Machines as structures that run on fuel and water (a mill grinds only while the river runs and someone stokes it); smoke as weather that shortens sight; rail and canal as fast travel along fixed lines. | Infrastructure that works only while maintained: the "growth and infrastructure" deadlines of the performance contract in gameplay. |
| **The megacity** (cyberpunk, prototype below) | One city of towers filling a 4 km floor: a core, ring highways, wards of different wealth, slums, works and docks on a bay, a wall; dry plains, ruins and salvage camps outside. | Density: thousands of lots, crowds and vertical structure; access (doors, wards, gates that check who you are); salvage as the outside economy. | The scale test: generation, hosting, streaming and population at the top of the contract. |
| **The sky archipelago** | Floating islands of 50–400 m at different heights over a cloud sea, joined by rope bridges, wind currents and a few stone causeways. | Falls that hurt or kill; wind as a moving force; gliding and climbing skills; bridges you can cut. | Height becomes a rule: the first real use of `Land::height` by the authority, and the first floor where the map has edges you can walk off. |
| **The long winter** | Tundra and pine taiga round a frozen sea; settlements in sheltered valleys; the sea freezes into a walkable plain in the cold season. | Cold that drains health away from fire and shelter; fuel as a need; seasonal terrain (sea ice walkable in winter, water in summer); snow slowing movement. | Laws that change terrain by season: a tile class that depends on time, tested in the tick and the client. |
| **The drowned city** | A sunken old city in a lagoon: rooftops, towers and bridges above water, streets below it; tides twice a day. | Water level as a law (tide by hour); walkability that changes with it; boats and swimming; diving to salvage. | Time-varying walkability on a large scale, and a reason for boats. |
| **The deep halls** | No sky: a vast cavern system of halls, shafts and an underground river, lit only by fungi, fire and what people carry. | Sight from carried light only; growing food without sun; vertical shafts; echoes carrying sound far. | Perception driven entirely by light, which tests the "view as perception" direction (GAME_BRIEF) at its extreme. |
| **The overgrowth** | A forest floor that eats what is left: roads and towns overgrow within days without upkeep; ruins under roots; a giant central tree. | Decay and growth as strong laws: structures and roads decay unless maintained, trees spread onto unused tiles. | Infrastructure decay, which today does not exist (remains never decay), with visible consequences and real maintenance work. |
| **The open steppe** | A 6–8 km grassland with a few rivers and no forests; herds migrate; nomad camps move with them. | Mounts and riding; migration by season (species already declare `migrate`); camps that pack up and move. | Size beyond 4 km and long travel, with settlements that are not fixed: the hardest test for a fixed lot table. |

## Engine gaps

### Scale

Measured on the dev-box: AMD Ryzen AI Max+ 395, 32 threads, x86_64 Fedora, rustc 1.97.1, wasmtime 39.0.1, SpacetimeDB 2.14.1 in a scratch container. Other agents' work kept the load average at 4–12, so times are indicative. Seed 11, `floor-megacity.json`; numbers are for the code on `floors-1`.

| | 2048 m | 4096 m |
|---|---|---|
| Native `land::generate`, x86_64 (dev-box) | 1.67 s | 7.27 s (5.8 s without the city, earlier build) |
| Native `land::generate`, aarch64 (DGX Spark, rustc 1.99.1) | 1.14 s | 4.92 s |
| Native peak heap during generation | 83 MB | 299 MB |
| `Land` kept after generation | 13 MB | 50 MB |
| WASM under wasmtime 39 (wasm32-wasip1, no fuel metering) | 2.42 s, peak heap 75 MB | 11.41 s, peak heap 282 MB |
| WASM in the authority (`init.land.generate`, fuel metered) | **3.05 s** | **ran out of energy after 5.2 s** (4.98 s on the final build, with a 2,000-character world ticking on the same host) |
| Estimated fuel for generation (120 × 10⁹ ran out in 5.2 s; scaled by the WASI times) | ~70 × 10⁹ (about 60% of the budget) | ~330 × 10⁹ (about 2.75 budgets) |
| `hosted_map` + digests, native x86_64 | 0.02 + 0.02 s | 0.12 + 0.08 s |
| `init.land.host` in the authority | 76 ms | not reached |
| Whole `init` in the authority (invoke to "Database initialized") | 3.9 s, of which town seating 74 ms | not reached |
| Module linear memory (`spacetime_worker_wasm_memory_bytes`) | 88.0 MB with about 2,100 characters (86.9 MB right after `init` on an earlier build; the island: 79 MB, ISLAND_AUTHORITY) | not reached; estimated 290–340 MB, the generation peak, since linear memory never shrinks |
| Rows: `terrain_chunk`, `lot`, `structure`, `gate`, `resource_node`, `settlement` | 16,384 (5.4 MB), 3,399, 3,934, 1,030, 20,218, 33 | 65,536 (~21.5 MB), 15,069 lots, about 4× the rest |
| Props (derived, not stored) | 1,905 | 5,314 |
| Container RSS (service-wide: two scratch databases, one with a 2,000-character crowd) | 954 MB | not reached |

**Digests:**

| Size | Builds that agree | Tiles | Heights | Layout |
|---|---|---|---|---|
| 2048 m | WASM authority, native x86_64, wasm32-wasip1, native aarch64 | `e182d4d6b67f0e3b` | `78040b114f6a6db6` | `50372111eee395a3` |
| 4096 m | native x86_64, wasm32-wasip1, native aarch64 | `85bd32f149ce7ef0` | `6016e68279d19134` | `cc0a5ed75c0f3ff0` |

The island's digests are unchanged by this work: tiles `c19cc98e8f1471f0`, heights `16412fd044a2b0b0`, layout `d45f735150add4ba` on `b7cf7fb` and on `floors-1`. In the verify run, both land worlds' `land` rows also matched a native regeneration.

**What follows:**
- **4096 m cannot be generated inside one reducer.** The island fits (≈1.9 s, about a third of the budget), the 2048 m megacity fits, a 4096 m floor needs about 2.7 budgets. The budget is fixed in standalone. Options, best first:
  1. **Staged generation.** `create_floor` schedules stages, each a reducer under budget, keeping intermediate results in private tables:
     1. macro grids (elevation, water, regions, sites: about 2 MB at 4096 m);
     2. tile classification in bands of rows (local given the macro grids);
     3. the global passes (connectivity, water distance);
     4. the settlement plan.

     It stays deterministic and digest-checked. The cost is that `Land` must be rebuilt from stored parts between stages. A precedent exists in the removed line ([STAGED_WORLD_INITIALIZATION_43](STAGED_WORLD_INITIALIZATION_43.md)).
  2. **Fewer instructions:**
     - classify tiles from the macro grids with a cheaper detail noise;
     - skip `connect`'s whole-map passes where the city has already linked everything.

     A 2× gain buys 4096 m only on fast CPUs, since fuel counts instructions, not seconds.
  3. **Offline generation and import.** A native tool generates; batched admin reducers insert `terrain_chunk` and `lot` rows; the authority recomputes the digests at the end. It is the fastest, but the module plus seed no longer generate the floor by themselves.
- **Client.** Regenerating a 4096 m floor takes about 7 s natively and keeps 50 MB; with the disk cache above, only the first visit pays. Streaming frame time in the look-dev island, on the dev-box's Radeon 8060S (Vulkan, headless 1600 × 900, uncapped):
  - the route ran from the core's plaza out to the first ring at run speed (470 m, 130 s, 28,863 frames);
  - p50 4.4 ms, p95 5.8 ms, p99 8.7 ms, worst 37.1 ms, with 5 frames over 33 ms and none over 50;
  - about 300 models and 1,400–1,500 meshes in view;
  - other agents kept the load average at 9–12.

  The worst frames are chunk loads, as on the island (ISLAND_AUTHORITY: 150–250 ms single frames there). The look-dev client ran from a private build with a 9-line change (below).
- **Population density.** The 2048 m city holds 2,217 metro, 620 slum and 437 works lots. The authority's `structure` table gets 3,934 rows (a door per building and one per gate tile), and `resource_node` 20,218 (the wastes only: paved city tiles grow nothing).

### Staged generation and the largest floor

Built on `megacity-1`. Numbers are from the dev-box (AMD Ryzen AI Max+ 395, 32 threads, Radeon 8060S), with other agents keeping the load average at 5 to 15; the fuel numbers are machine-independent.

**SpacetimeDB documentation and source checked (v2.14.1, as above):**

| Question | Finding | Implication |
|---|---|---|
| The per-reducer budget | **[V]** `FunctionBudget::DEFAULT_BUDGET` is 120 × 10⁹ fuel, one unit per WASM instruction (`crates/client-api-messages/src/energy.rs:133-142`); standalone's `NullEnergyMonitor` always grants it (`crates/core/src/energy.rs:27-35`). | Every step of world creation must stay well under 120 × 10⁹ instructions. |
| Scheduled reducers | **[V]** A `#[table(scheduled(reducer))]` row with `ScheduleAt::Time(ctx.timestamp)` runs its reducer once, as soon as possible ([schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/), `docs/docs/00200-core-concepts/00300-tables/00500-schedule-tables.md`). Each call is its own transaction with its own budget. | One step per call; each step schedules the next. |
| Module memory between calls | **[V]** "Global and Static Variables Are Undefined Behavior": instances may be fresh, replaced on publish, lost on restart, or replayed; global state is not rolled back with a transaction (`docs/docs/00200-core-concepts/00200-functions/00300-reducers/00300-reducers.md`). | Intermediate grids (hundreds of MB) cannot go through tables every step, so they stay in instance memory **as a cache only**: the durable `genesis` row says how far generation is, and a cache that is not this seed's, or not exactly as far, is thrown away and generation restarts from its first step. Generation is deterministic, so the restart rebuilds the same land; rows already written are the same rows and are kept. |
| Linear memory | **[V]** wasm32 only, no limit below 4 GiB, and it never shrinks (above). | A floor keeps its generation peak for life. |

**Design:**
- **Rules.** `land::generate` is now `land::Gen` run to the end, so staged and one-shot generation are the same code and give the same digests. Steps:
  1. the macro pass in two halves: relief, lakes and rivers; then water distances, moisture, regions and sites;
  1a. dispersed sites (hamlets, [seeded lives](SEEDED_LIVES.md)), at most 24 per step (since 2026-11-10);
  2. tile classification in bands of 4 M tiles (each band computes its own ground with a row of margin);
  3. fords, cleared sites and the connectivity pass;
  4. shore distances on land, then in the water;
  5. the planner (`settle::Staged`): the city, island roads (since 2026-11-10 in three parts: the routing grid, the settlements routed 8 per step, then the landing, cave paths, smoothing and crossings), streets, stairs, one step per ward's lots and one per band of a ward's back-fill (each band with its own random stream), the remaining towns' lots, painting, the walled connectivity pass, ornaments one settlement per step, and the roads as a graph for residents' known ways (`living_rules::ways`, kept on `Land::ways`, not serialized).
- **Authority** (`authority/src/floor.rs`):
  - A module built with a seed (the island, labs) creates its world in `init` as before when the land is at most 2048 m (`INLINE_MAX_M`).
  - A **floor module** (`LIVING_SEED=none`) starts empty. The admin's `create_floor(seed_json)` checks the seed, keeps it in the private `floor_seed` row, and creates the world.
  - A larger land is created by `genesis_step`, scheduled only. Each call runs one generation step, or hosting, or a batch of 16,384 terrain chunks, 8,192 lots, or 1,024 tile rows of resources, then people, animals and the settlements' life. The public `genesis` row holds progress, the step count, restarts and `done`. Ticks start when it is done.
  - **A land's side** is a multiple of 16 from 256 to 8192 m (the tested limit); `create_floor` refuses any other before it keeps the seed (`island::params_of`), where generation would panic (`Gen::new` asserts 256..=16384).
  - **A stopped chain.** Each step is a one-shot schedule. SpacetimeDB 2.14.1 deletes a one-shot row after the call whatever the outcome (`call_scheduled_reducer_with_tx` in `crates/core/src/host/scheduler.rs` at `v2.14.1`), and a step that fails rolls back its own scheduling of the next, so one failed step stopped the creation for good, and `create_floor` refuses a second seed. A step that returns an error now keeps the reason in the `genesis` label ("stopped: …") and schedules nothing; the admin's `resume_genesis` schedules the next step (refused while one is scheduled or once the world is made), and `stop_genesis` unschedules it (to free the server or before a module update). A trap (a panic, fuel run out) leaves the label as it was; `resume_genesis` carries on the same way, and a lost instance memory restarts generation from its first step as before. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) (docs 2.0.0) say one-shot rows are deleted after a scheduled reducer runs and interval rows never are, but not what an error does; the source settles it. An interval schedule would retry by itself, but a step runs for seconds and a deterministic failure would then repeat at every interval, so the chain stays one-shot with an explicit resume.
  - Readers of the seed (species overrides, weather, ways, the newcomer kit, communities, habitats) read the active seed, loaded once per instance when the world row is first read.
  - The seed's `rules` switches are still compiled in: `LIVING_RULES` sets them for a floor module, and `create_floor` refuses a seed whose `rules` differ.
- **Tooling:**
  - `just living-floor NAME DB` builds the floor module with the seed's switches, publishes it and calls `create_floor`.
  - `living/tools/land_fuel/run.sh SEED [SIZE]` runs each step under wasmtime 39.0.1 configured as SpacetimeDB 2.14.1's reducer engine, with the budget refilled per step, and prints fuel, time and linear memory per step and the digests.

**Fuel per step** (the second-pass megacity seed; the first column is the old generator for comparison):

| | 4096 m, prototype generator | 4096 m | 8192 m |
|---|---|---|---|
| Generation steps | 13 as first split (one `init` would need all 333 × 10⁹) | 126 | 152 |
| Total fuel, generation | 333 × 10⁹ (2.8 budgets) | 346 × 10⁹ (2.9 budgets) | 1,574 × 10⁹ (13.1 budgets) |
| Worst step | 77.6 × 10⁹ (lots, before they were split per ward) | 40.0 × 10⁹, 33.3% (a band of tiles) | 50.9 × 10⁹, 42.4% (island roads; relief and rivers 42.3%) |
| Hosting and digests (one step) | 8.8 × 10⁹ | 8.5 × 10⁹ | 35 × 10⁹ (prototype seed) |
| Linear memory at the end | 207 MB | 213 MB | 847 MB |

**With hamlets (2026-11-10, `lives-1`; the island seed, this branch against `origin/main` at `c0ff89d`, `land_fuel` on the dev-box).** Hamlets are dispersed sites at 3 per km² (2 to 400), so a large floor has many: 133 at 8192 m and 33 at 4096 m against 9 at 2048 m (seed 7). The first build of this placement trapped on fuel at 8192 m in its own step, which scanned every candidate against every placed site through a hashed grid on each of its 24 picks. Then, with that fixed, it trapped in a tile band, where each tile's height looped over all ~140 sites' levelling. Both were rewritten to give the same results (the island's and the megacity floor's digests are unchanged): a candidate keeps whether a site blocks it and its nearest site, updated only near each new site; a site's levelling is skipped by a box test before the distance. Island roads were then split into parts (their worst step had grown from 74 to 91 × 10⁹, 76% of a budget), and each settlement's distance to the network is kept up to date instead of measured afresh each round.

| Island seed | 2048 m, main | 2048 m, this | 4096 m, main | 4096 m, this | 8192 m, main | 8192 m, this |
|---|---:|---:|---:|---:|---:|---:|
| Steps | 14 | 18 | 17 | 21 | 29 | 195 (6 hamlet steps, 18 route steps, ornaments for every hamlet) |
| Total fuel | 57.2 × 10⁹ | 52.9 × 10⁹ | 203.2 × 10⁹ | 197.6 × 10⁹ | 793.5 × 10⁹ | 1,028.7 × 10⁹ |
| Worst step | 24.6% | 20.0% | 28.5% | 26.5% | 61.9% (island roads) | 40.2% (relief and rivers) |
| Hamlet steps | — | 0.17 × 10⁹ | — | 0.76 + 0.04 × 10⁹ | — | 3.0 × 10⁹ first, 0.2–0.4 after |
| Island roads | 3.1 × 10⁹ | grid 1.3, routes ≤ 0.6, end 0.4 | 14.4 × 10⁹ | grid, routes ≤ 1.3, end 2.5 | 74.3 × 10⁹ | grid 37.4, routes ≤ 2.7, end 16.7 |
| Roads as a graph | — | 0.08 × 10⁹ | — | 0.16 × 10⁹ | — | 0.89 × 10⁹ |

Tile bands at 8192 m cost 26–38% of a budget here against 16–29% on main: the levelling's box test still runs once per site per tile. The megacity floor seed (no hamlets) gives the same digests on both branches, which checks that the rewritten site placement and island roads pick the same sites and roads.

An 8192 m run first trapped on fuel in a slum ward's back-fill, which searched every street of the ward per grid point. That was fixed with a bucket lookup and back-fill bands before anything reached the authority; the harness exists to catch exactly that.

**In the authority** (a private 2.14.1 container on the dev-box, the floor module, `create_floor` called once):

| | 4096 m | 8192 m |
|---|---|---|
| Staged creation, `create_floor` to `done` | 20.2 s | 92 s |
| Rows: `terrain_chunk`, `lot`, `structure`, `resource_node`, `settlement` | 65,536; 12,059; 11,405; 75,749; 54 | 262,144; 47,254; 42,918; 305,533; 54 |
| Module linear memory (`spacetime_worker_wasm_memory_bytes`) | 212 MiB | 847 MiB |
| Container RSS (service-wide, both floors loaded) | | 2.2 GB |
| Digests against a native regeneration | identical (`1bfecfe677332f4a` `08e29adfdf9ee515` `5490b81d7ff1861d`) | `f69cc54c…` natively; the authority's row was the same in the fuel harness |
| Tick at rest, 30 s (105-107 people, 48 animals) | p50 0.72, p99 1.62, max 2.12 ms; 42 ms of work a second | p50 0.75, p99 1.71, max 3.21 ms; 44 ms of work a second |

Tick cost follows the population, not the land: the two floors tick alike. Before the second pass, the prototype generator had already been created at both sizes the same way (58 steps in 21.9 s, 92 steps in 120 s), with all 8 of its wolves placed (5 before: wolves now live where the seed's `animals.habitat` says, the megacity's wastes, and a lattice search finds scarce ground).

**The client** (look-dev with `LIVING_GAME_SEED`, the private binary copies, headless 1600 × 900, uncapped, a 400 m run outward from the core along an arterial at 3.6 m/s):

| | Land generated on the worker thread | Process peak RSS | Frames | p50 | p95 | p99 | Over 33 ms |
|---|---|---|---|---|---|---|---|
| 4096 m, prototype | 8.7 s | 2.07 GB | 28,448 / 28,452 | 3.90 / 3.83 ms | 5.09 / 5.12 | 5.66 / 5.75 | 0 |
| 4096 m, second pass | 8.9 s | 1.63 GB | 28,304 / 28,427 | 3.91 / 3.85 ms | 5.14 / 5.17 | 5.71 / 5.91 | 0 |
| 8192 m, second pass | 37-39 s | 1.89 GB | 32,708 | 3.10 ms | 4.74 | 5.20 | 0 |

A first run of the second pass at 4096 m under a load average of 11 read p95 18.5 ms and 43 frames over 33 ms; the reruns at load 5 to 8 match the prototype, so that was load, not the city.

**The largest floor: 8192 m.** It generates, hosts and streams within budgets here. What binds above it:
1. **Per-step fuel.** At 12,288 m the relief-and-rivers step and the island-roads step would need about 114 × 10⁹ each, extrapolated by area (native: 88 s for the whole land), so they must be banded too. Both are whole-grid passes that can be split as the tiles were.
2. **Module memory.** The generation peak is about 2.1 GB at 12,288 m (native heap) and would reach the 4 GiB wasm32 cap near 16,384 m; it stays for the floor's life, per floor. The biggest buffers are the connectivity passes' per-tile `u32` components, `u16` costs and `u8` directions, and the shore pass's `f32` distances: banded or compact encodings would cut it.
3. **The client.** Joining an 8192 m floor regenerates its land for 37-39 s and about 0.8 GB on the client, and twice that at 12,288 m. A land cache keyed by the digests ([the client switching floors](#the-client-switching-floors)) is needed before floors grow further.

Tick time and frame time do not bind: both depend on what is near, not on the land's size.

### The 4 GiB question

**Is 4 GiB a hard cap in our stack? Yes, but only for what the module holds in its own heap.**
- wasm32 linear memory is at most 4 GiB, and SpacetimeDB 2.14.1 sets no lower limit for Rust modules ([V], above).
- **Table data is not in it.** Rows live in the host datastore's pages and are copied through host calls ([V]). The megacity's 65,536 chunk rows, its lots and all characters count against host RAM and the shared page pool, not the module.
- **memory64 is not supported** and not announced ([V]/[A]).
- **What the cap applies to:**
  - thread-local caches: the derived `Map` (tiles: 4 MiB at 2048 m, 16 MiB at 4096 m; `common.rs`), compiled scripts and `Laws`, compiled behaviour graphs;
  - transient allocations inside a reducer.

  Generation is by far the largest. The peak heap during generation is 75 MB at 2048 m and 282 MB at 4096 m in wasm32, against a retained 4–16 MB map.
- Linear memory **never shrinks**. A floor's module therefore keeps its generation peak for its whole life: 88 MB measured at 2048 m, about 290–340 MB estimated at 4096 m. Per database, this is multiplied by `1 + procedure instances that ran` (`procedure-instance-pool-size`, default CPU count). Avoid procedures on floors, or measure them.
- **Scaling.** A host with 10 floors at 4096 m keeps about 3–3.5 GB of module memory, plus each floor's tables (tens of MB) and the page pool.
- **What dominates.** Generation's whole-map buffers: `f32` per tile for natural ground (67 MB at 4096 m) and water distance (67 MB), tile and mask bytes (17 MB each), chamfer passes. Staged generation also caps the peak: bands of rows instead of whole-map `f32` arrays.
- **If retained memory grows** (heights become a rule, so the authority keeps the `Land`):
  - **Derive on demand with bounded caches.** Keep the macro grids (≈2 MB) and the lot table. Compute `height()` per query (about 150 ns), and cache it per chunk in an LRU of a few hundred chunks.
  - **Chunked tiles in tables only.** Read `terrain_chunk` rows by index instead of holding the whole map. This costs a host call per chunk on a path search, so paths need a hierarchical road graph first (ISLAND_AUTHORITY, risks).
  - **Compact encodings.** 4-bit tile classes (half the map), heights as `u16` decimetres over a coarse grid with bilinear detail.
- **Conclusion.** A single 8 km floor (67 M tiles) would need about 1.2 GB transient in today's generator and 64 MiB of map cache. Staged generation is required there, but the 4 GiB cap is not the binding limit; the fuel budget and per-floor tick are.

### Verticality

**Today.** Buildings are blockers. A lot's footprint is `Wall` in the hosted tiles; interiors, roofs, walkways and stairs between levels do not exist in the rules. Terraces have ground levels and stairs, and they are the only multi-level ground.

**A staged path:**
1. **Street level plus visual vertical structure** (where the megacity is now). Towers up to 112 m, megatowers when assets exist, elevated highways drawn as presentation over a street-level road, sky bridges and walkways as props.

   The rules see only the street. Movement, sight and missiles use the 2D tiles. Sight lines ignore height, an honest simplification that `docs/GAME_BRIEF.md`'s perception view must state.
2. **The smallest real multi-level step: levels as separate tile layers, joined by stairs.**
   - A `level` (0 = ground) on `body`, `lot` and `terrain_chunk` (id `(level << 28) | (cy << 16) | cx`).
   - Level 1 covers only where a structure provides it: a rooftop, an elevated walkway, a highway deck.
   - Stairs and lifts are tiles that change level.
   - Path search runs per level, with links at stairs.
   - Perception between levels is limited to "see down from an edge". Missiles do not cross levels.

   This covers rooftops, a walkway between towers and a two-deck highway, without 3D physics. It costs a level index on subscriptions and one more chunk window for a body on level 1.
3. **Interiors as places.** Entering a building moves you into its interior, a separate small map keyed by the lot. That reuses the caves' idea that the caverns behind a mouth are a separate space (`land.rs`, `SiteKind::Cave`). It costs nothing until someone enters.
4. **Full height** (ledges, falls, jumping between roofs, line of sight in 3D) only on the sky floor. There height is the floor's point, and its laws (`fall_hurt`) need the authority's `height()` anyway.

### Populations per floor

**The contract.** 2,000 active characters, including a 200-character local battle, for 8 hours, at 60 Hz and within the latency limits. The immediate gate is 216 characters for 30 minutes.

**Measured:**
- **Setup.** One database, the 2048 m megacity (`verify-floors-mc2k`), instinct crowds (`spawn_crowd`, foragers, no minds), then a 200-fighter battle on top. 40 s windows after 15 s of settling, through `living/tools/bench.py`.
- **Not covered.** Observer, subscriber and player load, and the mind service.

| Window | People + animals | Ticks/s | p50 | p99 | Max | Tick work (ms/s) | Evaluations/s |
|---|---|---|---|---|---|---|---|
| seeded residents only | 96 + 40 | 60.3 | 0.62 | 1.80 | 2.58 | 41 | 161 |
| + 200 crowd | 296 + 40 | 60.4 | 1.31 | 2.78 | 4.00 | 81 | 440 |
| + 500 | 596 + 40 | 60.4 | 1.96 | 3.48 | 4.41 | 119 | 860 |
| + 1,000 | 1,096 + 40 | 60.4 | 2.89 | 5.19 | 7.06 | 177 | 1,590 |
| + 2,000 | 2,096 + 40 | 60.4 | 4.83 | 7.12 | 8.66 | 290 | 3,067 |
| + a 200-fighter battle (`spawn_battle 200`; 2,195 people counted) | 2,195 + 40 | 60.3 | 5.21 | 9.84 | 14.16 | 320 | 4,358 |

- Tick times are in ms. The dev-box load average was 3–5 during these windows.
- An earlier run of the same steps under other agents' builds (load 6–14, previous generator build) read p99 8.2 ms at 2,048 people and p99 15.7 ms, max 48 ms, with the battle. Load matters at this scale.
- **Where the work goes** at 2,096 people (ms of work per second): evaluation slots 147, motion 52, wakes 51, activity 37. With the battle: slots 113, combat 66, activity 65, wakes 53. Work grows by about 0.12 ms/s per character, with no sign of a knee up to 2,000.

**What follows:**
- One database holds 2,000 instinct-driven characters and a 200-character battle on a 2048 m floor at 60 Hz, with p99 under 10 ms on a quiet host.
- That is the world simulation alone. The contract adds minds (experience and deliberation writes), every connected client's subscriptions and delivery, players' reducer calls and the 8-hour duration, none measured here.
- A 4096 m floor with the same population spreads it further apart; that changes local density, not per-character tick cost.
- So the population question for a floor is open, and the next measurement must add subscribers and minds.

## Zones within a floor (later)

### What zoning would solve

- **Memory: the weakest reason.**
  - A 4096 m floor's tiles are 16.7 M bytes: 21.5 MB of chunk rows and 16 MiB of module map.
  - Even at 4 bytes per tile, a 4096 m floor is 67 MB and an 8 km floor 268 MB, far from host or module limits once generation is staged.
  - Splitting a floor into zones would not change the generation peak, which comes from generation, not hosting.
- **CPU: the strong reason.**
  - A database runs its reducers one at a time on one executor, and a scheduled 60 Hz tick blocks other reducers while it runs ([V] `module_host.rs:464-476`). So one floor's tick is bound to one core however many cores the host has. Different databases run on different executors in parallel.
  - Zones would spread one floor's population across cores, and across machines. That bears directly on the contract's 2,000 characters with a 200-character battle; see the measured trigger below.

### The design

- **Owner zones:**
  - A floor is split into zone databases along chunk boundaries (for example 4 quadrants of a 4096 m floor), all with the same module, seed and laws. Each generates or loads only its part of the tiles, but all hold the same macro data and digests.
  - Each body has exactly one owner zone, its authority. Zone membership is by the body's position, with hysteresis (below).
- **The overlap band:**
  - A band along each border (for example 32 m, about 3 × sight) where the neighbour holds read-only **ghost** rows of bodies near the edge: position, motion segment, `fighter` display state.
  - A zone sends its edge bodies' changes to the neighbour by IDC each tick it changes them, batched per tick. Then perception, sight and missiles work across the line: a zone perceives ghosts like bodies.
- **Actions on a ghost** are routed to its owner. A blow against a ghost becomes an IDC call `hit(target, attack)` to the owner zone, which resolves it in its own transaction and replies through `on_result`.
- **Crossing the border is a handoff,** with the floor-transit protocol: an idempotent ticket, the payload (here, everything: same floor, same laws), departure and arrival transactions.
  - **Latency estimate.** IDC delivers after the sending transaction is durable. On one host that is a commit-log flush plus a reducer call: assuming 1–5 ms each way, a handoff completes within a few ticks (about 5–20 ms), below one 60 Hz frame of client lag. A relay across machines adds a network round trip (sub-ms on a LAN, tens of ms across regions).
  - These are estimates; IDC latency was not measured here.
  - The body moves as a ghost on both sides until the handoff completes, so it never disappears.
- **The client** subscribes to both zones near a border (two connections, as for floor switching) and merges by soul id, preferring the owner's row.
- **Minds** follow their character as between floors: memory keyed by soul, and the mind service connected to every zone of the floor.

### The hard parts, with honest costs

- **Cross-border interactions without a shared transaction:**
  - **A blow across the line.** The attacker's zone sends `hit`, and the owner applies it a few ms later. A dodge that the target's zone committed meanwhile wins, so outcomes need a rule for conflict, such as the owner's state at receipt. Fair, but not instantaneous.
  - **Two people trading at the border.** A trade is a two-party transaction. It needs a two-phase protocol (reserve in A, transfer in B, confirm or release in A), or a rule that trades happen only within one zone (simplest: hand one party off first).
  - **A crowd on the line in a battle.** Every hit is a cross-zone call, and ghost traffic peaks. The usual answer is to move the border: a battle locks its locality into one zone, and the zone split adapts. That is the hardest part, and it is why the 200-character battle should stay inside one zone.
- **Ghost update traffic.** For B bodies in the band changing at rate r, ghost writes are B × r rows/s per direction. With 200 bodies in the band at the town's 68 updates per second per 72 bodies (ISLAND_AUTHORITY), that is about 190 rows/s of about 150 B, about 28 kB/s per border per direction. Moderate, but it is an extra write path in every tick.
- **The double subscription.** A client near a corner holds up to four connections. Each carries its own initial window send (about 44 kB per window move, ISLAND_AUTHORITY).
- **Oscillation** when someone stands on the line: hand off only when the body is a hysteresis distance past the border (for example 8 m) and has stayed there for a minimum time (for example 2 s).
- **Debugging and verification across two authorities.** Causal evidence then spans two commit logs. Every cross-zone call carries its ticket or hit id, and `verify-*` skills need a two-zone scratch setup. That is a new verification surface.

### Recommendation

- **One database per floor first,** with the transit protocol built general enough that a zone handoff reuses it (ticket, payload, idempotent arrival, return on refusal).
- **Zones only when measurement shows a single database cannot hold the floor's population within the tick budget.** The trigger is: tick p99 above about 8 ms (half the 16.7 ms frame, leaving room for spikes and housekeeping) at the floor's intended population. The work per second is a second signal: above about 500 ms/s, half a core of tick work. On today's numbers, a single megacity database reaches about 7 ms p99 at 2,000 characters and 10 ms with the battle, before minds and subscribers. It sits at the trigger, not past it.

The cheaper next step is inside the database:
- evaluation slots are half the tick work (147 of 290 ms/s), so evaluation cost per character is the first target;
- moving combat-rate laws to compiled tables (above) is the second.

Zoning should wait for a run with minds, subscribers and players at the contract's population that still exceeds the trigger after those.

## Prototype: the megacity floor

### The generator

- **A city mode of the land generator.** `LandParams.metro: Option<MetroParams>`. With it:
  - the land is relief, water and regions as before;
  - mountain ranges rise only beyond the city's edge, and the ground inside is levelled toward the plain;
  - no lakes stand in it, and the land's other sites keep outside it;
  - then `settle::metro` lays out the city before the usual roads between settlements.

  Without it nothing changes: the island's digests are identical on `b7cf7fb` and on `floors-1` (tiles `c19cc98e8f1471f0`, heights `16412fd044a2b0b0`, layout `d45f735150add4ba`).
- **The city, from the centre out** (`living/rules/src/settle/metro.rs`):
  - a central plaza;
  - 8 arterials running straight out through the wall into the wastes, ending at the shore on the sea's side;
  - 3 ring highways at 0.3, 0.58 and 0.82 of the radius;
  - the wall at the edge, with a gate on every arterial;
  - 25 wards: the core and 3 bands × 8 sectors.
- **Each ward takes the first matching district, by band, side toward the sea and wealth:**

  | District | Where | Character |
  |---|---|---|
  | core | the centre | towers up to 112 m round the plaza, the tallest on the rich side |
  | works | the sea's side | workshops, fabs and docks |
  | slum | the poor edge | 34 × 30 m blocks, 3.2 m lanes, kiosk shacks and narrow stacks, unpaved; reads sparse (below) |
  | dense | the inner band | blocks and towers |
  | mid | the rest | mid-rise blocks |

- **Inside each ward:**
  - a street grid turned toward the centre, clipped to the ward and to walkable ground;
  - a square in the cell nearest its middle, joined to a street;
  - lots along every street and along its own side of its highways, with passages through each frontage so courtyards stay reachable, and lamps along the highways;
  - its open ground paved, except the slums.
- **Outside the wall:**
  - dry riverbeds (`Water::dry_rivers`): cut and sanded, with no water;
  - one oasis lake;
  - arid ground (the region looks are seed data);
  - outposts, salvage camps and ruins (village sites in their own styles), joined by roads to the arterials;
  - caves in the hills.
- **Reuse:**
  - the planner's lots (`try_lot`, with a coarser ground-sample step), roads, road profiles, pads, the wall and gates, ornaments (neon streets, cables, billboards, washing lines) and paint passes;
  - Lanternquay's cyberpunk kit;
  - the city's styles (`metro`, `slum`, `works`, `outpost`, `salvage`, `ruin`) are `Style`s whose new `kit` field names the `buildings.py` style their models come from, so no new models or enum variants were needed. The authority, the client and the digests take the city as ordinary settlements, lots, roads and props.
- **No new `buildings.py` presets were added in this change.** Megatowers (150–400 m), megablocks (60–120 m footprints), shacks and ruins would make the core and slums read right. They should come as new presets or functions in coordination with the assets worker, and then only data (`Style.models`, district mixes) changes here.

### Tests

Added to `living-rules` and run with every `cargo test -p living-rules`:
- **Settle tests on the megacity at 2048 m:**
  - `megacity_lots_do_not_overlap_and_stand_on_dry_walkable_ground`: lots clear of each other and of roads, on walkable dry tiles, pads level;
  - `megacity_lots_front_streets_and_name_their_models`: every lot fronts its road, models match their kit, ornaments keep doors and streets clear;
  - `megacity_roads_connect_every_ward_and_settlement`: one road network joins every ward, outpost, camp and ruin;
  - `megacity_has_core_rings_districts_and_wall`: ward count; at least 40 core towers of 50 m or more; slum, works and metro wards present; a gate per arterial; every non-ward settlement outside the wall; every ward has homes and a square; arterials run past the wall;
  - `megacity_is_repeatable`: same digests twice, at 1024 m.
- **Host test.** `hosted_megacity_keeps_doors_reachable`: squares reachable; at most 2% of doors cut off once buildings block (measured: 0 of 2,890 doors; 337 tiles cut off).
- **Floor-law tests.** `floors::tests::one_build_two_floors_two_sets_of_laws`, `overlay_adds_and_guards`, and the ignored `law_call_cost`.

### Images

Overview maps from `floor_preview`, 1 m per pixel, hosted tiles: buildings shaded by height, magenta at 110 m; highways and arterials in yellow; the wall black. The repository commits no images, so they stay on the dev-box, under `~/floors-out/final-images/`:
- `megacity-4096-overview.png` (2048 px; the whole floor);
- `megacity-4096-core.png`, `megacity-4096-slum.png` and `megacity-4096-west-edge.png` (crops);
- `megacity-2048-overview.png`.

Headless look-dev captures of the 4096 m floor, in the same folder:

| Capture | Start (x, z) | Hour | Files | What it shows |
|---|---|---|---|---|
| The core at night | 2118, 2060 | 22 | `core-default.png`, `core-40_28_110_55.png`, `core-200_12_60_60.png` | towers of 50–112 m round the central plaza, paved ground, rain |
| A ring highway | 1678, 1848 | 21 | `highway-*.png` | the first ring between dense blocks and towers (fog hides the far side) |
| The slums | 1613, 782 | 20 | `slum-*.png` | kiosk shacks and narrow stacks on unpaved ground: sparse |
| The wasteland edge | 600, 1903 | 17 | `edge-*.png` | the arterial leaving a western gate, the skyline in haze behind it |
| A salvage camp | 928, 736 | 16 | `salvage-*.png` | kiosk shacks and a garage round a dirt square, residents |

**What the captures show that the maps do not** (the first two are addressed since, `acbbda7`):
- **The wastes looked green.** The client dressed every region with its environment's plants (`RegionKind::env`: meadow, forest), whatever the tiles say. *Since `acbbda7`*, a land whose rivers run dry (`water.dry_rivers`) is arid in the client (`island.rs`, `Climate::Arid`): its open country is dressed from three environments of its own, `wastes`, `scrubland` and `badlands` (`living/game/assets/envs/`: dry grass, scrub, dead trees, rocks and rubble from `nature.py`), on ground layers of its own (dry earth, cracked mud and gravel, 16 layers in all; `terrain.rs`, `paint.py`). Seeds still don't name a look per region: the client infers the climate from the land's parameters, and a `KindLook.env` field in the rules' data remains the proper home.
- **The wall was not drawn:** the cyberpunk kit had no wall model. *Since `acbbda7`* the megacity's wall line draws a 14 m cyberpunk wall (`buildings.py`, rows in `living/rules/data/buildings.json`); the megacity core renders at 4.7 ms a frame, island frame times and material counts unchanged.
- **The night is very dark and hazy:** GAME_BRIEF already lists "cyberpunk at night reads too dark and hazy".

### Not done

- **Look-dev captures** of a land seed: *done in `acbbda7`*. `LIVING_GAME_SEED=<seed.json>` makes look-dev draw that seed's land (its `seed`, `map.size` and `map.params`, as the authority builds it from that file; for example `living/seeds/floor-megacity.json`), generated on a worker thread; without it look-dev draws the environment's `world` on the default parameters. The log line names the seed, size and source file it drew. The captures above predate it: they used a private build with a 9-line `LIVING_GAME_LAND` change that was not committed.
- **The 4096 m floor in the authority.** *Done on `megacity-1`*: [staged generation](#staged-generation-and-the-largest-floor), up to 8192 m.
- **People.** The seed peoples six settlements with 96 residents and copies the island's `town_life` and `ways`: the core (`Spire Ward`), a dense ward, a works ward, a slum ward, an outpost and a salvage camp. The other 25 settlements stand empty. Peopling every ward means one seed entry each (`"site": "metro_town"`: the k-th entry takes the k-th ward), which a world preset would generate.
- **Elevated highways, megatower and megablock models, slum shacks, port cranes.** *Done on `megacity-1`* ([second pass](#the-megacity-second-pass)); cranes are placed only where a works building's front looks over water, which is rare.
- **The slums read sparse** (*addressed on `megacity-1`*: shanties a few metres deep, and blocks back-filled behind the frontages): about 3,000 lots in two wards at 4096 m, mostly along their streets. A 26 × 18 m grid made them sparser (narrow stacks are 10–13 m deep), so it stays 34 × 30 m. Denser slums need shack models a few metres deep, and lots that fill blocks from the back as well as the front.
- **Gate tiles:** 1,030 gate tiles at 2048 m, each a `structure` row. Each 24 m arterial opening is gated tile by tile (ISLAND_AUTHORITY, risks: "gates are per tile").

## The megacity, second pass

Built on `megacity-1` (2026-11-09) from the user's brief: the megacity is the whole world, with the verticality and density, megabuildings, layered highways, neon and street life of the genre, in our own names, layout, brands and look.

### The generator

The city keeps the prototype's frame (centre, arterials, rings, wall, wards) and adds to it. Everything below is a field of `MetroParams`, `District`, `Style` or `Ornaments`; the megacity's values live in [`floor-megacity.json`](../living/seeds/floor-megacity.json) and in the district styles of `settle::default_styles`.

- **More wards.** Four rings at 0.22, 0.42, 0.62 and 0.82 of the radius, and ten arterials: 41 wards.
- **Districts with quotas.** Wards choose districts in an order drawn from the seed, and a district may cap its wards (`quota`), so the market and the old town are one ward each and land in different sectors per seed. A district that fits nothing falls back to the mid-rise fill.

  | District (style) | Where | Character | Models (city kit) |
  |---|---|---|---|
  | corporate | the core; up to 3 rich wards of the inner band | megatowers set back on plazas, 120 × 100 m blocks, an arcology in the middle of the central square (the core's `landmark`) | arcology, megatower (blade, stepped, twin, needle), neon tower |
  | neon | up to 3 wards of the inner bands | clubs and towers wrapped in screens, the neon dressing on every street, holograms | neon tower, block, food stalls |
  | market | one ward | food courts and stalls on every street | market, old block, food stalls |
  | oldtown | one poorer ward | small, irregular blocks of older brick and plaster | old block, workshop |
  | megablock | the middle bands | residential megablocks: slab, courtyard and stacked forms | megablock, block |
  | works | the sea's side, outer bands | warehouses, container stacks, cranes on the water | warehouse, container |
  | slum | the outer band, poorer side, against the wall | shanties a few metres deep and stacked, container homes; blocks back-filled on a 9 m grid with 2.2 m alleys (`fill_m`, `fill_gap_m`) | shanty, container |
  | metro | the rest | mid-rise blocks | block, market, workshop |
  | outpost, salvage, ruin | the wastes | as before, from the city kit | container, shanty, ruin |

- **Layered transport** (`MetroParams.highways`). Elevated highway pieces stand over every arterial and ring inside the wall, 24 m each: ring decks 22 m wide at 9 m, arterial decks 16 m wide at 17 m, so arterials pass over the rings. They are props over the roads (`PropKind::Highway`). The rules keep the roads at street level, as [verticality](#verticality) stages it.
- **The wall's towers** (`MetroParams.wall_towers`) at its corners, clear of the gates.
- **Street detail per block** (`Ornaments`):
  - `street_kit`: dressing along every street and lane edge, drawn by weight per spot: vending machines, steam vents, rubbish, barriers and parked vehicles;
  - `neon_streets`: the neon dressing (signs, kiosks, stalls, cables) on the N busiest streets, not just one;
  - `holograms` round squares; `scaffold` on buildings of 20 m and more; `cranes` where a works building looks over water; `salvage` beside buildings in the wastes.

  Whatever blocks (vending machines, containers, salvage) stands in a square or beside a building, as before; parked vehicles are scenery and do not block.
- **Lit windows by time of day.** Each tower's windows are lit by storey and by run, so a night view shows occupied and empty floors. All glow scales with the hour in the client (`daylight.rs`); per-window switching over the evening is a client note ([game brief](GAME_BRIEF.md#the-megacity-kit-2026-11-09)).
- **Rules seen by the rest of the engine.** Lot kinds are unchanged (the authority keys structures on them): each district style maps them to the kit's models. One `Frontage::Alley(road)` marks back-filled lots. Settlement styles map to the `cyberpunk_megacity` asset folder (`settle::env_of`), and `settle::road_surface` names each style's paving for clients.

At 4096 m (seed 11): 54 settlements, 12,059 lots (642 of 50 m or more, the tallest 299 m), 15,500 props including 1,351 highway pieces and 69 wall towers.

### Tests

The megacity tests now assert:
- the arcology in the central square and at least six corporate towers of 100 m at 2048 m;
- a ward for every district of the seed, and the quota-1 districts once each;
- back-filled lots facing their road;
- highways and wall towers allowed over roads;
- squares reachable at their edge when a building stands in their middle.

`hosted_map` starts its walkable-area search from the first square's edge when its middle is built on. All 108 rules tests pass. The island's digests are unchanged (`d1b27361ae061547` `16412fd044a2b0b0` `b130838b553d95a5`).

### Captures and a blind A/B

Look-dev captures of the prototype (`origin/main`, 14f3a72, its own worktree and assets) and the second pass, at 4096 m, at night (22:00) and dusk (19:00), with the game camera (yaw from the spot, 32°, 26 m) and a vista (16°, 70 m). Spots come from `examples/city_preview.rs`, which picks the same kinds of place in any city layout: the core, a neon street, a megablock, the slums against the wall, a highway, the market, the port, the old town (second pass only), the wastes outside a gate and a salvage camp. The images stay on the dev-box (`~/megacity-out/cap-before`, `~/megacity-out/cap-after`); the repository commits none.

A fresh agent judged 18 pairs (each spot at night with the game camera and at dusk in a vista), sides randomised, with only the images: **second pass 10, prototype 6, ties 2.**
- The second pass won the market, port and salvage camp in every pair, the slums and the megablock at night, and the core and the highway in the vista.
- It lost the neon street in both shots, the core at night, the megablock vista, the slums at dusk and the highway at night.
- The judge's reasons for losing images: large empty squares and open ground, haze over everything beyond about 50 m, props in rows on open ground.
- Its reasons against even the winners: a flat blue-violet palette with dim neon, little visible layering (one image with a highway), text mirrored on container homes, a highway piece floating in fog.

Frame times (static spots at 22:00, mean of the last two reports, host load differing between arms): the core 7.5 → 6.2 ms, the wastes' edge 6.0 → 3.5 ms. The matched runs in [staged generation](#staged-generation-and-the-largest-floor) are the fair comparison: the same p50, p95 and p99 within noise.

### Next

- Fill the open ground: smaller squares and set-backs in the corporate core, denser street dressing (`street_kit_m`), lots on the plazas' edges.
- Night haze and palette: a floor's own mood curve in the client, longer fog distances, brighter neon and more emissive screens (client notes).
- Highways: ramps where decks end and pieces bent through curves; a lone piece by the core square reads as floating.
- Signs seen from behind read mirrored on container homes: make them two-sided or face them to the street.
- Peopling: the seed peoples six settlements; the other 48 stand empty.

## Phased plan

| Phase | What | What it proves | Verification surface |
|---|---|---|---|
| 0 (this change) | The megacity generator at 2048/4096 m in the rules, the floor-law composition, the design | A city-scale floor can be generated deterministically on both sides; the size limits are known | `cargo test -p living-rules`; `verify-generation` with the new seed at 2048 m |
| 1 | Staged generation in `create_floor`; the seed passed at runtime instead of compiled in (*both done on `megacity-1`*); the client's land cache by digest (the client reading `map.params` in look-dev is done: `LIVING_GAME_SEED`) | One module build hosts any floor up to 4–8 km within the fuel budget; a client joins a 4096 m floor in seconds | `verify-generation` (a 4096 m floor), `verify-client` (land row, digests, cache) |
| 2 | Laws as data: the inventory above moved behind law functions with their cadence; `law_card`; `rates_key`; overlay composition with AST merge | One build, several floors with different laws; no per-arm builds for labs | `verify-core` (law scenes per floor), `verify-minds` (the mind reads the floor's laws) |
| 3 | The tower database, soul ids, transit by IDC on one host; memory keyed by `(realm, soul)`; the client's floor switch | A character leaves floor A and arrives on floor B with exactly what should travel, and nothing duplicates or vanishes across crashes | New `verify-transit` skill (create with `create-verification-skill`): scripted tier (two scratch floors and a scratch tower; kill the server between each step and resume), and a player tier through `verify-player` |
| 4 | The second and third floors (steampunk valley, sky archipelago) with their laws | Floors differ in generation, technology and physics without engine forks | `verify-generation`, `verify-core` |
| 5 | Verticality step 2 (levels); population runs per floor against the contract | Multi-level ground works in rules and client; a floor's population limit is known | `verify-core`, `verify-player`, benchmarks under the performance contract |
| 6 (only if 5 says so) | Zones within a floor | A floor's population exceeds one core | Two-zone scratch setup in `verify-transit` |

## Open questions for the user

1. **Floor size.** The 4096 m megacity needs staged generation in the authority. Is 4096 m the floor size to build for, or should first floors be 2048–3072 m (which fit today), with 4096 m+ after phase 1?
2. **One host or several.** IDC works within one server or cluster. Should all floors share one host to start (simplest transit, one identity), or should floors be spread across machines (the dev-box, the Spark) from the start, which needs the relay and an OIDC issuer?
3. **What travels.** *Decided 2026-11-09 (working rule above): identity and mind only; the destination's defaults for the rest.* Earlier question: is the table above right? In particular: do possessions left on a floor stay owned while you are away? Do relations travel? Does know-how work on floors whose laws lack it (proposed: it travels, and fails honestly)?
4. **The tower in the world.** Is there one in-world tower that every gate leads into (a hub floor), or do gates link floors directly, as edges between floors?
5. **Death and floors.** Should a soul's death on any floor be final everywhere (proposed), or can a floor's laws differ here (an underworld floor)?
6. **Which floor second.** The sky archipelago (height as a rule) or the long winter (laws over seasons) as the first floor after the megacity?
7. **Buildings.** May the assets worker add megatower, megablock, shack and ruin presets to `buildings.py` for the megacity's districts?
