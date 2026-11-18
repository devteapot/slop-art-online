# Lower camera curve and compact hover, 2026-11-18 20:14 UTC

The release client built through build-slot and `cargo test -p living-game` reported 129 passed, 0 failed and 1 ignored. The toolchain reported a missing LLVM library during debug symbol postprocessing, but Cargo completed successfully. The laptop run used the private camera branch target directory.

The three top-down knots are Far (0.00, 19 m, 65°, 46°), Middle (0.55, 12 m, 58°, 44°), and Near (1.00, 8 m, 48°, 42°). The vertical FOVs were retained. Middle frames the torso and legs of the player and the resident, with room for the person window. The overhead hover uses the known name or the short outfit phrase. The target plate retains the detailed phrase at make-out range.

## Play-test 8 street

Run `ui-camera1-lower-1118-211454` used the copied play-test 8 scene with its own Rhai overlay (installed script SHA-256 prefix `c2748445bfe9`). The noon sight radius was 48 m. Facing on used the authority's 70° focal angle, 110° side angle, 10° margin, 3 m near distance and 0.3333 side share. Facing off used the same radial sight and occlusion. The market stall cutaway engaged at all six combinations of stop and facing setting. The resident behind the wall stayed hidden and the rear resident dropped out of the facing-on projection. Both Middle drives verified the short hover and longer target descriptions.

`camera` passed 60/60 and `camera-lod` passed 15/15. The run wrapper was edited during the run and emitted a shell parse error after the completed checks. Its exit handler removed the scratch database and module. The following runs used the syntax-checked wrapper.

The facing-on stills are in `.local/living/verify/ui-camera1-lower-1118-211454/ui/camera-on/` as `far.png`, `middle.png`, `near.png`, and `middle_window.png`. The two benchmark arms placed the same 17 authored residents around the played character, with facing off. Each sample used eight seconds of wall-frame intervals at 1600×900 with the frame limiter disabled. Counts are the visible near and far models at the end of each sample.

| Stop | Cap 8 near/far | Cap 8 p50/p99 (ms) | Uncapped near/far | Uncapped p50/p99 (ms) |
| --- | ---: | ---: | ---: | ---: |
| Far | 8/10 | 4.89/5.475 | 13/5 | 5.115/5.883 |
| Middle | 8/10 | 4.909/5.527 | 18/0 | 5.210/5.777 |
| Near | 7/10 | 4.890/5.501 | 17/0 | 5.216/5.755 |

The raw frames and `camera-lod.json` are in the run's `ui/` directory.
