# M1 verification — 2026-09-04

The bounded survival foundation in [ADR 008](adr/008-m1-authoritative-survival-slice.md) passes the first milestone's integrated checks. It executes inside SpacetimeDB, with live Ollama decisions and a working operator inspector. This accepts the new foundation path; it does not certify or migrate the legacy Bevy gameplay reducers. [Run it locally](M1_RUNBOOK.md).

## Executed checks

- `cargo test -p simulation --lib`: **14 passed**, including controller parity, sequence completion/failure/interruption, permanent death, speech/perception boundaries, sourced interpretation, identity affecting future choices, individual introspection, rejected/stale responses, snapshot continuation, and starvation recovery.
- `cargo test -p simulation -p bridge --lib --bins`: passed earlier in the implementation; the final kernel suite and both builds were repeated after corrections.
- `cargo build -p server_module --target wasm32-unknown-unknown` and `cargo build -p bridge --bin sao-sim`: passed. Existing unused-code warnings remain in the legacy module.
- `cargo check -p client`: passed with the regenerated SpacetimeDB 2.0.1 bindings.
- `python3 scripts/verify_m1.py`: passed against two concurrently initialized, separate real databases. Latest [report](../output/m1-verification-1788554485626691000/report.json) covers owner authorization/private tables, no overwrite or cross-run effects, equivalent human/AI skill effects, speech interpretation, failed sequences, permanent death, ignorant distant survivors, rejected responses, and ordered causal references. Model outputs in this suite are explicitly fixtures.
- Real-browser inspection exercised selection, world truth versus individual context, event filtering and parent links, exact free-form human speech submission, and a successful human Eat action. The archive identifies itself as read-only. Its snapshot and filtered query matched the saved records exactly; POST mutation was rejected.
- Restarted the owned SpacetimeDB service and re-exported both proof runs: state and every audit record were unchanged. [Durability results](../output/m1-durability.json). Dead players and history remain even after memories roll off; exported inspection returned the exact saved snapshot while the database service was stopped ([archive check](../output/m1-archive-check.json)). The service was then restarted.
- A real unavailable-model request returned Ollama HTTP 404. The [retained run](../output/m1-unavailable/snapshot.json) contains the error and rejected result while authored survival execution continues; it is not counted as live intelligence evidence.

## Live experiments and comparison

The two proof runs started concurrently, both using installed `qwen2.5:7b`, seed 42, and independent request/state/output destinations. [Comparison JSON](../output/m1-comparison.json) links identity metrics to event IDs. These few runs establish inspectability and rule behavior, not statistical claims about scarcity or model quality. The baseline also includes human participation, so differences cannot be attributed solely to food supply.

| Artifact directory | Database/run | Outcome | Live model results |
|---|---|---|---|
| [m1-proof-a](../output/m1-proof-a/manifest.json) | `sim-1788553862696-36990` | 45 ticks, 561 events; Mira and the human survived, Tovan died | 12 returned, 6 accepted, 6 rejected |
| [m1-proof-b](../output/m1-proof-b/manifest.json) | `sim-1788553862696-36988` | Scarcity variant, 41 ticks, 591 events; all died | 8 returned, 3 accepted, 5 stale |
| [m1-reviewed](../output/m1-reviewed/manifest.json) | `sim-1788554484431-44041` | Final-build baseline repeat, 41 ticks, 572 events; all died | 8 returned, 3 accepted, 5 stale |

The final-build repeat also verifies explicit arrival/execution parents on hazard events. Proof A/B used WASM SHA-256 `da9407fa932a932aa05c13d0222b0e52d216a134cc740f60f6e72472838db1d6`; the final repeat uses `6ac4935bd54bc7aa69d9453049e05de4141a2467bf14d04ba724697cb9aac124` and retains that [module executable](../output/m1-reviewed/module.wasm). Each manifest records its own exact hash. Proof A/B predate the executable-copy feature and the added hazard-parent link; their historical evidence has not been rewritten.

