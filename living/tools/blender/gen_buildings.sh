#!/usr/bin/env bash
# Regenerate the generated city buildings for the game's test environments (git-ignored output).
# Usage: living/tools/blender/gen_buildings.sh [count] [seed] [out_root]
#   out_root defaults to living/game/assets/envs; pass a scratch folder to preview a set.
# Heights are fixed per kind in buildings.py (HEIGHTS) and match the env JSON slots. Models have
# their origin at the floor, with a foundation below it; footprints are buildings.py ENVELOPES.
set -euo pipefail
cd "$(dirname "$0")/../../.."
count=${1:-8}
seed=${2:-1}
envs=${3:-living/game/assets/envs}
blender=${BLENDER:-blender}
# style kind folder
specs=(
  "fantasy house fantasy_city/house"
  "fantasy townhouse fantasy_city/townhouse"
  "fantasy tower fantasy_city/tower"
  "fantasy wall fantasy_city/wall"
  "fantasy market_stall fantasy_city/market_stall"
  "fantasy lamp fantasy_city/lamp"
  "fantasy well fantasy_city/well"
  "steampunk house steampunk_city/house"
  "steampunk factory steampunk_city/factory"
  "steampunk chimney steampunk_city/chimney"
  "steampunk pipe steampunk_city/pipe"
  "steampunk crate steampunk_city/crate"
  "steampunk lamp steampunk_city/lamp"
  "giant house giants_city/house"
  "giant tower giants_city/tower"
  "giant lamp giants_city/lamp"
  "giant well giants_city/well"
  "small house small_city/house"
  "small tower small_city/tower"
  "small well small_city/well"
)
pids=()
for spec in "${specs[@]}"; do
  read -r style kind dir <<<"$spec"
  rm -f "$envs/$dir"/gen-*.glb
  # Giants share the fantasy grammar; a different seed keeps their houses from being copies.
  s=$seed; [ "$style" = giant ] && s=$((seed + 50))
  ("$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- \
    --style "$style" --kind "$kind" --count "$count" --seed "$s" --out "$envs/$dir" 2>&1 | grep -E '^GEN|^WARN|Error|Traceback' || true) &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
# The footprint table the settlement planner reads (committed, unlike the models).
"$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- --table living/rules/data/buildings.json 2>&1 | grep -E '^TABLE|Error|Traceback' || true
