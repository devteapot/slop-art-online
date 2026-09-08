# Shared transaction-local trace loaders (40)

2026-09-08. Continues the [selective trace writer](SELECTIVE_TRACE_WRITES_39.md)
toward the [world](WORLD_VISION.md), [simulation](SIMULATION_VISION.md) and
[performance contract](PERFORMANCE_CONTRACT.md) objectives. The loader sharing
is retained for its verified reduction in temporary construction. Warmed
execution is essentially unchanged and no performance gate is accepted.

## Constraint and change

Iteration 39's largest crowded action takes 123.49 ms to execute and another
action's save reaches 84.86 ms. First-use personal evidence handling averages
0.065987 ms in systematic samples. Loading each participant's retained trace
creates a lazy payload closure and its owned run string for every entry, even
when many entries reference the same immutable body. The release's 50,645
current references point to 2,442 bodies, but storage sharing alone does not
share these in-memory loaders.

Each cold authority reader now owns a map of lazy immutable payload handles
keyed by run and body ID. Validated actor-scoped pages supply the metadata and
references. The reader reuses a handle only for an identical scoped body ID;
each personal record keeps its own cursor, source, tick, location, kind and
ordered parents. Identical bytes under different IDs are not used as an
identity proof. Metadata assembly performs no payload fetch or JSON parsing.

A later payload read still validates the stored run, ID, digest and JSON through
the existing body reader. Success or failure is memoized by the shared lazy
value. The cache contains only bodies referenced by traces already loaded through
the authorized path. It neither discovers other minds nor creates perceptions,
knowledge or personal records. Replacing one record's payload does not change
another record or the captured pre-action state.

The ownership boundary is one cold reader, contained in one transaction's loaded
World. A payload closure retains the body-read function, not the ColdReader or
the cache. This avoids a reference cycle. There is no global or cross-transaction
cache, and subsequent transactions obtain fresh handles. The map retains at most
the distinct bodies referenced by traces loaded in that reader. It is released
with the reader; surviving immutable snapshots own only their referenced values
and read function. Storage-backed snapshots must remain transaction-local.

## Documentation and data access

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before designing the change.
Actor-scoped page indexes and head primary keys remain unchanged. Body reads
remain validated primary-key lookups; repeated references in one reader can now
share the same lazy read. The cache is locked once per loaded actor trace while
constructing handles; it does not hold the lock while calling the database.

No persisted table, reducer interface, write frequency, subscription recipient,
retention policy or generated binding changes. SDK 2.1.0, control CLI 2.7.1 and
standalone service 2.10.0 (`b22dfaac6d46`) remain fixed. Normal builds have no
profiling logs. Opt-in profiling records each reader's total references and
distinct handles at drop; these are allocation-work counts, not body fetches,
all live values or persisted rows.

## Correctness

All 52 authority tests pass. New tests verify lazy construction, one fetch per
shared body, independent record metadata and payload replacement, scope-separated
failures, distinct body identities and release without an ownership cycle.
An actual-kernel World fixture compares exact exports and counts one validated
fetch per distinct body, repeats the export without another read, and repeats
the experiment with a fresh reader. Existing cold physical execution, commands,
rendering, malformed storage and lease comparisons pass. The simulation kernel,
bridge and public interfaces are unchanged.

The first test build failed on an unqualified test-only JSON macro; qualifying
it fixed compilation. Both the original failure log and passing run are retained.

## Live release diagnostic

`output/realtime/scale-40/combat-shared-trace-loaders/` freezes the candidate
module, source, controller module and probe. The workload matches iteration 39:
200 combatants in one cell, 200 reference controllers, one observer with
component rendering and open inspection, a declared ten-second active interval
and 60 Hz physical scheduling. No human connections or model calls are present.
Both services use the fixed 2.10.0 image, 6 GiB memory limits and 3 GiB page-pool
limits. Builds and cache cleanup do not overlap the measured interval.

All declared post-pause checks pass: ordered audit export, native traces and
reference retention, catalogs, combat-feed scope/reconnect, and component-render
equivalence. Both services exit 0. The trace has 200 heads, 1,763 pages, 2,483
bodies and 50,678 current references, with no legacy or extra current rows.
Payloads total 21,377,576 logical bytes and 870,436 stored bytes. This existing
storage sharing is not a new persisted-size reduction from this candidate.

| Live diagnostic | Iteration 39 | Shared loaders |
|---|---:|---:|
| Probe wall duration | 15,617 ms | 15,191 ms |
| Physical elapsed / survivors | 10,001 ms / 100 | 10,001 ms / 100 |
| Attack attempts / damage events | 1,076 / 827 | 1,104 / 856 |
| Deadline wakes / missed slots | 296 / 304 | 278 / 322 |
| Deadline execution plus query mean | 15.473 ms | 15.532 ms |
| Deadline p95 / p99 buckets | (50, 100] / (250, 500] ms | (50, 100] / (250, 500] ms |
| Scheduled queue p95 / p99 buckets | (10, 50] / (50, 100] ms | (10, 50] / (50, 100] ms |
| Action admission execution plus query mean | 0.954 ms | 0.992 ms |
| Observer physical gap p95 / maximum | 137 / 566 ms | 156 / 549 ms |
| Experience view calls / WASM total | 4,539 / 1,029.883 ms | 4,881 / 1,194.461 ms |
| Backend CPU | 16.69 s | 17.79 s |
| World outgoing WebSocket bytes | 17,587,450 B | 18,007,913 B |
| World peak RSS | 1,222,459,392 B | 1,252,245,504 B |
| World WASM peak | 158,990,336 B | 158,990,336 B |
| World jemalloc allocated peak | 527,476,648 B | 493,229,992 B |
| World jemalloc resident peak | 1,073,553,408 B | 1,043,771,392 B |

