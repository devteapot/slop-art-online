# skill-use-drain: minds and trials with the dead's skill uses drained

Branch `skill-use-drain` at `ed7c927a8` (the change `118084d12` with main `e0480aab8` merged), Spark, private servers `slop-retention-1126` (verify-minds, `127.0.0.1:3611`) and `slop-retention-tri` (trials, `127.0.0.1:3616`), SpacetimeDB 2.14.1, pinned to cores 0-4,10-14. Fake model only; no Neo4j (`LIVING_NEO4J=off` through a local variant `su-fake`). Launches under `trial-activity.lock`; builds through `build-slot`.

The mind service does not read `skill_use`; this checks that minds still run on the changed module and that trials keep their evidence.

| Run | Result |
|---|---|
| `verify_minds.py --case roundtrip --case conversation --no-unit-tests` (`minds-su-231748`) | roundtrip **pass**, conversation **pass** (living-mind tests ran in `just living-check`) |
| `trials.py run --batch sud zz-drain-arena arena-heavy --variants su-fake --fake` | both to duration. `zz-drain-arena` (a local, untracked copy of arena-heavy: the subject killed at 2.5 min, `life.stop_on_death` false, 6 min): the subject died at 152.9 s, the run ended 207 s later (past the 120 s grace); `final.json` has the subject's **20** `skill_use` rows, the copy read at its death (`state.json` `dead_uses`). `arena-heavy`: the subject survived; `final.json` 24 rows (the living keep 24); `uses.jsonl` 49 lines |
| `arena_report.py .local/living/trials/sud` | rc 0: arena-heavy survived, hp_min 48, 7 exposures, 27 fake calls |

Evidence: `.local/living/verify/minds-su-231748-roundtrip/`, `.local/living/verify/minds-su-231748-conversation/`, `.local/living/trials/sud/`, commitlogs `~/slop-evidence/verify-trial-sud-*.tar.zst` (+ `.sha256`).

**Not covered:** `trials.py`'s live read returning nothing after the grace is inferred from the drain (proved by verify-client `skill_use_events.py`), not logged by the runner; real-model trials; Neo4j.
