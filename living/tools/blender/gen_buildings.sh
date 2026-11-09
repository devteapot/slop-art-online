#!/usr/bin/env bash
# Regenerate the generated city buildings for the game's test environments (git-ignored output).
# Usage: living/tools/blender/gen_buildings.sh [count] [seed] [out_root]
#   count is models per form (kinds with forms, such as houses, make count per form);
#   out_root defaults to living/game/assets/envs; pass a scratch folder to preview a set.
# Street props (benches, fences, stairs, retaining walls...; buildings.py PROPS and
# PROP_STYLES) make PROP_COUNT (default 4) per form. ONLY=props regenerates just the props, and
# ONLY=buildings just the buildings; the table is gathered from every set under out_root either
# way. JOBS (default 12) Blender processes run at once.
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
prop_count=${PROP_COUNT:-4}
only=${ONLY:-all}
jobs_max=${JOBS:-12}
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
  "steampunk inn steampunk_city/inn"
  "steampunk hall steampunk_city/hall"
  "steampunk clocktower steampunk_city/clocktower"
  "steampunk mast steampunk_city/mast"
  "steampunk works steampunk_city/works"
  "steampunk arcade steampunk_city/arcade"
  "cyberpunk block cyberpunk_city/block"
  "cyberpunk tower cyberpunk_city/tower"
  "cyberpunk landmark cyberpunk_city/landmark"
  "cyberpunk market cyberpunk_city/market"
  "cyberpunk workshop cyberpunk_city/workshop"
  "cyberpunk neon_sign cyberpunk_city/neon_sign"
  "cyberpunk billboard cyberpunk_city/billboard"
  "cyberpunk cable cyberpunk_city/cable"
  "cyberpunk kiosk cyberpunk_city/kiosk"
  "cyberpunk food_stall cyberpunk_city/food_stall"
  "cyberpunk walkway cyberpunk_city/walkway"
  "cyberpunk lamp cyberpunk_city/lamp"
  "cyberpunk crate cyberpunk_city/crate"
  "cyberpunk wall cyberpunk_city/wall"
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
[ "$only" = props ] && specs=()
# Street props per style (keep in step with buildings.py PROP_STYLES): style env kinds...
prop_sets=(
  "fantasy fantasy_city barrel crate cart bench fountain market_cross fence gate planter flower_box sign banner washing_line tree kerb stairs retaining_wall"
  "steampunk steampunk_city barrel cart bench fountain market_cross fence gate planter flower_box sign banner washing_line tree kerb stairs retaining_wall"
  "cyberpunk cyberpunk_city barrel cart bench fountain market_cross fence gate planter flower_box banner washing_line tree kerb stairs retaining_wall"
  "giant giants_city barrel crate cart bench fence gate planter sign tree washing_line"
  "small small_city barrel crate bench fence gate planter flower_box tree"
)
if [ "$only" != buildings ]; then
  for set in "${prop_sets[@]}"; do
    read -r style env kinds <<<"$set"
    for kind in $kinds; do specs+=("$style $kind $env/$kind $prop_count"); done
  done
fi
for spec in "${specs[@]}"; do
  read -r style kind dir n <<<"$spec"
  rm -f "$envs/$dir"/gen-*.glb "$envs/$dir"/gen-*.json
  # Giants share the fantasy grammar; a different seed keeps their houses from being copies.
  s=$seed; [ "$style" = giant ] && s=$((seed + 50))
  while [ "$(jobs -rp | wc -l)" -ge "$jobs_max" ]; do wait -n || true; done
  ("$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- \
    --style "$style" --kind "$kind" --count "${n:-$count}" --seed "$s" --out "$envs/$dir" 2>&1 | grep -E '^GEN|Error|Traceback' || true) &
done
wait
# The footprint table the settlement planner reads (committed, unlike the models).
"$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- --table living/rules/data/buildings.json --envs "$envs" 2>&1 | grep -E '^TABLE|Error|Traceback' || true
