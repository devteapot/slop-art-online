# Script engines for skills and laws

**Status:** research spike, 2026-11-09, branch `spike-scripts`. No authority, rules or mind code changed. Bench crate: [`living/tools/script_bench/`](../living/tools/script_bench/) (standalone, not a workspace member). Raw results: [`living/tools/script_bench/results/2026-11-09/`](../living/tools/script_bench/results/2026-11-09/).

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
