#!/usr/bin/env bash
# Regenerate the outfit pieces for the look-dev VRoid characters (git-ignored output): every
# piece of living/tools/blender/outfits.py fitted and skinned to each living/game/assets/lookdev/
# vroid-*.glb, written to living/game/assets/lookdev/outfits/<style>/<piece>-<base>.glb, with
# outfits.json listing them. `--check DIR` also renders each base in its cyberpunk and steampunk
# sets (Workbench: rest, idle and walk; front, side and back) from the animated characters in
# lookdev/anim/ (gen_anim.sh), and prints how far each piece stands from the posed body.
# Usage: living/tools/blender/gen_outfits.sh [--check DIR]
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=living/game/assets/lookdev
out=$src/outfits
blender=${BLENDER:-blender}
check=""
[ "${1:-}" = "--check" ] && check=${2:?--check needs a directory}
rm -rf "$out"
mkdir -p "$out"
# One base at a time: each run merges its pieces into outfits.json.
for f in "$src"/vroid-*.glb; do
  "$blender" -b --python-exit-code 1 -P living/tools/blender/outfits.py -- --base "$f" --out "$out" 2>&1 | grep -E '^(OUTFIT|SPLIT|INDEX)|Error|Traceback' | grep -v OpenColorIO || true
done
[ -n "$check" ] || exit 0
mkdir -p "$check"
sets=(
  "cyberpunk cropped_jacket,high_collar,visor,glow_trim,cargo_straps"
  "steampunk long_coat,waistcoat,top_hat,brass_goggles,gloves,boots"
  "steampunk2 waistcoat,bowler,gloves,boots"
)
for f in "$src"/vroid-*.glb; do
  base=$(basename "$f" .glb)
  anim=$src/anim/$base.glb
  [ -f "$anim" ] || { echo "no $anim (run gen_anim.sh) — skipping its check"; continue; }
  for s in "${sets[@]}"; do
    read -r name pieces <<<"$s"
    style=${name%2}
    files=$(echo "$pieces" | tr , '\n' | sed "s|.*|$out/$style/&-$base.glb|" | paste -sd, -)
    "$blender" -b --python-exit-code 1 -P living/tools/blender/outfits_check.py -- --anim "$anim" --pieces "$files" \
      --out "$check/$name-$base" 2>&1 | grep -E '^FIT|Error|Traceback' | grep -v OpenColorIO || true
    python3 living/tools/contact_sheet.py "$check/sheet-$name-$base.png" "$check/$name-$base"-[0-9][0-9]-*.png --cols 9 --cell 280x430 >/dev/null
  done
done
ls "$check"/sheet-*.png
