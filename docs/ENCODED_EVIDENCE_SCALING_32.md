# Encoded event and lifecycle evidence scaling (32)

2026-09-08. Continues the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) work after
[action admission](ACTION_ADMISSION_SCALING_31.md). The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Physical burst evidence and implementation

Iteration 31's largest profiled action domain contains 200 loaded bodies, 130 due
actors and 11,070 new events. Its kernel takes 221.61 ms: actor work takes
132.94 ms and lifecycle observations 88.47 ms. A second domain takes 123.22 ms
with 5,274 events. These bursts remain far above a 16.667 ms active-update budget.

The lifecycle catalog is already encoded once per equivalent group. Previously,
each changed recipient expands that encoding into a fresh value tree, copies it
into a perception envelope, copies/redacts it again for personal evidence and
re-encodes it for retained controller metadata. The event and personal trace
then serialize separate copies during persistence.

Events now use the same immutable JSON payload representation as personal
experience records. A newly constructed value keeps its parsed representation;
an encoded/storage payload keeps its raw representation. The other form is
created only when requested and shared across retained copies. Source redaction
remains the original recursive policy, including explicit own-program/law
inspection exceptions. An unchanged redaction reuses the original payload;
a changed redaction keeps a separate immutable result and cannot mutate audit
truth. Neither result introduces wrapper fields into serialized JSON.

The bundled-law lifecycle refresh composes a client site perception around the
already-encoded catalog. The small site/infrastructure remainder and shared
catalog each pass the original redaction policy. Their fixed perception envelope
preserves that result without parsing the large combined object graph. Event IDs,
recipient cursors, causal parents, timestamps, knowledge-target updates and last
observed lifecycle remain distinct and retain their original semantics. Custom
law evaluation and non-client memory paths retain their existing ordering.

The native controller's activity adapter also borrows the immutable event payload
instead of expanding it merely to construct an activity event. Actual comparison
trials hold the previously built probe/controller binaries fixed to isolate the
authority change; library compilation and tests check the updated Rust adapter.

The native assembler also reuses identical retained catalog encodings among the
controller rows already selected for a transaction. Previously each row creates
an independent payload: when the catalog changes, semantic comparison can parse
the same old catalog once per character. A transaction-local exact-byte map now
shares that work. Row scope validation still precedes reuse, different encodings
remain distinct, and replacing one character's catalog cannot mutate another's
retained snapshot. The map adds no reads and is discarded after assembly.

## Data boundaries and documentation

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/). The change retains existing
actor/target/locality reads and existing private typed tables. It introduces no
schema, binding, subscription or permission changes. Authority and SDK versions
remain pinned to 2.1.0; actual trials use standalone 2.10.0 image `b22dfaac6d46`
and the established control CLI 2.7.1.

Each recipient still owns its separate perception/experience row. Audit rows and
controller metadata retain their ordinary JSON shape; serialization reuses
encoding but does not combine recipients or grant access to another character's
knowledge. Large changed catalogs can still cause substantial persisted and
delivered bytes. This is not a retention policy, shared public history table or
proof of bounded memory. Deferred values remain transaction-local and preserve
explicit load failures.

## Validation and trials

Simulation tests compare complete shared/unshared refresh state and exact event
JSON bytes across needs changes, offers, movement, death, arenas, reload and
custom hook faults. New tests compare immutable redaction with the original
recursive redactor, prove audit source preservation, retain the explicit
inspection exceptions and compare encoded site perceptions with the ordinary
path. They also verify that large audit/personal envelopes remain unparsed during
creation. Native storage and bridge checks cover downstream consumers.

The first bridge test attempt failed because `/tmp` had exceeded its user quota
and evidence writes failed. The original log is retained; the suite is rerun
with a workspace-local temporary directory and passes. Final validation passes
244 simulation library tests (one ignored), 33 authority library tests, 37 bridge
library tests and ten focused trace/retention codec checks for the initial encoded
variant. The final assembler sharing adds a differential scope/encoding test;
the complete authority suite then passes all 34 tests. Normal and profile
WASM builds pass. No gameplay or error assertion is relaxed to accommodate that
environment failure.

