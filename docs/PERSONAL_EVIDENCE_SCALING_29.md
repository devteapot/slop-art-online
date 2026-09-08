# Personal evidence and witness scaling (29)

2026-09-08. Continued scaling toward the [simulation](SIMULATION_VISION.md) and
[world](WORLD_VISION.md) visions after [iteration 28](ACTION_DOMAIN_SCALING_28.md).
The [performance contract](PERFORMANCE_CONTRACT.md) remains the acceptance target;
short diagnostic improvements do not accept its population, latency or duration gates.

## Implementation and preserved semantics

Candidate actions retain pre-action state so failed effects can roll back. Copying
an affected participant's experience vector previously cloned each historical
record's kind string and causal-parent vector, although its data payload was already
shared. An `Experience` now shares its complete record. An explicit metadata edit
detaches that record before mutation; retained snapshots keep their original fields
and bytes. Encoding reuse accepts identical retained records immediately and keeps
the exhaustive metadata/payload guard for detached records. The public JSON shape
and private row representation remain unchanged.

Event emission also stops cloning the event solely to pass it to personal-evidence
recording. The supplied event is borrowed, then moved into the ordered audit vector.
That recording path reads character state and the supplied event, not the audit
prefix. Initial participant enrollment likewise borrows the original events instead
of cloning the complete initial audit. Event IDs, ordering, retained personal
parents and redaction continue through the same recording implementation.

Each death still checks every candidate witness and records each actual perception
in its original order. Within one notification, equivalent visibility inputs can
reuse a result of the original Rhai hook. This requires the existing exact bundled
source hash and definition/layer checks. The verified hook uses health, distance,
ID equality, and whether the modality is death or speech. Results are grouped by
viewer location and those input values; arena permission is checked for every
recipient before reuse. The first evaluation uses actual inputs, and errors are
never memoized. Custom visibility, including identity-specific rules and failing
hooks, keeps full evaluation and its original fault behavior.

This equivalence contract is specific to the verified source. It is not permission
to infer arbitrary script dependencies or to retain results across law activation.
The cache exists for one notification, and no perception or personal knowledge is
copied between characters.

## Data paths and documentation basis

