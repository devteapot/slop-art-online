# Shared witness payloads (36)

2026-09-08. Continues the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) work after
[typed trace indexes](TYPED_TRACE_SCALING_35.md). The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Evidence and change

Iteration 35's after profile spends 106.71 ms in 100 death-witness deliveries.
Its largest action domain loads 200 actors and emits 12,605 events, taking
119.97 ms in actor execution. Death notifications rebuild the same JSON envelope
for each witness: death name, source actor, position, rules revision and physical
time are identical across that notification. Each recipient then separately
redacts and serializes that identical payload for personal evidence and audit.

The death path now constructs one immutable perception payload per notification.
Only witnesses accepted by the existing visibility rule receive it. Each
recipient retains its own event ID, actor, parent, personal cursor, location,
knowledge update, wake state and last cause. Memory-based controllers retain
separate memories with the original content. Client controllers retain their
existing known-target updates and do not gain another character's private state.

The shared payload uses the existing immutable `ExperienceData` representation:
its validated redaction and encoded JSON can be reused within the notification.
Per-recipient metadata and payload rows remain distinct and durable. This shares
an encoding of a fact already delivered through authority; it does not copy
knowledge by proximity or remove evidence. No cross-transaction cache or global
content pool is added. A notification payload lives as long as its existing
retained events/evidence, with no extra history-retention owner.

The original perception path and shared path use the same recipient operation.
Visibility and memory-limit hooks still run in original order. Sharing only
covers envelope fields that do not change during that delivery. Ordinary
perception and client site-catalog behavior keep their original data shape.
Gameplay law source, damage, death, parent filtering and retention limits are
unchanged.

## Documentation and storage implications

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before the change. Existing
private trace-index and experience tables keep their actor/cursor primary-key
and run-index access patterns. Personal and audit rows are still written
atomically by the same reducers. Subscription recipients, update frequency,
row counts and retention policies are unchanged. This change reduces repeated
in-memory construction/encoding; it does not claim fewer database writes or
smaller per-recipient wire data. Full exports remain explicit diagnostics.

SDK 2.1.0, control CLI 2.7.1 and service image `b22dfaac6d46` (standalone 2.10.0)
remain fixed. No table, reducer or generated interface changes, so bindings are
not regenerated.

## Correctness checks

The simulation library passes 246 tests with one ignored. Added comparisons use
the same kernel with notification sharing disabled, checking complete world and
ordered audit parity across three scenario families, both controller forms,
custom visibility selection and original visibility failures/quarantine. A
24-character mixed-controller case checks one shared payload, 23 distinct
witness events, matching personal evidence and separate memory updates. The dead
actor receives no extra witness perception.

The 41 authority tests pass, including full state/event parity through cold
physics/storage reloads and scoped action/rendering paths. Initial construction
of the new 24-character fixture failed arena validation; its arena/controller
metadata and population limit were corrected before these passing checks.

## Actual authority trials

The live release is `output/realtime/scale-36/combat-shared-witnesses`. The workload
continues the same 200 same-cell paired combatants, 200 reference controllers,
one component observer with inspector, no human and no inference, and a
ten-second 60 Hz loopback interval. Controller/probe binaries are fixed.
Paused diagnostics verify audit, combat feed/reconnect/access, rendering,
controller catalogs and exact typed trace/payload retention.

The host remains a Ryzen AI MAX+ 395 (16 physical/32 logical CPUs),
65,090,016 kB RAM, with unreserved CPU and shared relay/load generation. Each
service has a 6 GiB limit and 3 GiB pools. These short diagnostics do not establish
216 characters for 30 minutes, 2,000 characters for eight hours, stable rendered
FPS or the full model-workload contract.

The live release passes all declared paused checks, with 200 typed indexes and
50,631 retained payloads matching the full export, without extra current rows.
Both services stop with exit code zero. No human or model was connected.

| Release measurement | Iteration 35 | Shared witness payloads |
|---|---:|---:|
| Physical elapsed | 10,000 ms | 10,002 ms |
| Probe elapsed including cleanup | 14,268 ms | 14,907 ms |
| Physical updates / survivors | 338 / 100 | 322 / 100 |
| Attack attempts / damage events | 1,000 / 761 | 1,028 / 825 |
| Deadline wakes / missed slots | 337 / 263 | 321 / 279 |
| Deadline execution + query mean | 12.463 ms | 13.000 ms |
| Deadline p95 / p99 buckets | (50, 100] / (100, 250] ms | (50, 100] / (100, 250] ms |
| Scheduled queue p95 bucket | (10, 50] ms | (5, 10] ms |
| Action admission execution + query mean | 0.878 ms | 0.891 ms |
| Observer physical gap p95 / maximum | 135 / 534 ms | 109 / 423 ms |
| Backend CPU | 15.52 s | 17.10 s |
| World outgoing WebSocket bytes | 17,670,007 | 19,203,245 |
| World peak RSS | 1,265,950,720 B | 1,342,320,640 B |
| World WASM peak | 158,662,656 B | 158,662,656 B |
| World jemalloc allocated peak | 570,732,824 B | 581,522,968 B |
| World jemalloc resident peak | 1,082,683,392 B | 1,109,688,320 B |

