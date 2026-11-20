# Law overrides on the game client (`law-override-client`)

- **Branch:** `law-override-client`, on `origin/law-override` `ee92c9e90` (main `3df6e1f10`, which `origin/main` still was). The client changes were uncommitted in the worktree while these drives ran; the commit holds exactly them.
- **Setup:** the laptop's shared `sao-living_spacetimedb_1` (v2.14.1), `scoped` builds of this branch's authority (`--target-dir` per run). The release client was built from `.local/target` through `build-slot` with `BUILD_SLOTS=1`. No mind service ran, no model was called, and no owner play-test session was open.
- **Worlds:** `ui-lo-1119-2024` (island) and `ui-loc-1119-2028` (Cullet). Both were deleted afterwards.
- **What changed:** see [features/law-override.md](../../features/law-override.md).
  - `law_override` is in the base set.
  - `verbs::Rules` compiles with the rows, or lays them over in place. `laws_key` keys every cache of a law read.
  - `verbs::refresh_rules` runs before `perception_law`.

## Unit tests

`cargo test --release -p living-game`: **169 passed, 0 failed, 1 ignored**, on the committed source (the `#[ignore]`d `ik::spots::uneven_ground_spots` tool). The new tests in `net::cue_tests`:

- `law_override_rows_decode_as_the_authority_decodes_them`;
- `a_delivery_override_flips_the_set_in_place_with_the_script_revision_kept`;
- `cover_and_gaze_overrides_change_the_sight_laws_in_place`: gaze laid over in place gives the same senses and laws as a fresh `with_overrides`;
- `a_reconnect_lays_the_rows_it_finds_over_before_a_law_is_read`;
- `an_override_of_an_ordinary_law_at_the_same_revision_compiles_again`.

`cargo test --release -p living-rules`: **349 passed, 0 failed, 17 ignored**.

## `check.py law-override` (island): 72/72

The first attempt (`law-override-try1*`) passed 71/71. Its reconnect only re-chose the set the client already had, so the scenario was changed: the laws now go off while the client is offline. The second run passed **72/72**.

**Per call,** from `law-override.json`:

- *call* is the HTTP round trip of `set_world_law`;
- *laid over* and *effect* are the client-log lines' times after the reply;
- *tick gap* is the longest standstill of `clock.tick` in [t0 − 0.5 s, t1 + 1.5 s], sampled every ~20 ms. Its resolution is about 35 ms: the quiet baseline was 34.3 ms at 60.2 ticks/s.

| Law → value | Class | Script revision | Call | Laid over | Effect line | Effect | Tick gap | Ticks/s |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| `cue_transport_on` false | delivery | 5 → 5 | 2.5 ms | 10.1 ms | `rules: cue_transport_on false near_tier_on true` | 10.2 ms | 33.5 ms | 60.2 |
| `near_tier_on` false | delivery | 5 → 5 | 2.1 ms | 16.0 ms | `perception: on the untiered set after 17–22 ms` | 35.0 ms | 32.6 ms | 59.6 |
| `near_tier_on` true | delivery | 5 → 5 | 2.0 ms | 3.9 ms | `perception: on the tiered set after …` | 20.6 ms | 34.5 ms | 59.9 |
| `cue_transport_on` true | delivery | 5 → 5 | 1.9 ms | 7.2 ms | `rules: cue_transport_on true near_tier_on true` | 7.2 ms | 36.4 ms | 59.7 |
| `gaze_on` true | gaze | 5 → 5 | 4.1 ms | 1.4 ms | `sight edge: my senses from the authority (my_senses_v_2)` | 197 ms | 32.1 ms | 60.2 |
| `gaze_on` false | gaze | 5 → 5 | 3.0 ms | 9.7 ms | `… (my_senses)` | 10.2 ms | 32.6 ms | 60.0 |
| `cover_sight_on` true | cover | 5 → 5 | 3.8 ms | 9.5 ms | `sight field: cover policy Some(…)` | 10.1 ms | 72.2 ms | 58.4 |
| `cover_brush_min_fill` 0.5 | cover | 5 → 5 | 1.9 ms | 0.8 ms | `… brush_min_fill: 0.5 …` | 1.3 ms | 70.1 ms | 58.7 |
| `cover_sight_on` false | cover | 5 → 5 | 2.0 ms | 12.0 ms | `sight field: cover policy None` | 12.6 ms | 34.4 ms | 60.0 |
| `turn_rate` 6.5 (full install) | — | 5 → 6 | 1391 ms | — | `rules: skill script revision 6 compiled (67 skills, 6 law overrides)` | 20 ms | **1409 ms** | 41.1 |
| `turn_rate` 6 (full install) | — | 6 → 7 | 1411 ms | — | revision 7, the same | 34 ms | **1414 ms** | 40.8 |

**What the table shows:**

- **Gaze on:** the 197 ms is the authority's next attention sweep (every 200 ms) filling `my_senses_v_2`. The client laid the law over 1.4 ms after the reply.
- **Cover policy changes:** their ~70 ms gap is two sampler intervals. The authority compiles the cover mask on the next tick (docs/LAW_OVERRIDE.md: 13–40 ms).
- **No client compile** followed any value-only call: there was no `skill script revision … compiled` line within 3 s.

**Delivery switches,** frame by frame from `law-override.seen.jsonl`:

