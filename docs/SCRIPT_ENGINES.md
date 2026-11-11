# Script engines for skills and laws

**Status:** research spike, 2026-11-09, branch `spike-scripts`; its recommended boundary fixes landed on branch `rhai-1` the same day ([what changed](#what-changed-on-rhai-1)). Bench crate: [`living/tools/script_bench/`](../living/tools/script_bench/) (standalone, not a workspace member). Raw results: [`results/2026-11-09/`](../living/tools/script_bench/results/2026-11-09/) (the spike) and [`results/2026-11-09-rhai-1/`](../living/tools/script_bench/results/2026-11-09-rhai-1/) (`rhai-1`).

**Question (2026-11-09).** We chose Rhai to script skills and world rules. Is it the best option inside the SpacetimeDB authority module, and what does it cost?

## Answer

- **Rhai costs 28.5 µs per `rates(a)` call and 57.7 µs per strike (check + done) inside the module.** That is 310k and 620k WASM instructions of energy, and 300× and 190× the same laws written in Rust in the module. A constant lookup such as `combat_cooldown("strike")` costs 1.5 µs, 370× native. A real SpacetimeDB 2.14.1 reducer confirms these within 3%.
- **About 45% of Rhai's cost is not the script.** It is `to_map` building a fresh 60-field context map for every call. Giving the same script only the fields a law reads halves `rates` (12.9 µs) with identical outputs.
- **No other engine changes the picture.** Across the engines that build, the best interpreter is 3× faster than Rhai as embedded: piccolo at 9.4 µs for `rates`, Rune at 11.7 µs. Every engine still runs these laws at about 100× native or more. Each alternative has a blocker or a large cost, set out below. Lua (PUC 5.4 or Luau through mlua) cannot be built for the module at all.
- **Recommendation: stay on Rhai for authoring and fix the boundary.**
  - Read constants and tables once per install.
  - Build a lean context per law.
  - Move per-tick numeric laws into Rust primitives that Rhai parameterizes.

  This is a hybrid by cadence, not a language switch. Tighten `max_operations` from 20,000 to about 2,000: the heaviest law measured uses 258.

## What changed on rhai-1

Branch `rhai-1` from `9ea831f`, 2026-11-09. It keeps Rhai 1.27.0, now with the `internals` feature, and the same rules. One law changed form: `rates` (item 3), with identical outputs. Code: [script.rs](../living/rules/src/script.rs), [fields.rs](../living/rules/src/script/fields.rs), [context.rs](../living/rules/src/script/context.rs), [check.rs](../living/rules/src/script/check.rs).

**Measured on the dev-box:**

- **Harness:** the same as the spike (`sb-host`, wasmtime 39.0.1 in SpacetimeDB 2.14.1's reducer config, fuel on, pinned to core 6), with base `9ea831f` and `rhai-1` run back to back.
- **Base arm:** got the two bench cases added here (`rates-law`, `perceived`); its `rates-law` is its `rates`.
- **Equivalence:** every output on both arms is byte-identical to the native floor's, on all fixtures.

| Call, in the module | base µs p50 | base fuel | rhai-1 µs p50 | rhai-1 fuel |
|---|---:|---:|---:|---:|
| `rates`, as the authority calls it | 28.6 | 309,451 | **0.44** | **7,031** |
| `rates`, the law itself, every call (`rates-law`) | 28.6 | 309,453 | 11.5 | 127,454 |
| strike: `strike_check` + `strike_done` | 52.6 | 578,264 | **25.3** | **247,041** |
| a number by name: `combat_cooldown("strike")` | 1.49 | 20,656 | **0.065** | **1,694** |
| `perceived_of` (unchanged; the authority caches it) | 5.59 | 61,121 | 5.51 | 59,088 |
| compile (`Scripts::new`) | 5.3 ms | 52.5 M | 7.2 ms | 75.3 M |

The bench module grew from 4.00 to 4.15 MB, and the island authority module from 8.28 to 8.53 MB.

### 1. Constants read once

`num_of(f, name)` answers from a table that is filled when the script compiles, for every name the engine asks:

| Laws | Names |
|---|---|
| `combat_cooldown`, `combat_recover`, `combat_cost` | the combat shapes and catalog skills |
| `lunge`, `max_hp`, `yield_ms`, `carry_limit`, `carried_spoil`, `remains_s`, `<skill>_dist`, `<skill>_speed` | the creature kinds |
| `spoil_rate` | the items |
| `regrow` | the resources |
| `trap_every_s`, `trap_holds` | `meat` |

Any other name is asked once and kept. A Rhai function of one string cannot read anything else, so the table answers exactly as the script does (`numbers_by_name_are_tables_read_once`). Item lists work the same way: `items_of(f, name)` (since 2026-11-11, for `carcass(kind)`, the items a body leaves in its remains) calls a one-argument law that returns a map of items to whole amounts once per name and keeps the list. Block arc and hold time were already in the combat shape.

A lookup went from 1.49 µs to 65 ns, and from 20,656 to 1,694 instructions. It is two hash lookups by string; a typed accessor could make it a few ns, which at a few lookups per move start is not worth an API.

### 2. Lean per-law contexts

When the script compiles, [fields.rs](../living/rules/src/script/fields.rs) walks each function's AST with `AST::walk`. It finds what the function reads of each parameter, by these rules:

- **Field reads.** `.name` and `["name"]` chains are reads of that field.
- **Helpers.** A call passes on what the callee reads. `inv(a, "cloak")` reads `a.actor.inv["cloak"]`; `inv(a, a.item)` reads the whole inventory.
- **Names.** A `let` bound once to part of the context carries its reads back to the context.
- **Everything else counts as reading the whole value:** a built-in call, a comparison, a return, storing, iterating, a computed key, a method call, or a name bound twice. A call that sees its caller's variables (`f!()`) gives up on the whole script.

Per law, the result is a plan of top-level, actor, target and routine fields, and the inventory keys read ([context.rs](../living/rules/src/script/context.rs)). A call builds only those fields. The skill factor and the genes are computed only when read.

`lean_contexts_answer_as_the_whole_context_does` compares every law's answer under its plan with the answer under the whole map, over 152,208 calls: every law and skill function the engine calls with a context, 6 bodies × 28 targets × 6 items. All are identical.

What the hot laws read:

- **`rates`:** `actor.kind`, `.activity`, `.stage`, `.near_fire`, `.near_shelter`, `actor.inv[cloak]`, `night`, `season`, `raining`.
- **`strike_check`:** 22 fields: 10 of the actor's 27, 10 of the target's 19, `night` and `skill`. `strike_done` reads 4: `actor.inv[spear]`, `actor.strength`, `actor.factor`, `target.inv[armor]`.

A law that reads a field the engine does not provide is refused at install, naming it: "rates reads `a.actor.hungr`, which the engine does not provide (a.actor.* is id, kind, hp, hunger, …)". Without an install, the cached compile tolerates it, and the field reads `()` as it always has.

### 3. Per-tick number laws into Rust

`rates(a)` was the only candidate that runs per character at tick cadence. Its cache key is reset at every action start, blow and energy cost, so in a fight it is recomputed at combat cadence. Its continuous inputs are the body's hunger, energy and genes, which differ for every body, so every recompute needed a call.

Now the script keeps every named condition and returns the state's rates with the numbers the engine needs to finish them:

- the hunger and energy thresholds for starving, healing and running out of energy, and their health changes;
- the share of healing (age);
- the genes that divide tiring and multiply healing;
- exposure (wet, cold), added last.

[`NeedLaw::rates`](../living/rules/src/script.rs) applies them in the same order as the old script, in `f64`.

The law no longer reads a body's levels or genes. Its answer depends only on its plan's fields, so it is kept per state, by the bytes of those fields (at most 4,096 states, then the memo starts over). Every body in the same state shares one call.

Floors keep working: `one_build_two_floors_two_sets_of_laws` still passes. A floor that overrides `cold(a)` still changes the rates through `cold_hp`, and `base_rates(a)` overlays still work on the returned map. A script whose `rates` returns finished rates (`hunger`, `energy`, `hp`), such as one a world installed before this change, is used as before.

Proof: `need_rates_match_the_whole_script_computation` compares the old script's computation with the new one bit for bit over 24,576 states. They cover three kinds, four stages, four activities, hunger and energy on both sides of each threshold, fire, shelter, cloak, night, rain, winter and two gene sets. The bench's `rates` and `rates-law` dumps equal the native floor's on both arms.

The combat path stays a script decision at move start and completion: the check weighs yields, daring and costs. Its arithmetic (`dmg × strength × factor × armor`) is a handful of operations; the cost was the context, which item 2 removed.

### 4. Nightfall and rain

Measured; no code changed. Nightfall flips every character's `rate_key` at once, but no recompute happens until that character's own evaluation. Evaluations run in 1/60 slots (`authority/src/tick.rs`), so a character evaluated once a second recomputes within that second, and a fighter within 1/15 s. The spike's 6.2 ms was the sum over the 216-character gate, not one tick; it said so, and left the spread unmeasured.

On the island at rest, each arm on a fresh world, the authority logged a `needs.rates` span around each recompute (the facts and the law) and the tick span. [nightfall.py](../living/tools/script_bench/results/2026-11-09-rhai-1/nightfall.py) reports them by second around 20:00:

| | base | rhai-1 |
|---|---:|---:|
| characters (people, animals) | 261, 34 | 255, 28 |
| recomputes per second before nightfall | 112 | 98 |
| recomputes in the first second of night | 343 | 319 |
| their cost in that second | 35.0 ms | 10.4 ms |
| tick p50 the second before / the first second of night | 1.57 / 1.83 ms | 1.23 / 1.29 ms |
| slowest tick in the first 5 s of night / in the 25 s before | 3.5 / 3.8 ms | 3.4 / 3.3 ms |

The extra work spreads over that second's 60 ticks: about 0.6 ms each on base and 0.17 ms on rhai-1. No tick spiked, so there is nothing to stagger. Making light and weather inputs that do not key the cache would also save little now. With item 3, what remains of a recompute is mostly gathering the facts (row reads, about 15–30 µs), not the script.

Rain from `set_weather` flips the same key bit and goes through the same slots; it was not measured separately. Nightfall runs with `--battle 200` came out like the ones at rest: the fight was over by 20:00, 6.5 minutes in, so they show nothing more.

### 5. Limits

The limits were set from the install samples (`measure_limits`): each function's maximum operations, and the smallest limit under which all samples still pass.

| Limit | Before | Used by the rules | Now |
|---|---:|---:|---:|
| operations per call | 20,000 | 864 (`skill_io`); laws: 635 (`teach_check`), 386 (`take_check`), 384 (`gather_check`), 224 (`strike_check`), 177 (`rates`), 88 (`strike_done`), 56 (`perceived_of`), 4 (a constant) | **2,000** |
| call depth | 16 | 3 | 8 (a floor overlay adds one) |
| expression depth, global / in functions | 32 / 24 | 19 / 19 | 40 / 40 |
| string size | 4,096 | 570 | 2,048 |
| array size | 256 | 26 | 64 |
| map size | 256 | 30 (`laws()` has 29 keys) | 64 |
| source | 64 KiB | 57 KB | **256 KiB** |

- A call that runs into the operation limit now costs about 1.2 M instructions (about 0.1 ms) instead of 11–15 M.
- The string limit bounds what a script builds, not what it is handed. A reworked routine reaches `rework_check` as up to 32,000 characters, and the samples include one.
- Compile time and memory grow about linearly with the source, so the larger source cap costs only on install.

### 6. Install checks

`install_script` (and `init`) calls `Scripts::validate` before writing anything. It calls the laws on these samples:

- `laws()`, `skill_bar()`, each `_combat()` and `_shows()`;
- each number by name over its names;
- `skill_io` over the catalog skills (since `rules-2`, 2026-11-10, each skill's `<skill>_spec()` instead, read at compile; a skill with rules and no spec is refused, and hooks and `record_text` are probed too: [world rules](WORLD_RULES.md));
- `rates`, `body_state` and `move_speed` over six bodies in five kinds of weather and warmth;
- every skill the script has rules for: six bodies (adult, elder, child, infant, wolf, deer) against 28 targets (none, a place, oneself, people, animals, the dead, each resource and structure), and every item and technique for skills that take one. On each, the check runs, then the duration, effects, missile and hit when it passes, as the engine calls them;
- `perceived_of` over 16 observer/target cases.

In all, 20,979 samples. A law depends only on the fields it reads, so samples that agree on those fields are one call, and each is made once: 6,681 calls. A call that fails is refused with the function named, as is a wrong return shape, an unknown effect, a check that is not a reason, a number by name that is not a number, a context field the engine does not provide, or a call past a limit. For example: "install refused: `zap_done` failed for a person (adult, hunger 40, energy 80): …".

The calls run on a second engine with the same limits that counts operations. The module log gets each function's maximum ("install_script: 6681 calls over 201 functions; most operations: skill_io 864, teach_check 635, …"), and the `install.validate` span gets the time.

In the island authority module the checks take 212–215 ms (6,681 calls), and compiling takes 8–13 ms. Before samples were deduplicated they took 298–321 ms. An install therefore holds the world's reducers for about 13 ticks. That is acceptable for an admin action; if laws are ever edited in play, prune the samples further.

A world that installed a script before this change is not re-validated on a module update. Its laws run under the new limits, and a law past 2,000 operations would fail each call. Reinstall to see the refusal (verify-core `mechanics.md`).

### 7. Fuel budgets

The gate builds the Rhai bench module, runs it under wasmtime in SpacetimeDB's config with fuel on, and fails when a law's fuel per call exceeds [budgets.json](../living/tools/script_bench/budgets.json) ([gate.py](../living/tools/script_bench/gate.py)). Since `tool-8` it is the `script-gate` step of `just living-check` (stamped, [tooling](TOOLING.md#the-check)); `just living-script-gate` runs that step alone, and [gate.sh](../living/tools/script_bench/gate.sh) runs it by hand, keeping the evidence. Fuel counts WASM instructions, so it does not depend on the machine. It did depend on the build until `tool-8`: Rhai's hashing keys were drawn at random when `ahash` was compiled, and they moved a law's fuel by up to 29%. The bench now fixes them and measures under eight fixed sets ([living core](LIVING_CORE.md), "Fuel budgets"). Since `det-1` the rules fix them for every engine of the game too, and the gate judges the game's own set ([living core](LIVING_CORE.md#one-hashing-seed)). The table below is the history of the budgets, measured before that.

| Law | Measured | Budget |
|---|---:|---:|
| `rates` | 7,031 | 9,000 |
| `rates-law` | 127,454 | 160,000 |
| strike | 247,041 | 310,000 |
| cooldown | 1,694 | 2,200 |
| `perceived` | 59,088 | 75,000 |
| `hook` (added on `rules-2`: `on_give` over a giver's agreement, demand and regard; [world rules](WORLD_RULES.md#costs)) | 446,967 | 560,000 |

It is a bench gate, not a rules test. Measuring fuel needs the module and wasmtime, which a `cargo test` of the rules crate does not build.

### In the authority

**Setup:**

- **Arms:** island seed modules of base and `rhai-1`, each with the same `needs.rates` span added to settle_needs. That span times each recompute: the facts and the law.
- **Server:** a private 2.14.1 container on the dev-box. The two arms ran alternately (A B B A), each on a fresh world, 20 s of settling, then 60 s profiled ([bench.py](../living/tools/bench.py)).
- **Skirmish:** the same runs with `--battle 200`.
- **Machine:** load average 2.2–4.2 from other work.
- **Coverage:** profiling logs every span, and the log read covers the last 45–55 s of each window (2,700–3,300 tick samples).
- **Raw reports:** [ticks/](../living/tools/script_bench/results/2026-11-09-rhai-1/ticks/).

| Island, 60 s each | base run 1 | base run 2 | rhai-1 run 1 | rhai-1 run 2 |
|---|---:|---:|---:|---:|
| **at rest** (255–268 people, 33–34 animals) | | | | |
| tick p50 / p99 / max, ms | 1.52 / 2.80 / 3.96 | 1.26 / 2.46 / 3.46 | 1.24 / 2.31 / 3.35 | 1.19 / 2.18 / 2.98 |
| tick work, ms per s | 83.6 | 69.8 | 67.7 | 64.6 |
| rate recomputes per s | 73.5 | 71.8 | 71.4 | 72.2 |
| one recompute, p50 | 92 µs | 99 µs | 30 µs | 30 µs |
| recomputes, ms per s | 8.3 | 8.2 | 2.4 | 2.3 |
| **200-character skirmish** (340–359 people at the end) | | | | |
| tick p50 / p99 / max, ms | 2.73 / 5.39 / 6.90 | 2.85 / 5.83 / 7.99 | 2.66 / 5.45 / 7.99 | 2.43 / 4.64 / 7.91 |
| tick work, ms per s | 127.5 | 133.6 | 120.9 | 109.5 |
| `tick.combat`, ms per s | 51.8 | 54.1 | 50.6 | 46.5 |
| rate recomputes per s | 141.7 | 141.5 | 152.0 | 151.5 |
| one recompute, p50 | 63 µs | 65 µs | 17 µs | 15 µs |
| recomputes, ms per s | 9.5 | 10.0 | 2.9 | 2.5 |
| blows that landed | 187 | 226 | 242 | 218 |

- **Rate recomputes:** what the change targets drops 3–4× in both workloads, by about 6–7 ms of tick work per second. A fight recomputes rates twice as often as rest, because every move start, blow and energy cost resets the key.
- **Ticks:** p50 and tick work fall in both. In the skirmish the drop exceeds the recompute savings; part is the strike path (item 2), and part is run-to-run variation. The base arm's two rest runs alone differ by 14 ms/s of tick work.
- **Not established:** no tick exceeded 16.7 ms in any run. These runs do not establish performance acceptance at the 216-character gate (30 minutes) or beyond.

## What was measured

### Engines

| Engine | Version | How it runs the laws |
|---|---|---|
| Rhai (`rhai`) | 1.27.0, `std` + `no_time` | living-rules' own `Scripts` over the real `living/scripts/skills.rhai`: same `engine()` settings, AST compiled once. This is exactly the authority's call path. |
| Rhai, lean context (`rhai-lean`) | same | Same engine settings and same script, called with only the fields each law reads (diagnostic). |
| Rhai, map only (`rhai-map-only`) | same | A copy of `to_map` alone, built and dropped per script call (diagnostic: the context's share). |
| Rune (`rune`) | 0.14.2 | The laws ported to Rune (`scripts/laws.rn`), compiled once to a Unit; context is a Rune object shaped like Rhai's map. |
| wasmi (`wasmi`, `wasmi-fuel`) | 2.0.0 | The laws in Rust (`port.rs`) compiled to a 31 KB wasm32 guest, run by wasmi inside the module. Each call encodes the full context into guest memory and decodes the result. `wasmi-fuel` adds wasmi's own per-call fuel limit. |
| piccolo (`piccolo`) | 0.3.3 | Pure-Rust Lua; the laws in Lua (`scripts/laws.lua`); context is a Lua table. |
| Koto (`koto`) | 0.16.1 | Pure-Rust scripting language designed for Rust hosts; the laws in Koto (`scripts/laws.koto`). Picked as the optional engine because it is the most actively developed embeddable language of this kind besides Rhai and Rune. |
| mlua (`mlua`) | 0.12.2, vendored Lua 5.4 | Same `laws.lua`. Native only: it does not build for the module (see [Lua](#lua)). |
| Native (`native`) | — | `port.rs` in the module, reading `SkillCtx` directly: the floor. |

### Laws

All engines run the same three laws, ported line for line from `skills.rhai`. They take the same typed input (`SkillCtx`) and return the same typed output.

- **(a) `rates(a)`**: need rates for an actor, returned as `Rates`.
- **(b) the combat path**: `strike_check(a)`, then `strike_done(a)` when the check passes, returning a refusal or `Vec<Effect>`. This includes `attack_check`, `dares`, `winded`, `armor`, `spent`.
- **(c) `combat_cooldown(skill)`**: a constant lookup by name. It shows per-call overhead.

One call is what the authority pays: typed facts in, engine value built, law run, result decoded to typed values. For Rhai this is `Scripts::rates`, `Scripts::check` + `Scripts::done` and `Scripts::num_of`.

Fixtures (`bench/src/fixtures.rs`) are deterministic and realistic:

- 64 actors for `rates` and 64 strikes.
- Each actor has a full gene set: 4 body genes, a knack per skilled catalog skill and 8 traits. Each also has practice, know-how, a pack of 2–6 items, and senses and hurt state.
- The mix covers species, stages, night, rain, season and activity.
- 80% of strikes come from fit adults, so the full path runs.
- Calls cycle through all fixtures.

### Harness

Each engine is in its own `wasm32-unknown-unknown` bench module, built with the authority's release profile. The modules are run by `sb-host` under **wasmtime 39.0.1, configured as SpacetimeDB 2.14.1 configures its reducer engine**. This was checked in the source at tag `v2.14.1`:

- `Cargo.toml` pins `wasmtime = "39"` (lock 39.0.1) with the features `addr2line, async, cache, cranelift, demangle, parallel-compilation, runtime, std`. Without `gc`, the wasm exception-handling proposal cannot be enabled.
- `crates/core/src/host/wasmtime/mod.rs` `wasmtime_config` sets Cranelift `OptLevel::Speed`, `consume_fuel(true)`, `epoch_interruption(true)` and `wasm_backtrace_details(Enable)`. Reducers use the sync engine. A 10 ms epoch ticker is wired to a deadline callback that only logs and continues.
- `wasmtime_module.rs` refills fuel to `FunctionBudget::DEFAULT_BUDGET` (120 × 10⁹) before each call. Energy used is fuel consumed (`finish_opcall`). One fuel unit is one WASM instruction (`client-api-messages/src/energy.rs`).

The harness copies all of that: same config, same epoch ticker and callback, fuel refilled before each batch. Per-call time is measured from the host around batches of about 200 µs: 3,000 batches after warm-up, p50 and p99 of the per-call batch mean. Fuel per call is fuel consumed / calls.

The same code also ran natively (`sb-native`, x86_64) for reference.

**Machine:** dev-box, AMD Ryzen AI MAX+ 395, Fedora 44, `powersave` governor (amd-pstate). Timed runs were pinned to one core (`taskset -c 6`) with system load about 1.3.

### Calibration in a real SpacetimeDB 2.14.1

`stdb/` is a SpacetimeDB module that links the same bench code. Its reducers are admin-only:

- `bench_init(engine)` loads an engine.
- `bench(engine, law, n)` runs n calls, timed with `LogStopwatch`.
- `bench_digest(engine, law)` logs the output digest.

It was published as the scratch database `verify-scripts-bench` on a private `clockworklabs/spacetime:v2.14.1` container (port 3391). It is a minimal module, not the authority, and was never published to a lab or reference world.

Energy per reducer call is the `energy_quanta_used` the host returns in the caller's v1 `TransactionUpdate` (`crates/core/src/client/messages.rs:455`, which says it is the fuel used). The v2/v3 protocols, the Rust SDK and the CLI do not carry it, so `stdb_energy.py` calls the reducer over the `v1.json.spacetimedb` websocket protocol. Per call means (N-call reducer − 0-call reducer) / N, median of 5 runs.

## Results

### Time per call in the module (SpacetimeDB's wasmtime config, fuel on), µs

| Engine | rates p50 | rates p99 | strike p50 | strike p99 | cooldown p50 | cooldown p99 | rates vs native |
|---|---:|---:|---:|---:|---:|---:|---:|
| native | 0.095 | 0.098 | 0.302 | 0.309 | 0.004 | 0.004 | 1× |
| **rhai (as embedded)** | **28.5** | **30.8** | **57.7** | **70.9** | **1.48** | **1.52** | **301×** |
| rhai, lean context | 12.9 | 13.5 | 34.0 | 42.0 | 1.39 | 1.43 | 136× |
| rhai, map only | 12.7 | 13.0 | 26.3 | 27.2 | 0.075 | 0.077 | (134×) |
| rune | 11.7 | 12.0 | 21.8 | 25.2 | 0.269 | 0.275 | 123× |
| wasmi | 15.4 | 16.6 | 19.0 | 20.8 | 0.743 | 0.821 | 162× |
| wasmi + own fuel | 16.8 | 18.4 | 20.9 | 22.9 | 0.825 | 0.886 | 177× |
| piccolo | 9.42 | 9.77 | 17.7 | 19.9 | 0.300 | 0.309 | 99× |
| koto ¹ | 12.5 | 12.8 | 22.8 | 27.1 | 0.484 | 0.499 | 132× |

¹ Koto's module imports 21 wasm-bindgen functions, from `chrono` and `instant`, which `koto_runtime` depends on unconditionally. SpacetimeDB would refuse it. It was timed with those imports stubbed as traps; none was called.

### Energy (fuel = WASM instructions) per call, and the cost of metering

| Engine | rates | strike | cooldown | rates p50, fuel off (µs) | strike p50, fuel off (µs) | metering overhead (rates) |
|---|---:|---:|---:|---:|---:|---:|
| native | 1,739 | 5,203 | 45 | 0.079 | 0.236 | +20% |
| rhai | 309,494 | 619,074 | 20,527 | 21.6 | 44.6 | +32% |
| rhai, lean | 132,677 | 358,162 | 19,557 | 10.2 | 26.9 | +27% |
| rhai, map only | 135,729 | 279,392 | 633 | 9.00 | 18.5 | +41% |
| rune | 197,547 | 353,382 | 4,400 | 9.11 | 17.1 | +28% |
| wasmi | 82,945 | 103,160 | 4,532 | 13.4 | 17.1 | +15% |
| piccolo | 198,161 | 361,985 | 4,306 | 8.44 | 15.9 | +12% |
| koto | 175,264 | 319,702 | 8,886 | 10.1 | 19.0 | +24% |

- SpacetimeDB's fuel metering adds 12–41% to every engine.
- Energy does not rank engines the way time does. wasmi uses the least fuel but runs about 5 instructions per ns. The other engines run 11–21 per ns, because each wasmi bytecode step costs a few dispatch-heavy WASM instructions.
- `FunctionBudget` assumes 2 instructions per ns, so a reducer's nominal "1 minute" of budget is about 6–22 s on this CPU.

### Native x86_64 reference (p50, µs)

| Engine | rates | strike | cooldown | module/native (rates) | compile/load (ms) |
|---|---:|---:|---:|---:|---:|
| native | 0.037 | 0.125 | 0.002 | 2.6× | — |
| rhai | 12.1 | 22.8 | 0.550 | 2.4× | 2.76 |
| rhai, lean | 4.89 | 14.7 | 0.540 | 2.6× | 2.31 |
| rune | 5.11 | 9.49 | 0.104 | 2.3× | 3.17 |
| wasmi | 1.32 | 1.66 | 0.099 | **11.6×** | 0.40 |
| piccolo | 4.34 | 7.59 | 0.094 | 2.2× | 0.29 |
| koto | 6.07 | 12.0 | 0.256 | 2.1× | 0.35 |
| mlua (Lua 5.4) | 4.54 | 8.51 | 0.045 | does not build | 0.22 |

- Inside the module, every engine is 2.1–2.6× slower than natively, except wasmi.
- wasmi is 11.6× slower in the module. An interpreter compiled to WASM and run under Cranelift with fuel checks pays for every dispatch. Natively, wasmi is the fastest interpreter here; in the module it is mid-pack.
- The native Rhai figure (12.1 µs for `rates`) agrees with [FLOORS.md](FLOORS.md)' earlier 11.4 µs measured with lighter actors.

### Load time, module size and memory (wasm32, fuel on)

| Engine | module size | added over baseline | wasmtime compile of module (ms) | engine load (ms) | engine load fuel | memory after load |
|---|---:|---:|---:|---:|---:|---:|
| baseline (fixtures + native laws) | 112 KiB | — | 91 | — | — | 1,600 KiB (fixtures) |
| rhai | 3,893 KiB | +3,781 KiB | 2,460 | 5.2 | 51 M | +1,280 KiB |
| rune | 5,769 KiB | +5,657 KiB | 3,866 | 5.9 | 55 M | +2,048 KiB |
| wasmi (+ 31 KB guest) | 2,027 KiB | +1,915 KiB | 1,210 | 0.6 | 4.0 M | +1,216 KiB, +2,240 KiB after runs ² |
| piccolo | 874 KiB | +762 KiB | 626 | 0.45 | 3.1 M | +128 KiB |
| koto | 2,518 KiB | +2,406 KiB | 1,441 | 0.49 | 3.8 M | +192 KiB |

- "Engine load" is what `install_script` would pay: Rhai compiles the full 55 KB `skills.rhai`; the others compile only the three ported laws. Rhai's 51 M fuel is 0.04% of a reducer's budget.
- Memory is the module's linear memory, measured from the host. It only grows.
- The current authority module is 7.1 MB, built on the dev-box 2026-11-09. The Rhai-only bench module is 3.9 MB, so Rhai and the script runtime are probably about half of the authority. This is an estimate: the authority was not rebuilt without Rhai.
- Switching from Rhai changes the module size by roughly (other engine − Rhai): Rune +1.9 MB, piccolo −3.0 MB, wasmi −1.9 MB.

² The guest is a Rust wasm32 binary with the default 1 MiB stack in its own linear memory, which wasmi keeps inside the module's memory. A linker `stack-size` flag would shrink it.

### Calibration: harness against a real 2.14.1 reducer

| Engine | law | N | energy/call, real host | fuel/call, harness | µs/call, real host | µs/call, harness | host / harness |
|---|---|---:|---:|---:|---:|---:|---:|
| native | rates | 20,000 | 1,739 | 1,739 | 0.092 | 0.095 | 0.97 |
| native | strike | 20,000 | 5,245 | 5,203 | 0.288 | 0.302 | 0.96 |
| native | cooldown | 400,000 | 45 | 45 | 0.004 | 0.004 | 0.99 |
| **rhai** | **rates** | 1,000 | **309,574** | 309,494 | **29.3** | 28.5 | 1.03 |
| rhai | strike | 1,000 | 617,239 | 619,074 | 57.0 | 57.7 | 0.99 |
| rhai | cooldown | 20,000 | 13,668 | 20,527 | 1.07 | 1.48 | 0.72 |
| rhai, lean | rates | 1,000 | 133,034 | 132,677 | 12.5 | 12.9 | 0.97 |
| rhai, lean | strike | 1,000 | 357,591 | 358,162 | 33.2 | 34.0 | 0.98 |
| rune | rates | 1,000 | 195,605 | 197,547 | 11.3 | 11.7 | 0.97 |
| rune | strike | 1,000 | 349,687 | 353,382 | 20.8 | 21.8 | 0.96 |
| wasmi | rates | 1,000 | 83,031 | 82,945 | 16.3 | 15.4 | 1.06 |
| wasmi | strike | 1,000 | 103,215 | 103,160 | 19.4 | 19.0 | 1.02 |

- Energy matches within 1%, and time within ±6%, for every engine and law except Rhai's constant lookup. The real host does that lookup in about two-thirds of the harness's instructions; the cause was not found.
- A 1,000-call Rhai `rates` reducer used 309.5–309.7 M energy and 29–31 ms of host time. An empty call of the same reducer used 5.7 k and 78 µs.
- The harness numbers stand for the real host.
- Fuel is deterministic for identical inputs: two 1,000-call runs over the same fixtures differed by 10 instructions in 306 M. Runs that cover slightly different fixture mixes differ by 0.06%. Fuel can therefore serve as a speed budget.

### Equivalence

Every engine produces byte-identical outputs on all 64 + 64 + 8 fixtures for all three laws:

- natively;
- under wasmtime, with fuel on and off;
- inside the real SpacetimeDB reducer, where all digests were logged by `bench_digest`.

Floats were compared bit-exactly by their shortest round-trip form. `run.sh` checks the 57 dump files against the native floor's.

Two ports needed corrections before they matched. Both are authoring hazards:

- Koto's `not` binds looser than `and`: `not x and y` is `not (x and y)`.
- Koto's paren-less call syntax reads `(f a, b)` as a tuple.

### Where Rhai's time goes (in the module)

| | rates | strike (2 calls) |
|---|---:|---:|
| Full call as embedded | 28.5 µs | 57.7 µs |
| `to_map` alone (60 fields, 7 nested maps, string clones, a `format!` and a BTreeMap gene lookup for the skill factor) | 12.7 µs (45%) | 26.3 µs (46%) |
| Same script, lean context | 12.9 µs | 34.0 µs |
| Per-call overhead (a 4-operation constant lookup) | 1.48 µs, 20.5 k instructions | |
| Rhai operations per call (max over fixtures; limit 20,000) | 236 | 258 check + 88 done |

Script execution, at about 560–740 instructions per Rhai operation, is a little over half. The context is most of the rest.

The Rhai engine itself is not slow for an AST interpreter: with a lean context it is near Rune and piccolo for `rates`. The embedding rebuilds the whole world view for every question.

## What it means at the target populations

These are estimates from the measured per-call costs, not measurements of the authority.

- **Combat.** Assume 200 fighters starting about 2 moves a second ([FLOORS.md](FLOORS.md)' assumption), each with check + done: 400 strike paths/s.

  | Engine | ms of reducer time per second |
  |---|---:|
  | Rhai | 23 |
  | Rhai, lean context | 14 |
  | Rune | 8.7 |
  | piccolo | 7.1 |
  | native | 0.12 |

  The two constant lookups per move start add 1.2 ms/s in Rhai, and about 0 as tables.
- **Synchronized bursts.** The authority reruns `rates` only when a character's `rate_key` changes (`authority/src/brain.rs:151`). The key includes `night` and `raining`, so nightfall or the start of rain changes every character's key at once. At 28.5 µs each:
  - the 216-character gate needs 6.2 ms of Rhai (37% of a 16.7 ms tick);
  - 2,000 characters need 57 ms (3.4 ticks).

  How much of that lands in one tick depends on how evaluations are spread across slots; that was not measured. Lean context halves it; native makes it 0.2 ms.
- **A runaway law.** `max_operations` is 20,000. At about 560–740 instructions per operation, a call that reaches the limit costs about 11–15 M instructions, about 1–1.4 ms in the module, every time it is called. 200 characters hitting such a law in one tick would cost 200–280 ms.

## The engines

### Rhai (current)

- **Embedding:** the easiest of all. Pure Rust, no imports, builds for the module as is, already in use.
- **Sandboxing and limits:** the best of the interpreters. The limits are in-engine and deterministic: operations, call depth, expression depth, string, array and map sizes, and disabled symbols.
- **Typing and errors:** dynamic. A misspelled field (`a.actor.hungr`) is `()` or a runtime error only on the path that reads it. Install-time validation has to execute laws to find such errors.
- **Tooling:** Rust-like syntax, close to the authority's own code; no static checker.
- **Maturity:** 1.x since 2021, released 2026-10-21, 4.4 M recent downloads.
- **Hot reload:** `install_script` with source text works today. Compile is 5 ms.
- **Costs:** the call boundary as embedded (above), 3.8 MB of module, 1.3 MB of memory per loaded script.

### Rune

- **Speed and size:** about 2.4× faster than Rhai as embedded with the same full context (2.6× on strikes). For `rates` it is about as fast as Rhai with a lean context. It is the largest module (+5.7 MB) and the slowest wasmtime compile (3.9 s).
- **Limits:** an instruction budget (`runtime::budget::with`) and a memory limit (`alloc::limit::with`).
- **Typing:** dynamic, with stricter numbers than Rhai (no implicit int/float mixing), which catches some errors at run time.
- **Maturity:** 0.14 (2026-05), mostly one maintainer, about 25 k recent downloads; the language still changes between minors.
- **Hot reload:** source text compiles in 6 ms.
- **Verdict:** a 2× gain does not pay for porting 55 KB of rules plus a less mature dependency, and the boundary fix gets most of it.

### wasmi with laws written in Rust

- **Strengths:** the strongest typing (Rust, checked before upload) and a strong sandbox (separate linear memory, fuel, store limits). It uses the least energy per call.
- **Speed in the module:** an interpreter inside wasmtime runs 11.6× slower than natively. `rates` is 15.4 µs, no faster than Rune or piccolo, and native Rust in the module is 160× faster.
- **Boundary:** each call pays for encoding the context. A leaner ABI would help, but the same lean-context idea helps Rhai too.
- **Hot reload:** `install_script` would take a compiled `.wasm` blob, so authors need a Rust toolchain. That closes rules authoring to anyone without one.
- **Verdict:** not a good authoring path. For a hot law that must be fast, compiling it into the authority is strictly better.

### piccolo (pure-Rust Lua)

- **Speed and size:** the fastest interpreter in the module (3× Rhai as embedded) and the smallest (+0.76 MB, 128 KiB memory).
- **Limits:** fuel-stepped execution built in.
- **Embedding friction:**
  - it pulls in `getrandom` 0.2 (via `rand`) and 0.3 (via `ahash`), neither of which builds for wasm32-unknown-unknown without custom backends;
  - its gc-arena lifetimes make the host API the hardest here.
- **Authoring:** Lua semantics (1-based tables, `nil`, globals by default).
- **Maturity:** 0.3.3, last released 2024-06; experimental by its own description.
- **Verdict:** a credible future option only if it becomes maintained again.

### Koto

- **Speed:** similar to Rune.
- **Embedding:** blocked as published. `koto_runtime` unconditionally depends on `chrono` and `instant` with wasm-bindgen backends, so the module imports JavaScript glue SpacetimeDB cannot provide. A fork would be needed.
- **Limits:** its only execution limit is wall-clock time (`instant::Instant`), which does not exist in the module. There is no instruction or memory budget.
- **Authoring:** has the precedence trap above.
- **Verdict:** not suitable.

### Lua

The mlua attempt was timeboxed to about an hour; the blockers are structural.

- `mlua` + vendored **Lua 5.4**: the build script panics with `don't know how to build Lua for wasm32-unknown-unknown` (`lua-src-551.0.2/src/lib.rs:100`).
- `mlua` + vendored **Luau**: the C++ compile fails on the first headers, `fatal error: 'string.h' file not found`, `'climits' file not found`, `'algorithm' file not found`. The target has no libc or libc++.
- **Underneath both:**
  - PUC Lua and Luau need a C library. A WASI libc would add `wasi_snapshot_preview1` imports, which SpacetimeDB does not provide.
  - Lua's errors use `setjmp`/`longjmp` (`ldo.c`, `LUAI_THROW`). Without Emscripten's JavaScript glue, that needs the wasm exception-handling proposal. SpacetimeDB 2.14.1 builds wasmtime without `gc`, and wasmtime 39 refuses to enable exceptions without it (`config.rs`: "exceptions support requires garbage collection (GC) to be enabled in the build").
- Natively, PUC Lua 5.4 through mlua is about 2.7× faster than Rhai as embedded. That speed is out of reach in the module.
- The pure-Rust Lua that does build is piccolo, above.

### Native Rust

- **Speed:** 100–370× faster than any interpreter.
- **Limits and typing:** the module's own fuel only; full static typing.
- **Hot reload:** none. A change is a module publish, which SpacetimeDB does in place, keeping data, but it is not a rule edit at run time.
- **Fit:** the right home for primitives and per-tick numeric laws, parameterized by values the script supplies. This is the existing `laws()` and `<skill>_combat()` pattern.

## Recommendation

Items 1–4 below and the hardening items landed on `rhai-1` ([what changed](#what-changed-on-rhai-1)).

**Stay on Rhai, and make it a hybrid by cadence**, extending the [rules-in-Rhai](FLOORS.md#cadence-what-a-law-costs) direction. Do these in order of payoff:

1. **Constants become tables read once per install.** Examples: `combat_cooldown`, `combat_recover`, `combat_cost`, `lunge`, `yield_ms`, `max_hp`, `nutrition`, `spoil_rate`.

   Each is a `switch` on a name. Read every value at `install_script`, as `<skill>_combat()` and `laws()` already are. This turns a 1.5 µs (20 k instructions) call into a few ns, and costs nothing in authoring: the script still defines them.
2. **A lean context per law.** At install time, walk each law's AST for `a.actor.*`, `a.target.*`, `a.routine.*` and top-level `a.*` property reads. Rhai's AST walker, `AST::walk`, needs its `internals` feature. Then build only those fields.

   Measured on the same script with identical outputs: `rates` 28.5 → 12.9 µs, strike 57.7 → 34.0 µs. Also derive the skill factor and body genes only when read. A script that reads a field dynamically needs a fallback to the full map.
3. **Per-tick numeric laws become Rust primitives with Rhai-supplied parameters.** Anything evaluated per character per tick (steering, movement, combat timing) is 100–300× cheaper as Rust reading install-time tables. Keep Rhai for decisions at action start and completion, and for event-time rates.
4. **Spread rate recomputation.** Nightfall and rain change every `rate_key` at once. Recompute over a window or in the character's own evaluation slot instead of in one tick.
5. **Revisit the engine only with new evidence.** After 1–3, revisit only if script execution itself is the measured bottleneck in the 216-character gate. Rune is then the candidate (about 2× on execution). Its speed with a lean context was not measured.

Do not adopt wasmi-run Rust laws, Koto or a Lua for this module.

## Hardening items, with the numbers that change them

On `rhai-1` (see [what changed](#what-changed-on-rhai-1)):

- **Done:** the limits (§5), the install checks (§6) and the fuel gate (§7). Constant lookups no longer pay per-call overhead (§1).
- **Not done:** resolving each skill's function names at install. A check or done still formats its name and looks it up, about 0.1 µs against 11–25 µs for the call.

The table is the spike's proposal.

| Item | Current | Measured | Proposed |
|---|---|---|---|
| Per-call operation limit (`set_max_operations`) | 20,000 | Heaviest law here uses 258 (strike check); `rates` 236; about 560–740 WASM instructions per operation, so 20,000 operations is about 11–15 M instructions, 1–1.4 ms per call in the module. | About 2,000 (8× headroom), after measuring every law, not only these three. Report each law's maximum at install. |
| Source size (`MAX_SOURCE`) | 64 KiB | `skills.rhai` is 54,858 B (84% of it). Compiling it costs 5.2 ms and 51 M instructions (0.04% of a reducer budget) and holds 1.3 MB. | The limit is about memory and abuse, not CPU. Raise it to about 256 KiB before the corpus hits it (estimate: about 20 ms, about 5 MB at linear scale), or split per floor. |
| Install-time validation | Compile, required entry points, `_combat`/`_shows` traits | Running the three laws over 128 fixtures takes about 6 ms in the module. | At `install_script`: run every law over a fixture set, reject runtime errors and wrong return types, and record operations per law. This catches misspelled fields, which Rhai only reports on execution. |
| Speed-budget test | — | Fuel per call is deterministic for identical inputs (harness and real host within 1%). Wall time varies with CPU and governor. | Budget in fuel, not µs. A CI test runs `sb-host` on the rules and fails when a law exceeds its budget. Today: `rates` 310 k, strike 620 k, constant lookup 21 k. Target after items 1–2: about 135 k, about 360 k and 0. |
| Per-call overhead | `format!("{skill}_check")`, a `HashSet` lookup and a fresh `Scope` per call | 1.5 µs and 20 k instructions for a 4-operation function. | Resolve function names per skill at install; reuse the scope. |

## Limits of this spike

- Three laws were ported, not the corpus. Other laws (`experiment`, `teach`, `skill_io`'s string building) may weigh more and were not measured.
- The calibration module is not the authority. It shares the code path and the engine settings, but not the authority's heap state or module size.
- One machine and one CPU governor; times scale with both, fuel does not.
- Rune and piccolo were run with a full context. A lean context would speed them up too; that was not measured.
- The population figures are arithmetic on per-call costs, not authority measurements. A span around script calls in the skirmish benchmark would confirm them.
- SpacetimeDB documentation checked: [reducers](https://spacetimedb.com/docs/functions/reducers), [reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context), [lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle), [tables](https://spacetimedb.com/docs/tables/) and the [CLI reference](https://spacetimedb.com/docs/cli-reference). They confirm `#[reducer(init)]`, `ctx.sender()`, `accessor =` and private-by-default tables.
  - The docs do not mention energy, budgets or `LogStopwatch`. Those come from the v2.14.1 source cited above.
  - The docs call global or static state in reducers undefined behavior. The calibration module caches engines in a thread-local, as the authority caches `Scripts`, and reinitializes outside the timed span when the cache is empty.

## Reproduce

On the dev-box, in a worktree, with a private target dir:

```sh
cd living/tools/script_bench
CARGO_TARGET_DIR=~/scratch/sb-target OUT=~/scratch/sb-out PIN="taskset -c 6" ./run.sh
python3 report.py ~/scratch/sb-out
# Calibration (a private 2.14.1 container, never a lab world)
docker run -d --name sb-script-bench-stdb --user spacetime -p 127.0.0.1:3391:3000 \
  -v "$DIR_WITH_SB_STDB_WASM":/wasm:ro,Z docker.io/clockworklabs/spacetime:v2.14.1 start --listen-addr 0.0.0.0:3000
cargo build -p sb-stdb --target wasm32-unknown-unknown --release
docker exec sb-script-bench-stdb spacetime publish -s local -b /wasm/sb_stdb.wasm verify-scripts-bench -y
docker exec sb-script-bench-stdb spacetime call -s local verify-scripts-bench bench_init 1
python stdb_energy.py http://127.0.0.1:3391 verify-scripts-bench TOKEN_FILE 1 0 1000 5
```

Engine ids: 0 native, 1 rhai, 3 rune, 4 wasmi, 9 rhai-lean. Law ids: 0 rates, 1 strike, 2 cooldown.
