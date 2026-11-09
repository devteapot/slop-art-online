# script_bench

Research spike: the cost of running skill and law scripts inside the SpacetimeDB authority
module, across Rhai, Rune, wasmi (laws in Rust compiled to WASM), piccolo (pure-Rust Lua),
Koto, mlua (native only) and native Rust. Findings: [docs/SCRIPT_ENGINES.md](../../../docs/SCRIPT_ENGINES.md).

Standalone crate tree with its own `[workspace]`: not a member of `living/Cargo.toml` (it
depends on `living-rules` by path, so its `rhai` engine is the authority's call path).

| Path | What |
|---|---|
| `port.rs` | The three laws in Rust, line for line from `living/scripts/skills.rhai` |
| `scripts/` | The same laws in Rune, Lua and Koto |
| `bench/` | Fixtures, the context walk, one adapter per engine, run/dump/digest |
| `guest/` | The laws compiled to wasm32 for wasmi (`guest.wasm`, built by `run.sh`) |
| `module/` | A wasm32-unknown-unknown bench module (one per engine feature) |
| `host/` | `sb-host` (wasmtime 39.0.1 with SpacetimeDB 2.14.1's config) and `sb-native` |
| `stdb/` | Calibration module for a real SpacetimeDB 2.14.1 (admin-only reducers) |
| `stdb_energy.py` | Reads energy per reducer call over the v1 JSON websocket |
| `run.sh`, `report.py` | Build and run everything; print the tables |
| `gate.sh`, `budgets.json` | The fuel budget gate for the hot laws (`just living-script-gate`) |
| `results/2026-11-09/` | The run behind the doc (JSONL, sizes, imports, calibration logs) |
| `results/2026-11-09-rhai-1/` | Base against `rhai-1`: bench JSONL, the authority's tick runs and nightfall, limits |

Laws: `rates`, `strike` and `cooldown` run on every engine; `perceived` (`perceived_of`) and
`rates-law` (the `rates` law asked every time, where the authority shares one answer per state)
were added on `rhai-1` and run when named: `sb-host MODULE rhai --laws rates,rates-law,strike,cooldown,perceived`.

```sh
CARGO_TARGET_DIR=~/scratch/sb-target OUT=~/scratch/sb-out PIN="taskset -c 6" ./run.sh
python3 report.py ~/scratch/sb-out
```

Use a private `CARGO_TARGET_DIR`. Run the calibration only against a private container and a
scratch database (`verify-scripts-bench`), never a lab or reference world.
