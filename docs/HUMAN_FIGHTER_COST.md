# What a human fighter costs, and why

Status: **measurement**, 2026-11-22, dev-box. The measuring code is on branch `contract-cases` (`87459b903`), never for main.

[BATTLE_CONTRACT_CASES.md](BATTLE_CONTRACT_CASES.md) found that a human fighter adds **3.1–3.7 ms/s** of the database thread on top of an AI fighter's 1.4, though it runs no behaviour graph. Before the conclusion "the architecture can't meet the gate" goes to the owner, this note asks whether that cost is inherent or fixable, part by part. It also asks what sets the strict 60 Hz threshold of about 390 ms/s.

> **Update (2026-11-22, measured after cuts 1 and 2, §6).** With `seed-once` and `experience-incremental` on main (`4b9fa89cc`), the gate case still misses strict 60 Hz on every path.
> - **Main as shipped:** 56.5 ticks/s.
> - **Direct with the plausible cuts:** 58.2 ticks/s, 594 ms/s (614 before).
> - **The relay:** 59.6 ticks/s, step p99 19 ms, 0.65% of steps late, 508 ms/s (520 before). One millisecond over the slot.
>
> Cut 3 (b): **56% of a melee's sight tests have exactly the inputs of the viewer's last sweep**, over the 20% bar, but the sight tests are a small part of the sweep. Reusing them saves at most about 16 ms/s for 66 players (estimate).

## Bottom line

**The extra cost is mostly fixable work, not physics, but no single cut is enough.**
- **Where it goes:**
  - about 1.4 is a player's perception sweep, more than half of that heed;
  - about 0.65 is delivery in the tick (copies, earshot, cues), which the relay removes;
  - about 0.8 is blows and witness lines;
  - about 0.6 is input;
  - about 0.5 is views and subscription evaluation.
  - Each part has a cut, and several of the cuts change no rule and nothing a player is told (§2).
- **If every human-specific cost came down to an AI fighter's level, the 216 gate's battle would hold strict 60 Hz on both hosts, with or without the relay.** The 216 gate here is 100 human fighters and 116 walkers.
  - **Arithmetic, dev-box:** the empty world is 34.6 ms/s with 64 residents, about 0.54 each. Then 100 fighters × 1.42 plus 116 walkers × 0.54 gives about **239 ms/s**. Keep the walkers at their measured human cost (1.06 direct, 0.81 relay) and it is still **about 299 direct and 269 relay**.
  - **The measured analogue:** 100 AI fighters with the residents run 187.8 ms/s at 60.0 ticks/s, step p99 18 ms, no late steps.
  - **The limit:** strict 60 Hz held up to about 390 ms/s on the dev-box. X925 scales these by 0.86–0.92, to about 206–275.
