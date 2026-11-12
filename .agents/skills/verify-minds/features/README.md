# Internal mind verification map

| Feature | Cases | File |
| --- | --- | --- |
| Think, compile, install, act, speak; the world's rules told from the laws' descriptions (SENSES, MOVING, FOOD, SETTLEMENTS sections in every think and deliberate prompt) | `roundtrip`, `acts` | [deliberation.md](deliberation.md) |
| Running for minds (docs/STAMINA.md): the prompt documents `"run": true` and the `stamina` condition, the scene carries `you.stamina`, and an act with `"run": true` runs at the `run_share` law times the walk and drains breath on the vitals row | `run` | [deliberation.md](deliberation.md#running) |

| Think, compile, install, act, speak; the world's rules told from the laws' descriptions (SENSES, MOVING, FOOD, SETTLEMENTS sections in every think and deliberate prompt); the timing of the fighting moves one's character knows, and of none it does not (`LIVING_SKILL_TIMINGS`) | `roundtrip`, `acts`, `timings` | [deliberation.md](deliberation.md) |
| A deliberation consumes the reasons its prompt contained: plan-finished churn during model calls keeps no older reason pending, a reason arriving mid-call waits for the next deliberation only; each thought's `detail.reasons` with `carried_before` | `reasons` | [deliberation.md](deliberation.md) |
| Answer speech and close an exchange; a line parked while a deliberation runs; `LIVING_PARK=concurrent` turns alongside; `LIVING_GREET` modes over the `audience` table | `conversation`, `parked`, `alongside`, `greet` | [conversations.md](conversations.md) |
| Speech through a mind: a talk reply's `way` reaches `mind_say` (one the world lacks is said aloud), an `introduced` row reaches consolidation tagged with the person, the mind's own line reads as heard by those it saw (`heard`) | `speech` | [conversations.md](conversations.md#ways-and-who-heard) |
| Privacy of words: none of a line's words reach anyone who should not receive them (experience, prompts, client, memory), for any way on `speech_card` | `privacy.py` (Neo4j) | [privacy.md](privacy.md) |
| The prompt frame: `LIVING_FRAME=player` opens think, compile, talk and consolidation with the player frame (sent and journaled), never an identity; the default leaves prompts unchanged; a bad value stops the service | `frame`, `roundtrip`; `prompts::` tests | [frame.md](frame.md) |
| No-store persona/cursor, patch-loss XFAIL | `consolidation` | [consolidation.md](consolidation.md) |
| Validate graphs, restrict actors, recover connection | `prune`, `reject`, `only`, `reconnect` | [robustness.md](robustness.md) |
| Wait off stage and resume on stage | `lod` | [level-of-detail.md](level-of-detail.md) |
| An offline player's character: takeover after `takeover_s`, thought for like any AI, handback (plan stops, graph held), a reply in flight refused | `takeover` | [takeover.md](takeover.md) |
| A mind sees what its character sees: the scene the model is sent and the deaths it witnesses follow the sight line | `sight` | [sight.md](sight.md) |
| Sight that depends on facing (the `fov_on` law): what a mind hears and does not see, in its scene and the prompt in a person's words with no id, its facing, the percept when a sound begins, the person instinct's "turn to a sound" habit turning the body | `fov` | [fov.md](fov.md) |
| A mind is told of drops and low things in words (`terrain_near`), and sees the one across them, on the island | `drop` | [drop.md](drop.md) |
| A fighting mind's prompts give its opponent's health as the band ("they look hurt"), exact ("they have 70 of 100 health") only inside its own appraisal's 20 s; never a percentage | `health-seen` | [sight.md](sight.md) |
| The dead keep their names for those who knew them: a community member killed in view is named in the mind's death experience and in its next prompt (what happened, relations), not "a stranger"; the killer reads "killed by you" | `death-names` | [sight.md](sight.md) |
| Cheaper animal minds: one call picks among built options (choose), the deer it sees reuse it (pack), nothing new answers by instinct (salient) | `animals` | [animals.md](animals.md) |
| Reorganization at night, in the night's batch round | `night` (scheduling, no store); `verify-knowledge` sleep stage (the batch job) | [sleep.md](sleep.md) |
| A cached Jev judgment drives the graph: asked in the background, cached by `mind_judged`, read by `judged` | `jev` | [judgments.md](judgments.md) |
| The rethink gate: a fast judge (Jev or a chat model) holds non-urgent deliberations; urgent bypass, accumulation, talk while held, fallback, max hold | `rethink`, `rethink-llm` | [rethink.md](rethink.md) |
| Dealings: a demand on a mind's character is told and asks its mind; the deliberation shows it under "Your dealings" (the script's `record_text`); the model's give pays it and the rules count it (`met`, the demander told) | `dealings` | [dealings.md](dealings.md) |
| Answers by id: the scene shows a trade offer's id and the dealings a proposal's record id; the model's `accept` with `"offer"` and `decline` with `"record"` are executed (the trade taken with terms standing, the terms declined, the proposer told) | `answers` | [dealings.md](dealings.md) |
| An island resident is a mind from the start: this service thinks for it, it answers, takes talk turns, accepts the trade and teaches through its own acts, keeps its given places through a replacing update | `resident` | [resident.md](resident.md) |
| A resident of the seeded island knows its past and its people: relations as rows from world creation, its authored persona, people and `[before all this]` memories in its first prompt, secrets kept to their owner (scratch Neo4j) | `lives_mind.py` on an island run | [lives-mind.md](lives-mind.md) |
| Player memory: switch off, cadence (session end by presence), the takeover's wait for its past, persona inferred, reconnect from `lived_upto`, batch mode | `verify-knowledge` `player_memory.py` | [player-memory.md](player-memory.md) |
| Paid-wrapper dry safety and paid smoke check | dry safety; paid authorization required | [real-models.md](real-models.md) |
| Projects (`LIVING_PROJECTS=1`): self-chosen aims in the mind's graph, shown to every think step with `serves`, kept by consolidation and reorganization | `--fake` trial batch, variant `projects` (needs Neo4j; the suite's cases run without a store) | [projects.md](projects.md) |
| Trials: one mind in a scripted or open-ended world (`living/tools/trials.py`) | `--fake` dry batch; real batches measured, uncapped | [trials.md](trials.md) |

Each free case launches its own database through `verify.py` and passes doctor before driving the real mind binary. Admin calls arrange scenes only. Requests go through the production HTTP model boundary, and replies return through production mind reducers. Public snapshots use shared SQL; private deliberations use shared `sql --as-admin` with the token held in memory. Store-backed projections belong to `verify-knowledge`.

All evidence stays under `.local/living/verify/`. The paid tier is documented and intentionally unexecuted. Runtime discovery uses the shared `.agents/skills/` source and the existing Claude and Cursor links.
