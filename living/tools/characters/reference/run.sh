#!/bin/sh
# Take the VRoid reference apart and measure it beside our generated people (docs/CHARACTER_REFERENCE.md).
#
#   living/tools/characters/reference/run.sh [OUT]      # OUT defaults to .local/ref
#
# Needs the two VRoid files (living/tools/lookdev_assets.sh puts them in
# living/game/assets/lookdev/), Blender, numpy and Pillow. Every script that reads a third-party
# file runs with `python3 -I`. The VRoid files are copied into OUT/src and never committed.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../../.." && pwd)"
out="$(mkdir -p "${1:-$root/.local/ref}" && cd "${1:-$root/.local/ref}" && pwd)"
blender="${BLENDER:-blender}"
py() { python3 -I "$@"; }
bl() { "$blender" -b --python-exit-code 1 -P "$@" > /dev/null 2>&1; }
mkdir -p "$out/src" "$out/ours" "$out/npz" "$out/dump" "$out/fig" "$out/tex"
for f in Sendagaya_Shino Vivi; do
    [ -f "$out/src/vroid-$f.glb" ] || cp "$root/living/game/assets/lookdev/vroid-$f.glb" "$out/src/"
done
cd "$root"
bl living/tools/blender/person.py -- --variant woman --out "$out/ours/woman.glb"
bl living/tools/blender/person.py -- --variant man --set beard.style=none --set beard.stubble=0 --out "$out/ours/man.glb"
cd "$out"
for n in Sendagaya_Shino:shino Vivi:vivi; do
    f="src/vroid-${n%%:*}.glb"; k="${n#*:}"
    py "$here/dump.py" "$f" > "dump/$k.txt"
    py "$here/face.py" "$f" "npz/${k}_face" > /dev/null
    py "$here/analyse.py" "npz/${k}_face" > "dump/${k}_face.txt"
    py "$here/rig.py" "$f" > "dump/${k}_rig.txt"
    py "$here/tex.py" "$f" "tex/$k"
done
# The skull's top for our heads (their skin stops at the hairline): from head_form, as the generator places it.
tops="$(cd "$root" && python3 -I -c "
import sys, json; sys.path.insert(0, 'living/tools/blender')
import person_params as pp, head_form as hf
for v in ('woman', 'man'):
    s = pp.resolve(json.load(open('$out/ours/%s.params.json' % v))['params'])
    h = hf.Head(masc=s['masc'], child=s['child'], elder=s['elder'], face=s['face'], style=s['style'])
    print(v, 1.535 + (h.top_z - h.chin_z) * s['head_scale'])
")"
top() { echo "$tops" | awk -v v="$1" '$1 == v {print $2}'; }
py "$here/measure.py" src/vroid-Sendagaya_Shino.glb npz/shino_m.json > npz/shino_m.txt
py "$here/measure.py" src/vroid-Vivi.glb npz/vivi_m.json > npz/vivi_m.txt
py "$here/measure.py" ours/woman.glb npz/woman_m.json "$(top woman)" > npz/woman_m.txt
py "$here/measure.py" ours/man.glb npz/man_m.json "$(top man)" > npz/man_m.txt
py "$here/turn.py" shino vivi woman man > dump/turn.txt
py "$here/diff.py" > dump/vivi_vs_shino.txt
py "$here/plot.py" fig/sections.png "reference (Shino)=npz/shino_m.json" "ours (woman, pass 2)=npz/woman_m.json" "ours (man, pass 2)=npz/man_m.json"
py "$here/eyesec.py" src/vroid-Sendagaya_Shino.glb fig/eye-section-shino.png -0.045
py "$here/eyesec.py" ours/woman.glb fig/eye-section-woman.png -0.0384
py "$here/sheet.py" fig/eye-sections.jpg 480 fig/eye-section-shino.png fig/eye-section-woman.png
for a in src/vroid-Sendagaya_Shino.glb:shino src/vroid-Vivi.glb:vivi ours/woman.glb:woman ours/man.glb:man; do
    "$blender" -b --python-exit-code 1 -P "$here/render.py" -- "${a%%:*}" "fig/${a#*:}" x 2>/dev/null | grep -E "^(skin|file vs|quads)" > "dump/${a#*:}_render.txt"
