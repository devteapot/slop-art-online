# Characters: the generator

The game's people are made by our own tool: a set of parameters goes in, a rigged, painted, animated character file comes out. This replaces VRoid Studio bases (decision 2 of [the small city](SMALL_CITY.md)). The owner's bar is VRoid's quality close up, from a parameterized tool of our own.

**Status (2026-11-11, branch `char-3`, pass 2 of the track):**

- **The bar is the reference character:** the VRoid model the game has used so far (`lookdev/vroid-Sendagaya_Shino.glb`; the asset board's control `vroid=recipe:shino`), close up included. The owner accepted pass 1 as the base and said of it: "a step up … but still far away from the reference model we have been using so far. That is kind of what we want to get to".
- **Pass 1 (`char-2`):** faces and the parameter model. A seed or a parameter file gives a repeatable person of any sex and age from 1 to about 80, with real eye openings, a mouth that opens, 15 expressions under VRoid's names, stubble and six beard styles, age lines and freckles. One command makes a household or a whole town and its check page.
- **Pass 2 (`char-3`):**
  - hair built the way the reference builds it: a cap and layers of broad locks with a strand texture, fifteen styles from eight parameters, long hair on spring bones;
  - every face drawn toward the reference by one style number;
  - brows and lashes from strands;
  - the iris as a layer of its own on eye bones, so eyes can look round;
  - a tool that measures what a crowd of generated people costs in the game.
- **Not yet at the bar:** see [what still separates ours from the reference](#what-still-separates-ours-from-the-reference). In short: how the hair is finished, the face's painted softness, clothes and silhouette, hands.
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

# The eyes turned in the file, to photograph a look (degrees of the eyes' bones; about 6 is fully aside).
blender -b -P living/tools/blender/person.py -- --variant woman --look 6,0 --out x.glb

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

`just living-town .local/town` runs `town.py`; `just living-people` runs `gen_person.sh`. A pass's own report page is written by `living/tools/characters/report.py` from the board's media and a notes file.

`gen_person.sh` needs Blender and, for clips, the Kimodo library's takes (`KIMODO_DIR`, default `.local/kimodo/outputs/library`); it bakes the whole library unless `ONLY` names clips. `ONLY=present` bakes the entries whose takes are all there, for a machine whose copy of the library is behind `clips.json` (on 2026-11-11 the dev-box had 30 of 67: the takes of the re-made town motions and of the new locomotion clips had not reached it). The photographs need the game's release build; `view_assets.sh` honours a private `CARGO_TARGET_DIR`. A person takes about 6 s to generate; adding two clips takes about 6 s more and 30 clips about 15 s. 64 people with `idle` and `walk` and their photographs took 5 minutes with six jobs on a loaded dev-box (pass 2, 2026-11-11; hair adds under a second a person).

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
| `hair.colour` | `black`, `dark_brown`, `brown`, `chestnut`, `auburn`, `sandy`, `blond`, `grey`, `white`, or `[r, g, b]` | by skin tone; often the family's |
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

`gen_person.sh` writes `lookdev/own-<name>.glb` and `lookdev/anim/own-<name>.glb`. A recipe in `living/game/assets/characters/recipes.json` names the file as its `base` with the height and proportions from `<name>.params.json`. `python3 living/tools/blender/person_params.py --variant man --recipe man` prints that line. The presets' recipes are `cullet-man`, `cullet-woman`, `cullet-elder`, `cullet-lad`, `cullet-boy`, `cullet-girl` and `cullet-heavy`. Height and a child's proportions are the recipe's; everything else is in the file. A recipe's `colors` are for the VRoid bases: on a generated person the skin slot would tint the painted beard and lips with it, so colour belongs in the parameters.

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

- **The floor guard is in `animate.py`** (`floor_guard`, from the laptop's `floor-guard` branch). It runs on every Kimodo and overlay clip, so there is nothing to turn on: a foot whose heel, ball or toe tip is more than 1 cm under the floor is lifted, and a clip that never goes under bakes exactly as before. It guards feet. A hand under the floor is not lifted; the new takes below were picked so hands stay above it.
- **`work`, `play` and the three ground motions were taken again** (the clip lab; `clips.json` names the new takes), and 32 locomotion clips were added.
- **Pass 2's people were baked with that `animate.py`,** and so was the control. On the dev-box the library held the takes of 30 of the 67 entries; the re-made motions and the new locomotion clips were not there to bake, so they are not judged on pass 2's people yet (`ONLY=present`).
- **Hair on spring bones** changes nothing for `animate.py`: the chains hang under the head and the clips do not key them.

## What was learnt from VRoid

The controls `lookdev/vroid-Sendagaya_Shino.glb` and `vroid-Vivi.glb` were taken apart to see how the look is made. Nothing of theirs is used ([third-party record](../living/tools/blender/THIRD_PARTY.md)).

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

Measured in pass 2 (2026-11-11), before Cullet is built with these people, with `living/tools/characters/crowd.py`.

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

What level of detail and atlasing Cullet needs, in order of gain:

1. **Shared materials.** Ship the strand texture once (it is the same file for everyone) or have the loader join identical images: 64 hair materials become one. Put the town's faces on shared pages: 64 atlases at 512² fit one 4096² page or a texture array, so the face, eye and hair materials of everyone not close to the camera become three. `town.py` can build the page and rewrite the UVs; the face shadow maps go the same way.
2. **A far model** beyond about 10 m, written by the generator beside the full one: about 6,000 triangles in place of 29,000 to 37,000 (the face 10,000 to about 1,200, hands 4,500 to 600, the hair's cap 2,700 to 700, locks at half their segments).
3. **Fewer meshes a person:** 12.6 now; 6 when joined by shading kind (cloth, skin, face lines, face, eyes, hair). The clothes' separate materials exist for the VRoid recipe colour slots, which generated people do not use.
4. **Memory:** the full 1024² atlas only near the camera; clips stored once and shared (every file carries the same clips on the same skeleton); and a split of the 49 MiB a person before choosing more.

Not established: 64 people walking Cullet with its buildings, lamps and weather, a player moving and minds running.

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

- **Pass 3, in order:**
  1. Finish the hair's surface: fewer, cleaner locks at the fringe with cut ends drawn as edges; the highlight band as the reference has it (per-lock teeth, in the shading or painted into the strand texture's column); a neat nape; long hair that parts round the shoulders and collar.
  2. The face's paint toward the reference: nose and mouth as marks, a softer blush, the lower lid's line; and the skull's form (a wider, rounder cranium, the eyes lower still), which a style number cannot reach.
  3. Level of detail and shared materials for crowds ([crowd cost](#crowd-cost)), before 64 of them walk Cullet.
  4. The game turning the eyes (two bones, a few degrees) and looking at whoever speaks.
- **After that:** clothes as slots chosen by parameter, with cloth that swings; women's silhouettes; children's own garments; hands.
- `head_form.py`'s beard coverage could drive a beard of strands, as the brows now are.
