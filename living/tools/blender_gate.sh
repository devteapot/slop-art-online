#!/usr/bin/env bash
# blender_gate.sh: the dev-box's `blender` on PATH (docs/TOOLING.md, "Heavy work during a gate").
# Blender through gate_pause.sh: it waits while a scene gate holds gate.lock, pauses while a gate
# takes it, and is never paused by the gate's own work. Install both, side by side:
#   install -m 755 living/tools/gate_pause.sh ~/.local/share/slop-tools/build-bin/gate_pause.sh
#   install -m 755 living/tools/blender_gate.sh ~/.local/share/slop-tools/build-bin/blender
# For tests: SLOP_BLENDER_REAL (default /usr/bin/blender), SLOP_GATE_PAUSE (the helper), and
# gate_pause.sh's SLOP_GATE_LOCK, SLOP_GATE_LOG, SLOP_GATE_POLL_S, SLOP_GATE_PAUSE_CAP_S.
set -u
here=$(dirname "$(readlink -f "$0")")
helper=${SLOP_GATE_PAUSE:-$here/gate_pause.sh}
[ -x "$helper" ] || helper=$(command -v gate_pause.sh || true)
if [ -z "$helper" ] || [ ! -x "$helper" ]; then
  echo "blender-gate: gate_pause.sh not found beside $0 or on PATH; running Blender without the gate" >&2
  exec "${SLOP_BLENDER_REAL:-/usr/bin/blender}" "$@"
fi
export SLOP_GATE_LOG=${SLOP_GATE_LOG:-$HOME/.local/state/slop-build/blender-gate.log}
export SLOP_GATE_NAME=blender
exec "$helper" -- "${SLOP_BLENDER_REAL:-/usr/bin/blender}" "$@"
