#!/bin/sh
# Install the compile cache living/tools/check.py uses (docs/TOOLING.md): sccache, at a pinned
# version with pinned checksums, into ~/.local/share/slop-tools/bin (not on PATH, so no other
# project on the machine picks it up). Linux x86_64/aarch64 and macOS arm64/x86_64.
# Usage: living/tools/install_sccache.sh
set -eu
V=v0.19.0
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  A=x86_64-unknown-linux-musl  SUM=aa73c7270c997894038c0d8f0d297865f57569e1687883322bc431713d4bb9dd ;;
  Linux-aarch64) A=aarch64-unknown-linux-musl SUM=3e47fc4a71b1ddd1b4294a0de9d34498922fdf41e3cd0bda5df3954e3d6deb9d ;;
  Darwin-arm64)  A=aarch64-apple-darwin       SUM=a35a0b7d622618774bc1bb8102d72562dfb21e619f88b153b370d7f89bc286af ;;
  Darwin-x86_64) A=x86_64-apple-darwin        SUM=2db7344bb96de350df79cd9f0124dd4e9baa47b3de2fac1e63e1346b66b20684 ;;
  *) echo "install_sccache: no pinned build for $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac
BIN="$HOME/.local/share/slop-tools/bin"
if [ -x "$BIN/sccache" ] && "$BIN/sccache" --version | grep -q " ${V#v}\$"; then
  echo "install_sccache: $BIN/sccache is already ${V}"
  exit 0
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
NAME="sccache-$V-$A"
curl -fsSL -o "$TMP/$NAME.tar.gz" "https://github.com/mozilla/sccache/releases/download/$V/$NAME.tar.gz"
GOT=$( (sha256sum "$TMP/$NAME.tar.gz" 2>/dev/null || shasum -a 256 "$TMP/$NAME.tar.gz") | awk '{print $1}')
if [ "$GOT" != "$SUM" ]; then
  echo "install_sccache: checksum mismatch for $NAME.tar.gz ($GOT, expected $SUM)" >&2
  exit 1
fi
tar -xzf "$TMP/$NAME.tar.gz" -C "$TMP"
mkdir -p "$BIN"
install -m 0755 "$TMP/$NAME/sccache" "$BIN/sccache.new"
mv "$BIN/sccache.new" "$BIN/sccache"
"$BIN/sccache" --version
echo "install_sccache: installed $BIN/sccache; living-check uses it from the next run"
