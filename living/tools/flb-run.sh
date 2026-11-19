#!/bin/bash
# Run a single scheduled replicate after flb-all.sh has prepared the build and evidence directory.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ ${FLB_WINDOW_OPEN:-} == yes && ${LIVING_STDB_CONTAINER:-} == slop-trials-stdb &&
   ${LIVING_STDB_URL:-} == http://127.0.0.1:3320 ]]
arm=$1 size=$2 rep=$3 minutes=$4
case $arm in
  A) extra=() ;;
  B) extra=(--fast-lane --fast-real) ;;
  C) extra=(--fast-lane --fast-real --law fast_lane_rate=1 --law fast_lane_inflight=2) ;;
  *) exit 2 ;;
esac
run=minds-flb-${arm,,}-$size-$rep
exec python3 living/tools/battle_diag.py --run "$run" --battle "$size" --walkers 16 --minutes "$minutes" \
  --keep-plans --arm "$arm-$size" "${extra[@]}"
