# Action-domain scaling (28)

2026-09-08. Continued work toward the [simulation](SIMULATION_VISION.md) and
[world](WORLD_VISION.md) visions after [crowd lifecycle iteration 27](CROWD_LIFECYCLE_SCALING_27.md).
The [performance contract](PERFORMANCE_CONTRACT.md) remains unchanged and unaccepted.

## Evidence and implementation

The previous action-only clock reported an aggregate execution span without the
kernel's internal phases. The authority now uses the same optional phase observer
for full and local action transactions. Diagnostic builds separately time indexed
reads, assembly, execution, persistence, delivery and audit insertion. A compact
log record identifies each local execution's loaded population, living population
before execution, due actors and produced event count. These are diagnostic inputs
and attempted work, not proof of a committed physical outcome.

The summarizer retains aggregate statistics and adds per-reducer breakdowns and
correlated action phases. It marks boundary-truncated profiles incomplete. This
allows crowded work to be distinguished from nearly empty late-run updates instead
of presenting their combined average as battle capacity. Historical aggregate
summaries retain exact parity; original trial artifacts remain unchanged.

The baseline profile identifies 1.244 seconds of death-witness processing across
100 deaths. One world-maintenance reducer handles 80 of them; its actor phase
takes 1.321 seconds. Individual visibility checks reconstruct full numerical actor
inputs even though the exact bundled visibility law reads only identity, health,
distance and modality. This is distinct from the unavoidable requirement to
determine and record each actual witness.

Two implementation changes address measured repeated work:

- When no reproduction offers exist, the bundled-law lifecycle catalog is encoded
  once per location and arena for that refresh. Eligible recipients compare their
  retained encoded observations directly. Alternative JSON formatting still uses
  semantic equality. Personal offers and custom laws retain individual computation;
  no cache survives an action boundary, reload or law change.
- A death notification reuses the existing source-verified visibility input
  projection and caches the applicable binding by viewer location. The same Rhai
  hook still decides visibility. The original viewer order and interleaving of
  visibility checks with perceptions remain intact. Custom visibility receives its
  full inputs with the original quarantine/error behavior. No witness, memory,
  causal event or physical effect is dropped.

The visibility contract is guarded by the existing exact bundled-source hash.
Pending or custom visibility definitions do not acquire a broader optimization
contract merely because their output resembles the default law. A witness plan
exists for one notification and must not be retained across physical effects or
law activation.

## Documentation and data paths

