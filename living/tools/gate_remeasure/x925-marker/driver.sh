#!/usr/bin/env bash
# gate216-marker: runs PLAN lines "ARM NAME [EXTRA...]" (ARM idle|relay) under battle.lock (taken by the
# caller, holding nothing else: flock ~/slop-mq/battle.lock driver.sh PLAN). Per run: the server stopped
# by SIGINT (300 s; forced only past that, logged), its log saved, replicas cleared, started, no database
# listed; the merge lock free; the run under a shared trial-activity.lock with cores.py beside; redo
# (at most 3 tries) when the window's load ends above 8 or rises more than 1.0 above its running minimum.
set -uo pipefail
PLAN=$1
G=/home/gooning/slop-gate216-marker; SRC=$G/src
C=slop-gate216-marker; VOL=slop-gate216-marker; IMG=clockworklabs/spacetime:v2.14.1
export PATH=$G/shim:$PATH
export LIVING_STDB_CONTAINER=$C LIVING_STDB_URL=http://127.0.0.1:3631
export GR_BV=$SRC/living/tools/battle_viewers.py GR_LOAD=$G/target/release/gate-load GR_WASM=gate216_npc.wasm RELAY_BIN=$G/target/release/relay-proto
export OUT=$G/out/runs; mkdir -p $OUT $OUT/redo $G/out/server-logs
log(){ echo "$(date '+%F %T') $*" | tee -a $G/out/driver.log; }
stop_server(){
  local tag=$1
  if [ "$(docker inspect -f '{{.State.Running}}' $C)" = true ]; then
    docker kill -s INT $C >/dev/null
    if timeout 300 docker wait $C >/dev/null; then forced=no; else docker stop -t 10 $C >/dev/null; forced=YES; fi
    docker logs $C > $G/out/server-logs/$tag.log 2>&1
    log "server stopped by SIGINT ($tag): exit $(docker inspect -f '{{.State.ExitCode}}' $C), forced $forced, last line: $(grep -v '^\s*$' $G/out/server-logs/$tag.log | tail -1 | cut -c1-140)"
  fi
}
reset_server(){
  stop_server "$1"
  docker run --rm --cpuset-cpus 0-4,10-14 -v $VOL:/home/spacetime --entrypoint sh $IMG -c 'rm -rf /home/spacetime/.local/share/spacetime/data/replicas/*; ls /home/spacetime/.local/share/spacetime/data/replicas | wc -l' > /dev/null
  docker start $C >/dev/null
  for i in $(seq 60); do curl -sf $LIVING_STDB_URL/v1/ping >/dev/null && break; sleep 1; done
  local l; l=$(docker exec $C spacetime list -s local 2>&1 | tail -1); log "server up: $l; cpuset $(docker inspect $C --format '{{.HostConfig.CpusetCpus}}')"
  case "$l" in *"No databases found"*) ;; *) log "ABORT: databases listed"; exit 3;; esac
}
taskset -c 0-4,10-14 python3 $SRC/living/tools/gate_remeasure/poller.py & POLL=$!
taskset -c 0-4,10-14 python3 $SRC/living/tools/gate_remeasure/runners.py $OUT/runners.log & RUNNERS=$!
log "poller $POLL runners $RUNNERS"
trap 'kill $POLL $RUNNERS 2>/dev/null' EXIT
while read -r ARM NAME EXTRA; do
  [ -z "$ARM" ] && continue
  for try in 1 2 3; do
    reset_server "before-$NAME-t$try" < /dev/null
    until flock -n ~/slop-mq/lock true; do log "merge lock held; waiting"; sleep 30; done
    log "run $ARM $NAME ($EXTRA) try $try (load $(cut -d' ' -f1 /proc/loadavg))"
    if [ "$ARM" = idle ]; then CMD="bash $G/series_idle.sh $NAME"; else CMD="bash $SRC/living/tools/gate_remeasure/series.sh $ARM $NAME $EXTRA"; fi
    flock -s ~/slop-mq/trial-activity.lock bash -c "
      taskset -c 0-4,10-14 python3 $G/cores.py $C $G/out/cores-$NAME.jsonl & CP=\$!
      taskset -c 0-4,10-14 $CMD
      kill \$CP" < /dev/null
    mv $G/out/cores-$NAME.jsonl $OUT/$NAME/cores.jsonl 2>/dev/null
    docker exec $C sh -c 'cd /home/spacetime/.local/share/spacetime/data/replicas && tar cf - */module_logs' > $OUT/$NAME/replica-module-logs.tar 2>/dev/null
    ok=$([ -f $OUT/$NAME/battle-viewers.json ] && echo 1 || echo 0)
    lr=$(awk 'BEGIN{m=0; lo=99; rise=0} {if ($2>m) m=$2; if ($2<lo) lo=$2; if ($2-lo>rise) rise=$2-lo; last=$2} END{printf "%.2f %.2f %.2f", m, last, rise}' $OUT/$NAME/v0/load.log 2>/dev/null)
    read -r mx last rise <<< "${lr:-99 99 99}"
    log "done $NAME: result $ok, window load max $mx end $last rise $rise"
    if [ "$ok" = 1 ] && awk -v e="$last" -v r="$rise" 'BEGIN{exit !(e<=8 && r<=1.0)}'; then break; fi
    if [ "$ok" = 1 ] && [ $try = 3 ]; then log "KEPT $NAME after 3 tries despite the load rule"; break; fi
    log "redo $NAME (try $try)"; rm -rf $OUT/redo/$NAME-t$try; mv $OUT/$NAME $OUT/redo/$NAME-t$try; mv $OUT/$NAME.log $OUT/redo/$NAME-t$try.log 2>/dev/null
  done
done < $PLAN
stop_server "end"
log "series end"
