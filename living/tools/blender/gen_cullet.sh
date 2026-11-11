#!/usr/bin/env bash
# Cullet's asset kit (docs/SMALL_CITY.md, phase 3): every model the kit can build, for its lot or
# fixture of the hand-authored plan (living/seeds/worlds/cullet/plan.json), into
# living/game/assets/envs/cullet/<folder>/ (git-ignored), with fixtures.json (where the quay, the
# walls, the flights and the dressing stand, for the game client) and report.json.
# Usage: living/tools/blender/gen_cullet.sh [--only cone,low_4,retaining_wall] [--out DIR]
# Then check the files themselves: python3 living/tools/cullet_kit_check.py
set -euo pipefail
cd "$(dirname "$0")/../../.."
python3 living/tools/cullet_plan.py --check || { echo "plan.json is stale: run python3 living/tools/cullet_plan.py" >&2; exit 1; }
BLENDER=${BLENDER:-$(command -v blender || echo /Applications/Blender.app/Contents/MacOS/Blender)}
OUT=living/game/assets/envs/cullet
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=$2; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
"$BLENDER" -b -P living/tools/blender/cullet.py -- --out "$OUT" "${args[@]}" 2>&1 | grep -E '^GEN|Error|Traceback|^  File' || true
