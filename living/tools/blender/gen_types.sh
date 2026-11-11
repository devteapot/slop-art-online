#!/usr/bin/env bash
# Write the face types' files (docs/CHARACTERS.md, "The client format"): for each type of
# living/tools/characters/types.json, lookdev/types/<type>.glb with <type>.face.png beside it.
# Output is git-ignored. A type's file holds the J_Bip_* skeleton, the identity bones and the eye
# bones at rest; the type's head (skin, eyes, lines, skin under the jaw) with the two expressions
# the game drives; its neck and hands; the far head, neck and hands as the FarSkin mesh on the
# same skeleton; the designed face normals and shadow map (face_normals.py) and the outline
# normals (outline_normals.py). It holds no hair, no clothes and no clips: clips live once in
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
  python3 living/tools/characters/outline_normals.py "$out/$t.glb" > /dev/null
  rm -f "$out/$t.atlas.png" "$out/$t.far.png" "$log"
  python3 living/tools/characters/share.py list "$out/$t.glb" | head -1
}
export -f one
printf '%s\n' "${types[@]}" | xargs -P "${JOBS:-6}" -I{} bash -c 'one "$@"' _ {} "$out" "$blender"
rm -f "$out/strands.png"
