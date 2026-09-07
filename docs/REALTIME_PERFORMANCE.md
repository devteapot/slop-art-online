# Playable real-time performance

The current acceptance target is 216 living actors for 30 minutes at a 20 Hz
authority target, local input-to-authority latency below 100 ms at p95, no growing
queue and bounded active memory. Include a human input client and an observer;
measure browser frame pacing separately. Short seeded-controller trials are
diagnostics, not acceptance of this target or thousand-player capacity.

Baseline: the recovery pass reached 4.45 updates/s with 216 actors alive for a
declared minute. [Boundary evidence](CLIENT_AUTHORITY_BOUNDARY.md) records the
implementation, crash/timeout checks and remaining workload limitations.

## Actor profile and first candidate

`output/realtime/actor-profile-01/` separates action cloning, context construction,
validation, effects and physiology using opt-in host timers. Effects took 3.753
of 4.525 seconds of kernel advance time in the 20-second window. Cloning took
0.037 seconds and context construction 0.091 seconds. Those measurements rejected
the initial hypothesis that action cloning/context construction dominated.

`output/realtime/observation-profile-02/` then separated observation costs.
Visibility consumed 3.167 of 3.484 seconds of observation processing. Every
observation evaluated the law against all 216 actors. Both diagnostics preserve
normal gameplay and ordered evidence; profiling timers never affect state.

The first candidate adds a conservative distance filter only when the bundled
law source exactly matches its reviewed dependency contract and no applicable
overlay defines visibility. Retained candidates still execute the same Rhai law;
custom sources retain the full domain. Differential tests compare complete
observation state and ordered events, including dead bodies and custom laws.
The candidate still scans body positions in memory; it does not claim spatially
indexed clock processing or replace the broader regional work.

Command receipts are also deferred on the native clock path. A receipt read uses
the existing `(run, actor)` index; ordinary commands resolve their own receipts
for duplicate detection. Clock publication skips unchanged receipt collections.
The serialized state and table/interface shapes remain unchanged. Native storage
and command differential checks passed, including deferred export equivalence.

`output/realtime/candidate-01-60s/` reached only **4.60 updates/s** (284 updates in
61.751 seconds), all 216 alive, zero sampled controller faults. Clock WASM time
dropped from 19.99 to 11.97 seconds across the sampled minute, but dispatch and
view work kept the service saturated. This is not target acceptance. The same
48×36 scenario, persistent native controllers, eight world/four controller views
per identity and no inference/human/observer load were used. Exact artifacts,
metrics, source hashes and clean service-stop results are retained per run.

## Version-specific view invalidation

