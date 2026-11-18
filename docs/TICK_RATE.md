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

## Frame freshness on Cullet

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

Raw evidence is under `.local/fresh/evidence/20261118-211530/`.
`series.log` has timestamps and start/end load. Each run retains
SDK events, load samples, metrics and profile windows. The retained
replica logs restored the profile lines clipped by the CLI tail.
Their tick counts were 10–20 below the metrics counters because
the counters bracket a slightly wider interval. The table uses the
recovered profile's window. `series-report.json` holds per-view costs
and `duel-report.txt` holds the SDK latency samples' summary.
