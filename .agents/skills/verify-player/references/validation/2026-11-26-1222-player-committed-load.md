# Committed strike and dodge under load

Branch `player-committed-load` from `origin/main` `9cbb8d50ce`. All live runs used the island seed and scoped module built from that commit on the private Spark container `slop-committed-ikgmpo`, SpacetimeDB 2.14.1 at `127.0.0.1:32774`. The changed driver ran from the working tree (blob `1fb3659c2dfdc779251ed574bc701aa3631cd203`). The player used its own identity over HTTP. Admin calls placed the player and target and set the target to wait. Each invocation started with a fresh player.

The mechanics-force-load gate logged `strike: hit for 5` and `dodge: made way` at 12:58:36 local time. The original action log records the two HTTP responses at one-second resolution and omits authority timestamps for this pair. The fresh-world gate rerun passed.

The unchanged driver reproduced both outcomes without injection in `baseline-quiet-3-02.log` while another island was publishing. The authority accepted the strike at `1795695463256`, released it at `1795695463622` and recorded the dodge attempt at `1795695463807`, 185 ms after release. The response to the strike took 553 ms. In `diagnostic-1-03.log`, an activity read during a deliberately delayed pair recorded `phase=1`, `started_ms=1795695454917` and `ends_ms=1795695455267`. The skill-use rows put actual release at `1795695455275` and dodge arrival at `1795695455563`, 288 ms apart, with the same outcomes.

`strike_duration` gives the strike 350 ms. The authority sets the activity deadline at start and progresses it on a tick when due. `combat::held_by` permits a dash over a committed windup. `act::begin` cancels the live activity after checking that the dash can start. The fix restages only when the new skill-use rows show the strike already released before a successful dodge was attempted. The check still requires an accepted, unreleased strike marked `broken off` and a dodge marked `made way`.

| Run cohort | Dodge check passed | Full committed scene passed |
| --- | ---: | ---: |
| Main, one scene at a time, no injection (one run overlapped island startup) | 2/3 | 2/3 |
| Main, four concurrent scenes, no injection | 12/12 | 12/12 |
| Main, single diagnostic with 550 ms first-pair delay | 0/1 | 0/1 |
| Fixed, four concurrent scenes and 550 ms first-pair delay | 12/12 | 11/12 |
| Fixed, one scene at a time, no injection | 3/3 | 3/3 |

The four-way main cohort ran at a host one-minute load average of 45.30–46.48 at the start and end. The fixed four-way cohort ran at 44.92 and 40.81 at those points. The trace driver paused for 550 ms after the first strike response in each injected invocation to exercise the same missed window. In the fixed cohort all 12 first pairs missed by 201–310 ms, and every scene invocation proved the dodge interruption on its second staged pair. The separate throw check failed in `fixed-loaded-1-04.log` with `windup seen: False`, `throw: hit for 12`, and movement starting after the throw. The throw check remained unmodified.

Scratch runs `committed-ikgmpo-{02,03,04,05}` recorded actions and player results in `.local/living/verify/`. The run logs, original gate failure and rerun, and extracted activity and skill-use timings are preserved in `~/slop-evidence/player-committed-load-20261126.tar.zst` with its SHA-256 sidecar. The trace campaign covered the `committed` scene. `just living-check` passed using matching stamps for the unchanged build inputs. Zero paid model calls.
