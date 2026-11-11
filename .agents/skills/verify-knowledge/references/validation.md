# Knowledge validation

## 2026-11-11 fix-death-labels on main (Spark)

Main at `7837320` (the merge of `fix-death-labels`: `die` keeps the dead's name for its community, `witnessed` reads "you" for the event's object), worktree on the DGX Spark, against the trial container `slop-trials-stdb` (2.14.1, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL=http://127.0.0.1:3320`), private `CARGO_TARGET_DIR`, fake model only, load average 19–29 from other work.

- `verify_knowledge.py` (`knowledge-vdeath-20261111-155918`): all 20 proofs pass, including "death erases know-how and preserves tablets"; cleanup removed the database, the scratch Neo4j and the journal.
- `facts_mind.py` (`knowledge-facts-vd-20261111-160643`): all four proofs pass, including "a stranger stays a stranger in what the mind is sent".
- `player_memory.py --mode direct` (`knowledge-pmem-vd-20261111-160643`): all five proofs pass, including the death phase.
- `player_memory.py --mode batch`: the first run (`knowledge-pmem-vdb-20261111-161258`) failed at `assert 'player memory on' in log`: the mind logged only its subscription before the driver read the log, which the driver reads once right after `world subscribed:`. A harness timing fault under load, not this change; the rerun (`knowledge-pmem-vdb2-20261111-161447`) passes all five.
- The dead's name kept by its community is not asserted by these runners; `verify-minds`' `death-names` case (this date) and `verify-core`'s `death-names` scene cover it.
## 2026-11-11 projects (exp-projects, DGX Spark)

Worktree from `origin/main` `e09365b`, branch `exp-projects` (the `LIVING_PROJECTS=1` experiment: docs/LIVING_CORE.md, "Projects"), against the trial server `slop-trials-stdb` (2.14.1, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL=http://127.0.0.1:3320`) beside a running trial batch, fake model only. `knowledge-20261111-132650`: all proofs pass, including the new ignored test `projects_are_pursued_served_ended_and_faded` (taken up, revised with since kept, served and reinforced, an ended one closed with `outcome` and refused when served, every unreinforced one faded at a 90-minute fade, history kept). The shared harness needed one fix first: the trial server publishes its port on `0.0.0.0` and `verify.py local_urls` accepted only `127.0.0.1` bindings (a failed `minds-20261111-131717` launch; fixed in the same change).

## 2026-11-11 every person a mind (lives-2, dev-box)

On the dev-box worktree `~/dev/slop-lives2`, branch `lives-2` (d87310d unit 1, 6157bf0/055d80e/efcd489 units 2-4, 45d4ac6 the new-day fix), own container `lives2-stdb` (2.14.1, port 3461, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only. Several suites ran at once (load 25-45); one batch failed on a full disk (`No space left on device`, the whole dev-box at 98 %) and was rerun.

- `facts_mind.py` (new, replaces `woken_mind.py`): all proofs pass (`knowledge-facts-015503`, again `knowledge-facts-l2c-030713`): identity from facts at the service's start, before the first deliberation, marks `world`, the given `work` place in the mind, talk on the `people` mix's talk model, food, a lesson and lodging, a stranger stays a stranger. Two driver fixes on the way: the line to a living mind is a talk turn, so the driver asks for a deliberation (`set_behavior` think node, through the CLI, since `admin()`'s revision check races the mind's own install).
- Full suite `knowledge-l2c-030713`: all proofs pass. `knowledge-l2b-022738` failed one timing bound under load (`recall_by_cues_and_forgetting`: 670 ms against 500).
- `residents_real.py` (paid, replaces `woken_real.py`) was not run.

## 2026-11-10 rules2-r2 fixes (dev-box)

On the dev-box worktree `~/dev/slop-mind-small`, branch `fix-mind-small`, own container `mind-small-stdb` (2.14.1, port 3427, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only, scratch Neo4j on 7691 per run.

- `knowledge-ms-full` failed before any mind ran: `memory_integration` looks for the player's first line among Oren's first 40 experiences, and under load (three suites at once) Oren had lived 46 before it. A harness timing fault, not this change. `knowledge-ms-full2`, run alone, passes 20 of 20, including `missed_things_weaken` (an `exp:66219` memory is not weakened by thing #66219; `weakened_upto` 0, then 9), real consolidation with per-entry `because`, and the uploaded night batch.
- `woken_mind.py` (`knowledge-woken-ms`) passes all proofs; `player_memory.py --mode batch` (`knowledge-pmem-ms`) passes all proofs.

## 2026-11-10 mind feedback (Mac)

Branch `feedback-1` (ffb4280) on its own server `feedback-verify-stdb` (3343): `knowledge-fb1-011838` passes 19 of 19, including the new Cargo test `missed_things_weaken` (memories naming a missed thing's id lose half; another id and `KNOWS` do not). `woken_mind.py`: the first attempt failed because the script started the mind against `:3300`; with `LIVING_STDB_URL` honoured, `knowledge-woken-fb1b-*` passes 8 of 8.

## 2026-11-10 woken residents' minds (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), branch `townlife-2` (main `015707b`, the `harness-1` merge, merged in) in a worktree: town life layer 2, phase 2 (docs/TOWN_LIFE.md): woken minds made from facts and their ring, the `woken` route, the stage cap, `host`, the `habit` engagement class, names only when known (a feeling is no longer an introduction).

- `woken_mind.py` (new): `knowledge-woken-1` (`player_session.py` read `character` as the player; fixed to `my_characters`), `-2` (the models file lacked the per-purpose effort the fake tells purposes by), `-3` (the model's lesson had an unmet prerequisite; the driver now reads `requires`), `-4` 6 of 6, `-8` (the newcomer's name reached a talk prompt: `known_as`), `-11` 7 of 7 on the final code.
- `verify_knowledge.py run` (`knowledge-base-tl2`): 18 of 18. `player_memory.py --mode direct` (`knowledge-pmem-tl2b`): 6 of 6 after the integration path became shared with rings.
- Paid tier `woken_real.py --allow-live`: four runs, $0.47 in all; results and the two leaks they found in docs/TOWN_LIFE.md, "The paid runs".

## 2026-11-09 player memory with presence and the takeover (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `81b9dd8`/`dc5e41b` plus the uncommitted minds'-sight, projection and presence change (docs/PERCEPTION.md, "Second change"; docs/PLAYER_MEMORY.md, "Presence and the offline character"). Fake model only; every scratch database answered 404 after cleanup. `player_memory.py run --mode direct`: all six phases pass on `knowledge-pmem-perc2e` (switch off with `LIVING_PLAYER_MEMORY=0`; switch on with ids given as strings and the identity inferred; takeover; restart; recall; death). Earlier attempts `-perc2` … `-perc2d` found an authority defect (the takeover on an island seed went to the database, not the minds; fixed), a name leak through activity labels ("wave → Walker1"; fixed) and three driver gaps (leak check, relation check order, restart relying on idle detection; fixed). Batch mode was not run.

## 2026-10-18 stories, hearsay and childhood (`knowledge-20261018-205004`)

Host: macOS laptop, Docker Desktop 29.8.0 (first runs of this skill on Docker). Commit `f3595c3` plus the uncommitted knowledge-transmission changes (`living/mind/src/memory.rs`, `mind.rs`, `mind/recall.rs`, `mind/talk.rs`, `prompts.rs`) and harness portability fixes. SpacetimeDB 2.10.1, scratch Neo4j `neo4j:2026.09.0`. No paid model calls.

All seventeen proof groups passed, including the three new ignored tests (`grounds_link_stories_and_lessons`, `hearsay_fades_faster_until_corroborated`, `childhood_memories_last_longer`) and the real consolidation through the fake model. `graph-edges.txt` shows consolidated edges with provenance (six `hearsay: TRUE` from teller 25, two `firsthand: TRUE`) and `GROUNDS` links. `cleanup.json`: mind and fake stopped by SIGTERM, database 404, container removed, journal copied.

Portability fixes found on the way, each reproduced by a failed attempt (`knowledge-20261018-204243`, `-204405`, `-204436`, `-204602`, `-204927`; all cleaned up):

- Docker Compose named the server `sao-living-spacetimedb-1`; `living/deploy/compose.yml` now pins podman-compose's `sao-living_spacetimedb_1`.
- Docker Desktop reports the `/wasm` bind mount as `/host_mnt/...`; the shared harness strips it.
- `docker container exists` is podman only (on Docker, cleanup would report a running container removed); the runner uses `container inspect`.
- Docker lists the image by short name; the runner accepts it.
- `/proc/<pid>/stat` is Linux only; `proc_info` falls back to `ps -o lstart=,stat=`.
- A run that starts SpacetimeDB stops it in shared cleanup before the runner's final SQL check, which then fails with "connection refused". Start the server first (SKILL.md preconditions).
- `-204436` also caught a product bug: the memory write's new `GROUNDS` link used `$t` without passing it.

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

## Player memory (2026-11-09, Mac, uncommitted working tree on a4d79c0)

| Run | Result | Evidence and notes |
| --- | --- | --- |
| `knowledge-pmem-direct-130816` | Off and on phases passed; the restart check read a thought from before the restart. | Driver fixed to wait for a new thought (`before` count). |
| `knowledge-pmem-direct-131204` | The world had no tree in sight: the gather failed, and a check keyed on "+1 wood" failed. | The fixture and checks now key on "gather"; a failed act is still lived experience. |
| `knowledge-pmem-direct-131441`, `knowledge-pmem-batch-131746` | All four phases passed in direct and batch mode. | `results.json`: two requests (the off-phase backlog, then the session), identical system prompts, restart took ids 58 and 60 after `lived_upto` 57, recall 31–85 tokens. |
| `knowledge-pmem-direct-133133`, `knowledge-pmem-batch-133519` | All four phases passed with two new checks: the admin's `mind_update` with a persona for the player is refused ("identity is not projected"), and a planted `person:1` (never perceived) is dropped and noted. | `actions.log` (refusal), `on-player-*`, `requests.jsonl` (`batch_job`), `journal/`. |
| `knowledge-pmem-real-132240` (paid) | The driver read "internalized up to 0" as done and stopped the candidates early. DeepSeek and ministral direct answered; three batch jobs were left at the provider, and their status was read afterwards (SUCCESS in 24–30 s; GLM still running, then SUCCESS). | Driver fixed to wait for "lived experiences (". |
| `knowledge-pmem-real-132616` (paid) | Six candidates (ministral-14b, GLM Flash, DeepSeek Flash; direct and batch) internalized the same 11 rows. | `report.md`, `fidelity.json`, `cost.json`, `cand-*-nodes.txt`, `cand-*-edges.txt`, `journal/`. GLM batch wrote the resident as `person:29`, which led to the `perceived_people_only` guard. Results in `docs/PLAYER_MEMORY.md`. |

Every attempt's `cleanup.json` reports database deletion, scratch Neo4j removal and journal removal. `knowledge-pmem-direct-134341` added phase 5 (death: rows deleted by the authority, last words still integrated) and passed all five. Not covered: two players at once, the game-day cadence in real time, buffer overflow over 2,000 rows, and recall replayed on the real graphs.

## Merge guard (2026-11-10, Mac, branch `merge-guard` on bbf7271)

| Run | Result | Evidence and notes |
| --- | --- | --- |
| `knowledge-mg-20261110-131913` | Every feature passed up to the new pattern check, which found no `FITS` edge. | The patch held both edges. Non-fixed types are stored as `RELATES {rel}`, so the query was fixed. Both refusals were in the thought's notes, and Teodor kept his name. |
| `knowledge-mg2-20261110-132532`, `knowledge-mg3-20261110-133032` | Timed out waiting for the first decision (90 s) in `memory_integration`. | The only deliberation comes from the authority's reflect timer (170 s for Oren, counted from the world's start). The first run's cold build made it due early; warm reruns are faster. The wait is now 300 s. |
| `knowledge-mg4-20261110-133517` | All 20 features passed, including "merges between different identities refused and told". | `requests-sleep.jsonl` (the batch request tells the consolidation's refused merge), `sleep-thought.json` (notes), `graph-sleep-merged.txt`, `graph-sleep-people.txt`, `graph-sleep-pattern.txt`. |

Every attempt's `cleanup.json` reports database deletion, scratch Neo4j removal and journal removal. Not covered: the refusal list across a mind-service restart (it is kept in memory, as pruned graph parts are), and community and located-place refusals in a live world (unit tests only; land worlds clamp located places to 96 × 96, see docs/TRIALS.md).
