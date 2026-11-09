#!/usr/bin/env bash
# Generate the Kimodo clip library on the DGX Spark and copy the NPZs back.
# Usage: living/tools/kimodo/spark.sh [batch.py args, e.g. --only walk,run --force]
# Needs passwordless SSH to $KIMODO_HOST and the venv in ~/kimodo-test (see .local/kimodo/README.md).
# Writes ~/kimodo-test/library/ on the Spark and .local/kimodo/outputs/library/ here. Runs in the
# foreground and leaves nothing running.
set -euo pipefail
cd "$(dirname "$0")/../../.."
host=${KIMODO_HOST:-gooning@192.168.1.103}
remote='~/kimodo-test'
scp -q living/tools/kimodo/batch.py living/tools/blender/clips.json "$host:$remote/scripts/"
ssh "$host" "cd $remote/scripts && TEXT_ENCODER_MODE=local HF_HUB_OFFLINE=1 ../venv/bin/python batch.py clips.json ../library $*" \
  2>&1 | grep -E '^(LOAD|GEN|\{)|Error|error' || true
mkdir -p .local/kimodo/outputs/library
rsync -a "$host:$remote/library/" .local/kimodo/outputs/library/
