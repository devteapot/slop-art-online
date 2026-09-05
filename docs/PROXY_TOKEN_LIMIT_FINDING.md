# Read-only proxy token-limit finding — 2026-09-05

Inspected `/Users/carlid/dev/codex-cursor-proxy`, local Git HEAD `4666288af2e34f7c7302ca9565c82d24830f5bd9`. No applicable `AGENTS.md` was found at that repository or its parent paths. No proxy file, process, deployment or credential store was changed. This establishes the behavior of the inspected source; the revision deployed at `codex.carlid.dev` was not independently attested.

The source explains why requesting `max_completion_tokens: 1200` did not constrain the first run's reported 1,264–1,511 completion tokens:

- [server.js:162](/Users/carlid/dev/codex-cursor-proxy/src/server.js:162) calls `chatToResponsesRequest`, then creates an upstream Responses request; non-streaming Chat Completions collects its SSE before returning a completion at lines 166–172.
- [translate.js:97](/Users/carlid/dev/codex-cursor-proxy/src/translate.js:97) constructs an explicit field set. It does not map `max_completion_tokens`, `max_tokens`, or `max_output_tokens` into the upstream request.
- [translate.js:243](/Users/carlid/dev/codex-cursor-proxy/src/translate.js:243) applies another allowlist in `normalizeResponsesRequest`; it also omits output-limit fields. [upstream.js:62](/Users/carlid/dev/codex-cursor-proxy/src/upstream.js:62) sends that normalized body to `responses`.
- [translate.js:119](/Users/carlid/dev/codex-cursor-proxy/src/translate.js:119) maps upstream `usage.output_tokens` into `completion_tokens`. It does not count the returned decision text itself, and it omits upstream usage detail beyond its three aggregate fields. Missing individual counts within a supplied usage object default to zero in this proxy, so these are provider/proxy-reported values rather than independently measured quantities.

A synthetic local call to the exported translation functions confirmed that none of the three token-limit fields survived normalization. Feeding a synthetic upstream output-token count of 1,511 returned `completion_tokens: 1511`. No network or model call was made for this check.

The translator also defaults to reasoning effort `high` unless supplied/overridden, forces upstream streaming, and asks for automatic reasoning summary/encrypted content. That can matter for interpretation of latency/usage, but this inspection does not prove it caused the observed latency, and actual deployment configuration remains unverified. The generic simulation adapter does not send a reasoning-effort override or expose private reasoning as an execution explanation.

The new reactive-policy config requests 6,000 tokens to express a larger contract on endpoints that honor the setting. In this inspected proxy source the request remains uncapped by that field. No proxy patch or additional paid cap probe was necessary for the bounded behavior-tree experiment.

The authorized slower reactive-policy experiment subsequently observed HTTP 524 with plain-text `error code: 524` after approximately 125.2 seconds. That establishes an upstream failure before the 240-second client deadline; it does not independently identify the deployed gateway revision. Non-streaming buffering is consistent with the failure. See [the experiment report](REACTIVE_POLICY_VERIFICATION.md) for exact evidence and the local error-classification fix.

## Subsequent coordinated repair

The findings above describe the inspected historical revision and remain unchanged as evidence. In a later explicitly authorized proxy-owning task, the owner confirmed a direct upstream `max_output_tokens` probe returns unsupported-parameter 400, added explicit Chat token-alias rejection, and repaired immediate SSE headers plus keepalive comments. The owner reported public streaming readiness and unconditional terminal usage. SAO now opts into streaming and explicit unsupported-cap mode; see [current integration verification](CARLID_STREAMING_VERIFICATION.md). SAO did not modify/restart the proxy. This update must not be read as rewriting the old deployed revision or the older run manifests.