- **What the gate actually needs:** cuts of at least about **1.3 ms/s per human fighter beyond the relay** (A100 with the relay: 520 → 390), or **2.2 on the direct path** (614 → 390), on the dev-box.
  - On X925 (scaled demand 526 × 0.86–0.92 with the relay, 637 × 0.86–0.92 direct) the need is about **0.6–0.9** beyond the relay, or **1.6–2.0** direct.
  - The cuts in §2 that change no rule add up to about **0.6–0.9 beyond the relay** (estimate). That is about X925's need, at the edge, and not the dev-box's.
  - The rest needs either cuts that change what a player is told or when rules fire, or work off the thread (stage 2's perception).
- **The strict threshold is the tick's own spread, and it applies to AI ticks too.**
  - AI-only battles of 280 and 340 fighters, with no player transactions at all, miss strict 60 Hz at 427 and 487 ms/s: 59.6 and 58.8 ticks/s.
  - Scheduling, queueing and commits are small. The tick waits 0.05–0.1 ms in the queue, and its start delay p99 is about 5 ms throughout.
  - Late steps follow the tick's mean length, because the tick's p99 is about twice its median.
  - Spreading the player sweeps evenly over ticks (no rule change) cuts the long ticks by about a third at B100 with the relay. That is worth about 5% of threshold (estimate, §4).

## 1. Method

- **Runs:** the battle fixture of BATTLE_CONTRACT_CASES (Cullet plaza, 200 fighters within 7 m, 16 spectators on the 26–32 m ring, the plausible cuts, heed at 16, warm, `performance` governor).
- **The parts:**
  - the existing L1 runs (`cL1-*`) for the tick's phases per tick;
  - new **L2** runs (`profile_detail`, every detail span): B0 and B50 direct, and B50 with the relay, one run each.
  - **What a human fighter adds** = (B50 − B0) / 50, given two ways, since L2 runs slower (54.9 against 59.8 ticks/s): per second as measured (a low bound for per-tick work), and per tick at 60 Hz (a high bound).
- **New spans:** the input reducers had no span of their own. `join` (with `join.spawn`, `join.graph`, `join.kit`, `join.sweep`), `use_skill`, `release_skill` and `human_move` now have one, on the measuring branch, logged only while profiling.
- **Known answers:**
  - **Spans off at L0:** the same B50 on the new module, one run, measured 544 ms/s at 59.0 ticks/s, against series c's 559–581 at 58.5. That is within the arm's run-to-run spread; the code is unchanged at L0.
  - **Spans against the server's own transaction CPU:** `join` 7.9 against 8.66 ms per call; `use_skill` 0.26 against 0.50; `human_move` about 0.01 against 0.033. For small inputs, about half of the transaction is outside the module's code: the host's call and the commit of the rows written.
- **The threshold:** the server's own histograms for every L0 run of BATTLE_CONTRACT_CASES, with no new run:
  - the tick's scheduled-start delay;
  - each reducer's queue wait;
  - the tick's transaction CPU;
  - the tick with its subscription evaluation.

  Plus AI-only battles of 280 and 340 fighters (two runs each, L0) and the per-tick L1 logs.
- **Host:** the governor and warm poller as before. The other projects' runner listeners were sampled; no run in this set went over the mark.

## 2. The parts, per human fighter (ms/s of the database thread)

### 2.1 Perception: +1.37 per second, +1.53 per tick (`tick.perception`)

| Sub-part (L2 span) | Per s | Per tick at 60 Hz |
|---|---:|---:|
| Heed's features (`attend.features`) | 0.53 | 0.59 |
| Heed's rules (`attend.rules`) | 0.22 | 0.24 |
| Sight tests on every candidate (`sight.player_candidates`; about 113 in sight in a melee) | 0.24 | 0.27 |
| Projections of newcomers (`sweep.project`) | 0.18 | 0.20 |
| Hearing (every 5th sweep), the perceived set's rows, the scene, setup, crowd rows | 0.24 in all | 0.27 |

- **What it does.** Five times a second, for each player:
  - it gathers every creature within reach and runs the sight rule on each (facing, light, a clear line);
  - it ranks all those seen with heed (features per creature, then the rules) and keeps up to 16;
  - it writes crowd rows for the unattended;
  - it updates the perceived set;
  - it projects each newcomer through the regard law (its name or label as this viewer knows it).
- **Why a human pays more than an AI.** An AI fighter's perception is lazy: its graph asks for "the nearest person", which tests sight in distance order and stops at the first seen. A scene read costs about 7 µs per evaluation, about 0.13 ms/s per AI fighter in this battle. A player's sweep is exhaustive and eager, because the player is shown a set and its names, not one answer.
- **Cuts:**
  - **Heed incrementally (no rule change; bounded at 0.75–0.83).** Re-rank only when a member's features changed, or keep the last ranking's features for members whose inputs did not move. The same set comes out. Most of a melee's members move every sweep, though, so the saving is bounded, not measured: plausibly a third to a half, **about 0.25–0.4**.
  - **Re-test the unattended less often (`attend_throng_sight_ms`, already a prototype law on the E2 branch).**
    - The unattended are not shown, so a 400–600 ms throng interval changes only how soon one of them can be attended (a timing change in heed's input, not in what is shown at once).
    - Bounded by the sight tests' **0.24–0.27**; plausibly half.
  - **Projections:** already memoised per tick; what remains follows the set's churn (about 6 newcomers a second). Heed's holds already limit churn. No further cut proposed.
  - **Crowd rows:** about 23 rows a second per human fighter in a melee. Their tick work is small (0.03); their delivery cost is in subscription evaluation (§2.5). Turning them off changes what a player is told (no crowd summary).
  - **Stage 2:** perception off the thread takes the whole of it, plus about 0.2 for applying sets (PERCEPTION_OFF_THREAD). That changes where the rules run, not the rules: the owner's call.

### 2.2 Delivery in the tick: +0.51–0.58 (`tick.frames`), +0.12 cues

- **The parts:** copies of the creatures in the set (`frame.one` 0.35–0.39), earshot (0.15–0.17), the scene (0.11–0.13) and lines (0.07).
- **Why a human pays more:** an AI has no client.
- **Cut: the relay, measured.** It removes copies, cues, the feed and hearing: the human fighter's swap cost goes from 3.68 to 3.14 at B50 (BATTLE_CONTRACT_CASES §2.3). It changes nothing a player is told; it moves delivery.

### 2.3 Blows and witness lines: about +0.8

| Sub-part | Per s | Per tick at 60 Hz |
|---|---:|---:|
| A blow's damage, its onlookers and percepts (`act.damage`, in `tick.activity`) | 0.37 | 0.48 |
| of which: finding the blow's onlookers by sight (`fold.blow`) | 0.22 | 0.29 |
| The onlookers' folded lines (`fold.flush`, in `tick.fold`) | 0.24 | 0.30 |
| of which: each onlooker's names for the fighters (`fold.labels`) | 0.17 | 0.21 |
| Wakes | 0.07 | 0.19 |

- **What it does.** Each blow is written once with everyone who could see it (the sight rule for every mind near it). Each onlooker then gets one line per window of what it saw, with the fighters named as that onlooker knows them.
- **Why a human pays more.**
  - **Players are onlookers who get lines.** In a melee a human fighter witnesses nearly every blow: per blow, `fold.blow` costs 0.40 ms at B0, 0.57 at B100 and 0.66 at B200.
  - **Partly the workload, not humanness.** GATE_216's driver strikes about 1.6 times as often as the AI's fight graph: blows rise from 57/s at B0 to 73/s at B100, so about 0.45 blows/s per human fighter against 0.29 per AI. Human fighters also fall twice as often: 1.4 against 0.7 a minute.
- **Cuts:**
  - **Names from the projections already written (no rule change; bounded at 0.17–0.21).** An onlooker's `projected` row already holds its label for every creature in its set. Labels for fighters outside the set still need the regard law. Plausibly **0.1–0.15**.
  - **Onlookers from the perceived sets (no rule change for players, bounded at 0.22–0.29).** For player onlookers, `fold.blow`'s sight test could use the sight result of the onlooker's last sweep (within 200 ms) instead of testing again. It changes when a blow at the edge of sight counts as seen, by up to one sweep. Plausibly half: **0.1–0.15**.
  - **Fewer lines for a melee's players (changes what a player is told).** A player fighting in the melee already gets every blow of its attended set as events (the feed or the relay's events), so its lines repeat them. Folding only blows outside its attended set would remove most of the flush. That is a presentation decision.

### 2.4 Input: about 0.6 (0.63 at L0)

| Reducer | Calls per second per human fighter | Transaction CPU per call | Per human fighter |
|---|---:|---:|---:|
| `human_move` | 2.2 | 0.033 ms | 0.07 |
| `use_skill` (strike, guard, dodge) | 0.6 | 0.50 ms (module code 0.26) | 0.32 |
| `release_skill` | 0.14 | 0.39 ms | 0.05 |
| `join` (rejoin after death) | 0.023 | **8.66 ms** | 0.20 |

- **The rejoin's 8.7 ms is in three parts:**
  - the newcomer's kit, 4.3 ms;
  - the spawn, 2.6 ms (not split further: no detail span inside);
  - the first sweep, 0.9 ms;
  - setting its graph is negligible.

  **The kit parses the whole seed's JSON on every join** (`seed::newcomer_kit`: `serde_json::from_str::<Seed>(&active())`) to read its `newcomer` items and techniques. Cullet's seed is tens of thousands of lines.
  - **Cut (no rule change):** parse the newcomer section once per instance and keep it. That should save most of the 4.3 ms (bounded: the parse's share of the kit span is not split), and halve the rejoin's spike.
  - **Spreading the rest over ticks** (the first sweep after the join, as the scheduled sweep does) changes what a newcomer sees in its first 200 ms: a rule-visible change, small.
- **`use_skill`:** half its transaction is outside the module's code. That is the host's call and the commit of its rows (`skill_use`, the activity, readiness). The module's half is the act machinery's checks. No cut proposed; it is the price of an authoritative move.
- **Input waits behind ticks** (2.5–3.4 ms queue wait on average), never the reverse (the tick waits 0.05–0.1 ms). A 9 ms rejoin beside a 9 ms tick can still push the next step late.

### 2.5 Views and subscription evaluation: about 0.5

- **Views, about 0.33:** `my_experience` 0.17 (about 0.9 re-runs a second per human fighter, each about 0.19 ms, the whole window); `my_skill_uses` 0.07; `my_vitals` 0.04; `my_readiness` and `my_fighter` 0.02 each.
- **Subscription evaluation:** 0.15–0.22 direct, 0.05–0.07 with the relay.
- **Why a human pays more:** an AI has no subscriptions.
- **Cut (no rule change):** `my_experience` as rows the client reads incrementally (an event table, or a table with row-level security) instead of a per-user view re-run whole. It saves most of 0.17. It is a client and schema change, verified through verify-client.

### 2.6 What goes: the AI's own evaluation, −0.26 to −0.57

A human fighter replaces an AI fighter's combat evaluations (`eval.combat`, about 0.9 ms/s per AI fighter at 15 Hz). This is the "replacement" the framing expected. It is real, but small against the rest.

## 3. The 100-human gate case, cut by cut (dev-box, estimates on measured parts)

| Step | ms/s per human fighter over an AI's | A100 demand at 60 Hz, ms/s | Holds strict (≤ about 390)? |
|---|---:|---:|---|
| Direct, measured | 3.68 (B50) | 637 | no |
| Relay alone, measured | 3.14 | 526 | no |
| Relay plus the cuts that change no rule (rejoin parse, incremental heed, names from projections, onlookers from the sets, incremental `my_experience`): about 0.6–0.9 (estimate) | about 2.2–2.5 | about 435–465 | no (X925: about 375–430, at the edge) |
| … plus stage 2 (perception off the thread, applying sets 0.2) | about 1.3–1.5 | about 340–365 | **yes** (X925: about 290–335) |
| Every human-specific cost at an AI's level | 0 | about 239–269 | yes |

- The A100 demand line takes 526 (relay) and subtracts 100 × the cut, since the 116 walkers are unchanged. For the stage 2 line, the perception share (1.37–1.53) plus heed's cut is replaced by 0.2.
- These are estimates on measured parts; the cuts are not built.

## 4. What sets the strict 60 Hz threshold

- **Not scheduling, queueing or commits.** In every arm of BATTLE_CONTRACT_CASES:
  - the tick's scheduled-start delay has a mean of 1.2–2.1 ms and a p99 of about 5 ms (the histogram's bucket edge), in holding and narrowly missing arms alike;
  - the tick waits 0.02–0.26 ms in the queue;
  - its subscription evaluation is a few percent of its time (ticks over 10 ms: 15.6% with transaction CPU alone, 16.5% with evaluation, at B50 with the relay).
- **The tick's own spread.** Late steps follow the tick's mean length, because its p99 is about twice its median:
  - B100 with the relay (L1): body p50 9.5, p90 14.4, p99 19.6 ms;
  - B0: p50 6.0, p99 11.1.

  The long ticks are long in the phases whose work comes in bursts:
  - activities coming due, blows landing: +3.2 ms over the median in the long ticks;
  - perception: +1.6;
  - wakes: +1.5;
  - witness lines: +0.8.
- **Not specific to human fighters.** AI-only battles, with no player transactions:

  | AI fighters | ms/s | Ticks/s | Steps later than 25 ms | Step p99 | Ticks over 10 ms (CPU) |
  |---:|---:|---:|---:|---:|---:|
  | 200 | 319 | 60.0 | 0.04% | 18 | 0.9% |
  | 280 | 427 | 59.6 | 0.6% | 20 | 9.0% |
  | 340 | 487 | 58.8 | 1.8% | 30 | 20.7% |

  At equal mean tick (8.2–8.3 ms), 340 AI fighters and B50 have about the same share of long ticks (20–21%) and late steps (1.6–1.8%). Two runs each for the AI arms; the ticks over 10 ms are the first run's.
- **Spreading the work, costed by replaying measured ticks** (L1, each phase replaced by its mean per tick; the rest unchanged):

  | B100 with the relay, ticks over 14 ms | Share |
  |---|---:|
  | As measured | 11.7% |
  | Perception spread evenly | 8.3% |
  | Perception and witness lines spread evenly | 7.4% |
  | Activities spread evenly (moves timed by rules: changes when they land) | 5.5% |

  - **Perception's spread is a fixable artefact.** Each player's sweep phase comes from its id (`(id × 37) mod groups`), so the number of sweeps in a tick varies. Assigning phases by load instead changes no rule.
  - **It moves the threshold only a little,** perhaps 390 → about 410 ms/s (estimate); the mean decides.
  - **Activities and wakes come when the rules say;** spreading them changes timing.
- **The 600 ms/s budget of the earlier notes** would need the tick's p99 within one slot at a mean of 10 ms per tick. That holds only if the tick's work is nearly constant from tick to tick, which a battle's is not.

## 5. Not measured

- **The cuts themselves:** none is built. §3's figures are estimates on measured parts.
- **The spawn's 2.6 ms and the kit's parse:** the spawn is not split, and the parse's share of the kit is not split.
- **Human fighters on X925:** scaled by the same-code ratio (BATTLE_CONTRACT_CASES §3).
- **A less aggressive human driver:** some of the blow and death costs are the workload's. A real player's rate is not known.
- **L2's own cost:** the L2 runs ran slower (54.9 ticks/s at B50), so the per-part figures are given two ways and are shares, not totals.

## 6. Measured after cuts 1 and 2 (2026-11-22)

**What landed.**
- **Cut 1, `seed-once`** (main `9ed12f51d`): a rejoin's kit no longer parses the seed. `join` costs 5.0–5.4 ms per call against 9.3 before.
- **Cut 2, `experience-incremental`** (main `4b9fa89cc`): a player's lines are rows of `experience_copy`, and `my_experience`'s re-runs are gone. That was 10.4 ms/s in a battle with 66 players, about 0.15 each.
- **Cut 3** (heed re-ranked only on change) waits for heed, which is not on main; (b) below measures main's own sweep instead.

### 6.1 The gate case again

**The fixture:**
- 100 human fighters and 116 walkers, the case of BATTLE_CONTRACT_CASES (A100);
- the players read `experience_copy`, as the shipped client does;
- warm, `performance` governor, L0, two runs per arm, the runner listeners sampled (none over the mark).

**The arms:**
1. **Main as shipped** (`4b9fa89cc`): main has none of the prototype's plausible cuts (heed, the `vf_*` laws).
2. **Direct and relay** on `gate-remeasure` (`6eaf3a53c`): the prototype of BATTLE_CONTRACT_CASES with that main merged in and its bindings regenerated. These two compare with BATTLE_CONTRACT_CASES §2.1.

| Arm | Ticks/s | Step p50 / p99 / max (ms) | Steps later than 25 ms | Grid steps skipped (60 s) | DB thread, ms/s | Before the cuts (BATTLE_CONTRACT_CASES) |
|---|---:|---|---:|---:|---:|---|
| Main as shipped | 56.5 | 17 / 34 / 38–39 | 6.2% | 201–220 | 620 (612–628) | – |
| Direct, the plausible cuts | 58.2 | 17 / 33–34 / 35–36 | 3.1% | 88–126 | 594 (591–597) | 57.7; 33 / 3.8%; 614 |
| **Relay** | **59.6** | 17 / **19** / 35 | **0.65%** | 21–25 | **508** (506–511) | 59.2; 28 / 1.3%; 520 |

- **Strict 60 Hz** (at least 59.9 ticks/s, step p99 within one 16.7 ms slot) **holds on no path.** The relay is the closest: p99 19 ms, one in about 150 steps late.
- **The cuts took about 20 ms/s off the direct arm and 12 off the relay arm.**
- **The fight was real:** about 3 inputs a second per human fighter, and 1.7–2.1 deaths a second among them.
- **The relay arm's privacy:** 0 violations in 233,317 rows of the spectators' and walkers' streams.

### 6.2 Cut 3 (b): sight tests whose inputs did not change

**On main**, a player's sweep runs the sight rule over every candidate (there is no heed). For a sight test (viewer V, candidate C) between V's consecutive sweeps, **"unchanged" means bit-identical inputs:**
- V's eye position, facing and sight distance;
- C's position;
- whether C was already seen (the kept margin);
- the light on C.

Only then would reusing the last answer give the same result. A "loose" count (both moved under 5 cm, facing within 1°, the rest equal) is given for context only.

| Run (B50-like: 200 fighters of which 50 human, 16 spectators; main's laws; L1) | Candidates | Exactly unchanged | Loosely unchanged | Sweeps with V's own eye unchanged |
|---|---:|---:|---:|---:|
| `u-B50-r1` | 4,291,073 | **56.2%** | 56.5% | 70.9% |
| `u-B50-r2` | 4,418,327 | **55.8%** | 56.1% | 70.9% |

- **The share is far above the 20% bar.** In a melee most fighters stand while they wind up, block or recover, and so do the spectators between steps. What moves moves more than 5 cm, so the loose count adds almost nothing.
- **But the sight tests are a small part of the sweep.** At L2 (one run, `u-B50L2-r1`, 66 players):
  - the sweeps cost 98.9 ms/s, of which the sight tests (`sight.player_candidates`) 28.0. That figure includes the counter's own bookkeeping, so it is an upper bound.
  - Projections cost more (38.3 ms/s).
- **So reusing the unchanged 56% saves at most about 16 ms/s for 66 players** at L2, before the cost of keeping each viewer's last inputs. That is about 0.1–0.2 ms/s per player at L0 (estimate).
- It would change no rule: the same function on the same inputs.

**Evidence:**
- Branches `sweep-unchanged` (`f6ce05a8a`: the counter, logged only while profiling) and `gate-remeasure`, never for main.
- Runs: dev-box `.local/gr/runs/` (`series.log`, `tables.json`, `gr_tables.py`); archived to `~/archive/worktree-evidence-20261122/gate-remeasure.tar.zst` (sha256 beside it).

## Evidence

- **Code:** branch `contract-cases`:
  - `87459b903`: the input reducers' spans;
  - the harness, from `122c32f89`.
  - Module `hf-cullet` (`a17f921bbc70`).
- **Runs:** dev-box, worktree `t3-b749c655`, `.local/cc/runs/`:
  - `h-B50-r1`: the known answer;
  - `hL2-B0-r1`, `hL2-B50-r1`, `hL2-B50r-r1`: L2;
  - `h-ai280-r1/r2`, `h-ai340-r1/r2`: the threshold;
  - `cL1-*`: BATTLE_CONTRACT_CASES' L1 runs.
- **Scripts:** `series-h.sh`, `hf_spans.py` (the per-human spans), `cc_ticks.py` (the per-tick phases), `cc_flatten.py` (the replay), `cc_sched.py` (the scheduling histograms, every L0 run), `cc_tables.py`.
- **Archived** to `~/archive/worktree-evidence-20261122/human-fighter-cost.tar.zst` on the dev-box (sha256 beside it).
- **Related:**
  - [BATTLE_CONTRACT_CASES.md](BATTLE_CONTRACT_CASES.md);
  - [PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md);
  - [RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md);
  - [VIEWER_FLOOR.md](VIEWER_FLOOR.md);
  - [PERCEPTION.md](PERCEPTION.md);
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md).
