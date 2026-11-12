# The fast lane: a re-plan between blows

Design only (2026-11-12, branch `design-fast-lane`, from origin/main `d80a1373`). Nothing here is built. It details [combat mind](COMBAT_MIND.md) §3.4 within the owner's layered idea:

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

The fast lane starts from what the character has perceived, as `experience` rows the mind service already receives. It never reads the opponent's skill, vitals or plan.

- **A blow taken.** An `attacked` experience: a blow, a shot, a bolt that landed in full or in part.
- **A pattern repeating.** The same visible move, aimed at the character, by the same creature, perceived for the N-th time in one fight. N is the world law `seen_again_n`, shipped as 3, the same "three" the fight report already uses for blows that land or come to nothing (`act.rs` `fight_report`). It is a law of perception, the same for every creature and every fight, and never tuned per fight or opponent.
  - "The same visible move" is what `doing` reads: the move's `is` as `perception::doing_of` shows it (its skill or act card), the mover, `at_me`, under the one sight rule (`perception::in_sight`: field and facing when `fov_on`, the light, the far label).
  - "One fight" is a run of blows and moves with gaps under 30 s: the window `damage` already uses to decide that a blow is a first blow (`hurt_ms` older than 30 s).

### The repeat becomes a percept first (authority)

This is §3.2's folded percept, which was designed and not yet built. When a perceived creature starts a move aimed at a character whose mind runs, the authority counts it in that character's `mind_state` marks, keyed by (mover, look), as `fight_report` keeps its marks. At N, and again at 2N and 3N, it writes one experience, in words for the character and its memory:

> "Grim winds up an attack at you again (3 times now)."

Below N, nothing is written beyond today's percepts. A move the character did not see is not counted; the sight rule decides, not the trigger. This line is the same whether or not the fast lane is on: a person playing the character gets it in `my_experience` too, as perception.

### Debounce, per character

- **One in flight.** At most one fast-lane request per character at a time.
- **A gap.** At least `gap_s` between two fast calls' starts, in `living/configs/rethink.json` `fast.gap_s`, 6 s. A mind-service setting, like the gate's `max_hold_s`.
- **Triggers merge.** Triggers inside the gap, or while a request is in flight, are merged; the next call sends the latest exchanges. Nothing queues per blow.
- **Stale requests are dropped.** A trigger older than `fast.stale_s` (8 s) when its turn comes is dropped: the fight has moved on.

### With the think throttle

- **A separate clock.** The fast lane is not a deliberation. It does not count toward `think_min_s`, does not set `deliberated_ms`, and is not held by the rethink gate.
- **Both run.** The slow deliberation that urgent reasons already start ("X is attacking you!", a fight report) runs as today, side by side.
- **Who writes what.**
  - The fast lane writes only the `combat` branch (below); the slow deliberation stays the author of the whole plan.
  - A slow install whose request began before the last fast patch keeps the current `combat` branch: the authority splices it in by label. A later slow decision, which saw the patch in its prompt, replaces it like any other part of the plan.
- **Held after a patch.** For `fast.settle_s` (10 s) after a fast patch, the rethink gate counts "the plan was just revised" as a reason to hold the non-urgent triggers it already holds (a plan finished, a branch failing). Urgent reasons still pass, as they always do.

### With committed moves

- **Nothing in progress is cut.** The patched branch takes effect at the graph's next evaluation; a committed windup or dash in progress runs its course (`committed-moves`).
- **No answer to the current move.** The fast lane never tries to answer the move in progress; its first effect is on the next move the body chooses.

### With sleep

- **A sleeping body is never fast-laned.** A sleeper perceives only what wakes it.
- **The waking blow counts.** A blow that wakes it starts the waking deliberation, as today, and counts as a trigger once the body is awake.
- **Off stage, no fast lane.** Off-stage characters (`lod`: `Attention::OffStage`) don't get it either. Their fights are coarse and their minds slow by design.

## 2. What it sends and gets back

### The request

One chat call, built in code like the rethink gate's state (`rethink::state`). It carries only the character's own perception, plans and memory:

