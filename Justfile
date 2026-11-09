# Slop Art Online — the living core (docs/LIVING_CORE.md).
# The retired simulation/server/client line was removed; its last state is the
# `legacy-baseline` tag.
living_compose := "docker compose --env-file .local/living/neo4j.env -f living/deploy/compose.yml -p sao-living"
living_stdb := "living/tools/stdb"
living_db   := env("LIVING_DB", "living")

# Start SpacetimeDB (:3300) and Neo4j (:7689 bolt, :7476 browser) containers.
living-up: living-secrets
    {{living_compose}} up -d --wait
    {{living_stdb}} server set-default local >/dev/null

living-down:
    {{living_compose}} down

living-logs:
    {{living_compose}} logs -f --tail 100

# Generate the local Neo4j password once (git-ignored).
living-secrets:
    #!/bin/sh
    set -eu
    umask 077
    mkdir -p .local/living
    [ -f .local/living/neo4j.env ] || echo "LIVING_NEO4J_PASSWORD=$(openssl rand -hex 16)" > .local/living/neo4j.env

living-build:
    cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release

# Private tables are included: the mind service and the lab observer read them as the database
# owner (docs/PERCEPTION.md). The generated code is the same for `LIVING_PERCEPTION=open` and
# `scoped`, which differ only in which tables are public.
living-generate: living-build
    rm -rf .local/living/generated && mkdir -p .local/living/generated
    {{living_compose}} run --rm --no-deps -T -v "$PWD/living/target/wasm32-unknown-unknown/release:/wasm:ro" --entrypoint sh spacetimedb -c 'spacetime generate -l rust -b /wasm/living_authority.wasm -o /tmp/gen -y --include-private >/dev/null 2>&1 && tar -C /tmp/gen -cf - .' | tar -C .local/living/generated -xf -
    rm -rf living/bindings/src/generated && mv .local/living/generated living/bindings/src/generated
    rustfmt --edition 2021 living/bindings/src/generated/*.rs

# Export the world admin's token for the mind service.
living-token:
    #!/bin/sh
    set -eu
    umask 077
    {{living_stdb}} login show --token | sed -n 's/^Your auth token (don.t share this!) is //p' > .local/living/token
    test -s .local/living/token

# Update the module in place (keeps world data) and install the current skill rules.
living-publish: living-build
    {{living_stdb}} publish -s local -b /wasm/living_authority.wasm {{living_db}} -y
    {{living_stdb}} call -s local {{living_db}} install_script "$(python3 -c 'import json,sys; print(json.dumps(open("living/scripts/skills.rhai").read()))')"
    just living-token

# Choose the active seed (living/seeds/<name>.json → world.json); takes effect at the next reset.
living-seed name:
    cp living/seeds/{{name}}.json living/seeds/world.json

# Fresh world from the seed (DELETES the living world's data).
living-reset: living-build
    {{living_stdb}} publish -s local -b /wasm/living_authority.wasm {{living_db}} --delete-data -y
    just living-token

living-sql query:
    {{living_stdb}} sql -s local {{living_db}} "{{query}}"

living-mind:
    living/tools/run-mind.sh

# Native observer (LIVING_SERVER / LIVING_DB override http://127.0.0.1:3300 / living).
living-viewer:
    cargo run --manifest-path living/Cargo.toml --release -p living-viewer

# Browser observer at http://127.0.0.1:8330/ (add ?server=…&db=… to point elsewhere).
living-web:
    cd living/viewer && env -u NO_COLOR trunk serve --cargo-profile wasm-dev --address 127.0.0.1 --port 8330

# Optimized browser observer bundle in .local/living/web. (The public tunnel that served it,
# https://sos.carlid.dev, was retired on 2026-11-09; see docs/LIVING_CORE.md.)
living-web-dist:
    cd living/viewer && CARGO_PROFILE_RELEASE_STRIP=true env -u NO_COLOR trunk build --release --dist ../../.local/living/web

living-test:
    cargo test --manifest-path living/Cargo.toml -p living-rules

# Everything that must keep compiling after any change: authority (wasm), mind, the native
# and browser observer, the game client, and the rules tests. Run before every commit.
living-check: living-build
    cargo build --manifest-path living/Cargo.toml -p living-mind -p living-viewer
    # The game in release only: the build that is run, without a second ~10 GB debug tree.
    cargo build --release --manifest-path living/Cargo.toml -p living-game
    cargo build --manifest-path living/viewer/Cargo.toml --target wasm32-unknown-unknown --profile wasm-dev --bin living-viewer
    cargo test --manifest-path living/Cargo.toml -p living-rules

# Fuel budgets of the hot Rhai laws (rates, the strike path, perceived_of, a constant lookup) in
# the module under SpacetimeDB's wasmtime config; fails over living/tools/script_bench/budgets.json
# (docs/SCRIPT_ENGINES.md). Builds in its own target dir unless CARGO_TARGET_DIR is set.
living-script-gate:
    CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$PWD/.local/script-bench/target}" living/tools/script_bench/gate.sh


# The game client's generated assets (git-ignored; the scripts are the source), on any machine
# with Blender: CC0 look-dev models, nature, buildings, then the animated characters. The
# animation step needs the Kimodo cache in .local/kimodo/outputs/library/: make it with
# living/tools/kimodo/spark.sh, or copy it from a machine that has it.
living-game-assets:
    living/tools/lookdev_assets.sh
    just living-game-textures
    living/tools/blender/gen_nature.sh
    living/tools/blender/gen_buildings.sh
    living/tools/blender/gen_anim.sh

# The game's painted, tileable textures (git-ignored): the ground's layers for terrain.rs, from
# living/tools/textures/paint.py (numpy and Pillow through uv). `--set material` paints the
# model kinds (bark, planks, plaster, stone, brick, shingles, metal, leaves), not used yet.
living-game-textures *args:
    uv run living/tools/textures/paint.py {{args}}
