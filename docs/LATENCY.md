# Input latency: where the milliseconds go, and whether we need prediction

2026-11-09. A research note answering the user's question about the [performance contract](PERFORMANCE_CONTRACT.md)'s 80 ms round trip: "We are not even online. Do we need client-side prediction if SpacetimeDB is authoritative first?" It measures one player's input latency with **no added network delay** on this Mac and on the dev-box, reads what SpacetimeDB 2.14.1 provides, summarises how comparable games handle latency, and recommends the smallest design that fits the living core. It changes no game, authority or contract code. The contract is a product decision and stays as it is.

## Short answer

- **80 ms is not something we measured on our network. It is a test condition the contract chose** to model a remote internet player. [Gate 216](GATE_216.md) added it on purpose with `netem`. With no added delay, the network costs about 0.3 ms on the dev-box loopback and about 3–4 ms over the home LAN.
- **The milliseconds that matter today are ours, not the network's or SpacetimeDB's compute.** With no network delay, a movement input starts to be drawn about **108 ms (p50) / 184 ms (p95)** after the key is handled (dev-box). Over the home LAN it is 140 / 428 ms. SpacetimeDB's own work is about 1 ms of that. The rest comes from three things:
  1. **Confirmed reads**, the SDK default: about 35 ms (p50) of fsync wait per delivery on the dev-box.
  2. **The SDK queueing each call until the next `frame_tick`:** up to 2 frames, about 26 ms at 60 FPS.
  3. **The game's display clock**, which also delays your own body: 33–50 ms, with second-long spikes.
- **SpacetimeDB is authoritative first, but it does not hide latency.** It ships nothing for prediction or reconciliation in 2.14.1; its issue tracker lists the feature as planned. Its own MMO, BitCraft, predicts in the client. Its migration guide recommends turning confirmed reads off for real-time games.
- **What we need:**
  - **On a LAN or same-region server (below about 20 ms round trip), movement needs no prediction.** It needs three client fixes, and then it fits the 50 ms local-feedback line.
  - **At the contract's 80 ms, movement prediction is required for the 50 ms line.** No authoritative design can show a server-decided result 80 ms after it was asked for in under 50 ms.
  - **Skills are already handled the right way.** Their start is predicted (the clip plays at the press), and their outcome stays on the authority.

## 1. Measured: one player, no added network delay

### Method

- **Tools.**
  - `living/tools/latency_probe/` is a Rust client on SDK 2.14.1, like the game client. It is one real player connection with the game client's subscriptions.
  - `living/tools/latency.py` is the driver: it starts its own container, publishes a scratch world, runs the configurations, scrapes server metrics and analyses the results. Each configuration is a new player and character.
- **Inputs.**
  - **300 `human_move` direction changes,** one every 300 ms plus 0–17 ms of jitter, so inputs land at every phase of the 60 Hz tick.
  - **15 fire bolts at a ground point,** one every 4.3 s. Only 6 per configuration were released; the other 9 were refused as "too tired", for lack of energy.
- **Configurations.** Each run has four: confirmed reads on or off, crossed with how messages are processed.
  - `thread`: as they arrive (`run_threaded`).
  - `frame`: one `frame_tick` per 60 Hz frame, as the game client's `net::pump` does.
