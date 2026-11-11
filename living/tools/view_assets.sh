#!/usr/bin/env bash
# Photograph models through the game's renderer (on a 1 m checker) and make one contact sheet per model.
# Usage: living/tools/view_assets.sh OUT_DIR FILE_OR_DIR[,FILE_OR_DIR...] [ENV_ID] [HEIGHT_M]
#   OUT_DIR/<model>/NN-<shot>.png   one image per shot
#   OUT_DIR/<model>.png             contact sheet of all shots, six per row
#   OUT_DIR/report.json             size (m), triangles, materials, vertex colours, glow, clips
# Runs headless (no window; LIVING_GAME_WINDOW=1 shows one). ImageMagick's montage makes the sheets,
# or living/tools/contact_sheet.py (Pillow) where montage is missing.
# Pick shots with LIVING_GAME_VIEW_SHOTS (default "views,clips"), for example
#   LIVING_GAME_VIEW_SHOTS="game,120:20:0.6,walk@0.5/front,walk"
# Views: front, three-quarter, side, back, above, game, or YAW:PITCH[:ZOOM]; "<clip>" is six frames
# from the side, "<clip>/<view>" from that view, "<clip>@<seconds>[/<view>]" one frame.
# LIVING_GAME_VIEW_CLIP lists the clips "clips" covers; LIVING_GAME_SIZE=WxH sets the image size.
# Honours CARGO_TARGET_DIR. For fixed shots beside an accepted version, use the asset board
# (living/tools/board/board.py, docs/ASSET_BOARD.md).
set -euo pipefail
cd "$(dirname "$0")/../.."
out=$(mkdir -p "$1" && cd "$1" && pwd)
files=$2
env_id=${3:-}
height=${4:-}
cargo build --release -q -p living-game --manifest-path living/Cargo.toml
target=${CARGO_TARGET_DIR:-living/target}
LIVING_GAME_VIEW="$files" LIVING_GAME_VIEW_OUT="$out" LIVING_GAME_VIEW_ENV="$env_id" LIVING_GAME_VIEW_HEIGHT="$height" \
  RUST_LOG=${RUST_LOG:-warn,living_game=info} "$target/release/living-game" 2>&1 | grep -E 'view:|ERROR|panicked' || true
for d in "$out"/*/; do
  name=$(basename "$d")
  shots=$(ls "$d"[0-9][0-9]-*.png 2>/dev/null || true)
  [ -n "$shots" ] || continue
  # shellcheck disable=SC2086
  if command -v montage >/dev/null; then
    montage $shots -geometry 640x360+2+2 -tile 6x -background '#202020' "$out/$name.png" 2>/dev/null || true
  else
    python3 living/tools/contact_sheet.py "$out/$name.png" $shots || true
  fi
done
ls "$out"/*.png 2>/dev/null
