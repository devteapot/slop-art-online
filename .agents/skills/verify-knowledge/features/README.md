# Knowledge verification map

| Feature | File | Proof |
| --- | --- | --- |
| Acquiring techniques and truthful refusals | [know-how.md](know-how.md) | Seed, grant, teach, experiment, gating, practice and idempotence |
| Written knowledge and death | [artifacts-and-death.md](artifacts-and-death.md) | Tablets, signs, reading, remains and deleted know-how |
| Personal graph changes and fading | [memory-graph.md](memory-graph.md) | Ignored Neo4j tests, history, retraction, merge, forgetting and formative past |
| Consolidation and projections | [consolidation.md](consolidation.md) | Real mind, fake reply, saved Cypher and five authority tables |
| Situational recall and budgets | [recall.md](recall.md) | Later real prompt, authored seed past and nonempty replay cases |
| Player memory (on by default) | [player-memory.md](player-memory.md) | `player_memory.py`: switch off, session ended by the takeover and internalized with `lived_under`, projections and the inferred persona, the takeover's first thought after its past, `lived_under ai` for what the minds live, restart from `lived_upto`, no leak to a resident, recall tokens; direct and batch |

Run `scripts/verify_knowledge.py run --run knowledge-<unique-name>` from the repository root. It launches with the shared harness, passes doctor, drives the first five files and cleans up. Player memory has its own runner, `scripts/player_memory.py`, on an island world. Each file names the observations asserted by the runner. No paid tier is needed.
