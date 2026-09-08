# Compressed audit digests (48)

New lossless audit blocks hash their exact compressed bytes. Existing blocks keep
their original plaintext hashes and remain readable. Event strings, ordering,
archive boundaries, compression and private access do not change. Performance
acceptance still requires the complete world and client workload.

## Measured constraint and design

The [before profile](../output/realtime/scale-48/combat-audit-profile-before/clock-profile-summary.json)
separates per-event append and background archive phases. One physical append
contains 10,318 events; its complete audit phase reaches 30.58 ms. Sampled event
serialization averages 0.00115 ms and insertion 0.00280 ms. Samples are the first
and every 67th event per transaction; their means are not population estimates.

Background archiving has a larger stall: among 192 blocks, the complete encoder
reaches 85.01 ms. SHA-256 over the uncompressed JSON reaches 55.60 ms and totals
556.21 ms. JSON-array serialization reaches 16.43 ms; compression reaches
11.59 ms. These independent maxima need not occur in one block. The finding
prioritizes digest work over changing the audit row layout.

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[performance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/),
[scheduling](https://spacetimedb.com/docs/tables/schedule-tables/),
[access permissions](https://spacetimedb.com/docs/tables/access-permissions/) and
[procedures](https://spacetimedb.com/docs/functions/procedures/) before design.
Rust SDK 2.1.0, CLI 2.7.1 and service 2.10.0 remain fixed. Existing primary-key
blocks, indexed recent rows and one pending archive callback per world remain.
No schema or generated interface changes are required.

The existing `digest` string distinguishes the formats. A bare 64-digit lowercase
hexadecimal value continues to cover the complete plaintext JSON array. New
values use `zlib-sha256-v1:` followed by the hash of the stored zlib stream.
New readers verify that hash before bounded decompression, then verify the exact
plaintext length, 128-event count, world identity and contiguous event IDs.
Legacy blocks retain plaintext hash verification after bounded decompression.
Unknown formats and malformed metadata fail closed. A valid digest cannot
substitute for a valid stream or event identity.

This binds the exact compressed representation to its deterministic decoded
bytes; it does not remove integrity validation. The same zlib algorithm/level,
32 MiB plaintext limit, original JSON strings, 128-event boundaries and 2,048-event
recent tail remain. Compression still runs outside physical transactions.
Neither current perception nor personal evidence can be restored from owner
audit history. Owner checks still precede all archive reads.

New code reads mixed old/new blocks without rewriting history. Old readers do
not understand the new prefixed digest and fail rather than silently accepting
it. Reverting a module that has produced new blocks therefore requires a reader
that supports the prefixed format. No rollback or historical rewrite is part
of this change.

## Verification

The [authority suite](../output/realtime/scale-48/validation/authority-tests.log)
passes 63 tests and [storage integration](../output/realtime/scale-48/validation/storage-tests.log)
passes 39 tests. The new check covers both digest formats, exact whitespace,
Unicode and numeric text, modified compressed bytes, invalid streams with valid
hashes, wrong lengths, missing identities and unknown formats. The simulation
kernel is unchanged; its earlier tests are not added to this run's total.

Both normal and profiling WASM builds succeed with the existing 20 warnings.
The [normal frozen implementation](../output/realtime/scale-48/implementation/manifest.json)
and [profile variant](../output/realtime/scale-48/profile-implementation/manifest.json)
retain exact source/binary hashes; the unchanged iteration-41 controller module
and SDK probe remain the live-workload companions.

The [first authority checker](../output/realtime/scale-48/audit-combat-paired-authority/result.json)
finishes all three old/new combat repetitions with exact complete World and
ordered-audit parity. It then rejects the database's valid SATS encoding of
`Option::None`, `[1, []]`, while inspecting archive status. This is a checker
parsing failure, not a blocked archive or passed archive check. Its original
failure and exit-0 service shutdown remain preserved.

The [resumed checker](../output/realtime/scale-48/audit-combat-paired-authority-resumed/resume.json)
uses the same six retained worlds and the corrected optional-value parser.
Original physical measurements remain unchanged. The partially processed first
archive warmup is excluded from measured comparisons; both later archive worlds
were untouched by that failed check. The resumed verification completes.

## Actual authority and archive comparison

The original physical comparison retains six worlds in one isolated service:
200 colocated characters at 20 health per world, one fixed paired attack per
actor, no disturbances or starting behaviors, one sequential participant
identity, and two 2,500 ms owner advances. One world pair is warmup and two are
measured. There is no live physical scheduler, controller population, observer,
human input or inference. Each corresponding World and ordered audit matches;
every world has 100 deaths, 100 damage events and 14,950 death observations.
Archiving is disabled during these steps, so their small timing difference is
an unchanged-path control, not evidence of digest speed.

Archive catch-up then processes the same original 56,950 events per world,
retaining the recent tail and encoding 428 blocks of 128 events. One world runs
at a time; the checker polls with a 50 ms delay plus CLI overhead. The first
reference archive finishes before the resumed warmup metric boundary; all first-
world results remain excluded. The two later world pairs start unarchived and
alternate database order. Each produces exactly 54,784 archived events,
22,484,718 plaintext bytes and matching compressed byte counts between versions.

| Two measured archive worlds per version | Reference 47 | Compressed digest 48 |
| --- | ---: | ---: |
| Background callbacks | 856 | 856 |
| WASM execution, total | 908.08 ms | 582.97 ms |
| Execution plus queries, total | 1,010.97 ms | 690.44 ms |
| Catch-up wall time, total | 2,765.94 ms | 3,410.70 ms |

The [archive comparison](../output/realtime/scale-48/audit-combat-paired-authority-resumed/archive-measurement-summary.json)
uses **35.8% less WASM time but 23.3% more wall time**. Polling, scheduler spacing
and other host work are included in the latter; the comparison does not isolate
the cause of its increase or establish faster overall catch-up. It does establish
less reducer work for the same blocks and original event strings.

All six archives recover every exact event string. An independent Python zlib
and SHA-256 check validates the first, last and largest actual block in each
world, including original whitespace/bytes. The largest block is also the first
in each world, so these selections cover 12 distinct blocks. Complete World exports remain
unchanged. Captured evidence survives 260 rejected requests that evict its
last current trace/body reference. Trace/body reconstruction and counts pass;
the seven private trace/body/audit tables deny participant reads. Owner audit
procedures return the same unavailable error for foreign and missing runs.

The [upgrade check](../output/realtime/scale-48/audit-combat-paired-authority-resumed/upgrade-verification.json)
preserves all three reference worlds and 1,284 legacy blocks without rewriting
them. Further compaction creates two new-format blocks beside 428 legacy blocks
in one run, with exact full audit recovery. An explicit
[persistence restart](../output/realtime/scale-48/audit-combat-paired-authority-resumed/restart-verification.json)
then preserves all three worlds, complete audit and mixed block metadata.
Both resumed process phases exit 0 without OOM. These restarts validate recovery;
they are separate from timing and are not used as sustained-memory evidence.

## Live workload

The [candidate profile](../output/realtime/scale-48/combat-audit-profile/clock-profile-summary.json)
completes all declared correctness checks and both services exit 0. The workload
starts 200 colocated characters at 100 health with 200 reference controllers,
one SDK component observer with open inspection, no human input or inference,
and a declared ten-second 60 Hz interval. Each world/controller service has a
6 GiB memory limit and 3 GiB page-pool budget. Ordinary permanent deaths reduce
population to 100, so this is not a sustained-population trial.

Across 192 background blocks, the new profile records 38,360,320 plaintext bytes
and hashes their 4,545,341 compressed bytes. The largest block has 3,675,498
plaintext bytes. Normal builds omit these diagnostic byte counters and timers.

| Background archive phase | Before total / maximum | Candidate total / maximum |
| --- | ---: | ---: |
| Digest | 556.21 / 55.60 ms | 44.97 / 6.60 ms |
| JSON encoding | 170.84 / 16.43 ms | 163.95 / 15.78 ms |
| Compression | 88.46 / 11.59 ms | 88.85 / 12.71 ms |
| Complete encoder | 873.65 / 85.01 ms | 352.52 / 37.39 ms |

Both profiles encode 192 blocks but perform different asynchronous physical work.
Clock counters record 55.7% missed slots before and 46.4% afterward; timers,
changed requests and different event batches prevent treating that as an isolated
capacity comparison. Largest physical execution reaches 86.46 ms before and
78.85 ms after; audit append reaches 30.58 and 27.72 ms. The remaining encoder
and physical bursts still exceed a 60 Hz interval.

The [normal release](../output/realtime/scale-48/combat-audit-release/stack-analysis.json)
uses the same declared workload and all four paused verification flags, without
profiling timers. All paused checks and complete audit recovery pass. Both
services exit 0 without OOM. This run ends at 10,109 simulated milliseconds with
100 survivors and 65,967 verified audit events.

| Normal release diagnostic | Reference 47 | Candidate 48 |
| --- | ---: | ---: |
| Clock wakes / missed slots | 326 / 274 | 313 / 293 |
| Missed-slot fraction | 45.7% | 48.3% |
| Deadline execution plus queries p95 bucket | 50–100 ms | 50–100 ms |
| Deadline execution plus queries p99 bucket | 100–250 ms | 250–500 ms |
| Scheduled queue p95 / p99 buckets | 5–10 / 50–100 ms | 10–50 / 100–500 ms |
| Sampled backend CPU | 16.88 s | 16.18 s |
| World outgoing wire bytes | 18,441,970 | 21,177,207 |

The normal result is mixed: lower sampled CPU accompanies worse clock cadence,
tail latency and wire volume. Archive maintenance uses 415.96 ms WASM across
193 callbacks versus 711.36 ms across 189 previously, but the asynchronous event
work differs. Physical action-actor loads are 10,400 versus 10,000. Counters
include setup/cleanup; nearest one-second samples bound the resource metrics.
These results do not establish an overall capacity gain.

The observer misses no physical update IDs. Delivery interval p95/p99/maximum
are 125/303/509 ms; physical update interval p99 is 331 ms. These are SDK
observations, not rendered FPS. The active-combat clock requirement still fails.

Peak RSS, including enrollment, is 1,381,339,136 bytes for the world,
760,877,056 for the controller and 535,752,704 for the relay, with no sampled swap.
The world WASM gauge reaches 238,616,576 bytes. World allocator allocated/resident
peaks are 563,509,072 / 1,213,136,896 bytes, and page-pool peak is 10,027,536 bytes.
Controller allocator allocated/resident peaks are 286,141,784 / 693,133,312 bytes.
These independently sampled gauges are not added to RSS and do not establish
a sustained memory plateau.

Sampled retained WAL endpoints are 103,587,837 → 162,336,420 bytes for the world
and 95,014,861 → 382,868,160 bytes for the controller. These are retained sizes,
not cumulative writes. Table gauges lag; paused diagnostics reconstruct exactly
50,662 experiences across 1,765 pages and 2,404 bodies. Their 23,367,069 logical
body bytes occupy 845,163 stored bytes. Six catalogs occupy 113,639 bytes for
200 references. There are no unreachable current catalogs/bodies, legacy indexes
or payload rows.

## Storage reserve and preserved failures

Completed compiler/incremental-cache cleanup raises measured free disk from
8,474,017,792 to 10,282,074,112 bytes. A later cleanup removes completed single-
link test executables while the first checker is stopped. Source, runtime
binaries, frozen evidence and database volumes remain.

[Completed block sharing](../output/realtime/scale-48/validation/completed-block-dedupe-result.json)
verifies 437 snapshot/audit/metrics files, sharing duplicate extents without
changing complete SHA-256, size, modification time, permissions or ownership.
Measured free disk rises from 9,116,950,528 to 10,077,847,552 bytes.

A later [expanded pass](../output/realtime/scale-48/validation/expanded-archive-block-dedupe-partial-result.json)
verifies 603 of 685 selected files, then stops when the kernel refuses a writable
open of an existing executable with `Text file busy`. That file is not changed;
its original error log remains. The completed files pass the same byte/metadata
checks, with observed free disk rising from 8,697,905,152 to 9,937,850,368 bytes.
This is explicitly a partial pass. No experiment artifact or volume is deleted,
and no allocation maintenance overlaps measured authority work. Resource guards
remain 8 GiB free disk and 3 GiB available memory.

The final [correctness summary](../output/realtime/scale-48/validation/correctness-summary.json)
and [documentation/source checks](../output/realtime/scale-48/validation/documentation-check.json)
verify six frozen source/binary manifests, both paired module hashes, the
workspace's normal source/build match and all nine service-stop records. The
nine records include three lifetimes of the same paired service; all exits are
0 without OOM. Existing development services remain running. Original checker
and block-sharing failures remain explicitly separate from successful checks.

The 216-character/30-minute and 2,000-character/8-hour gates, full model workload,
human input, movement/combat mechanics, client pacing and autonomous outcomes
remain open. These short reference-controller diagnostics do not satisfy them.
