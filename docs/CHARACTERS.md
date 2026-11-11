# Characters: the generator

The game's people are made by our own tool: a set of parameters goes in, a rigged, painted, animated character file comes out. This replaces VRoid Studio bases (decision 2 of [the small city](SMALL_CITY.md)). The owner's bar is VRoid's quality close up, from a parameterized tool of our own.

**Status (2026-11-11, branch `char-2`, pass 1 of the track):**

- **Current:** faces and the parameter model. A seed or a parameter file gives a repeatable person of any sex and age from 1 to about 80. The face has real eye openings, painted eyes, lashes, brows, a mouth that opens, 15 expressions under VRoid's names, stubble and six beard styles, age lines and freckles. One command makes a household or a whole town and its check page.
- **Not yet at the bar:** hair (still the spike's clumps), women's silhouettes and outfits, cloth, hands, and anything that swings. Those are later passes; see [what is weak](#what-is-weak-and-what-later-passes-need).
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

# The comparison page beside the VRoid control (the same shots and clips for each).
living/tools/characters/capture.sh cullet-man ours .local/cap all
living/tools/characters/capture.sh cullet-man ours .local/cap motions   # whole clips, to judge a motion (MOTIONS=…)

# Measure baked clips on a character's own mesh: lowest point against the floor, how busy the hands
# are, how much it moves, hops, foot travel.
blender -b -P living/tools/blender/clip_check.py -- --in living/game/assets/lookdev/anim/own-man.glb --clips gather,work
python3 living/tools/characters/media.py .local/cap .local/page .local/town .local/sheets
python3 living/tools/characters/page.py .local/page
```

`gen_person.sh` needs Blender and, for clips, the Kimodo library's takes (`KIMODO_DIR`, default `.local/kimodo/outputs/library`); it bakes the whole library unless `ONLY` names clips. The photographs need the game's release build; `view_assets.sh` honours a private `CARGO_TARGET_DIR`. A person takes about 6 s to generate; adding two clips takes about 6 s more and the whole library (34 clips) about a minute. 64 people with `idle` and `walk` and their photographs took under 4 minutes on eight cores (dev-box, 2026-11-11).

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
  "hair": { "style": "bob", "colour": "auburn", "grey": 0.0 },
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
| `hair.style` | `tousled`, `short`, `sides`, `bob`, `bob_parted`, `kerchief` | by sex and age |
| `hair.colour` | `black`, `dark_brown`, `brown`, `chestnut`, `auburn`, `sandy`, `blond`, `grey`, `white`, or `[r, g, b]` | by skin tone; often the family's |
| `hair.grey` | 0 to 1 | rises from about 36 |
| `hair.length` | metres a bob hangs below the hairline | 0.05 to 0.11 |
| `hair.recede` | 0 to 1 (men's front hairline) | rises with age |
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
| The head's mesh | `head_mesh.py` | A cube-sphere projected onto the form, denser from the brows to the lip. The skin round each eye is cut away and stitched to a clean ring on the lids, with a rim turned inward. A bowl behind each opening carries the painted eye. The skin is slit along the mouth; the lower edge drops with the jaw and shows teeth, the dark and the tongue. Lashes, lid lines and brows are vector shapes 1 mm off the skin. Ears are lofted rings. |
| Expressions | `head_mesh.py` | The whole face is built again for each expression's state (lids, jaw, mouth corners, brows); the difference is the morph target. |
| The face's texture | `face_paint.py` | One 1024² atlas a person: the whole head's skin, the two eyes, a swatch for the ears. Each texel knows where on the head it lies, so paint follows the form. Painted: tone, blush, shade round eyes, nose and lip, lips, nostrils, the lids' edge, stubble, beards as fine strokes, age lines, freckles; each eye as white, lid shadow, iris with dark rim, gradient, lit crescent and rays, pupil, two highlights. |
| Beards | `head_form.py`, both above | A beard is the skin itself standing off the face (2 to 7 mm, a full one hanging below the chin) with its hairs painted, so its edge is a painted edge, not a mesh edge. |
| Body, clothes, hair, hands | `person.py` | As in the spike: lofted cages with written weights, garments as offsets of the body's form, vertex colours with painted shade. `build.weight` sets the torso's and limbs' girth and a belly; `build.muscle` the chest, shoulders and limbs. |
| Export | `person.py` | One GLB under VRoid's conventions: `J_Bip_*` bones, material name tags, `Fcl_…` morph names, a VRM 0.x block. `animate.py`, `merge_primitives.py`, `face_normals.py` and the game take it unchanged. |

**Expressions.** The game drives `Fcl_EYE_Close` and `Fcl_MTH_A`. The file also carries `Fcl_EYE_Close_L`, `Fcl_EYE_Close_R`, `Fcl_EYE_Joy`, `Fcl_MTH_I`, `Fcl_MTH_U`, `Fcl_MTH_E`, `Fcl_MTH_O`, `Fcl_MTH_Fun`, `Fcl_MTH_Sorrow`, `Fcl_BRW_Angry`, `Fcl_BRW_Sorrow`, `Fcl_BRW_Surprised` and `Fcl_BRW_Fun`, and VRM expression groups (`a` `i` `u` `e` `o`, `blink`, `joy`, `fun`, `angry`, `sorrow`). `person.py --expression Fcl_MTH_Fun=1` writes a file that starts with an expression on, to look at it.

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

The fix proposed for `animate.py`, not made in pass 1: a floor guard after the legs are solved, per character. Hold each ankle and wrist at or above a clearance over the floor (about 5 cm and 3 cm), by raising the leg's target, a two-bone solve for the arm, and lifting the hips where a limb cannot reach. The same guard on the ball of the foot stops the toe dips.

## What was learnt from VRoid

The controls `lookdev/vroid-Sendagaya_Shino.glb` and `vroid-Vivi.glb` were taken apart to see how the look is made. Nothing of theirs is used ([third-party record](../living/tools/blender/THIRD_PARTY.md)).

| VRoid (Shino) | What it does | Ours |
|---|---|---|
| The face is a mask of 1,342 triangles; the skin texture is nearly flat colour with a blush, a nose shadow and a lip tint | Detail is painted, not modelled | The same idea: a smooth form and a painted atlas |
| Real eye openings; the white is a bowl 3 to 25 mm behind the lids, the iris a disc in front of it, the highlight a third layer | The lids pass in front of the eye, so it reads as set in the head from any side | Real openings with a rim; one bowl carries white, iris and highlights as paint. Not separate layers yet, so the eyes cannot look round. |
| Iris texture: a tall ellipse, dark rim, dark upper half, a bright warm crescent below, a blue rim light above | The eye looks lit and deep | Round iris, dark rim, shaded top, lit crescent, rays, pupil, two highlights |
| Lash line, lashes and brows are separate cards with alpha-blended textures, standing off the skin | Soft drawn edges; they move with expressions | Vector shapes with vertex colours: crisp at any distance, no blending or sorting, less texture in them |
| Mouth: a real slit with teeth and tongue inside | Speech shapes show an inside | The same |
| 41 morph targets `Fcl_ALL_*`, `Fcl_BRW_*`, `Fcl_EYE_*`, `Fcl_MTH_*` | Expressions and visemes | 15, built from five controls (each lid, a joyful close, jaw, mouth width, corners, brow ends) |
| Face normals come sculpted; the game flattens them and shades from a map (`face_normals.py`) | A clean shadow edge that sweeps the face | Unchanged; our UVs wrap the whole head, so faces across the seam at the back have their own vertices |
| 30 textures, 10.7 MiB a character | | 1 texture, 0.1 to 0.3 MiB |

## What is weak, and what later passes need

- **Hair** is the spike's cap and clumps. It is the weakest part of every picture now, and it hides the head's outline. It also casts hard shadows on the cheeks.
- **Eyes cannot move.** The iris is painted on the bowl. Separate iris and highlight layers (as VRoid) would allow look-at.
- **Lashes and brows are flat shapes.** No strands inside them. Brows are one colour.
- **The nose from the front** is a shade and two nostril marks. Large noses read only in profile.
- **Ears** are simple rings.
- **Plain clean-shaven men are the closest to each other.** With the same hair they need a second look; beards, age and skin carry much of the men's variety.
- **Children wear adult garments** scaled by the recipe, and build is a light touch (girth, a belly, a chest).
- **Neck and face shade differently**, so a line shows under the jaw, as on VRoid files.
- **Cost is not measured.** A person is about 34,000 triangles (the head 9,700), one 1024² texture, 11 materials, 5.9 MiB with the library's 34 clips. Each person's face and eye materials are their own, so 64 people add 128 materials. Level of detail and crowd frame cost are later passes.
- **Notes for later passes.** Outfit pieces should become slots chosen by parameter, as hair styles are. Children wear adult garments scaled by the recipe. `head_form.py`'s beard coverage could drive a beard of real strands. The atlas has room: the eyes' strip is 448×192 a eye and could hold separate iris layers.