- **World.** Seed `island`, module from `47e82a3` (the authority sources clean), skills from `living/scripts/skills.rhai`. About 298 ambient characters (people and animals on instinct), no minds, no other players. This is the calmest realistic world: it measures the floor, not a crowd.
- **What is timed for each input:**
  - the send, on the client's clock;
  - the server receipt (`ReducerEvent.timestamp`, taken before the database's queue; [gate 216](GATE_216.md#method));
  - when the call's own reply arrives;
  - when my body's new segment arrives through `seen_bodies`;
  - for a skill, each state of its `skill_use` row.
- **Server stages** come from the server's histograms between scrapes: queue wait (`spacetime_reducer_wait_time_sec`), and the transaction with view refreshes and commit (`spacetime_reducer_plus_query_duration_sec`). Their buckets are coarse (0.1, 0.5, 1, 5 ms), so means are given.
- **Clocks.**
  - On the dev-box, the probe and the container read one kernel clock, so the server-minus-client offset is 0 (`analyze --same-clock`).
  - On the Mac, the server runs in Docker Desktop's Linux VM, whose clock drifts against macOS by a few milliseconds over a run. Offsets there are bounded from the calls within ±10 s (sent ≤ received ≤ replied), with a half-width of 0.3–4.5 ms. Single-clock intervals (send → reply, send → drawn) need no offset.
- **The frame that draws it.** The display delay is emulated, not observed in the game:
  - `latency.py` replays every received body row through the game's display clock (`living/viewer/src/sync.rs` `ServerClock`, driven by `living/game/src/bodies.rs`). It uses the same constants: 4 s window, 2% late share, 4 ms margin, 10% slew, 1 s resync. It feeds the newest `t_ms` per 60 Hz frame, as `net.rs` does.
  - From that it finds the first frame whose displayed authority time reaches my new segment's start.
  - Rendering and presenting that frame (GPU work and vsync, typically 1–2 frames) are not measured; no frame-to-photon hardware was used.

Hosts:
- **Mac:** Apple M4 Pro, 48 GB. Docker Desktop, image `clockworklabs/spacetime:v2.14.1`, its own container `lat-stdb` on port 3391.
- **dev-box:** AMD Ryzen AI Max+ 395, Fedora 44, rootless podman. Its own container `lat-stdb` on the LAN address, port 3391, 16 CPUs. **Shared:** other agents' work held the 1-minute load average at 13–24 during the runs.
- **LAN:** Mac on Wi-Fi to the dev-box on Ethernet, ICMP round trip 3.1 ms p50. The dev-box firewall admits only a few ports, so the WebSocket went through an SSH tunnel, which added about 1 ms to an HTTP round trip (4.3 ms p50).

Evidence: `.local/living/latency/<run>/` (git-ignored): `manifest.json`, one `<config>.jsonl.gz` (every input, reply, body row and skill state) and `<config>.metrics.json` per configuration, and `report.json`.

### A movement input, stage by stage (dev-box, loopback, one clock)

`human_move` writes the body's new segment in its own transaction. It does not wait for the tick: the segment starts at the receipt's millisecond (`t_ms` − receipt = −0.5 ms, millisecond truncation). Run `devbox-local-20261109-220351`, 301 moves per configuration. The table gives p50 / p95 / p99 in ms.

| Stage | Unconfirmed reads | Confirmed reads (SDK default) |
|---|---|---|
| Client send → server receipt, messages processed as they arrive | 0.26 / 0.35 / 0.42 | 0.23 / 0.39 / 1.19 |
| Queue wait (server metric, mean) | 0.17 | 0.10 |
| Reducer + view refreshes + commit (server metric, mean) | 0.45 | 0.38 |
| Durability (fsync) before the server sends | — | about 35 (p50), 56 (p95): the difference between the two columns |
| Subscription evaluation and delivery: receipt → reply at the client | 0.90 / 2.70 / 3.48 | 36.4 / 59.2 / 90.5 |
| **Send → reply, processed as it arrives** | **1.17 / 3.05 / 3.78** | **36.6 / 59.4 / 90.7** |
| SDK at 60 frames/s: the call waits for the next `frame_tick` to leave | 9.5 / 16.0 / 16.9 | 8.7 / 16.1 / 16.6 |
| SDK at 60 frames/s: the reply waits for the next `frame_tick` to apply | about 15.7 every time | (inside the row below) |
| **Send → reply applied, one `frame_tick` per frame (the game's pump)** | **25.9 / 32.6 / 33.4** | **56.7 / 80.1 / 98.7** |
| The game's display clock: applied → my segment's start drawn (emulated) | 33.4 / 33.4 / 1,083 | 50.0 / 116.7 / 1,067 |
| **Send → my new movement first drawn (emulated, before render and present)** | **59.1 / 66.3 / 1,117** | **107.9 / 184.1 / 1,121** |

Server work, the tick and the 60 Hz grid during the same runs:
- the tick's transaction, mean 2.1–3.4 ms;
- the tick starts a mean 3.1 ms after its intended time (`spacetime_scheduled_function_delay_seconds`);
- `use_skill`'s transaction, mean 0.7–1.0 ms.

### A skill input (fire bolt, 450 ms windup), dev-box

`use_skill` accepts the use in its own transaction: `accepted_ms` equals the receipt's millisecond in every case. The release is due at the end of the windup and happens at the first tick after it. n = 6 per configuration, so treat these as indicative.

| Stage (ms) | Unconfirmed, as it arrives | Confirmed, as it arrives | Unconfirmed, per frame | Confirmed, per frame |
|---|---|---|---|---|
| Send → acceptance arrives | 1.8 / 1.9 | 46.5 / 54.1 | 24.7 / 30.7 | 65.9 / 68.1 |
| Release after the declared windup, authority clock (the tick wait) | 6.5 / 10.8 | 8.0 / 9.0 | 8.5 / 9.0 | 14.0 / 14.0 |
| Release → it arrives at the client | 3.8 / 4.4 | 47.7 / 55.1 | 8.7 / 10.0 | 52.9 / 53.7 |
| Send → release arrives, minus the windup | 9.7 / 14.8 | 55.2 / 63.5 | 24.7 / 30.7 | 80.0 / 82.9 |

The tick wait is what a 60 Hz grid predicts: uniform from 0 to 16.7 ms. Across all 24 releases on both hosts the maximum was 16 ms.

### The same on the Mac (Docker Desktop) and over the LAN

Send → reply, moves, p50 / p95 / p99 ms:

| Host | Unconfirmed, as it arrives | Confirmed, as it arrives | Unconfirmed, per frame | Confirmed, per frame | Send → drawn, unconfirmed per frame (emulated) | Send → drawn, confirmed per frame (emulated) |
|---|---|---|---|---|---|---|
| dev-box loopback | 1.2 / 3.1 / 3.8 | 36.6 / 59.4 / 90.7 | 25.9 / 32.6 / 33.4 | 56.7 / 80.1 / 98.7 | 59.1 / 66.3 / 1,117 | 107.9 / 184.1 / 1,121 |
| Mac, Docker Desktop | 2.3 / 15.7 / 74.5 | 4.2 / 54.3 / 144.7 | 25.0 / 34.3 / 36.0 | 25.2 / 36.5 / 87.3 | 59.4 / 318.5 / 1,089 | 66.2 / 152.8 / 1,064 |
| Mac → dev-box, LAN (Wi-Fi, SSH tunnel) | 4.4 / 6.7 / 7.8 | 41.0 / 63.3 / 75.1 | 25.8 / 37.3 / 82.0 | 61.9 / 111.4 / 326.8 | 66.4 / 119.8 / 1,053 | 140.2 / 428.4 / 1,079 |

The runs are `mac-20261109-220032` (Mac) and `lan-20261109-221540` (LAN). Each column is a single-clock interval, so the client's clock alone measures it. The LAN adds about 3 ms to the dev-box loopback floor, as ICMP and the tunnel predict.

Notes on the hosts:
- **The Mac's fsync is cheap but has a long tail.** Confirmed costs about 2 ms at p50 there, against about 35 ms on the dev-box. Docker Desktop's VM disk likely does not reach the SSD on every fsync, so the dev-box figure is the one to plan with. The [gate](GATE_216.md) measured the same 30–40 ms there under load.
- **Docker Desktop's network path is noisier** than Linux loopback: a p95 of 15.7 ms against 3.1 ms, unconfirmed. The tick also starts later on average: 4.2–4.6 ms behind its intended time, against 3.1 ms.

### What the measurements say

1. **SpacetimeDB's own work is about 1 ms per input.** Queue wait and the reducer with its view refreshes take under 1 ms at this load. Linux loopback send → reply is about 1.2 ms at p50.
2. **Confirmed reads, the 2.x default, are the largest server-side cost: about 35 ms at p50 on the dev-box.** Each delivery waits for the commitlog batch holding its transaction to be fsynced. The durability actor writes whatever batch is queued and then fsyncs it (`crates/durability/src/imp/local.rs` L269–316 at v2.14.1). There is no timer: the cost is the disk's fsync time.
3. **The SDK holds each call until the next `frame_tick`.** In 2.14.1 a reducer call becomes a queued "pending mutation". It is sent on the WebSocket only when `advance_one_message` runs, and `frame_tick` loops that function (`sdks/rust/src/db_connection.rs` L419–447, L565–591, L656–659).
   - The game runs `net::pump` (`frame_tick`) *before* `controls::movement` in the same chain (`living/game/src/main.rs:134`).
   - So a move handled in frame *k* leaves at the start of frame *k*+1. Its reply, about 1 ms later, waits for frame *k*+2.
   - That is two frames on top of the network: 33 ms at 60 FPS, about 11 ms at the 180 FPS the dev-box client reaches uncapped.
4. **The display clock delays my own body, and in quiet scenes it sometimes runs seconds behind.**
   - `ServerClock` shows every body, mine included, at authority time minus the 98th-percentile delay of recent rows. That costs 33–50 ms at p50 after the row has arrived.
   - Its delay estimate assumes a row's `t_ms` is close to when it was written. It is not for a body entering view: its segment may have started seconds earlier (a standing body: minutes).
   - When such rows are the newest in more than about 2% of frames, the estimate jumps past the 1 s resync threshold. The display then shows the world, my character included, 1–2 s in the past until the old rows leave the 4 s window. In these runs that happened in 0–1.5% of frames (1–14 rows older than 300 ms at arrival per run), enough to give a p99 of about 1.1 s and, in the worst run, a p95 of 1.7 s.
   - This is an emulation of the client's code with the probe's rows. It should be confirmed in the game client, which does not log `delay_ms()` today.
5. **The tick costs only timed skill releases**, 0–16.7 ms. Movement and skill acceptance commit in the caller's own transaction.
6. **With 216 players, the server is no longer the 1 ms floor.** Gate 216's arm B with all 216 in calm play measured move server receipt → committed at p50 23.5 / p95 35.4 / p99 44.3 ms, confirmed reads included. With 30 fighting it measured 46 / 90 / 107 ms ([gate 216](GATE_216.md#diagnostic-arm-b-30-humans-in-the-battle)). That is the queue and the per-viewer view refreshes, the server problem the gate names. Prediction does not fix it.

## 2. What SpacetimeDB says (docs and v2.14.1 source)

Pinned versions: `spacetimedb = "=2.14.1"`, `spacetimedb-sdk = "=2.14.1"`, server image `v2.14.1` (commit `a0bf6be`). The live docs' version selector reads **2.0.0** (or 1.12.0), so every claim below was also read in the docs source and code at tag `v2.14.1`. Source links take the form `https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/<path>`.

| Topic | What it says | Where |
|---|---|---|
| The game loop | "a reducer that SpacetimeDB calls 20 times per second… every 50 milliseconds". Measure dt rather than assume it; "A tick that takes longer than 50 milliseconds delays everything else in the database, and the ticks it overlaps are skipped." | [Fixed-rate game tick](https://spacetimedb.com/docs/how-to/games/fixed-rate-game-tick) (`docs/docs/00250-how-to/01000-games/00200-fixed-rate-game-tick.md` L14–18) |
| Interval schedules | Anchored to intended times. "Missed interval ticks are skipped." | [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables); `crates/core/src/host/scheduler.rs` L811–842 |
| Prediction, reconciliation | No docs page. The Unity, Unreal and Godot tutorials only interpolate: "we linearly interpolate (lerp) between the position where the server says the entity is, and where we actually draw it", and point to Gabriel Gambetta's prediction demo. No SDK contains prediction code. | [Unity tutorial, part 3](https://spacetimedb.com/docs/tutorials/unity/part-3) |
| Planned prediction | Tyler Cloutier, Clockwork CEO: "We do not currently do lag compensation/client-side prediction for you, but you can do it. In BitCraft we implement it outside of SpacetimeDB." The plan is to run an embedded SpacetimeDB in the client and reconcile or roll back. Issue #2453 "Client-side prediction" is open ("on our radar"). | [HN, 2025-04-05](https://news.ycombinator.com/item?id=43595243); [HN, 2025-04-09](https://news.ycombinator.com/item?id=43636922); [#2453](https://github.com/clockworklabs/SpacetimeDB/issues/2453) |
| Confirmed reads | "In 2.0, **confirmed reads are enabled by default**… any data a client receives will survive a server restart." Cost: "a few milliseconds later". "If your application prioritizes low latency over durability guarantees (for example, a real-time game where occasional data loss on crash is acceptable), you can opt out" with `.with_confirmed_reads(false)`. | [Migrating to 2.0](https://spacetimedb.com/docs/upgrade) (`docs/docs/00250-how-to/00600-migrating-to-2.0.md` L1723–1778, read at the tag) |
| The default, in code | The SDKs send the flag only when set; the server default is `DEFAULT_CONFIRMED_READS = true` for WebSocket v2/v3. The send loop awaits `durable.wait_for(offset)` before draining. | `crates/client-api/src/lib.rs` L35; `routes/subscribe.rs` L136–143; `crates/core/src/client/client_connection.rs` L219–257 |
| fsync cadence | Group commit, no timer: write the queued batch, then `flush_and_sync`, then advance the durable offset. | `crates/durability/src/imp/local.rs` L269–348 (read at the tag) |
| No durability | `spacetime start --in-memory`: "After the process exits all data will be lost." Not an option for a persistent world. | `crates/standalone/src/subcommands/start.rs` L76–77 |
| Delivery | Event-driven: the send loop drains what is queued (up to 4,096 messages). WebSocket v3 coalesces messages that are already queued and does not wait for more. Brotli quality 1 is applied above 1 KiB. No send interval and no published latency figures. | `client_connection.rs` L166; `routes/subscribe.rs` L1318–1331, L1528–1561; `crates/core/src/subscription/websocket_building.rs` L199–218 |
| The SDK's send path | A reducer call is queued and sent when `advance_one_message` runs; `frame_tick` loops it, `run_threaded` runs it on a thread. | `sdks/rust/src/db_connection.rs` L419–447, L565–591, L656–670 (crate source 2.14.1) |
| Example game: Blackholio | The input reducer stores a direction (`update_player_input`); a 50 ms (20 Hz) `move_all_players` schedule moves everyone; the Unity client sends input 20 times a second and lerps every entity, its own included, over 0.1 s. No prediction. It keeps the confirmed-reads default. | `demo/Blackholio/server-rust/src/lib.rs` L143–146, L272–284, L313–409; Unity `PlayerController.cs` L9, L130; `EntityController.cs` L11, L39–41, L69–70 |
| Clockwork's own MMO: BitCraft | The client decides its movement. `player_move` receives the client's origin, destination, timestamp and duration, validates them leniently (8 s into the past, 1 s into the future, speed slack, a strike counter before a snap-back) and commits the client's segment. There is no movement tick. Combat is `attack_start` then a server `attack`. About 50 million movement transactions an hour. | `clockworklabs/BitCraftPublic` `BitCraftServer/packages/game/src/game/handlers/player/player_move.rs` L29–101, `reducer_helpers/move_validation_helpers.rs` L206–513, `handlers/attack.rs`; [HN, 2026-09-04](https://news.ycombinator.com/item?id=49566159) |

**What SpacetimeDB provides:**
- one authoritative transactional state machine;
- scheduled reducers that skip rather than catch up;
- incremental subscriptions with event-driven delivery;
- a per-connection choice between durable-before-visible (the default) and visible-at-commit.

**What it leaves to the game:**
- client prediction and reconciliation;
- interpolation of remote entities;
- lag compensation;
- dt handling and the tick budget;
- when the client pumps its connection.

Its examples interpolate. Its flagship game predicts and goes further: the client proposes movement and the server validates it.

## 3. How fast action games handle it

**Labels.** *Established* means stated in a primary source that was read. *Secondary* means press, a wiki, a vendor write-up or reverse engineering. *Inferred* means reasoning or recollection.

| Game | What the client predicts | What only the server decides | Tick and network | Source and status |
|---|---|---|---|---|
| **VALORANT** | "your client is always locally predicting the results of your inputs": movement and firing | Hits after rewinding to what the shooter saw (bounded), and death | 128 Hz; one buffered movement frame; a target of 35 ms ping for 70% of players | [Peeking into VALORANT's netcode](https://www.riotgames.com/en/news/peeking-valorants-netcode), [128-tick servers](https://www.riotgames.com/en/news/valorants-128-tick-servers): established |
| **Overwatch** | Everything by default: movement, abilities, weapons ("Predicting rockets is rad"); rollback and replay on a mismatch | Damage and death; hit rewind of about 0.5 s, off above about 220 ms RTT | 16 ms command frames (62.5 Hz); the client runs ahead by RTT/2 plus one frame; updates rose from 21 to 63 Hz in 2016 | Tim Ford, [GDC 2017](https://gdcvault.com/play/1024001/-Overwatch-Gameplay-Architecture-and) (talk not transcribed); details via an [Edgegap write-up](https://edgegap.com/blog/game-backend-deep-dive-overwatch-2016-netcode-architecture-rollback): secondary |
| **League of Legends** (click-to-move, server-authoritative) | An in-client "Use Movement Prediction" setting exists; Riot has not published what it predicts | Pathing, abilities, damage (inferred) | About 30 Hz (wiki; Riot's AWS talk cites 30 simulation updates/s); Riot built Riot Direct for ping | [Riot Support](https://support.riotgames.com/en-us/league-of-legends/performance/stuttering-champion-animations-in-league-of-legends): established that the setting exists. [Wiki](https://wiki.leagueoflegends.com/en-us/Tick_and_updates): secondary. The prediction details are inferred |
| **Path of Exile** (the closest ARPG precedent) | "Predictive" mode: "Start predicting the result of the action as though the server said yes, immediately… Action prediction is mandatory for this type of game but results in you being slightly out-of-sync almost all of the time." | Everything, with resynchronisation | "Lockstep" mode instead shows an action only after the server confirms it: "a delay equal to your latency"; best below about 100 ms | Chris Wilson, [2014](https://pathofexile.com/forum/view-thread/889669) and [2015](https://www.pathofexile.com/forum/view-thread/1262596/page/1): established |
| **World of Warcraft** (MMO) | The player's own movement (client-driven, with server plausibility checks and anti-cheat); the cast bar and global cooldown start; a 400 ms spell queue window sends the next cast before the current one ends | Hits, damage, auras, interrupts, cast success | Actions on other units were batched every 400 ms until Warlords of Draenor (2014), then processed "as fast as we can… between 1ms and 10ms". Classic relaunched with 400 ms "for authenticity" | Kaivax 2019 blue post via [Warcraft Tavern](https://www.warcrafttavern.com/wow-classic/news/blizzard-talks-about-spell-batching-in-wow-classic/) and Celestalon 2014 via [wowisclassic](https://www.wowisclassic.com/en/news/spell-batching-impact-ptr/): secondary quotes of blue posts. Movement validation: inferred |
| **Blue Protocol** (Bandai Namco, UE4 action MMO, toon style, JP 2023–2025) | Not documented | Not documented | Not documented | No netcode talk or interview found in English or Japanese. CEDEC 2023's talk was on enemy AI ([CEDEC](https://cedec.cesa.or.jp/2023/session/detail/s642a207eec70e.html)); launch problems were congestion and payments ([Famitsu](https://www.famitsu.com/news/202306/14306094.html)). Inferred only: Unreal's default character movement predicts the local player. *Blue Protocol: Star Resonance* (2025) is a different game by another studio. |
| **SUPERVIVE** | Not documented | Not documented | Not documented | No official netcode information found; servers close 25 Feb 2026 ([KitGuru](https://www.kitguru.net/gaming/joao-silva/theorycraft-games-shutting-down-supervive-just-five-months-after-1-0-launch/)) |

**Technique references, established:**
- Gabriel Gambetta's [client-side prediction and reconciliation](https://www.gabrielgambetta.com/client-side-prediction-server-reconciliation.html): inputs carry sequence numbers, and the client re-applies inputs the server has not acknowledged. The server stays authoritative; a hacked client "wouldn't affect the state of the server".
- Gambetta's [lag compensation](https://www.gabrielgambetta.com/lag-compensation.html) covers the hit rewind.
- Valve's Source networking page (100 ms default interpolation; the server rewinds for hits) returned 403 and is cited from memory: inferred.

**Perception, established, from performance and survey studies rather than detection thresholds:**
- Claypool & Claypool 2006 ([WPI TR-06-13](https://ftp.cs.wpi.edu/pub/techreports/pdf/06-13.pdf)) put third-person avatar games, RPGs among them, at a 500 ms performance threshold, against 100 ms for first-person shooters.
- A 2020 survey ([WPI TR-20-02](https://ftp.cs.wpi.edu/pub/techreports/pdf/20-02.pdf)) found players notice latency at about 85 ms on average.

**What every one of them does, where documented:**
- the local player's movement and the start of an action are shown at once, by prediction or by client-driven movement;
- outcomes (hits, damage, death, auras) are the server's;
- remote characters are interpolated a little in the past.

The *wait-for-server* model exists as PoE's Lockstep: it costs exactly one round trip and freezes on a lag spike.

**What an MMO with many players in one place does differently from a 10-player match.** The established parts are WoW's batching history and EVE Online's Time Dilation. The rest is inferred general practice.
- **Interest management.** Each client receives only what is near or relevant to it, at lower rates for distant things. Our per-sender perception views do this, and [gate 216](GATE_216.md#next-measured-bottleneck) shows their cost is the bottleneck in a crowd.
- **Priority loops.** Combat is processed fast, social and loot slowly. WoW's Kaivax described "multiple loops for messages of differing priorities". This matches our 60 Hz tick beside 1 Hz housekeeping, if housekeeping cannot block the tick.
- **Bounded crowds.** Sharding, layering and instances cap a space's population (WoW's [sharding](https://warcraft.wiki.gg/wiki/Sharding_(term)) and [layering](https://www.wowisclassic.com/en/news/realm-layering-update/), secondary). EVE instead slows the whole battle's clock to keep its queue short. CCP: "requests being acknowledged quickly and fairly, but everything just taking about 3x as long" in a fight of about 1,600 ships ([Time Dilation](https://www.eveonline.com/news/view/introducing-time-dilation-tidi), established).
- **Lower or variable rates.** LoL runs at about 30 Hz and WoW's old batching at 2.5 Hz, where VALORANT runs at 128 Hz. MMOs spend their budget on population, not tick rate. Our contract asks for both 60 Hz and 200 in one place, a harder target than any game cited here publishes.
- **Prediction stays local.** Only your own character is predicted; everyone else is interpolated from sparse updates. Crowds do not change that, they change the cost of the updates.

## 4. Recommendation

### Do we need prediction?

| | LAN or same region (below about 20 ms RTT) | The contract's 80 ms RTT |
|---|---|---|
| **Local player's movement** | **No**, after the client fixes below: about 1–4 ms server and network, plus 1 frame to send, plus render | **Yes.** A server-decided move cannot be drawn sooner than RTT + render, about 100 ms. The 50 ms line needs prediction. |
| **Skill start (clip, cast feedback)** | Already predicted in `combat.rs` and `town.rs` (the clip plays at the press). Keep it. | Same. Keep it. |
| **Skill outcome (release, hit, damage, death)** | Server only. Windups of 300–600 ms already cover the round trip: the release arrives at windup + ≤16.7 ms tick + RTT/2 | Server only, as everywhere above. Damage numbers wait for the authority. |
| **Remote bodies** | Interpolate in the past (the display clock), with its delay sized to recent fresh rows, not their tail | Same |

### What the 50 ms local-feedback line requires

The line measures **input → first visible response, at p95**: "Movement and attack feedback begins within 50 ms at p95, using prediction where appropriate."

- **Attacks pass already.** The clip starts at the press.
- **Movement today fails it with no network at all:**
  - 108 ms at p50 and 184 ms at p95, emulated, with confirmed reads;
  - 59 ms at p50 and 66 ms at p95 with unconfirmed reads;
  - both before render and present, and with a 1 s tail.
- **After the client fixes below, on a LAN:** about 1–4 ms server and network, plus up to 1 frame in the input system, plus 1–2 frames to render and present. That is about 20–40 ms at 60 FPS, which is plausible at p95 but must be measured.
- **At 80 ms round trip, only prediction meets it.**
- **The networked line (≤150 ms p95 at 80 ms RTT) leaves 70 ms for everything that is not the network.** Today's local pipeline spends 60–110 ms at p50 before drawing. The [gate](GATE_216.md)'s calm move p95 of 116 ms (arm B), measured to the reply and not to the drawn frame, shows the same budget being consumed.

### Is 80 ms a reasonable test condition?

It is reasonable as an **upper-typical** case for one server region serving its continent, not as the expected median:
- Riot designs VALORANT for 35 ms to 70% of players.
- A secondary report says Riot Direct brought 80% of League players under 80 ms.
- A player in the same city or region sees 10–40 ms; a cross-continent player sees 80–150 ms.

**It looks wrong only if the audience is a LAN or a single city.** In that case the contract tests a harder case than players will see, which is safe but costs prediction work earlier than needed. **If the plan is one world server for a whole continent or the world, 80 ms is the right test, and a p99 case near 150 ms deserves a look too.** This is a product decision; see the questions below.

### The smallest design that fits our architecture

The authority stays the single source of truth. No table, reducer or subscription changes are needed for steps 1–4.

1. **Send input immediately (client, 1 line of intent).** After input systems call reducers, call `conn.frame_tick()` again, or run the pump after the controls. This saves about one frame per input. It is SDK behaviour, so check it again when the SDK changes.
2. **Use unconfirmed reads for the game client (`with_confirmed_reads(false)`).** This saves about 35 ms at p50 and 56 ms at p95 on the dev-box. It is SpacetimeDB's own advice for real-time games.
   - **The trade-off:** after a server crash, a client may have seen up to one fsync batch that the world no longer has, and on reconnect it receives the durable state.
   - Server durability itself does not change. Minds, the observer and tools keep confirmed reads.
3. **Fix the display clock (client, `sync.rs`/`net.rs`).**
   - Estimate the delay only from rows whose segment changed in that transaction, so not from a body entering view.
   - Draw my own body from its newest segment as soon as it arrives (or predicted, step 4), not in the past.
   - This removes 33–50 ms at p50 and the 1–2 s spikes from my own movement. Remote bodies keep a small interpolation delay. Confirm the spikes in the game client first, for example by logging `scene.clock.delay_ms()` under `LIVING_GAME_FRAMES`.
4. **Predict my own movement with the shared steering code (client).**
   - On a direction change, run `living_rules::steer::plan` from my displayed pose with the same `Want` and `Tuning` the authority uses. Start drawing that segment at once.
   - `human_move` is sent as now. The `_then` reply identifies the authority's segment for that call.
   - When the authority's segment arrives, it replaces the prediction, and any error is blended over about 100 ms, which `sync.rs` already does for late rows.
   - **Expected mispredictions:**
     - combat holds (`rooted_now`, the move is deferred; `my_readiness` tells the client);
     - structures not in the client's land model;
     - speed changes from the character's state;
     - the input rate limit (`input_hz`).
   - The authority's segment wins every time.
   - The client never sends positions. That rejects BitCraft's client-proposed movement, which would weaken the shared-rules authority the [working principles](../AGENTS.md#working-principles) require.
   - Needed for internet players. On a LAN, steps 1–3 come first.
5. **Leave skills as they are.** The predicted clip at the press, outcomes from the authority. If needed later, start a missile's cosmetic flight at the predicted release time, never its hit.
6. **Not latency work, but the bigger gap at scale:** the server queue and per-viewer view refreshes ([gate 216](GATE_216.md#next-measured-bottleneck)). With 30 fighters they cost 90 ms at p95 server-side before any network. Prediction hides your own movement, but not other people's actions or your skill outcomes.

## Open product questions for the user

1. **Who connects, from where?**
   - One world server per region, or one world for everyone?
   - What round trip should the median player and the 95th-percentile player have?
   - The answer decides whether 80 ms is the planned case or a margin, and when step 4 (movement prediction) is needed.
2. **May the game client see state before it is durable?** That means unconfirmed reads for presentation. On a server crash, a few milliseconds of what a player saw could be rolled back. Do any actions need confirmed delivery to the player (trades, deaths, item transfers)?
3. **What is the 50 ms line measured to?** The press → the first frame drawn on the screen, including render and present? The contract says "feedback begins"; a frame-to-photon measurement needs a defined client and hardware, which the contract also leaves open.
4. **How much may movement mispredict?** Is a visible snap acceptable when a combat hold or a new wall cancels a predicted step, and how often? The contract says corrections "should be infrequent and unobtrusive" without a number.

## What this does not establish

- **One player in a calm world.** Crowds change the server stages; see [gate 216](GATE_216.md).
- **The display-clock delay and its spikes are emulated** from this client's code and the probe's rows. They are not observed in the game client. Rendering, presenting and input sampling are not measured.
- **Fire bolt outcomes:** n = 6 releases per configuration. Energy refused the other 9 ("too tired").
- **The dev-box was shared** (load average 13–24). Its fsync time depends on that disk and that load. The Mac's Docker Desktop fsync is not representative of a server.
- **The LAN path used an SSH tunnel** (about +1 ms) over Wi-Fi.
- **The industry rows marked secondary or inferred** were not verified against primary sources. No primary source was found for LoL's or Overwatch's prediction details, Blue Protocol or SUPERVIVE.

## Reproduce

```bash
export CARGO_TARGET_DIR=$PWD/.local/living/latency-target
LIVING_SEED=island cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
cargo build --release --manifest-path living/tools/latency_probe/Cargo.toml
living/tools/latency.py up                    # own container lat-stdb on 127.0.0.1:3391
living/tools/latency.py run --label mac       # verify-lat-* world, 4 configurations, about 11 minutes
living/tools/latency.py analyze .local/living/latency/<run> [--same-clock]
living/tools/latency.py down                  # delete its databases, the container and its volume
```

For another server, `run --url <ws base> --container <name> [--ssh <host>]` publishes through that host's container CLI while the probe runs locally.