The first actual trial, `output/realtime/scale-32/combat-components-encoded`,
aborts at the runner's disk-space guard. Its probe is force-stopped with signal
15; both database services then exit with code 0 without OOM. It has no verified
final world or completed workload and is excluded from performance comparisons.
Its frozen implementation, logs, metrics and volumes remain retained. Host
available RAM at the final sample is 18.20 GB; the guard also requires 8 GiB
free disk. Workspace Rust incremental build cache (11 GB, reproducible) is
cleared before another trial; experiment evidence and databases are preserved.

## Completed release comparison

The completed final release is `scale-32/combat-components-shared-encoding` under
`output/realtime/`; the baseline is the retained iteration 31 release. Both use
200 paired combatants in one cell, 200 reference controllers, a component
observer/open inspector, a ten-second 60 Hz loopback window, no human input and
no inference. Audit/full compatibility exports occur after pause, not during
the workload. Probe and controller module hashes match the baseline.

The host remains the Ryzen AI MAX+ 395 (16 physical/32 logical CPUs,
65,090,016 kB RAM). Each fresh database has a 6 GiB service limit and 3 GiB storage
pools. CPU is not reserved; the relay and load generator share the host. This is
the same short diagnostic envelope, not the full contract workload.

| Measurement | Iteration 31 release | Shared event/catalog encoding |
|---|---:|---:|
| Physical elapsed | 10,001 ms | 10,001 ms |
| Probe elapsed including cleanup | 14,024 ms | 14,651 ms |
| Physical updates | 319 | 294 |
| Deadline wakes / missed slots | 319 / 281 | 294 / 306 |
| Missed-slot fraction | 46.8% | 51.0% |
| Deadline reducer + query mean / count | 14.105 ms / 310 | 14.910 ms / 293 |
| Deadline p50 / p95 / p99 buckets | 0–5 / 50–100 / 100–250 ms | 0–5 / 100–250 / 100–250 ms |
| Highest occupied deadline bucket | 250–500 ms (3 samples) | 250–500 ms (2 samples) |
| Command reducer + query mean / count | 0.997 ms / 1,357 | 1.022 ms / 1,468 |
| Header processing / calls | 556.37 ms / 319 | 573.40 ms / 302 |
| World / controller / relay CPU | 7.34 / 3.33 / 4.84 s | 8.23 / 4.16 / 5.59 s |
| World outgoing wire bytes | 16.94 MB | 19.67 MB |
| Attacks: attempted / completed / failed | 974 / 774 / 200 | 1,016 / 806 / 210 |
| Site observations | 803 | 1,062 |
| Final alive / permanent deaths | 100 / 100 | 100 / 100 |

The release comparison does **not** establish an end-to-end performance gain.
Cadence and p95 worsen, with greater CPU and delivery volume. The asynchronous
executions perform different work: the new run has more attacks and site-catalog
updates, and its deaths arrive in different waves (10 at 3,600 ms, one at
3,842 ms, 25 at 4,062 ms, 47 at 4,455 ms, 15 at 4,855 ms and two at 5,770 ms).
These differences must not be erased or treated as deterministic replay.

Actual combat-feed checks pass for all 200 participants, including exact source
evidence, reconnect and access. Component reconstruction, inspector transitions,
reconnect and grant/revocation checks pass. The audit retains 65,747 contiguous
events, 39,800 initial sightings and 14,950 death perceptions. All 210 failed
attacks report a dead/out-of-range target; 21 rejected participant commands report
a dead character or stopped run. None is relabeled a completed physical action.

