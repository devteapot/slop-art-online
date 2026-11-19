#!/bin/sh
# Fuel budget gate for the hot laws (docs/LIVING_CORE.md, "Fuel budgets"), by hand:
#   CARGO_TARGET_DIR=dir [OUT=dir] living/tools/script_bench/gate.sh
# `just living-check` runs the same builds and gate.py as its `script-gate` step (stamped);
# this script is for keeping a run's evidence (OUT: the module, gate.jsonl, gate.err).
# Builds the Rhai bench module (living-rules' `Scripts` over living/scripts/skills.rhai, exactly
# as the authority calls it) and sb-host (wasmtime configured as SpacetimeDB 2.14.1 runs
# reducers, with fuel on), then gate.py measures each law's fuel per call: WASM instructions,
# the same on every machine for the same code and fixtures. Fails when a law is over
# budgets.json.
set -eu
cd "$(dirname "$0")"
: "${CARGO_TARGET_DIR:?set a private CARGO_TARGET_DIR}"
OUT=${OUT:-$CARGO_TARGET_DIR/script-gate}
mkdir -p "$OUT"
cargo build -q -p sb-module --target wasm32-unknown-unknown --release --features rhai
cp "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/sb_module.wasm" "$OUT/rhai.wasm"
# sb-host alone, without the native engines (Lua's C build, the wasmi guest)
cargo build -q -p sb-host --bin sb-host --release --no-default-features
exec python3 gate.py --host "$CARGO_TARGET_DIR/release/sb-host" --module "$OUT/rhai.wasm" --out "$OUT" --json "$OUT/gate.json"
