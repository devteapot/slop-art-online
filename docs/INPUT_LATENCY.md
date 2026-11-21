# Input response and fast-lane delivery

The targets are 300 ms p95 for N1 town orders and 150 ms p95 for N2 gate-seen responses. The [navigation rerun at `2ef3b238`](https://github.com/devteapot/slop-art-online/blob/2ef3b238/.agents/skills/verify-core/references/validation/2026-11-19-0408-nav-planner-arenas.md) reported N1 off-arm p95s of 485–1,851 ms and 3/20 unanswered stimuli in the N2 closed-gate off arms. The [dev-box walking series](https://github.com/devteapot/slop-art-online/blob/f9d909769/docs/TICK_RATE.md#interpreting-the-sparks-fast-lane-measurement) reports a 40 ms median and 3.1 s p90 from fast-ask issue to mind pickup, with about 1 ms median reducer body time. These are results from the earlier runs. The instrumented Spark measurements are below.

See [Movement mind](MOVEMENT_MIND.md), [Performance contract](PERFORMANCE_CONTRACT.md), [Perception](PERCEPTION.md), [Battle scale](BATTLE_SCALE.md), and [Mind harness](MIND_HARNESS.md) for the gameplay and workload definitions.

## Which paths the fixtures drive

- **N1 body** sends a direct `mind_act` HTTP request to the authority. It exercises the deliberate-act queue with no mind process in the loop. **N1 click** sends `human_act` using a real player's identity. Depending on whether the skill accepts deliberate acts, it queues the same kind of act or installs a one-shot graph and wakes its authority evaluator. The caller's HTTP response is an upper bound on that transaction's commit time.
- **N2** closes the gate while the subjects are away, then orders another walk. The stimulus used by the arena is the first geometric sight estimate on that walk. It is distinct from closure and from the authoritative `remembered` write. Ground marking runs in graph evaluation for both controllers, with a minimum interval of 900 ms between looks. The scheduled 200 ms sweep serves player perception and is a separate path. With `nav_belief` off, point steering can use the physical map without waiting for either kind of look. A turn that the scanner scores can also be ordinary steering. A walk can arrive without a qualifying velocity change in the two-second gate window.
- **Fast lane** starts at a perceived combat trigger. The authority can coalesce triggers and defer an issue. A mind receives the issued `fast_ask`, dispatches an asynchronous task, calls the fake provider and sends a patch or keep. Installation is an authority outcome. A following dodge or blow needs its own combat evidence and cannot be attributed to a patch from temporal proximity alone.

Main's N1 scanner starts its window at the **post-call** clock sample. The cited rerun uses the **pre-call** sample, which keeps a first response that happened before the call returned. The diagnosis retains both scores and also records wall time from the actual send to the authoritative body write. Segment timestamps can be re-anchored to earlier segment boundaries, so they serve the arena score rather than the transaction-time split.

## Instrumentation

| Stage | N1/N2 | Fast lane |
| --- | --- | --- |
| Stimulus | Pre-call clock tick plus wall send for N1. Physical gate close reducer or tick and geometric visibility estimate kept separately for N2 | First and latest coalesced trigger times. Trigger marker at the first waiting request |
| Sweep or authority look | Player sweep tick where applicable. Ground look and changed gate memory carry actor and gate ID | Immediate trigger evaluation on combat events, with waiting requests pumped on ticks |
| Write | Authority gate memory, experience and body writes. Experience IDs identify specific lines | Issued row write, joined by database, actor and `issued_ms` |
| End of tick body | Last marker after the tick's clock write when that tick emitted a trace | Same marker for scheduled issues. Used as a lower bound on commit |
| Commit and incremental evaluation | Lower bound from the end marker or last write. Upper bound from caller ack for direct HTTP or observer output for a subscribed write | Bounded together with delivery by write or tick end to mind callback |
| Send worker and socket queues | Per-database metrics give aggregate context. The observer timestamps output after the CLI decoded and printed it | Database queue depths at about 1 Hz. No per-ask enqueue, dequeue or wire receipt timestamp |
| SDK callback | CLI output bounds receipt, SDK apply and printing together. Player-input arm does not use the game client | Insert/update callback before enqueueing the mind event |
| Mind pickup and wake | No mind service. Graph install and matching revision at evaluation, or deliberate-act queue and start | Mind event dispatch, task start, provider admission/reply, patch send and reducer result |
| Authority result | Act attempt, terminal steering failure where it occurs, and velocity-changing body write | Patch entry, refusal, install, keep or expiry. Combat skill use and defence remain separate evidence |

Enable navigation with `nav_arena.py --input-latency`. It sets `latency_nav_from` to the first subject's ID, limits tracing to characters at or above that ID plus global gate changes, and restores the default zero on normal completion. Enable the fast path with `battle_diag.py --input-latency --fast-lane --fake-fast-patch`. It sets the authority's `latency_fast` law and the mind's `LIVING_INPUT_LATENCY=1` flag for the run. Both are off by default. The battle harness rejects combining its trace option with real models.

Authority markers use the existing module log. Each line carries the reducer start stamp in microseconds, the clock row's tick and time, a stage and correlation keys. For an in-flight tick the clock row can still hold its predecessor. The reducer name and matching `tick_end` marker recover the tick when recorded. The log record's `ts` is the host wall timestamp at the WASM log call. A log line can survive rollback. The client or mind evidence establishes visibility or a successful reducer result. The authority adds no table, index, view, column or subscription. The log endpoint requires [module-log access](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/client-api/src/routes/database.rs#L985-L1004). The off paths check cached laws and use no trace logging, while traced transactions read the clock row and emit logs only at the selected stages. Mind timestamps and a compact terminal outcome add no messages to the authority. Results written only on task exit can be absent at shutdown, so a missing outcome cannot prove a missing callback.

Use host wall times on one machine. For a distributed run, record the clock error before interpreting differences across processes. Keep negative stage differences visible. They can expose re-anchoring, measurement error or a geometric estimate that follows the actual look. The scanner reports p50, p90, p95 and denominators. Stage shares use the sum of that stage divided by the corresponding sum of end-to-end time on paired successes. Several intervals are bounds or overlap, so their shares need not add to 100%. Unanswered cases retain the latest observed stage. N2 shows whether gate memory was written and whether a qualifying motion response was observed within the arena window.

### SpacetimeDB 2.14.1

The [subscriptions guide](https://spacetimedb.com/docs/clients/subscriptions/) describes initial state and incremental replication. The [performance guide](https://spacetimedb.com/docs/tables/performance/) favors narrow indexed reads and subscriptions. [Event tables](https://spacetimedb.com/docs/tables/event-tables/) deliver transient rows at commit. This diagnosis uses existing logs to avoid adding rows to every transaction or changing a subscriber's query set. Persistent `fast_ask` rows still supply outstanding requests to a connecting mind.

- The [module host](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/wasm_common/module_host_actor.rs) runs the reducer and refreshes its views. The [subscription actor](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/subscription/module_subscription_actor.rs#L2041-L2123) downgrades the committed mutable transaction and evaluates its delta. That visibility boundary differs from timing a durable commitlog flush.
- The [subscription manager](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/subscription/module_subscription_manager.rs#L1347-L1395) enqueues computed updates after incremental evaluation. Its send worker broadcasts them to clients. The [worker metrics](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/worker_metrics/mod.rs#L701-L757) expose per-database queue depths and reducer-plus-query histograms. `spacetime_subscription_query_execution_time_micros` is for **initial** queries. [Database metrics](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/datastore/src/db_metrics/mod.rs#L106-L160) count incremental evaluations and matches. These series contextualize the combined interval. They cannot divide it per row or distinguish per-client queue age. Subtracting independent percentile estimates would not give the percentile of a stage.
- The [WebSocket server](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/client-api/src/routes/subscribe.rs) records serialization time, sent size and rows, and pong RTT. The [SDK WebSocket loop](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/websocket.rs#L444-L475) parses binary messages before putting them on the SDK's incoming queue. The [SDK transaction event](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/event.rs) for other callers gives the callback no server timestamp or socket receipt stamp. The split therefore bounds post-commit delivery and SDK decode/apply together. The [WASM log host call](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/wasmtime/wasm_instance_env.rs#L1519-L1555) obtains the timestamp from [the host wall clock](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/instance_env.rs#L425-L428). The [log record](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/database_logger.rs#L204-L232) serializes microseconds and the active reducer name.

## Frame views comparison

At instrumentation base `ea041af1`, main did not contain the held `frame-views` head `f9d909769`. Recheck before measuring. Its [near/far and cue design](https://github.com/devteapot/slop-art-online/blob/f9d909769/docs/TICK_RATE.md#frame-views-cues-and-tiers) changes player projection, post-reducer view materialization, delta workload and the pattern of sends. Engaged cues run each tick and near cues every other tick, with RLS selecting recipients. Near copies refresh at most every 500 ms, with far views on their separate budget. A client must subscribe to the cues and new tier views to measure the new delivery path. Neither the arena's owner `body` subscriber nor the mind's `fast_ask` subscription consumes those cues. Any effect on the fast split in the specified battle would come from shared authority or send load, and depends on the actual player subscriptions present.

## Reproducing the runs

Fetch main and check ancestry of `f9d909769` again. Record the tested commit and the running service version. Set the scratch trial container and its verified loopback URL explicitly and run the whole trial sequence under `flock ~/slop-mq/battle.lock`. Source `~/slop-sysroot/env.sh`, export `CARGO_TARGET_DIR=~/slop-input-latency-target`, and run Cargo through `~/slop-mq/build-slot` with the requested disk and memory floors. Build the release mind and the rules example `nav_optimal` into the private directory. Pass `--target-dir "$CARGO_TARGET_DIR"` to island launches. Check the container is already running before using the harness.

1. On fresh `verify-core-*` islands, run `nav_arena.py n1 --law off --input-latency` and `nav_arena.py n2 --law off --variant a --variant b --input-latency`, both controller arms, with unique `--run` names and five subjects per arm. Keep the arena `bodies.jsonl`, stimuli, walk records, module markers and benchmark windows. Use `input_latency.py nav <phase-directories>` for the per-phase distributions and last stages.
2. Run `battle_diag.py --run minds-input-latency-<stamp> --battle 200 --walkers 16 --minutes 10 --fast-lane --fake-fast-patch --keep-plans --input-latency`. Keep the standing target at 200 fighters with refills. Report the actual active count and arrivals throughout from the keeper samples. Restrict any claim about an exactly 200-active workload to windows where the observed census supports it. The existing fixture has a 1 s fake fast response and preserves a labelled combat branch to patch. Record the duration, density, subscribers, issue and patch counts, and actual traffic. Use `input_latency.py fast <run-directory>` for the split. Retain late and unanswered issues with their censoring status. Use the sampled metrics to distinguish persistent queueing from a thinly sampled burst.
3. Verify the pause before deleting owned scratch worlds. Retain the raw evidence, computed reports and unit-test output under the run's `.local` paths. Archive those paths and write the SHA-256 sidecar before removing evidence.

## Candidate fixes to size after the split

- **Arena scoring.** Use the send time or the pre-call lower bound and preserve response timestamps and censoring. This removes any apparent delay from discarding a first segment before the HTTP acknowledgement. It saves zero time in the authority. Compare the two scorers on the same exports to measure the reporting effect.
- **Authority sampling if it dominates N2.** Keep a local, indexed due set for ground rechecks on an approaching route rather than shortening every character's look interval. A 100 ms local interval would reduce the nominal wait ceiling from 900 ms to 100 ms under regular scheduling. The roughly 760 ms p95 difference assumes uniform stimulus phase and on-time evaluation. This applies only where the actual response depends on a ground observation.
- **Authority wake delay if it dominates N1.** Make an accepted command get the next eligible tick instead of relying on an ordinary graph slot, preserving committed-move and skill timing. A next-tick wake costs at most one 16.7 ms tick on an on-time 60 Hz authority, compared with up to about 1 s on an ordinary slot. If the trace shows the current install already gets its next-tick wake, that change offers no gain.
- **Fast delivery if the combined bound dominates.** First add temporary tagged server and SDK spans in a pinned diagnostic build, keyed by transaction offset and connection. If queue age accounts for the tail, test sending a small, authorized fast-lane stream independently of bulk observations, while retaining the durable ask for reconnect. Bringing the earlier 3.1 s issue-to-pickup p90 below 150 ms would save about 2.95 s at that boundary. This is the potential gain if the tail is delivery backlog and the isolated path actually meets the target. If the delay is in view materialization or incremental evaluation, reduce the affected query set and row fan-out before changing sockets. If delay is downstream of the SDK callback, test isolating fast dispatch in the mind process instead.

## Grant-stall comparison

The read-only urgent-merge investigation at `c2afb179` found a main-run gap at 185.5–198.2 s with about 95 queued calls and two busy slots. Two longer gaps appeared in branch run B2. Its grant rate after backlog was about 20/s with a 10 ms profile deadline and a 50 ms retry poll. Those observations came from a fixed-site fixture. Compare against the actual census and refill policy of this run.

With `LIVING_INPUT_LATENCY=1`, `mind.log` timestamps every grant across all scheduler lanes, each fast SDK callback, and each fast task pickup immediately. A once-a-second experience callback marker shows whether other subscribed updates are still reaching the mind. The scheduler also records a queue probe at most once per second while there are admission attempts. It records queued and busy counts, capacities, the count of profile-ready requests with a free slot ignoring lane order, and whether the scheduling pass found a candidate. A missing probe means there was no recorded inspection and cannot establish that slots were free. The parser aligns grant gaps of at least two seconds with callbacks, pickups, queue probes and the sampled count of committed authority ticks. These observations distinguish concurrent gaps from causal attribution.

For successful fast calls the grant ID joins the request to its exact scheduler grant. The split reports queue entry to grant separately from grant to reply. A narrow pacing diagnostic records timer wakes where the head request had a slot, was blocked by profile RPM spacing, and the scheduler found no candidate. It excludes token caps, provider outages, and global RPM waits. It measures the time after the profile deadline at the poll wake, with excess beyond 50 ms reported separately. It misses indirect waits behind other paced requests and yields a conservative observed portion of queue delay. At 10 ms spacing, a 50 ms timer can add about 40 ms per grant in a steady single-profile backlog. This is a hypothesis to test with the per-second grants and measured poll delay. There is no scheduler timing change.

## Spark measurements, 2026-11-19

The trial server ran SpacetimeDB 2.14.1. The measurement checkout applied the diagnostics to main `97858bbb` (authority and mind commit `0f77e28e`), which includes the deterministic battle formation from the fast-lane replicates. `frame-views` remained held. These tests use the old projection and delivery path. The trial driver held `battle.lock` throughout the live suite.

The fake battle used 200 starting fighters in the seed-7 formation around (406.5, 237.5), 16 extra walkers and 310 ambient characters. The mind had one subscription connection. Combat and profile samples were captured through the existing bench and HTTP tools. The fighter keeper sampled 111–200 active fighters, median 166, with 14 of 258 census samples at 200. Sixteen walkers survived throughout. The configured fixed target did not keep the active count fixed. Nineteen observed pickups were bracketed by census readings of 200 fighters less than five seconds apart. Their issue-to-pickup p50/p90/p95 was 114/1,390/1,900 ms. The sample supports neither a sustained 200-active claim nor a stable p99 estimate at that count. Ten 30-second profiling windows saw 11.7–40.1 ticks/s and 562–2,144 aimed windups per window. The fake fast provider used a one-second response. The 600-second scored interval had 294 valid clock samples, zero paused samples, zero clock errors and no orphan pause. Ticks advanced from 414 to 19,126 in those probes.

### Fast lane

The private diagnostic build of the pinned Rust SDK records when its WebSocket loop receives a complete binary message, before decompression and decoding. Only the timestamp, actor and issue stamp are logged for matching `fast_ask` inserts. The evidence includes the build script and SDK patch. This is a userspace frame receipt, with kernel arrival still unobserved. The owner-only API log tail truncated the authority export. The full export was recovered read-only from the identified run-owned replica's retained log and joined by actor and issue stamp.

There were 773 issued asks with receipt and SDK callback, 764 with task pickup, and 684 installed patches with matched outcomes. Nine expired issues lacked observed task pickup. Issue-to-install for confirmed patches was 1,255/3,990/6,392 ms at p50/p90/p95. For all 764 pickups, issue-to-pickup was **77/3,937/11,389/19,473 ms at p50/p90/p95/p99**. The archived real-model B-200 replicate had 493 pickups at 25/515/5,146/11,310 ms. The new fake battle reproduces a multi-second tail, with a larger one in this workload.

Callback to task pickup takes **87.7% of summed issue-to-pickup time** on all pickups and **92.6% in the slowest decile**. The slowest 77 asks had a median 11.44 s total, with median 10.63 s after callback. The callback-to-dispatch interval accounts for nearly all that stage. The dispatch-to-spawned-task interval was 2 ms p95. Commit, delta evaluation, outbound queues and transport remain combined in the write-to-receipt bound. On the 577 marked tick issues, the tick-end-to-receipt bound was 118 ms p95. No per-ask split of those server stages is available from the stock server metrics.

Shares below pair each stage with confirmed issue-to-install samples. Trigger admission and acknowledgement extend beyond that interval. Several bounds overlap, so their shares cannot be added.

| Stage | n | p50 ms | p90 ms | p95 ms | p99 ms | Share of issue-to-install |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First queued trigger → issue | 773 | 2,167.00 | 6,761.80 | 7,376.80 | 7,920.52 | — |
| Newest coalesced trigger → issue | 773 | 0.00 | 58.00 | 104.40 | 441.80 | — |
| Issue → ask write | 773 | 1.95 | 8.58 | 15.06 | 106.60 | 0.35% |
| Ask write → tick body end, when tagged | 577 | 13.22 | 38.86 | 66.87 | 155.42 | 1.13% |
| Tick body end → WebSocket receipt, combined bound | 577 | 8.87 | 50.72 | 117.69 | 1,250.94 | 2.08% |
| Ask write → WebSocket receipt, combined bound | 773 | 24.11 | 122.34 | 313.06 | 1,495.48 | 3.45% |
| WebSocket receipt → SDK callback | 773 | 10.00 | 237.60 | 479.20 | 1,137.84 | 3.18% |
| SDK callback → mind event dispatch | 761 | 0.00 | 3,727.00 | 10,630.00 | 18,333.60 | 27.82% |
| Dispatch → spawned task pickup | 761 | 0.00 | 1.00 | 2.00 | 9.00 | 0.03% |
| SDK callback → task pickup | 764 | 1.00 | 3,700.00 | 10,557.55 | 18,328.83 | 27.86% |
| Pickup → model call | 739 | 81.00 | 529.60 | 884.00 | 1,259.70 | 8.28% |
| Model call → scheduler queue | 739 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00% |
| Scheduler queue → grant | 739 | 0.00 | 58.40 | 108.60 | 1,349.32 | 1.92% |
| Observed RPM poll delay within queue time | 739 | 0.00 | 42.05 | 46.92 | 50.00 | 0.32% |
| Grant → model reply and journal | 739 | 1,004.00 | 1,237.20 | 1,487.20 | 2,236.80 | 50.58% |
| Model reply → patch send | 722 | 30.50 | 143.90 | 213.80 | 397.53 | 2.62% |
| Patch send → authority entry | 722 | 13.44 | 88.17 | 166.51 | 490.40 | 1.75% |
| Authority entry → patch install | 684 | 0.28 | 0.42 | 0.46 | 0.69 | 0.02% |
| Patch install → mind reducer result | 684 | 23.62 | 314.36 | 703.47 | 1,857.41 | — |

Four grant gaps lasted at least two seconds, beginning at 417.0, 420.6, 440.7 and 516.4 seconds. The longest was 5.30 seconds. During it, 14 fast frames arrived, one reached an SDK callback, none reached a task pickup, and experience callbacks appeared in five seconds. Tick throughput in sampled intervals was about 30.9/s. The scheduler repeatedly selected a candidate while it observed up to 171 ready requests with a free slot. Across all four gaps the authority kept ticking, and three had at least some socket receipts. These samples establish overlapping SDK and mind-service backlogs. They do not identify which scheduler or executor operation stopped grants. Under backlog, shared grant rate was 10/s p50, 16/s p90 and 18/s p95, with a 23/s maximum observed bin. The fast model queue was 109 ms p95, including a directly observed RPM-poll delay of 47 ms p95, about 0.32% of issue-to-install on paired installs. This delay was downstream of the issue-to-pickup split.

The largest measured opportunity is the mind's shared event path. Measure age and depth by event kind, then test a bounded, separately drained fast channel with stale-ask handling. The observed callback-to-dispatch time available to remove was 10.63 s p95 for samples with a dispatch stamp. Use the same fixed formation, actual roster and host-load strata to test the gain. For the SDK stage, test narrowing and prioritizing subscribed traffic and measure receipt-to-apply separately. The observed receipt-to-callback p95 budget was 479 ms. A profile-deadline wake can remove roughly 40 ms from a positively identified 50 ms pacing poll with a 10 ms spacing deadline. It cannot account for the seconds-long grant gaps. Investigate those using scheduler candidate age and time in the Tokio runtime, aligned with callback and event-loop progress.

### Law-off navigation

Twelve fresh island worlds drove N1 variants a–d and closed-gate N2 variants a–b, each with five scripted bodies or five actual player identities. Each world had one owner CLI body subscription and its bench sampler. No mind process ran on these worlds. Every target walk arrived. Every arena passed its periodic pause and tick-monotonicity checks, with no orphan-guard pause. The launch shell stayed alive through the run and only its Cargo subprocess used the build-slot wrapper.

N1 retains the pre-call scorer for comparison with the prior rerun. Its scored p95 is 697 ms for bodies and 1,675 ms for players when pooled. Actual send-to-first-body-write p95 is 991 ms for bodies and 2.56 ms for players. The deliberate-act queue explains nearly all of the scripted body's first-write delay. The player order replaces the current act, starts within 0.66 ms p95 of enqueue, and writes a new segment promptly. The score can wait another 1.69 s p95 for a sufficiently different velocity. Forty-five joined qualifying velocity changes preceded the first segment written after the new act attempt, and two other scored segments were written before input send. These early writes show why the scorer cannot assign every velocity change to the requested action. The post-call scorer misses further early responses.

All 20 eligible N2 stimuli reached the gate-memory write. Eighteen met the velocity threshold within two seconds, with pooled p95 about 1.96 s in both controllers. The player sweep occurred by 174 ms p95 and ground memory by about 901 ms p95. Ground memory was about 954 ms p95 for bodies. The law-off route can use the real closed gate from order time, so neither sweep nor gate memory is a prerequisite for its movement. The scored turns cluster near the two-second steering interval. In all four unanswered N1/N2 cases the authority wrote body motion and the walker arrived. In the N2 cases it also updated gate memory. The stopping point was the velocity-change criterion inside the two-second observation window.

The N1 rows leading to the first body write use send-to-first-write as their denominator. The qualifying-write intervals use only joins in chronological order after that first write. The N2 denominator is geometric stimulus to qualifying write. N2 intervals around the same look overlap and establish timing rather than a causal edge. Observer output includes subscription delivery, CLI processing and printing. Smaller samples and a two-second cutoff limit inference about extreme navigation tails.

| Arena arm | Received / stimuli | Arena p50 / p90 / p95 (ms) | Unanswered |
| --- | ---: | ---: | ---: |
| n1-a-off-body | 15 / 15 | 65.00 / 361.80 / 710.30 | 0 |
| n1-a-off-click | 15 / 15 | 21.00 / 1,584.60 / 1,679.90 | 0 |
| n1-b-off-body | 14 / 15 | 379.50 / 701.90 / 727.05 | 1 |
| n1-b-off-click | 14 / 15 | 14.00 / 1,715.70 / 1,814.75 | 1 |
| n1-c-off-body | 15 / 15 | 131.00 / 599.20 / 669.10 | 0 |
| n1-c-off-click | 15 / 15 | 20.00 / 717.20 / 771.90 | 0 |
| n1-d-off-body | 15 / 15 | 130.00 / 393.40 / 470.40 | 0 |
| n1-d-off-click | 15 / 15 | 22.00 / 184.60 / 286.90 | 0 |
| n2-a-off-body | 5 / 5 | 1,864.00 / 1,954.00 / 1,965.00 | 0 |
| n2-a-off-click | 5 / 5 | 1,829.00 / 1,955.40 / 1,969.20 | 0 |
| n2-b-off-body | 4 / 5 | 1,829.00 / 1,910.50 / 1,917.25 | 1 |
| n2-b-off-click | 4 / 5 | 1,844.00 / 1,905.30 / 1,912.65 | 1 |

**N1 body.** 59/60 scored. Arena p50 / p90 / p95 131.00 / 641.20 / 697.40 ms.
The main post-call score captures 48/60. 27 joined scored writes precede the first write after the new act attempt.

| Stage | n | p50 / p90 / p95 (ms) | Share of paired total |
| --- | ---: | ---: | ---: |
| `send_to_input_entry` | 60 | 0.98 / 1.34 / 1.71 | 0.4% |
| `input_entry_to_http_ack` | 60 | 7.94 / 25.18 / 31.17 | — |
| `input_entry_to_act_queue` | 60 | 0.08 / 0.10 / 0.11 | 0.0% |
| `act_queue_to_start` | 60 | 72.31 / 749.50 / 990.06 | 99.6% |
| `send_to_first_body_write` | 60 | 73.36 / 750.29 / 991.18 | 100.0% |
| `input_entry_to_first_body_write` | 60 | 72.38 / 749.56 / 990.14 | 99.6% |
| `act_attempt_to_first_body_write` | 60 | 0.31 / 0.49 / 0.59 | 0.1% |
| `first_write_to_scored_write` | 31 | 0.00 / 333.98 / 423.72 | 76.0% |
| `input_entry_to_body_write` | 31 | 0.62 / 386.96 / 573.00 | 99.3% |
| `body_write_through_observer_output` | 31 | 7.29 / 30.54 / 36.50 | — |
| Matched wall-time total to qualifying write | 31 | 1.69 / 387.77 / 573.86 | 100% |

Unanswered N1 body, actor 4394, walk 2. body_write_without_scored_response; arrived; observed arena_stimulus_ms, order_send_wall_ms, order_ack_wall_ms, input_entry_ms, act_queue_ms, act_attempt_ms, act_start_ms, first_body_write_ms.

**N1 click.** 59/60 scored. Arena p50 / p90 / p95 20.00 / 1,472.40 / 1,675.30 ms.
The main post-call score captures 46/60. 18 joined scored writes precede the first write after the new act attempt.

| Stage | n | p50 / p90 / p95 (ms) | Share of paired total |
| --- | ---: | ---: | ---: |
| `send_to_input_entry` | 60 | 1.01 / 1.42 / 1.90 | 68.8% |
| `input_entry_to_http_ack` | 60 | 7.72 / 13.88 / 15.50 | — |
| `input_entry_to_act_queue` | 60 | 0.12 / 0.15 / 0.16 | 7.2% |
| `act_queue_to_start` | 60 | 0.43 / 0.64 / 0.66 | 25.0% |
| `send_to_first_body_write` | 60 | 1.55 / 1.99 / 2.56 | 100.0% |
| `input_entry_to_first_body_write` | 60 | 0.54 / 0.73 / 0.75 | 31.2% |
| `act_attempt_to_first_body_write` | 60 | 0.37 / 0.56 / 0.60 | 21.5% |
| `first_write_to_scored_write` | 40 | 0.00 / 1,559.29 / 1,690.15 | 99.6% |
| `input_entry_to_body_write` | 40 | 0.84 / 1,559.48 / 1,690.64 | 99.7% |
| `body_write_through_observer_output` | 40 | 6.90 / 11.70 / 14.22 | — |
| Matched wall-time total to qualifying write | 40 | 2.38 / 1,561.86 / 1,691.54 | 100% |

Unanswered N1 click, actor 313, walk 2. body_write_without_scored_response; arrived; observed arena_stimulus_ms, order_send_wall_ms, order_ack_wall_ms, input_entry_ms, act_queue_ms, act_attempt_ms, act_start_ms, first_body_write_ms.

**N2 body.** 9/10 scored. Arena p50 / p90 / p95 1,864.00 / 1,934.40 / 1,955.20 ms.

| Stage | n | p50 / p90 / p95 (ms) | Share of paired total |
| --- | ---: | ---: | ---: |
| `geometric_stimulus_to_graph_eval` | 10 | 498.20 / 932.31 / 954.11 | 28.1% |
| `geometric_stimulus_to_ground_look` | 10 | 498.29 / 932.35 / 954.16 | 28.1% |
| `geometric_stimulus_to_gate_memory` | 10 | 498.32 / 932.36 / 954.18 | 28.1% |
| `geometric_stimulus_to_first_body_write` | 10 | 1,277.05 / 1,434.84 / 1,477.94 | 47.1% |
| `gate_memory_to_scored_write` | 9 | 1,283.18 / 1,713.31 / 1,773.71 | 71.9% |
| `geometric_stimulus_to_body_write` | 9 | 1,877.43 / 1,943.99 / 1,965.79 | 100.0% |
| `body_write_through_observer_output` | 9 | 6.86 / 8.55 / 8.55 | — |
| Matched wall-time total to qualifying write | 9 | 1,877.43 / 1,943.99 / 1,965.79 | 100% |

Unanswered N2 body, actor 311, walk 0. gate_memory_without_scored_response; arrived; observed arena_stimulus_ms, look_ms, gate_memory_ms, gate_close_ms, graph_eval_ms, first_body_write_ms.

**N2 click.** 9/10 scored. Arena p50 / p90 / p95 1,829.00 / 1,932.60 / 1,957.80 ms.

| Stage | n | p50 / p90 / p95 (ms) | Share of paired total |
| --- | ---: | ---: | ---: |
| `geometric_stimulus_to_player_sweep` | 10 | 109.15 / 164.25 / 173.77 | 6.0% |
| `geometric_stimulus_to_graph_eval` | 10 | 525.14 / 894.07 / 900.90 | 29.1% |
| `geometric_stimulus_to_ground_look` | 10 | 525.18 / 894.11 / 900.92 | 29.1% |
| `geometric_stimulus_to_gate_memory` | 10 | 525.20 / 894.13 / 900.94 | 29.1% |
| `geometric_stimulus_to_first_body_write` | 10 | 1,358.31 / 1,467.74 / 1,485.82 | 59.2% |
| `gate_memory_to_scored_write` | 9 | 1,315.99 / 1,561.26 / 1,588.07 | 70.9% |
| `geometric_stimulus_to_body_write` | 9 | 1,842.80 / 1,941.48 / 1,964.42 | 100.0% |
| `body_write_through_observer_output` | 9 | 8.22 / 10.13 / 10.40 | — |
| Matched wall-time total to qualifying write | 9 | 1,842.80 / 1,941.48 / 1,964.42 | 100% |

Unanswered N2 click, actor 313, walk 0. gate_memory_without_scored_response; arrived; observed arena_stimulus_ms, look_ms, gate_memory_ms, gate_close_ms, player_sweep_ms, graph_eval_ms, first_body_write_ms.

For N1, measure an accepted command's first authoritative body write and its distinct physical effect, with separate scores for direct player replacement and deliberate queues. This removes the player's apparent 1.67 s tail on the first-write measure, without speeding up movement. For the scripted queue, a targeted replace or next-eligible-tick option could recover up to the observed ~990 ms p95 queue wait if replacement is intended. It must preserve committed moves and queued acts with deliberate ordering.

For N2, close the gate after dispatch on a known route and time a demonstrated route change against actual gate observation. That fixture would separate geometric eligibility, knowledge, collision and response. An indexed, route-local wake for a newly observed obstruction could shorten time before the next steering decision if it depends on that observation. A 100 ms local cadence would reduce the nominal two-second segment wait ceiling by about 1.9 s for affected walkers. Shortening global sweeps cannot remove the observed post-memory delay in the law-off fixture.

Evidence is in `~/slop-evidence/input-latency-2026-11-19.tar.zst` with its SHA-256 sidecar. It includes the run scripts, pause probes, traces, full authority marker exports and scored reports. The separate battle commitlog archive was created by the verified scratch-world cleanup. No paid provider or rendered game client was exercised.

## Mind dispatch profile (fast-dispatch, 2026-11-20)

Branch `fast-dispatch`. The question was where the mind service spends the time between a request reaching it (the SDK callback) and the model request, and what changes about 140 s into a 200-fighter battle, when grants fall away on main and on `grant-stall` alike.

### Instrumentation

`LIVING_INPUT_LATENCY=1` (set by `battle_diag.py --input-latency`) turns on `living/mind/src/prof.rs`; off, each entry point is one cached flag test.

- **Series**, logged every 5 s as `input_latency_prof <ms> {json}` in `mind.log` (n, sum, p50/p90/p95/p99, max): event-queue age (`event.<kind>.wait`) and handling time (`.handle`) per event kind; the 2 s checks (`tick.*`); SDK callback time (`sdk.cb.*`); waits for and holds of the mind's own mutexes (`lock.<name>.wait/.hold`, and holds of 2 ms or more by caller line; `prof::Mx` is `std::sync::Mutex` with a name); a probe that reads the SDK client cache every 2 ms (`sdk.cache_lock_probe`: how long a read waits for the cache's one lock); tokio worker busy share, global queue and live tasks each second, and a 10 ms heartbeat's lateness on the workers (`rt.*`).
- **Per item**: each deliberation journals its steps to `outcomes/input_latency_deliberation.jsonl` (SDK callback, dispatch, spawn, the 400 ms gather, request found, gate, start, lane, character, recall, experiences, context, prompt, queue entry, grant, reply; the authority's `requested_ms`/`updated_ms`); fast asks add their grant time to `outcomes/input_latency_fast.jsonl`.
- `living/tools/dispatch_profile.py RUN_DIR` reports both for the measured window; lanes come from the fake provider's timing header (`battle_diag.py --fixed-site`, from `urgent-merge-ab2-control`).
- The CPU profile used a local build only (pprof-rs at 250 Hz, SIGPROF, libc frames dropped, so memcpy and malloc inside clones are undercounted); its patch and output are in the evidence archive, not in the tree.

### What the profile found (main + timing only, `7e00f3e7`; one profiled run `minds-fd-prof1`, then four A runs below)

The fixture: 200 fixed-site fighters striking in place with zero damage, 16 walkers, 310 ambient people, fake model (think 5 s, compile 4 s, consolidate 4 s, fast 1 s), fast lane on with `keep` replies, 64 shared slots, one mind connection, a fresh private SpacetimeDB 2.14.1 container pinned to CPUs 5–9,15–19.

1. **The SDK client cache's one lock, held by whole-table clones.** Every read of the Rust SDK's client cache takes one `std::sync::Mutex`, and `TableHandle::iter` clones every row of the table while holding it ([client_cache.rs `with_table_cache`/`iter`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/client_cache.rs)); the SDK also takes it to apply each update ([db_connection.rs `apply_update`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/db_connection.rs)). The generated cache offers only the experience table's primary key, so the mind found "a character's experiences" by cloning the whole subscribed table: `Minds::experiences` (every prompt, consolidation, the fast lane, `only_far` once per person a consolidation batch names), the lane test and the consolidation inbox. The table grows about 360 rows a second in this battle (78k rows at 3 min, 88k at 4 min), so each clone grows with it: 43.6 ms per `experiences()` call at the median of 5 s windows, 6,313 calls in the 300 s window (265 s of clone under the lock), plus 195 s of lane-test scans.
2. **What changes at about 140 s.** Once those clones ask for more lock time than there is, a convoy forms. In the profiled run the cache probe's p95 per 5 s window was 30–70 ms before 140 s, then 200 ms, then 0.4–1.7 s; the worker heartbeat stopped for up to 37.7 s at a time; the event loop waited up to 120 s (6,451 events queued); think and compile sends fell from about 45 per 5 s to 0–13. Across the four A runs the same collapse comes at 180–210 s: model sends per 30 s were 228–288 for the first 150–180 s and then 1–87. The SDK thread waits on the same lock, so receipt to callback grows too (fast issue→callback p95 334–411 ms on A against 98–116 ms on B).
3. **Consolidation's name lookup.** 62% of the sampled (non-libc) CPU was consolidation, 40% of it `named_people`: for each experience of a batch it cloned every character and lowercased every name. Consolidations begin to come due about 90–140 s in (the 90 s minimum gap), which is why the slowdown starts then and not at once.
4. **The event loop ran the 2 s checks inline.** `check_consolidation` cloned the whole experience table on the loop's own thread: up to 43.8 s for one pass in the profiled run, and every event (fast asks included) waited behind it. Fast callback→dispatch p95 was 0.6–1.1 s on the A runs, up to 58 s in the profiled run.
5. **A 2 s wait for a persona that never comes.** A person with nothing to start an identity from (no sheet, background, parents or seed entry: the battle's spawned bodies, or a body the minds take over) wrote no persona, and each of its deliberations then polled 20 × 100 ms for one. That was 2.4–3.7 s of the 3.1–3.2 s median pre-queue time on A.
6. **Not the scheduler queue lock, not the mind's own mutexes.** `llm_queue` waits were 21.9 s summed over 655,760 locks; `actors` holds of 2 ms or more were one call site (the consolidation check) at 58 ms median. The 50 ms poll added up to 40 ms a grant behind a pacing deadline.

### What changed

- **Keyed reads instead of clones.** `mind.rs` `Index` keeps experience ids by observer and each character's pending request, from the SDK's insert, update and delete callbacks (initial subscription rows arrive as inserts, [db_connection.rs `SubscribeApplied`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/db_connection.rs)). Rows are read from the cache by primary key, so the cache stays the one source of truth and what a mind reads is unchanged. Experience callbacks run before `fast_ask`'s in a message (the generated `invoke_row_callbacks` order), so a fast ask finds its message's experiences. `named_people_among` reads names and whom one knows once per batch.
- **Own channels and workers.** Fast asks: their own channel, runtime (`LIVING_FAST_WORKERS`, default 2) and HTTP client. Deliberation requests: their own channel and runtime (`LIVING_DELIBERATION_WORKERS`, default 4), where they are prepared and sent through their own HTTP client. The 2 s checks: their own thread, first pass at once. Speech, player memory and percepts stay on the event loop.
- **No 2 s persona wait** when the origin writes no persona (`writes_identity`).
- **Pacing-deadline wake.** The head of an eligible lane held only by pacing wakes at its deadline (`Queue::spacing_deadline`), not at the next 50 ms poll.
- **One saying rule.** `talk.rs` uses `living_rules::saying::saying_ms` (no copy).

No table, reducer, view or subscription changed; what a mind perceives and may do, and the rules both controllers run, are unchanged. The grant pass of `grant-stall` (`254c250a`) is not in this branch: with the slowdown gone, B had no grant stall in any run.

### A/B (main + timing vs fast-dispatch)

A is `7e00f3e7` (main `bd29fb7f` + the `input-latency` instrumentation + the `urgent-merge-ab2-control` timing harness + the profile); B is `006c1e6d`. Both: `battle_diag.py --battle 200 --walkers 16 --minutes 5 --keep-plans --fast-lane --fixed-site 412.5 237.5 --input-latency`, interleaved under one `battle.lock` hold (`.local/fd/fd_chain.sh`), each run in a fresh private container pinned to CPUs 5–9,15–19, started with the 1-minute load under 4, no compiler and the merge lock free. A run whose load passed 8 in its 300 s window was redone: a1 (21.6, my own suite's build), a1r2 (25.2), a2 (9.9) and a2r1 (36.7). a1r1 (6.9) counts; it was first marked invalid by a stricter rule (compilers at any sample) that the protocol does not ask for. Every run kept 200 fighters at the site, ticked every window, and the orphan guard paused none.

| | A1r1 | A1r3 | A2r2 | A3 | B1 | B2 | B3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Load at start / window max | 3.0 / 6.9 | 2.9 / 6.9 | 3.3 / 6.6 | 3.1 / 4.1 | 3.7 / 4.4 | 3.9 / 6.0 | 3.1 / 3.3 |
| Fast asks served | 310 | 289 | 296 | 293 | 600 | 599 | 600 |
| **Fast callback→dispatch p50 / p95 (ms)** | 0 / 1,141 | 0 / 976 | 0 / 593 | 0 / 945 | 0 / 1 | 0 / 1 | 0 / 1 |
| Fast callback→model queue p50 / p95 (ms) | 46 / 1,224 | 42 / 1,329 | 43 / 1,055 | 40 / 1,145 | 6 / 9 | 6 / 9 | 6 / 8 |
| Fast issue→callback p95 (ms) | 411 | 334 | 382 | 365 | 116 | 99 | 98 |
| **Urgent pre-queue (start→enqueue) p50 / p90 (ms)** | 3,230 / 5,441 | 3,130 / 6,170 | 3,072 / 5,084 | 3,058 / 5,584 | 22 / 31 | 20 / 30 | 20 / 29 |
| **Routine pre-queue p50 / p90 (ms)** | 4,542 / 7,940 | 4,927 / 7,518 | 3,995 / 7,694 | 4,642 / 9,095 | 22 / 32 | 23 / 30 | 22 / 30 |
| Urgent start→grant p50 / p90 (s) | 12.3 / 17.3 | 11.4 / 17.6 | 11.8 / 17.4 | 11.5 / 17.2 | 9.2 / 12.3 | 9.1 / 13.1 | 8.9 / 12.5 |
| Routine start→grant p50 / p90 (s) | 10.8 / 20.3 | 10.7 / 21.3 | 10.0 / 19.3 | 11.0 / 23.5 | 9.3 / 22.1 | 6.7 / 13.6 | 6.4 / 12.2 |
| Urgent request update→grant p50 / p90 (s) | 13.1 / 19.4 | 12.1 / 19.7 | 12.6 / 20.8 | 12.5 / 19.1 | 9.8 / 13.0 | 9.8 / 13.9 | 9.6 / 13.2 |
| Routine request update→grant p50 / p90 (s) | 10.7 / 21.5 | 11.4 / 23.2 | 11.0 / 20.7 | 11.4 / 27.7 | 9.9 / 22.8 | 7.4 / 13.9 | 7.0 / 12.8 |
| Urgent queue (enqueue→grant) p50 / p90 (s) | 9.4 / 17.5 | 8.9 / 19.1 | 9.1 / 19.1 | 8.6 / 18.1 | 9.4 / 14.1 | 9.4 / 14.4 | 9.3 / 14.1 |
| Routine queue p50 / p90 (s) | 9.3 / 13.7 | 9.3 / 19.1 | 8.4 / 21.0 | 7.9 / 20.9 | 12.1 / 24.2 | 9.6 / 15.6 | 9.9 / 13.4 |
| Background queue p50 / p90 (s) | 18.1 / 30.5 | 17.3 / 28.7 | 17.5 / 26.6 | 17.1 / 27.7 | 22.8 / 26.1 | 23.3 / 26.0 | 23.6 / 25.8 |
| Urgent / routine thinks sent | 662 / 152 | 665 / 151 | 682 / 152 | 683 / 152 | 1,133 / 332 | 1,114 / 347 | 1,117 / 343 |
| Model sends per 30 s, last 120 s | 49, 1, 6, 9 | 87, 2, 7, 17 | 68, 29, 31, 4 | 46, 14, 22, 31 | 290, 283, 293, 286 | 291, 285, 292, 292 | 291, 283, 291, 290 |
| Ticks/s (mean of 5 windows) | 45.96 | 46.02 | 45.68 | 45.58 | 46.80 | 46.52 | 46.50 |
| Grant stalls ≥ 1 s (longest ms) | 2 (2,443) | 3 (8,081) | 7 (13,546) | 6 (6,807) | 0 | 0 | 0 |
| Cache probe p95 (window median) / max (ms) | 110 / 2,781 | 132 / 1,919 | 87 / 2,056 | 80 / 2,297 | 0.001 / 90 | 0.001 / 43 | 0.001 / 42 |
| Longest event-queue wait (ms) | 88,672 | 119,810 | 99,527 | 124,639 | 73 | 26 | 23 |
| Reason lines per urgent prompt | 1.018 | 1.014 | 1.012 | 1.035 | 1.000 | 1.000 | 1.000 |

- **Targets.** SDK callback→dispatch p95 is 1 ms for fast asks on every B run (target < 100 ms; A 593–1,141 ms), and 0–6 ms p90 for deliberation requests (A 29–139 ms; these A medians are low because the stamp is the first callback since the character's last deliberation began, and most callbacks arrive while it is still deliberating). Deliberation pre-queue p90 is 29–32 ms on B against 5.1–9.1 s on A.
- **Better.** Urgent start→grant p90 12.3–13.1 s against 17.2–17.6; urgent update→grant p90 13.0–13.9 against 19.1–20.8; ticks/s 46.5–46.8 against 45.6–46.0; no grant stalls against 2–7 a run; the pool kept sending at about 290 calls per 30 s to the end, where every A run fell to 1–87.
- **Worse where the pool is now full.** B sends about 1.7× the urgent and 2.2× the routine thinks into the same 64 slots, so the wait *inside* the queue rose for the lower lanes: routine queue p50 9.6–12.1 s against 7.9–9.3 (p90 above A's range in B1 only, 24.2 against 13.7–21.0), background queue p50 22.8–23.6 s against 17.1–18.1 (p90 better, 25.8–26.1 against 26.6–30.5). The arm-neutral spans that include preparation are no worse: routine start→grant p90 12.2–22.1 against 19.3–23.5, routine update→grant p90 12.8–22.8 against 20.7–27.7. A's queue percentiles are also survivor-biased: they count only calls that reached the provider in the window, and A sent almost nothing in its last 90–120 s. Consolidations have no start stamp, so background has no arm-neutral span here.
- **Merging.** With requests read 20–30 ms after their start, urgent prompts carry 1.000 reason lines against 1.012–1.035: fewer lines arrive while a request waits to be prepared.
- **Resident stimulus → first body write.** The N1 arena drives the authority alone (`mind_act` with no mind process), and the authority is the same in both arms. N1 variant a, law off, 5 subjects × 3 walks, fresh islands, pinned private container, quiet host: a body's queued act waited for the act in progress p50 360 / 343 ms and p95 1.30 / 1.01 s (A / B, n = 10 each; `act_queued`→`act_started` markers), a player's started in 0.3 ms in both. The scripted body's first write is the queue behind the previous `goto`, which runs until steering arrives; a player's `human_act` replaces the act in progress. Reaching 150–300 ms for queued mind acts needs an authority decision (a mind act that may replace, or a next-tick start for an act whose predecessor has physically finished), not a mind change; this branch does not make it.

Evidence: `~/slop-evidence/fast-dispatch-20261120.tar.zst` (`.local/fd/`: driver scripts, preflight, host samples, placement, replica module logs, `ab.json`, the profiled run's `cpu.folded`, the pprof patch; and both checkouts' `.local/living/verify/minds-fd-*` and `core-nav-fd*` run directories).

## Mind acts replace (mind-act-replace, 2026-11-20)

Branch `mind-act-replace`. The parity gap the arena found: a player's command (`human_act`) replaces the act in progress and starts in the same transaction, while a mind's act (`mind_act`, `mind_act_checked`) waits in `act_queue` until the act in progress ends (at most 4 waiting, dropped after 120 s). The branch adds the value-only law **`mind_act_replaces`, off by default**: on, a mind's batch meets the act in progress exactly as a player's command does. Off is main's behaviour (proved below). Nothing is on by default.

### The rule, and what it touches

- **One path.** `acts::submit_player` (`human_act`) and, under the law, `acts::submit_mind` / `submit_checked` (`mind_act`, `mind_act_checked`) run the same step of `acts::submit_inner`: what was waiting in `act_queue` is dropped, and the act in progress (an `ACT` activity) is broken off (`act::cancel`, no reason) unless it is a committed move (`combat::committed`); the new act then starts through `act::begin` in the same transaction, with every gate a player's act meets (combat timing, the skill's checks, sight and reach). A reducer is one transaction: "Every reducer runs inside a database transaction … Either all changes succeed or all are rolled back" ([reducers](https://spacetimedb.com/docs/functions/reducers/)), so no client sees the body between the two acts.
- **Only a batch that holds an act for the body replaces** (one that `living_rules::acts::parse` accepts for the actor's body). A player's `human_act` reaches the step only with a parsed act; a mind's batch can also be a gaze change (`{"do": "gaze"}`, a mind's act only) or something unreadable, and those replace nothing. Gaze still goes to `attention::set` as before.
- **Act on act only.** A mind's act already took the body from a graph's activity at once in both arms (`acts::next` waits only for an `ACT`), and a reflex still breaks an act off (`acts::interrupt`). The law changes only what happens when a mind decides while one of its own acts runs.
- **Nothing new to replicate.** No table, column, view, subscription or reducer signature changed; the law is a `law_override` row like the other value-only laws (`VALUE_ONLY`, class Delivery, `law_override_check` covers it). A world switches it with `set_world_law mind_act_replaces true`, read at the next call with no install.
- **Diagnostics.** A second value-only law, `latency_acts` (off), logs each deliberate act's course as `input_latency act_*` module-log markers (submit, dropped, queued, started, replaced with its phase and age, done with its outcome code, refused, expired, set aside by a reflex) for every character; `latency_nav_from` logs them for the arena's subjects. `living/tools/act_trace.py` captures them from the replica's module log and reports each act's fate.

### What a player's replacement costs today, and the gaps

The law gives a mind exactly what a player has; it adds no cost. What a replacement costs either controller now:

| | Player (`human_act`) and a mind under the law | Gap? |
| --- | --- | --- |
| Work under way | Lost: the walk so far, a performing act's elapsed time, what waited in the queue. | No (physical). |
| Committed moves | Run their course (`combat::committed`). No deliberate act can be a combat move (real-time skills are refused as acts), so for an `ACT` this guard never fires; combat commitment, cooldowns and recovery hold on the graph and `use_skill` paths, which the law does not touch. | No. |
| A refused replacement | The old act is broken off **before** the new one is checked (`begin` runs after the cancel), so a replacement that is refused ("no food in your pack") leaves the body idle. `begin` itself checks first for a graph's options ("a higher-priority option that cannot start must not cancel the lower-priority work"). | **Yes, for both.** |
| Rate | `human_act` spends no input token (`human_move`, `use_skill` and `human_face` do: `input_hz` 30/s, `input_burst` 15), so a player can replace acts without limit. A mind is bounded only by its deliberation cadence (`think_min_s` 20 s for people, plus model time), not by a rule. | **Yes, for both.** |
| What is told | Nothing about the broken-off act (no outcome line, no `mind_state.last`); a recorded gesture's `skill_use` says "broken off" with no reason. The mind's next prompt shows truthfully what it is doing (`doing … (as you decided)`) and what still waits (`decided, not yet done`). | Minor. |
| Turning back | `act::turned_back` (a walk given up for another within 3 s is noticed; the sixth in 20 s is told, "You keep turning back and forth …", and asks for a thought) never runs on this path, because the old act is cancelled before `begin` sees it. A graph's walk replaced by another walk is noticed. | **Yes, for both**: the one self-perception of dithering is missing exactly where thrashing would happen. |
| The same act again | Restarts it (a performing act's elapsed time lost). `begin` continues an orphaned graph activity that matches. | Possible, for both. |

**Proposals (not added; each its own law, off until measured):** `act_replace_checks` (check the new act can start before breaking the old off, for both); `act_input_cost` (a replacing act spends from a bucket: `human_act` from the player's input bucket, a mind's replacing batch from a bucket of the same shape, for example a few replacements per 10 s); restore `turned_back` on the replace path for both; and "the same act continues" (a replacement by an identical act keeps the one under way). None of these is needed for the parity the law gives; the first three are gaps a player has today.

### Measurements

Host: the Spark, private server `slop-actreplace-20261120` (SpacetimeDB 2.14.1) pinned to CPUs 5–9,15–19, the whole series under one `~/slop-mq/battle.lock` hold, every run started at a 1-minute load under 4 with the merge lock free, arms interleaved (off-on, on-off, off-on), a run whose window load passed 8 redone (`arena-off3` three times and `battle-off1`, `town-off3` once: other workers' load; the last attempt counts, all at ≤ 6.4). Build: this branch's code as local commit `62e6dec3` on `fast-dispatch` `e52ec3a2`, since rebased onto main `7499c270` with no change to the act path (main's `act::unstick` and `relocated` only end movements that a teleport or a stall left without an end); the law was the only difference between arms (`latency_acts` on in both). Fake model only; no paid call.

**N1 arena (stimulus → first body write).** `nav_arena.py n1 --law off --subject body --reps 5 --input-latency --world-law mind_act_replaces=false|true`, variants a–d, 5 scripted bodies × 3 walks each, a fresh island per run, 3 runs per arm; no mind process (the arena's `mind_act` stands in for it). Every walk arrived (60/60 per run). Measured from the authority's own markers (`act_trace.py firstwrite`: the `mind_act` entry to the first `body_written` of the new act) and from `nav_report.py`'s act-scoped scores (the first authoritative write of the ordered act, and its physical effect: the first sample whose velocity differs from before, both from the wall send):

| | Off (n) | Off p50 / p90 / p95 (ms) | On (n) | On p50 / p90 / p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| `mind_act` entry → first body write of the new act | 187 | 325 / 750 / 999 | 188 | 0.31 / 0.43 / 0.45 |
| … variant a / b / c / d p95 | | 1,194 / 823 / 496 / 1,112 | | 0.51 / 0.37 / 0.47 / 0.44 |
| … started in a later transaction (waited) | 181 / 187 | | 0 / 188 | |
| Send → first write of the ordered act (`nav_report`) | 120 | 333 / 943 / 1,086 | 120 | 1.2 / 1.5 / 1.6 |
| Send → its physical effect (`nav_report`) | 120 | 333 / 943 / 1,086 | 120 | 52 / 53 / 53 |

The target was 150–300 ms; on, the body starts the decided act in the transaction that receives it, and its velocity visibly changes 52 ms later (the replacing walk takes over the glide and turns). Off, the wait is the remainder of the walk under way. The arena's older window score (any qualifying velocity change within 2 s of the send, `input_latency.py nav` `total`) does not separate the arms (variant a p50 372–480 off, 379–794 on), because it also counts the previous walk's own segments; the act-scoped scores above do not.

**Battle at a sustained 200** (`battle_diag.py --battle 200 --walkers 16 --minutes 6 --keep-plans --act-trace --fake-acts '[{"do": "goto", "target": "wander"}]'`, `--law mind_act_replaces=true` on): the fake mind thinks for every fighter, and each fighter's compile also decides a short walk (3–9 m), as a model's may. The keeper held 170.7–177.3 fighters alive on average (minimum 152–171), with 495–527 deaths refilled per run.

| | Off r1 / r2 / r3 | On r1 / r2 / r3 |
| --- | --- | --- |
| Mind acts decided / started | 1,048 / 833, 1,091 / 854, 1,093 / 847 | 1,083 / 841, 1,071 / 857, 1,096 / 886 |
| Decided while another act ran | 0, 0, 0 | 0, 0, 0 |
| Replaced (before their effect) | 0, 0, 0 | 0, 0, 0 |
| Never landed (refused at start: a committed move under way, "in the middle of a strike" / dodge / heal, as for a player) | 215, 237, 246 | 242, 214, 210 |
| Started → done | 832, 854, 847 | 840, 857, 886 |
| Decided → started p50 / p95 (ms) | 0.31 / 0.43, 0.30 / 0.41, 0.30 / 0.44 | 0.30 / 0.41, 0.29 / 0.35, 0.30 / 0.77 |
| Hits / blocked / dodged / missed | 12,706 / 10,387 / 2,992 / 684; 12,312 / 10,381 / 2,843 / 784; 12,144 / 10,386 / 2,943 / 704 | 12,940 / 9,863 / 3,070 / 823; 12,750 / 10,351 / 3,014 / 810; 12,504 / 10,367 / 2,779 / 769 |
| Timed defence (blows met by a dodge, block or jump) | 0.501, 0.514, 0.509 | 0.484, 0.520, 0.505 |
| Contact share; engagements per fighter-minute; contact s per engagement | 0.976, 0.971, 0.972; 0.30, 0.38, 0.41; 192, 152, 143 | 0.966, 0.960, 0.981; 0.39, 0.49, 0.38; 149, 119, 154 |
| Attacks per contact-minute | 27.2, 27.2, 27.4 | 27.7, 27.5, 27.2 |
| Ticks/s (mean of 6 windows); tick p50 / p99 (ms, median window) | 41.9, 46.0, 47.2; 11.7 / 25.0, 11.1 / 23.3, 10.7 / 22.1 | 43.6, 44.7, 42.0; 11.7 / 24.2, 11.1 / 23.9, 11.5 / 24.0 |

With a fighter deciding about once every 25 s and its walk lasting 2–3 s, **no mind act was ever decided while another of its acts ran**, so the law had nothing to replace: replacements per fighter-second 0 in both arms, and the combat readings and tick cost differ between arms no more than between runs of one arm. A fight's breaking off is the graph's reflexes (about 11,000 combat uses "broken off" per run in both arms), which the law does not touch. This fixture does not show what a model that issues long acts every few seconds would do in a fight; the town fixture below is the overlap case.

**Routine work in a town** (`act_town.py --minutes 10 --residents 40 --every 40`, island, `--law mind_act_replaces=true` on): 40 seeded residents at their daily ways (keeping their posts, resting, gathering, sleeping); the driver stands in for their minds and gives each an errand (walk to one of its given places, then another) at seeded exponential times, mean 40 s, the same 596 errands in every run; no mind service. This is the overlap stress: a walk across town lasts up to 77 s.

| | Off r1 / r2 / r3 | On r1 / r2 / r3 |
| --- | --- | --- |
| Errand legs started (of 1,192) | 891, 882, 887 | 987, 985, 986 |
| Decided while another act ran: wait for it p50 / p95 | 34.3 / 102.2 s, 35.0 / 105.4 s, 33.6 / 103.5 s | 0.27 / 0.46 ms, 0.27 / 0.48 ms, 0.27 / 0.47 ms |
| Never started: expired after 120 s / still waiting at the end | 31 / 58, 30 / 61, 31 / 59 | 0 / 12, 0 / 11, 0 / 12 |
| Replaced mid-walk (age p50 / p95) | 0 | 318 (8.8 / 38.8 s), 320 (8.8 / 38.9 s), 320 (8.7 / 37.4 s) |
| Legs dropped from the queue by a replacement | 0 | 193, 196, 194 |
| Legs walked to the end | 860, 851, 856 | 641, 638, 639 |
| Replacements per resident-minute | 0 | 0.80, 0.80, 0.80 |
| Routine outcomes ok / failed (`routine_stat`) | 848 / 144, 864 / 136, 879 / 138 | 1,092 / 181, 1,024 / 174, 1,094 / 191 |
| Graph tasks performed to their end / broken off while performing | 633 / 384, 594 / 399, 604 / 379 | 788 / 521, 779 / 481, 782 / 534 |
| Of which keeping a post | 136 / 232, 132 / 234, 126 / 235 | 174 / 301, 186 / 265, 168 / 293 |
| Gathers done per resident-hour | 3.9, 3.6, 3.75 | 7.65, 8.25, 8.25 |

Residents abandon their **errands** more under the law (a third of the legs started are replaced mid-walk and 640 instead of 855 reach their end), and no more of their **routine work**: the share of graph tasks broken off while performing is 37.8–40.2% off and 38.2–40.6% on. They do more routine work on (routine successes +24%, gathers doubled), because a queued errand holds the body (a graph's work waits while an act runs) and, off, errands pile up behind a long walk and run up to two minutes after they were decided, 30 of them never. Which is better depends on what the decisions mean: the fixture's errands are arbitrary and come faster than a walk across town; a real mind's next decision usually depends on what it now perceives.

**Tick cost and genesis.** The law adds one cached law read per `mind_act` call and, when on, a second parse of the batch's acts; nothing per tick. In the battle above, ticks/s were 41.9–47.2 off and 42.0–44.7 on, tick p50 10.7–11.7 against 11.1–11.7 ms and p99 22.1–25.0 against 23.9–24.2 ms (both arms with `latency_acts` logging, about 3 acts a second): within the spread of one arm. Genesis fuel on the island seed (`genesis_fuel.py --seed island`, the private server, rustc 1.99.1), main `7499c270` against this branch: `init` 11.744e9 → 11.761e9 (+0.15%: the shipped script that `init` compiles and validates is two laws longer), the 40 making steps 95.691e9 → 95.699e9 (+0.008%), the largest step 21.10% → 21.11% of the 120e9 budget. The island has no must-not-rise baseline (every seed is on the 10% headroom rule).

**Default off is main** (`det_compare.py`, the Cullet battle of 200, both builds `LIVING_SEED=cullet`, main `7499c270` against this branch on it). Identical over 3,600 ticks (every tick's table hashes, then 113 tables and 46,254 rows at the stop); with 16 players joined on the 10 m ring, identical over 1,500 ticks (44,682 rows). Negative control, the branch against itself with `--candidate-law mind_act_replaces=true` (a new `run` option: a law set on the candidate copy alone before both unpause): it differs from the first tick in `law_override`, `law_change`, `law_revision` and `chronicle` (the law's line, and the ids after it) and in no other table over 3,600 ticks. That battle's fighters act on instinct and no mind acts there, so the law has nothing to do; act-level identity cannot be shown with this tool, because a reducer called from outside the tick takes the wall clock as its time (`common::now_ms`), which differs between the two copies (an attempt that sent the same overlapping walks to both copies at the start tick differed only in those times and what follows from them). The `act_replace` scene, the arena and the town runs show the law's effect where acts overlap.

### Verification

- `just living-check`: ok (457 s), with main's known red `look::tests::the_island_wears_the_pool`. `cargo test -p living-rules`: 361 passed (the new laws in `VALUE_ONLY` go through `law_override_check`'s value-only tests).
- verify-core: `tick`, `teach`, `refusal`, `committed`, `food` and the new `act_replace` (off: queued, then started when the walk ends, its outcome told; on: replaced at once, the queue dropped, nothing told; a gaze change or an unreadable act replaces nothing) pass; `verify_mechanics.py` 23 of 23.
- verify-player: `combat.py --scene all` (with main's `teleport`) passes except `bow`, refused "out of breath" after the earlier scenes, which passes alone; `command`, `told`, `outcomes` pass.
- verify-minds (fake model): `acts`, `dealings`, `roundtrip`, `fast-lane`, `takeover` pass.
- verify-client: not run; no table, view, subscription or reducer signature changed.
- Records: `.agents/skills/verify-{core,player,minds}/references/validation/*-mind-act-replace.md`.

### For the GC

- **What on gives:** minds start what they decide at once, as players do: first body write 0.3 ms instead of 325 / 999 ms (p50 / p95), a visible change of course 52 ms after the send; the 150–300 ms target is met. No decision waits two minutes behind an old walk or silently expires.
- **What on costs:** a mind that decides faster than its acts finish breaks its own acts off (in the town stress, 0.8 replacements per resident-minute, a third of errand legs). Nothing else changes in a 200-fighter battle with the fake model's cadence. Tick cost is unchanged.
- **Before default-on:** the three gaps above are a player's today and become a mind's with the law: a refused replacement leaves the body idle, replacing has no rate limit, and `turned_back` never notices dithering on this path. Closing the first and third (and a rate law for both) would make default-on safer; a real-model battle and town trial, measuring the same fates with `latency_acts`, would show the actual overlap rate (paid; not run).

Evidence: `~/slop-evidence/mind-act-replace-20261120.tar.zst` with its SHA-256 sidecar (`.local/actreplace/`: the chain scripts, `runs.jsonl`, load samples, `summary.json`, the arena phases, det_compare outputs; and the run directories `.local/living/verify/{core-ar-*,minds-ab-*,minds-at-*}`).
