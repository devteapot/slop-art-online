# NPC reasoning backends

Latest live evidence: [mixed internal/external agent verification](LIVE_MIXED_AGENT_VERIFICATION.md) records ten genuine Luna calls, accepted behavior/dialogue/learning through both routes, preserved failures and corrections, and 66 passing regressions. Earlier no-fresh-inference statements below describe the preceding implementation milestone.

Current participant iteration: [participant agent runtimes](PARTICIPANT_AGENTS.md) and [ADR 013](adr/013-participant-agent-runtimes.md). Rules `m1-5` use one scoped API for the built-in harness and external MCP runtimes, with independent tree, speech and learning operations. Earlier evidence and legacy runner descriptions below retain their historical scope.

M1 now separates the simulation's NPC reasoning contract from provider transport. This applies to `sao-sim` and the foundation reducers. The legacy `bridge`/Bevy path remains Ollama-specific and has not been migrated. Nothing here changes a character's in-world intelligence or personality when choosing a model.

## Ownership

- [Simulation](../simulation/src/lib.rs): identity, perceptions and subjective memory, skills, behavior execution, death, generation/tick validity, and validation of proposed effects. Pending requests contain immutable permitted context. Observer truth is not added to it.
- [Reasoning service](../server/bridge/src/reasoning/mod.rs): assembles actual messages from that context and the simulation contract, parses typed proposals, correlates requests, applies wall-time deadlines/retry policy/cancellation, and journals evidence. The authority remains responsible for accepting and executing proposals.
- [Backend adapters](../server/bridge/src/reasoning/backend.rs): typed native Ollama, OpenRouter, and generic Chat Completions configuration, authentication, capability checks, HTTP payloads, response/error parsing, and returned provider/usage metadata. This module imports no simulation action types.

Current model output is `survivor-policy-v2`: a persistent reactive tree chosen by the LLM, with up to 64 combined nodes/conditions and depth eight. See [reactive policy semantics](REACTIVE_POLICIES.md). The older `survivor-sequence-v1` authority input remains available with at most eight actions; it is not the current generated format. The [schema](../simulation/src/contract.rs) is derived from authoritative `PolicyProposal`, node, condition, action and reflection types. Strict normalization uses nullable optional arguments and required fields; Chat Completions adapters remove nonstandard integer format annotations while preserving bounds. Semantic validation remains authoritative. Schemars is native-only and excluded from WASM.

## Run configuration

Start the isolated SpacetimeDB server and Ollama as described in the [M1 runbook](M1_RUNBOOK.md), then build:

```bash
just sim-build
just sim-run-config scenarios/survival.json output/local-next configs/reasoning/ollama.json 18878
```

The original positional local-model command remains valid. Alternatively set `NPC_REASONING_CONFIG` to a JSON path and pass `configured` in the positional model slot. Conflicting positional model overrides are rejected.

For OpenRouter, set `OPENROUTER_API_KEY` in the launching process environment using your normal secret-management workflow. Do not put it in JSON, commit it, or paste it into chat. Then:

```bash
just sim-run-config scenarios/survival.json output/remote-next configs/reasoning/openrouter.json 18878
```

The [OpenRouter example](../configs/reasoning/openrouter.json) explicitly requests `openai/gpt-4.1-mini` through the `openai` provider slug. Edit both for your experiment. This slug is not a claim that the underlying deployment can never change: retain returned model/provider identity and endpoint metadata. Credentials are referenced by `credential_env`, never stored in the manifest. The adapter sends credentials only to the fixed HTTPS OpenRouter API origin, with redirects disabled. The [Ollama example](../configs/reasoning/ollama.json) uses a local, credential-free HTTP origin.

Each output directory must be new. A missing credential fails before publishing or creating the run output. Capability preflight runs before publishing; its result and catalog are retained when an output directory has been created. OpenRouter authenticated inference remains unverified. Separately authorized hosted Luna experiments are documented in their run reports.

## Generic OpenAI-compatible endpoints

Use `backend.kind: "openai_compatible"` for an endpoint implementing text Chat Completions. Non-streaming remains the default; optional `backend.stream: true` selects SSE. The [local example](../configs/reasoning/openai-compatible-local.json) calls Ollama through its compatibility API:

```bash
just sim-run-config scenarios/survival.json output/compatible-next configs/reasoning/openai-compatible-local.json 18878
```

For a hosted server or gateway, copy the [bearer-auth example](../configs/reasoning/openai-compatible.json), replace its placeholder model/base URL, and set the named `NPC_LLM_API_KEY` environment variable in the launching process. `auth` is required: `{"kind":"bearer_env","credential_env":"NPC_LLM_API_KEY"}` sends a bearer credential, while `{"kind":"none"}` deliberately sends no Authorization header. Missing/empty referenced credentials fail before publishing. Redirects are disabled and credential values are excluded/redacted from saved evidence.

