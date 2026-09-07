# Native clock profiling and history separation

This implements the first measured optimization pass from
[the clock research](NATIVE_CLOCK_RESEARCH.md). The runtime comparison identified
instance retention; phase profiling identified repeated script-cache key encoding
and whole-world loading. The implementation separates frequently updated state
from histories and avoids repeated source encoding on script-cache hits. It does
**not** implement the proposed indexed hybrid clock or establish sustained 20 Hz.

## Implementation and access paths

- `clock-profile` is an opt-in module feature. Host `LogStopwatch` spans attribute
  clock loading, kernel phases, saving, participant delivery and audit insertion.
  Timings never enter simulation decisions or persisted gameplay state. Production
  builds omit the timers. Nested spans overlap; they cannot be added together.
- Private `SimNativeMindHistory` separates memories, knowledge, beliefs,
  relationships and site observations from execution, generation and failure
  fields. The history row is rewritten only when those fields change.
- Private `SimNativeExperience` stores one retained experience per
  `(run, actor, cursor)`. The participant header keeps ordered cursor references.
  Appends and evictions change individual records; unchanged payloads are reused.
  Participant transactions use the `(run, actor, cursor)` index with the run/actor
  prefix. The clock still reads all actors' history rows through the run index.
  This removes repeated history writes, **not** full-clock history loading.
- Both tables remain private. Existing authenticated participant projections and
  bounded trace/lease retention still apply; no new public subscription is added.
  The separate causal audit remains append-only. Durable knowledge, audit and
  retained WAL still require long-term growth management.
- Older inline component histories remain readable and convert on write. Explicit
  owner migration converts the complete run, validates exact world/audit equality
  and is idempotent. Export must materialize deferred captured observations before
  comparison. Missing or wrongly scoped history references fail closed. The older
  module cannot read the new references: rollback requires a compatible module or
  an explicit export migration, not simply republishing the old WASM.
- Two bounded script fast caches compare complete definitions, dependencies,
  ordered law layers and disabled hooks before the existing digest cache. They
  retain at most eight entries each and enforce a 2 MiB source-text budget each;
  that budget is not a bound on compiled AST or allocator memory. Invocation
  faults and operation budgets remain fresh. Changed sources with reused IDs or
  revisions cannot reuse an incompatible compiled artifact.
- Skill transactions stage new audit events without cloning the already emitted
  prefix into each candidate action. Full-world clones retain normal semantics.
  A differential test compares exact state, execution and audit with the previous
  clone-and-execute path; existing failed-effect rollback tests remain applicable.

Module/client dependencies and generated bindings remain at **2.1.0**. Only the
two new private table types and their generated exports changed for this pass.
The existing development service on port 3101 and its database were not upgraded.

## Documentation and version checks

