#!/usr/bin/env bash
# Write the shared hair styles' files (docs/CHARACTERS.md, "Hair styles"): for each style,
# lookdev/styles/hair/<style>.glb. Output is git-ignored. A style's file holds the hair alone, built
# once on the standard head (person_params.STYLE_HEAD): the `Hair` mesh and, on the same skeleton,
# its far mesh `FarHair`; the J_Bip_* skeleton and the identity bones it is weighted to, with its
# spring chains under J_Id_Cranium; neutral shades for the client's tag to colour; outline normals
# and widths. It holds no head, no clips and no clothes. The strand picture is the one shared file.
# A person wears it on any face type: the type's file carries the fit (hair_fit.py), and
# compose.py --hair shows the rule.
# Usage: living/tools/blender/gen_styles.sh [STYLE ...]     (default: every style)
#   JOBS=<n>     how many to build at once (default 6)
#   OUT=<dir>    where to write (default living/game/assets/lookdev/styles/hair)
set -euo pipefail
cd "$(dirname "$0")/../../.."
out=${OUT:-living/game/assets/lookdev/styles/hair}
shared=living/game/assets/lookdev/strands.png
blender=${BLENDER:-blender}
mkdir -p "$out"
styles=("$@")
if [ ${#styles[@]} -eq 0 ]; then
  mapfile -t styles < <(python3 -c "import sys; sys.path.insert(0, 'living/tools/blender'); sys.path.insert(0, 'living/tools/characters'); import person_params; print('\n'.join(person_params.STYLES))")
fi
one() {
  s=$1; out=$2; blender=$3; shared=$4
  log=$(mktemp); tmp=$(mktemp -d)
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/person.py -- --variant "style:$s" --parts hair --lod both --out "$tmp/$s.glb" > "$log" 2>&1; then
    grep -v OpenColorIO "$log" | tail -30; rm -rf "$log" "$tmp"; return 1
  fi
  python3 living/tools/merge_primitives.py "$tmp/$s.glb" "$out/$s.glb" > /dev/null
  [ -f "$shared" ] || cp "$tmp/strands.png" "$shared"
  python3 living/tools/characters/share.py strands --shared "$shared" "$out/$s.glb" > /dev/null
  python3 living/tools/characters/outline_normals.py "$out/$s.glb" > /dev/null
  rm -rf "$log" "$tmp"
  python3 living/tools/characters/share.py list "$out/$s.glb" | head -1
}
export -f one
printf '%s\n' "${styles[@]}" | xargs -P "${JOBS:-6}" -I{} bash -c 'one "$@"' _ {} "$out" "$blender" "$shared"
