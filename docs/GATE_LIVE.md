# The live gate check (batch `gl1`): prepared, not run

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
| `gate-jev-ds`: the same, less 15–25% of think and compile (58% of spend), plus Jev at about $0.00006 a question | $2.4–2.5 | 3 | $7.3 |
| **Total** | | | **≈ $15.6** |

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
