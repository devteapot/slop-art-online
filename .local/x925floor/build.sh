#!/usr/bin/env bash
set -euxo pipefail
source ~/slop-sysroot/env.sh
cd /home/gooning/.t3/worktrees/slop-art-online-t3/t3-eacddf65-5240dd2ef1d69529
T=$HOME/slop-x925floor-target
LIVING_SEED=cullet CARGO_TARGET_DIR=$T/auth cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
CARGO_TARGET_DIR=$T/load cargo build --manifest-path living/tools/gate_load/Cargo.toml --release
