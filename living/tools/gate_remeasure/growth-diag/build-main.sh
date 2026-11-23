#!/usr/bin/env bash
# growth-diag: main c5056f2e5 + gate-driver-main driver (growth-diag-main), Cullet module and gate-load, private target.
set -euo pipefail
source ~/slop-sysroot/env.sh
cd /home/gooning/.t3/worktrees/slop-art-online-t3/t3-2c307ca2-3b4d2ac37e3b5ddd
export CARGO_TARGET_DIR=/home/gooning/slop-growth-diag/target
LIVING_SEED=cullet cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
cp $CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm /home/gooning/slop-growth-diag/wasm/main_cullet.wasm
cargo build --release --manifest-path living/tools/gate_load/Cargo.toml
cp $CARGO_TARGET_DIR/release/gate-load /home/gooning/slop-growth-diag/wasm/gate-load-main
echo BUILD-OK
