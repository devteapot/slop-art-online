# Parent lookup experiments (38)

2026-09-08. Continues [paged personal traces](PAGED_TRACE_SCALING_37.md)
toward the [world](WORLD_VISION.md) and [simulation](SIMULATION_VISION.md)
visions. Both parent-lookup candidates were rejected after actual-authority
measurements; the retained implementation is iteration 37. The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Measured constraint and candidate designs

Iteration 37 still spends 100.50 ms in actor execution for its largest dense
combat burst. Its sampled parent-filter phase averages 0.013790 ms. For each
new personal event, the kernel checks each parent against up to 256 retained
records. Missing parents, common in death-witness events, scan the complete
history. These checks protect personal provenance and must remain exact.

The second candidate kept lazy minimum/maximum source-ID bounds alongside
its ordered records. It computes the bounds from metadata on first membership
use, then expands them when a record is appended. A parent outside that envelope
cannot be present. A parent inside it uses the original exact linear scan.

Eviction can leave the bounds wider than the current source set. That only causes
an unnecessary scan; it never grants membership to an absent source. Duplicate
source IDs, arbitrary record order, gaps and maximum u64 IDs remain exact. Parent
filtering still follows the incoming parent's order, including repeated IDs. The
existing append-then-remove-one retention rule remains exact for oversized input.

The trace retains the existing deferred, copy-on-write storage boundary. Immutable
snapshots can share a loaded metadata list; a mutation detaches its records and
two bounds together. General mutable access invalidates the bounds before an
edit, including source replacements, reordering and removals. Bounds are never
serialized, and neither building nor querying them loads historical payloads.
There is no copied sorted-ID array or cross-transaction cache.

Both candidates preserved authoritative JSON, the table schema, private page/body
format and public feeds. Captured leases kept independent trace vectors. Their
native loader wrapped the same deferred metadata/payload reads in the candidate
trace container. No bindings changed. The candidates are now confined to their
frozen experiment snapshots; current source uses the original trace container.