| Part | From | Size |
|---|---|---|
| Who you are: name, goals, mood | the persona, as in think | ~200 tokens |
| Your top level and your `combat` branch, as an outline; your routines' names and one line each, with `routine_stat` ("done 3×, failed 2×") | the installed graph, `routine`, `routine_stat` | ≤ 1,200 chars |
| What has happened in this fight, oldest first: blows taken and dealt, own outcomes ("You failed to dodge: it was over before the blow came"), refusals, the repeat percepts, what the other is visibly doing now (`visibly`) | experiences since the fight began, folded as the gate folds them (`rethink::folded`), newest 12 | ~600 tokens |
| What comes to mind about whom you face | situational recall with a small budget (§3.6): stances, beliefs, memories cued by the creature, its kind and the fight's words | ≤ 400 tokens |
| Your own moves' timings | `prompts::own_timings` (3.7), the moves the character knows | ~150 tokens |
| The graph grammar, the conditions and leaves only, and the reply format | the same `prompts.rs` text the compile step gets, without the acts and dealings sections | ~3,500 tokens, a stable prefix (prompt-cached) |

About 6,000 tokens in all, two-thirds of them a cached prefix: smaller than a think call (4,638 tokens at p50 in r2b–r2d, plus its own long cached prefix) and a third of a compile (13,226).

### The reply

The reply is one of these:

- `{"patch": {"label": "combat", "graph": …}, "thought": "…"}`: the `combat` branch rewritten in the grammar;
- `{"switch": "<one of your routines>", "thought": "…"}`: the branch becomes `{"routine": name}`;
- `{"keep": true, "thought": "…"}`: no change.

The `thought` is one sentence, kept as a thought row of kind `fast`, so the next think step sees why the branch changed.

### What it may not do

- **No speech, acts, stances or places.** Those stay with the slow mind.
- **Nothing outside the `combat` branch.**
- **Nothing a compile could not write.** The patch is validated by the same `set_graph` normalisation, and a refusal is a thought of kind `error`, as a rejected compile is.
- **No scripted counters, no "dodge on windup" answer, no tactic text.** The prompt states what the character perceived and what it knows how to do; the rules text keeps physics only (§6 of COMBAT_MIND).
- **No inventing.** A routine it switches to must be one the character wrote; the reply cannot create routines (the slow mind does that). The audit of §4.1 (every prompt sent, searched for the fixture's pattern words outside the character's own experiences) applies to the fast lane's prompts too.

### The data path

