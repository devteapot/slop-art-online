# The fast lane's balanced frame, re-judged

Branch `battle-frame` (2026-11-21), from main `bf7f59f5`. It re-asks the question of the Nov 19 frame trial (branch `fast-lane-frame` `6533b711`, never merged; its doc is `docs/FAST_LANE_FRAME.md` on that branch) on today's main, which has since gained fast-dispatch (the mind-side index, no convoy) and `mind_act_replaces`. It follows recommendation (a) of [why the fast lane disengages](FAST_LANE_WHY.md).

**The lane stays off.** The world law `fast_lane_on` stays false, so nothing changes in play. The mind service's `LIVING_FAST_FRAME` is `balanced` by default (since the merge decision of 2026-11-22: any trial or world that turns the lane on gets the less biased frame) or `first` (the frame every earlier trial ran, byte for byte, kept for replays and comparisons). It changes the text of the fast lane's prompt and nothing else: no rule, no table, no reducer, no reply the mind accepts. The runs below were made while `first` was still the default; each named its frame explicitly.

## 1. Why battle acts were refused (act-trial evidence, read only)

The real-model act trial (`act-trial`, base main `7e4c4d1d`; [INPUT_LATENCY.md](INPUT_LATENCY.md#real-model-trial-act-trial-2026-11-21)) had 200 real minds fight for 8 minutes an arm. Most of their deliberate acts were refused at the start. Read here from `~/slop-evidence/act-trial-20261121.tar.zst` (copies extracted elsewhere): every submitted act and its refusal (`journal/outcomes/act_attempts.jsonl`), the compile call that wrote it (`journal/<name>.jsonl`, matched by the `"you"` id in its prompt), the replica's act markers (`act-trace.jsonl`) and the 1 Hz body samples (`combat-samples.jsonl.gz`, positions replayed along each movement segment). Minutes 2–8, as the trial's tables. The scripts are `living/tools/battle_frame_refusals.py`.

**What was refused** (acts reported back at submission; the markers count 668 / 659 "unseen" refusals at act start in the same window, so these records hold 98% of them):

| Refusal | Off arm | On arm |
| --- | ---: | ---: |
| Acts submitted; refused | 1,578; 1,324 | 1,547; 1,286 |
| A `place` the authority does not know ("no place … in sight") | 380 (29%) | 354 (28%) |
| The body busy: a committed move, a cooldown | 322 (24%) | 322 (25%) |
| A creature named by `#id` not in sight | 264 (20%) | 280 (22%) |
| Not an act (a graph node, a `say`, an unknown skill `call`) | 256 (19%) | 250 (19%) |
| Other (heal with no wound, no path, …) | 102 (8%) | 80 (6%) |

**Creatures named by id: a stale view, mostly.** A compile writes its acts from the scene in its prompt. That scene is the deliberation request's (`perceive::scene_json`, taken when the request's last reason arrived), and it waits through the think call's queue and call and the compile's queue and call before any act starts. Fitting each prompt's listed distances to the replayed positions places the moment the scene was true to within 0.05 m (median fit error):

| `#id` refusals | Off | On |
| --- | ---: | ---: |
| Scene age when the act was submitted, p10 / p50 / p90 | 27.9 / 34.5 / 47.1 s | 27.9 / 34.7 / 48.3 s |
| Of the targets listed in the scene: in sight at the scene's moment | 95% | 95% |
| … 4 s later | 78% | 82% |
| … after the think and compile calls' own model time (p50 7.8 / 7.5 s), no queue | 65% | 59% |
| … at act submission | 6% (85% beyond 11 m, 10% dead) | 7% (79% beyond, 15% dead) |

Each refusal, partitioned (off / on):

| Cause | Off | On |
| --- | ---: | ---: |
| **Queue staleness**: in sight after the calls' own model time, gone by submission | 115 (44%) | 106 (38%) |
| **Fight pace**: gone (beyond 11 m or dead) within the calls' own model time | 59 (22%) | 73 (26%) |
| **Naming**: an id not in the scene's list (a structure or resource id 13 / 22; named elsewhere in the prompt 2 / 3; nowhere 11 / 9) | 26 (10%) | 34 (12%) |
| Already gone at the scene's moment | 10 (4%) | 10 (4%) |
| Within 11 m at submission by the replay (a wall, or replay error) | 11 (4%) | 10 (4%) |
| No scene fit (no two listed creatures with replayable positions) | 43 (16%) | 47 (17%) |

The mind service was saturated (160–199 of 200 fighters with a deliberation pending; a median 12 s wait for a slot per call, two calls per decision). That, not the fights' speed, is the largest cause; but even with no queue a quarter of the named targets would be gone.

**Places: a naming mismatch, the largest single cause.** `{"place": name}` resolves only against the character's own remembered `place` rows by exact name (`brain.rs` `place`). The minds wrote "berry bush", "home" (32 / 31; `"home"` is its own target), "house", "boulder", "road", "south", "house at [412,235]", and copied lines of their own "Places you remember" list ("8 tree around [1204, 1764]"), which are not place names either. 90 / 84 of the names hold coordinates. The refusal says "no place … in sight", which is not why it failed. This is not combat-specific and not a framing question.

**Would naming targets relative to the fighter's own perception help?** For the `#id` share (about a fifth of the refusals), a relative target is resolved when the act starts: at submission someone else was within 11 m in 89% / 93% of these refusals (within 2.5 m in 58% / 64%), so `attacker` or `{"nearest": "person"}` would have resolved where the id did not. It would resolve to whoever is nearest or attacking then, which is not the person the mind decided about 35 s before; for the `back_off` acts that make up most of these (207 / 215) that is close to what was meant, for `yield`, `heal` or `give` it is not. "The nearest enemy you see" would not resolve in this battle at all: `relation: enemy` reads the fighter's own relationships, and these fighters know nobody ("People you know: (nobody yet)"). The grammar already offers relative targets, and the slow minds' graphs use them (`attacker`, `nearest`); their one-off acts almost never do (back_off by id 271, by position 17, relative 0 in the off arm). The fast lane does not have this problem: its patches are graphs whose targets resolve on every tick. Recommendation: no target-naming change for the fast lane; for slow acts, the queue and the place naming are the levers, and both are outside this branch.

## 2. The balanced frame

`LIVING_FAST_FRAME=balanced`, the default (`prompts.rs` `FastFrame`, `fast_frame_text`, `FAST_WAYS`; `mind/fast.rs`); `first` gives the earlier frame, and the service refuses to start on any other value. `battle_diag.py --fast-frame first|balanced` (default balanced) always passes it and records `fast_frame` in `diag-head.json`.

**What changes, all in the fast lane's own prompt:**

- **The frame text.** The diff, sentence by sentence (`<` first, `>` balanced):

```text
> Why now is that one event as you perceived it; What has just happened, and How you are now when it is given, are what else you perceive.
< You may rewrite your `combat` branch, rewrite one of the routines listed under Your routines, switch your `combat` branch to one of them, or keep everything as it is.
> Your `combat` branch stays as it is unless you change it.
> You may keep everything as it is, rewrite your `combat` branch, rewrite one of the routines listed under Your routines, or switch your `combat` branch to one of them.
> A change can be one line put first in your `combat` branch, with the lines it has now (under Your top level) written out again beneath it: {"first": [the new line, then your branch's own lines]}.
> Six ways, side by side, each as short as the others; none is the right one, the numbers only show the form, and which fits is yours to judge from who you are and what you perceive:
> - keep it as it is: {"keep": true, "thought": "..."}
> - adjust your timing: {"if": {"doing": {"is": "hostile", "phase": "about to release", "at_me": true}}, "then": {"do": "block"}}
> - change whom you fight: {"if": {"sees": "attacker"}, "then": {"do": "strike", "target": "attacker"}}
> - press an opening: {"if": {"doing": {"phase": "recovering", "within": 2.5}}, "then": {"do": "strike", "target": "attacker", "run": true}}
> - make room and re-enter: {"if": {"count": {"of": "person", "within": 3, "at_least": 3}}, "then": {"do": "back_off", "target": "attacker", "distance": 4}}
> - break contact: {"if": {"health": {"below": 20}}, "then": {"do": "flee", "target": "attacker"}}
  The replies are listed keep, patch, routine, switch (first frame: patch, routine, switch, keep).
```

- **The fight one has is kept by default.** Keeping is the first way and the first reply; each other way is one line put ahead of the branch, which is written out again beneath it. A guarded line stops when its condition stops holding, and the fight beneath runs again (the grammar already says so), so "make room and re-enter" re-enters by construction. Nothing enforces this: a full rewrite, a bare `flee` or a switch install exactly as before (`change_of` is unchanged).
- **The triggering percept is kept apart** from what else is perceived (the second sentence; Why now was already its own section).
- **How you are now**, last in the user prompt: "How your body feels: …", the asker's own felt body in the words its think prompt already has under that heading (`body_text`, the world's `felt` law). Nothing else. **No counts of allies or enemies:** the mind holds no current view of what a fighter sees when a fast request comes (the deliberation row's scene is the request's, up to ~35 s old in a busy battle, §1), and getting one would need a new authority path (the Nov 19 branch's `fast_sight` table) — new knowledge for the mind, which this brief rules out. **No health number:** the felt words are the self-perception the person already has; the Nov 19 trial's numeric health and breath line is left out (whether a breath number invites breath guards stays a separate question).

**Unchanged:** the world's rules text and the graph grammar (the same bytes after the frame, in both frames; checked on 388 saved prompts below), the user prompt's other sections and their order, the route, caps, timeout, the reply forms, the authority. Think, compile, talk and every other purpose are untouched.

**The prompt audit** (`mind/fast.rs` tests):

- `the_balanced_frame_adds_no_tactic_beyond_the_shared_ways`: with the six ways taken out, the balanced frame says none of strike, block, dodge, flee, back off, retreat, escape, run away, safe, survive, danger, should, better, best, must, wise, outrun, miss, attacker, enemy, opening, counter, windup, win, lose, kill, hurt, health, breath, stamina more often than the first frame does. The fight-specific words of the balanced frame are only in the six shared ways.
- `the_balanced_frame_shows_six_ways_alike`: each way is listed; each non-keep line, put ahead of a strike, is a legal graph with no pruning warning and is taken as a `combat` patch; the lines differ in length by under 60 characters; keep comes first among the replies; the fake model still tells it as purpose `fast`.
- `the_balanced_frame_is_the_default_and_the_first_stays_selectable`: unset or empty gives the balanced frame, `first` the first; a misspelt value is refused; the first frame's user prompt is `fast_user` exactly, with no felt body; the balanced one adds only How you are now, and nothing when the body is not known. `fast-replay` needs `--frame` named, and `--frame first` reproduces the first arm's 388 prompts byte for byte.
- `every_speaking_mind_is_told_ids_are_never_spoken` now covers the balanced frame too.

## 3. Replaying saved inputs

`living-mind fast-replay --frame first|balanced --out FILE [--per-actor K] [--limit N] [--route P] [--prompts-only] RUN_DIR…` sends the fast lane's saved requests again. The first arm sends each saved system prompt as it was; the balanced arm swaps only its frame text (each saved prompt must open with this build's first frame, or nothing is replayed), so the world's rules and the grammar are the saved bytes in both arms. The user prompt is the saved one in both arms: a saved request has no felt body, so the replay holds How you are now out of both (the live fights in §4 include it). Calls go through the mind's own `Llm` (the fast route, `Lane::Fast`) and are journaled under `<out>.journal/`; `living/tools/battle_frame_classify.py` classifies the replies as the [WHY tables](FAST_LANE_WHY_TABLES.md) do.