The current [view guide](https://spacetimedb.com/docs/functions/views/#query-builder-in-views)
describes incremental query-builder evaluation. The selected image was directly
verified as SpacetimeDB 2.10.0, while module crates remain pinned at 2.1.0.
The [2.10.0 host source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.0/crates/core/src/host/wasm_common/module_host_actor.rs#L169)
shows a different materialization path: `run_query_for_view` compiles the returned
query, records a **whole-table read set** for every source table, executes its base
plan and returns all results. Its own comment identifies the resulting full view
and query reruns on any source-table change. `call_view_with_tx` then materializes
those rows. Ordinary SQL subscriptions and query-returning views must therefore
not be equated on this pinned host.

In candidate 01, the experience view ran 40,824 times and consumed 16.31 seconds
including materialization, despite only 0.66 seconds inside its WASM function.
The next candidate uses a procedural `(run, actor)` indexed range for that view,
which permits the host to track the actual actor-scoped read set. Authorization
still comes from the authenticated grant and controller bootstrap. It adds no
payloads, recipients or retention, and leaves the original raw trials unchanged.
The receipt/read views remain indexed procedural views for the same reason.

The earlier boundary note's assertion of incremental experience-view evaluation
described the intended behavior from current documentation; it is not supported
by this versioned-source evidence. These results take precedence for the current
runtime. Source copies used for the investigation are retained under
`output/realtime/runtime-source-v2.10.0/`.

`output/realtime/candidate-03-60s/` tests that indexed procedural experience
view: **6.96 updates/s** (426 updates / 61.195 seconds), all 216 alive, zero
sampled controller faults. Experience-view calls fell to 9,383 and total view
time to 4.97 seconds. Dispatch consumed 28.07 seconds of WASM CPU and clock
processing 15.25 seconds; the target remains unmet. Population, scenario and
subscription counts match candidate 01; no human or observer was included.
Both isolated services stopped with exit code zero.

## Definition parsing

`output/realtime/dispatch-profile-04/` adds dispatch spans to a 20-second
instrumented run. Reconstruction consumed 7.113 seconds across 2,211 commands
(mean 3.217 ms), versus 0.451 seconds of row reads, 0.762 of execution, 0.362
of state writes, 0.091 of delivery and 0.057 of audit insertion. Each command
parsed the same scenario, including 216 actors' starting data (832 KB when
serialized by the diagnostic script), and the script registry.

The next candidate caches parsed scenario and script definitions by their exact
complete row contents, with one entry per type and a 1 MiB input limit per entry.
Larger valid definitions still parse normally without entering the cache. Every
transaction still reads authoritative definition rows. Copy-on-write values
contain no table loaders; mutations detach, changed contents miss, and malformed
contents fail rather than returning an old value. The cache is disposable and
can neither authorize access nor supply state without matching the current row.
It adds no database rows or subscription recipients. The official
[performance guidance](https://spacetimedb.com/docs/tables/performance/) supports
focused rows and indexed access; this cache addresses measured parsing overhead
while the existing definition table remains authoritative. Tests cover exact
content changes, mutation isolation, failed parsing and oversized entries.

`output/realtime/candidate-05-60s/` reached **13.58 updates/s** (828 updates
/ 60.967 seconds), all 216 alive and zero sampled faults. The retained deadline
row reports 828 wakes and 383 missed 50 ms slots, with maximum lateness 972 ms.
Dispatch WASM CPU fell to 12.74 seconds while handling 8,525 dispatches; clock
WASM CPU was 19.38 seconds. Experience-view evaluation/materialization consumed
6.74 seconds. Both services stopped with exit code zero. This is still a short
controller-only trial and fails the playability gate.

The first parse cache still fetched and compared the complete definition string
on each transaction. The following candidate adds a small private
`sim_native_definition_version` row for scenario/scripts. Its SHA-256 digest
updates atomically with the body; all authoritative definition writes use this
path. Reads index the current version first, fetch/validate/parse the body only
on a miss, and use the same bounded copy-on-write cache. Older databases without
version rows use exact-body parsing until their next global save backfills them.
No identity, permission or mutable gameplay state comes from the cache. Tests
cover mismatched digests, content changes, cache-hit reads and mutation isolation.

`output/realtime/cached-profile-06/` measured the preceding exact-body cache:
clock load/advance/save averaged 4.35/8.38/8.91 ms. Dispatch reconstruction still
averaged 0.707 ms. `output/realtime/candidate-07-60s/` then tested scoped compiled
skill reuse and verified visibility input projection; it reached only 13.46
updates/s, 820 updates in 60.924 seconds, all 216 alive and zero sampled faults.
This does **not** establish a cadence improvement over candidate 05. The source
and dependency identity checks retain custom skill/law behavior and per-call
fault/budget isolation; visibility still executes the original Rhai hook.

## Live rendering work

The live observer now requests one optional inspector. Its authority projection
reads all run-indexed body/support/site rows for this bounded world, plus only
the selected actor's private state and latest trace. It omits captured leases and
receipts that rendering does not inspect. Differential tests compare the complete
render projection against full authority state and compare the selected context
against the original full inspector. Nonselected actors expose compact body
facts; explicit full diagnostics retain every context. Participant permission
checks remain separate and unchanged. Selection is authenticated and observer-only.

A private `sim_render_clock` follows physical/global commits, isolating live
renderers from the native head's next-event changes on unrelated local commands.
The participant rendering reader uses that same physical timestamp; command
transactions always use the canonical head. Observer history uses the latest
180 events before that render clock's event cursor, so newly admitted commands
appear on the next physical/global publication. Existing databases fall back to
the original head until the next global save.

This still uses one complete **presentation** JSON payload per live snapshot,
including the surveyed map and compact bodies. It is a bounded 216-actor bridge
for the playable gate, not the desired thousands-player subscription design.
Actual human/observer load and browser pacing must be measured before accepting
it; native projection equivalence alone is insufficient.

`output/realtime/candidate-09-60s/` measured the versioned cache without human or
observer load: **15.76 updates/s**, all 216 alive, zero sampled faults. Dispatch
WASM CPU was 7.29 seconds across 9,114 calls; clock CPU was 19.41 seconds.

## Delivery progress and controller journal retention

Controllers can now set their private delivery cursor on attachment/reconnect
and piggyback a durably ingested cursor on the next sequenced action dispatch.
The experience view returns only later retained rows; canonical personal
experiences, cursors and memory remain unchanged. Resetting the delivery cursor
can request the retained range again. The sender's grant, controller mode and
epoch remain authoritative, and a cursor ahead of the personal trace is rejected.
Older dispatch clients retain their original API and default full retained range.
An acknowledgement does not establish interpretation beyond the actual committed
controller state, and cannot recover evidence already outside the retained trace.

The controller journal now keeps 256–383 active rows per identity after normal
compaction, plus lossless 128-record compressed blocks. Blocks validate identity,
sequence, uncompressed length and SHA-256; archive insertion and active-row
deletion are atomic. Explicit `my_brain_journal` inspection reconstructs the same
ordered records. Compression failures retain the original rows and record a
blocked status. Historical compressed rows and WAL still grow: this bounds the
active journal tail, not all retained history or service memory indefinitely.
The long-run gate still requires actual memory measurement.

`output/realtime/functional-10/` found a real receipt-rotation failure at the
64-row boundary: the latest command's receipt was removed while earlier receipts
remained. The retained database was inspected separately under
`output/realtime/functional-10-diagnosis/`; no failed outcome was rewritten.
Indexed iteration includes transaction-local inserts and must not be treated as
sequence order. Receipt and captured-read rotation now sort explicitly.

`output/realtime/functional-10b/` then passed actual dual-service checks for
private-table denial, ungranted/observer cursor denial, cursor bounds, delivery
reset/replay, observer inspection and revocation, both transport reconnects, and
in-flight action completion without duplication. Four hundred explicit policy
replacements while paused crossed an archive boundary: all 417 journal records
remained visible unchanged, with zero subscriber deletions; 128 were archived
and 289 remained active. The archive was 3,652 bytes for 41,563 uncompressed
bytes. This is a bounded retention/transport test, not a performance trial.

`output/realtime/candidate-10-60s/` reached **15.99 updates/s**, all 216 alive and
zero sampled controller faults. It archived 198,400 journal records, retained
68,641 active rows (maximum 382 per controller) and stored 10.47 MB of compressed
history for 68.19 MB of original encoded records. Relay CPU fell to 24.32 seconds
and peak RSS to 391 MB; controller peak RSS was 743 MB. However, experience-view
calls rose to 177,714 and consumed 6.26 seconds. The three-column prefix/range
used by this candidate therefore did not deliver the intended reduction. The
next candidate restores the previously measured two-column actor index and
filters the bounded 256-row actor tail by delivery cursor inside the view.

The workload runner now optionally attaches one automated human input client
without a native brain, plus a separate observer. Both subscribe to
`sim_my_snapshot`, as Bevy does; the observer opens one inspector. Human actions
use `sim_client_intent`, with normal movement, eating and rest costs. Per-input
reducer completion latency and separate authoritative receipt outcomes are
retained. Per-second samples include received clock updates and presentation
bytes. Browser rendering/pacing remains a separate required check; automated
input is not labeled as a real person operating for 30 minutes.

`output/realtime/candidate-11-60s/` restored the two-column actor index and
reached **16.16 updates/s**, all 216 alive and zero sampled faults. Experience
views fell to 25,751 evaluations and 3.84 seconds. The controller service did
not exit within the runner's 30-second stop timeout and recorded exit **137**;
this was a forced stop, not a graceful shutdown. The runner now treats nonzero
service exit status as failure.

`output/realtime/provisioned-216-v1/` defines a distinct long-run fixture. It
preserves the crowded map, 216 actors, ordinary mechanics and AI policies, but
provisions food renewal, charger generation/capacity and charger-use access for
copied actors. Actor 3 is an ordinary biological human with food and a sheltered
adjacent movement route. The maximum duration is 2000 seconds. The generator
retains a source hash and change manifest. These provisions do not establish
survival; that requires the actual authority workload.

`output/realtime/mixed-12-60s/` used that fixture with 215 native brains, one
automated human client and one observer inspecting the human. It reached only
**4.15 updates/s**; all 216 survived, zero sampled controller faults, and all
112 human inputs had successful reducer completions and receipts. Completion
latency was **1456 ms at p95**, failing the target. Both services exited zero.
The clients received 137.95 MB of presentation JSON, excluding protocol framing.
The snapshot view ran 4,546 times and consumed 33.79 seconds, while each client
received only 370 changed snapshots. Native action admission updates scheduling
fields in the actor-support rows read by both renderers, invalidating expensive
projections even when the resulting picture does not change.

The next candidate separates private presentation support (arena, lifecycle,
body, materials and reproduction offer) from scheduling remainders, readiness
and dirty flags. Global physical commits reconcile one support row per actor;
local action admission updates only canonical scheduling state. Observers use
run-indexed presentation support and participants use point reads for their
local projection. Existing databases fall back to canonical rows until their
next global commit. Access grants and private inspector scope still apply.
This follows the official [focused-table guidance](https://spacetimedb.com/docs/tables/performance/)
and [index guidance](https://spacetimedb.com/docs/tables/indexes/), checked against
the pinned SDK. It adds O(population) retained support rows and no new public
subscription surface; the broader rendering JSON design remains a limitation.

The following payload candidate also avoids constructing the skill catalog for
presentation contexts (the renderer discards it), while the full context used by
model/participant reads remains unchanged. The render payload's `participant`
field becomes the existing explicitly labeled participant status projection.
Bevy uses the separately rendered player facts; full subjective context and
experience delivery remain available through the participant protocol's views
and explicit reads. This removes a redundant full context and 256-experience
copy per human frame, not canonical evidence or reconnect recovery.

`output/realtime/mixed-14-60s/` tested presentation support separation alone:
**4.61 updates/s**, 216 alive, zero sampled faults, all 111 human inputs accepted,
1166 ms completion latency at p95, and both service exits zero. Snapshot views
still consumed 32.91 seconds across 4,447 calls. This did not resolve the main
invalidation source. The retained [2.10.0 transaction source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.0/crates/datastore/src/locking_tx_datastore/mut_tx.rs#L448)
confirms that a range scan records a whole-table view dependency. In particular,
the observer's recent audit range was invalidated by every unrelated append.
The next candidate reads its exact contiguous 180 event IDs by primary key,
bounded by the physical render clock. It returns the same ordered tail and adds
no rows or recipients. These extra point lookups trade a bounded per-frame read
cost for removal of broad audit-table invalidation on the pinned host.

`output/realtime/functional-15/` passed all 15 dual-service boundary checks after
the projection changes, including scope/revocation, reconnect and unchanged
archived journal reconstruction. `output/realtime/mixed-15-60s/` then reached
**14.41 updates/s**, all 216 alive, zero sampled faults, all 102 human inputs
accepted and **376 ms p95** completion latency. Both services exited zero. The
snapshot view fell to 2,180 evaluations and 11.96 seconds; human maximum frame
size fell to 36,105 bytes. Neither cadence nor latency passes the playability
gate. `output/realtime/mixed-profile-16/` retains an instrumented follow-up.

The next candidate introduces `sim_my_render_snapshot` and
`sim_my_render_events`. Bevy and the measured clients subscribe to both in one
subscription. Frames omit history; individually stable event rows deliver the
same recent observer audit or the participant's own memories, with the existing
provider redaction and no additional permission. The full snapshot view remains
available for compatibility and comparison. The observer event view reads only
the render clock and exact recent event keys; participant history reads only the
actor's private memory row. Revocation clears both views and reconnect receives
the retained current range. Canonical historical evidence is unaffected.

This uses the official [incremental subscription contract](https://spacetimedb.com/docs/clients/subscriptions/)
with the pinned host's procedural point-read behavior. It retains no additional
canonical history rows: materialized view rows are bounded to 180 observer
events or the ordinary personal-memory limit per viewer. Full frame bodies
remain a measured limitation; unchanged history is no longer retransmitted
inside them. Client byte measurements include inserted event bodies separately
from frame bodies; wire metrics also include protocol/removal overhead.

`output/realtime/functional-17/` passed 16 actual dual-service checks, including
reconstruction of both observer and participant snapshots from the two new
rendering views and observer revocation of both views.

`output/realtime/mixed-17-300s/` kept all **216 actors alive for five minutes**,
including the cold-weather transition. It is a browser diagnostic, not a clean
single-observer comparison: it included an additional Bevy observer, switched
from a software to a hardware browser identity, and the host session list
performed whole-World exports every five seconds. The pinned host may continue
refreshing disconnected materialized views until cleanup. The measured full
window reached **9.77 updates/s** and **960 ms input completion at p95** across
514 automated inputs. World/controller peak RSS was 1.83/0.88 GB; retained WAL
was 1.55/3.25 GB. Both services exceeded the 30-second shutdown timeout and
recorded exit **137**, without OOM. Post-stop logs retain the shutdown messages
and database-lock release; this is not graceful-shutdown acceptance.

The actual Bevy history panel displayed incremental event rows. Chromium's
SwiftShader CPU backend averaged 8.24 rAF frames/s. After following the official
[headless GPU guidance](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/gpu/using-gpu-hardware-in-headless-chrome.md),
ANGLE verified the AMD Radeon 8060S/RADV Vulkan adapter: **59.40 rAF frames/s**
over 113.01 seconds inside the active workload, 16.8 ms p95, 33.5 ms maximum,
and no recorded long tasks. Screenshots, console/adapter records and raw frame
samples are retained. This is browser callback pacing, not physical display or
input-to-photon latency. The browser and development host were closed afterward.

The next host change reads the native run header for session-list metadata,
instead of exporting World for tick/stopped fields. Legacy normalized worlds
retain their compatibility fallback. This routine UI path was separate from the
background export loop, which was disabled during the browser diagnostic.

`output/realtime/mixed-17-clean-60s/` isolates the incremental-history change
with one SDK human input client and one SDK observer, no browser or development
host. Its 60.501-second window reached **14.59 updates/s**, all 216 actors alive,
107 accepted human inputs, no controller faults, **449.64 ms input completion at
p95**. World/controller peak RSS was 1.265/0.764 GB and retained WAL was
489/877 MB. Both services exited 0. Rendering views consumed 8.76 seconds in
2,210 invocations; physical clock reducer execution including queries averaged
39.39 ms. This remains below the 20 Hz / 100 ms target and is not a longevity
acceptance. The runner now retains post-stop logs as well as pre-stop logs.

The session-list host fix builds successfully. It follows the official
[index guidance](https://spacetimedb.com/docs/tables/indexes/): native run headers
have an existing primary-key index, so each known run requires only its tick and
stopped columns. No new index, subscription or retained data is introduced.

`output/realtime/actor-profile-18/` adds diagnostic storage subspans. Across 271
clock updates, participant persistence took 0.841 seconds of 1.536 seconds in
row saving; auxiliary rows took 0.377 seconds. Audit saving took 1.450 seconds,
including 1.005 seconds in compression. These nested timings must not be added
together. This profile included host-check startup exports; the last startup
and metadata checks overlapped tick 5, so it is not a clean throughput comparison.
The three corrected authenticated POST metadata requests returned the expected
run/tick/paused fields with no export counter increment between the retained
before/after metrics. Earlier test requests used the wrong method/header and
failed 405/403; the final harness's paused-world assertion failed because the
workload had started. The host was terminated after each attempt.

The next participant-save change reuses current-format experience metadata when
the evidence collection is the identical retained transaction snapshot. Activity
and controller changes then avoid loading/reconciling unchanged experience rows.
Changed evidence and legacy formats keep the original reconciliation path.
This uses the same private tables, indexes and subscription recipients, with no
new retention or gameplay rules. A focused lazy-loader check requires unchanged
history to remain unloaded and checks that legacy/changed history cannot reuse
this path. Actual-authority validation and performance measurement are pending.

`output/realtime/functional-19/` passed all 16 actual dual-service checks for
that participant-save change, including finite physical execution, policy and
transport reconnect, observer/personal render equivalence, revocation, delivery
cursor retention/recovery and private-table denial. Both services exited 0.

`output/realtime/mixed-19-60s/` measured the unchanged-evidence optimization:
**14.96 updates/s** over 60.448 seconds, all 216 alive, no controller faults,
102 accepted human inputs and **271.06 ms p95** completion. World/controller
peak RSS was 1.214/0.761 GB. This single window shows a modest cadence change,
not target acceptance. The world service exited 0; the controller service hit
the 30-second stop timeout and exited 137. Post-stop logs are retained.

The next view change uses the existing transaction-local deferred loader for
observer inspection and personal rendering. Previously these views eagerly
read and decoded every retained experience and the controller bootstrap before
rendering. A differential test across the existing world fixtures produces
identical human/observer live frames and participant status with zero experience
payload reads. The pinned 2.1 Rust read-only index handles compile with the same
loader adapter as reducer handles. Per the official
[view guidance](https://spacetimedb.com/docs/functions/views/), authorization still
comes from the caller grant; data is read through the view context, with only
actually used rows contributing dependencies. No cross-transaction value cache,
public raw table, new subscription or changed projection is introduced. Legacy
experience formats retain their loaders. Actual-authority validation is pending.

`output/realtime/actor-profile-20/` is a clean 20-second diagnostic with one SDK
human and one SDK observer. Its 702 render invocations took 0.907 seconds loading,
1.234 seconds constructing projections, 0.313 seconds serializing and 0.024
seconds building status. Participant row saving took 0.532 seconds over 311
clock updates (1.71 ms mean), versus 0.841 seconds over 271 updates in the
host-contaminated profile 18; these are diagnostic observations, not controlled
statistical attribution. Both services exited 0.

`output/realtime/functional-21/` passed all 16 actual-authority checks for deferred
render loading; both services exited 0. The subsequent presentation change
constructs just the inspector fields once; full participant/model context extends
those same fields with scene and catalog data. Rendered fields remain identical,
while the inspector avoids building discarded map, rule and protocol metadata.
The full simulation library suite passed 226 tests, with one existing ignored
test. Both authority modules and both probe binaries rebuilt successfully.
Combined storage/actual-authority checks and a clean minute are pending.

`output/realtime/functional-22/` passed all 16 actual-authority checks for the
combined rendering changes; both services exited 0. All 11 native storage tests
passed. The planned clean minute for version 22 has not run: the user asked to
reassess architecture and SpacetimeDB capacity before continuing incremental
optimization. Version 19 remains the latest clean measured implementation.

The reassessment must distinguish active actors, controller connections and
rendering clients. These runs have 215 automated controllers plus one human and
one observer, not 216 fully rendering human clients. The existing small-world
constraint also does not justify introducing regional shards prematurely.
Preserve client-side policy/mental processing, as already agreed. Review local
transaction work, incremental presentation, synchronous archival cost and the
controller/authority protocol before further tuning or partitioning.


## Raw authority: cause-specific food perception (23)

The user redirected work toward authority architecture and core-system design;
rendering is excluded from this comparison. See `AUTHORITY_EXECUTION_REVIEW.md`.
Food growth now refreshes site facts without implicitly re-observing every peer.
The full simulation suite passes 228 tests, one existing ignored. Both WASM modules
and authority probe binaries rebuilt. `output/realtime/functional-23/` passes all
16 actual dual-service checks (permissions, delivery, finite actions, reconnect,
retained journal and projection equivalence); both services exit 0.

`output/realtime/authority-22-clean-60s/` replays the exact hash-verified frozen
pre-change implementation, using the same crowded eight-site scenario as
`mixed-17-300s`, all 216 actors controlled by the separate controller instance,
no human input, observer, render subscriptions or inference. Enrollment and final
export are outside the active interval. No builds/tests overlap the measured
window. The 60.412-second baseline produces 972 physical updates (**16.09/s**),
216 survivors and no sampled controller faults. The world uses 35.30 CPU seconds,
controller 25.26 and relay 19.92; process RSS peaks including enrollment are
1.187 GB, 0.770 GB and 0.404 GB respectively. Mean scheduled pulse execution plus
query time is 26.69 ms. Both services exit 0. Per-reducer counts, subscription
bytes, table rows, allocator/pool/WASM gauges and retained WAL are in summary.json.

The earlier `authority-22-baseline-60s` is diagnostic only: build/test activity
overlapped measurement. Its sidecar records that caveat. The runner now accepts
`--implementation` for hash-verified frozen sources/artifacts and records its
actual driver and invocation separately, allowing baseline replay without
reverting the working tree. A short trial remains insufficient for sustained
20 Hz, low input latency or thousand-player capacity.


`output/realtime/authority-23-clean-60s/` completes the matching changed run:
60.410 seconds, 1,000 updates (**16.55/s**), 216 alive and no sampled controller
faults. World CPU is **31.35 seconds**, controller 23.40 and relay 18.61. World
RSS peaks at 1.184 GB, controller 0.755 GB and relay 0.392 GB, including enrollment.
Mean scheduled pulse execution plus query time is 23.11 ms. Both services exit 0.
Compared with the frozen baseline, world CPU falls 11.2% while cadence rises only
2.9%; this single pair does not establish statistical significance or sustained
capacity. The core-design correction removes unnecessary work, but does not meet
20 Hz or replace the pending clock/archival boundary changes.

Both scenarios initially place actors across nine positions, with occupancies
6, 6, 24, 24, 24, 24, 24, 36 and 48. Policies drive actions asynchronously, so
realized action counts differ: the sampled metric interval records 4,530 versus
4,468 controller dispatch reducers (about 75 versus 74 per second). World outbound
WebSocket metric deltas are 56.39 versus 52.11 MB. Final event cursors are 157,335
versus 125,594, including setup/cleanup; these are not isolated food-event counts.
Metric boundaries use the nearest one-second samples and can omit several pulse
commits; cadence uses the explicit probe window. Active-data and resource details
remain in each frozen summary. No input-latency or rendering result is claimed.

## Independent physical clocks (24)

The [implementation contract](INDEPENDENT_PHYSICAL_CLOCK.md) separates local
physical action opportunities, deadline-driven world maintenance and audit
compression. These are separate authority transactions, not parallel simulators.
Mode 24 is opt-in for paused native client-controller worlds. Existing running
worlds were not migrated.

`output/realtime/functional-24` passed all 16 actual dual-service checks, including
scoped access, finite action completion, transport reconnect, retained controller
journal history and render projection correctness. Both services stopped with
exit 0. This complements 231 passing simulation tests (one existing ignored) and
29 passing authority tests, including full/split kernel differential checks and
local attack/death/movement/recipient evidence comparisons.

`output/realtime/authority-24-clean-60s` froze the source, WASMs, probes, driver,
metrics and retained services. It uses the same 216 seeded controllers on the
48×36 map as `authority-23-clean-60s`: nine starting cells, 6–48 actors per occupied
cell, with neighboring crowd cells. There are no human, observer, render or fresh
inference connections and no exports during the active measurement. Controller
subscriptions retain their ordinary scoped frame/evidence/knowledge/receipt paths.
The 50 ms configured action interval is a target, not delivered cadence.

| Measurement | Previous 23 | Independent clocks 24 |
| --- | ---: | ---: |
| Measured wall time | 60.410 s | 60.423 s |
| Living actors at end | 216 | 216 |
| World-service active CPU | 31.35 s | 27.92 s |
| Controller-service active CPU | 23.40 s | 23.98 s |
| Relay active CPU | 18.61 s | 18.55 s |
| World-service peak RSS, including enrollment | 1.184 GB | 1.133 GB |
| World scheduled queue time, cumulative | 3.546 s | 3.771 s |
| World websocket bytes sent | 52.11 MB | 51.60 MB |

Mode 24 recorded 990 action-only transactions loading 58,416 actor instances
(mean 59.0, maximum 216), plus 72 full physical updates. Its 1,062 total physical
updates over the window combine two clocks and must not be read as 17.58 Hz of
whole-world simulation. The diagnostic clock row also counts enrollment and
cleanup full saves. The prior 1,000 updates likewise do not measure input latency.
World controller dispatch ran approximately 74.6 calls/s in the sampled window.

The deadline callback averaged 13.83 ms including its queries, versus 23.11 ms in
23; some deadline callbacks still execute full maintenance. Separate world wakes
averaged 59.95 ms over 48 calls, and 903 archive callbacks averaged 2.19 ms.
The action clock can also settle maintenance first, so wake count alone is not the
number of world phases. These averages do not describe tail latency. The trial
combines clock separation and asynchronous compression; it does not isolate their
individual contributions or establish a repeatable performance distribution.

The sampled world WASM peak was 148.44 MB, allocator allocated/resident peaks were
442.59/953.29 MB, and the retained WAL was 536.43 MB. At the end metric boundary,
900 audit blocks coexisted with 5,415 live audit rows and a pending archive wake;
55,073 native experience rows remained. Background compression can lag its 2,048
row target. Active history and total retained evidence growth are still separate
capacity limits. Both services exited 0; all 216 actors survived and no controller
fault samples occurred. Raw table, subscription, allocator and process evidence
is retained in the summary and metrics, without attributing other databases' RSS
to this world.

### Input and persistence trial at 33 ms

`output/realtime/input-24-33ms-60s` uses the same scenario with 215 seeded
controllers and one SDK-driven human actor. It sends ordinary explicit
`StartAction` requests, moving between surveyed adjacent cells at up to 2/s,
eating and resting under the original costs. It has no renderer, observer or
fresh inference. This is a separate workload/interval, not an isolated causal
comparison against the controller-only 50 ms run.

Over 60.448 seconds, all 216 actors survived with zero controller fault samples.
There were 1,503 local action transactions (24.86/s) and 72 full physical updates.
Local transactions loaded 68.3 actors on average, maximum 216. The configured
33 ms action schedule did not deliver sustained 30 Hz. All 107 inputs had accepted
receipts, completed reducer callbacks and an exact-request-ID execution notice;
none were missing or rejected. Input latency was:

| SDK measurement | Median | p95 | Maximum |
| --- | ---: | ---: | ---: |
| Send to reducer completion | 72.8 ms | 164.8 ms | 285.8 ms |
| Send to first scoped frame showing an attempt or success/failure | 93 ms | 331 ms | 573 ms |

These include local transport and delivery. An attempt notice is not animation
completion, a successful hit or a combat reconciliation measurement. Movement,
eating and resting do not establish precision combat performance. The current
latency fails the sub-100 ms p95 playability target even without rendering.

World/controller/relay CPU was 31.29/24.79/18.12 seconds; peak RSS including
enrollment was 1.158/0.765/0.384 GB, with no observed swap. The complete reducer,
queue, subscription, table and allocator measurements remain in `summary.json`.
Both services stopped with exit 0. Full world maintenance, dense local domains,
controller/delivery traffic and unbounded retained evidence remain limits; the
architecture change alone has not resolved tail latency or long-duration capacity.

After pause, the owner export validated every event from 1 through 129,293 across
compressed blocks and the live tail. `scripts/verify_physical_clock_restart.py`
then restarted only this experiment's stopped world service. The full paused
world and exact audit bytes matched, SHA-256
`b99b02b20105492451efdca7b647699865636c5ba5a14f1121d035b6b2bb7445`.
The maintenance origin of 60,002 ms and current time of 60,108 ms both survived,
preserving unsettled elapsed time. Recovery evidence is in `physical-restart/`;
original workload and shutdown artifacts remain unchanged. The recovery service
also stopped with exit 0. This is paused restart evidence, not an injected
mid-transaction crash or an outage catch-up trial.
