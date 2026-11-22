#!/usr/bin/env bash
set -euo pipefail
source ~/slop-sysroot/env.sh
cd /home/gooning/slop-gate216-x925/main-src
export CARGO_TARGET_DIR=/home/gooning/slop-gate216-x925/target-main
LIVING_SEED=cullet cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
cp $CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm /home/gooning/slop-gate216-x925/wasm/gate216_main.wasm
cargo build --release --manifest-path living/tools/gate_load/Cargo.toml
echo BUILD-MAIN-OK
