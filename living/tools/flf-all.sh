#!/bin/bash
# The fast-lane frame trial (docs/FAST_LANE_FRAME.md): paid; start only once the coordinator
# has authorized the run. Builds the authority and the mind service, then runs flf_trial.py.
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ ${1:-} != --authorized ]]; then
  echo 'The paid frame trial needs the coordinator'"'"'s authorization: flf-all.sh --authorized' >&2
  exit 2
fi
. ~/slop-sysroot/env.sh
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/slop-fastframe-target}" SLOP_SLOT_MIN_FREE_GB=45
export LIVING_STDB_CONTAINER=slop-trials-stdb LIVING_STDB_URL=http://127.0.0.1:3320
export FLF_AUTHORIZED=yes
LIVING_SEED=island ~/slop-mq/build-slot cargo build --manifest-path living/Cargo.toml --locked \
  -p living-authority --target wasm32-unknown-unknown --release
~/slop-mq/build-slot cargo build --manifest-path living/Cargo.toml --locked -p living-mind --release
exec python3 living/tools/flf_trial.py
