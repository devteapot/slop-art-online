# Participant agent runtimes

Latest live evidence: [mixed internal/external agent verification](LIVE_MIXED_AGENT_VERIFICATION.md) records ten genuine Luna calls, accepted behavior/dialogue/learning through both routes, preserved failures and corrections, and 66 passing regressions. Earlier no-fresh-inference statements below describe the preceding implementation milestone.

Rules `m1-5` add `sao-participant-v1`: an external runtime owns its model, memory, tools and deliberation schedule. The game supplies subjective experience and executes accepted intent. The built-in NPC harness uses the same scoped `ParticipantService`, authenticated reducer and caller-specific view as the MCP adapter. It has no owner token, observer subscription, SQL or privileged model-result route.

## Run the development world

Follow the tool prerequisites and CLI exports in [the Bevy runbook](BEVY_BROWSER_CLIENT.md), then start the database container, build and run from the repository root:

```sh
just bevy-db-up # or: just runtime=podman bevy-db-up
just bevy-db-login # first time for this database volume
cargo build --locked -p server_module --target wasm32-unknown-unknown
cargo build --locked -p bridge --bin sao-dev-client --bin sao-agent-mcp
just bevy-web-build
just bevy-dev
```

Open http://127.0.0.1:18891. This iteration uses `client/dist-participant` and `output/participant-agent-dev`; the previous host on 18890, its bundle, databases and archives remain separate. Each startup publishes to a fresh database in the SpacetimeDB 2.1.0 container on port 3101 (Compose project `sao-bevy`, persistent volume `sao-bevy_spacetimedb-home`). Stop it with `just bevy-db-down`, using the same runtime override; this retains database data. The clock starts paused. Resume or Step as observer; human input uses Participate as You. Human movement is finite, while agent trees repeat. Human speech uses the independent queue and does not replace movement.

Mira (actor 1) gets a scoped built-in identity. Default startup installs one explicitly authored tree through the participant API, without inference. Tovan (actor 2) gets a separately scoped external identity and no hidden bootstrap. You (actor 3) remains available to Bevy. Missing agent decisions leave the character without new intent; the authority does not invent a survival policy.

`output/participant-agent-dev/active.json` identifies the current run. Its `participants.json` lists session file paths. Session files under `.local/credentials` are private, created with mode 0600 and contain the SDK token. Give a runtime only its assigned session file. Do not commit, print, or include that token in a model prompt.

## Connect an external runtime through MCP

Launch this local stdio server from the MCP client of your choice:

```sh
SAO_PARTICIPANT_SESSION="/absolute/path/to/assigned-external.json" \
  /absolute/path/to/slop-art-online/target/debug/sao-agent-mcp
```

A typical client's server configuration has `command` set to that absolute binary path and `env.SAO_PARTICIPANT_SESSION` set to the session file path. Client configuration formats vary. No Codex configuration is automatically changed. The external runtime must connect, observe, choose operations and decide when to observe again; attaching an MCP server does not itself schedule autonomous play.

