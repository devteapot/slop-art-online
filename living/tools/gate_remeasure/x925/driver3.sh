#!/usr/bin/env bash
# gate216-x925: runs PLAN lines "ARM NAME" under battle.lock (taken by the caller: flock ~/slop-mq/battle.lock).
# Per run: server stopped, replicas cleared, started, no database listed; merge lock free; series.sh
# (load < 4 wait inside) under a shared trial-activity.lock; cores.py beside; redo if window load > 8.
set -uo pipefail
PLAN=$1
C=slop-gate216-x925; VOL=slop-gate216-x925; IMG=clockworklabs/spacetime:v2.14.1
B=/home/gooning/slop-gate216-x925; GR=/home/gooning/.t3/worktrees/slop-art-online-t3/t3-6ff50011-d08f9541c61140f8
export LIVING_STDB_CONTAINER=$C LIVING_STDB_URL=http://127.0.0.1:3621
export MAIN_BV=$B/main-src/living/tools/battle_viewers.py MAIN_LOAD=$B/target-main/release/gate-load MAIN_WASM=gate216_main.wasm
export GR_BV=$GR/living/tools/battle_viewers.py GR_LOAD=$B/target-gr/release/gate-load GR_WASM=gate216_relay.wasm RELAY_BIN=$B/target-gr/release/relay-proto
export OUT=$B/out/runs; mkdir -p $OUT $OUT/redo
log(){ echo "$(date '+%F %T') $*" | tee -a $B/out/driver.log; }
reset_server(){
  docker stop -t 30 $C >/dev/null; log "server stopped (docker stop, SIGTERM, 30 s grace): exit $?, state $(docker inspect $C --format '{{.State.ExitCode}}')"
  docker run --rm --cpuset-cpus 0-4,10-14 -v $VOL:/home/spacetime --entrypoint sh $IMG -c 'rm -rf /home/spacetime/.local/share/spacetime/data/replicas/*; ls /home/spacetime/.local/share/spacetime/data/replicas | wc -l'
  docker start $C >/dev/null
  for i in $(seq 60); do curl -sf $LIVING_STDB_URL/v1/ping >/dev/null && break; sleep 1; done
  local l; l=$(docker exec $C spacetime list -s local 2>&1 | tail -1); log "server up: $l; cpuset $(docker inspect $C --format '{{.HostConfig.CpusetCpus}}')"
  case "$l" in *"No databases found"*) ;; *) log "ABORT: databases listed"; exit 3;; esac
}
taskset -c 0-4,10-14 python3 $GR/living/tools/gate_remeasure/poller.py & POLL=$!
taskset -c 0-4,10-14 python3 $GR/living/tools/gate_remeasure/runners.py $OUT/runners.log & RUNNERS=$!
log "poller $POLL runners $RUNNERS"
trap 'kill $POLL $RUNNERS 2>/dev/null' EXIT
while read -r ARM NAME WASMF EXTRA; do
  export GR_WASM=$WASMF
  [ -z "$ARM" ] && continue
  for try in 1 2 3; do
    reset_server < /dev/null
    until flock -n ~/slop-mq/lock true; do log "merge lock held; waiting"; sleep 30; done
    log "run $ARM $NAME ($WASMF $EXTRA) try $try (load $(cut -d' ' -f1 /proc/loadavg))"
    flock -s ~/slop-mq/trial-activity.lock bash -c "
      taskset -c 0-4,10-14 python3 $B/cores.py $C $B/out/cores-$NAME.jsonl & CP=\$!
      taskset -c 0-4,10-14 bash $GR/living/tools/gate_remeasure/series.sh $ARM $NAME $EXTRA
      kill \$CP" < /dev/null
    mv $B/out/cores-$NAME.jsonl $OUT/$NAME/cores.jsonl 2>/dev/null
    docker exec $C sh -c 'cd /home/spacetime/.local/share/spacetime/data/replicas && tar cf - */module_logs' > $OUT/$NAME/replica-module-logs.tar 2>/dev/null
    ok=$([ -f $OUT/$NAME/battle-viewers.json ] && echo 1 || echo 0)
    # Load rule on the Spark: the run's own placement burst (216 joins, in the warmup) lifts the 1-min
    # load to ~12-14 and it decays through the window. Redo when the window's load ENDS above 8 or RISES
    # more than 1.0 above its running minimum inside the window (a disturbance from outside); the max is logged.
    lr=$(awk 'BEGIN{m=0; lo=99; rise=0} {if ($2>m) m=$2; if ($2<lo) lo=$2; if ($2-lo>rise) rise=$2-lo; last=$2} END{printf "%.2f %.2f %.2f", m, last, rise}' $OUT/$NAME/v0/load.log 2>/dev/null)
    read -r mx last rise <<< "${lr:-99 99 99}"
    log "done $NAME: result $ok, window load max $mx end $last rise $rise"
    if [ "$ok" = 1 ] && awk -v e="$last" -v r="$rise" 'BEGIN{exit !(e<=8 && r<=1.0)}'; then break; fi
    if [ "$ok" = 1 ] && [ $try = 3 ]; then log "KEPT $NAME after 3 tries despite the load rule"; break; fi
    log "redo $NAME (try $try)"; rm -rf $OUT/redo/$NAME-t$try; mv $OUT/$NAME $OUT/redo/$NAME-t$try; mv $OUT/$NAME.log $OUT/redo/$NAME-t$try.log 2>/dev/null
  done
done < $PLAN
reset_server < /dev/null
log "series end"
