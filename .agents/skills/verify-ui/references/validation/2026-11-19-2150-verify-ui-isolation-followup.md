# Verify-ui isolation follow-up

Follows [the gaze and cover order runs](2026-11-19-2136-verify-ui-isolation.md). Native arm64 Bevy 0.20.1 release client from the private target directory, with linked local look and environment assets. Authorities built through the laptop build slot and published as fresh scoped scratch worlds on the private SpacetimeDB 2.14.1 instance. Doctor passed on all published worlds. No mind service ran and no models were called.

The first Cullet sequence passed gaze 4/4 and support 8/8, but looks passed only 12/14. Its player was still at gaze's hedge eye (523.5, 698.5). The terrain-only free placement put resident #5 at (525.5, 697.5), where the authority did not perceive it. The missing resident broke the two-person view and missing-book fallback checks. The looks fixture now moves its player to open ground and faces the two borrowed residents before sampling. The sight rules and the checks themselves are the same. Initial evidence is in `.local/living/verify/ui-isolation-followup-213738/`, especially `ui/looks/scene.json` and `ui/looks/00.json`.

Looks-band needs its own accelerated Cullet seed and a prompt drive after genesis. The relative seed argument in the first launch attempt resolved under `living/seeds` and failed before publish. The recipe now uses the generated seed's absolute path. Camera uses the Brackenford fixtures on the island seed.

## Results

| Native drive | Checks passed | Evidence under `.local/living/verify/` |
| --- | --- | --- |
| Cullet, gaze → looks → support | Gaze 4/4, looks 14/14, support 8/8 | `ui-isolation-followup-retry-214426/ui/checks.json` |
| Accelerated Cullet, looks-band | 5/5 | `ui-isolation-band-retry-214426/ui/checks.json` |
| Island, camera | 60/60 | `ui-isolation-camera-213738/ui/checks.json` |

The server accepted the placement and graph restore for every borrowed resident. See `actions.log` alongside each run's `ui` directory. Looks-band restored three residents. The capture verified redraws for #24 and #43. Resident #33's key did not change during the capture, so there was no redraw check for it. In the corrected looks run, `ui/looks/00.json` shows both borrowed residents in the authority's perceived set and both formerly failing checks passed.

All four published scratch databases were deleted. Their `cleanup.out` files confirm the names no longer resolve. Evidence and generated assets remain local. These headless runs cover one client at a time and leave hardware input and performance outside the validation.
