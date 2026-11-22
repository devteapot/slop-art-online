#!/usr/bin/env bash
set -euo pipefail
source ~/slop-sysroot/env.sh
cd /home/gooning/.t3/worktrees/slop-art-online-t3/t3-6ff50011-d08f9541c61140f8
export CARGO_TARGET_DIR=/home/gooning/slop-gate216-x925/target-gr
LIVING_SEED=cullet cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
cp $CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm /home/gooning/slop-gate216-x925/wasm/gate216_relay.wasm
cargo build --release --manifest-path living/tools/gate_load/Cargo.toml
cargo build --release --manifest-path living/tools/relay_proto/Cargo.toml
echo BUILD-GR-OK
