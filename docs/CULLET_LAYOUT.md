# Cullet's layout

Two passes on the plan of [the small city](SMALL_CITY.md): pass 1 below, [pass 2](#pass-2-2026-11-11) after it.

## Pass 1 (2026-11-11)

Started 2026-11-11 (branch `layout-1`, Claude Fable 5.2). A design-and-authoring pass on the plan of [the small city](SMALL_CITY.md), after the owner's first walk of the kit's pass 1 with no residents:

> "I still think that the layout is really simple, doesn't seem that intentional, and there are lots of empty spaces. It does feel a little bit empty for now, I would say. But overall, I think we are moving towards improvements."

**Status.** The plan is rewritten in [`living/tools/cullet_plan.py`](../living/tools/cullet_plan.py), the only source of `plan.json` and `cullet.json`. The 65 buildings, the 93 lot ids, the households' homes, the residents' places (`lot:<id>`), the structures and the five landmarks are kept. 59 lots moved; 34 did not. The kit builds 114 new fixtures for the new uses. Judged in the game's renderer in look-dev, before and after from the same 20 viewpoints at 13:00 and 18:30. Not yet walked by the owner. Not a performance result: the 114 new models add about 81,000 triangles and no frame time was measured.

This pass changes the plan's geometry and adds fixtures. It changes no table, reducer, view, subscription or engine code, so no SpacetimeDB design was made. The ground's painting, the 22 grey boxes and the residents belong to other tracks.

## What read as empty, and why

From the game camera at walking height, along a newcomer's routes (the before stills: asset board families `place:cullet-*`, the version from `a078b5f8`):

| Where | What the stills show | Why it reads as empty or arbitrary |
|---|---|---|
| The whole town from the harbour | Six short terraces in two columns on three identical bands, and 150 to 180 m of street for 92 m of houses | A diagram of parallel lines. Every Row has the same section and the same two terraces at the same x. Nothing says why a house stands where it does. |
| Each Row | Houses on the north side; 6.5 m of bare walk before them; 9 to 11 m of bare ground behind them, up to a 4 m wall | A town keeps its life behind its houses. Here there was no behind: no yard, wall, privy or line. The widest bare strip lay in front, where the street should be. |
| Beside Mid and High Row | 34 m of each Row with nothing on it, west of the terraces | The grey city called these the lean years' cleared plots, but nothing showed that a house had stood there. |
| The Ladder | 14 glasshouses over 85 × 140 m, three on a terrace 140 m long; the root plots 60 m further west; two glasshouses alone behind the Crown | The landmark is a sawtooth of glass stepping up a slope. Spread this thin it was scattered sheds on lawn terraces. |
| West of x −100 | Three levelled terraces 65 to 85 m long with a lane and nothing else | Levelled, walled ground with no use is the emptiest ground there is. |
| The Strand's backs | 10 to 14 m between the quay's buildings and Low Row's wall, bare | The same fault as the Rows: no back. |
| The wynds | Four straight stairs; none ends on anything | A view with no end has no intent. |
| The upper terrace and the Crown | 14 m and 62 m deep, with a lane and five things on them | Still largely true: see [what still reads as empty](#what-still-reads-as-empty). |

## The decisions

**1. Draw the town in.** Levelled ground went from 5.9 ha to 3.6 ha. The Rows run from the Net Wynd to the Store Wynd and no further. The Ladder stands directly against them. West of its wind wall the hill is the island's own.

**2. A Row is a balcony street.** The street runs 4.5 m into its band, along the parapet, with a 2 m sill on the sea side for benches. The ground the grey city left before the houses is now behind them, as:

- a walled **back court** against each house (4.4 m deep on Low Row, 5.2 m above), with a privy, a rain butt, a peat stack and what the household does;
- a 2.5 m **back lane** ("Low Row backs", "Mid Row backs", "High Row backs") between the courts' walls and the plots: the narrowest ways in town;
- a **plot** that leans on the wall of the row above (5.7 m deep on Low Row, 6.9 m above).

**3. The hollow on the Tally Wynd has a cause.** The middle of each Row, straight above the Counting House, was the factors' and shipmasters' houses. They left first when the ships stopped, and their roofs were the first stripped (SMALL_CITY §1, the lean years). The harbour is sized for a trade that no longer exists, and so is the town's middle. What is left differs by Row, which is also how the working end and the rich end now differ:

| Row | What stands in the hollow | Walls |
|---|---|---|
| Low Row | **The oven court** before the Batch (15 × 12 m of worn flags, benches, the bread board, a trough): where the town meets while its roots bake. The Tally Wynd comes up into it. Behind it, a drying green anyone may use. | A 1.1 m coped wall on the back lane |
| Mid Row | **Five tofts**: the houses' walls pulled down to the height a person could reach, old limewash on the inner faces, the door steps and the hearths left standing. Roots (the Sarros), cold frames (the Greaves), one gone to nettles, the Row's drying green, the mason's slate yard (Gwil Stannard). | Stubs, 2.6 m falling to 1 m |
| High Row | **Seven walled gardens**, kept whole by the Kiln families who took the plots: the Dunmores' roots, the Hollins' frames glazed whole, one locked since the fever winter, Mirren Quill's herbs, Ode Pontil's cullet (with the Rows' one piece of cobalt), the Quills' roots, the Kiln's hens. Behind them, cut stone under the quarry face. | 2 m, coped, with gates |

**4. Each wynd has an end.**

| Wynd | Where it runs now | What it ends on |
|---|---|---|
| The Net Wynd | x −17 (was −30): down the Counting House's west wall | The Heron |
| The Tally Wynd | Dog-legs at x 24, 34.7, 2.2, 39.7, 0 (was 24, 32, −8, 34, −8): from the yard into the oven court, west along Mid Row past the five tofts, east along High Row past the seven gardens, and up the last flight on the line of the cupola and the Fish Steps | Uphill: the Crown. Downhill from the Crown: the Counting House cupola |
| The Ladder Wynd | x −52 (was −100): up the middle of the Ladder, a flight at each wall, ending on the top walk. It reaches the quay through the 4 m slot between the net lofts and the smokehouses. | Uphill from the quay: the glass. It no longer climbs to the Crown: the way to the Crown is the Tally Wynd. |
| The Store Wynd | As it was (x 66) | The Marver's terrace at its Mid Row landing |
| Every Row, looking west | Runs on into the Ladder as a walk | A rank of glass |
| Low Row and Mid Row, looking east | | The Cone |

**5. The Ladder is one block.** Each of the Rows' bands is cut in two west of the Net Wynd, the back half 2 m higher (three new levels: `lad_1`, `lad_2`, `lad_3`). So a wall stands every 13 to 15 m up the slope, seven in all, and against each lean two glasshouses and two or three root plots. The glass covers 54 × 92 m (was 118 × 140 m; §1 asks 90 × 90 m) and the whole block 65 × 102 m.

- Which side of the wynd the glass stands on changes from rank to rank: both east (the Rows' lee), one each side (a rung), both west (toward the wind wall).
- The storm's three broken houses (6, 11, 13) are the westernmost houses of the third, sixth and top ranks: the storm came from the south-west.
- A 2.4 m dry-stone **wind wall** runs down the west side, stepping with the terraces. A 2 m wall on the Net Wynd's west side closes it from the Rows.
- Each rank has a walk, a working corner (a kelp heap and fork, cold frames, canes) and its flight.

## What moved

Coordinates are the plan's: origin at the Fish Steps, x east, y north, metres.

| What | Before | After | Why |
|---|---|---|---|
| Levels west of x −84 (Low, Mid, High, the upper terrace, the Crown) | To x −165, −175, −185, −260, −260 | End at x −84 | Levelled ground with no use |
| High Row's level, east | To x 80 | To x 70 | Nothing stood east of the Store Wynd |
| The Crown's level | 315 × 62 m | 139 × 62 m, with a 12 m ledge over the Ladder's top wall | The root plots left it |
| Three new levels: `lad_1` +7.5, `lad_2` +11.5, `lad_3` +15.5 | | x −84 to −19.5; y 47–60, 75–90, 105–120 | The Ladder's own terraces |
| Row streets | 9 m into each band (y 41, 69, 99), x −98 to 78 | 4.5 m in (y 36.5, 64.5, 94.5), from the Net Wynd to their ends | Balcony streets; the bare walk becomes yards |
| All 24 row houses, the Batch and the Marver | Fronts at y 43.8, 71.8, 101.8 | Fronts at y 39.3, 67.3, 97.3 (4.5 m south) | With their streets |
| The three west terraces | East ends at x 22; west ends at x −11.3, 5.8, 6.4 | West gables on the Net Wynd at x −15.5; east ends at x 17.8, 0.7, 0.1 | The empty ground moves from the Rows' west end to their middle, on the Tally Wynd |
| The three east terraces | x unchanged (they end at x 64 on the Store Wynd) | | |
| The Marver's terrace | On the walk before the Marver (x 52–64) | The corner bastion at Mid Row's end (x 68–80, y 60–66.5), over Low Row and Cinder Row | Mid Row now runs along the parapet; the corner looks down the harbour and across at the Cone |
| Glasshouses 1–14 | Three a terrace at x −33 to −115, 13 and 14 at y 193 | Two a rank on seven ranks, x −79 to −25, y 42 to 133 | The Ladder as one block |
| Root plots 1–18 | 3 × 6 on the Crown's level at x −240 to −182 | Two or three a rank on the Ladder's terraces | "Above and west of" the glass, inside the Ladder |
| The Net Wynd | x −30 | x −17 | Ends on the Heron |
| The Ladder Wynd | x −100, to the Crown | x −52, to the top walk | The Ladder's middle |
| The Tally Wynd's flights | x 24, 32, −8, 34, −8 | x 24, 34.7, 2.2, 39.7, 0 | Through the hollow |
| Row walks west of the Ladder Wynd, the Crown path west of the thorn | | Removed | Their levels are gone |
| New lanes | | Three back lanes; three walks on the Ladder's own terraces; the Cinder Steps' head; the Crown path from the bench to the Readers' House past the cistern; the peat road to the barn | |
| Quay lamps at the feet of the Ladder Wynd and the Net Wynd; `floats_1` | x −100, −30; x −52 | x −49.4, −23; x −36.6 | With their wynds; the floats stood in the Ladder Wynd's new mouth |

Not moved: every lot of the Strand, Cinder Row, the mole and the Crown, the three outlying houses, the Lintel, the square, the quay, the resources at named places (fishing grounds, kelp, sand, peat, the Hanger, the clay bank) and the seven lamps. Structures at lots (hearths, the oven, the furnace, the smokehouses) and the resources of the root plots and glasshouses are placed by lot, so they moved with their lots.

## New uses and their causes

All are fixtures of the plan, written by `enclosure()` in `cullet_plan.py`: a rectangle, its walls (where, how high, of what make, with which gaps) and its contents (what, where), each with its cause in the plan. Nothing is rolled.

| Use | Count | Where | Cause |
|---|---:|---|---|
| Back court (`yard`) | 26 | Behind every row house, the Batch and the Marver | A household's court holds what its people do (SMALL_CITY §3): Rafe Dunlin's creels, Bram Calloway's lean-to, the Tarns' washing, Chidi Okoro's boat-roofed shed, Davin Vane's handcart, Kenji Sato's ash sacks and smoke-grey washing, the Marver's barrels, the Greaves' cold frames, Hobb Fenwick's three rain butts, Gwil Stannard's slates, Otto Brandt's crucibles, Ode Pontil's cullet crates. Kiln walls are 2 m and coped, Strand walls 1.5 m and dry. An empty house's court has gone to weed; a roofless shell's holds what fell. |
| Back plot (`back_plot`) | 39 | Across each back lane, under the wall above | Boat on trestles (Dunlin), timber and ship's knees for the *Second Thought* (Calloway), nets (Tarn, Morrow), wrack on racks (Okoro, Sato), roots, hens (Brandt, the Marver), Cora Stannard's flowers, Mirren Quill's herbs, the Batch's peat, weeds, rubble, quarry waste |
| Oven court (`oven_court`) | 1 | Low Row, before the Batch | See decision 3 |
| Toft (`toft`) | 5 | Mid Row's hollow | See decision 3 |
| Walled garden (`walled_garden`) | 7 | High Row's hollow | See decision 3 |
| The Bleach (`drying_green`) | 1 | Low Row's east end, over Cinder Row | The wash-house's drying green, up the Cinder Steps from the Cone's warm wall and upwind of its soot (Greta Dunmore wants the smoke kept off the washing) |
| The Marver's kitchen garden (`yard`) | 1 | Behind its terrace | Roots and greens for the pot |
| Wind wall (`wind_wall`) | 7 | The Ladder's west side | Against the south-westerly |
| Ladder corner (`ladder_corner`) | 10 | The spare end of each rank | Kelp for the beds, cold frames, canes, a barrow |
| Ropewalk (`ropewalk`) | 1 | Under Low Row's wall behind the smokehouses, 29 m | Chidi Okoro makes line; a line-maker needs the longest straight, sheltered run in town |
| Net green (`drying_green`) | 1 | Behind the net lofts | The six lofts' nets dry out of the spray; a boat laid up |
| Smoke yard, tally court, Store yard (`yard`) | 3 | Behind the smokehouses, the Counting House and the Store | Fuel and barrels; the ship days' bonded yard, its wall still coped; the town's peat, counted in |
| Quarry bench (`quarry_bench`) | 4 | The upper terrace | Every wall's basalt came off this face (SMALL_CITY §1, materials): cut stone never carried down |
| Graveyard wall (`graveyard_wall`) | 1 | The Crown | Dry stone, the gate toward the town |
| Sill bench (`sill`) | 5 | The Rows' sills | Where the morning sun is |
| Washing across a wynd (`wynd_washing`) | 2 | The Net Wynd at Low Row, the Tally Wynd at Mid Row | SMALL_CITY §6, the Rows' dressing |

## Walking times and landmarks

`living/tools/cullet_check.py` on a land dump, walking the hosted tiles at 2.6 m/s. The check was found to treat `Drop` tiles as walkable since `drop-1` (it predates them); it now uses the rules' own classes.

| From the Fish Steps to | Before | After | SMALL_CITY §2 |
|---|---|---|---|
| The Crown bench | 230 m, 88 s | 227 m, 87 s | about 2 minutes |
| The Readers' House | 262 m, 101 s | 246 m, 94 s | |
| The far end of the Wrack Strand | 315 m, 121 s | unchanged | about 3 minutes |
| The Lintel | 619 m, 238 s | 612 m, 235 s | about 3 minutes |
| The turf house | 409 m, 157 s | 400 m, 154 s | |
| The Watchglass, the Cone's mouth | 72 s, 60 s | unchanged | |
| The quay, end to end | 150 m, 58 s | unchanged | about 1 minute |

Every building door is reachable (`settle::stranded_doors` is empty).

Landmarks seen from the town's street points (every 6 m of every street and lane; 901 points, was 967), from a person's eye and from the game camera's height:

| Landmark | Before: eye, camera | After: eye, camera |
|---|---|---|
| The Cone | 70%, 93% | 47%, 92% |
| The Counting House | 80%, 99% | 61%, 99% |
| The Heron | 71%, 75% | 49%, 56% |
| The Watchglass | 54%, 98% | 31%, 98% |
| The Lintel | 11%, 83% | 2%, 76% |

The eye-height shares fell because a third of the points are now in enclosed places: the back lanes and the Ladder's walks under its walls. That is what enclosure costs. From the game camera only the Heron lost much; it is 13 m high and hidden from the back lanes and the Ladder. The farthest street point from the Cone is now 257 m (was 416 m), from the Watchglass 285 m (was 439 m).

## In the kit

`living/tools/blender/cullet.py` has one new section, "Layout pass 1: enclosures": `gen_enclosure`, the wall builder `e_wall` (dry, coped and stub walls, gates and boarded gaps), 35 kinds of content (`c_privy` … `c_ash_sacks`) and 13 new folders registered with `GEN.update`. No existing function was changed. All 363 models (114 new, about 81,000 triangles; the kit is now about 401,000) pass `cullet_kit_check.py`: footprint, triangles, surfaces, palette, materials.

## What still reads as empty

- **The Crown.** 139 × 62 m with the cistern, three buildings (grey boxes), the graveyard and its new wall, a thorn and a bench. It is meant to be open and windy, but it has no ground of its own yet and its buildings are boxes.
- **The upper terrace** east of the Ladder: 75 × 14 m with the upper walk and four groups of quarry stone. It needs the quarry face as rock, not a built wall.
- **The Strand's backs** between the new yards: about half that ground is still bare, and so is the square.
- **The sills.** A 2 m strip on each Row's sea side with five benches in all.
- **The Ladder's root plots** draw as flat slabs inside their walls: nothing grows in them yet.
- **Cinder Row** was left to the kit's pass 2. Its yard between the lehr house, the ash house and the Cone is open cinders.
- **Everything stands on lawn** until the kit's ground is in. The new enclosures name the ground they want (`ground`: setts, earth, worked soil, quay flags) for that pass to read.

## Not done, and next

(As pass 1 left it. Pass 2 did the first four.)

- **Walls do not block.** Fixtures are presentation: a person walks through a court's wall as through a net rack. A general rule for low walls and fences (tiles a plan marks as walls) would make the back lanes real. It is a rule for every world, so it was not added here.
- **Yards have no names or spots.** The courts and plots are not lots, so nobody can be sent to "the Tarns' yard". Open lots with spots would let residents hang washing or feed hens there.
- **The quarry** should be a notch in the Crown's level with a raw face, and the clay bank beside it.
- **The Crown** wants its own pass: where the cistern's overflow runs, how the graveyard's glass markers stand, the peat road's ruts.
- **Views.** The cupola axis and the Heron at the Net Wynd's foot were placed by geometry and checked in stills from above; they were not walked at eye height in a connected world.
- **Performance.** 114 more models and draw calls were added without a frame measurement.

## Verification (2026-11-11)

On the dev-box, with a private `CARGO_TARGET_DIR` and my own container (`layout1-stdb`, SpacetimeDB 2.14.1, port 3324).

- `cullet_plan.py --check` and `author_world.py cullet --check` (0 errors, 0 warnings: 64 residents, 22 homes bound) pass; `cullet.json` keeps its residents, homes, ways, town life and 34 structures.
- `cargo test -p living-rules`: 171 passed, 9 ignored, with `the_cullet_seed_is_valid_and_reachable` and the pinned digests.
- `cullet_kit_check.py`: 363 of 363 on footprint, triangles, surfaces, palette and materials.
- `set -o pipefail; just living-check` exits 0.
- verify-generation `--feature worlds --seeds cullet,plan-test`: plan-test 78 of 78; Cullet 313 of 317, every plan check passing (lots as written, doors walkable, drops, resources, structures, homes, digests). The four failures come from the shared harness installing the shipped script over Cullet's laws after publishing, under which four elders die of old age at once; see [verify-generation's validation](../.agents/skills/verify-generation/references/validation/history.md). They are not the plan's, and they were not rerun on plain `origin/main`.
- verify-ui `check.py support` on a scratch Cullet world: 7 of 7 (the flight, the terrace, the quay and a wall's top at their new places); the client's regenerated land matched the authority's digests. Its fixed spots were moved with the plan, and `drive.py` now honours `LIVING_STDB_URL`.
- The game client in look-dev: 67 stills from 20 viewpoints at 13:00 and at 18:30, before and after, on the asset board (`place:cullet-strand`, `place:cullet-rows`, `place:cullet-ladder`, `place:cullet-crown-and-views`) and on the pass's page (`.local/layout-1/index.html` on the dev-box).
- Not done: a walk in a connected world by a person; a frame-time measurement; verify-core, verify-minds and the other surfaces (no rule, mind or table changed).

## Pass 2 (2026-11-11)

Branch `layout-2`, Claude Fable 5.2. The owner's words stand ("the layout is really simple, doesn't seem that intentional, and there are lots of empty spaces"). Pass 1 answered most of that; three places still read as empty, and the dev-box coordinator decided what goes in each. This pass lays them out, and adds two rules for every world's plans: walls block walking, and courts and plots are places people can be sent to.

**Status.** Written in `living/tools/cullet_plan.py` (the section "Layout pass 2") and built by `living/tools/blender/cullet.py` (the same). The 65 buildings, the households' homes, the residents, the structures and the five landmarks are kept; ways and town life gained six named places and seven habits. Merged with main at `e3f0527f` (kit-2's ground and models, rules-3's stores). Judged in the game's renderer in look-dev, before (main with kit-2) and after from 33 viewpoints at 13:00 and 18:30. Not walked by the owner. Not a performance result: the kit goes from 434 to 469 models and from about 481,500 to 515,200 triangles, and no frame time was measured.

### The Crown

139 × 62 m with a few boxes. It is the town's quiet top, where people come in the late afternoon, so it stays open: what was added is ground, low walls and one corner that climbs.

| What | Where (plan frame) | Cause |
|---|---|---|
| **The graveyard**, moved | The Crown's south-east corner, x 30–55, y 134–157.5 (it was a 26 × 18 m rectangle in the north-west) | The bible: the dead are buried on the Crown; there is good clay under the Crown, where the graves are. It now stands over the clay pit, so that is visible. |
| Three bands half a metre apart | Two new levels, `graves_2` (+20.5) and `graves_3` (+21.0); the lowest band is the Crown's own | "Rows down the slope": the oldest graves at the top, the newest at the lip. The banks are walkable; a dry kerb holds each, with two flights of three steps. |
| The fever winter's row | The lowest band, y 137.5: nine markers with humped mounds, room for one more at the east end | The bible's nine, six years ago. Each has its glass and why: Iona Pontil's is cobalt (the Crown's one piece: the Glassmaster's only daughter), Arvo and Liss Dunmore's amber, Matthias Sarro's bottle green (a blower), Ada Frit's smoke. |
| The row behind it | y 141.3: nine markers | The bible's other named dead. Magda Tarn's husband and Sander Vane have a marker and no grave: the sea kept them. |
| The middle band | Two rows of nine and eight | Since the lean years: weathered, a few leaning. |
| The top band | Seventeen small dark markers set close; above them six round-headed basalt stones | The lean years, when half the town went or died and the glass was poor; and the ship days' stones, cut in the formal script nobody but Benedikt Orme reads. One has fallen. |
| Its wall | Dry stone, 1.2 m, on the Crown's lip on the south; the gate in the west side on the aisle between the two newest rows | The gate faces the town. A revetment holds the upper bands' west and north sides. |
| **The cistern's apron** | A ring of flags round the tank, worn pale on the south; the dipping step; buckets and a yoke | Everyone's water, twice a day. |
| The cistern path | From the head of the Tally Wynd north to the dipping step | The path worn to it. |
| The overflow | A cut runnel from the tank's south-east to the lip of the quarry's bay, a slab over it where the Crown path and the grave path cross; the face is green where it falls | Rain that the tank cannot hold has to go somewhere, and downhill is the quarry. |
| **The Readers' House's yard** | The forecourt on its south side, 11.8 × 8.3 m: a 0.9 m coped wall to sit on, the gate where the Crown path comes in | Lessons are from 09:00 to 12:00; the morning sun is on this side. |
| The tablets' bench | Against the house wall, west of the door (the lot's existing spot): a 4.2 m slab with nine tablets of slate and fired clay, two leaning | The ship-day tablets are read in daylight. |
| Eight stones in a half ring, a tray of white sand | Before the bench | The children's seats. Nothing that can be written on is thrown away, so they write in sand from the Sand Spit and smooth it. |
| **The thorn's stance** | A 1.3 m dry wall on the weather side of the thorn, flags under the bench | A thorn lives on a bare top only in a lee: the wall is older than the tree, and the tree leans the way the wall points. |
| **The dyke** | Dry stone, 1.3 m, round the Crown's west, north and east sides, 237 m, slumped in nine places | Built in the ship days against the moor's sheep. The island has none now, so nobody mends it. |
| The peat gap | In the north side at x 51.3, 3.6 m wide | The peat road goes through it. |
| The children's gap | A slump in the north side at x −12, open | The short way to the Lintel, which they dare each other to touch. |
| **The peat road**, rerouted | From the Crown path round the Readers' House's west gable to the barn's door and the gap | The straight line from the barn to the wynd runs through the Readers' House; feet bend round its corner. It no longer crosses the school's yard. |
| The grave path | From the wynd's head along the lip of the quarry's bay to the graveyard's gate | |

kit-2 models the Crown's buildings (the Readers' House, the cistern house, the peat barn), the cistern's tank, the thorn and the bench. This pass builds none of them. Its `gen_graveyard` (three rows on the lot's rectangle) is no longer used: the graveyard's three lots name no model, and `graveyard/graveyard.glb` is now the lowest band's fixture.

### The quarry

The upper terrace east of the Ladder, 75 × 14 m with four groups of stone. The basalt of every ground floor, the quay and every wall came off this face (SMALL_CITY §1, materials).

| What | Where | Cause |
|---|---|---|
| **The face**, raw | The Crown's edge from x 8 to 55, in eight lengths: 3 m of basalt in columns, each broken off at its own heights and set back as it rises | It was a built retaining wall. Basalt stands in columns and is worked in lifts a man can reach; no course runs along a face. |
| The bay | The upper terrace's level runs 6 m into the Crown between x 8 and 26 | The last working. A quarry bites in where the rock is good; a straight face is a wall. |
| Drill marks | Down the bay's back and its east return: dark half-holes on pale rock | Where it was split along drilled holes, the newest rock, not yet weathered. |
| The crane | At the bay's mouth: a ship's spar for a mast, two raking legs, a hand winch, a squared stone hanging a hand above the ground | Timber is precious, so it is a spar. The stone is as it was left. |
| Squared stones | Two stacks on bearers; a sledge with one stone on it; a block half split with the wedges in it | Cut in the ship days for a quay that needed no more. Gwil Stannard takes one when a wall wants it. |
| Spoil | Two heaps east of the bay, where the Tally Wynd's flight comes up; one gone to grass west of the wynd | What would not square, tipped where the barrow run ended. The grassed one is the oldest working. |
| **The clay pit** | A new level, `clay_pit` (+16.3), the terrace's east end, 14 × 8 m, dug 0.7 m down (a bank one walks) | The bible: the clay bank is nearly dug out. Brick for the Cone came from it. |
| Its face | 3.7 m under the graveyard's south wall, in spade lifts | Otto Brandt has dug to the wall's foot. The good clay goes on under the graves. |
| What is left | One bank of grey-blue clay in the north-east corner, his spade in it; boards of dug clay under sacking; a plank run up the bank; a wet floor of stony till | "Perhaps a season's crucibles." The clay bank's resource node stands here now. |

A newcomer climbing the Tally Wynd arrives on this terrace at x 39.7, beside the clay pit and the spoil, and walks 40 m west through the quarry to the last flight.

### The Strand's backs

The working shore. About half the ground between pass 1's yards was bare.

| What | Where | Cause |
|---|---|---|
| **The boatyard** | Between the dry dock and the net lofts, round the boatshed, 28 × 22 m | The bible: Bram Calloway has been building the *Second Thought* for four years from ship-day timber, driftwood and the planks of old sheds; he needs fourteen trees more. |
| The timber, by sort | Five stacks and the ship's knees behind the shed | Ship-day oak for the keel and frames, driftwood by length, tarred shed planks for the skin. |
| The steaming box | In the 7 m gap beside the dry dock: a 5.4 m tarred trunk on trestles, a kettle on a brick firebox | A plank goes hot from the box to the hull. |
| The working floor | East of the shed: saw trestles, the pitch pot, a bench, the boat on trestles | |
| A paling of hull planks | Along the slipway, with a gate | SMALL_CITY §1: hull planks are fences. |
| **The wrack stance** | Behind the Heron, 18 × 17 m: nine racks in three ranks set across the south-westerly, two wet heaps | The bible: the Heron still lifts kelp loads. What is landed wet dries here before it goes to the kilns. |
| **The way out to the kilns** | West of the slip, on the beach: three racks beside the strand path, the ash burner's handcart, and the four kelp kilns | The kilns were a feature with no model. Round, as everything that holds fire is; one is loaded. They stand off the town's levels, at the beach's own height. |
| **The peat stance** | Behind the yard, between the Tally Wynd and the Store's yard: five bearers under Low Row's wall | The bible: the peat stack is falling. Loads are counted in from the east, by the Store Wynd; the Rows take theirs from the west. So two ricks are full under tarred cloth, one half gone, two bare. The tally keeper's slate stands at the end. |
| **The creel stand** | At the foot of the Store Wynd: a stone bank at cart height, five creels, the handcart | The wynds are stairs, so peat comes down on backs. Here it is tipped into the porter's cart for the Cone. |
| **The working quay** | East of the Fish Steps, two gutting tables at the edge; west of them three bait tubs and two net-mending benches with a net on its frame | The bible: Magda Tarn divides the catch here; Ingrid Morrow mends nets here. Guts go to the harbour. |

Still bare on the Strand: the square, and the strip between the Store and the peat stance.

### Walls block walking

A general rule, for every world's plans: [authored plans, fixtures that block](AUTHORED_PLANS.md#fixtures-that-block). A plan's `fixtures` are lines (walls, fences, with gaps for gates) and rectangles; one marked `blocks` becomes blocking tiles when the land is hosted, `Wall` where it rises above the eye and is solid, `Low` where it is seen over.

On Cullet, `cullet_plan.py` `barriers()` writes one line for each wall of each enclosure and each root plot's wall: 261 lines, 2,372 m.

| Walls | Height | On the tiles |
|---|---|---|
| Kiln courts and the seven walled gardens (coped), tofts' party walls, the Ladder's wind wall, the Counting House's and the Store's yards | 1.7 to 2.6 m | `Wall`: 69 lines. They hide what is behind them: a Kiln garden is private from High Row. |
| Strand courts, plots, the oven court, drying greens, root plots, the graveyard, the dyke, the Readers' yard, kerbs, the boatyard's paling | 0.55 to 1.5 m | `Low`: 192 lines. One sees over them. |
| A toft's stub wall, which falls along its length | 2.6 to 1 m | Two lines: the part above the eye, and the rest |
| A boarded gap (the locked garden, both sides now) | | Shut: the garden's 44 tiles are the only ground in town no one can reach |

- Every building door is reachable (`settle::stranded_doors`), and so are all 387 spots and every authored resource (the rules' Cullet test, `cullet_check.py`, verify-generation).
- Three yards of pass 1 began 0.7 m behind their building's back wall (the smokehouses', the Counting House's, the Store's), which left a slot a tile wide. They begin at the wall now.
- `cullet_check.py` reports reachability and colours `Drop` and `Low` tiles.

### Courts and plots are open lots

A general rule in use, not in code: an open lot is a `lamp` lot of no height and no model, as the root plots already were. 108 of pass 1's and pass 2's enclosures are open lots now, each on its rectangle, named for who keeps it ("the Tarns' court", "Mirren Quill's garden", "the Ladder's third working corner"), with a spot inside its gate and at each thing one works at ("the washing line", "the crucibles on their planks", "the boat on its trestles"). `lot:<id>` names them in a resident's places, a trade's work or a named place.

- **Six named places** in `town_life.places`, which everyone in a town of 64 knows: the Bleach, the Readers' yard, the clay pit, the ropewalk, the wrack stance, the boatyard.
- **Seven habits** in the trades' starting ways (`ways.json`), each a first step of the routine for named hours, which a mind may drop:

  | Trade | Hours | Place |
  |---|---|---|
  | washer (Greta Dunmore) | 11–13 | the Bleach |
  | reader (Benedikt Orme, Sabine Quill) and child (13) | 9–12 | the Readers' yard |
  | pot_maker (Otto Brandt) | 7–10 | the clay pit |
  | line_maker (Chidi Okoro) | 13–16 | the ropewalk |
  | wrack_gatherer (Amara Okoro, Lark Morrow, Hana Sato) | 11–13 | the wrack stance |
  | boatwright (Bram and Kit Calloway) | 13–16 | the boatyard |

- **Not done:** a household's own court as its people's place (the Tarns' washing, Rafe Dunlin's boat). Ways are keyed by trade, and the Tarns are fishers, a smoker and children. It needs a place on the residents themselves, which come from the cast (`author_world.py --compile-only`); the lots are there for it.
- The Fish Steps' lot gained four spots (the gutting tables, the mending bench, the bait tubs), since a lot may not stand on the quay's street.
- **Found:** a spot's first number runs east along a south front, not west as the plan's names assumed. The Cone's west and east mouths, the Crown bench's seats, the wash-house's warm wall and the Fish Steps' second step each had the other's name; "Magda's place" stood in the harbour. Corrected, and kit-2's `spot_at` with them (below).

### Walking times

`cullet_check.py`, 2.6 m/s on the hosted tiles. Walls cost a few seconds where people cut across courts and the Crown's north side.

| From the Fish Steps to | Pass 1 | Pass 2 | SMALL_CITY §2 |
|---|---|---|---|
| The Crown bench | 227 m, 87 s | 233 m, 90 s | about 2 minutes |
| The Readers' House | 246 m, 94 s | 256 m, 98 s | |
| The far end of the Wrack Strand | 315 m, 121 s | unchanged | about 3 minutes |
| The Lintel | 612 m, 235 s | 617 m, 237 s | about 3 minutes |
| The turf house | 400 m, 154 s | 424 m, 163 s | |
| The Hanger cottage | 304 m, 117 s | 313 m, 120 s | |
| The Watchglass, the Cone's mouth, the quay end to end | 72 s, 60 s, 58 s | unchanged | about 1 minute (the quay) |

The turf house's 9 s are the dyke: the way to the Moss goes by the peat gap. Landmarks seen from the street points are within two points of pass 1's (the Cone 45% from the eye and 92% from the camera).

### In the kit, and in the client

- `cullet.py`, "Layout pass 2": 31 kinds of content, `gen_quarry_face`, `gen_quarry_crane`, `gen_kelp_kiln`, a paling for `e_wall`, and slumps in a dry wall. `e_wall` gained two branches; no other existing function changed. After the merge with kit-2 all 469 models pass `cullet_kit_check.py`, the coplanar check among them (44 new, 9 gone: four lengths of wall, pass 1's four quarry groups and its graveyard wall; 11 older ones changed, the sills, three yards, the locked garden and the wall at the bay).
- An enclosure's `ground` names one of kit-2's surfaces (`setts`, `earth`), so the ground pass paints the Readers' yard, the quarry's floor, the clay pit and the Strand's four new yards (152 areas, 147 before). The graveyard, the apron and the stance stand on the Crown's own turf.
- kit-2's `spot_at` took a spot's first number toward the west for a south front; the engine takes it east. It now follows the engine, and the three spots it reads (Halvard's bench, the cullet heaps, the trough) were moved onto the dressing kit-2 stands there, so the bench people are sent to is the bench that is drawn.
- Tall things stand alone (the crane is its own model), because the client fades and keeps the camera out of a model by its whole box.
- `fixtures.json` gives each fixture's `size`. The client draws no slab under an open lot a fixture stands on.
- **A client fault met on the way:** every one of the engine's own wall pieces and flights on Cullet drew a kit model of its folder at random, on top of the kit's own. It hid the quarry's face behind a wall. I fixed it here; `stairs-place` fixed it on main the same evening, and its fix is the one kept after the merge ([authored plans](AUTHORED_PLANS.md#the-game-client)). The stills were taken with mine; for Cullet the two do the same.

### What still reads as empty

- **The Crown's middle and north.** 80 × 40 m of open turf between the cistern, the Readers' House, the barn and the dyke. It is meant to be open, and with kit-2's ground and buildings it reads as a hilltop; whether it wants more is for the owner's walk.
- **The square.** 30 × 14 m of flags with a lamp. The market is under the arcade; the yard has nothing that says market day.
- **Cinder Row's yard**, as pass 1 left it.
- **The sills**, five benches on 500 m of parapet.
- **The Strand between the Store and the peat stance**, and the slot west of the Counting House.
- **The quarry's west third**, one grassed heap on 16 m.

### Not done, and next

- **Gates do not open or shut.** A gap is open ground.
- **Low walls in the rules' own sight.** A 1.5 m wall is `Low`, so a child behind it is seen as an adult is. The eye height is one per land.
- **Household courts as places** (above).
- **The clay face and the graveyard's markers** are plain: spade lifts read as blocks, and glass has no thickness of its own in the toon shader.
- **Performance.** 45 more models and 110 more lot rows, without a frame or connection measurement.

### Verification (pass 2)

On the dev-box, 2026-11-11, on the branch merged with main (`e301aa9f` for the generation and rhythm runs, `e3f0527f` for the rules tests' last run and `living-check`), with a private `CARGO_TARGET_DIR` and my own container (`layout2-stdb`, SpacetimeDB 2.14.1, port 3329). No paid model call.

- `cullet_plan.py --check` and `author_world.py cullet --check` (0 errors, 0 warnings; 64 residents, 22 homes bound) pass; `cullet.json` keeps its residents, homes, ways, town life and 56 structures.
- `cargo test -p living-rules`: 227 passed, 10 ignored: the pinned digests (the island and the megacity floor unchanged), the three new fixture tests and the extended Cullet test ([authored plans](AUTHORED_PLANS.md#fixtures-that-block)).
- `cullet_kit_check.py`: 469 of 469 on footprint, height, doors, triangles, surfaces, palette, materials and coplanar.
- verify-generation `--feature worlds --seeds cullet,plan-test` (`generation-layout2m-20261111-214828`): Cullet 329 of 329, plan-test 83 of 83, with the new checks (blocking fixtures on unwalkable tiles, walls above the eye as `Wall`, every gap open, every spot standable, each named place on one of its lot's spots) and `land` digests equal to the native generator's. The four checks that failed for pass 1 pass now. Record: [verify-generation's validation](../.agents/skills/verify-generation/references/validation/history.md).
- verify-core `rhythm` (thirteen residents on a 12-minute day; `core-layout2m-215141-rhythm`, and `core-layout2-213412-rhythm` before the merge): 25 of 26 in each. Residents reach their new places in their hours, through the gates of walls that block: Otto Brandt at the clay pit, Benedikt Orme in the Readers' yard, Greta Dunmore on the Bleach, Bram Calloway in the boatyard, and everyone knows the six named places. The failure in each run was my first check of the child at lessons: she walks 230 m from the Cone, three of that scene's 30-second hours, and arrived as lessons ended (6 m away at noon in one run, 19 m in the other, in the yard minutes later in both). The check now asks that; it passes on both runs' recorded samples and has not been driven live in that form. Record: [verify-core's validation](../.agents/skills/verify-core/references/validation/history.md).
- `set -o pipefail; just living-check` exits 0 on the merged tree (main `e3f0527f` in): authority, mind and viewer, game, viewer wasm, rules tests, seed laws and the script fuel gate, 390 s.
- The game client in look-dev: 210 stills a side from 33 viewpoints (layout-1's twenty and thirteen new ones at the three places, each at the game camera and the 9 m walking camera) at 13:00 and at 18:30. Before is main with kit-2 (`7c6a92b6`); both sides are photographed by this branch's client, so the pairs show the plan's change and not the stray-wall fix. On the asset board: `place:cullet-strand` (before `20261111-7c6a92b6-cc7e38`, after `20261111-67f9e733-a3c397`), `place:cullet-rows` (`…-fc91c8`, `…-bae352`), `place:cullet-ladder` (`…-ace3c9`, `…-1ea738`) and `place:cullet-crown-and-views` (`…-0ecbd2`, `…-f40db3`); nothing accepted yet. The pass's page is `.local/layout-2/index.html` on the dev-box (128 pairs, the plan maps, the hosted tiles), with `.local/layout-2.tar.gz`.
- Not done: a walk in a connected world by a person; verify-ui (its `support` spots did not move: the Ladder Wynd's first flight, the Marver's terrace, the quay, `wall_002`); verify-client, verify-player, verify-minds (no table, reducer, view or protocol changed); the authority's native `seed::tests`; any frame-time or connection measurement.
