# Coat chains v2 on the laptop

**The 5 mm ground target fails in 5 of 12 v2 cases, improved from 6 of 12 on the baseline.** Gaits and idle met their limits. The three red native UI assertions reproduced on the baseline.

Tested on 2026-11-19 using main `f7ecc7398` with Bevy 0.20.1 and a dedicated SpacetimeDB 2.14.1 container. Main's `Coat` spring loader was sufficient. The v2 archive `char-4-composed-392cf29d6-ktx2` (generation `c4-cbcc40bf`) matched SHA-256 `fd98d84020f0bd4fed0544664508c401de22c289da017c1682db3b048922b77c`. The play-test 11 control was `char-port-1-composed-c4-5d64f53e-ktx2`. Both complete bundles passed their manifest checks. Each v2 coat file had 9,124 triangles, two primitives, one material and eight weighted joints in each LOD. The 887 active v2 looks included zero child cut-0 draws.

The worktree rebake used `ONLY=present LOD=near living/tools/blender/gen_person.sh clips=man` with the specified Kimodo library. Both arms used the same result. All 87 animations were present, including all three `_f` variants. The skeleton checker reported zero mismatches across 212 files per arm.

## Ground, gaits and idle

Ground penetration is the maximum sampled coat depth in world millimetres, from the [seat-2a checker](../README.md) with `--frames 16 --seat-contact --ground-clips select --heights`, fitted bounds and the height-dependent hips blend. The checker ran the rise at 1.6×. The woman's clips resolved to the female family. The other three fittings played the original clips. Dev-box figures are the `final-on` rows from `392cf29d6:docs/seat-contact/coat-port/fittings.csv`.

| Fitting | Phase | Laptop v2 | Laptop baseline | Dev-box v2 |
| --- | --- | ---: | ---: | ---: |
| Woman, cut 2 | Descent | 17.90 | 19.81 | 17.90 |
| Woman, cut 2 | Seated | 17.52 | 18.76 | 17.52 |
| Woman, cut 2 | Rise | 17.52 | 38.15 | 17.52 |
| Man, cut 0 | Descent | 3.90 | 3.94 | 3.90 |
| Man, cut 0 | Seated | 0.00 | 0.00 | 0.00 |
| Man, cut 0 | Rise | 0.00 | 5.21 | 9.49 |
| Elder, cut 2 | Descent | 26.04 | 26.12 | 26.04 |
| Elder, cut 2 | Seated | 0.00 | 3.17 | 0.00 |
| Elder, cut 2 | Rise | 25.60 | 39.36 | 43.30 |
| Girl, cut 1 | Descent | 0.00 | 0.00 | 0.00 |
| Girl, cut 1 | Seated | 0.00 | 0.00 | 0.00 |
| Girl, cut 1 | Rise | 0.00 | 0.00 | 0.00 |

Ten of the twelve v2 depths reproduce dev-box to the reported precision. The man and elder rose with shallower sampled depths on the laptop. Measuring every fixed step of their v2 rises raised the peaks only to 0.82 and 26.55 mm respectively. The reason for the difference from dev-box remains unresolved. All twelve laptop depths were equal to or lower than baseline.

Walk, brisk walk and run produced zero layer crossings over 2 mm across four fittings and three cuts per bundle, with springs on and off at 16 poses per clip. The shipped fittings also showed no increases in unsimulated ground depth or layer crossings above 2 mm in the ground and chair clips at the reported precision. The largest unsimulated idle difference between v2 and baseline was 7.78 mm in model space on the girl's cut 1 at far LOD (7.74 mm near). Dev-box reported 7.8 mm. Spring motion alone moved the near coat mesh by a maximum of 1.08 mm during idle.

## Native verify-ui

| Scenario | v2 | Baseline rerun |
| --- | ---: | ---: |
| `seat` | 17 pass / 3 fail | 17 pass / 3 fail |
| `skirt-scale` | 5 pass / 0 fail | — |
| `look-walk` | 100 pass / 0 fail | — |
| `camera-lod` | 23 pass / 0 fail | — |

