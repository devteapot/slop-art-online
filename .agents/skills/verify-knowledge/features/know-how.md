# Acquiring and using techniques

## Sub-features

- Seed acquisition has `source = seed` and a positive `since_ms`.
- Admin grants have `source = granted`. Repeating the grant preserves the single row, ID and acquisition time.
- Teaching writes `taught by Walker1`. A repeated teaching attempt truthfully refuses the already-known technique.
- Experimenting with hide writes `worked it out` for tanning.
- Missing cloak know-how blocks crafting, consumes no materials and earns no practice. The refusal names teaching, writing and experimenting with fiber or hide as learning routes.
- Granting cloak enables the same craft. Two successful crafts increment `practice.uses` from one to two.
- Teaching leather names tanning. An unknown technique lists real techniques. Teaching a technique the teacher lacks reports that fact.

Sources: `living/authority/src/tables.rs:436`, `common.rs:603`, `act.rs:953`, `act.rs:968`; `living/scripts/skills.rhai:590`, `skills.rhai:637`. Rules tests are `missing_know_how_says_how_to_learn_it` and `teaching_names_real_techniques` in `living/rules/src/script.rs:622`.

## How to get to it (user POV)

A character learns by being taught, reading or experimenting, then uses a skill whose rules require that technique. Both controllers use the same authority path. Grants are scene support.

## Driving it with verify_knowledge.py

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run knowledge-know-how-$(date +%Y%m%d-%H%M%S)
```

The runner spawns five idle walkers and installs focused behavior graphs. Read `seed-knowledge.json`, `grant-*.json`, `gate-*.json`, `practice-*.json`, `taught-*.json`, `teach-*-feedback.json`, `teach-feedback-*.json`, `experiment-*.json` and the focused rules-test logs. Calls and acceptance statuses are in `actions.log`.

## Gotchas

- Grant idempotence, repeated teaching and repeated reading preserve the original `know_how` row. The indexed `(actor, technique)` lookup owns this guarantee.
- Experimentation succeeds only when the authority's roll is below 0.3. Granting cloak leaves only tanning discoverable from hide. The helper allows twenty real attempts and fails after a bounded wait if none succeeds. It never substitutes a grant for this proof.
- `source` is exactly `worked it out` in the act code. An older table comment says `worked out`.
- A skill refused at start records its reason in `mind_state.status` and requests deliberation. Completed action failures can also write `experience` rows. The helper captures both and labels the source of each feedback line.
- The CLI returned zero for a rejected out-of-range wait in an earlier attempt. Every `set_behavior` now requires a brain revision change. Reducer acceptance alone is insufficient.
