# Play-test 8 camera and projected LOD, 2026-11-18 20:55 CET

Run `ui-camera1-camera-1118-205511`, scoped SpacetimeDB 2.14.1. The play-test 8 seed and its original Rhai overlay launched without compatibility edits. Doctor passed and the installed script read back with SHA-256 prefix `c2748445bfe9`. Cleanup restored the epoch and removed the database and its module copy.

The 58 camera checks passed with aspect 1600×900, all three stops, the market awning, woods, resident selection, wheel ownership and Shade. The field-off resident behind the wall stayed outside the scoped view. With the field on, the rear resident was also absent. Radius read 48 m in all street dumps from `my_senses`. The world had 17 authored residents. Admin calls set noon, switched `fov_on`, and placed and held residents for the fixture. The play scene uses 48 m daylight, 14 m darkness, 20 m carrying a torch in darkness, 12 m hearing, 24 m recognition, 28 m lamplight visibility and 48 m for a carried light. With the field on, the readout reported 70° focal, 110° side, 0.3333 side share, 3 m near ring and 10° keep margin. The same law uses a 2 m near ring in darkness.

The 10 LOD checks compared the previous 10 m distance rule with the initial, uncapped projected-size version. Measurements are uncapped wall-frame intervals, one 8 s sample per stop at 1600×900. The counts cover visible on-screen people with fitted client models. The fixture used up to 17 placed, held residents and the player. It had no mind service. This run preceded the eight-character cap.

| Stop | Old near/far | Old p50/p99 ms | Projected near/far | Projected p50/p99 ms |
| --- | ---: | ---: | ---: | ---: |
| Far | 0/17 | 3.59/4.74 | 0/18 | 3.76/4.83 |
| Middle | 0/16 | 3.83/4.88 | 12/6 | 5.05/5.70 |
| Near | 0/16 | 3.84/4.95 | 17/0 | 5.20/5.91 |

Three model checks passed. The same 3840×2160 middle and near shots show resident 2's full generated head alongside resident 3's Shino fallback. A scratch copy of the client's look book omitted only resident 3's line. The UI dumps confirmed both model paths and near state. The stills, frame samples, proofs and logs are under `.local/living/verify/ui-camera1-camera-1118-205511/ui/`.
