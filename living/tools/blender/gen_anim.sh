#!/usr/bin/env bash
# Regenerate the animated VRoid characters (git-ignored output): each look-dev VRoid GLB gets the
# clips from animate.py, written to living/game/assets/lookdev/anim/ under the same file name.
# Usage: living/tools/blender/gen_anim.sh [extra animate.py args, e.g. --clips idle,walk]
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=living/game/assets/lookdev
blender=${BLENDER:-blender}
mkdir -p "$src/anim"
for f in "$src"/vroid-*.glb; do
  "$blender" -b --python-exit-code 1 -P living/tools/blender/animate.py -- \
    --in "$f" --out "$src/anim/$(basename "$f")" "$@" | grep -E '^(SKELETON|ANIM|GRAFT)' || true
done
