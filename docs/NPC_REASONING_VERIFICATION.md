# NPC reasoning verification — 2026-09-04

The provider refactor is implemented and verified with mock HTTP contracts and live local inference. **Live OpenRouter inference remains unverified:** `OPENROUTER_API_KEY` was absent from the task environment. No paid calls were made. The later generic endpoint extension is covered by [verification dated 2026-09-05](OPENAI_COMPATIBLE_VERIFICATION.md). This is separate from the previously accepted [M1 simulation proof](M1_VERIFICATION.md).

## Tests and builds

`cargo test -p bridge -p simulation --lib --bins` passed **27 tests**: 12 reasoning/backend tests, one archive-loading test, and the existing 14 authoritative simulation tests. The archive test was repeated after adding the native runner hash. Both `cargo build -p bridge --bin sao-sim` and the WASM module build passed; existing legacy unused-code/import warnings remain. No reducer signatures or table schemas changed, so no binding regeneration was needed.

The local HTTP tests cover exact OpenRouter routing/schema/auth behavior; requested versus served identity; usage/cost retention and missing values; secret redaction; Ollama native settings; unsupported capabilities/configuration; reasoning effort validation; refusal, malformed and truncated responses; bounded oversized-body evidence; opt-in retries without switching; wall-time deadlines; cancellation while the world progresses; and compact metadata with a complete journal. Fixtures exist only inside tests and do not establish live intelligence.

The [real database regression report](../output/m1-verification-1788558074021189000/report.json) passed controller parity, sequence/failure semantics, speech/perception boundaries, mortality/history, owner authorization/private tables, concurrent run isolation, and ordered causal references. This uses explicit fixture decisions, independently of live provider checks.

## Live evidence

| Run | Evidence |
|---|---|
| [backend-ollama-live](../output/backend-ollama-live/manifest.json), `sim-1788558074294-71121` | Real `qwen2.5:7b`, full survival scenario, 41 ticks and 558 events. Seven attempts: three parsed proposals, two accepted by the authority; four cancelled local waits. The remaining valid proposal arrived stale. All three players eventually died. |
| [backend-reviewed](../output/backend-reviewed/manifest.json), `sim-1788558375733-74722` | Late-build 12-tick check, 198 events. Three proposals accepted at decisions **60, 81, 164**; one wait cancelled when the run ended, with its result retained and rejected by the authority. Four complete request journals. |

In the final run, result **163** is correlated to pending request **124**, followed by accepted decision **164** and identity change **165**. The supplied user message exactly equals the authority's frozen subjective context. This equality was checked for every model exchange; observer world state was not added. Available local usage includes prompt/completion token counts and model duration; unavailable provider identity/cost stays null. These runs verify transport integration and evidence, not improved planning or survival quality.

The 12-tick check manifest records module SHA-256 `8b2c96c052a90aa102625d99c9b30b037b02860dd36b57234c85726980424c8b` and native runner SHA-256 `c2c609d1f3e4f2b4fa671bbbf8f89daabcd8a15d24becca4227b9249b1403232`. The earlier full run predates the envelope/redaction/hash refinements; its own manifest and journals remain unchanged. The last OpenRouter-only normalization removes nonstandard Rust integer format annotations from its transport schema while retaining integer types/bounds; adapter tests and the binary build were repeated afterward. It does not change the verified Ollama path.

The [comparison](../output/backend-comparison.json) includes old and new runs with exchange event IDs, requested configuration, returned provider/model and usage. It is descriptive evidence, not a controlled comparison of model quality. The [verification summary](../output/backend-verification.json) records context equality, journal API equality, path-traversal rejection and old-archive compatibility.

## OpenRouter evidence and remaining check

The public endpoint catalog was queried for the example's explicit `openai/gpt-4.1-mini` / `openai` route. Its selected endpoints advertised schema/response-format, output limit, temperature and seed support; the [exact catalog](../output/openrouter-public-capabilities.json) is retained. This metadata check and official API documentation informed the adapter, but they are not a completed authenticated generation. The configured run command failed clearly at missing-credential validation before publishing a database or creating its output directory.

After supplying `OPENROUTER_API_KEY` in the process environment, the remaining live check is:

```bash
just sim-run-config scenarios/survival.json output/openrouter-live configs/reasoning/openrouter.json 18878
```

Review `preflight.json`, the actual model-result/journal records, returned model/provider identity, and usage before making cross-provider behavior claims. Endpoint capabilities and model deployments may change; the adapter rechecks at run startup and requests no fallback.

## Inspector and services

Browser inspection verified the selected model-result evidence and **Full reasoning journal** link. Every final-run journal fetched from the API exactly matched its on-disk bytes. Invalid journal path input was rejected. The original proof A snapshot still matches its saved artifact, and the final binary also exported that old database into a separate directory without initializing any backend or requiring credentials; the snapshot matched exactly.

- Original M1 archive: [127.0.0.1:18877](http://127.0.0.1:18877), unchanged and read-only.
- New backend proof: [127.0.0.1:18880](http://127.0.0.1:18880), archived/read-only; no simulation is advancing.
- Existing isolated SpacetimeDB remains on port 3100; Ollama remains on 11434. The temporary compatibility inspector on 18879 was stopped.

All work remains uncommitted in the owning worktree. No ordinary database was reset, and nothing was merged, pushed or deployed externally. Local artifacts under `output/` are ignored by Git: preserve complete directories, including journals, before deleting the worktree. See the [backend runbook](NPC_REASONING.md) for limits and configuration.
