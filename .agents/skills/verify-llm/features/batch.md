# Provider batch jobs (`Llm::batch`)

Used by player memory in `LIVING_PLAYER_MEMORY_MODE=batch` (docs/PLAYER_MEMORY.md) and by night reorganization (`LIVING_REORGANIZE=night-batch`, mind/sleep.rs; docs/MIND_HARNESS.md item 2). Mistral's batch API (docs.mistral.ai/capabilities/batch, read 2026-11-09): one model per job, half price, no stated completion window. Its front proxy refuses an inline body above about 2.5 MiB (docs/MODEL_COST.md Part 2).

## Sub-features

- `Llm::batch(route, attention, purpose, …)` resolves the route like a direct call (a mix included) and builds each line's `body` with `request_body`: direct and batch requests of one prompt are identical, effort and `purpose_max_tokens` included.
- **Inline or file:** up to `BATCH_INLINE_LIMIT` (2,400,000 bytes; `LIVING_BATCH_INLINE_LIMIT` lowers it for tests) the job carries `requests: [{custom_id, body}]`; above it the JSONL goes up with `POST {base}/files` (multipart, `purpose=batch`) and the job names it in `input_files`. The log line says which (`inline, N bytes` or `file <id>, N bytes`).
- `POST {base}/batch/jobs` with `model`, `endpoint: /v1/chat/completions` and `metadata.purpose`; polled with `GET {base}/batch/jobs/{id}` until `SUCCESS`, `FAILED`, `TIMEOUT_EXCEEDED` or `CANCELLED`; answers from `GET {base}/files/{output_file}/content` (and `error_file`), matched by `custom_id`, the completion under `response.body`.
- **Failed polls (2026-11-10):** up to `BATCH_POLL_FAILURES` (5) failed polls in a row are tolerated, and so are as many failed reads of a finished job's answers. A job given up on (its polls keep failing, or it is not done by its give-up time) is cancelled (`POST …/cancel`) before the caller sends again.
- **Kept for a restart:** every sent job is written to `<journal>/batches/<job>.json` (profile, purpose, effort, each item's id, actor, exact body and the caller's `meta`) and removed once collected or cancelled. `Llm::pending_jobs` lists what a previous run left; `Llm::collect(job, poll, after_restart)` waits for it and journals its answers with `after_restart: true`. At start, `Minds::collect_left_batches` (mind/sleep.rs) applies a night's reorganizations to the minds they were for (unless that mind is busy); player-memory answers are journaled only, since their experiences were held in memory and are sent again. A finished job whose answers cannot be read stays on disk for the next start.
- Each answer is journaled like a direct exchange with `mode: batch`, `job`, `custom_id`, `effort`, `mix`, `attention`, `finish_reason` and `reasoning_tokens`; a request without an answer is journaled with its error and reported to the caller alone.

Sources: `living/mind/src/llm.rs` (`request_body`, `BatchItem`, `PendingJob`, `BATCH_INLINE_LIMIT`, `BATCH_POLL_FAILURES`, `Llm::batch`, `Llm::collect`, `Llm::pending_jobs`), `living/mind/src/mind/sleep.rs` (`Prep::meta`, `collect_left_batches`).

## Driving it

- Cargo (fake provider, both shapes): `cargo test --manifest-path living/Cargo.toml -p living-mind a_large_batch_is_uploaded_as_a_file`. A small job goes inline, a large one as one upload; every line carries the mix's effort and the 24,000 reorganize cap.
- Cargo (fake provider, `batch.poll_errors`): `a_failed_poll_keeps_the_batch_and_a_left_job_is_collected_after_a_restart`. One 500 on a poll: every answer comes back and nothing is cancelled. Every poll failing: the job is given up after five polls and cancelled once. A run dropped before its first poll leaves `batches/<job>.json`, with the callers' meta; a new `Llm` on the same journal collects it and journals `after_restart`.
- Night reorganization end to end (Neo4j, upload forced): the knowledge suite's `sleep_batch` stage (`verify-knowledge`, "night reorganization as an uploaded batch job").
- Player memory in batch mode:

```bash
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) --mode batch
```

- Paid, a real night (authorized runs only): `LIVING_NIGHT_BATCH_SAMPLES=<jsonl> cargo test … night_batch_replay -- --ignored --nocapture` sends the reorganization prompts as one job on the `people` mix and prints turnaround, upload or inline, usable replies and tokens.

## Gotchas

- The real output line shape is not in Mistral's batch page; the parser accepts the completion under `response.body` or `response`.
- A job may sit `QUEUED`; the caller's poll interval and give-up time bound it (`LIVING_PLAYER_MEMORY_POLL_S`/`_BATCH_WAIT_S`; `LIVING_REORGANIZE_POLL_S`/`_GIVE_UP_S`, default a game day). The give-up time is measured from the job's creation, so a job collected after a restart keeps its original deadline.
- The fake logs polls and cancels only for a script with a `batch` section, so other readers of its log still see request records only.
