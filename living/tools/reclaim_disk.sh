#!/bin/sh
# Reclaim disk from the living core's SpacetimeDB container.
#
# Every fresh publish (`--delete-data`) and every deleted database leaves its old replica
# directory behind; over a day of lab restarts they reach tens of GB, and Docker Desktop's
# disk image only gives space back to the host when trimmed. This removes replica
# directories in which no file changed for the last 2 hours (live labs write continuously),
# then trims the VM disk. A database left idle for 2 hours loses its data: republish it
# fresh afterwards. Usage: living/tools/reclaim_disk.sh [minutes-idle, default 120]
set -e
IDLE="${1:-120}"
C=sao-living-spacetimedb-1
docker exec "$C" sh -c "
cd /home/spacetime/.local/share/spacetime/data/replicas || exit 1
for r in *; do
  if [ -z \"\$(find \"\$r\" -type f -mmin -$IDLE -print -quit)\" ]; then rm -rf \"\$r\"; echo \"removed replica \$r\"; fi
done
du -sh ."
docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -u -i -n fstrim /var/lib 2>&1 | tail -1
df -h / | tail -1