These asynchronous live runs do not execute identical operations: attacks,
damage and death timing differ. The new release still misses 46.5% of durable
clock slots, versus 43.8% previously. It does not prove an end-to-end throughput
improvement. Observer gaps describe delivered authoritative updates, not rendered
FPS or per-actor combat cadence. The service's sampled gauges do not establish
bounded long-term growth; retained WAL is not cumulative writes. No swap is
observed, and each release service hosts its own isolated database.

## Paired actual-authority comparison

`output/realtime/scale-36/witness-paired-authority-valid` retains a separate
200-character comparison. Both databases begin with the old frozen module and
the exact same scenario. The scenario disables starting habits and authors 64
ordinary damage interventions at 2,500 ms. One database then receives the new
module without deleting data; publication leaves the full World unchanged.

Two owner-driven `sim_step` calls advance 2,500 ms each, using the real kernel
and persistence. No relay, model, human or observer is connected. The first step
contains all 64 deaths and 10,720 separately authorized witness perceptions;
the second has no new death burst. Complete world state matches after each step,
and all 51,721 audit events match byte for byte. Both databases' current typed
indexes and payload rows match the final full export. This exercises trace
retention at the crowded scale without introducing an approximate simulator.

| Measured reducer execution + query | Old release | New release |
|---|---:|---:|
| First step, authored death burst | 499.770 ms | 484.672 ms |
| Second step, no new death burst | 306.142 ms | 306.078 ms |
| First-step WASM time | 446.885 ms | 429.769 ms |
| Second-step WASM time | 304.747 ms | 304.541 ms |

The order alternates between steps. Each value is one reducer invocation,
measured by exact before/after service counters. The roughly 3% first-step
execution reduction is a bounded observation, not a statistical speedup claim.
This owner path loads and saves a complete world; its coarse step duration does
not measure 60 Hz scheduling. The single service retains both databases, so its
memory would be service-wide, not one World's footprint. It stops with exit zero.

The earlier `witness-paired-authority` attempt failed scenario decoding before
measurement: the driver wrote an empty list for the starting-behavior map. Its
original module log, driver, result and volume are retained. Shutdown was requested
with SIGINT and exited 1; it is not reported as a successful graceful stop. The
corrected attempt uses a fresh name and output, with explicit HTTP error capture.
No failed result is replaced by the later successful comparison.

## Profile and remaining constraint

The diagnostic `output/realtime/scale-36/combat-shared-witnesses-profile` passes
all declared checks. Its 200 typed indexes and 50,604 retained payload rows match
the full export; both services stop with exit zero. It finishes at 10,082 ms
with 100 survivors, 1,015 attack attempts and 815 damage events, versus
10,085 ms, 100 survivors, 946 attempts and 746 damage events in iteration 35's
profile. The new diagnostic records 283 wakes and 321 missed slots (53.1%).

| Instrumented phase | Iteration 35 | Shared witness payloads |
|---|---:|---:|
| Death-witness total / count | 106.71 ms / 100 | 136.24 ms / 100 |
| Actor kernel total / count | 549.37 ms / 343 | 607.99 ms / 280 |
| Action execution total / count | 684.75 ms / 340 | 822.10 ms / 277 |
| Action save total / count | 554.89 ms / 340 | 790.08 ms / 277 |
| First-use evidence sample mean | 0.057255 ms | 0.063261 ms |
| Already-loaded evidence sample mean | 0.002273 ms | 0.001988 ms |
| Payload-row save sample mean | 0.067855 ms | 0.055563 ms |
| Trace-index save sample mean | 0.096628 ms | 0.105339 ms |

These live profiles show no aggregate improvement. The new diagnostic has 2,615
eligible first-use evidence calls (390 sampled), versus 1,987 (293 sampled).
Already-loaded calls are 17,943 (290 sampled), versus 17,539 (273 sampled).
Changed participant saves number 2,776 (185 selected, 172 with changed evidence),
versus 2,164 deadline saves plus 14 maintenance saves (141 selected, 127 with
changed evidence). More death waves and action updates repeatedly load histories
and rewrite trace indexes. The lower already-loaded/payload-row sample means
are consistent with less repeated encoding, but these systematic samples are
not unbiased population estimates or equal-work timing comparisons.

The largest new action domain loads 200 actors with 149 alive/due execution
inputs, emits 6,793 events at 6,256 ms, and takes 66.42 ms in actor execution and
73.24 ms in complete action execution. Its smaller peak than iteration 35's
12,605-event burst does not prove improved capacity: work is distributed across
more bursts, and total cost is larger. Parent and child spans overlap; do not
sum them. Diagnostic logging also changes scheduling. Durable counters and
span counts use different selection boundaries.

The exact paired comparison supports retaining the shared encoding, but broad
live 60 Hz capacity remains unproven. The next structural cost is per-recipient
persistence and complete trace-index rewriting during dense notification bursts,
alongside repeated cold reads across physical updates. An optimization must
preserve current perception, distinct personal provenance, atomic outcomes,
lease/reconnect recovery and durable audit. Reducing evidence fidelity or
allowing model latency to stall physics is not the selected direction.

The normal module was rebuilt after profiling and matches the frozen release
WASM hash exactly. Documentation links and `git diff --check` pass. Reproducible,
unreferenced build-cache files were removed only after checking for running
builds/executables; every experiment output and volume was retained. No
development database was modified. The failed paired setup remains distinct
from the successful release, profile and corrected paired evidence.
