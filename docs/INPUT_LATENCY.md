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