The candidate misses 53.7% of clock slots versus 50.7% previously. It performs
more attacks and damage events, and two maintenance transactions fall inside
the sampled interval versus one previously. These differing asynchronous runs
do not isolate the loader's effect or establish an overall speedup. The unchanged
experience-view path still has real delivery cost. Observer update gaps combine
physical update types and do not establish per-actor cadence or rendered FPS.

Resource gauges are sampled and no swap is observed. Retained WAL changes from
105,482,718 to 212,107,226 bytes for the world and 102,704,789 to 399,337,760
bytes for controllers. Refresh timestamps are unavailable; these gauges do not
measure cumulative writes or steady-state storage growth. Original outputs and
volumes remain retained. The workload loses half its population and does not
satisfy the sustained performance contract.

## Paired actual-authority comparison

`output/realtime/scale-40/loaders-warm-paired-authority/` compares the frozen
iteration 39 and candidate normal modules on two fresh databases in one service.
Both modules are published before setup. One warmup world and two measured
worlds run per database, each with two 2,500 ms owner advances, alternating
execution order. All six worlds remain retained; nothing is published, migrated
or removed between measurements. This uses the actual authority and shared
kernel, without live controllers, human/model input or observer subscriptions.

Every initial and advanced World matches exactly between implementations. Each
world has 51,721 identical ordered audit events after the second advance,
including 64 deaths and 10,720 death-witness perceptions. Trace reconstruction
and reference retention match. After measurement, a 260-request eviction removes
the selected record from the current trace and deletes its last body reference,
while a prior lease retains its exact evidence. World and audit parity still
hold. All four trace/body tables deny access to a participant, whose granted
public head remains scoped to its character.

Publishing the candidate over the old reference database after all comparisons
preserves its three exported Worlds exactly. The service exits 0. These checks
exercise scope, recovery and upgrade fidelity, not long-duration capacity.

| Four measured owner advances, excluding warmup | Iteration 39 | Shared loaders |
|---|---:|---:|
| Execution plus queries, total | 1,282.642 ms | 1,278.892 ms |
| WASM execution, total | 1,227.424 ms | 1,225.848 ms |
| CLI wall time, total | 1,358.721 ms | 1,358.277 ms |

Execution differs by −0.29%, with individual comparisons in both directions.
Treat warmed execution as essentially unchanged, not a reliable speedup. Shared
service memory spans six retained worlds and cannot be attributed to either
implementation separately.

## Profile and decision

`output/realtime/scale-40/combat-shared-trace-loaders-profile/` passes the same
declared checks and both services exit 0. It reaches 10,001 physical milliseconds
with 100 survivors, 956 attack attempts and 754 damage events. It records 348
wakes and 252 missed slots (42%). The trace check reconstructs 50,593 entries
from 1,763 pages and 2,215 bodies. This instrumented run has different action
and death timing from the normal release; its better observed cadence does not
override the release failure or establish a controlled gain.

The new counters cover 30 deadline readers disposed inside the selected window.
They resolve 410,614 trace references through 14,848 distinct handles: **96.4%
of the former per-entry loader constructions are avoided**. Each reused handle
avoids another payload wrapper, deferred loader and owned run string. Every
personal record still has separate metadata. Per-reader maxima are 43,825
references and 1,575 distinct handles. Eight command readers resolve 1,949
references to 1,949 distinct handles, showing no sharing benefit for those
reads. These counts are exact for the included readers; they are not allocator
byte measurements, payload fetch counts or complete workload capacity.

| Instrumented phase | Iteration 39 | Shared loaders |
|---|---:|---:|
| First-use evidence sample mean | 0.065987 ms | 0.056402 ms |
| Already-loaded evidence sample mean | 0.001905 ms | 0.001787 ms |
| Death-witness total / count | 99.24 ms / 100 | 73.43 ms / 100 |
| Actor execution total / count | 551.74 ms / 303 | 497.42 ms / 346 |
| Action execution total / count | 729.80 ms / 300 | 644.84 ms / 343 |
| Action save total / count | 569.10 ms / 300 | 453.22 ms / 343 |
| Action execution maximum | 123.49 ms | 126.37 ms |
| Action save maximum | 84.86 ms | 86.01 ms |

The new deadline profile samples 283 of 1,896 first-use evidence calls and 280
of 17,612 already-loaded calls, versus 308 of 2,076 and 283 of 17,730 previously.
The previous profile also includes one maintenance sample in each category.
The new save profile samples 138 of 2,060 changed participants, with 120 changed
traces. Different workloads and systematic sample positions do not establish
unbiased population means. Nested timing spans must not be added to parents.

Retain the shared handles for their large verified construction reduction and
the one-read-per-body export behavior, with exact authority parity and no
material warmed execution change. Do not claim an overall speedup, a reduced
persisted footprint or a passed performance gate. Peak bursts remain unresolved:
the largest action loads 200 actors, with 198 alive/due inputs, and emits 15,531
events at 4,067 ms. Actor execution alone takes 116.82 ms. Reducing loader
construction does not remove per-recipient controller mutation, retained-record
copying, authoritative effects, persistence or synchronous subscription work.

The normal module is rebuilt after profiling and compared with the frozen
release. Logs, hash comparison and documentation checks are retained under
`output/realtime/scale-40/validation/`. Reproducible inactive build caches were
reclaimed outside measurement, excluding running executables and hard links;
browser assets, development databases, experiment outputs and volumes remain
preserved.

The immediate 216-character/30-minute gate, 2,000-character/eight-hour target,
complete client/combat coverage, sustainable population and autonomous world
outcomes remain open. The next investigation should address repeated state
copying within dense witness bursts and the remaining save/delivery critical
path, with the same exact physical and private-evidence requirements.
