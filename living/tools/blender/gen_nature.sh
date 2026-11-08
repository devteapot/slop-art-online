#!/usr/bin/env bash
# Regenerate the generated nature assets for the game's test environments (git-ignored output).
# Usage: living/tools/blender/gen_nature.sh [count] [seed]
set -euo pipefail
cd "$(dirname "$0")/../../.."
count=${1:-8}
seed=${2:-3}
envs=living/game/assets/envs
blender=${BLENDER:-blender}
# kind style folder
specs=(
  "tree meadow shared/tree"
  "bush meadow shared/bush"
  "rock meadow shared/rock"
  "flower meadow shared/flower"
  "pine forest forest/tree"
  "tree forest forest/tree"
  "bush forest forest/bush"
  "tree spirit spirit_forest/tree"
  "glow_mushroom spirit shared/glow_mushroom"
  "crystal spirit shared/crystal"
  "rock spirit caverns/rock"
)
for spec in "${specs[@]}"; do
  read -r kind style dir <<<"$spec"
  "$blender" -b --python-exit-code 1 -P living/tools/blender/nature.py -- \
    --kind "$kind" --style "$style" --count "$count" --seed "$seed" --out "$envs/$dir" | grep '^GEN' || true
done
