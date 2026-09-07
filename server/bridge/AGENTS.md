# Agent and bridge guidance

Follow the [root guidance](../../AGENTS.md), including the mandatory official SpacetimeDB documentation check for client subscriptions, procedures and other database integration. Read the [participant runtime guide](../../docs/PARTICIPANT_AGENTS.md), [external worker contract](../../docs/EXTERNAL_WORKER.md) and [audit contract](../../docs/AUDIT_AND_EXPERIMENTS.md).

## Active source map

| Source | Responsibility |
| --- | --- |
| [participant.rs](src/participant.rs) | Scoped database connection, observations and command receipts |
| [agent_harness.rs](src/agent_harness.rs) | Agent responsibility execution |
| [sao-agent-mcp.rs](src/bin/sao-agent-mcp.rs) | External participant MCP service |
| [participant_live_agent](examples/participant_live_agent.rs) and [worker modules](examples/participant_live_agent/) | Native model controller and persistent external transport |
| [sao-dev-client.rs](src/bin/sao-dev-client.rs) | Foundation development host, enrollment and exports |
| [sao-sim.rs](src/bin/sao-sim.rs) | Isolated headless authority runs and retained inspection |
| [reasoning](src/reasoning/mod.rs) | Provider configuration, inference and response handling |
| [owner_snapshot.rs](src/owner_snapshot.rs) | Owner export mode and wire-result parsing |

`src/main.rs`, `llm.rs`, `prompt.rs` and `tools.rs` retain the older `NpcPendingDecision` bridge. `cargo run -p bridge` selects that legacy executable; use the specific active binary/runbook for foundation work. Its old template fallbacks and serial queue are not requirements for the participant runtime.

## Data and model boundaries

Build context from authorized perceptions, personal state and legitimate learned records. No full observer World, other minds or unrestricted audit history in model prompts. Speech and model assertions do not become physical effects without authority acceptance.

Keep inference asynchronous and outside authoritative reducers. Support persistent connections and incremental scoped subscriptions; do not reconstruct/export the World to obtain ordinary local updates. Advance the SDK connection using the mode appropriate to the host and wait for initial subscription application. Check the actual SDK API rather than assuming all client I/O is blocking.

Preserve request IDs, controller/revision checks and exactly correlated receipts. A timeout can have an unknown delivery outcome; do not blindly replay it. HTTP 200, valid JSON, an accepted operation and an executed physical effect are different evidence.

The external worker's modes, deadline boundaries and cancellation contract are documented in [EXTERNAL_WORKER.md](../../docs/EXTERNAL_WORKER.md). Persistent transport, eight-slot external RPC admission, procedure exports and stopped-host finalization were explicit conditions of the passing finite trial, not universal defaults. Admission does not limit model inference concurrency. Stopped-host finalization currently targets fixed populations; preserve dynamic enrollment guarantees when extending it.

## Experiments and recovery

Retain actual prompts, outputs, provider configuration, versions, attempt records and concise reported explanations. Never claim hidden chain-of-thought. Isolate runs and output paths; use the real authority for effects. No automatic retries, model substitutions or deadline extensions that silently change a declared experiment.

Own worker/child process lifetimes and verify cancellation, disconnect, pause, revocation and coherent final capture. Distinguish pilot cleanup from database-service shutdown. Test the real connection lifecycle, export load and long-lived subscriptions used by the intended workload; a fixture with persistent clients cannot certify a workload that recreates subscriptions per request.

Model profiles and environment-supplied credentials are configured per run. Keep secrets out of source and evidence outputs. The [browser runbook](../../docs/BEVY_BROWSER_CLIENT.md) and [experiment guide](../../docs/EXPERIMENT_SCALING.md) define setup and orchestration; do not infer destinations from legacy constants.
