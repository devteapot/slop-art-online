#!/bin/sh
# Runs inside the database container. Avoid Compose's provider-specific --wait.
set -eu

attempt=0
while [ "$attempt" -lt 30 ]; do
    if curl --fail --silent --max-time 2 http://127.0.0.1:3000/v1/ping > /dev/null; then
        echo "SpacetimeDB is ready inside the container (port 3000)."
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 1
done

echo "SpacetimeDB did not become ready. Run 'just logs' (legacy) or 'just bevy-db-logs' (browser) with the same runtime to inspect it." >&2
exit 1
