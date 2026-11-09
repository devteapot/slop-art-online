#!/bin/sh
# Build and run the script engine spike (docs/SCRIPT_ENGINES.md).
#   OUT=dir CARGO_TARGET_DIR=dir living/tools/script_bench/run.sh
# Builds the wasmi guest, one wasm32-unknown-unknown bench module per engine, the wasmtime
# host (SpacetimeDB 2.14.1's wasmtime 39.0.1 configuration) and the native runner; runs all
# engines natively and under wasmtime with and without fuel; writes JSONL, dumps and sizes.
set -eu
cd "$(dirname "$0")"
: "${CARGO_TARGET_DIR:?set a private CARGO_TARGET_DIR}"
OUT=${OUT:-$CARGO_TARGET_DIR/script-bench-out}
BATCHES=${BATCHES:-3000}
# Pin the timed runs to one core, e.g. PIN="taskset -c 6".
PIN=${PIN:-}
W=$CARGO_TARGET_DIR/wasm32-unknown-unknown/release
mkdir -p "$OUT/wasm" "$OUT/dumps"

cargo build -q -p sb-guest --target wasm32-unknown-unknown --release
cp "$W/sb_guest.wasm" guest.wasm

for f in none rhai rune wasmi koto; do
    if [ "$f" = none ]; then F=""; else F="--features $f"; fi
    # shellcheck disable=SC2086
    cargo build -q -p sb-module --target wasm32-unknown-unknown --release $F
    cp "$W/sb_module.wasm" "$OUT/wasm/$f.wasm"
done
# piccolo needs custom getrandom backends on this target (bench/Cargo.toml); its RUSTFLAGS get
# their own target dir so the other builds are not invalidated.
RUSTFLAGS='--cfg getrandom_backend="custom"' CARGO_TARGET_DIR="$CARGO_TARGET_DIR-picc" \
    cargo build -q -p sb-module --target wasm32-unknown-unknown --release --features piccolo
cp "$CARGO_TARGET_DIR-picc/wasm32-unknown-unknown/release/sb_module.wasm" "$OUT/wasm/piccolo.wasm"
ls -l "$OUT/wasm" > "$OUT/sizes.txt"

cargo build -q -p sb-host --release
H=$CARGO_TARGET_DIR/release/sb-host

$PIN "$CARGO_TARGET_DIR/release/sb-native" native,rhai,rhai-lean,rhai-map-only,rune,wasmi,wasmi-fuel,piccolo,koto,mlua \
    --dumps "$OUT/dumps" --batches "$BATCHES" > "$OUT/native.jsonl"

for fuel in fuel no-fuel; do
    flag=""; [ "$fuel" = no-fuel ] && flag="--no-fuel"
    : > "$OUT/wasm-$fuel.jsonl"
    for m in none:native rhai:rhai,rhai-lean,rhai-map-only rune:rune wasmi:wasmi,wasmi-fuel piccolo:piccolo koto:koto; do
        f=${m%%:*}; k=${m#*:}
        extra=""; [ "$f" = koto ] && extra="--stub-imports"
        # shellcheck disable=SC2086
        $PIN "$H" "$OUT/wasm/$f.wasm" "$k" $flag $extra --dumps "$OUT/dumps" --batches "$BATCHES" >> "$OUT/wasm-$fuel.jsonl" 2>> "$OUT/imports.txt"
    done
done

# Equivalence: every engine's outputs are byte-identical to the native floor's.
cd "$OUT/dumps"
fail=0
for law in rates strike cooldown; do
    for d in *-"$law".txt; do
        case "$d" in *rhai-map-only*) continue ;; esac
        cmp -s "$d" "native-native-$law.txt" || { echo "DIFFERS: $d"; fail=1; }
    done
done
[ "$fail" = 0 ] && echo "equivalence: all engines identical on all fixtures ($(ls | wc -l) dumps)"
echo "results in $OUT"
