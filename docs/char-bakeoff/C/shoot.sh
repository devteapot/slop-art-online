#!/usr/bin/env bash
# Shared character bake-off photographer (dev-box, 2026-11-26)
# Usage: shoot.sh OUT_DIR FILE [FILE...]
#   FILE may be a .glb/.vrm path, look:<key>, or recipe:<name>.
#
# Sources shots.env, runs living/tools/view_assets.sh for both the animated shots
# (idle + play cameras + walk) and the bind pose (LIVING_GAME_VIEW_CLIP=bind),
# then builds one labelled contact sheet per character at OUT_DIR/<model>.png.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 OUT_DIR FILE [FILE...]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SHOTS_ENV="${SHOTS_ENV:-$SCRIPT_DIR/shots.env}"
if [ ! -f "$SHOTS_ENV" ]; then
  SHOTS_ENV="$HOME/.local/state/bakeoff/shots.env"
fi
# shellcheck source=/dev/null
source "$SHOTS_ENV"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ ! -x "$REPO_ROOT/living/tools/view_assets.sh" ]; then
  echo "shoot.sh: run from a slop-art-online worktree (missing living/tools/view_assets.sh under $REPO_ROOT)" >&2
  exit 1
fi

OUT_DIR="$(mkdir -p "$1" && cd "$1" && pwd)"
shift

# Join FILE arguments with commas for view_assets.sh
FILES=""
for arg in "$@"; do
  if [ -n "$FILES" ]; then
    FILES="$FILES,$arg"
  else
    FILES="$arg"
  fi
done

export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-8}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$REPO_ROOT/.local/target}"
mkdir -p "$CARGO_TARGET_DIR"

GATE_LOCK="$HOME/.local/state/slop-build/gate.lock"
run_view() {
  local target_dir="$1"
  shift
  if [ -d "$(dirname "$GATE_LOCK")" ]; then
    flock -s "$GATE_LOCK" env "$@" "$REPO_ROOT/living/tools/view_assets.sh" "$target_dir" "$FILES"
  else
    env "$@" "$REPO_ROOT/living/tools/view_assets.sh" "$target_dir" "$FILES"
  fi
}

ANIM_DIR="$OUT_DIR/_anim"
BIND_DIR="$OUT_DIR/_bind"
rm -rf "$ANIM_DIR" "$BIND_DIR"
mkdir -p "$ANIM_DIR" "$BIND_DIR"

echo "shoot.sh: [1/2] animated shots -> $ANIM_DIR"
run_view "$ANIM_DIR" \
  LIVING_GAME_SIZE="$LIVING_GAME_SIZE" \
  LIVING_GAME_HOUR="${LIVING_GAME_HOUR:-11}" \
  LIVING_GAME_DAY_MINUTES="${LIVING_GAME_DAY_MINUTES:-0}" \
  LIVING_GAME_VIEW_SHOTS="$LIVING_GAME_VIEW_SHOTS"

echo "shoot.sh: [2/2] bind shots -> $BIND_DIR"
run_view "$BIND_DIR" \
  LIVING_GAME_SIZE="$LIVING_GAME_SIZE" \
  LIVING_GAME_HOUR="${LIVING_GAME_HOUR:-11}" \
  LIVING_GAME_DAY_MINUTES="${LIVING_GAME_DAY_MINUTES:-0}" \
  LIVING_GAME_VIEW_CLIP="bind" \
  LIVING_GAME_VIEW_SHOTS="${LIVING_GAME_VIEW_SHOTS_BIND:-front,three-quarter,back}"

# Merge per-character stills + report.json into OUT_DIR and build one labelled contact sheet per character.
python3 - "$OUT_DIR" "$ANIM_DIR" "$BIND_DIR" <<'PY'
import glob
import json
import os
import re
import shutil
import sys
from PIL import Image, ImageDraw, ImageFont

out_dir, anim_dir, bind_dir = sys.argv[1:4]

def load_font(size):
    for path in (
        "/usr/share/fonts/google-droid-sans-fonts/DroidSans-Bold.ttf",
        "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
        "/usr/share/fonts/gnu-free/FreeSansBold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def pretty_label(filename, is_bind=False):
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"^\d+-", "", stem)
    if is_bind:
        stem = re.sub(r"^bind-", "", stem)
        return f"bind · {stem}"
    if stem.startswith("clip-idle@"):
        rest = stem.split("-", 2)[-1] if stem.count("-") >= 2 else stem
        if rest == "0_8_0.22_0.88":
            return "idle · face close-up"
        if rest == "near_0":
            return "idle · Near (8m)"
        if rest == "middle_0":
            return "idle · Middle (12m)"
        if rest == "game":
            return "idle · play camera (game)"
        return f"idle · {rest}"
    if stem.startswith("clip-walk-"):
        m = re.match(r"clip-walk-(\d+)-(.*)", stem)
        if m:
            return f"walk f{m.group(1)} · {m.group(2)}"
    return stem

