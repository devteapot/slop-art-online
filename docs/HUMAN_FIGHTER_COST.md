# What a human fighter costs, and why

Status: **measurement**, 2026-11-22, dev-box. The measuring code is on branch `contract-cases` (`87459b903`), never for main.

[BATTLE_CONTRACT_CASES.md](BATTLE_CONTRACT_CASES.md) found that a human fighter adds **3.1–3.7 ms/s** of the database thread on top of an AI fighter's 1.4, though it runs no behaviour graph. Before the conclusion "the architecture can't meet the gate" goes to the owner, this note asks whether that cost is inherent or fixable, part by part. It also asks what sets the strict 60 Hz threshold of about 390 ms/s.

> **Update (2026-11-22, the gate case re-read at microsecond resolution, §8).** The line was fixed and committed by the Spark before any result was read (`us_reread.py`, `gate216-x925` **`5956bc2da`**): at least 59.9 ticks/s, the p99 of step intervals from `arrival_us` within 17.5 ms, and at most 0.5% over 25 ms.
> - **On the dev-box every arm fails every part of the line:** main as shipped, direct, the relay and every lever arm.
> - **The best is (c):** 59.68 ticks/s, a p99 of 25.2 ms and 1.03% over 25 ms.
> - **What a client sees on the dev-box is wider than the server's 1 ms step times** (an arrival p99 of 25–27 ms against 18–23 on the relay arms). The watching client shares the host with the server, the driven clients and the relay.

> **Update (2026-11-22, the held-back levers measured, §7).** Strict 60 Hz holds with none of them on the relay arm, alone or together.
> - **Re-testing the unheeded every 500 ms** (`attend_throng_sight_ms`), **onlookers from the last sweep's sets** (`onlookers_from_sets`) and **even sweep phases** (`sweep_phase_even`) move the database thread by no more than the runs' own spread (about 506 ± 5 ms/s).
> - **The even phases are the best:** 59.6 ticks/s, step p99 18–19 ms against base's 20 ms. They change no rule.
> - **The projections cut** is at most about 5 ms/s on the relay arm (estimate). The 38 ms/s figure was main without heed.
> - The gate still needs about 506 → 390 ms/s; perception off the thread is the only cut of that size.

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

## 7. The held-back levers on the relay arm, measured (2026-11-22)

**Bottom line: it doesn't.** Strict 60 Hz holds with none of the three levers, alone or together.
- **The best is (c), the even sweep phases.** Ticks/s stay at 59.6, and the step p99 drops from 20 ms to 18–19 ms: one to two milliseconds over the slot.
- **No lever moves the database thread beyond the runs' own spread** (about ±5 ms/s around 506). The gate needs about 506 → 390.
- **The projections cut is not a lever either** (§7.3): at most about 5 ms/s on this arm (estimate).

### 7.1 The arms

**The fixture.** It is §6.1's relay arm:
- 100 human fighters and 116 walkers;
- the players read `experience_copy`;
- warm, `performance` governor, L0, two runs per arm, interleaved.

**The branch.** `gate-remeasure` `d40a876f0` (prototype + main `4b9fa89cc`), module `5535ab5b545c`, never for main.

**Each lever is a value-only law, off by default:**
- **(a)** `attend_throng_sight_ms=500`, the prototype's existing law;
- **(b)** `onlookers_from_sets=true`, new;
- **(c)** `sweep_phase_even=true`, new.

**The gate before the series:**
- det_compare (16 players, 200 fighters, 1,800 ticks, 113 tables) against main `5f3f6f080` was **identical** with every new law off;
- the negative control, `onlookers_from_sets=true`, differed in 1,800 of 1,800 ticks, among them `experience`, `line_seen` and `fight_seen`.

