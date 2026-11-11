# Written knowledge and death

## Sub-features

- Writing creates a tablet with the exact author, words, topic and holder. Giving it changes its holder.
- Reading that tablet teaches spear with `read Walker1's tablet`. Reading twice preserves the knowledge row and earns two read practices.
- Writing a sign creates a sign structure and an artifact held by `STRUCTURE_BIT | structure.id`.
- Reading the sign teaches planting with `read Walker1's sign`.
- Death removes the reader's know-how and practice, marks the character dead and creates remains.
- The tablet moves to the remains while its ID, text, topic, author and written time stay unchanged. A living student's knowledge survives.

Sources: `living/authority/src/act.rs:1356` (write), `act.rs:1373` (read), `act.rs:2114` (`die`: know-how deleted at `act.rs:2142`, held artifacts moved to the remains at `act.rs:2164`); `tables.rs:433` (`structure`), `tables.rs:594` (`know_how`), `tables.rs:609` (`artifact`).

## How to get to it (user POV)

A literate character writes a tablet to carry or give away, or leaves a sign where others can read it. Written techniques can outlive their holder. A dead person's know-how does not become another person's capability.

## Driving it with verify_knowledge.py

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run knowledge-artifacts-$(date +%Y%m%d-%H%M%S)
```

The runner uses `write`, `give` and `read` behavior leaves and then the admin `kill` reducer. Inspect `tablet-given.json`, `read-*.json`, `sign-*.json`, `death-*.json`, `dead-character.json` and `survivor-knowledge.json`.

## Gotchas

- Read needs writing know-how. The teacher must know the tablet's topic before describing it.
- Reading with no target selects a held tablet first. The sign scene uses `nearest: sign` explicitly.
- A sign's artifact holder and a dead person's tablet holder encode a structure ID with `1 << 40`.
- The scene proves a tablet moves into remains. Retrieval by a survivor and inheritance by a new identity are outside this scene.
- `die` also keeps the dead's name for the other members of its community (`perception::remember_member`, one `acquaintance` row each, act.rs:2136). This runner does not assert it; `verify-core`'s `death-names` scene and `verify-minds`' `death-names` case do.
