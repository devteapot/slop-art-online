# E3: who to track, on recorded scenes

Status: **E3(a) run (free); E3(b) and E3(c) not started.** 2026-11-22, branch `attention-exp` (Spark). It is the Spark's part of docs/ATTENTION_BUDGET.md §8 (v2 with the v2.1 amendments). No paid call has been made. Nothing merges to main until the owner decides on the law.

**The question.** Does a mind-written heed policy (b) or Jev's picks (c) keep track of what the mind later acts on better than the starting heed instinct (a), without missing more first blows and without more flicker?

**The answer from E3(a)**, and why the paid arms should wait:
- **The instinct misses no first blow** in 200 battle moments: 501 first blows, 0 from an unheeded attacker.
- **Its holds cut flicker by 94%** (112 → 6.8 a subject-minute in the battle; 313 → 19 in its dense moments) for about 1.7 points of the acted-on share.
- **The decisive measure has almost no data in these recordings.** Acted-on creatures beyond the 8 nearest: **n = 4**. Deliberate acts naming someone in sight: n = 9. The island's sight (11 m by day, 6 m at night) leaves few in sight (p50 4), and the minds' id-acts mostly name people already out of sight.
- So the frozen decision rule cannot be met by (b) or (c) on this evidence, whatever their quality (§6).

## 1. Frozen inputs

**Evidence.** Copied out of `~/slop-evidence` before reading: `act-trial-20261121.tar.zst` (sha256 `6df580d4cf9611bbbdd81396f37b3dc5b9ae31aa4910e3124eaaa68be542b301`, matching its `.sha256`), extracted under `.local/attention-e3/src/` in this worktree. Nothing in `~/slop-evidence` was opened in place.

| Scene | Runs | What it holds |
|---|---|---|
| Battle | `minds-atb1-off-055246`, `minds-atb1-on-060222` (200 real minds, island seed, 8 minutes; minutes 2 on) | 1 Hz body samples with movement segments (positions replay to any moment), skill uses with windup start and outcome, every think prompt, act attempts |
| Town | all 12 town arms of the act trial (`at1off` … `at11on`, `atfa`, `atfs`; 40 real minds, 30 minutes) | the 40 subjects' positions every 2 s, think prompts, act attempts, households (`cast.json`) |

**States.** `living/tools/attention_e3.py freeze`, seed `attention-e3-2026-11-22`. A state is one subject at the moment of one of its recorded think requests. It is followed from 10 s before to 30 s after (the window is the 30 s after).
- **Battle:** 100 per run, drawn from 2,069 and 2,075 think requests in the measured minutes.
- **Town:** moments with at least 8 people in sight. **The pool holds 39 across all twelve arms, not 100.** The town's sight is 11 m by day and 6 m at night, and only the 40 subjects are sampled, so the shortfall is reported rather than the threshold lowered.

| Frozen item | sha256 |
|---|---|
| The state list (canonical JSON) | `a2ed40db949aea2fb800b8ab3ecac8d53b1c56c3f3ec91f428facb99b018c032` |
| `states.json` as written | see `.local/attention-e3/MANIFEST.sha256` |
| Battle `combat-samples.jsonl.gz` | off `17307c49…bdd`, on `f1394fdc…3b0` (full hashes in the manifest) |

## 2. Method

**What each subject perceives** is rebuilt by `attention_e3.py fields`:
- **Battle:** every body's position from its movement segment, every 0.2 s (a player's sweep cadence).
- **Town:** the 2 s samples.
- **Sight:** the subject's own sight radius from its prompt's scene (11 m by day, 6 m at night), with the sweep's 1 m keep margin. **Distance only: no facing, cover or light.** The town's unsampled residents are missing.
- **Features per creature:**
  - kind (people from `chars.json`; other bodies are `animal`, species unrecorded);
  - distance and closing speed;
  - what it visibly does: its latest skill use, the phase from a 650 ms windup, and whether it is aimed at the subject;
  - when it last hurt or made contact with the subject;
  - whether the subject acts on it;
  - family (town);
  - the stranger bit (battle);
  - time in sight.
