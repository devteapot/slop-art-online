# A crowd of generated people

What a town of generated people costs in the client and whether the client draws it as meant: each face on a shared page shades with its page's shadow map, a person beyond the far distance shows the far model, and every person plays the one shared clip file. The client code is `living/game/src/lookdev.rs` (`convert`'s `face_map`, `far_models`, `figure_height`) and `living/game/src/anim.rs` (`clip_file`, `bind`, `Sets` keyed by the clip file). The generator's side is [docs/CHARACTERS.md](../../../../docs/CHARACTERS.md), "Crowd cost". This is a look-dev check: `crowd.py`, `compose_check.py` and `colour_check.py` need no world, no authority and no mind service. `living/tools/characters/live_crowd.py` is the connected client's side and needs a scratch world (below).

## Sub-features

- `faces`: a face whose file has no `<file>.face.png` takes the map its material's glTF extras name (`face_map`, share.py `pages`). Every face on a page is one `Face` material.
- `far`: a file built with `LOD=both` holds `Far*` mesh nodes on the same skeleton. Beyond `LIVING_GAME_FAR` metres (default 10, for a 1.75 m person, scaled by height) the far meshes show and the full ones hide. A far person comes back to the full model once it is `LIVING_GAME_FAR_BAND` (default 1.5 m) nearer.
- `identity`: a recipe's `identity` values move a type's identity bones (`characters/identity.rs`) when the scene comes in; `LIVING_GAME_PERF=…` `RUST_LOG=living_game::characters=debug` logs each bone's transform (`identity: <recipe> <bone> t … r … s …`) to compare with compose.py's nodes.
- `rebuild`: a character's scene spawned again is fitted, shaped, dressed and bound again (`characters::on_ready`), and a file is read once (`characters::SceneOf`).
- `compose`: by default (since compose-client-2; `LIVING_GAME_COMPOSE=0` turns it off) a recipe with a person line (`person`, the generator's `<name>.params.json` line) is composed from its type's file and the style files it names (`characters/compose.rs`): each file loaded once, its meshes and one toon material a file shared by everyone wearing it; hair and head pieces with the type's `hair_fit`; a hair style's spring bones under `J_Id_Cranium`; outfit pieces coloured by their own name in `colors.outfit`; overlays (`styles.overlays`: beards, stubble, lines, freckles, from `lookdev/styles/overlay/<type>/`) with the type's own bind matrices, blended over the face, shut and opened with its blink and mouth (`lookdev::FaceMorphs`, `rig`'s `faces`), a beard tinted by `colors.beard`, lines and freckles (`…FaceOverlay_00_FACE`) drawn as a fixed-colour face part, untagged and without a shadow map; a type's brows (`…FaceBrow_00_FACE`) take `colors.hair`; the line's `belly` moves `J_Fit_Belly` forward by `belly` × 0.108 m; a beard's `FarOverlay` shows with the far head; a greying person's hair greys lock by lock (`_GREY` into the mesh's second UVs, the shared hair toon's palette, `HairTints`, the tag's places and `grey`); every spring and collider group of a hair file comes across; `styles.hair` names a hair file with its cut (`tousled.2`). With `LIVING_GAME_COMPOSE=0` the same recipe is its whole `base` file; a recipe without a person line is its base file either way. Since look-1 a live person is drawn from their look book line when their projected key resolves (`live::recipe_for`; [looks.md](looks.md)), and only the fallback is a VRoid base. The far switch, outlines, identity bones, springs and shared clips work on both.
- `springs`: a spring bone (`J_Sec_*`) hung from a bone with its own scale (`shape`'s `Own`: hips, spine, chest, the legs and arms) takes that bone's scale with its offset (compose-skirt-scale), so the cloth on it (a skirt on the upper legs, a sleeve on a lower arm, the bust on the upper chest) grows with the body under it. A body bone's own children still take the offset alone. Main's composed files have spring chains only in hair, under the head, which scales uniformly, so composed people are untouched; the VRoid bases' skirts, sleeves and bust follow a scaled recipe. `check.py --run ui-<run> skirt-scale` (5 checks, no world): the asset view poses `shino`, `ranger`, `vivi` and `small` on one frame (`idle@0.5`, `LIVING_GAME_VIEW_JOINTS`). The hem (the skirt chains' `_end` joints) keeps its place on the thigh and its width on a scaled Shino, and its width on a scaled Vivi. Her side chains hang from the hips, whose own scale leaves height at 1, so her hem's place is not asserted.
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

A connected client's cost, before and after look-1 (docs/LOOK.md §5): `living/tools/characters/live_crowd.py --run RUN --out DIR --arm NAME=BINARY[@RUN][:K=V,...] … [--repeat 3]`, each arm through drive.py on `verify-RUN` (or the arm's own `@RUN`, for a client built against another module's bindings), as a player at the arrival, uncapped (`LIVING_GAME_FPS_CAP=0`). An arm `:PERF=nolooks` leaves the looks' prewarm out. It writes `live_crowd.json`: the still frame interval's p50 and p99 and the `views:` and `batches:` lines; walking, the longest frame, frames over 50 ms and first-sight `hitch:` lines; the resident size, physical footprint and graphics memory (macOS `footprint`), each at peak and steady; the `assets:` line and the load average at each run's start and end.

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
| `RUST_LOG=living_game::characters::compose=debug`: `compose: material <file>#<material> takes toon …` | every outfit piece's `Cloth` one toon, every hair cut's hair one, far beards one, each overlay its own (Cullet: 36 style toons) |
| `composed/view.log` `rigged a VRoid model (… with N more meshes on its expressions)` | N = the overlays the person wears (Ode Pontil's beard and lines: 2) |
| `sec_bones` | a hair style with spring chains brings the same count as the whole file (Tamsin's braid: 5 and 5) |
| `composed/view.log` | `compose: … wears …: N meshes` once a person; no `could not be put on`, `did not load` or `joint … is neither` |
| `stills/<name>.jpg` | hair, cap, kerchief, apron, beard, stubble and every piece on; the iris in the line's `eyes`; no floating or missing piece; the known limits (an overlay's one strength, no blush, a smock's sleeve bands taking its hue); with `FAR=0.01` a bearded man's far model keeps his beard |

Colours, the town's people against their whole files, and sharing against one material a file:

```bash
python3 living/tools/characters/colour_check.py <binary> .local/living/<run>/colour [name ...]   # default: the whole town; about 55 min for 64 (five arms, four shots)
```

| Read | Pass |
| --- | --- |
| `colour.json` `summary.sharing` | `composed_vs_perfile` within `composed_vs_again` (two runs of the same thing): sharing materials changes no pixel beyond the runs' own noise |
| `summary.delta_e` (head, torso, legs, face) | where a composed person's colours moved from their whole file's, by band (CIE76 ΔE of the band's mean); `summary.worst` names the bands to look at in the shots. Known movers: lines and blush on faces, aprons and smocks' sleeve bands |
| `summary.eyes` (and `colour.json` `eyes`) | the iris body's CIE76 ΔE, from the `eyes` arm's pure-green irises: composed and whole each against the line's eye colour (`colors.eyes_natural`, else `colors.eyes`; both carry the lighting and the lights' glow), and `composed_vs_whole` once each whole close-up is laid onto its composed one (`whole_shift_px`). On char-4's `9207d6a8`: 22.8, 22.4 and 5.5 at the median. A child's close-up can miss the eyes (in the hair): judge the largest by eye. `REUSE=1` measures a run again without the client |

Cost, the town's 64 as they are, both modes interleaved (`town` is each person's whole file, `composed` the same recipes with the switch on):

```bash
python3 $C .local/living/<run>/town .local/living/<run>/cost --runs x:empty,x:town,x:composed,x:composed,x:town,x:empty --repeat 2 --seconds 30 --binary x=$B/living-game
python3 $C … --runs x:town,x:composed,x:composed,x:town --repeat 3 --game-env LIVING_GAME_FAR=1000 --tag=-near   # everyone on the full model
```

| Line | Pass |
| --- | --- |
| `people ready: 65 characters (64 composed) …` | 64 composed with the switch on, 0 off |
| `people perf: … N mesh entities shown of M` | at the game camera (all far): 460 of 1,406 composed, 210 of 850 whole (Cullet's 97 shared files; char-4 `d82e7762`, a face 7 primitives with the brows) |
| `views: … [people …, P mesh-material pairs]` | the draws the people make once instanced: 104 composed against 210 whole at the game camera, 244 against 658 on the full model |
| `batches: preprocessing culling (multi-draw); opaque S sets …` | one set a material: 17 composed against 10 whole at the game camera, 53 against 84 on the full model. Style toons are keyed by content and source colour (`compose.rs`): they share only where the result is the same, so the count falls as the generator's pieces come to share one shading mean. `LIVING_GAME_PERF=filestyles` keys one a file, to compare |
| `--perf matnames`: `view materials: <material name> ×N, …` | people's distinct materials in view by name: composed `M00_000_00_EyeIris_00_EYE ×1` and `M00_000_00_FaceBrow_00_FACE ×1` (one each, shared by every type), whole files ×64 an iris |
| `assets: N meshes M MiB (… morph targets …)` and `batches: … textures … MiB` | composed far below whole: mesh data and morph targets, and GPU textures |

## Gotchas

- Run each binary once before measuring: Metal's shader cache is per binary, and a cold one gives a first run of 5 s frames.
- macOS process memory (RSS, `footprint`) moves by gigabytes with the other agents' load. Use the `assets:` line for what the people hold.
- `crowd.py`, `compose_check.py` and the foot-slide and stills harnesses each rewrite `recipes.json` for a run and restore it after. Never run two at once.
- Composing is the default since compose-client-2: a run that means a town person's whole file (a foot-slide run as `LIVING_GAME_PLAYER=<town recipe>`, a view of one) sets `LIVING_GAME_COMPOSE=0`. `crowd.py`, `compose_check.py` and `colour_check.py` set it for their whole arms.
- Other clients on the same GPU (another worker's tour or film) can make a run die about a second in with Metal's `Cannot allocate sample buffer` and `DeviceLost` (the `diag` flag's GPU counters). `crowd.py` then reports nulls for that run: check `ps` for other `living-game` processes and run it again.
- The frame time is not a performance claim (docs/PERFORMANCE_CONTRACT.md): interleave the sets and report the load average.
