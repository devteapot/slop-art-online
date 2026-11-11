# Authored plans: a settlement laid out by hand

Started 2026-11-11 (branch `plan-1`, Cullet phase 2's engine part; [the small city](SMALL_CITY.md#8-build-plan), decision 10). A land seed can now describe a settlement as written: its ground levels at exact heights, its streets, stairs, square, harbour and every lot with its model and height. The generator lays the rest of the land round it and steps aside for it. Nothing in the engine knows about Cullet: a plan is seed data, read by general code.

**Status.** Implemented and verified on scratch databases on the dev-box (SpacetimeDB 2.14.1 in its own containers, `plan1-stdb` and `plan2-stdb`). The test seed is [`living/seeds/plan-test.json`](../living/seeds/plan-test.json): a 9-lot harbour town on seed 3 at 1024 m. Since 2026-11-11 (branch `plan-2`) [`living/seeds/cullet.json`](../living/seeds/cullet.json) is the authored city: Cullet's 93 lots (65 buildings) on the Wrack, an island shaped by an [authored coastline and relief stamps](#authored-land-the-coast-and-stamps), written by [`living/tools/cullet_plan.py`](../living/tools/cullet_plan.py) ([below](#cullets-plan)). Seeds with no `plans`, no `relief.outline` and no `relief.stamps` produce byte-identical lands (`host::tests::pinned_digests_hold`).

## The format

A plan is an entry of `map.params.plans` (`living_rules::settle::PlanSpec`). Coordinates are metres in the plan's own frame: x east, y north (uphill, for Cullet), from `origin`. `origin` is a point on the land (land metres: x east, y south). `rotation_deg` turns the plan's north to that compass bearing on the land. The conversion uses `living_rules::det` trigonometry only, so the authority and every client derive the same land.

```json
"map": {"kind": "land", "size": 1024, "params": {
  "sites": [{"kind": "village", "min": 2, "max": 2, "per_km2": 0.0, "radius_m": 50.0, "spacing_m": 300.0, "scale": 1.0, "flatten": 0.75}],
  "plans": [{
    "id": "plan_test", "kind": "town", "style": "cullet",
    "origin": [575, 888], "rotation_deg": 15,
    "levels": [
      {"id": "quay", "height_m": 2.5, "area": [[-40, 0], [40, 0], [40, 24], [-40, 24]]},
      {"id": "row",  "height_m": 6.5, "area": [[-40, 24], [40, 24], [40, 54], [-40, 54]]}
    ],
    "sea": [[-60, -70], [60, -70], [60, 0], [-60, 0]],
    "square": {"level": "quay", "area": [[-12, 2], [12, 2], [12, 14], [-12, 14]], "paved": true},
    "streets": [
      {"id": "the row", "points": [[-38, 40], [38, 40]], "width_m": 4.0, "class": "street", "surface": "setts", "level": "row"},
      {"id": "the road out", "points": [[38, 40], [55, 62], [72, 96]], "width_m": 3.6, "class": "trunk"}
    ],
    "stairs": [{"id": "the steps", "from": "quay", "to": "row", "foot": [32, 18], "head": [32, 28], "width_m": 2.4, "rise_m": 4.0}],
    "lots": [
      {"id": "hall", "kind": "hall", "name": "the Tally Hall", "at": [0, 19], "size": [16, 9], "facing": "south", "level": "quay",
       "model": "cullet/hall/tally.glb", "height_m": 14.0, "landmark": true,
       "spots": [{"name": "under the arch", "at": [-4, 5.5]}]},
      {"id": "house_a", "kind": "house", "at": [-20, 32.5], "size": [6, 9], "facing": "north", "level": "row", "height_m": 8.5, "door_colour": "oxblood"}
    ]
  }]
}}
```

| Field | Default | Meaning |
|---|---|---|
| `id` | required | The site's seed id: `towns[].site` names it, as `town` or `steampunk_town` name generated sites. Unique across plans. |
| `kind`, `style` | `town`, required | The settlement's kind and `settlement.style`: the client's asset folder (`settle::env_of`; `cullet` is `envs/cullet/`). |
| `origin`, `rotation_deg` | required, 0 | The frame (above). |
| `scale` | 1 | Inhabitants' height relative to a 1.75 m adult. |
| `drop_m` | 0.6 | Width of the drop where a level meets a lower one. The ground falls inside the lower level, along its edge. |
| `skirt_m` | 10 | Width over which the plan's outer edge blends into the natural ground (never over water). |
| `blend_m` | 60 | How far round the levels the land's coarse relief is pulled toward them, so the hill meets the town gently. |
| `sea_depth_m` | 6 | Depth stamped inside `sea`. |
| `levels[]` | at least one, at most 64 | `id`, `height_m`, `area` (a polygon), `retaining` (default true: retaining walls stand along its edges where the ground falls more than a step below it). Levels may share edges; they may not overlap. |
| `sea` | none | A polygon forced to sea before the water is found (a harbour). It must reach the open sea to be sea, and may not overlap a level. |
| `square` | required | `level`, `area` (inside that level), `paved` (default true). The settlement's square: its centre is the settlement's centre and newcomers' arrival. |
| `streets[]` | none | `points`, `width_m`, `class` (`trunk`, `street`, `lane`, `path`; default `street`), `surface` (for clients; the rules do not read it), `level` (if given, every point must lie on it). Streets lie on the plan's ground as written: no grading, no shoulders. |
| `stairs[]` | none | `from` (lower level), `to` (higher level), `foot` (on `from`) and `head` (on `to`), `width_m` (2.4), `rise_m` (if given, it must equal the levels' difference within 5 cm), `model`. A flight rises at most 1 m per metre. |
| `lots[]` | none | `id` (unique), `kind` (a `LotKind`: `house`, `townhouse`, `inn`, `hall`, `chapel`, `workshop`, `barn`, `tower`, `well`, `market_stall`, `lamp`, `garden`, `field`), `name`, `at` (centre), `size` (width along the front, depth), `facing` (a bearing in degrees, or `north`, `east`, `south`, `west`), `level`, `model` (under the client's `envs/`; none: a box), `height_m` (6 for a building, 0 for a garden or field), `landmark`, `spots`. |
| `lots[].spots[]` | none | Named points (`name`, `at`): metres to the right of the lot's front as one faces out, and forward from its centre toward its front. |
| `resources[]` | none | Resources at authored points (`kind`, `at`, in the plan frame; anywhere on the land, not only on levels): fishing spots on a quay's edge, the trees of a copse. The authority places those of kinds the rules know (`catalog::kind_class` is `Resource`) at the nearest walkable tile when the world is created; the others stay in the plan, unplaced and logged, until their kinds exist. |

Anything else (`wear`, `door_colour`, `keepsake`, notes for the asset generator) is ignored by the engine and is not digested, so the plan file can carry the asset generator's inputs.

## Authored land: the coast and stamps

A land the generator's noise cannot make (an island of a given shape, a plateau here, a beach there) is drawn with two fields of `map.params.relief` (`living_rules::land::Relief`), in land metres (x east, y south). Both are general: any land seed may use them, and a land that uses neither is unchanged.

| Field | Default | Meaning |
|---|---|---|
| `outline` | none | The coastline as a polygon: the land is this shape instead of the warped ellipse round the main range. `coast_warp` (here a fraction of half the side) and `coast_feature` still roughen it. Inland, the plain rises to `lowland_m` over `outline_rise_m` (default 150) from the coast, as `tanh`. |
| `stamps[]` | none | Applied in order after the generated relief, islets and lake basins, and before the plans. Each has an `area` (polygon) and any of: `height_m` (the coarse ground inside is that height, fading into the ground round it over `blend_m`, default 40; a negative height makes shallows or a reef); `region` (a `RegionKind`: the land inside is of that kind, so its trees, beach width, rocks and dirt follow that kind's look); `ground` (`grass`, `sand`, `dirt`, `rock` or `forest`: the tiles inside are that, wherever they are not water). `id` and other fields are for the author. Lake basins keep off stamps (their area plus `blend_m`). |

`land::validate_relief`, called by the authority's `island::params_of` with the plans' checks, refuses an outline or a stamp area of fewer than three finite points, a non-finite height or a negative blend, a stamp that sets nothing, and an unknown `ground`.

What a stamp's height cannot do: it fades on every side, so a high stamp near the coast also lifts the sea floor round it (the north headland of the Wrack is a hill partly because of that). The height is the coarse (8 m) ground; the tiles' own relief (`regions.looks[].detail_m`) still rides on it.

Two things the seed already offered and Cullet needed, found while authoring it:
- A share of `regions.looks[].trees` of 0 still puts forest tiles here and there (the tile rule's noise reaches below 0); a treeless kind takes a negative share.
- `water.lakes_per_km2` of 0 still places one lake basin where the ground allows; stamps covering the land keep it off.

## What the generator does with it

1. **Relief.** `land::hydro_pass` pulls the macro relief toward each plan's ground within `blend_m` of its levels, and sinks its `sea` polygon below sea level, before the sea, lakes and rivers are found (`settle::plan::stamp_macro`). Islets and lake basins keep away from plans.
2. **Site.** Each plan is one fixed site, placed before the generated ones (which keep their usual distance from it), with `Site::plan` set, so `Site::id()` is the plan's id. Its radius holds every level, outlying ones included; unlike a generated site it does not clear forest and rock in that disc (its levels are opened by the `Plan` step), so a plan with outlying lots leaves the land between them as it is.
3. **The `Plan` step** of the planner (`settle::Staged`, only when the land has plans), right after the city step:
   - the plan's tiles: its levels are open land (water, rock and trees give way), its sea is water;
   - its ground ([`settle::plan::Ground`](../living/rules/src/settle/plan.rs) in `Land::height`'s modifications, applied before roads and pads): each level flat at its height; a smooth, steep drop inside a lower level where a higher one meets it; the outer edge blended into the natural ground over `skirt_m`, except over water, where a quay stands straight out of the sea (it falls to the bed within 0.5 m). It is continuous everywhere;
   - its streets as roads at the ground's height, ending at the square (`RoadEnd::Plaza`) where they touch it;
   - the settlement (`Settlement::planned`), its square as the plaza, its lots (contiguous, in plan order), its stairs as sloped pads and `stairs` props, and `retaining_wall` props along the drops.
4. **Everything else steps aside.** Street, lot, stair, terrace and ornament generation skip planned settlements; road profiles and road shaping leave their streets alone; their lots are their models' footprints exactly (no style margin, so terraced houses share walls with no gap). `terrace::paint_drops` makes every drop no one can step up (more than 0.8 m between neighbouring tiles) a `Drop` tile inside a plan as on terraces, except beside water: no one walks across it, everyone sees across it ([perception](PERCEPTION.md#drops-sight-across-ground-levels); before 2026-11-11 it was `Wall`).
5. **Island roads** never route through a plan's levels or harbour. When a plan has a `trunk` street, the network starts from it, and roads from the other settlements join it where it leaves the town; that is how they reach the square. Without one, the other settlements connect among themselves.

`Land::plans` (`settle::Laid`) keeps each planned lot's id, name and spots, each street's road id and surface, and the plan's authored resources on the land, for the authority. It is not digested.

## Refusals

`settle::validate_plans(plans, size)`, called by the authority's `island::params_of`, so `create_floor` and `init` refuse a bad plan before anything is generated or written. It refuses: duplicate ids (plans, levels, streets, stairs, lots); anything outside the land; levels that overlap each other or the sea; references to unknown levels; a lot off its level, on a street or on a stair; overlapping lots (sharing a wall is fine); a stair whose rise disagrees with the levels it joins, whose foot or head is off its level, or that climbs more than 1 m per metre; a square off its level; a bad `facing`. After generation, hosting refuses a plan whose building doors no one can reach on the hosted tiles (`settle::stranded_doors`).

## The authority

The plan rides in `land.params` and the existing rows; no table, column, reducer or view changed.

- **Homes by lot.** A seed town on a plan may give `homes`: household key → lot id. Those households live at that lot's door and own its house. The others take the remaining houses, nearest the square first, as before. Without `homes`, nothing changes.
- **Named buildings at a lot.** `buildings[].lot` puts the building's sign at that lot's door, and the building is the lot's own structure when it is of the same kind (its owner set), else a structure of its kind there. Without `lot`, it is placed near the centre as before.
- **Places by lot.** A `town_life` place or `work` kind `lot:<id>` is that lot's spots (each resident takes the nearest of the least used, as for other spots), else its door. `PlannedLot.key` and `PlannedLot.spots` are in memory only.
- **Authored resources** (`Hosted.resources`) are inserted as `resource_node` rows when the world is populated (`seed::plan_resources`, before a town's promised `resources` are topped up, so those count them), in one call or as the last step of a staged creation. A seed that wants only its authored resources of a kind sets that kind's `resource_scale` to 0, so the wild spawn adds none.

## The game client

- A planned settlement's lot draws its own model (`model`) when it is on disk. Otherwise it is a plain grey box of its footprint and `height_m` (`island::GreyBox`, from the `lot` row's `width_m` and `depth_m`), or, for an open lot of no height (Cullet's Fish Steps, slip, Cone yard, Marver's terrace, graveyard and root plots), a 2.5 cm slab of its footprint in a darker stone. It never borrows another model of its kind, so a missing or empty `envs/<style>/` folder simply leaves the grey city (`island::lot_item`, since `view-1`). Lots of generated settlements still sample their kind's models.
- A planned settlement's stairs and retaining walls without models are grey treads (0.18 m each) and grey walls.
- A flight's tread heights come from the prop: a modelled flight is `buildings.py`'s `prop_stairs` (17 treads over 3 m by 5 m, as before); a flight without a model takes its width and run from the prop and its rise from the ground at its head.
- A lot without a model path uses its settlement's style's environment (`settle::env_of`, which now knows `cullet`), not its site kind's.
- **Fixtures** (2026-11-11, `kit-1`). A planned settlement's kit may list models that stand at a point of the land and are not lots: a quay's wall, the walls and flights of its drops, street dressing. The kit's generator writes `envs/<env>/fixtures.json` (`file`, `kind`, `at` in land metres, `front`, `floor`, `height`, optionally `light` and `glow`), and the client places each whose file is on disk (`envs::fixtures`, `Island::build`, in look-dev and connected alike). When a kit lists fixtures, the grey stand-in treads and walls are not drawn: the kit brings its own. A flight's feet still follow the plan's stair (its footprint and 0.18 m treads), so a kit's flight must be built to that. Fixtures are presentation: the rules, the authority and the seed know none of them.
- **Ground per environment** (2026-11-11, `ground-1`; [game brief](GAME_BRIEF.md#ground-per-environment-2026-11-11)). The environment's `ground` object may carry a map: `street:<surface>` (a plan street's `surface`: Cullet's `setts`, `quay_flags`, `flags`, `cinders`, `earth`, `sand`), `class:<Terrain>`, `region:<RegionKind>`, `stamp:<ground>` and `area:<surface>`, each `{"layer", "colour", "tint"}`. The kit's generator may write `envs/<env>/ground.json`, areas of surface (polygons in land metres, later on top) for ground the rules know nothing of (a cinder yard, a quay's flags beyond its streets, root plots). The client looks up street, then area, stamp, class and region, and falls back to the island's rules; edges of streets and areas are crisp. Presentation only, like fixtures. A kit's large fixtures keep the camera out (`Solid`), what you stand on (a flight, a terrace) never fades, landmarks are never faded for hiding you, and lots' and fixtures' glow follows the world's `daylight` law.
- The mood is the environment whose `world` names the `land` row's seed and size, else the first world environment (as before). `envs/cullet.json` is Cullet's mood: fog 180 to 600 m on a clear day, `world` seed 83 at 1024 m. Since `view-1` the camera fogs by the mood, and landmarks (`landmark: true`) are drawn out to its `fog_end` ([game brief](GAME_BRIEF.md#view-distance-and-the-grey-city-2026-11-11)).

## Cullet's plan

Phase 2 of [the small city](SMALL_CITY.md#8-build-plan) (2026-11-11, branch `plan-2`). The source is [`living/tools/cullet_plan.py`](../living/tools/cullet_plan.py): it computes every lot, its height and its asset generator inputs, and writes [`living/seeds/worlds/cullet/plan.json`](../living/seeds/worlds/cullet/plan.json) (the plan, with the fields the engine ignores) and [`living/seeds/cullet.json`](../living/seeds/cullet.json) (seed 83 at 1024 m: the land, the plan merged into `map.params.plans`, a town with five named buildings and no people). Edit the script, not the files; `--check` says whether they are current. `living/game/assets/envs/cullet.json`'s `world` names seed 83 at 1024 m.

**The frame.** Origin at the Fish Steps, x east, y north (uphill), rotation 0; `origin` (510, 784) puts the island's middle on the map's middle.

**Levels.** The Strand at +2 m (the quay, x −75 to 75 and y 0 to 10, the strand buildings behind it, the slip and dry dock west, Cinder Row east up to y 62), the mole at +2 m (with its 13 m tip 60 m out), Low, Mid and High Row at +5.5, +9.5 and +13.5 m (bands 28 to 30 m deep, streets 9 m into each, so a 6.5 m walk overlooks the drop), an upper terrace at +17 m, and the Crown level at +20 m (the Crown east of x −55, the root plots west of it). Three outlying pads at their stamped ground: the turf house's yard on the Moss (+32), the Hanger cottage's (+14) and the Lintel's on the north headland (+46).

**Lots.** 93: 65 buildings as SMALL_CITY §2 counts them (27 houses, 4 landmark buildings, 20 working buildings, 14 glasshouses) and 28 open lots (18 root plots, the Fish Steps, the slip, the dry dock, the Cone yard, the Marver's terrace, the graveyard, the thorn, the Crown bench, the cistern, the Lintel). Landmarks (`landmark: true`) are the Cone, the Counting House, the Heron, the Watchglass and the Lintel only. Open lots other than the root plots are `lamp` lots of no height (named, with spots, drawn by nothing until their models exist): a `garden` lot is planted with berry bushes, which suits the root plots for now and nothing else. The Fish Steps and the Heron stand in notches cut out of the quay's edge, off the quay street.

**Terraces.** 24 row houses in six terraces of 3 to 5 (Low Row 1–5 and Batch + 6–10, Mid Row Marver + 1–4 and 5–7, High Row 1–4 and 5–7), numbered from the Cone's end, sharing walls. A front's width is 4.5 m plus 0.4 m for each person past the first and 0.5 m for a Kiln house (the best plots), at most 6.5 m; empty houses keep the 5.0 m of the original plots, shells 4.8 m. Depth 7.5 m; two storeys of 2.9 m (Kiln), 2.7 m (the Ladder's growers) or 2.6 m (Strand) on a 0.4 m plinth, roofs at 47°, so ridges are 9.3 to 10.2 m; the three roofless shells are 5.9 m walls. Households are lot fields (`household`, `household_name`, `family`, `people`, `address`, `door_colour`, `keepsake`) from SMALL_CITY §3; there are no residents (their sheets are phase 5). Empty: Low Row 3, Mid Row 6 (the contested house), High Row 4 and 6; roofless: Low Row 9 (a tree inside), Mid Row 3, High Row 7.

**Models, seeds and fixtures** (2026-11-11, `kit-1`; [Cullet's kit](CULLET_KIT.md)). Every lot but the root plots and the two open lots people walk on (the Fish Steps, the Marver's terrace: fixtures, so the client does not treat them as buildings) names its model, `cullet/<folder>/<id>.glb`, with one folder for each kind of thing (`row_house`, `net_loft`, `glasshouse`, `cone`, and so on), so a lot whose model is not built finds no other model in its folder and stays a grey box. Every lot has a `seed` (from its id), the one number its model may roll from. The plan file also carries `fixtures`, kept out of the seed: 28 lengths of quay wall, the mole in five pieces, 116 lengths of retaining wall along the six drops, the 17 flights, 18 plot walls, the Fish Steps, the Marver's terrace and the Strand's 27 pieces of dressing, each with its rectangle, facing, floor, wear and the cause of its place.

**Wear inputs** (`lots[].wear`, from §1's table, never rolled): `salt` = (6 m − floor) / 4 m, clamped; `soot` falls off over 60 m north-east of the Cone (bearing within 90° of 45°), plus a little within 20 m any way; `wind` is 0.55 × how squarely the front faces south-west plus 0.45 × floor / 34 m, less for a terrace's inner houses; `age` and `repair` by history (ship-day buildings 1.0; Kiln houses older and better kept than Strand houses; glasshouses new; the storm's three broken glasshouses 6, 11 and 13 at repair 0.15, the three on the lowest terrace kept whole at 0.9 in the Rows' shelter, the other eight patched at 0.7); `empty` 1 for empty houses and shells. Each lot's `wear.cause` names its height, its distance and bearing from the Cone and its facing.

**Streets and wynds.** The quay 10 m (`the Strand`), the Rows 5 m, lanes 3 to 4 m (the slipway, Cinder Row, the mole, the walks along the Ladder, the upper walk, the Crown path), 2 to 2.5 m paths out of town (the Moss road, the Lintel path, the Hanger path, the strand path). Five wynds: the Ladder Wynd (x −100, all the way to the Crown level), the Net Wynd (x −30) and the Store Wynd (x 66) to High Row, the Tally Wynd from the Counting House yard to the Crown, which dog-legs (its flights at x 24, 32, −8, 34, −8, the Rows between them), and the Cinder Steps from Cinder Row to Low Row's east end. 17 flights rise 3 to 4 m (the Rows' heights fix them) at 0.55 m per metre.

**Spots.** The arcade's seven bays (at its mouth: the rules block its footprint), the Fish Steps (four), the Cone's three mouths and Halvard's bench, the wash-house's warm wall (four), the Batch's oven mouth, the Marver's door and hearth bench and its terrace's six seats, the Watchglass's door, Rafe's place and the mole's tip, the Readers' House's step and bench, the cistern's rim, the Crown bench's two seats, each glasshouse's door and rain butt.

**The land** (the Wrack, docs/SMALL_CITY.md §2): an authored outline about 765 × 555 m in the middle of the map; the plain rises to 12 m over 120 m inland. Stamps: the whole island moor grass (`meadow`); the Moss (`highland`, +30 m, its middle +35 m, about 420 × 190 m); the north headland (+34 m shoulder, +46 m crown: the island's highest ground, so the Lintel shows over the Moss from the town); the Hanger (`forest`, a hollow at +15 m north-east); the Wrack Strand (west of the quay, about 190 × 40 m, `beach`, +0.8 m, `ground: sand`); the Sand Spit (east, about 120 × 40 m, the same); the Weirs (shallows at −0.6 m south-west of the quay); the Combs (a reef at −0.8 m, 150 to 170 m off the south shore). No rivers (`river_catchment_m2` 10⁹), no lakes, no wetlands, no islets, no mountain range (`peak_m` 1 m, no foothills); every region kind but forest has a negative tree share. No other settlement.

**Resources.** Placed now (`plans[].resources`, kinds the rules know): 22 fishing spots (the Fish Steps 2, the quay's edge 4, the mole 6, the Weirs' shore 10), 70 trees in the Hanger on a jittered grid, the clay bank below the Crown. The seed's `resource_scale` turns the wild spawn of those kinds off (and berry bushes), so these are all there are; boulders (0.4) and reeds (0.3) still spawn wild. Waiting in the plan for goods-1's kinds, placed the moment they exist (or moved when their spawning rules want other points):
<!-- resources waiting for their kinds (plan.json `resources`, plan frame):
  kelp   12  the Wrack Strand, a line from (-140, 4) to (-300, 36)
  sand    6  the Sand Spit, a line from (352, 100) to (372, 205)
  peat   18  the Moss, a grid x -150..150 by 60, y 360..440 by 40
  roots  18  one at each root plot's centre
  greens 11  one in each working glasshouse
-->
kelp 12 along the Wrack Strand, sand 6 on the Sand Spit, peat 18 across the Moss, roots 18 (one a root plot), greens 11 (one a working glasshouse). Features for the asset generator (`features`): the four kelp kilns on the Wrack Strand, the Weirs' stakes, the Combs.

**As a city** (`living/tools/cullet_check.py` on a land dump, `living/rules/examples/land_dump.rs`; 2026-11-11):
- Walking at 2.6 m/s on the hosted tiles: the quay end to end 150 m, 58 s; the Fish Steps to the Crown bench 230 m, 88 s (the real client walked it in 79 s over about 220 m, partly on road); to the Readers' House 262 m, 101 s; to the far end of the Wrack Strand 315 m, 121 s; to the Lintel 619 m, 238 s. SMALL_CITY §2 says about 1, 2, 3 and 3 minutes: the quay matches, the Crown is about 1.3 minutes and the Lintel nearer 4.
- Landmarks: the share of street points in town (every 6 m along the plan's streets and lanes) that see 90% of the landmark's height, from a person's eye (1.6 m) and from the game camera's height (about 12 m): the Cone 70% and 93%, the Counting House 80% and 99%, the Heron 71% and 75%, the Watchglass 54% and 98%, the Lintel 11% and 83%. The rules' own 2D sight (Wall and Rock block, terrace drops included) sees them from 2 to 19% of the points: the see-through drop below fixes that (done: `drop-1`; Wall and Rock alone block now). Farthest street point from each: the Cone 416 m, the Counting House 283 m, the Heron 277 m, the Watchglass 439 m, the Lintel 602 m (the far ends of the Ladder's walks and the root plots).
- Every building door is reachable (validation and hosting; `settle::plan::tests::the_cullet_seed_is_valid_and_reachable`, `seed::tests::the_cullet_seed_is_hosted`).

## Not done, and next steps

- **A see-through drop:** done on 2026-11-11 (`drop-1`, [perception](PERCEPTION.md#drops-sight-across-ground-levels)). Drops are `Drop` tiles on every land with them, terraces included, so the island's tile digest moved too.
- **Spots as more than places.** Spots feed `lot:<id>` places; nothing yet seats a person at a spot or lets a client know where they are (SMALL_CITY "Places need spots").
- **Streets that cross levels** are drawn at the ground's height, so a street across a drop is a cliff; use stairs, or split the street at the level's edge.
- **Height in the rules.** The ground's levels are presentation and tiles; the rules still move and see in 2D.
- **Cullet, after phase 2** (what the grey city leaves open):
  - The walk from the quay to the Crown is about 80 s, not §2's 2 minutes; the town is as big as §1 draws it, and the Tally Wynd already dog-legs. More dog-legs or a longer climb would be a design choice for the owner's walk-through.
  - The Ladder spans about 85 × 140 m (five terraces, the top two glasshouses on the Crown's level), not 90 × 90 m; Mid and High Row's west terraces leave 30 m of each row bare between them and the Net Wynd (the lean years' cleared plots).
  - The kelp, sand, peat, roots and greens resources wait for goods-1; berry bushes grow on the root plots as the garden rule's stand-in.
  - The client: fog closes at about 90 m from the camera, so the overview and the landmarks across town are not on screen yet; landmark lots beyond the 190 m lot radius are being drawn by another task; the slip, the Cone yard and the graveyard have no models (they draw as bare ground). Since `kit-1` the quay's edge and face, the Fish Steps and the drops have models ([Cullet's kit](CULLET_KIT.md)).
  - No residents (phase 5), no tide, no sight values for Cullet (phase 4).

## Verification (2026-11-11)

**plan-2** (dev-box, own container `plan2-stdb`, 2.14.1, port 3314; private `CARGO_TARGET_DIR`):
- `cargo test -p living-rules`: the pinned digests hold (island and megacity unchanged), with the new `land::tests::an_authored_outline_and_stamps_shape_the_land`, `settle::plan::tests::the_cullet_seed_is_valid_and_reachable` and `the_test_plans_resources_are_kept_on_the_land`; `cargo test -p living-authority seed::tests` with `the_cullet_seed_is_hosted`.
- verify-generation `--feature worlds --seeds cullet,plan-test,island` (`generation-plan2b-20261111-152231`): cullet 62, plan-test 69 and island 975 checks pass, `land` digests equal `floor_preview`'s, original seeds unchanged; Cullet's 93 authored resources of known kinds stand where written and the 65 of unknown kinds are not placed. Then `authored`, `guards` and `--seeds floor-megacity-4k` (the bad-plan refusal); see [verify-generation's validation](../.agents/skills/verify-generation/references/validation.md).
- The real game client, headless (`.local/living/plan-2/`, contact sheet `index.html`): look-dev stills of the quay, a wynd, each Row, the Crown, the Cone, the mole, the Ladder and an overview (`LIVING_GAME_LOOKDEV=1`, `LIVING_GAME_SEED=living/seeds/cullet.json`); connected to a scratch Cullet world (`verify-plan2-cullet`), the client's regenerated land matched the authority's digests (tiles `a0d5b31a4a93ff47`, heights `bc0680832fd92c40`, layout `18b1e66d0eb92a78`), and a fresh player walked from the Fish Steps to the Crown bench through `human_act goto` in 79 s over about 220 m, then to High, Mid and Low Row, the Cone and the mole's tip.

SpacetimeDB documentation consulted for plan-2 (live pages show 2.0.0; the service and crates are 2.14.1): [reducer lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle/), [tables](https://spacetimedb.com/docs/tables/) and [table performance](https://spacetimedb.com/docs/tables/performance/). No table, column, reducer, view or subscription changed: authored resources are ordinary `resource_node` rows inserted in the same `init` transaction (or the staged creation's last step) as the wild ones, so clients get them by their existing chunk subscriptions; a bad relief or resource is refused in `params_of`, and "failure prevents publishing" (lifecycle), as it did for the published scratch world whose plan was refused during this work. The pages state no per-transaction row limit; Cullet's `init` inserts about 1,300 resource rows in about 1.2 s.

**plan-1:**
**plan-1:**

- `set -o pipefail; just living-check` exits 0 (authority WASM, mind, both observers, game client, rules tests); `cargo test -p living-rules`: 139 passed, 7 ignored, including `host::tests::pinned_digests_hold` (island seed 7 at 2048 m: tiles `9b403da95bba9407`, heights `0d2f77752781845c`, layout `8ff57472b004a13f`; megacity floor at 2048 m: `db59549c884bf8b8`, `c06f16f3dcac1290`, `0c6b3f2c51f13129`, unchanged from `6593f725`) and the plan tests in `settle::plan::tests` (frame, validation, lay-out as written, continuous ground with walled drops, repeatability).
- verify-generation `worlds` on `island`, `plan-test`, `floor-megacity-2k` and `floor-megacity-4k`, with `land` digests compared against `floor_preview`, plus `create_floor` refusing a plan whose stair disagrees with its levels. Evidence under `.local/living/verify/generation-plan1b-*`; see [verify-generation's validation](../.agents/skills/verify-generation/references/validation.md).
- verify-core `town.py` on an island world (`core-plan1-town-20261111-135920`): 22 of 23, the failure being the scene's recorded flake (facing someone who comes up behind). The island does not use `homes` or `lot:` places; this checks that the changed `town::seat` and households code leave it as it was.
- The real game client, headless: look-dev on plan-test (`LIVING_GAME_LOOKDEV=1`, the `cullet` environment) and connected to a scratch plan-test world, walking from the square up the stair to the row and to house_a's door through `human_act goto`; digests matched the authority's. Stills under `.local/living/plan-1/`.

SpacetimeDB documentation consulted (live pages read 2.0.0; the service and crates are 2.14.1): [tables](https://spacetimedb.com/docs/tables/), [table performance](https://spacetimedb.com/docs/tables/performance/), [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/), [default values](https://spacetimedb.com/docs/tables/default-values), [reducer lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/). What follows from them here: no schema change was needed (the `lot` row already has `width_m` and `depth_m`), so no migration; the plan travels inside the existing `land.params` string, which every client subscribes to whole at connection (one row; the pages state no row-size limit, and a 65-lot plan is tens of kB, sent once); `init` failure prevents publishing, so a bad plan refused in `params_of` leaves no world behind, and `create_floor` refuses before it keeps the seed.