## Documentation and access implications

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/) and
[views](https://spacetimedb.com/docs/functions/views/) before the change. Typed
actor-scoped pages and primary-key body reads remain the authority access pattern.
The bounds can reject absent parents without scanning loaded metadata; this does
not add a persisted table, change subscription recipients or reduce evidence
retention. Existing transactional writes and permission checks remain in place.

Pinned Rust SDK 2.1.0, control CLI 2.7.1 and service 2.10.0
(`b22dfaac6d46`) remain fixed. No new database API is selected.

## Correctness

The sorted candidate passed 250 simulation library tests, with one ignored,
along with 39 storage integration tests, 46 authority tests and 37 bridge tests.
The bounds revision passed the 250-test kernel suite, 39 storage tests and 46
authority tests. Four focused trace tests then passed after adding an additional
empty/extreme-ID check. These validate candidate fidelity, not retained code. New comparisons cover
arbitrary record order, gaps, duplicate sources, repeated parents, absent and
evicted parents, direct edits, snapshot isolation, serialization and lazy-load
failures. A metadata-only check deliberately supplies a failing payload loader:
membership succeeds without reading it, and a later export fails closed.

A kernel comparison uses the original linear membership check as a test-only
reference across three scenario families and both controller forms. It crosses
the retention limit before a physical death/witness sequence and compares the
complete World and ordered audit. Existing custom-visibility and visibility-fault
parity cases also compare indexed membership with the original scans. No second
simulator or approximate physical outcome is introduced.

## Earlier sorted-index candidate

The first candidate maintained a complete sorted source-ID index, including
duplicates, for binary membership searches. Its retained
`output/realtime/scale-38/combat-indexed-parents` trial uses the same 200 same-cell
combatants, 200 reference controllers and one component observer/inspector as
iteration 37. It runs a ten-second 60 Hz loopback interval with no human or
inference. The host is Ryzen AI MAX+ 395, 16 physical/32 logical CPUs and
65,090,016 kB RAM; CPU is unreserved, with shared relay/load generation. Each
service has a 6 GiB memory limit and 3 GiB pools. Probe/controller binaries are
fixed. There is no overlapping build during the measured interval.

All declared paused checks pass: exact audit and trace reconstruction, retention,
catalogs, rendering, combat feed, reconnect and access scope. The retained trace
has 200 heads, 1,763 pages, 2,315 bodies and 50,609 entries with no extra current
rows. Both services stop with exit code zero.

| Release measurement | Iteration 37 | Indexed parents |
|---|---:|---:|
| Physical elapsed | 10,002 ms | 10,095 ms |
| Probe elapsed including cleanup | 15,535 ms | 14,909 ms |
| Physical updates / survivors | 354 / 100 | 306 / 100 |
| Attack attempts / damage events | 895 / 688 | 1,014 / 780 |
| Deadline wakes / missed slots | 353 / 247 | 305 / 300 |
| Deadline execution + query mean | 11.520 ms | 14.648 ms |
| Deadline p95 / p99 buckets | (25, 50] / (100, 250] ms | (50, 100] / (250, 500] ms |
| Scheduled queue p95 bucket | (1, 5] ms | (10, 50] ms |
| Action admission execution + query mean | 0.924 ms | 0.970 ms |
| Observer physical gap p95 / maximum | 96 / 528 ms | 120 / 493 ms |
| Backend CPU | 14.23 s | 15.45 s |
| World outgoing WebSocket bytes | 14,713,502 | 17,401,821 |
| World peak RSS | 1,203,535,872 B | 1,227,808,768 B |
| World WASM peak | 158,662,656 B | 158,662,656 B |
| World jemalloc allocated peak | 537,125,432 B | 476,264,584 B |
| World jemalloc resident peak | 1,031,081,984 B | 956,284,928 B |

The new release misses 49.6% of clock slots, versus 41.2% previously. These
asynchronous runs contain different action/death timing and amounts of work;
the new one has about 13% more attacks and damage events. This is worse observed
live timing and does not support an end-to-end performance improvement claim.
Per-process peaks include enrollment, service metrics use sampled boundaries,
and retained WAL is not cumulative writes. Each live world has its own isolated
service/database. No swap is observed. Observer update gaps are not rendered FPS
or per-actor combat cadence.

## Sorted-index equal-work comparison

`output/realtime/scale-38/parents-paired-authority` starts both databases with the
frozen iteration 37 module and identical 200-character state, then publishes the
new module to one. Publication preserves the exact World. Both already use paged
traces; there is no format migration in this comparison. Two owner-driven
2,500 ms steps include 64 authored deaths and 10,720 separate witness perceptions.
Full Worlds and all 51,984 audit events match, including a subsequent captured
lease surviving 260 requests that evict its source from the current trace.
The last current body reference is deleted while the lease preserves the record.
A granted participant can read its public head but cannot query private trace
or evidence tables. The service stops with exit code zero.

| Reducer measurement | Original scans | Sorted source index |
|---|---:|---:|
| First death-burst step, execution + query | 402.495 ms | 415.206 ms |
| First step WASM | 375.949 ms | 387.642 ms |
| Second step, execution + query | 263.839 ms | 259.263 ms |
| Second step WASM | 262.682 ms | 257.824 ms |

These are single invocations with alternating order. The first new step is about
3.2% slower and the second about 1.7% faster. This does not establish a net speedup.
No relay, model, human or observer runs during the paired steps. Both databases
share one service, whose memory would not be a single World's footprint. The
coarse owner step is not a 60 Hz capacity measurement.


The sorted candidate's profile (`combat-indexed-parents-profile`) also passes all
checks, with both services exiting 0. It records 287 wakes and 321 missed slots
(52.8%), 1,017 attacks and 817 damage events over 10,137 physical milliseconds.
The parent-check sample mean falls from 0.013790 to 0.011462 ms, but append rises
from 0.001102 to 0.001558 ms and already-loaded record cost rises from 0.001849 to
0.002060 ms. Different work and systematic sampling prohibit treating these as
population cost estimates. The result did not justify retaining a sorted array.

A read-only reconstruction from the paired initial trace and ordered audit
classifies 10,920 of 10,984 parent lookups as outside exact current source bounds;
64 are absent within the bounds. Reconstructed final source IDs and parent lists
match every retained personal trace. The 10,720 death-witness lookups are all
outside the bounds. This evidence motivates the smaller conservative range check.
The sorted candidate's original source, binaries, measurements and volumes remain
intact; the following trials use separate outputs for the range-check revision.


## Conservative bounds release

`output/realtime/scale-38/combat-parent-bounds` uses the same declared live setup.
Every paused check passes, both services stop with exit zero, and 50,659 personal
entries match the canonical export and exact body-reference counts. It reaches
10,128 physical milliseconds with 291 updates and 100 survivors, 1,079 attacks
and 842 damage events. The durable clock records 288 wakes and 319 missed slots
(52.6%). Deadline execution/query mean is 14.107 ms, p95 is in (50, 100] ms and
p99 in (250, 500] ms; scheduled queue p95 is in (10, 50] ms. Observer physical
update gaps have p95 142 ms and maximum 584 ms.

The bounds release consumes 16.72 backend CPU seconds and sends 17,234,176 world
WebSocket bytes. World peak RSS is 1,258,512,384 B, WASM 158,662,656 B, sampled
jemalloc allocated 458,837,048 B and resident 1,014,935,552 B. No swap is observed.
As with the sorted candidate, the differing amount/timing of work does not support
an end-to-end speedup claim. The same sampling, retention and FPS limitations apply.

`bounds-paired-authority` passes the same 200-actor full-state/51,984-event audit,
64-death/10,720-witness, lease-eviction and private-table checks. Its service exits
0. The first step is 383.904 ms for the old module and 400.565 ms with bounds;
the second is 263.363 versus 253.041 ms. This initial comparison has a setup
asymmetry: only the candidate is republished just before its first measured step.
The modules have disposable parse/script caches. Cache state is a possible
confounder; these measurements do not isolate it or establish its contribution.

## Warmed comparison and rejection

`output/realtime/scale-38/bounds-warm-paired-authority` publishes each database's
respective module before any world creation. It performs one identical warmup,
then repeats the same two 2,500 ms steps in fresh Worlds with alternating order.
Every previous World remains retained. Each contains 200 characters and produces
64 deaths and 10,720 distinct witness perceptions. No relay, model, human or
observer is connected. The service spans both databases and all retained Worlds;
this is not a single-world memory or 60 Hz acceptance measurement.

The warmup and first two measured repetitions have exact World equality after
each step and byte-identical ordered audit, with 51,721 events per World. The
8 GiB disk-space guard stops the run before its third planned measured repetition.
That original error is retained; the overall run is incomplete. Its service exits
0, and the completed repetitions remain usable bounded evidence. No measured
step overlaps a build or cache cleanup. Inactive reproducible build caches were
reclaimed afterward; all experiment outputs and database volumes remain intact.

| Completed warmed repetition | Step | Original scans | Conservative bounds |
|---|---|---:|---:|
| 1 | Death burst | 387.478 ms | 380.839 ms |
| 1 | Following step | 260.746 ms | 265.890 ms |
| 2 | Death burst | 385.673 ms | 384.170 ms |
| 2 | Following step | 263.535 ms | 268.812 ms |

These are reducer execution plus query measurements. The modest first-step
reductions are offset by slower following steps. The two combined old totals are
648.224 and 649.208 ms; candidate totals are 646.729 and 652.982 ms. This is not
a consistent overall improvement and does not justify another trace abstraction
in production. The sorted index and bounds are both removed from current source.
A separate bounds profile was not run after this rejection; its unused diagnostic
build log remains in validation evidence.

## Retained state and next constraint

The five affected existing source files were restored byte-for-byte from the
verified iteration 37 snapshot, and the experimental trace container was removed.
The normal module was rebuilt and checked against that frozen release. Candidate
source, binaries, tests, comparisons and the disk-guard failure remain available.
Documentation links and `git diff --check` pass. No development database was
modified and no performance gate is accepted.

The parent-check samples include cold metadata loads and use systematic sampling;
they cannot be extrapolated as the aggregate cost of all parent comparisons.
The next larger persistence issue remains visible in the source and prior
profile: the page writer clones and reconstructs metadata for an entire retained
trace even when most pages are unchanged, and accumulates reference deltas for
unchanged entries. Reducing those allocations and database-related work is the
next hypothesis to test, preserving exact page ordering, payloads, reference
counts, leases and authority. The complete world/simulation objective remains open.