- To untiered: 74 frames in the window, 8 creatures kept across it, 0 frames with one missing. The client's line said `missing now []`.
- Back to tiered: 72 frames, 8 kept, 0 frames with one missing.
- Both sets were subscribed beside the old one before it was dropped (make-before-break). There was no reconnect.

**The full installs:**

- Each moved the revision by one, and the client compiled it with the 6 overrides.
- No perception subscribe followed: the delivery laws in force were kept through the compile.
- The world still freezes for ~1.4 s on an ordinary law. That is the authority's install, as before.

**The reconnect:**

1. The client, on the tiered set, dropped its socket (`reconnect`).
2. While it was offline, `cue_transport_on` and `near_tier_on` were set off. Both calls returned 200 before it reconnected.
3. The base came back with `world subscribed after … (6 law overrides)`.
4. The first and only set subscribed after that was `untiered`, with no tiered set before it.

**A fresh client** on that world compiled with 6 overrides and subscribed only the untiered set.

**Restore:** every law touched went back to the value `law_override` held before, or the shipped value.

## Regressions

**Gaze** (Cullet `ui-loc-1119-2028`, `check.py gaze`): **4/4**.

- `gaze_on` and `cover_sight_on` went through the in-place path: `laid over in place … gaze true` and `… cover true`, with script revision 4 unchanged.
- The scenario's restore now reads `law_override`, because `world_law` is no longer written.

**Cover** (the same world, `check.py cover`):

| Run | Result | What happened |
| --- | --- | --- |
| 1 (after gaze) | 126/129 | 3 `cover-hedge: on_*: no hover, label, plate, talk or strike target` failed. |
| 2 | 126/129 | The same failures. |
| 3 | 96/129 | I misplaced #8 onto the trunk and edge fixtures' spot. It does not count. |
| 4 | **129/129** | #8 was moved to (660.5, 580.5) first. |

- **Cause of runs 1 and 2:** gaze's hedge fixture leaves resident #8 at (523.5, 697.5) with `{"wait": 600}`. That is 1 m from cover's hedge eye. An empty-cursor tap then addressed #8, and #8's plate showed.
- **The hidden target #4** was hidden in every run by authority, client and Shade alike.
- **This is a fixture interaction:** gaze and then cover on one world. It is not fixed in `check.py` here.
- Every cover change in these runs was laid over in place (`changed ["cover_sight_on"]; … cover true`).

**Frame-views' four states** (island `ui-lo-1119-2024`):

- **Scenarios:** talk, far, look-walk, reversal and camera.
- **One world:** the states were switched with value-only `set_world_law` calls, with no install between them.
- **The default state** is the shipped values written as `law_override` rows, not "no override". The law-override run started with 0 overrides, and that case is covered there.

| State (`cue_transport_on`, `near_tier_on`) | Set logged in every drive | talk | far | look-walk | reversal | camera |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| default (true, true) | tiered | 22 | 8 | 100 | 12 | 52 + 8 failed, then **60/60** |
| cues off (false, true) | tiered | 22 | 8 | 100 | 12 | 58 + 2 failed |
| tiers off (true, false) | tiered | 22 | 8 | 100 | 12 | 58 + 2 failed |
| both off (false, false) | untiered | 22 | 8 | 100 | 12 | 58 + 2 failed, then **60/60** |

- **The camera failures were missing generated assets in this fresh worktree.** The skill's launch note names `lookdev`, `textures` and `view`; these were two more:
  - `envs/<kit>/` (the market stall's model): 6 "market stall roof enters cutaway" failures in the default state. The kits were linked from the main checkout before the other states' camera drives.
  - `characters/looks.json`, the look book: the client logged "no look book … drawn as VRoid bases", and the short hover phrase comes only from the look book. That gave 2 "middle hover is short" failures in every state.
- **With both linked,** camera passed 60/60 in the default and both-off states.
- **The other scenarios** passed in every state without the look book (VRoid bases).
- **Every drive logged** `rules: cue_transport_on … near_tier_on …` matching its state.

## Evidence

- `.local/living/verify/ui-lo-1119-2024/ui/`:
  - `law-override{,.json,.seen.jsonl,.drive.log}` and `law-override-fresh/`;
  - the first attempt as `law-override-try1*` and `law-override-fresh-try1/`.
- `.local/living/verify/ui-lo-1119-2024/states/`: `states4.sh`, per state `*.out`, `*.checks.json`, `*.sets.txt` and `*.laws.txt`, and `*.camera2.out`.
- `.local/living/verify/ui-loc-1119-2028/`: `gaze-cover.out` and `cover{2,3,4}.out`; `ui/gaze/`; `ui/run{1,2,3}/` (the earlier cover runs) and `ui/cover-*` (run 4).

## Not covered

- A real window, and an owner play-test.
- Load: one client and no other players. The 216-player delivery switch is dev-box's.
- A set switch racing a reconnect. Each was driven alone, though the reconnect now meets changed rows.
- `cover_eye_height_m` and `cover_cliff_step_m` were not set live. They share the cover class and the `cover_law` row path with `cover_sight_on` and `cover_brush_min_fill`, which were, and the unit test lays `cover_eye_height_m` over.
- The tick sampler cannot resolve gaps under about 35 ms. The authority's own spans (docs/LAW_OVERRIDE.md: 0.4–2.1 ms) are the reducer cost.