| Arm | Ticks/s | Step p50 / p99 / max (ms) | Steps later than 25 ms | Grid steps skipped (60 s) | DB thread, ms/s |
|---|---:|---|---:|---:|---:|
| Base | 59.58 (59.56–59.59) | 17 / 20 / 34–37 | 0.70% | 25 | 506 (501–511) |
| (a) throng re-tests every 500 ms | 59.45 (59.31–59.58) | 17 / 19–32 / 34–35 | 0.92% | 25–41 | 517 (509–525) |
| (b) onlookers from the sets | 59.47 (59.43–59.51) | 17 / 21–22 / 35–37 | 0.88% | 29–34 | 501 (497–505) |
| **(c) even sweep phases** | **59.59** (59.51–59.68) | 17 / **18–19** / 34–35 | **0.67%** | 19–29 | 508 (502–513) |
| (a) + (b) + (c) | 59.45 (59.44–59.46) | 17 / 21–23 / 35 | 0.90% | 32–33 | 513 (510–515) |

**The strict line** is at least 59.9 ticks/s with step p99 within one 16.7 ms slot. **No arm reaches it.**

**What the fight was in every arm:**
- 296–300 inputs a second;
- 1.9–2.1 deaths a second among the human fighters;
- 0 privacy violations in 113,000–125,000 checked rows per run of the spectators' and walkers' streams.

**Runner listeners.** A run is marked when they average over 0.5 cores or pass 1.5 cores in any 10 s.
- Base r1 averaged 0.52 cores. It was marked and redone as r3, and the table uses r2 and r3.
- **Base r1 itself** (kept in `runs-flagged/`): 59.48 ticks/s, p99 21, 0.87% late, 509 ms/s.
- Every other run stayed under 0.35 cores average and 0.77 in any 10 s.

**Reading the table:**
- **Base** reproduces §6.1: 59.6 ticks/s, p99 19–20 ms, 0.65–0.70% late, 506–508 ms/s.
- **(a) and (b) do not show the work they were estimated to save.**
  - §2.1 and §2.3 estimated (b) at 0.1–0.15 ms/s per human, 10–15 ms/s for 100.
  - (b) measured −5 ms/s, inside the base's range.
  - (a)'s second run was the worst of the series (p99 32 ms, 1.15% late). One run does not show whether that is (a) or chance.
  - These runs are L0, so where the work went is not split.
- **(c) is the only one that moves the spread**, as §4's replay predicted. It changes nothing in the mean, and the threshold estimate there (390 → about 410 ms/s) still leaves the gate about 100 ms/s short.
- **All three together are no better than base.**

### 7.2 What each lever changes in timing

All three act on players only: the sweep and its sets belong to players. No mind is told anything differently, and no AI fighter's perception changes.

| Lever | What changes, and by how much | Visible? | Fairness |
|---|---|---|---|
| (a) `attend_throng_sight_ms=500` | A creature in a player's unheeded crowd keeps its last sight result for up to 500 ms. While that holds, it can stay in the crowd up to 500 ms after it left sight, and heed can pick it from there. | Hardly: the crowd rows are rewritten once a second. A figure may linger up to 0.5 s at the edge of sight. | Players against players: none, since every player has the same delay. Players against minds: a player's crowd lags by up to 0.5 s; a mind's perception does not use a crowd. |
| (b) `onlookers_from_sets=true` | A player onlooker's witness test for a blow uses its sight from its last sweep, up to 200 ms old, instead of now. A blow by or on a creature that came into sight in the last 200 ms is missed. One by a creature that just left is counted. | A witness line at the edge of sight can come or go. | **It matters a little.** Witness lines are learning evidence (`experience`, `line_seen`, `fight_seen`, as det_compare's negative showed). A player onlooker's evidence is up to one sweep behind an AI onlooker's at the same place. |
| (c) `sweep_phase_even=true` | A player's sweep phase is chosen once, at its first sweep: the least-loaded of the 12 groups. Its sweep can start up to 200 ms later than its id would give. Afterwards it is swept every 200 ms as before. | No. | None. Every player is still swept every 200 ms. Each player's phase differs, as it already does by id. |

(c) is the one lever that changes no rule.

### 7.3 The projections cut: a bounded estimate, nothing built

