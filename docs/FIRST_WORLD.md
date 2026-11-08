# First world: a generic km-scale placeholder

Started 2026-11-08. **This world is a placeholder to change later.** It gives the playable game a believable first place to test scale, travel and landmarks against. It is not the agreed world: the faction geography in [world vision](WORLD_VISION.md) is deferred, and no part of this world is named after a faction or a real company. This note is a design target and a measurement record. It is not an integration report; the authority does not host this world yet.

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
| village | 2–3 (1.2 per km²) | 50 m (100 m) | adults | flat, within 160 m of water, at least 450 m apart |
| giants | 1 | 130 m (260 m) | 3× adult, about 5.25 m | highland, mean ground at least 90 m, up to 70 m of relief before levelling |
| small folk | 1 | 28 m (56 m) | 0.35× adult, about 0.6 m | forest or hills, 20–220 m |
| cave mouth | 2–4 (1.2 per km²) | 5 m | — | mountain flank (slope 0.45–1.6), moved to the foot of rock and facing downhill; caverns are separate spaces, not in this height map |

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

Real routes are longer: rivers have fords about 400 m apart, and the ranges are mostly rock with narrow 3 m passes. Climbing is not modelled, because the rules are flat.

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

The default game camera ([`living/game/src/camera.rs`](../living/game/src/camera.rs)) looks 40° down from 16 m away, with a 44° vertical field of view:
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

## What the authority would need

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

- **Causeways:** islets join the island by straight 3 m sand causeways, because every land tile must be reachable on foot.
- **Passes:** the connectivity passes through rock are straight 3 m staircases, readable as cut lines on the map. They are paths, not designed passes.
- **Region borders** are polygonal Voronoi edges in kind colour. Tile densities blend across them, but region identity does not.
- **Coast:** the coastline is a single warped blob with few deep bays or peninsulas.
- **Rivers:** widths stay under 14 m, so there is no broad river. Fords are placed by distance, not by terrain.
- **Ground near rivers:** 6–12 m from a river, the ground can dip up to about 1.6 m below the river's level, where a meander leaves the carved valley line.
- **Main summit:** height varies by seed (303–430 m in these runs). Seed 7 at 3072 m stays near 300 m.
- **1 km worlds** are cramped: one short river and one lake.
- **Highland region:** it often covers a large share of the island and borrows `meadow` assets until it has an environment of its own.

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
