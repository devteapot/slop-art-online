#!/usr/bin/env bash
# Cullet's asset kit (docs/SMALL_CITY.md, phase 3): every model the kit can build, for its lot or
# fixture of the hand-authored plan (living/seeds/worlds/cullet/plan.json), into
# living/game/assets/envs/cullet/<folder>/ (git-ignored), with fixtures.json (where the quay, the
# walls, the flights and the dressing stand, for the game client), ground.json (the plan's ground
# areas, for the client's terrain) and report.json.
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
# A full run into the game's own folder also puts the lots' footprints, with what each hides at eye
# height, into the rules' table (living/rules/data/buildings.json, tracked: the authority and the
# client compile it in). A run elsewhere (--out) or of some models (--only) leaves the table alone.
table=()
if [ "$OUT" = living/game/assets/envs/cullet ] && [[ " ${args[*]} " != *" --only "* ]]; then table=(--table living/rules/data/buildings.json); fi
"$BLENDER" -b -P living/tools/blender/cullet.py -- --out "$OUT" "${table[@]}" "${args[@]}" 2>&1 | grep -E '^GEN|Error|Traceback|^  File' || true
