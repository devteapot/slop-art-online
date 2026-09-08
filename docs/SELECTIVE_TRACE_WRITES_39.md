# Selective trace materialization (39)

2026-09-08. Continues the [paged storage implementation](PAGED_TRACE_SCALING_37.md)
after rejecting [parent lookup candidates](INDEXED_PARENT_SCALING_38.md).
The [world](WORLD_VISION.md), [simulation](SIMULATION_VISION.md) and
[performance contract](PERFORMANCE_CONTRACT.md) objectives remain open.

## Constraint and change

The paged writer already skips database updates when a page is unchanged, but it
first deep-clones every old page and constructs new metadata for every retained
entry to discover that equality. It also adds and subtracts reference counts for
unchanged bodies. Iteration 37's largest action-save span is 85.62 ms, far beyond
the nominal 16.67 ms movement/combat interval.

The writer now validates and borrows existing page entries. It resolves current
body identities against the retained kernel snapshot, then groups borrowed
records by the same consecutive cursor-bucket boundaries. It compares their exact
metadata and body IDs to the old pages before materializing new typed rows. Only
changed or new pages allocate copies of kind strings and parent vectors.

For an ordinary retained trace of cursors 1–256, appending 257 and pruning 1 now
materializes 32 entries in the two changed edge pages. The other seven pages are
reused. Moving complete pages in retained order can change only the head. Gaps,
repeated bucket transitions and arbitrary retained ordering remain supported;
there is no assumption of a contiguous cursor interval.

Body-reference bookkeeping records only inserted, removed or changed identities.
Unchanged entries no longer add then subtract the same reference. Changes across
participants still aggregate before final checked retention updates. Leases are
saved before last-reference body deletion, preserving their existing independent
captured evidence and lifetime. Canonical World and ordered audit remain exact.

The same generic page walker validates owned reads and borrowed save comparisons.
It checks actor/run/key scope, head membership, page shape, bucket membership,
unique cursors and nonzero body IDs. The page planner rejects invalid current
cursors or body IDs before writing pages; reducer atomicity rolls back prior
body resolution if an invariant fails. The immutable-body identity checks and
legacy-format upgrade path remain intact.

This reduces temporary allocation and in-memory bookkeeping. It does not promise
fewer persisted page updates: the old writer already omitted identical rows.
Subscription invalidations, public row shapes, body retention and audit policy
are unchanged. Full exports remain explicit diagnostics.

## Documentation and access pattern

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before the change.
Affected reads remain the actor's indexed trace pages, its primary-key head and
required immutable bodies. Writes remain changed actor pages, a changed head and
net nonzero body-reference updates. No whole-World reads, extra public tables,
new subscription recipients or cross-transaction cache are introduced.

The Rust SDK stays at 2.1.0, control CLI at 2.7.1 and standalone service at 2.10.0
(`b22dfaac6d46`). Existing SDK APIs and schema are unchanged; bindings are not
regenerated. Normal builds contain no host-clock profiling.

## Correctness checks

All 49 authority tests pass. New comparisons apply the selective write plan and
compare it against the original complete materialization across metadata-only
edits, body replacement, arbitrary order, gaps, empty traces and migration from
no pages. A fixture verifies that an ordinary append/prune materializes only 32
entries, while a complete-page reorder writes no pages. Deferred payload loaders
in these tests fail if touched, proving that planning uses metadata only.

Reference-delta tests compare the incremental changes with independent full
multiset counts, including repeated body IDs, pruning, replacements and transfers
between participants. Owned and borrowed readers reject the same malformed pages.
Existing actual-kernel/cold-storage, scope, command, render, export and lease
fixtures pass. Simulation and bridge source and interfaces are unchanged from
the retained implementation.

## Paired actual-authority comparison

`output/realtime/scale-39/writes-warm-paired-authority/` compares the frozen
iteration 37 and 39 normal modules. Both databases were published before any
setup. Each ran one warmup world followed by two measured fresh worlds, with
two 2,500 ms owner advances per world and alternating execution order. All six
worlds remained retained. No publication, migration or cleanup occurred between
measurements. This exercises the actual authority and shared kernel, without
live controllers, model inference, human input or observer subscriptions.

Every corresponding initial and advanced World matches exactly. Each world has
51,721 identical ordered audit events after its second advance, including 64
deaths and 10,720 death witnesses. Both implementations preserve exact trace
reconstruction and body-reference counts. A subsequent 260-request eviction
removes the selected record from the current trace and deletes its last body
reference, while an existing lease retains its exact captured evidence. The
post-eviction Worlds and ordered audits still match. Unprivileged access to all
four private trace/body tables is denied, and the granted public head remains
scoped to its actor.

After all timing and parity checks, publishing iteration 39 over the reference
database preserves all three exported Worlds exactly. The service exits 0;
the database volume and all original results are retained.

| Four measured owner advances, excluding warmup | Iteration 37 | Iteration 39 |
|---|---:|---:|
| Execution plus queries, total | 1,301.968 ms | 1,296.487 ms |
| WASM execution, total | 1,249.428 ms | 1,243.906 ms |
| CLI wall time, total | 1,378.766 ms | 1,373.353 ms |

The execution difference is only −0.42%, with individual comparisons in both
directions. Treat this as essentially unchanged warmed execution, not a reliable
speedup or a 60 Hz capacity result. Service memory spans six retained worlds;
it cannot be attributed to either implementation alone.

## Live release diagnostic

