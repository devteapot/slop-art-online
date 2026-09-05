# Carlid streaming integration verification — 2026-09-05

**The repaired public Luna connection completed end to end through the actual SAO adapter and real authority.** The returned policy was rejected unchanged for 11 root branches (maximum 8), so this is transport success, not successful policy execution. The generic adapter supports opt-in streaming and explicit unsupported token caps. Existing non-streaming, native Ollama and specialized OpenRouter behavior remains supported. The authoritative policy contract/runtime is unchanged. All earlier uncommitted policy work, native-client gap documentation and archives are preserved.

## Local checks

[Final regression output](../output/streaming-capture-final-tests.txt): **54 tests pass** (28 reasoning/provider, 25 core, one archive). Native runner/probe and WASM builds pass. Nine added SSE suites cover explicit uncapped versus legacy numeric/default behavior; byte-fragmented UTF-8/CR/LF/multiline SSE; comments and repeated usage snapshots; complete JSON without DONE; error frames/refusal/length/malformed output; cancellation and heartbeat-independent absolute deadlines; abrupt disconnect; invalid UTF-8/128 KiB truncation; pre-stream HTTP rejection; credential material split across content deltas; successful modest-policy parsing beyond the raw capture prefix; and a bounded heartbeat flood. No network model requests are made by these tests. A synthetic launcher check confirms probe argument selection and environment-only credential transport.

The reader preserves partial response evidence across cancellation/deadline. Raw stream records and stream timing/counts live in attempt-finished journal records, linked from completion metadata. The final streaming reader retains a labeled 128 KiB raw prefix while continuing to parse, bounded separately by 4 MiB total wire, 128 KiB per SSE event and 50,000 bytes of generated content. Non-streaming total-body limits remain unchanged; usage snapshots are not summed and unavailable counts/cost are not invented. Token cap omission requires both unsupported capability and explicit null. No model/effort downgrade or semantic retry is introduced.

## One authorized hosted proof

The proxy owner confirmed repair/restart and public readiness before this check. One initial launch stopped at local database connection refusal before any hosted request; the existing isolated SpacetimeDB 2.0.1 service was restarted with its retained `/tmp/sao-m1-spacetimedb-b0b2` data directory. No ordinary database reset or proxy modification occurred.

The [proof script](../scripts/verify_hosted_generated_policy.py) creates a fresh run from the survival scenario with one AI/two human characters, one food at starting site and 30 ticks. It freezes the authoritative tick-1 subjective pending context for one hosted stream, submits the returned result unchanged, then executes 29 real reducer steps with no further model calls. This explicitly decouples model wall time from logical time; it is not a real-time concurrency benchmark.

