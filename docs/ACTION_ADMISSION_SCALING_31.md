# Action admission scaling (31)

2026-09-08. Continues the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) work after
[component inspection](COMPONENT_INSPECTION_SCALING_30.md). The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Dependency change

The previous profile records 1,350 action admissions in ten seconds. Reading
participant rows totals 349.37 ms and assembling them 430.00 ms, before shared
execution and saving. Each admission previously reads every co-located body and
station, plus body/arena support for their owners, although starting or cancelling
one finite action does not consume a local observation catalog.

The shared participant transaction module now declares whether each command needs
local context. `StartAction` and `CancelAction` read the actor and explicitly named
targets; all other commands retain the local context path. Human convenience
intents retain their existing path because they can route into persistent policy
or manual behavior admission. Physical execution still runs separately under the
shared action clock's full dependencies.

The authority point-reads the actor body, support, mind, participant/controller
metadata and retained lease headers. Receipts and private histories remain lazy.
Each named target supplies its body, support/arena and the exact numerical facts
consumed by current visibility laws. Validation receives the same actor facts,
skill definitions, scoped law binding and map. It still calls the original
`validate_scoped_action`, `target_perceived` and interruption implementations.
Custom laws receive the same complete hook inputs; this change does not replace
or approximate them. Remembered target IDs retain their existing meaning.

