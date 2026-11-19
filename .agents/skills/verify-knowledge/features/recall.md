# Situational recall and budgets

## Sub-features

- A later deliberation receives the newly consolidated knowledge marker in its user prompt.
- That same prompt includes Oren's exact authored flood memory, prefixed `[before all this]`.
- Cypher shows authored memory IDs, formative flags and rehearsal timestamps.
- `recall_replay` runs with a generated nonempty `LIVING_RECALL_CASES` file against this real graph.
- A budget of one yields one fact. A budget of eight yields more facts within its limit. An unrelated cue yields none.
- A textual flood cue recalls the authored flood memory in the replay output.
- `techniques_named_as_whole_words` (unit) covers the `know:<technique>` cues; experiences naming a technique link to that anchor through `INVOLVES` when kept as memories.

Sources: `living/mind/src/mind/recall.rs:47` (`techniques_in`), `recall.rs:68`, `recall.rs:164`; `living/mind/src/memory.rs:777`, `memory.rs:1063`, `memory.rs:1474`; `living/seeds/authored-test.json:37`.

## How to get to it (user POV)

Seeing someone, hearing words or thinking about a problem can bring relevant beliefs and memories back. The character does not receive every stored belief in every prompt.

## Driving it with verify_knowledge.py

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run knowledge-recall-$(date +%Y%m%d-%H%M%S)
```

After checking projection, the helper requests a new thought about `knowledge_marker amber ford flood millstone`. It requires a later `deliberate` request with both recalled content and the authored memory. Inspect `recalled-deliberation.json`, `graph-memories.*`, `recall-cases.json` and `recall_replay.log`.

## Gotchas

- `recall_replay` cannot run without its cases path. It only prints results. The helper asserts its actual output and supplies cases against the populated scratch graph.
- Fact and memory budgets differ. Up to two latest memories enter as working memory in addition to cued memories. An uncued replay may still show those recent memories.
- Production deliberation uses eighteen facts. Consolidation uses thirty-two. Replay tests use one and eight to expose the cap.
- `LIVING_GROUNDS` is off by default. The real mind in this proof runs without it, so recall here never follows `GROUNDS`; `grounds_link_stories_and_lessons` covers both settings in the store.
- `LIVING_LESSONS=1` changes the consolidation system prompt; the fake model ignores it. Only a paid lab shows its effect.
- Prompt proof includes the entire user prompt. A cue repeated in a reason is not sufficient by itself; the helper also checks the graph, projections and authored-memory prefix.

## Homes

Since 2026-11-12 (house-owner-label; docs/IDEAS_AUDITS.md §2: minds already keep homes as places and free `LIVES_AT` edges, and recall brings them back). `scripts/homes.py` drives it with the real mind, the fake model and Neo4j. Asserted: M's notice line names F while F is too far away to make out; M's `place` rows hold "<F>'s house" at the house; Neo4j holds `person:<F> -LIVES_AT-> place:verify_home_f`; with F in sight, the think prompt's "# What comes to mind" has the `LIVES_AT` line naming F and the house. Evidence: `homes.json`, `prompt-homes.txt`, `neo4j-lives-at.txt`, `homes-overlay.rhai`. The fake model's consolidation writes the home, so this proves the store, the projection and recall, not that a model would keep it.
