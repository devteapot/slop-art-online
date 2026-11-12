#!/usr/bin/env bash
# Generate people with the character generator (living/tools/blender/person.py, docs/CHARACTERS.md)
# and run them through the steps every character base goes through (as gen_anim.sh does for the
# VRoid bases): animate.py's clip library, merge_primitives.py, face_normals.py.
# Output is git-ignored: lookdev/own-<name>.glb with <name>.params.json (the person's full
# parameters and the game recipe's height and proportions) and <name>.atlas.png (the painted face)
# beside it, and lookdev/anim/own-<name>.{glb,clips.json,face.png}, which is what the game loads.
# Both copies are finished the same way (shading data, the person's identity on the bones); the
# one under anim/ has the clips.
# Usage: living/tools/blender/gen_person.sh [PERSON ...]     (default: the presets)
#   PERSON is [NAME=]SPEC. SPEC is a preset (man, woman, elder, youth, boy, girl, heavy), `<seed>:<kind>` (kind: man,
#   woman, elder_man, elder_woman, boy, girl), a seed alone, or a parameter file (*.json). NAME
#   defaults to the spec (a file's own name).
#   PERSON_ARGS=<args>  more arguments for person.py (e.g. "--set age=70 --set beard.style=full")
#   LOD=<list>          which models to make, comma-separated (default near): `near` the full model;
#                       `far` the far model (about 6,000 triangles, for beyond 10 m) as a character
#                       file of its own, lookdev/far/own-<name>.glb and lookdev/far/anim/…, with the
#                       same clips; `both` one file with the two on one skeleton, the far model's
#                       meshes named Far* (for a client that switches them by distance; today's
#                       client would draw both), as lookdev/lod/own-<name>.glb and lookdev/lod/anim/…
#   CLIPS=none          bake no clips into the files: a person's clips then come from the one
#                       shared file (lookdev/anim/own-clips.glb, share.py clips), as the client
#                       reads them since crowd-1. The default still bakes the library into each
#                       file, for a client or a tool that reads a file's own clips
#   MORPHS=client       keep only the expressions the game drives (the blink and the open mouth);
#                       the default keeps all fifteen
#   SHADOWS=ellipsoid   keep face_normals.py's ellipsoid normals and shadow map on a typed head,
#                       where the default is the type's designed shadows (face_shadow.py)
#   IDENTITY=bake       build a person's identity values into the vertices (person.py --bake).
#                       The default leaves the type's mesh as it is and moves the identity bones
#                       in the file (compose.py), which is what the client does to a type's file
#   ANIMATE=<file>      the animate.py that bakes the clips (default: this folder's), to bake a
#                       set with an earlier one for a comparison (docs/CHARACTERS.md, "Motions on
#                       generated people")
#   KIMODO_DIR=<dir>    the library's generated NPZs (default .local/kimodo/outputs/library)
#   ONLY=<clips>        comma-separated library entries (default: the whole library, clips.json);
#                       `present` takes every entry whose takes are all in KIMODO_DIR, for a
#                       machine whose copy of the library is behind clips.json
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=living/game/assets/lookdev
blender=${BLENDER:-blender}
animate=${ANIMATE:-living/tools/blender/animate.py}
kimodo=${KIMODO_DIR:-.local/kimodo/outputs/library}
only=${ONLY:-}
if [ "$only" = present ]; then
  only=$(python3 - "$kimodo" <<'PY'
import json, os, sys
have = set(os.listdir(sys.argv[1]))
clips = json.load(open("living/tools/blender/clips.json"))["clips"]
print(",".join(c["name"] for c in clips if all(f"{c['name']}_s{s}.npz" in have for s in c.get("seeds", []))))
PY
)
  echo "gen_person: baking the $(echo "$only" | tr ',' '\n' | wc -l) library entries present in $kimodo" >&2
fi
people=("$@")
[ ${#people[@]} -gt 0 ] || people=(man woman elder youth boy girl heavy)
mkdir -p "$src/anim"
IFS=, read -r -a lods <<< "${LOD:-near}"
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
  for lod in "${lods[@]}"; do
    case "$lod" in near) dir=$src ;; far) dir=$src/far ;; both) dir=$src/lod ;; *) echo "gen_person: LOD: $lod is not near, far or both" >&2; exit 1 ;; esac
    mkdir -p "$dir/anim"
    # shellcheck disable=SC2086
    if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/person.py -- "${arg[@]}" ${PERSON_ARGS:-} --lod "$lod" --morphs "${MORPHS:-all}" $([ "${IDENTITY:-bones}" = bake ] && echo --bake) --out "$dir/$name.glb" > "$log" 2>&1; then
      grep -v OpenColorIO "$log" | tail -30; rm -f "$log"; exit 1
    fi
    grep -E '^PERSON' "$log" || true
    if [ "${CLIPS:-library}" = none ]; then
      cp "$dir/$name.glb" "$dir/anim/$name.glb"
      rm -f "$dir/anim/$name.clips.json"
    else
      if ! "$blender" -b --python-exit-code 1 -P "$animate" -- --in "$dir/$name.glb" --out "$dir/anim/$name.glb" \
        --library living/tools/blender/clips.json --summary "$dir/anim/$name.clips.json" --kimodo-dir "$kimodo" ${only:+--only "$only"} > "$log" 2>&1; then
        grep -v "OpenColorIO\|^ANIM" "$log" | tail -30; rm -f "$log"; exit 1
      fi
      grep -E '^(SKELETON|GRAFT|SUMMARY)' "$log" | cut -c1-220 || true
    fi
    # The copy the game draws, and then the builder's own copy beside it, are finished the same
    # way: shown by itself, an unfinished file shades with a straight split down the face and
    # has the type's face and not the person's.
    for f in "$dir/anim/$name.glb" "$dir/$name.glb"; do
      python3 living/tools/merge_primitives.py "$f" "$f.tmp" && mv "$f.tmp" "$f"
      python3 living/tools/face_normals.py "$f" "$f.tmp" --png "${f%.glb}.face.png" && mv "$f.tmp" "$f"
      # The strand texture is the same for everyone: every file names the one copy (share.py).
      [ -f "$src/strands.png" ] || cp "$dir/strands.png" "$src/strands.png"
      python3 living/tools/characters/share.py strands --shared "$src/strands.png" "$f" > /dev/null
      # A face type's head takes its designed shadows: the planar proxy's normals and the type's
      # drawn threshold map (face_shadow.py), in place of the ellipsoid's. SHADOWS=ellipsoid keeps
      # face_normals.py's, to compare.
      if [ "${SHADOWS:-designed}" = designed ]; then
        python3 living/tools/characters/face_shadow.py --if-typed "$f" --png "${f%.glb}.face.png" > /dev/null
      fi
      # One smoothed direction a point for the outline, written once here (outline_normals.py).
      python3 living/tools/characters/outline_normals.py "$f" > /dev/null
      # A person of a face type: the type's mesh with its identity bones moved, as the client
      # composes one (compose.py). Last, so the designed normals are the type's own.
      if [ "${IDENTITY:-bones}" != bake ] && grep -q '"identity"' "$dir/$name.params.json"; then
        python3 living/tools/characters/compose.py "$f" "$f" --params "$dir/$name.params.json"
      fi
    done
  done
  rm -f "$log"
done
