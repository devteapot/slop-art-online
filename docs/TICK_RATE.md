# Tick rate: why Cullet at 216 players stepped at 40 Hz

Started 2026-11-13 on the dev-box (branch `tick-rate`, from main `2020ea1e6`). The [cullet-sweep acceptance](PERCEPTION.md#the-kept-sweep-a-law-that-reads-distance) left Cullet at 216 players at exactly 40.0 ticks a second with no tick body over 16.7 ms, while plan-test with the same players reached 59–60. This note records where the database thread's time goes, why boundaries were missed, the fix, and the subscription traffic per subscriber that the dev-box coordinator asked for alongside it (the Spark's `fast_ask` delivery delay in a 200-fighter battle).

## Measurement method

The baseline is main `29735dbe9`, selected at the start of the resumed work.
Both arms log the same per-tick frame diagnostic during profiling. The
baseline's instrumentation patch is saved with the raw evidence. Each
run starts a fresh scoped module on `tick-stdb`, joins 216 player identities
over real Rust SDK WebSockets, and places them in seven clusters of up to 31
at lot doors at least 40 m apart. The players walk circles with a new input
about every 1.5 s. The 30 s warm-up precedes a 120 s measurement window.
One passive owner SDK subscriber applies the mind service's fullest query
set without dispatching any model request. There is no game client, fight,
real mind service, observer or export load during the window.

The dev-box has an AMD Ryzen AI Max+ 395 with 32 logical CPUs and runs
SpacetimeDB 2.14.1, with clients on loopback. The series holds the shared
exclusive build gate to pause Blender batches. Each run waits for the
one-minute load to fall below 4, with a 20-minute wait limit. The series
log records the load before and after. Each run also samples host load
every ten seconds.

The tick body duration comes from the module's stopwatch. The server's
whole-call duration and scheduling delay have separate histograms.
The whole-call histogram has buckets at 10 and 25 ms around the 16.7 ms
threshold, so it can bound the share over 16.7 ms and the p99. The
server's scheduler histogram is the primary delay measurement.
`ticks.json` retains wall-clock start and end estimates and adjacent
gaps so a skipped slot remains visible even when the next invocation
starts on time.

`frames.json` counts every scene row in each served frame, even when
that row needed no write. It records each viewer's frame start and
scene size, rows per second and inter-frame percentiles. The summary
includes ticks that serve zero rows and pools consecutive frames within
each viewer to report cadence. These are times at the authority. Wire
arrival also includes serialization, network and SDK processing.

The server's counters cover all connections. The owner connection is
counted separately using its WebSocket and SDK counters, including both
row deltas for a keyed update. Player rates are the remaining totals
divided by 216. They estimate the mean subscriber, since the server
histograms have no connection label. Byte counts mix the server's
metered send size and the owner's wire counter in that estimate.
`metrics.json` and `series-report.md` retain reducer counts and times,
view materialization time, update CPU, message serialization time,
and queue gauges. Update CPU is the server's subscription evaluation
measure. The residual from whole-call time includes other executor work
such as read-set removal and commit.

## Resumed series

The 18 November 2026 series ran from 19:54 to 20:35 UTC. All twelve runs
started below load 4. The measured candidate was `b5e2f3ef9`. The ready
sample held about 43 seen character rows on Cullet and 26–27 on plan-test.
Tables show medians across the three runs per arm, with floor and observed
tick counts summed across runs.

| World | Arm | Runs | Start → end load (1 min, each run) | Ticks/s | Body >16.7 ms % | Body p99 ms | Frame rows/tick p10/p50/p90 | Ticks at floor | Scene rows/s/player | Viewer frame p50/p90 ms |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| cullet | branch | 3 | 3.52 → 2.49, 3.64 → 3.30, 3.11 → 4.20 | 59.56 | 0.00 | 5.60 | 806/1195/1582 | 0/21,458 | 327.8 | 117.3/167.8 |
| cullet | main | 3 | 3.68 → 3.52, 2.34 → 3.64, 3.38 → 3.11 | 39.85 | 0.00 | 8.58 | 2458/2478/2496 | 0/14,332 | 457.0 | 99.9/100.6 |
| plan-test | branch | 3 | 2.36 → 2.34, 2.76 → 3.38, 3.29 → 2.62 | 59.99 | 0.00 | 4.16 | 802/2069/2191 | 0/21,619 | 457.6 | 33.5/49.9 |
| plan-test | main | 3 | 2.49 → 2.36, 3.30 → 2.76, 3.61 → 3.29 | 59.72 | 0.00 | 4.87 | 583/1922/2494 | 0/21,528 | 467.5 | 33.4/49.8 |

**Cullet reaches 59.50–59.60 ticks/s** at 216 walkers, up from 39.59–39.90.
The candidate still skipped 48–60 interval boundaries per 120 s window.
It delivered 129.2 fewer scene rows per player per second (28.3%).
Viewer frame p50/p90 rose from 99.9/100.6 ms to 117.3/167.8 ms. The slowest
candidate run's p90 was about 216 ms. On plan-test the branch ran at
59.99–60.00 ticks/s. It delivered 9.9 fewer scene rows per player per
second (2.1%), with effectively the same p50 and p90 frame intervals.

### Subscription traffic

| World | Arm | All rows/s ∕ messages/s ∕ kB/s | Player mean rows/s ∕ messages/s ∕ kB/s | Owner rows/s ∕ messages/s ∕ kB/s |
|---|---|---:|---:|---:|
| cullet | branch | 23,636.3 ∕ 2,506.3 ∕ 1,570.75 | 109.1 ∕ 11.5 ∕ 7.23 | 76.9 ∕ 24.2 ∕ 8.16 |
| cullet | main | 24,231.1 ∕ 2,990.1 ∕ 1,609.62 | 111.8 ∕ 13.8 ∕ 7.42 | 72.3 ∕ 20.3 ∕ 7.46 |
| plan-test | branch | 9,390.5 ∕ 3,268.1 ∕ 618.10 | 43.4 ∕ 15.1 ∕ 2.85 | 19.7 ∕ 8.1 ∕ 2.15 |
| plan-test | main | 9,386.4 ∕ 3,272.3 ∕ 617.92 | 43.4 ∕ 15.1 ∕ 2.85 | 20.2 ∕ 7.8 ∕ 2.17 |

Cullet's whole tick calls took a median 638 ms per wall second on main
and 651 on the branch. Tick WASM time rose from 185 to 229 ms/s, including
sweep time rising from 82 to 109 ms/s. View call and materialization time
across all reducers fell from 292 to 265 ms/s. Tick subscription evaluation
CPU moved from 27.7 to 26.8 ms/s. On plan-test the corresponding figures
were 367 to 374 for tick whole calls, 120 to 128 for tick WASM, 47 to 65 for
sweeps, 128 to 128 for views and 17.3 to 17.5 for tick subscription
evaluation. These timers overlap. The Cullet gains came from spreading
work across more ticks. Total executor work per wall second did not fall.

### Per-run timing

| Run | Ticks/s | Body >16.7 ms % | Body p99 ms | Whole-call >16.7 ms bounds % | Whole-call p99 bucket ms | Scheduled delay mean ms | One / two / three-slot gaps |
|---|---:|---:|---:|---:|---:|---:|---:|
| main-cullet-r1 | 39.90 | 0.00 | 8.25 | 1.46–84.87 | 25–50 | 1.428 | 2378/2411/1 |
| branch-cullet-r1 | 59.60 | 0.00 | 5.60 | 0.00–78.49 | 10–25 | 1.339 | 7108/48/0 |
| main-plan-test-r1 | 59.72 | 0.00 | 4.87 | 0.00–12.30 | 10–25 | 1.666 | 7136/34/0 |
| branch-plan-test-r1 | 59.99 | 0.00 | 4.23 | 0.00–3.63 | 10–25 | 1.401 | 7202/1/0 |
| main-cullet-r2 | 39.59 | 0.00 | 8.72 | 2.98–83.52 | 25–50 | 1.858 | 2314/2429/11 |
| branch-cullet-r2 | 59.50 | 0.00 | 5.69 | 0.00–67.05 | 10–25 | 1.921 | 7086/60/0 |
| main-plan-test-r2 | 59.86 | 0.00 | 4.84 | 0.00–12.96 | 10–25 | 1.634 | 7171/17/0 |
| branch-plan-test-r2 | 59.99 | 0.00 | 4.04 | 0.00–3.53 | 10–25 | 1.712 | 7204/1/0 |
| main-cullet-r3 | 39.85 | 0.00 | 8.58 | 2.11–84.57 | 25–50 | 1.369 | 2374/2406/6 |
| branch-cullet-r3 | 59.56 | 0.00 | 5.60 | 0.00–76.44 | 10–25 | 1.399 | 7100/53/0 |
| main-plan-test-r3 | 59.67 | 0.00 | 4.88 | 0.00–13.45 | 10–25 | 1.803 | 7129/39/0 |
| branch-plan-test-r3 | 60.00 | 0.00 | 4.16 | 0.00–3.13 | 10–25 | 1.242 | 7208/0/0 |

The server histogram puts at least 99.98% of invocation starts within
5 ms of their scheduled boundary in all twelve runs. The dominant main
Cullet gap was a skipped boundary, despite the low invocation delay on
the boundary the server did schedule. The whole-call histogram gives
bounds because its buckets straddle the target. It cannot yield an exact
share above 16.7 ms. The body stopwatch provides the exact observed share
for its own scope.

Raw evidence is in `.local/tick/evidence/`, with load and run paths in
`.local/tick/series-resume.log`. The CLI log tail clipped some windows.
The full retained replica logs were recovered by database identity after
the series, stored as `full-profile.jsonl` and used to rederive each
run's ticks and viewer cadence. Original CLI data is retained. The trace
count agrees with the server's whole-call count within 15 ticks per
window, with slightly different capture endpoints. `series-report.md`
and `series-report.json` contain per-run tick gaps, server delay buckets,
reducer, view and subscription timings, and traffic. `frames.json`
holds per-viewer timing and counts.

### Verification and coverage

`just living-check` passed and `just living-generate` left zero diff.
The SDK sweep comparison matched all seven checkpoints and the look
comparison matched before and after reconnect, apart from the generated
player health tracked separately by the fixtures. `sweep_kept`,
`sweep_rollback`, `sweep_marks`, `tick` and `senses` passed. Main and
the candidate reproduced the same supplemental `doing_seen` far-guard
scene failure. The validation records retain those scene outputs.

These 120 s walking windows leave the 30-minute 216-character gate,
combat, rendered client freshness and the 2,000-character target
unverified. The passive owner probe exercises subscription delivery
without the live mind service's processing. The frame intervals measure
when the authority serves a frame.

## SpacetimeDB documentation and source consulted

Pinned: `spacetimedb = "=2.14.1"`, `spacetimedb-sdk = "=2.14.1"`; server image `clockworklabs/spacetime:v2.14.1`. The live docs' version selector reads 2.0.0. Where the docs are silent, the `v2.14.1` tag of `github.com/clockworklabs/SpacetimeDB` (commit `a0bf6be`) was read. The resumed runs used the same version of the server and SDK.

The scheduler anchors interval calls to intended times and skips missed
slots. The reducer API permits fresh instances, replays, concurrent
execution and memory that survives rollback. Keep the feedback in memory
only as an advisory cadence. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/),
[Reducers](https://spacetimedb.com/docs/functions/reducers/).

Procedural views rerun when their tracked reads change. Subscribers receive
deltas for changed rows. This favors pacing the existing indexed writes
and retaining the small scoped view reads. [Views](https://spacetimedb.com/docs/functions/views/),
[Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/),
[Performance](https://spacetimedb.com/docs/tables/performance/).

**Verified in the 2.14.1 source (read, not tested):**
- **One thread, one queue.** A WASM database runs every reducer, scheduled reducer and view on one executor thread (`WasmtimeModuleHost`, `crates/core/src/host/module_host.rs:496-503`: "Reducers are not executed concurrently"). A scheduled reducer is enqueued on the same instance queue as client calls (`call_scheduled_reducer` → `call_instance!`, `module_host.rs:3507`; the wait is the `reducer_wait_time` metric, label `"scheduled reducer"`). The thread shows up in `/proc` as `wasm-<database hash>`.
- **The tick's transaction includes its views, the commit and subscription evaluation.** `call_reducer_with_tx_inner` (`crates/core/src/host/wasm_common/module_host_actor.rs:1176-1343`) runs the reducer, then `call_views_with_tx` (every view whose read set the transaction wrote, `views_for_refresh`, `crates/datastore/src/locking_tx_datastore/mut_tx.rs:711`), then `commit_and_broadcast_event`, which commits and evaluates every subscription's delta on the calling thread (`eval_updates_sequential`, `crates/core/src/subscription/module_subscription_manager.rs:1347`) before handing the encoded updates to the send worker ("get this work off the main thread and over to the `send_worker`").
- **A refreshed view also pays to remove its prior read set.** Committing a refreshed view call drops its old read set with `remove_view_call` (`mut_tx.rs:455` and `:562`), which walks every table's index read sets in the database. This work is in no view timer: `view_total_time_usec` covers the call and materialization only.
- **The next tick is set after that transaction ends.** `call_scheduled_reducer_with_tx` (`crates/core/src/host/scheduler.rs:741`) reschedules an interval reducer after the call returns, at `next_interval_tick_after(intended, interval, now)` (`:837`): the first boundary after *now*, anchored to the intended time. A tick whose whole transaction ends after the next boundary loses that boundary.
- **Metrics** (`/v1/metrics`, per database; `crates/datastore/src/db_metrics/mod.rs`, `crates/core/src/worker_metrics/mod.rs`): `reducer_wasm_time_usec` (a reducer's or view's WASM time, by name), `view_calls`, `view_call_time_usec`, `view_total_time_usec` (by view), `view_calls_triggered_by_reducer`, `spacetime_reducer_plus_query_duration_sec` (a reducer's whole call: body, views, commit, subscription evaluation), `spacetime_txn_cpu_time_sec` / `spacetime_txn_elapsed_time_sec` (by kind and reducer), `spacetime_reducer_wait_time_sec` (queue wait), `spacetime_scheduled_function_delay_seconds` ("between when a scheduled function was due and when the scheduler began invoking it"), `spacetime_num_txns_total`, row counters by table. Subscription traffic: `spacetime_websocket_sent_msg_size_bytes` and `spacetime_websocket_sent_num_rows` (histograms per database, observed per message per client, `crates/client-api/src/routes/subscribe.rs:2064`), `spacetime_num_bytes_sent_to_clients_total`, `spacetime_websocket_serialize_secs`, `spacetime_websocket_pong_rtt_secs`, and the gauges `spacetime_subscription_send_queue_length` (the send worker's queue) and `spacetime_total_outgoing_queue_length` (all clients' outgoing queues). None is per connection.
- **The SDK** (`spacetimedb-sdk` 2.14.1, `src/event.rs`) gives a non-caller's row callbacks `Event::Transaction`, with no server timestamp; delivery delay must be timed from times inside the rows.

**Assumed:** that view cost per row and the read-set walk scale as measured on this host; that a later version may run reducers concurrently, as the docs reserve (nothing here depends on the single thread for correctness).

## Scheduling change

The old 2,500-row frame budget applied independently of the sweep. On Cullet
the heaviest sweep ticks refreshed a quarter of the players at once, then
could serve a full set of frames. Their body time fit inside 16.7 ms. The
combined reducer, refresh and commit could still use up the remainder of
the slot. A skipped boundary can therefore coincide with a small histogram
value for scheduler delay. The scheduler schedules the next future boundary
and measures delay against that boundary.

The branch spreads 200 ms sweeps over twelve evenly spaced phases by
character ID. Each sweep reserves budget for its observed scene size plus
the viewer. Frames use the remaining allowance, serving due viewers in
order of oldest frame. The oldest due viewer always gets a frame, including
on steps whose sweeps alone consume the allowance. The row estimate is a
workload proxy. Each scene row may induce several view rows or no database
write, and the first frame or a due sweep can take the step beyond the
allowance.

The controller starts at 2,500 rows, removes an eighth when two consecutive
tick starts are at least 25 ms apart and less than a second apart, and adds
two rows on other ticks up to 2,500. Its floor is 250. On the pinned server
the scheduled reducer's timestamp is sampled as it starts. Its spacing is
a signal for a missed boundary and includes executor contention. The
Prometheus histogram measures lateness relative to the intended time, and
the log-derived grid offset is approximate and wraps after one interval.

The new module memory holds only the allowance and last start timestamp.
After a failed transaction or a fresh instance it may admit a different
number of frames. It cannot supply projection inputs, suppress a sweep or
alter the write logic for a frame once admitted. The existing rollback
guard still invalidates the kept projection and requests full scene
comparisons. See [Module memory and rollback](PERCEPTION.md#module-memory-and-rollback).

## Data paths and costs

The sweep still runs the same indexed sight gather, projection and row
comparison for every due viewer. It returns their IDs, which costs one
temporary vector proportional to the number swept. The frame scheduler
looks up the scene lengths in the existing viewer map. More phases can
repeat chunk-body cache fills across ticks because that cache is shared
only within one sweep pass. Frames still read truth by creature ID and
use the existing per-viewer copies and view indexes. The cost changes via
how many scenes each tick sweeps and frames, and via the resulting view
refresh and subscription rates. There are no added database writes,
tables, indexes or subscriptions. Per-viewer row retention and access
rules are unchanged. The profiling-only frame log records work admitted
and can be disabled with the existing profiling flag.

## Interpreting the Spark's fast lane measurement

The 40 ms median, 3.1 s p90 and 12.8 s maximum are consistent with queueing
somewhere between issue and pickup. A 1 ms reducer body median has little
bearing on the end-to-end tail. The transaction after the body can hold up
a row before the send worker sees it. Subscription delta evaluation occurs
on the same executor and can extend that interval. After that, the send
worker and connection can accumulate a backlog while the authority
continues committing transactions. The SDK decodes and applies updates
before the row callback. In living-mind the callback sends
`Event::Fast` into its event channel, and the journal records
`picked_ms` after the event loop dispatches it and its spawned task begins.
If the Spark measured `picked_ms - issued_ms`, it includes this client-side
time. `issued_ms` itself comes from the authority's reducer timestamp,
ahead of the commit.

Correlate the same `(actor, issued_ms)` across row write, reducer return,
view refresh completion, commit completion, subscription evaluation
completion and send-worker enqueue. Then stamp send-worker dequeue,
connection queue enqueue/dequeue, serialization and socket write, wire
receipt, SDK apply and row callback, and mind event dequeue and task
pickup. Use monotonic deltas within each process and synchronized clocks
with known error across machines. Sample queue depth and oldest-item age
at the same stages. A large reducer-return-to-commit interval implicates
view and commit work. Commit to send-worker enqueue isolates delta
evaluation. Enqueue to socket write shows outbound backlog, and receipt
to pickup isolates SDK and mind processing. Align these measurements to
battle load and repeat with a passive owner subscriber so the passive
callback and real mind pickup can be compared. The walking workload here
has no 200-fighter battle or real mind service, so it cannot assign that
tail to one stage.

Source paths in the game are `living/authority/src/fast.rs`,
`living/mind/src/main.rs`, `living/mind/src/mind.rs` and
`living/mind/src/mind/fast.rs`.

## Frame freshness on Cullet (frame-fresh, not merged)

Recorded from branch `frame-fresh` (`66ca8a26f`, GPT-6.2 Sol, 2026-11-18), which was not merged: frame-views ([below](#frame-views-cues-and-tiers)) replaced it. Its code is on that branch; its evidence path below is in that branch's worktree.

`frame-fresh` starts from `cd2afe42e`. With the shared sweep and frame
budget, a viewer can receive updates to engaged and nearby characters
between deliveries of its whole scene. The sweep supplies distances to
characters already in sight. An unexpired combat move or visible activity
targeting a character promotes the visible pair in both directions.
Engaged frames become due at 33 ms and nearby frames at 50 ms. Direction
changes, new visible activities and fighting moves take precedence over
steady motion within the relevance group. Whole frames carry the remaining
characters, ordered by distance, and take priority when they reach 200 ms.
These are scheduling thresholds subject to the shared budget and the
availability of the sight sweep. Distance uses that sweep's last sample.
The player's own rows remain on their direct views.

The partial pass limits copy updates to the selected part of the scene.
Each body has a delivery cursor so moving between relevance groups preserves
pending updates. Health projections, combat-event expiry, experience lines,
senses and earshot run on the whole pass. Copy rows are read and written
by the existing keys. A tick gap discards speculative scene membership and
causes a full comparison. If there has been no new sweep, the scene comes
from the committed `perceived.viewer` index. Distance, targeting and
direction marks guide timing. The rows presented to each player still
come from the authority's existing sight rules and per-viewer copies.

### View work

The [views documentation](https://spacetimedb.com/docs/functions/views/)
recommends small read sets and describes incremental query-builder views.
In the pinned [2.14.1 execution path](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/wasm_common/module_host_actor.rs),
`run_query_for_view` records table-wide dependencies, accepts only
plain table rows and passes the result to the same materialization path
as a procedural view. The procedural views continue to read one sender
index key per stream. This preserves the narrow read set and sender
authorization described in [table performance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/) and
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/).
There are no new database rows, indexes or client subscriptions.

Changing any motion copy can still rebuild that sender's entire
`seen_bodies` result. The budget therefore charges the scene size for
a pass with pending motion, fighter or health changes. A doing-only pass
checks the doing range for that sender and charges its smaller result plus
possible additions. A pass with no marked scene change pays a minimum
charge for scheduler and maintenance work. A partial pass with only a
fighter or doing update leaves the motion view's read set untouched.
Distant changes are coalesced into whole passes so they cannot trigger an
extra motion-view rebuild during a nearby pass. Measure the effect using
`view_calls` and `view_total_time_usec` for each scene view.

The new scheduler state grows with currently perceived pairs and active
targeting moves. A target change triggers two indexed primary-key reads at
most, shared across viewers in the step. Scene cursor maintenance reuses
the indexed sweep results. A roll-forward can inspect all pairs in one due
viewer to select its work. The authority still bounds copy writes by the
shared budget, and each changed copy is exposed only to its own viewer.

### Measurement

`tick_cost.py` reports p50, p90 and p95 intervals pooled across
viewer/body pairs, both for all in sight and for engaged or within 8 m
at the last sweep. A pass counts a pair even when the current row needed
no write. This measures when the authority checks for new data. The
`--duel` fixture tracks separate first-delivery latency for structured
windups and visible activity over the duelists' Rust SDK connections.
Neither timing measures an 80 ms RTT path or renderer presentation.

#### 216-player results

The dev-box series ran 2026-11-18 from 21:18:10 to 21:59:46 UTC
under the exclusive build gate. The baseline was `cd2afe42e` with
measurement-only instrumentation and the candidate was `de8bd2fa2`.
Each arm ran three 120 s walking windows on Cullet and plan-test after
a 30 s warm-up. The fixture used 216 real SDK players in seven clusters
of up to 31 and one passive owner subscriber. Ready-state mean scene
sizes ranged from 43.1 to 43.9 characters on Cullet and 26.2 to 26.5 on
plan-test. Each run started below 4 on the one-minute load average.
The two additional Cullet windows lasted 30 s, with 214 walkers and
two stationary duelists.

The threshold was **missed**. Cullet's median fell from 59.50 to
59.46 ticks/s, with candidate runs spanning 59.35–59.47. Near-frame
p50 improved from 167 to 150 ms. The median p90 held at 233 ms, well
above the 100 ms target, and p95 rose from 251 to 266 ms. The
candidate's near p90 ranged from 233 to 318 ms. Plan-test near p90
rose from 50 to 66 ms and all-in-sight p90 rose from 50 to 100 ms.
The shared budget still charges an entire sender's motion view for
a single changed copy. Overdue whole scenes compete with partial passes,
and the candidate's 100 ms whole-scene scheduling interval also reduces
cadence on plan-test, where main commonly serves a whole scene every
33–50 ms.

Rows per tick count viewer/body pairs checked for delivery, including
unchanged rows and zero-delivery ticks. They exclude sweep rows. The
baseline profiler uses the last sweep's distance for the relevant
category. It does not classify out-of-range engagement separately.
The staged opponents were within melee reach in both arms. The
candidate also counts out-of-range visible targets as relevant.

| Run | Ticks/s | Engaged or ≤8 m p50/p90/p95 ms | All p50/p90/p95 ms | Rows/tick p10/p50/p90 | Load start → end |
|---|---:|---:|---:|---:|---:|
| main-cullet-r1 | 59.56 | 133/182/200 | 133/183/200 | 847/1167/1491 | 3.76 → 4.35 |
| branch-cullet-r1 | 59.46 | 134/233/266 | 167/234/267 | 596/915/1257 | 3.83 → 3.21 |
| main-plan-test-r1 | 59.98 | 33/50/50 | 33/50/50 | 796/1851/2148 | 3.21 → 3.09 |
| branch-plan-test-r1 | 59.95 | 50/66/67 | 50/100/100 | 0/1003/2133 | 3.09 → 3.78 |
| branch-cullet-r2 | 59.35 | 183/318/384 | 200/334/400 | 65/743/1256 | 3.78 → 3.96 |
| main-cullet-r2 | 59.50 | 167/233/251 | 167/233/251 | 635/886/1219 | 3.96 → 3.98 |
| branch-plan-test-r2 | 59.94 | 50/66/67 | 50/100/100 | 0/853/2253 | 3.98 → 2.93 |
| main-plan-test-r2 | 59.99 | 33/50/50 | 33/50/50 | 748/2056/2200 | 2.93 → 3.05 |
| main-cullet-r3 | 59.44 | 167/250/283 | 168/249/282 | 550/845/1135 | 3.05 → 3.58 |
| branch-cullet-r3 | 59.47 | 150/233/250 | 167/233/266 | 648/913/1188 | 3.58 → 2.49 |
| main-plan-test-r3 | 59.99 | 33/50/50 | 33/50/50 | 720/2063/2196 | 2.49 → 2.34 |
| branch-plan-test-r3 | 59.84 | 50/66/67 | 50/100/100 | 0/969/2110 | 2.34 → 4.84 |
| main-cullet-duel | 59.44 | 167/250/283 | 167/250/283 | 578/876/1116 | 3.98 → 3.36 |
| branch-cullet-duel | 59.45 | 167/250/284 | 200/266/300 | 569/803/1089 | 3.36 → 3.32 |

#### View refresh cost

The table reports medians from the three walking runs per arm.
Scene totals sum the six frame-delivered streams. The counters cover
SpacetimeDB view execution and materialization over the window.

| World | Arm | Scene views calls/s | Scene views ms/s | Motion view calls/s | Motion view ms/s |
|---|---|---:|---:|---:|---:|
| cullet | main | 2672.43 | 240.72 | 1734.14 | 140.81 |
| cullet | branch | 2565.73 | 229.66 | 1705.26 | 134.98 |
| plan-test | main | 3380.62 | 121.69 | 2969.87 | 100.95 |
| plan-test | branch | 3042.07 | 113.02 | 2627.43 | 92.57 |

On Cullet, aggregate scene-view work fell **4.6%** and motion-view
work **4.1%**. The median motion-view cost per refresh was nearly
unchanged at 80.2 µs on main and 80.3 µs on the candidate. On plan-test,
aggregate scene-view work fell **7.1%**, with motion-view cost per
refresh moving from 33.9 to 34.7 µs. The savings came from fewer
refreshes. An affected motion view still returns the same sender-scoped
rows through the same index key, and the experiment establishes no
gain in the cost of a single full materialization.

#### Cullet duel inside the crowd

Each run recorded 10 accepted strikes and 10 visible waves from their
opponents' SDK callbacks. Latency is the authority row's start time to
first receipt over loopback. With 10 observations, p90 and p95 both
select the largest sample under this percentile convention.

| Opponent row | Main p50/p90/p95 ms | Frame-fresh p50/p90/p95 ms |
|---|---:|---:|
| 350 ms strike windup | 117.8/325.2/325.2 | 137.3/288.9/288.9 |
| Visible action | 105.9/188.7/188.7 | 49.6/62.9/62.9 |

The visible-action stream was substantially faster in this fixture.
The windup median worsened and the tail remained too slow to support
a claim about timed defence over 80 ms RTT. The duel arms had one run
each. The experiment did not exercise remote latency, the rendered
client, the 30-minute gate or the 2,000-character target.

Raw evidence is under `.local/fresh/evidence/20261118-211530/` in frame-fresh's worktree.
`series.log` has timestamps and start/end load. Each run retains
SDK events, load samples, metrics and profile windows. The retained
replica logs restored the profile lines clipped by the CLI tail.
Their tick counts were 10–20 below the metrics counters because
the counters bracket a slightly wider interval. The table uses the
recovered profile's window. `series-report.json` holds per-view costs
and `duel-report.txt` holds the SDK latency samples' summary.

## Frame views: cues and tiers

Branch `frame-views` (2026-11-18, dev-box, Claude Opus 5.5 at high effort): an escalation. frame-fresh (GPT-6.2 Sol, above) did not reach the target, so under AGENTS.md ("Escalation") the task moved to Opus. The target (the general coordinator's decision): a frame interval of at most 100 ms at p90 for engaged others and others within 8 m, at 216 players on Cullet (43 in sight), keeping about 59.5 ticks a second or better; in a crowded duel, the windup and visible-action p90 within the contract's networked line (150 ms p95 at 80 ms RTT). All in sight may stay higher.

### What frame-views keeps from frame-fresh, and what it drops

- **Kept:** the engagements (`engaged_of`, frame-fresh's `engagements`: an unexpired move or visible act aimed at someone makes the pair engaged both ways, read again only for creatures whose rows were written); the sweep's distances handed to the frames (`frame::scene`); the profiling pair cadence (`frame_trace.rs`, extended with staleness); the duel fixture (`look_cost.py --duel`, gate-load's `duel` role) and `tick_cost.py`'s pair percentiles.
- **Dropped:** the relevance scheduler (engaged, near and whole-frame passes with per-body cursors) and its cost model. Its own measurement found the limit: in 2.14.1 any write to a viewer's copies re-runs that viewer's whole view of them, so a near pass costs a whole scene, and ordering passes cannot change that.

### Design

Two changes, documented in [Perception](PERCEPTION.md#cues-and-tiers-what-is-near-reaches-a-player-at-once-frame-views):

1. **Cues** deliver near and engaged changes without re-running any view: event tables (`seen_body_cue`, `seen_fighter_cue`, `seen_doing_cue`) filtered per subscriber by row-level security. Near and engaged pairs are cued at every tick (`CUE_TICKS` 1; every other tick by id was measured and was staler for little saving, below). Cost: one row per change per viewer it is near, independent of scene size.
2. **Tiers** cut what a frame re-runs: near copies live in three new tables (`motion_near`, `fighter_near`, `doing_near`), far ones stay in the old copy tables, and each perception view has two tiers, so a frame of the far creatures re-runs only the far views. Near copies follow at most every 500 ms, behind the cues.

**Bounds for dense crowds** (added after the review's battle arm was smoked, 2026-11-19, host load 15–60, indicative only): 200 fighters within 9 m and 16 walkers on Cullet ran at 2.5 ticks a second on main, 2.2 on the branch with cues off and 1.3 with cues on (about a million cue rows in 70 s: everyone near everyone, each change fanned out to about 200 viewers). So the near tier keeps at most `NEAR_MAX` (32): whoever is engaged with the viewer first, at any distance in sight and past the cap (the reviewer's condition; `near_tier.py`), then the nearest within 8 m, and a tick writes at most `CUE_ROWS_PER_TICK` (3,000) cue rows, shrinking with the frames' budget after missed boundaries (to `CUE_ROWS_MIN`, 300), engaged pairs first; the same smoke then wrote 3.7 times fewer cue rows. The cap was first 12; the post-review series' first Cullet run with it gave near motion (within 8 m) at 160 ms p90, since in a cluster of 31 within 3 m about 30 are within 8 m, so the cap is 32: the measured crowd's whole near neighbourhood, a sixth of a dense battle's unbounded fan-out, with the cue budget behind it. The dense battle is a prototype limit on main too; the series measures both arms.

**Why not tiers alone.** In the measured crowd (seven clusters of 31 within 3 m), about 30 of the 43 in sight are within 8 m, so a near view still holds most of the scene; refreshing it fast enough for 100 ms would cost what whole frames cost now. Per refresh, a view's cost also has a large fixed part (on the smoke runs about 40 µs of the 54 µs a 13-row far view took, against 85 µs for 43 rows), so many small views do not help either. Freshness for near changes has to come from something whose cost follows the changes, not the scene: cues.

**Why not cues alone.** The first smoke runs (cues, no tiers; host load 4–5, not a measurement) gave near motion at the SDK a p90 of 39 ms against 185 ms on main at the same load, but the cue traffic (24 messages a second per player against 10) shrank the frames' budget: all in sight went from 185 to 239 ms at p90, and whole frames from 217 to 384 ms. Tiers give the frames that time back.

### SpacetimeDB documentation and source consulted

Pinned 2.14.1 (server image, `spacetimedb` and `spacetimedb-sdk`). The live docs (version selector 2.0.0) were read for [views](https://spacetimedb.com/docs/functions/views/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [their semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics), [event tables](https://spacetimedb.com/docs/tables/event-tables/), [performance](https://spacetimedb.com/docs/tables/performance/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions) and the [SQL reference](https://spacetimedb.com/docs/reference/sql); the `v2.14.1` tag's own docs tree (commit `a0bf6be`) for event tables, [row-level security](https://spacetimedb.com/docs/how-to/rls) and [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations). Each was checked against the tag's source.

| Documentation says | 2.14.1 source (read, not tested unless noted) | Design implication |
|---|---|---|
| A procedural view re-executes in full when a row in its read set changes; keep read sets small (views). | `materialize_view_arg_hash` (`crates/engine/src/relational_db.rs`) deletes every row of the sender's result and inserts the new ones; `views_for_refresh` (`crates/datastore/src/locking_tx_datastore/mut_tx.rs`) matches each written row against the index keys each view read (`views_for_index_seek`, per column list and key). | A view's cost is its whole result. A `(viewer, near)` key separates two views over one table: a write re-runs only the view whose key the row has. |
| (not in the docs) | `ViewReadSets::merge` drops each refreshed view's old read set with `remove_view_call`, which walks every table's, column list's and key's view set in the database. | Every refresh pays for the database's whole read set: fewer refreshes matter as much as smaller ones. Six new views add 216 × 6 one-key entries. |
| Event tables: rows exist only in the inserting transaction, are broadcast to subscribers on commit and never stored; only `on_insert`; views cannot read them; RLS applies with the same semantics; the inserts are in the commitlog; v2 protocol only. | `is_event` in the datastore and `encode_v2_rows` (`EventTableRows`, inserts only); two different subscribe-alls, both read at tag `v2.14.1` (`a0bf6be`): the server's own `SELECT * FROM *` (`get_all`, `crates/core/src/subscription/subscription.rs`) filters `!t.is_event` and so leaves event tables out; the Rust SDK's `subscribe_to_all_tables` (`sdks/rust/src/subscription.rs` 200–218) sends one `SELECT * FROM <name>` per generated `ALL_TABLE_NAMES` entry, cue tables included, which is what the current docs mean by "subscribe-all helpers" including event tables. Each query of either kind is compiled with the caller's auth (`SubscriptionPlan::compile_plans` with `SchemaViewer::new(tx, auth)`), so row-level security applies to a non-owner whatever assembled it; `cues.py` subscribes both ways as a third player and receives no one else's cue (the Spark's review; the laptop's question). | Cues re-run no view and are not in the client cache. An owner identity bypasses RLS, so an owner using the SDK's subscribe-all would receive every player's cues: no program here subscribes all, and the mind service and observer name no cue table (`verify-client`'s `drive.py` fails if either changes). The generated list cannot leave them out without editing generated bindings. They do grow the commitlog (below). |
| RLS (experimental, `unstable` feature): a `client_visibility_filter` SQL rule with `:sender`; the docs recommend views instead, but event tables cannot be read by views, and the event-table page points to RLS for per-identity delivery. | The rule is compiled into each non-owner's query (`QueryHash` includes the caller); a `viewer = :sender` equality becomes a search argument (`PhysicalPlan::search_args`, `const_or_param_value`), so each inserted row is matched only to its viewer's query, through a delta index on `viewer` (`DeltaTableIndexes`). | Per-subscriber filtering of cues on the authority, with pruning per row. Verified live: `verify-client`'s `cues.py` (another identity, an anonymous connection and a query naming another identity receive none). |
| Subscriptions: one update message per transaction per client, a state delta; avoid overlapping queries. | `eval_updates_sequential` runs on the database thread inside the tick's transaction. | Each tick with a cue for a client is a message to it: cue messages are a per-tick cost. Near cues every other tick per viewer (`CUE_TICKS` 2) cut messages from 25 to 21 a second per player and made near cues staler (selection pair below), so they go every tick. |
| Automatic migrations allow adding tables, indexes, and columns at the end with a default. | Appending a column rewrites the table and disconnects every client (`crates/schema/src/auto_migrate.rs` 919–947, `AddColumns`); adding row-level security rules also disconnects everyone once (1315–1337); adding a table or a view does not (`AddTable`, `AddView`). | The near tier is three new tables, not a column (the first draft's `near` column was replaced after the Spark's review). The RLS rules still disconnect every client once: the rollout below. |
| Performance: split tables by access pattern; private tables cost no client traffic. | — | Copies stay private; tiers split one table's reads by key rather than duplicating rows. |

**Assumed:** that a later version's incremental query-builder views or event-table views would allow a simpler design (the docs defer both); that RLS keeps its 2.14.1 semantics until the module moves version (it is marked unstable).

### Row-level security, the kill switch and SpacetimeDB upgrades

Accepted conditionally by the general coordinator (2026-11-19): a failure here is a perception leak. So:

- **What is in use.** The authority crate enables `spacetimedb`'s `unstable` feature (`living/authority/Cargo.toml`) for `client_visibility_filter`: three rules in `frame.rs`, `SELECT * FROM seen_body_cue WHERE viewer = :sender` and the same for `seen_fighter_cue` and `seen_doing_cue`. The docs mark row-level security experimental ([RLS](https://spacetimedb.com/docs/how-to/rls); [event tables](https://spacetimedb.com/docs/tables/event-tables/), "Row-Level Security"). Main also enables the same feature for two procedures (`mind_act_checked`, `mind_reach`; docs/LIVING_CORE.md).
- **Every RLS-filtered table** (for the version-pin notes): `seen_body_cue`, `seen_fighter_cue`, `seen_doing_cue` (frame-views), `seen_body_copy` (battle-views, the public motion copies behind the `motion_tables_on` law) and `seen_character_copy` (battle-views, the mirror of a player's projections behind the `characters_table_on` law), each `viewer = :sender`, and no other; `verify-client`'s `drive.py` fails when the set of rules changes (`RLS_TABLES`). Each has its isolation case in the scene gate (`cues`, `motion_tables`). The near-tier tables (`motion_near`, `fighter_near`, `doing_near`) and the old copy tables are private and reached only through per-sender views. On a SpacetimeDB upgrade: run both cases on the new server before turning `motion_tables_on` or `characters_table_on` on; on a failure, turn them (and `cue_transport_on`) off. All three are value-only laws (`law_override` rows, docs/LAW_OVERRIDE.md): a switch applies at the next tick with no reinstall. Publishing a module that adds or changes a rule disconnects every client once (`auto_migrate.rs`), so such a publish happens at a merge window with the mind service restarted, never while the owner is in a play-test.
- **Tiers off, cues on** (`near_tier_on` off, `cue_transport_on` on): no creature is in a near tier, so no near cue is written; a creature engaged with a viewer is still cued to it through the far-tier path (each change at once, reconciled at the viewer's next frame), so in a walking crowd with no one engaged no cue row is written at all (the laptop's `frame-views-client-v2` checks this state). A valid state, not a recommended one.
- **Both off is main's code path** (since the short series' review): with `cue_transport_on` and `near_tier_on` both off, marks owe no cue and mark no target, the tick works out no engagement, and the sweep works out no near tier; what was kept for them goes once, at the change (`frame::DELIVERY`; `frame::tests::both_delivery_laws_off_take_main_s_path`, run by `living-check`'s `frame-tests` step). An engagement under way when they are turned on again is known from its next move or act.
- **The kill switch: two laws.** `cue_transport_on` off writes no cue; `near_tier_on` off (on by default) puts every copy in the far tier, the untiered views' tables, so a frame re-runs one view and frames are scheduled as before frame-views (no fixed per-frame charge). Both off is main's delivery; the post-review series found tiers alone, without cues, worse than main (near p90 338 against 165), so falling back means turning both off. The `cue_transport_on` law (`living/scripts/skills.rhai`, `Laws::cue_transport_on`; on by default since acceptance). Off: the authority writes no cue row, and near copies follow at every frame, so a client on the tiers alone sees what it saw before cues. `set_world_law cue_transport_on false` turns it off on a running world. A client reading the installed `skills` script (which the game client subscribes) should drop its cue overlays when the law turns off: a creature's last cue is otherwise shown until that creature's next row.
- **The permanent check.** `verify-client`'s `cues.py` proves the isolation (a third player, an anonymous connection and a query naming another identity receive no cue) with the law on, and that nothing is cued with it off. It is a case of the merge's scene gate (`living/tools/scene_gate.py`, case `cues`, group `client`: builds the SDK probe, launches a default-seed `verify-gate-*` world, runs `cues.py`), so every behavioural merge runs it.
- **On any SpacetimeDB upgrade** (server image, `spacetimedb`, `spacetimedb-sdk`): before the cues stay on, re-read the RLS and event-table pages for the new version; check in its source that a `:sender` filter still reaches each non-owner's subscription to an event table (`QueryHash` with the caller, `search_args` and `const_or_param_value` in this version), that a subscribe-all query still skips event tables, and that `unstable` still provides `client_visibility_filter`; then run `cues.py` on the new server, both phases, and the scene gate. Any failure: `set_world_law cue_transport_on false` on running worlds and the default off, until fixed. Also re-check that the views' read sets are still matched per index key (the tiers' saving) and whether event tables may be read by views (a simpler design).
- **The rollout.** The near tier adds tables and views only, but adding the three RLS rules disconnects every client once (`auto_migrate.rs` 1315–1337), and the mind service exits on a disconnect. So: one publish, with the paired client change, at a merge window and never during an owner session; restart the mind service after it; `cue_transport_on` is on by default since the acceptance series (the pair merge, 2026-11-19); `set_world_law cue_transport_on false` turns it off without a publish (but with the law-change freeze below).

### Data paths and costs

| Path | Reads | Writes | Recipients | Rate (216 walkers on Cullet) | Retained |
|---|---|---|---|---|---|
| Cue pass (`frame::cues`, every tick) | marks in memory; `body`, `fighter`, `doing`, `vitals` and `projected.by_viewer_body` by key, once per creature per tick (`Sources`) | event-table rows | the viewer only (RLS) | about 20 rows a second per player in the smoke runs | nothing in the database; one commitlog record per row |
| Far frame | the far copies' keys | far copies changed | far views' subscribers | at the frames' budget | copies as before |
| Near copies | the near copies' keys | near copies changed, at most every 500 ms | near views' subscribers | ≤2 refreshes a second per viewer, plus tier changes | as before |
| Tier change (sweep) | the creature's truth | its three copies (content and `near`) | both tiers' subscribers | when a creature crosses 8 m (9 m going out) | — |

Module memory: per viewer, its near set and pending cues (about the scene); per creature, the viewers it is near; per actor with an unexpired aimed move, its targets. The commitlog grows by each cue's row (about 100 bytes); the series records the database's disk before and after each window.

### First series (before the review)

The dev-box series of 2026-11-18/19, 23:38–00:32 UTC, under the exclusive build gate, on the worker's own `views-stdb` (v2.14.1). The candidate was `f9d909769` (the near tier as a `near` column, cues always on) with cues every tick. Main was `cd2afe42e` with measurement-only probes (`frame_trace.rs` and the change stamps; `.local/views/tools/instrument-main.py`). 216 real SDK players in seven clusters of 31 within 3 m, walking circles (a new input about every 1.5 s), one passive owner probe, 30 s warm-up, 120 s windows, three per arm per world, alternating order; then a crowded duel (two players 1 m apart in a cluster, alternating strike and wave every 3 s each) for 60 s, two per arm. Each run started with the one-minute load below 4 (2.4–4.0). Ticks a second are the server's own counter over the window; the CLI log tail clipped some windows, and the full profile came from the replicas' retained module logs (`recover-logs.py`). SDK freshness is the receipt time of a new motion segment (`t_ms` newer than the last one held for that body, by its view or a cue) less `t_ms`, at every third player, pooled; near is within 8 m of the receiver then. It includes loopback delivery and the SDK, not an 80 ms RTT. The 60 s selection pair before the series (one run each) compared cues every tick with every other tick.

| World | Arm | Ticks/s, median (range) | SDK near p50/p90/p95 ms | SDK all p50/p90/p95 ms | Far-pair frame interval p90 ms | Scene views ms/s | Subscription eval ms/s | Player rows/s ∕ msgs/s ∕ kB/s | Commitlog MB/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Cullet | main | 59.69 (59.67–59.72) | 93/167/189 | 92/166/189 | 184–216 | 158.0 | 27.7 | 110.8 ∕ 10.8 ∕ 7.3 | 3.23 |
| Cullet | cues + tiers | 59.30 (58.88–59.48) | 30/38/40 | 39/307/516 | 533–1300 | 100.8 | 39.0 | 110.9 ∕ 23.0 ∕ 8.2 | 3.06 |
| plan-test | main | 60.15 (60.13–60.18) | 38/57/63 | 38/57/63 | 50 | 100.1 | 18.8 | 43.0 ∕ 14.8 ∕ 2.8 | 1.53 |
| plan-test | cues + tiers | 59.73 (59.72–59.77) | 27/35/37 | 28/42/49 | 50 | 45.1 | 27.4 | 58.0 ∕ 19.5 ∕ 4.4 | 1.89 |

| Duel, Cullet (2 runs per arm, about 20 samples per stream per run) | Main p50/p90/p95 ms | Cues p50/p90/p95 ms |
|---|---:|---:|
| Opponent's windup, first receipt less `act_ms` | 109–113/149–183/181–183 | 27–33/36–39/38–40 (all by cue) |
| Opponent's visible act, first receipt less `since_ms` | 84–99/166–180/177–190 | 27–29/36–38/38–45 (all by cue) |

| Selection pair (Cullet, 60 s each) | Ticks/s | SDK near p90 | SDK all p90 | Player msgs/s |
|---|---:|---:|---:|---:|
| cues every tick | 59.37 | 34 | 177 | 25.2 |
| cues every other tick | 59.26 | 49 | 252 | 21.3 |

- **Near and engaged: met.** Near motion p90 38 ms against 167 on main; in the duel the windup and the visible act arrive in 36–39 ms at p90, so with 80 ms of round trip (40 ms each way) a windup reaches a client about 120 ms after the input, inside the networked line (150 ms p95).
- **Ticks: about 0.4 a second lower on both worlds.** Cullet 59.30 against 59.69, plan-test 59.73 against 60.15, with two-slot gaps from 0–2 to about 50 a window on plan-test. Cues' cost is host-side (subscription evaluation +11 ms/s on Cullet, messages per player doubled) and outside the frames' budget, which follows missed boundaries: frames lose the time.
- **All in sight: worse.** Far pairs' frames slowed (p90 533–1300 ms against about 200), so all in sight went from 166 to 307 ms at p90 on Cullet. Allowed by the target ("may stay higher"), but large.
- **Commitlog:** no net growth on Cullet (the near copies write less than the cues add); +0.36 MB/s on plan-test.
- **Every tick, not every other:** fresher at little more cost, so `CUE_TICKS` is 1.
- **Not covered:** an 80 ms RTT link, the rendered client, a battle, the 30-minute gate, 2,000 characters; RLS's own cost apart from the cue rows'. The post-review series measures those arms.

Evidence: `.local/views/evidence/20261118-233816-stopped-after-selection/` (the selection pair; the series after it was stopped and restarted to measure every tick) and `.local/views/evidence/20261118-234339/` (`series.log`, `series-report.md`, per-run metrics, profiles and SDK events). A first attempt at 23:36 failed at its first CLI call (the container's mounts were gone with a killed session) and measured nothing (`20261118-233647-failed-podman-exec/`).

### Post-review series (acceptance)

2026-11-19, 09:50–11:56 UTC, under the exclusive build gate, on `views-stdb` (v2.14.1). The candidate is `483c05b42`: the near tier in its own tables, engaged first and capped at `NEAR_MAX` 32, the cue budget, `cue_transport_on` set per arm with `set_world_law`. Main is `cd2afe42e` with the same measurement-only probes. The same crowd as the first series (216 SDK players, 7 clusters of 31 within 3 m, walking circles, 30 s warm-up, 120 s windows, three runs per arm alternating); ticks a second by the server's counter; full profiles from the replicas' module logs. Each run started below load 4 (2.1–4.0). The first Cullet runs of the branch, at a cap of 12, are kept separately (`20261119-095004-s2`): near p90 160 ms, which set the cap at 32; main's first Cullet and plan-test runs and the battle sweep's main arm come from that part of the window, the rest from `20261119-102415-s3` (both combined in `20261119-combined/series-report.md`).

Arms on Cullet: **main**; **tiers** (the tier views, the law off, no cue subscription); **cues off** (the tier views and the cue subscriptions, the law off: row-level security registered, no cue rows); **cues** (the law on).

| World | Arm | Ticks/s, median (range) | SDK near p50/p90/p95 ms | SDK all p90 ms | Scene views ms/s | Subscription eval ms/s | Player rows/s ∕ msgs/s ∕ kB/s | Commitlog MB/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Cullet | main | 59.86 (59.82–59.89) | 91/165/185 | 164 | 160 | 27.7 | 110.5 ∕ 10.9 ∕ 7.3 | 3.23 |
| Cullet | tiers | 59.66 (59.66–59.67) | 172/338/403 | 342 | 117 | 29.5 | 106.7 ∕ 8.1 ∕ 7.1 | 3.40 |
| Cullet | cues off | 59.63 (59.57–59.73) | 167/334/393 | 337 | 118 | 29.8 | 103.9 ∕ 8.2 ∕ 6.9 | 3.33 |
| Cullet | cues | 59.56 (59.52–59.62) | 30/38/40 | 288 | 109 | 40.3 | 116.2 ∕ 23.0 ∕ 8.5 | 3.48 |
| plan-test | main | 60.34 (60.30–60.40) | 36/50/54 | 50 | 106 | 19.8 | 43.2 ∕ 15.2 ∕ 2.8 | 1.54 |
| plan-test | cues | 60.05 (60.03–60.09) | 27/35/37 | 40 | 45 | 27.5 | 57.9 ∕ 19.6 ∕ 4.4 | 2.10 |

| Crowded duel, Cullet (2 runs per arm, about 20 samples per stream per run) | Main p50/p90/p95 ms | Cues p50/p90/p95 ms |
|---|---:|---:|
| Opponent's windup | 113–387/182–870/297–961 | 33–34/37–40/41–45 (all by cue) |
| Opponent's visible act | 66–184/249–799/287–1226 | 28–34/40–57/44–64 (all by cue) |

| Battle viewers: 200 AI fighters (`spawn_battle`), N players watching, 60 s, ticks/s | 0 | 1 | 4 | 16 |
|---|---:|---:|---:|---:|
| main | 59.98 | 59.97 | 59.22 | 53.69 |
| cues (cap 12) | 59.94 | 59.84 | 58.95 | 52.61 |
| cues (cap 32) | 59.95 | 59.94 | 59.02 | 52.94 |

| Battle of players: 200 player fighters within 9 m and 16 walkers (216 viewers), 120 s | Ticks/s | Near cues sent ∕ late, wait p99 ∕ max ticks | Engaged cues sent ∕ with an earlier near cue outstanding, max ticks |
|---|---:|---:|---:|
| main | 2.77–2.84 | – | – |
| cues | 1.87–2.17 | 29,200–35,525 ∕ 97%, 256 ∕ 410 | 14,230–15,132 ∕ 33%, 371 |

- **Near and engaged: met.** Near motion p90 38 ms on Cullet against 165 on main (target 100). In the duel the windup reaches the defender in 37–40 ms at p90 and 41–45 at p95, the visible act in 40–57 and 44–64; with 80 ms of round trip (40 each way) that is about 120–145 ms from the attacker's input, inside the networked line (150 ms p95), at its edge for the visible act's p95.
- **Ticks: 0.3 a second lower on both worlds.** Cullet 59.56 against 59.86, plan-test 60.05 against 60.34 (two-slot gaps 1–5 a window to about 40). Close to the target's "about 59.5" on Cullet; plan-test is not unchanged in tick rate, though it is fresher.
- **Row-level security's own cost is negligible here:** "cues off" (RLS subscriptions, no rows) against "tiers": subscription evaluation 29.8 against 29.5 ms/s, ticks within the runs' spread. The cue rows cost the rest: +10.5 ms/s of evaluation, 15 more messages a second per player, 0.07 ticks a second.
- **Tiers alone are worse than main** (near p90 338 against 165, all 342 against 164): with the law off every frame refreshes two views, each with its fixed cost, so frames come less often. The kill switch's off state is therefore a degraded fallback, not main's behaviour; a client on the untiered views in that state sees the same frames.
- **All in sight with cues: 288 ms at p90** against 164: far creatures' frames are slower (allowed by the target, large).
- **Commitlog:** +8% on Cullet (3.48 against 3.23 MB/s), +36% on plan-test (2.10 against 1.54).
- **The dense battle is per-viewer cost, as tick-rate found:** with no players, 200 AI fighters run at 59.98 ticks a second on main; 16 viewers inside, each seeing about 250 bodies, take it to 53.69, and 216 player fighters to 2.8. Tiers and cues do not move it (52.94 at 16, 1.9–2.2 with 216): the far tier still holds the whole crowd per viewer. In the battle of players the tick is overloaded, the cue budget sits at its floor and near cues wait (97% late, p99 256 ticks); an engaged pair's cue is never held by the budget (by construction and `frame::tests`), but a third of engaged cues went to a creature whose near cue had been waiting, up to 371 ticks (minutes, at 2 ticks a second). This is this track's core open problem: per-viewer frame cost at density.
- **Not covered:** an 80 ms RTT link, the rendered client (the laptop's `frame-views-client` is measured separately), the 30-minute gate, 2,000 characters.

- **Far tier: a known cost, accepted for now.** All in sight 288 ms at p90 against 164 on main (the reviewer, 2026-11-19): the client extrapolates far creatures along their segments, and far frames are slower because cues and the tiers' second view take their time.
- **plan-test's two-slot gaps (about 40 a window against 1–5): the frames' phases merging.** The late ticks served about 209 frames each against about 105 on the others (`frame cadence` lines; main's late ticks 132). The budget charged a frame its rows only, and with the tiers most frames are a far tier of a few rows, so all 216 viewers fit one step: after one late tick both phases of the 33 ms cadence came due together and stayed together, and every other tick re-ran every viewer's views (frames 4.7 ms in those ticks, 7.1 at most, against 2.8 and 4.6 on main). Cue fan-out (`tick.cues` 0.12 ms in late ticks) and subscription evaluation (+7.7 ms/s spread over every tick) were not it. Fixed with a fixed charge per frame, `FRAME_FIXED_ROWS` (16 rows, the views' fixed cost per refresh), while the tiers are on: the budget then spreads a crowd of small frames over the steps as main's full frames did. Measured in the short series below.

**Disk.** Each run's database was deleted by the harness at its end. After the series (11:57 UTC) the `clog/` and `snapshots/` of all 111 replicas on `views-stdb` (every database deleted) were removed, `module_logs/` kept for the recovered profiles (`.local/views/replicas-before-clean.txt`, `replicas-cleaned.txt`), and the server was stopped with SIGINT and started again to release files it held: the volume went from 30 GB to 1.4 GB, the host from 49 to 79 GB free.

### Short series: the all-off state and plan-test's gaps (`defc3e7bf`)

2026-11-19, 12:30–13:10 UTC under the exclusive build gate (`20261119-123014-s4/`), the same crowd and method, the candidate `defc3e7bf` (`near_tier_on`; the fixed 16-row charge per frame while the tiers are on). The diagnostic pair after it (14:04–14:11, gate held, load 1.5–4.1 at the starts) was outside the quiet window.

| Cullet, 216 | Runs | Ticks/s | SDK near p90 ms | SDK all p90 ms | Subscription eval ms/s |
|---|---:|---:|---:|---:|---:|
| main | 4 | 59.66–59.77 | 153–179 | 152–179 | 27.2–28.2 |
| all off, client on the tiers and cue tables | 3 | 59.57–59.66 | 190–207 | 189–205 | 27.0–27.6 |
| all off, client on the untiered views | 1 | 59.73 | 165 | 163 | 27.8 |
| cues (after the fixed charge) | 2 | 59.51–59.59 | 38 | 214–252 | 40.7–41.9 |

| plan-test, 216 | Runs | Ticks/s | Two-slot gaps a window | SDK near p90 ms |
|---|---:|---:|---:|---:|
| main | 2 | 60.16–60.18 | 1, 2 | 57 |
| cues (after the fixed charge) | 2 | 60.18–60.19 | 0, 0 | 34 |

- **(b) plan-test: fixed.** No two-slot gaps against main's 1–2; ticks equal to main's; near freshness 57 → 34 ms.
- **(a) the all-off state:** the module with both laws off equals main (ticks, freshness and subscription evaluation within main's runs) when the client subscribes as main's does. A client subscribed to the tiers and the cue tables pays about 24 ms at p90 near and all (190–207 against 153–179) with the same ticks and evaluation: twice the perception views per client (six tier views, three of them empty, against three), so every view refresh walks a larger read set, plus three RLS queries. So the switch's off state is main's on the authority; for a tiered client to equal main too, it would subscribe the untiered views while both laws are off (a client-side resubscribe on the law's change).
- **Cues after the fixed charge:** near 38 ms p90 as before; ticks 59.51–59.59.

### The paired all-off arm (`140df9653`) and the residual

2026-11-19, 15:54–16:14 UTC under the exclusive build gate (`20261119-155313-s6/`), Cullet at 216, interleaved, each start below load 4. The players subscribe exactly as the game client `frame-views-client-v2` (`4ff4dbded`) does with both laws off, which is main's client's query set.

| Arm | Near p90 ms | All p90 ms | Ticks/s | Subscription eval ms/s |
|---|---|---|---|---|
| main r1, r2, r3 | 154, 150, 182 | 153, 149, 181 | 59.84, 59.84, 59.80 | 28.65, 28.57, 27.25 |
| all off r1, r2, r3 | 171, 215, 201 | 171, 216, 201 | 59.83, 59.74, 59.78 | 28.07, 26.78, 27.05 |

Accepted by the reviewer as a known residual of the off state (Option 2), not fixed:
- **The residual:** near p90 at a median of 201 against 154 ms, all in sight likewise, ticks 0.05 a second lower, evaluation within main's runs. The off state delivers about 8% fewer frames (scene-view calls 1,877–2,172 a second against 2,099–2,411).
- **The cause:** the untiered views (`seen_bodies`, `seen_fighters`, `seen_doing`) read both the old copy tables and the near-tier tables, where main's read one: in the off state the near tables are empty, so each refresh pays an empty index read and every viewer's read set holds three more keys, which every view refresh in 2.14.1 walks (about 1–2 µs a view call: 72.6–72.8 against 70.4–71.8 µs).
- **Not taken:** reading only the old copy tables would make a client still on the untiered views lose every near creature while the tiers are on (an old binary during a rollout, or a reader not yet found).
- **The later fix:** the untiered views read the near tables only while `near_tier_on` is on, once a view can read a law cheaply: the Spark's value-only law path (`docs/LAW_REINSTALL.md`, branch `law-reinstall`), whose committed per-law override rows a view could read by key.
- **The r3 shape** of the earlier all-off arm (the frames' budget down to 725 rows, 61 seconds under 1,200) did not recur on the gated build: its lowest was 1,082 with at most 2 seconds under 1,200; main's lowest 1,268 with none.

**Who reads the untiered views today** (2026-11-19, besides the game client in the off state): the verify-client fixed suite (`drive.py`, the `SEEN` checks) and `cues.py` (which compares them with the tiers); the verify-player scenes reading them by SQL (`approach.py`, `drop.py`, `face.py`, `fov.py`); gate-load's players without `--tiers` (the series' main and all-off arms), its soak players (`gate_load/src/soak.rs`) and `living/tools/soak.py`; `living/tools/latency_probe` and `living/tools/perception_load`. Not the mind service nor the observer (`living/mind`, `living/viewer`), which read the tables as the owner.

### A law change freezes the world for about a second

Found by the laptop (`frame-views-client-v2`), confirmed in the source and by the Spark's measurement: `set_world_law` writes the override and then reinstalls the whole skill script inside the reducer (`install_source`: compile and full validation), on the database thread. Validation alone took 1.12–1.61 s on the laptop's worlds (the Spark: 963 ms on an island, 819 of it validation), and no tick runs meanwhile: everyone stops for about a second. Acceptable for a rollback; flipping `cue_transport_on` or `near_tier_on` on a live world costs the same. The fix is the Spark's value-only law path (`docs/LAW_REINSTALL.md`, branch `law-reinstall`): the compiled script kept, the committed override read by key, only dependent data invalidated; the two delivery laws are its first case, targeted under 5 ms. Built by the Spark after this merge; no separate path here. **Built on branch `law-override` (2026-11-19, [docs/LAW_OVERRIDE.md](LAW_OVERRIDE.md)):** the two delivery laws, the cover laws and `gaze_on` are value-only, read by `frame.rs` from `common::laws(ctx)` with one snapshot per transaction.

### Client change

The laptop owns the game client (`living/game`); nothing in it changes in this branch. The change, exactly:

- **Queries** (`living/game/src/net.rs`, the perception list): replace `SELECT * FROM seen_bodies`, `SELECT * FROM seen_fighters` and `SELECT * FROM seen_doing` with `SELECT * FROM seen_bodies_near`, `SELECT * FROM seen_bodies_far`, `SELECT * FROM seen_fighters_near`, `SELECT * FROM seen_fighters_far`, `SELECT * FROM seen_doing_near`, `SELECT * FROM seen_doing_far`, `SELECT * FROM seen_body_cue`, `SELECT * FROM seen_fighter_cue` and `SELECT * FROM seen_doing_cue`, in the same subscription as the rest of the perception set. The recipient is each player's own connection: RLS gives it only its own cues. The observer and the mind service subscribe nothing new.
- **Reads** (`find_motion`, `bodies`, `find_fighter`, `fighters`, `find_doing`): a perceived creature's row is the one in either tier. Keep three overlays keyed by creature id: `Moving`, `Option<Fighter>`, `Option<Doing>`. A cue's `on_insert` sets the overlay for its creature (`motion.id`, or `body`) when that creature's body is in sight, that is in `seen_bodies_near` or `seen_bodies_far`, for all three streams: a fighter or doing cue may bring a move or an act before that stream's tier row exists (its near copy follows within 500 ms), and that is intended; any insert, update or delete of that creature in the same stream's two tiers clears it; a reconnect clears all. The world's `cue_transport_on` law (in the installed `skills` script the client already subscribes) turning off clears all too. Show the overlay when there is one (`None`: no fighter row, nothing being done), else the tier row.
- **Elsewhere:** the late-row timing callbacks (`net.rs`, docs/LATENCY.md step 3) attach to both motion tiers and to `seen_body_cue`; the counts in `live.rs` add the two tiers.
- **Bindings:** regenerated here, additive: the six views, the three event tables and the three near-tier tables (private), with their types. No existing type changed.
- **Until the client moves:** it keeps working on the untiered views, but sees near creatures change at most every 500 ms (their copies follow at `NEAR_COPY_MS`). Land the client change with this branch, or before it.