**Inputs.** The Nov 19 replicates' arm B journals (`minds-flb-b-100-1`, `minds-flb-b-200-2`; real DeepSeek V4.1 Flash fast calls, frame 1, no personas, `--keep-plans`): the first two fast requests of each fighter, 388 requests from 258 fighters. Their first fast request is the one whose `combat` branch is surely the fixture's (heal under 50, defend when threatened, strike the nearest person).

### Free part (done)

- **Prompts only.** 388 of 388 first-arm system prompts are byte-identical to the saved ones; the balanced arm differs only in the frame (common prefix 235 characters, common suffix 39,328 of 40,426); the user prompts are identical across arms. The balanced system prompt is 1,246 characters longer (about 310 tokens). Saved user prompts are 10.6k characters at the median.
- **Fake model, through the call path.** 40 requests in each frame through `fake_llm.py` (`fake-models.json`: every profile pointed at the fake): all recognized as purpose `fast`, journaled under the replay's own journal, the scripted "one line ahead of the fight" patch parsed as a `combat` patch whose classification is a guarded `back_off`, fight kept, no unconditioned retreat.
- **What the saved replies (Nov 19, frame 1) were**, classified by the same script, for the paid comparison's reference:

| Saved replies, frame 1 | All 388 | First request per fighter (258) |
| --- | ---: | ---: |
| keep / patch / routine / switch / unusable | 65 / 288 / 8 / 24 / 3 | 40 / 193 / 6 / 17 / 2 |
| Patches with a retreat (`flee`, `back_off`) | 67.7% | 64.2% |
| … an unconditioned retreat | 35.8% | 31.6% |
| … a retreat ahead of the first attack | 50.7% | 46.1% |
| … any attack | 90.3% | 91.2% |
| … an explicit press | 3.8% | 3.6% |
| … the fixture's fight kept whole (all three of its lines) | 8.7% | 10.4% |
| Retreat guards reading stamina / health | 43% / 24% | 40% / 19% |