[Archive manifest](../output/carlid-luna-streaming-proof/manifest.json), [machine verification](../output/carlid-luna-streaming-proof/verification.json), [generation envelope](../output/carlid-luna-streaming-proof/generation.json), [complete retained journal](../output/carlid-luna-streaming-proof/reasoning/request-19.jsonl), [read-only developer inspector](http://127.0.0.1:18888).

Run **sim-hosted-stream-1788590824278393000** made exactly one HTTP generation attempt. Requested and reported model: **gpt-5.6-luna**. The actual wire request used `stream: true`, no token-cap aliases, no reasoning-effort override and no `stream_options` flag. Configuration: explicit unsupported/no cap, one attempt, 240-second overall deadline; frozen tick 1 during inference.

- HTTP **200**, response headers and first bytes after **1,070 ms**.
- Retained **10 comment lines**, **588 data events**, and **131,072 raw stream bytes**. Keepalives allowed the request to continue beyond the earlier approximately 125-second 524 boundary.
- At **148,069 ms**, the already-dispatched reader stopped at its then-current hard 128 KiB body limit. It had assembled only **2,786 characters** of partial model text. No finish reason, terminal DONE or usage snapshot had arrived. Cost and token usage are unknown.
- Authority model result **27** was rejected at event **28** as `reasoning failed; no proposal returned`. No policy/reflection was installed. The final run has **30 ticks/276 events**; subsequent steps used existing bootstrap, with no additional model generation. No generated branching or policy quality can be inferred.

The raw framing-budget problem was raised during this dispatched request. Its executable was left unchanged; [dispatched binary hashes](../output/carlid-luna-streaming-proof/dispatched-binaries.json) and manifest retain that identity. The subsequent correction separates capture from parsing: a 128 KiB prefix may be truncated with successful continued parsing up to 4 MiB total wire, while model output remains limited to 50,000 bytes. A real HTTP mock deliberately sends one-character content chunks whose envelopes exceed 128 KiB and proves the original valid policy still completes through DONE. A separate flood test proves the total-wire limit. **That correction was locally verified after this request was dispatched. The separately authorized corrected-build check below provides its live evidence.**

This live evidence establishes usable public streaming headers, content and keepalives beyond the former gateway timeout, not end-to-end completed Luna policy delivery. The later corrected-build check below closes the completed-stream integration gap. The previous hard capture stop was a SAO consumer limit, not a proxy 524 or bad model JSON. No retry, generated-output edit, downgrade or hidden usage estimate occurred.

Frozen-context equality, actual wire request fields, full retained journal/API byte equality, snapshot/API equality and ordered causal references all pass. The inspector is read-only and no inference/simulation is advancing.

Final native runner SHA-256: `32c33ccc8c8a1be94c099bf2cd5cd775d62d388f6610234182895bdf6fa3c705`; final hosted probe: `d55bab6d6229f5737c93eed07407eda8db5997d5b3ed58ac7df9f5f52c1b4d1f`; unchanged authoritative WASM: `a4a6ff9ef8d92e8c87fe62b6db99f7da4d5253cbb901e290bc859e7bf272ce68`. All edits remain uncommitted; no SAO push/merge or proxy changes occurred.

## Corrected-build validation

After the reproduced framing-budget defect was fixed and all 54 tests passed, the originating task explicitly authorized one further check. It uses a fresh archive, the same endpoint/model/prompt contract and unedited output, no semantic feedback or effort override, one attempt and the validated 300-second overall deadline. The final prefix/wire/content separation is active. This is a defect-validation experiment, not an automatic or hidden retry of the earlier run. The first archive remains unchanged.

[Corrected archive manifest](../output/carlid-luna-streaming-corrected-proof/manifest.json), [verification](../output/carlid-luna-streaming-corrected-proof/verification.json), [full generated output](../output/carlid-luna-streaming-corrected-proof/generation.json), [retained exchange journal](../output/carlid-luna-streaming-corrected-proof/reasoning/request-19.jsonl), [read-only developer inspector](http://127.0.0.1:18889), [cross-run comparison](../output/carlid-streaming-comparison.json).

Run **sim-hosted-stream-1788591171425289000** completed its one generation:

| Observation | Recorded result |
|---|---|
| Requested / reported model | `gpt-5.6-luna` / `gpt-5.6-luna` |
| HTTP / first headers and bytes | 200 / 1,434 ms |
| Complete generation elapsed | 144,306 ms, within 300-second absolute deadline |
| Stream completion | `finish_reason: stop`; terminal `[DONE]` received; no provider/transport error |
| SSE activity | 10 comment lines; 1,169 data events, including DONE |
| Wire / capture | 259,236 bytes parsed; 131,072-byte prefix retained, explicitly labeled truncated |
| Complete model output | 4,743 bytes, preserved and submitted unchanged |
| Reported usage | 2,434 prompt + 7,904 completion = 10,338 total; completion includes 6,732 reasoning tokens |
| Cache / cost | Reported cached and cache-write tokens 0; monetary cost not reported |
| Authority result | Model result 27; rejection event 29: `composite needs 1..8 children` |
| Runtime outcome | Root priority contains 11 branches; no policy/reflection installed; 30 ticks / 277 events |

The model's explanation describes eating, conserving energy, speaking to Tovan, cautious travel, confirmed-food gathering and danger-driven retreat. Those are **reported intentions only**. The root violates the existing authoritative width bound, so none of that generated policy executed. No tree was trimmed/rearranged, no rule was relaxed, and no further generation or semantic-feedback attempt followed. The remaining model-quality/contract-compliance issue is distinct from the repaired transport.

The generated output is complete even though raw SSE capture is intentionally a prefix. The parser continued past that prefix, recorded stop/DONE and the final reported usage snapshot without adding repeated counts. The journal explicitly exposes both total wire and captured byte counts. All request fields, frozen-context equality, no-feedback/no-effort-override/no-token-cap assertions, unedited raw-output equality, journal/API bytes, snapshot/API data and causal references pass. The [actual corrected executable hashes](../output/carlid-luna-streaming-corrected-proof/dispatched-binaries.json) match the manifest. This was one generation in a fresh run; the earlier failed framing-limit request remains separate and unchanged. All inference is stopped.


## Product boundary

Native Bevy development mode is the primary planned visual observer/participant interface. Development and release modes should share rendering/input/data contracts, with extra development panels and server-enforced observer privileges; headless experiment/API tools support parallel runs and agent debugging. The external browser inspector remains developer audit tooling. No Bevy UI work was started in this transport repair; the integration gap was subsequently addressed by the [browser-hosted Bevy slice](BEVY_BROWSER_CLIENT.md); this transport report retains its historical scope.