done
bl "$here/render2.py" -- src/vroid-Sendagaya_Shino.glb fig/shino-bs
bl "$here/render3.py" -- src/vroid-Sendagaya_Shino.glb npz/vivi_minus_shino.npy npz/shino_face.npz fig/vivi-vs-shino.png 8
B=fig/shino-bs
py "$here/grid.py" fig/shino-blendshapes.jpg 6 260 "skin weight to J_Adj_L_FaceEyeSet=$B/weight-J_Adj_L_FaceEyeSet.png" "weight to J_Adj_L_FaceEye (iris)=$B/weight-J_Adj_L_FaceEye.png" \
    "EYE_Close=$B/bs-target_12.png" "EYE_Joy=$B/bs-target_15.png" "EYE_Surprised=$B/bs-target_19.png" "EYE_Extra=$B/bs-target_20.png" "BRW_Angry=$B/bs-target_5.png" \
    "BRW_Sorrow=$B/bs-target_8.png" "BRW_Surprised=$B/bs-target_9.png" "MTH_A=$B/bs-target_29.png" "MTH_I=$B/bs-target_30.png" "MTH_U=$B/bs-target_31.png" "MTH_E=$B/bs-target_32.png" \
    "MTH_O=$B/bs-target_33.png" "MTH_Joy=$B/bs-target_26.png" "MTH_Down=$B/bs-target_22.png" "ALL_Joy=$B/bs-target_2.png" "ALL_Surprised=$B/bs-target_4.png"
py "$here/grid.py" fig/template.jpg 4 300 "Shino wire (front)=fig/shino/wire-front.png" "Vivi wire (front): the same 2,339 vertices=fig/vivi/wire-front.png" \
    "Vivi minus Shino after scale (0-8 mm)=fig/vivi-vs-shino-front.png" "the same, three-quarter=fig/vivi-vs-shino-three-quarter.png"
set --
for h in shino:Shino vivi:Vivi woman:"ours, woman" man:"ours, man (no beard)"; do
    for v in wire-front wire-three-quarter wire-side lambert-geo-three-quarter planes-three-quarter; do set -- "$@" "${h#*:} · $v=fig/${h%%:*}/$v.png"; done
done
py "$here/grid.py" fig/form-compare.jpg 5 250 "$@"
set --
for h in shino:Shino woman:"ours, woman"; do
    for v in toon-key-geo-three-quarter toon-side-geo-front toon-side-geo-three-quarter toon-side-file-three-quarter; do set -- "$@" "${h#*:} · $v=fig/${h%%:*}/$v.png"; done
done
py "$here/grid.py" fig/toon-compare.jpg 4 260 "$@"
t=tex/shino
py "$here/sheet.py" fig/shino-face-textures.jpg 330 $t/11-F00_000_Face_00.png $t/12-F00_000_00_Face_00_nml.png $t/13-F00_000_00_Face_00_out.png $t/00-F00_000_FaceMouth_00.png
py "$here/sheet.py" fig/shino-eye-textures.jpg 200 $t/05-F00_000_FaceEyeline_00.png $t/07-F00_000_FaceEyelash_00.png $t/08-F00_000_FaceBrow_00.png
py "$here/sheet.py" fig/shino-eye-textures2.jpg 220 $t/04-F00_000_EyeWhite_00.png $t/09-F00_000_EyeIris_00.png $t/10-F00_000_EyeHighlight_00.png $t/14-F00_000_00_EyeExtra_01.png $t/06-Matcap_Rim.png
py "$here/sheet.py" fig/shino-hair-textures.jpg 300 $t/25-F00_000_Hair_00_01.png $t/26-F00_000_Hair_00_nml.png $t/27-F00_000_Hair_00_spe.png $t/22-F00_000_HairBack_00.png $t/24-Matcap_RimHair.png
echo "written to $out (figures in $out/fig)"
