# Soak: is the island ready for a small playtest?

2026-11-10. A 4¼-hour soak of the living core on the island, with a handful of players, one real game client, minds on, and the disruptions an evening with friends brings: people dropping and coming back, a mind-service restart, a full SpacetimeDB restart and a module republish. Branch `soak-1`; the code under test is `main` at `fa53e0b`, unchanged. The branch adds only measurement tools and this note.

## Verdict

**Stable enough: yes. Ready for the playtest as a game: not yet. Fix two gameplay defects first.**

**What held up (the stability question)**
- No panic, no rollback, and no crash in the module, the mind service, the players or the game client in 4¼ hours.
- Every correctness check passed: 633 of 633 (`checks.jsonl`).
  - 61 reconnects gave back the same character, its inventory, and control.
  - 21 absences past `takeover_s` were taken over by the minds and handed back.
  - The container restart and the republish lost and duplicated nothing.
  - Privacy held on both passes, after every disruption.
- All 44,690 player inputs were answered. Move send → reply p99 stayed at 4.6–7.0 ms from the first hour to the last.
- The game client's frame work stayed at p50 2 ms and p99 12 ms, and its memory stayed flat at about 1.04 GB.
- Nothing grew without bound except the retained commit log (≈ 440 MB/h, below), which an evening can afford.

