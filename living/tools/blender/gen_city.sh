#!/usr/bin/env bash
# Regenerate the megacity kit (living/tools/blender/city.py) into the game's environment folders
# (git-ignored output: the script is the asset), then the footprint table the settlement planner
# reads (living/rules/data/buildings.json, with every other set under out_root).
# Usage: living/tools/blender/gen_city.sh [count] [seed] [out_root]
#   count is models per form (default 4); JOBS (default 12) Blender processes run at once.
set -euo pipefail
cd "$(dirname "$0")/../../.."
count=${1:-4}
seed=${2:-1}
envs=${3:-living/game/assets/envs}
blender=${BLENDER:-blender}
jobs_max=${JOBS:-12}
kinds=$("$blender" -b --python-exit-code 1 -P living/tools/blender/city.py -- --list 2>/dev/null | sed -n "s/^KINDS //p")
for kind in $kinds; do
  dir="$envs/cyberpunk_megacity/$kind"
  rm -f "$dir"/gen-*.glb "$dir"/gen-*.json
  while [ "$(jobs -rp | wc -l)" -ge "$jobs_max" ]; do wait -n || true; done
  ("$blender" -b --python-exit-code 1 -P living/tools/blender/city.py -- --kind "$kind" --count "$count" --seed "$seed" --out "$dir" 2>&1 | grep -E '^GEN|Error|Traceback' || true) &
done
wait
"$blender" -b --python-exit-code 1 -P living/tools/blender/buildings.py -- --table living/rules/data/buildings.json --envs "$envs" 2>&1 | grep -E '^TABLE|Error|Traceback' || true
