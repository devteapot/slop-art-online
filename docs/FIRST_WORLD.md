# First world: a generic km-scale placeholder

Started 2026-11-08. **This world is a placeholder to change later.** It gives the playable game a believable first place to test scale, travel and landmarks against. It is not the agreed world: the faction geography in [world vision](WORLD_VISION.md) is deferred, and no part of this world is named after a faction or a real company. This note is a design target and a measurement record. Since 2026-11-09 the authority can host this world on scratch databases (seed kind `land`, [`living/seeds/island.json`](../living/seeds/island.json)); the design, storage and measurements are in [island authority](ISLAND_AUTHORITY.md). The game client does not connect to it yet.

## What exists

- **Generator:** [`living/rules/src/land.rs`](../living/rules/src/land.rs). It holds mechanics only. Every size, count and threshold is a field of `LandParams`, which is serde data: a partial JSON object overrides the defaults.
- **Preview:** [`living/rules/examples/land_preview.rs`](../living/rules/examples/land_preview.rs) draws a top-down map, a true-scale cross-section and a text legend with the measured numbers:

  ```bash
  cargo run --release -p living-rules --example land_preview --manifest-path living/Cargo.toml -- SEED SIZE_M OUT_DIR
  ```

- **Tests:** `cargo test -p living-rules land::` covers:
  - determinism;
  - a single walkable component;
  - every region kind and site at 2048 m;
  - a summit of 250–520 m, a river over 800 m long and a lake 100–450 m across;
  - finite, continuous height that follows the water.
