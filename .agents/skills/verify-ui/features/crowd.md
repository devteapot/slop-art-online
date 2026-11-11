# A crowd of generated people

What a town of generated people costs in the client and whether the client draws it as meant: each face on a shared page shades with its page's shadow map, a person beyond the far distance shows the far model, and every person plays the one shared clip file. The client code is `living/game/src/lookdev.rs` (`convert`'s `face_map`, `far_models`, `figure_height`) and `living/game/src/anim.rs` (`clip_file`, `bind`, `Sets` keyed by the clip file). The generator's side is [docs/CHARACTERS.md](../../../../docs/CHARACTERS.md), "Crowd cost". This is a look-dev check. It needs no world, no authority and no mind service.

## Sub-features

- `faces`: a face whose file has no `<file>.face.png` takes the map its material's glTF extras name (`face_map`, share.py `pages`). Every face on a page is one `Face` material.
- `far`: a file built with `LOD=both` holds `Far*` mesh nodes on the same skeleton. Beyond `LIVING_GAME_FAR` metres (default 10, for a 1.75 m person, scaled by height) the far meshes show and the full ones hide. A far person comes back to the full model once it is `LIVING_GAME_FAR_BAND` (default 1.5 m) nearer.
- `rebuild`: a character's scene spawned again is fitted, shaped, dressed and bound again (`characters::on_ready`), and a file is read once (`characters::SceneOf`).
- `clips`: `own-*` files (and `lookdev/types/`) take their clips from `lookdev/anim/own-clips.glb` when it is there. A file without clips of its own is given its player and bone targets (`anim::bind`). `LIVING_GAME_SHARED_CLIPS=0` plays each file's own clips.

## How to get to it

A town from the generator, with both models in one file, its own clips removed, and the shared clip file:

```bash
PATH=<a python with pillow>:$PATH
python3 living/tools/characters/town.py .local/living/<run>/town --town living/seeds/cullet.json --lod near,both --clips present --models-only
python3 living/tools/characters/share.py clips living/game/assets/lookdev/lod/anim/own-*.glb
ONLY=present LOD=near living/tools/blender/gen_person.sh clips=man      # lookdev/anim/own-clips.glb
```

The bakes go through `build-slot` on the laptop. Blender and the Kimodo library are needed (`.local/kimodo/outputs/library`). Write into this worktree's own `living/game/assets/lookdev/`, not a link to the main checkout's: the line-up lists every file there.

## Driving it

`living/tools/characters/crowd.py` runs the client headless in the open meadow at the default game camera (22 m, 28° down), the crowd 25 to 40 m away, every person a different file:

```bash
C=living/tools/characters/crowd.py; B=<binaries>
python3 $C .local/living/<run>/town .local/living/<run>/crowd --runs after:empty,before:ours,after:lod,after:lod,before:ours,after:empty --repeat 2 \
  --binary after=$B/living-game-after --binary before=$B/living-game-before --seconds 30
python3 $C .local/living/<run>/town .local/living/<run>/assets --runs after:ours --binary after=$B/living-game-after --tag=-ownclips --game-env LIVING_GAME_SHARED_CLIPS=0
```

Each run's log (`LIVING_GAME_PERF=frames,diag`) holds what the check reads:

| Line | Pass |
| --- | --- |
| `people perf: … N of M with a far model show it` | `lod` at the game camera: 64 of 64 |
| `views: … [people N, M materials, Kk]` | `lod`: 210 meshes, 20 materials, 388k triangles for Cullet's 64 (pass 3's far-model figures); `ours`: 402, 29, 2,078k |
| `anim: lookdev/…/own-<name>.glb bound to lookdev/anim/own-clips.glb` | once a person for files without clips |
| `anim: lookdev/anim/own-clips.glb: 29 clips, …` | one graph for every generated person |
| `assets: … N clips (C curves); G graphs; …` | `lod` with the shared file: the VRoid bases' clips plus one set (159, 2 graphs); own clips: 64 sets (1,986, 65 graphs) |
| `characters: … scene was rebuilt and not shaped again` | never. Before rebuild-keep, 0–10 people a run lost their proportions |
| `LIVING_GAME_PERF=…,rebuild=4`: `characters: X's scene was spawned again (2 times); fitting and shaping it again` | once per character; then each is fitted, shaped (the same `characters: <recipe> … stride` line as at the start) and bound again (`bound to`) |

Same-framing stills of the full and the far model come from the asset view (`LIVING_GAME_VIEW=recipe:…`) with `LIVING_GAME_FAR=1000` (always full) and `LIVING_GAME_FAR=0.01` (always far). Face close-ups from a client before `crowd-1` show a paged face shaded as skin; with it, the swept shadow edge.

Foot slide with the shared clips: you as a town person (`LIVING_GAME_PLAYER=<recipe>`), `LIVING_GAME_AUTOWALK=90 LIVING_GAME_RAMP=4.5:14:2 LIVING_GAME_FEET=<file>`, then `living/tools/foot_slide.py <file> --bins 0.5`. Compare `LIVING_GAME_SHARED_CLIPS=0` on the full file with the shared clips on the stripped file, for the shortest and the tallest person.

A rebuilt person, before and after: `LIVING_GAME_PLAYER=<a child's town recipe>`, `LIVING_GAME_SEQ=<dir>:2:6:3`, `LIVING_GAME_SEQ_VIEW=0:10:3.5:35` and `LIVING_GAME_PERF=frames,rebuild=4`, with and without `nokeep`. Without the letting go, the child is drawn at its height with an adult's proportions from 8 s on.

## Gotchas

- Run each binary once before measuring: Metal's shader cache is per binary, and a cold one gives a first run of 5 s frames.
- macOS process memory (RSS, `footprint`) moves by gigabytes with the other agents' load. Use the `assets:` line for what the people hold.
- `crowd.py` and the foot-slide and stills harnesses each rewrite `recipes.json` for a run and restore it after. Never run two at once.
- The frame time is not a performance claim (docs/PERFORMANCE_CONTRACT.md): interleave the sets and report the load average.
