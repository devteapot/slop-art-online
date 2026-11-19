# Staged genesis (design note)

Status: 2026-11-20, dev-box, branch `staged-genesis` (from `origin/main` `a407be01a`). A design note for the coordinator, then the Spark, then the GC. Nothing here is built. Designed for main **without** status-parts (the Spark is reverting it; its re-land removes its genesis work rather than staging it), where the island's `init` uses 99.8% of its budget.

## Why

SpacetimeDB 2.14.1 gives every reducer call, `init` included, 120 × 10⁹ wasmtime fuel (`FunctionBudget::DEFAULT_BUDGET`, `crates/client-api-messages/src/energy.rs`: "roughly 1 minute of runtime", one fuel unit per wasm instruction; standalone cannot raise it). A call that runs out fails with "reducer ran out of energy", and a failed `init` refuses the publish ("Failure prevents publishing or clearing", [lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle)). The island's `init` uses 119.79 × 10⁹, 0.21 × 10⁹ short of the limit: status-parts' ~1 × 10⁹ was enough to break `skirmish` and `combat` on main (2026-11-19).

A fresh publish also runs `init` **twice**: once on an in-memory database to check the module's validity (`Host::try_init_in_memory_to_check`, `crates/core/src/host/host_controller.rs`: "some validity checks … require a fully instantiated database"), then for real. Today every island publish therefore spends about 2 × 6.7 s of wasm on genesis. The check starts no background work ("Validation never starts background work"), so staged steps run only on the real database.

## 1. What `init` costs today, by phase

Method: the same module built with a compile-time stop after each phase (a scratch patch, `LIVING_INIT_STOP`, never pushed), each published fresh on the worker's own server (`sg-stdb`, v2.14.1); fuel per `init` from the server's `reducer_wasmtime_fuel_used{reducer="init"}` divided by the number of `init` calls (`spacetime_reducer_plus_query_duration_sec_count`, two per publish). Fuel is deterministic for a module and a seed; differences between builds of the same tree are about ±0.1 × 10⁹ (code layout). Main `5bea89b55`.

