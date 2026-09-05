# ADR 013 — Participant agent runtimes

Status: implemented, 2026-09-05. Supersedes game-owned reasoning dispatch for new `m1-5` participant runs; preserves earlier run formats and evidence.

External players bring full runtimes with their own model access, memory and scheduling. A model endpoint alone is not an agent integration. The built-in NPC controller must prove the same authority boundary that an external runtime uses.

We introduce transport-independent `sao-participant-v1`, authenticated per-character observations and commands. The principal behavior operations are versioned whole-tree replacement and atomic subtree patching. Speech and subjective learning are independent commands. The authority executes skills and persistent trees, validates capability/provenance/concurrency, and emits bounded subjective experiences. It neither schedules model calls nor invents decisions for disconnected participants.

The built-in harness and thin official-SDK MCP stdio adapter both use `ParticipantService`. New participant runs reject old owner model-result/intent mutation routes. Operators retain scenario creation, enrollment, time controls and archives as development capabilities separate from the participant interface. Human Bevy controls retain finite action convenience through the same skill validation and executor.

Policy revisions, learning revisions and control epochs are distinct. Patching retains unaffected progress; replacing an active subtree interrupts it. Ownership changes invalidate slow proposals while installed fast behavior continues. Independent queued speech uses actual delivery-time position and bounded expiry. Reflection validates own evidence but allows mistaken conclusions. Cursor gaps and the bounded receipt window are explicit rather than implying unlimited memory or exactly-once delivery forever.

MCP 2026-07-28 with official Rust SDK 3.2.0 was selected after checking current official documentation and exercising real protocol calls. ACP is not required for this participant boundary. Full runtime scheduling remains the connecting client's responsibility.

The [runbook](../PARTICIPANT_AGENTS.md) specifies semantics, launch instructions, verification and limits. Real authority/MCP and delayed mocked-provider checks establish integration parity; they do not establish intelligent model behavior. Production authentication, unbounded durable idempotency and persistent agent memory need later work.
