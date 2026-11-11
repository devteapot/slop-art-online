# Fake model server interface

`scripts/fake_llm.py` uses only the Python standard library and binds to `127.0.0.1`. `verify-minds` and `verify-knowledge` can invoke this shared script directly. No product model adapter or simulator is substituted. The mind's production HTTP boundary is the fake boundary.

## Start and stop

```bash
.agents/skills/verify-llm/scripts/fake_llm.py --port 18181 --log .local/living/verify/llm-manual/requests.jsonl --scenario valid
```

`--port` and `--log` are required. Port 0 requests an OS-assigned port. A printed `READY http://127.0.0.1:<port>/v1 pid=<pid>` line signals that the socket is bound. `GET /health` returns 200. `POST /v1/chat/completions` returns the OpenAI-compatible envelope. The server accepts bearer authentication but never records the header or key. SIGTERM or SIGINT stops the listening socket and exits. Delayed request threads are daemon threads, so a stop does not wait 185 seconds. Stop only the pid your run created.

`--scenario` accepts `valid`, `429`, `500`, `malformed`, `repair`, `delay`, `timeout` or `outage`. These apply to every request. `--delay-s 1` controls the `delay` scenario. `timeout` delays 185 seconds, longer than the Rust client's 180-second timeout. `outage` logs the triggering request, closes its connection and closes the server port. Restart the same command on the same port to restore the endpoint.

A JSON script overrides `--scenario`:

```bash
.agents/skills/verify-llm/scripts/fake_llm.py --port 18181 --log .local/living/verify/llm-manual/requests.jsonl --script .local/living/verify/llm-manual/scenario.json
```

## Script schema

```json
{
  "defaults": {"tokens": 17},
  "replies": {
    "think": {"thought": "I will wait.", "intend": ["wait"], "say": null},
    "talk": {"thought": "I heard you.", "say": "Hello.", "to": 12, "end": true}
  },
  "rules": [
    {"model": "fake-primary", "purpose": "think", "status": 429, "times": 1},
    {"purpose": "deliberate", "content": "not JSON", "times": 1},
    {"purpose": "deliberate", "repair": true, "content_parts": true},
    {"purpose": "consolidate", "delay_s": 0.1, "times": -1}
  ]
}
```

The first matching rule wins. Omitted `model` or `purpose` matches every value. A rule's `contains` matches only requests whose JSON body contains that text (a marker in the reason, for example). `times` defaults to 1, 0 skips a rule, and -1 repeats forever. Selection and the counters share one lock, so concurrent requests consume each rule once. Matching is per request, not per actor. Use separate model names or ports to isolate actors. Restarting resets counters and appends to the log.

Each rule overlays `defaults`. Available response fields:

| Field | Meaning |
| --- | --- |
| `reply` | JSON value encoded as the message content. Overrides `replies[purpose]`. |
| `content` | Exact message content string. Use this for malformed or non-JSON model output. |
| `repair` | Wrap the JSON reply in a fence and add a trailing comma. Exercises `parse_json`. |
| `content_parts` | Return a non-text thinking part followed by a text part. Exercises content-array extraction. |
| `status` | HTTP status, default 200. Non-200 returns a scripted error object. |
| `delay_s` | Delay the response by this many seconds. |
| `close_port` | Close the request connection and stop the server's listener. |
| `raw_http_body` | Exact HTTP body. Use this for malformed envelope JSON. |
| `tokens` | `usage.total_tokens`, default 17. |
| `usage` | Exact usage object. Default prompt 12, completion 5, total 17, cached 8, reasoning 2 (`completion_tokens_details`). Omit individual fields to prove unknown values remain null. |
| `finish_reason` | The choice's `finish_reason`, default `stop` (direct and batch). |
| `headers` | Response header map, including Retry-After and optional provider rate-limit headers. |

## Citing the request (`cite`)

A rule with `"cite": true` fills placeholders in its `reply` from the experience lines the request carried (`- [id] time text {Name=#id}`), so a scripted memory patch can name real experience ids:

| Placeholder | Becomes |
| --- | --- |
| `$EXP:<words>` | the id of the first line whose text contains `<words>` (case-insensitive; 0 if none) |
| `$EXPS` | every line's id, as a list |
| `$EXPTEXT:<words>` | the text of the first line containing `<words>` (its time kept, its `{Name=#id}` tags dropped; `''` if none): a reply that repeats what it was told, for privacy checks (`verify-minds/scripts/privacy.py`) |
| `$PERSON` | `person:<id>` of the first tagged person |
| `$PERSON_ID` | that id, as a number |

## Batch jobs