`output/realtime/scale-39/combat-selective-trace-writes/` freezes the normal
module, source, controller module and probe. It uses the same scenario as the
retained iteration 37 release: 200 combatants in one cell, 200 reference
controllers, one observer with component rendering and open inspection, 60 Hz
physical scheduling, and a declared ten-second active window. There are no
human connections or model calls. The world and controller services each have
a 6 GiB memory limit and 3 GiB page-pool limit. Owner exports, native-trace and
catalog reconstruction, combat-feed scope/reconnect, and component-render
equivalence checks run after pause. All declared checks pass and both services
exit 0. This is a short backend diagnostic, not a sustainable battle or client
frame-rate test.

| Observed live workload | Iteration 37 | Iteration 39 |
|---|---:|---:|
| Probe wall duration | 15,535 ms | 15,617 ms |
| Physical simulation elapsed | 10,001 ms | 10,001 ms |
| Survivors | 100 | 100 |
| Attack attempts / damage events | 895 / 688 | 1,076 / 827 |
| Deadline wakes / missed slots | 353 / 247 | 296 / 304 |
| Deadline execution plus query mean | 11.520 ms | 15.473 ms |
| Deadline p95 / p99 buckets | (25, 50] / (100, 250] ms | (50, 100] / (250, 500] ms |
| Scheduled queue p95 / p99 buckets | (1, 5] / (50, 100] ms | (10, 50] / (50, 100] ms |
| Action admission execution plus query mean | 0.924 ms | 0.954 ms |
| Observer physical gap p95 / maximum | 96 / 528 ms | 137 / 566 ms |
| Experience view calls / WASM total | 3,761 / 735.031 ms | 4,539 / 1,029.883 ms |
| Backend CPU | 14.23 s | 16.69 s |
| World outgoing WebSocket bytes | 14,713,502 B | 17,587,450 B |
| World peak RSS | 1,203,535,872 B | 1,222,459,392 B |
| World WASM peak | 158,662,656 B | 158,990,336 B |
| World jemalloc allocated peak | 537,125,432 B | 527,476,648 B |
| World jemalloc resident peak | 1,031,081,984 B | 1,073,553,408 B |

Iteration 39 performs more attacks and damage events and has worse observed
cadence: 50.7% of slots missed versus 41.2%. The asynchronous workloads differ;
these runs establish neither an overall speedup nor an isolated writer regression.
Observer gaps combine physical update types and do not establish per-actor combat
cadence. Memory is sampled, and no swap is observed. The common owned page reader
also changes internally; its higher observed experience-view cost remains visible
in this table rather than being assumed unaffected.

The final exact trace check finds 200 heads, 1,764 pages, 2,442 immutable bodies
and 50,645 current references, with no legacy or extra current rows. Logical
personal payloads total 20,094,752 bytes and stored bodies 850,453 bytes; this
sharing comes from iteration 37 and is not a new storage reduction here.
Sampled retained WAL changes from 106,001,688 to 209,094,870 bytes for the world
and 103,488,469 to 397,215,532 bytes for controllers. These are retained-size
gauges with unknown refresh timestamps, not cumulative writes or steady-state
growth rates. Full original metrics and volumes are retained.

## Profile and retention decision

`output/realtime/scale-39/combat-selective-trace-writes-profile/` passes the same
checks and both services exit 0. It reaches 10,001 physical milliseconds with
100 survivors, 970 attacks and 718 damage events. It records 304 wakes and 296
missed slots. Its trace reconstruction matches 50,569 entries in 1,762 pages
and 2,202 bodies. Host timing and sampled logging perturb scheduling, so this
profile is diagnostic evidence only.

The new sampled page-plan counters show 132 changed traces with 30,038 retained
entries. The writer materializes 4,366 entries, reuses 805 pages, writes 211
pages and removes 58 old page keys. Thus 85.5% of retained entries in these
samples avoid new metadata copies. This excludes the additional removed clone
of old pages. It measures selected construction work, not allocator bytes,
all participant writes or total database writes.

| Instrumented phase | Iteration 37 | Iteration 39 |
|---|---:|---:|
| Trace diff sample mean | 0.063786 ms | 0.054516 ms |
| Payload resolution sample mean | 0.078978 ms | 0.060284 ms |
| Page planning/write sample mean | 0.057567 ms | 0.056526 ms |
| Action save total / count | 606.04 ms / 308 | 569.10 ms / 300 |
| Action save maximum | 85.62 ms | 84.86 ms |
| Actor execution total / count | 544.93 ms / 311 | 551.74 ms / 303 |
| Complete action execution maximum | 109.34 ms | 123.49 ms |

The new profile samples 147 of 2,217 changed deadline participant saves, with
132 changed traces; iteration 37 samples 148 of 2,162 with 138 changed traces.
Three additional maintenance participant saves are sampled in iteration 39.
Systematic first/every-17th samples and differing workloads do not establish
population means. Nested timing spans must not be added to their parents.

Retain the selective writer for its verified reduction in temporary metadata
construction and unnecessary reference bookkeeping, with essentially unchanged
warmed owner execution and exact authority parity. No overall performance gain
or gate acceptance is claimed. The largest profiled action still loads 200
actors, has 197 alive/due inputs and emits 14,491 events at 3,942 ms. Its actor
execution takes 115.94 ms; action saving reaches 84.86 ms elsewhere in the run.
Both remain far above the nominal 16.67 ms budget. Broader burst execution,
per-recipient evidence assembly, storage reads and subscription work remain
the next bottlenecks to address.

The normal module was rebuilt after profiling and matches the frozen release
WASM SHA-256 exactly. Validation logs and the hash comparison are retained in
`output/realtime/scale-39/validation/`. Existing experiment artifacts and volumes
remain preserved; the development database was not modified.

The 216-character/30-minute gate, 2,000-character/eight-hour target, complete
combat/client coverage, sustainable populations and autonomous world outcomes
remain open. This bounded storage change does not complete the world vision.
