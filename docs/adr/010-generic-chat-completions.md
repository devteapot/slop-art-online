# ADR 010: Explicit generic Chat Completions transport

Accepted and implemented 2026-09-05; extends [ADR 009](009-pluggable-npc-reasoning.md).

An OpenAI-compatible endpoint should not require OpenRouter catalogs, provider slugs or routing fields. Add a separate typed adapter with a complete API base prefix, model ID, explicit bearer-environment or no-auth choice, and operator-declared capabilities. Preserve native Ollama and specialized OpenRouter adapters.

Select strict JSON Schema, JSON-object, or prompt-only JSON explicitly. Reject undeclared options and preserve endpoint errors without silently downgrading. Token-limit field selection is explicit because compatible servers differ. Generic preflight validates declarations without claiming remote discovery. All modes retain simulation-specific prompts, subjective context, typed proposals, authoritative validation, asynchronous execution and correlated evidence.

This supports a bounded Chat Completions subset, not universal vendor compatibility. Authentication variants, streaming, tool calling, Responses API, vendor passthrough and remote schema discovery remain outside scope. OpenRouter route restrictions remain available through its specialized adapter.

See [configuration](../NPC_REASONING.md) and [executed verification](../OPENAI_COMPATIBLE_VERIFICATION.md).