**What a playtest would hit (not crashes, but they would spoil the evening)**
1. **Click-to-move cannot reach another town** ([D1](#d1-click-to-move-to-another-town-is-refused-no-path-there)). Every click on another town (all of them 400–2,200 m from the arrival point) was refused with "no path there": 165 of 165. The path search stops at 6,000 expansions, and those routes need 96,000–768,000. Even clicks about 55 m ahead were refused 404 times out of 643. Friends would have to hold a key for kilometres.
2. **The island starves** ([D2](#d2-the-islands-residents-starve-in-the-first-hours)). From about 30 minutes into a fresh world, residents die of hunger.
   - In this run, 123 residents starved and 22 died of cold in 4¼ h. The world's bodies fell from 307 to 175.
   - A control island with no players and no minds lost 76 of 261 people to starvation in 75 minutes, so the players do not cause it.
   - The towns would visibly empty over an evening.

Fix D1 and D2, then repeat a short version of this soak. Every other defect below is low severity.

## Workload

| Item | Declared |
|---|---|
| World | Seed `island` (2,048 m, 8 settlements, about 290 residents and animals), compiled into the module (`LIVING_SEED=island`, default `scoped` perception). Fresh scratch database `verify-client-soak-20261110-014900`, skills from `living/scripts/skills.rhai`. The name starts `verify-client-` because verify-client's probe opens only such databases. World day 12 real minutes, so the run spans about 21 days and nights. |
| Players | **7 driven players** (`gate-load soak`, new), each on its own thread with its own identity and its own WebSocket connection (Rust SDK 2.14.1), subscribing what the game client subscribes and acting only through the player reducers. Players 0, 2, 4, 6 use confirmed reads (the SDK default), 1, 3, 5 unconfirmed reads (what the game client now uses). |
| What players do | Walk between towns (click-to-move in hops of about 55 m, or held keys); gather berries, wood, reeds and stone; eat when hungry; build a campfire; try to craft a spear (refused: newcomers do not know how); talk to residents (`human_say` addressed to one, which wakes it); wave; give; trade with one another (`offer`, then the other `accept`s); sleep when tired; hunt the nearest wolf when the timeline says so (strike, fire bolt, bow, heal); spar with another player to the death now and then; arrive again 6–15 s after dying. |
| Game client | One headless `living-game` (release, the default 60 Hz cap, Metal on the Mac's M4 Pro), its own identity, joined as `SoakWatcher`. Its script walks town to town by click-to-move hops of about 50 m, holds keys in eight 3 s walks of new directions per town, gathers, eats, waves, says a line, opens and closes the pack panel, and presses "arrive again" now and then (harmless while alive). It records every frame (`LIVING_GAME_FRAMES`) and logs its own input → drawn latency every 10 s (`clock:` lines). |
| Minds | `living-mind` against the verify-llm fake model server (scenario `valid`), so the run costs nothing and model latency stays out. Neo4j on, in its own container. `LIVING_PLAYER_MEMORY=1` (a person's lived experience is internalized at takeover). `LIVING_CONCURRENCY=4`, no rate limit. The island's residents have no minds until a player wakes them (town life layer 2). A supervisor restarts the service 3 s after any exit, as `living/tools/run-mind.sh` does, and records each exit. |
| Network | Loopback. Players and the game client each connect through a byte-counting relay (`gate-load relay`), which can also cut every connection and refuse new ones for a while (a network outage). No added delay: this is a playtest on one LAN, not the contract's 80 ms condition. |
| Duration | 4.25 h of play (01:49:22–06:04:22 UTC). |
| Backend | `clockworklabs/spacetime:v2.14.1` in its own Docker Desktop container `soak-stdb` (memory limit 3 GB, port 3361, volume `soak-stdb-data`, stop signal SIGINT). Neo4j `2026.10.1` in `soak-neo4j` (heap 512 MB, page cache 256 MB, limit 1.5 GB, volume `soak-neo4j-data`). |
| Host | MacBook Pro, Apple M4 Pro (14 cores), 48 GB; Docker Desktop VM with 14 CPUs and 7.7 GB. **Shared:** other agents' containers ran in the same VM throughout (three SpacetimeDB servers, three Neo4j), and their builds on the host. |

### Disruptions (the timeline, `timeline.json`)

| When (h) | What |
|---|---|
| every 4–7 min | One player disconnects (closes its connection) and comes back. Each player in turn; alternate rounds stay away 4–20 s (short) or 45–110 s (past `takeover_s` = 30 s, so the world's minds take the character over and hand it back). |
| every 5–8 min | A player is sent to hunt the nearest wolf. |
| every 25–35 min | The two closest players meet and spar to the death. |
| 0.4 and 3.6 | Privacy: verify-client's perception checks on this world (below). |
| 1.0 | The game client's network drops for 10 s (relay cut). |
| 1.5 | Mind-service restart (SIGTERM; the supervisor starts it again). |
| 2.0 | **Full SpacetimeDB container restart** (`docker stop -t 60`, SIGINT; `docker start`). |
| 2.5 | The game client's network drops for 75 s, past `takeover_s`. |
| 3.0 | **Module republish**, the same wasm, data kept (`spacetime publish` without `--delete-data`). |
| 3.3 | Every player's network drops for 8 s at once (relay cut). |
| every 15 min | World invariants (below). |

Around the container restart and the republish, players hold still for 6 s, so the authority's state before and after can be compared exactly. The world itself keeps going: residents act, needs grow, food spoils.

## What is checked, and how

Every check is a row in `checks.jsonl` with its evidence.

- **Each reconnect** (the driver prints what its client was given back as soon as the base subscription is applied): the authority (read as the owner) has at most one living character for that person; the client got that character back; control is the person's again (`character.ai` false); `presence` says present, not AI, at least one connection; the client's inventory equals the authority's. A difference is accepted only when the authority's own experience rows explain it ("Some of your berries spoiled").
- **Away past `takeover_s`**: 36 s into the absence, `presence.ai` and `character.ai` are true and `present` false. **Away briefly**: before return, `present` false and `ai` false.
- **Game client outages**: the 75 s outage is taken over and handed back; the 10 s one is not.
- **Container restart and republish**: every player's living and dead characters and inventory are the same after as before; ticks resume; 25 s later every client that was connected is connected again and holds what the authority holds.
- **Invariants every 15 min**: one `presence` row per person; `presence.connections` equals the person's open `connection` rows; presence only for the living; at most one living character per person.
- **Privacy** (verify-client's perception checks, on this world): every one of the 50 private and 9 scoped tables (the lists in `.agents/skills/verify-client/scripts/drive.py`) is refused to an anonymous client, a fresh identity and a player, by WebSocket subscription (verify-client's probe) and by HTTP SQL. For every connected player, through its own identity: `seen_bodies` and `seen_characters` hold nothing but its own character and what the authority's `perceived` rows say it perceives; `my_characters`, `my_inventory`, `my_vitals` and `my_experience` hold only its own characters' rows.
- **Crashes**: the module log (`spacetime logs`), the mind service's log and exits, the players' disconnects and connect failures, every reducer reply, the game client's log.
- **Growth** every 30 s (server metrics, container memory and CPU, process RSS and CPU) and every 5 min (42 tables' row counts, the replica's `clog`, snapshots and module log on disk, Neo4j nodes and relationships).
- **Latency**: every input's send, server timestamp and reply on the driver's clock; the server's own queue wait and transaction time per reducer from its histograms; the game client's input → drawn from its `clock:` lines.

## Results (`soak-20261110-014900`)

### What was driven

| | Count |
|---|---|
| Player inputs | 44,690: 43,265 moves, 1,261 acts, 39 lines spoken, 72 skill uses, 53 joins. All answered: 44,688 ok, 2 refused "speaking too fast". |
| Act outcomes (the `act` experience rows) | 952: gathered 155, ate 164, gave 6, offered 6, accepted 3, built 5 campfires, waved 11. Refused as the rules say: crafting a spear 156 times (newcomers do not know how), a campfire without wood 7 times, a pack that was full once. Click-to-move refused 405 times ([D1](#d1-click-to-move-to-another-town-is-refused-no-path-there)). |
| Disconnects and returns | 47 planned absences (26 short, 21 past `takeover_s`), the game client's 10 s and 75 s outages, the container restart, the republish, the 8 s cut for every player. Clients reconnected 61 times. 14 connection attempts failed while the server or the relay was down; each retried 3 s later and succeeded. |
| Deaths and arrivals | 46 player characters died: 41 of hunger (D3), 5 in spars. One died while its person was away. There were 53 arrivals, including the first joins. The game client's character starved 8 times and arrived again by its script. |
| Minds | 1,999 fake-model requests: think 640, deliberate 640, consolidate 512, internalize 145, talk 62. 10 residents were woken, by speech, waves and gifts. Neo4j grew from 8 to 386 nodes. |
| Combat | Thin coverage. Of 37 hunts, few reached a wolf, because the wolves left alive were far from the players (up to 1.7 km). 8 spars were scheduled, and 5 ended in a kill. No missile panic (the [gate 216 defect](GATE_216.md#defect-found-the-missile-sweep-panics)) appeared, but there was little archery. |

### Crashes and errors, by category

| Source | Category | Count | Meaning |
|---|---|---:|---|
| Module log | panic, rollback | **0** | – |
| Module log | `human_act: graph.do: skill wave needs a target` | 11 | The game client's wave with nobody to wave at ([D4](#d4-the-game-client-waves-at-no-one)). |
| Module log | `mind_install` / `mind_routines: not your character` | 3 + 3 | The minds finishing a decision for a character whose person had just returned ([D5](#d5-minds-act-on-a-character-after-its-person-returns)). The authority refuses it, correctly. |
| Module log | `human_say` / `mind_say: speaking too fast` | 2 + 2 | The speech rate law, working as designed. |
| Mind service | exits | 3 | The planned SIGTERM restart (−15). Exit code 2 "disconnected from the world" when the container stopped, by design: it relies on a supervisor ([D6](#d6-the-mind-service-stops-only-by-being-killed)). The end of the run (−15). No panic, and no unplanned exit while the world was up. |
| Mind service | warnings | 8 | The 6 refusals above and the server's "module exited" close at the restart. |
| Players | errors | 0 | Every disconnect had no error (closed by us, the relay or the server). |
| Game client | WARN / ERROR | 0 besides `offline:` at each outage | It reconnected by itself every time: 3 s retry, 7 s after the container restart. |
| SpacetimeDB container | stop | exit 0 in 0.1 s, back in 1.2 s | A graceful SIGINT stop, not forced. The other containers were also removed with exit 0. |

### Correctness after each disruption

| Disruption | Checks | Result |
|---|---|---|
| Short absences (26) | still the person's (`present` false, `ai` false) before return; restored on return | 26 + 5 × 26 pass |
| Absences past `takeover_s` (21) | 36 s in: `presence.ai` and `character.ai` true, `present` false; on return: the same character, control back, `presence` present, inventory equal | 21 + 5 × 21 pass. One character starved while the minds had it; on return its person saw the death and arrived again (`restore.no_character_means_dead`). |
| Game client 10 s / 75 s outage | not taken / taken over and handed back | pass / pass |
| Mind-service restart | back in 3 s, Neo4j reconnected, minds resumed from their cursors (`mind cursor at …`) | pass, by the log. No check row. |
| Container restart | every player's living and dead characters and inventory equal before and after; ticks resume; all 7 clients reconnected and hold what the authority holds | 7 × 4 + 1 pass |
| Republish, data kept | the same; connections stay open (2.14.1 hot-swaps the module: neither the minds nor the game client reconnected) | 7 × 4 + 1 pass |
| All players cut for 8 s | every player reconnects, state restored | pass, through the restore checks |
| Invariants, every 15 min (17 times), before and after the restart and the republish, and at the end | one presence per person, presence counts equal open connections, presence only for the living, one living character per person | 66 pass |
| Privacy, at 0.4 h and 3.6 h | 59 tables refused to anonymous, a fresh identity and a player, by subscription and SQL; the seen views hold only own and perceived; the own-state views hold only own rows | 118 + 3 × 13 pass. The second pass covered 6 players, because the 7th was away. |
| Deaths | the authority's dead player characters (46) equal deaths the clients saw (45) plus deaths while away (1); one living character per player at the end | pass |

### Growth

The container restart at 2.0 h replaces the server process, so process memory is given before and after it separately. The rates "after" are the ones a long evening would see. Per hour, from the 30 s samples:

| Quantity | Start | 2.0 h | End (4.25 h) | Rate before the restart | Rate after the restart | Bounded? |
|---|---:|---:|---:|---:|---:|---|
| Commit log (`spacetime_message_log_size_bytes`), MB | 24 | 1,361 | 1,753 (max 2,156) | +650 /h (first half) | +232 /h (second half) | **No:** it grows with every write and is not trimmed. A compression pass at 3.6 h took the replica's `clog` from 2,137 to 1,510 MB. Fewer creatures lived late, so fewer writes. |
| Server data directory on disk, MB | 75 | – | 1,917 | +442 /h over the run | | The same as the commit log. Snapshots took 30 → 47 MB. |
| Server allocator, allocated (jemalloc), MB | 198 | 200 | 122 | +0.4 /h | +2.4 /h | Yes |
| Server allocator, resident, MB | 574 | 488 | 195 | −24 /h | +20 /h | Flattening (153 → 195 MB over 2 h) |
| Module WASM memory, MB | 63 | 63 | 14.5 | 0 | +1.0 /h | Yes. The restart starts a fresh instance. |
| SpacetimeDB container, anonymous memory, MB | 843 | 880 | 433 | +46 /h | +19 /h | Probably. Watch over a longer run. |
| SpacetimeDB container, all memory (cgroup), MB | 1,010 | 2,117 | 1,330 (max 2,175 of the 3 GB limit) | +566 /h | +429 /h | Page cache of the commit log, which is reclaimable. It is reported apart, as the contract asks. |
| Neo4j container memory, MB | 913 | 1,107 | 1,163 | +39 /h | +38 /h | Not shown. JVM heap capped at 512 MB. |
| Neo4j nodes / relationships | 8 / 0 | 176 / – | 386 / 96 | +81 nodes /h | +105 nodes /h | No. It grows with minded characters' memories, as designed. |
| Mind service RSS, MB | 47 | 45 | 40 | −1 /h | 0 /h | Yes |
| Driven players process RSS, MB | 20 | 26 | 27 | +1.5 /h | +0.4 /h | Yes |
| Game client RSS, MB | 1,146 | 1,058 | 1,037 | +47 /h (warming its caches) | −10 /h | Yes |

Rows (hourly samples at 0, 1, 2, 3 and 4 h):

| Table | Values | Bounded? |
|---|---|---|
| `body` (living creatures) | 307, 287, 171, 176, 175 | The die-off ([D2](#d2-the-islands-residents-starve-in-the-first-hours)) |
| `character` (living and dead) | 308, 330, 351, 376, 398 | No, by design: dead characters stay. Each player death adds one. |
| `skill_use` | 101, 5,842, 5,861, 5,881, 5,908 | Yes: it plateaus at its per-character cap. |
| `prior` (rings) | 86, 3,725, 2,568, 2,716, 2,687 | Yes: `woken_ring("slots")` per resident, removed at death. |
| `thought` | 0, 285, 585, 835, 1,200 | Per actor: `MAX_THOUGHTS` (`mind.rs`). The total grows with the number of minded characters (woken plus taken over). |
| `chronicle` | 235, 437, 726, 867, 1,066 | Capped at 4,000 (gate 216). Not reached. |
| `woken` | 0, 7, 2, 5, 9 (10 at most) | Woken residents die of hunger too. |
| `experience` | 31 → max 287 → 128 | Yes: 400 per character. |
| `presence`, `connection` | 8, 10 throughout | Yes |

Bytes received per client on the wire (the relays): driven players 360–490 B/s each, the game client 100–140 B/s. These are a calm island's rates, not a crowd's.

### Latency over time

Loopback, no added delay. "Send → reply" is the driver's own clock: the call leaves, then its transaction comes back. Receipt → reply uses the server's `ReducerEvent.timestamp` and an offset between the Docker VM's clock and the Mac's. The offset is bounded per minute from the calls themselves (half-width p50 0.12 ms, max 0.8 ms; [method](LATENCY.md#method)). p50 / p95 / p99 in ms (n):

| Hour | Move, confirmed reads | Move, unconfirmed reads | Act (`human_act`) | Skill (`use_skill` acceptance) | Move, server receipt → reply |
|---|---|---|---|---|---|
| 1 | 1.3 / 5.0 / 7.0 (5,499) | 1.3 / 4.5 / 6.5 (4,589) | 3.1 / 6.5 / 7.8 (327) | 3.4 / 5.2 / 5.5 (16) | 0.6 / 3.6 / 5.4 |
| 2 | 1.1 / 3.9 / 5.5 (6,120) | 1.0 / 3.7 / 5.2 (4,559) | 2.4 / 5.9 / 7.5 (260) | 1.9 / 3.7 / 4.0 (18) | 0.5 / 2.8 / 4.2 |
| 3 (container restart) | 1.1 / 3.7 / 6.6 (5,681) | 1.1 / 3.8 / 6.0 (4,415) | 2.5 / 6.3 / 65.9 (284) | 2.3 / 3.6 / 4.5 (20) | 0.5 / 2.9 / 4.5 |
| 4 (republish) | 1.4 / 4.4 / 5.9 (5,983) | 1.4 / 4.2 / 5.9 (3,916) | 3.4 / 6.6 / 9.1 (319) | 3.2 / 5.2 / 5.6 (18) | 0.7 / 3.2 / 4.7 |
| 4.0–4.25 | 1.4 / 4.8 / 6.3 (1,258) | 1.4 / 4.5 / 6.0 (1,243) | 3.3 / 5.8 / 23.3 (71) | – | 0.8 / 3.7 / 5.1 |

The server's own histograms (mean ms, queue wait / transaction with view refreshes and commit):

| Hour | `human_move` | `human_act` | `use_skill` | tick (transaction) | Tick transactions, % of the 60 Hz grid |
|---|---|---|---|---|---|
| 1 | 0.44 / 0.10 | 0.64 / 1.50 | 0.15 / 1.73 | 2.16 | 212,117 (98.2%) |
| 2 | 0.26 / 0.08 | 0.29 / 1.31 | 0.10 / 0.91 | 1.53 | 213,896 (99.0%) |
| 3 | 0.32 / 0.09 | 1.15 / 1.26 | 0.17 / 1.02 | 1.35 | 213,178 (98.7%) |
| 4 | 0.34 / 0.12 | 0.78 / 1.81 | 0.60 / 1.33 | 1.69 | 213,889 (99.0%) |

**Early against late:** flat. Late moves were no slower than early ones. The only tail is the act p99 of 66 ms in the restart hour: the first acts after the server came back. Confirmed reads cost nothing visible here, because Docker Desktop's fsync is cheap ([latency](LATENCY.md#the-same-on-the-mac-docker-desktop-and-over-the-lan)). On the dev-box it costs about 35 ms. 1–2% of the 60 Hz grid steps were skipped in every hour. That is the same calm-world slack gate 216 measured, and it fails the contract's 60 Hz line, as it did there.

### The game client

Headless `living-game` at its default 60 Hz cap, Metal, 733,001 frames.

| Hour | FPS | Interval p50 / p95 / p99 / max (ms) | Frame work p50 / p95 / p99 / max (ms) | Frames > 50 ms | > 250 ms | Input → drawn: median of the 10 s windows' p50 / their max | Same, p95 |
|---|---:|---|---|---:|---:|---|---|
| 1 | 47.5 | 21.7 / 24.6 / 33.1 / 596 | 2.0 / 2.6 / 11.7 / 100 | 27 | 1 | 23 / 52 | 39 / 52 |
| 2 | 49.1 | 20.2 / 24.4 / 30.7 / 217 | 2.0 / 2.5 / 11.3 / 28 | 11 | 0 | 23.5 / 39 | 37 / 40 |
| 3 | 48.8 | 20.3 / 26.0 / 33.0 / 194 | 2.0 / 9.4 / 11.6 / 138 | 246 | 0 | 21 / 35 | 39.5 / 224 |
| 4 | 46.6 | 23.2 / 24.6 / 33.0 / 69 | 2.2 / 2.8 / 11.8 / 35 | 7 | 0 | 24 / 42 | 40 / 47 |
| 4.0–4.25 | 46.4 | 23.2 / 24.2 / 24.8 / 37 | 2.2 / 2.4 / 3.0 / 13 | 0 | 0 | 36 / 39 | 41 / 41 |

- **Frame rate is the runner's, not the game's.** The headless loop's sleep overshoots on macOS (`ScheduleRunnerPlugin`; gate 216 saw the same on Linux): about 47 FPS with 2 ms of work a frame. The frame's own work is the measure, and it shows no drift over 4 hours (p50 2.0 → 2.2 ms).
- **Memory:** 1,146 MB at start, 1,037 MB at the end, max 1,070 MB after the first hour. No growth.
- **Stalls:** 53 hitches over 100 ms in 4¼ h ([D7](#d7-game-client-stalls-of-100190-ms-cause-not-established)).
- **Input → drawn** (the game's own `clock:` measurement: a `human_move` from the script to the frame that draws its new segment) stayed at 21–24 ms p50 and 37–41 ms p95 per window, with 221 inputs measured. One window after the container restart reached 224 ms.
- **Outages:** the client went offline 3 times (both relay cuts and the container restart). Each time it retried every 3 s, came back to the same character, and carried on with its script.

## Defects

### D1. Click-to-move to another town is refused: "no path there"

- **Severity:** high for a playtest. Walking between towns is the island's main activity.
- **Evidence:**
  - First attempt of this run, `soak-20261110-011532` (aborted after 23 minutes for this reason, kept as evidence): every `goto` to a settlement failed. That is 165 of 165, at straight-line distances of 400–2,200 m. The game client's script, clicking on towns too, stayed at the arrival point.
  - The main run's hops of at most 55 m: 643 sent, 320 "no path there", 85 "destination unreachable", 5 "you moved". Players then walked by held keys.
  - `living/tools/path_budget` on the run's own terrain (`path-budget.txt`). From the arrival point, budgets doubling from the authority's 6,000:

    | Target | Straight line | Budget that finds a path | Search time |
    |---|---:|---:|---:|
    | town #0 | 100 m | 6,000 | 0.1 ms |
    | village #4 | 477 m | 24,000 | 1.6 ms |
    | town #6 | 705 m | 96,000 | 10 ms |
    | village #3 | 1,856 m | 192,000 | 26 ms |
    | small_folk #2, village #5 | 1,797 m, 2,056 m | 384,000 | 40–44 ms |
    | giants #1, town #7 | 1,012 m, 1,427 m | 768,000 | 58–84 ms |

- **Cause:** `motion::start` calls `map.path(p, at, 6_000)` (`living/authority/src/motion.rs:556`). Longer routes run out of expansions and are refused. A refused target is also remembered as unreachable for a while (`no_path`/`unreachable`, same file), so asking again is refused without a search.
- **Why the short hops fail** is not established. Likely causes are hops that land in water or buildings, and that memo.
- **Status (2026-11-10, `path-1`): fixed.** The short hops failed for the same budget (255 of 319 "no path there"; the towns' building rows, rivers and ponds need 12,000–384,000 expansions to walk round) and for the memo (22 more). The 85 "destination unreachable" were hops into open water, correctly refused. A third cause was hidden behind these: a deliberate act gave up after 90 s of approach. Walks are now planned leg by leg over regions and areas of chunks, and a walk to a place lasts as long as its route: [walking routes](PATHS.md).
- **What a fix must weigh:** raising the budget inside the reducer costs up to 84 ms of the single database thread per click. A coarse route (towns and roads), a search off the reducer, or a partial path toward the goal would avoid that.
- **Owner:** steering and motion (`verify-core`).

### D2. The island's residents starve in the first hours

- **Severity:** high for a playtest. Towns empty over an evening.
- **Evidence:**
  - In the soak world (`final-characters.json`), 123 residents starved, 22 died of cold and exposure, 2 of exhaustion and 2 of old age in 4¼ h. 20 wolves starved. 125 people were alive at the end. The world's bodies fell from 307 to 175 (`body` rows above).
  - The deaths start about 30 minutes in. In the first hour, 16 infants, 4 children and 14 adults starved, and none of them had been woken.
  - Control `control-20261110/summary.json`: the same module and seed in its own container, no players, no minds, `rules.minds = false`, run alongside the soak. Starvation of people begins at minute 25–30: 16 by minute 35, 50 by 50, 76 by 75. Alive people went from 261 to 182.
- **Cause:** not investigated. It is in the world's rules or the island's instinct graphs: food supply, hunger rate, spoilage, or foraging. The players make no difference, because the control is worse.
- **Owner:** needs, food and life course (`verify-core`), and the island seed (`verify-generation`).

### D3. Players starve too

- **Severity:** medium. The evidence is weak.
- **Evidence:** 41 of the 46 player deaths were of hunger. Each driven player lived about 35 minutes on average. The game client's character starved 8 times.
- **Cause:** partly the harness. The driver eats only what it carries and gathers by chance. It does not go looking for food when it is hungry, and a person would. But the newcomer kit holds 4 berries, berries spoil (`spoil_rate`), and the residents starve with no players at all (D2). So a real player may also struggle to keep fed.
- **Next step:** check with a person, or a driver that forages when hungry.

### D4. The game client waves at no one

- **Severity:** low.
- **Evidence:** 11 module log errors, `human_act: graph.do: skill wave needs a target`. Each came from the script's `gesture:wave` when nobody was in reach.
- **Cause:** the G key's path (`living/game/src/town.rs`) sends the gesture without a target instead of doing nothing or showing why.

### D5. Minds act on a character after its person returns

- **Severity:** low.
- **Evidence:** 3 times each, `mind_install: not your character` and `mind_routines: not your character` for SoakGus, SoakBram and SoakAda. Each came just after a handback, while a deliberation started during the takeover finished.
- **Effect:** the authority refuses them, which is correct, so there is no wrong effect. The model calls were wasted.
- **Possible fix:** the mind service could drop its in-flight work for a character when `presence` says its person is back.

### D6. The mind service stops only by being killed

- **Severity:** low, operational.
- **Evidence:**
  - The planned restart and the end of the run ended the service by SIGTERM with exit −15. It has no handler, so those stops were forced, not graceful.
  - Nothing was seen lost: it resumed from its mind cursors 3 s later.
  - It exits with code 2 whenever the world disconnects (the container restart). It relies on `living/tools/run-mind.sh` to restart it.
- **For a playtest:** run it under `run-mind.sh`, never bare.
- **Also forced:** the game client, stopped at the end with SIGTERM (−15). Its script would have quit by itself later.

### D7. Game client stalls of 100–190 ms, cause not established

- **Severity:** low.
- **Evidence:**
  - 53 frames over 100 ms in 4¼ h.
  - One of 596 ms at 02:24:26: a 579 ms render set compiling 3 new pipelines while standing still. Shader compilation on first use.
  - A cluster of 43 at 03:53–04:00, four minutes after the container restart, standing still with nothing new to draw (`hitch:` lines: +0 entities, +0 meshes). On those frames the main schedule's own work was 3–58 ms, so most of each stall was outside it: rendering or presenting, or the OS.
  - The host's load average rose from about 4 to 10 in those minutes (other sessions), which may explain them.
- **Not established:** whether a windowed client with vsync would show the same stalls.

### Operational notes (not defects)

- **Commit log:** it grows with every write and is not trimmed: ≈ 650 MB/h with 300 creatures, ≈ 230 MB/h with 175. That is 2–3 GB for an evening, fine on disk. A persistent world needs the archive plan (gate 216 said the same). The container's page cache follows it, up to 2.2 GB of the 3 GB limit here. The cache is reclaimable, but a tight memory limit should leave room for it.
- **Republish:** in 2.14.1, a `spacetime publish` without `--delete-data` swaps the module under open connections. No client and no mind reconnected, and nothing was lost.

## What this does not establish

- **One host.** The Mac, with Docker Desktop's VM, cheap fsync and noisy timers. The dev-box's fsync costs about 35 ms per confirmed read ([latency](LATENCY.md)).
- **Network.** Loopback only: no 80 ms round trip, jitter or loss. Friends on one LAN are close to this; friends over the internet are not.
- **Minds.** The fake model answers at once with fixed replies (`{"wait": 2}` graphs, "verify fake" speech). Real model latency, cost, refusals and what real minds would do to the world are not covered. Woken residents and taken-over characters only waited.
- **Players are scripts.** Seven drivers and one scripted game client, not people. They trade only with each other, and their food-seeking is naive (D3). Combat coverage is thin: 72 skill uses, 5 spar kills, few wolf fights.
- **Privacy coverage.** verify-client's full suite (`run.py`) was not run: it requires the shared server on :3300 and makes its own world. Its probe and its table lists were run against this world. Its geometric perception steps (in sight, beyond sight, behind a wall) were not.
- **Performance and scale.** This is 8 players. The performance contract's gate is [gate 216](GATE_216.md)'s business; this run says nothing about crowds.
- **Duration.** 4¼ hours. Slow growth (Neo4j, the allocator's resident set) would need a longer run to call bounded.

## Evidence

All under `.local/living/soak/` on the Mac (git-ignored):

- `soak-20261110-014900/`, the run:
  - `manifest.json` (hosts, versions, binary hashes), `timeline.json`, `marks.json`, `run.log`, `stdout.txt` (the orchestrator's output, copied from `soak-main2.out`)
  - `checks.jsonl`, `disruptions.jsonl`, `events.jsonl.gz` (every input, reply, outcome, death, arrival, disconnect, reconnect and snapshot)
  - `samples.jsonl.gz` (metrics, cgroup, process and container memory, rows, disk, Neo4j)
  - `module.log.gz`, `mind.log.gz`, `mind-exits.json`, `fake-requests.jsonl.gz`, `game.stderr.gz`, `game/frames.csv`, `game/plan.txt`, `relay-*.jsonl.gz`
  - the before and after files of each disruption (`stdb_restart-*.json`, `republish-*.json`), `final.json`, `final-characters.json`, `privacy.json`, `report.json`, `tables.md`
  - `path-world.json.gz` and `path-budget.txt` (D1)
- `soak-20261110-011532/`: the first attempt, aborted at 23 minutes because every click to another town failed (D1; `ABORTED` says why).
- `soak-20261110-011505/`: a launch stopped at once (its task had a 2 h limit), with nothing in it.
- `control-20261110/`: the no-player control island (D2).
- `smoke-*`: the four compressed smoke runs that debugged the harness. Their failures are harness or compression artefacts, fixed before the main run.
- `bin/`: the exact binaries used.

## Reproduce

On the Mac with Docker Desktop and the game assets (`just living-game-assets`, or absolute links to an existing checkout's):

```bash
export CARGO_TARGET_DIR=$PWD/.local/living/target-wake
LIVING_SEED=island cargo build --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release
cargo build --release --manifest-path living/Cargo.toml -p living-mind -p living-game
cargo build --release --manifest-path living/tools/gate_load/Cargo.toml
cargo build --locked --release --manifest-path .agents/skills/verify-client/scripts/probe/Cargo.toml
B=.local/living/soak/bin; mkdir -p $B/wasm
cp $CARGO_TARGET_DIR/release/{gate-load,living-game,living-mind,verify-client-probe} $B/
cp $CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm $B/wasm/
living/tools/soak.py run                      # 7 players + the game client, 4.25 h
living/tools/soak.py run --smoke --hours 0.1  # the whole timeline compressed into 6 minutes (overlapping drops fail takeover checks by design)
living/tools/soak.py analyze .local/living/soak/<run>
living/tools/soak.py tables .local/living/soak/<run>   # the markdown tables below
living/tools/soak.py cleanup                  # its own processes (recorded PIDs), containers and volumes
```

`soak.py` copies binaries from `.local/living/soak/bin` so another session's build cannot change them mid-run, starts only its own containers and publishes only `verify-client-soak-*`. A run in the background must be its own session (`os.setsid`); it stops cleanly on SIGINT or SIGTERM.

`living/tools/path_budget/` (its own workspace) measures how many path-search expansions a click-to-move needs between two places on a world's real terrain.
