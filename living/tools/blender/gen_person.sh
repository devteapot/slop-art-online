#!/usr/bin/env bash
# Generate people with the character generator (living/tools/blender/person.py, docs/CHARACTERS.md)
# and run them through the steps every character base goes through (as gen_anim.sh does for the
# VRoid bases): animate.py's clip library, merge_primitives.py, face_normals.py.
# Output is git-ignored: lookdev/own-<name>.glb with <name>.params.json (the person's full
# parameters and the game recipe's height and proportions) and <name>.atlas.png (the painted face)
# beside it, and lookdev/anim/own-<name>.{glb,clips.json,face.png}, which is what the game loads.
# Usage: living/tools/blender/gen_person.sh [PERSON ...]     (default: the presets)
#   PERSON is [NAME=]SPEC. SPEC is a preset (man, woman, elder, youth, boy, girl, heavy), `<seed>:<kind>` (kind: man,
#   woman, elder_man, elder_woman, boy, girl), a seed alone, or a parameter file (*.json). NAME
#   defaults to the spec (a file's own name).
#   PERSON_ARGS=<args>  more arguments for person.py (e.g. "--set age=70 --set beard.style=full")
#   KIMODO_DIR=<dir>    the library's generated NPZs (default .local/kimodo/outputs/library)
#   ONLY=<clips>        comma-separated library entries (default: the whole library, clips.json)
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=living/game/assets/lookdev
blender=${BLENDER:-blender}
kimodo=${KIMODO_DIR:-.local/kimodo/outputs/library}
only=${ONLY:-}
people=("$@")
[ ${#people[@]} -gt 0 ] || people=(man woman elder youth boy girl heavy)
mkdir -p "$src/anim"
for p in "${people[@]}"; do
  spec=${p#*=}
  case "$spec" in
    *.json) arg=(--params "$spec"); name=$(basename "$spec" .json) ;;
    *[!0-9]*) arg=(--variant "$spec"); name=${spec//:/-} ;;
    *) arg=(--seed "$spec"); name=$spec ;;
  esac
  [ "$p" = "$spec" ] || name=${p%%=*}
  name=own-$name
  log=$(mktemp)
  # shellcheck disable=SC2086
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/person.py -- "${arg[@]}" ${PERSON_ARGS:-} --out "$src/$name.glb" > "$log" 2>&1; then
    grep -v OpenColorIO "$log" | tail -30; rm -f "$log"; exit 1
  fi
  grep -E '^PERSON' "$log" || true
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/animate.py -- --in "$src/$name.glb" --out "$src/anim/$name.glb" \
    --library living/tools/blender/clips.json --summary "$src/anim/$name.clips.json" --kimodo-dir "$kimodo" ${only:+--only "$only"} > "$log" 2>&1; then
    grep -v "OpenColorIO\|^ANIM" "$log" | tail -30; rm -f "$log"; exit 1
  fi
  grep -E '^(SKELETON|GRAFT|SUMMARY)' "$log" | cut -c1-220 || true
  rm -f "$log"
  python3 living/tools/merge_primitives.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp" && mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
  python3 living/tools/face_normals.py "$src/anim/$name.glb" "$src/anim/$name.glb.tmp" --png "$src/anim/$name.face.png" && mv "$src/anim/$name.glb.tmp" "$src/anim/$name.glb"
done
