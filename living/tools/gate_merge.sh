#!/usr/bin/env bash
# gate_merge.sh: the dev-box's `gate-merge` (docs/TOOLING.md, "The gate's server"). It runs
# `just living-merge ...` holding the scene-gate lock, so Blender (blender_gate.sh) pauses meanwhile.
# Install: install -m 755 living/tools/gate_merge.sh ~/.local/share/slop-tools/gate-merge
#
# - The gate's server first: with LIVING_GATE_STDB_CONTAINER set, `living/tools/gate_server.py check`
#   (docker exec and /v1/ping) before waiting for disk and every minute while waiting. A dead server
#   (the container stopped, or running with every exec failing: "transport endpoint is not
#   connected") exits 14 at once instead of waiting on disk; merge.py probes it again per attempt.
# - Disk: waits for SLOP_GATE_START_GB free before starting, then runs with the build floor lowered
#   to SLOP_GATE_FLOOR_GB (default 20): a gate must not stall mid-scene behind the 45 GB build floor
#   (it times scenes out). START defaults to the 45 GB floor plus the gate's known cost (its check
#   tree, about 18 GB; 2026-11-19 it took the disk from 58 to 40 GB), so a gate cannot by itself take
#   the host under the floor (general coordinator, 2026-11-19). While waiting it names the largest
#   idle build trees to prune; it never deletes anything itself.
# Run from the coordinator's worktree (it calls living/tools/ and `just` there).
START="${SLOP_GATE_START_GB:-$(( ${SLOP_DISK_FLOOR_GB:-45} + ${SLOP_GATE_COST_GB:-18} ))}"
free_gb() { df -BG --output=avail / | tail -1 | tr -dc 0-9; }
server_ok() {
  [ -n "${LIVING_GATE_STDB_CONTAINER:-}" ] || return 0
  python3 living/tools/gate_server.py check >/dev/null || {
    echo "gate-merge: the gate's server does not answer (above): not waiting for disk; exit 14" >&2
    exit 14
  }
}
wait_disk() {
  while [ "$(free_gb)" -lt "$START" ]; do
    server_ok
    echo "gate-merge: $(free_gb) GB free, under ${START} GB (floor + gate cost); waiting" >&2
    if [ -z "${said_trees:-}" ]; then
      echo "gate-merge: build trees by size (prune merged workers' trees first):" >&2
      du -s "$HOME"/.t3/worktrees/*/*/living/target "$HOME"/.t3/worktrees/*/*/.local/*/target 2>/dev/null | sort -rn | head -6 | awk '{printf "  %5.1f GB  %s\n", $1/1048576, $2}' >&2
      said_trees=1
    fi
    sleep 60
  done
}
export SLOP_BUILD_FLOOR_GB="${SLOP_GATE_FLOOR_GB:-20}"
LOCK="$HOME/.local/state/slop-build/gate.lock"
server_ok
# Check the disk again once the lock is held: another gate or a measurer may have used space while this one waited.
while :; do
  wait_disk
  exec {lk}>"$LOCK"; flock -x "$lk"
  if [ "$(free_gb)" -ge "$START" ]; then exec just living-merge "$@"; fi   # the lock fd stays open through exec
  echo "gate-merge: disk fell to $(free_gb) GB while waiting for the lock; waiting again" >&2
  flock -u "$lk"; exec {lk}>&-
done
