# Cover sight

Phase 1 proposal against main at `1a05552f`. The owner chose cover for both players and minds, with facing sight retained. See [the camera decision](CAMERA.md#4-proposed-vision-and-the-owners-decision) and [perception](PERCEPTION.md).

## Shared geometry

Put cover in `living_rules::map::Map::sight_clear`, which [authority sight](../living/rules/src/sight.rs) and [Shade](../living/game/src/sightfield.rs) already call. Extend the existing per-chunk opaque summary and exact grid traversal. Preserve the corner rule and exempt the observer and destination cells for solids. For dense brush, additionally check the destination cell: someone inside a patch is hidden from outside, including when the ray first touches the brush at its endpoint. Within the same contiguous patch, occupants can see each other along rays that stay within that patch, subject to ordinary range, facing and solid cover. Use four-connected patches so a diagonal touch leaves a gap. Rays across brush from outside stop at the first dense cell. Test symmetry for the same two eye points before adding range and facing.

Build a sparse, chunk-local mask with separate sight and missile bits. Compile the eye-height classification once per affected chunk and policy revision. Rust does deterministic rasterization and queries on a typed policy. Rhai chooses the policy. Keep the existing heightless trace for rock, walls and gates, with the same fast path in worlds with the law off.

| Feature | Source and cell selection | Sight | Missiles |
| --- | --- | --- | --- |
| Tree trunk | Derive procedural positions from forest tile coordinates using the same placement function as the renderer. Move the current placement predicate from `game/src/world.rs` into shared rules. In authored plans use the placed tree resource anchor and declared trunk footprint. | Trunk footprint where the trunk intersects standing eye height | Same solid footprint for current planar missiles |
| Brush | Deliberately declared dense undergrowth in authored plans or shared deterministic generation from forest tiles. Brush height and coverage must qualify under the law. | Dense eye-height brush, including occupant concealment | Passes through |
| Cliff | For land worlds, use the regenerated height field and marked rock faces or terrace risers. Rasterize the face, using the step between adjacent walkable surfaces to qualify the marked feature. Keep ramps and gaps open. | Qualifying face cells | Same face cells |
| Existing rock, walls, shut gates | Existing terrain and gate geometry | Blocks | Blocks |

Generic forest supplies placement input. Individual trees and brush supply the blockers. Flat tile maps can use authored cliff faces where there is no shared elevation field. A drop tile also represents hazards such as an open balcony edge, so it supplies insufficient evidence of a cliff face by itself. Compare the planar rule with a 2.5D variant over the same blocker cells. Each cell carries a signed decimetre top. In the height trace the observer and target eyes use their ground heights plus the world eye height. At each crossed cell use the interpolated ray height at its traversed midpoint, and at an exact corner use the crossing height. The ray clears when it reaches or exceeds the blocker top. Terrain height is also quantized to signed decimetres at cell centres. This is a reciprocal geometric test for the same endpoints. A steep viewing angle and the placement of the terrace lip determine which high-ground overlooks stay open. Planar missile collision still uses the solid bit. Existing walls, rock and shut gates retain their existing occlusion, so this comparison isolates the new blockers.

Give both variants identical cliff masks. For worlds without an authored cover recipe, the scratch compiler qualifies terrace `Drop` cells using 2 m of local 5×5 relief and takes the highest sampled ground as the face top. Cullet uses the authored recipe at `d0f84a7eb`. It marks five quarry faces and leaves ordinary terrace steps and overlooks open. Both Cullet variants use the same eight brush polygons and seventy resource-tree trunks. The earlier Cullet layout study found rules sight to landmarks from 2–19% of streets and camera visibility from 75–99%. Compare the new traces on the same sample locations. The camera can see over existing walls, so the remaining difference also depends on those walls. [Cullet's grey-city study](SMALL_CITY.md).

## Law and seed contract

Use typed, scalar world-law rows with `cover_sight_on=false` in the shipped `laws()`. Give `cover_sight_on`, `cover_eye_height_m`, `cover_brush_on`, `cover_brush_min_fill` and `cover_cliff_step_m` individual entries in `laws_about`. Starting values to exercise in fixtures are 1.6 m for eye height, brush enabled with 0.6 minimum cell coverage and 2.0 m for cliff step. The eye-height test also applies to brush. Enable the switch in the play-test world and set it in Cullet's overlay. The overlay should emit the effective values through the same typed policy as the shipped script.

`world_law` currently holds private overrides and misses defaults and overlay-only values. Publish a narrow read-only singleton of effective world-law values to the game client, keyed by world or singleton ID, with the policy values and script revision. Refresh it on genesis and script/law installation. Shade subscribes once and rebuilds its mask on policy changes. Keep `fov_on` independent and continue to read the player's field through `my_senses`. Authority caches the policy with the script revision. Keep cover disabled during the initial Shade load until the effective policy and corresponding map are ready.

Prefer geometry already held by the game client. It receives terrain chunks and regenerates land from the published land recipe. Use the existing draft authoring names in `map.params.plans[0]`, or `map.params.cover` for worlds without plans. Coordinates within a plan use its existing transform. Cullet reuses its existing plan `resources` with `{"kind":"tree","at":[x,y]}`. A tree may supply `trunk_r_m` and `trunk_h_m`. The default trunk needs no new fields. The cover object can contain:

- `brush` entries with `id`, closed `area` polygon, `height_m` and `fill`. Compare fill with `cover_brush_min_fill`.
- `cliffs` entries with `id`, open `points` along the face's top edge, and optional `height_m`. The height field supplies the default step.
- Reserved `overlooks` entries with `id` and open `points` exempting marked cliff cells. Keep parsing this escape hatch. The 2.5D trace should handle geometry-consistent overlooks directly. Decide whether to use exemptions after examining the remaining lost views and cell rasterization.

Old seeds can omit all optional cover fields. If an input is unavailable in the published recipe for a tile world, extend its existing recipe serialization if possible. A new static chunk-keyed public geometry table is the fallback when a recipe cannot carry the geometry. Keep any author-only source private. Avoid appending columns to existing tables. Keep canopy cutaway on rendered mesh bounds. The compiled mask has no per-cell canopy height, and the bounds can describe overhead geometry that does not intersect eye height.

[SpacetimeDB tables](https://spacetimedb.com/docs/tables/) and [table performance](https://spacetimedb.com/docs/tables/performance/) support separating data by access pattern and using indexed local reads. [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) supplies matching rows initially and then deltas. The [workspace](../living/Cargo.toml) and [service](../living/deploy/compose.yml) pin 2.14.1. The proposal uses the same table, primary-key and incremental subscription primitives already used in that version. See the [2.14.1 tagged source](https://github.com/clockworklabs/SpacetimeDB/tree/v2.14.1). Keep persistent geometry bounded by map size. Once loaded, a trace does zero database reads and writes. Map edits invalidate affected chunks and their cliff neighbors. An effective-law update is one low-frequency row per world delivered to game clients. Actor visibility remains scoped through existing authority projections.

## Gaze bands and cover

Use the [settled camera proposal](CAMERA.md#4-proposed-zoom-linked-sight-and-skill-gated-pan), design commit `f01e74c35`. Middle is the exact present field and the missing-row default for both controllers in enabled worlds. Far uses about 130% of the light cap with ±35° full and ±65° peripheral reach. Middle uses 100%, ±70° and ±110°. Near uses about 60%, ±110° and ±155°. Cullet day, torch and dark radii are 48/20/14 m in Middle and about 62/26/18 m in Far. The circle covered by a 1.3× gather radius has 1.69× the area. Local density, light, glow, chunk quantization and the narrower final field determine actual work.

The base and Cullet `senses(a)` derive the light cap and invoke the same Rhai gaze modifier using the observer's applied band. The modifier returns the field, hard caps on acquisition and retention, and explicit groundsight range. The authority applies the cap to candidate gathering before visiting chunks. The shared reach test applies facing, near awareness, glow and retention inside the cap. A successful reach test then uses the shared cover trace. Hard cover cuts sight in every band regardless of the retention margin. Shade reads the owner-confirmed applied band and field from `my_senses` and the geometry policy from the effective world-law row. Existing worlds with gaze disabled retain their current gaze rules. Benchmark facing off and on for cover independently, then run Far with facing on.

`human_gaze(band: u8)` resolves the sender's character. The authorized, non-replacing `mind_act` gaze command uses the same setter. Accept at most one changed band per character every 250 ms. Use one private `attention` row keyed by character ID for the band and acceptance time, and remove it at death. One point lookup supplies attention when computing the observer's senses. Cache only with safe invalidation for a changed band and script revision. There is no direct player subscription to the private table. Measure owner-visible `my_senses` updates and aggregate subscription counters, including downstream additions/removals from changing the field. If an authorized service subscribes to attention for a benchmark, measure that subscription separately. Measure persistence work and queue/reducer time separately from traffic. Scope the owner result through the existing sender-specific view. [Views](https://spacetimedb.com/docs/functions/views/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [2.14.1 source](https://github.com/clockworklabs/SpacetimeDB/tree/v2.14.1).

Survey is deferred until public-feed scoping. Its proposed 160% radius could expand the gather area to 2.56× before the ±25° field filter. Its 3 s duration, 8 s cooldown and stationary condition affect concurrent use. The owner-only `my_survey_map` projection adds a separate delivery cost, especially at start and cancellation. Reserve that workload for a later measurement.

## Perception consequences

Immediate cover loss applies even when range or facing retention would keep a target. Reacquisition restores live client and mind visibility and may retrigger notice according to existing novelty rules. Measure edge churn as adds plus removes per observer-second, and keep player and mind counts distinct. A mind's scene should use the same trace as a player's projection. Witness tests use the event's visibility at the time and can still record an appropriate audible event through brush. Hearing range and attenuation remain separate. The existing heard-only scene and marker paths are gated by the facing field. A cover-only world still carries audible events through their existing paths, and a heard-marker policy for facing-off worlds is a separate decision. A heard cue carries only what the existing hearing path permits.

Aimed actions should use current authority sight where the skill requires a visible target. Check both acquisition and release during implementation and explicitly record which skills currently check each. A released missile follows its own collision, so a blind shot can travel through brush. Retained last-seen position and label belong to memory. Live target position, hit proxy and confirmation stop at loss of sight. No geometry hysteresis should preserve live information through hard cover. Presentation can ease the edge without revealing a hidden contact.

## Scratch measurement

Run four fresh arms per workload, crossing current/cover with facing off/on. Keep geometry, start time, model latency, observer/client counts and population setup identical within each workload. Use `cullet.json` and its actual overlay. Adjust the live census to 216 and record the resident, spawned and animal counts. For the battle use `battle_diag.py --battle 200 --walkers 16 --minutes 5 --keep-plans` with woods inside the battle footprint in every arm. Record ambient population separately. Use the fake model only. Count a representative scoped player subscription separately from the mind subscriber or label runs with only mind traffic.

Set `profile_detail=true` in each arm. Extract `tick.perception` and the available sight spans from the same window as tick samples and count the share strictly above 16.7 ms. If the revision lacks a standalone sight span, add equal scratch-only instrumentation to both arms. Sample per-database metric deltas using the method from `origin/battle-subs-metrics` at `b55d83b5`, including bytes sent, evaluated/matched delta queries, duplicate rows and connection count. Include a visibility counter at the authority's observed-set diff, so a hide and reveal between SQL snapshots both count. Record the sample interval and denominator. Compare action rate as well, since fewer attacks or witnesses can change overall cost independently of trace cost.

For writes, interleave changes across all 216 characters and also test synchronized bursts at the same offered rate. Alternate different bands, record accepted changes and compare with a realistic trace of zoom intent that includes idle intervals and repeated requests. Until an intent trace exists, report any chosen realistic schedule as a fixture. The theoretical ceiling is `216 × 4 = 864` accepted changes/s. Keep accepted changes, no-op repeats, rejects, total subscription data and owner projection traffic separately identified.

### Cullet authority measurement

Cullet used the exact authored seed and the Cullet Rhai overlay. Each arm had 64 seed residents and 152 real SDK clients, 216 live throughout, and one 20 s profiled window after warm-up. Players walked in seven clusters by lot doors, changing movement direction every 1.5 s. The client workload subscribed to scoped game views including `my_senses`. There was no external mind subscriber and no observer. In this table, Round has facing off. Middle and Far have facing on, and every live character in a Far arm was assigned Far. The sight spans include candidate enumeration and the checks, so their cost is wider than a naked grid trace. Adds and drops count every player visible-set change in the clustered workload. Edge-specific attribution would require classifying each transition against a cover boundary.

| Cover | Field | Perception ms/s | Player sight ms/s | Mind sight ms/s | Tick ms/tick | Ticks/s | >16.7 ms | kB/s | Delta evaluated / matched per s | Player adds / drops per s | Player tests/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current | Round | 88.8 | 17.0 | 0.82 | 6.83 | 42.6 | 1.6% | 807 | 6496 / 6463 | 258 / 254 | 28556 |
| Current | Middle | 101.1 | 13.3 | 0.53 | 6.38 | 47.9 | 1.5% | 700 | 6565 / 6532 | 746 / 763 | 29442 |
| Current | Far | 178.2 | 24.5 | 0.67 | 9.10 | 39.1 | 15.5% | 689 | 5719 / 5686 | 918 / 933 | 44614 |
| 2D | Round | 91.9 | 25.7 | 1.70 | 6.64 | 45.2 | 0.0% | 811 | 6831 / 6802 | 240 / 248 | 29155 |
| 2D | Middle | 111.9 | 18.9 | 0.86 | 7.07 | 45.8 | 2.2% | 708 | 6412 / 6380 | 745 / 759 | 29356 |
| 2D | Far | 124.0 | 23.0 | 1.09 | 5.64 | 49.3 | 3.9% | 700 | 5934 / 5899 | 943 / 957 | 45575 |
| 2.5D | Round | 129.4 | 34.4 | 1.80 | 9.06 | 37.3 | 9.9% | 808 | 6112 / 6081 | 265 / 255 | 29476 |
| 2.5D | Middle | 115.7 | 19.9 | 0.98 | 7.19 | 46.0 | 3.5% | 680 | 6367 / 6332 | 729 / 754 | 29225 |
| 2.5D | Far | 138.7 | 26.0 | 1.16 | 6.25 | 48.6 | 7.6% | 894 | 7363 / 7322 | 955 / 972 | 45224 |

Far increased player candidate checks from roughly 29–30k/s to 44–46k/s. The 2.5D sight spans were above the 2D spans in all three fields. Tick rate and traffic also varied between windows, including the cover-off arms. These short runs on a shared host are cost samples. They do not establish the longer performance contract. The prototype rebuilt the full land height field when loading the cover mask. In Cullet that first map rebuild took 766–774 ms, versus about 2 ms without cover. It occurred before profiling. The retained grid and collection cost below are separate from that startup work. A production implementation needs a derivation and cache path that avoids repeating full land generation on a live reducer.


### Wooded battle authority measurement

Each arm ran `battle_diag.py --battle 200 --walkers 16 --minutes 5 --keep-plans` with the fake model and the 310 ambient island characters. The same 24 m square wooded patch surrounded the site near (406.5, 237.5) in the scratch geometry. Initial fighter positions and active census varied with combat. The refill kept its default 0.5 s interval, with arrivals from about 30 m. Fighter counts below exclude the arriving fighters, walkers and ambient island actors. They show that this fixture did not sustain 200 local fighters. All-Far arms assigned Far to the initial live census and subsequent refill fighters.

Six 20 s profiled windows were sampled per arm. Rates and tick p50 are medians across windows. The late-tick share pools the tick samples. The active-fighter range is the sample range. One subscribed mind service supplied the recorded traffic, so `tick.perception` mostly had no player work. The sight span covers full mind scene enumerations. Mind churn compares consecutive full scenes per actor, including scene updates away from cover edges. Traffic uses the database counter slopes around the benchmark windows.

| Cover | Field | Perception ms/s | Mind sight ms/s | Tick p50 ms | Ticks/s | >16.7 ms | kB/s | Delta evaluated / matched per s | Mind adds / drops per s | Active fighters median (range) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current | Round | 0.03 | 10.4 | 9.16 | 51.5 | 12.2% | 725 | 522 / 422 | 60 / 53 | 80 (68–132) |
| Current | Middle | 0.03 | 9.8 | 10.95 | 45.7 | 18.7% | 720 | 491 / 399 | 128 / 118 | 88 (69–152) |
| Current | Far | 0.04 | 10.9 | 9.32 | 50.7 | 14.4% | 621 | 516 / 418 | 104 / 101 | 84 (76–138) |
| 2D | Round | 0.03 | 21.4 | 16.25 | 33.5 | 38.4% | 583 | 420 / 346 | 130 / 121 | 106 (89–158) |
| 2D | Middle | 0.02 | 16.3 | 13.45 | 40.4 | 27.6% | 557 | 453 / 370 | 93 / 82 | 112 (96–168) |
| 2D | Far | 0.02 | 14.6 | 11.17 | 46.1 | 21.4% | 481 | 486 / 395 | 75 / 70 | 112 (101–157) |
| 2.5D | Round | 0.01 | 20.9 | 12.99 | 41.1 | 26.7% | 583 | 455 / 371 | 96 / 95 | 104 (93–150) |
| 2.5D | Middle | 0.02 | 15.6 | 10.46 | 47.2 | 17.9% | 530 | 499 / 404 | 91 / 94 | 102 (94–148) |
| 2.5D | Far | 0.02 | 15.3 | 9.80 | 49.0 | 17.9% | 481 | 512 / 414 | 71 / 69 | 109 (100–160) |

The timing comparisons include changes in fight activity and occupancy. Use the native paired checks below for the marginal geometric cost. The workload-level results show the combined effects and do not establish the 60 Hz or 200-local-fighter gates.

### Attention writes at 216

The realistic synthetic schedule selected 22 of the connected players per scheduled second and called their real `human_gaze` reducer. The rate-limited saturation uses 216 changed band requests in one admin transaction every nominal 250 ms. The separate storage arm injects the same transaction pressure without the wall-clock limiter. It measures row and downstream view work at the requested rate. It does not approximate 864 separate client reducer dispatches. The table uses actual elapsed time and accepts only successful changes. The initial authored saturation attempt hit the limiter and was rerun with rejection counting.

| Attention arm | Offered/s | Accepted/s | Tick/s | >16.7 ms | Perception ms/s | kB/s | Delta evaluated / matched per s | Reducer CPU µs/accepted row |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Human gaze trace | 23.1 | 23.1 | 42.6 | 6.0% | 135.1 | 704 | 6134 / 6098 | 10.9 |
| Rate-limited batches | 864.0 | 637.2 | 39.7 | 4.9% | 141.6 | 1397 | 7706 / 7681 | 0.8 |
| Storage injection | 864.0 | 864.0 | 40.1 | 2.2% | 149.1 | 1571 | 8059 / 8028 | 0.7 |

The private attention table generated 0 direct player subscription bytes. Its consumer was the authority. The measured delivery totals include `my_senses`, changed visible contacts and other subscribed game views. Per-database counters cannot isolate bytes by view. Actual player zoom telemetry was unavailable. Batched reducer CPU per accepted row includes the cost of rejected calls in the limiter arm.

The scratch prototype is in the `cover-sight` worktree and stays behind `cover_sight_on`, shipped false. Scratch gaze and elevation can be toggled separately. Its narrow purpose is cost measurement. The currently scoped implementation leaves the planned public policy row, shared Shade mask loading, full mind intent protocol, precise band ceilings and owner-band projection to the implementation phase. It uses the existing player `my_senses` view for effective-field traffic. The attention table is private. The prototype can set an entire cohort with one admin transaction, which isolates row and view work from individual reducer dispatch cost.

Historical Cullet evidence reports a median 82 ms/s in `tick.perception`, about 40 ticks/s and 0% over 16.7 ms at 216 WebSocket players in the shipped four-phase sweep arm. That used an earlier revision on dev-box. [Historical Cullet results](PERCEPTION.md).


## Authored Cullet geometry probe

The authoring input is the exact seed at `d0f84a7eb` on `origin/cullet-cover`, read into scratch without merging it. There are eight brush polygons, including two hedges, five quarry faces, seventy default 0.20 m radius × 3.2 m trunk trees and zero overlook exemptions. Both traces use identical compiled blocker cells. The native land dump matches dev-box's tile, height and layout digests.

The native probe uses the shared Rust trace, excluding range and facing for street readability. It uses the same 330 authored street samples as dev-box. The landmark ray stops immediately before it enters the target footprint, with its 2.5D height interpolated toward 90% of the landmark's height. The geometry columns to the right keep finite building envelopes or remove them at the same 1.6 m eye. Camera uses the historical 11.9 m ground-relative sample with the finite envelopes. Those three counterfactuals retain terrain elevation and hard non-building tiles.

| Landmark | Shared 2D | Shared 2.5D | Dev-box 2.5D model | Eye with buildings | Eye without buildings | Camera with buildings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cone | 15.8% | 15.8% | 14.8% | 27.0% | 44.8% | 40.9% |
| Counting House | 23.9% | 23.9% | 20.0% | 26.1% | 46.4% | 43.9% |
| Heron | 27.3% | 27.3% | 23.6% | 41.8% | 62.1% | 45.2% |
| Watchglass | 20.6% | 20.6% | 11.2% | 11.2% | 48.5% | 17.9% |
| Lintel | 10.6% | 10.6% | 1.8% | 1.8% | 3.0% | 20.0% |

Shared visibility is identical with cover off, planar cover and height cover for each landmark. The shared trace held all 1,890 route rays clear in each arm. These routes needed no overlook exemption. It found 0 m² of brush on the route strips. Dev-box's model held 1,806/1,890 clear with and without cover and found the same 0 m². Its ground test applies at every crossed cell, and its buildings have a separate volume test. The shared prototype applies height comparisons only to new cover cells. The two models therefore measure different baseline obstacles even on identical sample positions.

The cited 75–99% was an earlier layout and its own street sample set. That camera model traced to the target top over ground and finite roofs. Current terrain and building silhouettes matter independently. For instance, removing buildings at eye height raises Watchglass from 11.2% to 48.5%, while raising the eye with buildings still present brings it to 17.9%. On the same current samples, a camera ray with finite roofs and terrain elevation, omitting the hard tile tests, sees the Cone from 91.5% and Counting House from 96.4%, but the Heron from 48.2% and Watchglass from 31.8%. The historical camera range should not be used as a target for character sight. [Historical layout and camera evidence](SMALL_CITY.md#8-build-plan).

| Warm native geometric checks | 2D ns/check | 2.5D ns/check | Pairs changed / tested | Mask cells | Logical top payload | Additional ground grid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cullet | 391.6 | 411.8 | 269 / 23,220 | 1,027 | 2,054 B | 2,097,152 B |
| Wooded battle site | 71.8 | 79.6 | 0 / 23,220 | 219,511 | 439,022 B | 8,388,608 B |

All changed Cullet pairs became visible. The woods sample uses 216 walkable positions near the scratch battle centre at (406.5 m, 237.5 m). It tests exactly the same 23,220 unordered pairs in each mode. The checked maps share a signed 16-bit decimetre top per occupied cell in both variants. Per allocated map, the native hash capacity holds space for at least 14,336 B of Cullet keys and values or 1,835,008 B for the island, before hash metadata and allocator overhead. The ground grid is present only for the live height trace. The probe does not include the authority, a combat workload, subscriptions or multiple module instances.

### Cover-edge trajectories

A separate native probe drew observations at the ordinary 5 Hz player sweep cadence along one path beside the authored Hanger brush and one beside the scratch battle grove. It used fixed walkable target grids within a 16 m test range, facing off, and excluded the initial membership. These isolate geometry and range transitions from battle deaths and player turns. Invalid observer positions were skipped at their original time. The live aggregate above has no per-transition edge tag.

| Edge | Samples | Targets | Current adds / drops per s | 2D adds / drops per s | 2.5D adds / drops per s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hanger brush | 42 | 289 | 10.6 / 10.6 | 0.4 / 3.9 | 0.4 / 3.9 |
| Battle grove | 31 | 199 | 4.3 / 0.6 | 14.4 / 13.8 | 14.4 / 13.8 |

## Evidence

Authored Cullet live results and module logs are in `.local/cover-sight/cover-c-auth-*`. The battle arm records and per-window samples are in `.local/living/verify/minds-cover-210457-*`. Prototype geometry, data, landmarks and counterfactuals are in `.local/cover-sight/authoring/`. Each scratch run paused its world, read back pause and deleted the database. Full implementation and end-to-end gameplay verification remain separate from these measurements.

## Phase 2 implementation

Cover ships off in the base law. Cullet's overlay turns it on, with brush, since the 2026-11-19 [switch-on](#switch-on-2026-11-19); every other seed keeps it off. The common DDA in
[`Map::sight_clear`](../living/rules/src/map.rs) chooses the height-aware path only when it
has a mask. The authority uses that same map for player, mind and animal sight. Missile
collision reads the separate solid bit. Existing rocks, walls and gates retain their
original rules. Trunks and faces use a signed decimetre top. Brush has its own top and
patch index so occupants can see one another along rays within a patch. Overlooks are
parsed and reserved.

The land generator already has the elevation field at genesis. In a world whose cover law is on
when it is created, the authority samples it once at tile centres and writes quantized bands
with the procedural cover candidates. In any other world it writes none, and switching cover
on later derives them in steps ([cover geometry](#cover-geometry-only-where-cover-is-on-2026-11-20)).
This lives privately in `cover_ground`, and the enabled module map compiles the sparse
chunk mask from these bands once per map cache load. Cover-off map loads read no bands.
Runtime mask compilation does not generate land. The sparse mask uses a chunk directory and occupied row bits. If a ray's bounding rectangle has no cover cells, it takes the legacy trace without eye interpolation. The map uses static
genesis cover geometry while live terrain edits and gate state apply through the
existing terrain trace. [Shared cover compiler](../living/rules/src/cover.rs).

The acceptance Cullet mask with brush uses 334,624 bytes, plus 2,097,152 bytes
of quantized ground. Genesis sampling took about 138 ms. The mask compiled in
15–16 ms on activation. In the wooded island, the mask uses 9,718,816 bytes,
plus 8,388,608 bytes of ground. Genesis sampling took about 803 ms, and mask
compilation took 50–51 ms while the world was paused for setup. These figures
are per cached mask and ground buffer and exclude table storage overhead. Cell
tops are signed 16-bit decimetres.

### Public `cover_law` singleton

| Field | Type | Shade use |
| --- | --- | --- |
| `id` | `u8` | Primary key, always 0 |
| `cover_sight_on` | `bool` | Selects the enabled cover mask |
| `cover_eye_height_m` | `f32` | Computes the eye and target ray heights |
| `cover_brush_on` | `bool` | Selects brush concealment |
| `cover_brush_min_fill` | `f32` | Qualifies rasterized brush |
| `cover_cliff_step_m` | `f32` | Qualifies unmarked terrain steps |

This is a new table. The module writes it only on initial creation or an effective
policy change. Geometry bands remain private. The change does not add a gaze
protocol or expose attention. [Tables](https://spacetimedb.com/docs/tables/),
[performance](https://spacetimedb.com/docs/tables/performance/),
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/),
[SpacetimeDB 2.14.1](https://github.com/clockworklabs/SpacetimeDB/tree/v2.14.1).

### Client edits and scratch recipe

- [`net.rs`](../living/game/src/net.rs) subscribes to the effective cover policy once.
- [`live.rs`](../living/game/src/live.rs) retains the parsed land recipe for Shade.
- [`sightfield.rs`](../living/game/src/sightfield.rs) builds the shared mask from the
  regenerated land and policy, caching it across camera and terrain window updates.
  Shade's existing single `clear_line` entry calls `Map::sight_clear`.
- [`world.rs`](../living/game/src/world.rs) calls
  [`living_rules::cover::forest_tree`](../living/rules/src/cover.rs) for its tree
  placement predicate, and the shared coordinate sampler for existing variation.
  The tree positions and camera's mesh cutaway use their existing behavior.

Launch a fresh scratch world with `--seed cullet` to load the checked-in Cullet seed and its normal overlay. That seed includes the brush and quarry faces. After launch and doctor, use the scratch verify run name in both commands:

```sh
python3 .agents/skills/verify/scripts/verify.py call --run core-cover-capture \
  set_world_law '["cover_brush_on","true"]' --as-admin
python3 .agents/skills/verify/scripts/verify.py call --run core-cover-capture \
  set_world_law '["cover_sight_on","true"]' --as-admin
```

Read back `SELECT * FROM cover_law` under the player's identity. Clearing the scratch
test uses `["cover_sight_on","false"]` in the same command. This recipe is for new
scratch worlds with the genesis cover bands.

The scratch recipe was exercised on `verify-core-cover-012742` using the checked-in Cullet seed and its overlay. Useful positions for the laptop's stills
are below. Coordinates are land metres.

| Frame | Viewer | Target |
| --- | --- | --- |
| Behind a trunk | (781.5, 457.5) | (785.5, 457.5) |
| In brush | (608.5, 479.5) | (608.5, 472.5) |
| Across a cliff face | (390.5, 291.5) | (390.5, 286.5) |
| Overlook | (849.5, 613.5) | (842.5, 613.5) |

The live proof checked those four positions with cover off, on and off again. It
also checked arrows, player lines and the pending mind-scene target. See
`.local/living/verify/core-cover-012742/cover-proof.jsonl` (23 passing assertions). The SDK probe at
`.local/living/verify/client-cover-015635/` accepted `cover_law` and rejected
access to `cover_ground` and `attention`. The authored land dump preserved the
three pinned digests.

### Phase 2 acceptance

The acceptance runs used the rebased implementation at `1d9eb7c1`. Each fresh
scratch Cullet run had 64 ambient residents and 152 SDK game clients, for 216 live
characters at both censuses. The four arms per field ran off, on, off, on, with a
30-second profiled window per run. Each acquired the shared `battle.lock`.
Sight time is the sum of `sight.player_candidates` and `scene.sensed`. Tick
duration is the mean. Traffic comes from the server's per-database client bytes
counter. Adds and drops count player-visible-set transitions.

| Cullet field | Cover | Runs | Sight ms/s | Tick ms | Ticks/s | >16.7 ms | kB/s | Adds/s | Drops/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Round | Off | 2 | 27.02–39.21 | 2.52–3.95 | 59.13–59.47 | 0% | 803.3–813.6 | 259.1–261.2 | 253.1–255.8 |
| Round | On | 2 | 27.09–28.29 | 2.35–2.48 | 59.53–59.53 | 0% | 780.7–797.2 | 239.6–251.7 | 234.1–248.2 |
| Middle | Off | 2 | 25.52–28.33 | 2.78–3.08 | 59.23–59.43 | 0% | 688.7–701.7 | 731.2–754.4 | 743.7–766.9 |
| Middle | On | 2 | 29.00–30.42 | 3.06–3.18 | 59.33–59.33 | 0% | 670.7–690.7 | 735.6–741.0 | 750.0–753.4 |

Round passed both spread checks. Middle passed the late-tick check and exceeded
the cover-off sight spread in both cover-on runs. The gate therefore stays closed.

The wooded battle used a deterministic island site with 149 forest cells in a
17×17 patch and an authored brush strip. Each arm ran for five minutes with
facing on. The census recorded 96 of 96 fighters alive within 30 m at the
start and end of all 24 profile windows, alongside 16 walkers and the
310 ambient characters. We held spear damage low in both arms and used no
refill. An owner SDK connection subscribed to mind data with no inference
service. Sight measures `scene.sensed`, and adds and drops are mind-visible-set
transitions. Windows were five seconds each. The preliminary 20-second
windows overflowed the server's detailed log tail and were excluded.

| Wooded battle | Runs | Sight ms/s | Tick ms | Ticks/s | >16.7 ms | kB/s | Adds/s | Drops/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cover off | 2 | 25.09–27.31 | 6.04–6.26 | 57.47–57.80 | 1.64–1.82% | 431.4–432.1 | 87.0–134.2 | 99.5–119.3 |
| Cover on | 2 | 27.58–28.38 | 5.66–7.08 | 54.52–58.53 | 0.62–2.77% | 364.4–396.1 | 86.6–92.0 | 89.9–92.6 |

The wooded battle missed the sight gate in both cover-on runs. One cover-on
run had fewer late ticks than either control, and the other had more. The
shared lock covered each run. No other battle or scene process was detected
inside the measured windows. See `acceptance-host.csv` in the evidence archive
for per-run load, memory and population checks, and `acceptance-summary.txt`
for run-level numbers. Far, visual captures at the three zoom stops, a
separate live animal scene and a separate live replay against the unmodified
main binary were outside the evidence collected here.

## Switch-on gate (standing rule, 2026-11-19)

The general coordinator restated the switch-on gate as a cost budget, which replaces the
"within the cover-off spread" test used in phase 2. That test, with two runs per arm,
demanded zero cost, while the 2.5D blocker test does measurably more work per check
(+5–11% per check in the native probe). The rule for turning `cover_sight_on` on in any
world, and for later changes to the trace. The same rule applies to gaze (`CAMERA.md` §4) and
other sight-cost features:

- **Sight cost:** sight ms/s with cover on is at most **+15%** over the cover-off arms' mean.
- **Tick health (one-sided, 2026-11-19):** ticks/s with the feature on are no lower than the
  lowest off run, and the share of ticks over 16.7 ms is no higher than the highest off run.
  A run that is better than every off run passes; the test only guards against being worse.
- **Runs:** interleaved off/on, at least **4 runs per arm** for the wooded battle at a fixed
  local fighter count, and at least 2 per arm for Cullet 216 (Round and Middle), under
  `~/slop-mq/battle.lock`, with host load recorded per run.

Phase 2's Cullet runs pass this budget (Middle: on 29.0–30.4 against an off mean of 26.9 ms/s,
+13%; ticks and late ticks unchanged). The battle needs two more runs per arm before a verdict.
When it passes, `cover_sight_on` and `cover_brush_on` go on in Cullet's overlay (its brush and
hedge visuals are on main) and in the play-test world.

## Switch-on (2026-11-19)

Branch `sight-on`. The general coordinator let it merge ahead of the wooded battle runs once `living-check` and the two scenes below passed. The battle budget above stays the gate for any battle-scale world and for turning a law on by default.

**Cullet is directional for everyone.** Its `fov_on` goes from false to true on main, for players and minds alike, as the owner approved: "woods hide people, with sight depending on which way you face". With gaze on, Middle is the shipped directional field, so a resident who never sets a gaze sees what `fov_on` alone gave.

What is on where:

| World | `cover_sight_on` | `cover_brush_on` | `gaze_on` | `fov_on` | Where it is set |
| --- | --- | --- | --- | --- | --- |
| Cullet (`cullet.json`) | true | true | true | true | `laws()` in [Cullet's overlay](../living/seeds/worlds/cullet/laws.rhai) |
| `cullet-laws`, `hamlet`, `hamlet-6` (they share Cullet's overlay) | false | false | false | false | their seed `rules`, which keep the values they had before |
| The play-test world (the island seed with the laptop's scene overlay, `.local` on the laptop) | true | shipped (true; the island has no authored brush, so it hides nothing) | true | true | `laws()` in the scene's overlay, by the laptop (the lines below) |
| Every other seed | false | shipped | false | false | the base law |

`fov_on` is set explicitly beside gaze: enabling gaze makes Middle directional even where `fov_on` is false ([camera §4](CAMERA.md#gaze-authority-implementation)), so the line states what the world does. The play-test scene's overlay is not in the repository; its `laws()` gains, beside play-test 9's `turn_rate` and `look_walk_deg`:

```rhai
fn laws() {
    let policy = base_laws();
    policy.turn_rate = 30.0;          // play-test 9
    policy.look_walk_deg = 180.0;     // play-test 9
    policy.cover_sight_on = true;
    policy.gaze_on = true;
    // Enabling gaze makes Middle directional even where fov_on is false (CAMERA.md §4); explicit.
    policy.fov_on = true;
    policy
}
```

A world needs its cover bands (`cover_ground`) for the switch. Since `cover-genesis` (2026-11-20), a land made with its cover law off (the island) has none. When the overlay is installed, it derives them in steps (about 6 s on the island before `cover-stall`, about 2 s since, [the cover-stall fix](#the-cover-stall-fix-2026-11-20)), and cover is in force once they are complete ([cover geometry](#cover-geometry-only-where-cover-is-on-2026-11-20)). Before that, the play-test world had to be made fresh from a module at or after `7619ad71`.

**Island creation and an overlay (found 2026-11-19).** A module with the island seed compiled in *and* the play-test scene's overlay as the seed's `laws` ran out of reducer energy in `init`, with or without the switch-on lines; the plain island seed created normally on the same server. The scratch proof therefore made a plain island world and installed the composed overlay with `living/tools/install_script.py <db> --seed <seed>`. A play scene that compiles the overlay into an island module may hit the same limit. Proof: verify-player `sight_on.py` ([cover in a player's projection](../.agents/skills/verify-player/features/cover.md)) on scratch worlds of Cullet and of the island with that overlay, with the laws as shipped and no admin override before the checks. Its validation record is in `.agents/skills/verify-player/references/validation/`.

## Cover geometry only where cover is on (2026-11-20)

Branch `cover-genesis` (Spark), measured on main `b6aa7489` (staged genesis: every seeded world is made by `genesis_step` after `init`) and checked again on `a4d4b2ab`, rustc 1.99.1, SpacetimeDB 2.14.1 on a private server. A creation's last, finishing `genesis_step` (`floor::finish`) publishes the cover in force; when the law went on during creation after hosting, it also starts the derivation.

Before this branch, every land sampled its ground at every tile centre in its hosting step and kept it in `cover_ground`, whatever its cover law. That made `floor-megacity-4k`'s hosting step run out of energy, so the floor stalled at step 130 of 141. It was also most of every other land's hosting step. Now a world keeps cover geometry only when cover is on. The same rules apply to players and minds. Where cover is on, the bands are byte-identical to before.

### What it cost

Fuel from `living/tools/genesis_fuel.py --seed S` (a stepping build; `--floor-seed` for the megacity floors), main against the branch. The guard's rule is no step above 50 × 10⁹.

| Seed | `init` main / branch | Hosting step main / branch | Cover band steps (branch) | Largest step main / branch | Steps main / branch |
| --- | ---: | ---: | ---: | ---: | ---: |
| island | 11.56 / 11.56 × 10⁹ | 19.04 / **1.43** | — | 25.25 / 25.25 (populate) | 40 / 40 |
| Cullet (cover on) | 37.27 / 37.36 | 4.08 / 0.51 | 1 step, 3.74 | 7.78 / 7.78 (populate) | 23 / 24 |
| plan-test | 11.44 / 11.52 | 3.66 / 0.26 | — | 4.91 / 4.91 (land) | 25 / 25 |
| cullet-laws, world (not lands) | 37.21, 11.47 / 37.21, 11.44 | — | — | 0.34, 5.96 / same | 1 / 1 |
| floor-megacity-2k | 10.10 + `create_floor` 1.40 / 10.11 + 1.36 | **38.39** / 3.32 | — | 38.39 (hosting) / 27.40 (land) | 119 / 119 |
| floor-megacity-4k | 10.10 + 1.40 / 10.11 + 1.36 | **out of energy at 120** (step 131) / **14.94** | — | 120 (trap) / 28.80 (land) | stalls at 130 / 142, done |
| island with seed rule `cover_sight_on: true` (floor) | — / 10.11 + 1.44 | — / 1.48 | 4 steps, at most 4.65 | — / 24.06 | — / 44 |
| floor-megacity-4k with `cover_sight_on: true` | (traps) / 10.11 + 1.37 | — / 15.29 | 16 steps, 4.23–11.25 | — / 28.80 | — / 158 |

After the fix, no step needs splitting: the largest on any seed is a land-generation step (28.8 × 10⁹ at 4096 m). The first measurement, against `16f50c0c` before staged genesis, gave the same picture inside `init`. The island's `init` went from 118.32 to 100.65 × 10⁹; `floor-megacity-2k` went from out of energy to 90.91 × 10⁹; Cullet's bands were identical.

Native split on `living/tools/land_fuel` (wasmtime configured as 2.14.1), with a temporary export that was not kept:

| Land | `cover::ground` | `cover::candidates` | Hosting and digests |
| --- | ---: | ---: | ---: |
| island (2048 m) | 17.49 × 10⁹ | 0.12 × 10⁹ | 1.26 × 10⁹ |
| plan-test, Cullet (1024 m) | 3.37, 3.58 | 0.03, 0.02 | 0.23, 0.22 |
| megacity 2048 m | 34.98 | 0.09 | 3.23 |
| megacity 4096 m | **129.9** (eight slices of 8.3–22.1) | 0.36 | 14.77 |

Sampling is the cost: about 4 × 10³ WASM instructions a tile on the island and 8–10 × 10³ in the megacity, where every height evaluates the city's lots and roads. Persisting the bands is about 0.2 × 10⁹ on the island. On main the 4096 m floor's hosting step needed about 145 × 10⁹: 14.9 without cover, plus about 130 for sampling.

### The design

- **At creation, only when the effective law is on.** The law is the seed's overlay and `rules`, installed in `init` before the land (`floor::begin`). The staged creation keeps the generated land after hosting and samples it in band steps of 64 bands (1,048,576 tiles; `geometry::BANDS_PER_STEP`) after the terrain chunks. `cover::ground_range` gives exactly `ground`'s values for any range of tiles (Cargo `ground_in_bands_is_ground`). With cover off, nothing is sampled or kept.
- **Derived when switched on.** `set_world_law cover_sight_on true` or an `install_script` whose laws turn cover on starts the derivation. So does the end of a staged creation whose law went on after hosting. This applies on a made land without complete geometry: `geometry::ensure`, in the same transaction as the law write. `cover_step` is a one-shot scheduled reducer that does one bounded step and schedules the next, 100 ms later, like `genesis_step`. First the land is generated again from the `land` row's seed and side and the full parameters (`land_plan`), in `Gen`'s steps. Then the hosted tiles are rebuilt and checked against the `land` row's tile and height digests; a module whose generator differs stops with that reason instead of keeping other heights. Then the bands are written 64 per step. The private `cover_derivation` row shows progress, restarts and `done`, or `stopped: …` with the reason. The instance's memory is a cache. A step that finds the cache is not this land's, or not as far as the row says, starts generation again. Kept bands are kept, since they are written in order and the next band is the count kept. Switching cover off stops the derivation, and switching it on again carries on.
- **In force only when complete.** `common::cover_in_force` publishes `cover_law.cover_sight_on` as on only when every band is kept (`geometry::ready`, a `land` point lookup and the table's row count). The map compiles no mask before then, and Shade, which follows the `cover_law` row, builds none. Players, minds and clients therefore see the same thing during the derivation. The last step writes a law revision so every cached map compiles its mask on its next read (the tick right after), then publishes the row as on. The admin's own value stays in `law_override` throughout.
- **Refusals.** `cover sight requires a land world (a seed whose map kind is "land"), once it is made` replaces "cover sight requires a land created with quantized cover geometry", which was no longer true. `set_world_law` and `install_script` refuse it on a world with no `land` row: a world that is not a land, or a floor before its land exists. A seed that is not a land is refused by `floor::begin` as before.

Two new private tables: `cover_derivation`, one row, and `cover_timer`, its schedule. They add no columns to existing tables. The new scheduled reducer `cover_step` refuses any caller but the module itself, as `genesis_step` does. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) say one-shot rows are deleted after the reducer runs. The [lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle) page says scheduled calls carry the module's own identity. [Reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior", is why the in-memory land is only a cache. These are the 2.0 docs. The failure behaviour of one-shot rows was settled for floors against the `v2.14.1` source (docs/FLOORS.md, "A stopped chain"), and this chain relies on the same behaviour. [Tables](https://spacetimedb.com/docs/tables/): `count()` is the documented row count; the docs do not state its cost, and it is read once per step and per policy check, not per tick.

### Data paths

| Path | Reads | Writes | Recipients | Frequency |
| --- | --- | --- | --- | --- |
| Creation, cover off | nothing of cover | `cover_law` (off) | `cover_law` subscribers | once |
| Creation, cover on | the land in memory | `cover_ground` bands (island 256 × 32 KiB; 4096 m 1,024), `cover_law` | none for the bands (private) | once |
| Switch-on derivation step | `cover_derivation`, `land`, `land_plan` (point lookups), `cover_ground` count | one `cover_derivation` update, a `cover_timer` row; band steps 64 rows | none (private) until the last step's `cover_law` update | about 40 steps on the island, 147 at 4096 m, 100 ms apart |
| Policy check (`map`, on a law or script revision) | `land` point lookup, `cover_ground` count | — | — | per revision, not per tick |

The retained data is the same bands as before, and only in worlds that use cover. A derivation's land sits in module memory until its last step. It raises the instance's linear memory, which never shrinks, by the generation peak: about 60 MB on the island and 210 MB at 4096 m (`land_fuel`).

### What a derivation costs a running world

| World | Steps | Fuel in total | Largest step | Wall time |
| --- | ---: | ---: | ---: | ---: |
| island, live | 40 | 72.9 × 10⁹ | under 29 × 10⁹ (land generation, about 1.2 s) | 6.8 s |
| megacity 4096 m, live | 147 | 450.8 × 10⁹ | 28.8 × 10⁹ (land tile rows, 1.0 s) | 31.4 s |

Each step blocks the module while it runs, so ticks stopped for up to about a second during the large land steps. Superseded by [the cover-stall fix](#the-cover-stall-fix-2026-11-20): a land made since samples its kept ground source in steps of a few ms; a land made before still generates again, with shorter tile steps.

### Staged creation with cover on (4096 m megacity, seed rule `cover_sight_on: true`)

| | Main | Branch, cover off | Branch, cover on |
| --- | --- | --- | --- |
| Steps | stalls at step 130 of 141 (hosting traps) | 142, done | 158, done |
| Hosting | traps at 120 × 10⁹ | 14.9 × 10⁹ | 15.3 × 10⁹ |
| Cover band steps | (inside hosting) | — | 16, 4.2–11.3 × 10⁹ each |
| Largest step | 120 (trap) | 28.8 × 10⁹ (land tile rows) | 28.8 × 10⁹ |
| Fuel in total | — | 346.7 × 10⁹ | 481.6 × 10⁹ |
| Made in (back to back, ordinary build) | — | about 40 s | about 40 s |

### Proofs

- **Identical bands.** sha256 over every `cover_ground` row (id, heights, candidates):
  - island: main's genesis (cover off but sampled, at `16f50c0c` and at `b6aa7489`), the branch with the seed rule on, and the branch switched on after creation are all `e36c6426…` (256 rows).
  - Cullet: main (`16f50c0c` and `b6aa7489`) and the branch (staged band step) are all `6c1e9b53…` (64 rows).
  - 4096 m megacity: staged with cover on and switched on after creation are both `24ebfd97…` (1,024 rows). Main cannot make it.
  - plan-test: a compiled seed switched on, a floor switched on, and a floor updated to another build mid-derivation (one restart) are all `278e39c1…` (64 rows).
- **Behaviour.**
  - `cover_law` reads false right after the switch and true after the last step.
  - The tick compiles the mask in the next transaction: `cover: 1778144 mask bytes` on plan-test.
  - Switching off mid-derivation stops it; switching on again finishes it.
  - The refusal on the default world names the new reason.
  - An update with the same module kept the instance (no restart). An update to another build restarted generation once and kept the bands.

Evidence: `~/slop-evidence/cover-genesis-20261120.tar.zst`, with `results.jsonl`, the step traces, the band digests and the measurement patches.

### Limits

- The dead inline path (`seed::seed` for a land, used now only by a test) still samples the whole ground in its one call when cover is on.
- A derivation generates the land again. Its cost is the land's generation plus sampling: island about 73 × 10⁹, 4096 m about 450 × 10⁹. Up to a second at a time, it runs on a world that may be ticking.

## The cover-stall fix (2026-11-20)

Branch `cover-stall` (Spark), on main `f9b36cef` and before it `79cb4a42`, rustc 1.99.1, SpacetimeDB 2.14.1 on a private server.

### What the laptop saw

On island scratch worlds (main `75e26fca`), switching cover on stalled the tick for 829–936 ms. The `cover_law` row reached the client 5.45 s after `set_world_law cover_sight_on true`, and 2.44 s after a later `set_world_law cover_brush_min_fill …`. verify-ui `law-override` passed 68 of 72, and all four failures were cover laws (timing).

### Why

- **The stall.** SpacetimeDB runs one reducer at a time per database, in the order calls are queued. The 2.14.1 host runs a WASM module's reducers on "a single executor backed by a single OS thread" (`crates/core/src/host/module_host.rs`, `WasmtimeModuleHost`: "Reducers are not executed concurrently"). Its scheduler hands each due scheduled call to that executor as it comes due (`host/scheduler.rs`, `SchedulerActor`). So the tick waits behind whatever runs. The derivation's steps were the land generation's own steps: up to 24 × 10⁹ instructions on the island (all 2048 tile rows in one step, 0.9 s) and up to 29 × 10⁹ at 4096 m.
  - Procedures are no way out. A WASM procedure takes an instance from the procedure pool but runs on the same executor thread, and yields it only while it awaits (an HTTP request, a sleep). CPU-bound work in a procedure blocks ticks just the same.
  - The docs pages (version 2.0.0) do not say reducers run one at a time. [Reducers](https://spacetimedb.com/docs/functions/reducers/) reserve the right to run reducers "concurrently in separate execution environments", which is why module memory stays a cache here. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) say one-shot rows are deleted after the reducer runs, and that the dispatch order of rows already expired is not guaranteed. A derivation has one row at a time, so ordering cannot reorder its steps.
- **The brush-fill delay was not a re-derivation.** `set_world_law cover_brush_min_fill` with the bands kept is value-only: `geometry::ensure` returns at once, and only the `cover_law` row and the mask change. In the laptop's run, the scenario changes the brush 3 s after the switch-on, while the derivation was still running. The game client shows a cover policy only once `cover_law.cover_sight_on` is on (`sightfield.rs`), so the brush edit's effect line came when the derivation ended: 5.45 − 3.0 ≈ 2.45 s. A brush edit after the derivation took 0.5–0.8 ms in the reducer on both branches. The mask compile on the next tick, though, read all 256 bands back (8 MB of rows) and took 50–73 ms on the island (now 4–7 ms, below).

### The design

- **A ground source, kept at creation.** A land made with cover off now keeps, in its hosting step, what its ground heights are computed from: `Land::ground_source`. That is the macro grids, the sites' levelling, the shore distances (run-length coded) and the roads' and lots' shaping, encoded exactly, floats by their bits. It also keeps the tree and cliff candidates of the hosted tiles. They go in the new private table `cover_source` (256 KiB rows, never written again). Sizes: island 3.8 MB in 15 rows; the 4096 m megacity 9.0 MB in 35 rows. `Land::from_ground_source` gives a land whose `height` and `water_level` are bit for bit the generated land's (Cargo `ground_source_samples_the_land`: a default land and plan-test, every tile, plus the heights digest).
- **A switch-on samples it in short steps.** No generation is involved. Each `cover_step` does one of these:
  - reads two source rows;
  - decodes one part (`living_rules::land::GroundDecode`: grids and sites, shore distances, segments, pads and plans' ground, the shaping index built again);
  - checks 6,144 lattice points of the land row's heights digest (`host::heights_digest_rows`; a module whose ground differs stops with that reason);
  - samples half a band (8,192 tiles), writing the band's `cover_ground` row once its second half is sampled.

  Steps follow one another at once (`ScheduleAt::Time` at the step's own start, so due immediately). A tick queued meanwhile waits for one step at most.
- **No mask compile reads the bands back.** The last step hands what it sampled to the map's cover cache (`common::keep_cover_geometry`). Without it, the first compile reads the bands once into that cache. A later value-only cover edit (eye height, brush, cliff step) then compiles the mask from memory; it never derives anything.
- **Lands made before this branch** have no ground source. They still generate the land again, now with the tile rows in steps of 32,768 tiles instead of one, and the same half-band sampling. Their other generation steps are not split (the island's longest, the planner's lots, is about 0.5 s; up to 12 × 10⁹ at 4096 m), so a switch-on there still stalls the tick up to about half a second on the island. Pause such a world first if that matters, or make it again.
- **The same rules for players and minds.** Cover is in force for everyone at once, when the last band is kept, as before.
- **Bands are byte-identical.** sha256 over every `cover_ground` row (cover-genesis's `bands.py`):
  - island, from the source: `e36c6426…` (256 rows);
  - island made by main and then updated to this branch (the regeneration path): `e36c6426…`;
  - 4096 m megacity floor, from the source: `24ebfd97…` (1,024 rows).

  These are the digests cover-genesis recorded for creation with cover on and for its switch-on.

### Data paths

| Path | Reads | Writes | Recipients | Frequency |
| --- | --- | --- | --- | --- |
| Creation, cover off (hosting step) | the land in memory | `cover_source` (15 rows on the island, 35 at 4096 m) | none (private) | once per land |
| Switch-on step from the source | `cover_derivation`, `land`, `land_plan`, `cover_source` (2 rows, then none), `cover_ground` count | one `cover_derivation` update and one `cover_timer` row per step; one `cover_ground` row every second sampling step | none until the last step's `cover_law` update | about 540 steps on the island, 2,110 at 4096 m, back to back |
| Mask compile after a policy change | the cover cache (memory); the `cover_ground` rows once per instance when it is empty | — | — | per policy change |

Retained data grows by the source: about 3.8 MB per island-sized land, about 9 MB at 4096 m, kept whether or not cover is ever switched on (half the bands' 8 MB and 32 MB). The decoded source lives in module memory during a derivation, about 30 MB at 4096 m, against the regenerated land's 60–210 MB.
