# Frame views client v2: the untiered set while both laws are off

Follows [2026-11-19-1310-frame-views-client-v2.md](2026-11-19-1310-frame-views-client-v2.md).

- **Branch:** `frame-views-client-v2`.
- **Client commit:** `b0ad4b86a`. Its frame-views base is `802116def` (merged at `22bda79fb`). That base is docs and the `cues.py` test since `461c4c5d3`, with no shape change.
- **Setup:** the laptop's shared `sao-living_spacetimedb_1` (v2.14.1), island seed, `scoped` builds, private target directories. No mind service ran and no model was called.

## The change

With `cue_transport_on` and `near_tier_on` both off, the authority delivers as main does. But a client on the six tier views and three cue tables pays about +24 ms near p90 at Cullet 216 (`docs/TICK_RATE.md`, "Short series").

So the perception streams are now a subscription set of their own (`net::perception_law`):

- **The choice.** It is made from both laws, read from the compiled `skills` script once per revision.
- **Both off: `UNTIERED_STREAMS`.** That is `seen_bodies`, `seen_fighters` and `seen_doing`, exactly main's.
  - The base set (`PERCEIVED` plus `gate`) together with this set is query-for-query main client `cd2afe42e`'s: the same 27 perception queries plus `gate`. A unit test pins the three.
  - One difference: main holds the three in its base subscription, and here they are a separate subscription set.
- **Either on: `TIERED_STREAMS`.** The six tier views and three cue tables.
- **Before the script compiles,** nothing is subscribed. A script that does not compile gets the tiered set.
- **A change of set:**
  - The new set is subscribed beside the old.
  - The old is dropped once the new one is applied (`Window::settle`, as for chunk windows).
  - Reads then move to the new set, and the overlays are cleared.
- **Cues** are taken only while the tiered set is in place and the cue law is on.
- **A reconnect** subscribes the set afresh.
- **`LIVING_GAME_SEEN_LOG=<file>`** writes every frame's reads: the set in place, each other's id and segment `t_ms`, and the overlays.

Client tests: 131 passed, 1 ignored.

## verify-ui, all on and all off

Each state ran on a fresh world, `ui-fv3-on` and `ui-fv3-bothoff`, with the laws set by admin `set_world_law`.

| State | camera | talk | far | look-walk | reversal | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all on (tiered set) | 60 | 22 | 11 | 91 | 5 | 189 / 0 failed |
| all off (untiered set) | 60 | 22 | 8 + 3 failed | 91 | 5 | 186 / 3 failed |
| all off, `far` again (`ui-fv3-far`, fresh world, twice) | | | 11, 11 | | | 22 / 0 failed |

- **Logged sets.** Every all-off drive logged `perception: on the untiered set`, and every all-on drive logged `on the tiered set`.
- **The three all-off `far` failures** came from one cause:
  - The talk target went to resident 6, not 2; no said row was written; and the far plate was absent.
  - At the 6 m spot, resident 6 stood under the cursor aimed at resident 2 (dump `02`: `under` 6, hovered "a woman in a blue smock").
  - Resident 2 was perceived and drawn in every dump.
  - The same scenario passed 11/11 twice on a fresh all-off world on the untiered set, and 11/11 on the tier reads in the 1310 record. This was scene geometry, a resident walking in front.

## Live toggle, all on → all off → all on

The fixture (`.local/fv2/toggle.py`):

- One world, the client on Brackenford's square with residents about.
- Three fresh players beside it: B walking east and west (a new `human_move` every 0.8 s), C striking at D every 1.6 s (D kept alive with admin `admin_set_vitals`), and D waving.
- The laws were set one at a time, 6 s apart: `cue_transport_on` off, `near_tier_on` off (the switch to untiered), `cue_transport_on` on (the switch to tiered), `near_tier_on` on.
- Evidence: the seen log every frame, and B's drawn feet.

Two runs: `ui-fv2t-toggle` (its own world) and the replicate on `ui-fv3-on`. Each passed 7/7.

| Transition | Run | Set applied after | Others before | Frames with a missing creature | Segment regressions | Overlays after the off |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| on → off | toggle | 50 ms | 12 | 0 | 0 | 0 in 959 frames (max 18 before) |
| off → on | toggle | 50 ms | 12 | 0 | 0 | not applicable |
| on → off | replicate | 40 ms | 4 | 0 | 0 | 0 in 663 frames (max 4 before) |
| off → on | replicate | 47 ms | 4 | 0 | 0 | not applicable |

