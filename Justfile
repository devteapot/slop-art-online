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
