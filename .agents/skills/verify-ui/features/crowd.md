# A crowd of generated people

What a town of generated people costs in the client and whether the client draws it as meant: each face on a shared page shades with its page's shadow map, a person beyond the far distance shows the far model, and every person plays the one shared clip file. The client code is `living/game/src/lookdev.rs` (`convert`'s `face_map`, `far_models`, `figure_height`) and `living/game/src/anim.rs` (`clip_file`, `bind`, `Sets` keyed by the clip file). The generator's side is [docs/CHARACTERS.md](../../../../docs/CHARACTERS.md), "Crowd cost". This is a look-dev check. It needs no world, no authority and no mind service.

## Sub-features

- `faces`: a face whose file has no `<file>.face.png` takes the map its material's glTF extras name (`face_map`, share.py `pages`). Every face on a page is one `Face` material.
- `far`: a file built with `LOD=both` holds `Far*` mesh nodes on the same skeleton. Beyond `LIVING_GAME_FAR` metres (default 10, for a 1.75 m person, scaled by height) the far meshes show and the full ones hide. A far person comes back to the full model once it is `LIVING_GAME_FAR_BAND` (default 1.5 m) nearer.
- `identity`: a recipe's `identity` values move a type's identity bones (`characters/identity.rs`) when the scene comes in; `LIVING_GAME_PERF=…` `RUST_LOG=living_game::characters=debug` logs each bone's transform (`identity: <recipe> <bone> t … r … s …`) to compare with compose.py's nodes.
- `rebuild`: a character's scene spawned again is fitted, shaped, dressed and bound again (`characters::on_ready`), and a file is read once (`characters::SceneOf`).
- `compose`: with `LIVING_GAME_COMPOSE=1` a recipe with a person line (`person`, the generator's `<name>.params.json` line) is composed from its type's file and the style files it names (`characters/compose.rs`): each file loaded once, its meshes and one toon material a file shared by everyone wearing it; hair and head pieces with the type's `hair_fit`; a hair style's spring bones under `J_Id_Cranium`; outfit pieces coloured by their own name in `colors.outfit`; overlays (`styles.overlays`: beards, stubble, lines, freckles, from `lookdev/styles/overlay/<type>/`) with the type's own bind matrices, blended over the face, shut and opened with its blink and mouth (`lookdev::FaceMorphs`, `rig`'s `faces`), a beard tinted by `colors.beard`; the line's `belly` moves `J_Fit_Belly` forward by `belly` × 0.108 m. Off (the default) the same recipe is its whole `base` file. The far switch, outlines, identity bones, springs and shared clips work on both.
- `clips`: `own-*` files (and `lookdev/types/`) take their clips from `lookdev/anim/own-clips.glb` when it is there. A file without clips of its own is given its player and bone targets (`anim::bind`). `LIVING_GAME_SHARED_CLIPS=0` plays each file's own clips.

## How to get to it

A town from the generator, with both models in one file, its own clips removed, and the shared clip file:

```bash
PATH=<a python with pillow>:$PATH
python3 living/tools/characters/town.py .local/living/<run>/town --town living/seeds/cullet.json --lod near,both --clips present --models-only
python3 living/tools/characters/share.py clips living/game/assets/lookdev/lod/anim/own-*.glb
ONLY=present LOD=near living/tools/blender/gen_person.sh clips=man      # lookdev/anim/own-clips.glb
```

