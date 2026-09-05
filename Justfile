bindings_dir  := "shared/src/module_bindings"
web_bindings_dir := "web/src/module_bindings"
module_path   := "server/module/spacetimedb"
server        := "http://localhost:3000"
db            := "slop-art-online"
runtime       := env("CONTAINER_RUNTIME", "docker")
compose       := runtime + " compose -f deploy/docker-compose.yml"
spacetime     := "spacetime"

generate: check-cli
    {{spacetime}} generate --lang rust --out-dir {{bindings_dir}} --module-path {{module_path}}

generate-web: check-cli
    {{spacetime}} generate --lang typescript --out-dir {{web_bindings_dir}} --module-path {{module_path}}

generate-all: generate generate-web

client:
    cargo run -p client

# Start the database, wait for it, and create/update the game module.
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
bevy-web-build:
    cd client && env -u NO_COLOR trunk build --cargo-profile wasm-dev --dist dist-participant

bevy-dev:
    env -u NPC_REASONING_CONFIG cargo run -p bridge --bin sao-dev-client

bevy-native:
    cargo run -p client --no-default-features --features foundation
