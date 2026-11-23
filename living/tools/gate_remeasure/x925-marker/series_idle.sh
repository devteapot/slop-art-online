#!/usr/bin/env bash
# gate216-marker: the IDLE world of the GC's line: Cullet's 64 residents, no battle, the same build,
# the step marker on, no profiling. series.sh's flags minus the battle (0 fighters, humans, walkers,
# viewers) and minus the relay; same load wait (< 4), host.json and procs files.
#   series_idle.sh NAME
set -uo pipefail
NAME=$1
cd /home/gooning/slop-gate216-marker/src
OUT=${OUT:?}; mkdir -p $OUT
while true; do l=$(cut -d' ' -f1 /proc/loadavg); awk -v l=$l 'BEGIN{exit !(l<4)}' && break; sleep 10; done
out=$OUT/$NAME; rm -rf $out; mkdir -p $out
gov="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)/$(cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference 2>/dev/null)"
echo "{\"governor\": \"$gov\", \"arm\": \"idle\", \"args\": \"--law tick_marker_on=true --tick-marker\"}" > $out/host.json
ps -eo pid,comm,%cpu,rss --sort=-%cpu | head -12 > $out/procs-start.txt
timeout 3600 python3 $GR_BV --label "gr-${NAME,,}" --load $GR_LOAD --wasm $GR_WASM --seconds 60 --warmup 20 \
  --tiers --cues --motion-tables --character-tables --fighter-tables --combat-feed \
  --watch --detail --viewers 0 --fighters 0 --humans 0 --walkers 0 --lines-table --no-profile \
  --law tick_marker_on=true --tick-marker --out $out > $out.log 2>&1
echo "exit $?"
ps -eo pid,comm,%cpu,rss --sort=-%cpu | head -12 > $out/procs-end.txt
