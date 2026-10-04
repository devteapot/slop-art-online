# Knowledge validation

## 2026-10-04 implementation runs

Host: Fedora, rootless Podman through the docker CLI, SELinux enforcing. Commit: `384fb50`, plus existing uncommitted `living/` changes reported by shared launch. Authority and SDK pin: SpacetimeDB 2.10.1. Scratch graph image: `docker.io/library/neo4j:2026.09.0`, already present locally. No paid model calls ran.

The runner uses the shared harness's `authored-test` launch and doctor. Every attempt has its own `verify-knowledge-*` database and owned Neo4j on loopback port 7691. Evidence is local and git-ignored under `.local/living/verify/<run>/`.

## Successful run `knowledge-1004-g`

The final instructions ran end to end and exited zero. Launch was at 16:37:32 Europe/Zurich. Database cleanup was at 16:39:58. The only uncommitted product file was the pre-existing `living/viewer/src/clock.rs`. The world had nineteen seeded characters, five added walkers and one joined witness. One walker died in the death scene. Only Oren had a connected mind.

Evidence root: `.local/living/verify/knowledge-1004-g/`. [results.json](../../../../.local/living/verify/knowledge-1004-g/results.json) records fourteen passing proof groups. [post-cleanup-check.json](../../../../.local/living/verify/knowledge-1004-g/post-cleanup-check.json) confirms that every referenced evidence file survives, all five named memory tests passed, both owned processes exited, the database answers SQL with 404, the container is absent and the journal was copied before its original was removed.

### Launch and doctor

| Check | Result | Evidence |
| --- | --- | --- |
| Shared launch with `--seed authored-test` | Pass | `actions.log`, `state.json` |
| Authority doctor | Pass. Server image v2.10.1, module newer than source, ticks 60 to 299 over its four-second sample. | `actions.log` |
| Dedicated scratch Neo4j and explicit connection variables | Pass. Local 2026.09.0 image, port 7691, owned label and no supplied named volume. | `images.log`, `neo4j-start.log`, `neo4j-doctor.log`, `neo4j-ready.txt`, `mind-environment.json`, `mind.log` |
| Fake model boundary | Pass. Loopback endpoint only, health passed, real mind connected. | `models.json`, `fake.log`, `requests.jsonl`, `mind.log` |

### Know-how

| Feature | Result | Evidence |
| --- | --- | --- |
| Seed and grant sources | Pass | `seed-knowledge.json`, `grant-before-repeat.json` |
| Grant idempotence | Pass. Identical rows, IDs, source and acquisition time. | `grant-before-repeat.json`, `grant-after-repeat.json` |
| Missing know-how blocks craft | Pass. Inventory unchanged and no craft practice. | `gate-before.json`, `gate-after.json`, `gate-practice.json`, `gate-knowledge-before.json` |
| Truthful learning feedback | Pass. Names teaching, writing and experimenting with fiber or hide. | `gate-feedback.json`, `gate-feedback-state.json`, `missing_know_how_says_how_to_learn_it.log` |
| Know-how enables craft and practice counts | Pass. Cloak made, practice rises from one to two. | `gate-unlocked.json`, `practice-one.json`, `practice-two.json` |
| Teaching source and repeat refusal | Pass. `taught by Walker1`, single preserved row. | `taught-knowledge.json`, `taught-after-repeat.json`, `teach-repeat-feedback.json` |
| Truthful technique names | Pass. Leather names tanning, stone lists valid techniques, missing cloak reports the teacher's lack. | `teach-feedback-leather.json`, `teach-feedback-stone.json`, `teach-feedback-cloak.json`, `teaching_names_real_techniques.log` |
| Experiment source | Pass. Tanning acquired as `worked it out`. | `experiment-before.json`, `experiment-after.json` |

### Artifacts and death

