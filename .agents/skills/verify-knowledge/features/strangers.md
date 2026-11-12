# Two strangers stay two people

Defect: the arrival batch ar2 (docs/TRIALS.md on `trials-ar2`, "Arrival batch ar2", finding 3). Residents blamed the silent newcomer for what Cal, of the other settlement and unnamed to them, did: "I have watched you cook and teach all morning" was Cal teaching his nephew. Every unnamed person was "a stranger", so "a stranger" in memory was several people.

## What keeps them apart (`fix-stranger-merge`)

- **One node per person, named as perceived.** A person one does not know by name is the node `person:<id>`, named "a stranger #<id>" (or "a child #<id>", "an old stranger #<id>", "a baby #<id>": the authority's projection label, `perception::stranger`, with the id the mind perceives them by in its scene and in experience tags). `Minds::remembered_as` names nodes; `Minds::known_as` stays the prose label of prompts. Nodes for people a kept memory involves are named too (`name_people`).
- **Descriptions are anchored by evidence.** A reply that writes a person as a description (`person:the_stranger`: not an id, nobody's name) has each edge anchored to the one person not known by name that the edge's cited experiences involve (`memory::anchor_described`); the key's node, retractions and merges follow when all its edges went to one person. A description with no single person behind it stays a concept of its own. A name merely heard is not resolved to anyone (`canonical_people` resolves only names the mind knows).
- **Recall.** "stranger" is a stop word (`memory::STOP`): the word cues no one; people are cued by `person:<id>` (the scene, experience subjects). A name in a text cues its person only when the mind knows that name (`named_people`). A recalled memory is shown with whom it involves when its gist does not name them: "A stranger was teaching Lio. (with a stranger #77)" (`Store::involved`, `memory::with_involved`).
- **A name learned names the same node.** At each integration, every person the batch's experiences involve keeps its node's name current (`Store::rename_people`, existing nodes only), so the introduction names "a stranger #<id>" even when the reply mentions no one. The deeds stay on that node.
- **Too far away to make out** (far-label, 2026-11-12, docs/STRANGERS.md §1). Someone whose every experience in the mind's window reads "someone too far away to make out" (the authority's label where the world's `perceived_of` law marks them `far`) is remembered as "someone too far away to make out #<id>", known by name or not (`Minds::remembered_as`, `only_far`). Once made out they become "a stranger #<id>" or their name. The store never renames a node back to the far handle once it has another name (`memory::FAR_NAME_KEPT`, in `apply` and `rename_people`; checked in the ignored test `strangers_stay_apart`, run 2026-11-12 against the trial Neo4j). The authority writes no relation labelled "stranger" about someone whose name the character knows (`mind_update`; verify-core `stranger_filter`).
- What is not revealed: the id is the one the mind's scene and experience tags already carry; no description says two ids are one person; no name reaches a node before the authority counts it known.

## Driver

`scripts/strangers.py --run minds-strangers-<x> [--name Mercy]`: a real mind against the fake model with its graph in Neo4j (`verify-minds/scripts/privacy.py`'s helpers and environment, as `names.py`; nodes under the run's own name, deleted after). The mind first integrates its backlog, then:

1. Stranger A says 4 lines holding "spearcraft", and the mind integrates them; stranger B says 4 lines holding "fishbones", and the mind integrates them. The fake reply writes each deed under `person:the_stranger` and keeps one memory (rules by `contains`; the gists do not repeat the tokens).
2. A says "I am Mercy" and 2 more lines; the reply mentions no one.

Checks (`strangers.json`): two person nodes "a stranger #<A>" and "a stranger #<B>", no description-keyed person node, neither player's name; `TEACHES_SPEAR` on A only and `SMOKES_FISH` on B only; each memory `INVOLVES` only its own stranger; B's integration prompt shows A's deed only with `#<A>`; a recall replay cued by B and "a stranger" brings none of A's beliefs and shows A's deed only as A's; "the stranger" alone seeds nothing; after the introduction A's node is "Mercy", the same node with its deed, no node added; B stays "a stranger #<B>". Evidence: `neo4j-people*.txt`, `neo4j-deeds*.txt`, `neo4j-involves.txt`, `fish-consolidation-prompt.txt`, `recall-cases.json`, `recall_replay.log`, `fake-requests.jsonl`, `mind.log`.

The ignored Cargo test `strangers_stay_apart` (in the runner's `TESTS`) proves the store side on its own graph: cue by one stranger and the words "a stranger", neither the other's belief nor memory comes back; renaming makes no node.

## Not covered

- The scene's strangers are players who speak; a stranger seen doing a thing (an activity in a scene) reaches memory the same way (experience subject), but no scene drives it.
- Recall's working memory (the two most recent memories) still shows the other stranger's latest deed; it is tagged with its own stranger.
- Whether models stop conflating strangers in their words: that needs a paid arrival batch.