All paths under `output/` are local, ignored artifacts in this worktree. Preserve them separately before deleting the worktree. Prompts, complete raw responses/provider metadata, model catalog/digests, initial scenarios, human inputs, logical order, and actual state are retained. A Git baseline alone does not identify uncommitted code; use the recorded executable hash. Fresh model calls are stochastic. The bounded snapshot-continuation test does not establish a general or cross-version replay engine.

## Connected evidence in proof A

Open `just sim-inspect output/m1-proof-a 18877`, select Mira, and filter by the relevant event kind. The same events are in [snapshot.json](../output/m1-proof-a/snapshot.json), [events.jsonl](../output/m1-proof-a/events.jsonl), and a [connected-evidence extract](../output/m1-connected-evidence.json). Event IDs below are local to this run.

1. Mira's live decision **69** pursues the reported food site. Move attempt **75** completes at **98**. Hazard **100** causes damage **101**, perceived at **102**; identity change **103** replaces the safe report with experienced danger and changes caution **64 → 68**, fear **0 → 15**.
2. Request **117** supplies that subjective experience. Actual model result **172** proposes a warning and movement away; accepted decision **173** and interpretation **176** raise caution **68 → 72**. Speech attempt **178** emits warning **179**; movement **199 → 220** reaches position −1. Later model contexts retain the changed caution and belief.
3. Tovan interprets the initial report differently (**73**, versus Mira **70**). Harm changes his caution by two per experience, versus Mira's four, reflecting their configured introspection. His later choices and fatal return to danger remain visible; no preferred survival story is imposed.
4. Human speech **373**, entered through the inspector, thanks Mira and warns against the eastern clearing. Mira hears it at **374**. Request **468** includes that perception; live result **489**, accepted decision **490**, and interpretation **493** change trust in the human **0 → 2** and retain the dangerous-site belief. The selected movement executes at **495 → 499**. The following gather fails at **503 → 504**, without inventing food or executing the following Eat. Request **513** records reconsideration after lack of progress.
5. Human Eat decision **440** leads to attempt **446** and actual result **447**, decreasing carried food and hunger through the same kernel skill used by AI. The inspector showed the resulting state.

This maps connected cycle, imperfect knowledge, consequential free speech, individual development and introspection to actual live evidence. The integration suite adds controlled failure/interruption, mortality/privacy and cross-run assertions. Persisted histories, concurrent experiments, comparison and manifests cover the remaining audit checks.

## Review entry point and services

The retained proof A inspector is left running at [127.0.0.1:18877](http://127.0.0.1:18877), explicitly **archived · read-only**, not advancing. The isolated SpacetimeDB 2.0.1 server remains on `127.0.0.1:3100`, using `/tmp/sao-m1-spacetimedb-b0b2`; Ollama remains on `127.0.0.1:11434`. All experiment runner processes have completed. To start a fresh live run while keeping the archive open:

```bash
SIM_TICK_MS=2000 just sim-run scenarios/survival.json output/my-next-run qwen2.5:7b 18878
```

Use a new output directory for each run. No ordinary development database was reset; no changes were pushed, merged or published externally.

## Limits and follow-up

The local model sometimes proposes gathering where no food exists, repeats warnings, confuses speaker names, or produces contradictory prose and structured beliefs (for example **176** says “safe” while `danger: true`). These remain subjective outputs, never world facts. Proof A rejects three stale responses, two unsupported perception references and one response to a cancelled/resolved request. Scarcity and the final repeat reject five stale responses each. Damage invalidates an incompatible pending plan; validation was not weakened to increase acceptance counts.

These traces support bounded experience-linked change, not robust planning, rich psychology or reliable cooperation. Improve model/context quality and hazard-response planning using these retained failures. The current behavior format supports sequential skills only. The next integration work is connecting Bevy participation and legacy character paths to this authority, then extending skills while retaining these tests and evidence contracts. Large populations, rich terrain, souls/reincarnation, distributed operation and general replay remain outside M1.
