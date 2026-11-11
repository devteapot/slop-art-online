# Cullet's layout, pass 1

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
- verify-generation `--feature worlds --seeds cullet,plan-test`: plan-test 78 of 78; Cullet 313 of 317, every plan check passing (lots as written, doors walkable, drops, resources, structures, homes, digests). The four failures come from the shared harness installing the shipped script over Cullet's laws after publishing, under which four elders die of old age at once; see [verify-generation's validation](../.agents/skills/verify-generation/references/validation.md). They are not the plan's, and they were not rerun on plain `origin/main`.
- verify-ui `check.py support` on a scratch Cullet world: 7 of 7 (the flight, the terrace, the quay and a wall's top at their new places); the client's regenerated land matched the authority's digests. Its fixed spots were moved with the plan, and `drive.py` now honours `LIVING_STDB_URL`.
- The game client in look-dev: 67 stills from 20 viewpoints at 13:00 and at 18:30, before and after, on the asset board (`place:cullet-strand`, `place:cullet-rows`, `place:cullet-ladder`, `place:cullet-crown-and-views`) and on the pass's page (`.local/layout-1/index.html` on the dev-box).
- Not done: a walk in a connected world by a person; a frame-time measurement; verify-core, verify-minds and the other surfaces (no rule, mind or table changed).
