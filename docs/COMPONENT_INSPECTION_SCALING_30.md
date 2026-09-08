# Component inspection and catalog scaling (30)

2026-09-08. Continued work toward the [simulation](SIMULATION_VISION.md) and
[world](WORLD_VISION.md) visions after [iteration 29](PERSONAL_EVIDENCE_SCALING_29.md).
The [performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Current-client workload and implementation

The recent kernel trials held one SDK compatibility observer fixed. The current
Bevy client instead subscribes to `shared::render_projection::SUBSCRIPTIONS`:
header, actors, body support, sites, scene and events. The benchmark now offers
`--render-mode components` using that exact query set. Compatibility remains an
explicit mode and the default for historical invocation compatibility. Both
comparison trials keep the inspector open on the first character.

The SDK probe waits for subscription application and records header timing plus
component insert/delete counts. Header/event JSON byte counts explicitly exclude
typed component row bytes; total delivery comparisons must use server wire
counters. This exercises the current backend delivery path, not Bevy frame
construction, GPU presentation or a human playtest. Post-pause checks reconstruct
the complete component projection and compare it with the compatibility view.

The component baseline exposes an avoidable whole-world operation: the header
view constructs and serializes a complete compatibility observer snapshot, parses
it back into JSON and extracts the one inspected character. Its header view takes
1,463.76 ms across 296 sampled calls in `combat-components-before`.

The header now loads the inspected character through an indexed local presentation
path and constructs only that character's rich projection. The same shared
projection helper also serves the existing full snapshot and personal view.
The authority checks the observer grant before loading inspection state. Current
perception, private memories and observer truth retain their existing meanings.
The participant header path and scoped access rules remain unchanged.

Care catalogs have another repeated cost: every peer calls the same pure bundled
care hook even when location, dependent status, hunger and health inputs are identical.
Catalog construction now reuses a result for identical complete inputs within
that construction/refresh. The existing bundled-law guard excludes changed,
pending or active custom laws. Custom/failing hooks retain full evaluation and
original fault order. The original hook still computes each distinct result;
the result cache lasts for one construction or refresh. Personal observations
remain separately retained.

## Data paths and official documentation

Consulted official SpacetimeDB
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and
[views](https://spacetimedb.com/docs/functions/views/) guidance. The module and SDK
remain pinned to 2.1.0. Trials use standalone 2.10.0 (`b22dfaac6d46`) and control
CLI 2.7.1. No schema, binding, subscription permission or table visibility changes
are introduced. RawQuery views are not substituted for the indexed paths whose
runtime behavior was measured in earlier iterations.

Open inspection reads the selected actor by key, its co-located bodies/stations
through location indexes, required body/arena support by actor key, and its own
mind/controller metadata. Referenced personal knowledge is loaded lazily when the
rich projection uses it. Captured reads, leases, command receipts, trace payloads
and controller bootstrap are not part of inspection. Closed inspection continues
to avoid actor private-state reads. Legacy storage retains its explicit decoding
fallback.

Inspection writes no rows. Ordinary actor, body, site and scene delivery remains
on the existing typed views. Current catalogs are recomputed from authoritative
inputs; remembered observations are not substituted for current facts. Large
changed catalogs are still serialized and persisted per recipient, and shared
maintenance still loads the hot world. Long-term history retention is not bounded
by these changes.

## Validation and retained trials

Simulation tests compare shared and unshared care catalogs across changed needs,
offers, death, movement, arenas and reload. The custom-hook test retains its
original unprimed fault/quarantine comparison. Native storage tests compare scoped
rich inspection with the full observer projection across the existing world
families and both controller representations. Failing lazy loaders verify that
inspection does not consume command traces, receipts or controller bootstrap.

Artifacts live under `output/realtime/scale-30/`. The newly built probe is held
fixed between the component baseline and changed authority; controller binaries
remain fixed. Each trial freezes source, modules, probe, invocation, scenario,
logs and measurements. Both actual subscription verification suites pass in the
baseline and changed release: personal combat/reconnect/access checks for all 200 participants and
component equality, inspector transitions, reconnect and grant/revocation checks.

The baseline starts 200 paired attackers in one cell, with 200 reference
controllers, one component observer, no human input and no inference. It requests
ten seconds over loopback at exact 60 Hz. It misses 312 of 600 clock slots (52.0%);
that is not accepted cadence. The comparison retains the same starting workload,
open-inspector load and requested duration.

Focused checks pass: 242 simulation library tests (one ignored) and 32 authority
library tests. The release probe and both normal/profile authority WASM builds
pass. The normal release build is restored after profiling. No UI assets or
generated bindings changed in this iteration.

## Release comparison

Both trials use the same AMD Ryzen AI MAX+ 395 host (16 physical/32 logical CPUs,
65,090,016 kB host memory), with a 6 GiB limit and 3 GiB storage pools per database
service. CPU is not reserved; the controller relay and load generator share the
host. Each service contains one fresh trial database. The development service and
historical databases remain separate. There is no active full export during the
workload; explicit full snapshots and audit exports follow pause. Measurements
use nearest sampled active-window boundaries, which can include setup edges.

| Measurement | Component baseline | Scoped inspection + care sharing |
|---|---:|---:|
| Physical elapsed time | 10,001 ms | 10,001 ms |
| Probe elapsed including cleanup | 14,341 ms | 13,992 ms |
| Physical updates | 288 | 312 |
| Deadline wakes / missed slots | 288 / 312 | 310 / 290 |
| Missed-slot fraction | 52.0% | 48.3% |
| Sampled deadline reducer + query mean | 15.27 ms (287 samples) | 11.86 ms (282 samples) |
| Deadline p50 / p95 / p99 enclosing buckets | 5–10 / 50–100 / 100–250 ms | 0–5 / 25–50 / 100–250 ms |
| Highest occupied deadline bucket | 250–500 ms (2 samples) | 500–1,000 ms (1 sample) |
| Header view total / calls | 1,463.76 ms / 296 | 508.11 ms / 294 |
| World / controller / relay CPU | 8.10 / 3.01 / 4.39 s | 6.97 / 2.97 / 4.06 s |
| World outgoing wire bytes | 12.79 MB | 13.45 MB |
| Attacks: completed / failed | 744 / 200 | 635 / 200 |
| Final alive / permanent deaths | 100 / 100 | 100 / 100 |

These are two short asynchronous executions, not deterministic replay or an
isolated estimate of either change. Different attack and death schedules affect
work performed. The baseline loses 42 characters at 3,820 ms and 58 at 4,524 ms;
the changed run loses 61 at 3,540 ms, 34 at 4,189 ms and five at 5,292 ms. Quiet
updates after deaths dominate the median. Both retain 39,800 initial sightings
and 14,950 actual death perceptions. Original failed actions remain present.
There are 35 and 14 rejected participant commands respectively, caused by dead
characters or the stopped run. Both final audits are contiguous.

The changed run has one additional sample in the 250–500 ms bucket. Observer
physical update gaps have p95/p99/max of 171/309/649 ms versus 138/450/704 ms;
delivery gaps are 100/420/746 ms versus 120/556/682 ms. These are combined
action/world update deliveries, not per-character combat cadence or rendered
FPS. Scheduled-reducer queue p99 remains in the 100–500 ms bucket in both runs.
No human input-to-outcome or input-to-photon latency is measured here.

Header work falls substantially, but outgoing wire volume increases. Event-view
processing also increases from 189.06 ms/288 calls to 351.15 ms/286 calls. Typed
body/site/scene views have almost no active-window reevaluation, as expected for
these stationary combatants. The changed run samples two world-maintenance
reducers averaging 108.40 ms. The baseline has no world-maintenance samples in
its selected metric interval; this does not establish zero maintenance cost.

World/controller/relay peak RSS is 1.322/0.719/0.509 GB before and
1.313/0.723/0.498 GB after. World WASM peaks at 160.76 MB in both. World allocator
allocated/resident peaks are 499.26/1,071.61 MB before and 577.05/1,152.40 MB after;
page-pool resident peaks are 1.84 and 16.32 MB, with BSATN pools at 0.0415 MB.
These service measurements do not establish a long-term per-character footprint.

Retained world WAL gauges move from 128.55 to 384.66 MB before, while table/view
rows move from 85,410 to 65,642. The changed world reports unchanged 128.68 MB and
86,676 rows across its selected endpoints. Controller gauges are unchanged at
105.96 MB/79,928 rows before, and move from 96.52 MB/72,100 rows to
110.95 MB/83,029 rows after. Gauge refresh timestamps are unavailable: unchanged
values do not establish zero growth. Counts include materialized subscription
rows; retained WAL is not cumulative bytes written. The retained raw metrics and
audit exports are needed to interpret these short snapshots.

## Diagnostic profile and next constraints

`combat-components-profile` is a separate instrumented execution of the changed
authority. Its 100 deaths retain the same 14,950 death perceptions. It is used
for attribution, not substituted for the release comparison. All six owned
world/controller service instances across the three trials exited with code 0;
their volumes, original outputs and stop records are retained.

The profile records 309 scoped inspector loads averaging 0.776 ms (1.332 ms
maximum), followed by projection averaging 0.597 ms (1.265 ms maximum).
Lifecycle observation across all 299 kernel samples averages 0.862 ms, but its
maximum remains 71.26 ms. Action execution peaks at 201.37 ms, saving at 77.25 ms
and audit work at 65.29 ms. Those phases can occur in the same transaction;
their maxima must not be added as if they describe one observed transaction.
The 100 death-witness calls total 117.53 ms, with a 15.65 ms maximum.

The same profile records 1,350 command admissions. Row reading totals 349.37 ms,
assembly 430.00 ms, shared execution 302.66 ms and saving 180.00 ms. Inspection of
the generic admission loader shows it still reads the co-located crowd for action
start/cancel commands. A next candidate is to narrow these reads to the actor,
explicit targets and exact permission/validation dependencies, retaining the
shared authoritative rules and custom-law fallback. This requires separate
read/write-set and privacy verification before implementation. It is not an
accepted architecture or a reason to remove valid target checks.

Other remaining constraints include shared world maintenance, serialization and
retention of large personal catalogs, admission beyond the prototype limit,
sustainable populations, geography and richer physical workloads. Current Bevy
frame quality, fresh inference, the 216-character/30-minute gate and the full
2,000-character/8-hour contract remain unverified. Neither these optimizations
nor the seven-stage bounded implementation establishes the complete world vision.
