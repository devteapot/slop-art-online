#!/bin/sh
# Reclaim disk from the living core's SpacetimeDB container.
#
# Every fresh publish (`--delete-data`) and every deleted database leaves its old replica
# directory behind; over a day of lab restarts they reach tens of GB, and Docker Desktop's
# disk image only gives space back to the host when trimmed. This removes replica
# directories in which no file changed for the last 2 hours (live labs write continuously),
# then trims the VM disk. A database left idle for 2 hours loses its data: republish it
# fresh afterwards. Usage: living/tools/reclaim_disk.sh [minutes-idle, default 120]
#
# Manual only: idle replicas include paused reference worlds. The automatic cleanup
# (living/tools/disk_clean.py, docs/TOOLING.md) never touches databases or volumes.
#
# Refused (2026-11-12, docs/TRIAL_DISK.md): removing a replica directory is irreversible, and on
# SpacetimeDB 2.14.1 every deleted database's directory holds its whole commitlog, the exact
# record of that world. The server it targets keeps the paused reference worlds `aske-coast*`
# and `stage*` (.agents/skills/verify/SKILL.md), which must never be published, reset, paused or
# deleted. It runs only with `--owner-approved` (the owner's decision for this run, after the
# commitlogs worth keeping are archived), and never while a reference world is on the server.
set -e
if [ "$1" != "--owner-approved" ]; then
  echo "refusing: reclaim_disk.sh removes replica directories (irreversible; each holds a world's commitlog)." >&2
  echo "The server it targets keeps the paused reference worlds aske-coast* and stage*. See docs/TRIAL_DISK.md;" >&2
  echo "run only with --owner-approved, after the owner approves this removal." >&2
  exit 1
fi
shift
IDLE="${1:-120}"
# Docker Compose names it sao-living-spacetimedb-1, podman-compose sao-living_spacetimedb_1.
C=$(docker ps --format '{{.Names}}' | grep -E '^sao-living[-_]spacetimedb[-_]1$' | head -1)
REFS=$(docker exec "$C" spacetime list 2>/dev/null | awk -F'|' '{gsub(/ /,"",$1); if ($1 ~ /^(aske-coast|stage)/) print $1}')
if [ -n "$REFS" ]; then
  echo "refusing: the server holds kept reference worlds ($(echo $REFS | tr '\n' ' ')); their replicas must not be touched." >&2
  exit 1
fi
if ! docker exec "$C" spacetime list >/dev/null 2>&1; then
  echo "refusing: spacetime list failed, so the reference worlds cannot be ruled out." >&2
  exit 1
fi
docker exec "$C" sh -c "
cd /home/spacetime/.local/share/spacetime/data/replicas || exit 1
for r in *; do
  if [ -z \"\$(find \"\$r\" -type f -mmin -$IDLE -print -quit)\" ]; then rm -rf \"\$r\"; echo \"removed replica \$r\"; fi
done
du -sh ."
docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -u -i -n fstrim /var/lib 2>&1 | tail -1
df -h / | tail -1
