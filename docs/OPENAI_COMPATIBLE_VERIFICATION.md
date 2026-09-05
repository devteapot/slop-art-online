# Generic Chat Completions verification — 2026-09-05

The generic endpoint adapter is implemented in [backend.rs](../server/bridge/src/reasoning/backend.rs) and exercised by [contract tests](../server/bridge/src/reasoning/tests.rs) plus real local inference. This extends the [original provider verification](NPC_REASONING_VERIFICATION.md). No paid or externally authenticated inference was performed. Bearer authentication was verified against a local HTTP mock; live verification used explicit no-auth mode.

## Tests and build

`cargo test -p bridge -p simulation --lib --bins` passed **32 tests**: 17 reasoning/provider tests, one old-manifest compatibility test and 14 authoritative simulation tests. `cargo build -p bridge --bin sao-sim`, targeted Rust formatting checks and `git diff --check` passed. Existing legacy warnings remain. This extension changes no authoritative simulation, reducer signatures, table schemas or generated bindings, so it uses the existing verified module binary.

The five added grouped tests cover root and prefixed API bases, trailing slash normalization, exact `/chat/completions` request paths, bearer environment lookup and redaction, missing credentials, explicit absence of Authorization, both token-limit keys, all three response modes, optional temperature/seed declarations, invalid URLs and undeclared settings. Generic preflight makes no catalog request; generic payloads contain no OpenRouter routing/reasoning or native Ollama fields. HTTP mode rejection, malformed provider/decision JSON and refusal preserve errors without downgrading or retrying. Every response mode also submits an oversized action sequence through the real authority and verifies semantic rejection. Existing OpenRouter routing/capability and native Ollama tests continue passing; their config examples remain valid.

## Live check

With the isolated SpacetimeDB 2.0.1 service and existing Ollama installation running:

```bash
NPC_REASONING_CONFIG=configs/reasoning/openai-compatible-local.json SIM_TICK_MS=2000 \
  target/debug/sao-sim run output/compatible-scenario.json output/compatible-live configured 18878
```

The scenario is a 12-tick copy of the existing survival scenario. The [manifest](../output/compatible-live/manifest.json) records run `sim-1788563844141-12894`, `npc-reasoning-v2`, unchanged `survivor-sequence-v1` and `m1-3`. The actual route is `http://127.0.0.1:11434/v1/chat/completions`, using real `qwen2.5:7b`, no Authorization header and strict JSON Schema output. This follows [Ollama's compatibility API](https://docs.ollama.com/api/openai-compatibility), rather than its native `/api/chat` endpoint.

The database advanced 12 ticks and retained **200 events**. Four requests produced three parsed proposals and one cancelled local wait. The authority accepted two proposals at decisions **78** and **111**. The third proposal was recorded after run-stop invalidation and rejected at **198**; the cancelled request's result was likewise retained and rejected at **200**. The model continued to make imperfect judgments, including a proposed reflection discounting perceived danger. This verifies transport, cancellation and authority separation, not reasoning quality.

For all four exchanges, the supplied user message exactly equals the authority's frozen subjective context, the three journal phases are present, and the journal API matches the saved bytes. Three complete replies report the actual model and prompt/completion token usage; unavailable provider identity and cost stay unknown. The cancelled reply's usage stays null. The saved [catalog](../output/compatible-live/model-catalog.json) explicitly identifies operator declarations and unverified remote capabilities. Only `json_schema` was exercised with live inference; JSON-object and prompt-only modes were exercised by mock HTTP and authority tests.

The runner SHA-256 is `d63392344ded3455f08411cc2b88363d239e0fac568ff97940e76804c75187ba`; the unchanged module SHA-256 is `8b2c96c052a90aa102625d99c9b30b037b02860dd36b57234c85726980424c8b`. The [machine-readable checks](../output/compatible-verification.json) retain exact exchange IDs, authority outcomes and usage. The updated binary loaded all three old/new archives into [comparison output](../output/compatible-comparison.json), and each archive inspector's snapshot matched its saved artifact.

## Review and limits

The [new archive inspector](http://127.0.0.1:18878) is read-only. The earlier [M1 proof](http://127.0.0.1:18877) and [native backend proof](http://127.0.0.1:18880) remain available and unchanged. The previously stopped local services were restarted using the same data directory; no ordinary database was reset. No simulation is advancing.

This historical check covered the documented non-streaming text Chat Completions subset with explicit capabilities; it does not establish support for every vendor, model, authentication scheme or server implementation. Generic preflight does not verify remote support. OpenRouter live inference remains unverified without a credential; its specialized adapter still provides routing restrictions and capability checks. See [configuration and modes](NPC_REASONING.md) for the exact supported surface.

All work remains uncommitted. Nothing was pushed, merged or deployed. Preserve complete ignored `output/` directories, including their reasoning journals, when retaining this evidence.

Subsequent opt-in SSE and explicit unsupported-cap support are verified in [Carlid streaming integration](CARLID_STREAMING_VERIFICATION.md), including fragmented streams, incomplete-output rejection and bounded capture/parsing. Older archives remain unchanged.
