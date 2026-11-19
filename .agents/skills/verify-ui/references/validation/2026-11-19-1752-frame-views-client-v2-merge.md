# Frame views client v2 after merging frame-views a52efdd22 and main 57c8b88cb

Follows [2026-11-19-1504-frame-views-client-v2-switch.md](2026-11-19-1504-frame-views-client-v2-switch.md).

- **Branch:** `frame-views-client-v2`, head before this record `1f3742ed5`: `origin/frame-views` `a52efdd22` (with main `8851982d2` and the server side resolved by dev-box) merged at `eec582116`, then `origin/main` `57c8b88cb` (sit-f-select, no conflict) at `1f3742ed5`.
- **What changed upstream:** `cue_transport_on` is now on by default in `skills.rhai` and `Laws::default()`, so a fresh world starts with tiers and cues. `skills.rhai` holds main's `seen_ranges` and `seen_ranges_check` laws just above both delivery laws. Main's client brought the gaze owner view (`my_senses_v_2`, `human_gaze`) and `cover_law` in the static set. The fast lane (`living/authority/src/fast.rs`) is authority and mind only: the client has no fast-lane subscription or handling, so there was nothing of it to merge or drive here.
- **Setup:** the laptop's shared `sao-living_spacetimedb_1` (v2.14.1), `scoped` builds of this branch's authority (`.local/living/verify/fv2-target`, `fv2-target-cullet`), the release client from `.local/target` built through `build-slot` with `BUILD_SLOTS=1`. No mind service ran and no model was called. No owner play-test session was open during any build or drive.

## Merge

| File | Conflict | Resolution |
| --- | --- | --- |
| `living/game/src/net.rs`, imports | main's `living_rules::sight::GazeBand` against the cue overlays' `EventTable`, `HashMap`, `Deref` | both sets of imports |
| `living/game/src/net.rs`, tests | `cue_tests` against main's `gaze_tests` | both modules kept |
| `verify-ui/features/README.md` | main's new look-walk row against the others-in-motion row; the `net.rs` source row | main's look-walk row and ours below it; `net.rs` maps to look-walk, talking, bar and gaze |

The rest of `net.rs` merged without conflict. The gaze owner view is a subscription of its own, made once the base is applied, beside the base and the perception set. The perception set is chosen by `perception_law` from the laws. `update_gaze` reads only `my_senses_v_2` and calls `human_gaze`, whichever set is in place. A disconnect drops the gaze view, the base and the perception set together (`gaze.reset_owner()` and `perception = Window::default()`), and the next connection subscribes each afresh. No generated binding conflicted, and `living/bindings` was not touched.

## The laws' parse and the fallback

- **Parse.** The client reads the two laws with `living_rules::script::Scripts::laws()`, the same parse the authority uses, from the installed `script` row it already compiles. It now goes through `net::delivery_laws`, `net::perception_set` (untiered only while both laws are off) and `net::delivery_fallback`.
- **Fallback, changed.** A world script that does not compile here, with no law read before, used to give `(false, true)`: the tiers with cues not taken. That was right while `cue_transport_on` defaulted off. It now takes `Laws::default()`, which is `(true, true)`: the tiered set with cues, as a fresh world starts. A later script that fails keeps the last values read, as before.
- **Test.** `net::cue_tests::both_delivery_laws_are_read_beside_the_seen_ranges_laws_and_choose_the_set`:
  - The shipped `skills.rhai` reads `(true, true)` with `seen_ranges` on and `seen_ranges_check` off, and takes the tiered set.
  - Each of the four states is written as a world's own values the way the authority writes them (`with_world_laws`). The two `seen_ranges` laws are flipped in the same block, so a neighbour cannot mask a delivery law that was not found. Each state reads back as written and picks its set: untiered only for `(false, false)`.
  - The fallback is `(true, true)`, equal to the shipped script's values, and picks the tiered set.
- **Client tests:** `cargo test --release -p living-game`, **157 passed, 0 failed, 1 ignored** (the `#[ignore]`d `ik::spots::uneven_ground_spots` tool). `cargo check -p living-game` gave no new warning in `net.rs`.

## verify-ui per law state (island)

Each state ran on its own fresh world, `ui-fv4-{def,cuesoff,tiersoff,bothoff}`, driven by `.local/fv2/states4.sh` in this order: talk, far, look-walk, reversal, camera. **`def` had no law override:**

- `world_law` was empty before the scenarios. After them it held only `fov_on`, which camera's field case sets.
- Launch reported "installed script is the shipped one".

The other three set `cue_transport_on` and `near_tier_on` with admin `set_world_law` after launch.

| State (`cue_transport_on`, `near_tier_on`) | Set logged | talk | far | look-walk | reversal | camera | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fresh default, no override (true, true) | tiered in all 14 scenario drives | 22 | 11 | 100 | 12 | 60 | 205 / 0 failed |
| cue transport off (false, true) | tiered (12) | 22 | 11 | 100 | 12 | 60 | 205 / 0 failed |
| near tier off (true, false) | tiered (12) | 22 | 11 | 100 | 12 | 59 + 1 failed | 204 / 1 failed |
| both off (false, false) | untiered (12) | 22 | 11 | 100 | 12 | 59 + 1 failed | 204 / 1 failed |
| near tier off, camera again (`ui-fv4c-tiersoff`, fresh world) | tiered | | | | | 60 | 60 / 0 failed |
| both off, camera again (`ui-fv4c-bothoff`, fresh world) | untiered | | | | | 60 | 60 / 0 failed |

