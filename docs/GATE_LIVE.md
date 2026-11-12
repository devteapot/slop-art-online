# The live gate check (batch `gl1`): run 2026-11-12

Branch `trials-gate-live`, 2026-11-12. This is the live test that [GATE_QUALITY](GATE_QUALITY.md) and idea #3 of [MIND_RESEARCH_IDEAS](MIND_RESEARCH_IDEAS.md) ask for before the rethink gate can be on by default. The general coordinator approved it (about $16). It runs after the earshot stage and the fs1 re-run, so the Cullet runs do not overlap.

**Everything below is fixed before any paid call:** the arms, the measures, the target spread and the stop rule.

## The arms

| Arm (variant) | Gate | Think | Everything else |
|---|---|---|---|
| `gate-off-ds` | off | `deepseek-flash` (effort low) | the `people` mix as `trials.py` runs it: deliberate on stage `deepseek-flash@low`, off stage `glm-flash`; talk `deepseek-flash`; consolidate and reorganize `glm-flash` |
| `gate-jev-ds` | `LIVING_RETHINK=jev`: `rethink.json` as shipped (Jev `jev-1.14.0`, `proceed_above` 0.3, `max_hold_s` 600) | the same | the same |

- **Think on DeepSeek in both arms.** GATE_QUALITY found it the better think model and the one to pair with the gate. The arms differ only in `LIVING_RETHINK`.
- **The switches, recorded per instance** (`mind-env.json`, `models.json`):
  - `LIVING_RETHINK`;
  - `LIVING_FRAME` unset (`character`);
  - level of detail, lessons, projects and the player frame off;
  - world laws as `strangers-control` (main's);
  - the `people` mix's routing with the change above.
  - `trials.py` drops `groups`, `assign`, `rotate` and `stages`, as in every trial batch.

## The world: Cullet, stage 2b's script (chosen over the hamlet)

The trial file is `living/trials/gate-live.json`, which extends `strangers-2b-c`.
- **Script:** the newcomer stands 5 minutes at the arrival point from 360 s, walks the Strand past the Fish Steps, and then stands 5 minutes at the densest group.
- **Minds:** 63, all residents.
- **Length:** 20 minutes, which is 21 resident-hours a run.

**Why Cullet, not the hamlet.**
- **It is where the gate's question is.** The strangers measures (with the walk) are about who answers a newcomer and how soon. That is exactly what a held deliberation could delay: a first sight, a cue, a line to someone.
- **It is cheap enough to replicate.** 63 minds for 20 minutes is about $2.8 a run.
- **The hamlet's births measures need 6-hour runs.** bi1 ran 360 minutes. That is about $9 a run at 12 thinkers, so it would allow one run per arm, and it is a different question.

**Replicates:** 3 per arm, 6 runs, `--parallel 3`, as two waves of about 25 minutes. The newcomer's stand, walk and second stand are the same in every run.

## Cost (estimate, from st2b's journals)

| Item | Per run | Runs | Total |
|---|---:|---:|---:|
| `gate-off-ds`: st2b's C arm ($2.49) with think moved from GLM ($0.36) to DeepSeek ($0.0019 a think, 334 thinks) | $2.77 | 3 | $8.3 |
| `gate-jev-ds`: the same, less 15–25% of think and compile (58% of spend), plus Jev's questions (price not committed) | not committed | 3 | not committed |
| **Total** | | | **not committed** (the `gate-off-ds` arm: $8.3) |

Judging (below) uses fresh Claude subagents, so it costs no API money.

## Measures (per instance and per arm; `gate_quality.py live` and `held`)

1. **Dollars per resident-hour:** every journaled call, the gate's own Jev calls included, over 63 minds × minutes run ÷ 60.
2. **Deliberations per resident-hour:** think calls.
3. **The gate's verdicts:**
   - holds, rethinks, urgents, fallbacks;
   - hold episodes, their length (p50, p90), and what released them (a yes, an urgent merge, `max_hold_s`, the run's end).
4. **Reaction to a failed act:** from any resident's "What you had decided did not work out" (`experiences_all`) to that resident's next deliberation (`thoughts_all`), p50, p90, and how many had none within 10 minutes.
5. **Held triggers judged as delayed:**
   - **Sample:** 80 hold episodes from the gated arm (`gate_quality.py held --n 80`), blind, by two fresh Claude subagents, 40 each plus 10 judged by both.
   - **Rubric:** [DELAYED.md](../living/tools/gate_quality_judge/DELAYED.md). The item is the state at the first hold, how long it was held and why it was let go, and what the deliberation that finally ran did and how long after.
   - **Labels:** what the moment needed (`nothing`, `could_wait`, `soon`, `now`); what waiting cost (`none`, `small`, `harmful`); and whether the later deliberation addressed it.
6. **Outcome measures:** stage 2b's strangers measures, `arrive_spread.py --strangers` with the walk counted in range (docs/STRANGERS.md, "Target spread"):
   - residents in range;
   - the four classes (asks, approaches silently, notices inwardly, unaware), and tells others;
   - time from the join to the first heard line;
   - `converge_60s` and `together_4m`;
   - re-asks and unheard lines;
   - the guards: false replies, repeated lines, and talk that led to something, net of placebo.
   - `plans_other` (ar2's contact measure).

## Target spread (written before any run)

| Measure | `gate-off-ds` expected | `gate-jev-ds` in shape if |
|---|---|---|
| $ per resident-hour | about $0.13 (st2b C: $0.118 on GLM think) | its mean is below the off arm's lowest run, by 8% or more |
| deliberations per resident-hour | about 21 (st2b C: 20.7, 20.9) | 15–35% fewer than the off arm's mean (the all-minds replay held 27%) |
| hold episodes judged `harmful` | – | at most 10% of the 80; **out of shape above 20%** |
| holds where the moment needed `now` | – | at most 10%, and each one released within 60 s or by an urgent merge |
| reaction to a failed act, p50 | about 45–60 s (st2b C: 61, 44) | within the off arm's spread, or at most 30 s longer |
| failed acts with no deliberation within 10 min | st2b C: 9 and 13 a run | at most the off arm's highest run plus 5 |
| strangers classes, first heard line, `together_4m`, `converge_60s` | the C bands of docs/STRANGERS.md | every run inside the same bands as the off arm's runs, or within the off arm's spread |
| guards (false replies, repeated lines, talk that led to something) | the off arm's own spread | within the off arm's spread |

**How it is read.**
- **The pass reading** is idea #3's: cost down by more than the spread, with no guard, reaction time or strangers measure worse than the off arm's spread.
- **Three replicates are few.** A single run outside the spread is reported, not read as a failure. Two of three outside is a failure of that measure.
- **The owner judges from the inspector pages,** one per arm.

## Stop rule

- **Spend.** `gate_quality.py watch gl1 --stop-usd 18 --pid <runner>` reads the live journals every 30 s. Past **$18** it sends SIGINT to `trials.py run`, which stops every instance and keeps the evidence. The worlds are paused before any deletion (`trials.py clean`, since fix-trials-pause).
- **Runaway.** `trials.py`'s runaway watchdog stops an instance whose calls loop. A backstop of 30 million tokens an instance stops a run at about twice st2b's size (`budget.tokens`). A run stopped either way is reported as it is and is not re-run without approval.
- **A failing gate.** If more than 20% of the gated arm's verdicts are `fallback` (Jev errors or timeouts), stop the batch: the arm would be measuring the gate's outage, not the gate.
- **Fixed in advance.** No change to the arms, the measures or this spread after the first paid call.

## Commands (paid; only once the earshot stage and the fs1 re-run are done)

```bash
# in ~/dev/slop-gate-live (trials-gate-live); .env copied in (mode 600) and removed after
python3 living/tools/trials.py build gate-live
python3 living/tools/trials.py run --batch gl1 gate-live --variants gate-off-ds,gate-jev-ds --replicates 3 --parallel 3 &
python3 living/tools/gate_quality.py watch gl1 --root . --stop-usd 18 --pid $!
python3 living/tools/gate_quality.py live .local/living/trials/gl1
python3 living/tools/gate_quality.py held .local/living/trials/gl1 .local/living/trials/gl1/held --n 80
python3 living/tools/arrive_spread.py --strangers --control gate-live:gate-off-ds .local/living/trials/gl1
python3 living/tools/trials.py clean --batch gl1                            # pauses each world before deleting it
```

## Results (batch `gl1`, 2026-11-12 18:21–19:02)

**Run:**
- **Build:** main `c13a31df`, plus `gate_quality.py`'s tick context. Module and mind rebuilt with `trials.py build gate-live`.
- **Script:** as prepared above, 3 runs per arm, `--parallel 3`. The three control runs went first (18:21–18:42) and the three gated runs second (18:42–19:02), so the arms ran in different 20-minute windows of provider load.
- **Every run stopped by duration,** with no runaway, no outage, one mind start and 63 minds (21.0–21.1 resident-hours).
- **Switches (`mind-env.json`, `models.json`):**
  - `LIVING_RETHINK=jev` in `gate-jev-ds` only;
  - concurrency 64; no world laws beyond main's;
  - the `people` mix with think on `deepseek-flash`;
  - deliberate on stage `deepseek-flash@low`, off stage `glm-flash`; talk `deepseek-flash`; consolidate, reorganize and the rest `glm-flash`.
- **Spend:** the providers' calls (DeepSeek, GLM) cost **$15.88** (control $8.36, gated $7.52). The gate's own Jev questions are on top. They are priced from the local prices file (every Jev call had a known cost, none unknown) and are not published (docs/STORE.md, Model terms).
- **The stop rule did not fire:** the spend stayed under $18, and 0 of the gate's 1,395 verdicts were `fallback`.

### Against the target spread

| Measure | `gate-off-ds` (r1/r2/r3) | `gate-jev-ds` (r1/r2/r3) | Target for the gated arm | In shape? |
|---|---|---|---|---|
| $ per resident-hour, providers' calls | 0.133 / 0.134 / 0.131 | 0.112 / 0.126 / 0.119 | mean below the off arm's lowest run by ≥ 8% | providers alone: 9.1% below (10.2% below the off mean). **With Jev's questions, as the measure is defined, it does not clear the 8% line.** That figure is in the local record. **Borderline: not met.** |
| deliberations per resident-hour | 20.45 / 20.12 / 20.04 | 16.42 / 18.65 / 18.03 | 15–35% fewer | **12.4% fewer: not met** |
| hold episodes judged `harmful` (80 sampled of 139) | – | 6 (7.5%) | ≤ 10%; out of shape above 20% | **met** |
| holds where the moment needed `now` | – | 24 (30%); 14 released within 60 s or by an urgent merge, 10 held 68–384 s | ≤ 10%, each released within 60 s or by an urgent merge | **not met** |
| reaction to a failed act, p50 (s) | 64.4 / 65.4 / 67.3 | 51.8 / 52.6 / 32.7 | within the off spread, or ≤ 30 s longer | **met (faster)** |
| failed acts with no deliberation within 10 min | 14 / 13 / 16 | 11 / 19 / 13 | ≤ the off arm's highest + 5 (21) | **met** |
| strangers classes, `together_4m`, `converge_60s` | asks 1/3/3, approaches 2/1/0, inward 0/0/1, unaware 19/20/17, tells 0/1/0; `together_4m` 0/1/1; `converge_60s` 1/2/1 | asks 2/1/2, approaches 5/2/0, inward 0/1/0, unaware 17/15/21, tells 0/0/0; `together_4m` 1/2/2; `converge_60s` 1/2/2 | within the off arm's spread | **met** (every class within the off spread; both arms outside STRANGERS.md's C bands the same way, with unaware high) |
| first heard line to the newcomer (s after the join) | 299 / 611 / 620 | none / none / 478 | within the off arm's spread | **not met**: no heard line in 2 of 3 gated runs (residents with a heard line 0/0/1 against 1/2/3) |
| guards: false replies a minute, repeated lines, talk that led to something (net of placebo) | false 0.45/0.35/0.70; rep 0/0/0.03; led 0.29/0.04/0.72 | false 0.15/0.45/0.15; rep 0.21/0.02/0; led 0.33/0.78/0.25 | within the off spread | **met** (`arrive_spread.py`: within spread on every guard) |

Other columns from `arrive_spread.py` (disjoint from the control's range, `<`):
- **Lines said:** 522–628 against 642–712. The gated arm speaks less.
- **Reused-reason events:** 41–48 against 49–70.
- **Talk turns:** 11.6–13.1 an hour against 13.1–15.6, within spread.

### The gate's behaviour live

- **Verdicts (r1/r2/r3):**

  | Verdict | r1 | r2 | r3 |
  |---|---:|---:|---:|
  | first | 61 | 62 | 62 |
  | rethink | 281 | 326 | 313 |
  | hold | 90 | 64 | 122 |
  | urgent | 4 | 5 | 5 |

- **Holds are 16–28% of the judged (non-first) verdicts,** less than the all-minds replay's 27% at its high end. That is why deliberations fell 12%, not 15–35%.
- **Hold episodes:** 49, 43 and 47.
  - Held p50 65–91 s and p90 277–321 s.
  - Released by a yes 107 times and by an urgent merge once. 31 were still held when their run ended.

### Held triggers judged as delayed (80 episodes, two blind judges)

- **Agreement:** the judges agreed on the cost of waiting in 10 of 10 doubly judged items, and on what the moment needed in 8 of 10.
- **What the held moment needed:**

  | needed | holds |
  |---|---:|
  | nothing | 17 |
  | could wait | 19 |
  | soon | 20 |
  | now | 24 |

- **What waiting cost:**

  | cost of waiting | holds |
  |---|---:|
  | none | 42 |
  | small | 32 |
  | harmful | 6 |

- **Addressed when the deliberation came:** 45 yes, 7 no, 28 not applicable (nothing needed, or nothing ran before the end).
- **The six harmful holds are one pattern: someone was addressing the character, or the body kept failing the same act, and the gate held for 2–6 minutes.**
  - Posy was talking to her at the heaps as her plan ended. She was held 384 s, and Posy went unanswered.
  - Pacing through 29 re-checks while Tilly's question went unanswered (255 s).
  - Juno waiting for him to sit, 281 s.
  - Vessa asking again and again for a successor, 135 s.
  - A missed chance to ask Benedikt before he slept, 262 s.
  - Late for a lesson while pacing, 246 s.
- **The `now` holds held past 60 s** (10 of 24) are the same kinds of moment.

### Ticks (context, not a committed measure)

- **Source.** Read from the authority's own `stats` row in `final.json`. The server's database list no longer shows trial databases: `spacetime list` shows none of `gl1`'s, so a sampler that reads it cannot see them.
- **Ticks in the run:** control 70.6–70.7 thousand, gated 72.1–72.3 thousand (about 59 and 60 a second).
- **Largest gap between ticks:** 22–27 ms against 18–19 ms.
- **Not a gate effect.** The arms ran in different windows, with other sessions' batches on the machine; this says nothing about the gate itself.

### Reading

**Not in shape for default-on.** Four measures were not met:
- the cost saving is borderline once the gate's questions are counted;
- deliberations fell 12%, short of the 15–35% band;
- 30% of holds came at moments that needed an answer now, 10 of them held for over a minute;
- in 2 of 3 gated runs the newcomer never heard a line.

What was met:
- the harmful share (7.5%);
- reaction to failed acts, which was faster;
- the strangers classes and the guards, within the control's spread.

The harm has one shape: someone is waiting on this character (a line *to* it not yet answered, an invitation, a lesson), or the body keeps failing the same act.
- **What the gate's state shows.** It counts lines the character said that went unanswered (`spoke_to_without_answer`). Incoming speech appears only among what was perceived, with nothing marking that someone waits on an answer.
- **What its questions do.** Neither question treats repeated failures of one act as a broken plan before `would_repeat` holds it.

**What a fix would need to do, for the general coordinator and the owner to decide:**
- treat a line addressed to the character, or a wait on it, and a repeated failure of the same act as reasons the gate never holds;
- then run this check again.

That is a change to the gate's urgent rules, not to the world.

### Evidence

`~/dev/slop-gate-live/.local/living/trials/gl1/` (the store's run record for this batch):
- the six instances with their journals and rows;
- `gate-live.json`, with providers' dollars at top level and Jev's under `jev`, which the scrubber drops;
- `arrive-spread.md` and `arrive-spread.json`;
- `held/`: the rubric, the items, the key and the judges' labels.
- **Key fragments:** a grep of the record and the preflight for every 12-character window of the three key values, and for key-like patterns, found **0**.
- **Cleanup:**
  - each instance paused its world before deleting it, at the end of its run (`delete_db`);
  - all six databases answer 404;
  - `trials.py clean` removed the Neo4j minds.
  - `clean` itself lists databases with `spacetime list`, so it would miss a kept trial database now.

## Fake smoke run

Batch `glf2`, 2026-11-12 16:24–16:32:
- **Setup:** `--fake --fake-script living/trials/fake/latency.json`, both arms, 1 replicate, 8 minutes, `--parallel 2`. The tree was 90d917c5 plus this branch. (`glf` was a first try that made no instances, because `--variants` was not given.)
- **Both ran to duration with no runaway,** with 63 minds each (8.4 resident-hours).
- **Routing:** `models.json` routes think to `deepseek-flash` in both arms (journaled as `fake-deepseek-v4-1-flash-1017`), and deliberate as the `people` mix has it.
- **The gated arm's Jev** went to the fake server's `/v1/systemone` (`LIVING_RETHINK_URL` in `mind-env.json`; `trials.py` sets it in fake mode, with a placeholder key). No call left the machine.
- **The gate's verdicts:** 341 decisions (62 first thoughts, 278 holds, 1 urgent). The fake answers every question 0.1, so every non-urgent request is held. They make 36 hold episodes; all were still held when the 8-minute run ended (`max_hold_s` is 600 s).
- **Deliberations per resident-hour:** 17.9 off against 7.5 gated (talk 126 against 73). These are plumbing numbers: the fake's verdicts say nothing about the real gate.
- **The tools:** `gate_quality.py live` and `held` both ran on it; `held` built items from the 36 episodes. With no failed acts in 8 minutes, the reaction measure had nothing to time.
- **Cleanup:** `trials.py clean --batch glf2` paused each world before deleting it. Both databases now answer 404, and the Neo4j minds of both runs were removed.
