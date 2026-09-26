bindings_dir  := "shared/src/module_bindings"
web_bindings_dir := "web/src/module_bindings"
module_path   := "server/module/spacetimedb"
server        := "http://localhost:3000"
db            := "slop-art-online"
runtime       := env("CONTAINER_RUNTIME", "docker")
compose       := runtime + " compose -f deploy/docker-compose.yml"
spacetime     := "spacetime"
bevy_cli_config := env("SPACETIME_CONFIG_PATH", ".local/credentials/bevy-cli.toml")

generate: check-cli
    {{spacetime}} generate --lang rust --out-dir {{bindings_dir}} --module-path {{module_path}}

generate-web: check-cli
    {{spacetime}} generate --lang typescript --out-dir {{web_bindings_dir}} --module-path {{module_path}}

generate-all: generate generate-web

client:
    cargo run -p client

# Legacy server prototype; use bevy-db-up / bevy-dev for the 2D foundation client.
dev: check-cli up publish

publish: check-cli
    {{spacetime}} publish --no-config --server {{server}} --module-path {{module_path}} --delete-data=never -y {{db}}

publish-reset: check-cli
    {{spacetime}} publish --no-config --server {{server}} --module-path {{module_path}} --delete-data -y {{db}}

publish-generate: publish generate

up:
    {{compose}} up -d spacetimedb
    {{compose}} exec -T spacetimedb sh -s < deploy/wait-for-spacetimedb.sh

down:
    {{compose}} --profile mac --profile gpu down

logs:
    {{compose}} logs -f spacetimedb

status:
    {{compose}} ps

call reducer *args:
    {{spacetime}} call --server {{server}} {{db}} {{reducer}} {{args}}

[private]
check-cli:
    #!/bin/sh
    set -eu
    case "$({{spacetime}} --version)" in
        *"spacetimedb tool version 2.1.0;"*) ;;
        *)
            echo "Use SpacetimeDB CLI 2.1.0: spacetime version install 2.1.0 && spacetime version use 2.1.0" >&2
            exit 1
            ;;
    esac

# M1 experiments use isolated databases, never the ordinary development DB.
sim-build:
    cargo build -p server_module --target wasm32-unknown-unknown
    cargo build -p bridge --bin sao-sim

sim-run scenario output model='qwen2.5:7b' port='18877':
    cargo run -p bridge --bin sao-sim -- run "{{scenario}}" "{{output}}" "{{model}}" "{{port}}"

sim-inspect output port='18877':
    cargo run -p bridge --bin sao-sim -- inspect "{{output}}" "{{port}}"

sim-verify:
    cargo test -p simulation --lib
    python3 scripts/verify_m1.py

# Explicit per-run NPC provider configuration; credentials stay in the environment.
sim-run-config scenario output config port='18878':
    NPC_REASONING_CONFIG="{{config}}" cargo run -p bridge --bin sao-sim -- run "{{scenario}}" "{{output}}" configured "{{port}}"

# Actual Bevy WASM game client; no model calls during build or default host startup.
# Separate Compose project keeps foundation data apart from the legacy database.
bevy-db-up:
    SPACETIMEDB_PORT=3101 {{compose}} -p sao-bevy up -d spacetimedb
    SPACETIMEDB_PORT=3101 {{compose}} -p sao-bevy exec -T spacetimedb sh -s < deploy/wait-for-spacetimedb.sh

bevy-db-down:
    SPACETIMEDB_PORT=3101 {{compose}} -p sao-bevy down

bevy-db-status:
    SPACETIMEDB_PORT=3101 {{compose}} -p sao-bevy ps

bevy-db-logs:
    SPACETIMEDB_PORT=3101 {{compose}} -p sao-bevy logs -f spacetimedb

# First-time login to the container, separate from the global CLI account.
bevy-db-login:
    #!/bin/sh
    set -eu
    umask 077
    mkdir -p "$(dirname "{{bevy_cli_config}}")"
    "${SPACETIME_CLI:-$HOME/.local/share/spacetime/bin/2.1.0/spacetimedb-cli}" --config-path "{{bevy_cli_config}}" login --server-issued-login http://127.0.0.1:3101

bevy-web-build:
    cd client && env -u NO_COLOR trunk build --cargo-profile wasm-dev --dist dist-participant

bevy-dev:
    env -u NPC_REASONING_CONFIG SPACETIME_CONFIG_PATH="{{bevy_cli_config}}" cargo run -p bridge --bin sao-dev-client

# Share the development world on a trusted LAN (host is this machine's LAN IP).
bevy-lan host:
    SPACETIMEDB_BIND_ADDR=0.0.0.0 just runtime={{runtime}} bevy-db-up
    BEVY_DEV_BIND=0.0.0.0 BEVY_DEV_PUBLIC_URL="http://{{host}}:${BEVY_DEV_PORT:-18891}" just bevy-dev

bevy-native:
    cargo run -p client --no-default-features --features foundation

# ---- Living core (docs/LIVING_CORE.md): SpacetimeDB 2.10.1 + Neo4j in Docker, separate workspace ----
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

living-generate: living-build
    rm -rf .local/living/generated && mkdir -p .local/living/generated
    {{living_compose}} run --rm --no-deps -T -v "$PWD/living/target/wasm32-unknown-unknown/release:/wasm:ro" --entrypoint sh spacetimedb -c 'spacetime generate -l rust -b /wasm/living_authority.wasm -o /tmp/gen -y >/dev/null 2>&1 && tar -C /tmp/gen -cf - .' | tar -C .local/living/generated -xf -
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

living-test:
    cargo test --manifest-path living/Cargo.toml -p living-rules