**The 38 ms/s figure was main without heed.** It came from `u-B50L2-r1` (§6.2: main's laws, 66 players, L2), where a player has about 96 creatures in sight per sweep.

**On the relay arm, heed caps that at about 15.** `hL2-B50r-r1` (§1, the relay arm with heed, 66 players, L2) projects in **11.2 ms/s**, not 38.

| L2, 66 players | `sweep.project` | of which the per-row test | writes | the law | building rows | rest | Rows tested per s | Rows projected again per s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Main, no heed (`u-B50L2-r1`) | 38.3 | 16.3 | 9.0 | 3.9 | 3.3 | 5.8 | 31,384 | 1,519 |
| Relay arm, heed (`hL2-B50r-r1`) | 11.2 | 3.5 | 2.9 | 1.3 | 1.2 | 2.3 | 4,918 | 330 |

- "Building rows" is `project.as`. On main, "rest" includes `project.show` (2.0), which the relay does not run.
- On main, the 1,519 rows projected again a second split into:
  - 668 newcomers inserted;
  - 486 updated;
  - **365 that came out the same (24%).**
- On main, the test read health 8,411 times a second.

**What kind of change it is.**
- **It is already incremental.** Under `regard_cache` (on by default), `kept_sweep` projects a row again only when one of its inputs changed:
  - it came into sight;
  - a distance band of the law was crossed;
  - health changed at the precision the law gives;
  - knowledge or a reveal changed;
  - the character's record was marked.

  `regard_cache_check` compares every kept row with a fresh projection.
- **What is left is a polled test of every row on every sweep.** It computes the distance band, reads health where the law shows it, and looks up the marks.

**What a cut could be:**
1. **On-change, exact.** Health writes and the sight pass's own distances mark the rows they affect, and the sweep tests only marked rows.
   - It changes nothing anyone is told: the rows stay equal to a fresh projection, and `regard_cache_check` still proves it.
   - It saves at most the test: 3.5 ms/s for 66 players at L2, so **about 5 for 100** at L2 and less at L0.
   - The "same" re-projections cannot be avoided without projecting.
2. **Fewer tests, a timing change.** Each row is tested every second sweep.
   - It saves about half the test, **about 2–3 ms/s**.
   - A name shown only within a distance, or health drifting between blows (its regeneration), reaches a player up to 200 ms later. Blows still reach at once, through `health_moved`.
   - It affects players only. Minds read the regard law in the rules, not the projected rows.

**So the projections can give at most about 5 ms/s on this arm, about 1% of the tick.** That is not a lever for strict 60 Hz.

### 7.4 Where this leaves the gate

- **The relay arm needs about 506 → 390 ms/s**, a 23% cut, with all of the levers here giving at most about 10 (estimate).
- **§3's remaining step is perception off the database thread** (stage 2, [PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md)). It is the only measured or estimated cut of that size.
- (c) is worth keeping with it: it changes no rule and takes one to two milliseconds off the step p99.

**Evidence:**
- **Branch** `gate-remeasure` `d40a876f0`: the two new laws in `perception.rs`, `fold.rs` and `living/rules`; `living/tools/gate_remeasure/`.
- **Runs:** dev-box `.local/lv/`:
  - `series-lv.sh` and `series-lv-redo.sh`;
  - `runs/` with `series.log`, `tables.json` and `runners.log`;
  - `runs-flagged/lv-base-r1`;
  - det_compare in `det-off/` and `det-negative/`.
- **Archived** to `~/archive/worktree-evidence-20261122/levers.tar.zst` (sha256 beside it).
- **The projections figures** come from the module logs of `u-B50L2-r1` (this note's `gate-remeasure.tar.zst`) and `hL2-B50r-r1` (`human-fighter-cost.tar.zst`). They were summed from the L2 timing-span lines and the `diag` and `sweep kept` lines.

## 8. The gate case re-read at microsecond resolution (2026-11-22)

**The line and the method came first.** Both were committed by the Spark in `living/tools/gate_remeasure/x925/us_reread.py` on branch `gate216-x925`, commit **`5956bc2da`**, before any microsecond result was computed. They are the same for both hosts.

**The line:**
- at least **59.9 ticks/s**;
- the **p99 of step intervals from `arrival_us` within 17.5 ms**: the contract's "approximately 16.7 ms" plus 0.8 ms for measurement and scheduling jitter;
- **at most 0.5% of intervals over 25 ms.**

**The method:**
- Input: the run's `ticks-watch.csv` from `gate-load watch`, with lines `c|u,tick,last_ms,arrival_us`.
- Only the unconfirmed connection's lines (`u`), as `steps_from()` uses.
- Each tick's first arrival inside the run's window (`v0/result.json` `window.t0`/`t1`).
- An interval is `arrival_us(tick + 1) − arrival_us(tick)`, taken only between consecutive ticks.
- The p99 is the nearest rank: the sorted intervals at index `int(0.99 n)`.
- Ticks/s are the run's own (`ticks_per_s`).

**On the dev-box the script ran unmodified** (sha256 `41684705…`) on the archived runs of §6.1 and §7. The run folders already had the layout it expects. All runs were pre-fair-ties (before main `0877fe93a`), on the `performance` governor.

**What it measures:** `arrival_us` is when the watching client received the tick's row. It adds delivery jitter to the tick's own timing, so it measures what a client experiences, which is arguably the right thing for the contract. On the dev-box the watching client runs on the same host as the server, the 216 driven clients and the relay.

| Arm (two runs each) | Ticks/s | Step p50 / p99 / max, `arrival_us` (ms) | Over 25 ms | Against the line |
|---|---:|---|---:|---|
| Main as shipped (§6.1) | 56.33, 56.64 | 17.0–17.2 / 34.1–34.8 / 44–46 | 7.8–8.3% | **fail** |
| Direct, the plausible cuts (§6.1) | 58.51, 57.89 | 16.8–16.9 / 30.4–32.1 / 40–41 | 3.6–4.6% | **fail** |
| Relay (§6.1) | 59.58, 59.64 | 16.7 / 25.9–26.1 / 35 | 1.37% | **fail** |
| Relay base (§7; r2, r3) | 59.56, 59.59 | 16.7 / 25.6–25.7 / 37–38 | 1.23–1.32% | **fail** |
| (a) `attend_throng_sight_ms=500` | 59.58, 59.31 | 16.7–16.9 / 25.6–27.4 / 34–36 | 1.18–2.67% | **fail** |
| (b) `onlookers_from_sets` | 59.51, 59.43 | 16.7–16.8 / 27.0–27.2 / 35–36 | 1.66–2.55% | **fail** |
| (c) `sweep_phase_even` | 59.68, 59.51 | 16.7–16.8 / 25.2–25.7 / 35–36 | 1.03–1.23% | **fail** |
| All three | 59.46, 59.44 | 16.7 / 26.3 / 34–37 | 1.63–1.71% | **fail** |

**Every arm fails every part of the line on the dev-box:**
- **Ticks/s** reached at most 59.68.
- **The arrival p99** is 25–35 ms. It is not near 17.5.
- **Over 25 ms**, the best was 1.03%.
- **Base r1**, kept out for its runner-listener mark, gives the same: 59.48 ticks/s, p99 26.4 ms, 1.49%.

**The microsecond read is wider than §6's and §7's 1 ms read of `last_ms`:**
- On the relay arms, the arrival p99 is 25–27 ms, against 18–23 ms from the server's step times (one run 32).
- The share over 25 ms is about twice as large.

So on the dev-box, a client sees the tick's spread plus about 4–7 ms more at the p99. That is delivery on a host that also runs the server, the driven clients and the relay. Unlike the X925 relay run, which missed only the slot by 1 ms at 1 ms resolution, nothing on the dev-box is close to the line. This does not change §7's bottom line.

**Evidence:**
- `us_reread-devbox.json` (the script's output) and a copy of the script, in `.local/us/`;
- archived to `~/archive/worktree-evidence-20261122/us-reread.tar.zst` (sha256 beside it);
- the runs themselves are §6.1's (`gate-remeasure.tar.zst`) and §7's (`levers.tar.zst`).

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
