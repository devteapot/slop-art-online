#!/usr/bin/env bash
set -u
cd /home/gooning/.t3/worktrees/slop-art-online-t3/t3-eacddf65-5240dd2ef1d69529
export LIVING_STDB_CONTAINER=slop-x925floor-20261122 LIVING_STDB_URL=http://127.0.0.1:3591
O=.local/x925floor/smoke; mkdir -p $O
taskset -c 0-4,10-14 python3 .local/x925floor/sampler.py $LIVING_STDB_CONTAINER $LIVING_STDB_URL $O/samples.jsonl & SP=$!
flock -s ~/slop-mq/trial-activity.lock taskset -c 0-4,10-14 python3 living/tools/battle_viewers.py --label x9fsmoke --wasm x925-cullet.wasm --load $HOME/slop-x925floor-bin/gate-load \
  --viewers 0,2 --seconds 10 --warmup 5 --tiers --cues --motion-tables --character-tables --fighter-tables --combat-feed \
  --keep-fighters 1 --keep-alive 0.5 --paused-placement --battle-after-placing --ring 10,10 --detail --no-profile --out $O < /dev/null > $O/run.log 2>&1
echo "exit $?" >> $O/run.log
kill $SP
