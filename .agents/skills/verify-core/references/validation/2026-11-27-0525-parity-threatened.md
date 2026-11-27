# parity-threatened: `threatened` from what the character perceives (`perceived_threat_on`, off)

Branch `parity-threatened` from origin/main `e220bea8e`, driven on `550b92262` (the change) and `313d77868` (the scene). Spark (aarch64), private servers `slop-ppt-stdb` (scenes, `127.0.0.1:3391`) and `slop-ppt-deta` (det_compare, copies on 3393–3396), SpacetimeDB 2.14.1. Builds through `build-slot` with a private `CARGO_TARGET_DIR`; launches under `trial-activity.lock`; worlds deleted by `verify.py cleanup`. No mind service in the core runs, no model calls. Host load 35–50 throughout (other workers' builds).

**Change.** Under the new ordinary law `perceived_threat_on` (off as shipped), the graph condition `threatened`, the desire weight `threatened` and heed's `threatening` read `perception::threat_seen` over the scene's creatures (a hostile move winding up at one, or a menace, by someone seen), never the private `activity.victim` of someone unseen (docs/PERCEPTION_PARITY_AUDIT.md). Off, every path is as before. features/perceived-threat.md.

**Det (law off).** det_compare against main `e220bea8e`, each copy with its build's own script (`--scripts … --seed`):

| Template | Result |
|---|---|
| Cullet, `spawn_battle` 200, 16 players, 3,600 ticks | **identical** (3,600 ticks, 113 tables, 51,838 rows) |
| island, `spawn_battle` 20 with its wildlife, 16 players, 3,600 ticks | **identical** (3,600 ticks, 113 tables, 105,551 rows) |

**Scenes.**

| Scene (run) | Result |
|---|---|
| `perceived_threat` (new, `core-ppt1-045244`, default seed) | 13/13 (third attempt: the first's weight graph sat under a `seq` after a turn, the second waited on a `skill_use` row a menace never writes; both scene fixes) |
| `fov`, `heed`, `doing_seen` (same run) | 18/18, 18/18, 11/11 |
| island `skirmish` (`core-ppt1i-061300`) | 8/8 |
| Cullet `sides_battle` (`core-ppt1s-061300`) | 12/12 |

`perceived_threat`: law off, the weight dodges B's unseen attack from behind (the leak) and the condition does not (its fov gate); law on, A's attack and threat in sight are dodged by both, B's attack and threat from behind by neither.

**Law on versus off** (`ab.py`, a scratch driver: fresh world per arm, the same build, no mind; one replicate per arm, arms not simultaneous; counts from `activity` sampled at 2 Hz, `skill_use` every 5 s and the chronicle):

| | Cullet + sides battle 60, 5 min, off / on | island, 10 min, off / on |
|---|---|---|
| attacks accepted | 3,090 / 3,213 | 0 / 0 |
| dodges / blocks | 1,831 / 1,740 · 364 / 403 | 0 / 0 |
| deaths (killed) | 33 / 36 | 0 / 0 |
| flee starts | 0 / 0 | 0 / 0 |
| threats (chronicle) | 0 / 0 | 2 / 2 |
| wolf attacks on people | – | 0 / 0 |
| refused combat moves | 0 / 0 | 0 / 0 |

Nothing became impossible; the battle's differences are within one replicate's spread on a loaded host. On the island no one fought in either arm.

Evidence: `.local/living/verify/core-ppt1-045244/`, `core-ppt1i-061300/`, `core-ppt1s-061300/`, `core-pabc-{off,on}-0501/`, `core-pabi-{off,on}-0514/` (each `ab-uses.json`, `ab-chronicle.json`); det: the session scratchpad `det/thr-cullet-off/`, `det/thr-island-off/` (archived with the branch's evidence).

**Not covered:** heed's `threatening` under the law (heed scene ran with the law off); a point-aimed bow shot facing one, which now counts; the A/B is one replicate per arm and not a fake-model mind world (the minds' own fight graphs are in verify-minds).
