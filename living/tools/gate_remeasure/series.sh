#!/usr/bin/env bash
# The gate case of docs/HUMAN_FIGHTER_COST.md §6 and §7: 100 human fighters and 116 walkers, the players
# reading experience_copy (as the shipped client), Cullet; warm (poller.py), one run after another,
# each waiting for a 1-minute load under 4, the server's deleted replicas cleared between runs.
#
#   series.sh ARM NAME [extra battle_viewers flags...]
#     ARM main   main as shipped: MAIN_BV/MAIN_LOAD (branch gate-driver-main), MAIN_WASM
#     ARM direct gate-remeasure with the plausible cuts: GR_BV/GR_LOAD, GR_WASM
#     ARM relay  the same with the relay: GR_BV/GR_LOAD, GR_WASM, RELAY_BIN
#
# Environment: LIVING_STDB_CONTAINER, LIVING_STDB_URL (a private clockworklabs/spacetime:v2.14.1 whose
# /wasm holds the modules), OUT (the runs folder), and the paths above. Start poller.py and
# runners.py OUT/runners.log beside a series (the dev-box ran both; runners.py samples other
# projects' CI runners there). Read the results with tables.py OUT.
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ARM=$1; NAME=$2; shift 2
OUT=${OUT:-.local/gr/runs}; mkdir -p $OUT
HEED="--law attend_on=true --law attend_ceiling=16 --law attend_policy=3 --law attend_crowd_on=true"
case $ARM in
  main)   BV=$MAIN_BV; LOAD=$MAIN_LOAD; WASM=$MAIN_WASM; LAWS="" ;;
  direct) BV=$GR_BV; LOAD=$GR_LOAD; WASM=$GR_WASM; LAWS="$HEED --law sweep_keep_memory=true --law vf_lines_ms=1000 --law vf_hear_every=5 --law vf_feed_off=true" ;;
  relay)  BV=$GR_BV; LOAD=$GR_LOAD; WASM=$GR_WASM; LAWS="$HEED --law sweep_keep_memory=true --law vf_lines_ms=1000 --law relay_on=true --relay $RELAY_BIN" ;;
  *) echo "ARM: main, direct or relay"; exit 2 ;;
esac
while true; do l=$(cut -d' ' -f1 /proc/loadavg); awk -v l=$l 'BEGIN{exit !(l<4)}' && break; sleep 10; done
out=$OUT/$NAME; rm -rf $out; mkdir -p $out
gov="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)/$(cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference 2>/dev/null)"
echo "{\"governor\": \"$gov\", \"arm\": \"$ARM\", \"args\": \"$*\"}" > $out/host.json
ps -eo pid,comm,%cpu,rss --sort=-%cpu | head -12 > $out/procs-start.txt
timeout 3600 python3 $BV --label "gr-${NAME,,}" --load $LOAD --wasm $WASM --seconds 60 --warmup 20 \
  --tiers --cues --motion-tables --character-tables --fighter-tables --combat-feed \
  --keep-alive 0.5 --keep-fighters 1 --paused-placement --battle-after-placing --ring 26,32 --watch --detail \
  --viewers 0 --fighters 100 --humans 100 --walkers 116 --lines-table --no-profile $LAWS "$@" --out $out > $out.log 2>&1
echo "exit $?"
ps -eo pid,comm,%cpu,rss --sort=-%cpu | head -12 > $out/procs-end.txt