`base_url` is the complete API prefix, without `/chat/completions`. A base `https://host/tenant/api/v1/` becomes `https://host/tenant/api/v1/chat/completions`; a root base becomes `/chat/completions`. Both HTTP and HTTPS are supported. Embedded credentials, query strings, fragments, and a full completion endpoint are rejected. No model/provider naming convention is required.

The required `capabilities` object declares the endpoint's supported `response_modes` and its output-token key (`token_limit_field: "max_tokens"` or `"max_completion_tokens"`). An endpoint that cannot enforce either may explicitly declare `"unsupported"` only with `max_output_tokens: null`; neither omission alone nor a conflicting numeric cap silently disables limits. Optional `temperature` and `seed` support default to false; requesting either without declaring support fails validation. This is **operator configuration, not remote capability discovery**. The generic adapter does not fetch a catalog or require OpenRouter parameters. Its saved `model-catalog.json` marks `capability_source: "operator_configuration"` and `remote_capabilities_verified: false`; a successful preflight establishes configuration validity only. An endpoint that contradicts these declarations produces a recorded error during generation.

| Selected `structured_output` | HTTP request | Guarantee before simulation validation |
|---|---|---|
| `json_schema` | Strict `response_format` with the derived schema | Endpoint is asked to enforce the schema. |
| `json_object` | `response_format: {"type":"json_object"}` | Endpoint is asked for JSON; shape still needs local parsing. |
| `prompt_json` | No `response_format` | JSON is requested only in the simulation prompt. |

The selected mode must appear in `capabilities.response_modes`. Every mode receives the same simulation instructions, derived schema, and frozen subjective context, then passes through typed proposal parsing and authoritative semantic validation. There is no automatic mode downgrade, response repair, model switch, or tool execution. An unsupported schema response stays an explicit failed attempt.

