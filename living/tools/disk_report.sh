#!/usr/bin/env bash
# Disk use across the machines the game work runs on: free space and the biggest build and
# cache folders, with a warning under the threshold. Reports only; it deletes nothing.
# Usage: living/tools/disk_report.sh [min_free_gib, default 60]
#
# Usual cleanups (check what is running first):
# - Rust: `living/target/debug` (rebuilt by living-check; release is what the game runs from),
#   `*/incremental`, stale lab target dirs. Never `cargo clean` while a build runs.
# - Scratch photographs: intermediate review rounds (keep finals until they are reported).
# - dev-box: only the game worktree `~/dev/slop-game` is ours; leave `~/dev/slop-art-online`.
# - Spark: `~/kimodo-test` and the Hugging Face cache hold the Kimodo models (keep).
# - Docker volumes may hold lab worlds: never prune them without the user.
set -uo pipefail
min=${1:-60}
repo=$(cd "$(dirname "$0")/../.." && pwd)

flag() { # available GiB
  if [ "${1%.*}" -lt "$min" ]; then echo "  << LOW (under ${min} GiB)"; fi
}

avail=$(df -g /System/Volumes/Data 2>/dev/null | awk 'NR==2 {print $4}')
echo "== mac: ${avail:-?} GiB free$(flag "${avail:-0}")"
du -sh "$repo/living/target"/{debug,release,wasm32-unknown-unknown} 2>/dev/null | sed 's/^/   /'

remote() { # name, ssh target, paths...
  local name=$1 target=$2
  shift 2
  local out
  if ! out=$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$target" "df -BG ~ | awk 'NR==2 {gsub(\"G\",\"\",\$4); print \$4}'; du -sh $* 2>/dev/null; true" 2>/dev/null); then
    echo "== $name: unreachable"
    return
  fi
  local free
  free=$(echo "$out" | head -1)
  echo "== $name: ${free} GiB free$(flag "$free")"
  echo "$out" | tail -n +2 | sed 's/^/   /'
}

remote dev-box carlid@dev-box '~/dev/slop-game/living/target' '~/dev/slop-art-online/living/target' '~/.cargo/registry' /tmp
remote spark gooning@192.168.1.103 '~/kimodo-test' '~/.cache/huggingface'