Only the actor's existing write set leaves the transaction: player/execution,
participant state, receipt/evidence, next clock hint, audit events and applicable
law faults. No target effect occurs at admission. Leases remain loaded so saving
an action receipt cannot accidentally discard previously captured evidence.
No schema, binding, permission, subscription or retention-policy change is made.

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[indexes](https://spacetimedb.com/docs/tables/indexes/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/) and
[views](https://spacetimedb.com/docs/functions/views/). Existing primary keys serve
these point lookups; no speculative indexes or broad view queries are introduced.
The module and SDK remain pinned to 2.1.0. Trials retain standalone 2.10.0 image
`b22dfaac6d46` and the established control CLI 2.7.1.

## Validation

Native storage differential checks compare each command's complete resulting
authority state, receipt, exact event order and next physical clock hint with the
full shared kernel. Cases cover five world families, both controller forms,
valid/invalid targets, movement, observation, rest, building, giving, repeated and
conflicting request IDs, stale revision/epoch, death, active attempt interruption
and preserved observation leases. Existing custom-visibility tests also run
through the narrowed path for same-cell, nearby and remote targets.

An initial test compile used the wrong action field; a later interruption fixture
used duration 20, which the real law rejects (allowed range 1–5). Both original
failures are retained in local validation logs. The corrected fixture uses a
valid five-unit wait and asserts the actual attempt exists before cancellation.
These were fixture errors, not evidence to relax the gameplay validator.

All 33 authority library tests pass. Normal and profile WASM builds pass. The
existing probe and controller module hashes match the comparator exactly; the
probe is not rebuilt because its behavior is unchanged. The authority change
introduces no UI or generated interface changes.

## Actual release workload

The comparator is `scale-30/combat-components-scoped`; the new release is
`scale-31/combat-components-admission`, both under `output/realtime/`. Both use
the same 200-person paired combat scenario, 200 reference controllers, one
component observer with open inspection, no human input or inference, a ten-second
loopback window and exact 60 Hz clock. There is no active full export; audit and
compatibility projections are exported after pause for verification.

Hardware remains the Ryzen AI MAX+ 395 host (16 physical/32 logical CPUs,
65,090,016 kB RAM), 6 GiB limits and 3 GiB storage pools per fresh database service.
CPU is not reserved and the relay/load generator shares the host. Original
sources, executables, invocations, metrics, audit and stop records are retained.

| Measurement | Previous component release | Narrow action admission |
|---|---:|---:|
| Physical elapsed | 10,001 ms | 10,001 ms |
| Probe elapsed including cleanup | 13,992 ms | 14,024 ms |
| Physical updates | 312 | 319 |
| Deadline wakes / missed slots | 310 / 290 | 319 / 281 |
| Missed-slot fraction | 48.3% | 46.8% |
| Command reducer + query mean / count | 1.614 ms / 1,259 | 0.997 ms / 1,357 |
| Deadline reducer + query mean / count | 11.856 ms / 282 | 14.105 ms / 310 |
| Deadline p50 / p95 / p99 buckets | 0–5 / 25–50 / 100–250 ms | 0–5 / 50–100 / 100–250 ms |
| Highest occupied deadline bucket | 500–1,000 ms (1 sample) | 250–500 ms (3 samples) |
| Header processing / calls | 508.11 ms / 294 | 556.37 ms / 319 |
| World / controller / relay CPU | 6.97 / 2.97 / 4.06 s | 7.34 / 3.33 / 4.84 s |
| World outgoing wire bytes | 13.45 MB | 16.94 MB |
| Attack attempts / completed / failed | 835 / 635 / 200 | 974 / 774 / 200 |
| Final alive / deaths | 100 / 100 | 100 / 100 |

Admission is cheaper, but total CPU, wire volume and mean deadline cost rise as
the asynchronous trial performs more attacks and catalog updates. Neither trial
is deterministic replay or an accepted sustained workload. The new release loses
41 characters at 3,742 ms, 36 at 4,286 ms, three at 4,851 ms, 19 at 5,150 ms and
one at 5,437 ms. Its low median includes quiet updates after permanent deaths.

All 200 personal combat feeds pass exact-source, reconnect and access checks.
Component reconstruction equals the compatibility projection; inspection changes,
reconnect, participant denial and grant/revocation checks pass. The audit retains
64,699 contiguous events, 39,800 initial sightings and 14,950 death perceptions.
The 32 rejected participant commands all report dead characters or a stopped run.
Original failed attacks are retained rather than relabeled successful admissions.

Observer physical-gap p95/p99/max is 119/299/544 ms and delivery-gap p95/p99/max is
109/415/598 ms. These are combined action/world deliveries, not per-character
combat cadence or rendered FPS. Scheduled queue p99 is in the 50–100 ms bucket,
with four samples still in 100–500 ms. No human input latency or Bevy frame quality
is measured. No world-maintenance reducer samples fall inside the new release's
selected metric endpoints; this is missing interval coverage, not zero cost.

New world/controller/relay peak RSS is 1.330/0.754/0.520 GB; world WASM peaks at
161.09 MB. World allocator allocated/resident peaks are 512.65/1,065.90 MB,
page-pool resident 1.77 MB and BSATN pool resident 0.0415 MB. These are service
measurements of fresh trial databases, not a retained multi-world RSS estimate.
Retained world WAL gauges move from 129.58 to 419.00 MB (+289.42 MB), while table
and materialized-view rows move from 85,622 to 63,704. Controller endpoint gauges
are unchanged at 106.96 MB and 80,752 rows. Gauge refresh times are unavailable;
unchanged values do not establish zero growth. Retained WAL is not cumulative
write volume, and decreasing materialized-view counts do not establish bounded
personal history. The earlier run's gauge limitations remain documented in
iteration 30.

## Diagnostic profile and remaining work

The completed `combat-components-admission-profile` diagnostic records 1,335
admissions. Every sampled admission loads exactly two bodies, two auxiliary rows,
zero stations and one target-facts row. These counters describe the selected
dependencies, not all database reads: actor metadata, definitions, retained leases
and lazy receipts still have costs. All sampled commands are finite action
admissions, so this is not evidence for the other command classes.

| Instrumented command phase | Iteration 30 (1,350 calls) | Iteration 31 (1,335 calls) |
|---|---:|---:|
| Read mean / total | 0.259 ms / 349.37 ms | 0.037 ms / 49.94 ms |
| Assembly mean / total | 0.319 ms / 430.00 ms | 0.056 ms / 74.32 ms |
| Shared execution mean / total | 0.224 ms / 302.66 ms | 0.171 ms / 228.74 ms |
| Save mean / total | 0.133 ms / 180.00 ms | 0.143 ms / 190.43 ms |

The read span excludes the subsequent explicit-target point lookups in both
profiles. Combined read/assembly mean falls from 0.577 to 0.093 ms, consistent
with the narrower dependencies. Saving is not improved by this change. Profiles
are separate asynchronous executions and include instrumentation overhead.

Physical action execution still peaks at 221.61 ms, lifecycle observation at
88.47 ms, action saving at 71.20 ms and audit insertion at 60.99 ms. These maxima
need not belong to the same transaction and must not be summed. Death-witness
processing totals 133.57 ms across 100 deaths. The actual audit retains all 14,950
death perceptions and 39,800 initial sightings. Full world-maintenance kernel
work peaks at 93.28 ms in three measured calls; its save phase peaks at 58.19 ms.
The next investigation should address these physical-update bursts and shared
maintenance rather than assume cheaper admissions establish 60 Hz capacity.

Both new world/controller pairs stop with exit code 0 and without OOM. Original
volumes and evidence remain retained. The normal uninstrumented release WASM is
restored after profiling. No current-client FPS, fresh inference, sustainable
population or latency acceptance is established. The 216-character/30-minute
gate, full 2,000-character/8-hour contract and complete world vision remain open.
