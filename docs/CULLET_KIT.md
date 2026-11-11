# Cullet's kit

Started 2026-11-11 (branch `kit-1`, phase 3 of [the small city](SMALL_CITY.md#8-build-plan)). Fable 5.2 wrote it, starting from its A/B arm (`ab-arm1`), as the owner decided (decision 12). Pass 1 was the P0 list of SMALL_CITY §6; pass 2 (branch `kit-2`, the same day) is the ground and most of the P1 list.

**Status.** 432 models, about 480,000 triangles, built for their places from [Cullet's plan](AUTHORED_PLANS.md#cullets-plan). All 432 pass the checks below. Judged in the game's renderer, in look-dev (the land of `living/seeds/cullet.json`, the `cullet` mood) at 13:00, dusk and 21:30. Not yet walked by the owner in this state. Not a performance result: no frame times were measured. The ground is Cullet's own since the laptop's `ground-1` (on main) draws what this pass paints and maps ([the ground](#the-ground)).

## Run it

```bash
python3 living/tools/cullet_plan.py            # the plan, the seed and the env's ground map, when cullet_plan.py changed
living/tools/blender/gen_cullet.sh             # every model, fixtures.json, ground.json, report.json, the footprint table (about 40 s)
python3 living/tools/cullet_kit_check.py       # the checks, on the GLB files themselves
just living-game-textures --set all            # the ground's painted layers, with Cullet's nine
```

Two runs on one machine give byte-identical files (all 464: the models, `fixtures.json`, `ground.json`, `report.json` and the footprint sidecars; dev-box, Blender 5.2.2), and a second full run leaves `living/rules/data/buildings.json` as it is. Another machine or Blender version has not been compared: the geometry and colours follow from the plan alone, but the exporter's bytes are Blender's. A machine without Blender can take the dev-box's generated folder as a tarball instead (unpack it at the repository's root).

`gen_cullet.sh --only cone,low_4,retaining_wall` builds some models (ids or folders). `--out DIR` writes elsewhere; `--figure` stands a 1.75 m figure by each model, for contact sheets only. Only a full run into the game's own folder touches the footprint table. `just living-game-assets` runs the generator with the other kits. The output, `living/game/assets/envs/cullet/`, is git-ignored: the scripts are the asset.

## How it is built

- **One script**, [`living/tools/blender/cullet.py`](../living/tools/blender/cullet.py), on `buildings.py`'s helpers, as `city.py` is. Metres, +Z up, fronts to −Y, colour per vertex on one `Body` material with the surface tag in alpha, glowing parts on `Glow` (oil lamps), `GlowAmber` (the furnace, the Batch's oven, the yard fire), `GlowEmber` (a banked fire deep in a room: the lehr, the wash-house copper), `GlowDim` and `GlowCyan` (the Watchglass).
- **A model for each place.** The script reads `plan.json` and builds one model for each lot and each fixture that it has a generator for, at the path the plan names (`cullet/<folder>/<id>.glb`). Footprint, height and level come from the plan. So does wear: `salt`, `soot`, `wind`, `age`, `repair` and `empty`, each with its cause. A model's origin is the middle of its lot's rectangle; it is never re-centred, so a terrace's houses meet at their party walls.
- **The only random numbers** come from the `seed` the plan records for the lot (which stone is a shade darker, where a flake of lime lies). The same plan gives byte-identical files.
- **Compass.** A model's front looks along its lot's `facing`. `Env` turns compass bearings into the lot's own frame, so lichen and flaked lime lie on the faces the south-westerly strikes, whichever way the lot faces.
- **Terraces are built as rows.** Each house is its own model on its own lot, laid out with its neighbours: they share a party wall (each model carries its half) and the stack on it (half each, as high as the taller roof needs). A house's width is its household's size, its storeys its family's, its door its household's colour, and what stands by the door is the household's keepsake from the plan. The Rows follow the slope's contours, so a row's floors are level; the roof line steps where storeys differ. The rank of net lofts is built the same way.
- **Working buildings stand open** (SMALL_CITY decision 7). Each front is a list of what the building is for: doors, small-paned windows, and openings with the room behind them and what is kept in it (the lehr's arches, the pot house's drying shelves, sacks, crates of cullet by colour, a boat on her cradle). The opening is real depth, so it shows from the game camera and it is what the sight rule measures (below).
- **Glow** was set in the game, not in Blender. The game's emission is the material's strength times exposure times the hour's `glow` (three times stronger at night). `buildings.py`'s strength of 2.6 does not show on daytime glass colours. The kit's strengths (220 for oil lamps, 300 for the furnace, 240 for the Watchglass, 110 for a banked fire) read as lit at 21:30 and leave a pane its own colour at 13:00.
- **A glasshouse's light is its one lantern's** (the dev-box coordinator's call, 2026-11-11: glow is sparse and true to what is lit). Every pane within 1.0 m of the lantern strip is lit; out to 2.4 m fewer and fewer catch a dimmer light (`GlowDim`, 80); beyond it a pane keeps its glass colour. That is 8 to 12 lit and 15 to 21 dim panes of 342 in a worked house, and none in a broken one. The two distances are generator parameters: `gen_cullet.sh --lantern-core M --lantern-reach M`.
- **No two faces in one plane** (pass 2, after the owner's walk: [the flicker](#the-flicker-at-a-gable)). Before export every model goes through three passes: undersides on the floor are removed; a face wholly covered by faces looking the other way in its own plane is removed (the back of a sill against its wall); and where two parts' faces still share a plane and overlap, the later part is moved 3 mm along its own normal, 6 mm for a third layer, so what was laid later lies on top.

## What the kit builds

| What | Models | Triangles | Largest | Pass | Notes |
|---|---:|---:|---:|---|---|
| The Cone | 1 | 9,882 | 9,882 | 1 | 14 m across, 24 m. Two mouths lit, the third's door half open on the glow. |
| The Counting House | 1 | 11,460 | 11,460 | 1 | 30 × 12 m. Seven open arches, the tally room's seven windows, a hipped roof, the cupola's clock at ten past four. |
| The Watchglass | 1 | 2,930 | 2,930 | 1 | An eight-sided shaft under a lantern room too big for it: 320 panes in facets, one band of cobalt. |
| The mole | 5 | 15,508 | 3,954 | 1 | Root, three sections of the arm, tip. Sea walls with the tide line, a wave wall east, ship's bollards west. |
| The Heron and its jib | 2 | 2,670 | 2,152 | 2 | A hunched crane house of tarred timber, 13 m to the king post's verdigris cap; the quay side open on the 3.9 m treadwheel. The jib, a fixture, reaches 9 m over the water with a net of kelp on its fall. |
| Row houses | 24 | 48,379 | 3,027 | 1, 2 | Six terraces: 17 lived in, 4 empty and sound, 3 roofless shells. Pass 2: lit windows from the plan; the shells' hearth breasts, joist sockets, fallen rafters and slates, a bramble, and in Low Row 9 the thorn grown taller than its walls. |
| The lamp house | 1 | 2,459 | 2,459 | 2 | The Faros' house on the mole's root: a row house on its own, a stack at its gable, an oil drum and a coil of wick by the door, lit below and above. |
| The Marver and its terrace | 2 | 6,730 | 5,176 | 1 | Three serving hatches, the hearth, the figurehead; tables, benches and an anchor over the drop. |
| Glasshouses | 14 | 90,492 | 7,133 | 1, 2 | One generator, three states from `repair`. Pass 2: Jory Greave's fan-trained fruit tree in glasshouse 9, Cora Stannard's flowers in glasshouse 4. |
| Net lofts | 6 | 7,432 | 1,274 | 1 | One rank. Double doors of two 0.9 × 2.0 m leaves. |
| Cinder Row: the lehr house, pot house, cullet shed, ash house and wash-house | 5 | 22,253 | 7,077 | 2 | The lehr house is the bonded warehouse: three round-arched cart doors open on the lehr's banked arches, boarded loading doors, three flues. The pot house's two bays show the drying shelves and the wheel; the ash house its sacks; the cullet shed crates of four colours; the wash-house is a lean-to on its own warm brick wall, troughs, a copper and linen under the slates. |
| The Batch | 1 | 2,854 | 2,854 | 2 | One tall storey at the east end of Low Row's west terrace: the oven's brick breast and glowing mouth to the street, the loaf shelf, peels, the bench. |
| Smokehouses | 2 | 3,764 | 1,906 | 2 | Basalt to the waist, tarred boards above, a louvred ridge; the half door open on the fish. Their folder is `smoke_shed`: `smokehouse` is the engine's fire. |
| The Store | 1 | 4,037 | 4,037 | 2 | Shut: double doors under a carved lintel, a loading door and cathead, barred windows, the tally slate. |
| The boatshed | 1 | 4,620 | 4,620 | 2 | The whole front open between two piers and a post; a clinker boat on her cradle with planks off, the bench, the pitch pot. |
| The dry dock and the hull of the *Second Thought* | 1 | 3,558 | 3,558 | 2 | Stepped altars on three sides, keel blocks, shores, a staging; the hull in frame, 20 ribs a side, planked four strakes of ten (the plan's `stage`), 8 m to the stem's head. |
| The Readers' House | 1 | 5,136 | 5,136 | 2 | Tall small-paned windows, the lit one with Benedikt Orme's shelf of tablets; the school bell, a bench. |
| The cistern and its house | 2 | 2,578 | 1,568 | 2 | A round basalt tank 9 m across, dark water, the measuring staff, two rain channels; the pump house with the level slates. |
| The peat barn | 1 | 4,364 | 4,364 | 2 | Three open bays, two stacked to the plate, one drawn down in steps; a sledge. |
| The Crown's thorn and bench | 2 | 901 | 751 | 2 | One wind-bent thorn leaning north-east, inside its 2 m lot; a thwart on two blocks. |
| Quay wall and edge, the Fish Steps | 29 | 20,824 | 900 | 1 | Lengths of at most 12 m; the landing and its flight. |
| Retaining walls | 102 | 52,566 | 712 | 1, 2 | Along the drops between levels. Pass 2: a 1 m parapet where a street or lane runs along the top. |
| Flights | 19 | 10,960 | 736 | 1 | The plan's stairs, with the treads the game walks on. |
| Plot walls | 18 | 13,164 | 732 | 1 | Dry stone, a hurdle in the gap. |
| The Strand's dressing | 26 | 25,499 | 1,427 | 1 | Net racks, barrels, creels, bollards, quay lamps, the boat, the peat stack, floats and cullet. |
| Cinder Row's dressing | 12 | 4,483 | 720 | 2 | The blowpipe rack, crucible stacks, the four heaps of cullet (amber nearly out), ash sacks, the handcart, the trough, Halvard's bench at the mouth. |
| The Rows' backs, the Ladder's corners, walled gardens and the rest of layout pass 1's enclosures | 114 | 78,576 | 3,641 | layout-1 | Layout pass 1's 114 fixtures ([Cullet's layout](CULLET_LAYOUT.md)): walls and what stands inside them, each written out by the plan. Built by `gen_enclosure`; they go through the same export passes and checks. |
| The Hanger's trees and stumps | 9 | 4,246 | 716 | 2 | Six wind-bent forms, all leaning north-east, and three stumps of the old wood, round the woodward's yard. |
| The open lots' own ground | 21 | 13,000 | 1,060 | 2 | No floors (the ground is the plan's): a root plot's ridges of root tops, the Cone yard's kerb, ruts and ash, the slip's skids and capstan, the graveyard's glass markers (one cobalt). Without a model the client draws an open lot as a pale slab. |
| The engine's structures in Cullet's look | 8 | 4,403 | 1,426 | 2 | The kerb sign, the covered cart of the common store, the fire basket, a household's fire box, the lamp, and what stands at the Cone's mouth, the Batch's oven and a smokehouse's door. |

3 lots have no model yet and are drawn as grey boxes: turf house, hanger cottage, lintel. Every open lot has a model now (without one the client draws it as a pale slab).

## Lots, fixtures and structures

A lot's model is found as before: the plan's `model` goes into the land and the `lot` row, and the client draws that file when it is on disk. Each kind of thing has its own folder, so an unbuilt lot never borrows another's model.

A **fixture** is a model that stands at a point of the land and is not a lot. The plan lists them (`fixtures`, written by `cullet_plan.py`, kept out of the seed). The generator builds each and writes `envs/cullet/fixtures.json` in land metres. The game client places them ([authored plans, the game client](AUTHORED_PLANS.md#the-game-client)). **Open lots people walk on are fixtures too**: the Fish Steps and the Marver's terrace (the client keeps its camera out of every lot's model and fades a low one when you stand by it). **So is the Heron's jib**: it reaches 9 m out over the harbour, past the lot, and a lot's model must stand inside its lot. Pass 2's dressing is all fixtures, each placed by `cullet_plan.py` from the lots and spots it belongs to, so it followed them when layout pass 1 moved 59 lots. That pass ([Cullet's layout](CULLET_LAYOUT.md)) walled the yards behind the Rows and filled them (privies, lean-tos, butts, washing, hens, beds, canes: `gen_enclosure`), so the lean-tos, privies, rain butts, washing lines, hen coops and canes this pass had built for the same ground were taken out again: one yard cannot hold both.

A **structure model** is what the client draws for one of the engine's own structures in this environment (`plan.json` `structures`; `envs/cullet/<kind>/*.glb`, origin on the ground at the structure's place, front to the street). The laptop's `ground-1` adds the lookup (a structure on a land world takes its settlement's environment's model, else the old procedural mesh). The kit supplies three, after the laptop's walk found the generic ones reading as brown huts:

- `sign/sign.glb`: a painted board hanging from an iron bracket on a spar at the kerb, its back (+Y) to the building. It is a kerb sign and not a board on the wall because the engine stands a sign 0.5 m outside its building's lot and 1.5 m east of the lot's middle, and Cullet's walls stand 0.5 to 0.95 m inside their lots (the Cone's is round): a board modelled against a wall would float before most of them. A true wall sign needs the sign's distance to the wall per building; the buildings that should carry their name on the façade can take it in their own models instead.
- `storage/storage.glb`: the common store in the Counting House yard: a handcart under a tarred cloth, crates and two barrels.
- `campfire/campfire.glb`: an iron fire basket on three stones, peat in it; the fire is on `GlowAmber`, for the client's lit rule.

The rules and the authority know nothing of fixtures, so:

- People walk through the dressing. It is placed against walls, in yards and on the quay's edge, out of the walking lines.
- A flight's treads are the client's own (the plan's stair: its footprint, and round(rise / 0.18) treads). The generator builds each flight to exactly that.

No SpacetimeDB table, reducer, view or subscription was designed or changed in either pass, so no SpacetimeDB documentation applied. The seed's lots carry a model path, a seed and (pass 2) their lit windows; the rules ignore the last.

## The ground

Pass 1 stood on the island's yellow cobbles and bright lawn. Pass 2 paints Cullet's ground and says where each surface lies; drawing it is the laptop's `ground-1` ([game brief](GAME_BRIEF.md#ground-per-environment-2026-11-11)), built to this interface in parallel (agreed 2026-11-11 through the dev-box coordinator) and merged to main the same day. This pass's final stills are on the merged client.

**How the client chooses ground.** One texture array, painted by `living/tools/textures/paint.py` (`GROUND`, in `terrain.rs` `NAMES`). Per vertex, `island.rs` weights layers and picks a colour from the terrain class, the region and the climate; a road takes its settlement style's paving. Nothing was chosen per environment.

**Nine new layers** in `paint.py`'s `GROUND`, after `gravel` and before `cliff` (25 in all; `ground-1` matches layers by name, so the order of merging does not matter):

| Layer | Tile (m) | What is painted |
|---|---:|---|
| `slate_setts` | 3.2 | Basalt setts a third of a metre deep in courses, a paler path where feet go, moss in the untrodden joints |
| `quay_flags` | 4.8 | Flags a metre deep and up to 1.5 m long, some split, wet in their hollows (the height channel: puddles gather there), rust streaks |
| `cinders` | 2.6 | Clinker and ash trodden flat, crumbs of burnt brick, chips of glass |
| `kelp_shingle` | 3.4 | Wet shingle with straps of kelp lying the way the tide left them |
| `wet_sand` | 5.0 | Firm ripples, wet in the troughs, worm casts, shell |
| `peat` | 4.0 | A cut face: the spade's banks, root fibre, drying cracks |
| `heather` | 3.6 | Cushions of heather, some in bloom, moor grass and bog cotton between |
| `worked_soil` | 3.2 | Spade-wide ridges, clods, kelp dug in, shell grit |
| `thin_turf` | 4.0 | Short wind-combed moor grass, the basalt showing through in lichened patches |

Each is detail round mid-grey, as the others are; the colour comes from the map.

**The map** is the keys of `ground` in [`living/game/assets/envs/cullet.json`](../living/game/assets/envs/cullet.json) that hold a colon, beside its four old keys. `cullet_plan.py` writes them (`GROUND_MAP`) and its `--check` covers them. A value is `{"layer": <name>, "colour": [r, g, b], "tint": [r, g, b]}`: sRGB 0 to 255, the tint optional (the macro variation leans toward it). Every colour is a palette colour of SMALL_CITY §1 or a mix of two. The client looks a vertex up most specific first, and anything unmapped keeps today's rules, so the island is unchanged:

| Order | Key | From | Cullet's entries |
|---|---|---|---|
| 1 | `street:<surface>` | the plan's `streets[].surface`, on a road tile | `setts`, `quay_flags`, `flags`, `cinders`, `earth`, `sand` |
| 2 | `area:<surface>` | an area of `envs/cullet/ground.json` (below) | `quay_flags`, `setts`, `cinders`, `earth`, `worked_soil`, `peat`, `kelp_shingle`, `white_sand` |
| 3 | `stamp:<ground>` | a relief stamp's `ground` | `sand` (the Wrack Strand: wet sand) |
| 4 | `class:<Terrain>` | the rules' terrain class | `Road` (the paved square), `Sand`, `Dirt` (bare peat), `Rock`, `Drop`, `Wall`, `Low`, `Forest`. Grass and Water are left out on purpose |
| 5 | `region:<kind>` | the region | `meadow` (thin turf), `highland` (heather: the Moss), `beach` (kelp shingle), `forest` (the Hanger) |

**Areas.** Class and region cannot say that the whole quay is flags, that Cinder Row's yard is cinders or that a root plot is dug soil: those are grass tiles of the meadow. So the plan has `grounds`: 147 polygons, each with a surface and a cause, later ones on top (the quay, the slip and dock yard in setts, Cinder Row, the mole, each Row's sill and kerb in setts, the ground inside each of layout pass 1's enclosures as its `ground` says (a court's setts, a yard's earth, a plot's dug soil), the 18 root plots, the Sand Spit, the wrack line, the 18 peat cuttings). They are kept out of the seed, as fixtures are, and the generator writes them in land metres to `envs/cullet/ground.json`: `[{"id", "surface", "area": [[x, z], ...], "cause"}]`. `ground-1` reads that file and draws areas with crisp edges, as roads are.

**What the client needed** (all in `ground-1`; nothing in `terrain.rs`, `island.rs` or `envs.rs` was edited here): 25 layers matched by name, so six blend attributes where there were four; the lookup above for the current environment; the areas file; tile sizes for the nine layers (the table above; `paint.py` `TILE_M`). A level's own surface (`levels[].surface`) was considered and dropped, because a level is too coarse (the strand level holds the quay, the slip and Cinder Row); the areas say it instead.

Judged first as painted layers and as a plan view of which surface lies where, then in the game once `ground-1` was merged. One colour was changed for what the game showed: the thin turf's base, moor grass with 12% basalt, read mustard beside the setts, and is now 32% basalt.

## Two decisions of pass 2

The dev-box coordinator decided both on 2026-11-11, answering pass 1's open questions.

**Retaining walls.** A 1 m parapet where a street or lane runs along the top of a drop, so the edge reads as one people would not step off; the 0.4 m coping, a wall to sit on, elsewhere. `cullet_plan.py` decides per section: a street or lane of the upper level whose middle runs parallel to the drop within 10 m of it, over more than half the section. Each wall records its `coping_m` and `coping_cause`. Of 102 sections, 78 carry a parapet (12 along the upper walk, 10 along Low Row, 8 along Mid Row, 8 along High Row, 7 along Mid Row walk, 7 along High Row walk, 6 along Low Row walk, 6 along the Ladder's second walk, 6 along the Ladder's fourth walk, 6 along the Ladder's sixth walk, 1 along the Cinder Steps' head, 1 along the Crown path) and 24 keep the coping: the Crown's own edge (11), the walls that face east at the ends of the Rows and of the Ladder's terraces (9), two short lengths where no street runs, and the two under the Marver's terrace, which has its own rail. The parapet is the wall carried up in the same courses with a walk side, under a 0.14 m capping; at 1 m it is below the eye, so it does not hide.

**Lit windows.** A window is a static model, so each house shows one fixed evening. It shows 0 to 2 lit windows for a cause its household gives (`lots[].lit`: the windows and the cause in words); empty houses are dark. Before, every lived-in house showed one to three. The causes, in order:

- **Night workers.** Thessaly Marl (Low Row 10) stokes the Cone by night: the kitchen lamp is left for her and a night light burns above for Wick, who is five. Anselm Faro keeps the Watchglass: the lamp house is lit below and above.
- **The bakers.** Pieter Achterberg rises at 02:30 to fire the Batch: the Marver shows one window, the one over the hearth.
- **By family.** A Kiln house has someone on the evening watch at the Cone two times in three, and then the kitchen lamp waits. A Strand house rises with the tide and is dark, save one in four where someone mends by lamplight. A Ladder house, done at 16:00, sits up in every second one. Benedikt Orme reads by lamp at the Readers' House.
- **A full house** (four or more) has someone still up above, two times in three.

"Two in three" and the like are the lot's recorded seed, never a roll. Of 22 households, 8 are dark, 9 show one window and 5 show two; the 7 empty row houses are dark. Gable attic lights, rooflights and back windows are no longer lit. The Counting House keeps its one tally-room lamp.

## Sight from model data

eye-2 (on main) lets a model hide by its real shape at eye height: `buildings.py` `eye_record` measures the share of the view blocked through each 0.5 m square of the footprint between 1.2 and 1.8 m, and `host::hosted_map` makes a lot's tile `Wall` only where a square blocks at least 80%, else `Low` (it stops the foot, not the eye). Cullet's lots were not in the table, so each hid by its plan height, throughout.

Pass 2 does both things the brief offered. The generator calls `B.eye_record(obj, width, depth)` for every lot's model and records `eye_solid` and `eye_cells` in `report.json`; it writes each folder's footprint sidecar (`gen-<folder>-cullet.json`), so `buildings.py --table` carries Cullet with the other sets; and a full run merges the 88 lots that have a model into `living/rules/data/buildings.json` as style `cullet` in `write_table`'s own form (every other set's entries are kept; the file round-trips byte for byte). Fixtures are not in the table: the rules do not know them.

On the quay (`sight_census`, eye at the arrival point (540.5, 766.5), 48 m, eye height 1.6 m): **1,225 of 4,241 points hidden before, 1,182 after**, on the plan as pass 1 left it. After layout pass 1 moved the lots the same run gives 1,371 hidden by height and 1,321 by shape, of 4,187. The Counting House hides on 270 of its 360 tiles (its arcade is open), the roofless shell of Low Row 9 on 17 of 40. The gain is small because the quay's own buildings are mostly closed; it is larger where fronts stand open (Cinder Row, the boatshed) and was not measured there. The land's height and layout digests are unchanged by the table; the hosted tiles' digest changes (tiles under open fronts are now `Low`), so the authority and the client must both be built from this table, as after any table change. A client connected to a scratch world built from it reports all three digests matching.

## The checks

`living/tools/cullet_kit_check.py` reads the GLB files, not the generator's own report, except for where the doors are and where each roof's ridge is.

| Check | How | Result (2026-11-11, pass 2) |
|---|---|---|
| Coplanar | No two triangles of a model lie in one plane (within 1 mm) and overlap | 432 of 432 |
| Doors | Each door is 0.9 × 2.0 m, and the mesh has the leaf's four corners there | 40 of 40 |
| Footprint | Nothing above the floor stands more than 0.1 m outside the lot's, fixture's or structure's rectangle | 432 of 432 |
| Height | The ridge is within 0.1 m of the plan's `height_m` (lots) | 88 of 88 |
| Materials | Only `Body` and `Glow*` | 432 of 432 |
| Palette | Every vertex colour is a palette colour within 0.056, or lies between two | 432 of 432 |
| Same seed, same output | A second generation is byte-identical | 432 of 432 |
| Surfaces | At least 90% of lit triangles carry a surface tag | 432 of 432 |
| Triangles | Within the budget of SMALL_CITY §6 (ground pieces and dressing: §7's prop budgets) | 432 of 432 |

How four of them are read:

- **Footprint is what stands above the floor**, as `buildings.py` measures it. Foundations, sea walls and the Fish Steps' flight go down below their floor, and the sea walls and the flight lie outside their rectangle there: a lot must lie on its level, and the water is not one.
- **Height is the roof**, not the chimney. A row house's stack and pots stand 1.3 to 2 m above the plan's height; the tree in a shell rises above its walls.
- **Palette allows a blend of two palette colours**, because wear is one palette colour laid over another (soot is tar over brick). A colour that is neither fails.
- **Coplanar** counts pairs of triangles of one model whose planes coincide within 1 mm and whose areas overlap (a shared edge is not an overlap), facing the same way or opposite ways. It passes at zero.

### The flicker at a gable

On the first walk the owner saw a sawtooth flickering where a gable met its roof edge. Reproduced in the asset view on Mid Row 4's east side: the half stack on a party wall had its outer face in the party wall's own plane, and where the neighbour is lower or roofless (Mid Row 3 is a shell) that wall shows, so brick and limewash fought for depth in a sawtooth under the stack. The checker found the same kind of thing all through pass 1: 60 to 800 same-facing coplanar overlaps a model (flakes of lime laid over one another at one offset, panes, planks against posts) and hundreds more back to back. Fixes, all in the generator and none by depth bias: the stack now stands 3 cm proud of the party wall; two-sided sheets are two faces 3 mm apart; the three export passes above remove what is hidden and part what is left. The kit went from the counts above to zero on every model. Before and after stills are on the kit-2 page.

## Layout pass 1: enclosures

Added 2026-11-11 (branch `layout-1`, [Cullet's layout](CULLET_LAYOUT.md)). The plan now writes 114 **enclosures**: a rectangle, its walls and its contents, each with its cause. One generator, `gen_enclosure`, builds exactly what is written. It is a section of its own in `cullet.py` and changes none of the functions above it.

- **Walls** (`e_wall`): `dry` (rough basalt, each stone its own height), `coped` (coursed, with a coping) or `stub` (a pulled-down house's wall, falling along its length, old limewash on its inner face), with gaps, driftwood gates and boarded gaps. One quad a stone. Neighbouring enclosures share a wall: each builds its west wall, and its east wall only at a terrace's end, so no two faces lie in one plane.
- **Contents** (35 kinds, `c_privy` to `c_ash_sacks`): privies, lean-tos, a shed roofed with an upturned boat, peat stacks, rain butts, washing (blown north-east), hen runs with hens, dug beds, herb and flower squares, boats on trestles, nets on poles, wrack heaps and racks, cold frames, slates, cut stone, crucibles, cullet crates and a cullet-edged bed, timber and ship's knees, a handcart, a barrow, barrels, creels, benches, weeds, rubble, a standing hearth, flags, the bread board, a sundial, a trough, the ropewalk, cane wigwams, a door step, ash sacks.

| Folder | Models | Triangles | Budget each |
|---|---:|---:|---:|
| `yard` | 30 | 24,872 | 3,000 |
| `back_plot` | 39 | 21,478 | 3,000 |
| `toft` | 5 | 5,954 | 3,500 |
| `walled_garden` | 7 | 10,884 | 3,500 |
| `oven_court` | 1 | 1,314 | 3,500 |
| `drying_green` | 2 | 4,882 | 4,000 |
| `wind_wall`, `ladder_corner`, `ropewalk`, `quarry_bench`, `graveyard_wall`, `sill`, `wynd_washing` | 30 | 11,176 | 600 to 3,000 |

The plan now has 102 lengths of retaining wall (was 116: fewer and shorter drops) and 19 flights (was 17). With them alone (before pass 2 was merged) the kit was 363 models and about 401,000 triangles; with pass 2 it is the count at the top of this file, and the enclosures go through pass 2's export passes and its coplanar check. An enclosure's `ground` field (setts, earth, worked soil, quay flags) is read by pass 2 into an area of its rectangle ([the ground](#the-ground)). Weak: walls do not block (fixtures never do); hens stand still; washing is stiff; the courts' privies are all one privy.

## What is weak

Seen in the game's renderer on 2026-11-11:

- **Grey on grey.** With the ground drawn, setts, flags, walls and basalt ground floors sit within a few steps of value of one another at 13:00. The palette asks for 70% dark stone, but paving and walls now merge at a distance; limewash, doors and glass carry all the contrast.
- **No kerb line or gutter.** A Row's street, its sill under the parapet and the strip before the doors are one field of setts. Kerbs and gutters (SMALL_CITY §6, P0) are not built.
- **Area edges are straight.** A yard's earth, a bed's soil and the turf beside them meet on a ruled line, as the plan draws them. Layout pass 1's enclosures are read into areas whole, walls included.
- **The ground was tuned late and little.** The layers were painted before the client could draw them. In the game the thin turf was changed twice (it read mustard, then ochre) and is still the least convincing layer; tile sizes and strengths were not tuned at all; the Moss, the Wrack Strand and the Sand Spit were looked at only in the plan view.
- **The Heron's jib points at the default camera** (south, over the water), so from the quay the beak reads only from the side. The crane house and the jib fade apart, since one is a lot's model and one a fixture.
- **A working building's room is a shallow dark box** (1.3 to 4.6 m deep). The lehr's banked arch is a flat glowing shape at the back of it.
- **Big gables are bare.** The lehr house, the Store and the boatshed show 10 to 14 m of blank basalt and lime with one small window.
- **A shell's inside is hard to see** from the game camera: the walls that make it a shell hide the hearth, the rafters and most of the thorn.
- **Glasshouses are still opaque**, so Jory's tree and Cora's flowers show only through holes, vents and the door. The eight patched houses are still alike.
- **The Hanger is not the kit's yet.** The six wind-bent forms stand round the woodward's yard, on the one level ground there. The wood's own trees are the engine's `tree` resources, drawn with the client's models, and a fixture cannot stand on a slope (it is placed at the `floor` it is given). Needed from the client: Cullet's `tree` resources drawn from `envs/cullet/hanger_tree/`, and a fixture with no `floor` standing on the ground.
- **A hearth stands in the street at every lived-in door.** Connected to a scratch world, the engine's structures draw with the kit's models (the yard's lamp, store and fire basket; the kerb signs; the oven's trestle at the Batch). The 22 household hearths are placed half a metre outside each lot, so each fire box sits on the setts beside the stoop. It reads as a cooking fire at the door, but a hearth belongs indoors, and that is the plan's placing, not the model's.
- **Dressing does not block**, and nobody sits: fixtures are presentation only.
- **Smoke** from the Cone, the stacks, the smokehouses' louvres and the lehr is an effect the client does not have.
- **Three lots are still grey boxes** (the turf house, the Hanger cottage, the Lintel), and the Counting House yard, where a newcomer arrives, has no market dressing.

## Pass 3

In this order:

1. **The three grey boxes left**: the turf house on the Moss, the Hanger cottage, the Lintel. `gen_cottage` already builds a free-standing home; both need its one-storey form, and the turf house a turf roof.
2. **Walk the ground and tune it.** The layers were judged as paintings and as a plan view before the client drew them; their tile sizes, strengths and colours need a pass in the game at the camera's height, the cinders and the thin turf first.
3. **The market under the arcade and the square**: trestle tables, fish slabs, root baskets, the tally board, the counters table (SMALL_CITY §6, P1). The Counting House yard is the arrival point and is still bare.
4. **Seats and solid dressing**, once the client seats people: Halvard's bench, the Crown bench, the Batch's bench and the doorstep benches as the plan's spots; and the dressing that should block (barrels, the handcart, heaps).
5. **The Rows' fronts**: flower boxes for the Ladder families, boot scrapers, a cat, chalk marks; doorstep benches for the houses with elders.
6. **The Ladder**: cold frames and pane crates on the terraces above the lowest two, the kelp heaps as their own fixtures, a wheelbarrow.
7. **Nature**: heather and bog cotton as scatter on the Moss, kelp heaps and drying racks on the Wrack Strand, the kelp kilns (P2), weir stakes and jetties, basalt rocks and the Combs.
8. **The Crown**: glass grave markers in the graveyard, a sundial (P2).
9. **Signs on their buildings**: the Counting House's and the Marver's names carved or painted on the façades themselves, so the kerb sign is only for buildings without one.

**On the asset board** ([asset board](ASSET_BOARD.md); `living/assets/board/`, tracks `kit-1` and `kit-2`). Pass 2 is the latest version of the eleven families pass 1 left on the board, and starts nine more (layout pass 1's `place:` families are its own):

| Family | Members |
|---|---|
| `building:cone`, `building:counting-house`, `building:watchglass` | one model each; unchanged in design (hidden and coplanar faces removed) |
| `building:glasshouse` | `glasshouse` (4, now with Cora's flowers), `glasshouse_sound`, `glasshouse_broken`, `glasshouse_tree` (9, Jory's tree; new member) |
| `building:row-low` | `row`: Low Row's east terrace joined for the board (`gen_cullet.sh --join "Low Row east"`) |
| `building:row-houses` | `tarn`, `pontil`, `greave`, `morrow`, `empty`, `shell` (Low Row 9, the thorn), and new members `marl` (the night stoker's lit house) and `shell_plain` (Mid Row 3) |
| `building:mole`, `building:net-loft`, `building:marver`, `prop:strand` | as pass 1 |
| `prop:ground` | `quay`, `fish_steps`, `wall` (now with its parapet), `stairs`, `plot_wall`, and new member `wall_coping` |
| `building:heron` (new) | `heron`, `jib` |
| `building:lamp-house` (new) | `lamp_house` |
| `building:cinder-row` (new) | `lehr_house`, `pot_house`, `cullet_shed`, `ash_house`, `wash_house` |
| `prop:cinder-row` (new) | `blowpipe_rack`, `crucible_stack`, `heap_aqua`, `heap_amber`, `ash_sacks`, `handcart`, `trough`, `bench` |
| `building:strand-works` (new) | `batch`, `smokehouse`, `store`, `boatshed`, `dry_dock` |
| `building:crown` (new) | `readers_house`, `cistern`, `cistern_house`, `peat_barn`, `thorn`, `bench` |
| `prop:open-lots` (new) | `root_plot`, `cone_yard`, `slip`, `graveyard` |
| `prop:hanger` (new) | `tree_1` to `tree_6`, `stump` |
| `prop:structures` (new) | `sign`, `storage`, `campfire`, `hearth`, `lamp`, `furnace`, `oven`, `smokehouse_fire` |

Published 2026-11-11 from commit `8e52115f`. The owner has not decided on any of these versions.

## Verification (2026-11-11, pass 2)

All on the dev-box, on the tree with `origin/main` merged (through layout-1, `3c73d835`).

- `gen_cullet.sh` twice and `cullet_kit_check.py --again`: 432 of 432 on every check, the coplanar check and byte identity among them. Layout pass 1's 114 fixtures are in that count and pass the coplanar check after the export passes.
- `cullet_plan.py --check` and `author_world.py cullet --check` (0 errors): the seed keeps its 64 residents, 22 homes, the ways and town life and rates-2's 34 structures.
- `set -o pipefail; just living-check` exits 0 (authority WASM, mind, both observers, the game client, the script gate, `cargo test -p living-rules`), with a private target directory and 12 jobs.
- verify-generation on the dev-box's own container (`kit2-stdb`, SpacetimeDB 2.14.1, port 3322), because the model table changed. `generation-kit2-20261111-195631` (`--feature worlds --seeds island,plan-test,cullet,floor-megacity-2k,floor-megacity-4k`, before layout-1): island 979, plan-test 78, floor-megacity-2k 77 and floor-megacity-4k 92 checks pass, their `land` digests equal `floor_preview`'s. Cullet failed 4 of 317 there, and the same 4 on a clean checkout of `origin/main` (`6a31176a`): four residents dead of old age six seconds after creation and the laws overlay not matching, which main fixed the same evening (goods-2: the verify launch keeps a seed's laws again). On the final tree, `generation-kit2c-20261111-204204` (`--seeds cullet,plan-test`): **cullet 317 of 317 and plan-test 78 of 78**, original seeds unchanged. Among Cullet's checks: its 93 lots in order with their kinds, sizes, models, heights and level floors; blocking lots on wall, low or drop tiles; land digests and the arrival point equal to the native generator's.
- `sight_census` on `living/seeds/cullet.json` before and after the table change (1,225 and 1,182 hidden of 4,241; heights and layout digests equal). Run before layout-1 moved the lots; not repeated after.
- The game client connected to a scratch Cullet world on the same container, from the merged tree, through verify-ui's driver (`ui-kit2c-1111-204510`, a fresh player, no minds): the client's log says the land's three digests match the authority's; stills of the Counting House yard, the Batch, Low Row and Mid Row show the lots, fixtures, ground and the engine's structures in the kit's models. A walk for pictures, not a run of verify-ui's scenarios.
- The game client, headless, look-dev: stills of the quay, the Strand, a wynd, each Row, the Batch, the Crown, the Cone, Cinder Row, the mole and the Ladder at 13:00, 18:30 and 21:30, beside pass 1's; a contact sheet of 49 models through the asset view with a 1.75 m figure; Mid Row 4's gable before and after. The page is `.local/kit-2/index.html` on the dev-box.

Not covered: frame time or memory with the larger kit; verify-core (no rule changed; the table changes which tiles hide, which verify-generation's digests and tile checks cover); the Moss, the Wrack Strand, the Sand Spit and the Hanger in the game.

Pass 1's verification (its own generation, connected client and look-dev runs) is in this file's history at `d6794f79`.
