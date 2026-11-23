#!/usr/bin/env bash
# growth-diag: 30-minute gate-case runs with a per-minute profile (prof.py), under battle.lock (taken by the
# caller, holding nothing else: flock ~/slop-mq/battle.lock driver.sh PLAN). PLAN lines "ARM NAME [EXTRA...]"
# (ARM relay|main). Per run: server stopped by SIGINT (300 s; forced only past that, logged), its log saved,
# replicas cleared (after the module logs were copied out), started, no database listed; merge lock free;
# the run under a shared trial-activity.lock with cores.py, mem.py and prof.py beside. One try per long run;
# the window's load (max, end, rise above running minimum) is recorded, not used to redo.
set -uo pipefail
PLAN=$1
G=/home/gooning/slop-growth-diag; SRC=$G/relay-src
C=slop-growth-diag; VOL=slop-growth-diag; IMG=clockworklabs/spacetime:v2.14.1; PORT=3641
export PATH=$G/shim:$PATH
export LIVING_STDB_CONTAINER=$C LIVING_STDB_URL=http://127.0.0.1:$PORT
export GR_BV=$SRC/living/tools/battle_viewers.py GR_LOAD=$G/relay/gate-load GR_WASM=gate216_npc.wasm RELAY_BIN=$G/relay/relay-proto
export MAIN_BV=/home/gooning/.t3/worktrees/slop-art-online-t3/t3-2c307ca2-3b4d2ac37e3b5ddd/living/tools/battle_viewers.py MAIN_LOAD=$G/wasm/gate-load-main MAIN_WASM=main_cullet.wasm
export OUT=$G/out/runs; mkdir -p $OUT $G/out/server-logs
log(){ echo "$(date '+%F %T') $*" | tee -a $G/out/driver.log; }
if ! docker inspect $C >/dev/null 2>&1; then
  docker run -d --name $C --cpuset-cpus 5-9,15-19 --ulimit nofile=65536:524288 -p 127.0.0.1:$PORT:3000 -v $G/wasm:/wasm -v $VOL:/home/spacetime $IMG start --listen-addr 0.0.0.0:3000 >/dev/null
  for i in $(seq 60); do curl -sf $LIVING_STDB_URL/v1/ping >/dev/null && break; sleep 1; done
  log "container $C created on $PORT, cpuset $(docker inspect $C --format '{{.HostConfig.CpusetCpus}}')"
fi
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
  docker run --rm --cpuset-cpus 0-4,10-14 -v $VOL:/home/spacetime --entrypoint sh $IMG -c 'rm -rf /home/spacetime/.local/share/spacetime/data/replicas/*' > /dev/null
  docker start $C >/dev/null
  for i in $(seq 60); do curl -sf $LIVING_STDB_URL/v1/ping >/dev/null && break; sleep 1; done
  local l; l=$(docker exec $C spacetime list -s local 2>&1 | tail -1); log "server up: $l; cpuset $(docker inspect $C --format '{{.HostConfig.CpusetCpus}}')"
  case "$l" in *"No databases found"*) ;; *) log "ABORT: databases listed"; exit 3;; esac
}
taskset -c 0-4,10-14 python3 $SRC/living/tools/gate_remeasure/poller.py & POLL=$!
log "poller $POLL"
trap 'kill $POLL 2>/dev/null' EXIT
while read -r ARM NAME EXTRA; do
  [ -z "$ARM" ] && continue
  reset_server "before-$NAME" < /dev/null
  until flock -n ~/slop-mq/lock true; do log "merge lock held; waiting"; sleep 30; done
  log "run $ARM $NAME ($EXTRA) (load $(cut -d' ' -f1 /proc/loadavg))"
  flock -s ~/slop-mq/trial-activity.lock bash -c "
    taskset -c 0-4,10-14 python3 $G/cores.py $C $G/out/cores-$NAME.jsonl & CP=\$!
    taskset -c 0-4,10-14 python3 $G/mem.py $C $LIVING_STDB_URL $G/out/mem-$NAME.jsonl & MP=\$!
    taskset -c 0-4,10-14 python3 $G/prof.py $C $LIVING_STDB_URL $OUT/$NAME $G/out/prof-$NAME.jsonl & PP=\$!
    taskset -c 0-4,10-14 bash $SRC/living/tools/gate_remeasure/series.sh $ARM $NAME $EXTRA
    kill \$CP \$MP; sleep 5; kill \$PP 2>/dev/null" < /dev/null
  for f in cores mem prof; do mv $G/out/$f-$NAME.jsonl $OUT/$NAME/$f.jsonl 2>/dev/null; done
  docker exec $C sh -c 'cd /home/spacetime/.local/share/spacetime/data/replicas && tar cf - */module_logs' > $OUT/$NAME/replica-module-logs.tar 2>/dev/null
  log "module logs copied: $(ls -la $OUT/$NAME/replica-module-logs.tar | awk '{print $5}') bytes"
  ok=$([ -f $OUT/$NAME/battle-viewers.json ] && echo 1 || echo 0)
  lr=$(awk 'BEGIN{m=0; lo=99; rise=0} {if ($2>m) m=$2; if ($2<lo) lo=$2; if ($2-lo>rise) rise=$2-lo; last=$2} END{printf "%.2f %.2f %.2f", m, last, rise}' $OUT/$NAME/v0/load.log 2>/dev/null)
  log "done $NAME: result $ok, window load max/end/rise $lr"
done < $PLAN
stop_server "end"
log "series end"