Free-part evidence: `~/slop-battleframe-work/replay/` (`free-first.jsonl`, `free-balanced.jsonl`: every prompt as it would be sent; `fake-*.jsonl` and their journals; `frame-first.txt`, `frame-balanced.txt`), and §1's per-act tables `diag-minds-atb1-{off,on}-*.json`; to be archived to `~/slop-evidence/battle-frame-20261121.tar.zst` with its SHA-256 when the branch's work ends. Verification: `mind/fast.rs` and `prompts.rs` unit tests (139 pass), verify-minds `fast-lane`, `fast-frame`, `fast-takeover` pass (`minds-bf-215732`, private server `slop-battleframe-20261121`, SpacetimeDB 2.14.1).

### Paid part: results (2026-11-21, 23:15 CET, after the coordinator's go)

**The balanced frame mostly keeps.** On the same 258 inputs it kept the fight as it is three times as often, wrote a retreat a sixth as often, and pressed no less. The effect comes mostly from choosing keep: in a live fight, the lane would mostly leave the fixture's fight alone.

- **Run.** Branch `battle-frame` `1175a611`. DeepSeek V4.1 Flash (the fast route, thinking off), concurrency 6 a frame, both frames at once. **$0.615** by the journals (first $0.319, balanced $0.296); 516 calls, 0 failed. Guards: `act_trial.py watch` per frame on its own journal ($0.75 each). The first watcher was given a directory, not a glob, and exited at once; the replay ran unguarded for about 30 s (it had spent $0.12) until a watcher per process took over.
- **Switches.** Only the frame differs. The first arm's system prompt is the saved bytes; the balanced arm swaps the frame text. Both arms send the saved user prompt (no How you are now). No world and no laws are involved.

