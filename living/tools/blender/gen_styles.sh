#!/usr/bin/env bash
# Write the shared style files (docs/CHARACTERS.md, "Hair styles" and "Outfit pieces"). Output is
# git-ignored.
# - lookdev/styles/hair/<style>.glb: a hair style, alone, built once on the standard head
#   (person_params.STYLE_HEAD): the `Hair` mesh, its tie in cloth where it has one, and on the same
#   skeleton the far mesh `FarHair`; spring chains under J_Id_Cranium; neutral shades for the
#   client's tag. `<style>.2` and `.3` are other cuts of the style (another length, parting and
#   fringe); `<style>.cap.glb` is the style as worn under a cap, and `<style>[.N].collar.glb` a
#   style that hangs past the collar as worn over a coat. A last `.m` is a style that lies on the
#   back as combed over a man's back (the others lie on a woman's).
# - lookdev/styles/outfit/<piece>.glb: an outfit piece, alone, built once at the standard build:
#   the `Cloth` mesh and its far mesh `FarCloth`, skinned to the J_Bip_* bones every person has.
#   Body pieces come as `-m` and `-f`; `cap` and `kerchief` sit on the standard head.
# - lookdev/styles/overlay/<type>/<name>.glb: a detail a person has and a type does not (a beard
#   form, stubble, age lines, freckles), as a thin layer over that type's own face: the `Overlay`
#   mesh with the face's weights and its two expressions, and a grey picture with an alpha for the
#   client's tag to tint. Lines and freckles also get the type's shadow map beside them.
# No file holds a head, a body or clips. The strand picture is the one shared file. A person wears
# them on any face type and build: compose.py shows the rule.
# Usage: living/tools/blender/gen_styles.sh [hair|outfit|overlay|NAME ...]     (default: everything)
#   JOBS=<n>     how many to build at once (default 6)
#   OUT=<dir>    where to write (default living/game/assets/lookdev/styles)
set -euo pipefail
cd "$(dirname "$0")/../../.."
root=${OUT:-living/game/assets/lookdev/styles}
shared=living/game/assets/lookdev/strands.png
blender=${BLENDER:-blender}
mkdir -p "$root/hair" "$root/outfit" "$root/overlay"
names() {
  python3 -c "
import sys; sys.path.insert(0, 'living/tools/blender'); sys.path.insert(0, 'living/tools/characters'); import person_params as p
hair = ['hair/' + s + ('' if c == 1 else '.' + str(c)) for s in p.STYLES for c in range(1, (1 if s == 'kerchief' else p.CUTS) + 1)] + ['hair/' + s + ('' if c == 1 else '.' + str(c)) + '.collar' for s in p.COLLARED for c in range(1, p.CUTS + 1)] + ['hair/' + s + '.cap' for s in p.CAPPED]
hair += ['hair/' + n[5:] + '.m' for n in hair if n[5:].split('.')[0] in p.MAN_BACKED and not n.endswith('.cap')]
outfit = ['outfit/' + n + f for n in p.PIECES for f in ('-m', '-f')] + ['outfit/' + n for n in p.HEAD_PIECES]
import face_types
types = face_types.load()['types']
overlay = ['overlay/' + t + '/' + n for n in p.OVERLAYS for t in p.overlay_types(n, types)]
print('\\n'.join(dict(hair=hair, outfit=outfit, overlay=overlay, all=hair + outfit + overlay)['$1']))"
}
items=()
[ $# -gt 0 ] || set -- all
for a in "$@"; do
  case "$a" in
    hair|outfit|overlay|all) while read -r n; do items+=("$n"); done < <(names "$a") ;;
    */*) items+=("$a") ;;
    *) echo "gen_styles: name a file as hair/<style> or outfit/<piece>" >&2; exit 1 ;;
  esac
done
one() {
  item=$1; root=$2; blender=$3; shared=$4
  kind=${item%%/*}; n=${item#*/}
  log=$(mktemp); tmp=$(mktemp -d)
  lod=both
  if [ "$kind" = hair ]; then
    args=(--variant "style:$n" --parts hair)
  elif [ "$kind" = overlay ]; then
    t=${n%%/*}; o=${n#*/}; lod=near
    case "$o" in beard_*) lod=both ;; esac  # a beard has a far mesh too, for the far head
    mkdir -p "$root/overlay/$t"
    args=(--variant "overlay:$t:$o" --parts overlay --overlay "$o" --morphs client)
  else
    keep=$(python3 -c "import sys; sys.path.insert(0, 'living/tools/blender'); sys.path.insert(0, 'living/tools/characters'); import person_params as p; print(','.join(p.piece_parts('$n')))")
    args=(--variant "piece:$n" --parts keep --keep "$keep")
  fi
  if ! "$blender" -b --python-exit-code 1 -P living/tools/blender/person.py -- "${args[@]}" --lod "$lod" --out "$tmp/x.glb" > "$log" 2>&1; then
    grep -v OpenColorIO "$log" | tail -30; rm -rf "$log" "$tmp"; return 1
  fi
  python3 living/tools/merge_primitives.py "$tmp/x.glb" "$root/$item.glb" > /dev/null
  # One shading mean a class, so the client can share one material between a class's files.
  python3 living/tools/characters/shade_mean.py "$kind" "$root/$item.glb" > /dev/null
  if [ "$kind" = hair ]; then
    [ -f "$shared" ] || cp "$tmp/strands.png" "$shared"
    python3 living/tools/characters/share.py strands --shared "$shared" "$root/$item.glb" > /dev/null
  fi
  if [ "$kind" = overlay ]; then
    case "${n#*/}" in
      lines|freckles)
        # One fixed colour in a material the client draws unshaded: no shadow map goes with it.
        rm -f "$root/$item.face.png" ;;
      *)
        # A layer lit as the face is needs the face's forward and the type's map.
        python3 living/tools/face_normals.py "$root/$item.glb" "$root/$item.glb" --png "$root/$item.face.png" > /dev/null
        types=$(dirname "$root")/types
        if [ -f "$root/$item.face.png" ] && [ -f "$types/${n%%/*}.face.png" ]; then cp "$types/${n%%/*}.face.png" "$root/$item.face.png"; fi ;;
    esac
  fi
  python3 living/tools/characters/outline_normals.py "$root/$item.glb" > /dev/null
  rm -rf "$log" "$tmp"
  python3 living/tools/characters/share.py list "$root/$item.glb" | head -1
}
export -f one
printf '%s\n' "${items[@]}" | xargs -P "${JOBS:-6}" -I{} bash -c 'one "$@"' _ {} "$root" "$blender" "$shared"
# An outfit piece's file says where it is worn and how far out: its slot and layer, in the
# scene's extras (look_lines.py wear; person_params.PIECE_WEAR).
if [ -d "$root/outfit" ]; then python3 living/tools/characters/look_lines.py wear "$root" | tail -1; fi
