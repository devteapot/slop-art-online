# The immediate gate: 216 active characters for 30 minutes

2026-11-09. The first measurement of the [performance contract](PERFORMANCE_CONTRACT.md)'s immediate gate on the living core: 216 active characters for 30 minutes with a crowded battle, at 80 ms round trip, against every requirement the contract lists. Branch `gate-1`, code under test `14f3a72` (main) plus the measurement tools below. Earlier 216-character evidence came from the removed legacy stack ([short baseline](PERFORMANCE_BASELINE_25.md)).

**Result: the gate fails.** The 30-minute run fails 60 Hz cadence, both latency requirements and the slow-system deadlines, by orders of magnitude once the battle starts. The authority's single database thread saturates. Most of its time goes to per-sender perception views re-run for every player who perceives a change, in a cluster of 100 human-driven characters. That is about 1.1 of the container's 16 cores. Frame pacing on the one headless game client passes, but the world it drew was mostly frozen, so that pass is weak evidence. A real authority defect was also found: a tick panics and rolls back when a missile kills the owner of another missile in flight ([defect](#defect-found-the-missile-sweep-panics)).

| Requirement (locked) | Verdict | Measured, 30-min window | Cause |
|---|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail** | 9.0 steps/s overall: 50.2/s calm, 0.51/s battle, 0.17/s in the last 10 min. 89,051 of 104,836 grid steps skipped. Step interval p50 16.9 ms, p99 2.4 s, max 31.3 s | The tick waits in the database's queue behind player transactions whose view refreshes take milliseconds each. The queue ended at 7,333 operations. |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail** | Moves: calm p95 94.5 / p99 228.5 ms; window p95 16.4 s / p99 49.0 s. Skill outcomes: window p95 6.7 s / p99 15.2 s | Queue wait. In calm, confirmed-read fsync adds about 30–40 ms to every delivery. |
| Client input → authoritative outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail** | Moves: calm p95 176.7 / p99 309.0 ms; window p95 16.5 s / p99 49.0 s; 21,471 inputs never answered | As above, plus 80 ms of network. |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | **pass, weak** | 99.79% of frames ≤ 16.7 ms (uncapped, p50 5.4 ms, p99 9.2 ms), 173 frames > 25 ms, 2 > 50 ms | The server delivered few updates during the battle, so the client did not render a live 100-fighter battle for most of the window. |
| Slow systems at their deadlines (1 Hz housekeeping) | **fail** | 827 runs in 1,800 s; interval p50 1.47 s, p99 12.3 s, max 29.5 s | The same queue: housekeeping is a scheduled reducer behind the same backlog. |

No overall pass. A 10-minute [diagnostic arm](#diagnostic-arm-b-30-humans-in-the-battle) with 30 instead of 100 humans in the battle keeps its queue bounded, but still fails:
- **60 Hz:** 19.4 steps/s in the battle.
- **Server receipt → committed:** move p95 89.5 ms.
- **Client input → received:** move p95 170.8 ms.

Housekeeping and frame pacing pass in that arm. The [next measured bottleneck](#next-measured-bottleneck) names what to change.

## Workload (declared before the run)

The manifest is `manifest.json` in the run's evidence directory. It holds the binary hashes, the host and the settings.

| Item | Declared |
|---|---|
| World | Seed `island` (seed 7, 2048 m), fresh scratch database `verify-gate-20261109-200119`, skills installed from `living/scripts/skills.rhai` (sha256 `00291afc…`). World day = 12 real minutes, so the run spans day and night (sight 11 tiles by day, 6 at night). |
| **The 216 active characters** | **All 216 are human-driven player clients**, each over its own real WebSocket connection (Rust SDK 2.14.1, compression and confirmed reads at the SDK defaults, as the game client). 0 of the 216 are AI or instinct. "Active" means moving or fighting at every moment by construction: each client sends movement or combat input continuously. |
| Battle group | **100 players** placed within 9 m of one spot, 30 m north of the arrival point on open ground. **Calm phase** (5 min warm-up + first 5 min of the window): they mill round where they stand, with a new `human_move` direction every 1.5 s ±10%. **Battle** (window minutes 5–30): one decision every 250 ms ±10%, played against the nearest person each perceives (`seen_characters` + `seen_bodies`). In order: heal when below 45% health; strike in reach (`skill_card.reach` + 0.4 m); a fire bolt at 4–15 m (25% of chances); a bow shot at 2.5–14 m while arrows last; a raised guard (8%, released after 600 ms) or a dodge (5%) within 6 m. Otherwise it moves toward the target (run beyond 6 m), sending a move only when the direction changes by more than 30°, run toggles, or 2 s pass. A skill is tried only when `my_readiness`, `my_vitals.energy` and the client's own windup+recovery allow. A dead player rejoins (`join`, a new character with the newcomer kit) 3 s after death, at the arrival point 30 m away, and walks back into the fight. |
| Walkers | **116 players** placed at lot doors spread round all settlements (`place_at`, setup only), walking small circles: a new `human_move` direction every 1.5 s ±10%, 60° on. |
| Ambient (not counted in the 216) | The island's own residents and animals on their instinct graphs and daily rhythm: 293 characters at publish (people, deer, wolves, the bold pack). `rules.minds = false`. Their wolves joined the fight near the arrival point. |
| Observer | One owner connection with the lab observer's subscriptions (`living/viewer/src/net.rs`: whole `body`, `character`, `vitals`, `activity`, `terrain_chunk` … and one inspected character), plus two owner connections subscribing only `clock` (the tick watcher, below). |
| Game client | One headless `living-game` (release, uncapped, 1600×900, Vulkan on the dev-box's Radeon 8060S), connected as an extra player `GateWatcher` through the same 80 ms path, placed 14 m south of the battle and walking 3 s left and right. It is the 217th character and is not counted among the 216. |
| Minds | The mind service against the local fake model server, so model latency stays out. It received **0** model requests: the island's residents have no minds and no player went offline long enough for a takeover. |
| Inputs | Calm: 144 inputs/s (all moves). Battle: 337 inputs/s (moves 258/s, skills 62/s, joins and releases). |
| Network | Every player connection and the game client: **80 ms round trip, no jitter, no loss** (method below). The observer and watcher connect locally. |
| Duration | 5 min warm-up, then a 30 min window (20:08:23–20:38:23 UTC): calm 0–5 min, battle 5–30 min. "Late" is the last 10 minutes. |
| Backend | SpacetimeDB `clockworklabs/spacetime:v2.14.1` in its own rootless podman container `gate-stdb` (`--cpus 16`, port 3397, volume `gate-stdb-data`). The module is `living_authority.wasm` from `14f3a72` built with `LIVING_SEED=island` (default `scoped` perception). |
| Host | dev-box: AMD Ryzen AI Max+ 395 (16 cores / 32 threads), 62 GB, Radeon 8060S, Fedora 44, kernel 7.2.8. **Shared**: other agents' builds and labs ran throughout (1-minute load average p50 18, max 22.7). The load generator, game client, observer and server shared the host. |

The contract's full workload (2,000 characters, 200 in one battle, 8 hours) is not this one. The minimum client hardware is not yet defined, so the frame-pacing line uses the dev-box's integrated GPU.

## Method

**Clock.** Every timestamp is the host's wall clock in microseconds. The server container and the namespaced clients share the host kernel's `CLOCK_REALTIME`, so all intervals use one clock, with no cross-machine synchronisation.

**80 ms round trip.** `tc` was not installed and sudo was unavailable, so `iproute-tc` 6.17 was unpacked from its Fedora RPM (`gate.py` does this). Each client process runs in its own unprivileged user and network namespace made by `pasta --config-net -T <port>`. Inside it, `tc qdisc add dev lo root netem delay 40ms limit 100000` delays every packet each way on the namespace's loopback, where pasta's forwarded port lives. Calibration before the run: 30 TCP connects inside the namespace took p50 80.18 ms, max 80.24 ms. 30 HTTP requests to the server's `/v1/ping` took p50 80.71 ms, max 81.2 ms (`calibration.json`). The namespaces are gone when their processes exit; none remained.

**Correlation id.** No authority change was needed. A player's input is identified by its connection and call sequence (`p`, `n`). The SDK's per-call `_then` callback returns that call's own `ReducerEvent`. The server folds the caller's row changes into the call's reply, so the callback fires when the outcome of that very transaction has reached the client. A skill's input is also tied to its `skill_use.id`: the row this player recorded, with `at_ms` equal to the call's server timestamp. Every later state of that row (accepted, released, outcome) is timed when it arrives through the player's own `my_skill_uses` view. Events: `events.jsonl`.

**What each interval is.**
- *Server receipt*: `ReducerEvent.timestamp`. In 2.14.1 this is taken after the WebSocket frame is decoded and **before** the database's queue (`crates/core/src/host/module_host.rs:2489`, `call_reducer_params`). The docs' "invoked" and the module crate's "started" comments are inaccurate here, so queue wait falls inside the interval, as the contract wants.
- *Committed outcome*: the reply's arrival at the client minus the 40 ms downlink delay. This is an upper bound: it includes the server's send, the relay and pasta hops. SDK clients use **confirmed reads** by default (`client-api/src/lib.rs:35`, `DEFAULT_CONFIRMED_READS = true`), so a reply waits for the commitlog fsync. "Committed" therefore means durable and delivered.
- *Client input → outcome received*: send to arrival, with the 80 ms included.
- *Outcomes*: a move's outcome is its own transaction (the player's motion row changes in it). A timed skill's outcome (strike 350 ms, bow shot 300 ms, fire bolt 450 ms, heal 600 ms windup, from `skill_card`) is its **release**, with the declared windup subtracted, as the contract asks. A dodge or a raised guard's outcome is its acceptance (the dash or the guard is the move). A refusal is an outcome. Moves broken off before release, and uses whose actor died during the windup, are counted apart, not as latency. Missile flight time after release is physics and is not included.
- *Missing*: an input with no reply 5 s before the window closed, or an accepted timed skill with no release and no recorded end.

**Steps (60 Hz).** The tick is an `Interval(16_667 µs)` schedule. In 2.14.1 it is fixed rate, anchored at its intended times, and never catches up: a late step drops the missed grid steps (`crates/core/src/host/scheduler.rs:823-845`). Per step:
- Start and code time come from the module's `LogStopwatch` span (profiling on for the whole run, as `bench.py` does).
- Delivery comes from the tick watcher, two owner connections subscribed to the private `clock` row, which every tick writes. One uses confirmed reads, one `with_confirmed_reads(false)`, so the fsync share shows.
- Lateness against the grid is each start's offset from the starts' circular mean phase, shifted so its mean equals the server's exact mean delay for the window (`spacetime_scheduled_function_delay_seconds`). That is reliable only while steps are late by less than one period, so with the queue backed up the step interval and skipped-step counts are the measure.

**Bytes per client.** Each connection goes through `gate-load relay`, which counts the bytes each connection receives on the wire (compressed, as sent). The server's `spacetime_num_bytes_sent_to_clients_total` undercounts shared queries ([perception](PERCEPTION.md)).

**Resources.** Every 10 s: the database's Prometheus lines (reducer queue wait, transaction time, view time, scheduled delay, WASM memory, jemalloc, the commitlog size), the container's cgroup CPU and memory, and each tool process's CPU. Every 60 s: row counts of 25 tables, and the replica's `clog`, `snapshots` and `module_logs` on disk. Raw: `samples.jsonl.gz`.

**Frames.** The game client records every frame (`LIVING_GAME_FRAMES`, new: the wall clock, the `Time<Real>` interval and the main schedule's own time) and runs uncapped (`LIVING_GAME_FPS_CAP=0`). A smoke run at the default 60 Hz cap showed the headless runner's sleep overshoot: interval p50 16.71 ms with 3 ms of work, 59.6 FPS. That artefact of `ScheduleRunnerPlugin` would fail any client, so the uncapped interval, the frame's real cost, is what is judged. "Missed" is a frame over 25 ms (1.5 × 16.7); a "stutter" is one over 50 ms.

### Instrumentation added

- **The authority: none.** Receipt time, correlation and step timing all came from what 2.14.1 already exposes.
- `living/game/src/perf.rs`: `LIVING_GAME_FRAMES=<file>` appends `unix_us,interval_us,work_us` per frame. Off unless set, and registered inside `perf::diagnostics`; `main.rs` is unchanged.
- `living/tools/gate_load/` (its own Cargo workspace, like `perception_load`): the `players`, `relay`, `watch` and `observe` modes.
- `living/tools/gate.py`: the whole run, analysis and cleanup.

## Results, 30-minute run (`gate-20261109-200119`)

### Steps

| Window | Steps/s | Grid steps skipped | Interval p50 / p95 / p99 / max (ms) | Tick code p50 / p95 / p99 / max (ms) | Start → delivered, unconfirmed p50 / p95 / p99 (ms) | Same, confirmed reads p50 / p95 / p99 (ms) |
|---|---|---|---|---|---|---|
| calm (5 min) | 50.2 | 2,940 of 17,995 | 16.84 / 39.0 / 70.6 / 271 | 1.27 / 6.23 / 8.66 / 26.4 | 3.6 / 31.1 / 50.4 | 41.2 / 74.1 / 212.7 |
| battle (25 min) | 0.51 | 86,107 of 86,837 | 1,457 / 5,248 / 12,852 / 31,335 | 68.1 / 107.7 / 125.1 / 134.7 | 782 / 3,909 / 10,245 | 815 / 3,938 / 10,272 |
| late (last 10 min) | 0.17 | 32,712 of 32,808 | 4,505 / 14,568 / 21,629 / 31,335 | 66.7 / 112.8 / 131.6 / 134.7 | 3,294 / 11,827 / 30,866 | 3,314 / 11,844 / 30,879 |
| whole window | 9.04 | 89,051 of 104,836 | 16.9 / 82.9 / 2,405 / 31,335 | 1.31 / 9.12 / 88.6 / 134.7 | 3.8 / 56.0 / 1,603 | 42.0 / 196.7 / 1,633 |

- **Scheduled delay** (server metric, start − intended): calm mean 2.2 ms (p95 ≤ 5 ms, p99 ≤ 50 ms by bucket); battle mean 1,508 ms.
- **The tick's own code grew 50×** in the battle (p50 1.3 → 68 ms). Every step that did run had seconds of due motions, activities and evaluations to catch up on.
- **Phases, calm, ms of work per second:** perception sweep 29.9, slot evaluations 31.3, activity 10.9, wakes 8.1, motion 6.1. The tick's transaction averaged 6.5 ms (`reducer_plus_query`), against 1.3 ms of its own code; the difference is the 2,262 view refreshes per second it triggered, and the commit.

### Inputs (all 216 players, 80 ms RTT)

| Window | Inputs (per s) | Move: client p50 / p95 / p99 / max (ms) | Move: server receipt → committed p50 / p95 / p99 | Skill outcome: client p50 / p95 / p99 | Skill outcome: server p50 / p95 / p99 | Unanswered |
|---|---|---|---|---|---|---|
| calm | 43,165 (144) | 122 / 177 / 309 / 726 | 42 / 95 / 229 | — | — | 0 |
| battle | 505,381 (337) | 3,156 / 17,561 / 50,798 / 63,627 | 3,075 / 17,480 / 50,718 | 2,090 / 6,739 / 15,313 | 2,009 / 6,658 / 15,233 | 21,471 |
| late | 232,202 (387) | 7,565 / 30,737 / 57,173 | 7,484 / 30,657 / 57,093 | 5,842 / 18,976 / 49,079 | 5,762 / 18,896 / 48,999 | 21,471 |
| window | 548,546 (305) | 2,705 / 16,487 / 49,032 / 63,627 | 2,624 / 16,406 / 48,951 | 2,090 / 6,739 / 15,313 | 2,009 / 6,658 / 15,233 | 21,471 |

- **The calm phase already fails the server line** (p95 94.5 ms against 50). It is closest to a working world, so its parts are worth naming:
  - **Queue wait.** `human_move` waited a mean of 7.4 ms in the instance queue.
  - **The move's own transaction:** mean 1.36 ms, with the view refreshes it triggers (`reducer_plus_query`).
  - **The confirmed-read fsync:** about 38 ms at p50. Tick delivery was 3.6 ms unconfirmed against 41.2 ms confirmed.
- **Missing outcomes:**
  - 21,471 inputs were never answered: sent in the last minute while the queue was about 60 s behind, and still unanswered when the clients disconnected.
  - 92 accepted timed skills got no release and no recorded end.
  - Counted apart: 3,098 broken off before release ("broken off", "they moved away", "nothing to attack"), and 101 whose actor died in the windup.
- **Refusals dominate the battle's skill inputs:** 55,836 of 70,113 strikes. Most were "still recovering from your last move" and "already in the middle of a strike": the clients' `my_readiness` view arrived seconds late, so they retried moves the authority was still holding. In a healthy run this would be rare (smoke runs: 2–3% of strikes, all "out of reach").
- **Released skills, on the authority's own clock** (release − acceptance − declared windup): strike p50 1.7 s, p95 5.1 s. In smoke runs it was p50 9 ms, p99 16 ms: one tick of granularity.
- **Deaths and renewal:** 1,146 deaths and 1,145 rejoins in the battle. The battle group stayed at 100 throughout through ordinary `join`.

### Subscription bytes per client (on the wire, compressed)

| Window | Battle players, B/s p50 / p95 / max | Walkers, B/s p50 / p95 / max | Observer (owner, whole tables) | Game client |
|---|---|---|---|---|
| calm | 4,839 / 6,963 / 7,248 | 206 / 707 / 830 | 69.9 kB/s | 137 B/s |
| battle | 5,579 / 6,260 / 6,465 | 561 / 1,015 / 2,784 | 35.7 kB/s | 140 B/s |
| late | 4,043 / 4,481 / 4,592 | 980 / 2,185 / 3,144 | 21.5 kB/s | 98 B/s |

These are the bytes of a starved world: with 0.5 steps/s, bodies rarely moved. Battle bytes are a lower bound for a battle at 60 Hz. Per-table row events received over the run, summed over the 216 players: `seen_bodies` 6.07M, `my_combat` 4.00M, `seen_fighters` 3.34M, `seen_characters` 1.41M, `my_experience` 1.30M.

The game client's connection carried about 140 B/s. It placed and joined, then received almost nothing while the server was backed up. Its frames show the island and the crowd as of its last updates.

### Frames (game client, Radeon 8060S, uncapped)

| Window | FPS | Interval p50 / p95 / p99 / max (ms) | ≤ 16.7 ms | > 25 ms (missed) | > 50 ms (stutters) |
|---|---|---|---|---|---|
| calm | 183 | 5.25 / 7.24 / 10.24 / 49.1 | 99.70% | 37 | 0 |
| battle | 176 | 5.39 / 7.40 / 8.85 / 57.2 | 99.81% | 136 | 2 |
| late | 168 | 5.72 / 7.70 / 8.42 / 57.2 | 99.92% | 23 | 1 |

The client used 3.4 cores (mostly the uncapped loop).

### Server resources, memory, growth

| | Calm | Battle | Late |
|---|---|---|---|
| Server container CPU (cores, of 16) | 0.65 | 1.12 | 1.13 |
| Container memory (MB): start → end, max | 1,241 → 1,337 | 1,337 → 1,578, max 2,113 | 2,108 → 1,578 |
| Database WASM memory | 84.3 MB | 84.3 MB | 84.3 MB |
| jemalloc resident (node) | 836 → 832 MB | 832 → 1,083 MB | — |
| Instance operation queue (end) | 2 | 7,333 | 7,333 |
| Commitlog (`spacetime_message_log_size_bytes`) | 129.8 → 222.2 MB | 222.2 → 390.2 MB | — |

- **CPU.** The server never used more than about 1.15 of its 16 cores. One database runs its reducers and view refreshes on one thread, so the CPU budget was not the limit.
- **Tool processes** (cores, battle): players 0.30, relays 0.04, observer 0.01, watchers 0.00, mind 0.008, fake model 0.00.
- **Retained WAL.** The commitlog grew by 260 MB over the 30-minute window (about 520 MB/hour at this degraded throughput). The replica held 405 MB of `clog` and 78 MB of snapshots at the end; segments are compressed after snapshots, not trimmed.
- **Module log.** It grew 29 MB, profiling included.
- **Rows** (first and last sample of the run):
  - `experience` 20 → 29,202: players' windows, and dead characters' windows that stay.
  - `skill_use` 664 → 29,089: 24 per character, and 1,146 characters died.
  - `perceived` 4,626 → 14,619; `projected` 4,661 → 14,707.
  - `chronicle` 457 → 3,627 (capped at 4,000).
  - `inventory` 905 → 4,168, `structure` 446 → 1,622: newcomer kits and residents' building.
  - The `character`, `body` and `vitals` counts timed out in the last sample: SQL also waits in the backed-up queue.
- **Housekeeping** (1 Hz) ran 827 times instead of 1,800; interval p99 12.3 s, max 29.5 s. Its own work was p99 2.7 ms.

## Defect found: the missile sweep panics

In a smoke run of the same tools (6 battle players, 4 walkers), the tick **panicked and rolled back 8 times in a row**:
- Message: `unexpected update error: The row was not found` (`UniqueColumn<missile>::update` in `combat::missiles`).
- Each panic also replaced the WASM instance: `map.rebuild` 11 ms after each.
- No step committed for 364 ms.

The cause is in `living/authority/src/combat.rs` `missiles` (lines 399–452):
1. The due missiles are collected first.
2. A strike in the loop can kill a creature. `combat::died` (line 513) then deletes the dead creature's own missiles, including ones still later in the collected list.
3. The loop then calls `.update()` on a row that no longer exists and panics.
4. A rollback restores the same state, so the next steps hit the same missiles until their positions change the outcome.

The fix belongs to the combat owner and is not made here, because this branch changes no rules. It would re-read each missile (`ctx.db.missile().id().find(m.id)`) before using it and skip one that is gone. The 30-minute run logged no panic, because its battle barely stepped. A healthy battle with bows would hit it. `died`'s scan of every missile by owner (`missile().iter().filter(owner == id)`) is also unindexed.

## Next measured bottleneck

**The failing requirement:** 60 Hz steps, and through them every latency line.

**The cause, measured:** one database thread spends its time re-running per-sender perception views for every player who perceives a change, inside each transaction. In a cluster of 100 human players, each perceiving about 102 bodies:
- **Calm, players milling:**
  - `seen_bodies` 76.9 ms/s and `seen_fighters` 11.3 ms/s of view WASM.
  - The tick triggered 2,262 view refreshes/s, and each `human_move` about 9 (1,270 a second at 144 moves a second; about 19 in the warm-up sample below).
  - The tick's transaction averaged 6.5 ms against 1.3 ms of its own code.
- **Battle:**
  - `seen_bodies` 147 ms/s, `seen_fighters` 140 ms/s, `my_combat` 13 ms/s, `my_experience` 12 ms/s of view WASM, before materialising rows.
  - `use_skill` transactions averaged 8.2 ms and `human_move` 1.1 ms; 374,604 moves and 92,206 skill uses arrived in 25 minutes.
  - The input rate exceeds what one thread can commit, so the queue grows without bound: timing debt accumulates, the contract's explicit failure mode.

The live sample during warm-up shows the same:
- `seen_bodies` 270 ms of WASM per second;
- 552 ms/s of view time with materialisation;
- 4,688 view calls/s triggered by `human_move` alone.

The cost scales with players in a cluster × changes they perceive × rows per view: cubic in the cluster's size. That is what [perception](PERCEPTION.md) predicted for crowds ("refreshes per tick ≤ min(players, players perceiving a body that changed this tick)") and measured at 50 walkers (48 ms/s).

**With 30 humans fighting (arm B)**, the queue stays bounded but steps still skip. The ranking changes:
- `my_combat` 95 ms/s, the tick's own code 90 ms/s, `my_experience` 41 ms/s, `seen_fighters` 36 ms/s;
- the tick's transaction averages 38.8 ms, almost all of it the view refreshes its writes trigger.

So the next bottleneck after the cluster's motion views is the per-player feeds: `my_combat` re-runs at every expiry, and `my_experience` re-materialises up to 400 rows per line.

**Hypotheses, in order of expected gain (not measured):**
1. **Stop per-sender views from re-materialising their whole result when one perceived row changes.** In 2.14.1 a view re-runs in full in the writing transaction. Options:
   - player-scoped rows written once per change (a per-viewer motion table updated only for viewers in sight, as `projected` already is for characters);
   - batching motion into the tick, so a step refreshes each viewer at most once rather than once per write.
2. **Per-player feeds that do not re-materialise.** `my_experience` returns up to 400 rows and is re-run for each new line. `my_combat` is re-run each time a feed row expires (every tick). Candidates: expiry batched to a slower cadence, and windows read as smaller recent sets. Players already subscribe to them as views, so changing their shape changes the client protocol.
3. **Fewer writes that viewers read.** `fighter` rows change on every move start, release and end, so each re-runs `seen_fighters` for every onlooker; a battle writes them thousands of times a second. `my_combat` re-runs on every feed row.
4. **Durability on the response path.** Confirmed reads add about 30–40 ms (p50) to every delivery, against a 50 ms p95 server budget. Measure the fsync cadence, and whether the game client should take unconfirmed reads for presentation with confirmed ones for outcomes.
5. **Back-pressure.** A player's inputs are admitted without limit while the queue grows (the `input_hz` bucket counts per character, not per server load).

6. **The missile panic** ([defect](#defect-found-the-missile-sweep-panics)): it repeats a rolled-back step and replaces the instance until the missiles' state changes. It is a correctness fix before any battle measurement can pass.

## Diagnostic arm B: 30 humans in the battle

`gate-20261109-210040`. The same tools and the same 216 connections. 30 humans in the battle and 186 walkers spread round the settlements. 2 min warm-up, then a 10-minute window: 2 min calm, 8 min battle (here "late" is the battle). A diagnostic, not the gate: it is shorter, and the battle is a third of the size.

| | Calm (2 min) | Battle (8 min) |
|---|---|---|
| Steps/s; grid steps skipped | 56.6; 405 of 7,200 | 19.4; 19,471 of 28,799 |
| Step interval p50 / p95 / p99 / max (ms) | 16.8 / 32.4 / 33.8 / 49.8 | 50.4 / 90.1 / 107.5 / 158.0 |
| Lateness vs grid p50 / p95 / p99 (ms) | 1.9 / 2.8 / 4.9 | 3.3 / 9.1 / 11.3 |
| Tick code p50 / p95 / p99 (ms); tick transaction mean | 1.55 / 4.73 / 5.93; 4.5 ms | 4.09 / 10.1 / 13.2; 38.8 ms |
| Start → delivered, unconfirmed / confirmed p95 (ms) | 15.7 / 35.9 | 75.0 / 88.7 |
| Move, server receipt → committed p50 / p95 / p99 (ms) | 23.5 / 35.4 / 44.3 | 46.1 / 89.5 / 107.0 |
| Move, client input → received p50 / p95 / p99 (ms) | 103.8 / 116.3 / 129.2 | 126.6 / 170.8 / 191.0 |
| Skill outcome (windup taken off), server p50 / p95 / p99 (ms) | — | 93.6 / 155.5 / 182.4 |
| Skill outcome, client p50 / p95 / p99 (ms) | — | 174.1 / 237.2 / 265.4 |
| Released after declared windup, authority clock, strike p50 / p95 / p99 (ms) | — | 28 / 72 / 89 |
| Queue wait, `human_move` mean | 1.6 ms | 27.0 ms |
| Operation queue at the end | 0 | 7 |
| Unanswered inputs; accepted without outcome | 0; 0 | 0; 0 |
| Housekeeping interval p99 / max (ms) | 1,055 / 1,091 over the window | (same) |
| Server CPU (cores) | 0.50 | 1.01 |
| Bytes per battle player / walker, p50 (B/s) | 4,742 / 356 | 13,015 / 303 |
| Observer bytes | 79.9 kB/s | 82.2 kB/s |
| Frames ≤ 16.7 ms (uncapped, p99) | 99.99% (7.3 ms) | 99.94% (6.5 ms) |
| Commitlog growth | 31.9 MB in 2 min | 290 MB in 8 min (about 2.2 GB/hour) |

What arm B says:
- **The authority holds a bounded queue with 30 humans fighting, but not 60 Hz.** The tick's transaction averages 38.8 ms against 4.1 ms of its own code. The rest is the 1,900 view refreshes per second that the tick's writes trigger, and their materialisation. So steps skip about two grid steps in three.
- **Latency** passes the client line with moves only (p95 170.8 ms fails 150; calm passes at 116.3). The server line fails in the battle (p95 89.5 ms).
- **The views at the top change with a smaller cluster.**
  - `my_combat`: 94.6 ms/s of WASM. The feed's rows expire every tick, and each expiry re-runs the viewer's feed.
  - `my_experience`: 41.4 ms/s. A player's experience window, up to 400 rows, is re-materialised for each new experience line, and a battle writes several per blow.
  - `seen_fighters`: 36.3 ms/s; `seen_bodies`: 18.0 ms/s.
  - The tick's own code: 90 ms/s.
- **The missile defect reproduced:** two panics at 21:09:15, with the instance replaced (WASM memory fell from 84 to 16 MB).
- **Even calm 216-player life misses steps:** 5.6% of grid steps skipped. The tick's transaction (4.5 ms mean) plus the walkers' moves leave little slack against tokio's 1 ms timer and 2 ms mean scheduling delay. The contract counts a skipped step.
- **The commitlog grows fast:** about 2.2 GB/hour during this battle. It is reported apart from active memory, as the contract asks, but a long run needs the archive plan.

## SpacetimeDB documentation and source consulted (2026-11-09)

Pinned: `spacetimedb = "=2.14.1"`, `spacetimedb-sdk = "=2.14.1"`, server image `v2.14.1` (commit `a0bf6be`). The live docs' selector reads 2.0.0. Every claim the measurement relies on was checked in the v2.14.1 source.

| Source | What it says | What follows here |
|---|---|---|
| [Reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context/) | `timestamp`: "Time when the reducer was invoked". | Source: taken before the per-database queue (`module_host.rs:2489`). Used as server receipt; queue wait is inside the interval. |
| [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) | "Interval schedules are anchored to their intended execution times"; when late, "schedules the next future tick rather than running missed ticks back-to-back". | Missed steps are counted as skipped grid steps. `ctx.timestamp` of a scheduled call is `max(intended, now)` (`scheduler.rs:992-999`). |
| [Subscription semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics) | "Responses to client requests are always sent back in the same order the requests were received"; updates "reflect the exact order of committed transactions". | Per-connection call order holds. The SDK folds the caller's rows into the call's reply (`module_subscription_manager.rs:2104-2141`), so the `_then` callback times the outcome. |
| Source only: confirmed reads | `DEFAULT_CONFIRMED_READS = true` (`client-api/src/lib.rs:35`); messages wait until `durable_offset ≥ tx_offset` (`client_connection.rs:226-255`). | Client-observed latency includes the fsync. The tick watcher measures it with and without. |
| Source only: metrics | `spacetime_reducer_wait_time_sec` (enqueue → start), `spacetime_reducer_plus_query_duration_sec` (transaction with views, commit and delta evaluation), `spacetime_scheduled_function_delay_seconds`, `spacetime_message_log_size_bytes`, `view_*_time_usec`. | The resource and queue numbers above. |
| [Views](https://spacetimedb.com/docs/functions/views/) | Per-sender views compute separately for each subscriber. | The measured bottleneck; details in [perception](PERCEPTION.md). |

No table, reducer, view or subscription was added or changed.

## Reproduce

On a Linux host with podman (docker CLI), `pasta`, Vulkan, and the game assets (`just living-game-assets`):

```bash
export CARGO_TARGET_DIR=$PWD/.local/living/gate-target
LIVING_SEED=island cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
cargo build --release --manifest-path living/Cargo.toml -p living-mind -p living-game
cargo build --release --manifest-path living/tools/gate_load/Cargo.toml
living/tools/gate.py run                      # the gate: 100 battle + 116 walkers, 5 min warm-up, 30 min
living/tools/gate.py run --battle 30 --walkers 186 --warmup 120 --seconds 600 --calm 120   # arm B
living/tools/gate.py run --smoke              # 6 + 4 players, 2 minutes: checks the harness
living/tools/gate.py analyze .local/living/gate/<run>
living/tools/gate.py cleanup --container      # its own processes by recorded PID, its container and volume
```

`gate.py` starts its own container (`GATE_STDB_CONTAINER`, default `gate-stdb`, port 3397) and publishes only `verify-gate-*` databases, deleting each afterwards unless `--keep`. It stops only processes it recorded (`.local/living/gate/pids.json`, each checked against its command line). The verdicts are in `report.json`.

## Evidence

On the dev-box worktree (`~/dev/slop-gate`), git-ignored:
- `.local/living/gate/gate-20261109-200119/`: the 30-minute run;
- `.local/living/gate/gate-20261109-210040/`: arm B;
- `.local/living/gate/smoke-20261109-195736/`: the smoke run with the missile panic;
- the other `smoke-*` directories: the runs that debugged the harness.

Each holds:
- `manifest.json`, `calibration.json`, `skill_cards.json`, `marks.json`, `run.log`;
- `events.jsonl`: every input, reply and skill-use state;
- `ticks.csv`: every tick's delivery to the watchers;
- `module.log.gz`: the module's spans;
- `samples.jsonl.gz`: metrics, cgroup, rows and disk;
- `relay-*.jsonl`: bytes per connection;
- `game/frames.csv`;
- `players-done.json` and `observer-done.json`: row events per connection;
- `report.json`: everything above, analysed, with the verdicts.

## What this does not establish

- The workload is one choice. A battle of human clients is the costliest case for perception views; a battle of instinct fighters is cheaper and is not measured here. The battle group stays in one cluster for 25 minutes.
- The host was shared, and the load generator and game client ran beside the server. The database's thread was saturated by its own work (about one core) while 15 more were free to it, so contention is not the explanation for the collapse. It does add noise to the calm-phase numbers.
- The game client never drew a 100-fighter battle moving at 60 Hz. Frame pacing under a working battle remains unmeasured.
- Network: 80 ms round trip on loopback, no jitter or loss. It is not a WAN impairment profile.
- Correctness gates at load (scoped privacy, reconnect recovery, causal evidence) were not re-verified.
