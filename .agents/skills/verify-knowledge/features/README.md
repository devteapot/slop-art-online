# Knowledge verification map

| Feature | File | Proof |
| --- | --- | --- |
| A resident's mind from the world's facts | [facts-minds.md](facts-minds.md) | `facts_mind.py`: the first identity made at start from facts only (no sheet, no perception), before the first deliberation; marks `world`/`ai`, its given `work` place in its mind; talk on the `people` mix's talk model; acts (food, a lesson, `host`); a stranger stays a stranger; paid: `residents_real.py` |
| Acquiring techniques and truthful refusals | [know-how.md](know-how.md) | Seed, grant, teach, experiment, gating, practice and idempotence; a world's own technique taught (`world-know-how`, cullet-laws) |
| Consolidation and projections | [consolidation.md](consolidation.md) | Real mind, fake reply, saved Cypher and five authority tables |
| Names from what happened: an introduction is an `acquaintance` and an `introduced` row, consolidation anchors it to the person, the graph names the person after it, and no one out of earshot learns it | [names.md](names.md) | `names.py`: real mind, fake reply, Neo4j (the trial stack's or any, `LIVING_PRIVACY_NEO4J`) |
| Night reorganization as a batch job | [sleep.md](sleep.md) | A fresh mind with the whole day as night: a round of one, the request uploaded as a file, the answer applied, the thought marked `batch` |
| Personal graph changes and fading | [memory-graph.md](memory-graph.md) | Ignored Neo4j tests, history, retraction, merge, forgetting and formative past |
| Player memory (on by default) | [player-memory.md](player-memory.md) | `player_memory.py`: switch off, session ended by the takeover and internalized with `lived_under`, projections and the inferred persona, the takeover's first thought after its past, `lived_under ai` for what the minds live, restart from `lived_upto`, no leak to a resident, recall tokens; direct and batch |
| Situational recall and budgets | [recall.md](recall.md) | Later real prompt, authored seed past and nonempty replay cases; token budget (`LIVING_RECALL_TOKENS`) and the deduplicated `rel` property by Cargo test |
| Two strangers stay two people: each unnamed person is its own node `person:<id>` named "a stranger #<id>"; a deed written under a description (`person:the_stranger`) goes to the one stranger its experiences involve; "stranger" cues no one in recall; a recalled memory says whom it involves; a name learned later names the same node | [strangers.md](strangers.md) | `strangers.py`: real mind, fake reply, Neo4j as `names.py`; `strangers_stay_apart` (ignored Cargo test, in the runner) |
| Written knowledge and death | [artifacts-and-death.md](artifacts-and-death.md) | Tablets, signs, reading, remains and deleted know-how |

Run `scripts/verify_knowledge.py run --run knowledge-<unique-name>` from the repository root. It launches with the shared harness, passes doctor, drives know-how, artifacts and death, the memory graph, consolidation and recall (the five original files) and the night batch and cleans up. Player memory has its own runner, `scripts/player_memory.py`, on an island world. Each file names the observations asserted by the runner. No paid tier is needed.
