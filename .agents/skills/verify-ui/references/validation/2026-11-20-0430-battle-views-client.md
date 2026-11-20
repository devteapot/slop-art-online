# The copy tables on the game client (`battle-views-client`)

- **Branch:** `battle-views-client`, from `origin/main` `715aeb1ca`. The client and harness changes were uncommitted in the worktree while these drives ran. The commit holds exactly them, plus these records.
- **Setup:**
  - Server: the laptop's shared `sao-living_spacetimedb_1` (v2.14.1).
  - Module: a `scoped` island build of main's authority (no authority change), built through `build-slot` into a private target dir.
  - Client: the release client, built through `build-slot` (`BUILD_SLOTS=1`) into a private `CARGO_TARGET_DIR`.
  - No mind service ran, no model was called, and no owner session was open.
- **World:** `ui-bv-045109` (island), deleted afterwards ("name no longer resolves"). The laws were back to the world's own values before the delete: `cue_transport_on` and `near_tier_on` true, the table laws false.
- **What changed:** [features/battle-views.md](../../features/battle-views.md).
  - `net::Feed`: one switch for the tier state and the two table laws.
  - `seen_characters` moved out of the base set into the perception set.
  - `Copies` indexes the two tables.
  - The readers `characters`, `find_character`, `character_count` and `motion_count`; every read site in `living/game/src` goes through them.
  - A body waits for its character row before it is drawn.
- **Maintenance:** this pass was scoped to the change (`maintain-verification-skill`, no full audit). The coordinator read the changed sources itself, with no source-wave subagents. Updated: `features/battle-views.md` (new), `features/README.md` (a row and the `net.rs` source row), `features/law-override.md` (the table laws are delivery), `SKILL.md` (the scenarios and `LIVING_GAME_CLIENT_SERVER`), and `scripts/check.py`. The three scenarios register themselves with `@scenario`. In `scripts/drive.py`, `LIVING_GAME_CLIENT_SERVER` points the client alone at another server.

## Unit tests

`cargo test --release -p living-game`: **190 passed, 0 failed, 1 ignored**, on the final source. The new and changed tests in `net::cue_tests`:

- `the_untiered_set_is_main_s_three_views_and_the_base_holds_no_stream`: with all off, `seen_characters` plus main's three views, and no stream, characters query or table in the base;
- `each_table_law_replaces_exactly_its_views_in_every_frame_tier_state`: all 8 feeds, the key round trip, exactly the replaced views, and the motion cue staying with the tiers;
- `the_four_delivery_laws_are_read_beside_the_seen_ranges_laws_and_choose_the_set`: 16 law states through `with_world_laws`;
- `copy_rows_map_to_the_views_rows`: `moving_of` field by field, and the mirror keyed by creature;
- `a_copy_change_replaces_the_row_in_either_callback_order_and_the_kill_switch_keeps_rows`;
- `the_table_laws_flip_the_set_in_place_as_delivery_laws_in_every_combination`: every change is laid over in place as delivery, with the revision kept;
- `a_reconnect_with_the_table_laws_on_chooses_the_tables_first`.

`cargo test --release -p living-rules`: **358 passed, 0 failed, 17 ignored**, including the `ui::` guard (38).

## `check.py battle-views`: 126/126

The first run (`first-attempt/`) passed 131 of 132. Its one failure was the fixture's: a step set `characters_table_on` false while it was already false, so nothing changed and the client rightly logged nothing. The step was removed, and the in-place match was bounded to each step's 3 s.

From `battle-views.json`, per call:

- The switch took **17–54 ms** from the reply (`effect_ms`).
- Each switch window held 72–75 frames, and no frame lacked a kept creature (8–10) or character (9–11). Both missing lists in each switch line were empty.
- **Kill switch by row:** the table was empty to the owner's SQL **41–45 ms** after the reply, for each of the four offs: motion tiered, characters tiered, motion untiered and characters untiered. Motion off left my copies in `motion_seen`/`motion_near`, none public.
- Motion on: all my copies were public, none private. Characters on: mirror rows equal to `projected` rows.
- Tick gaps were 70–77 ms, against a quiet baseline of 76.5 ms (the sampler's resolution); about 60 ticks/s throughout.
- The script revision was unchanged on every call.
- **All 8 combinations ran:** tiered and untiered × the four table-law states. The tiered state was reached both ways: tiers only (`cue_transport_on` false) and cues only.
- **Reconnect with both table laws on:** the only subscribe after it was `the tiered set (9 queries; tables: motion true characters true; …)`, and the reads moved to it.
- **Fresh client:** one subscribe, of the table set, which it read.

## `check.py battle-views-ui`: 96/96

With both table laws on: camera 60/60, talk 22/22 and far 11/11, plus 3 checks of the scenario's own. All four clients (`camera-off`, `camera-on`, `talk`, `far`) read both tables, and only them. far's script install kept the law rows.

## `check.py battle-views-cost`

The final run, after the harness fix below, passed **10/10**, and `talk` **22/22** after it. This is a single client on a quiet laptop: a smoke measure, not the 216 series. The walker was in sight throughout, except 13 s of one square off arm.

| Place | Laws | kB/s (each arm) | kB/s mean | Near segments | Near p50 | Near p90 | Near max |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Brackenford square, 5–6 others in sight | off | 1.85, 1.29 | 1.57 | 136 | 23 ms | 40 ms | 159 ms |
| Brackenford square | on | 1.80, 2.29 | 2.04 | 178 | 23 ms | 37 ms | 67 ms |
| Open spot, 3 in sight | off | 0.70, 0.73 | 0.71 | 120 | 22 ms | 35 ms | 131 ms |
| Open spot | on | 0.81, 0.82 | 0.81 | 124 | 19 ms | 31 ms | 38 ms |

- **kB/s:** +14% on the open spot (tight arms), and about +30% on the square, where the arms vary with the residents. This matches the authority's own measure: Cullet 216 per player +36% for motion and +10% for characters.
- **Near ages:** no worse with the tables on; the off arms' tail is longer (max 131–159 ms against 38–67).
- Ages are frame-quantized: 45–53 frames a second, headless.

Earlier attempts are void as measures, and their evidence is kept:

- `cost-first-attempt/`: the age counted re-entries into sight, and two checks compared JSON key order.
- `cost-second/`: the walker left sight for part of every octagon loop (period 6 s, alike in both arms). On the square one off arm saw it for 2 s, and that arm failed the fixture's adequacy check.
- That run also left both players at the open spot. After it, `talk` failed 11 checks: its residents were placed for a square scene, and `camera` had left `fov_on` on. So `battle-views-cost` now puts both players back where they were (re-driven: me back at 412.5, 256.5).

## Laws off: main's queries (`off-regression`)

- **law-override: 70/70** with the laws off. Switch times 18–36 ms, nobody missing, and a reconnect and a fresh client chose the untiered set only. Its subscribe line now reads `the untiered set (4 queries; tables: motion false characters false; …)`: `seen_characters` plus main's three views.
- **far: 11/11.** talk's 11 failures in that run came from the scene above, and its rerun passed 22/22.

## Harness gap found, not fixed here

`check.py camera` sets `fov_on` true at its end (`fov_on` sync) and does not restore it. A scenario after it that expects facing sight off can fail on scene.

## Evidence

All under `.local/living/verify/ui-bv-045109/`:

- `ui/battle-views{.json,.seen.jsonl,.drive.log,/,-fresh/}`, `ui/checks-battle-views.json`;
- `ui/battle-views-ui.json`, `battle-views-ui.out`, `ui/checks-battle-views-ui.json`, and the camera, talk and far drives;
- `ui/battle-views-cost.json`, `ui/battle-views-cost-{square,open}-*`, `battle-views-cost.out`, `ui/checks-battle-views-cost-talk.json`;
- `off-regression.out`, `ui/law-override*`, `ui/checks-off-regression.json`;
- the void attempts, in `first-attempt/`, `cost-first-attempt/` and `cost-second/`.

## Not covered

- The play-test world itself and the defaults flip, which is dev-box's part.
- The 216-player scale.
- A real window.
- Cullet scenarios: none here touch the copy tables differently from the island.