- **Every drive logged the laws as set:** `rules: cue_transport_on … near_tier_on …`. On the fresh-default world that was `true true` from the shipped script.
- **Check counts.** Look-walk (100) and reversal (12) have more checks than the 1504 record's 91 and 5: main's scenarios grew. These counts are this merge's, not a change in pass rate.
- **The two camera failures** were the same check, "street, woods and roof stills captured" (`on near` in tiers-off, `off near` in both-off):
  - The missing file was `roof_near.png`, the plan's last `shot:`, which is followed directly by `quit`.
  - The client logged `ERROR bevy_render::view::window::screenshot: Failed to send screenshot: sending on a closed channel`: it exited before the readback landed. The laptop's load average was about 14 at the time.
  - Every other check of that stop passed, including the roof's cutaway. The `roof_near` dump was written.
  - The same scenario passed 60/60 on a fresh world in each of the two states, with no screenshot error.
  - This is a capture race at quit in the scenario's plan, not a delivery fault. It is not fixed here.

## Gaze in all four states (Cullet)

- **World and fixture.** One Cullet world, `ui-fv4-cullet`, ran `check.py gaze` four times. Before the first run there was no law override; before each later run, the two delivery laws were set. The scenario itself sets `gaze_on`, `fov_on` and the cover laws, and restores them.
- **Kit.** The local Cullet kit was the untracked `living/game/assets/envs/cullet` as found in this worktree. It was not regenerated.

| State | Set logged, before and after the scenario's reconnect | `gaze accepted` lines | Checks |
| --- | --- | ---: | ---: |
| fresh default (true, true) | tiered, tiered | 10 | 4 / 0 failed |
| cue transport off (false, true) | tiered, tiered | 11 | 4 / 0 failed |
| near tier off (true, false) | tiered, tiered | 11 | 4 / 0 failed |
| both off (false, false) | untiered, untiered | 11 | 4 / 0 failed |

The four checks passed in each state:

- three stops with authority-matched Shade fields;
- the rapid spin under the limiter;
- the reconnect restoring Far before the queued Near;
- gaze with cover hiding the hedge contact.

So main's gaze client works on either set. The reconnect re-subscribes the law's set as well as the gaze view.

## Live toggle with the client connected (`ui-fv4-def`)

- **Fixture.** `.local/fv2/toggle.py` ran on the fresh-default world after its scenarios, with the noon fixture and `fov_on` off. Fresh players B, C and D were beside the client:
  - B walked;
  - C struck at D;
  - D waved.
- **Law sequence:** `cue_transport_on` off → `near_tier_on` off (the switch to untiered) → `cue_transport_on` on (the switch to tiered) → `near_tier_on` on, 6 s apart.
- **Result: 7/7 passed.**

| Transition | Set applied after | Others before | Kept through 1 s | Frames with a missing creature | Segment regressions | B in the 3 s after |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| tiered → untiered | 48 ms | 8 | 8 | 0 | 0 | 157 frames, 0 still, 0 jumps, max step 0.08 m |
| untiered → tiered | 55 ms | 8 | 8 | 0 | 0 | 140 frames, 0 still, 0 jumps, max step 0.18 m |

- **Overlays.** Up to 9 overlays were held before `cue_transport_on` went off. They were cleared then, and stayed at 0 for 873 frames, until reads moved back to the tiers.
- **No reconnect.** The client kept one connection through the toggle. Its log shows the switches, no `offline:` line, and none of the switches listed a creature as missing.
- **The known `set_world_law` stall.** Each law call took 1.58–1.70 s to return (`install.compile` 86–95 ms, `install.validate` 1.24–1.25 s, `toggle/module.log`). In the 3 s before each switch, B had one still run of 1.37–1.39 s. B moved smoothly after each switch. This stall is known and not this branch's to fix.

## Docs updated

- `verify-client/features/game-client.md` now states:
  - `cover_law` in the static set;
  - both laws on in the shipped script, so a fresh world takes the tiered set with cues;
  - the fallback (`net::delivery_fallback`);
  - the gaze owner view as a subscription of its own, kept in every law state.
- verify-ui's SKILL.md and feature pages said nothing about the delivery laws' defaults, so they needed no change beyond the merged README row.

## Evidence

- Per law state:
  - `.local/living/verify/ui-fv4-{def,cuesoff,tiersoff,bothoff}/ui/`: `checks-states.json`, each scenario's `client.log`, dumps and stills;
  - `ui-fv4-def/world_law_{before,default}.json`;
  - logs in `.local/fv2/v4-*.log`.
- Camera again: `.local/living/verify/ui-fv4c-{tiersoff,bothoff}/ui/` and `.local/fv2/v4c-*.log`.
- Gaze: `.local/living/verify/ui-fv4-cullet/ui/gaze-{def,cuesoff,tiersoff,bothoff}/` (`gaze-proof.json`, `client.log`, `scene.json`, `fields/`) and `checks-gaze-*.json`; `.local/fv2/v4-cullet.log`.
- Toggle: `.local/living/verify/ui-fv4-def/toggle/` (`result.json`, `seen.jsonl`, `feet.jsonl`, `module.log`) and `ui/toggle-client/client.log`.
- Every scratch database was deleted: `verify-ui-fv4-{def,cuesoff,tiersoff,bothoff,cullet}` and `verify-ui-fv4c-{tiersoff,bothoff}`. Each name answered "no longer resolves".

## Not covered

- The SDK-level drives (verify-client `cues.py`, `near_tier.py`) and the near-motion ages: they were not rerun after this merge. The server side is dev-box's, and its record is `verify-client/references/validation/2026-11-19-1641-frame-views-merge.md`.
- The reconnect fixture with cues on (`reconnect.py`): not rerun. Gaze's reconnect re-subscribed the right set in all four states.
- A live toggle on Cullet. A set switch racing a reconnect.
- Scale, the 216-player arms and a real window.
- The camera scenario's capture race at quit (above).