| Feature | Result | Evidence |
| --- | --- | --- |
| Write and transfer tablet | Pass. Exact author, text, topic and recipient. | `tablet-given.json` |
| Tablet reading source and idempotence | Pass. `read Walker1's tablet`, unchanged knowledge row after a second read, two practices. | `read-knowledge.json`, `read-after-repeat.json`, `read-practice.json` |
| Write sign and read its topic | Pass. Sign artifact belongs to its sign structure; planting source is `read Walker1's sign`. | `sign-written.json`, `sign-structure.json`, `sign-knowledge.json` |
| Delete dead actor's know-how and practice | Pass. Character is dead and both tables are empty for that actor. | `death-before-knowledge.json`, `death-after-knowledge.json`, `death-after-practice.json`, `dead-character.json` |
| Transfer held tablet into remains | Pass. Only the holder changes. | `death-before-tablets.json`, `death-remains.json`, `death-after-tablets.json` |
| Keep a survivor's learned capability | Pass | `survivor-knowledge.json` |

### Memory graph

| Feature | Result | Evidence |
| --- | --- | --- |
| Revision, relabeling, retraction, merge and belief fading | Pass. Named ignored test ran once. | `minds_revise_merge_and_fade.log` |
| Cue-based recall, stance relaxation and forgetting | Pass. Named ignored test ran once. | `recall_by_cues_and_forgetting.log` |
| Formative past fades slower | Pass. Ordinary stance and memory expire at the test's six-hour timestamp; authored equivalents remain. | `formative_past_outlasts_ordinary_beliefs.log` |
| Authored memory cues, identity history and secret preservation | Pass. Named ignored test ran once. | `authored_memories_are_recalled.log` |
| Every fixed edge type and arbitrary `RELATES` edge | Pass. Saved Cypher includes all ten fixed types, plus `RELATES` with `rel = SAFE_AT`. | `graph-edges.cypher`, `graph-edges.txt`, `graph-nodes.txt` |

### Consolidation and projection

| Feature | Result | Evidence |
| --- | --- | --- |
| Real mind accepts scripted consolidation | Pass. Reply and kept memory reference an actual heard speech experience. | `memory-input.json`, `fake-script.json`, `requests.jsonl`, `consolidation-thought.json`, `journal/` |
| Facts reach graph and beliefs | Pass | `graph-nodes.txt`, `graph-edges.txt`, `projection-belief.json` |
| Relation reaches authority | Pass. Teodor trust 66, affinity 33 and exact label. | `projection-relation.json` |
| Judgment reaches authority | Pass. Exact key and reason, value within 0.02 of 0.91 after relaxation. | `projection-judgment.json` |
| Place reaches authority | Pass. Amber Ford at 30, 40. | `projection-place.json` |
| Authored persona reaches authority | Pass. Oren's mill narrative is preserved. | `projection-persona.json`, `graph-nodes.txt` |

### Recall and budgets

| Feature | Result | Evidence |
| --- | --- | --- |
| Later deliberation recalls consolidated fact | Pass. User prompt contains the rendered `KNOWS` fact and named marker. | `recalled-deliberation.json` |
| Authored seed past is recalled | Pass. Same prompt includes `[before all this]` and Oren's exact flood memory. Cypher shows its authored ID, formative flag and positive rehearsal timestamp. | `recalled-deliberation.json`, `graph-memories.cypher`, `graph-memories.txt` |
| Fifth ignored test, `recall_replay` | Pass. Ran with four nonempty scratch cases. It requires a `LIVING_RECALL_CASES` path and cannot run without one. | `recall-cases.json`, `recall_replay.log` |
| Fact budgets and unrelated cue | Pass. Budget one returns one fact, budget eight returns six, unrelated cue returns zero. | `recall_replay.log` |
| Textual authored recall | Pass. Flood cue returns the authored flood memory. Two recent memories still appear as working memory in uncued cases. | `recall_replay.log` |

### Cleanup and retained evidence

