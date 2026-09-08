# Typed personal trace indexes (35)

2026-09-08. Continues the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) work after
[deferred controller catalogs](DEFERRED_CATALOG_SCALING_34.md). The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Measured dependency and storage change

Iteration 35 first adds opt-in systematic samples around personal evidence
recording and participant saves. The before diagnostic retains iteration 34's
mechanics and storage. In 337 deadline kernel calls it records 2,026 first-use
and 17,593 already-loaded evidence operations. The 301 selected first-use
operations average 0.083747 ms; 282 selected already-loaded operations average
0.002184 ms. First use loads the retained ordered metadata from a JSON header.
The header also lives on the mutable participant row and is rebuilt for changed
traces. Sampled header construction averages 0.042476 ms. These are sampled
instrumented costs, not unbiased estimates for all records or proven capacity.

The new private `sim_native_trace_index` table stores one current row per
migrated participant, addressed by the run/actor primary key and indexed by run
for explicit exports. Its typed ordered entries contain cursor, source, tick,
location, kind and parents. The mutable participant row contains a constant
format marker. It no longer carries the complete JSON metadata header.

Routine cold assembly retains a deferred loader. A first trace read fetches its
actor's index by primary key, checks run/actor/key and cursor uniqueness, then
constructs the existing shared-kernel experience representation. Individual
payload bodies remain deferred indexed reads with exact metadata validation.
No cursor interval or configured-limit approximation replaces retained order,
gaps or parent links. Evidence, causal provenance and gameplay are unchanged.

Changed traces atomically reconcile existing payload rows and update the typed
index with the exact retained sequence. An unchanged trace can reuse the marker
only when it shares the actor's strongly retained transaction snapshot. It does
not load or rewrite the index. Existing inline, cursor-only and JSON metadata
formats remain readable; a changed trace upgrades lazily. Full owner exports
load all indexes and bodies and keep the existing canonical World format.

One current metadata row and the existing payload rows remain per retained
participant, bounded by the actual gameplay trace retention policy. Death keeps
its existing identity/history semantics. Historical audit and captured lease
evidence keep their existing storage and retention. This is not a bound on the
number of identities over an indefinitely growing world. A changed trace still
rewrites its complete retained metadata vector; incremental trace mutation and
remaining global physical processing are future scaling work.

## Documentation and access pattern

