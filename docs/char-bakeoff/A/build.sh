#!/usr/bin/env bash
# Build the stage-one source and game export in a fresh output directory.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
clip=$(realpath "${1:?supply the render set lookdev/anim/own-clips.glb}")
out=$(realpath -m "${2:?supply a new output directory}")
if [[ -e "$out" ]]; then
    echo "Output already exists: $out" >&2
    exit 1
fi
export JOBS=3
export PATH="$HOME/.local/share/slop-tools/build-bin:$PATH"
export BLENDER_USER_RESOURCES="$root/.local/mpfb-profile"
src="$root/.local/mpfb-src"
if [[ ! -d "$src" ]]; then
    git clone --depth 1 --branch v2.0.18 https://github.com/makehumancommunity/mpfb2 "$src"
fi
[[ $(git -C "$src" rev-parse HEAD) == d0a32e57a7f915cb2f2b95410e2117648c7bbb7e ]]
extensions="$BLENDER_USER_RESOURCES/extensions/user_default"
mkdir -p "$extensions"
[[ -e "$extensions/mpfb" ]] || ln -s "$src/src/mpfb" "$extensions/mpfb"
blender -b -t 3 --python-exit-code 2 -P docs/char-bakeoff/A/generate.py -- "$out" "$clip"
