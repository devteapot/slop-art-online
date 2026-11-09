# Island authority: hosting the km-scale land

Started 2026-11-09. This note records how the living authority hosts the generic island of [first world](FIRST_WORLD.md) (`living_rules::land`, seed 7, 2048 m) as a world. It covers the design decisions, the documentation they rest on, what was built and what was measured. The lab worlds (`realm.rs`, 512 m) keep their seeds and behaviour.

**Status.** Implemented on scratch databases (`verify-*`) on the dev-box with SpacetimeDB 2.14.1. No lab or reference world was touched. Since 2026-11-09 the game client connects to an island world and draws it ([connected client](#connected-client-2026-11-09)). The authority was not changed for that.

## SpacetimeDB documentation consulted (2026-11-09)

Pinned version: `spacetimedb = "=2.14.1"` and `spacetimedb-sdk = "=2.14.1"` in `living/Cargo.toml`; server image `clockworklabs/spacetime:v2.14.1`. The live docs' version selector reads 2.0.0, so quotes were checked against the docs source and code at tag `v2.14.1`.

| Page | What it says | What follows here |
|---|---|---|
| [Tables](https://spacetimedb.com/docs/tables/) | "organize data by access pattern, not by the entity it describes"; "Separate data you read at different times or frequencies"; all data is held in memory. | Static land data (`land`, `settlement`, `lot`) is kept apart from hot rows (`body`, `vitals`). Terrain keeps its own chunk table. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/) | "Break large tables into smaller, more focused tables"; batch work in one reducer call; "Be mindful of unbounded table growth". | Heights, roads and models are not stored per tile: they are derived. Lots are about 375 rows. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | Indexes cost memory and slow writes. Primary keys index automatically. | `lot.chunk` has a btree index because clients subscribe by chunk. `land` and `settlement` are tiny and have only their primary keys. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | Group subscriptions with the same lifetime. "subscribe to the new set before unsubscribing from the old one". Avoid overlapping queries. | Clients subscribe to a moving window of chunks, not to whole tables. |
| [SQL reference](https://spacetimedb.com/docs/reference/sql) | Subscription predicates support `AND`, `OR` and comparisons; "Arithmetic expressions are not supported". The 2.14.1 parser has no `IN` (`crates/sql-parser/src/parser/mod.rs:240-291`). Joins need indexes on both join columns. | A window is expressed as `id >= a AND id <= b` per row of chunks (chunk ids are `(cy << 16) \| cx`, so one row of chunks is one id range), or `chunk = c` per chunk. |
| [Views](https://spacetimedb.com/docs/functions/views/) | Views read only through indexed lookups. They can take arguments (Rust supported; no floats; no primary key; no `WHERE` on top). Anonymous views are shared by subscribers with the same arguments. Per-sender views are computed per subscriber. | Table subscriptions do this job: a chunk-window view would be a new instance for every window position and player, so it would share less. A view becomes the tool once perception filtering is enforced on the authority. |
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) | Rows live only in their transaction and are broadcast. Joins and views cannot read them. | Not needed for static land data. |
| [Reducers](https://spacetimedb.com/docs/functions/reducers/) and [lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle) | Init runs once at publish or clear, and failure prevents publishing. Module-level state that persists across calls is "undefined behavior". | Generation runs inside `init` (measured below). The authority's existing module caches already rely on instances being reused; that is not guaranteed (see [risks](#open-risks)). |

Verified in the `v2.14.1` source, not stated in the docs:
- A reducer has a fuel budget of `PER_EXECUTION_SEC * 60` (`crates/client-api-messages/src/energy.rs:133-142`, commented "Roughly 1 minute of runtime"). Init runs through the same path and fails with "init reducer ran out of energy" (`crates/core/src/host/host_controller.rs:325`). Standalone uses `NullEnergyMonitor`, which hands every call that default budget.
- Long WASM calls are only logged ("Wasm has been running for …", `crates/core/src/host/wasmtime/wasmtime_module.rs:358-366`).
- No explicit linear-memory cap was found beyond WASM32's 4 GiB.

Assumptions not verified: how many wall-clock seconds the fuel budget allows when host calls dominate; per-client limits on subscription count or initial volume.

## Decisions

### A seed kind for the island

`"map": { "kind": "land", "size": 2048, "params": { … } }` generates `living_rules::land::generate(seed, size, params)`. `params` is an optional partial `LandParams` (serde defaults). [`living/seeds/island.json`](../living/seeds/island.json) is seed 7 at 2048 m with:
- a walled town;
- three villages;
- the giants' settlement and the small folk's;
- 24 deer and 6 wolves;
- `"rules": {"minds": false}`.

`realm` and `valley` seeds are unchanged.

Settlement entries reuse the town schema (`towns`, `villages`) with a new optional `site`: `town`, `village`, `giants` or `small_folk`. It defaults to `town` in `towns` and `village` in `villages`. The k-th entry of a kind takes the k-th settlement of that kind; a settlement without an entry stands empty but keeps its lots and structures. `bands` are not placed on a land world: their homestead search scans the whole map against every food source, which does not scale to 4.2M tiles. The module logs a warning instead.

### Where generation runs: inside `init`

At 2048 m, generation runs in the WASM module in 1.89 s; natively on the Mac it takes 0.64 s. The whole init takes 3.1 s, well within the fuel budget. Generating in the module keeps a single source of truth: the published module and its seed fully determine the world, and no import format or offline step is needed. A 3 km world would take about 2.5 times as long, still well inside the budget, but not measured.

### Storage per data path

| Data | Stored as | Rows (seed 7, 2048 m) | Bytes (rows + index keys) | Written | Read by |
|---|---|---|---|---|---|
| Terrain tiles, with building footprints as `Wall` | `terrain_chunk` (unchanged: 16 × 16 bytes, id `(cy << 16) \| cx`) | 16,384 | 5.37 MB + 66 kB | init; a road, clearing, bridge or wall built (one row each) | the module's map cache (once per instance), clients by chunk window |
| Ground height, water level, roads, plazas, walls' geometry, crossings | **derived**: clients run `living_rules::land::generate` with the `land` row's seed, size and params | 0 | 0 | — | clients (presentation) |
| The land's identity and digests | `land` (one row): seed, size, params JSON, tiles/heights/layout digests, arrival point | 1 | < 200 B | init | clients once |
| Settlements | `settlement`: kind, style, centre, radius, folk scale, community | 6 | ~600 B | init | clients once |
| Lots | `lot`: kind, centre, size, yaw, floor, model file, door point, door structure, chunk (btree) | 375 | 69 kB | init | clients by chunk (`lot.chunk`) |
| Buildings' function (shelter, inn, hall, workshop, storage) | `structure` at the lot's door (existing table; owner set as households move in) | 238 of 361 | 38 kB (all structures) | init; ownership | rules (shelter warmth, sleep, homes), clients by chunk |
| Town gates | `gate` + `structure` per tile across each wall opening | 109 | — | init; open/shut | rules (shut gates block), clients |
| Street ornaments, stairs and retaining walls (`Land::props`) | **derived**, like heights; blocking ones as `Wall` tiles; see [ornaments and terraces](#ornaments-terraces-and-styled-towns-2026-11-09) | 0 (1,302 props derived) | 0 | — | clients (presentation) |
| Resources | `resource_node` (unchanged per-area density) | 68,175 | 7.66 MB + 0.82 MB | init; gathering | rules by chunk, clients by chunk |

**Heights are derived, not stored.** The rules do not use height yet (movement is flat), so the authority does not keep the `Land` after init: it drops its 9 MB, and only the hosted tiles and the planned rows survive. FIRST_WORLD.md flagged the risk of regenerating on clients: `f32` transcendental functions can differ between the native and WASM math libraries.
- **Fix:** `land.rs` and `settle.rs` now call `exp`, `tanh`, `powf`, `hypot`, `sin`, `cos`, `sin_cos` and `atan2` through [`living_rules::det`](../living/rules/src/det.rs), which wraps the pure-Rust `libm` crate (0.2.16, already in the lock file). Arithmetic, `sqrt`, rounding and `powi` with a constant exponent are exact IEEE operations on both targets.
- **Check:** the authority stores three digests ([`living_rules::host::digests`](../living/rules/src/host.rs)):
  - the hosted tiles;
  - `height` and `water_level` on an 8 m lattice (66,049 points);
  - the layout: settlements, lots, models and road profiles.
- **Measured:** for seed 7 at 2048 m, the WASM authority (rustc 1.97.1), native x86_64 Linux (rustc 1.97.1 release and debug, and 1.99.1 release) and native aarch64 Linux (DGX Spark, rustc 1.99.1 release) produce identical digests:
  - with the buildings table at `dc34fdf`: tiles `265e05fc88bb8ce5`, heights `e3119943ec9f7c8f`, layout `0c6735e09f26b036`;
  - with the table at `977a14c` and the plaza-blocking fix: tiles `9d1884118850c39c`, heights `f860069dd92e1341`, layout `f59dcf9649678035`. The WASM authority, x86_64 and aarch64 all agree. Before the fix, aarch64 read tiles `f1e4205218880a45` with the same heights and layout.

  The digests change with the buildings table and with the blocking rule, as they should: lots and footprints come from them. macOS on Apple Silicon (aarch64 like the Spark, but its own system libm, which `det` no longer calls) is not run, because that machine had to stay idle. A run of the generator without `det` was not made, so it is not shown that the old code actually diverged.
- **Client rule:** a client compares its digests with the `land` row before trusting derived heights. On a mismatch it should report it and still walk by the authority's tiles, which stay the truth for movement.

When height becomes a rule (slope speed, line of sight, falling), the authority will evaluate the same `Land`. That costs 9 MB of retained module memory and about 150 ns per `height()` call inside settlements, and it is deterministic by the same digest.

**Roads are derived.** Their gameplay part is already in the tiles: `Road` tiles are faster to walk. Their geometry is presentation.

**Lots are rows.** They are where gameplay attaches to buildings:
- the door point, and the structure standing there;
- the footprint that blocks;
- later: who owns the building, whether its door is open, and damage.

### Buildings as authority entities

- **Collision and blocking:** every lot whose model blocks has its footprint turned into `Wall` tiles in the hosted map ([`host::hosted_map`](../living/rules/src/host.rs)). That covers houses, townhouses, the inn, the hall, the chapel, workshops, barns, towers, wells and market stalls; lamps, gardens and fields stay open.
  - The footprint is the lot shrunk by its style's margin.
  - Water under a footprint is left alone, and so are roads, except under wells and market stalls. Those stand on the paved plaza by design; the first generation run found 12 of them not blocking until this exception was made.
  - Measured on seed 7 at 2048 m with the buildings table at `977a14c`: 24,364 tiles blocked. Only 19 walkable tiles are cut off (enclosed yards); nothing is placed there. All 249 building doors and every plaza stay reachable (`host::tests::hosted_island_keeps_doors_reachable`). With the table at `dc34fdf` the figures were 24,445 and 18.
  - Blocking goes through tiles, so pathfinding, steering, `line_clear` and perception need no new code.
- **Doors:** `host::door(lot)` is the point half a metre in front of the lot, snapped to the nearest walkable tile. A `structure` stands there:
  - `house` for houses and townhouses;
  - `inn`;
  - `hall` for halls and the chapel;
  - `workshop`;
  - `storage` for barns.

  The rules' shelter warmth (2.5 m), restful sleep and homes already work from structures, so a resident's home is the house at their door. `lot.structure` links the two. Households claim the house at their door (`seed::house`); empty houses stay unowned for newcomers.
- **Gates:** each opening in the town wall becomes one `gate` row and one `structure` per tile across it (109 gate tiles in all), kept by the town's community. A shut gate blocks through the existing `blocked` set.
- **Not modelled:** interiors, entering buildings, opening doors, and the giants' and small folk's body sizes (below).

### Residents without minds

`rules.minds = false` (a new `rules` flag, compiled in like `cry_prompts_carers`) gives seeded people, animals and their newborns the database identity as controller with `ai = false`, the path the benchmark crowds already use. They live on their instinct graphs and occupation repertoires:
- they write no experiences and no deliberation requests;
- the mind service is not needed;
- no model is called.

The default stays `true`, so lab seeds are unchanged.

Households come from each settlement's `occupations`, through the existing `town`/`drawn_households` machinery:
- **Households:** 2–4 adults plus children.
- **Homes:** the home lots nearest the plaza. Each household's house is the house structure at its door.
- **Plaza:** the hearth, the stores and the ledger sign.
- **Food:** a berry bush in every garden and three along every field.
- **Community:** one per settlement, keeping the gates.

Backgrounds name the folk (`folk`, `body_scale`, `settlement`). **Bodies are not sized:** the rules carry no body size yet ([first world, open question 6](FIRST_WORLD.md#open-questions)). The giants and small folk are adult-sized `person` bodies living in their own settlements, and the client draws them at `settlement.scale`.

### Data paths, readers and growth

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| World creation (`init`) | the seed | every table above | — | — | once | — |
| First map read in a module instance | all 16,384 `terrain_chunk` rows, all `gate` rows | — | `terrain_chunk.id` | — | once per instance (module start or update) | 4 MiB of map in module memory |
| A tile built (road, clearing, bridge, wall) | that chunk row | that chunk row | `terrain_chunk.id` | subscribers of that chunk | rare | none |
| The next transaction after a tile edit | only the edited chunk rows | — | `terrain_chunk.id` | — | after each edit | none |
| A gate opened or shut | that gate row, then all `gate` rows (109) | that gate row | `gate.id` | gate subscribers | rare | none |
| Path search (`Map::path`) | the cached map | — | — | — | every throttled re-plan | at most `max_expansions × 8` entries per call, freed after |
| A client's window | `terrain_chunk`, `lot`, `body`, `resource_node`, `structure` by chunk | — | `id` / `chunk` btrees | that client | on crossing a chunk border | none |
| The tick | due rows only (unchanged) | bodies, activities, vitals | `next_ms`, `ends_ms`, `slot` | body/vitals/activity subscribers | 60 Hz | population-bound |

**Two whole-map costs from FIRST_WORLD.md are fixed:**
- **`Map::path` allocations.** Each call allocated and filled two `u32` arrays the size of the map: 32 MiB per call at 2048 m and 2 MiB at 512 m. The search now keeps cost and predecessor in a hash map sized by its expansion budget (`max_expansions = 6,000`, so at most about 48k entries). The results are identical: missing entries read as the arrays' initial values, and the open list and tie-breaking are unchanged.
- **Whole-cache rebuild after a tile edit.** `common::set_tile` used to drop the cached map, so the next read rebuilt it from every chunk row. It now patches the cached map in place and records the chunk with the transaction's timestamp. The next transaction re-reads just those rows, because the editing transaction may have rolled back. Opening or shutting a gate re-reads only the gate rows.

**What remains whole-map:**
- The first map read after a module (re)start reads every chunk row; measured at 8.6 ms below.
- World creation scans every tile once to place resources. It now shuffles 4-byte tile indices instead of 8-byte pairs (16 MiB instead of 32 MiB at 2048 m), with the same RNG draws, so a lab world's resources come out the same as before for the same RNG stream.

No new whole-World scan was added to a routine action.

### Ornaments, terraces and styled towns (2026-11-09)

The planner now dresses settlements with props, terraces sloping sites, and lays out a steampunk and a cyberpunk town of their own ([first world](FIRST_WORLD.md#ornaments-terraces-and-styled-towns-2026-11-09)). What the authority keeps of them:

**Props are derived, not rows.** Seed 7 at 2048 m has 1,302 props: 507 fence and gate sections, 230 kerbs, 202 retaining walls, 95 flower boxes, 53 barrels, 46 benches, 44 trees and the rest. They are fixed at world creation, and no rule reads them except to block movement.
- **Documentation consulted (2026-11-09).** The live pages show version 2.0.0; the pin is 2.14.1, as above. No storage changes, so no versioned source was needed.
  - [Tables](https://spacetimedb.com/docs/tables/): "organize data by access pattern, not by the entity it describes", and "SpacetimeDB keeps hot data in memory for extremely low latency and high throughput access, keeps colder data on disk, and automatically persists all data".
  - [Table performance](https://spacetimedb.com/docs/tables/performance/): "Be mindful of unbounded table growth"; splitting tables "Allows more targeted subscriptions".
  - [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): "SpacetimeDB sends all matching rows immediately", and keep subscriptions small.
  - None of these pages gives a row-count limit or a per-row cost, so the decision rests on the access pattern, not on a measured cost of the rows.
- **Why derived:**
  - Props are static presentation. Clients already regenerate the land from the `land` row, so a `prop` table would only resend what they compute, through one more chunk subscription per client.
  - Lots stay rows because gameplay attaches to them: doors, structures and, later, owners and damage.
  - A prop that gains gameplay (a bench to sit on, a cart that moves, a market stall's stock) moves to a table keyed by chunk, like `lot`.
- **Check:** the layout digest now covers every prop (kind, centre, size, front, floor, height, model file), after the lots. A client compares it as before.
- **Blocking:** fountains, market crosses, carts, kiosks and food stalls block every walkable tile under their footprint in [`host::hosted_map`](../living/rules/src/host.rs) (`host::prop_tiles`). The planner keeps them off carriageways, doors and the way out of doors. The tiles digest covers them.

**Terraces are ground and tiles.**
- Their levels are part of `Land::height`, so the heights digest covers them.
- A drop that no one can step up (more than 0.8 m between neighbouring tiles) is `Wall` in the land's own tiles. Stair tiles are `Road`. Sealed slivers of under 150 tiles are closed, like the land's small pockets.
- Movement goes by tiles, so the authority needs no new code: terraces connect only through streets, ramps and stairs.

**Styled towns are settlements of kind `town`** whose `settlement.style` names their models (`steampunk`, `cyberpunk`).
- Their site has its own id (`living_rules::land::Site::id`: `steampunk_town`, `cyberpunk_town`). `island::match_seed` matches seed entries by that id, so `"site": "steampunk_town"` in [`island.json`](../living/seeds/island.json) peoples Kettlebridge and `"cyberpunk_town"` peoples Lanternquay.
- `SiteKind` gains no variant: client code matches it exhaustively. Newcomers still arrive at the first (walled) town.

## Measurements

All measurements ran on the dev-box: 32-thread AMD x86_64, Fedora, rootless podman, SpacetimeDB 2.14.1 in a scratch container `slop-game-stdb`, seed `island` (seed 7, 2048 m).
- **First pass:** on `dc34fdf` plus this change, before the plaza-blocking fix, on database `verify-gen-island-1`: world creation, the first window, the soak and memory.
- **Subscriptions and the map cache:** `verify-client-island-1`, same code.
- **Second pass:** on `977a14c` (its regenerated `buildings.json`) plus this change with the fix, on `verify-island-20261109-023510`. It covers the WASM digests and a final pair of windows.

**World creation** (module log spans):

| Step | Time |
|---|---|
| `init.land.generate` | 1.89 s |
| `init.land.host` (hosted map, digests, plans) | 43 ms |
| `init` total, log timestamps from invoke to "Database initialized" | 3.13 s |
| `reducer_wasm_time_usec{reducer="init"}` | 6.26 s (this metric is larger than the logged span; the cause is not established) |

Second pass: `init.land.generate` 1.88 s, `init.land.host` 42 ms, and about 3.2 s for the whole `init` (the generate span's start, inferred from its length, to "Database initialized"). The authority logged digests tiles `9d1884118850c39c`, heights `f860069dd92e1341` and layout `f59dcf9649678035`, identical to native x86_64 and aarch64 at that commit. That run had 372 lots, 24,477 blocked tiles, 19 cut off, 361 structures, 109 gate tiles, 225 characters and 67,973 resource nodes.

**Population:** 223 characters (193 people, 24 deer, 6 wolves) and 6 settlements. All seeded settlements were placed: the town, 3 villages, the giants' and the small folk's.

**Tick, first 60 s window** (`bench.py`, minute 3 of the world's life):
- 59.3 ticks/s;
- p50 1.20 ms, p95 1.90 ms, p99 2.27 ms, max 3.77 ms;
- 0 of 3,614 ticks over 16.7 ms;
- 290 evaluations/s, 171 steering updates/s, 74 completions/s;
- 0 experiences/s and 0 deliberation requests/s;
- a subscriber to the whole `body` table received 236 row updates/s (112 kB/s as JSON).

**30-minute soak** (same database, no subscribers, no mind service). A 60 s window ran every 5 minutes, from world minute 3 to minute 30; a deer was born in that time.

| Window (UTC) | Characters | Ticks/s | p50 | p95 | p99 | Max | Over 16.7 ms | Evaluations/s |
|---|---|---|---|---|---|---|---|---|
| 01:33 | 223 | 60.4 | 1.26 | 2.00 | 2.42 | 4.52 | 0 of 3,612 | 299 |
| 01:38 | 223 | 59.4 | 0.65 | 1.46 | 2.52 | 3.45 | 0 of 3,612 | 250 |
| 01:44 | 223 | 59.4 | 1.18 | 2.02 | 2.40 | 3.90 | 0 of 3,612 | 307 |
| 01:49 | 224 | 60.4 | 0.74 | 1.59 | 3.59 | 7.33 | 0 of 3,613 | 251 |
| 01:54 | 224 | 59.4 | 1.55 | 2.67 | 3.37 | 5.80 | 0 of 3,612 | 315 |
| 01:59 | 224 | 59.4 | 1.56 | 2.76 | 3.74 | 5.23 | 0 of 3,614 | 308 |

Tick times are in ms. Every character stayed alive. The soak covers only the windows: 6 of 26 minutes were profiled. The dev-box was otherwise idle apart from builds limited to 4 nice'd jobs.

Growth over the 26 minutes:
- `resource_node` grew from 68,532 to 71,299 rows (residents planting berry bushes; about 6,400 an hour if it continues, and nothing removes them).
- `chronicle` grew from 220 to 408 rows.
- `experience` and `deliberation` stayed at 0.
- `inventory` fell from 205 to 137 stacks, as food was eaten.
- WASM memory stayed at 79,101,952 bytes.
- The container's RSS went from 689 to 715 MB.

Second pass, minutes 1–3 of a fresh world (195 people and 30 animals): two 60 s windows had p50 1.08 and 1.10 ms, p95 1.89 and 1.92, p99 2.33 and 2.51, max 4.23 and 4.53, and 0 of 3,614 and 0 of 3,613 ticks over budget.

This is the immediate gate's population (216 or more) for its 30 minutes, without its observer, subscriber or player load and without minds. It does not establish the gate.

**Memory:** `spacetime_worker_wasm_memory_bytes` was 79 MB after init. WASM linear memory does not shrink, so this mostly holds the generation peak. The container's RSS (the whole service, this one database) was 687 MB.

**Subscriptions** (fresh `verify-client-island-1`, 231 characters with one joined player). Each query ran as one real SDK subscription through the verify-client probe. Bytes are the server's `spacetime_num_bytes_sent_to_clients_total` delta for the database (binary protocol); rows were received in the client cache.

| Query | Initial rows | Bytes | Live events |
|---|---|---|---|
| `terrain_chunk`, whole table | 16,384 | 4,325,376 (4.3 MB) | 0 in 3 s |
| `terrain_chunk`, 22 × 22 chunk window around the arrival point (≈ ±170 m, 22 `id` ranges joined by `OR`) | 484 | 127,776 | 0 in 3 s |
| `lot`, 6 × 6 chunks round the town plaza (6 `chunk` ranges) | 48 | 5,662 | 0 |
| `structure`, same window | 33 | 1,355 | 0 |
| `resource_node`, same window | 78 | 4,644 | 4 in 3 s |
| `body`, same window, 30 s | 44 | 185,498 (6.2 kB/s) | 1,241 |
| `body`, whole table, 30 s | 231 | 1,151,498 (38 kB/s) | 7,484 |
| `land` | 1 | 51 | 0 |
| `settlement` | 6 | 259 | 0 |

A client that subscribes to a terrain window instead of the whole table receives 3% of the bytes at join, and its body window costs about a sixth of the whole `body` table at this population.

**Map cache:** the first full rebuild after world creation took 8.6 ms (`map.rebuild` span, 16,384 rows). On that world a player built a wall (`human_act build wall`): its chunk row changed from tile 0 to 7, and no second `map.rebuild` was logged. The edit patched the cached map instead of rebuilding it. An in-place republish of the same module with data kept (`launch --keep-data`) left 231 characters and 375 lots in place and the world ticking. That module was identical, so the republish does not prove that a different module updates cleanly.

**Lab worlds unchanged** (`realm-4`, the default seed, 512 m). Origin/main's module and this change's were each published fresh as `verify-realm-base` and `verify-realm-new` and measured in interleaved 60 s windows after 30 s of settling:
- **Terrain:** the sha256 of all 1,024 `terrain_chunk` rows is identical (`ff98ec4e…`).
- **Counts:** characters 264 vs 265, structures 81 vs 85, resource nodes 6,139 vs 6,124; gates (14), communities (7) and memberships (163) are equal. These counts come from the RNG-driven parts of the seed and from 90 s of life.
- **`init`:** 0.45 s in both.
- **`map.rebuild`:** 0.51 ms.

| Arm | People + animals | p50 | p95 | p99 | Max | Over 16.7 ms |
|---|---|---|---|---|---|---|
| base, window 1 | 182 + 82 | 1.48 | 2.26 | 2.66 | 3.64 | 0 |
| new, window 1 | 182 + 82 | 1.49 | 2.24 | 2.72 | 3.99 | 0 |
| base, window 2 | 180 + 82 | 1.46 | 2.24 | 2.66 | 3.58 | 0 |
| new, window 2 | 186 + 82 | 1.20 | 2.00 | 2.45 | 4.27 | 0 |

## Verification

Free tiers only, on `verify-*` scratch databases, through the shared harness (`verify.py launch|doctor|sql|player|call|cleanup`) with the dev-box shim described below. No mind service ran, and no model was called.

| Surface | What was driven | Result | Evidence (`.local/living/verify/` on the dev-box worktree) |
|---|---|---|---|
| Generation, first pass (`dc34fdf`) | `generation.py`, all features: realm ×2, valley, authored-test, aske-coast, stage3-village, island, authored compile, guards | island failed 2 of 56 checks: 12 plaza stalls and wells did not block, and `body_scale` read 0.3499999940395355. Both were fixed. Everything else passed. | `generation-20261109-021430*` |
| Generation, second pass (`977a14c`) | the same | 19 of 20 results pass. The island passes 56 of 56, and repeatability passes. `realm` failed "Saltmere memberships": a drawn grandparent, seeded at the end of their lifespan, died of old age 1.2 s after creation, and the death cleanup removed their membership. The seed code is unchanged from origin/main, so this is a flaky check, recorded in the skill's validation record. | `generation-20261109-023510*` |
| Core | `cargo_checks.py` (rules 72, authority 10, mind 47, viewer sync 3), scenes `tick`, `needs`, `seize`, `verify_mechanics.py` (23 of 23, including road, wall and gate built, gate shut and opened), `verify_steering.py` (5 of 5) | pass. The infant, lifecycle and wildlife scenes (30+ minutes each) were not run. | `core-20261109-021430*` |
| Client | `run.py` on the default seed: base subscriptions, privacy, views, the reducer permission matrix, reconnect. Then island chunk-window queries through `drive.py --query` | 13 PASS and 2 XFAIL (the known anonymous `experience` and `thought` leaks), with cleanup confirmed by SQL 404 | `client-20261109-021430`, `client-island-1/subs.txt` |
| Player (island) | `player join`, two `act build wall` calls, `move` | the newcomer arrived at `land.arrive_*` (512.5, 174.5). The first wall turned tile (514, 174) from 0 to 7. The second was refused ("cannot build a wall there"), because that tile was already blocked. | `client-island-1/actions.log` |
| Lab worlds | origin/main vs this change on `realm-4` | terrain identical, ticks equivalent (table above) | `realm-compare/` |
| Project check | `just living-check` on both bases | exit 0 | dev-box `~/island-logs/check-*.log`, `p2-check.log` |
| Bindings | `just living_compose=~/island-shim/compose living-generate` | three new tables; regenerating again at `977a14c` changed nothing | `living/bindings/src/generated/` |

**Ornaments, terraces and styled towns (2026-11-09).** `generation.py` ran on `c5a2c00` plus this change, as `generation-orn-20261109-035123` on the dev-box:
- **Result:** 19 of 20 results pass: every seed, authored compilation, guards, repeatability, and cleanup with SQL 404 for every database. The island passes 65 of 66 checks: 8 settlement rows, each seeded settlement on its site, including `steampunk_town` and `cyberpunk_town`; 546 lots; door structures; wall tiles under every blocking lot; folk backgrounds.
- **The one failure is the known flake:** "Reedmoor memberships". Hanmo, a seeded grandparent of that unchanged village, died of old age right after creation, as Saltmere's did in the second pass above.
- **World:** 443 structures, 109 gate tiles, 287 characters and 67,694 resource nodes.
- **Digests:** the WASM authority's `land` row reads tiles `c19cc98e8f1471f0`, heights `16412fd044a2b0b0` and layout `d45f735150add4ba`. Native x86_64 (`host::tests::print_digests`, rustc 1.97.1) prints the same.
- **Not measured:** `init` time and memory, and aarch64.
- **Defects the driver found, since fixed:**
  - the clock tower in the paved square did not block: `hosted_map` now blocks road tiles under any lot standing in its plaza;
  - its "stands on a site" check compared the seed's `site` with the row's `kind`: it now accepts `<style>_<kind>`.
- **Harness:** port 3300 was held by another agent's container (`slop-live-stdb`, with that worktree mounted at `/wasm`), so this run used a container of its own: `slop-orn-stdb` (2.14.1, port 3310, the run's own worktree at `/wasm`), behind a `docker` name shim. The harness's hard-coded 3300 was patched to 3310 in that worktree only, not committed. The container, its volume and the worktree (with the run's evidence under `.local/`) were removed afterwards; the results, island checks and cleanup records went with the task's report.

**Dev-box harness shim.** On the dev-box the name `sao-living_spacetimedb_1` belongs to another checkout's stopped 2.10.1 container, which had to stay untouched. A `docker` wrapper on `PATH` (`~/island-shim/docker`) mapped that name to the scratch container `slop-game-stdb`: image `v2.14.1`, its own volume, `--security-opt label=disable` for SELinux, and the worktree's `/wasm` mount. A `compose` wrapper ran the bindings recipe's one-off `compose run` as a `docker run` of the same image. The harness, the scripts and every reducer call were otherwise unchanged.

## What the client needs next

*Ornaments (2026-11-09):* the look-dev client draws `Land::props` from the regenerated land, in connected mode too, since they are not rows. A settlement's assets come from its style (`living_rules::settle::env_of`), and a lot's or prop's kind folder from its model file (`settle::asset_kind`). That is how the steampunk and cyberpunk towns find `steampunk_city` and `cyberpunk_city`.

The list as written before the client was built. Items 1 to 3 and 5 are done ([connected client](#connected-client-2026-11-09)). Item 4 uses the settlement round each character's home. Item 6 does not apply, because the client predicts no movement. To connect to an island world, the game client needed these changes:
1. **Read the `land` row** and, when present, generate `living_rules::land::generate(seed, size, params)` instead of its hard-coded seed 7. Compute `living_rules::host::hosted_map` and `digests`, then compare all three digests with the row. On a mismatch, log it and keep walking by `terrain_chunk`.
2. **Stop subscribing to `terrain_chunk` whole.** `net.rs` subscribes `SELECT * FROM terrain_chunk` (5.4 MB and 16,384 rows on the island). Use the chunk window, either as one range per chunk row (`SELECT * FROM terrain_chunk WHERE id >= a AND id <= b`) or as `id = c` per chunk. A window is only needed for edits; initial tiles can come from the regenerated land once the tiles digest matches.
3. **Subscribe `lot` by chunk** alongside `body`, `resource_node` and `structure` (`SELECT * FROM lot WHERE chunk = c`). Draw `lot.model` at `(x, floor_m, y)` with `yaw`, instead of planning lots itself. `settlement` (6 rows) and `land` (1 row) can be subscribed whole.
4. **Draw folk at size:** a character's `background` names `folk` and `body_scale`; `settlement.scale` gives the same per settlement.
5. **Spawn and camera:** `join` places a newcomer at `land.arrive_x/arrive_y`, outside the town's first gate.
6. **Collision prediction:** `living_rules::host::footprint_tiles` gives the same blocked tiles the authority uses, if the client predicts movement.

## Connected client (2026-11-09)

`living/game` connects to a land world and draws it through the island renderer. The code is in `net.rs` (subscriptions) and `live.rs` (land, buildings, characters and the headless script), with `island.rs` drawing hosted lots and `ui/live.rs` placing nameplates and bubbles on the island's ground. Presentation only: the authority was not changed, and the client moves nothing itself.

**Data paths:**

| Path | Rows | Recipients | When |
|---|---|---|---|
| `world`, `land`, `settlement`, whole | 1 + 1 + 6 | this client | at connection |
| `character WHERE controller = :sender` (indexed) | my characters, dead ones included (the death screen) | this client | at connection |
| my `body`, `vitals`, `experience`, `place` by id | mine | this client | while my character lives |
| near window: `body` ±5 chunks; `character` joined to those bodies (both primary keys); `terrain_chunk` ±3 chunks | about 70 bodies and characters, and 49 chunks at the town square | this client | re-centred after 2 chunks |
| far window: `lot` ±11 chunks | about 200 lots | this client | re-centred after 5 chunks |

A window is one id range per row of chunks joined by `OR`, since 2.14.1 has no `IN`. A new window is subscribed before the old one is dropped. `:sender` and the join with `OR`ed ranges on the joined table were checked against the 2.14.1 server before use. The [SQL reference](https://spacetimedb.com/docs/reference/sql) allows two-table joins that return one table, with indexes on both join columns. The [subscription guide](https://spacetimedb.com/docs/clients/subscriptions/) says to group subscriptions by lifetime and to subscribe before unsubscribing. That is why static lots have their own, longer-lived window: re-sending them with every near move cost about 130 kB a move.

**Land:**
- The client regenerates the `Land` from the row on a worker thread, in 1.4–1.5 s (release, dev-box), and computes the hosted map and the three digests. All of them matched the authority's in every run: tiles `9d1884118850c39c`, heights `f860069dd92e1341`, layout `f59dcf9649678035`.
- On a mismatch the client warns and draws anyway. Movement never depends on the client's copy.
- The `terrain_chunk` window is compared with the hosted tiles, and edits are counted in the log. Edits are not drawn yet.

**Measured on the dev-box** (Radeon 8060S, Vulkan, 1600×900 headless, uncapped). Database `verify-client-live-1`: seed `island`, about 230 characters (residents without minds, 24 deer, 6 wolves, plus the test players), 60 Hz authority. One game client was connected and nothing else, with no observer and no mind service. Other agents' work kept the load average at 8–16, so the frame times are indicative.

| | Frame time (2 s means) | Notes |
|---|---|---|
| Arrival, outside the walls | mean 8.4 ms, median 7.6 | 15–40 characters drawn |
| In the town, walking the streets (146 s run) | mean 12.5 ms, median 12.3, highest 15.3 | 70–80 characters drawn; worst single frame 57 ms |
| Standing in the square, two later runs | 10.8 and 12.6 ms | with and without the atmosphere: no difference beyond load noise |
| Look-dev at the same spot, same hour | 6.6 ms with its 24 people, 9.0 ms with 66 | the client's own planner crowd |
| Chunk streaming | single frames of 150–250 ms | when a new 64 m chunk's models load, as in look-dev |

Connected play costs about 1.5–3.5 ms more than look-dev with a similar crowd. That is not attributed: the HUD only runs when connected, the crowds are not identical, and the load varied.

| Subscription bytes (server metric, by kind) | |
|---|---|
| 146 s walk from arrival through the town | 296 kB subscribe, 230 kB unsubscribe, 1.59 MB updates (about 14.5 kB/s) |
| `body` window at the square, 72 bodies | 9.7–10.4 kB/s, about 68 updates/s of about 150 B (the whole row with its path) |
| character join | 33 B/s |
| a near-window move | about 44 kB subscribe and 44 kB unsubscribe (with the ±5 terrain window) |
| `spacetime_active_queries` | 12, flat through the walk |

**Not drawn yet:** resource nodes and structures (berry bushes, hearths, stores), gates open or shut, and terrain edits. Animals are the procedural placeholder creatures, without limb motion. Speech from mindless residents does not exist (below).

**What the server must provide next, for town life and combat:**
- **Resident speech and reactions.** Residents with `rules.minds = false` never speak and write no `experience` rows, so they neither hear a player nor answer. The only speech in town is players'. Town life needs instinct-level talk: greetings, barks and answers from rules or skills, without model calls.
- **A slimmer moving-body stream.** Every steering update sends the whole `body` row, path included, at about 150 B. That is about 10 kB/s for 72 bodies, and it scales with the crowd. At the town's update rate, 200 characters in view would be about 28 kB/s per client; a battle steers more often, so more. A narrower row or table for what clients draw (position, velocity, heading, segment time) would cut it.
- **Perception-scoped subscriptions.** Every window table is public, and the windows are not permission boundaries. A view with arguments (2.13+) or per-sender filtering on the authority is needed before the client shows only what the character perceives.
- **Body size as a rule.** Giants and small folk are drawn at their settlement's scale, but the rules move and collide them as adults.
- **Combat state per character for others:** health, what they are doing, attack and skill events with timings. Today only my own `vitals` are readable, and the HUD's skill bar shows "Not on the server yet".
- **Gait speeds that match the clips.** The rules' walk is 2.6–2.7 m/s and their run 4.1. The walk clip was authored at 1.4 m/s, so walking plays it at about 1.9×. Either clips are authored for the rules' speeds, or the rules get a slower ambling gait.
- **Masonry for newcomers**, if a newcomer should be able to wall anything: `build wall` is refused without the know-how, as designed.

## Open risks

- **Long paths:** `Map::path` keeps its 6,000-expansion budget. Across a 2 km island, a route around a lake or over a ford 400 m away can exhaust it, so a click-to-move to a far point fails ("no path there"). Hierarchical routing (road graph, then tiles) is needed before long travel.
- **Module caches:** the map cache and the other caches rely on module instances being reused between transactions, which the docs call undefined behaviour. A fresh instance rebuilds the map from all 16,384 chunk rows (8.6 ms measured). The patch-and-revalidate scheme is correct for rollbacks in a single instance, but not if two instances ever run reducers concurrently.
- **Generation in `init` grows with size:** 1.9 s at 2048 m. Island edits after creation are ordinary tile writes. A persistent game world updates the module in place and never regenerates (`--keep-data`), so a changed generator changes only new worlds. Its digests then differ from an old world's row, which is the intended signal.
- **Gates are per tile:** shutting a gate means shutting every tile across it (109 gate tiles for the town's openings). A mind or player shutting "the gate" shuts one tile.
- **Resources:** 68k nodes at the lab's per-area density (7.7 MB). Per-chunk reads are unchanged, but world creation's per-kind scans in `settlement_resources` would be slow if a land seed listed promised `resources`.
- **Privacy:** every table read here is public. Spatial subscriptions are not permission boundaries ([game brief, core work 1](GAME_BRIEF.md#core-work-the-game-needs-engine-independent)).
- **Body size** is not a rule. The giants' houses and streets are built for 3× bodies that the rules still treat as adults.
- **The libm switch** changed some generated values, which can shift a few tiles relative to the earlier native output. All `land::` and `settle::` tests still pass. FIRST_WORLD.md's measured tables come from before the switch.