Consulted official SpacetimeDB
[performance guidance](https://spacetimedb.com/docs/tables/performance/) and
[views](https://spacetimedb.com/docs/functions/views/), with the pinned 2.1.0 module
and SDK contracts retained from the preceding iteration. The isolated runtime is
standalone 2.10.0, image `b22dfaac6d46`, controlled with CLI 2.7.1. The changes do not
introduce a table, index, subscription, permission or generated-binding change.

Local action reads still use active/due actor and location indexes. The loaded
neighbor dependency set, participant history persistence, scoped publication and
audit insertion remain on their existing paths. Shared maintenance still loads the
hot world. The in-memory catalog encoding is reused, but stored per-character
catalogs are not deduplicated. All history and exact failed outcomes remain retained;
this does not establish bounded long-term resource use.

## Focused validation and profiling

Tests compare complete physical/personal state and the separately retained ordered
event vector against unshared catalog computation and full visibility inputs.
They exercise both controller representations, personal offers, changes and reload,
separate arenas, custom visibility reading additional attributes and failing
visibility hooks. Canonical immutable comparisons remain unparsed and key-order
differences remain semantically equal.

The profile artifacts are under `output/realtime/scale-28/`:
`combat-profile-domains`, `combat-profile-shared-encoding` and
`combat-profile-witness-inputs`. They freeze source, authority/controller modules,
probe, scenario, invocation, logs and metrics. Controller/probe binaries remain fixed;
only the authority module is rebuilt for these changes.

For a diagnostic comparison, select complete local profiles loading all 200 living
characters and exclude physical timestamps containing a death in the retained
authority audit. This filter is stated after inspecting the trace; it is not a
predeclared acceptance workload. It avoids conflating ordinary crowded refreshes
with mass-death catalog changes or empty local transactions.

| Crowded lifecycle refresh | Domain baseline | Shared encoding |
| --- | ---: | ---: |
| Complete non-death samples | 11 | 14 |
| Mean refresh time | 63.35 ms | 6.61 ms |
| Maximum refresh time | 69.89 ms | 6.83 ms |

The shared-encoding trace still has a 178.87 ms changed-catalog refresh and a
1,005.99 ms action execution. Death witnesses consume 852.39 ms across 100 deaths.
Those original remaining spikes are preserved rather than hidden by the lower
ordinary-refresh mean. Profiling perturbs runtime and cannot establish acceptance.

The combined profile retains the same 14,950 death-witness perceptions for 100
deaths. Their processing totals 533.10 ms, with a maximum of 18.88 ms per death.
The longest local action execution is 685.02 ms and a changed-catalog refresh
still takes 175.59 ms. All three profiles retain the same death-witness count;
ordinary attack traces differ because controller scheduling remains asynchronous.
This is reduced implementation work with unchanged witness semantics, not accepted
combat cadence.

## Combined release verification

`combat-release-combined` uses an uninstrumented authority build. Like iteration
27, it starts 200 paired attackers in one physical cell, with 200 reference
controllers, one SDK compatibility observer, no human input and no model inference.
The requested workload is ten seconds over loopback with the exact 60 Hz physical
schedule. There are 836 actual attack attempts: 636 completed and 200 failed.
These counts describe the trace, not a fixed offered action rate. Enrollment and
post-pause combat-feed checks are outside the requested measurement window.

The shared host is an AMD Ryzen AI MAX+ 395, 16 physical/32 logical CPUs, with
`MemTotal: 65090016 kB`. CPUs are not reserved; the load generator shares the host.
Each isolated database has a 6 GiB memory limit and 3 GiB configured pool limits.
No Bevy browser or display frame pacing is measured. All source and binary hashes,
configuration and logs remain in the run directory.

| Release diagnostic | Iteration 27 immutable catalog | Iteration 28 combined |
| --- | ---: | ---: |
| Clock wakes / missed slots | 219 / 381 | 275 / 325 |
| Missed fraction | 63.5% | 54.2% |
| Sampled deadline transactions | 201 | 275 |
| Mean execution plus query time | 24.47 ms | 16.00 ms |
| p95 enclosing histogram bucket | 100–250 ms | 25–50 ms |
| p99 enclosing histogram bucket | 100–250 ms | 100–250 ms |
| Final living population | 100 | 100 |
| World process peak RSS | 1.36 GB | 1.28 GB |
| Sampled world WASM memory | 160.76 MB | 160.43 MB |

The final trace has two deadline transactions in the 500–1,000 ms bucket. Although
246 of 275 sampled transactions are under 10 ms, many are quiet work after deaths.
Sixty-one characters die at physical time 3,922 ms and another 39 at 4,921 ms.
The final physical time is 10,001 ms; the probe's elapsed interval including
cleanup is 13,047 ms. Neither the aggregate mean nor update count establishes
200-living-character battle capacity. All clock counters are captured after pause
and retain their setup/cleanup scope. The one sampled shared maintenance reducer
takes 121.14 ms. Scheduled reducer queue p99 is in the 100–500 ms bucket.

World/controller/relay CPU use is 8.03/2.90/4.03 seconds in the sampled active
interval. Their process peak RSS is 1.28/0.74/0.54 GB, including enrollment. These
are isolated services, not the retained development service's combined footprint.
World outgoing wire data is 15.30 MB. No full-owner `sim_run` view is activated.

The sampled world/controller retained WAL gauges report 124.60/107.42 MB and
table-plus-materialized-view counts of 85,832/81,164. Those gauges remain unchanged
between the sampled endpoints despite new retained authority and controller
evidence. Their refresh timestamps are unavailable, so the arithmetic zero delta
does **not** establish zero storage growth or a final post-run footprint. The
summarizer now labels this limitation; the original summary is retained alongside
`stack-analysis-retention-resolution.json`. Longer measurement with confirmed
fresh retention samples is still required. Retained WAL is not cumulative writes,
and view rows must not be counted as additional durable source records.

The final authority audit verifies 63,258 contiguous events. All 200 personal
combat feeds match their authority-scoped source, reconnect is exact, and
ungranted, observer-only and revoked access return no private feed. All 14,950
death-witness perceptions remain present. Forty-two rejected submissions report
`character dead or run stopped`; the 200 failed skill attempts and their original
outcomes remain in the audit. Both owned services stop with exit code zero.

Final checks pass: 241 simulation library tests (one ignored), 31 authority tests,
37 bridge tests, default and profiling release WASM builds, local documentation
links and `git diff --check`. Existing compiler warnings remain. No client assets
or generated bindings require changes in this iteration.

## Remaining work

No performance acceptance gate passes. Changed catalogs still serialize and
persist per recipient, real witness delivery still causes large bursts, and
shared maintenance still loads the hot world. The next scaling work must reduce
those costs while retaining original personal evidence and custom-law behavior.
Admission beyond the prototype actor limit, sustained provisioning and population,
representative fresh inference, client frame pacing, and the 216-character
30-minute and 2,000-character eight-hour workloads remain unverified.
