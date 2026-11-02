# Personal graph changes and fading

## Sub-features

- Graphs isolate concepts by `(run, actor, key)`.
- Applying a patch replaces labels, retracts edges and merges duplicate ideas while retaining closed history.
- `minds_revise_merge_and_fade` proves revision, merge, belief fading and graph projections.
- `recall_by_cues_and_forgetting` proves associative recall, uncued exclusion, stance relaxation and forgotten memories.
- `formative_past_outlasts_ordinary_beliefs` proves authored stances and memories survive an artificial six-hour interval that removes ordinary equivalents.
- `authored_memories_are_recalled` proves authored memories recall by people and words, `WAS` identity history and secret preservation.
- `grounds_link_stories_and_lessons` proves `GROUNDS` from a kept memory to what a belief citing it is about, whether the belief or the memory is written first, and that recall follows it only with the switch on (story to stance, stance to story, the latter not rehearsed).
- `hearsay_fades_faster_until_corroborated` proves single-source testimony closes at 40 minutes while a lived belief and one backed by a second teller hold; the same teller twice is still hearsay.
- `childhood_memories_last_longer` proves a childhood memory survives eight hours that forget an ordinary one.
- The non-ignored unit test `attributes_hearsay_by_teller` covers provenance rules (lived, own words, testimony about the teller, unknown experiences).

Sources: `living/mind/src/memory.rs:109`, `memory.rs:152`, `memory.rs:185`, `memory.rs:344`, `memory.rs:421`, `memory.rs:498`, `memory.rs:1118` (`attribute`); consolidation attribution in `living/mind/src/mind.rs` `consolidate`; ignored tests at `memory.rs:1288`, `memory.rs:1348`, `memory.rs:1402`, `memory.rs:1430`, `memory.rs:1577`, `memory.rs:1628`, `memory.rs:1664`.

## How to get to it (user POV)

Each character forms its own beliefs, memories and identity. Later experiences can revise them. Weak unreinforced beliefs close, and weak memories become forgotten history instead of disappearing.

## Driving it with verify_knowledge.py

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run knowledge-graph-$(date +%Y%m%d-%H%M%S)
```

The helper starts a dedicated throwaway Neo4j and runs all seven ignored tests with explicit scratch credentials. The matching `.log` file proves each named test ran once and passed. No test touches A or B.

## Gotchas

- Belief confidence is multiplied by `exp(-age / 40 min)` and closes below 0.2 when `fade` runs. Durable structural edges do not fade.
- Stances relax toward 0.5 and close below an absolute lean of 0.05. Memories use a three-hour time constant and become `Forgotten` below 0.15.
- Authored stances and memories fade twelve times slower. This does not apply to every authored edge. Childhood memories fade four times slower. Hearsay beliefs and stances (`hearsay = true`: never lived, one source) fade twice as fast.
- Provenance (`firsthand`, `sources`, `hearsay`) is set only by consolidation from experience kinds (`speech`, `read` are testimony). Conversation-turn edges and edges written before 2026-10-18 carry none and fade normally.
- Fixed edge types are `KNOWS`, `FEELS`, `JUDGES`, `WAS`, `INVOLVES`, `GROUNDS`, `CHILD_OF`, `PARENT_OF`, `MERGED_INTO`, `AGREED` and `WITH`. `GROUNDS` and `INVOLVES` are written by the store only; a model patch naming them is dropped. Other names use `RELATES {rel}`. The tests cover graph behavior; the real consolidation fixture separately captures every fixed type with Cypher.
- The tests advance timestamps to exercise fading. This proves the store operations, not the real mind's sleep scheduling over six wall-clock hours.