The supported surface is text-message Chat Completions, non-streaming by default or opt-in SSE, with the typed options above. Responses API, tool calls, arbitrary vendor parameters, query-based API versions and custom authentication headers are outside it. Generic usage of a gateway does not apply OpenRouter's specialized route locks or catalog checks; choose the `openrouter` adapter when those controls are needed. Returned model/provider/usage fields are retained when supplied and otherwise remain unknown. Compatibility differs between servers; see the [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat) and [Ollama's supported subset](https://docs.ollama.com/api/openai-compatibility).

Endpoint-specific setup: [Carlid / GPT Luna local credential workflow](CARLID_ENDPOINT_SETUP.md). The [first authenticated run report](CARLID_LUNA_FIRST_RUN.md) records observed behavior and remaining limits.

## Capabilities and options

OpenRouter always receives one model, an explicit provider `only`/`order`, `allow_fallbacks: false`, `require_parameters: true`, and strict JSON-schema `response_format`. There is no automatic provider/model switch. The adapter conservatively checks every endpoint selected by the provider slug for advertised structured-output and requested parameter support; choose a narrower endpoint slug if necessary. Unsupported or unknown settings are rejected rather than omitted. These controls follow [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection) and [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs); provider-side schema claims do not replace simulation validation.

Common options are `deadline_ms` (default 90000), `max_attempts` (default 1, maximum 2), `retry_backoff_ms` (default 500), `max_output_tokens` (default 6000 for the policy contract, numeric range 1..8192; explicit null only for a generic endpoint declaring unsupported token caps), optional `temperature`, and optional `seed`. When using an explicit config, an omitted seed is not sent; the scenario seed is still recorded separately. Positional Ollama runs preserve the previous temperature 0.6 and scenario-seed defaults. Neither mode promises deterministic fresh model calls.

Ollama preserves `num_ctx` and `keep_alive`, sends the derived schema in `format`, and records available prompt/completion/cache token counts and duration. See the [Ollama chat API](https://docs.ollama.com/api/chat).

OpenRouter additionally supports a `reasoning` object under `backend`, either `{"mode":"effort","effort":"low"}` or `{"mode":"tokens","max_tokens":512}`. The endpoint must advertise reasoning support, and the model's capability declaration must support the selected effort or token-budget mode. Missing evidence is an explicit rejection. A token budget must be smaller than the overall output limit. The request uses `exclude: true`; reported decision explanations remain distinct from private reasoning and verified execution. See [reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens). Explicit cache directives and arbitrary provider pass-through parameters are outside this bounded adapter; returned cache usage and automatic provider caching evidence are retained where supplied.

## Time, retries, and cancellation

The runner advances the real database while HTTP requests are pending. A request has one overall wall-time deadline spanning attempts and backoff. The separate simulation expiry remains 30 logical ticks, plus policy-generation/death/controller/run-stop validity. Damage alone preserves the installed policy and pending request; current guard/effect checks and newer-evidence protection apply. When the authority no longer considers a request current, the runner cancels the local HTTP wait. Late results still pass through the authority's stale-result checks against the exact supplied request context.

Retries are opt-in and limited to definite transient HTTP 429/503 rejections with parseable provider errors, using the same model/provider/request. Numeric `Retry-After` is honored within the remaining deadline. Ambiguous delivery failures, timeouts, malformed output, refusals, truncated output and semantic rejections are not automatically retried. Dropping an HTTP wait does not guarantee the provider stops processing or charging. Unreturned usage/cost stays unknown; it is never recorded as zero.

## Evidence and archive compatibility

New manifests retain resolved backend settings, reasoning/decision versions, and executable hashes for both module and runner. Existing manifests without these fields still load. Inspection/export never initializes a model backend or requires a credential. Old M1 records are not rewritten.

Each actual attempt is durably journaled before dispatch in `reasoning/request-ID.jsonl`, followed by its response and completion records. Normal results retain the complete request/config, raw provider response, extracted output, parsed proposal, actual served model/provider if returned, usage/cost if returned, errors, attempt counts and timing in `model_result` metadata. Sensitive credential values are redacted before persistence; a modified response body is labeled. Reported explanations are not proof of causes or successful effects.

The operator's **Full reasoning journal** link, and `/api/reasoning?request=ID`, expose that same correlated evidence. When metadata exceeds 60 KB, the reducer receives a compact summary plus its journal reference to avoid CLI argument-size limits. Retain the whole output directory, not just `snapshot.json`. Provider bodies above 128 KiB are explicitly rejected with a captured prefix and truncation flag. Cancellation/deadline before a complete response can leave raw response and usage unavailable; the attempt and outcome remain recorded. A process crash can leave an `attempt_started` record without completion; there is no automatic crash-recovery retry.

`compare` includes reasoning exchanges linked to event IDs, requested configuration, actual served identity, per-attempt usage and errors. Missing legacy fields remain null. Compare provider runs only after accounting for stochastic output, timing, scenario differences and external inputs.

See the original [provider verification](NPC_REASONING_VERIFICATION.md) and [generic endpoint verification](OPENAI_COMPATIBLE_VERIFICATION.md) for exactly what was tested and what remains unverified.

For a bounded validation experiment, the reasoning API can accept explicit recorded rejection feedback as an additional message. The normal runner supplies none and does not automatically retry semantic rejection. The subjective request stays unchanged, every generation/raw response is retained, and the authority revalidates the proposed policy. See the [local feedback evidence and its behavioral failure](REACTIVE_POLICY_VERIFICATION.md#two-targeted-local-follow-ups-after-contract-correction).

## Streaming completion and evidence

Opt-in generic SSE accepts LF, CRLF or CR line endings and arbitrary HTTP/UTF-8/event boundaries. Multi-line data fields join with newlines; colon comments and non-data SSE fields are ignored by the content parser. Only ordered choice-0 text deltas are assembled. The adapter requires a stop finish reason plus terminal `[DONE]`; it rejects provider error frames, refusal, unsupported finish reasons/content, missing DONE/early EOF, malformed JSON/UTF-8 and size overflow. Complete JSON text without DONE is still a failed transport result. Partial raw text stays in audit evidence but never becomes the submitted decision envelope.

Deadline and cancellation are checked inside the response reader so partial bytes, model identity and available reported usage survive interruption. The absolute deadline is shared by the whole reasoning request and is not extended by keepalives. Once a successful streaming response starts, it cannot be retried automatically, including after partial text or disconnect. Definite HTTP rejections before streaming retain existing backend retry policy; the Carlid config permits exactly one attempt.

The attempt-finished journal retains an exact **128 KiB raw-stream prefix**, subject to credential redaction. Crossing that capture limit sets `body_truncated`/`stream.capture_truncated` but parsing continues; it does not invalidate a complete policy. Separate explicit bounds are **4 MiB total SSE wire bytes**, **128 KiB per SSE event**, and the generated-output ceiling below. Non-streaming responses retain their existing 128 KiB total-body limit. Invalid UTF-8 is a failure and retains a byte-prefix hex representation when redaction permits it. The assembled model-output ceiling remains **50,000 bytes**. SSE framing counts against the separate total-wire limit, not the generated-output limit. `reply.stream` records header/first-byte timing, captured/total wire bytes and capture truncation, data-event/comment-line counts and whether DONE arrived. Full journals remain the evidence source if the reducer's metadata envelope is compacted. Usage is the latest non-null reported cumulative snapshot, never a sum of frames; missing fields are not synthesized. Only reported explanation text is an execution explanation; no private reasoning is inferred from token counts.

The [Carlid integration](CARLID_ENDPOINT_SETUP.md) uses streaming because long buffered completions exceeded gateway limits and explicitly disables the unsupported upstream token cap. This is endpoint-specific configuration, not a capability assumption applied to other services.
