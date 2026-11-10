# Night reorganization as a batch job

The store-backed half of [verify-minds sleep.md](../../verify-minds/features/sleep.md): a mind that is due goes to sleep in the night's round, its reorganization request goes out in a provider batch job, and the reply is applied to its Neo4j mind (fade, merge, retract, generalize) like a direct one. Design: docs/MIND_HARNESS.md, item 2.

## Sub-features

- `sleep_prepare` fades weak beliefs, then builds the request for a person whose mind holds at least 25 links; a smaller mind or an animal only fades.
- The job goes up as a JSONL file when the inline body passes `BATCH_INLINE_LIMIT` (the stage lowers it with `LIVING_BATCH_INLINE_LIMIT=2000`).
- `sleep_finish` applies the patch and writes a `reorganize` thought whose detail has `how: batch`.
- Merges between different identities (`memory::merge_refusal`) are refused: in the reply's `patch_from` on keys alone, and again in `canonical_people` with people named by id, communities and the mind's located places. Refusals are the thought's `notes` (`merge A → B refused: why`). They are kept per mind (`refused_merges`, from consolidations and reorganizations; in memory, at most 12) and told at the end of the next reorganization request under `# Merges that were not made last time`. `sleep_finish` also runs `name_people`, so a person node keeps the name this mind knows them by.

Sources: `living/mind/src/mind/sleep.rs`, `living/mind/src/llm.rs` (`Llm::batch`).

## Driving it

The `sleep_batch` stage of `scripts/verify_knowledge.py run` (after consolidation and recall): it stops the first mind and starts another with `LIVING_REORGANIZE=night-batch`, `LIVING_NIGHT=0-24`, no gap and one integration due; two lines of speech give Oren the integration, answered by a second fake provider that adds twelve links. It asserts the round (`night N: 1 of 1 minds go to sleep (1 in a batch`), the upload (`requests-sleep.jsonl` line with `upload`), the reorganize requests answered under a `batch_job`, `slept on it (batch)` in `mind-sleep.log` and the thought's `how`.

The merge guard rides on the same stage. The fake consolidation also merges the witness into Teodor (refused, kept). The fake reorganization merges Teodor into the witness and `stance:teodor_worth_another_try` into Teodor, merges `idea:sleep_detail_1` into `idea:sleep_detail_0`, renames Teodor "unresponsive townsfolk" and links both people to a new `idea:townsfolk_who_dont_answer`. The stage asserts that the batch request tells the consolidation's refusal, that the thought's notes hold both reorganization refusals, and that only the duplicate gained `MERGED_INTO` (`graph-sleep-merged.txt`). Both people and the stance stay unmerged, and Teodor is not renamed (`graph-sleep-people.txt`). Both people link to the pattern (`graph-sleep-pattern.txt`).

## Gotchas

- Oren's mind holds about 20 links after the earlier stages, under the 25 a reorganization needs; the stage's own fake provider answers his consolidation with twelve more, so his mind is big enough to send.