Consulted the official SpacetimeDB
[performance](https://spacetimedb.com/docs/tables/performance/) and
[index](https://spacetimedb.com/docs/tables/indexes/) guidance before changing the
authority path. The module and SDK remain pinned to 2.1.0, with isolated standalone
2.10.0 (`b22dfaac6d46`) and control CLI 2.7.1. No table, index, subscription,
permission or generated-binding change is introduced.

Affected actor/history reads retain their indexed storage paths. Historical
records are shared in memory, not merged across owners in storage. Changed
participant headers and new experience rows still persist through the existing
transaction; personal delivery and audit retention remain unchanged. Large changed
catalogs are still encoded per recipient. Shared maintenance still loads the hot
world. These are remaining costs, not accepted long-term storage boundaries.

## Correctness and diagnostic evidence

Existing storage tests mutate every experience metadata field and replace its
payload while retaining a snapshot. They verify snapshot isolation, encoding
certificates, unchanged row IDs, lazy loading, scope validation and corruption
failures. Full-state and ordered-event comparisons exercise death witnesses under
both controller representations, multiple arenas, custom identity/empathy rules
and throwing visibility hooks. An additional differential check varies health,
identity equality, distance and modality while comparing cached results with the
full original visibility path.

The retained trials are under `output/realtime/scale-29/`. Each freezes source,
authority/controller modules, probe, invocation, scenario, logs and measurements.
Controller/probe binaries remain fixed for comparison; the authority is rebuilt.
The source-compatible bridge constructor is checked by bridge tests, while the
trial's existing consumer also exercises unchanged wire compatibility.

In `combat-profile-record-sharing`, the first change alone reduces total
death-witness processing from 533.10 ms in the previous profile to 415.28 ms across
100 deaths. Both traces retain 14,950 death-witness perceptions. Action commit
processing totals 35.76 ms versus 104.26 ms, with different numbers of attempted
actions (841 versus 894) because controller scheduling remains asynchronous.
The longest local execution still takes 390.21 ms. This identifies reduced copying
cost without claiming that a mixed average measures crowded battle capacity.

The combined profile, `combat-profile-witness-reuse`, retains all 14,950
death-witness perceptions and 100 deaths. Their processing totals 125.81 ms,
with a 1.47 ms p95 and 15.73 ms maximum per death. Local execution still peaks
at 193.44 ms and a changed-catalog refresh at 129.57 ms. Site-perception work
averages 0.34 ms per observation versus 0.46 ms with record sharing alone; the
traces contain different numbers and sizes of changed catalogs. These are
diagnostic comparisons, not controlled action-rate or accepted latency claims.

The profiled combined run still misses 335 of 605 clock slots. Its lower kernel
cost does not eliminate query delivery, persistence, queueing or quiet updates
after death. All original and intermediate profile evidence remains retained.

The first combined-release launch stopped before creating services because its
output basename reused an earlier trial's credential label. The original error
is retained in `combat-release-combined/setup-error.txt`; it is a setup failure,
not a workload result. The actual release trial uses `combat-release-witness-reuse`.
The runner now includes a hash of the resolved output path in generated labels,
so future iteration directories can reuse descriptive basenames without reusing
credentials, containers or volumes. Existing evidence and credentials are preserved.

## Uninstrumented release result

The release workload starts 200 paired attackers in one cell, with 200 reference
controllers and one SDK compatibility observer. It requests ten seconds over
loopback at the exact 60 Hz physical schedule, with no human input, fresh inference
or browser frame measurement. There are 916 actual attack attempts: 715 completed
and 201 failed. This is an asynchronous trace, not a fixed offered action rate.
Enrollment and post-pause verification are outside the requested workload window.

The shared host remains an AMD Ryzen AI MAX+ 395, 16 physical/32 logical CPUs,
`MemTotal: 65090016 kB`. CPUs are not reserved and the load generator shares the
host. Each isolated database has a 6 GiB memory cap and a 3 GiB configured pool
limit. Per-process peaks include enrollment; active metrics use nearest samples.

| Release diagnostic | Iteration 28 combined | Iteration 29 witness reuse |
| --- | ---: | ---: |
| Clock wakes / missed slots | 275 / 325 | 278 / 327 |
| Missed fraction | 54.2% | 54.0% |
| Sampled deadline transactions | 275 | 257 |
| Mean execution plus query time | 16.00 ms | 15.99 ms |
| p95 enclosing histogram bucket | 25–50 ms | 50–100 ms |
| p99 enclosing histogram bucket | 100–250 ms | 250–500 ms |
| Final living population | 100 | 100 |
| World process peak RSS | 1.28 GB | 1.30 GB |
| Sampled world WASM memory | 160.43 MB | 160.43 MB |

**The faster kernel profile does not establish improved overall cadence.** The
missed fraction is effectively unchanged and both upper-percentile buckets worsen
in this release comparison. Three sampled deadline transactions take 250–500 ms;
226 of 257 are under 10 ms, including quiet work after death. Five characters die
at physical time 3,661 ms, 28 at 4,138 ms and 67 at 4,813 ms. The final physical time
is 10,089 ms; the probe's elapsed interval including cleanup is 13,428 ms. Durable
clock counters are captured after pause and include setup/cleanup. Different
sample boundaries and asynchronous action traces prevent treating these aggregates
as a controlled battle-rate comparison.

Two sampled shared-maintenance reducers average 105.40 ms. Scheduled reducer queue
p99 is in the 100–500 ms bucket. The compatibility observer receives every update
ID, but delivery gaps reach 698 ms; that is not accepted frame pacing. Its snapshot
view consumes 1,157.45 ms over 269 sampled invocations. The controller-experience
view consumes another 525.86 ms over 3,544 invocations. Storage, views, delivery and
queueing remain material costs alongside changed-catalog execution.

World/controller/relay active CPU totals are 7.91/3.34/4.13 seconds, with process
peak RSS of 1.30/0.76/0.55 GB. World outgoing wire data is 17.49 MB. No full-owner
`sim_run` view is activated. Both owned services stop with exit code zero; the
retained development service remains separate and unchanged.

The world retained-WAL gauge changes from 126.22 to 395.54 MB at the sampled
boundaries. Reported table-plus-view rows fall from 85,410 to 64,337; this includes
materialized-view lifecycle and is not a count of durable evidence loss. The
controller WAL/row gauges remain unchanged at 106.44 MB/80,340 rows, so they cannot
establish active storage growth. Gauge refresh timestamps are unavailable, and
retained WAL is not cumulative writes. The explicit final export independently
contains 50,540 active personal experience records, while the controller retention
query reports 63,575 retained journal records. Neither the stale controller gauges
nor this finite run establishes bounded long-term history cost.

All 200 personal combat feeds match their authority-scoped source; reconnect is
exact, and ungranted, observer-only and revoked queries return no private feed.
The audit verifies 64,216 contiguous events, including all 14,950 death-witness
perceptions, 201 failed skill attempts and 35 rejected submissions reporting
`character dead or run stopped`. Original failed outcomes are retained.

Final checks pass: 242 simulation library tests (one ignored), 39 storage
integration tests, 31 authority tests and 37 bridge tests; profiling and normal
release WASM builds; stable/distinct runner-label checks; documentation links and
`git diff --check`. Existing compiler warnings remain. No client assets or
generated bindings change in this iteration.

## Remaining acceptance work

No performance gate is accepted. The next work must address changed-catalog
materialization/persistence, broad maintenance dependencies and actual client
delivery costs. The pinned host's previously measured broad RawQuery-view read
sets are not a reason to replace indexed views without new evidence. Preserve
scope and reconnect guarantees in any storage or subscription change.

Admission beyond the prototype actor limit, sustainable provisioning/population,
representative fresh inference, the current Bevy delivery/frame path and the
216-character 30-minute and 2,000-character eight-hour workloads remain unverified.
