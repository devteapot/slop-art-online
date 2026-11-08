#!/usr/bin/env bash
# Regenerate the generated nature assets for the game's test environments (git-ignored output).
# Usage: living/tools/blender/gen_nature.sh [count] [seed]
# Each spec sets its own variant count; a count argument overrides them all. Runs one Blender per
# set, several at once (JOBS, default 6). Each folder first loses its generated gen-*.glb files
# that no spec writes any more, and each set removes its own earlier files, so a smaller count or
# a moved kind leaves no stale variants behind.
set -euo pipefail
cd "$(dirname "$0")/../../.."
count=${1:-}
seed=${2:-3}
jobs=${JOBS:-6}
envs=living/game/assets/envs
blender=${BLENDER:-blender}
# kind style folder variants (folder: assets/envs/<env>/<kind>/, or the shared fallback
# assets/envs/shared/<kind>/ that every environment without its own folder uses)
specs=(
  "tree meadow shared/tree 12"
  "oak meadow shared/oak 8"
  "birch meadow shared/birch 8"
  "coppice meadow shared/coppice 6"
  "young meadow shared/young 8"
  "sapling meadow shared/sapling 8"
  "snag meadow shared/snag 4"
  "bush meadow shared/bush 8"
  "rock meadow shared/rock 8"
  "flower meadow shared/flower 8"
  "grass meadow shared/grass 8"
  "tree forest forest/tree 12"
  "oak forest forest/oak 8"
  "pine forest forest/pine 12"
  "spruce forest forest/spruce 12"
  "birch forest forest/birch 12"
  "coppice forest forest/coppice 8"
  "young forest forest/young 12"
  "sapling forest forest/sapling 12"
  "snag forest forest/snag 8"
  "bush forest forest/bush 8"
  "grass forest forest/grass 8"
  "log forest forest/log 8"
  "tree spirit spirit_forest/tree 12"
  "giant spirit spirit_forest/giant 6"
  "sapling spirit spirit_forest/sapling 10"
  "grass spirit spirit_forest/grass 8"
  "glow_plant spirit spirit_forest/glow_plant 8"
  "glow_mushroom spirit shared/glow_mushroom 8"
  "crystal spirit shared/crystal 8"
  "rock spirit caverns/rock 8"
  "stalagmite spirit caverns/stalagmite 8"
)
# Drop generated files of kinds that no spec writes into that folder any more.
for spec in "${specs[@]}"; do
  read -r _ _ dir _ <<<"$spec"
  [ -d "$envs/$dir" ] || continue
  for f in "$envs/$dir"/gen-*.glb; do
    [ -e "$f" ] || continue
    keep=
    for s in "${specs[@]}"; do
      read -r k st d _ <<<"$s"
      [ "$d" = "$dir" ] && [[ $(basename "$f") == gen-"$k"-"$st"-* ]] && keep=1
    done
    [ -n "$keep" ] || rm -f "$f"
  done
done
gen() {
  local kind=$1 style=$2 dir=$3 n=$4
  mkdir -p "$envs/$dir"
  rm -f "$envs/$dir"/gen-"$kind"-"$style"-*.glb
  "$blender" -b --python-exit-code 1 -P living/tools/blender/nature.py -- \
    --kind "$kind" --style "$style" --count "$n" --seed "$seed" --out "$envs/$dir" 2>&1 | grep -E '^GEN|Error|Traceback' || true
}
for spec in "${specs[@]}"; do
  read -r kind style dir n <<<"$spec"
  gen "$kind" "$style" "$dir" "${count:-$n}" &
  while [ "$(jobs -rp | wc -l)" -ge "$jobs" ]; do sleep 0.2; done
done
wait
