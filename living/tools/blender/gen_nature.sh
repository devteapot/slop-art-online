#!/usr/bin/env bash
# Regenerate the generated nature assets for the game's test environments (git-ignored output).
# Usage: living/tools/blender/gen_nature.sh [count] [seed]
# Runs one Blender per kind, several at once (JOBS, default 6). Each set first removes its own
# earlier gen-<kind>-<style>-*.glb files, so a smaller count leaves no stale variants behind.
set -euo pipefail
cd "$(dirname "$0")/../../.."
count=${1:-8}
seed=${2:-3}
jobs=${JOBS:-6}
envs=living/game/assets/envs
blender=${BLENDER:-blender}
# kind style folder (assets/envs/<env>/<kind>/ or the shared fallback assets/envs/shared/<kind>/)
specs=(
  "tree meadow shared/tree"
  "bush meadow shared/bush"
  "rock meadow shared/rock"
  "flower meadow shared/flower"
  "grass meadow shared/grass"
  "pine forest forest/tree"
  "tree forest forest/tree"
  "bush forest forest/bush"
  "grass forest forest/grass"
  "log forest forest/log"
  "tree spirit spirit_forest/tree"
  "grass spirit spirit_forest/grass"
  "glow_plant spirit spirit_forest/glow_plant"
  "glow_mushroom spirit shared/glow_mushroom"
  "crystal spirit shared/crystal"
  "rock spirit caverns/rock"
  "stalagmite spirit caverns/stalagmite"
)
gen() {
  local kind=$1 style=$2 dir=$3
  mkdir -p "$envs/$dir"
  rm -f "$envs/$dir"/gen-"$kind"-"$style"-*.glb
  "$blender" -b --python-exit-code 1 -P living/tools/blender/nature.py -- \
    --kind "$kind" --style "$style" --count "$count" --seed "$seed" --out "$envs/$dir" 2>&1 | grep -E '^GEN|Error|Traceback' || true
}
for spec in "${specs[@]}"; do
  read -r kind style dir <<<"$spec"
  gen "$kind" "$style" "$dir" &
  while [ "$(jobs -rp | wc -l)" -ge "$jobs" ]; do sleep 0.2; done
done
wait
