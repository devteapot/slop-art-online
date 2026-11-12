# Names from what happened

Design: docs/COMMUNICATION.md §6 and §7 ("Names"). A name is learned only from something that happened to the learner. Standing near someone never teaches one.

- **Self-introduction** (built): a line whose words hold the speaker's own name gives every receiver of the words an `acquaintance` row (`perception::introduce`). From then on, every projection, percept and prompt names the speaker: `knows_name` on the authority, `known_as` in the mind service.
- **The moment is a row** (since `speech-1`). When the name is news, the receiver gets an `introduced` experience (subject the speaker, salience 0.55): "Mercy told you their name." A name already known writes nothing. A receiver of a line out of earshot gets neither row.
- **Into memory.** The mind's consolidation sees the line tagged `{Mercy=#id}`, the anchor `person:<id>`. The graph's node for the person, named "a stranger #<id>" before (`name_people` uses `remembered_as`, since `fix-stranger-merge`), is named "Mercy" at the next consolidation after it: by the reply's own node, or, when the reply mentions no one, by `Store::rename_people` for every person the integrated experiences involve ([strangers.md](strangers.md)).

## Driver

`scripts/names.py --run minds-names-<x> [--name Mercy]` runs a real mind against the fake model with its graph in Neo4j, using `verify-minds/scripts/privacy.py`'s helpers, its environment and the trial stack's Neo4j under the run's own name (deleted after). The scene:

1. A player greets the mind three times without a name, and the mind consolidates: its node for the player reads "a stranger #<id>".
2. The player says "I am Mercy, …", and the mind consolidates again.
3. A second mind stands 38 m away, out of earshot.

The checks: one `introduced` row with the right subject and text; the only new acquaintance is the mind's; the consolidation prompt holds the tagged line; the memory keeps it; the person's node is named afterwards; the far mind's graph has no node naming the player. Evidence: `names.json`, `neo4j-person-before.txt`, `neo4j-person-after.txt`, `neo4j-memories.txt`, `neo4j-far.txt`.

## Names of two words

`mentions` compares each word of the line with the whole name, so a name of two words ("Vessa Pontil", as in Cullet) is never mentioned: saying "I'm Vessa" teaches nothing. Fixed on `speech-2`: the player says only its given name, so `--name "Mara Quill"` proves a name of two words is learned from "I am Mara" (docs/COMMUNICATION.md §14).
