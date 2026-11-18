#!/bin/sh
# Print the allocated size in decimal GB for the hourly disk alarm.
set -eu
export LC_ALL=C
docker volume inspect slop-trials-stdb >/dev/null
size=$(docker run --rm --network none --user 0 \
    -v slop-trials-stdb:/d:ro --entrypoint du clockworklabs/spacetime:v2.14.1 -sk /d)
printf '%s\n' "$size" | awk '{printf "%.3f\n", $1 * 1024 / 1000000000}'
