bindings_dir := "client/src/module_bindings"
module_path  := "server/module/spacetimedb"
server       := "http://localhost:3000"
db           := "slop-art-online"

generate:
    spacetime generate --lang rust --out-dir {{bindings_dir}} --module-path {{module_path}}

publish:
    cd server/module && spacetime publish --server {{server}}

publish-generate: publish generate
