# The contract's own battle: human fighters, measured

Status: **measurement**, 2026-11-22, dev-box. The measuring code is on branch `contract-cases`, which never goes to main.

The question comes from the coordinator's framing. Every series before this one measured 200 AI fighters plus N extra viewer characters on a ring, so at 216 viewers about 416 characters. The contract's own workloads are different:
- the **216 gate**: 216 active characters with a crowded battle, as GATE_216 drove it, 216 human clients with 100 of them in the battle;
- the **scale gate**: a 200-character battle within 2,000.

In those, the people watching a battle are mostly its fighters. A human fighter replaces an AI fighter rather than adding a viewer, and it runs no behaviour graph, only input. So is the viewer's cost already inside the battle?

## Bottom line

**No. The contract's own battle does not fit at 60 Hz on either host, on any path that keeps rule work on the database thread.** That covers the direct path, the direct path with the plausible cuts, and the relay alone.

**The 216 gate:**
- **With 100 human fighters among 216 human characters**, it misses narrowly with the relay alone:
  - on the dev-box, measured: 59.2 ticks/s, step p99 28 ms, 1.3% of steps later than 25 ms;
  - on X925 it is at the edge (scaled, §3).
- **The direct path misses** on both hosts.
- **With 200 human fighters,** every path saturates near 27–31 ticks/s.

**The premise does not hold.** A human fighter does not replace an AI fighter's cost. It adds **3.1–3.7 ms/s** on top of the AI fighter's 1.4, measured at 50 human fighters:
- perception of a melee (about 113 in sight, 16 heeded);
- the player's character;
- delivery;
- input, rejoins included.

**Verdicts per case and host.** "Holds" means at least 59.9 ticks/s with step p99 within one slot (18 ms). The dev-box columns are measured. The X925 columns are the dev-box's demand at 60 Hz scaled by the measured same-code ratio, 0.86–0.92 (§3).

| Case (16 spectators in B) | Dev-box, direct | Dev-box, relay alone | X925, direct (scaled) | X925, relay alone (scaled) |
|---|---|---|---|---|
| B0: 200 AI fighters | **holds** (59.9; 386 ms/s) | **holds** (60.0; 354) | holds (332–356) | holds (305–326) |
| B50: 50 human, 150 AI | fails (58.5; 2.5% of steps late) | misses (59.3; 1.2% late) | misses (503–538) | edge (445–476) |
| B100: 100 human, 100 AI | fails (50.2) | fails (54.4) | fails (692–740) | fails (599–641) |
| B200: 200 human | fails (27.0; 25.6 ms a tick) | fails (28.3; 24.0 ms a tick) | fails (22–24 ms a tick) | fails (21–22 ms a tick) |
| A100: 100 human fighters, 116 walkers | fails (57.7; 3.8% late) | misses (59.2; 1.3% late) | misses (548–586) | edge (453–484) |
| A200: 200 human fighters, 16 walkers | fails (27.2) | fails (30.8) | fails (22–23 ms a tick) | fails (18–20 ms a tick) |

