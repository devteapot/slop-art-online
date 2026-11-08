#!/bin/sh
# Download the CC0 models used by the client's look-dev mode into living/game/assets/lookdev
# (git-ignored). Licences, checked 2026-11-08:
# - VRoid beta samples Sendagaya Shino and Vivi: VRM metadata licenseName CC0, commercial use
#   allowed (mirror: github.com/madjin/vrm-samples; official CC0 source: OpenGameArt
#   "VRoid Studio CC0 models").
# - KayKit Adventurers 1.0 (Kay Lousberg): CC0 (LICENSE.txt, saved beside the models).
set -eu
dir="$(cd "$(dirname "$0")/../game/assets" && pwd)/lookdev"
mkdir -p "$dir"
cd "$dir"
for f in Sendagaya_Shino Vivi; do
    curl -sfL "https://raw.githubusercontent.com/madjin/vrm-samples/HEAD/vroid/beta/$f.vrm" -o "vroid-$f.glb"
done
k=https://raw.githubusercontent.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0/HEAD/addons/kaykit_character_pack_adventures
for c in Knight Mage Rogue Barbarian; do
    curl -sfL "$k/Characters/gltf/$c.glb" -o "kaykit-$c.glb"
done
curl -sfL "$k/LICENSE.txt" -o KAYKIT-LICENSE.txt
ls -la "$dir"
