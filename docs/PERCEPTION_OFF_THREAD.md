# Perception off the thread: does it reach about 1.2 ms/s a viewer?

Status: **measurement and design**, 2026-11-22, dev-box. The prototype lives on branch `perc-offthread` (on `relay-proto`) and never goes to main. This note measures the premise of [BATTLE_DELIVERY_PATHS.md](BATTLE_DELIVERY_PATHS.md)'s stage 2, which [RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md) made the next question: with the relay doing delivery, what does the authority pay per viewer once sight and the attention choice are worked out off its thread?

> **Correction (2026-11-22, the 60 Hz budget): the viewer counts here are upper bounds for strict 60 Hz.**
> - **Measured** ([BATTLE_CONTRACT_CASES.md](BATTLE_CONTRACT_CASES.md) §4, dev-box, `performance` governor). Strict 60 Hz means at least 59.9 ticks/s, with step p99 within one 16.7 ms slot. It held only up to about **390 ms/s** of database-thread work. Arms at 440–520 ms/s ran 59.0–59.9 ticks/s, with about 1% of steps late.
> - **What sets the 390** (the tick's own work, commits, or the scheduler) is being measured in HUMAN_FIGHTER_COST.
> - **Why the counts are upper bounds:** the table under "The answer" counts N = B / f with B = 600 − R.
> - **This note's own runs show it:** its 64- and 128-viewer arms (420 and 500 ms/s) ran 59.6 and 59.0 ticks/s.
> - **With 390 ms/s as the budget** (an estimate): relay plus off-thread perception at 1.33–1.46 ms/s per viewer fits about **53–58 viewers** with 15 Hz fighters (R 312.8) and **71–78** with 10 Hz fighters (R 286.7). That is not 197–236.
> - **The answer stands:** no.

## The answer

**No. Relay plus off-thread perception measures 1.33–1.46 ms/s per viewer at 128 viewers, and 1.41–1.68 at 64.** That is above the about 1.2 target.
- **Conditions:** contract density (26–32 m ring), uninstrumented, the dev-box on the `performance` governor, two runs per arm. Each range spans the two 0-viewer references (§2.2).
- **With what the stand-in skips** (validation, a real computer's wider feed, crowd rows, the sweep's other per-viewer duties), the cost is about **1.45–1.65** (estimate, §1.2 and §3.2).

**What that buys, at 60 Hz in the 200-fighter battle** (budget 600 ms/s less the battle with the relay connected):

| | 15 Hz fighters (R = 312.8, B = 287) | 10 Hz fighters (R = 286.7, B = 313) |
|---|---:|---:|
| Today's path with the plausible cuts (64 viewers: 3.01 ms/s) | about **93** | about 104 |
| Relay alone (64 viewers: 2.18; 2.22 at 10 Hz) | about **132** | about 141 |
| **Relay plus off-thread perception** (128 viewers: 1.33–1.46) | **197–216** | **215–236** |
| The same, with the stand-in's omissions added back (1.45–1.65, estimate) | 174–198 | 190–216 |

The direct row's 15 Hz budget is against the battle alone (318.8, B = 281). Its 10 Hz figure assumes the per-viewer cost unchanged at 10 Hz, as the relay arms showed; direct was not run at 10 Hz.

**216 viewers at 60 Hz is at the edge, not reached with margin.** It needs all of:
- the relay (measured);
- perception off the thread (measured with a stand-in; the owner's call);
- 10 Hz fighters (measured; the owner's call).

Even then the measured range lands at 215–236 and the estimate at 190–216.

**Why it stops near 1.3–1.5.** About 0.8 ms/s per viewer is the viewer as a character: its witness lines, its own evaluations, its acts, its body. An AI character in its place pays the same, and **10 Hz fighters do not reduce it.** Relay at 64 viewers costs 2.18 per viewer at 15 Hz and 2.22 at 10 Hz. 10 Hz saves about 26 ms/s battle-wide (313 → 287) instead. Applying the sets costs about 0.2 ms/s per viewer (`perc_apply`: 13.8 ms/s at 64 viewers, 24.5 at 128).

**So to reach 1.2 with margin,** the next lever is not delivery or perception. It is the per-character cost of a player character in a battle. That is the AI tick's side ([COMBAT_PHASE.md](COMBAT_PHASE.md)), and it applies equally to the contract's 2,000 characters.

**Privacy, re-proved on the fixed probe** (§1.4, `26c71b96e`):
- **The known answer:** the broken relay was caught with 143 violations in 23,350 rows; the real relay had 0.
- **Every relay arm since:** relay alone at 16, 64 and 128 viewers, and relay plus perception at 16, 64 and 128: **0 violations in 2,463,253 rows**, including set changes in the same transaction (§2.3).

**For the owner:** stage 2 is worth it only together with the relay and 10 Hz fighters, and even then only reaches 216 at the edge. The design is in §3: the authority keeps writing and checking every set; the computer runs the same rules crate; a fallback to the authority's own sweep; replays from the commitlog.

## 1. What was measured, and what the stand-in pays and skips

### 1.1 The prototype (branch `perc-offthread`)

- **A value-only switch `perc_external`, off by default.** With it on, the authority's scheduled sweep does nothing for players: no sight, heed, hearing, crowd rows, projection refresh or anything else `sweep_one` does in the tick.
- **An admin reducer `perc_apply(diffs)`.** For each viewer's diff (the creatures that came into its set, and those that left), it does what the sweep does with its own result:
  - deletes the leavers' `perceived` rows and their projections;
  - inserts each newcomer's `perceived` row;
  - writes the newcomer's projection: its name or label as this viewer knows it, under the regard law (`project`).
- **The stand-in for the off-thread computer:** `relay_proto perc`, our Rust tool. It runs one owner connection subscribing `body` and `player`.
  - Every 50 ms it handles a quarter of the players, so each is handled every 200 ms, as the sweep's 5 Hz.
  - It picks each one's set by a geometric rule: the nearest 11 within 25 m, plus a deterministic swap of the farthest member on 40% of rounds.
  - It sends the round's changes in one `perc_apply` call: about 20 calls a second for the whole battle.
- **The stand-in was calibrated to heed's measured output at the same density** (RELAY_PROTOTYPE series s):

  | | Stand-in | Heed |
  |---|---:|---:|
  | Mean set | 11.0 | 10.6–11.0 |
  | Newcomers per viewer-second | 5.5 | 4.9 |

  So the authority applies slightly more churn than heed would give it.
- **Code:**
  - `fd3ad754a`: the switch, `perc_apply`, the stand-in and `battle_viewers.py --perc`;
  - the commits after it: the stand-in's knobs;
  - `26c71b96e`: the transaction-naming fix (§1.4).
- **Bindings** regenerated; the only additions are `perc_apply` and the `PercDiff` type.
- **Off is off.** Main `a6375a70e` against the `perc-offthread` module (`4965d3e06a27`) with every switch off, in `det_compare`'s player mode (16 players, 200 fighters, 1,800 ticks): **identical**, 113 tables and 45,904 rows. The negative control, `perc_external=true`, differs: the scheduled sweep stops.

### 1.2 What the stand-in's numbers include, and what they leave out

**Included in the authority cost measured:**
- the reducer call for each batch;
- decoding the diffs;
- every `perceived` insert and delete;
- every projection written for a newcomer (the regard law) or deleted for a leaver;
- the subscription evaluation of those rows for the relay;
- the stand-in's own subscription (`body`, `player`).

**Not included,** each a cost a real design adds back, listed in §3:
- **Validation:** the checks the authority would make before applying a set (§3.2): the distance bound, forced individuals and a sampled audit.
- **The real computer's wider subscription:** characters, vitals, fighters, doings, the heed tables and the script, beyond `body` and `player`.
- **What the sweep does for players besides choosing the set:**
  - the own row's projection refresh about once a second;
  - re-projection when the viewer's knowledge or a reveal changes;
  - crowd rows;
  - earshot;
  - the resources look;
  - first sights and the gaze band.
- **The stand-in's rule is not the sight rule or heed.** It stands in for their output only, so its cost on its own process is not the real computer's.

### 1.3 Fixture, host and arms

- **The fixture:** as RELAY_PROTOTYPE.
  - the 200-fighter sustained Cullet battle;
  - viewers on the 26–32 m ring, the contract's density;
  - the relay on (`relay_on`) for every arm except the direct arm and its reference, so the result reads "relay plus off-thread perception";
  - module memory for the sweep and lines every 1 s;
  - no profiling for the headline numbers;
  - 20 s warm-up and a 60 s window.
- **The host:** the dev-box on the **`performance` governor** (EPP `performance`, `amd-pstate-epp`, all 32 cores) since **2026-11-22 11:25:36 UTC**, the owner's decision. Every run of the headline series is after it, and every run records the governor and the poller in `host.json`. A process waking every 200 µs ran through the series, as before, so all arms share the host's state.
- **Superseded:** the same arms run before the switch, on `powersave` (warm), are kept in `.local/pc/superseded/powersave/` and labelled with the governor. §2.4 compares them.

**Arms** (series q, the poller on throughout, two runs each unless marked):

| Arm | Viewers | What |
|---|---:|---|
| `q-rr0cold`, `q-rr0warm` (1 each) | 0 | the governor check: relay connected, with and without the poller |
| `q-broken16`, `q-real16` (1 each, 30 s) | 16 | the privacy probe's known answer on the fixed naming |
| `q-r0` | 0 | the battle alone (reference for direct) |
| `q-rr0` | 0 | the battle, relay connected (reference for relay arms) |
| `q-pr0` | 0 | the battle, relay and stand-in connected, `perc_external` (reference for perception arms) |
| `q-direct64` | 64 | today's path with the plausible cuts (RELAY_PROTOTYPE's direct arm) |
| `q-relay64` | 64 | relay only |
| `q-perc16`, `q-perc64`, `q-perc128` | 16, 64, 128 | relay plus off-thread perception |
| `q-rr0e10`, `q-relay64e10` | 0, 64 | relay, with fighters at 10 Hz (`combat_eval_hz=10`) |
| `v-priv16`, `v-priv128` (1 each, series v) | 16, 128 | privacy arms: relay only |

### 1.4 A defect in the privacy probe, found and fixed here

- **The defect.** Housekeeping (1 Hz, `tick.rs`) writes the `clock` row without moving its tick, and so does a script install. The relay and the checker both named transactions by (the latest tick, the number of messages since it), and treated any `clock` change as a new tick. So once a second two transactions shared a name.
- **How it showed.** In one `powersave` run (`p-perc64-r1`), 6 rows were flagged: creature 98's `fighter` row reaching 5 viewers after it left their sets. Viewer 30's log shows the row labelled 4851.2 arriving **before** the "gone" labelled 4851.1 on the same WebSocket, so the names, not the relay, were out of order.
- **The fix** (`26c71b96e`): a transaction is a new tick's only when the clock's tick number moves.
- **What it means for earlier evidence.** The earlier 0-violation results (RELAY_PROTOTYPE §3.4) stand as observed. But the collision, once a second, could in principle also have hidden a real violation at those boundaries. The known answer was run again on the fixed naming (§2.3).

## 2. Results (performance governor, warm)

### 2.1 The governor check

- With the relay connected and 0 viewers: **327.3 ms/s cold, 332.3 warm.**
- On `powersave` the same pair differed by about 12% (RELAY_PROTOTYPE §2.3). On `performance` the difference is gone, within one run's spread.
- The poller still ran through the series, so all arms share the host's state.

### 2.2 Per viewer (performance governor; L0; 2 runs per arm)

| Arm | Viewers | Ticks/s | Database thread, ms/s | Per viewer, ms/s | Its reference |
|---|---:|---:|---:|---:|---|
| Battle alone | 0 | 60.0 | 318.8 (313.5–324.0) | – | – |
| Battle, relay connected | 0 | 60.0 | 312.8 (310.6–315.0) | – | – |
| Battle, relay and stand-in, `perc_external` | 0 | 59.9 | 330.0 (327.0–333.0) | – | – |
| Battle, relay, 10 Hz fighters | 0 | 60.0 | 286.7 (285.3–288.1) | – | – |
| Direct | 64 | 59.1 | 511.5 | **3.01** (2.97–3.05) | battle alone |
| Relay | 64 | 59.4 | 452.4 | **2.18** (2.13–2.23) | relay connected |
| Relay, 10 Hz fighters | 64 | 59.3 | 428.7 | 2.22 (2.17–2.26) | relay, 10 Hz |
| Relay plus perception | 16 | 60.0 | 358.9 | 1.81 (1.66–1.96) / 2.88 | stand-in connected / relay connected |
| **Relay plus perception** | **64** | 59.6 | 420.1 | **1.41** (1.37–1.45) / **1.68** | stand-in connected / relay connected |
| **Relay plus perception** | **128** | 59.0 | 500.2 | **1.33** (1.30–1.36) / **1.46** | stand-in connected / relay connected |

- **Two references for the perception arms.**
  - The battle with the relay and stand-in connected ran 17 ms/s above the battle with the relay alone. That held in both runs (327.0–333.0 against 310.6–315.0), although with no players the stand-in sends nothing and the authority sweeps no one.
  - Its subscription evaluation is the same (1.33 against 1.26 ms/s), so the 17 ms/s is not explained.
  - Each perception arm is given against both references. The higher figure (against the relay-only battle) is the conservative one.
  - At 16 viewers the per-viewer figure carries the references' ±3–5 ms/s divided by 16, so it does not separate arms.
- **Applying the sets** (`perc_apply` transactions): 4.9, 13.8 and 24.5 ms/s at 16, 64 and 128 viewers. That is **0.19–0.31 ms/s per viewer**, inside the figures above.
- **The off-thread side.** The stand-in used 13, 21 and 32 ms/s of CPU, and the relay 19, 33 and 49 ms/s, at 16, 64 and 128 viewers. Both are separate processes, off the database thread. The stand-in's CPU is not the real computer's: it does not run the sight rule or heed.
- **Latency.** Relay hop p99: 0.16–0.35 ms at 16 viewers, 0.43–0.48 at 64, 0.90 at 128. Tick start → client p99: 32–38 ms. Each set reaches the authority within one 50 ms round of the stand-in, plus the reducer's queue.

### 2.3 Privacy on the fixed probe

| Arms | Viewers | Rows checked | Outside the set |
|---|---:|---:|---:|
| Broken relay (known answer) | 16 | 23,350 | **143** |
| Relay only (`q-real16`, `v-priv16`) | 16 | 58,089 | 0 |
| Relay only (`q-relay64`, `q-relay64e10`, 4 runs) | 64 | 680,526 | 0 |
| Relay only (`v-priv128`) | 128 | 356,328 | 0 |
| Relay plus perception (`q-perc16`) | 16 | 81,183 | 0 |
| Relay plus perception (`q-perc64`) | 64 | 407,161 | 0 |
| Relay plus perception (`q-perc128`) | 128 | 879,966 | 0 |
| **All real-relay arms** | 16–128 | **2,463,253** | **0** |

The checker rides along in every relay arm and in its 0-viewer reference alike, so its cost (about 1 ms/s for the battle) cancels out of the per-viewer figures. This corrects RELAY_PROTOTYPE §3.4, whose figure was checked under the old naming; that note carries the correction too.

### 2.4 Against the `powersave` runs (superseded)

The same arms run warm on `powersave`, one or two runs each, before the switch. Relay plus perception: 1.51 at 64 viewers, 1.34 at 128 (against the stand-in-connected reference). Relay alone: 2.27 at 64. Relay at 10 Hz: 2.06 at 64.

The `performance` series agrees within the runs' spread, and its absolute database times are about 5–6% lower: 312.8 against 331.6 for the battle with the relay connected.

## 3. The design, for the owner's decision

### 3.1 Who computes perception, and who writes the sets

- **The computer.** A perception computer we own (Rust, like the mind service and the relay), running **the same rules crate**:
  - `living_rules::sight::sees` with the map;
  - the senses law and the keep margins;
  - `living_rules::heed::select` with each character's policy and capacity;
  - the installed script for the Rhai laws (the senses law, the capacity law).

  It is not a second approximate simulator. It is the authority's own rule code, run on the authority's own rows, outside the reducer thread.
- **Its input.** One trusted subscription to what sight and heed read:
  - bodies (motion segments), characters (kind, stage, the senses' inputs), vitals for contact and hurt;
  - fighter and doing for aims, the engagement map's source;
  - the heed tables (`heed_policy`, `attend_pick`, `attend_effect`);
  - structures, light and the world's day;
  - the `script` row.
- **Its output.** Each viewer's set diff, tagged with the authority tick its inputs were read at, sent in batched `perc_apply` calls.
- **Who writes.** Only the authority, in `perc_apply`: the `perceived` rows, projections, and everything that follows from them (the relay's permissions, first sights, knowledge). The computer writes nothing itself.

### 3.2 What the authority checks before applying a set

All cheap, local and bounded per viewer:
1. **The caller** is the allow-listed computer identity, as the mind service is.
2. **Freshness.** The diff's tick is within a bound of now (say 30 ticks, 500 ms); a stale diff is refused.
3. **Reach.** Each newcomer is alive and within the viewer's widest possible sight from current positions: one distance check per newcomer, not the sight rule.
4. **Capacity.** The set does not exceed the viewer's capacity (the capacity law's value, which the authority already holds).
5. **The ruled forced individuals** (the owner's ruling on point 6: whom the viewer acts on, and who made contact in the last few seconds). The authority adds them itself from its own maps, so no lag or computer fault can produce an invisible blow.
6. **A sampled audit.** The authority re-runs the real sight rule (and, at a lower rate, heed) for a small random share of the computer's (viewer, creature) answers each second, say 1%, and counts disagreements. That bounds drift and a broken computer. A disagreement rate above a threshold switches to the fallback (§3.3).

These checks are not in the measured number (§1.2). A rough size: the distance and capacity checks are about a microsecond per newcomer (at 5.5 a viewer-second, about 0.006 ms/s a viewer). The 1% audit is 1% of today's sight-and-heed cost, about 0.01 ms/s a viewer. **Together, under about 0.05 ms/s a viewer (estimate).**

### 3.3 When the computer lags or dies

- **Detection.** The authority records the last applied diff's tick per viewer. If no diff arrives for a bound (say 500 ms) while the viewer's surroundings changed, the computer counts as lagging.
- **Fallback.** The authority's own sweep for that viewer resumes. The code stays, behind the same switch, now a runtime state. A whole-computer failure means the authority sweeps everyone, at today's cost: the battle's tick rate falls to what VIEWER_FLOOR measured (about 96 viewers fit at 60 Hz) until the computer is back.
- **Meanwhile, what players see:**
  - their last set stays, with leavers beyond reach dropped by the authority's own distance check each second;
  - newcomers appear only when the fallback sweep runs;
  - the forced individuals (contact, acting) are always added by the authority, so a blow from someone not yet attended still brings them into view;
  - the relay keeps fanning out the last set's changes.
- **Minds see nothing different.** They build scenes from the authority (`Sensing`, `scene_json`) and their attended sets live in module memory rebuilt from rows (the Spark's answer, RELAY_PROTOTYPE §5). The computer is for players' perceived sets only. A later design could extend it to minds, but that is not this stage.

### 3.4 Determinism and replays

- **Today:** perception is a function of the tick's state, computed in the tick, so `det_compare` can step two builds and compare every table every tick.
- **With the computer, a perceived set becomes an input,** like a player's reducer call. It is committed by `perc_apply` transactions, which the commitlog keeps. **A replay of the commitlog reproduces the sets exactly.**
- **Stepped comparison (`det_compare`).** The computer is a pure function of the state at its basis tick plus the rules. A deterministic harness runs it synchronously: compute at tick t, apply at tick t + k with k fixed. Two builds then step identically, as today. The prototype's off-equals-main check already runs with the switch off. A deterministic computer mode is part of the build, not of this measurement.
- **Live timing is not reproducible from the seed alone.** Which tick a diff lands in depends on wall time, as players' inputs do today. The causal record stays exact: each applied diff carries its basis tick, and audit truth can keep (viewer, basis tick, diff) for a window.

### 3.5 AGENTS.md's constraints

- **"Keep rules authoritative in the living authority and expressed in its shared rules and skill scripts."** The rules stay the shared rules crate and the installed script, evaluated by the same code. Authority over the outcome stays with the authority, which checks, bounds, audits and writes. **What changes is where the evaluation runs.** Sight and heed would no longer be computed in the reducer thread. That is the owner's call, which is why stage 2 is marked so.
- **"Do not create a second approximate simulator."** The computer must not approximate. It reads the same rows and runs the same functions. Anything the sweep keeps in module memory (`KEPT`, the senses' memo, `HEARD_KEPT`) is a cache of rows, which the computer rebuilds from the same rows. The sampled audit (§3.2) is how a divergence would be caught. The stand-in measured here is **not** such a computer: it approximates on purpose, to measure the authority's side only.
- **"Spatial subscriptions are not permission boundaries."** The permission remains the authority-written `perceived` set, which the relay enforces (RELAY_PROTOTYPE).
- **External inference stays in the mind service.** The computer evaluates rules, not models.

## 4. What was not measured

- **A real perception computer.** The stand-in picks sets by distance and churn, calibrated to heed's output. It does not run the sight rule or heed, so its own CPU (13–32 ms/s) is not the real computer's. A real one would run the sight rule over about 49 in sight and heed's features and rules per viewer at 5 Hz. By VIEWER_FLOOR's L2 shares that is about 0.4–0.6 ms/s per viewer of CPU, off the database thread: about 90–130 ms/s at 216, a fraction of one core (estimate).
- **Validation, audit and fallback on the authority** (§3.2, §3.3). Estimated under about 0.05 ms/s per viewer, plus the fallback's full cost while it runs.
- **What the scheduled sweep does for players besides the set:** the own row's projection refresh, knowledge re-projection, crowd rows, earshot, first sights and the gaze band. Together a share of the sweep's 0.92 ms/s that is not split here (RELAY_PROTOTYPE §3.2); crowd rows alone were about 0.04–0.08 (E2).
- **Minds.** They keep sweeping (`Sensing`) on the authority. Their attended sets are not moved.
- **The 17 ms/s between the two 0-viewer references** (§2.2), unexplained. Both are reported.
- **X925 on L0 at current main.** The Spark is measuring it. The host counts here are dev-box's.
- **Tick latency p99 against the contract** at the fitting counts. Ticks held 59.0–59.6 per second at 64 and 128 viewers.

## Evidence

- **Code:** branch `perc-offthread`, never for main:
  - `fd3ad754a`: the switch, `perc_apply` and the stand-in;
  - the stand-in's knobs;
  - `26c71b96e`: the naming fix.
  - On top of `relay-proto` (`b12a05ae5`).
  - Module `pc-cullet` `4965d3e06a27`. Main's module for the off-equals-main check: `cde8d300c340` (`a6375a70e`).
- **Runs:** dev-box, worktree `t3-b749c655`, `.local/pc/`:
  - `runs/` holds series q and v: per run, `battle-viewers.json`, `host.json` (governor and poller), `v<n>/metrics.json`, `threads.json`, `relay.json`, `clients.json`, `perc.json`, `checker.log`, `clients.json.items`;
  - `runs/series.log` holds module hash, commit, dirty count, governor, poller and load per run;
  - `tables-q.json` (`pc_tables.py q`);
  - `superseded/powersave/` holds the `powersave` arms;
  - `det-off/` and `det-negative/`;
  - the scripts `series-p.sh`, `series-q.sh` and `series-v.sh`.
- **Archived** to `~/archive/worktree-evidence-20261122/perc-offthread.tar.zst` on the dev-box (sha256 in the `.sha256` beside it).
- **The governor switch:** `performance`, EPP `performance`, all 32 cores, from 2026-11-22 11:25:36 UTC (the coordinator's switch, the owner's decision); `cpu-governor-performance.service`.
- **Related:**
  - [RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md) (corrected here);
  - [BATTLE_DELIVERY_PATHS.md](BATTLE_DELIVERY_PATHS.md);
  - [VIEWER_FLOOR.md](VIEWER_FLOOR.md);
  - [PERCEPTION.md](PERCEPTION.md);
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md).