Consulted the official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/) and
[pinned Rust SDK](https://docs.rs/spacetimedb/2.1.0/spacetimedb/).
Typed rows group data by access pattern; local first-use reads use the actor
primary key, and full diagnostics use the run index. Index updates occur only
when retained evidence changes. Tables remain private; authority perception,
learning and grant checks remain the access boundary. Existing scoped views
track the rows they actually read. No new public subscription or transient
notification replaces durable personal evidence.

The SDK stays at 2.1.0. The 2.1.0 generation CLI regenerates only the two new
Rust types and module exports. Actual trials use control CLI 2.7.1 and service
image `b22dfaac6d46` (standalone 2.10.0). No announced newer API is assumed.

## Diagnostic interpretation

The profiling feature samples the first and every seventh first-use evidence
operation, first and every 67th already-loaded/parent/append operation, and first
and every 17th changed participant save in each batch. It reports exact eligible
and sampled counts. The parser validates sample counts and equal evidence phase
eligibility. Phase timers nest, and their logging adds cost. Selected actor/order
positions are systematic and can be biased; phase sample means must not be
extrapolated as population totals or added to enclosing spans. Normal builds
contain no host timing calls from this instrumentation. Timing never affects
simulation decisions.

Before evidence is retained in
`output/realtime/scale-35/combat-evidence-before-profile`. Both trial forms use
200 paired same-cell combatants, 200 reference controllers, one component
observer with its inspector, no human and no inference, a ten-second loopback
60 Hz physical clock, and paused final diagnostics. This is a short workload,
not the 216-character/30-minute or 2,000-character/eight-hour acceptance gate.
The host is a Ryzen AI MAX+ 395 (16 physical/32 logical CPUs), 65,090,016 kB RAM;
services have 6 GiB limits and 3 GiB pools. CPU is unreserved and load generation
shares the host. Controller and probe binaries remain fixed.

## Validation and actual results

The 41 authority tests pass with typed metadata in cold physics, scoped action,
rendering and repeated storage reload fixtures. Complete state/event parity
covers existing scenario families. Added faults cover missing/foreign indexes,
changed metadata, duplicate cursors and count mismatches; retained order and
gaps roundtrip exactly. All 37 bridge tests pass after binding generation.

The full simulation library passes 244 tests with one ignored. A focused
unchanged-history check also verifies marker reuse without calling the cold
loader and rejects reuse after snapshot detachment.

A retained two-database upgrade trial (`output/realtime/scale-35/trace-upgrade`)
publishes the old iteration 34 module to both databases, creates the same
four-character world, and publishes the new release over one without deleting
data. Publication leaves the canonical world unchanged. Eight further steps
produce identical complete world state and all 97 audit events. All four traces
upgrade; 45 retained payloads and four typed indexes match the canonical export.
The isolated service stops with exit code zero.

The release (`output/realtime/scale-35/combat-typed-traces`) passes combat feed,
reconnect, denial/revocation, component rendering, inspector scope, audit and
catalog checks. After pause, all 200 typed indexes match retained order and
metadata; all 50,577 payload rows match complete exported evidence, with no extra
current rows. These final SQL counts differ from slowly refreshed service gauges.
Both services stop with exit code zero. No development database is changed.

| Release measurement | Iteration 34 | Typed traces |
|---|---:|---:|
| Physical elapsed | 10,087 ms | 10,000 ms |
| Probe elapsed including cleanup | 14,213 ms | 14,268 ms |
| Physical updates / survivors | 370 / 100 | 338 / 100 |
| Attack attempts / damage events | 918 / 695 | 1,000 / 761 |
| Deadline wakes / missed slots | 367 / 238 | 337 / 263 |
| Deadline execution + query mean | 9.027 ms | 12.463 ms |
| Deadline execution + query p95 bucket | (10, 25] ms | (50, 100] ms |
| Deadline execution + query p99 bucket | (100, 250] ms | (100, 250] ms |
| Scheduled queue p95 bucket | (0.1, 0.5] ms | (10, 50] ms |
| Action admission execution + query mean | 0.943 ms | 0.878 ms |
| Observer physical gap p95 / maximum | 87 / 474 ms | 135 / 534 ms |
| Backend CPU | 13.98 s | 15.52 s |
| World outgoing WebSocket bytes | 14,156,044 | 17,670,007 |
| World peak RSS | 1,272,532,992 B | 1,265,950,720 B |
| World WASM peak | 158,662,656 B | 158,662,656 B |
| World jemalloc allocated peak | 560,142,464 B | 570,732,824 B |
| World jemalloc resident peak | 1,111,367,680 B | 1,082,683,392 B |
| World page pool resident peak | 18,940,432 B | 21,824,016 B |

This release does **not** establish a throughput improvement. Deadline mean,
missed-slot fraction and observer gaps worsen in this run. Attack counts,
controller commands and death timing also differ: iteration 34 has death waves
at 3,513 and 3,987 ms, while the new run spreads deaths from 3,774 to 5,906 ms.
Wall-clock asynchronous runs do not execute identical workloads. Means include
later sparse updates and cannot certify a 200-character battle at 60 Hz.
Histogram counts use sampled metric boundaries (325 new deadline calls), while
durable wake counters include setup/cleanup (337); these are distinct scopes.

Service memory is measured for isolated databases, not allocated specifically
to individual World objects. No swap is observed. Retained WAL/table gauges do
not refresh across these short active windows, so their zero delta does not
establish zero growth. Final SQL verifies current trace retention only; sustained
WAL, table, allocator and identity-history growth remain unproven.

## Profile result and next constraint

The after diagnostic (`output/realtime/scale-35/combat-typed-traces-profile`)
passes the same live checks. Its 200 typed indexes and 50,564 retained payloads
match the full export; both services stop with exit code zero. It records 946
attack attempts and 746 damage events, versus 965 and 763 before. Both finish
with 100 survivors. After has 343 wakes/262 missed slots and before 339/266;
these are instrumented short runs with different physical event timing.

| Sampled phase | Before mean | Typed mean | Before / typed samples |
|---|---:|---:|---:|
| First-use evidence recording | 0.083747 ms | 0.057255 ms | 301 / 293 |
| Already-loaded evidence recording | 0.002184 ms | 0.002273 ms | 282 / 273 |
| Parent selection (nested) | 0.014920 ms | 0.008994 ms | 308 / 302 |
| Append and prune (nested) | 0.001289 ms | 0.001127 ms | 308 / 302 |
| Save controller | 0.048142 ms | 0.046923 ms | 144 / 141 |
| Save header | 0.042476 ms | 0.002726 ms | 144 / 141 |
| Save evidence diff | 0.052693 ms | 0.007256 ms | 134 / 127 |
| Save payload rows | 0.068516 ms | 0.067855 ms | 134 / 127 |
| Save typed index | absent | 0.096628 ms | 0 / 127 |
| Save participant commit | 0.008071 ms | 0.002312 ms | 144 / 141 |

After's exact eligible evidence counts are 1,987 first-use and 17,539
already-loaded calls, 19,526 parent/append phases across 342 deadline kernels.
Changed participant saves are 2,164 across those batches, selecting 140; one
maintenance batch changes 14 and selects one. Evidence diff/row/index phases
occur only for selected saves with changed evidence (127). Before counts and
sampling rules are given above and in the retained machine-readable summaries.

The first-use sample mean falls about 32%; there is no reduction in the
already-loaded mean. Header/diff savings largely move into typed index writes,
so this does not establish a net participant-save improvement. Complete
action-execution spans total 759.50 ms before and 684.75 ms after, but action-save
spans total 550.38 and 554.89 ms. Their counts are 335 and 340, workloads differ,
and sparse tails dominate many samples. These totals do not prove a causal
end-to-end speedup.

The largest after action domain loads 200 actors, has 193 alive/due execution
inputs, and emits 12,605 events at physical time 3,968 ms. Its actor kernel takes
119.97 ms and complete action execution 128.29 ms. Before's largest domain emits
9,316 events and takes 91.89/103.14 ms. These are actual burst costs far beyond
16.67 ms; the bursts are not equal-work comparisons. The improvement in cold
metadata access is retained, while the expensive full index rewrite and event
burst processing remain the next constraints to address and measure. Reducing
retained evidence, perception fidelity or causal history to fit the clock is
not the chosen solution.

The normal release was rebuilt after profiling and matches the frozen release
WASM hash exactly. Relevant local documentation links, Python syntax and
`git diff --check` pass. No experiment data was reset or discarded, and no
service required a forced stop. All three 200-character trials, their exact
implementations and the upgrade evidence are retained. The acceptance gate,
rendered FPS, input-to-photon latency, full inference access and sustained
population/resource limits remain unproven.