The two `seat` renewal assertions (contact on and off) expect a new `doing.since_ms`. The contact-on continuity assertion also requires that inferred renewal. On current main, renewal keeps `since_ms` and extends `until_ms`. Both arms of both bundles showed that extension for all four observed sitters. The watched v2 sitter stayed on the seated loop for 3,318 frames, and the baseline sitter for 3,626. The v2 coated resident reported eight cloth joints, with the lowest sampled coat tail 41.1 mm above ground with contact on. The mesh measurements above describe separate fitted poses.

Native evidence is under `.local/living/verify/ui-coat2a-v2/ui/` and `.local/living/verify/ui-coat2a-baseline/ui/`. Each contains `checks.json`. Seat details are in `seat.json`, `seat-on/scene.json` and `seat-off/scene.json`. The timestamp comparison is in `.local/coat-2a/renewals.json`.

## Spring-step CPU and frame times at eight near

Apple M4 Pro, windowed Metal, 1600×900 requested, stock presentation mode. The client ran at roughly 120 Hz. The scratch Cullet fixture used the original near-budget scene and its eight matched coated looks, with the camera at Middle (12 m), a dry noon reset and zero far characters. Each of the six alternating launches sampled 32 seconds after 18 seconds of warm-up. The excluded pilot caught the player before its coat swap completed. The start and end dumps for the accepted trials show the same eight composed looks.

The spring-step CPU time per displayed frame is reconstructed from the client's existing three-second simulation CPU counters. It sums the simulation across characters and fixed steps, then divides by displayed frames. Log rounding makes the result approximate. Spring-system wall time includes selection and transform writes. Whole-frame statistics use the frame interval from `frames.csv`. The stock window presentation cadence is part of those measurements.

| Run | Bundle | Spring CPU µs/frame | Spring CPU µs/character-step | Spring wall µs/frame | Frame p50 / p95 / p99 ms | Frames |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | 2.40 | 0.60 | 5.9 | 8.329 / 8.669 / 9.467 | 3839 |
| 2 | v2 | 6.18 | 1.54 | 10.0 | 8.336 / 8.885 / 9.745 | 3837 |
| 3 | baseline | 2.40 | 0.60 | 5.0 | 8.330 / 8.698 / 9.483 | 3840 |
| 4 | v2 | 6.04 | 1.51 | 10.0 | 8.330 / 8.673 / 9.415 | 3840 |
| 5 | baseline | 2.40 | 0.60 | 5.0 | 8.334 / 8.717 / 9.657 | 3837 |
| 6 | v2 | 7.64 | 1.47 | 11.9 | 8.378 / 17.104 / 17.921 | 3246 |

| Bundle | Spring CPU µs/frame | Spring CPU µs/character-step | Spring wall µs/frame | Frame p50 / p95 / p99 ms |
| --- | ---: | ---: | ---: | ---: |
| baseline | 2.40 | 0.60 | 5.0 | 8.330 / 8.698 / 9.483 |
| v2 | 6.18 | 1.51 | 10.0 | 8.336 / 8.885 / 9.745 |

The summary table gives the median of the three run values for each metric. The last v2 run had a 17.921 ms p99 and about 101 displayed frames per second through the timed window. Both endpoint dumps still matched the eight-coat fixture. That slower window is included in the table. The profiler counted eight character calls on stepped frames in both bundles, including empty spring rigs in the baseline. Raw frame intervals, client logs, host samples, timed windows and LOD dumps are retained in `.local/living/verify/ui-coat2a-perf/ui/`.

Cloth inputs, raw checker logs and height CSVs are under `.local/coat-2a/cloth/`. Idle displacement by fitting and LOD is in `.local/coat-2a/idle-summary.json`. Each of the three scratch databases was deleted after its run.
