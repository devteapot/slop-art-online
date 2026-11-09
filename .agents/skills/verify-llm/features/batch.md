# Provider batch jobs (`Llm::batch`)

Used by player memory in `LIVING_PLAYER_MEMORY_MODE=batch` (docs/PLAYER_MEMORY.md). Mistral's batch API (docs.mistral.ai/capabilities/batch, read 2026-11-09): inline `requests` (fewer than 10,000), one model per job, half price, no stated completion window.

## Sub-features

- Each line's `body` is built by `request_body`, the same function as a direct call (model, messages, `max_tokens`, JSON mode, effort, cache key): direct and batch requests of one prompt are identical.
- `POST {base}/batch/jobs` with `model`, `endpoint: /v1/chat/completions`, `requests: [{custom_id, body}]` and `metadata.purpose`; polled with `GET {base}/batch/jobs/{id}` until `SUCCESS`, `FAILED`, `TIMEOUT_EXCEEDED` or `CANCELLED`; cancelled (`POST …/cancel`) after the give-up time; answers from `GET {base}/files/{output_file}/content` (and `error_file`), matched by `custom_id`, the completion under `response.body`.
- Each answer is journaled like a direct exchange with `mode: batch`, `job` and `custom_id`; a request without an answer is journaled with its error and reported to the caller alone.

Sources: `living/mind/src/llm.rs` (`request_body`, `BatchItem`, `Llm::batch`).

## Driving it

The fake server answers the batch endpoints (see [fake-llm.md](../references/fake-llm.md)). The end-to-end proof is the player-memory runner in batch mode:

```bash
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) --mode batch
```

Its `requests.jsonl` lines carry `batch_job`; the copied `journal/` carries `mode: batch`.

## Gotchas

- The real output line shape is not in Mistral's batch page; the parser accepts the completion under `response.body` or `response`. The paid player-memory run records what the provider actually returned.
- A job may sit `QUEUED`; the caller's poll interval and give-up time (`LIVING_PLAYER_MEMORY_POLL_S`, `_BATCH_WAIT_S`) bound it.