This adapter uses official Rust SDK `rmcp = 3.2.0`, stdio, and the current MCP **2026-07-28** lifecycle. The executable verification uses actual `server/discover`, `tools/list` and `tools/call` requests with per-request protocol/client metadata. The [official architecture](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture), [July release](https://blog.modelcontextprotocol.io/posts/2026-07-28/) and [Rust SDK releases](https://github.com/modelcontextprotocol/rust-sdk/releases) were checked for this implementation. No ACP orchestration or bespoke legacy HTTP protocol is included.

## Contract and concurrency

| Operation | Required concurrency / effect |
|---|---|
| `observe(after_cursor, limit)` | Returns own context, execution, revisions, control epoch, bounded experiences, receipts and queued speech. Limit is 1–256. |
| `replace_tree` | Requires current policy revision. Validates the complete tree, interrupts previous execution, installs a new revision. |
| `patch_subtree` | Requires current policy revision and canonical `root/0/guard`-style path. Atomically replaces one node after validating the resulting whole tree. |
| `speak` | Requires current control epoch, chosen text and expiry tick. Queues speech independently of policy and learning revisions. |
| `reflect` | Requires current learning revision and observed cursor. Applies bounded interpretations, caution/trust/belief changes and optional goal independently of execution. |

Every mutation carries `api_version` (the MCP adapter supplies it), a unique `request_id` and the observed `control_epoch`. The authenticated grant determines the run and actor; callers cannot select another actor. Wrong versions/epochs, invalid trees, unknown fields, hidden targets and stale revisions are rejected. A command is atomic; a multi-operation harness proposal is a sequence of separately atomic commands, not a transaction. A failed command leaves intent/learning unchanged and retains a rejection receipt.

Patch semantics retain ancestor and unaffected sibling sequence progress. Cursors and branch state at or below the replaced node reset. The running attempt is interrupted only when its active leaf lies inside that subtree. The next tick rechecks guards, so preserved progress is still subject to current conditions. Tree bounds remain 64 nodes, depth 8, eight children and the shared skill requirements.

The installed fast tree continues while reasoning is delayed, disconnected or absent. A new participant assignment or active grant revocation increments the control epoch and cancels queued speech, preserving the already installed tree. A same-identity switch to observer preserves committed intent/speech so paused human input can be stepped; re-entry as participant advances the epoch. Grant removal also removes the caller-specific row. Death and stopped runs reject new effects and cancel queued speech. Slow harness calls are cancelled on death, stop, disconnect or epoch change, and the authority independently checks submission validity.

Independent speech is FIFO, at most eight queued utterances, 1–1000 characters, with expiry from the next tick through 30 ticks ahead. Delivery occurs after movement/consequences at the speaker's actual position, to living listeners within distance two. Tree speech shares the one-utterance-per-character-per-tick limit; a repeatedly speaking tree can delay queued speech until expiry. Cancellation is audited. Hearing creates a perception, never automatic belief agreement.

Learning cites retained own experience source IDs at or before the supplied cursor. Eligible sources are perceptions, skill results/progress, interruptions and speech cancellation. No other character's source is accepted; trust needs a perceived counterpart, beliefs concern known locations, and older evidence cannot overwrite a newer subjective belief. Each source can be interpreted once while retained. At most eight reflections apply together with bounded deltas. Conclusions may be wrong: provenance is validated without substituting observer truth. Learning revision changes independently from policy revision, including authoritative identity changes after damage.

Experiences are subjective and cursored, capped at 256; own parent links are filtered to retained own sources. `oldest_cursor`, `next_cursor`, `latest_cursor` and `gap` make retention loss explicit. Runtimes should retain their own longer memory and advance using `next_cursor`. The full operator audit remains durable but is not participant-readable. Reconnect with the same session restores the same scope. The latest 64 receipts support exact-id/content retries; changed content under an existing ID is rejected. Idempotency is bounded to that receipt window: do not retry an older uncertain command blindly. A future durable request ledger is needed for unbounded offline retries.

## Built-in harness

Explicit `NPC_REASONING_CONFIG=/absolute/provider.json cargo run -p bridge --bin sao-dev-client` enables the built-in harness instead of its fixture. It uses the existing provider adapter, requires `max_attempts=1`, and does not silently repair or retry generated proposals. Behavior, communication and learning have separate loops and may each return zero operations. Default intervals are 15, 21 and 27 seconds, configurable by `SAO_BEHAVIOR_MS`, `SAO_COMMUNICATION_MS` and `SAO_LEARNING_MS` (minimum one second). Those schedules belong to this harness, not the game. All three loops receive only the same character's participant view.

Journals retain redacted requests, reported explanations, replies and receipts under the run's reasoning directory. They are development audit artifacts, not private chain of thought or a production long-term memory implementation. The external runtime can implement its own memory and scheduling without changing authority code. The old `sao-sim` runner remains an archive/legacy experiment path; legacy `sim_intent` and `sim_model_result` cannot mutate a participant-mode run.

## Verification and limits

[Executed verification](PARTICIPANT_AGENT_VERIFICATION.md) records the 64 passing regressions, final real-database probe and actual browser events.

`cargo test -p simulation -p bridge` covers policy, learning, speech, ownership epochs, cursor gaps and provider/archive regressions. `cargo run -p bridge --example participant_authority_probe` uses an isolated real SpacetimeDB run and separate authenticated internal/external/stranger sessions. It invokes the actual MCP process, verifies scoped observations and denied owner/private-table access, compares movement/speech/learning effects, tests stale patch and foreign-source rejection, and removes grants. One built-in learning call uses a deliberately delayed **local mocked provider** while the real authority advances three movement ticks. It is evidence of asynchronous API parity, not model intelligence.

No fresh real-model inference was performed for this iteration. Successful fresh generated adaptive behavior remains unverified; prior Qwen/Luna results keep their original labels and archives. Stdio was verified locally, not every MCP client or remote deployment. Enrollment is a loopback developer broker, not production authentication. Browser input remains the bounded desktop Bevy client. ACP, public provisioning, production scheduling, richer long-term memory and broad autonomous social behavior remain outside this slice.
