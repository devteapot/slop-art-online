#!/usr/bin/env bash
# Photograph models through the game's renderer (on a 1 m checker) and make one contact sheet per model.
# Usage: living/tools/view_assets.sh OUT_DIR FILE_OR_DIR[,FILE_OR_DIR...] [ENV_ID] [HEIGHT_M]
#   OUT_DIR/<model>/NN-<view>.png   single views (front, three-quarter, side, back, above, game,
#                                   then 6 frames per animation clip, from the side)
#   OUT_DIR/<model>.png             contact sheet: the six views, then one row per clip
#   OUT_DIR/report.json             size (m), triangles, materials, vertex colours, glow, clips
# Needs a display (the game opens a window) and ImageMagick's montage for the sheets.
set -euo pipefail
cd "$(dirname "$0")/../.."
out=$(mkdir -p "$1" && cd "$1" && pwd)
files=$2
env_id=${3:-}
height=${4:-}
cargo build --release -q -p living-game --manifest-path living/Cargo.toml
LIVING_GAME_VIEW="$files" LIVING_GAME_VIEW_OUT="$out" LIVING_GAME_VIEW_ENV="$env_id" LIVING_GAME_VIEW_HEIGHT="$height" \
  RUST_LOG=${RUST_LOG:-warn,living_game=info} living/target/release/living-game 2>&1 | grep -E 'view:|ERROR|panicked' || true
for d in "$out"/*/; do
  name=$(basename "$d")
  views=$(ls "$d"[0-9][0-9]-*.png 2>/dev/null | grep -v -- '-clip-' || true)
  clips=$(ls "$d"[0-9][0-9]-clip-*.png 2>/dev/null || true)
  [ -n "$views" ] || continue
  # shellcheck disable=SC2086
  montage $views $clips -geometry 640x360+2+2 -tile 6x -background '#202020' "$out/$name.png" 2>/dev/null || true
done
ls "$out"/*.png 2>/dev/null
