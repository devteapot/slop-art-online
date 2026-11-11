# Cullet's kit

Started 2026-11-11 (branch `kit-1`, phase 3 of [the small city](SMALL_CITY.md#8-build-plan)). Fable 5.2 wrote it, starting from its A/B arm (`ab-arm1`), as the owner decided (decision 12). This is pass 1: the P0 list of SMALL_CITY §6.

**Status.** 261 models, about 338,000 triangles, built for their places from [Cullet's plan](AUTHORED_PLANS.md#cullets-plan). All 261 pass the checks below. Judged in the game's renderer, in look-dev (the land of `living/seeds/cullet.json`, the `cullet` mood) at 13:00, dusk and 21:30. Not yet walked by the owner. Not a performance result: no frame times were measured.

## Run it

```bash
python3 living/tools/cullet_plan.py            # the plan and the seed, when cullet_plan.py changed
living/tools/blender/gen_cullet.sh             # every model, fixtures.json and report.json (about 20 s)
python3 living/tools/cullet_kit_check.py       # the checks, on the GLB files themselves
```

Two runs on one machine give byte-identical files (all 263: the models, `fixtures.json` and `report.json`; dev-box, Blender 5.2.2). Another machine or Blender version has not been compared: the geometry and colours follow from the plan alone, but the exporter's bytes are Blender's. A machine without Blender can take the dev-box's generated folder as a tarball instead (unpack it at the repository's root).

`gen_cullet.sh --only cone,low_4,retaining_wall` builds some models (ids or folders). `--out DIR` writes elsewhere; `--figure` stands a 1.75 m figure by each model, for contact sheets only. `just living-game-assets` runs the generator with the other kits. The output, `living/game/assets/envs/cullet/`, is git-ignored: the scripts are the asset.

## How it is built

- **One script**, [`living/tools/blender/cullet.py`](../living/tools/blender/cullet.py), on `buildings.py`'s helpers, as `city.py` is. Metres, +Z up, fronts to −Y, colour per vertex on one `Body` material with the surface tag in alpha, glowing parts on `Glow` (oil lamps), `GlowAmber` (the furnace) and `GlowCyan` (the Watchglass).
- **A model for each place.** The script reads `plan.json` and builds one model for each lot and each fixture that it has a generator for, at the path the plan names (`cullet/<folder>/<id>.glb`). Footprint, height and level come from the plan. So does wear: `salt`, `soot`, `wind`, `age`, `repair` and `empty`, each with its cause. A model's origin is the middle of its lot's rectangle; it is never re-centred, so a terrace's houses meet at their party walls.
- **The only random numbers** come from the `seed` the plan records for the lot (which stone is a shade darker, where a flake of lime lies). The same plan gives byte-identical files.
- **Compass.** A model's front looks along its lot's `facing`. `Env` turns compass bearings into the lot's own frame, so lichen and flaked lime lie on the faces the south-westerly strikes, whichever way the lot faces.
- **Terraces are built as rows.** Each house is its own model on its own lot, laid out with its neighbours: they share a party wall (each model carries its half) and the stack on it (half each, as high as the taller roof needs). A house's width is its household's size, its storeys its family's, its door its household's colour, and what stands by the door is the household's keepsake from the plan. The Rows follow the slope's contours, so a row's floors are level; the roof line steps where storeys differ. The rank of net lofts is built the same way.
- **Glow** was set in the game, not in Blender. The game's emission is the material's strength times exposure times the hour's `glow` (three times stronger at night). `buildings.py`'s strength of 2.6 does not show on daytime glass colours. The kit's strengths (220 for oil lamps, 300 for the furnace, 240 for the Watchglass) read as lit at 21:30 and leave a pane its own colour at 13:00.
- **A glasshouse's light is its one lantern's** (the dev-box coordinator's call, 2026-11-11: glow is sparse and true to what is lit). Every pane within 1.0 m of the lantern strip is lit; out to 2.4 m fewer and fewer catch a dimmer light (`GlowDim`, 80); beyond it a pane keeps its glass colour. That is 8 to 12 lit and 15 to 21 dim panes of 342 in a worked house, and none in a broken one. The two distances are generator parameters: `gen_cullet.sh --lantern-core M --lantern-reach M`. The first version lit every pane within 2.6 m of two pools, which was nearly the whole of a sound house.

## What pass 1 builds

| What | Models | Triangles | Notes |
|---|---:|---:|---|
| The Cone | 1 | 10,258 | 14 m across, 24 m. Two mouths lit, the third's door half open on the glow. The pot room is in the lot's south-west corner and the stair winds up the east flank, so everything stays inside the 14 m lot. |
| The Counting House | 1 | 11,814 | 30 × 12 m. Seven open arches, the tally room's seven windows, a hipped roof, the cupola's clock at ten past four. |
| The Watchglass | 1 | 2,974 | An eight-sided shaft 4 m across under a lantern room 5 m across: 320 panes in facets, one band of cobalt. |
| The mole | 5 | 15,766 | Root, three 13.3 m sections of the arm, tip. Sea walls with the tide line, a wave wall east, ship's bollards west, the tip's rail with its south spans gone. |
| Row houses | 24 | 51,338 | Six terraces: 17 lived in, 4 empty and sound, 3 roofless shells (one with a tree). 1,120 to 3,245 each. |
| The Marver and its terrace | 2 | 7,580 | Three serving hatches, the hearth, the figurehead; tables, benches and an anchor over the drop. |
| Glasshouses | 14 | 95,624 | One generator, three states from `repair`: 3 sound, 8 patched, 3 broken. The panes near a worked house's lantern glow. |
| Net lofts | 6 | 7,888 | One rank. Double doors of two 0.9 × 2.0 m leaves. |
| Quay wall and edge | 28 | 20,608 | Lengths of at most 12 m. The face stands 0.5 m out over the water. |
| The Fish Steps | 1 | 904 | The landing stands on the lot; the flight goes down into the water south of it. A fixture (below). |
| Retaining walls | 116 | 62,086 | Along the six drops, between the flights. |
| Flights | 17 | 11,472 | The plan's stairs, with the treads the game walks on. |
| Plot walls | 18 | 13,716 | Dry stone, a hurdle in the gap. |
| The Strand's dressing | 27 | 26,559 | Net racks, barrels, creels, bollards, quay lamps, the boat, the peat stack, floats and cullet. |

22 lots have no model yet and are drawn as grey boxes: the Heron, the two smokehouses, the Store, the boatshed, the dry dock, the wash-house, the lehr house, the pot house, the cullet shed, the ash house, the lamp house, the Batch, the cistern and its house, the Readers' House, the thorn, the Crown bench, the peat barn, the turf house, the Hanger cottage and the Lintel. The slip, the Cone yard and the graveyard are open lots with no model and no height, so nothing is drawn there.

## Lots and fixtures

A lot's model is found as before: the plan's `model` goes into the land and the `lot` row, and the client draws that file when it is on disk. Each kind of thing has its own folder, so an unbuilt lot never borrows another's model.

A **fixture** is a model that stands at a point of the land and is not a lot. The plan lists them (`fixtures`, written by `cullet_plan.py`, kept out of the seed). The generator builds each and writes `envs/cullet/fixtures.json` in land metres. The game client places them ([authored plans, the game client](AUTHORED_PLANS.md#the-game-client)). This was the one client change of the pass: 20 lines in `island.rs` and a small reader in `envs.rs`. **Open lots people walk on are fixtures too**: the Fish Steps and the Marver's terrace. The client keeps its camera out of every lot's model and fades a low one when you stand by it, which suits a building; connected to a world, the Fish Steps' landing vanished under the player. So those two lots name no model, and a fixture stands on each lot's rectangle. The lots stay for their names and spots.

The rules and the authority know nothing of fixtures, so:

- People walk through the Strand's dressing. It is placed against walls and on the quay's edge, out of the walking lines.
- A flight's treads are the client's own (the plan's stair: its footprint, and round(rise / 0.18) treads). The generator builds each flight to exactly that.

No SpacetimeDB table, reducer, view or subscription was designed or changed. The seed's 73 lots with a model now fill the existing `model` column of their `lot` rows.

## The checks

`living/tools/cullet_kit_check.py` reads the GLB files, not the generator's own report, except for where the doors are and where each roof's ridge is.

| Check | How | Result (2026-11-11) |
|---|---|---|
| Footprint | Nothing above the floor stands more than 0.1 m outside the lot's or fixture's rectangle | 261 of 261 |
| Height | The ridge is within 0.1 m of the plan's `height_m` (lots) | 48 of 48 |
| Doors | Each door is 0.9 × 2.0 m, and the mesh has the leaf's four corners there | 30 of 30 models, 37 doors |
| Triangles | Within the budget of SMALL_CITY §6 (ground pieces and dressing: §7's prop budgets) | 261 of 261 |
| Surfaces | At least 90% of lit triangles carry a surface tag | 261 of 261 (all 100%) |
| Palette | Every vertex colour is a palette colour within 0.056, or lies between two | 261 of 261 |
| Materials | Only `Body` and `Glow*` | 261 of 261 |
| Same seed, same output | A second generation is byte-identical | 261 of 261 |

How three of them are read:

- **Footprint is what stands above the floor**, as `buildings.py` measures it. Foundations, sea walls and the Fish Steps' flight go down below their floor, and the sea walls and the flight lie outside their rectangle there: a lot must lie on its level, and the water is not one.
- **Height is the roof**, not the chimney. A row house's stack and pots stand 1.3 to 2 m above the plan's height.
- **Palette allows a blend of two palette colours**, because wear is one palette colour laid over another (soot is tar over brick). A colour that is neither fails.

## What is weak

Seen in the game's renderer on 2026-11-11:

- **The ground is not Cullet's.** Streets are yellow cobbles and everything else is bright lawn. The kit's basalt and lime stand on a meadow. The Cone's yard should be cinders, the Strand wet flags, the Crown moor grass. Ground textures are on §6's P0 list and were not in this pass.
- **Glasshouses are opaque.** Panes are drawn solid in pale aqua, so the plants inside show only through holes, vents and the door. See-through glass is a client feature.
- **Patched glasshouses are alike.** The eight share one pane census. Their holes fall in different bays by seed, but from the game camera they read as one model eight times.
- **A lit pane is paler by day** than its unlit neighbours. The game's emission has a day to night ratio of 3; a pane that glows at night keeps a little of it at noon.
- **Row houses are plain behind.** Backs have two windows and no yards, lean-tos or privies (P1).
- **The Marver's figurehead is small** from the game camera, and its front is in shadow most of the day (it faces south under its own shutters).
- **Retaining walls are long and bare.** One dark face with a coping and weep holes. They need the Rows' dressing against them.
- **The Fish Steps' landing sits on the level's flat ground**, a 3 m tongue into the harbour, and the flight begins at its seaward edge. A cut into the quay would need the plan's level changed.
- **The quay's coping covers 1.5 m of the quay**, to hide the ground's own bank at the level's edge.
- **Dressing does not block.** People walk through barrels and net racks.
- **Jory's fruit tree and Cora's flowers** (glasshouses 9 and 4) are in the plan's notes and not in the models.
- **Smoke** from the Cone and the stacks is an effect the client does not have.

Client behaviour met, not changed: tall models between the camera and the figure fade (the Watchglass from the mole, the Cone from its yard); the kit's own contact sheet was shot before the asset view could show night, so glow was judged in the city stills; the asset board's shots (below) have night. The first stills were taken while the camera's fog closed about 90 to 110 m out; the final ones follow the laptop's `view-1` (fog by the mood, 180 to 600 m), so the Cone, the Counting House and the Rows are seen from the mole and from over the harbour. The long view also shows how bare the slope still is: lawn between the Rows, long dark walls, 22 grey boxes.

## Pass 2

In this order:

1. **Ground textures**: setts, quay flags, cinders, wet sand, peat and heather. Nothing else changes the city's look as much.
2. **The Heron**, the last landmark (P1), and the lamp house beside the Watchglass.
3. **Cinder Row**: the lehr house, the pot house, the cullet shed, the ash house and the wash-house against the Cone, with the Cone yard's dressing (cullet heaps, Halvard's bench).
4. **The rest of the working buildings**: smokehouses, the Batch (it stands in Low Row's west terrace as a grey box), the Store, the boatshed, the dry dock and hull, the Readers' House, the cistern, the peat barn.
5. **The Rows' backs and dressing**: lean-tos, privies, hen coops, washing across the wynds, rain butts, doorstep benches.
6. **Roofless shells** deserve their own pass: fallen roof timbers, a hearth still standing.
7. **The Ladder**: plants seen through gaps, Jory's tree, cold frames; then nature (the thorn, heather, kelp).
8. **Seats**: benches, stoops and the Fish Steps as the plan's spots, once the client seats people.

**On the asset board** ([asset board](ASSET_BOARD.md); `living/assets/board/`, track `kit-1`, published 2026-11-11 from commit `368e2af4`). This pass is the latest version of the four families the A/B arm started, beside their accepted versions, and starts seven more:

| Family | Members |
|---|---|
| `building:cone` | `cone` |
| `building:glasshouse` | `glasshouse` (a patched one, as the accepted version was), `glasshouse_sound`, `glasshouse_broken` |
| `building:row-low` | `row`: Low Row's east terrace, five houses joined into one model for the board only (`gen_cullet.sh --join "Low Row east"`); the game draws each house as its own model |
| `prop:strand` | the eight props, the first of each on the Strand |
| `building:counting-house`, `building:watchglass` (new) | one model each |
| `building:mole` (new) | `root`, `arm`, `tip` |
| `building:row-houses` (new) | `tarn`, `pontil`, `greave`, `morrow`, `empty`, `shell`: single houses as the game draws them |
| `building:net-loft` (new) | `loft_end`, `loft_mid` |
| `building:marver` (new) | `marver`, `terrace` |
| `prop:ground` (new) | `quay`, `fish_steps`, `wall`, `stairs`, `plot_wall` |

The board's night shots are the asset view's first of this kit. They showed the sound glasshouse glowing over nearly all its panes; `building:glasshouse` was published again from `78b8f3a2` with the lantern's falloff. The owner has not decided on any of these versions.

Open questions for the owner's walk: whether the retaining walls' 0.4 m coping should be a 1 m parapet; whether lit windows should be this many (every lived-in house shows one to three).

## Verification (2026-11-11)

- `gen_cullet.sh` twice and `cullet_kit_check.py --again`: 261 of 261 on every check.
- `set -o pipefail; just living-check` exits 0 after merging `origin/main` (bible-1, goods-1, drop-1, view-1, the residents, ui-1 and the asset board, then the character track's `buildings.py`), at `f7efd158`: authority WASM, mind, both observers, the game client; `cargo test -p living-rules` 158 passed, 8 ignored. The kit generated on that tree is byte-identical to the one before the merge.
- verify-generation `--feature worlds --seeds cullet,plan-test` on the dev-box's own container (`kit1-stdb`, SpacetimeDB 2.14.1, port 3316), run `generation-kit1b-20261111-165531`: cullet 65 and plan-test 72 checks pass, `land` digests equal `floor_preview`'s, original seeds unchanged. The seed changed only in what its lots carry (a model path and a seed each, the glasshouses' repair). After the last merge, with main's 64 residents in the seed, `generation-kit1c-20261111-173034`: cullet 301 and plan-test 72 pass.
- The game client, headless, connected to a scratch Cullet world on the dev-box's own container (`kit1-stdb`, SpacetimeDB 2.14.1): the land's digests matched the authority's, the `lot` rows drew their models or boxes and the fixtures stood with them, on the quay, Low Row, a wynd, Mid Row, the Cone and the mole. Repeated with `view-1` merged. Since `view-1` an open lot without a model draws as a footprint slab, so the Cone yard is a flat taupe rectangle before the Cone.
- The game client, headless, look-dev: stills of the quay, the net lofts, a wynd, each Row, the Crown, the Cone, the mole and the Ladder at 13:00, 18:30 and 21:30; a contact sheet of 31 models through the asset view with a 1.75 m figure. The page is `.local/kit-1/index.html` on the dev-box.
