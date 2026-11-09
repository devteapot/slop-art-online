#!/usr/bin/env bash
# Regenerate the generated city buildings for the game's test environments (git-ignored output).
# Usage: living/tools/blender/gen_buildings.sh [count] [seed] [out_root]
#   count is models per form (kinds with forms, such as houses, make count per form);
#   out_root defaults to living/game/assets/envs; pass a scratch folder to preview a set.
# Fixed kinds (towers, walls, lamps...) have the exact heights in buildings.py HEIGHTS, matching
# the env JSON slots; houses, halls and the like come in forms of varying size. Models have their
# origin at the floor, with a foundation below it. Each set writes gen-<kind>-<style>.json with
# every model's footprint; the last step gathers them into living/rules/data/buildings.json,
# which the settlement planner reads, so a scratch out_root rewrites that table too.
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
  "fantasy inn fantasy_city/inn"
  "fantasy hall fantasy_city/hall"
  "fantasy chapel fantasy_city/chapel"
  "fantasy workshop fantasy_city/workshop"
  "fantasy barn fantasy_city/barn"
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
  "giant hall giants_city/hall"
  "small house small_city/house"
  "small tower small_city/tower"
  "small well small_city/well"
  "small hall small_city/hall"
)
pids=()
for spec in "${specs[@]}"; do
  read -r style kind dir <<<"$spec"
  rm -f "$envs/$dir"/gen-*.glb "$envs/$dir"/gen-*.json
  # Giants share the fantasy grammar; a different seed keeps their houses from being copies.
  s=$seed; [ "$style" = giant ] && s=$((seed + 50))
  ("$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- \
    --style "$style" --kind "$kind" --count "$count" --seed "$s" --out "$envs/$dir" 2>&1 | grep -E '^GEN|Error|Traceback' || true) &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
# The footprint table the settlement planner reads (committed, unlike the models).
"$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- --table living/rules/data/buildings.json --envs "$envs" 2>&1 | grep -E '^TABLE|Error|Traceback' || true