`POST /v1/batch/jobs` with inline `requests` (`[{custom_id, body}]`, Mistral's shape) answers each request through the same script and log as a direct one (the log line gets `batch_job`) and returns `{"id": "job-N", "status": "QUEUED"}`. `GET /v1/batch/jobs/job-N` reports `QUEUED` on the first poll, `RUNNING` on the second and `SUCCESS` with `output_file: job-N-out` after. `GET /v1/files/job-N-out/content` returns one JSONL line per request: `{id, custom_id, response: {status_code: 200, body: <chat completion>}, error: null}`. `POST /v1/batch/jobs/job-N/cancel` answers `CANCELLATION_REQUESTED`. A script's `batch` section scripts the polls: `{"batch": {"poll_errors": n}}` answers each job's first n polls with HTTP 500 without moving the job on (`-1`: every poll). With a `batch` section the log also gets `{"poll": job, "status"}` per poll and `{"cancel": job}` per cancel; without one it holds request records only.

## Uploaded batch files

`POST /v1/files` (multipart with `purpose` and `file`) keeps the JSONL lines and answers `{"id": "file-N", "purpose": "batch", "bytes"}`; the log gets `{"upload": "file-N", "bytes", "lines"}`. A batch job whose body names it in `input_files` answers those lines as if they had been inline.

## Jev (`POST /v1/systemone`)

TypeSafe's judgment endpoint, shaped as its docs give it (docs.typesafe.ai, read 2026-11-09): `{"model", "state", "questions": {id: {"type": "noul"|"choice"|"score", "instructions", "criteria"}}}` → `{"model", "answers": {id: …}, "usage": {"input_tokens", "output_tokens"}}`. By default a noul's yes probability is how hurt `state.body` is (1 − health / max_health; 0.2 without a body), a choice takes its first criterion and a score is 0. A script rule with `"purpose": "judge"` may set `noul`, `status` or `delay_s`. Each request is logged with purpose `judge` and its `answers`. A rethink gate's request (its `state` has `why_it_is_asked_to_think`) is purpose `rethink` instead: its nouls default to 0.1, a rule's `noul` may be one number or a map per question id, and health is not read from its body (the gate sends needs as words).

## Purpose and valid replies

A rethink gate's chat question ("should stop and think again" in the system prompt) is `rethink`, default reply `{"rethink": false, "p": 0.1}`. An animal choosing ("pick one of the numbered", `LIVING_ANIMAL_MINDS=choose`) is `choose` and a sleep ("Tidy the person") is `reorganize` whatever the effort says, since they go out under `deliberate` and `consolidate` effort maps. Otherwise the purpose is `reasoning_effort` when its value is a purpose name (`think`, `deliberate`, `consolidate`, `talk`, `internalize`, `reorganize`, `judge`, `choose`, `rethink`), else the system prompt decides: "someone you cannot see" is `internalize`. The production body has no separate purpose field. The local runner sets the per-purpose effort map to these names. They are fake values, not recommended live provider effort levels.

Defaults come from `prompts.rs` and the parsers in `mind.rs` and `mind/talk.rs`:

- Think returns a thought, an intention to wait and a spoken line. The mind preserves think speech when compiling the plan.
- Deliberate returns `graph: {"wait": 2}`, `plan: "verify fake wait"` and speech. The mind places the graph in the current-plan routine and retains bodily needs.
- Consolidate returns a valid empty memory patch and identity fields for background bootstrap. It creates no invented causal memories. The local basic case also proves an actual experience-consolidation reply is accepted.
- Talk returns one line, a settled outcome and `end: true`. Its target comes from the other person's numeric id in the system prompt. An explicit scripted reply overrides that inference.

The think default also has `feeling` and `impulse` for animal prompt compatibility. `reorganize` returns an empty sleep patch with a summary. `choose` takes each numbered option in turn across requests (`pick` = request count mod options, strength cycling low/mid/high), so a run exercises every option an animal is offered. This skill proves human-purpose parsing. It does not prove all animal flows or every memory patch operation.

Projects (`LIVING_PROJECTS=1`, the mind's experiment) change the defaults only when the prompt carries them: a think request whose system prompt names `"serves"` answers `serves` with the first key listed under `# Your projects` in the user prompt (null when none is listed), and a consolidation or reorganization whose system prompt names `"projects"` answers one project, `project:verify_fake_shelter`, whose progress counts the projects the request listed. Without the switch every reply is as above.

## Request evidence

The log appends one JSON line before a response delay or injected outage. Each line has `at_ms`, `sequence`, `purpose`, `model`, `reasoning_effort`, `body_excerpt`, full `body`, and the selected `status`, `delay_s`, `close_port` and `content`. Authorization headers are excluded. The excerpt is at most 2,000 characters. Exact prompts remain in `body`, and the real mind independently journals attempts, replies and failures.

The fake log proves receipt. The mind journal proves the client's recorded result. Authority `thought`, `brain`, `routine` and `chronicle` rows prove application. Check all three when acceptance matters.
