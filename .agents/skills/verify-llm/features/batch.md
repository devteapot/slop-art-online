# Provider batch jobs (`Llm::batch`)

Used by player memory in `LIVING_PLAYER_MEMORY_MODE=batch` (docs/PLAYER_MEMORY.md) and by night reorganization (`LIVING_REORGANIZE=night-batch`, mind/sleep.rs; docs/MIND_HARNESS.md item 2). Mistral's batch API (docs.mistral.ai/capabilities/batch, read 2026-11-09): one model per job, half price, no stated completion window. Its front proxy refuses an inline body above about 2.5 MiB (docs/MODEL_COST.md Part 2).

## Sub-features

- `Llm::batch(route, attention, purpose, …)` resolves the route like a direct call (a mix included) and builds each line's `body` with `request_body`: direct and batch requests of one prompt are identical, effort and `purpose_max_tokens` included.
- **Inline or file:** up to `BATCH_INLINE_LIMIT` (2,400,000 bytes; `LIVING_BATCH_INLINE_LIMIT` lowers it for tests) the job carries `requests: [{custom_id, body}]`; above it the JSONL goes up with `POST {base}/files` (multipart, `purpose=batch`) and the job names it in `input_files`. The log line says which (`inline, N bytes` or `file <id>, N bytes`).
- `POST {base}/batch/jobs` with `model`, `endpoint: /v1/chat/completions` and `metadata.purpose`; polled with `GET {base}/batch/jobs/{id}` until `SUCCESS`, `FAILED`, `TIMEOUT_EXCEEDED` or `CANCELLED`; cancelled (`POST …/cancel`) after the give-up time; answers from `GET {base}/files/{output_file}/content` (and `error_file`), matched by `custom_id`, the completion under `response.body`.
- Each answer is journaled like a direct exchange with `mode: batch`, `job`, `custom_id`, `effort`, `mix` and `attention`; a request without an answer is journaled with its error and reported to the caller alone.

Sources: `living/mind/src/llm.rs` (`request_body`, `BatchItem`, `BATCH_INLINE_LIMIT`, `Llm::batch`).

## Driving it

- Cargo (fake provider, both shapes): `cargo test --manifest-path living/Cargo.toml -p living-mind a_large_batch_is_uploaded_as_a_file`. A small job goes inline, a large one as one upload; every line carries the mix's effort and the 24,000 reorganize cap.
- Night reorganization end to end (Neo4j, upload forced): the knowledge suite's `sleep_batch` stage (`verify-knowledge`, "night reorganization as an uploaded batch job").
- Player memory in batch mode:

```bash
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) --mode batch
```

- Paid, a real night (authorized runs only): `LIVING_NIGHT_BATCH_SAMPLES=<jsonl> cargo test … night_batch_replay -- --ignored --nocapture` sends the reorganization prompts as one job on the `people` mix and prints turnaround, upload or inline, usable replies and tokens.

## Gotchas

- The real output line shape is not in Mistral's batch page; the parser accepts the completion under `response.body` or `response`.
- A job may sit `QUEUED`; the caller's poll interval and give-up time bound it (`LIVING_PLAYER_MEMORY_POLL_S`/`_BATCH_WAIT_S`; `LIVING_REORGANIZE_POLL_S`/`_GIVE_UP_S`, default a game day).
