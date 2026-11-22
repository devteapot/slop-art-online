# E5: who to heed in a real-mind battle (proposal)

Status: **proposal only: design and cost estimate.** 2026-11-22, branch `heed-e4` (Spark). No paid call has been made and no run was started for it; the only work done is the prompt-length and sample-size measurements below, on existing recordings. The general coordinator approved writing it. Nothing merges to main until the owner decides on the heed law. Jev's price is never written here: it is read from the local prices file.

**The question (E3's, where the field is much larger than capacity).** In a fight, does a mind-written heed policy (b) or Jev filling `chosen` (c) keep track of the people a mind thinks about better than the starting heed instinct (a), without missing more first blows, without more flicker and without fighting worse?

**Why a battle, and why now.** E3's recordings could not answer it: the island and Cullet towns gave 4 and 14 named people beyond the 8 nearest (docs/ATTENTION_E3.md §6, §9.1), and today's prompts hide everyone past the 14 nearest. E4 (docs/ATTENTION_E4.md) showed where who-picks matter: in the two-sided melee, the instinct fills a small capacity with one's own side, and side A lost at capacity 4–8. And heed-e4 has built what this needs: with `heed_on`, a mind's scene lists its heeded individuals with no 14-cap and the rest as throng lines.

## 1. The scene change: prompt length

`living/tools/heed_e5_prompts.py` on every recorded think prompt (read-only; copies of the evidence under the session's scratch directory):
- **Battle:** the act trial's two 200-real-mind battles (`act-trial-20261121.tar.zst`, sha256 checked: `minds-atb1-off-055246`, `minds-atb1-on-060222`; island, 11 m day sight; 4,954 think prompts).
- **Town:** E3's real-mind Cullet town (`heedreal1`, 40 minds, 15 minutes; 154 think prompts).

**Method.** Before is each prompt's logged `prompt_tokens`. After is the same prompt with its scene built as the authority builds it under `heed_on`:
- **Who is in sight:** the scene's own list where it holds fewer than 14, which is the authority's sight with cover, walls and gaze. At the cap, the recorded positions within the scene's `sight` are used (distance-only: on the island, without cover or field, that is the authority's rule).
- **Individuals listed:** min(in sight, capacity). Capacity comes from the formula on the subject's own health, energy and stamina in its scene. Each individual costs that scene's own mean creature entry.
- **The throng:** one line per (8-way direction, band under 8 m, under 20 m, farther) group, about 140 characters each, measured on the authority's own scene in verify-core `heed`.
- **Tokens:** each prompt's own characters per token.

| Scene | Capacity | In sight p50 / p95 | Listed before p50 / p95 | Listed after p50 / p95 | Throng lines p50 / p95 | Prompt tokens before p50 / p95 | After p50 / p95 | Change p50 / p95 |
|---|---|---|---|---|---|---|---|---|
| Battle (30% of prompts with more than 14 in sight) | formula (person 10) | 6 / 122 | 6 / 14 | 6 / 10 | 0 / 14 | 4,756 / 6,535 | 4,804 / 6,745 | 0 / **+360** (+5.5%) |
| Battle | formula, base 14 | 6 / 122 | 6 / 14 | 6 / 14 | 0 / 14 | 4,756 / 6,535 | 4,847 / 6,878 | 0 / +507 |
| Battle | fixed 16 | 6 / 122 | 6 / 14 | 6 / 16 | 0 / 14 | 4,756 / 6,535 | 4,856 / 6,993 | 0 / +609 |
| Battle | fixed 32 (ceiling 32) | 6 / 122 | 6 / 14 | 6 / 32 | 0 / 13 | 4,756 / 6,535 | 4,863 / 7,521 | 0 / **+1,210** (+18.5%) |
| Cullet town (real minds) | any of the above | 2 / 7 | 2 / 7 | 2 / 7 | 0 / 0 | 7,382 / 8,277 | unchanged | 0 / 0 |

**Reading.**
- **The median prompt does not change:** most think prompts have fewer in sight than capacity. Only crowded moments grow.
  - At the formula's 10 the 14-cap was the tighter bound, so heed can even shorten a prompt (p5 −169 tokens: 14 entries become 10 plus a few throng lines).
  - At 32 the p95 prompt grows by about 1,200 tokens (+18.5%).
- **In the real Cullet town the authority's own sight is small:** cover, walls and the gaze band leave p50 2 and p95 7 in sight, under any capacity, so heed changes nothing there.
  - **This is a caveat for E3 §9.** Its fields used distance-only sight at 48 m (p50 9–11 in sight). Some of its "named in sight beyond the 8 nearest" may be people the mind could not see. That should be checked against each scene's own list before §9.1's 14 events are used again.
- **A size bound.** The bound on individuals shown is capacity itself: the heed ceiling, 16 by default. No separate prompt cap is proposed: the scene, the graph and memory should agree on one heeded set (docs/ATTENTION_BUDGET.md §7).
  - What can be bounded is the throng: **at most 8 lines**, one per direction, merging the distance bands of a direction beyond the nearest band.
  - That cuts the battle's p95 by about 5–6 lines, roughly 200–250 tokens (estimate). It is a small change to `heed::throng_lines`, to make before E5 if adopted.

## 2. The design

**The fixture: the two-sided melee** (`spawn_battle_sides`, fixed on main as `7a4eb77ed`; casualties confirmed in E4's smoke), not battle_diag's crowd.
- **Its sides make who-picks meaningful:** an enemy and an ally are both "close", and E4 found the instinct spends small capacities on allies.
- **Its field is larger than capacity:** 59 others at the start, most within 15 m.
- **Size: 120 minded fighters** (`spawn_battle_sides(120, 2)`, 60 a side, every fighter a real mind), on Cullet's arrival plaza. Each fighter starts on the fixture's combat graph; its mind may then rewrite it, as in the act trial.
  - Cullet's laws apply (48 m day sight). The fight is on the open plaza, so cover matters little.
- **Length:** 8 minutes a run, no refills. A run ends early if a side is down to 20%.
- **Models:** the `people` mix as the act trial and heed-town: think and compile on GLM Flash at low effort, talk on DeepSeek V4.1 Flash. Main's mind defaults otherwise; switches recorded per run (`mind-env.json`, `world_laws.json`).

**Capacity: record wide, judge narrow.**
- **The recording runs with `heed_on` and every character's capacity fixed at 32** (ceiling 32). Minds then see up to 32 individuals plus the throng: no 14-cap, and a wide view of whom they would think about.
- **The arms are judged at the formula's capacity** (person base 10, and base 14 as a second pass: E4's other formula arm), on the recording's frozen states.
- This is E3's replay method, so every arm is scored on the same moments, paired. A live recording at capacity 10 could not be used: a mind can then name only what (a) already heeded, which is circular.

**The arms.**

| Arm | What | How | Paid |
|---|---|---|---|
| (a) instinct | the person heed instinct as seeded, holds on, smoothed closing (1 s) | `living-mind heed-replay` on the frozen states | free |
| (b) mind-written policy | per state, the subject's own recorded think prompt plus the heed section (`heed_ask.rs`, the `heed` grammar, placeholder examples only: `the_heed_field_names_no_one`); the policy then replayed for the state's 30 s | E3's (b) caller on its recorded route (GLM Flash low) | yes, about 1 call a state |
| (c) Jev `chosen` | the instinct, with `chosen` from TypeSafe `systemone` at the state's moment and every 6 s (5 requests a state), handles not ids, at replay rate only, concurrency ≤ 4 | E3's (c) caller | yes, priced from the local prices file |

A live (b) battle, where minds write their own `"heed"` field in think replies, is **phase 3 below and not part of this ask**. It needs a build first: `mind_update` gains `heed`, the authority keeps `heed_policy` rows, and the prompt gains "# What you keep track of". It is free to build, verify and smoke on the fake model.

## 3. Measures, frozen before any paid call

**States.** Every think request of the recording with a reply and at least 9 others in sight (so that "beyond the 8 nearest" exists), from minute 1 to 30 s before the end. The sample is frozen and hashed before (b) or (c) is called.

| Measure | Definition |
|---|---|
| **M2″ named heeded** (decisive) | of the people a think reply names (`#id`, `say.to`, a full name or a unique first name, `names.json`) who are in the subject's sight at the request: the share each arm heeds at that moment, **beyond the 8 nearest** (decisive) and **beyond capacity** (10th or farther), and overall |
| **M1 first blows from the unheeded** | per attacker, its first blow reaching the subject in the window, whose maker the arm did not heed when its windup began; per 100 first blows. Repeated invisible blows must stay 0 (forced contact) |
| **Flicker** | E3's: stints under 3 s between individual and throng, in sight throughout, per subject-minute |
| **Deaths and blows landed** | per side and run, from the recording. They describe the wide-view fight only; arms are not compared on them in replay (phase 3 does that live) |
| **Cost** | per arm: calls, tokens, spend from the journals, latency |

**Decision rule** (docs/ATTENTION_E3.md §5, unchanged). (b) or (c) is preferred over (a) only if all three hold:
- its M2″ beyond the 8 nearest is higher by at least 5 points (paired by state, exact sign test p < 0.05);
- its M1 is no worse by more than 1 per 100 first blows;
- its flicker is at most 1.5× (a)'s.

(c) over (b) by the same rules. Otherwise the simpler arm stands: (a), then (b), then (c). Base 14 is reported beside base 10 without its own rule.

**The sample the rule needs.** Under the exact sign test at 80% power, a 5-point net gain needs the following, depending on how often the two arms disagree on an event:

| Arms disagree on | Disagreeing events needed | Named-beyond-8 events needed |
|---|---|---|
| 10% of events | 30 | about 300 |
| 15% | 72 | about **480** |
| 25% | 199 | about 800 |

Planning figure: **about 480 named-beyond-8 events, about 400 states.**

**Will the design reach it?** Measured on the act trial's 200-mind battles (`living/tools/heed_e5_named.py`, 4,946 think replies of 396 minds, about 8 measured minutes each):
- 2,579 named people in sight, **455 beyond the 8 nearest**, 397 beyond the 10th and 326 beyond the 14th (named from memory: past the prompt's list);
- about **0.14 beyond-8 events a mind-minute**, under today's 14-cap.

Expected yield:
- **4 runs of 120 minds for 8 minutes** is about 3,840 mind-minutes: **about 540 events** at that rate.
- With the cap lifted to 32 the rate should rise, since minds can see and name more. With sides it may fall, if minds name mostly their attackers.
- **Stop-or-extend rule, frozen now:**
  - After run 2, if fewer than 200 events are counted, run 3 and 4 proceed only with the general coordinator's word.
  - After run 4, if under 300 events, the result is reported as underpowered, with no preference claimed.

## 4. Cost

From the ledgers (committed prices for GLM Flash and DeepSeek V4.1 Flash, `act_trial.py` `PRICES`):

| Source | Minds × minutes | Spend | Per mind-minute |
|---|---|---|---|
| act trial, 200-mind battle (off / on) | 200 × 8 | $6.74 / $6.67 | **$0.0042** |
| act trial, 40-mind towns (30 min) | 40 × 30 | $2.07–2.10 | $0.0017 |
| heed-town (real, Cullet) | 40 × 15 | $0.90 | $0.0015 |
| pool-study (`pool-study-20261121`, e.g. `runs/b128`) | fake-model battles (128–384 minds) | none (fake) | **calls:** 326 a mind-hour in a battle (think 100, deliberate 103), against the act trial's 5.0 a mind-minute (300 an hour): the same call mix, so the act trial's spend per mind-minute carries over |

A battle mind costs about 2.5 times a town mind: it thinks about 1.6 times a minute against 0.17–0.35.

| Part | Expected | Cap (the guard stops at cap less $0.50) |
|---|---|---|
| Phase 0: fake-model smokes of the recording (heed on, capacity 32, 120 minds; prompts, `_stage`, throngs, the guard) and of (b) and (c) through their callers | free | – |
| **Phase 1: the recording**, 4 runs × 120 minds × 8 min, about 3,840 mind-minutes | about **$16** | **$20** |
| **Phase 2 (b)**, about 400 states × 1 call on GLM Flash low (about 7k prompt tokens with the heed section) | about $0.6 | **$2** |
| **Phase 2 (c)**, about 400 states × 5 requests (about 2,000), sized from the local prices file at launch | from the local prices file; E3 found 1,195 requests within $5 | **$5**; the launcher shortens the state list to what fits, and refuses without a local price |
| **This ask** | about **$17 plus (c)** | **$27** |
| Phase 3 (not asked now): live (a) against live (b) at capacity 10, 6 melees each, 60 minds × 6 min | about $18 | $22, separate go after phase 2 |

**Stop rules** (any one stops; nothing is re-run without the general coordinator's word):
1. **The guard first:** `act_trial.py watch --ready --pid-file` on each part's own journal folder, created empty before the runner; the launcher (`heed_e3_launch.py` for (b) and (c); its battle twin for phase 1) holds every paid call until the ready file exists. No ready file: no run (battle-frame's lesson: a watcher given a folder that exited at once left a replay unguarded for 30 s).
2. **Caps** as above, from journal spend: phase 1 at the committed prices; (c) at the local prices file's price, never written down.
3. **Failures:** more than 10% of the last 50 calls (at least 20) stops that part.
4. **Runaway:** 120 battle minds make about 650 calls a minute (pool-study's 326 a mind-hour); phase 1 stops above 1,000 calls a minute over any 2 minutes.
5. **Jev throughput (unknown):**
   - concurrency at most 4;
   - one HTTP 429 or a p95 over 1 s across the last 50 requests pauses (c) for 5 minutes at half concurrency;
   - a second trip stops it.
6. **(b) validity:** over 30% of the first 50 replies failing the heed grammar stops (b) until the section is fixed on the fake model.
7. **Host and measurement rules:**
   - `battle.lock` taken first and held alone while waiting; the trial-activity lock per launch; a quiet start under load 4;
   - a private SpacetimeDB pinned to CPUs 5–9 and 15–19;
   - 40 GB of memory and 45 GB of disk free (the guard's defaults).
8. **Frozen inputs:** the state rule, M2″, the arms' prompts and models, capacities and the decision rule are hashed before the first paid call of phase 2.
9. **Keys:** copied from another trials checkout's `.env` without being shown (mode 600), removed at exit, and absent from every evidence file (scanned).

## 5. What has to be built first (free)

- **A melee trial or battle driver with minds:** `heed_e4_melee.py` gains `--minds` (the mind service for every fighter, the `people` mix), the records E3's freeze reads (every body at 5 Hz with kinds and names, every think request in the journal), and `act_trial.py watch` wiring.
- **`attention_e3.py freeze --melee-run`:** states from the recording, fields from its bodies at the authority's own sight. Where the scene lists fewer than the capacity, its list is the in-sight set (the town caveat of §1).
- **Optionally, the throng bound of §1** (8 lines).
- **For phase 3 only:** the `"heed"` reply field and `heed_policy` rows (a new private table, no new column), verified with verify-minds (a new `heed-reply` case) and verify-client (the table refused to players).

## Sources

- Prompt-length table: `.local/heed-e4/prompts*.json` on heed-e4 (copied with the session's evidence); tool `living/tools/heed_e5_prompts.py`.
- Named counts: `living/tools/heed_e5_named.py` on the act trial's battles.
- Ledgers: `act-trial-20261121.tar.zst` (`.local/acttrial/ledger.json`, `b1/*-report.json`), docs/ATTENTION_E3.md §9.1 for heed-town.
