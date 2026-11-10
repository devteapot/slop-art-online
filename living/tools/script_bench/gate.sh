#!/bin/sh
# Fuel budget gate for the hot laws (docs/SCRIPT_ENGINES.md, "Fuel budgets").
#   CARGO_TARGET_DIR=dir living/tools/script_bench/gate.sh
# Builds the Rhai bench module (living-rules' `Scripts` over living/scripts/skills.rhai, exactly
# as the authority calls it) and runs it under wasmtime configured as SpacetimeDB 2.14.1 runs
# reducers, with fuel on. Fuel is WASM instructions and is deterministic for the same inputs, so
# it is a speed budget that does not depend on the machine. Fails when any law takes more fuel
# per call than budgets.json allows.
set -eu
cd "$(dirname "$0")"
: "${CARGO_TARGET_DIR:?set a private CARGO_TARGET_DIR}"
OUT=${OUT:-$CARGO_TARGET_DIR/script-gate}
W=$CARGO_TARGET_DIR/wasm32-unknown-unknown/release
mkdir -p "$OUT"
# sb-host links every engine, the wasmi one with its guest.
cargo build -q -p sb-guest --target wasm32-unknown-unknown --release
cp "$W/sb_guest.wasm" guest.wasm
cargo build -q -p sb-module --target wasm32-unknown-unknown --release --features rhai
cp "$W/sb_module.wasm" "$OUT/rhai.wasm"
cargo build -q -p sb-host --release
"$CARGO_TARGET_DIR/release/sb-host" "$OUT/rhai.wasm" rhai --laws rates,rates-law,strike,cooldown,perceived,hook --batches "${BATCHES:-200}" > "$OUT/gate.jsonl" 2> "$OUT/gate.err"
python3 - "$OUT/gate.jsonl" budgets.json <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
budgets = json.load(open(sys.argv[2]))["fuel_per_call"]
fail = False
for r in rows:
    law, fuel = r["law"], r["fuel_per_call"]
    b = budgets.get(law)
    ok = b is not None and fuel <= b
    fail |= not ok
    print(f"{'ok  ' if ok else 'OVER'} {law:10} {fuel:>9.0f} fuel/call  budget {b}  ({r['p50_ns'] / 1000:.2f} us p50 here)")
missing = set(budgets) - {r["law"] for r in rows}
if missing:
    print("not measured:", ", ".join(sorted(missing)))
    fail = True
sys.exit(1 if fail else 0)
EOF