Observer physical-gap p95/p99/max is 163/291/400 ms; delivery-gap p95/p99/max is
171/323/414 ms. These are combined action/world deliveries, not per-character
combat cadence, Bevy frames or human input latency. Scheduled queue p95 is in
10–50 ms and p99 in 50–100 ms. World-maintenance has no reducer samples in the
selected metric endpoints, which does not imply zero maintenance cost.

New world/controller/relay peak RSS is 1.328/0.775/0.556 GB and world WASM peaks
at 158.99 MB. World allocator allocated/resident peaks are 511.61/1,021.53 MB,
page-pool resident 2.29 MB and BSATN pool resident 0.0415 MB. Retained world WAL
gauges move from 131.59 to 483.33 MB (+351.75 MB); table/materialized-view rows move
from 85,199 to 65,146. Controller gauges are unchanged at 105.99 MB and 79,928 rows.
Gauge refresh timestamps remain unavailable; unchanged values do not establish
zero growth. Retained WAL is not cumulative write volume, and these short
service measurements do not establish bounded long-term memory/history.

## Diagnostic profile and remaining work

The completed `combat-components-shared-profile` run records exact-byte reuse
across 10,400 controller rows in 245 deadline assemblies: 304 distinct payload
decodes in total, at most 12 in one assembly. Only 52 assemblies load a 200-body
domain; the other 193 have no local bodies. Three world-maintenance assemblies
load 600 controller rows with 20 distinct payloads. One-actor command/inspection
assemblies retain their one-row dependency and gain no cross-actor reuse.

| Instrumented phase | Iteration 31 profile | Final iteration 32 profile |
|---|---:|---:|
| Site-perception count / mean / total | 240 / 0.317 ms / 75.99 ms | 1,469 / 0.023 ms / 34.41 ms |
| Lifecycle-observation total / maximum | 227.24 / 88.47 ms | 234.93 / 12.19 ms |
| Physical execution total / maximum | 786.50 / 221.61 ms | 904.86 / 72.46 ms |
| Physical save total / maximum | 407.74 / 71.20 ms | 696.81 / 55.64 ms |
| Physical audit total / maximum | 108.31 / 60.99 ms | 84.25 / 18.15 ms |
| Death-witness total (100 deaths) | 133.57 ms | 211.71 ms |

These are different asynchronous workloads and burst sizes. Smaller phase
maxima do not prove the same burst would now meet a deadline. Site-perception
construction gets cheaper, while total lifecycle time is similar despite many
more observations. Total physical execution and saving increase; encoding is
also deferred into first persistence. The complete result must retain all these
costs rather than claim improvement from the isolated construction timer.

The final profile has 100 permanent deaths spread over eleven physical updates,
14,950 death perceptions, 1,669 site observations and 66,973 contiguous audit
events. Its 247 wakes and 358 missed slots (59.2%) are diagnostic counters, not
release acceptance. The largest recorded kernel domain begins with 200 living
actors, has 184 due actors and emits 3,896 events; this is substantially less
work than iteration 31's 11,070-event largest domain. Average read/assembly
across all updates includes empty domains and must not be used as crowded
transaction capacity.

The next dependency issue is visible in source and these counts: every active
local physical update still loads the neighborhood's controller rows, including
large retained catalog strings and trace metadata, even though most bodies have
no effect or new observation. Sharing after row loading cannot remove that ABI
and storage cost. Investigate compact hot controller metadata and exact deferred
payload dependencies, while preserving current/remembered facts, named-target
validation, original witness evidence and custom-law behavior. A new storage
boundary needs separate permission, atomicity, retention and reconnect evidence;
this profile alone does not select or validate its design.

All six owned database services across the aborted release, completed release
and profile exit with code 0 without OOM. The aborted probe remains explicitly
force-stopped. The normal release WASM is restored and its hash matches the
completed release. No inference, client-FPS, population sustainability, 216-person
30-minute gate or full 2,000-person eight-hour acceptance is established. The
complete simulation/world vision remains open.