- **Events between steps:** each windup aimed at the subject at its start (the policy's to take), and each contact at its outcome. Contact is a blow that landed, or one the subject blocked or dodged; it is forced.

**The selector is the shared code.** `living-mind heed-replay` runs `living_rules::heed` as the authority would: the event pass (`admit`) for each event, then the full pass (`select`) at each step, with each rule's own hold. The capacity is the shipped `heed_capacity(a)` law on the subject's recorded health, energy and stamina (from its prompt), or a fixed number. The ceiling is `heed_ceiling` (16) and the contact window `heed_contact_s` (4 s).

**Arms of E3(a)**, all on the same states:

| Arm | Policy | Capacity |
|---|---|---|
| `a-formula` | the person instinct as seeded (holds on) | the formula (p50 10) |
| `a-formula-noholds` | the same, every `hold_s` taken out | the formula |
| `a-cap8`, `a-cap16` | the instinct | fixed 8, 16 |

## 3. Measures

| Measure | Definition |
|---|---|
| **M1 first blows from the unheeded** | per attacker, its first landed blow in the window: was it heeded when that blow's windup started (heeded already, or taken by the event pass)? Per 100 first blows and per subject-minute. Also later blows landing unheeded, which forced contact should keep at zero. |
| **M2 acted-on share** | of the creatures the subject acted on in the window (its deliberate acts naming an id; its skill uses' targets; in town, its acts naming an id), the share heeded one step before the act. Reported for all, for deliberate acts, for skill uses, and for those beyond the 8 nearest (where arms can differ). |
| **M3 churn** | ids entering or leaving the heeded set per minute; promotions per second |
| **Flicker** | a stint shorter than 3 s, individual or throng, with a change between individual and throng on both sides, the creature in sight throughout. It is what a player sees as a figure popping out of the throng and back. Per subject-minute, and the share of figures that flicker at least once. Coming into or leaving sight is counted apart (sight changes). |
| M4 cost, M5 validity, the blind check | the paid arms only (§5) |

**Known biases.** The recorded minds decided with their prompt's 14 nearest, and their graphs strike the nearest, so M2 favours distance-like policies, (a) included. M1 is counterfactual: who would have been heeded; the recorded blows fell under full perception.

## 4. Results of E3(a)

All windows, the 30 s after each state:

| Arm | Scene | Capacity p50 | Heeded p50 | Promotions /s | Flicker /min | Figures flickering | First blows unheeded | M2 all (n) | M2 beyond 8 nearest (n) |
|---|---|---|---|---|---|---|---|---|---|
| a-formula | battle | 10 | 4.6 | 0.64 | **6.8** | 14.6% | **0 of 501** | 97.7% (1,981) | 0% (4) |
| a-formula-noholds | battle | 10 | 4.6 | 1.75 | **112** | 57.2% | 0 of 501 | 99.4% (1,981) | 25% (4) |
| a-cap8 | battle | 8 | 4.6 | 0.61 | 6.9 | 14.9% | 0 of 501 | 97.5% (1,981) | 0% (4) |
| a-cap16 | battle | 16 | 4.9 | 0.82 | 5.6 | 10.6% | 0 of 501 | 98.4% (1,981) | 0% (4) |
| a-formula | town | 10 | 6.3 | 0.20 | 0.15 | 0.6% | – | 100% (4) | – (0) |
| a-formula-noholds | town | 10 | 6.3 | 0.20 | 0.67 | 2.2% | – | 100% (4) | – (0) |
| a-cap8 | town | 8 | 5.8 | 0.22 | 0.41 | 1.7% | – | 100% (4) | – (0) |
| a-cap16 | town | 16 | 6.4 | 0.18 | 0.0 | 0.0% | – | 100% (4) | – (0) |

- **Sight changes** (coming into or leaving sight) are 115 a subject-minute in the battle and 31 in town in every arm. They are larger than the heed churn, and no heed setting changes them.
- **The battle's 1,913 windups aimed at subjects were all heeded at their start in every arm.** Later blows landing unheeded: 0.

**Dense moments** (more in sight than the capacity), where the choice matters:

| Arm | Battle states | In sight p50 | Promotions /s | Flicker /min | Figures flickering |
|---|---|---|---|---|---|
| a-formula | 67 | 28 | 1.21 | 18.9 | 21.4% |
| a-formula-noholds | 67 | 28 | 4.31 | 313 | 75.5% |
| a-cap8 | 69 | 28 | 1.10 | 18.2 | 21.2% |
| a-cap16 | 48 | 37 | 1.99 | 22.2 | 17.4% |

Town dense moments: 8 (formula), 19 (capacity 8), none at 16; flicker there is 0.4–2.5 a minute.

**Reading.**
- **No first blow from an unheeded attacker, at any capacity from 8 to 16.** In these scenes the instinct's first rule takes every windup aimed at the subject. At most 3 attacks aimed at one fighter at once never exceed even capacity 8. A policy without that rule, or E4's capacity 4 in a swarm, is where M1 can move.
- **Holds are what keep the throng still.**
  - Without them a contested figure flips at the sweep's pace. Dense battle moments churn 4.3 promotions a second; E2's smoke saw about 14 per viewer-second at about 59 in sight.
  - With the instinct's 3 s and 5 s holds, measured from when the rule last took the creature on its merit, flicker falls by 94% overall and 94% in dense moments, and promotions by 63–72%.
  - The cost is 1.7 points of the acted-on share (99.4 → 97.7%): a held figure occasionally keeps a place the graph's next target needed.
- **Capacity 8 against 16 barely matters here.** In-sight p50 is 4 in the battle and 8 in town. A larger capacity gives more places to turn over (16: 0.82 promotions a second against 0.64 at the formula's 10), with slightly fewer figures flickering.
- **M2 cannot discriminate.**
  - Graph skill uses (1,972) target the nearest and are 97–99% heeded in every arm.
  - Deliberate acts naming someone in sight: 9.
  - The beyond-8 subset: 4.

## 5. The paid part: rules frozen before any call

**Decision rules** (from docs/ATTENTION_BUDGET.md §8.1, M1 restated for forced contact). (b) or (c) is preferred over (a) only if all hold:
- its M2 beyond the 8 nearest is higher by at least 5 points (paired by state, exact sign test p < 0.05);
- its M1 (first blows unheeded per 100) is no worse by more than 1;
- its flicker is at most 1.5× (a)'s.

(c) over (b) by the same rules. Otherwise the simpler arm stands. Reported per scene type, with every failed state kept.

**Stop rules** (docs/ATTENTION_BUDGET.md §8.3, unchanged):
1. **Caps:** $12 for E3 in all; (b) $4, (c) $5, $3 reserve only with the general coordinator's word. Each arm stops at its cap less $0.25, everything at $11.50. Spend is read from the journals: (b) priced at the committed prices, (c) at the local prices file's price, never written here.
2. **The guard first:** `act_trial.py watch --ready --pid-file` (main since `21017ee1`), started before the runner and confirmed reading the arm's journal; the launcher holds every paid call until its ready file exists (§7).
3. **No local price, no Jev.**
4. **Failures:** more than 10% of the last 50 calls failing (at least 20) stops the arm.
5. **Jev throughput:** concurrency at most 4; one HTTP 429 or a p95 above 1 s over the last 50 calls pauses (c) for 5 minutes at half concurrency, and a second trip stops it.
6. **Validity of (b):** more than 30% of the first 50 replies failing validation stops (b) until the prompt is fixed on the fake model and the coordinator says go.
7. **Frozen inputs:** the states (hash above), prompts, question templates, models and these rules; any change is a new run needing approval.
8. **Replays only.**
9. **Order:** (a) (done), the free fake-model parts, then the general coordinator's go, (b), then (c).

**Routes.** (b) uses each subject's own recorded compile route: GLM Flash (`zai-glm-5-3-flash`, profile `glm-flash`, effort low) for every subject here. At about 6k prompt and 1k completion tokens a call, 239 calls are well inside $4, so no switch to DeepSeek V4.1 Flash is needed. (c) is TypeSafe `jev-1.14.0`, 5 calls a state (at the moment and every 6 s), about 1,200 calls.

## 6. Recommendation for the general coordinator

**Hold (b) and (c) as frozen.** On these recordings neither can pass the decision rule: its decisive sample is 4 acts. Spending on them would buy validity and cost figures only. Three ways forward, cheapest first:
1. **Run (b) and (c) small, for validity only:** M5, M4 and the blind plausibility check, about 60 states each, with no preference claimed. A few dollars at most.
2. **Record scenes where the choice matters** (recommended).
   - A free fake-model battle and town on Cullet: 48 m day sight, body samples for every creature at 5 Hz.
   - Or a re-recording of the act-trial battle with full samples and a wider sight law.
   - Freeze a new sample from those, then run the paid (b) and (c) on it.
3. **Widen M2** to the people a think reply names (its thought and intentions by id or name). That is more data, but a weaker link to action.

## 7. The free fake-model parts and the guard

*(Filled in below once the (b) and (c) callers are built: prompts only, the fake model through the call path, validation of fake replies, and the guard's dry run.)*

## Files

- **Code (branch `attention-exp`):**
  - `living/rules/src/heed.rs` (the selector, the grammar and validation, the instinct loader, the capacity clamp; unit tests);
  - `living/seeds/heed.json` (the instincts);
  - `living/scripts/skills.rhai` (`heed_capacity(a)`, `heed_knack()`, the laws `heed_on`, `heed_ceiling`, `heed_contact_s`);
  - `living/seeds/worlds/heed/laws.rhai` (the `watch` skill and the `keeping_watch` technique, as an overlay only);
  - `living/mind/src/mind/heed.rs` (`living-mind heed-replay`);
  - `living/tools/attention_e3.py` (freeze, fields, score).
- **Evidence (worktree `.local/attention-e3/`, untracked):** `states.json`, `fields.jsonl`, `picks-<arm>.jsonl`, `score-<arm>.json`, `MANIFEST.sha256`, the extracted copies under `src/`. To be archived to `~/slop-evidence/attention-e3-<date>.tar.zst` with its sha256 when the branch's work ends.
