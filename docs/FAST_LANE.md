# The fast lane: a re-plan between blows

Designed on `design-fast-lane` and **built on `fast-lane`** (2026-11-12), with the general coordinator's change: **nothing the trigger counts is told to anyone** (owner: minds find patterns themselves; r2b–r2d show they name a pattern by its 3rd or 4th exposure without help). **Off by default:** the world law `fast_lane_on` is false; a trial turns it on per arm. While the 100-fighter battle collapse is diagnosed (2026-11-12: 18.5 → 2.9 ticks a second in 30 minutes, every witnessed blow waking every minded onlooker), nothing may add calls to battles: the lane stays off outside 1v1 arenas, and nothing is tuned for battles. It details [combat mind](COMBAT_MIND.md) §3.4 within the owner's layered idea:

> "the big model basically prepares a bunch of schemes, and then the decision model decides more or less real-time when it's the good time to apply them. But then there is still live real-time execution of things, so that we are not bounded by the decision model."

- **The slow mind prepares.** Think and compile write the plan, the routines and the movement intents (3.3), as today.
- **The fast lane revises between blows.** One small call, on the rethink gate's machinery, writes the character's `combat` branch again, or switches it to a routine the character already has. It answers what the character has just perceived of a fight.
- **Execution stays real-time in the graph.** The routine's own conditions (`doing`, `threatened`, `near`, stamina) answer a windup on the tick. The fast lane is never on that path, and no body waits for it.