The design follows official [table design](https://spacetimedb.com/docs/tables/),
[indexes](https://spacetimedb.com/docs/tables/indexes/),
[performance](https://spacetimedb.com/docs/tables/performance/) and
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) guidance:
group independently updated state, index local access, keep subscription scope
authoritative, and measure actual transactions and growth. The current table
permissions page could not be accessed during implementation; private-by-default
behavior was checked against pinned macro source and actual denied subscriptions.
The timer API was checked in
[versioned 2.1.0 source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/bindings/src/log_stopwatch.rs).
Runtime selection and instance-pool differences are sourced in the research note.

## Declared workload and retained evidence

Evidence is under `output/native-clock-implementation/`, with plans, artifact
hashes, immutable WASM/probe copies, metrics, service/module logs, exact exports,
read receipts and cleanup outcomes. Every trial used a fresh isolated database,
container and volume at localhost:3103. No models or builds ran during sampling.

The comparison uses 72 actors on the same 48 × 36 map with maximum initial
co-location 16, authored starting policies and 72 persistent authenticated SDK
connections. The 180-second workload requests 128 experiences per observation in
twelve simultaneous rounds at 5, 20, …, 170 seconds: 864 reads, ten-second deadline,
no retry. Diagnostic 120-second trials use the first eight rounds (576 reads);
60-second trials use the first four (288). There are no active observer
subscriptions or owner exports; full exports occur at paused boundaries. Actual
action counts depend on the existing elapsed-time clock and contested policies;
these runs do not have identical event trajectories or fixed action rates.

Resource guards remain 12 GiB service memory, 11 GiB RSS, no extra service swap,
at least 3 GiB host available memory and 8 GiB disk free, and 4 GiB retained WAL.
The 8 GiB page-pool maximum is capacity, not resident memory. RSS includes the
whole isolated service; optional access and migration checks occur after active
measurement. Stops returned exit 137 after the timeout: these were forced service
stops, even when the run was paused and grants were successfully revoked.

## Runtime comparison

The identical prior WASM and 2.1.0 SDK ran on verified server images 2.1.0 and
2.10.0. No source changes were mixed into this comparison.

| Result | 2.1.0, 180 seconds | 2.10.0, intended 180 seconds |
| --- | ---: | ---: |
| Original protocol | Completed | Failed at WAL guard |
| Timely verified reads | 864, reconciled | 792 before abort; final 72 unresolved |
| Module instances | 73 | 2 |
| Peak service RSS | 5.84 GB | 1.30 GB before abort |
| Retained WAL | 1.89 GB near pause | 4.48 GB at 155.965 seconds |
| Completed cadence | 3.20 updates/s | No completed-trial cadence claim |

The newer runtime reduced observed instance/RSS retention but exposed faster WAL
growth in the original schema. It did not pass the original workload. The failed
run is retained unchanged. A frozen volume copy preceded separate cleanup
recovery; the recovered clock required explicit operator recovery after the long
gap, was paused without catch-up, exported and left with zero grants. Recovery
does not turn the original failure into a pass.

## Diagnostic attribution

Both 120-second diagnostics used 2.10.0 and identical fixture/read schedules.
Instrumentation and differing completed update counts prevent interpreting these
as a controlled per-action speedup or production capacity result.

| Mean host span / outcome | Original algorithm | Histories + script caches |
| --- | ---: | ---: |
| Clock load | 54 ms | 59 ms |
| Kernel advance | 105 ms | 27 ms |
| Clock save | 24 ms | 19 ms |
| Completed updates/s | 4.55 | 7.19 |
| Timely reconciled reads | 576 / 576 | 576 / 576 |
| Retained WAL at pause | 3.22 GB | 0.87 GB |

The final diagnostic passed privacy/reconnect/expiry checks and migration with
exact world, exact audit, idempotency and execution of pre-migration queued speech.
An earlier history-only trial failed migration because comparison attempted to
serialize a deferred observation capture. The export-materialization fix passed
the subsequent live migration. The original failure remains recorded in
`profile-history-60s/result.json`.

Audit-prefix staging alone did not show a clear performance gain in its finite
trial, so none is attributed to it. The fixed-input native script microbenchmark
improved from approximately 10.2 ms to 0.6 ms per 1,000 no-overlay calls; it is
supporting CPU evidence, not actual WASM/server capacity.

## Production workload

Both uninstrumented production runs passed the original 72-actor, 180-second
protocol with all 864 reads reconciled and no resource abort. These are individual
finite trials, not repeated estimates or soak tests.

| Measurement | Original on 2.1.0 | Candidate on 2.1.0 | Candidate on 2.10.0 |
| --- | ---: | ---: | ---: |
| Completed updates/s | 3.20 | 4.79 | 6.27 |
| Read p95 / maximum | 1,085 / 4,755 ms | 903 / 1,050 ms | 779 / 919 ms |
| Peak RSS during active window | 5.77 GB | 5.43 GB | 1.26 GB |
| Peak RSS including boundary work | 5.84 GB | 5.63 GB | 1.52 GB |
| Retained WAL near pause | 1.89 GB | 0.82 GB | 1.65 GB |
| Retained audit events | 145,247 | 166,311 | 180,117 |

The existing-runtime comparison demonstrates a measured cadence improvement
without requiring an upgrade. It does not remove the old runtime's substantial
RSS/instance retention. Every candidate run ended paused with zero grants and its
service stopped; only the pre-existing development service remained running.

The uninstrumented candidate on 2.10.0 completed the full 180-second workload:
864/864 reads reconciled, 779 ms p95 and 919 ms maximum, 1,128 updates (6.27/s),
and 179,969 ms of simulated time. Active service peak RSS was 1.26 GB; peak RSS
including paused-boundary work was 1.52 GB. Retained WAL at pause was 1.65 GB,
with 180,117 audit events, 131.17 MB of subscription bodies and no dropped samples.
There were no engine errors or resource aborts, all 72 actors survived, pause took
141 ms and no grants remained. This passed the finite protocol/resource test;
the separate 20 Hz result remained false.

This is a combined implementation-plus-runtime result against the original 2.1.0
baseline (3.20/s, 1,085 ms p95, 4,755 ms maximum). It is not a cache-only speedup.

At the nearest pause metric boundary, 2.10.0 reported two module instances and
93.39 MB aggregate WASM memory, 2.95 MB resident page-pool memory and 41,488 B
resident BSATN row-list pool memory. These do not account for all process RSS.
The original 2.1.0 WASM gauge reported 62.78 MB but does not aggregate its 73
instances correctly, so those gauge values are not a memory-saving comparison.
Final current table data totaled 114.25 MB versus 85.48 MB in the original run;
lower retained WAL does not mean smaller live state. The candidate retained
18,432 experience rows (72 × 256), 72 separate mind-history rows, 288 leases and
288 captures. Audit volume and world trajectories differ between runs.

## Correctness checks

The final source passed 204 kernel tests (one existing ignored benchmark), all
17 module tests, and all 36 bridge library tests with a disk-backed `TMPDIR` and
serial execution. The initial parallel bridge run had one timing failure: the
streaming cancellation test observed its 300 ms deadline before the scheduled
operator cancellation. Its failure log is retained alongside the passing serial
run; no timeout or assertion was relaxed. The production WASM build passed with
the existing 13 warnings. Live access and migration results are recorded above.

## Remaining clock work

Loading now dominates this fixture. The next dependency extraction must remove
irrelevant history loading before a deadline index can provide its intended
benefit. Existing perception hooks, remote infrastructure, law changes and ordered
contested actions prevent treating current position as the complete dependency
set. Birth-specific physiology, failed operations and observation provenance must
remain exact. A durable active/due/dirty representation and its full differential
verification remain unimplemented. Completion-relative scheduling, timestep and
catch-up semantics are unchanged. No thousand-player or sustained-20-Hz claim is
supported by these finite trials.
