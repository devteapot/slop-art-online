#!/usr/bin/env bash
# Write the face types' files (docs/CHARACTERS.md, "The client format"): for each type of
# living/tools/characters/types.json, lookdev/types/<type>.glb with <type>.face.png beside it.
# Output is git-ignored. A type's file holds the J_Bip_* skeleton, the identity bones and the eye
# bones at rest; the type's head (skin, eyes, lines, skin under the jaw) with the two expressions
# the game drives; its neck and hands; the far head, neck and hands as the FarSkin mesh on the
# same skeleton; the designed face normals and shadow map (face_normals.py) and the outline
# normals (outline_normals.py). Its far head's picture and its lip layer are tiles of two pages
# every type shares (lookdev/pages/types-far.png, types-tint.png; share.py types), and its iris is
# one picture every type names (lookdev/pages/types-iris.png). It holds no
# hair, no clothes and no clips: clips live once in
# lookdev/anim/own-clips.glb (share.py clips), and a person is this file with its identity bones
# moved (compose.py shows the rule).
# Usage: living/tools/blender/gen_types.sh [TYPE ...]     (default: every type)
#   JOBS=<n>     how many to build at once (default 6)
#   OUT=<dir>    where to write (default living/game/assets/lookdev/types)
set -euo pipefail
cd "$(dirname "$0")/../../.."
out=${OUT:-living/game/assets/lookdev/types}
blender=${BLENDER:-blender}
mkdir -p "$out"
types=("$@")
if [ ${#types[@]} -eq 0 ]; then
  mapfile -t types < <(python3 -c "import json; print('\n'.join(json.load(open('living/tools/characters/types.json'))['types']))")
fi
one() {
  t=$1; out=$2; blender=$3
  log=$(mktemp)
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/person.py -- --variant "type:$t" --parts head --lod both --morphs client --out "$out/$t.glb" > "$log" 2>&1; then
    grep -v OpenColorIO "$log" | tail -30; rm -f "$log"; return 1
  fi
  python3 living/tools/merge_primitives.py "$out/$t.glb" "$out/$t.glb.tmp" > /dev/null && mv "$out/$t.glb.tmp" "$out/$t.glb"
  python3 living/tools/face_normals.py "$out/$t.glb" "$out/$t.glb.tmp" --png "$out/$t.face.png" > /dev/null && mv "$out/$t.glb.tmp" "$out/$t.glb"
  # How the shared hair styles' head is laid onto this type's (hair_fit.py), in the scene's extras.
  python3 living/tools/characters/hair_fit.py "$t" "$out/$t.glb" > /dev/null
  # Designed shadows: the planar proxy's normals and the drawn threshold map, one map a type.
  python3 living/tools/characters/face_shadow.py "$out/$t.glb" --png "$out/$t.face.png" > /dev/null
  python3 living/tools/characters/outline_normals.py "$out/$t.glb" > /dev/null
  rm -f "$out/$t.atlas.png" "$out/$t.far.png" "$out/$t.tint.png" "$out/$t.iris.png" "$log"
  python3 living/tools/characters/share.py list "$out/$t.glb" | head -1
}
export -f one
printf '%s\n' "${types[@]}" | xargs -P "${JOBS:-6}" -I{} bash -c 'one "$@"' _ {} "$out" "$blender"
rm -f "$out/strands.png"
# The far heads' pictures and the lip layers go on two pages every type shares (share.py types),
# beside the types' folder; a type built again goes back into its own tile.
files=()
for t in "${types[@]}"; do files+=("$out/$t.glb"); done
python3 living/tools/characters/share.py types --dir "$(dirname "$out")/pages" "${files[@]}"
# Every type's iris is the one shared picture, with the source colour that the lines' eye
# colours are worked out from (person_params.eye_line_colour).
python3 living/tools/characters/eye_colours.py "$out" --check | tail -1
