# Personal graph changes and fading

## Sub-features

- Graphs isolate concepts by `(run, actor, key)`.
- Applying a patch replaces labels, retracts edges and merges duplicate ideas while retaining closed history.
- `minds_revise_merge_and_fade` proves revision, merge, belief fading and graph projections.
- `recall_by_cues_and_forgetting` proves associative recall, uncued exclusion, stance relaxation and forgotten memories.
- `formative_past_outlasts_ordinary_beliefs` proves authored stances and memories survive an artificial six-hour interval that removes ordinary equivalents.
- `authored_memories_are_recalled` proves authored memories recall by people and words, `WAS` identity history and secret preservation.

Sources: `living/mind/src/memory.rs:90`, `memory.rs:126`, `memory.rs:158`, `memory.rs:293`, `memory.rs:369`, `memory.rs:443`; ignored tests at `memory.rs:1174`, `memory.rs:1234`, `memory.rs:1288`, `memory.rs:1316`.

## How to get to it (user POV)

Each character forms its own beliefs, memories and identity. Later experiences can revise them. Weak unreinforced beliefs close, and weak memories become forgotten history instead of disappearing.

## Driving it with verify_knowledge.py

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run knowledge-graph-$(date +%Y%m%d-%H%M%S)
```

The helper starts a dedicated throwaway Neo4j and runs all four ignored tests with explicit scratch credentials. The matching `.log` file proves each named test ran once and passed. No test touches A or B.

## Gotchas

- Belief confidence is multiplied by `exp(-age / 40 min)` and closes below 0.2 when `fade` runs. Durable structural edges do not fade.
- Stances relax toward 0.5 and close below an absolute lean of 0.05. Memories use a three-hour time constant and become `Forgotten` below 0.15.
- Authored stances and memories fade twelve times slower. This does not apply to every authored edge.
- Fixed edge types are `KNOWS`, `FEELS`, `JUDGES`, `WAS`, `INVOLVES`, `CHILD_OF`, `PARENT_OF`, `MERGED_INTO`, `AGREED` and `WITH`. Other names use `RELATES {rel}`. The tests cover graph behavior; the real consolidation fixture separately captures every fixed type with Cypher.
- The tests advance timestamps to exercise fading. This proves the store operations, not the real mind's sleep scheduling over six wall-clock hours.