Paired by input (`living/tools/battle_frame_pairs.py`). Shares are of all 258 replies. "Only first" and "only balanced" count the inputs where the measure held in one frame and not the other. p is an exact two-sided sign test on those two counts.

| Measure | First | Balanced | Only first | Only balanced | p |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keep reply | 17.1% | 75.2% | 6 | 156 | <0.001 |
| Patch | 76.7% | 20.5% | 150 | 5 | <0.001 |
| Switch or routine | 5.4% | 3.1% | 12 | 6 | 0.24 |
| Kept (keep, or a patch keeping the fixture's fight whole) | 21.3% | 75.2% | 9 | 148 | <0.001 |
| Pressed (an explicit press, or the press way) | 5.0% | 8.1% | 12 | 20 | 0.22 |
| Any retreat | 49.2% | 8.5% | 114 | 9 | <0.001 |
| Unconditioned retreat | 22.1% | 1.6% | 55 | 2 | <0.001 |
| Retreat ahead of the first attack | 38.8% | 6.6% | 91 | 8 | <0.001 |
| Any attack | 70.2% | 19.8% | 140 | 10 | <0.001 |
| Unusable | 0.8% | 1.2% | 2 | 3 | 1.0 |
| Copied an example's numbers | 0.4% | 5.4% | 1 | 14 | 0.001 |

Among the patches only (198 first, 53 balanced):
- Explicit press: 6.6% vs 39.6%.
- Unconditioned retreat: 28.8% vs 7.5%.
- Retreat guards reading stamina: 43% vs 18%. Reading health: 20% vs 59%.
- No balanced patch kept the fixture's three lines exactly: 50 of 53 strike the attacker rather than the nearest person, and 35 of 53 keep heal-self.
- Some keep replies give a thought of wanting to get clear but keep anyway ("I need to get clear of #434 …").

**Rule for the fights:** go if the balanced frame keeps or presses more without more retreats. It did, so the fights below were started.

### Paid part: the plan as written before the go

- **Arms.** The 258 first requests per fighter, each sent once in each frame: 516 calls on DeepSeek V4.1 Flash (the fast route, thinking off), concurrency 8, first and balanced interleaved by input. Model, rules text, grammar and user prompt held fixed; only the frame differs.
- **Measures, per arm and paired by input:** reply kinds; among patches, the fixture's fight kept whole, an unconditioned retreat, a retreat ahead of the first attack, any attack, an explicit press, retreat guards by what they read, lines per patch; which of the six ways a reply takes up (its line's shape in the patch), and whether it copies the example's numbers; replies the live lane could not use. Paired: for each input, kept-fight and unconditioned-retreat in one frame against the other (discordant pairs counted both ways).
- **Cost.** At the Nov 19 rate (13.6k prompt tokens, 10.9k cached; 0.30 / 0.007 / 1.20 USD per million in / cached / out; about 250 tokens out) a call costs about $0.0012: **about $0.65** for the 516 calls. Stop: `act_trial.py watch` on the replay's journal stops the replay by PID at $1.50, or at more than 10% failed calls over 2 minutes.

