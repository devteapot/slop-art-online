# Cullet cover authoring

[The plan](../living/seeds/worlds/cullet/plan.json) and [the seed](../living/seeds/cullet.json) get their cover geometry from [cullet_plan.py](../living/tools/cullet_plan.py). Coordinates are metres in the plan frame, north positive. The current Rust parser ignores the new key. The checker follows the later 2.5D agreement. The Spark's phase-1 design at `0d83cbf7` described a planar trace.

## Brush

These are local placements in the Moss, the Hanger and the disused plots documented in [Small City](SMALL_CITY.md), [the bible](../living/seeds/worlds/cullet/bible.md), and [the layout](CULLET_LAYOUT.md). The existing kit provides low weed dressing in the tofts and gardens. Exact dense footprints, heights and fills below are authoring choices. A matching visual pass is needed before enabling the law in the game.

| ID | Polygon area (m²) | Height (m) | Fill | Placement |
| --- | ---: | ---: | ---: | --- |
| `moss_west_gorse` | 210.00 | 1.80 | 0.80 | Gorse on the western moor shoulder, well west of the Moss road and clear of the peat cuts. |
| `moss_east_bracken` | 228.00 | 1.65 | 0.70 | Bracken on the eastern moor shoulder, away from the Lintel path and the turf-house approach. |
| `hanger_west_understorey` | 224.00 | 1.80 | 0.80 | Understorey within the west side of the copse, uphill of the cottage. |
| `hanger_east_understorey` | 244.50 | 1.90 | 0.80 | Understorey on the interior east side of the copse, with open ground between it and the west patch. |
| `mid_row_toft_3_brush` | 7.99 | 1.70 | 0.75 | An overgrown interior patch in the abandoned toft where the plan already places nettles and rubble. |
| `mid_row_plot_toft_3_hedge` | 4.94 | 1.80 | 0.85 | A narrow overgrown margin inside the old back plot, clear of the back lane and plot entrance. |
| `high_row_garden_3_brush` | 10.57 | 1.80 | 0.80 | An interior thicket in the garden left locked since the fever winter. |
| `high_row_plot_garden_3_hedge` | 5.32 | 1.80 | 0.85 | A narrow overgrown margin inside the back plot behind the locked garden, away from the gate. |

## Quarry

The native land dump shows a one-cell nonwalkable drop strip at the raw cuts. At all 59 one-metre segment midpoints, the four cells sampled across the edge contain a drop and no adjacent walkable pair with a step of 2 m or more. The height field also gives the quarry and surrounding built or open terrace edges the same kind of break. The five polylines use the kit's exact top edges and the difference between the levels on either side.

| ID | Length (m) | Height (m) | Why marked |
| --- | ---: | ---: | --- |
| `face_bay_w` | 6 | 3.0 | Weathered west return of the cut. The drop strip separates the two floors on the short return. |
| `face_bay` | 18 | 3.0 | Drilled back of the bay under the runnel. The drop hides walkable adjacency along its length. |
| `face_bay_e` | 6 | 3.0 | Drilled east return. The short drop turns into the much longer Crown edge. |
| `face_east` | 15 | 3.0 | Worked-out basalt east of the bay. The drop below the graveyard has additional low tiles on the Crown side. |
| `face_clay` | 14 | 3.7 | Raw clay beneath the graveyard wall. The face runs from the lower clay-pit floor to the Crown. The built wall above it remains a fixture. |

The ordinary terrace steps, retaining walls, stair mouths, ramps and open overlooks have no marks. Built dry and coped walls keep their existing fixture geometry, including gates. Short weeds, crops, grass, stumps and the sparse shell bramble fall below the height or density needed for brush. The Ladder's working beds, open parts of the Moss and most of the Hanger stay open.

The 70 tree resources use the standard trunk footprint. The kit's six Hanger forms share a 0.20 m base radius and have no exceptional trunks requiring overrides. The separate cottage-yard tree fixtures, the Crown thorn, and the thorn inside Low Row 9 are outside the agreed resource-only tree input. Radius and height alone cannot describe the kit's leaning trunks or their offset from the anchor. A single brush height and fill cannot express seasonal bracken dieback or individual gaps within a cell. The cliff polyline and height cannot describe the quarry mesh's foot depth, taper or benches.

## Readability

The [checker](../living/tools/cullet_cover_check.py) reads the native land dump and the plan. Both arms test terrain height, building envelopes and hosted rock and wall tiles. The second arm adds trunks, qualifying brush and marked faces. A walkable step's high ground already contributes to both arms. The model estimates brush occupancy on a 1 m grid, clips solid trunk traces to a circular footprint and uses 0.20 m radius and 3.20 m height as defaults. It traces cliff tops at the authored edges. Runtime rasterization, facing, range, fog, missiles and sound are outside this check.

For landmarks, the 330 points are town street and lane centerline samples at intervals of at most 6 m. Each ray runs from 1.6 m above ground to 90% of the landmark's height. These absolute shares measure a different sample and baseline from [Phase 2](SMALL_CITY.md#8-build-plan), whose old camera result was 75–99% and old rules result was 2–19%.

| Landmark | Without cover | With cover |
| --- | ---: | ---: |
| The Cone | 49/330 (14.8%) | 49/330 (14.8%) |
| The Counting House | 66/330 (20.0%) | 66/330 (20.0%) |
| The Heron | 78/330 (23.6%) | 78/330 (23.6%) |
| The Watchglass | 37/330 (11.2%) | 37/330 (11.2%) |
| The Lintel | 6/330 (1.8%) | 6/330 (1.8%) |

For routes, the checker splits authored centerlines at bends and crossings. It samples each leg at intervals of at most 3 m and traces to the next bend, crossing or endpoint in both directions. It estimates hidden area across the authored widths at 0.25 m spacing. Strip areas count segments independently, so junction overlaps may be counted in both routes.

| Routes | Clear without cover | Clear with cover | Hidden without cover | Hidden with cover |
| --- | ---: | ---: | ---: | ---: |
| 45 town streets, lanes and wynd segments | 1,306/1,306 | 1,306/1,306 | 0 m² | 0 / 7,008.66 m² |
| 4 outlying paths | 402/486 | 402/486 | 0 m² | 0 / 1,609.70 m² |
| 19 stair flights | 98/98 | 98/98 | 0 m² | 0 / 324.48 m² |
| All routes | 1,806/1,890 (95.6%) | 1,806/1,890 (95.6%) | 0 m² | 0 / 8,942.83 m² |

No feature hid a previously visible turn or junction. The checker prints the per-route denominators and flags each added blocker on baseline-clear rays.

```bash
mkdir -p .local/cullet-cover
git show 1a05552f:living/seeds/cullet.json > .local/cullet-cover/baseline.json
cargo run -p living-rules --example land_dump --manifest-path living/Cargo.toml -- .local/cullet-cover/baseline.json .local/cullet-cover/before
cargo run -p living-rules --example land_dump --manifest-path living/Cargo.toml -- living/seeds/cullet.json .local/cullet-cover/after
python3 living/tools/cullet_cover_check.py .local/cullet-cover/after
```

Native Cullet dumps before and after regeneration match byte for byte. Tiles `aba9f73ec66f029b`, heights `9604d8ab11f4274f`, layout `b7c81bc388729a4a`. The authoring change adds static input through the existing seed recipe. There are no database schema changes, new subscriptions, indexes or new per-tick data paths. [SpacetimeDB table performance](https://spacetimedb.com/docs/tables/performance/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/).
