# Authored plans: a settlement laid out by hand

Started 2026-11-11 (branch `plan-1`, Cullet phase 2's engine part; [the small city](SMALL_CITY.md#8-build-plan), decision 10). A land seed can now describe a settlement as written: its ground levels at exact heights, its streets, stairs, square, harbour and every lot with its model and height. The generator lays the rest of the land round it and steps aside for it. Nothing in the engine knows about Cullet: a plan is seed data, read by general code.

**Status.** Implemented and verified on scratch databases on the dev-box (SpacetimeDB 2.14.1 in its own container, `plan1-stdb`). The test seed is [`living/seeds/plan-test.json`](../living/seeds/plan-test.json): a 9-lot harbour town on seed 3 at 1024 m. A first rough [`living/seeds/cullet.json`](../living/seeds/cullet.json) has the Strand, three Rows, the Crown, 16 wynd flights and 65 boxes on the same land; it is a format check at Cullet's scale, not the authored city. Seeds with no `plans` produce byte-identical lands (`host::tests::pinned_digests_hold`).

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

Anything else (`wear`, `door_colour`, `keepsake`, notes for the asset generator) is ignored by the engine and is not digested, so the plan file can carry the asset generator's inputs.

## What the generator does with it

1. **Relief.** `land::hydro_pass` pulls the macro relief toward each plan's ground within `blend_m` of its levels, and sinks its `sea` polygon below sea level, before the sea, lakes and rivers are found (`settle::plan::stamp_macro`). Islets and lake basins keep away from plans.
2. **Site.** Each plan is one fixed site, placed before the generated ones (which keep their usual distance from it), with `Site::plan` set, so `Site::id()` is the plan's id.
3. **The `Plan` step** of the planner (`settle::Staged`, only when the land has plans), right after the city step:
   - the plan's tiles: its levels are open land (water, rock and trees give way), its sea is water;
   - its ground ([`settle::plan::Ground`](../living/rules/src/settle/plan.rs) in `Land::height`'s modifications, applied before roads and pads): each level flat at its height; a smooth, steep drop inside a lower level where a higher one meets it; the outer edge blended into the natural ground over `skirt_m`, except over water, where a quay stands straight out of the sea (it falls to the bed within 0.5 m). It is continuous everywhere;
   - its streets as roads at the ground's height, ending at the square (`RoadEnd::Plaza`) where they touch it;
   - the settlement (`Settlement::planned`), its square as the plaza, its lots (contiguous, in plan order), its stairs as sloped pads and `stairs` props, and `retaining_wall` props along the drops.
4. **Everything else steps aside.** Street, lot, stair, terrace and ornament generation skip planned settlements; road profiles and road shaping leave their streets alone; their lots are their models' footprints exactly (no style margin, so terraced houses share walls with no gap). `terrace::paint_drops` walls every drop no one can step up (more than 0.8 m between neighbouring tiles) inside a plan as on terraces, except beside water.
5. **Island roads** never route through a plan's levels or harbour. When a plan has a `trunk` street, the network starts from it, and roads from the other settlements join it where it leaves the town; that is how they reach the square. Without one, the other settlements connect among themselves.

`Land::plans` (`settle::Laid`) keeps each planned lot's id, name and spots, and each street's road id and surface, for the authority. It is not digested.

## Refusals

`settle::validate_plans(plans, size)`, called by the authority's `island::params_of`, so `create_floor` and `init` refuse a bad plan before anything is generated or written. It refuses: duplicate ids (plans, levels, streets, stairs, lots); anything outside the land; levels that overlap each other or the sea; references to unknown levels; a lot off its level, on a street or on a stair; overlapping lots (sharing a wall is fine); a stair whose rise disagrees with the levels it joins, whose foot or head is off its level, or that climbs more than 1 m per metre; a square off its level; a bad `facing`. After generation, hosting refuses a plan whose building doors no one can reach on the hosted tiles (`settle::stranded_doors`).

## The authority

The plan rides in `land.params` and the existing rows; no table, column, reducer or view changed.

- **Homes by lot.** A seed town on a plan may give `homes`: household key → lot id. Those households live at that lot's door and own its house. The others take the remaining houses, nearest the square first, as before. Without `homes`, nothing changes.
- **Named buildings at a lot.** `buildings[].lot` puts the building's sign at that lot's door, and the building is the lot's own structure when it is of the same kind (its owner set), else a structure of its kind there. Without `lot`, it is placed near the centre as before.
- **Places by lot.** A `town_life` place or `work` kind `lot:<id>` is that lot's spots (each resident takes the nearest of the least used, as for other spots), else its door. `PlannedLot.key` and `PlannedLot.spots` are in memory only.

## The game client

- A lot whose model is not on disk, and that has no model of its kind in its environment, is drawn as a plain grey box of its footprint and `height_m` (`island::GreyBox`). The client fills the box from the `lot` row's `width_m` and `depth_m`.
- A planned settlement's stairs and retaining walls without models are grey treads (0.18 m each) and grey walls.
- A flight's tread heights come from the prop: a modelled flight is `buildings.py`'s `prop_stairs` (17 treads over 3 m by 5 m, as before); a flight without a model takes its width and run from the prop and its rise from the ground at its head.
- A lot without a model path uses its settlement's style's environment (`settle::env_of`, which now knows `cullet`), not its site kind's.
- The mood is the environment whose `world` names the `land` row's seed and size, else the first world environment (as before). `envs/cullet.json` is Cullet's mood: fog 180 to 600 m on a clear day, `world` seed 3 at 1024 m. The camera still sets the fog distance it draws from its own draw radius (`camera.rs` `follow`), so the long view is not on screen yet; that belongs to the client's owner.

## Authoring the full Cullet plan

For the later task that writes Cullet's 65 lots:
- Keep the plan in `living/seeds/worlds/cullet/plan.json` and merge it into `living/seeds/cullet.json`'s `map.params.plans` (the rough seed was written by a throwaway script; replace it).
- Coordinates as in SMALL_CITY: origin at the Fish Steps, x east, y north (uphill). Choose `origin` and `rotation_deg` so the Strand's south edge lies on the coast; the `sea` polygon forces the harbour either way.
- Give each row its own level and the drop between rows will be walled; join levels by stairs (the wynds) or by a street that leaves the levels (the skirt is walkable where it is gentle).
- Terraced houses: put neighbours' rectangles edge to edge (sharing a wall is allowed); leave a gap at least a stair's width at each wynd.
- Every building's front must face walkable ground within half a metre (its door); validation and hosting say which door is stranded.
- Lots on the Counting House's arcade, the market and the Marver's seats are places through `spots`; name them in `town_life` as `lot:<id>`.
- The Moss, the Hanger, the Lintel and the Wrack Strand lie outside the town: either more plans (each is a site), or generated sites through `sites`, or plain land with resources. The Watchglass on the mole needs a thin `mole` level reaching into the harbour; the `sea` polygon must then leave it out.
- One mood per land: `envs/cullet.json`'s `world` must name Cullet's final seed and size.

## Not done, and next steps

- **A see-through drop.** Drops are `Wall` tiles, and the authority is 2D: `Wall` and `Rock` block sight (`map.rs`), so 48 m sight does not cross the Rows' retaining walls. A `Drop` terrain class (unwalkable, transparent) would fix it. Cost: a ninth `Terrain` value through `map.rs` (`from_u8`, `walkable`, opacity), every exhaustive match on terrain in rules, authority, viewer and game client (tile colours), verify-generation's tile check (`max(t) <= 7`), `paint_drops` writing it in plan zones only (so other lands keep their digests), and a perception check in verify-core. About half a day with verification; not done here.
- **Spots as more than places.** Spots feed `lot:<id>` places; nothing yet seats a person at a spot or lets a client know where they are (SMALL_CITY "Places need spots").
- **Streets that cross levels** are drawn at the ground's height, so a street across a drop is a cliff; use stairs, or split the street at the level's edge.
- **Height in the rules.** The ground's levels are presentation and tiles; the rules still move and see in 2D.

## Verification (2026-11-11)

- `set -o pipefail; just living-check` exits 0 (authority WASM, mind, both observers, game client, rules tests); `cargo test -p living-rules`: 139 passed, 7 ignored, including `host::tests::pinned_digests_hold` (island seed 7 at 2048 m: tiles `9b403da95bba9407`, heights `0d2f77752781845c`, layout `8ff57472b004a13f`; megacity floor at 2048 m: `db59549c884bf8b8`, `c06f16f3dcac1290`, `0c6b3f2c51f13129`, unchanged from `6593f725`) and the plan tests in `settle::plan::tests` (frame, validation, lay-out as written, continuous ground with walled drops, repeatability).
- verify-generation `worlds` on `island`, `plan-test`, `floor-megacity-2k` and `floor-megacity-4k`, with `land` digests compared against `floor_preview`, plus `create_floor` refusing a plan whose stair disagrees with its levels. Evidence under `.local/living/verify/generation-plan1b-*`; see [verify-generation's validation](../.agents/skills/verify-generation/references/validation.md).
- verify-core `town.py` on an island world (`core-plan1-town-20261111-135920`): 22 of 23, the failure being the scene's recorded flake (facing someone who comes up behind). The island does not use `homes` or `lot:` places; this checks that the changed `town::seat` and households code leave it as it was.
- The real game client, headless: look-dev on plan-test (`LIVING_GAME_LOOKDEV=1`, the `cullet` environment) and connected to a scratch plan-test world, walking from the square up the stair to the row and to house_a's door through `human_act goto`; digests matched the authority's. Stills under `.local/living/plan-1/`.

SpacetimeDB documentation consulted (live pages read 2.0.0; the service and crates are 2.14.1): [tables](https://spacetimedb.com/docs/tables/), [table performance](https://spacetimedb.com/docs/tables/performance/), [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/), [default values](https://spacetimedb.com/docs/tables/default-values), [reducer lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/). What follows from them here: no schema change was needed (the `lot` row already has `width_m` and `depth_m`), so no migration; the plan travels inside the existing `land.params` string, which every client subscribes to whole at connection (one row; the pages state no row-size limit, and a 65-lot plan is tens of kB, sent once); `init` failure prevents publishing, so a bad plan refused in `params_of` leaves no world behind, and `create_floor` refuses before it keeps the seed.
