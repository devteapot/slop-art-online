# Internal mind verification map

| Feature | Cases | File |
| --- | --- | --- |
| Think, compile, install, act, speak | `roundtrip`, `acts` | [deliberation.md](deliberation.md) |
| Answer speech and close an exchange | `conversation` | [conversations.md](conversations.md) |
| No-store persona/cursor, patch-loss XFAIL | `consolidation` | [consolidation.md](consolidation.md) |
| Validate graphs, restrict actors, recover connection | `prune`, `reject`, `only`, `reconnect` | [robustness.md](robustness.md) |
| Wait off stage and resume on stage | `lod` | [level-of-detail.md](level-of-detail.md) |
| An offline player's character: takeover after `takeover_s`, thought for like any AI, handback (plan stops, graph held), a reply in flight refused | `takeover` | [takeover.md](takeover.md) |
| A mind sees what its character sees: the scene the model is sent and the deaths it witnesses follow the sight line | `sight` | [sight.md](sight.md) |
| Cheaper animal minds: one call picks among built options (choose), the deer it sees reuse it (pack), nothing new answers by instinct (salient) | `animals` | [animals.md](animals.md) |
| Reorganization at night, in the night's batch round | `night` (scheduling, no store); `verify-knowledge` sleep stage (the batch job) | [sleep.md](sleep.md) |
| A cached Jev judgment drives the graph: asked in the background, cached by `mind_judged`, read by `judged` | `jev` | [judgments.md](judgments.md) |
| The rethink gate: a fast judge (Jev or a chat model) holds non-urgent deliberations; urgent bypass, accumulation, talk while held, fallback, max hold | `rethink`, `rethink-llm` | [rethink.md](rethink.md) |
| Dealings: a demand on a mind's character is told and asks its mind; the deliberation shows it under "Your dealings" (the script's `record_text`); the model's give pays it and the rules count it (`met`, the demander told) | `dealings` | [dealings.md](dealings.md) |
| An island resident is a mind from the start: this service thinks for it, it answers, takes talk turns, accepts the trade and teaches through its own acts, keeps its given places through a replacing update | `resident` | [resident.md](resident.md) |
| A resident of the seeded island knows its past and its people: relations as rows from world creation, its authored persona, people and `[before all this]` memories in its first prompt, secrets kept to their owner (scratch Neo4j) | `lives_mind.py` on an island run | [lives-mind.md](lives-mind.md) |
| Player memory: switch off, cadence (session end by presence), the takeover's wait for its past, persona inferred, reconnect from `lived_upto`, batch mode | `verify-knowledge` `player_memory.py` | [player-memory.md](player-memory.md) |
| Paid-wrapper dry safety and paid smoke check | dry safety; paid authorization required | [real-models.md](real-models.md) |
| Trials: one mind in a scripted or open-ended world (`living/tools/trials.py`) | `--fake` dry batch; real batches measured, uncapped | [trials.md](trials.md) |

Each free case launches its own database through `verify.py` and passes doctor before driving the real mind binary. Admin calls arrange scenes only. Requests go through the production HTTP model boundary, and replies return through production mind reducers. Public snapshots use shared SQL; private deliberations use shared `sql --as-admin` with the token held in memory. Store-backed projections belong to `verify-knowledge`.

All evidence stays under `.local/living/verify/`. The paid tier is documented and intentionally unexecuted. Runtime discovery uses the shared `.agents/skills/` source and the existing Claude and Cursor links.
