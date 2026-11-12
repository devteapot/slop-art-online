# Characters: the generator

The game's people are made by our own tool: a set of parameters goes in, a rigged, painted, animated character file comes out. This replaces VRoid Studio bases (decision 2 of [the small city](SMALL_CITY.md)). The owner's bar is VRoid's quality close up, from a parameterized tool of our own.

**Status (2026-11-11, branch `char-4`, pass 3 of the track: step 1, crowd cost; step 2, types and rig as data; step 3, the cage head for each type with the rig in it; step 4, designed shadows; step 5, lines where the form turns; hair as shared style files; outfits as shared style files; overlays; the hair's finish):**

- **The bar is the reference character:** the VRoid model the game has used so far (`lookdev/vroid-Sendagaya_Shino.glb`; the asset board's control `vroid=recipe:shino`), close up included. The owner accepted pass 1 as the base and said of it: "a step up … but still far away from the reference model we have been using so far. That is kind of what we want to get to".
- **Pass 1 (`char-2`):** faces and the parameter model. A seed or a parameter file gives a repeatable person of any sex and age from 1 to about 80, with real eye openings, a mouth that opens, 15 expressions under VRoid's names, stubble and six beard styles, age lines and freckles. One command makes a household or a whole town and its check page.
- **Pass 2 (`char-3`):**
  - hair built the way the reference builds it: a cap and layers of broad locks with a strand texture, fifteen styles from eight parameters, long hair on spring bones;
  - every face drawn toward the reference by one style number;
  - brows and lashes from strands;
  - the iris as a layer of its own on eye bones, so eyes can look round;
  - a tool that measures what a crowd of generated people costs in the game.
- **Pass 3, step 1 (`char-4`): crowd cost.** The owner accepted pass 2 as the new base. Nothing about the look was meant to change in this step:
  - every person's file is six meshes, one for each kind of shading, where it was 12 to 14;
  - the strand texture is one shared file, and a town's faces are tiles on shared pages, so 64 people bring 12 materials where they brought 195;
  - a far model of about 6,000 triangles comes from the same parameters;
  - `town.py` reads Cullet's actual cast from the world seed;
  - a seed keeps its hair colour as it ages;
  - measured on the 64 residents: about 11 ms a frame where pass 2's files took about 20 ms, and about 8 ms for the far models, on a loaded machine ([crowd cost](#crowd-cost)). The client needs three changes to use all of it, listed there.
- **What comes next changes how a person is made.** After the owner's verdict and two research reports ([the reference taken apart](CHARACTER_REFERENCE.md), [the survey](CHARACTER_RESEARCH.md)), identity moves onto bones over a few shared meshes for each type of face and body, and per-person baked meshes stop. See [what later passes need](#what-later-passes-need). The per-person pages and far models of step 1 are the stop-gap until then; the shared strand texture, the six meshes, the client's three changes and the measuring tools carry over.
- **Pass 3, step 2: types and rig, as data and diagrams, before any mesh** ([types and rig](#types-and-rig)). No generated file changes in this step.
  - **The rig:** 25 new bones under the head carry identity through 38 values; 31 of pass 2's 34 values keep their names on them.
  - **The types:** 21 designed face types (three for each sex and age band, three for children), set from the reference's measurements, with body types tied to them (`living/tools/characters/types.json`).
  - **The parameter model:** a person is a type plus values bounded by their distance from it; families share a line and 0.7 of their values.
  - **The client format:** a person is a recipe line (type id, values, colours, style ids) over shared type and style files.
  - **No wall for bones.** No clip keys anything but `J_Bip_*` rotations and the hips' translation; a probe file in the game holds a posed face through four clips; about 105 joints of Bevy's 256; and bones leave about 0.3 mm of what pass 2's values do.
- **Pass 3, step 3: the cage head for each type, with the rig in it** ([the cage head](#the-cage-head)). From this step the generator's people have a type's head, and identity is in bones.
  - **The head** is a quad cage through each type's measured sections, subdivided and fitted so the surface passes through the designed points: about 4,300 triangles for the whole skull. All 21 types are built by one script and each is within 0.03 of a head height of what it was built to, measured with the reference's own tool.
  - **The eye** is set the reference's way: the iris a flat disc 4 mm behind the lid, the white a bowl falling away 15 mm, the lid's rim folded in.
  - **A person is the type's mesh with 25 identity bones moved.** The same person baked into the vertices differs by 0.00 mm on every mesh, and the clips play on it unchanged.
  - **Type files** are written to the client format's paths (`lookdev/types/<type>.glb`, about 0.93 MB each), with outline normals in them.
  - **Every value end, alone and in pairs, is a valid head on every type** (60,648 of 60,648) after nine ranges were trimmed.
  - **Lips and blush do not survive the client's one-colour recolour of a shared skin texture;** the lid's shade does. They are to become their own small meshes or overlay styles ([what the client needs for types](#what-the-client-needs-for-types)).
- **Pass 3, step 4: designed shadows** ([designed shadows](#designed-shadows)). The straight split down the middle of the face and the dark band along the jaw are gone.
  - **The shadow map is drawn, not derived.** For each type a script draws the shade at 18 light angles from the type's landmarks (the side plane, the nose's wedge, the socket, the jaw; flat until about 55°, after step 4b), turns each drawing into a distance field and interpolates them into one threshold map, `lookdev/types/<type>.face.png`.
  - **The face's normals come from a planar proxy** laid out from the same landmarks, and the skin under the jaw is one plane looking down.
  - **The map's format is unchanged,** so today's client draws it as it is.
- **Pass 3, step 5: lines where the form turns** ([lines](#lines-where-the-form-turns)).
  - **Shell lines in the files:** an edge under the jaw and chin, round the ears and along the upper lip, as geometry in the face's line primitive; a heavier one under the jaw of the far head.
  - **Per-vertex outline width in the files** (`_OUTLINE_WIDTH`: none on lids, lashes and lines, heavier along the jaw, lighter on hair), beside the outline normals, which stay separate from the lighting normals.
  - **Close up the jaw's line reads; at the game camera it does not** on the near head, and is one darker pixel row on the far head. A line that holds its width on screen needs the client's outline pass; the exact need is written there.
  - Cost: 496 triangles and 37 kB a type file (4%).
- **Pass 3, hair** ([hair styles](#hair-styles)).
  - **Why hair looks washed out and half transparent close up: the client's rim light,** added in one pale colour whatever the surface's own, which on dark hair is several times the hair's colour; and the film gradient near the top of the frame. Not alpha (the hair is opaque), not the shared strand picture (the same bytes), and no normals of ours avoid it. Where and what is written for the laptop.
  - **Hair is 13 shared style files** (`lookdev/styles/hair/<style>.glb`, 4.4 MB together), each built once on one standard head, with its far mesh, its spring chains under `J_Id_Cranium`, neutral shades for the tag to colour, and no clips.
  - **Each type's file carries a fit** of the standard head onto its own (`hair_fit`), so one style sits on all 21 types.
  - **A head composes from a type file and a style file the client's way:** read as glTF it matches the generator's rule to 0.000 mm, and Blender's reading agrees to 0.007 mm.
- **Pass 3, outfits** ([outfit pieces](#outfit-pieces)). A whole person now composes from shared files.
  - **26 outfit piece files** (`lookdev/styles/outfit/<piece>.glb`, 6.8 MB): jersey (alone, under a coat, under a smock), coat, six smocks, trousers and boots, each for a man's and a woman's body, and a cap and a kerchief; each with its far mesh, no clips. Hair gained `balding`, `kerchief` and seven styles as worn under a cap.
  - **Build is the bones':** a piece is built once at the standard build, and the person's girth goes into the recipe's `build`, which the client's proportions already apply.
  - **Three Cullet residents composed the client's way** (type, hair with its tie, outfit pieces, a cap, identity and build): every attached mesh matches the rule to 0.000 mm. Against each person's own file the clothes differ by 2.0 to 9.7 mm (root mean square), most on a heavy man.
  - **Cullet's 64 residents wear 51 shared files, 26.4 MB,** where their own files are 149 MB: 121 unique meshes where there were 448. A person is 9 to 11 mesh entities where their own file was 7.
  - Beards, stubble, lines and the apron followed in [the overlay step](#overlay-styles).
- **Pass 3, overlays** ([overlay styles](#overlay-styles)). A composed person now keeps what their own file had.
  - **Beards, stubble, age lines and freckles are overlay styles:** a thin layer over a type's own face with a grey picture and an alpha, tinted by the tag. 72 files for the types that can wear them (8.1 MB).
  - **The apron is a piece of its own,** with its own colour.
  - **The iris is a material of its own** (`…EyeIris_00_EYE`) with its own picture, so the tag for the eyes' colour reaches it.
  - **A belly is a bone** (`J_Fit_Belly`), moved forward by the person's `belly`.
  - **Four Cullet residents composed against their own files:** every attached mesh matches the rule to 0.000 mm; clothes of ordinary build are within 1.3 to 3.2 mm of the own file's, and a full beard within 0.3 mm.
- **Pass 3, the hair's finish** ([hair finish and cuts](#hair-finish-and-cuts)).
  - **The fringe** is finer locks to one line where it was seven broad blocks; **the ends** of hanging hair are cut to one hem; **the temple** is covered: the hairline on a type's head comes down to a sideburn and sits close over the ear.
  - **Three cuts of every style** (`<style>`, `.2`, `.3`): 50 hair files, 17.0 MB. Cullet's 64 wear 30 of them where they wore 14, and six people (three pairs) share both a file and a colour.
  - **A far beard** for the far head: one plain mesh a beard form, about 450 triangles.
- **Not yet at the bar:** see [what still separates ours from the reference](#what-still-separates-ours-from-the-reference). In short: the eyes' drawing, the face's painted softness, clothes and silhouette, hands, and hair that is still locks of one thickness.
- The models are not yet used by the running game's residents. That is phase 5 of the small city's build plan.

## Commands

All output is git-ignored: the scripts are the asset.

```bash
# One person: generate, add the clip library, merge primitives, add the face's shading data.
living/tools/blender/gen_person.sh man woman           # presets: man, woman, elder, youth, boy, girl, heavy
living/tools/blender/gen_person.sh 12                  # the person of seed 12
living/tools/blender/gen_person.sh halvard=halvard.json  # a parameter file, under a name
PERSON_ARGS="--set age=70 --set beard.style=full" living/tools/blender/gen_person.sh old=12

# A person's parameters, without building anything.
python3 living/tools/blender/person_params.py --seed 12 > person.json   # edit, then pass back as a file
python3 living/tools/blender/person_params.py --seed 12 --set age=70 --set face.jaw_width=0.8

# A sheet of faces through the game's renderer (rest pose, no clips): the quick way to judge a change.
# Each view is photographed three times and the take with the eyes open is kept (the game blinks by itself).
python3 living/tools/characters/faces.py out.jpg man woman 12 13+age=70 "woman+!Fcl_MTH_Fun=1"

# A household or the whole town, and the page to check it by (line-up, game camera, every face).
python3 living/tools/characters/town.py .local/town                    # the stand-in for Cullet, 64 people
python3 living/tools/characters/town.py .local/town --household kiln-03
python3 living/tools/characters/town.py .local/town --town cullet.json  # a town file
python3 living/tools/characters/town.py x --write-town cullet.json      # save the stand-in to edit

# What a crowd of them costs in the game: frame time, triangles, materials, draws and memory.
python3 living/tools/characters/crowd.py .local/town .local/crowd      # 64 of ours, 64 VRoid, and the empty scene
python3 living/tools/characters/crowd.py .local/town .local/crowd --runs ours --perf nooutlines --tag=-nooutlines
python3 living/tools/characters/crowd.py .local/town .local/crowd --runs same --tag=-one                   # 64 people, all one file
python3 living/tools/characters/crowd.py .local/town .local/crowd --runs ours,far,far,ours --repeat 4      # the far models beside the full ones, interleaved
python3 living/tools/characters/crowd.py .local/town .local/crowd --set old=.local/town-old --runs old,ours,ours,old --repeat 4   # another town's files beside this one's

# The eyes turned in the file, to photograph a look (degrees of the eyes' bones; about 6 is fully aside).
blender -b -P living/tools/blender/person.py -- --variant woman --look 6,0 --out x.glb

# The far model too (about 6,000 triangles, for beyond 10 m), as a character file of its own.
LOD=near,far living/tools/blender/gen_person.sh man woman   # lookdev/far/own-man.glb, lookdev/far/anim/…
LOD=both living/tools/blender/gen_person.sh man             # one file, the far model's meshes named Far* (lookdev/lod/)

# The actual Cullet cast from the world seed: full and far models, faces on shared pages.
python3 living/tools/characters/town.py .local/town --town living/seeds/cullet.json
python3 living/tools/characters/town.py .local/town --town living/seeds/cullet.json --models-only   # no photographs

# What a file holds (meshes, materials, pictures), and textures shared between files by hand.
python3 living/tools/characters/share.py list living/game/assets/lookdev/anim/own-man.glb
python3 living/tools/characters/share.py pages --name set living/game/assets/lookdev/anim/own-{man,woman}.glb

# Whether two people's baked clips are the same motion.
python3 living/tools/characters/clips_compare.py living/game/assets/lookdev/anim/own-{man,woman}.glb

# The comparison page beside the VRoid control (the same shots and clips for each).
living/tools/characters/capture.sh cullet-man ours .local/cap all
living/tools/characters/capture.sh cullet-man ours .local/cap motions   # whole clips, to judge a motion (MOTIONS=…)

# Measure baked clips on a character's own mesh: lowest point against the floor, how busy the hands
# are, how much it moves, hops, foot travel.
blender -b -P living/tools/blender/clip_check.py -- --in living/game/assets/lookdev/anim/own-man.glb --clips gather,work
python3 living/tools/characters/media.py .local/cap .local/page .local/town .local/sheets
python3 living/tools/characters/page.py .local/page
```

A pass is also published through the asset board, the record of which version the owner accepted (`docs/ASSET_BOARD.md` and `living/tools/board/board.py`). Its records are in `living/assets/board/`.

- Pass 1 is the `character:*` families' versions `20261111-0df94138-…`, which the owner accepted as the base.
- Pass 2 is their versions `20261111-f32f73f9-…` (`adult-woman`, `adult-man`) and `20261111-27e84b1a-…` (`elder-man`, `youth`, `boy`, `heavy-man`, `cast-64`), each beside pass 1 and the VRoid control `vroid=recipe:shino`, photographed with the same shots and clips. The generator and the models are the same for both commits; the second only added documentation and the crowd tool.

- Pass 3's first step (crowd cost) is their versions `20261111-4448a7e8-…`, beside pass 2 and the control. The six presets are the same people in six meshes, so their photographs should match pass 2's; `cast-64` is now Cullet's actual cast from the world seed, not the stand-in, so its people differ.

- Pass 3's third step (the cage head) is their versions `20261111-26c98cc2-…`: the six presets on their types' heads beside step 1's and the control, `cast-64` with identity in bones, and `character:face-types` with every type as a bare head, three people drawn from each close up and at the game camera, one person composed against baked, the skin-tone sheet and the children's heads beside the adults' at one scale, with the VRoid and Blue Protocol rows.

- Pass 3's fourth step (designed shadows) is their versions `20261112-1fa6fc0f-…`: the six presets and `cast-64` under the board's fixed light beside step 3's, and `character:face-types` with the drawn shapes at every angle, the light sweeping across four faces close up and at the game camera, before and after, and the reference under the same sweep.

- Step 4b is `character:face-types` `20261112-1fc23e0d-b70164` (step 4 above 4b under the sweep, eyes held open). Pass 3's fifth step (lines) is the versions `20261112-2c79242a-…`: the lines on bare type heads, four presets close up before and after, the head at the game camera near and far, the six presets and `cast-64`.

- The hair step is `character:face-types` `20261112-6cd9d9f4-…`: the wash tests, six shared styles on five types, four presets' hair before and after, and one person composed. The six presets and `cast-64` were not published again: their files changed only in where the spring chains hang.

- The outfit step is `character:face-types` `20261112-c512a401-…`: three Cullet residents composed from shared files above the same people from their own files.

- The overlay step is `character:face-types` `20261112-5511f776-…`: four Cullet residents composed with their beards, stubble, lines, aprons, eye colours and bellies above the same people from their own files.

`just living-town .local/town` runs `town.py`; `just living-people` runs `gen_person.sh`. A pass's own report page is written by `living/tools/characters/report.py` from the board's media and a notes file.

`gen_person.sh` needs Blender and, for clips, the Kimodo library's takes (`KIMODO_DIR`, default `.local/kimodo/outputs/library`); it bakes the whole library unless `ONLY` names clips. `ONLY=present` bakes the entries whose takes are all there, for a machine whose copy of the library is behind `clips.json` (on 2026-11-11 the dev-box had 30 of 67: the takes of the re-made town motions and of the new locomotion clips had not reached it). The photographs need the game's release build; `view_assets.sh` honours a private `CARGO_TARGET_DIR`. A person takes about 6 s to generate; adding two clips takes about 6 s more and 30 clips about 15 s. 64 people with `idle` and `walk` and their photographs took 5 minutes with six jobs on a loaded dev-box (pass 2, 2026-11-11; hair adds under a second a person). With the far models as well (pass 3), the 64 took 6 minutes to build and page, and their photographs 7 more.

## A person's parameters

A person is a small JSON object. Every value is optional.

```json
{
  "seed": 12,
  "family": 1003,
  "sex": "female",
  "age": 29,
  "build": { "height": 1.62, "weight": 0.0, "muscle": 0.0 },
  "face": { "jaw_width": 0.4, "eye_size": -0.3, "nose_length": 0.5 },
  "skin": { "tone": 0.26, "freckles": 0.0, "weathered": 0.1 },
  "eyes": { "colour": "green" },
  "hair": { "style": "bob", "colour": "auburn", "grey": 0.0, "length": 0.08, "parting": -0.3, "fringe": 0.9, "volume": 0.5, "curl": 0.1 },
  "beard": { "style": "none", "stubble": 0.0 },
  "outfit": { "coat": "smock", "coat_colour": "green", "jersey_colour": "navy", "headwear": "none", "apron": true }
}
```

- **A seed gives a repeatable person.** Each missing value is drawn from its own random stream named by the seed and the parameter. Setting one value never changes another, and adding a parameter later does not reshuffle existing people.
- **Sex and age are settled first.** Most other values are drawn round them: a child's height, a man's beard, an elder's grey hair.
- **A file or `--set` overrides any value.** `--set a.b=value` takes JSON values (`--set outfit.apron=false`).
- **`family` makes relatives.** People who share it take about half of each face value from the family's draw, and usually its skin tone, eye and hair colour.
- Beside each model the generator writes `<name>.params.json`: the full parameters it used and the game recipe it implies. Edit that file and pass it back to change the person.
- **A seed keeps its hair colour as it ages** (fixed in pass 3). Until then a child's draw gave blond twice the weight, which moved every colour's share, so one seed in four changed hair colour when its age crossed 16. The draw now uses the adults' weights at every age: no adult changes, and about a quarter of seeded children get a different colour than pass 2 gave them (in Cullet's cast two: Tilly Dunlin and Col Roon, blond to sandy).

| Parameter | Values | Drawn from the seed as |
|---|---|---|
| `seed` | integer | given (0 if missing) |
| `family` | integer or text | none; relatives who share it share part of their face, skin, eyes and hair colour |
| `sex` | `male`, `female` | even |
| `age` | years, 1 to about 80 | Cullet's mix: 14 children (2 to 16), 44 adults (18 to 59), 6 elders (62 to 78) in 64 |
| `build.height` | metres | by age and sex (adults about 1.77 ± 0.055 m for men, 1.64 for women; a growth table under 18) |
| `build.weight` | -1 lean to 1 heavy | normal round 0 |
| `build.muscle` | -1 slight to 1 strong | normal round 0, a little higher for men |
| `skin.tone` | 0 fairest to 1 darkest | mostly fair to medium; from the family when one is given |
| `skin.freckles` | 0 to 1 | about a quarter of people, more on fair skin and on children |
| `skin.weathered` | 0 to 1 (ruddier, deeper, lined) | rises with age |
| `eyes.colour` | `blue`, `grey`, `green`, `hazel`, `amber`, `brown`, `dark_brown`, or `[r, g, b]` | by skin tone; often the family's |
| `stylise` | 0 to 1: how far the face leans toward the reference's drawing | not drawn; the town's one number, `STYLE["toward"]` = 0.70 ([Style](#style-the-numbers-set-toward-the-reference)) |
| `hair.style` | `crop`, `short`, `tousled`, `swept`, `shag`, `bob`, `bob_parted`, `long`, `tail`, `bun`, `braid`, `braids`, `sides`, `kerchief`, `balding` | by sex and age. Men whose hairline has gone far back get `balding`; a cap brings `sides`, a headscarf `kerchief` |
| `hair.colour` | `black`, `dark_brown`, `brown`, `chestnut`, `auburn`, `sandy`, `blond`, `grey`, `white`, or `[r, g, b]` | by skin tone; often the family's. The same at every age since pass 3 (see below) |
| `hair.grey` | 0 to 1; hair greys lock by lock before it greys all over | rises from about 36 |
| `hair.length` | metres the hair hangs below the hairline over the ear (`shag`, `bob`, `bob_parted`, `long`, `tail`, `braid`, `braids`), or a bun's size. For the short styles it scales the hairs' own length round 0.07 | by style: a bob 0.05 to 0.11, long hair 0.20 to 0.36, a tail 0.10 to 0.28 |
| `hair.parting` | -1 to 1: where the hair parts, from the character's right to the left, 0 the middle. A swept fringe falls away from it | normal round 0 |
| `hair.fringe` | 0 none to 1 at the brows (up to 1.3, over the eyes) | 0.5 to 1.05; grown men 0.3 to 0.9 |
| `hair.fringe_style` | `auto` (the style's own), `straight`, `swept`, `curtain` | `auto` |
| `hair.volume` | 0 flat to 1 full: how far locks stand off the head and how thick they are | 0.25 to 0.85 |
| `hair.curl` | 0 straight to 1 curly: waves along each lock | mostly straight (mean about 0.2) |
| `hair.recede` | 0 to 1: men's front hairline; with `balding`, how far the bald crown reaches | rises with age |
| `beard.style` | `none`, `stubble`, `moustache`, `goatee`, `chinstrap`, `short`, `full` | men from 17; fuller with age |
| `beard.stubble` | 0 to 1 (shade on the jaw and lip) | light for most men |
| `outfit.coat` | `coat`, `smock`, `none` | by sex and age |
| `outfit.coat_colour`, `outfit.jersey_colour`, `outfit.headwear_colour` | `oilskin`, `tarred`, `olive`, `canvas`, `blue`, `red`, `green`, `cream`, `navy`, `heather`, or `[r, g, b]` | Cullet's cloth; the exact shade is drawn within the name's range |
| `outfit.headwear` | `none`, `cap`, `kerchief` | caps on some men, kerchiefs on some women |
| `outfit.apron` | true, false (on a smock) | most women |
| `outfit.hem` | metres above the ground a smock ends | 0.50 to 0.74 |

Cloth names and their ranges are in `person_params.py` (`CLOTH`); every colour comes from Cullet's palette ([SMALL_CITY.md](SMALL_CITY.md) §1).

### The face

Each value runs from about -1 to 1 round the average for the person's sex and age; 0 is that average. Seeds draw them from a normal distribution of width 0.52, clipped at ±1. Sex, age and weight move the average: a man's jaw is wider and his eyes smaller, a child's eyes are large and low and the nose small, age lowers the lids and lengthens the nose and ears, weight fills the cheeks.

| `face.` | at -1 | at 1 |
|---|---|---|
| `face_length` | short lower face | long lower face |
| `face_width` | narrow | wide |
| `forehead` | low, sloping | high, full |
| `cheekbones` | narrow, soft | wide, set |
| `cheeks` | hollow | full |
| `jaw_width` | narrow jaw | wide jaw |
| `jaw_square` | tapered jaw | square jaw |
| `chin_length` | short chin | long chin |
| `chin_width` | pointed chin | broad chin |
| `chin_forward` | receding chin | jutting chin |
| `brow_ridge` | smooth brow bone | heavy brow bone |
| `eye_size` | small eyes | large eyes |
| `eye_spacing` | close-set | wide-set |
| `eye_height` | eyes low on the face | eyes high |
| `eye_open` | narrow | round, open |
| `eye_tilt` | outer corners down | outer corners up |
| `eye_shape` | lid peaks toward the nose | lid peaks outward |
| `iris_size` | small iris | large iris |
| `eye_fold` | no lid fold | deep lid fold |
| `brow_thickness` | thin brows | heavy brows |
| `brow_height` | low brows | high brows |
| `brow_tilt` | inner ends high (mild) | inner ends low (stern) |
| `brow_arch` | straight brows | arched brows |
| `brow_length` | short brows | long brows |
| `nose_length` | short nose | long nose |
| `nose_width` | narrow nose | broad nose |
| `nose_bridge` | low, scooped bridge | high, arched bridge |
| `nose_tip` | tip turned down | tip turned up |
| `mouth_width` | small mouth | wide mouth |
| `mouth_height` | mouth close under the nose | mouth low |
| `lip_fullness` | thin lips | full lips |
| `mouth_curve` | corners down | corners up |
| `ear_size` | small ears | large ears |
| `ear_out` | ears flat to the head | ears standing out |

### Style: the numbers set toward the reference

One number says how drawn the whole town's faces are: `STYLE["toward"]` in `person_params.py`. At 0 a face keeps the proportions of life that pass 1 had; at 1 it has the reference's. It is set to **0.70**. A person's `stylise` overrides it for that person. The owner did not ask to choose these; they were set in pass 2 by measuring the reference and looking at the results (the pass-2 page shows 0, 0.35, 0.7 and 1 side by side).

The figures are the woman preset's with every face value at 0, computed from `head_form.py`; the reference's are measured on its mesh.

| What | Pass 1 (0) | Chosen (0.70) | At 1 | The reference |
|---|---|---|---|---|
| Eye centre, as a share of the head's height above the chin | 53% | 47.5% | 45% | 39% |
| Eye opening, height over width | 0.52 | 0.66 | 0.72 | 0.77 |
| Iris width, as a share of the eye's | 52% | 61% | 63% | about 62% |
| Iris against the opening | fills its height | the same; the upper lid crosses its top | the same | the same |
| Head, width over height | 0.65 | 0.70 | 0.72 | 0.80 |
| Figure, in heads | 7.0 | 7.0 | 7.0 | 7.0 |
| How far the nose stands out | 1 | 0.73 | 0.62 | barely modelled |
| Mouth width | 1 | 0.90 | 0.85 | small |
| Chin width | 1 | 0.83 | 0.76 | a point |
| Brow thickness | 1 | 0.86 | 0.80 | a thin line |
| Lash line weight | 1 | 1.39 | 1.55 | heavy, with a wing |
| Lash colour | near black | 70% of the way | `(0.24, 0.10, 0.09)` | a warm dark red-brown |

- **Why 0.70 and not 1.** The town has bearded men, elders and small children, and the reference is one young woman. At 1 a lined, bearded face with eyes that tall stops reading as an old fisherman. At 0.70 the women and children are most of the way to the reference's proportions and the men still look grown.
- **Men and elders take less.** A grown man's face takes 66% of the number (`STYLE["men"]`) and an old face 85% of that again (`STYLE["elders"]`). With 0.70 a man's eye opening goes from 0.41 to 0.48 and his eyes from 56% to 52% up the head. Children already had large low eyes, so the number moves them about half as far.
- **The head grows with it** (`STYLE["head"]`, 8.5% at 1, on top of the 8% the generator always had). The lower face shortens, and without this the head would shrink against the body. The figure stays 7.0 heads tall, as the reference is.
- **Still short of the reference at 1:** the eyes are not as low and the head not as wide. Those two need the skull's form changed (a wider, rounder cranium), not a number; see pass 3.
- The other entries are `STYLE["lash"]` (how much heavier the lash line is at 1) and `STYLE["lash_colour"]`.

### What age changes

| Age | What the generator does |
|---|---|
| 1 to 16 | A child's face in proportion to how young: larger, lower eyes, a short lower face, full cheeks, a small scooped nose. Height from a growth table. The recipe gives a larger head and shorter limbs. |
| 11 to 18 | Sex differences come in: jaw, brow, lashes, shoulders. |
| 17 on | Men may have stubble or a beard. |
| 30 on | Lines begin: folds beside the nose, then crow's feet, forehead lines, lines from the mouth's corners. `skin.weathered` adds to them. |
| 36 on | Hair greys (`hair.grey`), beard a little ahead of the head. Men's hairlines recede. |
| 46 on | An elder's face: lower lids, thinner lips, hollower cheeks, jowls, larger nose and ears, heavier brows on men. Height drops a little. |

### Into the game

`gen_person.sh` writes `lookdev/own-<name>.glb` and `lookdev/anim/own-<name>.glb`, and with `LOD=near,far` the far model as `lookdev/far/own-<name>.glb` and `lookdev/far/anim/own-<name>.glb`, a character file like any other. A recipe in `living/game/assets/characters/recipes.json` names the file as its `base` with the height and proportions from `<name>.params.json`. `python3 living/tools/blender/person_params.py --variant man --recipe man` prints that line. The presets' recipes are `cullet-man`, `cullet-woman`, `cullet-elder`, `cullet-lad`, `cullet-boy`, `cullet-girl` and `cullet-heavy`. Height and a child's proportions are the recipe's; everything else is in the file. A recipe's `colors` are for the VRoid bases: on a generated person the skin slot would tint the painted beard and lips with it, so colour belongs in the parameters.

## How a person is built

| Part | Script | How |
|---|---|---|
| Parameters | `person_params.py` | `draw()` fills in a person; `resolve()` turns them into the generator's numbers and the recipe. Plain Python. |
| The head's form | `head_form.py` | A loft: at each height a superellipse set by four curves (the front view's half width, the profile's front and back, how boxy the front is). The outline of jaw, cheekbones and chin and the profile are therefore set directly. Nose, brow ridge, eye hollows, cheeks, lips and chin are bumps on the front. |
| The head's mesh | `head_mesh.py` | A cube-sphere projected onto the form, denser from the brows to the lip. The skin round each eye is cut away and stitched to a clean ring on the lids, with a rim turned inward as far as the eye. The skin is slit along the mouth; the lower edge drops with the jaw and shows teeth, the dark and the tongue. Ears are lofted rings. |
| The eyes | `head_mesh.py` | Each eye lies on a ball of 8 cm radius set behind its opening. The white is a patch of the ball. The iris is its own disc just off the white, weighted to the eye's bone (`J_Adj_L_FaceEye`, `J_Adj_R_FaceEye`, at the ball's centre), so turning the bone slides it. Two highlights sit over it and follow the bone half way. `person.py --look` turns them in the file. |
| Brows and lashes | `head_mesh.py` | Strands, made as the hair's locks are in small: each a tapering, bending card standing off the skin, with its own tone. A brow is 22 to 34 hairs over a soft shape, growing up at the inner end and sweeping out along the brow. A woman's upper lid carries 9 lashes and 4 under the outer corner. The lash line and its wing stay a drawn shape. They move with the expressions. |
| Expressions | `head_mesh.py` | The whole face is built again for each expression's state (lids, jaw, mouth corners, brows); the difference is the morph target. |
| The face's texture | `face_paint.py` | One 1024² atlas a person: the whole head's skin, the two eyes, a swatch for the ears. Each texel knows where on the head it lies, so paint follows the form. Painted: tone, blush, shade round eyes, nose and lip, lips, nostrils, the lids' edge, stubble, beards as fine strokes, age lines, freckles; each eye as white, lid shadow, iris with dark rim, gradient, lit crescent and rays, pupil, two highlights. |
| Beards | `head_form.py`, both above | A beard is the skin itself standing off the face (2 to 7 mm, a full one hanging below the chin) with its hairs painted, so its edge is a painted edge, not a mesh edge. |
| Hair | `hair.py`, `person.py` | See [how hair is built](#how-hair-is-built). |
| Body, clothes, hands | `person.py` | As in the spike: lofted cages with written weights, garments as offsets of the body's form, vertex colours with painted shade. `build.weight` sets the torso's and limbs' girth and a belly; `build.muscle` the chest, shoulders and limbs. |
| Meshes | `person.py` (`join_kinds`) | Since pass 3 a person is six meshes, one for each kind of shading: `Cloth` (every garment, buttons, ties and headwear), `Skin` (hands and neck), `Hair`, and the face's three (`…Face_00_SKIN`, `…Eye_00_EYE`, and one `…_FACE` material for lash lines, brows, highlights and the mouth's inside). Cloth, skin and lines are white materials with colour per vertex, so every person's are the same material in the game. Pass 2 made 12 to 14 meshes a person. |
| The far model | `person.py --lod far`, `head_mesh.FarFace`, `face_paint.paint_far`, `hair.Hair(detail=…)` | The same person from the same parameters at 5,300 to 6,700 triangles in three meshes (`FarCloth`, `FarSkin`, `FarHair`): the garments' cages without subdivision; a head on a 12×12 grid with no openings, its eyes, lash lines and brows painted onto a 256² picture; mitten hands; the same locks on the same paths with longer steps and three vertices across. No expressions. Alone it lists no spring bones, so its hair hangs rigid. `--lod both` puts it in the full model's file on the same skeleton. |
| Shared textures | `living/tools/characters/share.py` | The strand texture is one file, `lookdev/strands.png`, that every person's file names by path (`gen_person.sh` does this). `town.py` lays a town's face atlases out as tiles on shared pages (`lookdev/pages/<town>-<n>.png`, 4096², 16 people each; the far pictures on one 2048² page of 64), moves each file's UVs into its tile, and lays the face shadow maps out the same way. The game makes one material for each distinct content, so files that name the same picture share the material ([crowd cost](#crowd-cost)). |
| Export | `person.py` | One GLB under VRoid's conventions: `J_Bip_*` bones, material name tags, `Fcl_…` morph names, a VRM 0.x block. `animate.py`, `merge_primitives.py`, `face_normals.py` and the game take it unchanged. |

**Expressions.** The game drives `Fcl_EYE_Close` and `Fcl_MTH_A`. The file also carries `Fcl_EYE_Close_L`, `Fcl_EYE_Close_R`, `Fcl_EYE_Joy`, `Fcl_MTH_I`, `Fcl_MTH_U`, `Fcl_MTH_E`, `Fcl_MTH_O`, `Fcl_MTH_Fun`, `Fcl_MTH_Sorrow`, `Fcl_BRW_Angry`, `Fcl_BRW_Sorrow`, `Fcl_BRW_Surprised` and `Fcl_BRW_Fun`, and VRM expression groups (`a` `i` `u` `e` `o`, `blink`, `joy`, `fun`, `angry`, `sorrow`). `person.py --expression Fcl_MTH_Fun=1` writes a file that starts with an expression on, to look at it.

### How hair is built

`hair.py` (numpy only) makes the locks; `person.py` adds the cap, the texture and the bones.

1. **The cap.** The scalp's own quads inside the hairline, pushed out a few millimetres and given the strand texture running out from the crown, so no skin shows between locks. A `balding` head keeps its scalp where the crown is bare.
2. **Roots and directions.** A style lays out locks in layers (`hair.py`, the `_<style>` functions): where each starts on the scalp, which way it is combed, and how long it is or how low it hangs. The layers are `under` (the sides and back), `over` (from the parting across the top), `crown`, `bangs` (straight, swept or curtain), `temples`, `field` (short hair all over) and `gather` (drawn back to a tail's tie).
3. **Combing.** Every lock is walked from its root in 6 mm steps. It keeps its direction, bends toward the ground, and is pushed out of the head, the neck or collar, and the shoulders (`Comb`), so it flows over the skull and then hangs. Hair that lands on a shoulder slides forward or back off it.
4. **Curl** bends the walked path into waves.
5. **Ribbons.** Each path becomes a closed lens-shaped ribbon: five vertices across a flat front with turned edges, one behind, tapering to a point or cut blunt. A broad lock on the head bends across to follow the skull. Its shading normals turn only a little across the lock, so the head of hair shades as one mass.
6. **Colour and strands.** Colour is per vertex: the hair's colour, a tone of the lock's own, a darker root, grey hairs lock by lock. Each lock takes its own column of one grey strand texture (`hair.paint_strands`, 256×512, the same file for everyone, written beside the models as `strands.png`).
7. **Springs.** The locks of `long`, `tail`, `braid` and `braids` hang from chains of bones under the head (`J_Sec_Hair<chain>_<joint>`, a joint every 9 cm). The file's VRM block lists them with spheres on the head, neck and chest, and the game's spring bones swing them (`characters.rs`).

A braid is short fat locks crossing from side to side along a hanging path; a bun is locks wound round a ball.

Counted on the woman preset at each style's usual length:

| Style | Locks | Triangles in the locks | With the cap (2,500 to 2,800) | Spring chains |
|---|---|---|---|---|
| `kerchief`, `sides` (under headwear) | 10 to 26 | 600 to 1,000 | 3,200 to 3,700 | none |
| `crop`, `balding` | 39 to 46 | 1,400 to 1,700 | 4,000 to 4,400 | none |
| `short`, `tousled`, `swept` | 38 to 51 | 1,900 to 2,500 | 4,500 to 5,200 | none |
| `shag`, `bob`, `bob_parted` | 39 to 40 | 3,000 to 4,100 | 5,600 to 6,800 | none |
| `tail`, `bun`, `braid`, `braids` | 32 to 38 | 3,200 to 4,300 | 5,800 to 7,000 | 1 (a tail, a braid) or 2 (braids), none for a bun |
| `long` | 44 | 8,500 to 8,800 | 11,100 to 11,600 | 5, of 4 or 5 joints each |

The reference's hair is 16,400 triangles.

## Types and rig

Pass 3's second step (2026-11-11, branch `char-4`) set how a person is made from here on, as data and diagrams, before any mesh was rebuilt. Step 3 built it: [the cage head](#the-cage-head). Pass 2's head remains behind `person.py --loft`.

**The decision** (the dev-box coordinator's, after the owner's verdict on pass 2 and the two research reports): identity in bones, on a few shared meshes for each type. Per-person baked meshes stop.

- **A type** is a designed head: a complete set of skull and landmark values, built once by a cage script with its own designed normals, shadow map and line data. There are about three for each sex and age band, each with a body type tied to it.
- **A person** is a type plus bounded bone values. Families share a type's line and part of their values.
- **Why:** shadows and lines are designed once for a type and the bones carry them with the form; meshes, textures and clips are shared at the source; the far face is the same rig on a lower-detail mesh of the type.
- **What it takes from Blue Protocol** (one of the owner's named art references; [the survey](CHARACTER_RESEARCH.md), §2 rules 6 and 7): choose one of three face types and vary within it; move the face's five parts (brows, eyes, nose, mouth, outline) by bones and not by blend shapes, so a face copies cheaply to a crowd; a body type tied to the face type; height changing the head's proportion and not only the scale; a far face that is shared.

The data is [`living/tools/characters/types.json`](../living/tools/characters/types.json); the tool that makes, checks and draws it is `living/tools/characters/face_types.py`.

```bash
living/tools/characters/reference/run.sh .local/ref                         # the reference, measured (ref-1's tools; about a minute)
python3 living/tools/characters/face_types.py measure .local/ref            # the anchors into types.json (also needs .local/ref/avg: pass 2's average heads)
python3 living/tools/characters/face_types.py build                         # compose the 21 types
python3 living/tools/characters/face_types.py check                         # every type, drawn people and value ends are valid heads
python3 living/tools/characters/face_types.py draw OUT_DIR                  # the diagram sheets
python3 living/tools/characters/face_types.py person --seed 12 --sex female --age 29 --family 7
python3 living/tools/characters/bone_reach.py                               # can bones do what pass 2's 34 values do?
python3 living/tools/characters/rig_probe.py IN.glb OUT.glb --pose          # five probe bones on a pass-2 file, to see it in the game
```

### The rig

25 new bones carry identity, all under `J_Bip_C_Head`, named `J_Id_…`; the two eye bones the files already have (`J_Adj_L_FaceEye`, `J_Adj_R_FaceEye`) move under the orbits. A bone on the character's left has a mirrored twin on the right that takes the same values.

- **A value runs from -1 to 1 and 0 is the type.** At -1 the bone is at `least`, at 1 at `most`; the two need not mirror each other, so each direction has its own designed reach (a small nose is not a large nose run backwards).
- **Units follow the layer a bone sits on.** `move` is in thousandths of the head's height (‰H), in the frame of the bone's parent, so a child bone's value is scaled by its parents: the orbits ride the face block, and widening the face spreads the eyes before `eye_spacing` says anything.
- **The parts** are Blue Protocol's five (brows, eyes, nose, mouth, outline) plus the skull above them and the ears.

| Bone | Under | Part | Value | Does | Least to most | Was |
|---|---|---|---|---|---|---|
| `J_Id_Cranium` | `J_Bip_C_Head` | skull | `cranium_width` | scale x | ×0.94 to ×1.07 | new |
|  |  |  | `cranium_depth` | scale y | ×0.95 to ×1.06 | new |
|  |  |  | `cranium_height` | scale z | ×0.95 to ×1.07 | new |
| `J_Id_Forehead` | `J_Id_Cranium` | skull | `forehead` | move y | -12 to 16 ‰H | pass 2's `forehead`: low and sloping to high and full |
| `J_Id_Glabella` | `J_Id_Cranium` | brows | `brow_ridge` | move y | -4 to 12 ‰H | pass 2's `brow_ridge` |
| `J_Id_Face` | `J_Bip_C_Head` | outline | `face_length` | scale z | ×0.92 to ×1.095 | pass 2's `face_length`: everything below the eyes |
|  |  |  | `face_width` | scale x | ×0.94 to ×1.07 | pass 2's `face_width` |
| `J_Id_Corner_L`, `J_Id_Corner_R` | `J_Id_Face` | outline | `front_breadth` | move x | -16 to 12 ‰H | new: how broad the front planes are |
| `J_Id_Zygoma_L`, `J_Id_Zygoma_R` | `J_Id_Face` | outline | `cheekbones` | move x | -12 to 16 ‰H | pass 2's `cheekbones` |
|  |  |  | `cheekbone_height` | move z | -12 to 12 ‰H | new |
| `J_Id_Cheek_L`, `J_Id_Cheek_R` | `J_Id_Face` | outline | `cheeks` | move o | -9 to 20 ‰H | pass 2's `cheeks`: hollow to full, out of the cheek (0.55 away from the midline and 0.83 forward) |
| `J_Id_Jaw` | `J_Id_Face` | outline | `jaw_width` | scale x | ×0.88 to ×1.14 | pass 2's `jaw_width` |
|  |  |  | `jaw_angle` | turn x | -2 to 2.5 ° | new: a flatter or steeper jaw line (the chin up or down about the jaw's hinge) |
| `J_Id_Gonion_L`, `J_Id_Gonion_R` | `J_Id_Jaw` | outline | `jaw_square` | move x | -10 to 14 ‰H | pass 2's `jaw_square`: tapered to square |
| `J_Id_Chin` | `J_Id_Jaw` | outline | `chin_length` | move z | 20 to -28 ‰H | pass 2's `chin_length`: short (the chin's point up) to long (down) |
|  |  |  | `chin_width` | scale x | ×0.7 to ×1.4 | pass 2's `chin_width`: pointed to broad |
|  |  |  | `chin_forward` | move y | -16 to 20 ‰H | pass 2's `chin_forward` |
| `J_Id_Orbit_L`, `J_Id_Orbit_R` | `J_Id_Face` | eyes | `eye_spacing` | move x | -12 to 14 ‰H | pass 2's `eye_spacing` |
|  |  |  | `eye_height` | move z | -14 to 10 ‰H | pass 2's `eye_height` |
|  |  |  | `socket_depth` | move y | -10 to 8 ‰H | new: the eye set deeper or shallower |
|  |  |  | `eye_size` | scale xyz | ×0.88 to ×1.105 | pass 2's `eye_size` |
|  |  |  | `eye_open` | scale z | ×0.82 to ×1.125 | pass 2's `eye_open` |
|  |  |  | `eye_tilt` | turn y | -6 to 7 ° | pass 2's `eye_tilt`: outer corners down to up |
| `J_Adj_L_FaceEye`, `J_Adj_R_FaceEye` | `J_Id_Orbit_L` | eyes | `iris_size` | scale xyz | ×0.9 to ×1.1 | pass 2's `iris_size` |
| `J_Id_Brow_L`, `J_Id_Brow_R` | `J_Id_Face` | brows | `brow_height` | move z | -9.5 to 16 ‰H | pass 2's `brow_height` |
|  |  |  | `brow_tilt` | turn y | -8 to 8 ° | pass 2's `brow_tilt` |
|  |  |  | `brow_thickness` | scale z | ×0.7 to ×1.4 | pass 2's `brow_thickness` |
|  |  |  | `brow_length` | scale x | ×0.9 to ×1.12 | pass 2's `brow_length` |
| `J_Id_Nose` | `J_Id_Face` | nose | `nose_length` | scale z | ×0.85 to ×1.13 | pass 2's `nose_length` |
|  |  |  | `nose_width` | scale x | ×0.8 to ×1.25 | pass 2's `nose_width` |
|  |  |  | `nose_bridge` | scale y | ×0.8 to ×1.25 | pass 2's `nose_bridge`: how far the nose stands out |
| `J_Id_NoseTip` | `J_Id_Nose` | nose | `nose_tip` | move z | -10 to 12 ‰H | pass 2's `nose_tip`: turned down to turned up |
| `J_Id_Mouth` | `J_Id_Face` | mouth | `mouth_height` | move z | 9 to -12 ‰H | pass 2's `mouth_height`: close under the nose (up) to low (down) |
|  |  |  | `mouth_width` | scale x | ×0.85 to ×1.18 | pass 2's `mouth_width` |
|  |  |  | `lip_fullness` | scale z | ×0.7 to ×1.35 | pass 2's `lip_fullness` |
| `J_Id_MouthCorner_L`, `J_Id_MouthCorner_R` | `J_Id_Mouth` | mouth | `mouth_curve` | move z | -6 to 6 ‰H | pass 2's `mouth_curve`: corners down to up |
| `J_Id_Ear_L`, `J_Id_Ear_R` | `J_Bip_C_Head` | ears | `ear_size` | scale xyz | ×0.87 to ×1.2 | pass 2's `ear_size` |
|  |  |  | `ear_out` | turn z | -8 to 18 ° | pass 2's `ear_out` |

**Which bones the clips animate.** Every clip in the library keys rotations on 51 `J_Bip_*` bones and rotation and translation on `J_Bip_C_Hips`, and nothing else (`rig_probe.py --list` on a baked file: 29 clips, 52 bones keyed). The root, the eye bones and the hair's spring chains are never keyed. Identity therefore sits on bones no clip touches, and needs no step after animation: the client writes each identity bone's local transform once when it spawns the person, as `characters.rs` `shape` already does for a recipe's proportions.

**Shown in the game** (`rig_probe.py`, on pass 2's woman, nothing in the client changed): five probe bones were added under the head with soft weights on the face and hair.

- With the bones at rest the file photographs as it did: 0.02% to 0.19% of pixels differ over five shots, where spring-bone hair hangs differently.
- With the bones posed in the file (a wider and taller cranium, a narrower jaw, a longer chin, larger eyes set further apart) the same mesh is a different face, and stays so through `idle`, `walk`, `run` and `sword_slash`. The expressions' morphs move with it, since morphs apply before skinning.
- The weights there are plain distances on a mesh not built for bones, so the result is rough at the fringe and the neck. A type's cage is built with its weights.

**Joints.** Bevy's limit is 256 joints a skin. A person today has 55 (the body's 52, the root and two eyes) and up to 79 with long hair's spring chains. Identity adds 25: about 105 at most. The VRoid control has 148.

### How far bones reach

`bone_reach.py` asks whether bones with soft weights can do what pass 2's 34 values do. It takes pass 2's head with every value at 0 as the shared mesh, each varied head as the target, and fits the rig's bones (25 of them carry skin) to carry one onto the other: 1,767 surface points have to land on the target's surface and 42 landmarks on the target's landmarks.

- **Every value alone, at -1 and +1:** the most left after the bones is 0.46 mm (root mean square over the surface, for `face_width`, which moved 3.7 mm); the worst single landmark is 2.9 mm (`crown`, for `forehead`). Eyes, brows, nose and mouth are followed to 0.1 mm.
- **40 people drawn as pass 2 draws them, every value at once:** the surface moved 2.6 mm and the landmarks 4.4 mm; after the bones 0.31 mm is left on the surface at the median and 0.64 mm at worst, and 0.28 mm on the landmarks (0.82 at worst, the worst single landmark 3.6 mm). A man's head gives the same (0.33 and 0.34 mm).
- **What that does and does not say.** The fit gives each bone every move, scale and small turn, which is more than the 38 named values, and it is made on pass 2's loft, not on a cage. It says the bone layout has no hole: no part of what varies between pass 2's people is out of reach. It does not say the named values are enough; that is judged on the cage in step 3.
- **Three of the 34 are shapes, not placements,** and a type fixes them: `eye_shape` (where the upper lid peaks), `eye_fold` and `brow_arch`. So does how sharp the planes' creases are.

No wall was found for bones: not in the animation, not in the joint count, not in reach.

### The types

Twenty-one: three for each sex in the bands youth (12 to 17), adult (18 to 59) and elder (60 and over), and three for children of 2 to 11, whose faces differ little by sex. Each type's line has a letter that holds across the bands, so a family keeps its line as its people age: `a` round, `b` even, `c` long.

**How they were set.** By measuring, and by drawing the result (the board's `character:face-types` sheets).

1. **The anchors**, measured with ref-1's tools (`living/tools/characters/reference/`), in units of the head's height H from chin to crown: the reference and its sister file, and pass 2's average head (every face value at 0) for each sex and band. Only proportions are taken from the VRoid files; nothing of theirs is used.
2. **A band's base** is the reference plus the difference pass 2 makes between that group's average and the adult woman's. Men, elders and children so keep the look the owner accepted, on the reference's structure: a man's eyes sit higher and are smaller, and his front is narrower than a woman's, but it is the reference's broad front and not pass 2's narrow one. Places are carried as differences and sizes as ratios.
3. **The lines.** `a` moves 0.8 of the way from the reference toward its sister file, which is a wider, blunter lower face with taller eyes. `c` moves half as far the other way and is lengthened: the eyes and nose a little higher, the lower face narrower, the chin to a point on women and cut square on men, the cheek corner sharper.
4. **Designed, not measured:** the skull above and behind the reference's mask (it has none), the ears, the brows, the jaw's angle, the creases' sharpness, the eye's depths (from ref-1: the iris 4 mm behind the lid, the white a bowl 15 mm deep), and the body types.

| Head | Eyes: height, apart | Eye: width by height | Front at the eyes, within 0.15 / 0.30 H | Jaw (0.12 H), chin (0.04 H) | Nose tip |
|---|---|---|---|---|---|
| The reference (Shino) | 0.39, 0.39 | 0.16 by 0.12 | 0.64 / 0.72 | 0.42, 0.19 | 0.24 |
| Its sister file (Vivi) | 0.37, 0.40 | 0.17 by 0.15 | 0.63 / 0.72 | 0.51, 0.26 | 0.27 |
| Pass 2's average woman | 0.47, 0.28 | 0.18 by 0.14 | 0.56 / 0.65 | 0.44, 0.20 | 0.30 |
| Pass 2's average man | 0.52, 0.26 | 0.14 by 0.09 | 0.52 / 0.59 | 0.44, 0.25 | 0.35 |
| Pass 2's average old man | 0.52, 0.26 | 0.14 by 0.08 | 0.51 / 0.58 | 0.46, 0.26 | 0.33 |
| Pass 2's average girl of 7 | 0.44, 0.29 | 0.18 by 0.15 | 0.57 / 0.66 | 0.48, 0.23 | 0.31 |

| Type | Line | Eyes: height, apart, width by height | Front at the eyes, within 0.15 / 0.30 H | Jaw, chin | Nose tip | Cheek corner | Body: usual height, weight |
|---|---|---|---|---|---|---|---|
| `child-u-a` | round | 0.36, 0.40, 0.17 by 0.14 | 0.65 / 0.73 | 0.54, 0.27 | 0.26 | 0.40 | 1.20 m, +0.35 |
| `child-u-b` | even | 0.37, 0.39, 0.16 by 0.12 | 0.65 / 0.73 | 0.46, 0.22 | 0.26 | 0.52 | 1.22 m, +0.00 |
| `child-u-c` | long | 0.40, 0.38, 0.15 by 0.11 | 0.65 / 0.73 | 0.40, 0.18 | 0.25 | 0.66 | 1.25 m, -0.30 |
| `youth-f-a` | round | 0.39, 0.40, 0.16 by 0.13 | 0.63 / 0.72 | 0.50, 0.24 | 0.25 | 0.60 | 1.58 m, +0.30 |
| `youth-f-b` | even | 0.39, 0.39, 0.16 by 0.12 | 0.64 / 0.72 | 0.42, 0.19 | 0.24 | 0.72 | 1.60 m, -0.05 |
| `youth-f-c` | long | 0.42, 0.38, 0.15 by 0.10 | 0.64 / 0.72 | 0.36, 0.13 | 0.24 | 0.86 | 1.63 m, -0.35 |
| `youth-m-a` | round | 0.43, 0.38, 0.14 by 0.10 | 0.61 / 0.67 | 0.51, 0.29 | 0.29 | 0.68 | 1.64 m, +0.25 |
| `youth-m-b` | even | 0.43, 0.37, 0.13 by 0.08 | 0.61 / 0.67 | 0.43, 0.24 | 0.28 | 0.80 | 1.66 m, -0.10 |
| `youth-m-c` | long | 0.46, 0.36, 0.12 by 0.07 | 0.61 / 0.67 | 0.37, 0.24 | 0.28 | 0.94 | 1.69 m, -0.40 |
| `adult-f-a` | round | 0.39, 0.40, 0.16 by 0.13 | 0.63 / 0.72 | 0.49, 0.24 | 0.25 | 0.60 | 1.62 m, +0.35 |
| `adult-f-b` | even | 0.39, 0.39, 0.16 by 0.12 | 0.64 / 0.72 | 0.42, 0.19 | 0.24 | 0.72 | 1.64 m, +0.00 |
| `adult-f-c` | long | 0.42, 0.38, 0.15 by 0.10 | 0.64 / 0.72 | 0.36, 0.13 | 0.24 | 0.86 | 1.67 m, -0.30 |
| `adult-m-a` | round | 0.44, 0.38, 0.13 by 0.09 | 0.60 / 0.66 | 0.50, 0.29 | 0.30 | 0.68 | 1.75 m, +0.35 |
| `adult-m-b` | even | 0.45, 0.36, 0.13 by 0.07 | 0.60 / 0.66 | 0.42, 0.24 | 0.29 | 0.80 | 1.77 m, +0.00 |
| `adult-m-c` | long | 0.47, 0.36, 0.12 by 0.07 | 0.60 / 0.66 | 0.36, 0.24 | 0.29 | 0.94 | 1.80 m, -0.30 |
| `elder-f-a` | round | 0.39, 0.40, 0.15 by 0.12 | 0.63 / 0.71 | 0.50, 0.26 | 0.24 | 0.65 | 1.59 m, +0.45 |
| `elder-f-b` | even | 0.40, 0.38, 0.15 by 0.10 | 0.63 / 0.70 | 0.42, 0.20 | 0.23 | 0.77 | 1.61 m, +0.10 |
| `elder-f-c` | long | 0.43, 0.38, 0.14 by 0.09 | 0.63 / 0.70 | 0.36, 0.15 | 0.23 | 0.91 | 1.64 m, -0.20 |
| `elder-m-a` | round | 0.44, 0.38, 0.12 by 0.08 | 0.59 / 0.65 | 0.51, 0.30 | 0.28 | 0.73 | 1.72 m, +0.45 |
| `elder-m-b` | even | 0.45, 0.36, 0.12 by 0.06 | 0.59 / 0.65 | 0.44, 0.25 | 0.28 | 0.85 | 1.74 m, +0.10 |
| `elder-m-c` | long | 0.48, 0.36, 0.12 by 0.06 | 0.59 / 0.65 | 0.38, 0.25 | 0.28 | 0.99 | 1.77 m, -0.20 |

A type's record holds, in H: the sections at nine heights (the face's full width within 0.15 H and 0.30 H of depth behind the bridge of the nose, the skull's side, the midline's profile, the front plane beside the nose and the surface 0.30 H off the midline), the eye (height, spacing, size, tilt, how far it sits behind the brow and the cheek, the iris's and the white's depths), brow, nose, mouth, jaw, ear, the creases' sharpness, and the body type (height as least, usual and most; weight; muscle).

**The sections are step 3's acceptance.** The widths within 0.15 H and 0.30 H are the measure ref-1 set for the cage: `adult-f-b` is the reference's own, so the cage for it is accepted when its sections match these within the stated tolerance. One cell of ref-1's table differs from this file's (the reference at 0.64 H within 0.15 H: 0.70 there, 0.64 here), because the depth is taken from the bridge at eye height here; the other fourteen agree to 0.01.

**Checked** (`face_types.py check`): every type is a valid head (the thirds in order, each width inside the next, the eyes on the front plane and clear of the nose and brow, the mouth inside the front, the nose between the eyes, the eye in its socket). Of 4,200 people drawn, 4,197 are valid as drawn, and every one is once pulled back toward its type. Of 60,648 cases of one or two values at their ends on every type, 60,539 are valid; the 109 that are not (nose base ×79; the eye's upper lid reaches the brow ×22; at 0.20 the front ×8) are ranges to trim on the cage.

**Body types.** Each type carries one: the band's and sex's height (least, usual, most), and the line's lean: `a` a little shorter and heavier, `c` a little taller and leaner. A body's build stays what it is today, the recipe's proportions as bone scales (legs, arms, torso, neck, head, shoulders, hips, build, hands, feet), which the client already applies; weight's belly and muscle's chest, which pass 2 bakes into the mesh, become two more bones in step 3.

### The parameter model

**What a type fixes:** the skull and every landmark's place; the planes and how sharp their creases are; the sockets' form; the lid's shape, the fold and the brow's arch; the topology and UVs; the designed normals, shadow map and lines; the expressions' morphs; the body's mesh.

**What a person varies:** the type itself (one of three), the 38 bone values, height and build, colours, and style ids (hair, beard, clothes, details).

**The draw** (`face_types.draw_values`; the numbers are `DRAW` in `face_types.py`):

1. Along four directions in which heads vary together, each a normal draw (width 0.42): `broad` (face, cranium and jaw width, cheekbones, the front's breadth, eye spacing), `long` (face, chin and nose length), `bony` (cheekbones and brow ridge up, cheeks down, a squarer jaw, shallower sockets) and `eyes` (size, opening, iris).
2. Then value by value (width 0.22), each from its own random stream, so adding a value later does not reshuffle people.
3. **Bounded by distance from the type, not per value:** when the root mean square of all the values passes 0.42, the whole set is scaled back to it. A person may have one or two strong features but not every feature strong at once.
4. A head that still fails the checks is pulled back toward its type until it passes.

**Families** share a type's line (eight in ten of a family's blood relatives take the family's line; the band and sex choose the type on that line) and 0.7 of their values, in place of pass 2's half of each value.

**Age** changes the band, and so the type, at 12, 18 and 60. Within a band a person's values do not change with age yet; ageing inside a band (lines, lower lids) is to be an age direction on the same bones, set on the cage.

**Height changes the head's proportion,** as Blue Protocol does, not only the scale: the recipe's head multiplier is (the type's usual height / the person's height) to the power 0.6, so a person 10% taller than usual has a head about 4% larger, not 10%.

**How pass 2's 34 values map onto this:**

- **31 carry over under the same name** as bone values: `forehead`, `brow_ridge`, `face_length`, `face_width`, `cheekbones`, `cheeks`, `jaw_width`, `jaw_square`, `chin_length`, `chin_width`, `chin_forward`, `eye_spacing`, `eye_height`, `eye_size`, `eye_open`, `eye_tilt`, `iris_size`, `brow_height`, `brow_tilt`, `brow_thickness`, `brow_length`, `nose_length`, `nose_width`, `nose_bridge`, `nose_tip`, `mouth_height`, `mouth_width`, `lip_fullness`, `mouth_curve`, `ear_size`, `ear_out`.
- **3 become the type's:** `eye_shape`, `eye_fold`, `brow_arch`.
- **7 are new:** `cranium_width`, `cranium_depth`, `cranium_height`, `front_breadth`, `cheekbone_height`, `jaw_angle`, `socket_depth`. How sharp the cheek corner is belongs to the type.
- A value's meaning is now "from this type" and no longer "from the average for the sex and age", and `stylise`, the men's and elders' shares and `STYLE` go: how drawn a group is lives in its types.
- **Existing seeds will give different faces.** That is accepted; it is recorded here.

### The client format

For the laptop coordinator. The type files exist since step 3 ([type files](#type-files)); style files (hair, outfit) and the client's side do not yet.

**A person becomes a recipe line**, with a type in place of a base file:

```json
{
  "name": "tamsin-hollin",
  "type": "adult-f-a",
  "height": 1.62,
  "proportions": { "head": 1.0, "shoulders": 0.895, "build": 0.973, "hands": 0.88, "feet": 0.9 },
  "identity": {"cranium_width": -0.384, "cranium_height": -0.31, "brow_ridge": 0.271, "face_length": -0.499, "jaw_width": -0.292, "jaw_square": -0.518, "chin_length": -0.948, "chin_forward": -0.504, "socket_depth": 0.576, "eye_size": 0.387, "eye_open": -0.258, "iris_size": 0.257, "nose_length": -0.273, "mouth_height": -0.29, "mouth_width": -0.648},
  "colors": { "skin": "#e6b89c", "hair": "#4a2a1a", "eyes": "#536f54", "outfit": { "coat": "#5d7f9a", "jersey": "#d8d2bd" } },
  "styles": { "hair": "bob", "outfit": ["smock_58-f", "jersey_smock-f", "apron_58-f", "trousers-f", "boots-f"], "overlays": ["lines", "freckles"] }
}
```

- `styles.hair` is a file under `lookdev/styles/hair/`, and `styles.outfit` a list of files under `lookdev/styles/outfit/`, as the generator writes them into `<name>.params.json` (`person`) since the outfit step.
- `type`: an id from `types.json`. `identity`: values from -1 to 1 by name; one left out is 0. `proportions` and `height` are as today. `colors` and `styles` replace what pass 2 paints and builds into each person's file.
- Sixty-four residents are 64 such lines. No file is made for a person.

**What the client loads:**

| File | Holds | Shared by |
|---|---|---|
| `lookdev/types/<type>.glb` | The `J_Bip_*` skeleton, the 25 identity bones and the eye bones; the type's head (skin, eyes, lines, with the expressions' morphs) and its skin (neck, hands); the far head as `Far*` mesh nodes on the same skin | everyone of that type |
| `lookdev/styles/hair/<style>.glb`, `…/outfit/<piece>.glb` | One mesh a style, skinned to the same bone names (hair to the cranium's bones and its own spring chains), with its far mesh | everyone wearing it |
| `lookdev/anim/own-clips.glb` | Every clip, once | everyone: all types share the body's skeleton, as all generated people do today |
| `characters/types.json` | The rig: each value's bone, what it does and its range | the client, to turn values into transforms |

**How the client composes a person:**

1. Spawn the type's scene, as it spawns a base today.
2. **Identity,** once, in `shape`: for each value in the rig, set its bone's local transform from the bone's rest in the file. A `move` adds (the value's amount in ‰H × the type's head height) along the bone's axis to the rest translation, the axis turned by the bone's rest rotation (identity for all but the cheeks); a `scale` multiplies the axis; a `turn` rotates about the axis, after the rest rotation. The rig's x, y and z are the file's X, -Z and Y. A paired bone's x points away from the midline on both sides and its turns have the same sense on both, so the right bone takes the left's values with x reversed. No clip keys these bones, so nothing is done per frame.
3. **Build,** as today: the recipe's proportions through the helper joints.
4. **Styles:** hair, beard and clothes attach as outfit pieces do today (`characters/outfit.rs`): each primitive under the character's root with a `SkinnedMesh` whose joints are the character's own bones by name. Pieces must find the identity bones as well as `J_Bip_*`.
5. **Colours:** through the mesh tag on shared materials, as recipes recolour today (`recolor`, mode 3): skin on the face and skin meshes, hair on the hair, the iris on the eyes, each garment on its piece. A tag carries one colour a mesh.
6. **The far switch and clips once** are as written under [what the client needs](#what-the-client-needs): `Far*` nodes beyond about 10 m; clips from the shared file. Shared face shadow maps fall away: a type's map is one file beside its type file, shared by everyone of the type.

**To settle with the laptop before step 3 writes files:**

- **Details a person has and a type does not:** stubble and beards, age lines, freckles, lip tint. Pass 2 paints them into each person's atlas. The proposal is style ids for shared overlay meshes on the type (a beard shell, a lines layer), tinted by the mesh tag, with the count a person may wear kept small. The alternative is a second tag or a material value per person.
- **One colour a mesh.** Mode 3 moves a texture's mean colour to the person's. Lips, blush and the lid's shade sit in the same skin texture and move with it; whether that holds across Cullet's skin tones is to be judged on the board in step 3.
- **Bindless.** Whether per-person colour as a material value under bindless toon materials beats the mesh tag is the client's to measure ([the survey](CHARACTER_RESEARCH.md), §4).
- **Spring chains** of a hair style hang under `J_Id_Cranium`, so a wider skull moves their roots; the collider spheres on the head should take the cranium's scale.
- **Normals under a bone's scale.** A bone scaled unevenly skews the normals it carries a little (ranges are within ±15% for the skull and face). Designed normals ride through it; if it shows, the cure is in the ranges.

### The cage head

Pass 3's third step (2026-11-11). `living/tools/blender/cage_head.py` builds a type's head, and `person.py` puts it on every person that has a type (all of them, unless `--loft`).

```bash
python3 living/tools/characters/cage_accept.py .local/ref                  # every type's head against what it was built to (about 2 minutes)
living/tools/blender/gen_types.sh                                           # the 21 type files, lookdev/types/<type>.glb (about 1.5 minutes)
blender -b -P living/tools/blender/person.py -- --variant type:adult-f-a --parts face --out head.glb   # one type's bare head, to look at
python3 living/tools/characters/compose.py TYPE_OR_PERSON.glb OUT.glb --params NAME.params.json        # move the identity bones, as the client will
python3 living/tools/characters/compose.py --compare COMPOSED.glb BAKED.glb                            # a composed person against the same one baked
python3 living/tools/characters/outline_normals.py FILE.glb [--check]       # the outline's directions, written into a file
python3 living/tools/characters/rig_check.py adult-f-b                      # how far the landmark sketch of each value is from what its bone does
```

**How it is built.**

- **A cage of quads, not a loft.** 22 rows from the crown to the neck and 28 columns round the head, with the eye openings and the mouth's slit cut in. Each row is set from the type's measured sections: the midline's profile, the plane beside the nose, the cheek's corner at 0.15 H behind the bridge, the side at 0.30 H, the widest point, the ear line and the back.
- **Subdivided once the Catmull–Clark way,** with creases along the cheek corner, the brow line and the jaw line, so planes meet in edges where the type says so and are smooth elsewhere. The cage is fitted backwards (five rounds), so the subdivided surface passes through the designed points and not inside them.
- **The eye, with the reference's depths** ([the reference taken apart](CHARACTER_REFERENCE.md)): the lid's rim folds in 2.5 mm; the white is a bowl cut to the lid's own opening, 15 mm deep at its middle; the iris is a flat disc 4 mm behind the lid, on the eye's bone; the lash line stands 4.5 mm forward. Depths are measured from the opening's own plane, which leans back toward the outer corner, and scale with the head.
- **The skin under the jaw is body skin,** a fourth primitive of the `Face` mesh, so the face's flattened normals stop at the jaw line. A typed person is seven meshes where pass 3's first step had six.
- **Faces are wound by carrying the winding from face to face.** Asking each face whether it looks away from the head's middle turned the nose's underside inward, which showed as a hole from below.
- The lash lines, lashes, brows, mouth's inside, ears and the 15 expressions are `head_mesh.py`'s, laid on the cage. An expression is the same subdivision on a moved cage.
- A typed person's head in the file is 0.2564 m tall whatever the person; the recipe's `head` carries its size ([the parameter model](#the-parameter-model)).

**Acceptance** (`cage_accept.py`). Each type's whole-skull skin (4,264 triangles) is written to a file and measured with the reference's own tool (`living/tools/characters/reference/measure.py`), then compared with the type's record: the face's width within 0.15 H and within 0.30 H of depth at eight heights, and the eyes.

| | Result over the 21 types | Allowed |
|---|---|---|
| Widths (16 a type) | worst 0.006 to 0.025 H; `adult-f-b`, the reference's own type, 0.013 H | 0.03 H |
| Eye centre's height | -0.002 to -0.005 H | 0.03 H |
| Eye spacing, width, height | 0.000 | 0.03 H |
| Eye behind the brow | +0.004 to +0.012 H deeper than set | reported |
| Eye behind the cheek | -0.018 to +0.004 H | reported |
| Nose tip's height | -0.006 to +0.017 H | reported |

- 0.03 H is 7.7 mm on the file's head. The widest misses are at the temple (0.76 H) on the long types and low on the jaw (0.04 to 0.12 H) on the round ones.
- `adult-f-b` is the reference's measurements; the other 20 are composed from it and pass 2's average heads, so passing says the cage builds what a type's record says, not that the record is a good face. That is judged on the board.

**The rig in it.** `cage_head.rig_pivots` places the 25 identity bones on the type (the eye bones move under the orbits) and `identity_weights` weights every vertex to at most four of them.

- Features come first, each riding its own bone whole: an eye's opening and the skin round it, the brow, the nose and its tip, the mouth and its corners, the chin, the ears. Then the points that shape the outline (cheek corner, zygoma, cheek, jaw angle), then the forehead and glabella, and what is left goes to the cranium, the jaw and the face block.
- Hair, headwear, the neck's top and the far head follow the same bones: their weight to `J_Bip_C_Head` is shared out by where each vertex lies (`spread_head_weights`).
- **The bones are the definition of a value.** `face_types.apply`, which moves a type's landmarks, is kept as a sketch for the diagrams and the validity checks, where a whole head would be slow to build; `rig_check.py` says how far it is from the bones.
- Two ranges contradicted their names and were reversed (`chin_length`, `mouth_height`: -1 is short and close under the nose). `jaw_angle` turns less (-2° to 2.5°), and `cheeks` moves out of the cheek along a fixed direction (`o`: 0.55 away from the midline, 0.83 forward) in place of a bone turned at rest.

**Composed against baked.** One person (seed 4991, a woman of 35 on `adult-f-a`, 38 values at distance 0.31 from the type) made three ways:

| | Face skin | Eyes | Lashes, brows, lines | Skin under the jaw | Hair |
|---|---|---|---|---|---|
| Composed by bones against baked | 0.00 mm | 0.00 mm | 0.00 mm | 0.00 mm | 0.00 mm |
| The type itself against baked | 2.21 mm | 1.72 mm | 1.70 mm | 4.18 mm | 2.02 mm |

- Root mean square, each vertex to the nearest of the other file's (`compose.py --compare`); the largest single distance for the type is 9.4 mm.
- **Composed** is the type's mesh with this person's hair and clothes, run through the whole pipeline (clips baked, primitives merged, designed normals, outline normals) and then `compose.py`, which moves 27 bones by the client's rule. **Baked** is `person.py --bake`, which applies the same rule to every vertex and expression and leaves the bones at rest.
- Blender, importing both files, agrees to 0.00 mm, so the rule in `compose.py` is what a glTF reader does with the nodes.
- The clips of the composed file key only `J_Bip_*` bones, as before.
- **Photographs cannot show this to the pixel.** The asset view blinks and moves the eyes, so two photographs of the same file differ by 4% to 25% of pixels. The board shows the three side by side; the numbers are from the files.
- The first version of `--bake` built the head from the moved landmarks and differed from the bones by 1.8 to 2.6 mm. That was two models of one value, and the landmark one was dropped.

**Value ranges, trimmed.** Step 2 left 109 of 60,648 pairs of value ends that made an invalid head: a long nose, mostly on `elder-f-c` (79), large high eyes under a low brow (22), and a broad front with hollow cheeks (8). Nine ends were shortened, the least that clears them all:

| Value | End | Was | Is |
|---|---|---|---|
| `nose_length` | most | ×1.20 | ×1.13 |
| `face_length` | most | ×1.10 | ×1.095 |
| `eye_height` | most | 14 ‰H | 10 ‰H |
| `eye_size` | most | ×1.13 | ×1.105 |
| `eye_open` | most | ×1.18 | ×1.125 |
| `brow_height` | least | -12 ‰H | -9.5 ‰H |
| `mouth_height` | least (up) | 12 ‰H | 9 ‰H |
| `front_breadth` | most | 16 ‰H | 12 ‰H |
| `cheeks` | least | -12 ‰H | -9 ‰H |

`face_types.py check` now passes every type, every value end alone and in pairs, and all 4,200 people as drawn (200 a type).

**Outline normals.** `outline_normals.py` writes one smoothed direction a point into every file as the vertex attribute `_OUTLINE_NORMAL`: the angle-weighted mean of the faces round the point, the same for every vertex at that place across the file's meshes and materials. The client makes these up per mesh when it loads a file; written here they also close the line where two meshes meet (the face's skin, the skin under the jaw and the neck). Today's client ignores the attribute without a warning and draws as before.

### Designed shadows

Pass 3's fourth step (2026-11-12). `living/tools/characters/face_shadow.py` runs after `face_normals.py` on any file whose head is a face type's, and replaces the two things that tool derives from an ellipsoid. `gen_types.sh` and `gen_person.sh` run it (`SHADOWS=ellipsoid` keeps the old ones, to compare).

```bash
python3 living/tools/characters/face_shadow.py FILE.glb [OUT.glb] [--png OUT.face.png] [--sheet SHEET.jpg]
```

**What was wrong.** How a face is lit in the client comes from two places only (`toon.wesl`): the map, compared with the sun's horizontal angle round the head, and the cast shadow, which a face looks up 12 cm out along its normal so a fringe does not blotch it.

- **The straight split down the middle** was not the map. The ellipsoid's normals on the far half point away from the light, so the lifted point lay in the head's own shadow, with its edge at the middle of the face.
- **The band along the jaw** was the same on the near side: a point 12 cm out to the side of a cheek is under the hair.
- The map's own edge was a vertical line too (an ellipsoid's horizontal facing), but it showed only past those.

**The planar proxy** gives each face-skin vertex its normal, from landmarks read out of the file itself (the identity bones' bind positions, the eye primitive's openings, the skin's own sections):

| Plane | Where | Turned |
|---|---|---|
| Front | inside the cheek's corner line (the face's width within 0.15 H of depth) | up to 11° out at the corner |
| Side | beyond the corner line | 36° from the front |
| Nose wedge | the nose, bridge to base | 54° to each side of a 3 mm ridge |
| Under the nose | tip to base, where the skin looks down | down |
| Under the lip | below the lower lip | down and forward |
| Sockets | round each eye | down under the brow, a little up below |
| Under the jaw | the skin below the jaw line (body skin) | straight down, easing into the neck at the ring |

- Planes meet in blends about a centimetre wide. Above the forehead and wherever the skin turns from the front, the head's own round form takes over.
- **The side planes are turned 36°, not the skull's 65°,** because of the lift: at 36° the lifted point is in front of the face. That is what removes the jaw's band. If the client lifts along the head's forward instead (below), the side planes can be true.
- In today's client the face's normal drives only that lift and the rim light; the skin under the jaw is shaded by its normal, so it now reads as one shape under the chin.

**The threshold map** is made the way anime face maps are authored ([the survey](CHARACTER_RESEARCH.md), §3): draw the shade for each of N light angles, turn each drawing into a signed distance field, interpolate.

- **18 angles** from 55° to 180°, light from the face's right; the left is the mirror. Each drawing is the one before plus more, so a texel goes dark once.
- **The face is flat until about 55°,** as the reference's is. Step 4 drew a nose wedge from 30° and a lit triangle inside the shaded cheek; close up they read as hard patches, not form, and step 4b (2026-11-12) moved every onset later and took the islands out.
- **Drawn in the face's front view** at half a millimetre a pixel, from the landmarks. The onsets are named numbers at the top of `face_shadow.py`:
  1. the nose's wedge on the far cheek from 56° (`WEDGE_ON`), small, taken in by the far side's shade soon after;
  2. the far side plane, from the silhouette in to the cheek's corner line (60° to 72°, `SIDE_ON`, `SIDE_FULL`);
  3. the edge crossing the front as the corner line scaled toward the middle, so it follows the cheek's own contour; it reaches the middle at 96° (`MIDDLE`, `CROSS`);
  4. between the brow and the nose's base the edge runs half the way ahead toward the bridge (72° to 86°, `SOCKET_ON`, `SOCKET`): the socket's shade;
  5. below the nose the far half waits 20° (`WAIT`), so the mouth and chin keep their light and the edge leaves the nose's wing and runs out to the jaw;
  6. a band along the far jaw from 60° (`JAW_ON`), and the near jaw's later.
- **Nothing holds its light inside the shade:** no cheek triangle, no bright near side of the nose.
- **Interpolated** between each pair of drawings by their distance fields, then blurred by 1.4 mm (`SOFT_MM`), so every edge is a pixel or two soft at close range.
- **Baked into the face's UV space** at 512 × 512. Where the skin turns from the front (behind the cheek, the skull), the drawn picture gives way to the plain rule of a round head.
- **One map a type:** `lookdev/types/<type>.face.png`, 21 files, about 40 kB each. A person's own file gets the same map beside it, because the client looks there.
- About 7 seconds a file.

**The format is unchanged** (`face_normals.py`; `face_lit` in `toon.wesl`): R is the light's horizontal angle from the face's front, 0 to 1 for 0 to 180°, up to which a texel stays lit for light from the face's right; G the same for the left; linear. **The client needs no change.** Three things it could do, none required:

1. **Lift the cast-shadow lookup along the head's forward** (`in.uv_b`, already in the fragment shader) in place of the face's normal. The side planes could then be turned as the skull is, which the rim light would read better.
2. **The face's shade and the neck's are two tones** (`face_shadow` 1.25 on a face; the plain skin depth on the neck), so the jaw line shows where both are in shade, as on the reference.
3. **The sun's height is not in the map.** The shapes answer the horizontal angle only, so the planes under the nose and lip cannot answer a high sun. The map's blue channel is free for a second threshold if that is wanted.

**What the board shows** (`character:face-types`): the drawings at every angle for four types and the map's shade at three angles for all 21; the light sweeping across the woman, the man, the boy and the elder from 24° to 71°, close up and at the game camera, with step 3 above step 4 (version `ac12a5`) and step 4 above step 4b (the version after it), eyes held open; turned from the light; and the reference under the same sweep.

- The sweep's heads are copies without clips, held straight: the idle clip turns the head, and with it the angle of the light, so the later shapes did not show.
- **At the game camera a face is about a dozen pixels across.** The shapes do not read there; only which half is darker does. They are a close-up matter.
- **Turned from the light** the camera sees the lit side, so the edge past the middle is mostly out of view; the sheets of the drawings show it.

### Lines where the form turns

Pass 3's fifth step (2026-11-12). A figure's outline today is its silhouette: the client draws each mesh's hull pushed out by a width in pixels (`bevy_mod_outline`, `style.rs` `outline`), and a line never falls inside the figure. So nothing marks where the jaw stands over the neck, which is where depth reads in a drawn face. Blue Protocol keeps shell geometry for exactly that: the jaw, the mouth and the ears ([the survey](CHARACTER_RESEARCH.md), §3).

**Shell lines, in the files** (`cage_head.CageFace._shell_lines`; `person.py --no-lines` leaves them out). They are faces of the `Face` mesh's line primitive (the lashes' and brows' material, unshaded), so they add no mesh and no material, and they are built on each expression's cage, so they ride the morphs and the identity bones.

| Line | How | Width on the file's head |
|---|---|---|
| Jaw and chin | the first ring of the skin under the jaw, pushed out along the jaw line and turned inside out; pinned to the skin on its lower edge | 1.9 mm under the chin, 1.0 mm along the jaw, gone before the ear |
| Ears | the whole ear inside out, a little larger | 0.7 mm |
| Mouth | a thread along the upper lip's edge, heavier at the corners; it rides the upper lip, so it holds when the mouth opens | 0.6 to 1.2 mm |
| Jaw, far head | the far head's down-facing skin between chin and neck, inside out (`cage_head.far_jaw_line`) | 16 mm |

- **Why inside out.** A hull's faces are seen only where the surface they copy faces away from the viewer. The skin under the jaw faces away from anyone looking at the face, so its hull shows as a dark edge exactly where the jaw stands over the neck, and not from below, where the skin itself is seen.
- **The colour** is the skin's own line colour taken halfway to a dark brown (`cage_head.line_colour`), so it reads on every skin tone.
- **Widths are metres, not pixels.** That is the limit of a line made of geometry: 1.9 mm is a few pixels in a close-up and a tenth of a pixel at the game camera, where a face is a dozen pixels across.
- **The far head's line is sized for the game camera:** 16 mm is about a pixel at 22 m and two at the 10 m where the far model takes over. It reads as one darker pixel row under the chin, and under a beard not at all.

**Cost** (`adult-f-b`, built both ways):

| | Without lines | With lines | |
|---|---|---|---|
| Triangles, near head (`Face`) | 5,840 | 6,184 | +344 |
| Triangles, far head (`FarSkin`) | 1,964 | 2,116 | +152 |
| Triangles, the type file | 12,340 | 12,836 | +4.0% |
| Vertices | 7,607 | 7,974 | +367 |
| File size | 994 kB | 1,031 kB | +37 kB (3.7%) |

- The 21 type files are 21.7 MB together (1.01 to 1.06 MB each). They were 19.6 MB at step 3; the rest of the growth is the designed normals (step 4) and the width attribute, 4 bytes a vertex (about 32 kB a type file).
- A whole person gains the near head's 344 triangles: the `woman` preset goes from 30,692 to 31,036.
- `face_normals.py` and `face_shadow.py` append a normal accessor each time they are run on a file and leave the old one in it. A file made once by `gen_types.sh` or `gen_person.sh` has no such waste; a file run through them again by hand grows by about 28 kB a run.

**Per-vertex outline width, in the files.** `outline_normals.py` writes a second attribute beside `_OUTLINE_NORMAL`: `_OUTLINE_WIDTH`, one float a vertex, a multiple of the figure's own outline width. Nothing reads it yet.

| Where | Width |
|---|---|
| Eyes, lashes, brows, painted lines, shell lines | 0 (a line round a lash floats; a line needs no line) |
| A face's skin at the lids' edges | 0, easing to 1 by 8 mm from the opening |
| A face's skin and the skin under the jaw, along the jaw line | 1.6, easing to 1 by 14 mm |
| Hair | 0.7 |
| Everything else | 1 |

- **Outline normals stay separate from lighting normals.** `NORMAL` on a face is the planar proxy's (step 4); `_OUTLINE_NORMAL` is the smoothed geometric direction, welded across meshes and materials (step 3). The shell lines' own vertices carry both, and width 0.

**What the client needs for a line that holds its width on screen** (for the laptop coordinator; nothing in `living/game` was edited). Two changes, the first one line, the second a patch to the outline crate (`bevy_mod_outline` 0.14.0, the version pinned):

1. **Draw people's hulls at their true depth:** add `OutlineMode::ExtrudeReal` to the bundle `style.rs` `outline` returns for `Outlined::Person` (scenery's stencils use it already). As the code reads, a person's hulls are flattened to one depth today (`outline` adds no `OutlineMode`, and the crate's default is `ExtrudeFlat`), and all of a person's meshes share an origin, so the face's hull is never in front of the neck. This was read, not tested: nothing in `living/game` was built differently. At true depth the jaw's hull shows over the neck in screen pixels, at any distance. It also shows every other inner contour (hair over the face, a collar over the neck, the lids), which is why the second change belongs with it.
2. **Per-vertex width in the outline pass:**
   - register the attribute with the glTF loader, as `_OUTLINE_NORMAL` was: `add_custom_vertex_attribute("OUTLINE_WIDTH", ATTRIBUTE_OUTLINE_WIDTH)` with `ATTRIBUTE_OUTLINE_WIDTH = MeshVertexAttribute::new("Outline_Width", <an id of our own>, VertexFormat::Float32)` (the gltf crate turns `_X` into `Extras("X")`);
   - `pipeline.rs`, where the vertex layout is built (`buffer_attrs`, beside the push of `ATTRIBUTE_OUTLINE_NORMAL` at location 1): when `layout.0.contains(ATTRIBUTE_OUTLINE_WIDTH)`, push it at shader location 3 and add the shader def `VERTEX_WIDTH`;
   - `outline.wesl`, `struct Vertex`: `@if(VERTEX_WIDTH) @location(3) outline_width: f32,`;
   - `outline.wesl`, `fn vertex`, the line `let ndc_delta = offset * corrected_norm * view_uniform.scale_clip_from_logical * clip_pos.w;`: multiply by the vertex's width in the volume pass only (`@if(VERTEX_WIDTH && VOLUME)` use `offset * vertex.outline_width`), so the stencil is untouched. A vertex with width 0 then draws no line.
   - The shader normalises the outline normal before use, so the width cannot be carried in the normal's length: it needs the attribute.
3. With both in, the shell lines can stay for close-ups or be dropped (`--no-lines`); the far head's 16 mm line should then go, since the pass draws the same edge at the right width.

**Blue Protocol's inner lines as a post-process: what the generator would have to write.** Not built. Their lines come mostly from a screen pass over depth, normals and an inner-line ID ([the survey](CHARACTER_RESEARCH.md), §3). For that the files would carry:

- **A line ID a vertex** (`_LINE_ID`, an unsigned byte): one number for each part a line should separate. On a head: the face, the skin under the jaw, the neck, each ear, the nose, the upper and the lower lip, each eye's socket; on a body: each garment piece, each hand; on hair: each lock group. The pass draws a line where neighbouring pixels' IDs differ. The generator knows every one of these today as a material kind, a cage row or a part's name, so this is bookkeeping, not modelling.
- **A line weight a vertex,** which `_OUTLINE_WIDTH` already is.
- **A mask for lines that must not draw** (between the lids and the eye, between a lash and the skin): width 0 covers it.
- The client's side would be a G-buffer target for the ID and a pass like the one scenery's edges use, reading it. That pass costs the same for 64 people as for one, where shells cost triangles a head.

**On the board** (`character:face-types` and the six presets): the lines on two bare type heads from five sides; four presets close up with step 4b above step 5; the head at the game camera pixel for pixel, near and far, with and without; the reference beside each.

### Hair styles

Pass 3, after step 5 (2026-11-12).

**Why hair looks washed out and half transparent close up.** Four suspects, each tested on the `woman` preset with one thing changed at a time (the board's `hair-wash-tests`):

| Suspect | Test | Result |
|---|---|---|
| Alpha | The file's hair material is opaque and single-sided. The face's skin painted green | No green shows through the fringe. Hair is not blended. (Green does show beside the eye, where there is a real gap between locks at the temple.) |
| The shared strand picture | The same file with its strand picture embedded, as before step 1 | The embedded picture and `lookdev/strands.png` are the same bytes (SHA-1 `7d891fb6…`), and the hair's colour on screen is the same to within 5 of 255. |
| Normals | Hair normals as built; blended wholly toward the head's capsule; all turned to face the front camera | As built and wholly blended look the same as today's 0.35 blend. Turned to the camera, the grey veil on the side locks is gone from the front, and from behind (now facing away) the whole head goes pale: back of the head 123, 90, 71 becomes 164, 142, 122. |
| The client's shading | Reading `toon.wesl` and `edges.wesl`, and the fringe at three heights in the frame | See below. |

- **The cause is the rim light on hair.** `toon.wesl`'s fragment adds `rim_light(fr, lit, rim_strength) * sun` to every surface, with `rim_strength = toon.rim.a` (0.35) for everything but faces and face parts. `rim_light` (`toon_light.wesl`) is `toon.rim.rgb * pow(fr, toon.band.w) * strength * (0.35 + 0.65 * lit)`: a pale cream (1.0, 0.95, 0.85), added, whatever the surface's own colour. On skin or cloth that is a soft edge. On dark hair, whose own colour is about 0.05 in linear light, an added 0.1 to 0.35 is two to seven times the hair itself, across every lock that turns from the viewer: the side curtains seen from the front, the whole outline. That is the washed-out, half-transparent look. Hair then gets a second rim of its own in `hair_light` (`toon.hair.w`, tinted by the hair).
- **The film gradient adds to it at the top of the frame.** `edges.wesl` ends with a screen blend of `edges.grade.rgb * edges.grade.a * pow(1.0 - uv.y, 2.0)` (0.22 at the very top). The same fringe is 146, 117, 99 when the crown sits at 0.17 of the frame's height and 133, 99, 77 at 0.65. A close-up puts hair exactly there.
- **The reference shows the same,** for the same reason.
- **It is the client's, and nothing in `living/game` was changed.** For the laptop: in `toon.wesl`, where `rim_strength` is chosen, hair (`is_kind(4.0)`) should not take the general rim at `toon.rim.a`: either none (it has `hair_light`'s own, in its own hue) or a strength of its own as faces have (`toon.face.w`). More generally the rim could be scaled by the surface's own lightness, so it never exceeds what it lights. The film gradient is a look decision; it could spare dark pixels by being a tint and not a screen.
- **No normals of ours avoid it:** the rim follows the angle to the viewer, and any normal that hides it from one side shows it from another.
- **Fixed on the laptop (`hair-rim-1`, 2026-11-12).** Hair takes no general rim (`toon.wesl`, `rim_strength` is 0 for `is_kind(4.0)`), so `hair_light`'s rim in the hair's own hue (`hair_rim`, 0.2) is its only one. In look-dev close-ups (meadow, hour 15) the dark fringe went from 151, 139, 126 to 138, 126, 115 (`smith`) and from 152, 145, 135 to 130, 124, 119 (`shino`); in shade (the side away from the sun) from 156, 152, 147 to 123, 126, 133 (`shino`). Light hair (`scholar`) and skin, clothes, sky and ground did not change beyond a re-run's own noise.
- **The film is now the larger lift.** The same frames with the meadow's `grade_strength` at 0: `smith`'s fringe is 88, 58, 39 and `shino`'s 67, 71, 78. In the top sixth of a close-up the film adds 50 to 80 levels to dark hair, and 25 to 80 to dark clothes and hats in the upper half of the frame. A screen blend adds the same amount in linear light to every pixel, which is several times a dark pixel's own value. The proposal is a tint that scales with the pixel (`color * (1 + g)`) or that spares dark pixels. That is a look decision for the owner.

**Shared style files.** `living/tools/blender/gen_styles.sh` writes `lookdev/styles/hair/<style>.glb` for the 13 styles (`person_params.STYLES`), about 40 seconds for all.

```bash
living/tools/blender/gen_styles.sh                                    # the 13 style files
python3 living/tools/characters/hair_fit.py --table                   # every type's fit onto the standard head
python3 living/tools/characters/compose.py TYPE.glb OUT.glb --hair STYLE.glb --hair-colour '#6a3a22' --drop Far [--params NAME.params.json]
```

| | |
|---|---|
| Built on | the standard head, `adult-f-b` with every identity value 0 (`person.py --variant style:<name> --parts hair`), at the lengths and parting the style's own seed draws |
| `Hair` | the cap and the locks, one material (`…_HAIR`), weighted to `J_Bip_C_Head`'s identity bones by where each vertex lies, and to the style's spring chains |
| `FarHair` | the far mesh on the same skeleton |
| Skeleton | the `J_Bip_*` bones and the 25 identity bones, as a type's file has, so every joint is found by name; the spring chains (`J_Sec_Hair<chain>_<joint>`) hang under `J_Id_Cranium` |
| Colour | neutral shades, 0.86 at the root to 1.0 at the tip, for the client's tag to tint; the strand picture is the one shared file |
| Also | `_OUTLINE_NORMAL`, `_OUTLINE_WIDTH` (0.7); the file's VRM block lists the spring chains |
| Not in it | a head, clothes, clips |

| Style | `Hair` triangles | `FarHair` | Spring bones | File | Other meshes |
|---|---|---|---|---|---|
| `bob` | 6,432 | 1,600 | 0 | 0.40 MB | |
| `bob_parted` | 9,252 | 2,146 | 0 | 0.55 MB | |
| `braid` | 6,156 | 1,714 | 4 | 0.40 MB | the tie, in cloth |
| `braids` | 5,640 | 1,882 | 8 | 0.40 MB | the ties |
| `bun` | 5,124 | 1,474 | 0 | 0.33 MB | |
| `crop` | 2,808 | 940 | 0 | 0.21 MB | |
| `long` | 8,664 | 1,906 | 16 | 0.51 MB | |
| `shag` | 5,532 | 1,300 | 0 | 0.34 MB | |
| `short` | 3,396 | 1,012 | 0 | 0.24 MB | |
| `sides` | 2,076 | 688 | 0 | 0.16 MB | |
| `swept` | 3,512 | 862 | 0 | 0.24 MB | |
| `tail` | 4,956 | 1,168 | 3 | 0.32 MB | the tie |
| `tousled` | 3,704 | 1,030 | 0 | 0.26 MB | |

- 4.4 MB for the 13. `kerchief` is not a style file: it is headwear, and comes with outfits.
- A style's file skips `face_normals.py`'s blend of hair normals toward the head (that tool needs a face in the file); the tests above show no visible difference.

**One style on every type: `hair_fit`.** The types' skulls differ from the standard's by up to 5.4 mm (root mean square over the region hair grows on). Each type's file carries, in its scene's extras, the matrix that lays the standard skull onto its own: a scale about the cranium's pivot and a shift, fitted by least squares (`hair_fit.py`; `gen_types.sh` writes it).

| Type | Skull from the standard's, as built | After the fit | Most | Scale (across, up, depth) |
|---|---|---|---|---|
| `child-u-a` | 2.3 mm | 1.7 mm | 8.3 mm | 1.012, 1.008, 1.009 |
| `child-u-b` | 2.4 mm | 1.5 mm | 9.4 mm | 1.015, 1.012, 1.017 |
| `child-u-c` | 2.6 mm | 1.6 mm | 9.6 mm | 1.016, 1.014, 1.020 |
| `youth-f-a` | 0.8 mm | 0.6 mm | 2.5 mm | 0.997, 0.997, 0.995 |
| `youth-f-b` | 0.0 mm | 0.0 mm | 0.2 mm | 1.000, 1.000, 1.000 |
| `youth-f-c` | 0.7 mm | 0.6 mm | 2.8 mm | 1.002, 1.003, 1.003 |
| `youth-m-a` | 4.0 mm | 1.8 mm | 4.2 mm | 0.967, 0.984, 0.967 |
| `youth-m-b` | 3.8 mm | 1.7 mm | 3.8 mm | 0.969, 0.987, 0.969 |
| `youth-m-c` | 3.9 mm | 1.8 mm | 3.9 mm | 0.968, 0.989, 0.969 |
| `adult-f-a` | 0.8 mm | 0.7 mm | 2.5 mm | 0.998, 0.997, 0.995 |
| `adult-f-b` | 0.0 mm | 0.0 mm | 0.0 mm | 1.000, 1.000, 1.000 |
| `adult-f-c` | 0.7 mm | 0.6 mm | 2.9 mm | 1.002, 1.003, 1.003 |
| `adult-m-a` | 4.8 mm | 2.1 mm | 4.7 mm | 0.959, 0.982, 0.961 |
| `adult-m-b` | 4.7 mm | 2.0 mm | 4.5 mm | 0.959, 0.985, 0.962 |
| `adult-m-c` | 4.8 mm | 2.1 mm | 4.8 mm | 0.958, 0.987, 0.962 |
| `elder-f-a` | 1.5 mm | 1.4 mm | 8.8 mm | 1.000, 1.001, 0.997 |
| `elder-f-b` | 1.5 mm | 1.4 mm | 9.0 mm | 1.002, 1.004, 1.000 |
| `elder-f-c` | 1.9 mm | 1.6 mm | 8.8 mm | 1.003, 1.007, 1.001 |
| `elder-m-a` | 5.3 mm | 2.3 mm | 5.1 mm | 0.952, 0.980, 0.956 |
| `elder-m-b` | 5.3 mm | 2.2 mm | 4.9 mm | 0.953, 0.983, 0.957 |
| `elder-m-c` | 5.4 mm | 2.3 mm | 5.4 mm | 0.951, 0.985, 0.957 |

- Every generated head sits at the same place in its file (the chin at 1.535 m), so the matrix is in the file's own space and needs no other frame.

**How the client attaches a style** (`compose.py`, `attach_hair`, is this rule applied to a file):

1. Take the style's `Hair` mesh as it is, with its weights. Beyond the far switch take `FarHair`.
2. **Joints by name:** each joint the style's skin names is the person's own bone of that name. The bones only the style has (its spring chains) are added under the person's `J_Id_Cranium`, each at `hair_fit` × its rest in the style's file.
3. **Inverse bind matrices:** for each joint, the inverse of that joint's rest in the type's file (which is the type's own inverse bind matrix for it) times `hair_fit`. A hair vertex then stands at `hair_fit` × its place in the style's file, and follows the identity bones from there.
4. **Colour** by the mesh tag, as recipes recolour hair today.
5. The spring chains are listed in the style's VRM block; add them to the person's.
6. The style's other meshes (a tie, in cloth) attach the same way.

**Proved on a file.** A man of `adult-m-a`, the type furthest from the standard, with 38 drawn identity values (distance 0.32 from his type):

| | Hair vertices | Root mean square | Most |
|---|---|---|---|
| `tousled` (no spring bones): the composed file as a glTF reader evaluates it, against the generator's rule | 2,033 | 0.000 mm | 0.000 mm |
| `long` (16 spring bones added): the same | 4,502 | 0.000 mm | 0.000 mm |
| `long`: Blender reading the composed file, against `compose.py` reading it | 4,502 | 0.007 mm | 0.067 mm |

- The generator's rule here is the baked person: every hair vertex through `hair_fit`, then through the identity bones' matrices by its weights (`cage_head.bone_matrices`), a spring chain moving as the cranium's bone does.
- **Against hair built on the type itself** the fitted style is not the same hair: 4.2 mm away on `adult-m-a` with `tousled` (root mean square; 7.6 mm at the 95th percentile), 3.1 mm on `child-u-a` with `bob`, 2.6 mm on `elder-f-c` with `bun`. Unfitted it is 5.2, 3.3 and 2.6 mm. Another head grows slightly different hair (the hairline and the locks are placed from the head's own surface), so this measures the difference between two valid heads of hair, not only the misfit.
- **Judged by eye** on five types and six styles (the board's `styles-on-types`): no scalp shows through and no style floats.

**What a shared style gives up.** A person's hair was drawn from eight numbers (length, parting, fringe, volume, curl and so on); a shared style has the one set its file was built with. Variety within a style then comes from colour and from more style files, each about 0.3 MB. Greying lock by lock, which was a person's, is not in a style file.

**What the client needs for hair styles** (for the laptop coordinator):

1. Attach a style by the six steps above. The one new thing beside what outfit pieces do today is `hair_fit` in the inverse bind matrices, and adding the style's own bones.
2. The rim on hair, as above.
3. Until outfits are style files too, a person cannot be spawned whole from a type file: `gen_person.sh` still writes one file a person, with its own hair.

### Outfit pieces

Pass 3, after hair (2026-11-12). `living/tools/blender/gen_styles.sh` writes them with the hair styles (about two minutes for everything); `gen_styles.sh outfit` writes only these.

```bash
living/tools/blender/gen_styles.sh [hair|outfit|hair/<style>|outfit/<piece>]     # the shared style files
python3 living/tools/characters/compose.py TYPE.glb OUT.glb --person NAME.params.json --drop Far   # a whole person from shared files
python3 living/tools/characters/person_check.py OUT.glb NAME.params.json [--own OWN.glb]           # against the rule, and against their own file
```

**The split between a type's body and the pieces.**

- **A type's file holds the skin that shows:** the head, the neck and the hands. There is no torso, arm or leg skin in any file: the clothes are the body, as they were, so no hidden skin is drawn.
- **A piece holds only what shows of it in the outfit it belongs to.** A jersey is three files: whole (worn alone), as worn under a coat (its front, collar and cuffs) and as worn under a smock (its collar and cuffs). Trousers and boots are whole in every outfit.
- **Hair under a cap** is the style's `.cap` file, cut where the cap covers it. Under a kerchief it is the style `kerchief`.
- **A tie** (a braid's, a tail's) is a second mesh in its hair style's file, in cloth, and attaches with it.

**The files.** Every piece is built once (`person.py --variant piece:<name> --parts keep`), on the standard head and at the standard build (weight and muscle 0). It holds the `Cloth` mesh and its far mesh `FarCloth`, skinned to the `J_Bip_*` bones every generated file shares, with outline normals and widths, and no clips.

| Piece | Forms | `Cloth` triangles | `FarCloth` | File |
|---|---|---|---|---|
| `jersey` | `-m`, `-f` | 4,320 | 1,080 | 0.39 MB |
| `jersey_coat` | `-m`, `-f` | 2,128 | 532 | 0.21 MB |
| `jersey_smock` | `-m`, `-f` | 1,280 | 320 | 0.13 MB |
| `coat` (with its buttons) | `-m`, `-f` | 7,176 | 844 | 0.43 MB |
| `smock_50`, `smock_58`, `smock_74` (the hem's height, cm) | `-m`, `-f` | 4,544 to 4,064 | 1,136 to 1,016 | 0.27 to 0.30 MB |
| `apron_50`, `apron_58`, `apron_74` (since the overlay step; the smocks are plain) | `-m`, `-f` | 448 | 112 | 0.06 MB |
| `trousers` | `-m`, `-f` | 2,096 | 524 | 0.20 MB |
| `boots` | `-m`, `-f` | 2,680 | 660 | 0.19 MB |
| `cap` | one | 660 | 232 | 0.06 MB |
| `kerchief` | one | 1,188 | 432 | 0.09 MB |

- 26 files, 6.8 MB. Hair is now 22 files, 5.7 MB: the 13 styles, `balding`, `kerchief`, and seven as worn under a cap.
- **Two forms, `-m` and `-f`,** because a woman's torso and limbs are built differently (the torso's shape, and limbs 0.86 as thick). Children wear `-m`, as they wore a man's garments before.
- **Colour** is per vertex on one material a file, as the client's outfit pieces are today, so a recipe colour moves the piece's mean colour.
- **Head pieces** (`cap`, `kerchief`) sit on the standard head and attach with the type's `hair_fit`, as hair does. Body pieces need no fit of their own: every file's body skeleton is the same.

**Build is the bones'.** The client's proportions already move the body (`characters.rs`, `bone_scale`: `build` is the girth of torso and limbs, `shoulders`, `hips`, `torso`, `legs`, `arms`, `neck`). A per-person file also built the person's girth into its meshes (the torso's from 0.91 to 1.15 across Cullet, the limbs' from 0.77 to 1.11). A shared piece cannot, so a person's line carries it in `build`: the per-person recipe's `build` times the mean of the torso's and the limbs' girth, each against the standard for the person's form (`person_params.person_line`). Across Cullet that `build` runs from 0.80 to 1.21.

- **What bones cannot give:** a belly (12 of the 64 have one worth the name) and a strong chest, which were shapes of the mesh. They are gone from composed people until a body type's piece brings them.

**A person's line** is written into `<name>.params.json` as `person`, beside the per-person file's `recipe`: the type, the height, the proportions (with the `build` above), the identity values, the colours and the style files worn. That is the recipe line of [the client format](#the-client-format), as the generator now writes it.

**Proved on three Cullet residents** (`compose.py --person`, then `person_check.py`), each composed onto their type's file: Tamsin Hollin (`adult-f-a`; a braid with its tie; smock with apron, jersey, trousers, boots), Fenn Brandt (`adult-m-b`; `sides` under a cap) and Joss Tarn (`adult-m-b`, `build` 1.18; a coat).

| | Tamsin Hollin | Fenn Brandt | Joss Tarn |
|---|---|---|---|
| Hair, as read against the rule | 0.000 mm (3,768 vertices) | 0.000 mm (1,026) | 0.000 mm (2,033) |
| Clothes, as read against the rule | 0.000 mm (6,900, five files) | 0.000 mm (7,186, four) | 0.000 mm (9,122, four) |
| Face skin against their own file | 0.4 mm | 0.2 mm | 1.3 mm |
| Clothes against their own file | 4.2 mm (46 at most) | 2.0 mm (8.8) | 9.7 mm (25.1) |
| Neck and hands against their own file | 3.7 mm | 2.5 mm | 10.3 mm |
| Hair against their own file | 47 mm | 5.2 mm | 6.3 mm |

- **Against the rule** is the baked person as before: each style file's own vertices through the type's fit and the identity bones (hair and head pieces) or as they are (body pieces). The composed file, read as glTF, is that to 0.000 mm.
- **Against their own file** both are posed by the client's proportions (repeated in `person_check.py`), the composed one by its line's and the own file by its recipe's. Root mean square, each vertex to the nearest of the other. This is the cost of sharing: the clothes of a person of ordinary build are within 2 to 4 mm, a heavy man's within a centimetre (25 mm at most), and Tamsin's braid is the style's length, not her own.
- **In the game** the three stand and move beside their own files (the board's `people-composed-and-baked`), on the shared clips.

**Cullet's 64 residents, as shared files against their own files:**

| | Their own files (pass 3) | Type and styles |
|---|---|---|
| Files | 64, one a person | 51 shared (17 types, 14 hair, 20 outfit) and 64 lines of about 1.5 kB |
| Size on disk | 149 MB (2.33 MB a person, without clips) | 26.4 MB |
| Unique meshes (near) | 448 (7 a person) | 121 |
| Unique materials | each person's atlas makes four of their own (face, eyes, lines, skin) unless paged | 38 |
| Mesh entities a person | 7 | 9 to 11 (10.1 on average) |

- Everything on disk, worn or not: 69 files, 34.2 MB.
- **A person is more mesh entities than before** (a coat, a jersey, trousers and boots are four where the own file joined all cloth into one), and what that costs depends on whether the client batches the shared meshes. **The draw counts could not be measured:** the crowd tool measures files the client can spawn, and it cannot spawn a person from styles yet.

**What the client needs for outfits** (for the laptop coordinator; nothing in `living/game` was edited):

1. **Pieces attach as outfit pieces do today** (`characters/outfit.rs`): each primitive under the person's root with a `SkinnedMesh` on the person's own bones by name, the piece's own inverse bind matrices. The files are named in the person's line (`styles.outfit`), not in `outfits.json`.
2. **`cap` and `kerchief` attach as hair does,** with `hair_fit` ([hair styles](#hair-styles)).
3. **A hair style's second mesh** (its tie) attaches with it.
4. **`build` in a person's line is larger** than in the per-person recipe, as above; nothing changes in how it is applied.
5. Beyond the far switch, take each file's `Far*` mesh.

**Not built in this step.**

All three of these (beards, stubble and lines; the apron; the eyes' colour) were built in the next step: [overlay styles](#overlay-styles).

### Overlay styles

Pass 3, after outfits (2026-11-12). A composed person lost what a type does not have: a beard, stubble, age lines, freckles. The apron took its smock's colour, the eyes the type's, and a heavy person their belly. This step gives each back through shared files.

**Beards, stubble, lines, freckles** (`gen_styles.sh overlay`; `person.py --variant overlay:<type>:<name> --parts overlay`). Each is `lookdev/styles/overlay/<type>/<name>.glb`:

- **A thin layer over the type's own face:** the faces of the face's skin the detail touches, 0.3 mm off it, as one mesh, `Overlay`, with the face's own weights and its two expressions, so it rides the identity bones, the blink and the open mouth. Under a beard the layer stands off the skin by the beard's thickness, as the skin itself did in a per-person file.
- **Its picture is what the face's paint adds for that detail,** as grey with an alpha (512 × 512). The client tints a grey picture by the tag in place of moving its mean colour, so the layer takes the person's colour and blends over the type's face.
- **Two materials:** `M00_000_00_Overlay_00_HAIR` (a beard, stubble), which the hair's tag reaches, and `M00_000_00_FaceOverlay_00_SKIN` (lines, freckles), which the skin's tag reaches and which is lit as a face is: its file has the type's shadow map beside it. Both are `alphaMode: BLEND`; today's client blends them as they are.
- **One file a type, and no `hair_fit`.** That fit lays one skull onto another. A beard lies on the jaw, which differs between types by more than a fit of six numbers carries, and its picture is drawn in the type's own skin layout. So an overlay is built on each type that can wear it, and attaches with the type's own inverse bind matrices, as a body piece does.

| Overlay | For | Triangles (on `elder-m-b`) | File |
|---|---|---|---|
| `beard_moustache`, `beard_goatee`, `beard_chinstrap`, `beard_short`, `beard_full` | men's adult and elder types (6) | 1,020 (goatee) to 1,680 (full) | 0.12 to 0.20 MB |
| `stubble` | those and the youths' (9) | 1,340 | 0.18 MB |
| `lines` | adult and elder types (12) | 756 | 0.13 MB |
| `freckles` | every type (21) | 766 | 0.13 MB |

- 72 files, 8.1 MB. Cullet's 64 wear 28 of them: lines 31 people, stubble 13, freckles 12, a full beard 5, a goatee 3, a short beard 1.
- **Each has one strength,** the file's (stubble at 0.8, lines at an elder's, freckles at 0.7): a person wears it or not, by a threshold on their own value (`person_params.person_line`). Fenn Brandt's stubble on the board is heavier than his own file's.
- **A type's own face is now clean of them:** `gen_types.sh` builds every type with no lines, stubble or freckles, the elders' too.

**The apron** is a part of its own (`Apron`, built 1.8 mm over the smock) and a piece of its own, `apron_50`, `apron_58`, `apron_74` in `-m` and `-f`, 448 triangles. The smocks are plain. A person in a smock and apron wears both, each with its colour.

**Eye colour.** How the tag reaches the iris, exactly:

- The client groups materials by VRoid's names, and the eyes' colour (`colors.eyes`) goes to materials whose name contains `EyeIris`. It recolours by moving the material's picture's mean colour to the person's.
- Our iris was part of the eye's material (`…Eye_00_EYE`) and drawn on the face's atlas, so no tag reached it, and had one, the atlas's mean is the skin's.
- So the files carry: the iris as a primitive of its own in the `Face` mesh, in the material `M00_000_00_EyeIris_00_EYE`, with a picture of its own (the atlas's iris block, 192 × 192) and UVs into it. A type's face is six primitives where it was five. The white and the lights in the eye stay in `…Eye_00_EYE`.
- Nothing is asked of the client beyond what it does for a VRoid base. The far head paints its eyes on its skin and takes no eye colour.

**Bellies.** Twelve of the 64 have one worth the name, and 33 have some. Two fixes were possible: a heavy variant of every upper piece (about 18 more files, and a step between two bodies), or a bone. The bone is cheaper and continuous, and it was built:

- **`J_Fit_Belly`,** under `J_Bip_C_Spine`, in every generated file's skeleton. No clip keys it.
- **The fronts of the upper pieces carry a share of it** (`person.py`, `belly_weights`): the same bell by height the generator's own belly has, on the front half. At rest nothing changes.
- **A person's line has `belly`** (the generator's value, 0 to 0.35 across Cullet) when they have one. **The client moves the bone forward by `belly` × 0.108 m** (the file's -Z) from its rest; `compose.py` does that.
- It is the belly's forward bulge only. The sides' widening (0.45 of it in the generator) is not in it.

**Girth does not move the arms.** The client hangs the arms from the upper chest, widened by `build` × `shoulders`. A person's own file put its girth on below the shoulders only. So a person's line divides `shoulders` by the girth it multiplied `build` by. Neck and hands went from 2.5 to 10.3 mm off their own file's to 0.3 to 2.0 mm.

**Colours in a person's line:** `hair` is the natural colour gone as grey as the person's is (a per-person file greys lock by lock; a shared style takes one tint); `beard` is the beard's own; `eyes` is the iris's; `outfit` has a colour for each piece, the apron's included.

**Four Cullet residents, composed against their own files** (`compose.py --person`, `person_check.py`): Ode Pontil (`elder-m-b`; a full beard and lines), Fenn Brandt (`adult-m-b`; stubble and lines; `sides` under a cap), Tamsin Hollin (`adult-f-a`; lines and freckles; a braid; smock and apron) and Joss Tarn (`adult-m-b`, `build` 1.18, `belly` 0.22; a coat).

| | Ode Pontil | Fenn Brandt | Tamsin Hollin | Joss Tarn |
|---|---|---|---|---|
| Hair, clothes and overlays, as read against the rule | 0.000 mm | 0.000 mm | 0.000 mm | 0.000 mm |
| Face with its overlays against their own file | 0.3 mm (1.3 at most) | 0.2 mm | 0.4 mm | 1.3 mm |
| Clothes against their own file | 1.3 mm | 1.5 mm | 3.2 mm (46 at most) | 7.4 mm (25 at most) |
| Neck and hands against their own file | 0.3 mm | 0.3 mm | 0.7 mm | 2.0 mm |
| Hair against their own file | 7.8 mm | 5.2 mm | 47 mm | 6.3 mm |

- **Against the rule** now covers overlays (the identity bones alone, on the type they were built on) and the belly's bone on body pieces.
- **Ode Pontil's beard** lies within 0.3 mm of the bearded skin of his own file.
- **Joss Tarn** is the heaviest of the four: 9.7 mm before this step, 9.4 with the belly's bone, 7.4 with the shoulders'.
- Hair differs as before: a shared style is not the person's own length.
- **By eye** (the board's `people-composed-and-baked`): beards, stubble, the apron's colour, grey hair and eye colours now agree with the own files; a composed face's lines are fainter than an elder's own, and the eyes' colour is a stand-in for the client's tag (the iris's picture redrawn in the colour).

**Cullet's 64, with overlays:**

| | Their own files | Type and styles |
|---|---|---|
| Files | 64 | 79 shared (17 types, 14 hair, 20 outfit, 28 overlay) and 64 lines |
| Size on disk | 149 MB | 29.2 MB |
| Unique meshes (near) | 448 | 166 |
| Mesh entities a person | 7 | 10 to 15 (12.3 on average) |

- Everything on disk, worn or not: 141 files, 41.3 MB.
- **A composed person is now about twelve mesh entities,** two or three of them blended layers on the face. That is the price of keeping details out of per-person pictures, and it is the client's batching that decides what it costs. It could not be measured here, for the reason given under [outfit pieces](#outfit-pieces).

**What the client needs for overlays** (for the laptop coordinator; nothing in `living/game` was edited):

1. **Attach** each file a person's line names in `styles.overlays`, from `lookdev/styles/overlay/<type>/`, as a body piece: joints by name, the file's own inverse bind matrices.
2. **Drive the two expressions on the layer too.** `lookdev.rs` `rig` finds the blink and the mouth on the `Face` node only; an `Overlay` mesh has the same two targets and must take the same weights, or a beard stays shut when the mouth opens.
3. **Tags:** `Overlay_00_HAIR` takes `colors.beard` (or the hair's), `FaceOverlay_00_SKIN` the skin's. Their pictures are grey, so they are tinted.
4. **`belly`:** translate `J_Fit_Belly` by (0, 0, -`belly` × 0.108 m) from its rest, once, when the person's scene comes in.
5. `colors.eyes` already reaches `EyeIris` materials.

**Left.** A far model has none of these layers, so a bearded man's far head is clean-shaven. Per-person files (`gen_person.sh`) still paint the details into the person's own atlas.

### Hair finish and cuts

Pass 3, after overlays (2026-11-12). Three faults of the hair's finish, more variety, and beards on the far head.

**Judged without the rim light.** The client's rim light on hair is being fixed on its own branch (`hair-rim-1`), and with it hair cannot be judged ([hair styles](#hair-styles)). The stand-in used here is `compose.py --hair-toward YAW`: every hair normal turned to the asset view's camera for that one view, which takes the rim out from that side. It also flattens the hair's own light and shade, so the pictures show shape and edge, not the final shading.

**The finish** (`hair.py`, and `hairline` in `person.py`):

| Fault | What it was | What changed |
|---|---|---|
| A blocky fringe | Seven broad locks (48 mm), their ends up to 8 mm apart, each cut square | Half as many locks again and each narrower (0.74), ends within 1.5 mm of one line with every second a little longer, tips less square |
| Ragged ends | The hanging layers' locks ended up to 16 mm apart; `long` tapered every lock to a point at a length of its own | Ends within 3 to 4 mm of one hem, locks a tenth wider so the hem closes; `long` is cut (blunt 0.4) with 6 mm of unevenness, where it had 35 |
| The temple gap | The hairline tuned on pass 2's head left a bare temple and skin above the ear on a type's head; a short style's scattered locks did not cover it | On a type's head the line is 18 mm lower at the temple, runs down to a sideburn at the middle of the ear, and sits 4 to 6 mm closer over the ear's top; `crop`, `short` and `tousled` get six short locks a side there. A style with hanging sides (`bob`, `long`, `shag`) had bare scalp between the fringe's edge and the side hair: three locks a side now come from high on the temple, two combed down and back and one straight, and the side layer starts at the ear's front (64° round, where it started at 56°), so nothing of it hangs over the eye from a three-quarter view |

- Checked on `adult-f-b`, `adult-m-a`, `child-u-a` and `elder-f-c`, with `bob`, `long`, `tousled`, `short` and `bun`, from the front, three-quarter and side, and at the game camera (the board's `hair-finish`).
- **At the game camera** the differences are a pixel or two: the fringe's line and the covered temple show, the ends do not.
- **What it did not change:** locks are still ribbons of one thickness with no strand breaking away, and a spiky style (`tousled`) is still spikes. That is the style's drawing, not a fault of finish.
- **What is left of the temple:** a strip of skin a finger wide beside a straight fringe, from the front and three-quarter. From the exact side a full `bob` or `long` hides the face but for the nose, as it did before; the reference's side hair starts 3 cm further back.

**Variety: three cuts of each style, as separate files.**

- **What was chosen.** Each style is written three times, `<style>`, `<style>.2` and `<style>.3` (`person_params.CUTS`), each from its own seed, so each has its own length, parting, fringe, volume and curl, drawn as a person's used to be. A person wears the cut their seed picks. `kerchief` has one, and the seven styles written for under a cap have one each.
- **Why files and not bones.** A parting on the other side moves every root; a curtain fringe is other locks than a straight one; a longer cut has more rings in each lock. Those are different meshes. A bone could lengthen a hanging lock or lift a fringe, but it needs a table and code in the client, and it gives one axis where a cut gives five. A file needs nothing new from the client: the name in a person's line is the file.
- **What it costs.** 50 hair files, 17.0 MB (0.12 to 0.68 MB each), where there were 22 and 5.7 MB.
- **What it gives Cullet.** The 64 wear 30 hair files where they wore 14. The most worn is `tousled.2`, by six. With the hair's colour, six people in three pairs have the same file and the same colour; the other 58 differ from everyone in one or the other.
- **If more is wanted,** `CUTS` is one number: a fourth cut of every style is about 5 MB.

**Far beards.** A bearded man's far head was clean-shaven. Each beard's overlay file now has a second mesh, `FarOverlay`: the far head's own faces under the beard, 4 mm out, in a plain material (`M00_000_00_FarOverlay_00_HAIR`, no picture, no expressions) that the hair's tag tints. 456 triangles for a full beard on `elder-m-b`; the file goes from 0.20 to 0.22 MB. Stubble, lines and freckles have no far mesh: at that distance they are not seen.

**What the client needs** (for the laptop coordinator):

1. Nothing for the cuts: `styles.hair` in a person's line names the file, cut included.
2. Beyond the far switch, take a beard overlay's `FarOverlay` mesh with the far head, tinted as the near one is.

**Cullet's 64 after this step:** 95 shared files worn, 36.4 MB (17 types 18.0, 30 hair 11.1, 20 outfit 4.2, 28 overlay 3.2). Everything on disk: 169 files, 53.0 MB.

### Type files

`living/tools/blender/gen_types.sh` writes `lookdev/types/<type>.glb` for the 21 types, with `<type>.face.png` (the face's shadow map) and `<type>.params.json` beside each. A file holds:

| | |
|---|---|
| Skeleton | the 52 `J_Bip_*` bones and the root, as every generated person; the 25 `J_Id_*` bones and the two eye bones at rest: 80 joints |
| `Face` | the whole head (the scalp too, since every hair style shares it): skin, eyes, lashes and lines, and the skin under the jaw; 5,840 triangles; two morph targets, `Fcl_EYE_Close` and `Fcl_MTH_A` |
| `Skin` | the neck and hands, 4,536 triangles |
| `FarSkin` | the far head, neck and hands on the same skeleton, 1,964 triangles, with its own small picture |
| Normals | the designed face normals (`face_normals.py`) and `_OUTLINE_NORMAL` |
| Not in it | hair, clothes, clips, hair's spring bones |

- **Size:** 0.91 to 0.96 MB a file, 19.6 MB for the 21; the shadow maps are 0.37 MB together.
- **The figure** a type's file is built on is `person.py --variant type:<id>`: every identity value 0, the band's usual age, height and build, no freckles, stubble or weathering, skin tone 0.25.
- **Morph data.** A type's file has 3,568 morphed vertices and 2 targets: 86 kB in the file. A person's file today has 15 targets on about 3,170 vertices: 570 kB. At the 36 bytes a vertex a target that Bevy's morph texture holds (position, normal and tangent; our estimate, not measured in the client), that is about 0.26 MB a type against 1.7 MB a person, and 5.3 MB for all 21 types. The laptop measured 339 MiB of morph targets for 64 people. By the same ratio (2 targets of 15, and at most 21 types for any number of people) types bring that to about 15 MiB however large the town.
- **Expressions.** `--morphs client` keeps the two the game drives. The other 13 (`Fcl_EYE_Joy`, the mouth shapes, the brows) are still built by `--morphs all` and by `gen_person.sh` unless `MORPHS=client`; when the client drives one, it is added to `CLIENT_MORPHS` in `person.py` and each costs a type about 0.13 MB.
- **`gen_person.sh` switches:** `CLIPS=none` bakes no clips into a file; `MORPHS=client`; `IDENTITY=bake` builds the identity into the vertices where the default moves the bones.

**The standard figure for the shared clips.** `lookdev/anim/own-clips.glb` (`share.py clips`, from the client's `crowd-1`) is baked on the `man` preset, and the client measures a person's stride against that file's figure, so nothing else depends on which figure it is. With the cage head the `man` preset stands 1.803 m in the file; it stood 1.837 m when `crowd-1` chose it, because the head changed. The clip file is to be made again from the current preset when the type files go into use, and is not to move to a type's own figure.

### What the client needs for types

Nothing in `living/game` was edited in step 3, and every file loads in today's client. For the laptop coordinator, in the order they unlock things. 1 to 3 are done in the client since types-1 ([below](#the-client-since-types-1-2026-11-12)); 4 waits for the style files.

**1. Outline normals from the file** (`lookdev.rs`, `convert` and the scenery path). Small.

- Name the attribute to the glTF loader: `GltfPlugin::default().add_custom_vertex_attribute("OUTLINE_NORMAL", bevy_mod_outline::ATTRIBUTE_OUTLINE_NORMAL)`, without the underscore: the gltf crate names a custom attribute `_X` as `Semantic::Extras("X")` (types-1 found the name with the underscore never matches).
- Skip `generate_outline_normals` for a mesh that already has `ATTRIBUTE_OUTLINE_NORMAL`.
- It saves the generation at load for every person and closes the outline between a person's meshes. Per-vertex line width (step 5) will ride the same path.

**2. Identity** (`characters.rs`, `shape`). Medium. The rule is `living/tools/characters/compose.py`, `transforms`, about 30 lines, and `compose.py --compare` checks a file posed by it:

- each value v in -1 to 1 becomes an amount from `types.json`'s `rig.bones`: at -1 the value's `least`, at 0 nothing, at 1 its `most`;
- a `move` adds amount ‰ × `file.head_height_m` (0.2564) along the value's axis to the bone's rest translation; a `scale` multiplies the axis; a `turn` rotates about it;
- the rig's x, y, z are the file's X, -Z, Y; `o` is 0.55 x + 0.83 y; on a paired bone x points away from the midline on both sides, so the right bone (`…_R`, at +X) takes the left's values mirrored;
- a bone's node gets translation, rotation and scale, and its children ride it.
- **Order with `shape`'s proportions:** identity is inside the head; the recipe's `head` scales `J_Bip_C_Head` as today, and the identity bones ride it. The helper joints `shape` makes for unevenly scaled bones are not needed for identity bones: their children are meant to take the scale.
- A person's recipe `head` is written by the generator (`<name>.params.json`, `recipe.proportions.head`); the `cullet-*` lines in `recipes.json` do not carry it yet.

**3. Colours without a texture a person.** The step-3 board's `skin-tones` sheet has one file painted at tone 0.30 recoloured by today's client (mode 3, the texture's mean moved to the person's colour) beside the generator's own paint at seven tones.

- **The lid's shade holds** at every tone.
- **Lips and blush do not.** They fade toward the skin at every tone, the file's own included, and are nearly gone on the lightest two. A mean-colour move keeps only what differs from the mean in lightness.
- So lips and blush leave the skin texture: lips become a small mesh of their own with its own tag colour, blush an overlay style, as stubble, lines and freckles are to be. That is the generator's work, with the face's paint (step 6), and needs nothing new from the client beyond the mesh tag it has.
- **Textures held CPU-side.** The laptop measured about 500 MiB of face pages kept CPU-side for recolouring. Under types the skin texture is one a type (21, about 0.1 MB each as PNG). The format does not need the client to keep or rewrite it: if the tag's colour is applied in the shader (the type's texture as a tint map over the person's skin colour, the same mode-3 sum done per fragment), no picture is copied a person and none needs to stay CPU-side. That is the client's to choose; nothing in the files depends on it.

**4. Type files in place of person files** (the recipe's `type`), with styles. Later: it needs the style files (hair, outfit), which the generator does not write yet. Until then a person is still one file, made by `gen_person.sh`, with its identity in bones.

- A hair style's spring chains hang under `J_Id_Cranium`; a type's file has none of its own.
- The far switch and clips once are as in [what the client needs](#what-the-client-needs).

### The client since types-1 (2026-11-12)

**What the client does now:**

- **Outline directions from the file.**
  - `main.rs` names `_OUTLINE_NORMAL` to the glTF loader, as `OUTLINE_NORMAL`. Every place that gave a mesh outline directions now calls `style::outline_normals`, which keeps a mesh's own and generates them only for a mesh without.
  - The `assets:` diag line counts both. A type's or a new person's meshes bring theirs (21 of 21 in a run of the three people below); pass 3's town files predate `outline_normals.py` and are generated as before.
  - `LIVING_GAME_PERF=genoutlines` generates every mesh's, to compare.
- **Identity** (`characters/identity.rs`, `characters.rs` `set_identity`).
  - A recipe's `identity` (values by name) moves the identity bones by compose.py's rule, ported line for line. The rig comes from `characters/types.json` under the asset folder when there is one, else from the copy compiled in (`living/tools/characters/types.json`).
  - **It is set when the person's scene comes in** (the `WorldInstanceReady` observer, which also runs for a scene spawned again), not in `shape`. Bevy 0.20 takes a skinned mesh's bounds from its joints, and `fit` sizes the person by those bounds. Set in `shape`, a person was fitted on the type's rest head and came out about a pixel larger than the same person composed in the file.
  - A file whose identity bones are already moved (`gen_person.sh`'s people, through compose.py) starts from the rest its nodes record (`extras.rest_translation`), so values given again change nothing.
  - **The proof:**
    - `characters::identity::tests` holds the port to compose.py's own `transforms` for three sets of values (every value at 1, every value at -1, a generated person's 38): 81 bone changes (`living/tools/characters/identity_cases.py` writes them).
    - In the client, a person whose identity bones were put back to rest, given the same values in its recipe, ends with all 27 bones at compose.py's transforms: translation within 5×10⁻⁹ m, scale 1×10⁻⁷, rotation 3×10⁻⁹.
    - Photographed with the idle clip held, that person, the same person composed by compose.py and the same person baked (`IDENTITY=bake`) show the same face. Their pixels differ by 0.05 to 1% between any two, the composed and baked pair included, from the pose's run-to-run settling (foot IK, the head on the hips).
  - **A type's file can't be a character by itself yet:** it is a head, neck and hands, and `fit` sizes a person by its meshes, so it would stretch the head to the person's height. That waits for the style files (4).
- **Colours without pictures held on the CPU** (`characters.rs` `thumb_pictures`, `Thumbs`).
  - The tag colour was already applied per fragment (mode 3 in `toon.wesl`). The CPU read a picture only for the mean colour of the texels a mesh uses, and for that kept every picture's pixels.
  - Now each picture of a character file (`lookdev/…`) keeps a 64×64 summary of its colours, and its usage becomes the render world's alone, so Bevy drops the main world's copy once it is uploaded. The means are taken from the summary, so a page shared by 16 people serves the ones that spawn later.
  - `LIVING_GAME_PERF=keeppixels` keeps the pixels, to compare.
  - **Measured** (the `assets:` line, laptop, at the game camera):

    | | Pixels kept (before) | Pixels dropped (types-1) |
    |---|---|---|
    | Cullet's 64 (both-files, paged) | 525.9 MiB of images | 9.2 MiB |
    | 64 VRoid bases (recoloured) | 182.4 MiB | 9.2 MiB |

    The 9.2 MiB left are the scene's own pictures. The recoloured VRoid crowd draws the same either way: 0.13% of pixels differ, from the idle loops' timing.
- **The shared clip file again.** `lookdev/anim/own-clips.glb` is baked from today's `man` preset, 1.803 m with the cage head. Stride against it still gives each of three of Cullet's people their own metres a cycle to 1 mm in every forward gait (walk 1.408 against 1.409 m at most).
- **Morphs:** the client drives `Fcl_EYE_Close` (the blink) and `Fcl_MTH_A` (the mouth, only for look-dev's `talk`) and no other, so `--morphs client` loses nothing.
- **Not done here:** step 4's optional shading (the shadow lookup along the head's forward vector, the face and neck shade blended at the jaw, the sun's height in the map's blue channel) and the far head's own round normals; type files as characters with styles (4).
- **Evidence:** `.local/living/types-1/` (`view/identity-held`, `view/outline-*`, `mem/`, `identity-transforms.json`).

## Motions on generated people

`animate.py` retargets the clip library onto a generated person unchanged, since the skeleton is VRoid's. Limb lengths are our own, so a take can behave differently on our people than on a VRoid base: our man's arms are longer, and a hand that clears the floor on Shino goes 8 cm into it on him.

The eight motions added to the library on 2026-11-11 were baked and judged on both (`clip_check.py`, and the pass-1 page):

| Motion | Verdict | Why |
|---|---|---|
| `gather`, `eat`, `dodge` | Keep | They read at once. `dodge`'s boot toes dip up to 6 cm under the floor during the push-off, too briefly to show at the game camera. |
| `work` | Needs new takes | The hands are busy for about 30% of 6 s, at chest height; it reads as looking at something held. |
| `play` | Needs new takes | One hop in 4 s; the boots go 8 cm under the floor at the hop. |
| `sit_ground_down`, `stand_up_ground` | Fix in retargeting | Good motions. The supporting hand goes 8 to 9 cm into the floor on our man, and the crossed feet sit 7 cm under at the ankle (14 cm at the boot). |
| `sit_ground` | Needs new takes, and the same fix | One held pose: everything ranges 3 cm over 6 s. The feet are under the floor for the whole loop. |

What happened since (2026-11-11):

- **The first floor guard is in `animate.py`** (`floor_guard`, commit `93a4f3d6`, from the laptop's `floor-guard` branch). It runs on every Kimodo and overlay clip and has no switch: a foot whose heel, ball or toe tip is more than 1 cm under the floor has its ankle lifted, and a clip that never goes under bakes exactly as before. It guards feet. A hand under the floor is not lifted; the new takes below were picked so hands stay above it.
- **The second floor guard is not used for these people.** `floor-guard-2` (main, `b30c5df1`) turns the foot about its planted heel or ball and bends the toes, and that makes the toes flick: the dev-box coordinator measured toe jerk of 28 to 98° on Vivi against 7 to 16° before, and up to 43° on `own-man`. Pass 2's branch was merged with main before it landed. Until `floor-guard-3` is on main, bake generated people with an `animate.py` from before `b30c5df1`.
- **`work`, `play` and the three ground motions were taken again** (the clip lab; `clips.json` names the new takes), and 32 locomotion clips were added.
- **Pass 2's people were baked with the first guard** (`animate.py` at `93a4f3d6`), and so was the control. It lifted an ankle in 16 of the 29 clips on our people, by 1.2 to 8.0 cm (`dodge` most; `walk` 2.6 cm, `run` 1.5 cm), and in 15 on the control. The toe bone's worst change in step is 16.2° (`walk_brisk`) on ours and on the control alike, with no clip over 20°. On the dev-box the library held the takes of 30 of the 67 entries; the re-made motions and the new locomotion clips were not there to bake, so they are not judged on pass 2's people yet (`ONLY=present`).
- **The limb guard** (`limb_guard` in `animate.py`, branch `floor-guard-4`) runs after the floor guard on every Kimodo and overlay clip and every body, with no switch.
  - It keeps wrists at least 3 cm above the floor (`LIMB_WRIST_CLEAR`). It keeps ankles at least 0.9 of the lower of the ankle's standing height and the foot's half width (`LIMB_ANKLE_FACTOR`): 4.0 cm on Vivi, 4.6 on Shino, 4.8 on `own-man`.
  - A short wrist is raised by arm IK; where the arm can't reach, the hips rise. A short ankle is raised by leg IK, and the foot keeps its rotation.
  - A low foot (ankle under 0.6 of its standing height: sitting, kneeling, lying) whose heel, ball or toe tip is still under turns toes up about the ankle, at most 70°. What is still under after that lifts it again.
  - It has the floor guard's jerk protection: a clip whose largest frame-to-frame jerk would rise more than 6° is left alone (`limb_guard_skipped`, a marker_check warning).
  - Baked onto the 65 entries with the final town takes, it changed `sit_ground_down` and `sit_ground` on every body, `stand_up_ground` on `own-man`, and `death` on the VRoid bases (toes turned 1–10°). Every other clip bakes byte-identically: 61 of 65 on each VRoid base, 62 on `own-man`.
  - The crossed ankles went from 1–5 cm under the floor to 4.0–4.8 cm above it. The deepest sole point went from 11–20 cm under its standing height to 5–10.
  - **The torso** (branch `body-guard-1`): on low frames (hips under 0.6 of their standing height) the torso stays out of the floor. That is the mesh of the hips, spine, chest, neck, head and shoulders within 20 cm of its bone, so a coat's hem or long hair doesn't count. Where it goes under, the whole body rises by the depth, smoothed over ±8 frames, legs and all (the legs re-solve only for an ankle's own lift, so no new jerk).
    - Baked onto the 65 entries with `death` s1, it changed `death` on every rig (the body lifted 4.0–6.3 cm), plus `sit_ground_down`, `sit_ground` and `stand_up_ground` on `own-man` (3.9–4.4 cm: his hips sat in the floor).
    - Everything else bakes byte-identically: 64 of 65 clips on each VRoid base, 61 on `own-man`. No clip's largest jerk moved by more than 0.5°.
    - `death` s1's last frame: the torso went from 4–7 cm under to clear (the lowest body vertex left under is long hair weighted to the head, 1.6–2.3 cm), and the toes from 1.7–2.5 cm under to 1.4–3.7 cm above.
  - Hands: no wrist goes under 3 cm in any clip. Fingertips are not guarded (`death` 4–4.5 cm under on all three; `stand_up_ground` 2.4 cm on `own-man`).
- **The knee's pole** (`knee_turn` in `animate.py`, branch `leg-pole-1`), in `plant_feet`'s leg solve and in both guards.
  - The leg solves bent the knee toward the thigh's forward axis. A folded knee (kneeling, a tuck) brings that axis into line with the hip-to-ankle line, and there the side the knee bends to flipped: `stand_up_ground` snapped the right thigh 79° in one frame on Vivi (30° on Shino), so both floor guards skipped it and its feet stayed 4–5 cm under the floor.
  - Now the pole turns about the hip-to-ankle line toward where the take's own knee is, by how bent that knee is: not at all within 5% of the thigh's length of the line, fully from 25%. A knee on the far side of the line counts only when clearly bent (`LEG_POLE_FAR`). In `plant_feet` the weight is smoothed over a few frames.
  - Baked onto the 65 entries on three rigs, no clip's largest frame-to-frame jerk rises by more than 1°. Falls: `stand_up_ground` 78 → 10° (Shino 30 → 9.5), `jump_forward` 50–55 → 24, `jump_back` 40–47 → 27, `sit_ground_down` 20–23 → 13–14, and `jump_right` on Shino 24 → 17.5.
  - Both guards now run on `stand_up_ground` on the VRoid bases: the ankles sit 4.0–4.6 cm above the ground (were 4–5 cm under).
  - Every clip's bytes change, since the knee now bends where the take bends it: the legs turn up to 20° in locomotion (`run_fast` on Vivi), 6° in the idle.
  - The forward gaits' planted feet slid no more in the game's look-dev ramp (0–6 m/s on Vivi): walk 2.7 → 2.3%, `walk_brisk` 3.0 → 2.4%, run 4.4 → 3.8%, `run_fast` 3.2%. marker_check: 0 errors.
  - `death` on Shino is still skipped by the floor guard (its hand jerks 93°).
- **Hair on spring bones** changes nothing for `animate.py`: the chains hang under the head and the clips do not key them.
- **Since pass 3 generated people are baked with main's `animate.py` again** (floor-guard-4, `25c1fb92`, which replaced the second and third guards: wrists and ankles are kept above the floor on every clip and body). The board's seven presets and the control were baked with it on the 29 entries this machine holds, and `living/tools/marker_check.py` on that bake reports no errors. On each of our people the guard changed 16 clips; the largest jerk rose by 0.4° at most (`run`, 17.8° to 18.2°, 6° allowed), and one warning stands (`sneak`: the right foot slides 4.5 cm while planted, 4 allowed). The 64 residents used for pass 3's crowd measurement were baked earlier with the first guard, as pass 2's were (`ANIMATE=<a copy from 93a4f3d6>`), so the two sets compared carry the same clips.

## What was learnt from VRoid

The controls `lookdev/vroid-Sendagaya_Shino.glb` and `vroid-Vivi.glb` were taken apart to see how the look is made. Nothing of theirs is used ([third-party record](../living/tools/blender/THIRD_PARTY.md)). The full study of the reference (form, topology, morphs, rig, materials, VRoid's parameter model, the licence) and what our head should change is [CHARACTER_REFERENCE.md](CHARACTER_REFERENCE.md).

| VRoid (Shino) | What it does | Ours |
|---|---|---|
| The face is a mask of 1,342 triangles; the skin texture is nearly flat colour with a blush, a nose shadow and a lip tint | Detail is painted, not modelled | The same idea: a smooth form and a painted atlas |
| Real eye openings; the white is a bowl 3 to 25 mm behind the lids, the iris a disc in front of it, the highlight a third layer; each eye turns on a bone (`J_Adj_L_FaceEye`, `J_Adj_R_FaceEye`), about 10° for a look fully aside | The lids pass in front of the eye, so it reads as set in the head from any side, and it can look round | Since pass 2 the same three layers on a ball of 8 cm radius, the iris and highlights on the same two bones; 6° is a look fully aside |
| Iris texture: a tall ellipse, dark rim, dark upper half, a bright warm crescent below, a blue rim light above | The eye looks lit and deep | Since pass 2 a tall ellipse with a dark rim, a shaded top, rays, a pale ring, a warm crescent below, a cool arc above and a soft pupil; one picture for both eyes |
| Lash line, lashes and brows are separate cards with alpha-blended textures, standing off the skin | Soft drawn edges; they move with expressions | The lash line is a drawn shape with vertex colours. Since pass 2 lashes and brow hairs are strands (small tapering cards), each with its own tone: crisp at any distance, no blending or sorting. |
| Hair: 46 locks, each one primitive of a front and a back surface 3 vertices across and 15 to 88 along (16,400 triangles), all mapped root to tip onto one 512×1024 grey strand texture that is darker at the root and the tip; the scalp carries a second texture of the same strands with a jagged alpha edge at the hairline | Each lock shows strands and shades as one piece; no skin shows between locks | Since pass 2 the same construction, computed: 32 to 51 locks five vertices across over a cap with the strand texture ([how hair is built](#how-hair-is-built)); colour per vertex, so one strand texture serves everyone |
| The highlight is a separate emissive texture: a band a third of the way down each lock, broken into vertical teeth | The glossy band of drawn hair | Not built: the game's own hair shading draws a ring round the head from the normals, with teeth from the hair's UVs. Ours takes that ring; it is thinner and more even than the reference's band |
| 15 chains of spring bones on the long locks, with colliders on the head and body | Hair swings and settles | Since pass 2 up to 5 chains of 5 joints on `long`, `tail`, `braid` and `braids`, in the same VRM block, so the game's spring bones swing them |
| Mouth: a real slit with teeth and tongue inside | Speech shapes show an inside | The same |
| 41 morph targets `Fcl_ALL_*`, `Fcl_BRW_*`, `Fcl_EYE_*`, `Fcl_MTH_*` | Expressions and visemes | 15, built from five controls (each lid, a joyful close, jaw, mouth width, corners, brow ends) |
| Face normals come sculpted; the game flattens them and shades from a map (`face_normals.py`) | A clean shadow edge that sweeps the face | Unchanged; our UVs wrap the whole head, so faces across the seam at the back have their own vertices |
| 30 textures, 10.7 MiB a character | | 1 texture, 0.1 to 0.3 MiB |

## Crowd cost

Cullet will have 64 residents. This section says what 64 generated people cost in the game, what pass 3 did about it, and what the client still has to change. Measured with `living/tools/characters/crowd.py`.

### Pass 3: shared materials, six meshes, a far model (2026-11-11)

Pass 2 found that the cost of 64 different people was not triangles but materials and memory: each file brought its own face, eye and hair materials. Pass 3 changed four things in the generator and none in the game:

- **One material for each kind, shared by everyone.** The strand texture is one file that every person's file names. A town's face atlases are tiles on shared pages, 16 people a page (`share.py`). The game makes one material for each distinct content, and a picture named by path is one picture, so 64 people now bring 12 materials where they brought 195: cloth, skin, face lines, hair, and a face-skin and an eye material for each of four pages.
- **Six meshes a person where there were 12 to 14,** joined by shading kind (`person.py`, `join_kinds`).
- **A far model** from the same parameters, 5,300 to 6,700 triangles in three meshes and three materials (`person.py --lod far`).
- **Clips are not shared yet.** The game takes a body's clips from its own file, so that needs the client ([what the client needs](#what-the-client-needs)). Since crowd-1 the client shares them ([the client since crowd-1](#the-client-since-crowd-1-2026-11-11)).

**What was run.** The 64 residents of Cullet's cast (`town.py --town living/seeds/cullet.json`), each a different file, in the game's own crowd in the open `meadow` environment at the default game camera (22 m, 28° down), every one playing `idle`; headless, uncapped, 1600×900, `LIVING_GAME_PERF=frames,diag`, 24 s a run. Three sets of the same 64 people from the same parameters: pass 2's generator (main at `1d71e6c2`), pass 3's full models, and pass 3's far models. The crowd stands 25 to 40 m from the camera, all of it beyond 10 m, so the far models are what a client that switches by distance would draw there. Each of four rounds ran empty, VRoid, pass 2, pass 3, far, far, pass 3, pass 2, so the three sets were always measured next to each other. One game binary for all (this branch's, built from `1d71e6c2`).

**The machine.** The dev-box, AMD Radeon 8060S integrated graphics, with other workers building throughout: load average 19.9 to 57.7 on 32 threads.

| At the game camera, 1600×900, uncapped | Empty meadow (you alone) | 64 VRoid bases (2 files) | 64 of Cullet, pass 2's files | 64 of Cullet, pass 3's files | 64 of Cullet, pass 3's far models |
|---|---|---|---|---|---|
| Rounds | 4 | 4 | 8 | 8 | 8 |
| Different character files | 1 | 2 | 65 | 65 | 65 |
| Frame time, mean: median (least to most) | 6.4 ms (4.21 to 14.22) | 16.5 ms (10.43 to 48.2) | 19.8 ms (15.9 to 47.91) | 10.8 ms (7.76 to 20.52) | 8.4 ms (6.11 to 26.37) |
| GPU time of the render passes: median (least to most) | 2.6 ms (1.4 to 3.8) | 4.6 ms (2.45 to 7.84) | 6.8 ms (3.89 to 12.26) | 4.1 ms (3.35 to 8.39) | 2.7 ms (1.86 to 4.54) |
| Load average while measuring: median (least to most) | 35 (20.9 to 51) | 38 (20.5 to 48.9) | 25 (20.8 to 57.7) | 25 (21.3 to 57.3) | 24 (19.9 to 57.4) |
| Materials on people in view | 17 | 33 | 212 | 29 | 20 |
| Meshes drawn in the camera's view, people only (one draw each a pass) | 18 | 1,136 | 817 | 402 | 210 |
| Triangles in the camera's view, people only | 31k | 1,846k | 2,078k | 2,078k | 388k |
| Process memory, peak resident: median (least to most) | 2794 MiB (2539 to 3788) | 2886 MiB (2375 to 3365) | 5770 MiB (4982 to 6277) | 4421 MiB (3759 to 4801) | 3334 MiB (2380 to 3915) |
| Graphics memory of the process: median (least to most) | 3530 MiB (3237 to 4180) | 4120 MiB (3650 to 5086) | 5588 MiB (5097 to 7091) | 4674 MiB (4140 to 5189) | 4473 MiB (3241 to 6068) |

**What is firm, and what is not:**

- **Firm: the counts.** Materials on people 212 to 29 (17 of each are the scene's own), meshes 817 to 402, and for the far models 210 meshes and 388,000 triangles against 2,078,000. They do not depend on load.
- **Firm: the order.** Pass 3's files were faster than pass 2's in 8 of 8 runs measured next to each other, and the far models faster than the full ones in 5 of 8.
- **Not firm: how much.** The medians say 64 of pass 3's people take about 11 ms a frame where pass 2's took about 20 ms, and the far models about 8 ms, against 6 ms for the empty scene and 16 ms for 64 VRoid bases. The same run moved by up to three times with the machine's load, and the empty and VRoid runs have four rounds, not eight. In the two quietest rounds (load average 20 to 26) the frame times were: pass 2 15.9, 18.41, 20.3, 17.17 ms; pass 3 9.62, 10.67, 14.84, 10.98 ms; far 7.32, 7.19, 8.77, 7.99 ms.
- **Memory fell, roughly.** Peak process memory over the empty scene's is about 46 MiB a person for pass 2's files, 25 MiB for pass 3's and 8 MiB for the far models. The peak moves with load too (the empty scene's ran from 2,539 to 3,788 MiB), so these are sizes, not measurements to the megabyte.
- **This does not establish the 60 FPS target either way.** That needs a quiet machine, Cullet's buildings and lamps, the town running, a player moving and minds running. The performance contract's rules apply to any claim beyond these counts.

**What the clips cost.** Every file carries its own copy of every clip. The town above was baked with two (`idle`, `walk`). The same 64 far models with the 29 clips this machine's library holds take 4,098 MiB of process memory at their peak against 3,164 MiB with two (3,780 to 4,318 against 2,943 to 3,683; higher in 4 of 4 runs measured next to each other): about 15 MiB a person, or about 553 KiB for each clip a person carries. On disk a far model grows from 0.46 MB to 2.84 MB. The whole library is 67 entries, so 64 people carrying it would hold roughly 2 GB of clip copies. One shared copy needs the client (below; done in crowd-1).

### What the client needs

As written for pass 3. All three are done in the client since crowd-1 ([below](#the-client-since-crowd-1-2026-11-11)).

The generator's files load in today's client unchanged. Three things need a change in `living/game`, which the laptop coordinator owns. Nothing in `living/game` was edited in this pass.

**1. Faces' shadow maps on shared pages** (`lookdev.rs`, `convert`). Small.

- Today: a face's shadow map is looked for only beside its file, `<file>.face.png`. The path is part of the material's content key, so each person's face is a material of its own.
- A paged town has no per-person map. Its maps are tiles of one picture a page (`lookdev/pages/<town>-<n>.face.png`, laid out exactly as the colour page), and each file's face material names it in its glTF extras: `{"face_map": "lookdev/pages/cullet-0.face.png"}`, a path under the asset folder. Bevy puts a material's extras on each mesh entity as `GltfMaterialExtras`.
- The change: when `<file>.face.png` is missing, take the path from the mesh's `GltfMaterialExtras` (`face_map`). The content key already holds the path, so every face on a page becomes one `Face` material.
- Until then a paged face has no map and shades as skin (`Kind::Skin`, as `convert` does for any face without a map): no swept shadow edge, and a fringe can cast a blotch on it. The draw cost is the same either way, so the figures below stand. People made one at a time (`gen_person.sh`, the board's presets) keep their own map and shade as before.

**2. Switching to the far model** (a new small system, or `convert`). Medium.

- The file: `LOD=both gen_person.sh …` (`person.py --lod both`) writes one file that holds the full model and the far model on the same skeleton. The far model is three mesh nodes named `FarCloth`, `FarSkin` and `FarHair`; the full model's are `Cloth`, `Skin`, `Face` and `Hair`. Both sets are skinned to the same bones, so one `AnimationPlayer`, one set of spring bones and one shaped skeleton serve both. Today's client would draw both sets at once, so `town.py` does not make these files yet.
- The change: for a character whose scene has `Far*` mesh nodes, show those and hide the others beyond about 10 m from the camera, and the other way round nearer, with a metre or two between switching out and switching back so a person at the edge does not flicker. `character_shadows` already walks a character's meshes by camera distance and is the pattern. Bevy's `VisibilityRange` would do it with a dithered crossfade, and `toon.wesl` already calls `visibility_range_dither`; check first that `bevy_mod_outline`'s outline pass follows it, since outlines are drawn on their own.
- The far meshes have no morph targets, so blinking and the mouth stop beyond the switch. `rig` finds the face's morphs on the full model's `Face` node as now.
- Until then: the far model also exists as a character file of its own (`lookdev/far/own-<name>.glb`), which is what was measured. A recipe may name it as its base today, for people who are never seen close.

**3. Clips once** (`anim.rs`, `build`; `lookdev.rs`, `rig`; `gait.rs`). Medium.

- Today: a body's clips are its own file's `named_animations`, and the animation graph is built once per file (`Sets` is keyed by `model.file`). Sixty-four files are 64 copies of every clip and 64 graphs.
- Every generated person has the same skeleton: the same bones, parents and rest positions (the generator's `JOINTS`), whatever their sex, age or build, because height and a child's proportions are the recipe's. `clips_compare.py` on two of Cullet's people gives the `idle` clip identical to 0.00°. A locomotion clip differs (`walk`: up to 11° at the feet, loops of 1.00 s and 1.03 s) only because `animate.py` scales a walk's time by the figure's measured height, which includes the hair. The motion is the same.
- The change: let a model take its clips from a shared clip file. `build` loads that file's `Gltf` in place of `model.file`'s and keys `Sets` by the clip file, so everyone shares one set of `AnimationClip`s and one graph. Clips bind to bones by name path (`AnimationTargetId`), which matches across generated people. `rig`'s `clips` flag and `gait::of` (the `.clips.json` beside the file) must read the clip file too. The hips' translation needs no new scaling for generated people, since their rest skeletons are equal.
- How a model names its clip file: by convention (`lookdev/anim/own-clips.glb` for every `own-*` base), or a `clips` entry in the recipe.
- The generator's side is then one bake of the library on a standard figure and files without animations, a small change to `gen_person.sh` when the client is ready. A file without clips falls back to the procedural walk today, so it cannot be done first.

### The client since crowd-1 (2026-11-11)

**What the client does now:**

- **Shared face maps** (`lookdev.rs` `convert`). A face without `<file>.face.png` takes the map its material's extras name (`face_map`). A page's faces are one `Face` material, with the swept shadow edge. A type's own map beside its file (`lookdev/types/<type>.face.png`) works the same way.
- **The far switch** (`lookdev.rs` `far_models`).
  - A character whose file has `Far*` mesh nodes shows them beyond `LIVING_GAME_FAR` metres (default 10, for a 1.75 m person, in proportion to height, as the spring bones' distance is). It shows its full meshes again once it is `LIVING_GAME_FAR_BAND` nearer (default 1.5 m), so a person at the edge doesn't flicker.
  - The choice is made when the scene's meshes appear, before the model is first shown, so the two never draw together.
  - Meshes that join a character later join its lists and take the side it shows: an outfit piece, a style's mesh named `Far*`, a scene rebuilt in place.
  - Hidden meshes draw in no view: no shadow, no outline. Animation and springs run on the one skeleton whichever shows.
  - There is no crossfade (`VisibilityRange`'s dither was not tried).
- **Clips once** (`anim.rs` `clip_file`, `bind`; `characters.rs` `shape`).
  - `own-*` files and anything under `lookdev/types/` take their clips from `lookdev/anim/own-clips.glb` when it exists (`LIVING_GAME_SHARED_CLIPS=0` plays a file's own). `Sets` is keyed by the clip file, so every generated person shares one graph.
  - A file without clips gets no `AnimationPlayer` from Bevy's loader. `bind` adds the player, and on every node below it its name-path target, from the node named as the clip file's scene root (`Armature`). It does this again after a scene rebuild.
  - **The height in `walk`'s timing needs no change in `animate.py`.** Gaits play at a shared phase whose rate is `speed / (stride × metres a cycle)`, so a clip's duration cancels out. Only the metres matter, and the sidecar gives them for the baked figure scaled to 1.75 m. `shape` therefore measures `Character::stride` against the clip file's figure, through `lookdev::figure_height`: the span of the GLB's accessor bounds, `Far*` meshes left out. On three of Cullet's people that gives each person's own cycle metres to three decimals (walk 1.409, 1.420 and 1.398 m, shared against own).
- **Generator side, made for this:**
  - `town.py --lod both` pages both-files: their full atlases on `<town>-lod-<n>` and their far pictures on `<town>-lod-far-<n>` (`share.py pages --which near|far`).
  - `share.py clips` removes a file's own clips and sidecar.
  - The shared clip file is one preset baked with the library: `ONLY=present LOD=near gen_person.sh clips=man`, the `man` figure, 1.837 m. Which figure should be the standard is the generator's call.
  - A `gen_person.sh` switch that bakes no clips is the step still to take; `share.py clips` stands in for it.

**What was measured.**
- **The machine:** the laptop, an Apple M4 Pro (14 cores, 48 GB), with other workers building throughout (load average 15.7 to 21.9).
- **The people:** the same 64 of Cullet's cast as above (`town.py --town living/seeds/cullet.json`: same names, seeds and ages as the dev-box's set). They were baked here with main's `animate.py` and the 30 library entries this machine holds (`ONLY=present`, 29 clips), and put on shared pages. Two sets:
  - *before*: the full files, each with its own clips, drawn by main at `4447b2fb`;
  - *after*: the both-files with their own clips removed, drawn by crowd-1, with the shared clip file.
- **The scene:** the meadow at the default game camera, 1600×900, uncapped, 30 s a run, `LIVING_GAME_PERF=frames,diag`. The runs went empty, before, after, after, before, empty, twice. Evidence: `.local/living/crowd-1/`.

| At the game camera, 1600×900, uncapped, M4 Pro | Empty meadow | 64 of Cullet, before | 64 of Cullet, after |
|---|---|---|---|
| Rounds | 4 | 4 | 4 |
| Frame time, mean: median (least to most) | 8.6 ms (6.45 to 9.49) | 12.3 ms (9.6 to 13.19) | 9.1 ms (7.69 to 14.91) |
| People showing the far model | – | – (no switch) | 64 of 64 |
| Meshes drawn in the camera's view, people only | 18 | 402 | 210 |
| Materials on people in view | 17 | 29 | 20 |
| Triangles in the camera's view, people only | 31k | 2,078k | 388k |
| Animation clips loaded (curves); graphs | 130 (6,890); 1 | 1,986 (105,258); 65 | 159 (8,427); 2 |
| Clip data, on disk | – | 2.47 MiB a person, 158 MiB for 64 | 5.2 MiB once (the shared file, meshes included) |

The two VRoid bases' 65 clips each are part of every run's clip count. The clip rows come from the client's `assets:` line (`perf.rs`). The before set's clip counts were taken with crowd-1 and `LIVING_GAME_SHARED_CLIPS=0`, which loads the files the same way.

**What is firm, and what is not:**

- **Firm: the counts.** Meshes 402 to 210, materials 29 to 20 and triangles 2,078k to 388k: exactly the dev-box's far-model figures, now reached by switching. Clips 1,986 in 65 graphs become 159 in 2. They don't depend on load.
- **Not firm: the frame time.** The after set was faster in 3 of 4 runs measured next to each other (median 9.1 ms against 12.3). The other workers' load moved runs by up to twice.
- **Not measured: the process memory.** On macOS, resident size and `footprint`'s graphics memory moved by gigabytes with the other workers' memory pressure: the empty scene's RSS ran from 1,354 to 2,938 MiB and its graphics memory from 154 to 2,400 MiB. The dev-box's figure of about 15 MiB a person for the clips stands as the RSS estimate.
- **Found on the way.** For 64 people, morph targets are 339 MiB of the 487 MiB of mesh data in the main world (about 5 MiB a person, the face's 15 targets). The face pages are kept CPU-side too: about 500 MiB of image data. Both are candidates for the type format and for dropping main-world copies.

**Foot slide with shared clips.** Three of Cullet's people walked as you on flat ground (`LIVING_GAME_AUTOWALK`, a 0 → 4.5 → 0 m/s ramp over 14 s, about 70 s). Each was measured three ways: main's client, crowd-1 with each file's own clips, and crowd-1 with the shared clips on the stripped both-file. `foot_slide.py --bins 0.5` gives the supporting foot's median slide as a share of the body's speed:

| Person | Height | Walking (0.5–2.5 m/s): main / own clips / shared | Running (2.5–4.5 m/s): main / own / shared |
|---|---|---|---|
| wick-marl (5) | 1.03 m | 0.057 / 0.056 / 0.061 | 0.084 / 0.093 / 0.094 |
| tamsin-hollin | 1.66 m | 0.022 / 0.021 / 0.023 | 0.036 / 0.039 / 0.038 |
| imre-sarro | 1.87 m | 0.024 / 0.022 / 0.023 | 0.034 / 0.030 / 0.036 |

The shared clips are within the spread of the other two arms for all three heights. A child slides about two and a half times as much as an adult, with any of the three, which is a separate matter (the clips are an adult's at a child's proportions).

**Look-dev stills** (`.local/living/crowd-1/stills/`, the asset view). The same four people were shown by main's client and by crowd-1, crowd-1 with the far model forced off, forced on, and by distance.
- **Faces:** paged faces shade with the swept edge where main's shaded them as skin, with a diagonal blotch.
- **The swap:** at the switching distance the far model keeps the silhouette, the proportions and the colours. Fine detail goes: the stripes of a knit, a child's curls, the face's depth. It is visible if you look for it on patterned clothes and invisible on plain ones.

**Not covered:**
- a crowd that walks, or a camera crossing 10 m while it records, beyond the unit test of the band;
- shadows' cost per cascade with the far model;
- the island and Cullet scenes;
- a connected world;
- frame time on a quiet machine;
- the dev-box's GPU.

`.agents/skills/verify-ui/features/crowd.md` is the recipe to check it again.

**Seen in every run, before as after:** a few crowd members' scenes are rebuilt after they are shaped (`scene was rebuilt; its proportions and outfit are lost`, 0 to 6 of 64 a run). crowd-1 rebinds their clips, but their proportions are lost, as before. Fixed in rebuild-keep (below).

### Scenes rebuilt (rebuild-keep, 2026-11-11)

**The cause.** Bevy 0.20 loads a label (`own-x.glb#Scene0`) by force-loading its root (`HandleLoadingMode::Force` in `AssetServer::load_internal`) even when a load of the root itself is under way (bevy#10549). `characters::spawn` asked for both in the same frame: the scene's label for the `WorldAssetRoot`, and the root for the clips (`kept`). So a new file was read twice. The second read replaced the scene asset (`AssetEvent::Modified`), and Bevy respawned every instance already made from the first read, on new bone entities: the shaped skeleton, the outfit and the springs were left on bones that no longer existed. A probe of the asset events showed it on each rebuilt person: the glTF `LoadedWithDependencies` twice, then `Modified` on it and on its scene. In look-dev the line-up's own load of the same files, dropped when the tour switches environment, did it too. The island waits for a scene to load before it spawns a person there, so it does not race.

**The fix.**
- `characters::SceneOf`: a character, an animal (`bodies::spawn_beast`), the look-dev line-up and the asset view ask for the root alone. The scene is the root's own `scenes[0]` once it is in (`place_scenes`), so a file is read once.
- If a scene is spawned again anyway (a changed file, a hot reload), `characters::on_ready` counts each character's spawns (`WorldInstanceReady`). On the second it lets go of what was built on the old bones, hiding the person until fitted again: the fit, the proportions (`Shaped`), the rig, springs, outfit and its pieces, the far model's lists, the clips' player binding, the look's and the feet's bones. Each is then built again by its usual system.
- It sends `characters::Rebuilt`. A type's identity bones belong in `shape`, which runs again; anything else that sets a person's bones once listens to that message.
- `LIVING_GAME_PERF=rebuild=S` spawns every character's scene again S seconds after the cover lifts, through Bevy's own respawn; `nokeep` skips the letting go, to compare.

**What was measured** (the laptop, Cullet's 64 in the meadow at the game camera):
- **Before:** 9 of 13 runs of the 64 lost some people's proportions (1 to 10 people a run).
- **After:** 0 rebuilds and 64 of 64 people shaped, in 6 of 6 runs: 3 with the both-files, 3 with the full files.
- **Forced** (`rebuild=4`, all 65 characters, you as wick-marl, 1.03 m: legs 0.80, head 1.39): with `nokeep` all 65 were left unshaped, and the child became an adult-proportioned figure at its height. With the fix all 65 were fitted, shaped and bound again: wick-marl `1.03 m (×0.607), hips ×0.827, stride 0.53` before and after, and the far switch rebuilt (64 of 65 far, you near).
- **Unit test:** `characters::tests::a_second_spawn_of_a_characters_scene_lets_go_of_what_was_built_on_the_old_one`.
- **Evidence:** `.local/living/rebuild-keep/`.

### Pass 2's measurement (2026-11-11)

Kept as measured, before the changes above. It used `town.py`'s stand-in cast and an earlier build of the game.

- **What was run.** 64 generated people from `town.py`'s stand-in town, each a different file, in the game's own crowd (`LIVING_GAME_CROWD`) in the open `meadow` environment at the default game camera (22 m, 28° down), every one playing `idle`. Headless, uncapped, 1600×900, `LIVING_GAME_PERF=frames,diag`. Beside it: the empty scene, 64 of the VRoid bases the game used before, and 64 of ours that are all one file.
- **The machine.** The dev-box, AMD Radeon 8060S integrated graphics, building for other workers throughout (load average 10 to 72 on 32 threads over the rounds). The same run varied by a factor of two between rounds, so each frame time is the median of 4 interleaved rounds with the least and the most. The counts and the process memory do not depend on load.
- **How the people get into the crowd.** The crowd draws its bases from `recipes.json`'s `bases`. For the run the tool writes a temporary `recipes.json` whose list puts a different person at each index the crowd's seeded draws land on, and restores the file afterwards. The game is not changed.

| At the game camera, 1600×900, uncapped | Empty meadow (you alone) | 64 VRoid bases (2 files) | 64 of ours, all one file | 64 of ours, 64 files |
|---|---|---|---|---|
| Different character files | 1 | 2 | 2 | 65 |
| Frame time, mean: median of 4 rounds (least to most) | 8.13 ms (5.32 to 13.52) | 23.34 ms (13.01 to 38.97) | 18.86 ms (8.32 to 23.55) | 27.09 ms (12.79 to 44.77) |
| GPU time of the render passes: median (least to most) | 1.8 ms (1.13 to 3.74) | 3.76 ms (2.31 to 7.64) | 2.74 ms (2.02 to 6.91) | 5.38 ms (4.07 to 12.49) |
| Load average while measuring: median (least to most) | 27.4 (9.5 to 31.8) | 25.9 (10.7 to 54.5) | 25.0 (11.8 to 70.7) | 27.8 (13.2 to 72.4) |
| Triangles in the camera's view, people only | 31k | 1,846k | 2,210k | 2,085k |
| Meshes drawn in the camera's view, people only | 18 | 1,136 | 850 | 816 |
| Materials on people in view | 17 | 33 | 23 | 212 |
| Each shadow cascade: meshes / triangles | 228 / 60k | 228 / 60k | 228 / 60k | 248 / 123k |
| Spring bones: joints simulated | 65 | 3,738 | 79 | 256 |
| Process memory, peak resident: median (least to most) | 2455 MiB (2142 to 2840) | 2387 MiB (2039 to 2585) | 2346 MiB (1858 to 2451) | 5416 MiB (5211 to 5612) |
| Graphics memory of the process: median (least to most) | 3714 MiB (2919 to 4204) | 3274 MiB (2485 to 3286) | 3759 MiB (2686 to 4574) | 4970 MiB (4357 to 6173) |

What it says:

- **Frame time.** 64 different files cost more than 64 of one file in every round (medians 27.09 ms against 18.86 ms), and more than the VRoid crowd in three rounds of four; the two crowds' ranges overlap (12.79 to 44.77 ms ours, 13.01 to 38.97 ms VRoid). In the quietest round (load average about 10 to 13) the figures were: empty 5.8 ms, VRoid 13.0 ms, ours from one file 8.6 ms, ours from 64 files 19.2 ms. This does not establish the 60 FPS target either way: that needs a quiet machine, Cullet's buildings and the town running.
- **Triangles are not the difference:** 2.1 million in view for ours, 1.8 million for the VRoid crowd, and fewer meshes (816 against 1,136).
- **Materials are:** 212 on 64 different people, 23 when they are one file, 33 for the VRoid crowd. Each person's face, eye and hair materials are their own, because each file carries its own textures. `living/game/src/perf.rs` notes that each distinct material and mesh is a batch set per view and pass, and that this per-batch work usually limits the frame.
- **Memory is:** about 49 MiB of process memory and 19 MiB of graphics memory for each different person (5,416 MiB peak with 64 files against 2,346 MiB with one). Not split into textures, meshes, morph targets and clips.
- **Spring bones are small:** 256 hair joints simulated for ours, 3,738 for the VRoid crowd.

What pass 2 proposed, in order of gain, and what became of it:

1. **Shared materials.** Done in pass 3, as above.
2. **A far model** beyond about 10 m. Made in pass 3; the client does not switch to it yet.
3. **Fewer meshes a person.** Done in pass 3: six.
4. **Memory:** clips stored once need the client; the split of the memory a person costs was not made, since the plan after pass 3 moves identity onto bones over a few shared meshes, which removes most of it at the source.


## What still separates ours from the reference

**After the hair step**, the list below stands, with its first item split: the wash and the half-transparent look are the client's rim light and film gradient ([hair styles](#hair-styles)), and the hair's finish (a blocky fringe, ragged ends, gaps at the temple) is ours and was not changed in this step, which made hair shared, not better.

**After pass 3's fifth step (lines)**, judged on the board with the reference beside ours, ordered by how much it shows:

1. **Hair.** Close up it looks washed out and half transparent in every shot, and its finish is as it was: a blocky fringe, ragged ends, gaps at the temple on the new head. Next.
2. **The eyes' drawing:** thin lash lines and a plainer iris. Step 6.
3. **The jaw's line does not hold at a distance.** Close up the shell line marks the jaw, the chin and the ears, lightly; at the game camera it is gone on the near head and a single darker pixel row on the far one, where the reference's whole figure is carried by its outline. A line in screen pixels is the client's ([lines](#lines-where-the-form-turns)).
4. **Lips and blush are painted into the skin.** Step 6.
5. **Clothes and silhouette, hands** (unchanged).

**After pass 3's fourth step (designed shadows)**, judged on the board's `20261112-1fa6fc0f-…` versions with the reference beside ours, ordered by how much it shows:

1. **The eyes' drawing:** thin lash lines and a plainer iris against the reference's heavy upper lash and two-tone iris. Step 6.
2. **How the hair is finished** (unchanged), and how it sits on the new head at the temple.
3. **No lines where the form turns** (jaw, chin, mouth). Step 5.
4. **The nose's wedge is still a shape the reference does not draw.** After step 4b the face is flat until about 55° and nothing is lit inside the shade, which is near the reference; the small wedge beside the nose from 56° is ours. Its onset and the others are single numbers in `face_shadow.py`.
5. **Lips and blush are painted into the skin.** Step 6.
6. **Clothes and silhouette, hands** (unchanged).

What step 4 closed: the straight split down the middle of the face and the band along the jaw.

**After pass 3's third step (the cage head)**, judged on the board's `20261111-26c98cc2-…` versions with the reference beside ours, ordered by how much it shows:

1. **The shading across the face.** Ours splits into light and shade along a straight line down the middle of the face, and again along the jaw. The reference's shade is a drawn shape: under the fringe, down the side of the cheek, never across the nose. The form under it is now close; the normals and the shadow map are still pass 2's. This is step 4.
2. **The eyes' drawing.** The eye now sits behind the lid as the reference's does and no white shows at the corners. But the reference's upper lash line is a heavy dark shape and its iris has two tones and a large light; ours has thin lines and a plainer, smaller-looking iris. Paint, step 6.
3. **How the hair is finished** (unchanged): a blocky fringe, ragged ends, and a strand that can stand out at the nape in a fixed shot.
4. **No lines where the form turns.** The reference draws the jaw, the chin and the mouth's corners with a line; ours has only the silhouette's. Step 5.
5. **The lower face still reads rounder.** The sections are within 0.013 H of the reference's on its own type, but without the jaw's line and shade the chin does not read as pointed.
6. **Lips and blush are painted into the skin** and do not survive a shared texture's recolour ([what the client needs for types](#what-the-client-needs-for-types)).
7. **Clothes and silhouette, hands** (unchanged).

What the cage head closed, from the lists below: the head's form and structure (the owner's "depth … and how it is structured internally"), the eyes' corners, the nose from the front as geometry, and the line under the jaw between the neck's and the face's shading.

New weak points of step 3:

- **Children's types are close to the adult women's** at one scale (the board's `children-beside-adults`): lower, larger eyes and a shorter chin, on much the same skull. A child reads as a child mostly by the body and the head's size on it.
- **Hair sits less well on the new head at the temple.** On the `man` preset, skin shows between the locks in front of and above the ear from the side, where step 1's did not: the styles were tuned on pass 2's head.
- **The crown is coarse:** the cage's top rows have edges up to 48 mm, which matters for a bald or thin-haired head seen from above.
- **The ears are laid on the cage, not part of it** (`head_mesh.py`'s ear): the root meets the skin in doubled edges.

**After pass 2**, judged on the pass-2 page and the asset board, where every close-up has the reference beside it. Ordered by how much it shows.

| | After pass 1 | After pass 2 |
|---|---|---|
| 1 | **Hair:** clumps on a cap, the scalp showing, no strands, no highlight | **How the hair is finished.** The construction is now the reference's, and the gap is in the surface. The reference's locks are fewer and cleaner, with crisp cut ends, and its highlight is a broad band broken into teeth. Ours shows more lock edges, its ends are ragged, the game's ring on it is a thin even stripe, and long hair lies on the shoulders in slabs. Men's short styles have no counterpart in the reference and are the roughest. |
| 2 | **Eyes:** half the reference's height, high on the head, a small iris | **The face's paint.** The reference's skin is almost flat colour with a soft blush, a dot of a nose and a tiny mouth. Ours still paints a nose shadow, nostrils and a full mouth, and the lower lid's line is harder. Its eyes are still lower on a wider head than ours at any style number. |
| 3 | **Proportions:** a long lower face, a narrow head, a modelled nose | **Clothes and silhouette.** The reference wears fitted, folded cloth with a skirt and a bow that swing. Ours wears tubes: smooth coats, smocks and boots with painted shade. Untouched since the spike. |
| 4 | **Brows and lashes:** flat shapes of one colour | **Depth in the eye.** Close up the reference's iris has two colours, a sparkle and blended lash clumps. Ours has the same parts drawn crisper and plainer, and its lashes are separate hairs. |
| 5 | **Clothes and silhouette** | **Hands**, and how cloth, hair and body meet: hair passes through a raised collar, and the neck and face shade differently under the jaw. |

What pass 2 did not change, from pass 1's list:

- **The nose from the front** is a shade and two nostril marks. Large noses read only in profile.
- **Ears** are simple rings.
- **Plain clean-shaven men are the closest to each other,** though less so than in pass 1 now that six short styles, a parting and a fringe vary; beards, age and skin still carry much of the men's variety.
- **Children wear adult garments** scaled by the recipe, and build is a light touch (girth, a belly, a chest).
- **Neck and face shade differently**, so a line shows under the jaw, as on VRoid files.

New weak points of pass 2:

- **Short hair from behind and at the temples.** The nape ends in a ragged line of points, and skin can show in front of the ear.
- **Long hair on the shoulders** lies in broad flat slabs with visible cut ends, and passes through a coat's raised collar.
- **The highlight ring** is the game's, drawn from the normals. On our smooth mass of hair it is a thin even stripe across the fringe; the reference's band is broader and more broken.
- **A wide lock can cross a cheek** in the three-quarter view on some seeds (the side locks of `long` and `bob`).
- **The eyes' corners.** The white lies on a ball, so at the outer corner it sits a few millimetres behind the lid; from a low side angle a dark gap can show.
- **The look is not driven by the game yet.** The bones, weights and the file's look-at block are there, and `--look` shows it; the client has to turn the two bones.
- **Stray strands in some fixed shots.** The asset view photographs 0.6 s after posing a figure, and a spring chain can still be settling; the reference shows the same. In play the hair hangs and swings.
- **Grey goes lock by lock,** which can read as patches at middle values on fair hair.
- **Greying brows, beards and hair** are still three separate colours.

## What later passes need

The order was set by the dev-box coordinator on 2026-11-11, after the owner's verdict on pass 2 ("we are still lacking … depth and probably in the shape, how it is structured internally") and the two research reports. Pass 2's own list (hair finish, then the face's paint) is put back behind the head's form.

**The decision: identity in bones, on a few shared meshes for each type.** For each sex and age band there are about three designed face types, with body types tied to them. A type is a complete set of skull and landmark values, built once by a cage script with its own designed normals, shadow map and line data. A person is a type plus bounded bone values; families share a type and part of their values. Meshes, textures and clips are then shared at the source, and the far face is the same rig on a lower-detail type mesh.

1. **Crowd cost.** Done in pass 3's first step ([crowd cost](#crowd-cost)).
2. **Types and rig, as data and a page before any mesh.** Done in pass 3's second step ([types and rig](#types-and-rig)): which bones, their ranges, what a type fixes and a person varies, three face types for each band, and the client's format. Left for the cage: trimming the value ranges that fail in pairs, the age direction inside a band, the belly and chest bones, and how details a person has (beard, lines, freckles) are carried.
3. **The cage head for each type, with the rig in it.** Done in pass 3's third step ([the cage head](#the-cage-head)): 21 types from one script, accepted against the reference's measured sections, with its eye depths, outline normals, the trimmed ranges and the type files. Left from it: lips and blush out of the skin texture (with step 6's paint), the style files for hair and outfits, the age direction inside a band, and a second look at bindless colours with the laptop.
4. **Designed shadows.** Done in pass 3's fourth step ([designed shadows](#designed-shadows)): a planar proxy's normals and a threshold map from script-drawn shapes at 16 light angles, one map a type, in the client's existing format. Left from it: the far head still shades by its own round normals, and the shapes' onset angles wait on the owner's eye.
5. **Lines where the form turns.** Done in pass 3's fifth step ([lines](#lines-where-the-form-turns)): shell lines at the jaw, chin, ears and mouth in the files, per-vertex outline width in the files, the client's need written out, and the data a post-process inner line would take.
6. **Hair and outfits as shared style files.** Done ([hair styles](#hair-styles), [outfit pieces](#outfit-pieces)): a whole person composes from a type's file, a hair style and outfit pieces. Overlays, the apron, eye colour and bellies followed ([overlay styles](#overlay-styles)). Left: a far model's overlays; a strong chest.
7. **Hair finish.** Done ([hair finish and cuts](#hair-finish-and-cuts)): the fringe, the ends, the temple; three cuts of every style; far beards.
8. **The eyes' drawing, lips and blush** (the face's paint; lips and blush out of the skin texture).
9. **Later:** the game turning the eyes, clothes that swing, women's silhouettes, children's own garments, hands.

Each pass page sets two references beside ours: the VRoid control, and a still from Blue Protocol's published character material (one of the owner's named art references), for comparison only. The stills are kept outside the repository, in `~/archive/asset-board/references/blue-protocol/`, with their sources.
