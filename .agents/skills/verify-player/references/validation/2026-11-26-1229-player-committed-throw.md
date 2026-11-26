# Committed throw and movement under load

Follow-up to the [committed strike and dodge validation](2026-11-26-1222-player-committed-load.md) on branch `player-committed-load`. Private Spark container `slop-committed-throw` ran SpacetimeDB 2.14.1 at `127.0.0.1:32775`. The four scratch island worlds `committed-throw-{01,02,03,04}` used the scoped authority from `49ea86cc6`. The final working-tree driver has blob `871a7c0528290de9c2eb3ed45f52bb736a026900`. Each scene invocation started with a fresh player and ran its four assertions through the player HTTP reducers.

The previous loaded cohort missed the throw windup observation once. For this check, `human_move` defers movement while a committed activity holds the body. The authority resumes the pending direction in the throw-release transaction, using the same timestamp. The scene reads the southward steering input before sending the stop command and compares its `input_ms` with `released_ms` from the fresh throw's skill-use row. It retries only for a successful movement call whose input timestamp is strictly later than release. The pass still requires observing a live windup, a fresh released throw without a broken-off outcome, less than 0.2 m of movement during windup, and more than 0.5 m of movement afterward.

| Final driver cohort | First-run full scene passes |
| --- | ---: |
| `verified-same-delay-*`, four concurrent scenes, 550 ms after the first strike response | 12/12 |
| `verified-late-throw-*`, same concurrency and strike delay, plus 1.1 s after the first throw response | 4/4 |

All 12 original-delay invocations restaged the dodge and passed the throw check on its first pair. The throw challenge recorded the first movement input 296–303 ms after release in all four invocations. Each passed on its second staged throw. The host's one-minute load average was 13.33 at the start of the original-delay cohort and 15.77 at the end, below the earlier gate-like campaign's 44.92–40.81.

An initial temporary trace wrapper treated the string-valued `do` field as an object and then had a syntax error while being corrected. Those logs are retained and excluded from the final cohorts. An intermediate driver also passed 12/12 and 4/4 before the freshness check was tightened to use a monotonically increasing skill-use ID. Both final cohorts were rerun with that change.

The evidence archive `~/slop-evidence/player-committed-throw-20261126.tar.zst` and SHA-256 sidecar contain per-invocation logs, the assessment, and action logs and result files from `.local/living/verify/committed-throw-{01,02,03,04}/`. Coverage was limited to the full `committed` scene. `just living-check` passed using matching stamps for unchanged build inputs. Zero paid model calls.
