# ADR 009: Simulation-specific NPC reasoning with typed provider adapters

Status: accepted, implemented 2026-09-04. Builds on [ADR 008](008-m1-authoritative-survival-slice.md).

The M1 runner embedded Ollama HTTP payload construction and result extraction. Replacing the model backend required editing the world-driving executable, while provider capabilities, deadlines, usage and actual served identity were not explicit contracts.

Introduce a Rust NPC reasoning service and a small typed Ollama/OpenRouter transport boundary in the existing bridge crate. Keep the simulation authoritative and send only each pending request's subjective snapshot. Derive the structured proposal schema from authoritative types; retain the eight-action sequence as a separately versioned execution constraint. No ACP, MCP, general agent framework, or world-effect tool calling is introduced.

Require explicit OpenRouter model/provider routing with fallback disabled, mandatory schema output, preflight capability checks, and simulation-side validation. Preserve provider-specific supported settings through typed options rather than arbitrary request merging. Default to one attempt; allow one bounded retry for definite transient rejection. Record unknown usage as unknown and distinguish configured from actually served identity.

Journal requests and attempts before dispatch. Retain normal evidence in database model-result events and a complete per-request local journal; reference the journal when the CLI audit envelope would be too large. Cancel local waits when requests become invalid, without claiming remote cancellation or zero cost. Keep old archives loadable without initializing a backend.

The implementation and operational limits are in [NPC reasoning](../NPC_REASONING.md); executed evidence and the missing live OpenRouter check are in [verification](../NPC_REASONING_VERIFICATION.md). The legacy gameplay bridge remains outside this refactor.
