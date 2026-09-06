# Law-source storage and execution regression

The first completed no-model law-storage diagnostic failed its minimum-read gate: 76 atomic reads completed against a requirement of 120 during the requested ninety-second measurement. Every observed identity, exact payload, private-source/case, lease and physical-work check passed. This is a failed overall diagnostic with a narrower correctness finding; the original result is retained unchanged.

## Original measurement

[Original result](../output/society-lab/reality-m7-storage-preflight/law-regression-v2/storage-regression.json), [gate decomposition](../output/society-lab/reality-m7-storage-preflight/law-regression-v2/law-storage-analysis.json), [participant results](../output/society-lab/reality-m7-storage-preflight/law-regression-v2/participant-storage-result.json), and [snapshot](../output/society-lab/reality-m7-storage-preflight/law-regression-v2/snapshot.json) retain the measurements. The fresh database was `sim-bevy-db-1788667511777-51980`; exclusive publication mapped it to replica `8000037`. The diagnostic created its own run and left the original paused fixture unchanged. No model ran.

Four persistent participant connections subscribed to their status and personal client views, and an observer subscribed to the rendering view. The owner concurrently queried the complete compatibility World. Actor 1 submitted an explicit tooling law through the ordinary participant interface, paid three terminal quanta, retrieved separate code/report copies, inspected/reflected on the held code, and installed west revision 1. Events 61, 840 and 887 identify submission, staging and activation. This source is a fixture, never autonomous authorship evidence or scenario knowledge.

| Measure | Original result |
| --- | ---: |
| Atomic reads / rounds | 76 / 19 |
| Read errors / failed observed checks | 0 / 0 |
| Exact retained leases | 16 / 16 |
| Measurement wall / simulation seconds | 94.710 / 93.405 |
| Updates / updates per wall second | 21 / 0.222 |
| Atomic read median / p95 ms | 3,274 / 5,370 |
| Owner full-state SQL median / p95 ms | 5,025.681 / 5,482.559 |
| Actual WAL logical growth bytes | 20,771,907 |
| Actual WAL allocated growth bytes | 20,975,616 |
| Final complete World bytes | 3,984,964 |
| Paid electricity / cooling water | 6 / 3 |

The exact fifty-byte installed source, private cases, terminal copies and personal copies survived. Every captured World round-trip and subscribed status comparison matched. Other actors lacked the author's source/private-case markers, nonowners could not select the raw World, and direct private-table queries were denied. The audit is contiguous through event 2,430. The probe paused its run, revoked its grants and reported no cleanup errors; its host was then stopped.

WAL values are actual file and allocated-block measurements of the mapped replica's `clog` directory, including segment allocation behavior. They are not inferred from compact JSON rows and do not establish device write volume. The low observed throughput is not evidence of sustainable 20 Hz cost. Four-world and 36-person trials need their own measured storage budget.

An earlier warm-up attempt, retained in `law-regression`, created and completed a paid prototype but queried the wrong participant jobs field before retrieval. The corrected probe used `own_jobs` and started a new owned run. This tooling failure is separate from the completed measurement's throughput failure; neither historical result is overwritten.

## Scoped execution cache investigation

Source inspection found that active-overlay skill invocation rebuilt its Rhai engine, law dispatch wrappers/modules and dependency modules on each call, while the skill AST itself was already cached. The compiled scoped-engine cache now uses exact-definition keys and fresh per-invocation fault/budget state through the Rhai invocation tag. It retains the existing 64-entry bound and carries no mutable active-world pointer. Two regressions cover same-reference source/dependency/base changes, current quarantine, fresh fault logs and reset call budgets. All 202 simulation tests pass; one ignored benchmark is run explicitly. [Retained benchmark results](../output/society-lab/reality-m7-cache-check/benchmark.json) give medians from three paired native debug benchmarks of 1,000 warm calls: 307,868 → 305,312 microseconds without overlays and 2,180,950 → 626,586 microseconds with an active overlay (3.48× faster). These isolate compiler overhead, not host cadence. The subsequent actual-authority repeat below measures subscribed reads and storage separately. The earlier Stage 6 and first law diagnostic also differ in payload size and workload, so their raw throughput difference alone cannot attribute a kernel regression.


## Cache-repaired actual-authority repeat

The unchanged ninety-second / 120-read gate **passes** on a fresh database and owned run. [Original successful result](../output/society-lab/reality-m7-cache-authority-check/law-regression/storage-regression.json), [analysis](../output/society-lab/reality-m7-cache-authority-check/law-regression/law-storage-analysis.json), [participant checks](../output/society-lab/reality-m7-cache-authority-check/law-regression/participant-storage-result.json) and [snapshot](../output/society-lab/reality-m7-cache-authority-check/law-regression/snapshot.json) retain the evidence. Database `sim-bevy-db-1788668997912-719630` maps exclusively to replica `8000039`; owned run `sim-law-storage-regression-1788669085922463102` is distinct from its untouched paused default fixture.

| Measure | Repaired repeat |
| --- | ---: |
| Atomic reads / rounds | 164 / 41 |
| Read errors / failed observed checks | 0 / 0 |
| Exact final leases | 16 / 16 |
| Authoritative updates / wall seconds | 44 / 93.445 |
| Updates per wall second | 0.471 |
| Simulation / wall time ratio | 98.75% |
| Read median / p95 ms | 1,465.5 / 2,401 |
| Owner SQL median / p95 ms | 2,338.895 / 2,470.466 |
| Actual WAL logical growth bytes | 45,326,377 |

The same paid three-quanta fixture installed and retained west revision 1. Every law-source/private-case check, sixteen final leases, full World round-trip and four subscribed status comparisons passed. All four 256-entry traces filled and rotated; all three private tables denied nonowner access. The final audit contains 3,449 contiguous events; snapshot SHA-256 is `f68c64eaf61a30ec9f634b451d5eae9880753f0cfaccb830ffad0fba66d6b66c`. The owned run was paused, grants revoked and both database clocks verified paused, with no cleanup errors. The diagnostic host was then stopped.

This passes the bounded subscribed storage and retained-law prerequisite, not 20 Hz performance or autonomous authorship. Native paired benchmarks isolate the compiled-code improvement; the two actual database measurements are separate runs and also differ in their accumulated state and concurrent system load. Faster processing increased measured log growth, so the forthcoming batch samples its own fixed replica directories and retains the 3 GiB disk reserve. Earlier failed measurements and build-quota failures remain retained.
