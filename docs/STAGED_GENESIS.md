# Staged genesis (design note)

Status: 2026-11-20, dev-box, branch `staged-genesis` (from `origin/main` `a407be01a`). Reviewed by the coordinator and the Spark; the GC's go (2026-11-20), to build after the Spark's revert of status-parts lands. Nothing here is built yet. Designed for main **without** status-parts: its re-land removes its genesis work (filled lazily on first ask) rather than staging it; anything that truly must run per body at genesis becomes one of the steps below, under 50 × 10⁹. Here the island's `init` uses 99.8% of its budget.

**Existing worlds are unaffected.** `init` runs only on a fresh publish (or a clear); a module update of a running world does not run it, and nothing in a made world's tables changes. Only worlds created after this lands take the staged path.

**The GC's decisions** (2026-11-20): populate stays one step (per settlement later, if a seed needs it); the double overlay validation (§1) is fixed first, as its own small merge (`overlay-validate-once`); `join` and `mind_*` before the world is ready are refused with the stable code `world_preparing` (§4).

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

**Targets.** `init` under 15 × 10⁹ for every seed (12.5% of the budget, at least 87% headroom). Every step at most 50 × 10⁹ (about 40%; at least 58% headroom), comfortably inside the Spark guard's 10% floor and leaving room for content growth. `land` is split by `Gen`'s own steps (the island's 72 × 10⁹ into steps under 50); `populate` (25 × 10⁹ on the island, the largest single step) fits now and stays one step (the GC: per settlement later, only if a seed grows past the target). The overlay cut (§1) lands first as `overlay-validate-once`, so the `rules` step here already validates once.

This is the floors' staged path (`floor.rs`, docs/FLOORS.md "Staged generation") made the only path: `INLINE_MAX_M` goes, and `seed::seed`'s inline branch becomes the same steps. The floors' `genesis`, `genesis_timer`, `resume_genesis` and `stop_genesis` stay as they are.

## 3. Scheduling

A **resumable cursor**, as floors have it, not a reducer per step:

- **One reducer, `genesis_step`, on a one-shot schedule** (`ScheduleAt::Time(now)`), which does the next step and schedules the next one in the same transaction. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/): one-shot rows are removed after the reducer runs; scheduling from `init` is the documented pattern (the docs' own `init` inserts a schedule row). A failed step rolls back its own schedule of the next, so the chain stops; `resume_genesis` (admin) carries on, `stop_genesis` stops between steps (both exist).
- **The cursor is the `genesis` row** (durable): which step, and how far within it (chunks, lots, resource rows done). It gains a `phase` column for the step names above.
- **Module memory is a cache, never the truth.** [Reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior": values need not survive between calls. As floors do: intermediate land grids stay in memory only while the cursor says they are this seed's and this far; otherwise generation starts again from its first step. Generation is deterministic, so a restart rebuilds the same land, and rows already written are kept.
- **Back to back**: each step schedules the next at its own `ctx.timestamp` (`ScheduleAt::Time`, "now"), never on an interval, so the chain runs as fast as the scheduler dispatches one-shot rows; the only added time per step is a transaction's commit and the scheduler's dispatch.
- **No interval tick before `done`**: `start_ticking` runs in the last step, as now.

**Wall time to ready.** The GC's bound: staged within a few seconds of today's inline time, since play-test staging, the scene gate and verify launches all wait on it. Today's inline time (publish start to the first tick; main `5bea89b55`, `sg-stdb`, three publishes each; the publish includes the validity check's own run of `init`): see the table in §8. Staged, the validity check runs only the small `init`, which saves about one genesis' worth of wasm time; each step adds a commit and a dispatch (milliseconds), about 15–25 steps on the island. The build reports the staged times against these.

## 4. Readiness

"World ready" = `genesis.done` (public row). One predicate in the authority, `genesis::ready(ctx)`, decides it, so refusing (the GC's choice) or a later queue is one place to change.

**The public `genesis` row** (one row, `id` 0; floors already publish it): `done` (bool), `step` (steps done), `steps` (steps expected so far; grows once a land's wards are known), `phase` (new: `rules`, `land`, `chunks`, `build`, `resources`, `populate`, `done`), `label` (the next step's work, for a progress line), `started_ms`, `updated_ms`, `restarts`. Clients and tools wait on a subscription to it (`SELECT * FROM genesis`), not by polling a reducer.

**The refusal code** (stable, documented, for clients to match): a refused call returns the error string `world_preparing: the world is still being made (step <step> of <steps>: <label>)`. Clients match the prefix `world_preparing`; the rest is for people.

What each consumer sees between `init` and the last step:

- **The tick and housekeeping** do not run (not scheduled until `done`).
- **Clients (players)**: `join` (and the other player reducers) refuse with `world_preparing`; the game client shows a "preparing" state from the `genesis` row and retries `join` when `done` turns true (the laptop's client half, after this branch).
- **The mind service**: `mind_*` reducers refuse with `world_preparing`; the service retries quietly (no failed startup, no error log per refusal), and does no deliberation before ready. It sees no characters until `populate` writes them.
- **`world_guard`**: an unfinished genesis is not orphaned or stalled. The guard arms at publish as now; its lease and inactivity rules count a world whose `genesis.done` is false and whose `updated_ms` advances as alive, and pause or delete it only by the same rules as a made world. Pausing between steps is harmless (no wasm runs between steps), and `world_delete.py`'s rule holds.
- **The owner's launcher, `living/tools/play.py` (the first priority)**: today it publishes, reads the laws back (`check_laws.py`), then starts the minds and the client. It waits for `genesis.done` after publishing and before the read-back and the minds (it already waits this way for floors).
- **The verify harness and every publisher**: `verify.py launch` waits for ready before `doctor`; `doctor` reports "world being made: step i of n (label)" instead of "not ticking". Every tool that publishes and then calls admin reducers or SQL waits through **one shared helper**, `living/tools/genesis_wait.py` (`wait_ready(url, db, token, timeout_s=600) -> genesis row`, raising with the last label on a timeout or a stopped chain), as `world_delete.py` and `law_values` are shared. The publishers today: `verify.py`, verify-core's `record_stdb.py` and `updates.py`, `battle_viewers.py`, `bench.py`, `board/board.py`, `duel.py`, `gate.py`, `lab.py`, `latency.py`, `look_cost.py` (and `tick_cost.py` on it), `perception_bench.py`, `play.py`, `soak.py`, `store.py`, `trials.py` (the Spark's), `verify_mechanics.py`, `verify_steering.py`.
- **The merge gate's scenes** wait through the harness, with its timeout.

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
- **Verification skills**: the build runs `maintain-verification-skill` on verify-generation (its staged cases become the seeded path's, and verify-core's world setup goes through it), and updates verify-client's and verify-player's refusal maps for `world_preparing`.

## 7. Reporting fuel for the Spark's guard

Agreed with the Spark (2026-11-20; its `genesis-fuel-guard` consumes this format). A step cannot read its own fuel (the module has no fuel API), and the server's `reducer_wasmtime_fuel_used{reducer="genesis_step"}` is one counter for all steps. So the interface is a tool, which reads the counter the same way for `init` and for each step:

- **A step-by-step mode** for measurement only: a module built with `LIVING_GENESIS_STEPPING=1` has `init` mark the `genesis` row as stepping, so each step schedules nothing; the tool calls `resume_genesis` once per step and reads the counter before and after. Production modules chain unattended.
- **The output** (`living/tools/genesis_fuel.py --seed S [--wasm W]`, one JSON object per seed):

```json
{"seed": "island", "commit": "<sha>", "budget": 120000000000,
 "init_fuel": 11000000000, "init_runs": 2,
 "steps": [{"phase": "rules", "label": "…", "fuel": 2000000000, "reducer": "genesis_step"}],
 "largest_step_share": 0.42}
```

`init_fuel` is per run (the counter divided by `init_runs`, 2 on a fresh publish: the validity check's and the real one); `budget` is 2.14.1's `FunctionBudget::DEFAULT_BUDGET`, recorded in the file; `largest_step_share` is the largest step's `fuel / budget`.

- **Thresholds** (the Spark's guard): fail above 90% of the budget for `init` and for every step (each scheduled step has its own budget); warn above 50%.

## 8. Wall time to ready, inline today

Publish start to the first tick, main `5bea89b55` (without status-parts), the worker's own `sg-stdb` (v2.14.1), three fresh publishes each, 2026-11-20 (1-minute load 3.7 at the start; `.local/sg/wall-inline.jsonl`, `.local/sg/tools/genesis_wall.py`):

| Seed | Publish returns (s) | Ready: first tick (s) |
|---|---:|---:|
| island (and the player world, the same seed) | 15.95 / 16.17 / 16.56 | 16.43 / 16.58 / 17.01 |
| Cullet | 16.04 / 16.26 / 16.47 | 16.38 / 16.56 / 16.96 |
| default world | 5.73 / 5.81 / 5.89 | 6.00 / 6.10 / 6.31 |

A publish runs `init` twice today (the validity check, then the real one), so about half of the island's and Cullet's time is the check's own genesis. Expected when staged (an estimate from §1's measured wasm time, to be measured by the build): the check runs only the small `init` (about 1 s of wasm), the steps run genesis once (island about 6.7 s of wasm, Cullet about 7 s after the overlay cut), plus a commit and a dispatch per step. So staged should be several seconds *faster* than inline on the island and Cullet, and about the same on the default world.

The staged times are reported by the build against these.
