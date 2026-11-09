#!/usr/bin/env bash
# Regenerate the animated VRoid characters (git-ignored output): each look-dev VRoid GLB gets the
# clip library (living/tools/blender/clips.json) from animate.py, written to
# living/game/assets/lookdev/anim/ under the same file name, with <name>.clips.json beside it
# (each clip's length, loop, natural and baked speed, and source), then merges each file's
# same-material primitives (living/tools/merge_primitives.py) to cut draw calls.
# Kimodo clips need their generated NPZs in .local/kimodo/outputs/library/ (living/tools/kimodo/spark.sh).
# Usage: living/tools/blender/gen_anim.sh [extra animate.py args, e.g. --speed 2.6 --run-speed 3.9]
#   Without the library (hand-keyed clips only): gen_anim.sh --library "" --clips idle,walk,talk,run,attack
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=living/game/assets/lookdev
blender=${BLENDER:-blender}
mkdir -p "$src/anim"
for f in "$src"/vroid-*.glb; do
  name=$(basename "$f" .glb)
  "$blender" -b --python-exit-code 1 -P living/tools/blender/animate.py -- \
    --in "$f" --out "$src/anim/$name.glb" --library living/tools/blender/clips.json \
    --summary "$src/anim/$name.clips.json" "$@" | grep -E '^(SKELETON|ANIM|GRAFT|SUMMARY)' || true
  # One draw per material per mesh (VRoid hair is dozens of primitives); clips are untouched.
  python3 living/tools/merge_primitives.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp"
  mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
done
