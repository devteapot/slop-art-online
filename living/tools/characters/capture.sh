#!/usr/bin/env bash
# Photograph a character recipe through the game's renderer for the check page
# (living/tools/characters/page.py): the same stills and the same clip frames for every character.
# Usage: living/tools/characters/capture.sh RECIPE NAME OUT_DIR [stills|clips|motions|blink|all]
#   `motions` photographs whole clips (MOTIONS="<clip>:<fps>:<views> …"; default the eight town and
#   combat motions added to the library on 2026-11-11), for a verdict on each.
#   FACE_K=<factor> FACE_AIM=<0..1>  scale and aim the close face shots (see below)
#   OUT_DIR/NAME/stills/<shot>.png and OUT_DIR/NAME/frames/<clip>-<view>/NNN.png
# Clip frames are poses held at a time (the asset view's `clip@seconds/view`), so spring bones
# (VRoid hair and skirts) rest instead of swinging.
set -euo pipefail
cd "$(dirname "$0")/../../.."
recipe=$1; name=$2; out=$(mkdir -p "$3" && cd "$3" && pwd); what=${4:-all}
tmp=$out/$name/tmp
view() { # size, shots, dest dir, prefix
  rm -rf "$tmp"
  LIVING_GAME_SIZE=$1 LIVING_GAME_VIEW_SHOTS=$2 living/tools/view_assets.sh "$tmp" "recipe:$recipe" 2>&1 | grep -E "ERROR|panicked|WARN" || true
  mkdir -p "$3"
  local i=0
  for f in $(ls "$tmp"/recipe:*/[0-9]*-*.png | sort -t/ -k99 -V); do
    if [ -n "${4:-}" ]; then cp "$f" "$3/$(printf %03d $i).png"; else
      n=$(basename "$f" .png); cp "$f" "$3/${names[$i]}.png"; fi
    i=$((i + 1))
  done
  rm -rf "$tmp"
}
if [ "$what" = stills ] || [ "$what" = all ]; then
  names=(front three-quarter side back face face-three-quarter face-side hands rest-front rest-three-quarter)
  # `rest`: the pose at time 0 of sword_slash is the library's neutral stand.
  # The view frames a model by its own size, so a face shot's zoom is relative to the whole
  # figure. FACE_K scales it (and FACE_AIM moves it) to frame a head of another proportion alike.
  fz=$(python3 -c "print(f'{0.2 * ${FACE_K:-1}:.4f}')"); fa=${FACE_AIM:-0.92}
  view 1000x1000 "idle@1.0/0:8:0.62,idle@1.0/40:14:0.62,idle@1.0/90:8:0.62,idle@1.0/180:8:0.62,idle@1.0/0:4:$fz:$fa,idle@1.0/40:6:$fz:$fa,idle@1.0/90:4:$fz:$fa,talk@2.0/35:10:0.3:0.62,sit_idle@1.0/40:14:0.62,sit_idle@1.0/90:8:0.62" "$out/$name/stills"
  mv "$out/$name/stills/rest-front.png" "$out/$name/stills/sit-three-quarter.png"
  mv "$out/$name/stills/rest-three-quarter.png" "$out/$name/stills/sit-side.png"
  names=(game game-walk)
  view 1600x900 "idle@1.0/game,walk@0.3/game" "$out/$name/stills"
  names=(elbow knee shoulder hip)
  view 1000x1000 "sword_slash@1.25/35:10:0.34:0.72,run@0.2/90:6:0.34:0.3,wave@1.4/20:8:0.34:0.82,sit_idle@1.0/60:20:0.4:0.45" "$out/$name/stills"
fi
clip() { # clip, view name, view spec, start, end, fps
  # The first shot of a run can catch the model still fading in: it is taken twice and the first
  # copy dropped.
  local shots="$1@$(python3 -c "print(f'{$4:.3f}')")/$3," t
  local n=$(python3 -c "print(max(1, round(($5 - $4) * $6)))")
  for k in $(seq 0 $((n - 1))); do
    t=$(python3 -c "print(f'{$4 + $k / $6:.3f}')")
    shots+="$1@$t/$3,"
  done
  # The view writes at most two digits of step index before names stop sorting; keep runs short.
  local d="$out/$name/frames/$1-$2"
  rm -rf "$d"
  view 720x720 "${shots%,}" "$d" seq
  rm -f "$d/000.png"
  for k in $(seq 1 "$n"); do mv "$d/$(printf %03d "$k").png" "$d/$(printf %03d $((k - 1))).png"; done
  echo "$6" > "$d/fps.txt"
}
tq=40:14:0.74; side=90:8:0.74
len() { python3 -c "import json,sys; print(json.load(open('living/game/assets/lookdev/anim/$1.clips.json'))['$2']['seconds'])"; }
base=$(python3 -c "import json; r=[r for r in json.load(open('living/game/assets/characters/recipes.json'))['recipes'] if r['name']=='$recipe'][0]; print(r['base'].split('/')[-1][:-4])")
if [ "$what" = clips ] || [ "$what" = all ]; then
  clip idle tq $tq 0 4 12
  clip walk tq $tq 0 "$(len "$base" walk)" 15
  clip walk side $side 0 "$(len "$base" walk)" 15
  clip run tq $tq 0 "$(len "$base" run)" 24
  clip run side $side 0 "$(len "$base" run)" 24
  clip sword_slash tq $tq 0 "$(len "$base" sword_slash)" 15
  clip sit_down tq $tq 0 "$(len "$base" sit_down)" 15
  clip sit_idle tq $tq 0 2 12
fi
if [ "$what" = motions ]; then
  # Whole clips to judge a motion by: MOTIONS="<clip>:<fps>:<views> …" (views: tq, side).
  for m in ${MOTIONS:-gather:15:tq work:15:tq eat:15:tq play:15:tq,side sit_ground_down:15:tq,side sit_ground:12:tq stand_up_ground:15:tq,side dodge:30:tq,side}; do
    IFS=: read -r c fps views <<< "$m"
    for v in ${views//,/ }; do clip "$c" "$v" "${!v}" 0 "$(len "$base" "$c")" "$fps"; done
  done
fi
if [ "$what" = blink ]; then
  # The game blinks and moves the mouth by itself (LIVING_GAME_ACT=talk); photograph the face many
  # times and let media.py pick a blink and an open mouth.
  rm -rf "$out/$name/blink"
  fz=$(python3 -c "print(f'{0.2 * ${FACE_K:-1}:.4f}')")
  LIVING_GAME_ACT=talk LIVING_GAME_SIZE=600x600 LIVING_GAME_VIEW_SHOTS="$(python3 -c "print(','.join(['idle@1.0/0:4:$fz:${FACE_AIM:-0.92}'] * 90))")" \
    living/tools/view_assets.sh "$tmp" "recipe:$recipe" 2>&1 | grep -E "ERROR|panicked" || true
  mkdir -p "$out/$name/blink" && cp "$tmp"/recipe:*/[0-9]*.png "$out/$name/blink/" && rm -rf "$tmp"
fi
echo "captured $name -> $out/$name"
