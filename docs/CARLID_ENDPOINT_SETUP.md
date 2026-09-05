# Carlid NPC endpoint: streaming integration

The [first authenticated run](CARLID_LUNA_FIRST_RUN.md) is retained as historical non-streaming evidence. The current configuration uses opt-in streaming and explicitly omits unsupported provider token caps; see [streaming verification](CARLID_STREAMING_VERIFICATION.md). The endpoint returned usable responses reporting `gpt-5.6-luna`; requested token-limit enforcement remains unverified. The requested endpoint is `https://codex.carlid.dev/v1`; the requested model is `gpt-5.6-luna`, based on the supplied Codex model identifier convention. Before setup, the reported unauthenticated `/v1/models` check returned 403. The linked run report distinguishes authenticated findings from remaining protocol assumptions.

## Enter the credential locally

Open [.local/credentials/codex-carlid.json](../.local/credentials/codex-carlid.json) in the Codex editor and replace the empty string in `api_key` with your key, then save. Keep valid JSON. The prepared file is owner-only (0600), its credential directory is 0700, and Git ignores the directory. Do not paste the key into chat or put it in the reasoning config.

The template contains no secret until you fill it. The launcher refuses a missing, malformed, empty, non-owner-only or non-regular credential file and does not print its contents. If an editor changes permissions, restore them with `chmod 600 .local/credentials/codex-carlid.json`.

## Run after saving

From this worktree, with the existing isolated local SpacetimeDB service running and the module/runner already built:

```bash
python3 scripts/run_carlid_npc.py output/my-new-carlid-run
```

The [launcher](../scripts/run_carlid_npc.py) reads the JSON directly, puts the key in `CARLID_NPC_API_KEY` in the runner's inherited environment, and starts the existing `sao-sim` binary. It never sources/evaluates the file, prints the key, or puts it in command arguments. This works when launched by Codex; exporting a variable in an unrelated terminal is unnecessary. It selects [codex-carlid-luna.json](../configs/reasoning/codex-carlid-luna.json), a new output directory, the existing 45-tick survival scenario and inspector port 18881. `SIM_TICK_MS` defaults to 8000 unless already set. Optional `--scenario PATH` and `--port PORT` choose another scenario/port. `--config PATH` selects another reasoning config only if it uses the same prepared Carlid endpoint and credential reference. Relative paths resolve from the worktree root. Existing output directories are rejected by the runner.

The command starts real hosted inference once a credential is present. The first output directory already exists; use a new name only when intentionally starting another authorized experiment. Build prerequisites and the local isolated server command are in the [M1 runbook](M1_RUNBOOK.md). After completion, inspect the retained evidence without loading credentials:

```bash
target/debug/sao-sim inspect output/carlid-luna-first 18881
```

## Current endpoint contract

The generic adapter posts to `https://codex.carlid.dev/v1/chat/completions` with `stream: true`. The proxy owner repaired its immediate SSE headers/comment and periodic keepalives and confirmed public readiness. The adapter ignores comment lines, joins ordered content deltas, and requires both a `stop` finish reason and terminal `data: [DONE]`. SSE error frames, missing DONE, malformed/incomplete content, refusals, truncation, disconnect, cancellation and deadline are failures. No partial output is submitted as a valid policy. Reported model and usage snapshots are retained when present; absent usage remains unknown and repeated cumulative snapshots are not added together. This proxy supplies terminal usage without `stream_options`; that flag is not sent.

A direct upstream check by the proxy owner established that this Codex/ChatGPT transport rejects `max_output_tokens`. The repaired proxy now explicitly rejects Chat token-cap aliases with HTTP 400 `unsupported_parameter` before inference. Consequently this endpoint declares `token_limit_field: "unsupported"` and **explicit `max_output_tokens: null`**. It has no provider-enforced output-token cap. Other endpoints retain numeric caps by default; a numeric cap paired with unsupported capability is a configuration error, never silently dropped. Historical manifests preserve what was actually requested at their time.

The normal config permits one attempt per request and a 240-second **overall** wall deadline; the separate [corrected proof config](../configs/reasoning/codex-carlid-luna-streaming-proof.json) uses the validated 300-second maximum. Heartbeats do not reset it. The normal launcher's default eight-second tick delay gives a pending request its unchanged 30-tick logical window; run duration and HTTP deadline remain separate limits. No temperature, seed, reasoning-effort override, OpenRouter routing fields or `response_format` is sent. Upstream reasoning remains its configured high default. `prompt_json` requests the unchanged authoritative policy contract; typed parsing and full authority validation remain mandatory. A normal scenario may issue multiple independent requests, so use the single-generation proof when a one-call experiment is required. Usage/cost after cancellation may remain unknown, and local cancellation is not a provider billing guarantee.

The [single-generation proof script](../scripts/verify_hosted_generated_policy.py) creates one isolated real database, exports its exact pending subjective context, holds logical tick 1 during one hosted request, submits that result unchanged and then runs 29 real reducer steps with no more inference. Its [probe](../server/bridge/examples/hosted_policy_probe.rs) restricts the endpoint, single attempt, uncapped streaming mode and <=300-second deadline. The launcher option `--probe-state PATH` loads the same credential safely for that probe; the credential remains only in the environment. This is a deliberately timed experiment, not real-time throughput evidence.

Generic preflight checks configuration only. The corrected adapter completed a public Luna stream with stop/DONE and reported usage; the unchanged generated tree was rejected for 11 root branches against the maximum 8. See [streaming verification](CARLID_STREAMING_VERIFICATION.md) for exact timing, capture limits and model-quality outcome. The external inspector is a developer audit surface; native Bevy development mode remains the intended visual observer/participant interface, with server-enforced observer privileges and shared rendering/input/data contracts. No native UI integration is included in this transport repair.
