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

The first matching rule wins. Omitted `model` or `purpose` matches every value. `times` defaults to 1, 0 skips a rule, and -1 repeats forever. Selection and the counters share one lock, so concurrent requests consume each rule once. Matching is per request, not per actor. Use separate model names or ports to isolate actors. Restarting resets counters and appends to the log.

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
| `usage` | Exact usage object. Default prompt 12, completion 5, total 17, cached 8. Omit individual fields to prove unknown values remain null. |
| `headers` | Response header map, including Retry-After and optional provider rate-limit headers. |

## Purpose and valid replies

Purpose is `reasoning_effort` when its value is `think`, `deliberate`, `consolidate` or `talk`. Otherwise the server recognizes the system prompt. The production body has no separate purpose field. The local runner sets the per-purpose effort map to these names. They are fake values, not recommended live provider effort levels.

Defaults come from `prompts.rs` and the parsers in `mind.rs` and `mind/talk.rs`:

- Think returns a thought, an intention to wait and a spoken line. The mind preserves think speech when compiling the plan.
- Deliberate returns `graph: {"wait": 2}`, `plan: "verify fake wait"` and speech. The mind places the graph in the current-plan routine and retains bodily needs.
- Consolidate returns a valid empty memory patch and identity fields for background bootstrap. It creates no invented causal memories. The local basic case also proves an actual experience-consolidation reply is accepted.
- Talk returns one line, a settled outcome and `end: true`. Its target comes from the other person's numeric id in the system prompt. An explicit scripted reply overrides that inference.

The think default also has `feeling` and `impulse` for animal prompt compatibility. This skill proves human-purpose parsing. It does not prove all animal flows or every memory patch operation.

## Request evidence

The log appends one JSON line before a response delay or injected outage. Each line has `at_ms`, `sequence`, `purpose`, `model`, `reasoning_effort`, `body_excerpt`, full `body`, and the selected `status`, `delay_s`, `close_port` and `content`. Authorization headers are excluded. The excerpt is at most 2,000 characters. Exact prompts remain in `body`, and the real mind independently journals attempts, replies and failures.

The fake log proves receipt. The mind journal proves the client's recorded result. Authority `thought`, `brain`, `routine` and `chronicle` rows prove application. Check all three when acceptance matters.
