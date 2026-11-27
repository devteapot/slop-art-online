# skill-use-drain: a dead character's skill uses drained after 120 s

Branch `skill-use-drain` from origin/main `18564737a`, driven on `118084d12` (the authority change; later commits add verify-client's script and docs, and merge main `e0480aab8`). Spark (aarch64), private server `slop-retention-1126` (SpacetimeDB 2.14.1, `127.0.0.1:3611`, pinned to cores 0-4,10-14). Builds through `build-slot` with a private `CARGO_TARGET_DIR`; launches under `trial-activity.lock`; worlds deleted by `verify.py cleanup`. No mind service, no model calls.

**Change.** `skill_use_event` (private event table) carries each finished `skill_use` row; death writes `dead_skill_use_due` and housekeeping drains a dead actor's rows 120 s later by index (docs/COMBAT.md, "Skill uses: kept, sent and drained"). A living character keeps its last 24 as before. No rule reads a dead actor's uses, so no scene's behaviour should change; these are the scenes that write or read `skill_use` and the death path.

| Scene (run) | Result |
|---|---|
| `refusal` (`core-su-224956`) | 4/4 |
| `seize` | 6/6 |
| `committed` | 16/16 |
| `dodge_told` (reads the dodger's `skill_use` outcome) | 5/5 |
| `health_seen` | 11/11 |
| `death-names` | 8/8 |
| `sex_seen_bound` (remains expiry) | 7/7 |
| `crowd_sight`, `familiar_dense`, `notice_delta` (first sights, familiarity, noticing) | 8/8, 4/4, 8/8 |
| island `skirmish` (`core-su-224956-isl`) | 8/8 |
| island `outcomes` | 16/16 |

det_compare against main `18564737a` on the Cullet battle of 200 with 16 players, 1,800 ticks: **identical** (113 tables, 45,710 rows; `~/slop-retention-det/skilluse-vs-main/det-compare.json`). `dead_skill_use_due` is not in the trace (main lacks it); no grace ends inside 30 s.

Evidence: `.local/living/verify/core-su-224956/`, `.local/living/verify/core-su-224956-isl/`.

**Not covered:** no scene of this skill waits out the grace; verify-client's `skill_use_events.py` does (`client-su2-224358`). The scenes ran before the merge of main `e0480aab8` (give-out-of-sight-line); `just living-check` ran after it.
