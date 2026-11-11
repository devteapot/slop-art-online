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
    python3 living/tools/install_script.py {{living_db}}
    just living-token

# Choose the active seed (living/seeds/<name>.json → world.json); takes effect at the next reset.
living-seed name:
    cp living/seeds/{{name}}.json living/seeds/world.json

# Fresh world from the seed (DELETES the living world's data).
living-reset: living-build
    {{living_stdb}} publish -s local -b /wasm/living_authority.wasm {{living_db}} --delete-data -y
    just living-token

# A floor (docs/FLOORS.md): the floor module, built without a seed, on database `db`, given seed
# `name` at runtime by `create_floor` (DELETES the database's data). A land larger than 2048 m is
# created in steps after the call returns: watch `SELECT * FROM genesis` until `done`. The seed's
# `rules` are the world's own values of the script's laws, kept when the world is created.
living-floor name db=living_db:
    LIVING_SEED=none cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
    {{living_stdb}} publish -s local -b /wasm/living_authority.wasm {{db}} --delete-data -y
    {{living_stdb}} call -s local {{db}} create_floor "$(python3 living/tools/seed_text.py living/seeds/{{name}}.json --arg)"
    just living-token

living-sql query:
    {{living_stdb}} sql -s local {{living_db}} "{{query}}"

# One command to play a scene (world, memory store, minds, client); paid parts stop when the client exits.
living-play scene *args:
    python3 living/tools/play.py {{scene}} {{args}}

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
# living/tools/check.py runs these five cargo steps (docs/TOOLING.md): the three cargo build
# directories at once under one jobserver; a step skipped when it already passed on this
# machine on byte-identical inputs; rustc through sccache when it is installed
# (living/tools/install_sccache.sh). `living-check-full` runs every step regardless of stamps;
# LIVING_CHECK_SERIAL=1 runs them one by one with cargo's output on the terminal.
living-check:
    python3 living/tools/check.py

living-check-full:
    python3 living/tools/check.py --full

# Merge a branch into main end to end, from a clean coordinator worktree: --no-ff merge onto
# origin/main, living-check, push; when main moved, fetch, merge and check again
# (docs/TOOLING.md). Arguments after the branch: -m "message", --retries N, --no-push.
[positional-arguments]
living-merge branch *args:
    python3 living/tools/merge.py "$@"

# Remove idle build folders under the policy in docs/TOOLING.md (a dry run unless --apply);
# `living/tools/disk_clean_install.sh` runs it on a timer.
[positional-arguments]
living-disk-clean *args:
    python3 living/tools/disk_clean.py "$@"

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
    just living-game-textures --set all
    living/tools/blender/gen_nature.sh
    living/tools/blender/gen_buildings.sh
    living/tools/blender/gen_city.sh
    living/tools/blender/gen_cullet.sh
    living/tools/blender/gen_anim.sh

# The asset board (docs/ASSET_BOARD.md): every generated family photographed in the game's own
# renderer beside the version the owner accepted, with decisions and history in
# living/assets/board/ and media in ~/archive/asset-board/. `just living-board publish ...`,
# `decide`, `status`, `build`, `check`, `pack`.
[positional-arguments]
living-board *args:
    python3 living/tools/board/board.py "$@"

# People from the character generator (docs/CHARACTERS.md; git-ignored output): presets, seeds or
# parameter files, each generated, given the clip library and the face's shading data.
# `just living-people` makes the presets; `just living-people 12 halvard=halvard.json` others.
living-people *args:
    living/tools/blender/gen_person.sh {{args}}

# A household or a whole town of people and the page to check them by (line-up, game camera,
# every face): `just living-town .local/town`, `--household kiln-03`, `--town cullet.json`.
living-town *args:
    python3 living/tools/characters/town.py {{args}}

# The game's painted, tileable textures (git-ignored), from living/tools/textures/paint.py
# (numpy and Pillow through uv): `--set ground` (the default) the ground's layers for
# terrain.rs, `--set material` the model surfaces (bark, planks, plaster, stone, brick,
# shingles, metal, leaves) that style.rs binds on scenery, `--set all` both.
living-game-textures *args:
    uv run living/tools/textures/paint.py {{args}}
