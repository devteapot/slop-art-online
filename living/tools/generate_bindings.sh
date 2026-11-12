#!/bin/sh
# `just living-generate`: the Rust bindings (living/bindings/src/generated) from the built
# authority module, private tables included (docs/PERCEPTION.md).
#
# The generator writes into a temporary folder; the bindings are swapped in only when it exited 0,
# produced files with a mod.rs, and rustfmt parsed them. On any failure the existing bindings stay
# as they were and the script exits non-zero with the cause. (Before, a generator that failed,
# such as a compose run without .local/living/neo4j.env, left an empty folder that replaced them.)
#
# The generator is a shell command that writes a tar stream of the generated folder to stdout:
#   LIVING_GENERATE_CMD   the whole command (a stub, or another server's CLI); it gets WASM_DIR,
#                         the folder holding living_authority.wasm
#   LIVING_COMPOSE        otherwise the compose prefix for the default command (the Justfile's
#                         living_compose: a one-off `spacetimedb` service container)
# The module is $CARGO_TARGET_DIR's build when that is set (where living-build put it), else
# living/target's.
set -eu
cd "$(git rev-parse --show-toplevel)"
out=living/bindings/src/generated
WASM_DIR=$(cd "${CARGO_TARGET_DIR:-living/target}" 2>/dev/null && pwd)/wasm32-unknown-unknown/release
export WASM_DIR
fail() { echo "living-generate: FAILED: $*; $out left as it was" >&2; exit 1; }
[ -f "$WASM_DIR/living_authority.wasm" ] || fail "no module at $WASM_DIR/living_authority.wasm (run just living-build)"
mkdir -p .local/living
tmp=$(mktemp -d .local/living/generated.XXXXXX)
trap 'rm -rf "$tmp" "$tmp.tar" "$tmp.err"' EXIT
if [ -n "${LIVING_GENERATE_CMD:-}" ]; then
  cmd=$LIVING_GENERATE_CMD
else
  : "${LIVING_COMPOSE:?LIVING_COMPOSE or LIVING_GENERATE_CMD is required}"
  # spacetime generate's own output goes to stderr: stdout carries only the tar stream.
  cmd="$LIVING_COMPOSE run --rm --no-deps -T -v \"\$WASM_DIR:/wasm:ro\" --entrypoint sh spacetimedb -c 'spacetime generate -l rust -b /wasm/living_authority.wasm -o /tmp/gen -y --include-private >&2 && tar -C /tmp/gen -cf - .'"
fi
code=0
sh -c "$cmd" > "$tmp.tar" 2> "$tmp.err" || code=$?
[ "$code" -eq 0 ] || fail "the generator exited $code: $(tail -5 "$tmp.err" | tr '\n' ' ')"
[ -s "$tmp.tar" ] || fail "the generator wrote nothing (its stderr: $(tail -5 "$tmp.err" | tr '\n' ' '))"
tar -C "$tmp" -xf "$tmp.tar" 2> "$tmp.err" || fail "its output is not a tar stream: $(tail -3 "$tmp.err" | tr '\n' ' ')"
[ -f "$tmp/mod.rs" ] || fail "its output has no mod.rs ($(ls "$tmp" | wc -l) files)"
n=$(ls "$tmp"/*.rs | wc -l)
[ "$n" -gt 1 ] || fail "its output has only $n .rs file"
rustfmt --edition 2021 "$tmp"/*.rs 2> "$tmp.err" || fail "rustfmt could not parse it: $(tail -5 "$tmp.err" | tr '\n' ' ')"
# The swap: the old folder aside, the new one in, the old one removed; put back if the move fails.
old=$out.old.$$
if [ -e "$out" ]; then mv "$out" "$old"; fi
if ! mv "$tmp" "$out"; then
  [ -e "$old" ] && mv "$old" "$out"
  fail "could not move the new bindings into place"
fi
rm -rf "$old"
echo "living-generate: $n files in $out (from $WASM_DIR/living_authority.wasm)"
