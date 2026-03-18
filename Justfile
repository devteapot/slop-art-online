bindings_dir  := "shared/src/module_bindings"
module_path   := "server/module/spacetimedb"
server        := "http://localhost:3000"
db            := "slop-art-online"
compose       := "docker compose -f deploy/docker-compose.yml"

generate:
    spacetime generate --lang rust --out-dir {{bindings_dir}} --module-path {{module_path}}

publish:
    cd server/module && spacetime publish --server {{server}}

publish-reset:
    cd server/module && spacetime publish --server {{server}} --delete-data -y {{db}}

publish-generate: publish generate

up:
    {{compose}} --profile mac up -d

down:
    {{compose}} --profile mac down

logs:
    {{compose}} logs -f

call reducer *args:
    spacetime call --server {{server}} {{db}} {{reducer}} {{args}}
