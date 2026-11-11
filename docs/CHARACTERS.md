# Characters: the generator

The game's people are made by our own tool: a set of parameters goes in, a rigged, painted, animated character file comes out. This replaces VRoid Studio bases (decision 2 of [the small city](SMALL_CITY.md)). The owner's bar is VRoid's quality close up, from a parameterized tool of our own.

**Status (2026-11-11, branch `char-4`, pass 3 of the track: step 1, crowd cost, and step 2, types and rig as data):**

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
- **Not yet at the bar:** see [what still separates ours from the reference](#what-still-separates-ours-from-the-reference). In short: the head's form and structure, how the hair is finished, the face's painted softness, clothes and silhouette, hands.
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

Pass 3's second step (2026-11-11, branch `char-4`): the plan for how a person is made from here on, as data and diagrams, before any mesh is rebuilt. Nothing in this section is in the generated files yet; pass 2's baked people remain what the tools make until the cage head of step 3.

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
| `J_Id_Face` | `J_Bip_C_Head` | outline | `face_length` | scale z | ×0.92 to ×1.1 | pass 2's `face_length`: everything below the eyes |
|  |  |  | `face_width` | scale x | ×0.94 to ×1.07 | pass 2's `face_width` |
| `J_Id_Corner_L`, `J_Id_Corner_R` | `J_Id_Face` | outline | `front_breadth` | move x | -16 to 16 ‰H | new: how broad the front planes are |
| `J_Id_Zygoma_L`, `J_Id_Zygoma_R` | `J_Id_Face` | outline | `cheekbones` | move x | -12 to 16 ‰H | pass 2's `cheekbones` |
|  |  |  | `cheekbone_height` | move z | -12 to 12 ‰H | new |
| `J_Id_Cheek_L`, `J_Id_Cheek_R` | `J_Id_Face` | outline | `cheeks` | move y | -12 to 20 ‰H | pass 2's `cheeks`: hollow to full; this bone is turned at rest to face out of the cheek, so its forward is the surface's normal |
| `J_Id_Jaw` | `J_Id_Face` | outline | `jaw_width` | scale x | ×0.88 to ×1.14 | pass 2's `jaw_width` |
|  |  |  | `jaw_angle` | turn x | -4 to 5 ° | new: a steeper or flatter jaw line |
| `J_Id_Gonion_L`, `J_Id_Gonion_R` | `J_Id_Jaw` | outline | `jaw_square` | move x | -10 to 14 ‰H | pass 2's `jaw_square`: tapered to square |
| `J_Id_Chin` | `J_Id_Jaw` | outline | `chin_length` | move z | -28 to 20 ‰H | pass 2's `chin_length` (down is longer) |
|  |  |  | `chin_width` | scale x | ×0.7 to ×1.4 | pass 2's `chin_width`: pointed to broad |
|  |  |  | `chin_forward` | move y | -16 to 20 ‰H | pass 2's `chin_forward` |
| `J_Id_Orbit_L`, `J_Id_Orbit_R` | `J_Id_Face` | eyes | `eye_spacing` | move x | -12 to 14 ‰H | pass 2's `eye_spacing` |
|  |  |  | `eye_height` | move z | -14 to 14 ‰H | pass 2's `eye_height` |
|  |  |  | `socket_depth` | move y | -10 to 8 ‰H | new: the eye set deeper or shallower |
|  |  |  | `eye_size` | scale xyz | ×0.88 to ×1.13 | pass 2's `eye_size` |
|  |  |  | `eye_open` | scale z | ×0.82 to ×1.18 | pass 2's `eye_open` |
|  |  |  | `eye_tilt` | turn y | -6 to 7 ° | pass 2's `eye_tilt`: outer corners down to up |
| `J_Adj_L_FaceEye`, `J_Adj_R_FaceEye` | `J_Id_Orbit_L` | eyes | `iris_size` | scale xyz | ×0.9 to ×1.1 | pass 2's `iris_size` |
| `J_Id_Brow_L`, `J_Id_Brow_R` | `J_Id_Face` | brows | `brow_height` | move z | -12 to 16 ‰H | pass 2's `brow_height` |
|  |  |  | `brow_tilt` | turn y | -8 to 8 ° | pass 2's `brow_tilt` |
|  |  |  | `brow_thickness` | scale z | ×0.7 to ×1.4 | pass 2's `brow_thickness` |
|  |  |  | `brow_length` | scale x | ×0.9 to ×1.12 | pass 2's `brow_length` |
| `J_Id_Nose` | `J_Id_Face` | nose | `nose_length` | scale z | ×0.85 to ×1.2 | pass 2's `nose_length` |
|  |  |  | `nose_width` | scale x | ×0.8 to ×1.25 | pass 2's `nose_width` |
|  |  |  | `nose_bridge` | scale y | ×0.8 to ×1.25 | pass 2's `nose_bridge`: how far the nose stands out |
| `J_Id_NoseTip` | `J_Id_Nose` | nose | `nose_tip` | move z | -10 to 12 ‰H | pass 2's `nose_tip`: turned down to turned up |
| `J_Id_Mouth` | `J_Id_Face` | mouth | `mouth_height` | move z | -12 to 12 ‰H | pass 2's `mouth_height` (down is lower) |
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

For the laptop coordinator. Nothing of this is built yet; the type files arrive with step 3.

**A person becomes a recipe line**, with a type in place of a base file:

```json
{
  "name": "tamsin-hollin",
  "type": "adult-f-a",
  "height": 1.62,
  "proportions": { "head": 1.0, "shoulders": 0.895, "build": 0.973, "hands": 0.88, "feet": 0.9 },
  "identity": {"cranium_width": -0.384, "cranium_height": -0.31, "brow_ridge": 0.271, "face_length": -0.499, "jaw_width": -0.292, "jaw_square": -0.518, "chin_length": -0.948, "chin_forward": -0.504, "socket_depth": 0.576, "eye_size": 0.387, "eye_open": -0.258, "iris_size": 0.257, "nose_length": -0.273, "mouth_height": -0.29, "mouth_width": -0.648},
  "colors": { "skin": "#e6b89c", "hair": "#4a2a1a", "eyes": "#536f54", "outfit": { "coat": "#5d7f9a", "jersey": "#d8d2bd" } },
  "styles": { "hair": "bob", "beard": "none", "outfit": { "coat": "smock", "headwear": "none" }, "details": { "lines": 0, "freckles": 0, "stubble": 0 } }
}
```

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

Judged on the pass-2 page and the asset board, where every close-up has the reference beside it. Ordered by how much it shows.

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
3. **The cage head for each type, with the rig in it,** accepted against the reference's measured sections ([CHARACTER_REFERENCE.md](CHARACTER_REFERENCE.md)), with its eye depths, and smoothed outline normals written in the same pass.
4. **Designed shadows:** a planar proxy's normals, and a shadow map from script-drawn shapes at several light angles (the cheek triangle, the side of the nose, the eye socket, the underside of the jaw).
5. **Lines where the form turns:** shell lines at the jaw, chin, mouth and ears; per-vertex line width needs a client outline shader, to be written up for the laptop.
6. **Later:** hair finish and the face's paint (pass 2's items 1 and 2), the game turning the eyes, clothes as slots with cloth that swings, women's silhouettes, children's own garments, hands.

Each pass page sets two references beside ours: the VRoid control, and a still from Blue Protocol's published character material (one of the owner's named art references), for comparison only. The stills are kept outside the repository, in `~/archive/asset-board/references/blue-protocol/`, with their sources.
