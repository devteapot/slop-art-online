# Privacy of words

Design: docs/COMMUNICATION.md §7 ("Where words may go"). The words of a line may go only into the experience rows of those who received them, the speaker's own `said` row and the developer chronicle. They must never reach a character that did not receive them through any of these channels:

- its experience rows;
- its model prompts (talk, think, deliberate, consolidate);
- its person's client (`my_experience`);
- its memory graph.

## Driver

`scripts/privacy.py` runs a scene on its own launched world. Five seeded AI adults run under the real `living-mind` binary against the fake model, two players (each its own identity) take part, and the personal memory graph is written to Neo4j:

- the speaker, the addressee 1 m away, a bystander at 4 m and the near player at 5 m stand on one quiet spot;
- a far mind, a decoy speaker and the far player stand at a second spot, more than 20 m beyond the way's carry.

The speaker says four lines that hold a unique word (`plover<7 digits>`) to the addressee in `--way`, through `mind_say`. The decoy speaker says four lines to the far mind, and the near player says four to the bystander, so that those who must not hear still have lines to integrate. Then every mind is asked to deliberate, and the driver waits (`--wait`, 260 s) until the addressee, the far mind and the bystander have each consolidated.

Who must not receive the words follows from the way's `speech_card` row:

- beyond `carry_m`;
- and, for a `private` way, everyone but the addressee.

So a new way plugs in with `--way NAME` and no change to the driver. The fake model's consolidation reply is `remember: [{exp: $EXP:<word>, gist: $EXPTEXT:<word>}]` (verify-llm `fake_llm.py`). A memory therefore holds the words exactly when that mind's consolidation prompt did, and the Neo4j check is not trivially true.

Channels checked, per character:

| Channel | Read how |
| --- | --- |
| Experience rows | As the owner, right after the lines (before consolidation deletes integrated rows) |
| Client | `my_experience` with each player's own token |
| Prompts | Every journaled exchange of each mind, with its system prompts put back from `system/` |
| Memory | `MATCH (n) WHERE n.run = <db> AND n.actor = <id> RETURN properties(n)` in the Neo4j given by `LIVING_PRIVACY_NEO4J` |

The verdict, `privacy.json`:

- **Violations:** an excluded character with the word in a channel.
- **Missing positives:** a receiver (the addressee; for a public way, those in earshot) without the word in a channel it had. These keep the check from passing vacuously.
- **Not consolidated:** the addressee or the far mind never integrated, so the memory check would be vacuous. The run fails.

`--control` is the check of the check. It counts a public way as private, so the bystander and the near player are counted as ones who must not hear. The run passes only if the check finds the word in their experience rows, their prompts and the near player's client.

```bash
export LIVING_PRIVACY_NEO4J=slop-trials-neo4j:127.0.0.1:7699 LIVING_PRIVACY_NEO4J_ENV=<file with LIVING_NEO4J_PASSWORD=…>
python3 .agents/skills/verify-minds/scripts/privacy.py --run minds-privacy-say --way say
python3 .agents/skills/verify-minds/scripts/privacy.py --run minds-privacy-ctl --way say --control
```

The password is read from the file and handed to the mind's environment only; it is never printed or written to evidence. Nodes are written under the run's own database name and deleted at the end (`neo4j-cleanup-check.txt` holds the count left, 0).

## Ways covered

Since `speech-2`, the driver runs for each way on `speech_card`:

- `say`: public, carry 9 m. The bystander and the near player receive the words; the far group must not.
- `whisper`: private, 1.5 m. Only the addressee receives the words. The bystander and the near player, within 6 m and seeing the speaker, get `whispered` rows ("… whispers something to …") with no words, listed under `noticed` in `privacy.json`. The far group gets nothing.
- `call`: public, carry 22.5 m. The far group is placed at least the carry plus 25 m away, and must not receive the words.

## Evidence

`<run>/privacy.json`, `cast.json` (the way, the word, who receives and who must not), `experience-<id>.json`, `my-experience.json`, `neo4j-<id>.txt`, `thoughts-<id>.json`, `journal/` (copied at cleanup), `result.json`.

## Not covered

- A real model's paraphrase: the fake repeats the experience's text, so the check finds the word itself, not a retelling.
- Deliberation scenes (`scene_json`) and recall beyond the run's own nodes.
- A second mind service.