## 4. Matched fights: results (2026-11-21 23:25 – 2026-11-22 01:17 CET)

**With the balanced frame, the lane no longer makes fighters fight less.** In the clean runs:
- **Contact:** 76% with the balanced frame, against 46% with the first frame and 95% with the lane off.
- **Attacks per contact-minute:** 25.8, against 16.2 with the first frame and 27.7 lane off. Fighters in contact swing as often as with the lane off.
- **Damage:** dealt and taken return most of the way to the lane-off level.
- **Time away:** 24%, against 59% with the first frame.
- **Timed defence:** 54% (67% after a fighter's first patch), against 62% / 72% with the first frame and 52% lane off.
- **Returns after a retreat:** fewer fighters come back within 10 s (39% vs 62%), and the retreat rate is about the same.

The lane with the balanced frame is mostly a lane that keeps: 82–84% of its live replies were keep, against 23–27% with the first frame. It costs about twice as much a run ($0.48–0.53 against $0.27–0.28), because fighters who stay in the fight are hit more and so trigger more fast calls.

- **Runs.** Branch `battle-frame` `1175a611`. `battle_diag.py --battle 100 --walkers 16 --minutes 6 --keep-plans`, island seed 7, site (406.5, 237.5). Private server `slop-battleframe-20261121` (SpacetimeDB 2.14.1) and the runs pinned to CPUs 5–9,15–19. Driven by `series.sh` under one `battle.lock` hold per series, each run started at a 1-minute load under 4 with the merge lock free, launched through `flock -s ~/slop-mq/trial-activity.lock`. Every run held 59.5–60 ticks a second.
- **Switches.** A: `fast_lane_on` false. B1: `fast_lane_on` true with the shipped caps, real fast calls (DeepSeek V4.1 Flash), `LIVING_FAST_FRAME=first`. B2: the same with `LIVING_FAST_FRAME=balanced`. In every arm: all other purposes on the fake model (think 5 s, compile keep), `LIVING_SKILL_TIMINGS` unset (on), every law as shipped on main (`mind_act_replaces` false), no personas ("(no persona yet)").
- **Validity (the load rule, redo above 8 in the run).** The host was busy with other workers' builds that night. Valid: A-1 (max load 6.8), B1-1 (5.1), B1-2 (7.3), B2-2 (4.2), B2-4 (6.2). Over 8: A-2 (9.5 for 40 s), A-3 (30.5), A-4 (23.5), B2-1 (14.9), B2-3 (10.3 for 160 s). The invalid runs are shown, and each lies within the spread of its arm's valid runs. The lane-off arm has one clean run; its four runs agree within 2.6 points of contact.
- **Spend.** $2.59 for the fights (B1 $0.284, $0.273; B2 $0.528, $0.484, $0.528, $0.494). **$3.21 in total** with the replay, of the $8 cap. No guard stopped a run. Every world was deleted, the key copy was removed, and no evidence file holds a key.

| run | contact % | engagements/f-min | attacks/f-min | attacks/contact-min | retreats/f-min | re-engaged 10 s % | timed defence % | after patch % | dmg taken/dealt per f-min | away % | idle or away % | deaths | ticks/s | fast calls | patched fighters |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A-1 | 95.1 | 0.62 | 26.38 | 27.7 | 0.00 | nan | 51.7 | – | 131.9 / 141.6 | 4.4 | 71.7 | 243 | 59.9 | 0 | 0 |
| A-2 | 94.0 | 0.88 | 26.73 | 28.4 | 0.00 | nan | 49.5 | – | 134.4 / 145.3 | 5.4 | 71.7 | 241 | 59.9 | 0 | 0 |
| A-3 | 96.6 | 0.49 | 26.68 | 27.6 | 0.00 | nan | 50.2 | – | 136.0 / 146.9 | 1.6 | 70.8 | 260 | 59.5 | 0 | 0 |
| A-4 | 94.6 | 0.73 | 26.86 | 28.4 | 0.00 | nan | 49.7 | – | 135.1 / 145.9 | 3.7 | 71.2 | 250 | 59.8 | 0 | 0 |
| B1-1 | 49.2 | 2.11 | 7.92 | 16.1 | 0.90 | 65.8 | 60.0 | 70.6 | 27.3 / 29.4 | 53.2 | 88.2 | 33 | 60.0 | 365 | 119 |
| B1-2 | 41.7 | 2.22 | 6.81 | 16.3 | 0.75 | 57.8 | 64.4 | 74.0 | 21.0 / 23.1 | 64.2 | 87.8 | 22 | 60.0 | 353 | 112 |
| B2-1 | 81.4 | 1.55 | 21.18 | 26.0 | 0.78 | 42.9 | 52.1 | 62.1 | 102.8 / 111.2 | 20.1 | 73.2 | 190 | 60.0 | 668 | 81 |
| B2-2 | 75.1 | 1.77 | 19.52 | 26.0 | 0.62 | 43.3 | 53.6 | 66.4 | 93.4 / 101.1 | 25.9 | 76.4 | 160 | 60.0 | 680 | 92 |
| B2-3 | 76.9 | 1.28 | 19.69 | 25.6 | 0.53 | 48.2 | 54.6 | 63.3 | 93.1 / 99.7 | 23.4 | 75.8 | 165 | 60.0 | 676 | 80 |
| B2-4 | 76.3 | 1.32 | 19.51 | 25.6 | 0.86 | 34.3 | 53.9 | 67.2 | 91.2 / 97.2 | 21.3 | 74.8 | 168 | 60.0 | 625 | 84 |

The Nov 19 measures, means of the valid runs:

| Measure | A, lane off (A-1) | B1, first frame (B1-1, B1-2) | B2, balanced (B2-2, B2-4) |
| --- | ---: | ---: | ---: |
| Contact | 95.1% | 45.5% | 75.7% |
| Aimed attacks: attempts per fighter-minute; per contact-minute | 26.4; 27.7 | 7.4; 16.2 | 19.5; 25.8 |
| Retreats per fighter-minute; re-engaged within 10 s | 0; – | 0.83; 61.8% | 0.74; 38.8% |
| Timed defence, sampled blows; after the target's first patch | 51.7%; – | 62.2%; 72.3% | 53.8%; 66.8% |
| Damage taken / dealt per fighter-minute | 131.9 / 141.6 | 24.2 / 26.3 | 92.3 / 99.2 |
| Away; idle or away | 4.4%; 71.7% | 58.7%; 88.0% | 23.6%; 75.6% |
| Deaths in 6 minutes | 243 | 33, 22 | 160, 168 |

What the live fast replies were (from each run's journal):

| Run | Fast calls | Keep | Patch | Switch / routine | Patches with a retreat | … unconditioned | Failed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1-1 | 365 | 23% | 64% | 12% | 47% of calls | 23% | 2% |
| B1-2 | 353 | 27% | 65% | 7% | 48% | 23% | 1% |
| B2-1 | 668 | 83% | 11% | 3% | 8% | 1% | 1% |
| B2-2 | 680 | 83% | 12% | 4% | 9% | 1% | 0% |
| B2-3 | 676 | 84% | 10% | 4% | 7% | 1% | 1% |
| B2-4 | 625 | 82% | 14% | 2% | 11% | 2% | 2% |

**What this does not establish.**
- It does not establish that the balanced lane fights better than no lane. Contact, attacks and damage are still below the lane-off arm. Timed defence is above it by 2 points (14 after the first patch).
- One persona-less fixture, one site, 6-minute runs, two clean runs an arm (one for lane off).
- How you are now (the felt body) was in B2 only, so the live comparison changes frame and felt body together; the replay (§3) changed the frame alone.
- Most of the balanced effect is keeping. Whether the balanced lane is worth its calls over leaving the lane off is a separate design question; the lane stays off.

**The general coordinator's reading (2026-11-22), for the record:** "The balanced lane mostly answers 'keep', which is close to no lane. A whole-graph patch every blow isn't the missing middle layer. The ATTENTION_BUDGET work and prepared routines that run on their own conditions (R3's veterans) are where that question goes next."

**Merged as:** the tooling (`fast-replay`, the refusal and pairing scripts, the spend guard's fixes below) and the option, with `balanced` as the mind's default and `fast_lane_on` off.

Evidence: `~/slop-battleframe-work/fights/` (`chain.log`, per run `*.run`, `*.log`, `*-loads.txt`, `*-spend.jsonl`, `report-all.json`) and the run directories `.local/living/verify/minds-bf-*` in the worktree, to be archived to `~/slop-evidence/battle-frame-20261122.tar.zst` with its SHA-256 when the branch's work ends.

## 5. The spend guard can no longer watch nothing

On step 3 the first guard was given a journal folder instead of its files (`--journal DIR`); `glob` matched the folder, the reader failed on it, and the replay ran unguarded for about 30 s ($0.12). A second slip in the same series: the guard deduplicated journals by file name, so two arms whose journals share names (`Walker1.jsonl`) were counted as one. Both are fixed in `act_trial.py watch`:

- **Refused at start (exit 2, the runner stopped, no ready file):** a `--journal` that is a directory, one that does not name `.jsonl` files, a wildcard outside the file name, or a journal folder that does not exist within `--ready-wait-s`.
- **A handshake before paid calls.** `--ready FILE` is written once every journal folder exists; `--pid-file` lets the guard start before its runner. `living-mind fast-replay` makes no model call until its `--guard-ready` file exists (else it exits; `LIVING_REPLAY_UNGUARDED=1` or `--prompts-only` to run without one), and `battle_diag.py` with real calls refuses to start without `--guard-ready` (or an explicit `--unguarded`, recorded in `diag-head.json`), creating the mind's journal folder (`.local/living/journal/verify-<run>`) and waiting for the ready file before it starts the mind.
- **No silent zero.** With no journal file matched `--first-journal-s` (600 s by default) after the runner is known, the guard stops the runner and exits 3; the ledger records the arm as `unguarded`.
- **Two journals of one name both count:** copies are told apart from other runs' journals by their first call as well as their name.
- `living/tools/act_trial_guard_selftest.py [--mind-bin PATH]` checks each case with a `sleep` as the runner and journals it writes (13 checks; free, no server).

## 4a. Matched fights: the plan as written before the go

- **Arms.** A: the lane off (every purpose on the fake model, as the replicates' A) — free. B1: the lane on, first frame, real fast calls. B2: the lane on, balanced frame, real fast calls. All on `battle_diag.py --battle 100 --walkers 16 --keep-plans --fixed-site 406.5 237.5`, island world seed 7 (the Nov 19 site and formation), 6 minutes, measured from minute 1. Two runs of each, interleaved A B1 B2 A B1 B2, under one `~/slop-mq/battle.lock` hold, each started with the merge lock free and a 1-minute load under 4, redone if the load passes 8 in its measured window; the server and the mind pinned to CPUs 5–9,15–19, no builds during the series.
- **Switches, recorded per run:** `fast_lane_on` false (A) or true (B1, B2) with the shipped caps; `LIVING_FAST_FRAME` first or balanced; every purpose but `fast` on the fake model (think 5 s, compile "keep"); `LIVING_SKILL_TIMINGS` unset (on); `force_outcomes` and every other law as shipped on main; `mind_act_replaces` false (main's default); no personas (main's fixture: "(no persona yet)").
- **Measures** (`flb_report.py`, per run and per arm): time in contact; engagements and attacks attempted per fighter-minute; attacks per contact-minute (aimed attacks); retreats, and the share re-engaged within 10 s; time away; damage taken and dealt per fighter-minute; timed defence (all sampled blows, and after the target's first patch); deaths; ticks a second; fast calls, failures, installs and their classification (§3's script); spend.
- **Cost.** The Nov 19 frame trial's arm B cost $0.29–0.32 per 5-minute run at 100 fighters. **About $0.40 a run, $1.60 for the four paid runs.** Stops: per run at $1.00, the whole step at $5.00, and the whole branch (§3 and §4) at **$8.00** by the journals; a run also stops at more than 10% failed fast calls over 2 minutes or two windows under 2 ticks a second.

**Estimated total: about $2.25 of an $8 cap.**
