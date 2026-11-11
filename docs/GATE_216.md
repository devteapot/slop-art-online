# The immediate gate: 216 active characters for 30 minutes

2026-11-09. The first measurement of the [performance contract](PERFORMANCE_CONTRACT.md)'s immediate gate on the living core: 216 active characters for 30 minutes with a crowded battle, at 80 ms round trip, against every requirement the contract lists. Branch `gate-1`, code under test `14f3a72` (main) plus the measurement tools below. Earlier 216-character evidence came from the removed legacy stack ([short baseline](PERFORMANCE_BASELINE_25.md)).

**Update (2026-11-10, branch `scale-1`).** Perceived state is now delivered once per frame per player, and the feeds' and views' hidden costs are gone ([scale change](#scale-change-frames-2026-11-10-branch-scale-1)). [Final measurements](#final-measurements-after-merging-main-3ff9e8a-arrival-1-the-battle-in-the-town), on main `3ff9e8a` merged, with the battle inside the town since `arrival-1`: the 30-minute gate still fails 60 Hz and both latency lines (battle 4.9 steps a second, the queue bounded), the calm passes both latency lines with the game client's unconfirmed reads, and housekeeping misses by one interval (1,530 ms against 1,500). With 30 fighters every latency line passes in the battle with the game client; 60 Hz does not (56 steps a second). What follows here is the first measurement as it was.

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

## Scale change: frames (2026-11-10, branch `scale-1`)

What was changed, and what it did to each line of the contract. The design is in [perception](PERCEPTION.md#frames-what-others-do-reaches-a-player-once-per-frame). Privacy, rules and the views' shapes are unchanged; one view's window and the feed's row lifetimes are smaller (below).

### What was changed

The gate's hypotheses, in the order they were measured, and what each measurement found:

1. **No view re-runs on one perceived row's change (hypothesis 1, frames).** The `seen_*` views read per-viewer copies (`motion_seen`, `fighter_seen`, `doing_seen`, the band of `projected`) that the tick writes at each viewer's frame, only for what changed since its last one. A player's own body, fighter row and projection are read directly, so its own moves and outcomes arrive in their own transaction. Frames come every 33–100 ms by scene size; a step serves at most 2,500 creatures of scene, stalest viewers first.
2. **Feeds that do not re-materialize (hypothesis 2).**
   - `my_combat`: an onlooker's rows are written at its frame and kept 300 ms; the two involved get theirs at once for 1.5 s (a refusal 4 s). The per-tick expiry is gone: a viewer's rows expire at its frame, with a 1 Hz sweep for the rest. **The measured cause was not expiry:** every death sent a DEATH row to every onlooker, kept two minutes, so in arm B's battle `combat_seen` held 10–14k rows and each player's feed re-materialized hundreds of old deaths at every refresh. Now only the one who died keeps its death and witnesses, until it joins again.
   - `my_experience`: the newest 64 lines of the living character (or of the last character while none lives), released at its frames through `line_seen`, which holds a copy of each line. **The measured cause:** the view returned the window of every character the player ever had. A battle player who had died 25 times re-read 25 windows at each new line (855 µs a refresh).
3. **Fewer viewer-visible writes (hypothesis 3).** Subsumed by frames: a `fighter` row written at a move's start, release and end now re-runs no one's view; a frame copies its state once.
4. **A cost the gate did not name: every refresh scans the whole database's read set.** A `perf` profile of a symbolized 2.14.1 server (built from tag `v2.14.1` with line tables) during a 100-fighter battle put 11.4% of the server's CPU in one function, plus about 3.5% in the value comparisons it calls: `TableReadSet::remove_view_call` (`crates/datastore/src/locking_tx_datastore/mut_tx.rs:562`). When a refreshed view commits, 2.14.1 drops its old read set with a `retain` over every key of every view in the database. So each refresh costs time in proportion to the total number of keys all views read: players × keys per view. Before this change `seen_bodies`, `seen_fighters` and `seen_doing` read one key per creature in the scene, and `my_experience` up to 400 per character the player ever had. Now each view reads a handful of keys (the viewer's copies by one index point; `my_experience` one point on `(observer, true)`).
5. **Tick code.** `perceive::witnessed` projects each onlooker's label of the subject once (it was three times per onlooker, the know-how list read each time), and a frame reads each changed creature's rows once per tick for all viewers.

### Arms and method

Every arm is the authority module built from `1693f3e` plus the change as it then stood, published by `gate.py` into my own container (`scale-stdb`, `clockworklabs/spacetime:v2.14.1`, `--cpus 16`, port 3407) with the same load tools, network shaping, game client, observer and minds as the gate. Each run's `manifest.json` names the module's hash.

| Arm | Module (sha256, first 10) | What it adds |
|---|---|---|
| base | `e141e451af` | main `1693f3e` as merged (the gate's code plus the missile fix) |
| frames1 | `b0f1510dc7` | frames for motion, fighter state and bands; onlookers' feed at frames; `my_experience` through `line_seen` (64 lines) |
| frames2 | `3e056cdc89` | only the dead keep their death rows; a join clears the feed; `my_experience` of the living character only |
| frames3 | `14be632ee3` | frames every other tick at most; moves in `fighter_seen` (`seen_characters` no longer re-runs on moves); bands to projections every 250 ms; the involved's feed rows 1.5 s |
| frames5 | `2a87ca0677` | `doing_seen`; `line_seen` holds the line (every view a handful of keys); `witnessed` labels once; per-tick source reads |
| frames6 | `a5bd2291d3` | the per-step frame budget (2,500 creatures of scene); onlookers' rows 300 ms; projections' bands each second. **The branch's code.** |

Tools added: `living/tools/gate_compare.py` (side-by-side report tables), `living/tools/gate_counters.py` (per-second Prometheus counters over a run's window), and in `gate.py` a `GATE_WASM_DIR` override, a ping loop that survives a starting container, and retried identity minting. A symbolized server for profiling was built from tag `v2.14.1` (`--profile profiling`, line tables) and run natively on port 3417; the A/B runs used only the official image.

**Host load.** The dev-box was shared throughout (other agents' builds and labs); each table gives the 1-minute load average's median. The full 30-minute run overlapped my own verification suites in a second container (`scale-verify`) for its first 20 minutes.

### Arm B (30 fighters, 186 walkers), battle window (8 min)

| | base | frames1 | frames2 | frames3 | frames6 |
|---|---|---|---|---|---|
| Run | `gate-20261109-214939` | `-220506` | `-223432` | `-230833` | `gate-20261110-005041` |
| Steps/s; grid steps skipped | 19.0; 19,688 of 28,796 | 18.6; 19,882 | 43.3; 8,032 | 49.2; 5,174 | 53.0; 3,338 |
| Step interval p50 / p95 / p99 (ms) | 50.0 / 105.7 / 151.0 | 33.6 / 157.5 / 226.2 | 17.2 / 37.6 / 50.6 | 17.0 / 34.1 / 50.0 | 16.9 / 33.4 / 34.5 |
| Tick transaction mean (ms) | 39.4 | 38.4 | 12.6 | 9.4 | 7.6 |
| Views' time with materializing (ms/s) | 610 | 341 | 230 | 152 | 136 |
| Move, server p95 / p99 (ms) | 130.6 / 187.0 | 225.5 / 857.2 | 69.3 / 89.7 | 55.5 / 72.0 | 50.7 / 63.8 |
| Move, client p95 / p99 (ms) | 212.5 / 269.4 | 306.7 / 937.5 | 150.9 / 179.7 | 137.0 / 161.4 | 132.1 / 152.7 |
| Skill outcome, server p95 / p99 (ms) | 200.9 / 273.0 | 317.3 / 614.5 | 91.5 / 118.7 | 76.2 / 99.0 | 72.5 / 87.0 |
| Skill outcome, client p95 / p99 (ms) | 282.2 / 354.2 | 397.9 / 694.9 | 172.7 / 209.5 | 157.8 / 186.8 | 153.6 / 175.7 |
| Queue wait, `human_move` mean (ms) | 31.9 | 66.9 | 6.8 | 4.7 | 3.0 |
| Host load (1 min, p50) | 14.3 | 23.6 | 19.0 | 12.5 | 12.6 |

frames6's calm window: 59.2 steps/s (91 of 7,200 grid steps skipped), move server p95 / p99 45.4 / 55.6 ms, client 126.4 / 144.0 ms: the calm passes both latency lines. In the battle the client line passes for moves (p95 132.1, p99 152.7) and the server line misses by 0.7 ms at p95 (50.7); skills miss both (server p95 72.5, client p95 153.6), and 11.6% of grid steps are skipped.

frames1 did not help: in arm B every battle player's scene is small enough that its frame came every tick, and the feed's cost was not where the gate had placed it. Its counters (`view_total_time_usec`, `view_calls`, the `combat_seen` row count) found the two causes that frames2 removed. frames3's calm window: 58.5 steps/s, move server p95 42.6 ms, client p95 123.5 ms (base 57.0, 39.5, 120.9).

### 100 fighters, 116 walkers: a 9-minute form (2 min warm-up, 2 min calm, 5 min battle), back to back

| | base `gate-20261110-000002` | frames5 `gate-20261109-233615` | frames6 `gate-20261109-234826` |
|---|---|---|---|
| Calm: steps/s; move server p95; client p95 (ms) | 9.2; 419.5; 500.4 | 42.5; 81.2; 162.5 | 44.6; 88.9; 170.2 |
| Battle: steps/s; grid steps skipped | 1.0; 17,608 of 17,908 | 4.0; 16,785 | 5.5; 16,361 of 17,991 |
| Battle: tick code p50 / p95 (ms); transaction mean | 65.9 / 103.6; 266 | 81.4 / 134.2; 191 | 54.0 / 98.7; 149 |
| Battle: move server p95 / p99; client p95 (ms) | 2,720 / 3,734; 2,801 | 367 / 451; 448 | 260 / 308; 342 |
| Battle: skill outcome server p95; client p95 (ms) | 3,165; 3,246 | 626; 707 | 437; 518 |
| Battle: `human_move` queue wait mean (ms); operation queue at the end | 1,290; 329 (growing) | 177; 0 | 113; 0 |
| Host load (1 min, p50), battle | 16.0 | 14.7 | 14.3 |

The base's calm is far worse here (9.2 steps/s) than in the gate's own run (50.2); the short form has a 2-minute warm-up and the host differed. The frames arms are compared with this base, which ran right after frames6.

### The full gate, 30 minutes: before and after

The same workload as the gate (100 fighters, 116 walkers, 5 min warm-up, 30 min window: calm 5, battle 25), `gate-20261110-001148` (frames6) against the gate's own run `gate-20261109-200119` (`14f3a72`, earlier the same day on the same host; a 30-minute base run was not repeated: it fails the same way, by minutes of queue).

| Requirement (locked) | Before | After | Measured after, 30-min window |
|---|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail**: 9.0 steps/s overall, battle 0.51, late 0.17; queue 7,333 | **fail**: 12.5 steps/s overall, calm 51.4, battle 4.7, late 2.5; queue 41 at the end, bounded | Step interval p50 / p95 / p99 in the battle 186 / 464 / 618 ms (before 1,457 / 5,248 / 12,852). Tick code p50 65 ms in the battle: the tick's own work, not views (below). |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail**: move window p95 16.4 s / p99 49.0 s | **fail**: move window p95 440 ms / p99 617 ms; skill outcome p95 722 ms / p99 1,007 ms | Calm: move p95 154 ms, p99 437 ms (before 94.5 / 228.5; this calm overlapped my verification builds and their fsyncs, and its confirmed delivery doubled to 142 ms at p95; arm B's calm, measured without them, is unchanged from its base). |
| Client input → outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail**: move window p95 16.5 s / p99 49.0 s; 21,471 unanswered | **fail**: move window p95 521 ms / p99 698 ms; 0 unanswered | Skill outcome p95 803 ms / p99 1,088 ms. |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | pass, weak | **pass, weak** | 99.87% (calm), 99.97% (battle), 100% (late) within 16.7 ms; 66 frames over 25 ms and 8 over 50 ms in the battle. The client now draws a battle that moves (5 steps a second on the authority, 9.4 kB/s per battle player), still not a 60 Hz one. |
| Slow systems at their deadlines (1 Hz housekeeping) | **fail**: 827 runs, interval p99 12.3 s | **pass** | 1,799 runs in 1,800 s; interval p50 1,000 ms, p99 1,250 ms, max 1,441 ms. |

Inputs: 274 a second in the battle (base 337); 4,700 deaths and rejoins kept the battle group at 100. Memory: container 6.9 → 9.8 GB, service-wide (this container held every arm's databases, deleted after each run); WASM memory 84.3 MB throughout; commitlog 0.70 → 2.99 GB over the window (about 4.6 GB/hour at this throughput, reported apart from active memory).

### After merging main `fe6ec66` (megacity-1, soak-1): the final measurements

Main moved while this was measured: `megacity-1` (floors, a new island generator) and `soak-1`. The branch was merged with main at `fe6ec66` and measured again; the island itself changed (arrival at (304.5, 319.5), it was (512.5, 174.5)), so these runs compare only with each other. Before is main `fe6ec66`'s module (`14c12c2d2f`), after is the merge (`07677b08ae`), back to back on the same container, without anything else of mine on the host.

| Arm B (30 fighters), battle (8 min) | main `gate-20261110-083859` | merge `gate-20261110-085253` |
|---|---|---|
| Steps/s; grid steps skipped | 23.6; 17,491 of 28,800 | 56.6; 1,690 of 28,797 |
| Step interval p50 / p95 / p99 (ms) | 38.1 / 81.8 / 102.7 | 16.8 / 25.8 / 34.2 |
| Tick transaction mean (ms) | 30.4 | 5.8 |
| Views' time with materializing (ms/s) | 582 | 86 |
| Move, server p95 / p99 (ms) | 99.0 / 124.0 | 52.2 / 67.9 |
| Move, client p95 / p99 (ms) | 180.1 / 208.3 | **133.5 / 158.5** |
| Skill outcome, server p95 / p99 (ms) | 150.5 / 188.5 | 79.7 / 113.6 |
| Skill outcome, client p95 / p99 (ms) | 232.2 / 272.8 | 161.8 / 204.1 |
| Queue wait, `human_move` mean (ms); queue at the end | 22.5; 5 | 2.5; 0 |
| Host load (1 min, p50) | 15.1 | 15.8 |

Calm (2 min): both hold 60 Hz (59.9 and 59.7 steps/s). Frames cost the calm tick about 0.9 ms (its transaction 3.37 → 4.23 ms: the frames and the sweep's extra rows), which moves the calm move's server p95 from 48.0 to 50.8 ms (p99 57.2 → 60.3): **just over the 50 ms line where main is just under it**. The client line passes in both (p95 128.8 and 132.0 ms).

**The full gate on the merge** (`gate-20261110-090632`; 100 fighters, 116 walkers, 5 min warm-up, 30 min window), with nothing else of mine on the host (load p50 13.5–13.9):

| Requirement (locked) | Verdict | Measured, 30-min window |
|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail** | 12.7 steps/s overall: calm 55.7 (1,292 of 17,999 grid steps skipped), battle 4.0, last 10 min 2.4. Operation queue 0 at the end. Battle step interval p50 / p95 / p99 240 / 477 / 603 ms; tick code p50 77 ms (`tick.activity` 144, `tick.wakes` 88, `tick.frames` 48, `tick.perception` 42 ms/s). |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail** | Moves: calm p95 51.6 / p99 63.6 ms; window p95 425 / p99 547 ms. Skill outcomes: window p95 706 / p99 908 ms. |
| Client input → outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail** | Moves: calm p95 132.7 / p99 150.3 ms (passes); window p95 506 / p99 628 ms; 0 unanswered. Skill outcomes: window p95 786 / p99 988 ms. |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | **pass, weak** | Battle: 100.0% within 16.7 ms, no frame over 25 ms. |
| Slow systems at their deadlines (1 Hz housekeeping) | **pass** | 1,800 runs in 1,800 s; interval p99 1,272 ms. |

This run's calm, free of my verification load, answers the calm regression of `gate-20261110-001148`: move p95 51.6 ms at the server and 132.7 ms at the client, against 94.5 and 176.7 ms in the gate's own run. The battle and the last ten minutes are where `gate-20261110-001148` left them, and the world grew the same way (6,083 characters, 6,178 structures by the end).

The harness found one more defect on the way: with the shell's soft limit of 1,024 open files, the relay ran out of descriptors after about 170 players ("Too many open files"), and the players' process then died with exit 101 and no message. `gate.py` now raises its soft limit to the hard one at start (an earlier unexplained exit 101 in this work was probably the same).

### After merging main `0812ada` (path-1, rethink-1): two client arms

Superseded by the [final measurements](#final-measurements-after-merging-main-3ff9e8a-arrival-1-the-battle-in-the-town) below; kept as measured.

The merge with main `0812ada` (merge `0c39794`, module `f32ced6837`; main's module `91887f0844`) carries the player verbs' client (`fa53e0b`, already in `fe6ec66`): `living/game` now reads unconfirmed, subscribes the `skills` script row and `resource_node` and `structure` in its near window, and sends input in the frame it is made. The players `gate.py` runs stand for one client or the other (`--client`, recorded in each manifest as `workload.client`):
- **`gate`**: what the gate first measured: confirmed reads (the SDK default) and the gate's subscriptions. Every number above this section used it.
- **`game`**: `living/game` since the player verbs: unconfirmed reads, the script row, the resource and structure windows.

The headless game client in every run is `living/game` itself, reading unconfirmed since `fa53e0b`; it gives only the frame-pacing line. All runs below were back to back with nothing else of mine on the host (load p50 7–12).

**Arm B (30 fighters), battle (8 min).** Before is main `0812ada`, after is the merge.

| | `gate` client: main `gate-20261110-114536` | `gate` client: merge `-115926` | `game` client: main `-121259` | `game` client: merge `-122701` |
|---|---|---|---|---|
| Steps/s; grid steps skipped | 33.9; 12,545 of 28,799 | 53.1; 3,350 | 28.2; 15,317 | 43.9; 7,738 |
| Tick transaction mean (ms) | 17.8 | 7.6 | 24.0 | 11.5 |
| Move, server p95 / p99 (ms) | 51.4 / 61.5 | **31.0 / 38.0** | **46.5 / 59.8** | 51.6 / 67.2 |
| Move, client p95 / p99 (ms) | **132.7 / 146.9** | **112.0 / 123.7** | **127.9 / 144.8** | **133.3 / 151.7** |
| Skill outcome, server p95 / p99 (ms) | 93.3 / 107.7 | 50.9 / 61.1 | 103.6 / 123.0 | **41.5 / 52.1** |
| Skill outcome, client p95 / p99 (ms) | 174.5 / 190.8 | **132.1 / 145.5** | 184.8 / 206.9 | **122.7 / 138.2** |
| Queue wait, `human_move` mean (ms) | 11.2 | 3.2 | 16.3 | 9.6 |

Bold: within the contract's line (≤50 / ≤100 ms at the server, ≤150 / ≤250 ms at the client). Calm (2 min) holds about 60 Hz and passes both lines in all four; with the `game` client, moves arrive in 88–90 ms at p95 at the client and 7–8 ms at the server, the fsync gone from both.

- With the `gate` client the merge passes both lines for moves and the client line for skills in the battle (skills miss the server's p95 by 0.9 ms); 60 Hz still fails (11.6% of grid steps skipped).
- With the `game` client the server line no longer includes the fsync, so skills pass both lines; moves miss the server's p95 by 1.6 ms.
- The merge's `game`-client run cost the tick far more than its `gate`-client run (297 against 165 ms/s of tick code: `tick.wakes` 101 against 28, `tick.activity` 100 against 41) with fewer deaths (555 rejoins against 736) and fewer accepted skills (9,400 against 11,877; more refused as "already in the middle of" a move, since the players see their own moves sooner). Rows the subscriptions scanned and sent were lower, so the windows are not the cause. One run each: whether the client arm or run-to-run variance in the battle (who else joins it) explains the difference is not established.

**The full gate on the merge, `game` client** (`gate-20261110-124038`; 100 fighters, 116 walkers, 30 min):

| Requirement (locked) | Verdict | Measured, 30-min window |
|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail** | 13.2 steps/s overall: calm 56.1, battle 4.7, last 10 min 2.4; operation queue 70 at the end. |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail** | Moves: calm p95 10.8 / p99 19.2 ms (passes); window p95 390 / p99 525 ms. Skill outcomes: window p95 702 / p99 933 ms. |
| Client input → outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail** | Moves: calm p95 92.3 / p99 103.8 ms (passes); window p95 471 / p99 606 ms. Skill outcomes: window p95 783 / p99 1,014 ms. |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | **pass, weak** | Battle: 100.0% within 16.7 ms. |
| Slow systems at their deadlines (1 Hz housekeeping) | **pass** | 1,800 runs; interval p99 1,272 ms. |

Against the same gate with the `gate` client on the earlier merge (`gate-20261110-090632`): calm moves fall from 51.6 to 10.8 ms at the server and from 132.7 to 92.3 ms at the client at p95, which is the fsync; the battle is where the database thread's saturation leaves it either way (4.0 and 4.7 steps a second, moves 439 and 405 ms at the server's p95).

**On main as well:** `verify-player`'s `combat.py` fails five checks on main `0812ada` exactly as on the merge (the bow's arrow "struck a wall"; the graph attacker never reaches the player in the block, dodge and heal scenes): the scene's fixed offsets from the arrival point meet walls on the island the merged generator now builds. A driver fixture to move, not a rule failure, and not this branch's.

### After merging main `8fd4f43` (hunger-1, trials-1, merge-guard)

Superseded by the [final measurements](#final-measurements-after-merging-main-3ff9e8a-arrival-1-the-battle-in-the-town) below; kept as measured.

The branch was merged with main `8fd4f43` (merge `2a8e0fa`; it already held seeded lives `bdca15f` and `path-1` `7e5de53` from the `0812ada` merge, so the island's 277 authored residents and the hierarchical routes were in the runs above too; `8fd4f43` changed the island seed again: residents' food places). Before is main `8fd4f43`'s module (`c2c30cd071`), after is the merge (`4dd8559b3e`), back to back, nothing else of mine on the host (load p50 7–12). Every run starts with 528 characters. The client arm of each run is named.

**Arm B (30 fighters), battle (8 min):**

| | `gate` client: main `gate-20261110-145110` | `gate` client: merge `-150501` | `game` client: main `-151834` | `game` client: merge `-153236` |
|---|---|---|---|---|
| Steps/s; grid steps skipped | 26.4; 16,193 of 28,799 | 52.0; 3,884 | 28.4; 15,189 | 51.7; 4,011 |
| Tick transaction mean (ms) | 26.2 | 7.9 | 23.6 | 7.9 |
| Move, server p95 / p99 (ms) | 67.4 / 83.9 | **31.8 / 39.5** | **46.8 / 58.1** | **16.5 / 24.2** |
| Move, client p95 / p99 (ms) | 148.8 / 168.9 | **112.8 / 125.2** | **128.3 / 143.9** | **97.9 / 109.6** |
| Skill outcome, server p95 / p99 (ms) | 127.1 / 153.2 | 53.0 / 64.9 | 105.0 / 123.3 | **44.7 / 57.2** |
| Skill outcome, client p95 / p99 (ms) | 208.5 / 235.2 | **134.5 / 151.3** | 186.5 / 207.0 | **126.0 / 141.1** |
| Queue wait, `human_move` mean (ms) | 18.6 | 3.5 | 16.2 | 3.5 |

Bold: within the line. Calm (2 min) holds about 60 Hz and passes both lines in all four (moves at the client p95 103.6 and 104.1 ms with the `gate` client, 89.2 and 88.3 ms with the `game` client).

- **With the `game` client every latency line passes in arm B's battle on the merge**; with the `gate` client all but the skills' server p95 (53.0 ms). 60 Hz does not: 52 steps a second, 13–14% of grid steps skipped.
- The tick cost the same under both client arms here (165 and 166 ms/s of tick code, 756 and 777 rejoins), so the 297 ms/s of the `0812ada` merge's `game`-client run was the battle's variance, not the client arm.

**The full gate on the merge, `game` client** (`gate-20261110-154610`; 100 fighters, 116 walkers, 30 min):

| Requirement (locked) | Before: the gate's run `gate-20261109-200119` (`gate` client) | After |
|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail**: 9.0 steps/s; battle 0.51; queue 7,333 | **fail**: 12.9 steps/s overall; calm 55.4 (1,370 of 17,999 grid steps skipped), battle 4.4, last 10 min 2.4; queue 0 at the end |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail**: moves p95 16.4 s | **fail**: moves calm p95 11.4 / p99 19.9 ms (passes), window p95 387 / p99 494 ms; skills window p95 691 / p99 858 ms |
| Client input → outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail**: moves p95 16.5 s; 21,471 unanswered | **fail**: moves calm p95 92.7 / p99 103.3 ms (passes), window p95 468 / p99 576 ms; skills window p95 772 / p99 939 ms; 0 unanswered |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | pass, weak | **pass, weak**: battle 100.0% within 16.7 ms, one frame over 25 ms |
| Slow systems at their deadlines (1 Hz housekeeping) | **fail**: 827 runs | **pass**: 1,800 runs, interval p99 1,282 ms |

The battle's tick is the next bottleneck, as named below: 329 ms/s of tick code (`tick.activity` 142, `tick.wakes` 90, `tick.frames` 49, `tick.perception` 38), and the world grows from 528 to 6,127 characters and 6,232 structures over the 30 minutes as the battle's dead are replaced.

Verification on this merge: `just living-check` exit 0 (rules 116 passed); `verify-client` scoped 30 of 30; `verify-core` `sight` 6 of 6, `skirmish` 8 of 8, `town.py` 20 of 21 (the approach scene, known to be flaky); `verify-player` `gesture.py` 10 of 10.

### After merging main `67cdb0a` (rules-2)

Superseded by the [final measurements](#final-measurements-after-merging-main-3ff9e8a-arrival-1-the-battle-in-the-town) below (a new arrival, the battle in the town); kept as measured, on the road site.

The branch was merged with main `67cdb0a` (merge `d1d39be`): `rules-2` (skill specs in the script, `mending` renamed `wound_tending`, private record tables and a `my_records` view) on top of the `8fd4f43` merge. Before is main `67cdb0a`'s module (`b4c67ef585`), after is the merge (`9dc1cd8f0a`), back to back, nothing else of mine on the host (load p50 7–12). Every run starts with 528 characters. The client arm of each run is named (`gate`: confirmed reads and the gate's subscriptions; `game`: `living/game`'s unconfirmed reads and windows).

**Arm B (30 fighters), battle (8 min):**

| | `gate` client: main `gate-20261110-170555` | `gate` client: merge `-171947` | `game` client: main `-173319` | `game` client: merge `-174724` |
|---|---|---|---|---|
| Steps/s; grid steps skipped | 24.6; 17,005 of 28,798 | 53.6; 3,135 | 27.1; 15,804 | 56.2; 1,890 |
| Tick transaction mean (ms) | 28.8 | 7.4 | 24.9 | 6.2 |
| Move, server p95 / p99 (ms) | 68.5 / 82.6 | **30.5 / 37.6** | 51.1 / 65.8 | **12.9 / 19.9** |
| Move, client p95 / p99 (ms) | **149.9 / 168.2** | **111.5 / 122.9** | **132.7 / 152.2** | **94.1 / 104.4** |
| Skill outcome, server p95 / p99 (ms) | 125.3 / 144.4 | **50.0 / 60.4** | 115.5 / 135.8 | **39.1 / 51.2** |
| Skill outcome, client p95 / p99 (ms) | 206.4 / 228.5 | **131.3 / 143.6** | 197.1 / 218.2 | **120.9 / 139.4** |
| Queue wait, `human_move` mean (ms) | 20.2 | 3.2 | 17.6 | 2.4 |

Bold: within the line. Calm (2 min) holds about 60 Hz and passes both lines in all four (moves at the client p95 103.5 and 104.2 ms with the `gate` client, 88.9 and 87.6 ms with the `game` client). **On the merge every latency line passes in arm B's battle with both client arms** (the `gate` client's skills at exactly 50.0 ms at the server's p95); 60 Hz does not (53.6 and 56.2 steps a second, 7–11% of grid steps skipped). The tick cost was alike under both arms (166 and 160 ms/s of tick code).

**The full gate on the merge, `game` client** (`gate-20261110-180100`; 100 fighters, 116 walkers, 30 min):

| Requirement (locked) | Before: the gate's run `gate-20261109-200119` (`gate` client) | After |
|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail**: 9.0 steps/s; battle 0.51; queue 7,333 | **fail**: 13.0 steps/s overall; calm 55.8 (1,245 of 17,999 grid steps skipped), battle 4.4, last 10 min 2.3; queue 0 at the end |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail**: moves p95 16.4 s | **fail**: moves calm p95 10.5 / p99 18.8 ms (passes), window p95 410 / p99 520 ms; skills window p95 718 / p99 894 ms |
| Client input → outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail**: moves p95 16.5 s; 21,471 unanswered | **fail**: moves calm p95 91.8 / p99 102.3 ms (passes), window p95 492 / p99 600 ms; skills window p95 799 / p99 974 ms; 0 unanswered |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | pass, weak | **pass, weak**: battle 100.0% within 16.7 ms, none over 25 ms |
| Slow systems at their deadlines (1 Hz housekeeping) | **fail**: 827 runs | **pass**: 1,799 runs, interval p99 1,284 ms |

The battle's tick is the next bottleneck, as named below: 329 ms/s of tick code (`tick.activity` 143, `tick.wakes` 90, `tick.frames` 49, `tick.perception` 38), and the world grows from 528 to 6,182 characters and 6,263 structures over the 30 minutes.

Verification on this merge: `just living-check` exit 0 (rules 120 passed); `verify-client` scoped 30 of 30 (with `rules-2`'s `record`, `record_party` and `record_clock` and the frame tables in the private inventory); `verify-core` `sight` 6 of 6, `skirmish` 8 of 8, `town.py` 20 of 21 (the approach scene, known to be flaky); `verify-player` `gesture.py` 10 of 10.

### Final measurements: after merging main `3ff9e8a` (arrival-1), the battle in the town

`arrival-1` moved the island's arrival onto the first town's square, and `gate.py` stages its battle 30 m north of the arrival, so **this round's battle is fought inside the town**, among walls and houses, where every earlier round fought on open ground. Which arrival each round used (all on the `island` seed, battle site = arrival − 30 m in y):

| Rounds | Island | Arrival (x, y) | Battle site |
|---|---|---|---|
| The gate's first runs and arm B, base to frames6 (`gate-20261109-*`, `gate-20261110-000002`, `-001148`) | main `1693f3e` and earlier | (512.5, 174.5) | (512.5, 144.5), open ground north of the arrival |
| The `fe6ec66`, `0812ada`, `8fd4f43` and `67cdb0a` merges (`gate-20261110-08*` to `-180100`) | megacity's generator | (304.5, 319.5) | (304.5, 289.5), on the road outside the town |
| **This round** (`gate-20261110-193642` to `-203153`) | `arrival-1` | **(410.5, 258.5)**, the first town's square | **(410.5, 228.5), inside the town** |

The walls cut what each player perceives: at placement a battle player held 8–14 creatures in arm B (22–24 at the road site) and 31–40 in the full gate (78–79 at the road site), and a battle player received 6.5–7.8 kB/s against 9.4–11.5. Merge `5362933` (module `5e219e3c14`) against main `3ff9e8a`'s module (`ec59719c54`), back to back, nothing else of mine on the host (load p50 6–11); every run starts with 528 characters. **These are the branch's final numbers.**

**Arm B (30 fighters), battle (8 min), in the town:**

| | `gate` client: main `gate-20261110-193642` | `gate` client: merge `-195036` | `game` client: main `-200412` | `game` client: merge `-201818` |
|---|---|---|---|---|
| Steps/s; grid steps skipped | 41.8; 8,796 of 28,798 | 56.5; 1,709 | 46.4; 6,586 | 56.1; 1,926 |
| Tick transaction mean (ms) | 12.4 | 5.9 | 10.1 | 6.4 |
| Move, server p95 / p99 (ms) | **46.1 / 62.7** | **27.9 / 42.6** | **24.1 / 39.1** | **13.6 / 22.2** |
| Move, client p95 / p99 (ms) | **127.9 / 149.3** | **109.3 / 131.8** | **105.7 / 127.0** | **94.5 / 108.1** |
| Skill outcome, server p95 / p99 (ms) | 89.2 / 116.6 | 52.4 / 79.8 | 63.8 / 93.7 | **37.1 / 53.1** |
| Skill outcome, client p95 / p99 (ms) | 171.3 / 199.8 | **134.5 / 165.7** | **145.7 / 179.6** | **118.3 / 139.1** |
| Queue wait, `human_move` mean (ms) | 7.9 | 2.4 | 5.8 | 2.6 |

Bold: within the line. Calm (2 min) holds about 60 Hz and passes both lines in all four. With fewer creatures in each scene, main itself runs the town battle far faster than the road battle (41.8 and 46.4 steps a second against 24.6 and 27.1), and the merge's margin narrows: 56 steps a second against 42–46. **On the merge with the `game` client every latency line passes in arm B's battle; with the `gate` client all but the skills' server p95 (52.4 ms). 60 Hz does not: 56 steps a second, 6–7% of grid steps skipped.**

**The full gate on the merge, `game` client, in the town** (`gate-20261110-203153`; 100 fighters, 116 walkers, 30 min):

| Requirement (locked) | Before: the gate's run `gate-20261109-200119` (`gate` client, open ground) | After |
|---|---|---|
| 60 Hz authoritative simulation, battle included | **fail**: 9.0 steps/s; battle 0.51; queue 7,333 | **fail**: 13.2 steps/s overall; calm 55.2 (1,445 of 17,999 grid steps skipped), battle 4.9, last 10 min 3.2; operation queue 76 at the end |
| Server receipt → committed outcome ≤50 ms p95, ≤100 ms p99 | **fail**: moves p95 16.4 s | **fail**: moves calm p95 13.1 / p99 21.5 ms (passes), window p95 333 / p99 468 ms; skills window p95 619 / p99 838 ms |
| Client input → outcome received at 80 ms RTT ≤150 ms p95, ≤250 ms p99 | **fail**: moves p95 16.5 s; 21,471 unanswered | **fail**: moves calm p95 94.6 / p99 104.5 ms (passes), window p95 414 / p99 549 ms; skills window p95 699 / p99 918 ms; 0 unanswered |
| Client 60 FPS, 99% of frames ≤ ~16.7 ms | pass, weak | **pass, weak**: battle 99.99% within 16.7 ms, 2 frames over 25 ms |
| Slow systems at their deadlines (1 Hz housekeeping) | **fail**: 827 runs | **fail, by one interval**: 1,800 runs, interval p50 1,000 ms, p99 1,266 ms; the longest was 1,530 ms, over the 1,500 ms the verdict allows (the road-site run's longest was 1,441 ms) |

In the town the battle's tick spends less on frames (42 against 49 ms/s) and twice as much waking creatures: 389 ms/s of tick code, `tick.wakes` 173 (90 at the road site), `tick.activity` 126, `tick.frames` 42, `tick.perception` 36. Residents in the streets around the fight witness it and are woken; that is the town's next cost on top of those named below. The world grows from 528 to 6,272 characters and 6,415 structures over the 30 minutes.

Verification on this merge: `just living-check` exit 0 (rules 121 passed); `verify-client` scoped 30 of 30; `verify-core` `sight` 6 of 6, `skirmish` 8 of 8, `town.py` 21 of 21; `verify-player` `gesture.py` 10 of 10, `combat.py` 20 of 25, the same five checks failing on main `3ff9e8a` run from a worktree of it (the fire bolt meets a wall, the dodge is cut to 1.95 m, and the graph attacker of the block, dodge and heal scenes never reaches the player: the scenes' fixed offsets meet the town's buildings around the new arrival).

### Next measured bottleneck

At 100 fighters the database thread is still saturated, now by the tick's own work and by world growth rather than by view refreshes:

1. **The tick's own code: 346 ms/s in the battle.** `tick.activity` 136 ms/s (a release: the blow, `witnessed` percepts to every onlooker, about 200 in sight, each an `experience` row and a staged line, the feed events), `tick.wakes` 101 ms/s (every creature struck is woken and its graph evaluated), `tick.perception` 50–72 ms/s (sweeps of 100 players who each see about 100 creatures, a crowd that keeps coming and going at the sight's edge), `tick.frames` 41–49 ms/s.
2. **The onlookers' feed volume.** One `combat_seen` row per event per onlooker: in the battle 12–20k rows live at once, inserted and deleted at about 19k a second, and `my_combat` 115 ms/s of view time. Fewer rows need a protocol change: one row per frame per viewer carrying its events, or the client deriving releases from `seen_fighters`.
3. **World growth with every death.** Each rejoin is a new character: by the end 5,242 characters, 5,228 remains, 84k `skill_use` and 81k `experience` rows. Each player owns about 47 dead characters, and every `my_*` view reads all of them through `character.controller` at each refresh; `combat::humans` rescans every character after each death or join. Steps fell from 4.7 a second over the battle to 2.5 in the last 10 minutes with the tick's per-second work unchanged. A player's current character needs a row of its own for the views to read.
4. **The confirmed-read fsync**, 20–40 ms on this disk on every delivery: next to the 50 ms server line once the queue is bounded.

### What this does not establish

- 60 Hz with 100 humans fighting in one place: not reached.
- The game client against the 64-line `my_experience` window was built and its log change applied (`ui/live.rs`, after the merge with main `0812ada`), but not played through a long fight.
- The 200-character battle and 2,000 characters of the contract.
- Onlookers' feed rows now live 300 ms: a client stalled longer than that misses an onlooker's effect. Not measured with the game client under a stall.

### Durability on the response path (hypothesis 4): measured, not decided

- **How 2.14.1 commits.** The durability actor (`crates/durability/src/imp/local.rs`, `Local::run`) takes every transaction queued, writes them and then calls `flush_and_sync` once: a group commit with no timer. A transaction waits for the fsync in progress and then its own. A client with confirmed reads (the SDK default, `DEFAULT_CONFIRMED_READS = true`) gets a transaction's rows only when the durable offset passes it (`client_connection.rs`).
- **This disk.** 100 synchronous 4 KB writes in a container volume took 2.02 s: about **20 ms per fsync** (XFS on device-mapper on NVMe, the dev-box's `/`). 100 × 64 KB took the same 2.02 s, so the cost is the sync, not the bytes.
- **What it costs the lines.** The tick watcher's two connections (one confirmed, one not) measure it on every step:

  | Run | Window | Step → delivered, unconfirmed p50 / p95 (ms) | Confirmed p50 / p95 (ms) | Added at p50 |
  |---|---|---|---|---|
  | arm B, base | calm | 3.5 / 15.4 | 24.1 / 39.4 | 20.6 |
  | arm B, frames3 | calm | 3.4 / 14.1 | 29.8 / 45.7 | 26.4 |
  | arm B, frames3 | battle | 7.0 / 26.7 | 34.8 / 54.6 | 27.8 |
  | 100, frames6 | calm | 10.6 / 58.2 | 43.3 / 78.5 | 32.7 |

  With the queue bounded, the fsync is most of what is left between a commit and the 50 ms server budget: arm B's battle delivers a step in 26.7 ms at p95 without it and 54.6 ms with it.
- **The choice, for the user.** (a) Presentation on unconfirmed reads (others' motion and moves, the onlookers' feed, `seen_*`), outcomes on confirmed ones (`my_skill_uses`, `my_vitals`, `my_inventory`, the two involved's feed rows). The SDK sets confirmed reads per connection (`with_confirmed_reads`), so this is two connections per player with the subscriptions split between them, at no extra view cost (views are per identity, not per connection). The trade-off: a server crash loses the transactions not yet synced (about one fsync's worth, 20–40 ms here), and a client that drew them sees them undone after it reconnects. For motion that is invisible; for an outcome (a kill, loot, a heal) it would be a visible rewind, so outcomes stay confirmed. (b) Faster storage: an fsync measured in tens of microseconds (an NVMe with power-loss protection, or a durable write cache) removes most of the gap with no client change; this host's consumer drive cannot show that. (c) Leave it: confirmed everywhere costs 20–40 ms on this disk on every delivery. Not decided here.

### Back-pressure (hypothesis 5)

- **On delivery: built.** A step's frames cover at most 2,500 creatures of scene, stalest viewers first, so delivery cannot make a step arbitrarily long; when more is due, frames come less often. In the 100-fighter battle the budget serves about 20 viewers a step (scenes of about 120), so at 5.5 steps a second each viewer gets about one frame a second (arithmetic from the budget, not counted), and `tick.frames` costs 61 ms/s.
- **On input: not built.** A player's inputs are still admitted by the per-character bucket (`input_hz` 30/s), and an input waits in the database's queue before any reducer can see it, so the module cannot shed load it has not dequeued. The workable place is the client: keep at most one `human_move` in flight and send only the latest direction when its reply arrives, which caps a player's queue share at one move per round trip. That is a client protocol change and is proposed, not made. Measured need: with frames the queue stays bounded in every run here (the 100-fighter battle ended at 0), so input back-pressure is a safeguard, not the bottleneck.

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