- **Missing creatures.** A creature counts as missing in a frame if it was in the reads in the frame before the switch and 1 s after, but absent in between. Each switch's own log line listed nobody missing.
- **Overlays** were cleared when `cue_transport_on` went off, 6 s before the set switch. They stayed at zero through the untiered period, until reads went back to the tiers.
- **B across each switch.** B was in sight throughout. In the 3 s after each switch, B was drawn in 141–164 frames, with 0 frames still and no jump.
  - The largest single step, 0.37 m, came in the replicate after the off→on switch, on a frame of at least 46 ms. It stayed within the jump rule.

**An authority finding: `set_world_law` stalls the world for about 1.3 s.**

- Each call reinstalls the script on the database thread: `install.compile` takes 81–83 ms and `install.validate` 1.12–1.61 s (`toggle/module.log`).
- For about 1 s before each of the four law changes (the two that switch the set and the two that don't), no creature got a new segment: B, and the residents too.
- B was drawn standing for 1.06–1.31 s just before each switch, and then moved on smoothly.
- In the first toggle draft, the law calls came 1.5 s apart, and this stall overlapped the switch.
- The client renders through it with no frame over 100 ms.
- A kill-switch flip on a live world pauses everyone for about that long.

## Near-motion age at the SDK

- **Fixture:** `.local/fv2/motion_age.py`. A single SDK viewer, two players 1 m apart on a quiet open line, B walking an octagon (53 inputs in 40 s), 55 segments per row of the table. Fresh worlds `client-fv3-main` and `client-fv3`.
- **Smoke measure only:** one viewer on a quiet laptop. It cannot show the 216-player read-set cost.

| Authority and state | Probe's motion queries | p50 | p90 | max |
| --- | --- | ---: | ---: | ---: |
| main `cd2afe42e` | `seen_bodies`, `my_body` (main's client) | 29 ms | 56 ms | 141 ms |
| this branch, both off | `seen_bodies`, `my_body` (this client's both-off set) | 27 ms | 46 ms | 63 ms |
| this branch, both off | the tiers and `seen_body_cue` (the earlier client) | 29 ms | 45 ms | 58 ms |
| this branch, both on | the tiers and `seen_body_cue` | 16 ms | 26 ms | 30 ms |

## Reconnect, cues on (`ui-fv3-recon`)

- **Before the drop:** the old connection held overlays of (1, 3, 2); the new one started at (0, 0, 0).
- **No stale overlay:** B was drawn exactly where the authority holds it (0.000 m off over the last 10 frames). The new connection subscribed the tiered set again and it applied in 38 ms. No cue of B, C or D was taken after the reconnect.
- **As first written, two checks failed:** "no cue after the reconnect" and "all reports (0, 0, 0)". They assumed an empty scene, but 136 cues of walking residents arrived.
- **Re-scored on the fixture's players** (`result-rescored.json`): 4/4.
- **A first reconnect attempt** on `ui-fv3-on`, after the toggle and four scenarios, never took a fighter cue and stopped before its drop. It was not used.

## Evidence

- verify-ui:
  - `.local/living/verify/ui-fv3-{on,bothoff,far}/ui/` (`far-run1`, `far-run2`)
  - `.local/fv2/v3-*.log`
- toggle:
  - `.local/living/verify/ui-fv2t-toggle/toggle/` (`result.json`, `seen.jsonl`, `feet.jsonl`, `module.log`) and `ui/toggle-client/client.log`
  - the replicate in `ui-fv3-on/toggle/`
- reconnect: `ui-fv3-recon/reconnect/`
- ages:
  - `.local/living/verify/client-fv3/motion-age-{untiered,tiered}*`
  - `.local/living/verify/client-fv3-main/motion-age-main*`
  - the first attempts, which failed on an argument, in `*-try1/`

Every scratch database was deleted. Main's worktree was removed after its evidence was copied.

## Not covered

- The 216-player all-off arm. dev-box runs it, on this client's set.
- A real window.
- A set switch under a reconnect race. The switch and a reconnect were each driven alone.
