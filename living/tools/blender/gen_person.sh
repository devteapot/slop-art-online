#!/usr/bin/env bash
# Spike (branch char-spike): generate the scripted people (living/tools/blender/person.py) and run
# them through the same steps as the VRoid bases (gen_anim.sh): animate.py's clip library,
# merge_primitives.py, face_normals.py. Output is git-ignored: lookdev/own-<variant>.glb and
# lookdev/anim/own-<variant>.{glb,clips.json,face.png}.
# Usage: living/tools/blender/gen_person.sh [variant ...]     (default: every variant)
#   KIMODO_DIR=<dir>  the library's generated NPZs (default .local/kimodo/outputs/library)
#   ONLY=<clips>      comma-separated library entries (default: those the spike's page shows; the
#                     archived cache of 2026-11-11 lacks gather, work, eat, play, the ground sits
#                     and dodge, so the whole library cannot be built from it)
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=living/game/assets/lookdev
blender=${BLENDER:-blender}
kimodo=${KIMODO_DIR:-.local/kimodo/outputs/library}
only=${ONLY:-idle,idle_look,walk,walk_brisk,run,run_fast,talk,wave,sit_down,sit_idle,stand_up,sword_slash,sword_overhead}
variants=("$@")
[ ${#variants[@]} -gt 0 ] || variants=(man youth elder woman)
mkdir -p "$src/anim"
for v in "${variants[@]}"; do
  name=own-${v//:/-}
  log=$(mktemp)
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/person.py -- --variant "$v" --out "$src/$name.glb" > "$log" 2>&1; then
    grep -v OpenColorIO "$log" | tail -30; rm -f "$log"; exit 1
  fi
  grep -E '^PERSON' "$log" || true
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/animate.py -- --in "$src/$name.glb" --out "$src/anim/$name.glb" \
    --library living/tools/blender/clips.json --summary "$src/anim/$name.clips.json" --kimodo-dir "$kimodo" --only "$only" > "$log" 2>&1; then
    grep -v "OpenColorIO\|^ANIM" "$log" | tail -30; rm -f "$log"; exit 1
  fi
  grep -E '^(SKELETON|GRAFT|SUMMARY)' "$log" | cut -c1-220 || true
  rm -f "$log"
  python3 living/tools/merge_primitives.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp" && mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
  python3 living/tools/face_normals.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp" --png "$src/anim/$name.face.png" && mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
done
