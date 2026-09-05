# Scripting decision: embedding evidence

Executed 2026-09-05 for [ADR 016](adr/016-scripted-gameplay-rhai.md). This is a language/embedding probe, not production gameplay migration or a second simulator. At the time of this isolated probe, main workspace dependencies and gameplay databases were unchanged. The subsequent [gameplay integration](SCRIPTED_GAMEPLAY.md) adds Rhai to the real workspace and verifies a fresh gameplay database and client.

## Results

| Check | Observed result |
|---|---|
| Rhai 1.26.0 native | One test passed, exercising 11 embedding checks. |
| Rhai + SpacetimeDB 2.1.0, `wasm32-unknown-unknown` release | Compiled; published successfully to a separate local SpacetimeDB 2.1.0 server with `no_time` enabled. |
| Same 11 checks inside a real reducer | Passed; result persisted to the probe table. |
| Runtime source, initial movement law | Input position 0 / energy 10 / target 4 produced position 1 / energy 8. |
| Runtime source, changed movement law | The next invocation received position 1 / energy 8, the same skill source, and a different law; produced position 3 / energy 7 without republishing the module. |
| Failed runtime script, exhausted operation budget, hidden variable access | All rejected by the evaluator; no output row committed for any failed call. |
| Luau via `mlua` 0.12.1 native | Passed a minimal sandboxed function call. |
| Luau stock raw-WASM release build | Failed in the vendored C/C++ build with missing `string.h` / `climits` target headers. This is an observed stock-toolchain failure, not proof that a custom port is impossible. |

The 11 common checks cover movement, a changed law, a scripted prerequisite, removing a gameplay cost through a law change, composing two steps, operation-budget termination, unavailable host access, unavailable hidden observation, recursive execution rejection, invalid result type rejection, and script failure before returning a result. They deliberately do not duplicate the game's world implementation.

The runtime-source verifier additionally exercises actual reducer submission and database commit/rejection. It passes the preceding state into the next invocation; this proves re-evaluation with explicit state, not a completed production scheduler or law registry. The probe's public reducer accepts arbitrary source solely in a disposable test database; it is not the production definition-installation API.

## Configuration finding

The first Rhai build used `std` and `no_float`, with default features disabled. Compilation passed, but server publication failed with an unresolved browser import, `__wbindgen_placeholder__::__wbindgen_describe`. Rhai's time support pulls in browser time bindings for WASM. Adding the supported `no_time` feature removed the required browser import and publication succeeded. The pinned probe manifest retains this configuration.

The final engine uses `Engine::new_raw`, no module/file resolver, no ambient clock, disabled dynamic evaluation/import syntax, and explicit operation, call-depth, expression-depth, source-size, container-size, and variable limits. No host mutation callbacks are exposed in this small probe. This does not certify a future richer API, aggregate memory accounting, compilation under adversarial load, or multiplayer performance.

The first standalone-server invocation lacked its required key setup; the installed CLI wrapper performed that setup. The HTTP verifier was corrected to send JSON content types for reducer calls and to recognize SpacetimeDB's reducer-failure status. The passing verification checks both the evaluator's actual error reason and absence of a committed row, rather than counting arbitrary HTTP failures as successful rejection.

## Reproduction

Source: [Rhai probe](../experiments/scripting-rhai/src/lib.rs), [movement script](../experiments/scripting-rhai/scripts/movement.rhai), [database verifier](../experiments/scripting-rhai/verify_database.py), [Luau target probe](../experiments/scripting-luau/src/lib.rs). Each probe has an isolated Cargo workspace and a retained dependency lockfile.

From the repository root:

```sh
cargo test --locked --manifest-path experiments/scripting-rhai/Cargo.toml -- --nocapture
cargo build --locked --manifest-path experiments/scripting-rhai/Cargo.toml --features database --target wasm32-unknown-unknown --release
cargo test --locked --manifest-path experiments/scripting-luau/Cargo.toml
# Expected to fail on the tested stock raw-WASM toolchain:
cargo build --locked --manifest-path experiments/scripting-luau/Cargo.toml --target wasm32-unknown-unknown --release
```

Use a SpacetimeDB **2.1.0** CLI/server for the runtime check, on a free loopback port and fresh disposable directory. Do not publish this module over a gameplay database. In separate terminals, keeping the server running for the check:

```sh
spacetime start --listen-addr 127.0.0.1:3197 --data-dir output/scripting-decision/server --in-memory --page_pool_max_size 67108864 --non-interactive
spacetime --config-path output/scripting-decision/cli.toml publish --server http://127.0.0.1:3197 --anonymous --no-config --bin-path experiments/scripting-rhai/target/wasm32-unknown-unknown/release/sao_scripting_probe.wasm sao-rhai-decision -y
spacetime --config-path output/scripting-decision/cli.toml call --server http://127.0.0.1:3197 --anonymous sao-rhai-decision check
python3 experiments/scripting-rhai/verify_database.py --output output/scripting-decision/verification.json
```

The `check` reducer inserts one fixed result row; call it once per fresh probe database. The source verifier uses unique result names and can run repeatedly. Stop the disposable server after checking. Local generated evidence is under `output/scripting-decision/`; this document retains the results when that ignored directory is removed.

No language-wide speed ranking, population capacity, public sandbox certification, or gameplay migration is claimed. Rune, Starlark, Boa, and standard Lua were documentation comparisons, not executable benchmarks in this evaluation.
