#!/bin/sh
# Fuel per step of staged land generation (docs/FLOORS.md, "Staged generation").
#   CARGO_TARGET_DIR=dir living/tools/land_fuel/run.sh SEED_JSON [SIZE_M]
set -eu
cd "$(dirname "$0")"
: "${CARGO_TARGET_DIR:?set a private CARGO_TARGET_DIR}"
cargo build -q -p lf-guest --target wasm32-unknown-unknown --release
cargo build -q -p lf-host --release
seed=$(cd - >/dev/null && realpath "$1")
"$CARGO_TARGET_DIR/release/lf-host" "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/lf_guest.wasm" "$seed" "${2:-0}"