`cleanup-first.json` records both processes stopped with SIGTERM and no forced kill. `cleanup-container.log` records Neo4j's exit code 0 and `docker rm -v`. `cleanup.json` confirms database, container and original journal removal. The documented cleanup command was repeated successfully after the password had been removed from private state. Evidence and the copied production journal remained intact. The shared SpacetimeDB service stayed running. Neo4j A and B were never used.

## Earlier attempts and corrections

| Run | Result | Evidence and correction |
| --- | --- | --- |
| `knowledge-1004-a` | Graph tests, seed and grant passed. Feedback drive failed. | `failure.log`, `results.json`, `gate-feedback.json`. Replaced invalid 600-second waits with 120 seconds and added brain-revision assertions. |
| `knowledge-1004-b` | Graph tests, seed and grant passed. Feedback drive failed. | `failure.log`, `graph-after-22.json`, `gate-feedback.json`. A refused start stores the reason in `mind_state.status`, not an `experience` row. Capture both. |
| `knowledge-1004-c` | Gating and practice passed. Unknown teaching item failed to reach the rules. | `failure.log`, `teach-feedback-leather.json`, `graph-after-20.json`. Normalization dropped `hide_preservation`. Use catalog item `stone` to drive the no-technique rule. The focused rules test still checks the exact unknown name. |
| `knowledge-1004-d` | Teaching passed. Scene-action assertion caught a truncated experiment sequence. | `failure.log`, `graph-after-23.json`. Split twenty attempts into two ten-child sequences. An interrupt arrived during cleanup; rerunning the documented cleanup command removed the remaining container. `cleanup.json` confirms recovery. |
| `knowledge-1004-e` | Every authority scene passed. Real consolidation and all projections worked. Graph assertion lacked `MERGED_INTO`. | `failure.log`, `graph-edges.txt`, `projection-*.json`, `consolidation-thought.json`. Merges run before new nodes are added. Changed the fixture to rename an already-existing authored stance. |
| `knowledge-1004-f` | Every authority scene, all fixed edge types, projection and later prompt recall worked. Memory evidence assertion failed on uppercase `TRUE`. | `failure.log`, `graph-memories.txt`, `recalled-deliberation.json`. Parse Cypher's CSV output and check the authored ID, formative flag and rehearsal timestamp. |

Each attempt's `cleanup.json` reports database deletion, container removal, journal removal, retained evidence and no cleanup errors after recovery. The shared authority service remained running. No product code, shared harness or neighbouring skill was edited.

## Issues observed at the product boundary

`living/rules/src/normalize.rs:383` rejects an unknown item before the teaching rule. `normalize.rs:195` drops a bad composite child and `normalize.rs:203` truncates children beyond twelve. `living/rules/src/graph.rs:385` discards those normalization warnings through `from_value`, used by `living/authority/src/mind.rs:265`. The resulting installed admin graph can omit the intended teaching action without a corresponding knowledge refusal. The proof captures this in attempt C and now asserts the installed action leaves. These existing semantics were not changed.

`living/tools/stdb` returned exit zero for calls containing invalid waits in attempt A. The runner now checks the brain revision and installed action leaves instead of treating the CLI status as proof. No shared harness change is required for the completed scenes. Propagating reducer rejection status and graph normalization warnings would make admin scene driving easier.

## Compatibility and limits

The helper uses Python's standard library and is executable. The skill has `name: verify-knowledge` and a descriptive frontmatter field. Read-only path checks confirm `.agents/skills/verify-knowledge`, `.claude/skills/verify-knowledge` and `.cursor/skills/verify-knowledge` resolve to the shared skill. This covers source discovery paths for Codex, Claude, Cursor and Mistral Vibe. Actual invocation in each runtime was not tested.

Fake replies prove memory plumbing and projection. They do not prove authentic model learning. Timestamp-based fading tests do not prove the real scheduler over six wall-clock hours. The proof does not cover permissions, observer controls, reconnect recovery, retrieval from remains, a new identity's inheritance, or scale. Use the neighbouring skills named in `SKILL.md` for those checks.
