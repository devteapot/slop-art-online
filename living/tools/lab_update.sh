#!/bin/sh
# Update running labs in place (their worlds keep going): rebuild each scenario's module and
# republish it without deleting data, install the current skill script (the database keeps
# its own copy), rebuild the mind service and restart the labs' minds (lab.py restarts them).
# Usage: living/tools/lab_update.sh [scenario:db ...]  (default: the three stage-1 labs)
set -e
LIVING="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LIVING"
LABS="${*:-stage1-base:living stage1-wolves:stage1-wolves stage1-scarce:stage1-scarce}"
cargo build -q -p living-mind --release
SCRIPT=$(python3 -c 'import json; print(json.dumps(open("scripts/skills.rhai").read()))')
for sc in $LABS; do
  s=${sc%%:*}; db=${sc##*:}
  LIVING_SEED=$s cargo build -q -p living-authority --target wasm32-unknown-unknown --release --target-dir "target/lab-$s"
  w="living_authority_$(echo "$s" | tr - _).wasm"
  cp "target/lab-$s/wasm32-unknown-unknown/release/living_authority.wasm" "target/wasm32-unknown-unknown/release/$w"
  tools/stdb publish -s local -b "/wasm/$w" "$db" -y 2>&1 | tail -1
  tools/stdb call -s local "$db" install_script "$SCRIPT" >/dev/null
done
pkill -f "^$LIVING/target/release/living-mind" || true
echo "minds restarting (lab.py supervises them)"