- **A new reducer, `mind_patch(actor, label, graph, base_ms, thought)`.**
  - Like `mind_install`, it is authorised by the caller being the character's controller.
  - It applies only if the installed graph is still the one the request read (`brain.installed_ms == base_ms`); otherwise it returns an error and writes nothing. SpacetimeDB reducers are transactions: an error rolls back every write ([reducers](https://spacetimedb.com/docs/functions/reducers/)).
  - Adding a reducer is a safe module update. Changing `mind_install`'s signature would not be: clients calling the old version would get runtime errors ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/), docs 2.0.0, read 2026-11-12).
  - Bindings are regenerated with `just living-generate`.
- **Writes.** One `brain` row update and one `thought` row per accepted patch. No new table, column or subscription.
- **Reads.** The request reads rows the mind service already holds (its characters' experiences, routines, graph).

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

- **The rate.** §5.2's battle had 9.2 blows a second among 20, so each fighter is struck about every 2 s. The 6 s gap binds: 20 fighters × 1 call per 6 s is 3.3 calls a second.
- **The global cap binds before that** (below): **2 calls a second, $0.0026 a second, $0.16 a minute**. A 3-minute battle costs about **$0.47**.
- **The total spend** rises by the cap's share: at 2 calls a second the queue's Urgent share is spent on fast calls, and the cap keeps the queue from flooding.

### The bound that keeps a battle from flooding the queue

- **Per character:** one in flight, the 6 s gap, merged triggers, stale drops (above).
- **Global:** `fast.max_in_flight` 4 and `fast.per_s` 2, a token bucket across the service.
  - Past either, a trigger waits its turn or goes stale; it never displaces a deliberation.
  - Turns go first to the character struck most recently, then by attention (on stage first), the ordering the queue's admission already uses (`NON_INTERACTIVE_ADMISSIONS`: six of ten admissions are Urgent).
- **What the cap means at scale:**
  - At 200 fighters the cap means each gets a fast call about every 100 s: the lane degrades to nothing for most fighters, and the slow mind and the routines carry the fight, as today.
  - The fast lane is a help to those in view, not a promise to every combatant. Measured at the 216-character gate before it counts as accepted.

## 5. One controller rule

- **The fast lane serves a character whose mind is running:**
  - an AI character;
  - a player's character while the AI holds it (the player offline, `presence.ai`).
- **Never while a person controls the body.** The authority already enforces it: `mind_patch`, like `mind_install`, is authorised only when the caller is the character's controller. When the player comes back (`presence.rs` `hand_back`), the player becomes the controller again, so a reply arriving after that is refused, writing nothing.
- **The player's return cancels a pending re-plan.** The mind service drops the character's in-flight fast request when it sees `character.ai` go false or the controller change; it doesn't wait for the reply.
- **A stale reply can't land after the AI takes over again.** When the player leaves once more, `take_over` installs the AI's graph (`set_graph` from `ai_graph`), which changes `brain.installed_ms`. A reply prepared before the player's return carries the old `base_ms` and is refused by `mind_patch`, even though the mind service is the controller again.
- **The player is never served.** A human-controlled body gets no fast lane: its "fast lane" is the person. The repeat percept of §1 reaches the player all the same, as perception.

## 6. How to test it

### The arm

- **R2 with a variant `fast`** (`LIVING_FAST=1` with `LIVING_RETHINK` set to `llm`, the gate's machinery) against `default`: the same fixtures (`arena-heavy`, `arena-kiter`), 5 replicates each.
- **Free first:** `--fake`, for the plumbing and the floor. From a blow to a patch installed, with an instant model, should be about 1 s.
- **Then paid:** about $0.40 for the pair of arms at r2d's scale, plus the fast calls ($0.05–0.2).

### Measures

- **Exposures to the first answer** (the first exposure k answered), per fight, the arm's main measure, against `default` and against r2d's: heavy, never in 5; kiter, 13 in one fight and never in four.
- **K** (three answered in a row), as before.
- **Attribution.** From the journal (purpose `fast`) and the `thought` rows of kind `fast`: was each first answer made by a fast patch, a slow plan or a reflex?
- **Fidelity.** For each fast patch: does it do what its `thought` says? Does it name a skill the character has? Is it valid on the first try?
- **Did a mind's timing move?** `arena_report.py`'s doing→dodge table, by install time and source: do fast patches move from "winding up" toward "about to release" after "it was over before the blow came"?
- **Latency.** Blow to patch installed, p50 and p90, and the share dropped as stale. **Cost per fight.**

### Free verification cases it would need, before any paid run

**verify-minds `fast-lane`, with the fake model:**
- (a) a blow taken starts one fast request whose prompt holds the fight's experiences, the `combat` outline and the routine names, and no tactic text; the reply's patch is installed through `mind_patch`;
- (b) blows inside `gap_s` merge into one call;
- (c) a reply with a stale `base_ms` (a slow install in between) is refused and changes nothing;
- (d) the player coming back (handback) while a request is in flight drops it, and the authority refuses a late reply; after the AI takes over again, a reply prepared before is refused;
- (e) a sleeping body is not fast-laned;
- (f) with the switch off, no `fast` call is made;
- (g) a slow install that began before a fast patch keeps the patched `combat` branch.

**verify-llm `fast-route`:** the purpose `fast` routes to `fast.route`'s profile on the `Urgent` lane, is journaled with `latency_ms` and `queue_wait_ms`, and a reply past `timeout_ms` is dropped as a timeout.

**verify-llm `fast-cap`:** at most `max_in_flight` fast calls run at once and at most `per_s` start a second; excess triggers wait or go stale, and deliberations are never displaced.

**verify-core `seen_again`:** the repeat percept under the `seen_again_n` law:
- written at N and 2N for a creature's same visible move at a character that sees it;
- not for one it does not see (behind it with `fov_on`, beyond sight);
- not for different moves;
- an installed law changes N.

**verify-player:** the repeat percept reaches a player's `my_experience`; a played body gets no fast call.

## What this design does not do

- **It does not answer a windup.** Graphs do, with conditions the minds write (r2d: every condition still said "winding up"; whether minds move it is the arm's question, not something the fast lane is told to do).
- **It does not add a decision model choosing among prepared ways** (COMBAT_MIND §3.5).
- **It does not prepare routines before a fight.** The slow mind does, or doesn't.
