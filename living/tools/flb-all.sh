#!/bin/bash
# Start only after the Spark coordinator opens the paid trial window.
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ ${1:-} != --window-open ]]; then
  echo 'The paid sequence requires the coordinator to open the window.' >&2
  exit 2
fi
. ~/slop-sysroot/env.sh
export CARGO_TARGET_DIR="$HOME/slop-flb-replicates-target" SLOP_SLOT_MIN_FREE_GB=45
export LIVING_STDB_CONTAINER=slop-trials-stdb LIVING_STDB_URL=http://127.0.0.1:3320
export FLB_WINDOW_OPEN=yes
LIVING_SEED=island ~/slop-mq/build-slot cargo build --manifest-path living/Cargo.toml --locked \
  -p living-authority --target wasm32-unknown-unknown --release
~/slop-mq/build-slot cargo build --manifest-path living/Cargo.toml --locked -p living-mind --release
exec python3 living/tools/flb_replicates.py