- **Settlements and roads:** [`living/rules/src/settle.rs`](../living/rules/src/settle.rs) runs at the end of generation; see [settlements](#settlements-and-roads-2026-11-09).
- [`realm.rs`](../living/rules/src/realm.rs) is unchanged, because the lab's seeds depend on it.

Why a new generator: `realm` sizes its features in tiles. At 2048 m (seed 7) it repeats its half-km patterns, its heights run only −1 to 71 m, rivers mostly vanish, and it always places 4 towns. `land` sizes features in metres: a larger world gets more regions of the same size, longer rivers and a second range.

## How it is built

Two layers, both 1 tile = 1 m:

1. **Macro grid** (8 m cells, 257 × 257 nodes at 2048 m):
   - **Island:** a warped radial falloff, stretched 1.2× along the main range.
   - **Ranges:** one range at every size. From 1.6 km, half the seeds add a second; from 2.6 km every seed does.
     - The main range is a curved spine offset from the centre. One coast is steep; the other side is long and gentle, and that is where the long rivers run.
     - Crest height is 300–480 m. A Gaussian cross-profile and ridged noise give spurs and side valleys, with foothills about 2.2 half-widths wide.
     - Noise octaves are rotated against each other, so value noise's grid does not show as blocks.
   - **Lakes:** 1–6 basins (0.9 per km² of land), each a warped bowl with a rim. One natural depression of suitable size may also become a lake.
   - **Rivers:**
     - Flow is routed by priority flood from the sea, on slightly noisy ground so rivers wander.
     - A stream becomes a river at a 30,000 m² catchment. Tributaries under 350 m are dropped.
     - Levels fall monotonically, so a river cuts through a rim instead of filling the hollow behind it.
     - Valleys rise from the nearest river along a widening cone (slope 0.08 + 0.0016 × distance).
     - Width is 0.009 × √catchment, clamped to 2.5–14 m.
   - **Moisture:** noise, nearby water and a rain shadow behind high ground upwind.
   - **Regions:** warped Voronoi cells 320 m apart (smaller below 2048 m), classified by mean height, slope and moisture.
   - **Sites:** placed by flatness, water and access, then levelled toward their mean ground.
2. **Tiles (1 m):** the existing `Terrain` classes.
   - Water comes from lakes, the sea, rasterised river centre lines and wetland pools.
   - Sand lies on river banks and beaches.
   - Rock covers slopes over 0.85 plus outcrops by region kind.
   - Forest and dirt cover follows per-kind densities, blurred across region borders.
   - A ford (a 3 m sand bar) crosses each river about every 400 m.
   - Connectivity runs last:
     - pockets under 60 tiles are closed, except pockets holding a site;
     - every other pocket gets the cheapest 3 m crossing to the main land, with water becoming sand and rock becoming dirt;
     - the tests check that the map ends as one walkable component.

**`Land::height(x, y)`** is macro relief (Catmull-Rom between nodes), plus local detail scaled by region kind, plus site levelling. Banks then meet the water surface, and beds lie below it.
- The water's edge comes from a signed distance per tile (1 byte, in eighths of a metre).
- `Land::water_level(x, y)` gives the sea at 0, each lake's level, and rivers sloping down to the sea.
- The function is continuous: the test steps 0.02 m along three lines across a 1 km map and finds no jump of 0.25 m or more.

Unlike [`height.rs`](../living/rules/src/height.rs), this height **does not follow from the tiles alone**: it needs the seed, the parameters and the macro fields (see [hosting](#what-the-authority-would-need)).

## Region and site kinds

| Region kind | Picked by | Environment it maps to now |
|---|---|---|
| `meadow` | lowland, driest 35% | `meadow` |
| `forest` | lowland, middle moisture | `forest` |
| `old_forest` | lowland, wettest 30% | `forest` (denser: 92% tree cover) |
| `spirit_grove` | exactly one: the most remote old forest | `spirit_forest` |
| `wetland` | flat, wet lowland near water; 0.5 per km², 1–3 where the lowland has room | `meadow` (stand-in) |
| `highland` | mean height over 150 m or mean slope over 0.4 | `meadow` (stand-in) |
| `peaks` | mean height over half the highest point | `meadow` (stand-in) |
| `beach` | over 30% of land within 70 m of the sea and under 12 m high | `meadow` (stand-in) |
| `sea` | mostly sea | — |

`RegionKind::env()` returns the environment id. `Land::kind_at(x, y)` gives the kind at a point, and `Land::region_at(x, y)` gives the region record. Beach, wetland, highland and peaks have no environment yet.

| Site | Count | Radius (diameter) | Inhabitants | Placed |
|---|---|---|---|---|
| town | 1 | 150 m (300 m) | adults, 1.75 m | flat lowland, rivers allowed, no lake or sea inside, prefers a river or coast |
| village | 2–3 (1.2 per km²) | 50 m (100 m) | adults | flat, within 160 m of water, at least 450 m apart; out of wetland unless placement relaxes |
| giants | 1 | 130 m (260 m) | 3× adult, about 5.25 m | highland, mean ground at least 90 m, up to 70 m of relief before levelling (85% levelled, so their lots fit) |
| small folk | 1 | 28 m (56 m) | 0.35× adult, about 0.6 m | forest or hills, 20–220 m |
| steampunk town (`steampunk_town`) | 0–1 (1 from about 1.6 km² of land) | 105 m | adults | 12–44 m of relief across the site (a hillside to terrace), at least 500 m from the town; levelled 40%; placed after the villages |
| cyberpunk town (`cyberpunk_town`) | 0–1 (as above) | 100 m | adults | up to 24 m of relief, prefers the coast; levelled 65%; placed after the villages |
| cave mouth | 2–4 (1.2 per km²) | 5 m | — | mountain flank (slope 0.45–1.6), moved to the foot of rock and facing downhill; caverns are separate spaces, not in this height map |
| hamlet (`hamlet_village`, a dispersed site; since 2026-11-10) | 2–9 (3 per km²; 9 on seed 7) | 26 m | adults | placed after every other site, on not-too-rough meadow, forest, old forest, highland or beach, spread over the island and over region kinds; a green with a well, one street, barns and fields; 2–5 houses ([seeded lives](SEEDED_LIVES.md#placement-hamlets-and-known-ways)) |

Settlements avoid the spirit grove. When a site does not fit, placement relaxes its limits in steps, so a cramped 1 km island still gets a town.

## Measured (release build, Apple Silicon, single thread)

`land_preview` measures with a counting allocator. Peak is the highest heap use during generation; retained is what the finished `Land` keeps.

| Size | Generate | Peak heap | Retained | `height()` |
|---|---|---|---|---|
| 1024 m | 0.11–0.12 s | 12–13 MB | 2 MB | 42–47 ns |
| 2048 m | 0.42–0.72 s (0.46 s typical) | 42–47 MB | 9 MB | 44–96 ns |
| 3072 m | 1.0–1.2 s | 100 MB | 21 MB | 45–46 ns |

The 2048 m figures for seed 7 come from three repeat runs; the occasional slow run (0.72 s, 95 ns) came while other builds ran on the machine. The WASM build compiles (`cargo check --target wasm32-unknown-unknown`), but nothing has been timed in WASM.

| Seed, size | Summits | Height range | Walkable land | Regions on land (median across) | Rivers (longest) | Lakes across |
|---|---|---|---|---|---|---|
| 7, 2048 | 405, 258 m | −29 .. 407 m | 2.43 km² | 33 (349 m) | 5 (994 m) | 116, 158, 204, 223 m |
| 11, 2048 | 430 m | −28 .. 436 m | 2.36 km² | 31 (353 m) | 7 (1032 m) | 128, 139, 152, 222 m |
| 23, 2048 | 343, 221 m | −30 .. 343 m | 2.20 km² | 30 (355 m) | 5 (992 m) | 124, 180, 246 m |
| 7, 3072 | 303, 227 m | −29 .. 307 m | 5.52 km² | 61 (356 m) | 19 (2413 m) | 106–420 m (7) |
| 5, 1024 | 231 m | −29 .. 231 m | 0.67 km² | 21 (214 m) | 1 (252 m) | 100 m |

At 2048 m the tiles are about 30–37% water, 31–35% grass, 12–16% forest, 9–12% rock, 7–8% dirt and under 1% sand. Region sizes fall in 120–470 m across (equal-area circle). The smallest are clipped by the coast or the map edge; interior regions are 290–470 m. Each 2048 m seed has 9–10 sites. The connectivity pass opens 9,600–14,700 blocked tiles there.

## Travel times

Straight-line distance, flat ground, no detours. The rules currently walk at 2.6 m/s and run at 3.9 m/s ([scale](GAME_BRIEF.md#scale-decided-2026-11-08)). The 1.4 m/s column is a realistic walking pace for comparison.

| Distance | Example | Walk 1.4 m/s | Rules walk 2.6 m/s | Run 4 m/s |
|---|---|---|---|---|
| 100 m | across a village | 71 s | 38 s | 25 s |
| 300 m | across the town | 3.6 min | 1.9 min | 75 s |
| 500 m | town to a near village | 6.0 min | 3.2 min | 2.1 min |
| 1 km | the long river at 2048 m | 11.9 min | 6.4 min | 4.2 min |
| 1.8 km | across the island at 2048 m | 21 min | 11.5 min | 7.5 min |
| 2.4 km | the long river at 3072 m | 29 min | 15 min | 10 min |
| 2.9 km | corner to corner at 2048 m | 34 min | 19 min | 12 min |

Real routes are longer: rivers have fords about 400 m apart, and the ranges are mostly rock with narrow 3 m passes. Climbing is not modelled, because the rules are flat. Measured routes in the game client are in [expedition](#expedition-2026-11-09): by road, 1.1–2.3 × these straight-line times.

## Density for 2,000 characters

- **Island-wide:**
  - At 2048 m (2.2–2.4 km² walkable), 2,000 characters means 830–910 per km², or one per 1,100–1,200 m² (about 34 m apart if spread evenly).
  - At 3072 m (5.5 km²) it is 360 per km², or one per 2,760 m².
  - At 1024 m (0.67 km²) it is about 3,000 per km², or one per 335 m², which is crowded.
- **Settlements:** at a medieval town density of 100–200 people per hectare:
  - the 7.1 ha town holds 700–1,400 adults;
  - a 0.79 ha village holds 80–160;
  - the 5.3 ha giants' settlement holds 60–120 giants (a 3× body needs about 9× the floor area);
  - the 0.25 ha small-folk settlement holds 200–400 people at a third of adult height.
- **The 200-character battle:** a 120 × 120 m field (1.4 ha, 72 m² each) fits inside any meadow region (a median region is about 9.6 ha).

## Landmark visibility

*Written for the first camera (40° down, 16 m, 44° field of view). Since 2026-11-09 the default is 28° down, 22 m away, with a 50° field of view: the top of the frame is 3° below the horizon, so rising ground and anything above eye level beyond the focus now show.* The first camera ([`living/game/src/camera.rs`](../living/game/src/camera.rs)) looked 40° down from 16 m away, with a 44° vertical field of view:
- The top of the screen is 18° below the horizon, and the bottom is 62° below it.
- The camera sits about 10.3 m above the focus point, so flat ground is in frame from about 7 m behind the focus to about 19 m ahead.
- Distance fog runs from 60 to 110 m.
- A point is on screen only if it lies at least 0.325 × its distance below the camera. **Anything higher than the camera never shows**: no peak, no far ridge, no tower top.
- From high ground the view does look down. At a cliff edge, the land a few hundred metres below fills the top of the frame, but fog hides it beyond 110 m.

Options, none applied (the camera is unchanged):

1. **Zoom-tied pitch:** a far zoom flattens to about 25°, bringing the top of the frame to about 3° above the horizon. The cost is aiming precision; the brief's open tension on skillshots applies.
2. **Vista framing:** at passes, summits, lake shores and town gates, the camera briefly tilts up toward the horizon, like the context framing noted in the brief (Diablo IV). It needs authored or detected vista points.
3. **A bent world:** a vertex shader lifts distant terrain into the top band, the opposite of a "rolling log" bend. It is presentation only, so the rules and aiming stay flat. It is stylised and can disorient.
4. **Cues instead of sight:**
   - the range's long shadows at dawn and dusk across the lowland (a precomputed horizon or shadow field from `Land::height`);
   - cloud shadows;
   - wind and snow drifting down from the peaks;
   - rivers that visibly flow from the high side.
5. **Vertical landmarks within reach of the frame:** smoke columns, beacon fires, a light pillar over the spirit grove, giant trees, the giants' towers. These read within about 20–100 m.
6. **Reflections:** peaks mirrored in lakes, through a planar reflection or a baked panorama per region.
7. **Fog that scales with height above the ground below**, so high places look far.
8. **Map and compass UI** with landmark bearings.

## Walking it in the game client (2026-11-09)

`LIVING_GAME_LOOKDEV=1 LIVING_GAME_ENV=island living/target/release/living-game` (or pick **Island** in F1 → Look dev). Client only: `living/game/src/island.rs` generates seed 7 at 2048 m and streams it around you in 64 m chunks:
- Ground meshes come from `Land::height`, coloured by terrain and region. Water surfaces sit at `Land::water_level`.
- Each region gets its environment's scatter slots at that environment's density, thinned on beach, highland, peaks and wetland.
- Things taller than 1.6 m stream within 170 m; smaller things within 60 m.
- Settlements use their city environment's layout, centred on the site.
- Water and rock block walking. You start at the town; `LIVING_GAME_START=x,z` starts elsewhere.
- For measurement, `LIVING_GAME_AUTOWALK="<degrees> [run]"` walks for you.
- Tour shots wider than the default view lift the sight cap, so vistas can be photographed.

Outlines now hide where the fog has mostly swallowed a thing, so distant objects no longer draw as bare line drawings in the fog.

Second pass (2026-11-09, user feedback):
- **Stands and glades:** tall things gather into stands with glades between them, from a slow density field. Ground cover stays everywhere.
- **Blended ground colour:** the ground colour is averaged over about 25 m, so region borders no longer switch along straight polygon edges.
- **Water placement:** water draws only on water tiles and their neighbours. Using the nearest water's level alone put a sheet of water over dry slopes.
- **Camera:** see the camera notes in [game brief](GAME_BRIEF.md).

Settlements in the client (2026-11-09):
- **Lots:** `island.rs` places a building on every planner lot at its levelled floor, facing its street, in the model's own size. It spawns the exact model the lot names (`Lot::model_file`) when that file is on disk, else a random model of the kind. Look-dev's fit stands models with foundations on their origin.
- **Walls:** wall pieces run along town walls.
- **Roads:** roads and paved squares draw crisply in the ground, and no wild scatter lands on them.
- **People:** each settlement gets recipe characters of its folk (adults, giants, small folk) at house fronts and in the square, capped at about a dozen for now. Each VRoid character is about 95 meshes; a cheaper far form is part of the performance work.
- **Fog:** edge lines now end where the fog has mostly swallowed things.
- **Frame time:** about 19–23 ms in the town square, headless.

Measured headless at 1600×900 on the development Mac, running from the town into the forest:
- frame time about 19 ms on average (52 fps), with chunk-build peaks of 26–30 ms;
- 35–39 ground chunks, and up to about 1,600 models and 2,800 meshes loaded.

Before this scales, static props need merging or instancing, and level of detail.

## Settlements and roads (2026-11-09)

The cities were the environment JSON's grid and ring slots round each site, which read as houses dropped in a square or a circle. [`settle.rs`](../living/rules/src/settle.rs) now lays out every settlement in the shared rules, so the authority can use the same layout later. It holds mechanics only: every width, spacing, chance and kind is a field of `SettleParams` (`LandParams::settlements`), and building footprints come from [`data/buildings.json`](../living/rules/data/buildings.json), which `buildings.py --table` writes.

**Island roads.** Least-cost routes on a 4 m grid:
- costs: grade (doubling at 7%, ten-fold above 28%), forest, sand, rock cuttings, the spirit grove, rivers (cheap at existing fords);
- sea, lakes and wetland pools are closed; when nothing else reaches, a causeway may cross lake water;
- settlements join nearest first, each road ending where it meets the network, so later roads branch off earlier ones in T-junctions;
- a footpath (the small folk's, the cave mouths') may join any road, but a road never joins a footpath;
- the town gets a road down to the sea shore if the coast is within 600 m;
- paths are smoothed (a moving average over about three road widths, kept out of still water and cliffs);
- every river crossing is a `Crossing`, a ford or (over 6 m) a bridge, and its tiles become road.

**A settlement**, in order:
1. A plaza: an irregular oval stretched along the arriving roads, on clean ground near the centre. The town's is a paved market square (62 × 38 m) with a well and two rows of stalls; villages have a green with a well.
2. A landmark and the big buildings: the town's chapel (the giants' tower) on the plaza edge away from the roads in; the small folk's tower in the middle of their green. Then, on the plaza edge away from the roads and from each other, the town's inn (near a road in) and guildhall, a village's chapel and inn, the giants' longhall and the small folk's mushroom hall. Where the edge has no room, they go on a main street as near the plaza as they fit.
3. The edge, per direction: out to the site radius, stopping short of water, rock or steep relief.
4. For the town, a wall of straight curtains between corners round a lobed version of that edge, with gates where roads cross it, a tower beside each gate and at most corners, and a lane just inside it. The wall breaks where it would stand in water.
5. Main streets: the arriving roads, bent gently between the edge and the plaza, plus radial streets out through the widest gaps (at least 4 for the town and giants, 2 for villages, 3 for small folk).
6. Lanes branching off every street (and the wall lane, inward) that steer along contours on slopes and round the centre on flat ground, wander a little, and join the next street or end as dead ends. They keep a distance from parallel streets.
7. Lots along both sides of every street and round the plaza, facing the street: townhouses in the core and along main streets, houses outside it with some workshops, gardens behind them (burgage plots, deeper on main streets), and street lamps along main streets. Each lot first picks a model from `data/buildings.json` (the deeper of two on main streets) and takes its footprint plus the style's margin (`margin_m`) all round, so frontages vary with the models: narrow townhouses beside wide ones, cottages beside longhouses. Where another road passes a lot's side (a junction, or a road leaving the plaza), the lot takes a corner model whose second front faces that road. When a model does not fit, narrower ones are tried.
8. Outskirts: houses and barns along the roads out, thinning with distance, then fields (strips along the roads, some ploughed to dirt).

Styles per site kind: villages are small and loose; the giants' settlement is built to their scale (12 m streets, 29 × 27 m house lots, 60 m lamp spacing, lanes along contours); the small folk's is tiny and organic (0.9–1.2 m paths that wander, 3 × 3.5 m burrow and mushroom-house lots round a green).

**Ground.** `Land::height` now includes:
- **Roads:** each road follows a profile: the ground along it, averaged over 4–28 m (by width), pinned to the plaza floor at plazas and to the other road at junctions and crossings. The surface has a cross-fall of the ground across it, limited to 3%, and blends into the terrain over a 2.5 m shoulder plus half the width. Each road is one surface (a soft minimum over its segments), so its centre line is its profile.
- **Pads:** the ground under each house, townhouse, tower and well (and each plaza) is exactly its floor, with a smooth skirt (3 m; 7 m for giants, 1.2 m for small folk). Next to another pad a skirt gives way, so neighbouring pads stay level; neighbours whose floors differ are kept apart by 0.8 × the difference. A floor is the street level at the lot's front plus a small step. A lot is placed only where levelling cuts at most 2.6 m and fills at most 2.2 m (9 and 6 m for giants).
- Shaping fades out at the water's edge, and never lowers a bank below its water.

`height()` stays continuous: the tests step 0.02 m through the town and across a whole 1 km map.

**Data for the client** (all public on `Land`):
- `settlements`: kind, `buildings.py` style, centre, scale, radius, `plaza` (outline, floor, paved), `wall` (ring, corners, `runs`, `gates`, height, thickness; `Wall::pieces(len, centre)` spreads wall-segment models along the runs), the lot range and the landmark.
- `lots`: settlement, `kind` (`LotKind::model()` names the `buildings.py` kind and asset folder; gardens and fields have no model), `centre`, `width_m` × `depth_m` (the model's footprint plus the margin), `front` (unit vector toward the street), `yaw` (`Quat::from_rotation_y(yaw)` turns a model's +Z front to `front`, with game x = land x and game z = land y), `floor_m` (where the model's origin goes), `frontage`, `model_file` (the model's path under `envs/`) and `height_m` (its height above the floor).
- `roads`: class (trunk, street, lane, path), points with surface heights, width, cross-fall per segment, and what each end joins.
- `crossings`: road, ford or bridge, position, direction and span.

Tiles: roads and paved plazas become `Road`, the wall `Wall` (gates stay open, and the connectivity pass links any pocket a wall closes through water or rock, never through a wall), forest under lots becomes grass, and some fields become dirt.

**Tests** (`cargo test -p living-rules settle::`, on seed 7 at 2048 m and seed 5 at 1024 m): every settlement is laid out with a landmark and the town has gates; every lot names a model of its style and kind and is that model's footprint plus the margin; the town has one inn, hall and chapel (its landmark), each bigger than any house, on the plaza or a main street; the town's homes have at least 20 distinct footprints, 6 forms and frontages from narrowest to at least 1.8× that; every corner building has a road on its corner side, and a town has at least 4; lots overlap neither each other nor roads; lots stand on walkable, dry land; every lot faces its road, its plaza, its house (gardens) or stands on its wall (towers); the road graph joins every settlement; pads and plazas are level to 2 mm; trunk roads follow their profile to 2 cm; height is continuous through the town; the parameters round-trip as data. `settle::tests::settle_sweep` (ignored, release) repeats the layout checks for seeds 5, 7, 9, 11 and 23 at 1, 2 and 3 km.

**Preview:** `cargo run --release -p living-rules --example town_preview --manifest-path living/Cargo.toml -- SEED SIZE_M OUT_DIR` draws the road network and a close-up of each settlement (lots coloured by kind with a white bar on each front, gardens, fields, wall, gates, contours) and writes a legend with counts, timings, grades and a pad check.

**Measured** (release, Apple Silicon, single thread, seeds 7, 11 and 23 at 2048 m, three runs each):

| | seed 7 | seed 11 | seed 23 |
|---|---|---|---|
| generation with settlements (without) | 0.64 s (0.55 s) | 0.65 s (0.53 s) | 0.64 s (0.53 s) |
| `height()` inside settlements / over the map | 150–153 / 53–55 ns | 177–180 / 53–54 ns | 157–163 / 52–55 ns |
| town lots (townhouses, houses, gardens, towers) | 184 (71, 29, 42, 10) | 194 (77, 39, 37, 13) | 171 (52, 33, 40, 9) |
| giants' houses, small folk's houses | 9, 49 | 9, 52 | 9, 42 |
| roads: count, trunk length | 51, 4.9 km | 56, 4.1 km | 43, 3.4 km |
| steepest 10 m of trunk road | 53% | 44% | 50% |

Settlement planning adds 0.09–0.12 s at 2048 m and 0.26 s at 3072 m. Each 2048 m world has about 350–410 lots.

**Model-sized lots (2026-11-09; one run each, same seeds and machine):** planning takes 0.12–0.15 s at 2048 m. `height()` is unchanged (153, 179 and 161 ns inside settlements).

| | seed 7 | seed 11 | seed 23 |
|---|---|---|---|
| town lots (townhouses, houses, workshops, barns, gardens, towers) | 202 (70, 46, 3, 0, 39, 9) | 226 (85, 51, 6, 5, 36, 12) | 188 (50, 44, 1, 6, 33, 8) |
| town's distinct home footprints (0.5 m), corner buildings | 31, 9 | 40, 7 | 33, 6 |
| giants' houses, small folk's houses | 16, 58 | 16, 56 | 12, 74 |

Every town has one chapel (its landmark), inn and guildhall.

## Ornaments, terraces and styled towns (2026-11-09)

User requests: street ornaments ("right now it's just a bunch of buildings"), elevation within towns ("stairs and things like that"), and steampunk and cyberpunk towns on the island. The planner does all three in the shared rules, so the authority and clients derive the same result from the seed ([island authority](ISLAND_AUTHORITY.md#ornaments-terraces-and-styled-towns-2026-11-09)).

### Styled towns

Two more site specs of kind `town` carry a building style (`SiteSpec::style`), a relief range and a coast preference. They are placed after the villages, so the earlier sites stay where they were. Each has its own `Style` in `SettleParams::styles`, with the same street, plaza, landmark and lot logic. `Style::models` maps lot kinds to the style's own `buildings.py` kinds.

| | Steampunk (hill town) | Cyberpunk (harbour town) |
|---|---|---|
| Square | 52 × 36 m, paved; the **clock tower** in the middle (`Tower` → `clocktower`), a fountain beside it | 40 × 26 m, paved; the **megatower** on its edge (`Chapel` → `landmark`), an info pylon in it |
| Round the square | the pub (`inn`), the exchange (`hall`) and the iron-and-glass market arcade (`Chapel` → `arcade`) | the food court (`Inn` → `market`) and a slender tower (`Hall` → `tower`) |
| Homes | narrow, wide and corner brick houses (`house`) | narrow, wide and corner blocks (`block`) |
| Outskirts | works (`Workshop` → `works`) and factories (`Barn` → `factory`) | garages and fabs (`Workshop`, `Barn` → `workshop`) |
| Streets | lanes follow the contours (`contour` 0.9); street trees every 18 m; pipes along works | wider main streets (6 m), straighter lanes (`wander` 0.12); a **neon street** |
| Terraces | yes (seed 7: 3 m steps) | where the site has the relief (seed 7: flat, so none) |

The client finds their models through `living_rules::settle::env_of(style)` (`steampunk_city`, `cyberpunk_city`) and each model file's kind folder (`settle::asset_kind`). Site ids for seeds are `steampunk_town` and `cyberpunk_town` (`land::Site::id`).

On seed 7 at 2048 m the steampunk town stands at (743, 841), above a river in the hills, with 63 lots, 32 homes, 6 stairs and 202 retaining walls. The cyberpunk town stands at (576, 1600) by the west coast, with 86 lots and 41 blocks.

### Terraces

A style terraces with `terrace_m` (3 m for every person-sized style). A site is terraced when its built-up area has at least `terrace_relief_m` of relief (6–7 m), so flat towns stay flat. On seed 7 only the steampunk town is terraced; the walled town and the villages are too flat.

- **Ground** ([`settle/terrace.rs`](../living/rules/src/settle/terrace.rs)): the site's ground is smoothed over about 12 m. Level `i` is flat at `base + i × 3 m`, and the drop to the next level is 0.8 m wide wherever the hill is steeper than that allows. The zone fades back to the natural ground over 16 m past the built-up edge, and within 6.5–14 m of water, so banks stay natural. Terraces apply before roads and pads in `Land::height`, so the heights digest covers them.
- **The square** is one of the terraces: its floor snaps to a level, and where the slope crosses it, its edge becomes a drop with retaining walls.
- **Streets:** main streets cross the drops as ramps, because their profiles average over the terraced ground. Lanes steer by the smoothed hill rather than the flat terrace, so they run along the terraces, and they stop short of a drop.
- **Stairs** are flights rising 3 m over 5 m (about 0.18 m risers), square to the drop:
  - one where a lane stops short of a drop;
  - others about `stair_m` (30–34 m) apart along each drop, wherever a street lies near the foot and another near the head.

  The ground under a stair rises with it (a sloped pad), and its tiles are road. Lots keep clear of stairs and their landings.
- **Retaining walls** stand along every drop and round a square cut into the slope, wherever the finished ground drops at least 1.35 m across the line. Each is a 4 m piece facing the lower ground, low (1.5 m) or high (3 m) by the drop.
- **Walking agrees with the ground:** of two neighbouring tiles whose ground differs by more than 0.8 m, the upper one becomes `Wall`, or the lower one when the upper is a road, a stair, water or a building. The levels then join only by streets, ramps and stairs. Slivers sealed between drops, water and rock (under 150 tiles) are closed, like the land's small pockets.
- **Houses** may back into the terrace above (`cut_m` 3.5 in the steampunk style), so a row of houses on the uphill side of a lane holds the next drop.

### Ornaments

[`settle/ornament.rs`](../living/rules/src/settle/ornament.rs) dresses each settlement after its lots. Each rule is a field of `Ornaments` in the style. Models come from `data/buildings.json`: 432 new prop models from `buildings.py`, mostly under 500 triangles, with the steampunk clock pillar and fountain about 1,300–1,500.

| Kind | Where | Styles |
|---|---|---|
| fountain / market cross | the square's centrepiece, else along its axis: a market cross in the walled town, a fountain in the steampunk square, an info pylon in the cyberpunk one | fantasy, steampunk (fountain with gears, clock pillar), cyberpunk (lit basin, info pylon) |
| bench | round the square's edge every 9–12 m, facing in, away from street entries; beside an inn's door | all |
| tree | 1–2 on the square (in a ring or grate on paving, a shade tree on a green); behind houses in gardens; along steampunk main streets | all |
| banner | both sides of every street entering the square, inside town gates | fantasy, steampunk, cyberpunk (holo strip) |
| sign | a shop sign beside inn and workshop doors; a signpost where streets leave the square | fantasy, steampunk; cyberpunk uses its neon signs |
| barrel, crate, cart | by inns (three spots), workshops and barns (two), behind market stalls; a rain barrel by some houses | all |
| flower box, planter | beside house doors (at least 1.8 m from the door), at front corners | all |
| fence, gate | round every garden's three open sides in 2–4 m sections, a gate in the back | all |
| washing line | across some gardens on posts; across 1.6–6 m gaps between neighbouring houses, 3.3 m up | all |
| kerb | both edges of paved main streets and round a paved square, in 4 m pieces | fantasy town, steampunk, cyberpunk |
| neon sign, kiosk, food stall, cable | the cyberpunk main street with the most buildings: signs and stalls wherever the frontage leaves room, cables across it every 12 m between buildings | cyberpunk |
| billboard | round the cyberpunk square | cyberpunk |
| pipe | along the sides of steampunk works and factories | steampunk |
| well | 2 more wells in the walled town, beside lanes where they leave a main street (lots, not props) | fantasy |
| lamp | lanes now have lamps too: 42 m apart in the walled town, 36 m steampunk, 30 m cyberpunk (lots) | town styles |

Placement rules, checked for every prop:
- Off every carriageway (kerbs on its edge) and out of buildings. Signs and flower boxes may stand in a lot's margin against the wall, never in the model's footprint. A tree takes room at its trunk, and its crown overhangs.
- Clear of doors (0.9 m) and of the 2 m way out of each door. Stairs keep their landings.
- On even ground (not across a drop), in the plaza only when meant to be, clear of town walls.
- Fountains, market crosses, carts, kiosks and food stalls block movement (`PropKind::blocks`). The rest are posts, low things or overhead.

Seed 7 at 2048 m has 1,302 props: 446 fence sections, 230 kerbs, 202 retaining walls, 95 flower boxes, 61 gates, 53 barrels, 46 benches, 44 trees, 32 washing lines, 22 signs, 19 banners and fewer of the rest. The walled town alone has 617.

### Tests

`cargo test -p living-rules` (77 tests). New ones run on seed 7 at 2048 m and seed 5 at 1024 m:
- `ornaments_keep_doors_and_streets_clear`: every prop names a model of its settlement's style and kind; it stands off carriageways and out of buildings (attached ones out of the model's footprint), clear of every door (0.5 m, scaled with the folk); blocking ones stand in a plaza or beside a building. The island has every common kind, and every settlement but the small folk's has a bench.
- `stairs_connect_levels`: every stair's ground rises evenly by one step from foot to head, its tiles are walkable, and a walk from just beyond its foot to just beyond its head exists, tile by tile, with no step over 0.8 m.
- `terraces_are_level`: away from roads, pads, stairs and drops, a terrace's ground is its level to 2 mm (1,510 points on the steampunk town); the plaza's floor is a terrace level.
- `walkable_ground_has_no_cliffs`: on the hosted tiles inside terraced settlements, no two neighbouring walkable tiles differ by more than 0.8 m, except road against road (reported: up to 1.4 m on seed 7, where a trunk road runs within 1 m of a river and road shaping fades out at the water's edge; up to 2.0 m at a lane junction in a 1 km village).
- `styled_towns_stand_on_the_island`: both towns exist with their site ids, landmarks (`clocktower`, `landmark`) and at least 20 homes, and every lot names a model of the town's own style. The steampunk town is terraced, its buildings stand on at least 3 levels, and it has at least 3 stairs and 10 retaining walls.
- `host::tests::hosted_island_keeps_doors_reachable` now hosts the props as well: 327 doors, none stranded; 35,205 tiles blocked and 235 walkable tiles cut off (19 before this change).
- Changed: lamps stand only where their ground is within 0.5 m of the road and even. Gardens and fields may cross a terrace's drop.

`settle_sweep` (ignored, release) also runs the four new checks. It passes on seeds 5, 7, 9, 11 and 23 at 1, 2 and 3 km; all 15 worlds at 2 and 3 km place both styled towns. It found five defects, all fixed: a lamp on a drop wall, a town with no room for its landmark, stair landings on the next drop or dipped by a neighbouring pad, and a square snapped below a river's level.

### Preview

`town_preview` (above) now names each image by site id (`town-SEED-<n>-steampunk_town.ppm`), draws a core close-up of every town, and draws the props: stairs orange with treads, retaining walls dark brown, kerbs pale grey, cables and washing lines as white lines, the rest as small marks by kind. Its legend counts props per settlement and notes terraces.

Measured on the dev-box while other builds ran (seed 7 at 2048 m, release; not an A/B against the earlier code): generation 1.55 s with settlements and 1.21 s without; `height()` 282 ns inside settlements and 135 ns over the map.

## Expedition (2026-11-09)

Timed, scripted walks across seed 7 at 2048 m in the look-dev game client. They measure the client's walking (water, rock and walls block it; slopes do not slow it), not the authority. [`living/game/src/route.rs`](../living/game/src/route.rs) makes your character follow a route, photographs it and measures it:

- `LIVING_GAME_ROUTE=road:town>giants@run` follows `Land::roads`: the shortest path on the road graph between plazas. Places: `town`, `giants`, `small`, `village1`–`3`, `farvillage` and `shore`.
- `points:x,z;…` follows straight segments.
- `regions` loops off-road through one region centre of every land kind and the coast.
- Speeds: `walk` 1.4 m/s, `run` 3.6, `rules-walk` 2.6, `rules-run` 3.9, or a number.
- When the route makes no progress for 4 s, that place counts as a stuck point: it is photographed, and `Map::path` finds a detour back to the route.
- Photographs every 150 m and at landmarks (plazas, lakes, foothills, the spirit grove, fords, the coast, stuck points, steep climbs): the game camera, then a vista.
- `summary.json` holds times, distances, estimates, stuck points, slides, grades, frame times and the worst frames with their places.

Headless runs ride on the tour (`LIVING_GAME_TOUR=<dir> LIVING_GAME_TOUR_ONLY=island LIVING_GAME_TOUR_SHOTS=default`); the module's header has the details.

**Runs:** one run per route on the dev-box (Radeon 8060S, Vulkan, load average 4–9), plus the giants' road on the development Mac (M4 Pro, load average about 16 from other agents). All at 1600×900 headless, uncapped, at commit 977a14c. Route time excludes photograph stops, and frame statistics leave out the half second after each photograph. The journal (summaries, tracks, a map, 58 photographs and a contact sheet) is outside the repository, in the coordinating session's scratchpad (`expedition/`).

### Travel

| Route | Straight | By road | Speed | Time | Straight-line estimate | Ratio |
|---|---|---|---|---|---|---|
| town → village2 | 576 m | 631 m | run 3.6 | 2:54 | 2:39 | 1.09 |
| town → village1 | 1,806 m | 2,918 m | run 3.6 | 13:28 | 8:21 | 1.61 |
| village1 → village3 | 560 m | 628 m | run 3.6 | 2:52 | 2:35 | 1.11 |
| village3 → small folk | 544 m | 610 m | run 3.6 | 2:47 | 2:31 | 1.11 |
| town → small folk (the three legs above) | 1,814 m | 4,130 m walked | run 3.6 | 19:07 | 8:24 | 2.27 |
| town → giants (up the trunk road) | 967 m | 1,997 m | run 3.6 | 9:05 | 4:28 | 2.03 |
| giants → town (down) | 967 m | 1,997 m | rules walk 2.6 | 12:35 | 6:11 | 2.03 |
| town → village3, the furthest village | 2,041 m | 3,522 m | walk 1.4 | 41:49 | 24:18 | 1.72 |
| town → village3 | 2,041 m | 3,522 m | run 3.6 | 16:15 | 9:27 | 1.72 |
| off-road loop: every land region kind and the coast | 4,407 m in straight legs | 8,445 m walked | run 3.6 | 40:56 | 20:24 | 2.01 |

- **On roads, time is the road's length divided by the speed,** to within 1.5% (corners cut make the walk 0.2–1.7% shorter). No road had a stuck point or a slide at any of the three speeds, and the Mac and the dev-box took the same time to the second.
- **The road network makes the island about twice as far across as it is.** The trunk roads form a tree round the west and south of the central range (see the journal's map). The small folk are reached only through village1 and village3, so they are 4.1 km by road for 1.8 km straight. The giants' road doubles back round the range's spur. The eastern massif, about a third of the land, has no road and no settlement.
- **At these speeds:** the furthest village is 42 min away at the look-dev walk, 16 min running, and 22.6 min at the rules' walk (3,522 m at 2.6 m/s, computed from the measured road-time match). The small folk are about 49 min away at 1.4 m/s (computed).

### Stuck points and slides

None on roads. The off-road loop met 26 stuck points, each resolved by one detour of 15–965 m (5,244 m in all). No point needed a teleport.

| Blocker | Count | Largest detours |
|---|---|---|
| Rock (highland, peaks, old forest, the spirit grove's edge) | 17 | (1168, 856) peaks, 965 m; (916, 467) highland, 658 m; (1045, 546) highland, 589 m; (1015, 470) highland, 148 m |
| Water: lakes, wetland pools, rivers | 9 | (226, 842) wetland, 933 m; (256, 740) wetland, 197 m; (971, 1552) spirit grove, 143 m |
| The town's edge: its wall, with a river along it | 4 | (495, 344), 509 m; (379, 370), 287 m; (423, 135), 135 m; (403, 139), 98 m |

(Some points have two blockers nearby, so the counts overlap. One, (1081, 1487) in the spirit grove, was a small obstacle with a 14 m detour.)

- **Slide-on-blocked walking never got round anything.** Every slide longer than 0.75 s was the 4 s before a stuck point: the walker slid a metre or two along the block and stopped. Against a straight block face, sliding only helps when the goal lies along the face.
- **Rock does not read as rock.** In the photographs of the highland and peaks stuck points, the blocking rock is a smooth sand-coloured slope, the same as the walkable ground beside it. The walker stops against an invisible wall. The town wall reads clearly, but the river along its outside makes long detours to the gates.

### Steep grades

Grade is the climb over the last 10 m walked. The client moves at full speed on every grade.

- **The giants' trunk road** (the only steep road): it climbs 176 m in 1,964 m. 305 m of it is steeper than 20%, and 114 m steeper than 30%. Its steepest 10 m are:

  | Peak grade | Where | Stretch over 20% |
  |---|---|---|
  | 56% | (595, 1055) | 53 m from (582, 1034) |
  | 48% | (681, 992) | 52 m from (687, 959) |
  | 34% | (574, 943) | 25 m |
  | 32% | (756, 985) | 74 m from (780, 964) |
  | 32% | (576, 1011) | 25 m |
  | 27% and 25% | (535, 962) and (545, 989) | 23 and 18 m |

  The photographs show the road cut straight up the slope with sawtooth edges, the 4 m routing grid's steps.
- **Other roads:** the steepest 10 m elsewhere is 20%, at (746, 453) on the trunk south. Village and small-folk roads stay under 9%.
- **Off-road:** the walker climbed up to 113% over 10 m at (1010, 468), with stretches of 88% at (989, 533) and (1147, 777) and 86% at (966, 666). Wherever ground is not rock, it can be run up at 3.6 m/s, however steep.

### Frame time

Dev-box, per run: mean 3.9–5.9 ms, p95 5.7–10.0 ms, p99 7.7–15.7 ms, and worst 71–146 ms. Mac, giants' road: mean 4.3 ms, p95 5.1 ms, and worst 461 ms.

- **The hitches are settlement arrivals.** The worst frames of every run are where a settlement's near chunks (people and small things, within 60 m) spawn:

  | Settlement | Where | Worst frame |
  |---|---|---|
  | village2 | (838, 117) | 71 ms |
  | giants | (660, 1093) | 72 ms on the dev-box, 461 ms on the Mac |
  | village1 | (900, 1919) | 104–118 ms |
  | village3 | (1480, 2003) | 85–113 ms |
  | small folk | (1769, 1532) | 146 ms |

  At village3, the 112.8 ms frame added 74 models and about 280 meshes. `BUILDS_PER_FRAME` limits chunks, not things, and a settlement chunk can hold 70 or more models. On the Mac, the last 200 m to the giants also ran at 1 s means of 20–60 ms for about 20 s, and the measured speed dipped to 3.1–3.3 m/s; its 461 ms frame exceeds Bevy's 250 ms time clamp, so that frame lost distance. Away from settlements and their outskirts, the worst frames stay under about 65 ms.
- **Walking versus running** on the same road (town → village3): mean 3.9 against 4.1 ms, p95 5.7 against 5.8 ms, and worst 104 against 113 ms. Streaming at running speed costs little more. The running run's first 2.5 min (meadow, (528–690, 120–160)) ran at 15–21 ms means. In the same seconds, the per-character spring cost rose by 40–80%, and the walking run on the same road did not slow there, so this was load from other work on the machine, not the island.

### What it implies

1. **Size:** 2048 m is not too small. Even running, the road network makes the far settlements 16–19 min away, and walking at 1.4 m/s puts them 42–49 min away. That is long for a default pace. Before considering 3072 m, choose between:
   - the rules' 2.6 / 3.9 m/s pair (the far village at 22.6 / 15 min);
   - running as the travel pace;
   - mounts, carts or boats.

   A road across or round the east would cut town → small folk from 4.1 km to about 2 km (the straight line is 1.8 km) and open the unused third of the island.
2. **Switchbacks:** the giants' trunk road needs real switchbacks at (575–600, 1000–1060) (56%), (680–690, 960–995) (48%), (750–780, 965–990) (32% for 74 m) and (535–585, 940–965) (27–34%). These are the stretches the 4 m grid and smoothing steepen (see [what still looks weak](#what-still-looks-weak)): the fixes to try are routing that penalises turns, or a coarser grid with real switchbacks.
3. **Blocking must be visible:** rock should look like cliff or scree, distinct from walkable slopes. Alternatively, steep ground should become walkable but slow, which needs slope in the rules (open question 3). Either way the walker should not meet invisible walls.
4. **Slope speed:** the client climbs 113% at full speed, so steep roads cost no time yet. If height becomes a rule, the giants' road is the first place it shows.
5. **Settlement streaming:** spread a settlement's near-tier spawns across frames (a budget in things, not chunks), or load its people and models before you arrive. This should take the 70–146 ms arrival hitches (461 ms on a loaded Mac) under the 33 ms frame.
6. **Vistas:** in a pulled-back vista, distant outlined trees float over fog-coloured void where the ground has faded (the spirit grove). Vista framing (option 2 under [landmark visibility](#landmark-visibility)) needs that fixed. Vista frame cost was not measured: the statistics exclude photograph frames.

## What the authority would need

*Superseded on 2026-11-09 by [island authority](ISLAND_AUTHORITY.md), which hosts this world: heights are derived from the seed with platform-independent math and checked by digests, building footprints block as `Wall` tiles, lots are rows, `Map::path` no longer allocates whole-map arrays, and a tile edit patches the cached map instead of rebuilding it. The analysis below is kept as written before that work.*

Out of scope here; nothing in the authority, mind, viewer or game uses `land` yet. **Before designing storage or subscriptions for this world, consult the SpacetimeDB documentation as [AGENTS.md](../AGENTS.md) requires**: [tables](https://spacetimedb.com/docs/tables/), [performance](https://spacetimedb.com/docs/tables/performance/), [indexes](https://spacetimedb.com/docs/tables/indexes/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [views](https://spacetimedb.com/docs/functions/views/). Check them against the pinned version.

With today's chunking ([`map.rs`](../living/rules/src/map.rs): 16 × 16 tiles, one byte per tile, chunk ids packing 16-bit chunk coordinates, sides up to 4096 m):

| Side | Tiles | Chunk rows | Terrain bytes (excluding row overhead) | Signed water distance (1 B/tile) | Macro fields (4 × f32 grids) |
|---|---|---|---|---|---|
| 1024 m | 1,048,576 | 4,096 | 1 MiB | 1 MiB | 0.27 MB |
| 2048 m | 4,194,304 | 16,384 | 4 MiB | 4 MiB | 1.06 MB |
| 3072 m | 9,437,184 | 36,864 | 9 MiB | 9 MiB | 2.4 MB |

Existing patterns that would not hold at this size, measured from source and not yet profiled:
- **Whole-map pathfinding:** `Map::path` allocates two `u32` arrays the size of the whole map on every call. That is 32 MiB per call at 2048 m and 72 MiB at 3072 m. It needs a bounded search window or hierarchical paths first.
- **Whole-map rebuild:** `common::map` caches the whole `Map` in module memory (4–9 MiB) and rebuilds it from every `terrain_chunk` row after any tile change. That is a whole-World read per road or wall.
- **Generation inside a reducer:** 0.5–1.2 s natively with a 45–100 MB peak heap. Whether that fits in a reducer, or whether the world should be generated offline and imported as chunks, is a question for the documentation and a measurement.
- **Height is not derivable from tiles:**
  - Clients would need the macro fields and the signed distance, or would have to re-run the generator.
  - Re-running is risky: the generator uses `f32` transcendental functions (`exp`, `tanh`, `powf`, `hypot`), whose results can differ between native and WASM math libraries. That can flip a tile near a threshold.
  - The safer default is that the authority's tiles are the truth and the macro fields are shipped as data.
- **Subscriptions:** clients should subscribe by area, not to every chunk. The camera spike already loads only nearby chunks; the lab observer was not checked.

## What still looks weak

*Ornaments, terraces and styled towns (2026-11-09):*
- **Fences** double up where two gardens touch, and fence sections are fixed lengths (2, 3 and 4 m), so a garden side ends in a gap of up to 1 m. Fences do not block movement.
- **Steep road pairs:** road shaping fades out at the water's edge, so a road's edge tiles beside a river can step up to 1.4 m against the road's middle. Some lane junctions between terraces step up to 2 m. These are walkable road tiles; the drop walls do not cover them.
- **The hill town** is small (32 homes) because its slope (up to about 30%) leaves narrow terraces. The far side of its river stays empty farmland on terraces. Lanes end at stairs more often than they join.
- **Retaining walls** run through the terraced fields beyond the town too (202 pieces). That is consistent with the ground, but costly to draw.
- **Cyberpunk neon street:** its plaza is small, and the dense blocks leave little frontage for stalls (one kiosk and 8 neon signs on seed 7). Cables need buildings on both sides within 3 m of the street's edge; only 4 qualify.
- **Kerbs** are separate 4 m models, 230 on the island. They are cheap (under 130 triangles), but they are many small meshes until static props are merged.
- **Body size:** giants' and small folk's props are the fantasy props scaled to them.

*Earlier:*

- **Causeways:** islets join the island by straight 3 m sand causeways, because every land tile must be reachable on foot.
- **Passes:** the connectivity passes through rock are straight 3 m staircases, readable as cut lines on the map. They are paths, not designed passes.
- **Region borders** are polygonal Voronoi edges in kind colour. Tile densities blend across them, but region identity does not.
- **Coast:** the coastline is a single warped blob with few deep bays or peninsulas.
- **Rivers:** widths stay under 14 m, so there is no broad river. Fords are placed by distance, not by terrain.
- **Ground near rivers:** 6–12 m from a river, the ground can dip up to about 1.6 m below the river's level, where a meander leaves the carved valley line.
- **Main summit:** height varies by seed (303–430 m in these runs). Seed 7 at 3072 m stays near 300 m.
- **1 km worlds** are cramped: one short river and one lake.
- **Highland region:** it often covers a large share of the island and borrows `meadow` assets until it has an environment of its own.
- **Settlements:**
  - Mountain roads: the 4 m routing grid makes short switchbacks, and smoothing them steepens the climb, so trunk roads up to the giants reach 44–53% over 10 m and cave paths up to 63%. Streets and lanes stay under 18%. Fixing it needs routing that penalises turns, or a coarser grid with real switchbacks.
  - On flat ground the main streets are the routed roads, nearly straight; their gentle bend helps but towns on flat land still read as a spider web round the plaza.
  - Lanes sometimes branch twice from about the same point and form small teardrop loops, and on steep giants' ground they wriggle.
  - The giants' settlement holds about 16 houses on its shelf in seed 7 (2048 m), and none of their 36–45 m longhouses fits.
  - Block interiors in the town stay as gardens and open green; there are no back lanes or courtyards. Only workshops have yards, built into their models.
  - Cottages and narrow townhouses outnumber the other forms (about 20 of 46 houses and 47 of 70 townhouses in seed 7), because a lot that does not fit tries narrower models.
  - A village in a cramped spot can end with only a few houses and no well.
  - The client still dresses settlements from the environment JSON slots; the lots are not drawn yet.

## Open questions

1. **Size:** 2048 m or 3072 m? At 2048 m and 2,000 characters, the island is busy (one person per 1,200 m²). At 3072 m, the far side is a 12-minute run away.
2. **Seeing mountains:** which visibility option(s) above, given the skillshot aiming constraint?
3. **Mountains as walls:** should rock stay unwalkable, so ranges are walls with passes? Or should steep ground be walkable but slow? That needs height or slope in the rules.
4. **Does height become a rule?** Slope speed, line of sight, falling, climbing. If so, the authority must evaluate the same height, which raises the determinism question above.
5. **Islets:** sand causeways, boats, or no islets?
6. **Character size:** the giants' and small folk's settlements are sized for 3× and 0.35× bodies, but the rules carry no body size yet ([scale](GAME_BRIEF.md#scale-decided-2026-11-08)).
7. **Caverns:** how a cave mouth links to its separate underground space, and how large that space is.
8. **Missing environments:** beach, wetland, highland and peaks have none, and villages borrow `fantasy_city`.
9. **Sight versus world size:** day sight is 11 m in a world 2 km across.
10. **Where the parameters live:** in the game seed's `rules` block or in a separate world file, and how this world updates in place once it is persistent.