| Phase (where in the code) | Island | Cullet | World (default) |
|---|---:|---:|---:|
| world and clock rows | 0.00 | 0.00 | 0.00 |
| compile the shipped script (`Scripts::new`) | 0.94 | 0.90 | 0.91 |
| validate it (`Scripts::validate`) | 8.79 | 8.80 | 8.77 |
| codes, cards, script row, cover law, instincts | 0.92 | 1.01 | 0.98 |
| seed check (`floor::check`: the laws overlay compiled and validated, rules, plans, looks) | 1.00 | **25.73** | 0.80 |
| seed rules (`floor::begin`: day, `install_source` of the overlay, `law_override`, cover) | 0.97 | **26.82** | 0.87 |
| land generation (`island::generate` / `map::generate`) | **72.04** | 19.92 | 1.02 |
| terrain chunks | 0.34 | 0.08 | 0.03 |
| world row and `island::build` (lots, structures) | 0.33 | 0.29 | ~0 |
| resources (`spawn_resources`) | **9.11** | 1.10 | 0.69 |
| populate (stores, people, animals, settlements' life) | **25.35** | 7.67 | 4.23 |
| **total** (share of 120 × 10⁹) | **119.79 (99.8%)** | **92.33 (76.9%)** | **18.21 (15.2%)** |

Units: 10⁹ fuel. The player world (`combat`) is the island seed. Evidence: `.local/sg/phases.jsonl`, `.local/sg/tools/build-phases.sh`, `.local/bv/tools/init_fuel.py`.

Two findings independent of staging:

- **Cullet validates its laws overlay twice**, about 26 × 10⁹ each: `floor::check` compiles and validates the overlay, and `floor::begin` → `install_source` compiles and validates it again. Validating once (keep the checked `Scripts` and install it without a second validation) saves about 26 × 10⁹ on any seed with an overlay.
- **The island's land generation is 72 × 10⁹ in one call** (60% of a budget). It is already steppable: floors run `living_rules::land::Gen` one step per call ("each under half a budget at 8192 m").

## 2. Step boundaries: what stays in `init`, what becomes a step

`init` keeps only what must exist before any other call and is small for every seed:

- the world and clock rows, the `genesis` row (step 0) and the first step's schedule;
- the shipped script compiled, validated and installed, the codes and cards (about 11 × 10⁹, 9% of a budget): every reducer reads the script, and a script that fails validation should still refuse the publish, as now;
- parsing the seed (cheap) and refusing a malformed one, so a bad seed still fails the publish.

Everything after that is a step, run in order, on every seeded world (one path for all seeds; the small default world takes a few short steps):

| Step | Work | Island | Cullet | World |
|---|---|---:|---:|---:|
| `rules` | seed check and rules, the overlay validated **once** | ~2 | ~27 (was ~52) | ~2 |
| `land` × n | land generation in `Gen` steps (or `map::generate` / `realm::generate` for non-land seeds) | 72 in n steps | 20 | 1 |
| `chunks` × n | terrain chunks in batches (as floors: 16,384 a step) | 0.3 | 0.1 | 0.03 |
| `build` | world row, lots and structures (`island::build`, batched as floors' `lots`) | 0.3 | 0.3 | ~0 |
| `resources` × n | resources by rows of tiles (as floors: 1,024 rows a step) | 9.1 | 1.1 | 0.7 |
| `populate` | stores, people, animals, settlements' life; then `start_ticking` | 25.4 | 7.7 | 4.2 |

**Targets.** `init` under 15 × 10⁹ for every seed (12.5% of the budget, at least 87% headroom). Every step at most 50 × 10⁹ (about 40%; at least 58% headroom), comfortably inside the Spark guard's 10% floor and leaving room for content growth. `land` is split by `Gen`'s own steps (the island's 72 × 10⁹ into steps under 50); `populate` (25 × 10⁹ on the island, the largest single step) fits now and is the first to split (per settlement) if a seed grows.

This is the floors' staged path (`floor.rs`, docs/FLOORS.md "Staged generation") made the only path: `INLINE_MAX_M` goes, and `seed::seed`'s inline branch becomes the same steps. The floors' `genesis`, `genesis_timer`, `resume_genesis` and `stop_genesis` stay as they are.

## 3. Scheduling

A **resumable cursor**, as floors have it, not a reducer per step:

- **One reducer, `genesis_step`, on a one-shot schedule** (`ScheduleAt::Time(now)`), which does the next step and schedules the next one in the same transaction. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/): one-shot rows are removed after the reducer runs; scheduling from `init` is the documented pattern (the docs' own `init` inserts a schedule row). A failed step rolls back its own schedule of the next, so the chain stops; `resume_genesis` (admin) carries on, `stop_genesis` stops between steps (both exist).
- **The cursor is the `genesis` row** (durable): which step, and how far within it (chunks, lots, resource rows done). It gains a `phase` column for the step names above.
- **Module memory is a cache, never the truth.** [Reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior": values need not survive between calls. As floors do: intermediate land grids stay in memory only while the cursor says they are this seed's and this far; otherwise generation starts again from its first step. Generation is deterministic, so a restart rebuilds the same land, and rows already written are kept.
- **No interval tick before `done`**: `start_ticking` runs in the last step, as now.

## 4. Readiness

"World ready" = `genesis.done` (public row). Until then:

- **The tick and housekeeping do not run** (not scheduled until `done`).
- **Players**: `join` is refused with "the world is still being made (step i of n)"; the game client shows the `genesis` row's label and progress (a client subscribing `genesis` already can).
- **The mind service** connects as before and subscribes; it sees no characters until `populate` writes them and the tick starts. Its reducers (`mind_*`) need the world ticking anyway; they are refused before `done` with the same message, so a mind that connects early waits rather than acting on a half-made world.
- **The verify harness**: `verify.py launch` publishes, arms `world_guard` (unchanged: it arms at publish and pauses or deletes an orphaned world either way), then **waits for `genesis.done`** (with a timeout and the label in the error) before `doctor`; `doctor` reports a world still being made instead of "not ticking". `play.py` already waits this way. The scene gate inherits it through the harness.
- **`world_guard`**: unchanged. A world it pauses mid-genesis has no tick to pause; its `set_paused` is harmless, and `world_delete.py`'s rule (pause, read back, delete) holds: a staged world between steps is not running wasm.

## 5. Consistency

Genesis output must be identical to today's for the same seed. Two things make it so:

- **Deterministic draws**: generation already draws from per-stage streams (`Creating::start(seed, STEP_…)`), so splitting a stage across calls does not change its draws as long as each stage keeps its own stream (the floors' `Gen` already resumes deterministically).
- **One clock for content**: today every row created in `init` carries the `init` call's time (`now`). Steps run later, so every step stamps its rows with the genesis start time (`genesis.started_ms`), not the step's own `ctx.timestamp`. Only the `genesis` row's own `updated_ms` and the scheduling rows show real step times.

**The check**: a tool (`living/tools/genesis_hash.py`) publishes a seed twice, once on main (inline) and once on the branch (staged), waits for `done`, reads every table as the owner (sorted by primary key; `world.epoch_ms`, `genesis.*` and the timer tables left out, and every `*_ms` column taken relative to `world.epoch_ms`), and compares a hash per table. Acceptance: identical hashes for the island, Cullet, plan-test and the default world.

## 6. Tests and scene coverage

- **Fuel** (the Spark's guard, below): `init` and every step per seed, within the targets in §2.
- **Hashes** (§5): staged against inline for each seed above.
- **Restart**: a step whose instance lost its memory (a module update mid-genesis, or a forced new instance) restarts generation and ends on the same hashes (verify-generation already covers stop and resume on floors; it gains the seeded path).
- **Readiness**: `join` and a `mind_*` call refused before `done` and accepted after; the harness waits; `doctor` reports progress.
- **Scenes**: the scene gate's island cases (`skirmish`, `combat`), the default-world cases (`tick`, `sight`, `senses`, `refusal`, `cues`, `motion_tables`), the minds' cases, verify-generation's staged cases and a Cullet look scene, all on the staged path.
- **Unit**: the step table's order and each step's cursor advance (pure functions over the `genesis` row).

## 7. Reporting fuel for the Spark's guard

A step cannot read its own fuel (the module has no fuel API), and the server's `reducer_wasmtime_fuel_used{reducer="genesis_step"}` is one counter for all steps. So the interface is a tool, read the same way for `init` and for every step:

- **A step-by-step mode**: the admin's `set_genesis_stepping(true)` (stored in the `genesis` row) makes each step schedule nothing; `resume_genesis` then runs exactly one more step. The tool publishes the seed, sets stepping right after publish (the first step is scheduled by `init` for "now"; `init` itself sets stepping when the module is built with `LIVING_GENESIS_STEPPING=1`, a measurement build, so no race), and for each step reads the fuel counter before and after one `resume_genesis`, with the step's `phase` and label from the `genesis` row.
- **The output** (`living/tools/genesis_fuel.py --seed S`, one JSON object per seed): `{"seed": S, "module": sha, "budget": 120e9, "init": {"fuel": f, "share": f/budget}, "steps": [{"step": i, "phase": p, "label": l, "fuel": f, "share": s}], "max_step_share": m, "total_fuel": t}`.
- **The guard's rule** (the Spark's): fail when `init.share` or `max_step_share` is above 0.9 (10% headroom), per seed; warn above 0.5.
- **Production worlds** run the chain unattended, as now; stepping is only for measurement.

The Spark's status-parts re-land fits the same shape: whatever genesis work it keeps is a step (or part of `populate`) and shows in the same report, and work it removes from genesis disappears from it.

## Open questions for the GC

- `populate` as one step (25 × 10⁹ on the island today) or split per settlement now.
- The overlay double validation (§1): fix it in this work (a pure cut, about 26 × 10⁹ on Cullet), or separately.
- Whether `join` and `mind_*` should be refused before `done` (proposed) or queue.
