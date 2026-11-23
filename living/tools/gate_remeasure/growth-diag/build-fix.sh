#!/usr/bin/env bash
# growth-diag: wasm builds, one target dir per checkout. (1) relay arm + fixes (Cullet), (2) growth-fix (Cullet),
# (3) growth-fix default seed (det candidate), (4) main 62fccc74b default seed (det base).
set -euo pipefail
source ~/slop-sysroot/env.sh
G=/home/gooning/slop-growth-diag
b(){ local src=$1 tgt=$2 seed=$3 out=$4; cd $G/$src; export CARGO_TARGET_DIR=$G/$tgt
  if [ -n "$seed" ]; then LIVING_SEED=$seed cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
  else env -u LIVING_SEED cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release; fi
  cp $CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm $G/wasm/$out; echo "built $out from $(git -C $G/$src rev-parse --short HEAD)"; }
case ${1:-cullet} in
  cullet) b relayfix-src target-relayfix cullet relayfix_cullet.wasm; b fix-src target-fix cullet fix_cullet.wasm ;;
  det) b main-src target-mainbase cullet main62_cullet.wasm ;;
  fixdet) b fix-src target-fixdet cullet fix2_cullet.wasm ;;
esac
echo BUILD-OK
