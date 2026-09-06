# Persistent external worker

`participant_live_agent external-worker SESSION ACTOR_OUT_ROOT` accepts one job at a time on stdin and returns one terminal JSON object per accepted job on stdout. The supervisor must use pipes; Linux uses nonblocking Unix pipe descriptors so a pending stdin read cannot delay shutdown. Worker diagnostics and MCP stderr go to stderr.

```json
{"protocol":"sao-external-worker-v1","op":"job","id":1,"config_path":"/absolute/config.json","responsibility":"behavior","output":"01-behavior"}
```

IDs must be positive and strictly increasing. `responsibility` is `behavior`, `communication`, or `learning`; `output` is one path component under the actor audit root. A new or empty job directory is accepted; prior job journals are never overwritten. A second in-flight job is a protocol failure, cancels the active job and exits without executing the second job.

```json
{"protocol":"sao-external-worker-v1","id":1,"phase":"completed","exit_code":0,"error":null,"worker_reusable":true}
```

Terminal phases are `completed`, `failed`, and `interrupted`. Send `{"protocol":"sao-external-worker-v1","op":"cancel","id":1}` to cancel the active job or `{"protocol":"sao-external-worker-v1","op":"shutdown"}` to cancel, reap and exit. EOF, SIGINT and SIGTERM also shut down. An idle shutdown emits no acknowledgement. Cancellation retires the actor transport permanently; later attempts can be counted as failures by the supervisor.

The MCP child starts on the first valid configured job and persists for that actor. Every job performs fresh discovery, tool listing and `observe(after_cursor=0,limit=256)` before the normal single-attempt backend request. The shared payload function preserves the original external runtime's request bytes. The original five-argument `internal`/`external` modes remain available. No persistent-mode metadata enters participant context or model messages.

Each RPC has one 15-second deadline covering optional admission wait, write, flush and response. A separate reader preserves partial frames across caller deadlines and drains retired response IDs without exposing their bodies to later jobs. A failed or interrupted write poisons the transport; EOF, malformed frames and invalid response IDs do likewise. An application error or response deadline after a completed write can leave it reusable. No request is replayed, and a dead MCP child is never respawned. Closing kills and explicitly waits up to three seconds for the child; the supervisor retains its outer process-group cleanup bound.

`worker-job.json` records every safely addressed job, including failures before context exists. `external.json` begins only after real context and the normal backend payload exist. The local worker journal contains child PID, random instance identifier, creation time, cumulative RPC IDs, discarded-late-response count and per-job request method/tool, start/flush time, elapsed time, unchanged deadline and outcome. These are transport diagnostics, not authority read request IDs. Model completion and individual tool receipt errors preserve the original runtime's separate result semantics.

Offline verification (no authority or model):

```sh
CARGO_TARGET_DIR=target/experience-prefetch-native CARGO_BUILD_JOBS=2 TMPDIR=/home/carlid/.cache/sao-tmp cargo test -p bridge --example participant_live_agent
CARGO_TARGET_DIR=target/experience-prefetch-native CARGO_BUILD_JOBS=2 TMPDIR=/home/carlid/.cache/sao-tmp cargo build -p bridge --example participant_live_agent
TMPDIR=/home/carlid/.cache/sao-tmp SAO_WORKER_TEST_BINARY="$PWD/target/experience-prefetch-native/debug/examples/participant_live_agent" python3 server/bridge/examples/participant_live_agent/worker_contract_tests.py
```

The subprocess tests install a fake MCP only in their own temporary working directory and serve deterministic empty proposals from a local HTTP fixture. They check actual worker/child lifetime, reuse with fresh observations, application errors, fatal framing, cancellation during MCP and provider I/O, signal shutdown, and rejection of queued work. Rust tests cover partial frames across timeouts, write cancellation, envelope validation, protocol paths, early-failure journals and frozen legacy-payload parity across all three responsibilities.

## Optional shared RPC admission

Admission defaults off. To enable it, the supervisor sets both `SAO_EXTERNAL_RPC_ADMISSION_DIR` (an absolute, canonical run-owned directory) and `SAO_EXTERNAL_RPC_CONCURRENCY` (1–36). Before workers start, create distinct regular files `slot-00.lock` through `slot-(N-1).lock`, using two-digit zero-padded indexes. For eight slots the last file is `slot-07.lock`. Workers never create or unlink slots. Partial configuration, missing slots, symlinks, hard links or changed file identities fail closed. Keep the directory and slot files unchanged for the whole run; use a fresh private directory for each run. Native admission requires Unix file identity validation.

Only `tools/call` acquires a slot; discovery and listing bypass it. Each permit owns a fresh file handle locked with `std::fs::File::try_lock`. The handle stays open until the RPC returns, fails or is cancelled; process death also releases it. There is no lease recovery process, retry, replay or reconnect. The outer RPC deadline starts before admission, and the authority's existing 5-second read and 10-second receipt deadlines remain unchanged. A timed-out or cancelled dispatched RPC may still finish at the authority after its local permit is released, so the limit bounds local in-flight RPC calls, not eventual authority work.

The worker journal adds flat per-request `admission_wait_ms`, `admission_slot` (zero-based or null), `admission_count` (configured count or null), `admission_outcome` (`disabled`, `not_required`, `acquired`, `deadline`, `cancelled`, `failed`) and `delivery_unknown`. Admission-only timeout or cancellation has null RPC ID/flush time and false `delivery_unknown`. Dispatched transport failures and tool error receipts conservatively retain unknown-delivery evidence. These fields are absent from participant context and model messages.

Additional offline tests verify four native worker processes respect a two-slot cap, admission cancellation dispatches no request, and killing a native worker frees its slot while its original MCP child remains alive. Rust tests validate configuration, contention/release, admission-only deadlines and cancellation, and the shared admission/response deadline.
