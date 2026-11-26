# Deliberate-act scenes under load

Branch `act-scenes-load`, scene commit `afde6e632` from `origin/main` `6b71513d5`. The first final-code wave ran from the working tree before the scene commit. Its driver is identical to the committed driver (blob `0c1bb7d0a2647860f9cbbb3f16d477058e51f84b`). The private Spark container `slop-act-scenes-load-21c19451` ran SpacetimeDB 2.14.1 on `127.0.0.1:32773`. The server, scene runner and 25 busy loops shared CPUs 0–4 and 10–14. Builds used the Spark build slot and a private target directory. Every `verify.py` invocation held the shared trial-activity lock.

The `world` seed matches the acting gate group. Each fresh world ran `act_gaps` then `act_replace`, with up to four worlds running at once. The loaded harness injected 8 s before the first law-on walk and 3.2 s between the first two walk starts (eight worlds in the law-on arm and four in the law-off arm), and 4 s before the gaze call. Timing injection was local to the driver harness. The scenes exercised the real reducer and read the resulting authority rows.

| Evidence under `.local/living/verify/` | Worlds | `act_gaps` first runs | `act_replace` first runs |
|---|---:|---:|---:|
| `core-scenes-21c19451-load-{2,3}-{1..4}` and `core-scenes-21c19451-load-final-1-{1..4}` | 12 | 12/12 | 12/12 |
| `core-scenes-21c19451-quiet-1-{1,2}` (no injected load, high ambient load) | 2 | 2/2 | 2/2 |

Loaded scene starts saw 1-minute host load 53.79–61.84. Every loaded turning scene restaged the missed window within its first invocation. The completed on arm recorded six qualifying replacements and one new experience ID for the turn notice. The off arm recorded six qualifying replacements and zero notices. Each final gaze and unreadable-act call left the expected long walk active with the same `started_ms`. The stock-driver runs used neither client delay injection nor busy loops. The first two began at ambient load 128.32–157.10. The host did not reach a quiet window during the wait. Low-ambient-load coverage remains open.

An initial version asserted exact equality with the requested placement coordinate. In `core-scenes-21c19451-load-1-{1..4}`, `act_gaps` passed 4/4 and `act_replace` stopped at setup in all four with `AssertionError: no-op walk staging: expected pose (8.5, 8.5), got {'x': 8.5, 'y': 7.5}`. The final assertion verifies the distance from the observed pose to the destination, with a minimum of 28 m. Those initial results remain in the evidence. Editing the local runner while it was active caused it to reuse `load-3-4` once after the first world had been deleted. Both invocations of both scenes passed. The table counts that name once, and its action logs retain both invocations.

Each run directory has the results, action log, load samples and cleanup transcript. `act_gaps-turns-{off,on}.json` records the staged walks and experience IDs. The `act_replace` result contains the observed pose and the activity read after each call. `act-scenes-load-21c19451/evidence/assessment.txt` summarizes the series. All worlds were paused, confirmed through SQL and deleted by the shared cleanup path. The private server exited 0 on SIGINT. Its shutdown log was inspected before removal.

`just living-check` passed using matching stamps for the unchanged build inputs. Coverage here is limited to the two core scenes on the default seed. The full scene gate, player-side acts, mind-service behavior, and the wolf signal collision were outside these runs. No model calls.
