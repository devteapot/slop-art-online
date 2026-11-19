#!/bin/sh
# A LIVING_GENERATE_CMD for a machine whose SpacetimeDB runs in a container that is already up
# (the Spark's slop-trials-stdb): copy the built module in, run `spacetime generate` there and
# write the generated folder to stdout as a tar stream (living/tools/generate_bindings.sh reads
# it, checks it and swaps it in). Usage: generate_in_container.sh CONTAINER  (WASM_DIR set by
# generate_bindings.sh). A container that is not running is a failure, never a silent pass.
set -eu
c=${1:?usage: generate_in_container.sh CONTAINER}
[ "$(docker inspect "$c" --format '{{.State.Running}}' 2>/dev/null)" = true ] || { echo "container $c is not running" >&2; exit 1; }
tag=gen-$$-$(date +%s)
docker exec "$c" mkdir -p "/tmp/$tag" >&2
trap 'docker exec "$c" rm -rf "/tmp/$tag" >/dev/null 2>&1 || true' EXIT
docker cp "$WASM_DIR/living_authority.wasm" "$c:/tmp/$tag/living_authority.wasm" >&2
docker exec "$c" sh -c "spacetime generate -l rust -b /tmp/$tag/living_authority.wasm -o /tmp/$tag/gen -y --include-private >&2 && tar -C /tmp/$tag/gen -cf - ."
