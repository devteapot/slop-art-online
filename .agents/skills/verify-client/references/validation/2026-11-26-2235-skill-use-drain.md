# skill-use-drain: skill uses for exporters, the drain, privacy

Branch `skill-use-drain` (`118084d12` + verify-client script `79be041a1`), Spark, private server `slop-retention-1126` (SpacetimeDB 2.14.1, `127.0.0.1:3611`). Probe built in `.local/living/verify/target-client`. Launches under `trial-activity.lock`; worlds deleted by `verify.py cleanup`.

**Shape change.** Two private tables: `skill_use_event` (an event table) and `dead_skill_use_due`; both in `drive.py`'s `PRIVATE` inventory, `skill_use_event` also probed as the player. The probe streams `skill_use_event` inserts. New script `scripts/skill_use_events.py` (SKILL.md, features/combat.md, the map).

| Run | Result |
|---|---|
| `client-su-223909` `skill_use_events.py` (first version) | 11/12: "no event names an actor other than A and B" failed on the default world's own fights (the check was wrong for a living world: now counted, not checked); its drained check passed vacuously (A had no open use) |
| `client-su2-224358` `skill_use_events.py` (A killed in its strike's windup) | **11/11**: owner receives every finished row as an `outcome` event equal to it (5 events: 4 outcome, 1 drained); A's open use sent `drained`, no outcome; due row at death + 120,000 ms; past it A's rows and due row gone, B's 3 kept; anonymous and player refused as private; owner SQL of the event table empty |
| `client-su2-224358` `drive.py` (the suite, scoped build) | **45 PASS**, exit 0; private table visibility: 118 tables, `skill_use_event` and `dead_skill_use_due` refused (anonymous; the event table to the player too) |

Evidence: `.local/living/verify/client-su2-224358/` (`skill_use_events.json`, `skill-use-events-*.jsonl`, `visibility.json`), `.local/living/verify/client-su-223909/`.

**Not covered:** the open (`LIVING_PERCEPTION=open`) build was not run (no visibility change between builds: both tables are private in every build). No exporter consumes `skill_use_event` yet; this proves delivery to the owner, not an archive.
