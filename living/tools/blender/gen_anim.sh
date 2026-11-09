#!/usr/bin/env bash
# Regenerate the animated VRoid characters (git-ignored output): each look-dev VRoid GLB gets the
# clip library (living/tools/blender/clips.json) from animate.py, written to
# living/game/assets/lookdev/anim/ under the same file name, with <name>.clips.json beside it
# (each clip's length, loop, natural and baked speed, and source), then merges each file's
# same-material primitives (living/tools/merge_primitives.py) to cut draw calls, and adds the anime
# face data (living/tools/face_normals.py: flattened face normals and <name>.face.png).
# Also makes the wolf and the deer (wolf.py, deer.py on quadruped.py: their own rigs and keyed
# clips, no Kimodo).
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
  log=$(mktemp)
  # Fail on Blender's own status; the filter below only trims what is printed.
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/animate.py -- \
    --in "$f" --out "$src/anim/$name.glb" --library living/tools/blender/clips.json \
    --summary "$src/anim/$name.clips.json" "$@" > "$log" 2>&1; then
    grep -v OpenColorIO "$log" | tail -30
    rm -f "$log"
    exit 1
  fi
  grep -E '^(SKELETON|ANIM|GRAFT|SUMMARY)' "$log" || true
  rm -f "$log"
  # One draw per material per mesh (VRoid hair is dozens of primitives); clips are untouched.
  python3 living/tools/merge_primitives.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp"
  mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
  # Anime face shading: flattened face normals, the head's forward, and the face's shadow map
  # ($name.face.png, read by lookdev::convert).
  python3 living/tools/face_normals.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp" --png "$src/anim/$name.face.png"
  mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
done
# The wolf: a procedural quadruped rig with keyed clips (living/tools/blender/wolf.py), with
# wolf.clips.json beside it.
"$blender" -b --python-exit-code 1 -P living/tools/blender/wolf.py -- \
  --out "$src/anim/wolf.glb" --summary "$src/anim/wolf.clips.json" 2>&1 | grep -E "^(CLIP|WOLF)|Error|Traceback" || true
# The deer, on the same quadruped machinery, with deer.clips.json beside it.
"$blender" -b --python-exit-code 1 -P living/tools/blender/deer.py -- \
  --out "$src/anim/deer.glb" --summary "$src/anim/deer.clips.json" 2>&1 | grep -E "^(CLIP|DEER)|Error|Traceback" || true
# Marker sanity (living/tools/marker_check.py): a summary per character and gait; warnings for
# split, short or long contacts, unpaired feet, an unsynced phase 0, a clip longer or shorter than
# its sidecar or planted feet that slide in the baked take. Fails only on missing markers.
python3 living/tools/marker_check.py "$src"/anim/*.glb
