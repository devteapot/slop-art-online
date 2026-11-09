# Night reorganization as a batch job

The store-backed half of [verify-minds sleep.md](../../verify-minds/features/sleep.md): a mind that is due goes to sleep in the night's round, its reorganization request goes out in a provider batch job, and the reply is applied to its Neo4j mind (fade, merge, retract, generalize) like a direct one. Design: docs/MIND_HARNESS.md, item 2.

## Sub-features

- `sleep_prepare` fades weak beliefs, then builds the request for a person whose mind holds at least 25 links; a smaller mind or an animal only fades.
- The job goes up as a JSONL file when the inline body passes `BATCH_INLINE_LIMIT` (the stage lowers it with `LIVING_BATCH_INLINE_LIMIT=2000`).
- `sleep_finish` applies the patch and writes a `reorganize` thought whose detail has `how: batch`.

Sources: `living/mind/src/mind/sleep.rs`, `living/mind/src/llm.rs` (`Llm::batch`).

## Driving it

The `sleep_batch` stage of `scripts/verify_knowledge.py run` (after consolidation and recall): it stops the first mind and starts another with `LIVING_REORGANIZE=night-batch`, `LIVING_NIGHT=0-24`, no gap and one integration due; two lines of speech give Oren the integration, answered by a second fake provider that adds twelve links. It asserts the round (`night N: 1 of 1 minds go to sleep (1 in a batch`), the upload (`requests-sleep.jsonl` line with `upload`), the reorganize requests answered under a `batch_job`, `slept on it (batch)` in `mind-sleep.log` and the thought's `how`.

## Gotchas

- Oren's mind holds about 20 links after the earlier stages, under the 25 a reorganization needs; the stage's own fake provider answers his consolidation with twelve more, so his mind is big enough to send.
