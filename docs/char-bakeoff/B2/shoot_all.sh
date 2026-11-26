#!/usr/bin/env bash
# Track B2: build, photograph and lay out everything. Run from the worktree's root:
#   docs/char-bakeoff/B2/shoot_all.sh [WORK_DIR]     (default .local/b2)
# Needs Blender (through the dev-box wrapper on PATH), Pillow, and the game built into CARGO_TARGET_DIR.
set -euo pipefail
W=${1:-.local/b2}; B=docs/char-bakeoff/B2; O=$PWD/$W/out
export PATH=~/.local/share/slop-tools/build-bin:$PATH JOBS=3 CARGO_BUILD_JOBS=8 CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$PWD/.local/target}
q() { grep -E "Traceback|Error:|line [0-9]+,|B2 " | grep -v OCIO || true; }
python3 $B/facetex.py $W/out >/dev/null
blender -b --python $B/base.py -- $W/out 2>&1 | q
rm -rf $W/shoot $W/full; mkdir -p $W/pv
~/.local/state/bakeoff/shoot.sh $W/shoot $O/b2-woman.glb $O/b2-man.glb $O/b2-elder.glb $O/b2-child.glb $O/b2-base.glb 2>&1 | grep -E "ERROR|panicked" || true
F="$O/b2-woman.glb,$O/b2-man.glb,$O/b2-elder.glb,$O/b2-child.glb"
LIVING_GAME_SIZE=900x1200 LIVING_GAME_HOUR=11 LIVING_GAME_DAY_MINUTES=0 \
  LIVING_GAME_VIEW_SHOTS="idle@1.0/front,idle@1.0/three-quarter,idle@1.0/back,run@0.3/three-quarter,sit_ground@1.0/three-quarter" \
  flock -s ~/.local/state/slop-build/gate.lock living/tools/view_assets.sh $W/full "$F" 2>&1 | grep -E "ERROR|panicked" || true
LIVING_GAME_SIZE=900x1200 LIVING_GAME_HOUR=11 LIVING_GAME_DAY_MINUTES=0 LIVING_GAME_VIEW_CLIP=bind \
  LIVING_GAME_VIEW_SHOTS="front,three-quarter,side,back" \
  flock -s ~/.local/state/slop-build/gate.lock living/tools/view_assets.sh $W/fullbind "$O/b2-woman.glb" 2>&1 | grep -E "ERROR|panicked" || true
for f in $W/fullbind/b2-woman/[0-9]*.png; do cp "$f" "$W/full/b2-woman/9$(basename "$f" | cut -c2-)"; done
blender -b $W/out/b2-woman.blend --python $B/preview.py -- $W/pv/wire up_tq,lo_tq,hand wire 2>&1 | q
# the same person at one subdivision (a quarter of the body's triangles), for the play distances
mkdir -p $W/out-l1 && cp $W/out/face-*.png $W/out-l1/
B2_LEVEL=1 blender -b --python $B/base.py -- $W/out-l1 2>&1 | q
mkdir -p $W/l1 && cp $W/out-l1/b2-woman.glb $W/l1/b2-woman-l1.glb
LIVING_GAME_SIZE=1600x900 LIVING_GAME_HOUR=11 LIVING_GAME_DAY_MINUTES=0 \
  LIVING_GAME_VIEW_SHOTS="idle@1.0/0:8:0.22:0.88,idle@1.0/near@0,idle@1.0/middle@0,idle@1.0/front" \
  flock -s ~/.local/state/slop-build/gate.lock living/tools/view_assets.sh $W/l1shots "$PWD/$W/l1/b2-woman-l1.glb" 2>&1 | grep -E "ERROR|panicked" || true
cp $W/out-l1/report.json $W/out/report-l1.json
blender -b $W/out/b2-woman.blend --python $B/preview.py -- $W/pv/cage tq wire cage 2>&1 | q
blender -b $W/out/b2-base.blend --python $B/variety.py -- $W/variety $W/out 2>&1 | q > $W/variety.log
python3 - "$W" <<'PY'
import sys
from PIL import Image
d = sys.argv[1] + '/variety/'; ims = [Image.open(d + 'v%02d.png' % i) for i in range(16)]
w, h = ims[0].size; s = Image.new('RGB', (w * 8, h * 2))
for i, im in enumerate(ims): s.paste(im, ((i % 8) * w, (i // 8) * h))
s.save(sys.argv[1] + '/variety.png')
PY
python3 $B/sheet.py $W/shoot $W/full $W/pv $W/variety.png $W/out/report.json $B/contact-sheet.jpg $W/l1shots $W/out/report-l1.json
cp $W/out/report.json $B/report.json; cp $W/out/report-l1.json $B/report-l1.json