models = sorted(
    {
        os.path.basename(d.rstrip("/"))
        for base in (anim_dir, bind_dir)
        for d in glob.glob(os.path.join(base, "*/"))
    }
)

if not models:
    print("shoot.sh: no model directories produced", file=sys.stderr)
    sys.exit(1)

# Prefer anim report.json (has clips); fall back to bind report.json.
for rep_src in (os.path.join(anim_dir, "report.json"), os.path.join(bind_dir, "report.json")):
    if os.path.exists(rep_src):
        shutil.copy2(rep_src, os.path.join(out_dir, "report.json"))
        break

font_hdr = load_font(22)
font_lbl = load_font(16)

cell_w, cell_h = 640, 360
lbl_h = 28
pad = 4
hdr_h = 40
cols = 4

sheets = []
for name in models:
    dst = os.path.join(out_dir, name)
    os.makedirs(dst, exist_ok=True)
    tiles = []

    a_dir = os.path.join(anim_dir, name)
    b_dir = os.path.join(bind_dir, name)

    for rep_src in (os.path.join(a_dir, "report.json"), os.path.join(b_dir, "report.json")):
        if os.path.exists(rep_src):
            shutil.copy2(rep_src, os.path.join(dst, "report.json"))
            break

    anim_shots = sorted(glob.glob(os.path.join(a_dir, "[0-9][0-9]-*.png")))
    bind_shots = sorted(glob.glob(os.path.join(b_dir, "[0-9][0-9]-*.png")))

    for src in anim_shots:
        bn = os.path.basename(src)
        out_p = os.path.join(dst, bn)
        shutil.copy2(src, out_p)
        tiles.append((out_p, pretty_label(bn, is_bind=False)))

    for idx, src in enumerate(bind_shots):
        bn = os.path.basename(src)
        stripped = re.sub(r"^\d+-", "", bn)
        out_bn = f"{90 + idx:02d}-bind-{stripped}"
        out_p = os.path.join(dst, out_bn)
        shutil.copy2(src, out_p)
        tiles.append((out_p, pretty_label(out_bn, is_bind=True)))

    if not tiles:
        continue

    c = min(cols, len(tiles))
    rows = (len(tiles) + c - 1) // c
    tile_w = cell_w + 2 * pad
    tile_h = cell_h + lbl_h + 2 * pad
    sheet = Image.new("RGB", (c * tile_w, hdr_h + rows * tile_h), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)

    # Header bar
    draw.rectangle([0, 0, sheet.width, hdr_h], fill=(16, 16, 20))
    meta = ""
    rep_p = os.path.join(dst, "report.json")
    if os.path.exists(rep_p):
        try:
            rep = json.load(open(rep_p))
            tris = rep.get("triangles")
            mats = len(rep.get("materials", []))
            sz = rep.get("size_m")
            if tris is not None:
                meta = f"  |  {tris:,} tris · {mats} mats"
                if isinstance(sz, list) and len(sz) == 3:
                    meta += f" · {sz[1]:.2f} m"
        except Exception:
            pass
    draw.text((12, 8), f"{name}{meta}", fill=(240, 240, 245), font=font_hdr)

    for i, (path, label) in enumerate(tiles):
        im = Image.open(path).convert("RGB")
        im.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
        gx = (i % c) * tile_w + pad
        gy = hdr_h + (i // c) * tile_h + pad
        draw.rectangle([gx, gy, gx + cell_w, gy + lbl_h], fill=(38, 38, 44))
        draw.text((gx + 8, gy + 5), label, fill=(235, 235, 240), font=font_lbl)
        ox = gx + (cell_w - im.width) // 2
        oy = gy + lbl_h + (cell_h - im.height) // 2
        sheet.paste(im, (ox, oy))

    sheet_path = os.path.join(out_dir, f"{name}.png")
    sheet.save(sheet_path)
    sheets.append(sheet_path)

for s in sheets:
    print(s)
PY