The rule of [COMBAT_MIND](COMBAT_MIND.md#the-rule-this-design-follows) holds throughout: it is a lane of the mind service chosen by urgency, not a combat planner. Its prompt carries no tactic text, its reply is in the grammar every mind writes, and it is the same for every controller whose mind is running.

## What R2 says it is for

- **The slow path arrives late.** A blow to an installed plan takes 8.6 s at p50 with real models (R1, §5.1); in r2c the answering plan came 13 s after the exposure that prompted it.
- **The pattern was noticed before it was answered.** Minds named the pattern by the third or fourth exposure. The first fitting answer came at exposure 8 (r2c r2) and 13 (r2d kiter r1); in the other heavy fights the fight ended first.
- **Exposures were spaced enough to answer.** In r2d the heavy blows came 9.8 s apart at p50 (p10 9.3 s) and the arrows 1.33 s (p90 2.5 s).

A revision that lands in about 3 s would come between heavy blows and after two or three arrows, where today's lands after five or ten.

## 1. The trigger

The authority raises the trigger from what the character perceived (`living/authority/src/fast.rs`). It never reads the opponent's plan or vitals for it.

- **A blow taken.** In `act::damage`, a blow, shot or bolt that landed in full or in part on a character the minds hold. The request's reason is the character's own line for it: "A stranger shot you with an arrow: hit for 7", "Kelkelly attacked you (10 damage)".
- **A move repeating.** In `combat::accepted`, a move started with a victim, seen by the victim (`perception::sees_creature`: the one sight rule, facing when `fov_on`, the light), is counted per (victim, mover, skill) within one fight: moves less than 30 s apart, the window `damage` uses for a first blow. At every N-th, a trigger whose reason is the event as perceived: "Grim winds up an attack at you". No number, no "again".
  - N is the world law `seen_again_n`, shipped as 3, the same for every creature and fight. It is used for the trigger only.
  - The count is kept in the authority's memory and is never written or told: no experience, no prompt, no player row carries it (verify-core `seen_again`, verify-minds `fast-lane`, verify-player `fast_lane`).
- **Only a character whose mind runs:** alive, `ai` (an AI character, or a person's character while the minds hold it), a person past infancy, awake (`perceive::asleep`), not instinct-only.

### Turns: the `fast_ask` row and the laws

A private table, one row per character, holds its newest trigger: reason, when, the oldest one not yet served, when it was issued, and the graph it was issued against (`brain.installed_ms`). Rows are issued to the mind service under world laws, all in `skills.rhai` `laws()`:

| Law | Shipped | What it bounds |
|---|---:|---|
| `fast_lane_on` | false | the lane at all |
| `seen_again_n` | 3 | the repeat trigger |
| `fast_lane_rate` | 2 a second | issues across the world (a bucket holding one second's worth) |
| `fast_lane_inflight` | 4 | issued and unanswered at once, across the world |
| `fast_lane_gap_s` | 6 s | between one character's issues |
| `fast_lane_stale_s` | 8 s | a trigger waiting longer is let go; an issued one unanswered in twice that is let go |

- **One in flight per character**, and triggers merge: a trigger while one is issued or waiting replaces the reason and waits for the next turn. Nothing queues per blow.
- **Turns** go to the most recently triggered first. A row answered with nothing newer stays idle until its gap has passed, so the gap holds.
- **Pumped** on each trigger and answer, on the tick while a row waits, and in housekeeping.

### With the think throttle

- **A separate clock.** The fast lane is not a deliberation. It does not count toward `think_min_s`, does not set `deliberated_ms`, and is not held by the rethink gate.
- **Both run.** The slow deliberation that urgent reasons already start ("X is attacking you!", a fight report) runs as today, side by side.
- **Who writes what.**
  - The fast lane writes only the `combat` branch (below); the slow deliberation stays the author of the whole plan.
  - A slow install whose request began before the last fast patch keeps the current `combat` branch: the authority splices it in by label. A later slow decision, which saw the patch in its prompt, replaces it like any other part of the plan.
- **Not built: held after a patch.** The design had the rethink gate hold non-urgent triggers for 10 s after a fast patch. Not built: the gate is off by default, and nothing measured asks for it yet.

### With committed moves

- **Nothing in progress is cut.** The patched branch takes effect at the graph's next evaluation; a committed windup or dash in progress runs its course (`committed-moves`).
- **No answer to the current move.** The fast lane never tries to answer the move in progress; its first effect is on the next move the body chooses.

### With sleep

- **A sleeping body is never fast-laned.** A sleeper (in a sleep act, or between two sleeps of one rest: `perceive::asleep`) is not counted or triggered.
- **The waking blow does not count.** It starts the waking deliberation, as today; later blows, on the woken body, do.
- **Off stage, no fast lane, when the level of detail is on.** With `LIVING_LOD` on, off-stage characters (`Attention::OffStage`) don't get it: their fights are coarse and their minds slow by design. With it off (the default, and in trials) every character is served. A staged model mix calls every character no player watches "off stage" for model routing; that alone does not keep the lane off (fix-fast-onstage, 2026-11-12: r2e's fake run found every request answered "kept: off stage" in an arena with no player).

## 2. What it sends and gets back

### The request

One chat call (`living/mind/src/mind/fast.rs`, `prompts::fast_system` and `fast_user`). It carries only the character's own perception and plans:

| Part | From |
|---|---|
| Why now: the trigger's reason, the event as perceived | `fast_ask.reason` |
| Who you are, with its own moves' timings | `persona_text` and `own_timings` (3.7), as think has them |
| What has just happened, oldest first: the newest 12 experiences (blows taken and dealt, own outcomes, refusals) | `exp_line`, as deliberation renders them |
| Your top level (plan and outline) and Your routines (names, one line each, `routine_stat`) | the installed graph, `routine`, `routine_stat` |
| The world's rules (physics), the graph grammar and the four replies; no acts or dealings | `world_rules()`, `grammar()`, a stable prefix (prompt-cached) |

**Not built:** situational recall in the prompt (§3.6's "what comes to mind about whom you face"). The size and cost of the built prompt are measured in r2e.

### The reply

The reply is one of these:

- `{"patch": {"label": "combat", "graph": …}, "thought": "…"}`: the `combat` branch rewritten in the grammar;
- `{"routine": {"name": "<one of your routines>", "graph": …}, "thought": "…"}`: one of its own routines rewritten (never a new one; r2–r2d's plans live in the routine "current plan");
- `{"switch": "<one of your routines>", "thought": "…"}`: the branch becomes `{"routine": name}`;
- `{"keep": true, "thought": "…"}`: no change.

The `thought` is one sentence, kept as a thought row of kind `fast`, so the next think step sees why the branch changed.

### What it may not do

- **No speech, acts, stances or places.** Those stay with the slow mind.
- **Nothing outside the `combat` branch and its own existing routines.** The authority does the splice (`living_rules::graph::patch_branch`, shared with the compile's patch), so a reply cannot touch anything else.
- **Nothing a compile could not write.** The patch is validated by the same `set_graph` normalisation, and a refusal is a thought of kind `error`, as a rejected compile is.
- **No scripted counters, no "dodge on windup" answer, no tactic text.** The prompt states what the character perceived and what it knows how to do; the rules text keeps physics only (§6 of COMBAT_MIND).
- **No inventing.** A routine it switches to must be one the character wrote; the reply cannot create routines (the slow mind does that). The audit of §4.1 (every prompt sent, searched for the fixture's pattern words outside the character's own experiences) applies to the fast lane's prompts too.

### The data path

- **Two new reducers:**
  - `mind_patch(actor, target, graph, asked_ms, thought)`: `target` is `combat` or `routine:<name>`.
  - `mind_fast_done(actor, asked_ms, thought)`: no change (kept, no usable answer, off stage, timed out).
- **Who may call them.** Both are authorised as `mind_install` is (the caller is the character's controller), and both need an open request issued at `asked_ms`; a body its person controls never has one, so a player is refused even for its own character (verify-client).
- **The plan check.** `mind_patch` lands only if the graph installed when the request was issued is still installed (`fast_ask.base_ms == brain.installed_ms`). Otherwise it changes nothing and keeps the refusal as a `fast` thought ("refused: the plan changed since it was asked"), so refusals can be counted; the request's turn ends either way.
  - SpacetimeDB reducers are transactions: an error rolls back every write ([reducers](https://spacetimedb.com/docs/functions/reducers/)), which is why the plan check returns success with the refusal recorded.
  - Adding reducers is a safe module update; changing `mind_install`'s signature would not be: clients calling the old version would get runtime errors ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/), docs 2.0.0, read 2026-11-12).
- **Install source `fast`.** A patch installs with source `fast`, so it does not count as having thought (`deliberated_ms`, `think_min_s`). A committed move under way runs its course (the activity is kept as an orphan the new graph may adopt).
- **Schema.** One new private table, `fast_ask` (adding a table is a safe change). Bindings regenerated with additions only (`fast_ask`, the two reducers; and `slumber`, which main's bindings lacked).
- **Writes.** Per issue, one `fast_ask` row update; per answer, one `brain` row update (and one `routine` row for a routine) and one `thought` row.
- **Subscription.** The mind service subscribes `fast_ask` on its own; a world without it still starts.

## 3. Model and latency

### Measured, from the journals of r2b, r2c and r2d

Calls without errors on the trial stack; one thinking subject per world, so the queue was empty: `queue_wait_ms` was 0 at p50 and p90 for every purpose.

| Purpose, model | n | Prompt tokens p50 | Completion p50 | Latency p50 / p90 |
|---|---:|---:|---:|---:|
| think, DeepSeek V4.1 Flash | 84 | 4,639 | 445 | **2.0 / 3.9 s** |
| think, GLM 5.3 Flash | 109 | 4,494 | 272 | 7.7 / 16.4 s |
| deliberate (compile), DeepSeek Flash | 71 | 13,226 | 984 | 3.4 / 7.8 s |
| deliberate, GLM Flash | 120 | 13,503 | 346 | 10.9 / 21.5 s |

### Elsewhere

- **Talk-sized calls.** MODEL_COST: about 1.8 s; DeepSeek's first text at 0.6 s against Ministral's 0.3–0.4 s.
- **Ministral.** Ministral 3B answers a think-sized prompt at 3.5 s p50, but was judged acceptable 0 of 12 times; it would write graphs no one could trust.
- **A loaded hour.** In MODEL_COST's afternoon, DeepSeek queued 7–11 s before its first token. verify-llm's [timeout](../.agents/skills/verify-llm/features/timeout.md) and [overflow](../.agents/skills/verify-llm/features/overflow.md) features are how such hours are survived.
- **The pipeline without a model.** R1: about 0.7 s from a blow to a think reply with an instant model (the reason, the request, the pickup); one install adds about 0.2 s.

### The choice

DeepSeek V4.1 Flash, thinking off (the `deepseek-flash` profile), through a purpose `fast` on the `Urgent` lane, configured in `rethink.json` `fast.route`.

- It is the only model measured fast enough. Its compile fidelity without thinking was judged weak (5 of 24, MODEL_COST), so fidelity is a measure of the arm, not an assumption (§6).
- The fast lane's small prompt is in think's size class, so its latency should be think's: about **2.0 s p50, 3.9 s p90** in a good hour.

### Blow to patch installed

About 1.0 s of pipeline plus the call: **≈ 3 s p50, ≈ 5 s p90 in a good hour**, 10 s or more in a loaded one. `fast.timeout_ms` is 6,000: a reply later than that is dropped as stale, journaled as a timeout, and changes nothing.

### Against the windows

| Window | Length | Can the fast lane land in it? |
|---|---|---|
| A windup (the heavy blow) | 0.75 s | **No.** Nothing that calls a model can. The routine's own conditions answer it on the tick (67 ms cadence), and the fast lane only writes those conditions. |
| The exchange that triggered it (a blow and its pause) | ~2–3 s | **No.** The trigger is the blow, already landed, and 3 s is longer than the rest of the exchange. |
| The next exchange | heavy: 9.8 s p50 between blows in r2d; arrows: 1.33 s | **Heavy: yes, usually** (3 s against 9.8 s; the p10 gap is 9.3 s). Arrows: no. A patch lands after the next two or three, so it answers about the third arrow after the trigger. |

**What it buys.** The re-plan cannot answer the exchange it was triggered by, nor a windup. It answers the next exchange of a paced fight (heavy blows, an approach, a guard), and the third or fourth of a fast one (arrows). Against today's 8.6–13 s, that is the difference between answering at about exposure k+1 to k+3 and at about k+5 to k+10, or after the fight. Whether the answer fits is what the arm measures (§6).

## 4. Cost

### Per call

DeepSeek Flash is $0.30 per million input tokens, $1.20 per million output and $0.007 per million cached (trials.py `PRICES`).

- **Estimate:** about 2,000 fresh and 4,000 cached input tokens and 300 out: $0.00099.
- **Bound used below:** think's measured mean of **$0.0013 a call** (r2b–r2d, 84 calls, 48% cached).

### Per fight, from r2d's blows and exposures

Triggers are the blows taken plus one per N repeats, merged by the 6 s gap.

- **Heavy:** 4–11 blows taken and 4–13 heavy exposures a fight. About 5–8 calls, **$0.007–0.010 a fight**.
- **Kiter:** 3–14 arrows struck and 10–57 exposures over 10 minutes. With the 6 s gap, about 10–30 calls, **$0.013–0.04 a fight**; the gap's ceiling is 100 calls, $0.13.
- **Against r2d:** r2d's own spend was $0.026–0.036 a fight, so the fast lane adds about a quarter in heavy fights, and up to the whole of it again in an arrow fight.

### Per battle of 20 fighters

An estimate only. No paid battle runs until the 100-fighter collapse is understood (see the top).

- **The rate.** §5.2's battle had 9.2 blows a second among 20, so each fighter is struck about every 2 s. The 6 s gap binds: 20 fighters × 1 call per 6 s is 3.3 calls a second.
- **The global cap binds before that** (below): **2 calls a second, $0.0026 a second, $0.16 a minute**. A 3-minute battle costs about **$0.47**.
- **The total spend** rises by the cap's share: at 2 calls a second the queue's Urgent share is spent on fast calls, and the cap keeps the queue from flooding.

### The bound that keeps a battle from flooding the queue

- **Per character:** one in flight, the 6 s gap, merged triggers, stale drops (above).
- **Global, world laws:** `fast_lane_inflight` 4 and `fast_lane_rate` 2 a second, applied by the authority when it issues rows.
  - Past either, a trigger waits its turn or goes stale; it never displaces a deliberation.
  - Turns go first to the character triggered most recently.
- **Measured** (verify-llm `fast-cap`, fake model, 20 fighters in ten pairs attacking each other, all served, each fast reply held 2.5 s, 30 s):
  - at most 4 issued at once and 4 in flight at the provider;
  - at most 3 started in any one second in that run; the bucket allows up to 4 (its burst of 2 plus one second's refill of 2), which the test now checks (fix-fast-cap-test);
  - 28 calls, and 19 of the 20 fighters got a call (9 got two);
  - the wait from trigger to issue was 0.09 s at p50, 4.7 s at p90 and 5.7 s at most (under the 8 s stale limit).
  - **No tick numbers.** Any reading in a battle would be confounded by the battle collapse under diagnosis, and nothing is tuned for battles.
- **What the cap means at scale:**
  - At 200 fighters the cap means each gets a fast call about every 100 s: the lane degrades to nothing for most fighters, and the slow mind and the routines carry the fight, as today.
  - The fast lane is a help to those in view, not a promise to every combatant. Measured at the 216-character gate before it counts as accepted.

## 5. One controller rule

- **The fast lane serves a character whose mind is running:**
  - an AI character;
  - a player's character while the AI holds it (the player offline, `presence.ai`).
- **Never while a person controls the body.** The authority already enforces it: `mind_patch`, like `mind_install`, is authorised only when the caller is the character's controller. When the player comes back (`presence.rs` `hand_back`), the player becomes the controller again, so a reply arriving after that is refused, writing nothing.
- **The player's return cancels a pending re-plan.** The mind service drops the character's in-flight fast request when it sees `character.ai` go false or the controller change; it doesn't wait for the reply.
- **A stale reply can't land after the AI takes over again.** The player's return deleted the request (`fast::cancel` in `hand_back`), so a reply prepared before it is refused by `mind_patch` ("no fast re-plan was asked of this character"), even though the mind service is the controller again (verify-minds `fast-takeover`).
- **The player is never served.** A human-controlled body gets no fast lane: its "fast lane" is the person.

## 6. How to test it

### The arm

- **R2 with the world law `fast_lane_on` set true for the arm** against r2d (the same fixtures, `arena-heavy` and `arena-kiter`, 5 replicates each).
- **Free first:** `--fake`, for the plumbing and the floor. From a blow to a patch installed, with an instant model, should be about 1 s.
- **Then paid:** about $0.40 for the pair of arms at r2d's scale, plus the fast calls ($0.05–0.2).

### Measures

- **Exposures to the first answer** (the first exposure k answered), per fight, the arm's main measure, against `default` and against r2d's: heavy, never in 5; kiter, 13 in one fight and never in four.
- **K** (three answered in a row), as before.
- **Attribution.** From the journal (purpose `fast`) and the `thought` rows of kind `fast`: was each first answer made by a fast patch, a slow plan or a reflex?
- **Fidelity.** For each fast patch: does it do what its `thought` says? Does it name a skill the character has? Is it valid on the first try?
- **Did a mind's timing move?** `arena_report.py`'s doing→dodge table, by install time and source: do fast patches move from "winding up" toward "about to release" after "it was over before the blow came"?
- **Latency.** Blow to patch installed, p50 and p90, and the share dropped as stale. **Cost per fight.**

### Verification (built, free)

- **verify-minds `fast-lane`** (fake model), each sub-case a check:
  - (a) a blow taken issues one fast request whose prompt holds why now (the victim's own line), what has just happened, the top level and the routines, and no count or "again"; the reply's `combat` branch is installed through `mind_patch`;
  - (b) blows inside the 6 s gap merge into one call;
  - (c) a reply held while an install changes the plan is refused by the plan check;
  - (e) a sleeper's blow issues nothing;
  - (f) with the law off, blows ask nothing;
  - (g) the slow install the same blow started keeps the patched branch.
- **verify-minds `fast-takeover`:** (d) the player's return drops the request; the minds take over again and the late reply is refused.
- **verify-llm `fast-route`:** the purpose `fast` goes to `fast.route`'s profile on the urgent lane, journaled with `latency_ms` and `queue_wait_ms`; a reply past `timeout_ms` is dropped and journaled as a timeout.
- **verify-llm `fast-cap`:** the laws' caps, as measured above.
- **verify-core `seen_again`:** the repeat trigger, with `fast_lane_inflight` 0 so rows wait and can be read:
  - the windup reason first comes at the 3rd windup (law 3) and at the 2nd (law 2);
  - no reason or experience counts or says "again";
  - shot from behind with `fov_on`, only the struck line.
- **verify-client:** `mind_patch` and `mind_fast_done` are refused to anonymous callers, to players for another character ("not your character") and for their own ("no fast re-plan was asked"); `fast_ask` is private.
- **verify-player `fast_lane`:** a played body struck by four heavy blows gets no `fast_ask` row, and its rows carry no count or "again".
- **Unit tests:** `mind::fast::tests` (what a reply may change; no count or tactic text in the prompt); the rules' install check covers the six laws.

## What this design does not do

- **It does not answer a windup.** Graphs do, with conditions the minds write (r2d: every condition still said "winding up"; whether minds move it is the arm's question, not something the fast lane is told to do).
- **It does not add a decision model choosing among prepared ways** (COMBAT_MIND §3.5).
- **It does not prepare routines before a fight.** The slow mind does, or doesn't.