For `compose`, the type and style files (hair, outfit and overlay) and town people whose params carry a person line (the generator since char-4's overlays). On macOS pass the types to `gen_types.sh` (its `mapfile` needs bash 4); `CLIPS=none` skips each person's own clips, which the shared clip file replaces:

```bash
living/tools/blender/gen_types.sh $(python3 -c "import json; print(' '.join(json.load(open('living/tools/characters/types.json'))['types']))")
living/tools/blender/gen_styles.sh
CLIPS=none python3 living/tools/characters/town.py .local/living/<run>/town --town living/seeds/cullet.json --lod both --clips present --models-only
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
| `assets: … N images M MiB; …; outline directions generated for G meshes, brought by B` | images: the scene's own few MiB, not the people's pages (`keeppixels` keeps them: 526 MiB for Cullet's 64); B > 0 for files from `outline_normals.py` (types, new people) |
| `characters: … scene was rebuilt and not shaped again` | never. Before rebuild-keep, 0–10 people a run lost their proportions |
| `LIVING_GAME_PERF=…,rebuild=4`: `characters: X's scene was spawned again (2 times); fitting and shaping it again` | once per character; then each is fitted, shaped (the same `characters: <recipe> … stride` line as at the start) and bound again (`bound to`) |

Same-framing stills of the full and the far model come from the asset view (`LIVING_GAME_VIEW=recipe:…`) with `LIVING_GAME_FAR=1000` (always full) and `LIVING_GAME_FAR=0.01` (always far). Face close-ups from a client before `crowd-1` show a paged face shaded as skin; with it, the swept shadow edge.

Foot slide with the shared clips: you as a town person (`LIVING_GAME_PLAYER=<recipe>`), `LIVING_GAME_AUTOWALK=90 LIVING_GAME_RAMP=4.5:14:2 LIVING_GAME_FEET=<file>`, then `living/tools/foot_slide.py <file> --bins 0.5`. Compare `LIVING_GAME_SHARED_CLIPS=0` on the full file with the shared clips on the stripped file, for the shortest and the tallest person.

A rebuilt person, before and after: `LIVING_GAME_PLAYER=<a child's town recipe>`, `LIVING_GAME_SEQ=<dir>:2:6:3`, `LIVING_GAME_SEQ_VIEW=0:10:3.5:35` and `LIVING_GAME_PERF=frames,rebuild=4`, with and without `nokeep`. Without the letting go, the child is drawn at its height with an adult's proportions from 8 s on.

### Composed people (`compose`)

Fidelity, a few people in the asset view, three arms: their whole file, composed, and composed with the whole recipe's proportions (the control):

```bash
python3 living/tools/characters/compose_check.py <binary> .local/living/<run>/fidelity tamsin-hollin fenn-brandt joss-tarn vessa-pontil wick-marl
```

| Read | Pass |
| --- | --- |
| `fidelity.json` `control_file_units.most_mm` | 0.000 for every person and shot (79 bones, `J_Fit_Belly` apart): the composing rule. In metres the control differs by the height fit only (`scale_ratio` within 0.3%) |
| `control_file_units.belly_mm` | `belly` × 108 mm × the spine's girth scale (Joss Tarn: 0.217 → 25.05 mm); 0 without a belly |
| `composed` | differs by the line's `build` and `shoulders` (the girth a whole file built into its meshes): 1.6 to 10 mm, most on the heaviest (Joss Tarn) |
| `composed/view.log` `rigged a VRoid model (… with N more meshes on its expressions)` | N = the overlays the person wears (Ode Pontil's beard and lines: 2) |
| `sec_bones` | a hair style with spring chains brings the same count as the whole file (Tamsin's braid: 5 and 5) |
| `composed/view.log` | `compose: … wears …: N meshes` once a person; no `could not be put on`, `did not load` or `joint … is neither` |
| `stills/<name>.jpg` | hair, cap, kerchief, apron, beard, stubble and every piece on; the iris in the line's `eyes`; no floating or missing piece; the known limits (an overlay's one strength, no blush, far heads clean-shaven, a smock's sleeve bands taking its hue) |

Cost, the town's 64 as they are, both modes interleaved (`town` is each person's whole file, `composed` the same recipes with the switch on):

```bash
python3 $C .local/living/<run>/town .local/living/<run>/cost --runs x:empty,x:town,x:composed,x:composed,x:town,x:empty --repeat 2 --seconds 30 --binary x=$B/living-game
python3 $C … --runs x:town,x:composed,x:composed,x:town --repeat 3 --game-env LIVING_GAME_FAR=1000 --tag=-near   # everyone on the full model
```

| Line | Pass |
| --- | --- |
| `people ready: 65 characters (64 composed) …` | 64 composed with the switch on, 0 off |
| `people perf: … N mesh entities shown of M` | at the game camera (all far): 422 of 1,211 composed, 210 of 722 whole (overlays included) |
| `views: … [people …, P mesh-material pairs]` | the draws the people make once instanced: 71 composed against 210 whole at the game camera |
| `batches: preprocessing culling (multi-draw); opaque S sets …` | one set a material: 60 composed against 10 whole at the game camera, 97 against 84 on the full model. `LIVING_GAME_PERF=sharestyles` (colours wrong, measurement only) shows what sharing style materials would give |
| `assets: N meshes M MiB (… morph targets …)` and `batches: … textures … MiB` | composed far below whole: mesh data and morph targets, and GPU textures |

## Gotchas

- Run each binary once before measuring: Metal's shader cache is per binary, and a cold one gives a first run of 5 s frames.
- macOS process memory (RSS, `footprint`) moves by gigabytes with the other agents' load. Use the `assets:` line for what the people hold.
- `crowd.py`, `compose_check.py` and the foot-slide and stills harnesses each rewrite `recipes.json` for a run and restore it after. Never run two at once.
- Other clients on the same GPU (another worker's tour or film) can make a run die about a second in with Metal's `Cannot allocate sample buffer` and `DeviceLost` (the `diag` flag's GPU counters). `crowd.py` then reports nulls for that run: check `ps` for other `living-game` processes and run it again.
- The frame time is not a performance claim (docs/PERFORMANCE_CONTRACT.md): interleave the sets and report the load average.