- **The X925 thresholds are measured runs on both hosts:**
  - arms at about 390 ms/s or less hold 60 Hz;
  - arms at 440–520 ms/s run 59.0–59.9 ticks/s (the Spark's 16-viewer arm, 443 ms/s, ran 59.73–59.92);
  - arms above about 570 ms/s fail.
- **The largest number of human fighters that holds 60 Hz** in the 200-fighter battle with 16 spectators is about 10 on the dev-box with the relay, and almost none direct. On X925 it is about 20–30 with the relay, or 10–20 direct (estimates). Not 200, and not 100.

**Which host decides.** The contract does not choose:
- it says representative workload parameters "must be fixed before claiming acceptance, rather than chosen after seeing results";
- an acceptance run's manifest freezes "exact backend and client hardware/settings" beforehand;
- it notes that "a vCPU count alone does not make two machines equivalent".

The reference server is not selected yet; that choice is the owner's. **The choice of reference server decides which column applies.** On this battle, both columns say no.

## 1. Method

### 1.1 The cases

| Case | Characters | What |
|---|---|---|
| **A, the 216 gate** | 216 humans | A100: 100 human fighters and 116 walkers. A200: 200 human fighters and 16 walkers. No AI fighters. |
| **B, mixed** | 200 fighters and 16 spectators | H of the 200 fighters are human (H = 0, 50, 100, 200), the rest AI; 16 human spectators on the ring. |
| References | – | An empty world (Cullet's own residents only); 116 walkers alone; 100 and 200 AI fighters alone. |

**Two paths for each,** both with no rule work leaving the database thread:
- **direct:** today's path with VIEWER_FLOOR's plausible cuts: heed at a ceiling of 16 with holds, crowd rows, module memory for the sweep, lines every 1 s, hearing every 5th sweep, the feed off;
- **relay alone:** RELAY_PROTOTYPE's `relay_on`, with the relay doing delivery, hearing and the fight feed. Sight and heed stay on the authority.

### 1.2 The fixture

Kept as in the earlier series, so the numbers compare:
- **Place:** Cullet, the plaza 20 m from the arrival point.
- **Fighters:** every fighter, AI or human, starts within 7 m of the battle's centre; this is the earlier series' density.
- **Spectators:** on the 26–32 m ring, kept alive.
- **AI fighters:** `spawn_battle`'s fight graph (attack the nearest person, dodge or block when threatened). The keeper refills the dead one for one, every second.
- **Human fighters** fall like anyone else. A dead one rejoins after 3 s with the newcomer's kit, at the arrival point 20 m away, and walks back into the fight (GATE_216's renewal, `join`).
- **Walkers:** at lot doors round the settlements, walking small circles (GATE_216's walkers).
- **Timing:** paused placement, the AI battle spawned after placing, 20 s warm-up, a 60 s window, no profiling (L0) for the headline numbers.

### 1.3 A human fighter's input

- **The driver:** GATE_216's (`gate-load`, battle role). One decision every 250 ms ±10%, against the nearest person it perceives:
  - heal below 45% health;
  - strike in reach (+0.4 m);
  - a fire bolt at 4–15 m (25% of chances);
  - a bow shot at 2.5–14 m while arrows last;
  - a raised guard (8%, released after 600 ms) or a dodge (5%) within 6 m;
  - otherwise a move toward the target, sent only when the direction changes by more than 30°, running toggles, or 2 s pass.
- **One change, gated on what the game client gates on.** A move is tried only when its pool (breath or focus) has its cost and the character knows the technique, as the game client checks before sending (`living/game/src/verbs.rs`, `me_facts`).
  - GATE_216's driver predates the breath pool. In the first smoke run most strikes came back "out of breath", and heal and fire bolt were unknown to a Cullet newcomer.
  - With the gate, refusals are mostly "out of reach", as in GATE_216's smoke runs.
- **Where the rate comes from:** GATE_216's declared workload. Measured here: each human fighter sent about 2.9–3.0 inputs a second (at 100 human fighters: 2.2 moves, 0.44 strikes, 0.16 raised guards, 0.15 releases, 0.03 dodges and 0.02 rejoins). GATE_216's battle sent about 2.6 per battle player (337 a second for 100 fighters and 116 walkers).
- **In the relay arms,** the authority writes no copies, so a human fighter aims from the relay's own stream of its set's bodies (gate-load opens a WebSocket to the relay). Its other subscriptions are unchanged.

### 1.4 What each run records

- The database thread's CPU and the tick's transactions by reducer (server metrics), as before.
- **Steps:** a tick watcher (gate-load `watch`, as GATE_216): two owner connections subscribing `clock`. From it, each step's interval on the authority's own clock, its p50/p99/max, and grid steps skipped. It runs in every arm, references included.
- **The fight:**
  - the human fighters' inputs by kind, their deaths and how their released moves came out (gate-load's events);
  - the AI fallen (the keeper's refills).
- **Host:**
  - the governor (`performance` throughout) and the warm poller, as before;
  - the busiest processes at each run's start and end;
  - a 2 s sampler of the host's busy CPU and of the processes under `~/.local/share/github-actions`.

  Other projects' self-hosted runner listeners ran throughout, restarting in bursts. A run is marked when their CPU averaged over 0.5 cores or any 10 s exceeded 1.5 cores, and marked runs were redone (§2.5).

**Not in these runs:** the 80 ms round trip, the observer and the game client. The earlier series did not have them either, so the numbers compare. GATE_216's other parts (latency lines, frame pacing) are not measured here.

## 2. Results on the dev-box (L0, `performance` governor, warm, 2 runs per arm)

### 2.1 The arms

| Arm | Humans | Path | Ticks/s | Step p50 / p99 / max (ms) | Steps later than 25 ms | DB thread, ms/s (range) | Tick, ms/s | Subscription evaluation | Views | Input reducers |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| Empty world | 0 | direct | 60.0 | 17 / 18 / 18 | 0 | 34.6 | 32.7 | 0.7 | 0 | 0 |
| 116 walkers | 116 | direct | 60.0 | 17 / 18 / 19 | 0 | 157.0 | 133.2 | 7.5 | 4.2 | 15.3 |
| 116 walkers | 116 | relay | 60.0 | 17 / 18 / 18 | 0 | 127.2 | 107.6 | 3.2 | 3.6 | 15.5 |
| 100 AI fighters | 0 | – | 60.0 | 17 / 18 / 18 | 0 | 187.8 | 183.5 | 0.8 | 0 | 0 |
| 200 AI fighters | 0 | direct | 60.0 | 17 / 18 / 28 | 0.04% | 319.0 (317–321) | 312.1 | 0.9 | 0 | 0 |
| 200 AI fighters | 0 | relay | 60.0 | 17 / 18 / 32 | 0.07% | 317.8 (314–321) | 310.8 | 1.3 | 0 | 0 |
| **B0** | 16 | direct | 59.9 | 17 / 18 / 33 | 0.11% | 386.1 (374–398) | 374.1 | 3.1 | 2.0 | 2.5 |
| **B0** | 16 | relay | 60.0 | 17 / 18 / 30 | 0.04% | 354.1 (353–355) | 342.4 | 2.2 | 1.9 | 2.4 |
| **B50** | 66 | direct | 58.5 | 17 / 33 / 34 | 2.5% | 570.2 (559–581) | 517.3 | 12.3 | 18.5 | 35.5 |
| **B50** | 66 | relay | 59.3 | 17 / 28 / 35 | 1.2% | 510.9 (509–513) | 464.8 | 5.3 | 17.5 | 35.1 |
| **B100** | 116 | direct | 50.2 | 17 / 34 / 46 | 19% | 680.1 (679–681) | 591.1 | 18.3 | 29.0 | 67.9 |
| **B100** | 116 | relay | 54.4 | 17 / 34 / 46 | 10% | 635.2 (631–640) | 559.8 | 7.9 | 32.3 | 64.0 |
| **B200** | 216 | direct | 27.0 | 34 / 60 / 70 | 97% | 843.4 (840–846) | 692.5 | 26.2 | 33.5 | 126.4 |
| **B200** | 216 | relay | 28.3 | 34 / 58 / 68 | 95% | 813.6 (807–820) | 678.2 | 11.6 | 56.2 | 124.3 |
| **A100** | 216 | direct | 57.7 | 17 / 33 / 38 | 3.8% | 614.4 (609–620) | 512.4 | 23.1 | 34.3 | 79.5 |
| **A100** | 216 | relay | 59.2 | 17 / 28 / 36 | 1.3% | 519.8 (517–522) | 432.9 | 8.8 | 35.2 | 78.1 |
| **A200** | 216 | direct | 27.2 | 34 / 61 / 78 | 96% | 836.4 (835–838) | 686.2 | 25.7 | 33.3 | 126.3 |
| **A200** | 216 | relay | 30.8 | 33 / 53 / 72 | 84% | 790.5 (779–802) | 655.6 | 11.2 | 55.0 | 124.7 |

- **A saturated arm** (ticks under 59) reports what the thread managed, not what 60 Hz would ask. Its demand at 60 Hz is estimated by scaling the tick's work by 60 / ticks (§3).
  - B200 and A200 need 21–26 ms of tick per step on the dev-box, against a 16.7 ms slot, before any input. No host in reach makes up a factor of 1.5.
- **The fight is real.**
  - Human fighters land blows: at 100 humans, about 34 hits a second of 44 strikes, with blocks, dodges and misses.
  - They fall about 1.4 times a minute each and rejoin; the AI fall about 0.7 times a minute each, and the keeper refills them.
  - Blows a second (all fighters, L1 counter): 57 at B0, 73 at B100, 83 at B200.
- **Against GATE_216** (2026-11-09: 0.51 steps a second in its battle), the authority now runs a 100-human battle among 216 humans at 57.7–59.2 ticks a second. The view work that sank it is gone (subscription evaluation 9–23 ms/s here).

### 2.2 What one character costs (ms/s of the database thread)

| Character | Direct | Relay | How |
|---|---:|---:|---|
| AI fighter | **1.42** (1.53 at 100) | – | (200 AI − empty) / 200 |
| Walker at a lot door | 1.06 | 0.81 | (116 walkers − empty) / 116 |
| Spectator on the ring (16) | 4.2 | 2.3 | (B0 − 200 AI) / 16; 16 spectators do not separate well |
| **Human fighter, replacing an AI fighter** (B50, near 60 Hz) | **+3.68** | **+3.14** | (B50 − B0) / 50 |
| The same at B100 (saturated, a low bound) | +2.94 | +2.81 | (B100 − B0) / 100 |
| **Human fighter, all-human battle** (A100) | **4.57** | **3.93** | (A100 − 116 walkers) / 100 |

**So a human fighter costs about 4.6–5.1 ms/s on the direct path and 3.9–4.6 with the relay.** That is about three times an AI fighter's 1.4.
- The coordinator's framing expected the viewer's cost to replace the AI's. It does not: the human's perception and player character come on top, and only the AI's combat evaluation goes (§2.3).
- In this battle, the 16 spectators are a small part (35–70 ms/s). The fighters themselves are the cost.

### 2.3 Where a human fighter's cost goes (L1, B100 against B0, per human fighter)

The L1 runs saturate with humans (B100: 41.9 ticks/s direct, 50.5 relay), so the tick's parts are given two ways:
- per second as measured, a low bound for work done each tick;
- per tick at 60 Hz, a high bound, since slow ticks also carry time-driven catch-up.

The L0 swap cost (3.68 and 3.14) falls inside both.

| Part, ms/s per human fighter | Direct | Relay |
|---|---:|---:|
| **Perception:** the sweep for a player (about 113 in sight in the melee, 15.5 heeded; ring spectators see about 40) | **1.28–1.90** | **1.16–1.40** |
| Delivery in the tick: frames, copies, cues | 0.39–0.59 | 0.14–0.18 |
| Subscription evaluation | 0.15–0.22 | 0.05–0.07 |
| Views | 0.25–0.37 | 0.29–0.35 |
| **The player's character** over the AI's: fold, activity, wakes, slots, motion | **0.69–1.71** | **0.69–1.14** |
| Combat in the tick: the AI's evaluations that go with it | −0.23 to −0.69 | −0.36 to −0.59 |
| **Input:** moves, skills, releases, rejoins | **0.63** | **0.61** |
| **Total** | 2.76–5.04 | 2.48–3.37 |

- **Input is about 0.6 of it,** at about 3 inputs a second.
  - **Rejoins are the dear part.** A `join` costs about 8.7 ms of the thread (20 ms/s at 2.3 rejoins a second), half a tick slot in one transaction.
  - A strike or guard (`use_skill`) costs about 0.57 ms; a move about 0.02–0.03 ms.
  - Rejoins and skills are also a source of late steps: a 9 ms join beside a 9 ms tick misses the slot.
- **The relay saves about 0.5 per human fighter** (frames, copies, evaluation): the 3.68 → 3.14 at B50. It leaves perception, the character and input.
- **Perception for a fighter costs more than for a spectator** (1.2–1.9 against RELAY_PROTOTYPE's 0.92 on the ring). A melee puts about three times as many in sight, and heed is at its ceiling.

### 2.4 Privacy (relay arms)

The privacy probe (`26c71b96e`, the fixed naming) rode along in every relay arm:
- 723,372 rows received by the spectators' and walkers' relay clients were checked, with 0 outside the viewer's set;
- the human fighters' own relay streams were not logged.

### 2.5 Host

- **Governor:** `performance` in every run, with the warm poller.
- **Runner listeners.** Other projects' self-hosted runner listeners were restarting in bursts through the series.
  - Five runs went over the mark: about 0.5 cores on average, or 1.5 cores in some 10 s. They were the 200-AI references (both paths), 116 walkers direct, B100 relay and B200 direct.
  - The five were redone, with no mark. The originals are kept and listed in `flagged.txt`.
  - In the arms kept, the listeners averaged 0.1–0.5 cores.

## 3. Two hosts: the dev-box and X925

**The ratio, measured on identical code** (the Spark's request): the dev-box ran the Spark's X925 fixture.
- **The fixture:** main `d0c2f4e85`'s own module (Cullet), `battle_viewers.py` and gate-load; 200 sustained fighters; 0 and 16 viewers on the 10 m ring; every shipped delivery path; L0.
- **The dev-box's runs:** 2 runs each, interleaved 0, 16, 16, 0, on the `performance` governor, warm.

| | X925, pinned (the Spark, 3 runs) | Dev-box (2 runs) | X925 / dev-box |
|---|---:|---:|---:|
| 0 viewers, ms/s | 294.9 (289–304) | 321.5 (320–324) | **0.92** (0.90–0.95) |
| 16 viewers, ms/s | 442.7 (439–444) | 494.4 (484–505) | 0.90 |
| Per viewer, ms/s | 9.24 ± 0.30 | 10.81 (10.05–11.56) | **0.86** (0.73–0.96) |
| Ticks/s at 16 viewers | 59.73–59.92 | 59.01–59.44 | – |

- **Against the Spark's own comparison:** its 0.78 for the battle was taken against the dev-box's `powersave`-era 377.6. On the same governor and code, X925 is about 8–14% cheaper, not 22%.
- **VIEWER_FLOOR §6's 1.16** compared delivery paths, not cores: X925's figure came from a build without the fighter table and the combat feed. VIEWER_FLOOR carries a correction box in the same docs change.
- **How the X925 columns are made.** The bottom-line table scales each arm's demand at 60 Hz by 0.86–0.92. That rests on two assumptions:
  - human fighters' work scales like the viewers' and the AI's (not measured on X925);
  - the 60 Hz thresholds are wall-clock thread time on both hosts. The Spark's 443 ms/s at 59.73–59.92 ticks/s fits the dev-box's measured edge.

## 4. What this means

- **The contract's 200-character battle, with players in it, is not a delivery problem.** Delivery off the thread (the relay) is worth about 0.5 ms/s per human fighter. What remains per human fighter is:
  - perception, 1.2–1.9;
  - the player's character over an AI's, 0.7–1.7;
  - input, 0.6.

  Stage 2 (perception off the thread, PERCEPTION_OFF_THREAD.md) would take the perception share and add about 0.2 for applying sets. That leaves about 2 per human fighter above an AI's (estimate). At B100 with the relay that is still about 560–600 ms/s at 60 Hz, well beyond the edge.
- **The cuts that would matter here are:**
  - the player character's own tick work (fold, activity, wakes);
  - a cheaper rejoin;
  - fighters' perception in a melee (in sight and heed at the ceiling).

  These are the same per-character costs PERCEPTION_OFF_THREAD named.
- **A finding about the budget the earlier notes used.** VIEWER_FLOOR, RELAY_PROTOTYPE and PERCEPTION_OFF_THREAD counted viewers that fit "at 60 Hz" with the whole tick's work at or below 600 ms/s. Measured here, arms at 450–520 ms/s already miss about 1% of steps (59.2–59.4 ticks/s). Strict 60 Hz holds only to about 390–400 ms/s on the dev-box. Those counts are therefore upper bounds for strict cadence. Each of those notes carries a correction box in the same docs change.

## 5. Not measured

- **The 80 ms round trip, the observer, the game client,** and so GATE_216's latency lines and frame pacing.
- **Human fighters on X925.** The X925 columns are scaled (§3).
- **The 30-minute duration.** The windows are 60 s after a 20 s warm-up, with the battle sustained. Growth over 30 minutes (rejoins add characters, remains and records) is not measured.
- **Perception off the thread with human fighters.** §4's figure is an estimate from the L1 shares.
- **Human fighters' privacy on the relay.** Only spectators' and walkers' streams were checked.

## Evidence

- **Code:** branch `contract-cases` (`122c32f89`), never for main.
  - Built on `perc-offthread` (`1c8b97980`), which carries `relay_on`, the relay and the privacy probe (`26c71b96e`).
  - Module `cc-cullet` = `pc-cullet` (`4965d3e06a27`); every switch off is identical to main `a6375a70e` (PERCEPTION_OFF_THREAD §1.1).
- **The same-code X925 arms on the dev-box:** main `d0c2f4e85` exported (no worktree), its own `battle_viewers.py` and gate-load. Module `x-cullet` `c2e679a44580`; the Spark's build was `0ba0ca698b7b…`, from the same commit on another toolchain.
- **Runs:** dev-box, worktree `t3-b749c655`, `.local/cc/`:
  - `runs/c-*`: series c, L0;
  - `runs/x-*`: the Spark's fixture;
  - `runs/cL1-*`: L1;
  - `runs/series.log`: commit, module, governor, poller and load per run;
  - `runs/runners.log`: the 2 s host and runner sampler;
  - `flagged.txt`;
  - `tables-c.json` (`cc_tables.py c`) and `split-L1.json` (`cc_split.py`);
  - the scripts `series-c.sh`, `series-c1.sh`, `series-c2.sh`, `series-x.sh` and `runners.py`.
- **Archived** to `~/archive/worktree-evidence-20261122/contract-cases.tar.zst` on the dev-box (sha256 in the `.sha256` beside it).
- **The Spark's X925 evidence:** branch `x925-floor` (`7062c4d47`) and `~/slop-evidence/x925-floor-20261122.tar.zst` on the Spark (sha256 `11f128a8…`).
- **Related:**
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md);
  - [GATE_216.md](GATE_216.md);
  - [VIEWER_FLOOR.md](VIEWER_FLOOR.md) (corrected here);
  - [RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md);
  - [PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md);
  - [COMBAT_PHASE.md](COMBAT_PHASE.md).
