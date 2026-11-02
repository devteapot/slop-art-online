#!/bin/sh
# Keep the mind service connected: it exits when the world disconnects (e.g. a module
# update) and is restarted here. Logs append to .local/living/mind.log.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
cargo build --manifest-path living/Cargo.toml --release -p living-mind || exit 1
while true; do
  ./living/target/release/living-mind >> .local/living/mind.log 2>&1
  echo "[$(date -u +%FT%TZ)] living-mind exited ($?); restarting in 3s" >> .local/living/mind.log
  sleep 3
done
