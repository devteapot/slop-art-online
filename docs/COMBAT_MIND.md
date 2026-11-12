# How a character's mind fights

Written 2026-11-11 on the Spark (branch `design-combat-mind`, from `origin/main` 4b76ef41). A design, not a build: no rule, table, reducer or prompt is changed. The one measurement is read-only: [`living/tools/fight_mind_audit.py`](../living/tools/fight_mind_audit.py) over 32 existing real-model trial runs. The survey behind it is [COMBAT_MIND_RESEARCH.md](COMBAT_MIND_RESEARCH.md).

## The rule this design follows

The owner, verbatim:

> "But really, all of this we should try to not hard-code it. It should be emergent from how they already learn, with except maybe some changes to the architecture of the mind where it makes sense, of course."

So everything the owner described while thinking this through is **behaviour we want to see a mind produce**, not modules to build for it:

- schemes the large model prepares, with the conditions under which each applies, and a decision model that times them;
- a working picture of this opponent built during the fight: skills shown, the ranges and timings, how it answers being approached, pressed or left alone, what it has never done;
- lessons that outlast the fight and carry to the same opponent, to another of its kind, and to a stranger who fights the same way, so that "the combat should be much easier".

What follows from that:

- **No combat-specific learning.** There is no hand-made table of opponents, no built-in list of tactics, no code that recognises a pattern for the mind and no reward for winning. If a character comes to hold a picture of an opponent, it is because it noticed, remembered and reasoned, as it does when it learns who cheats at the market.
- **Architecture may change where it makes sense, and then generally.** A change is fair when it serves anything time-critical a character does: a chase, catching a falling child, haggling against the clock. Combat is the hard case that shows the need. Each change below is justified by something the existing mind measurably cannot do.
- **The arenas measure emergence; they don't train it.** Scripted opponents and fixed setups are trial fixtures. Nothing learned in an arena is installed into characters, and no engine behaviour is added so that an arena passes.

The project's standing rules hold throughout: real-time behaviour runs beneath slower model revision; inference lives in the mind service, never in reducers; shared rules and costs for every controller; no instinct branches for dealings; nothing hard-codes engine behaviour for a trial.

The order is the owner's: what exists (§1); what a fight asks of it and where it falls short, measured (§2); the smallest general changes that would close each gap (§3); how we would tell that the behaviour emerged and wasn't put there (§4). §5 lists the runs that would show what this turn could not.

## 1. What exists

Everything here is on `main` unless marked.

### 1.1 The body's fast layer

- **Behaviour graph** ([LIVING_CORE](LIVING_CORE.md#behavior-graph), `living/rules/src/graph.rs`): `first`, `seq`, `if`, `repeat` and a weighted `desires` top level, evaluated about once a second, immediately on salient events, and at about 15 Hz (staggered) for 8 s after the last blow, so a reaction fits inside a windup.
- **What a graph can test in a fight:** `threatened` (a hostile windup is aimed at me; while `fov_on` is on, only if I see the one winding up), `hurt_within`, `health`, `health_of` a target, `near` a target within a distance, `sees`, `count`, `believes` a stance the mind holds, `judged` (below), `chance`.
- **What it can do in a fight:** the combat skills (`strike`, `bowshot`, `firebolt`, `block`, `heal`, `dodge`, `jump`; older `attack`, `shoot`, `throw`, `threaten`, `yield`), each a script with a spec, a check and the shared timing; and movement: `goto`, `follow` (keeps 1–2 tiles), `flee` (until clear), `wander`, a dodge's dash.
- **Steering** carries movement: goals, not waypoints, re-planned at 8 Hz in a fight (`combat_hz`).
- **Routines** (`routine` table, at most 40 per character): named sub-graphs the mind writes for itself and calls from its top level; `routine_stat` counts how each has gone (ok, failed, the last failure).
- **The `judged` condition** ([MIND_HARNESS](MIND_HARNESS.md) item 4, `LIVING_JEV`, off by default): a graph reads a typed judgment cached by the mind service and never waits; with no fresh answer it takes its `else`. Jev (TypeSafe's small model) answers `noul`, `choice` or `score` questions. Measured from the dev-box: p50 136–174 ms, p95 166–240 ms. The one declared question, `fight_risk`, is refreshed every 4 s on the mind's 2 s tick. The owner decided on 2026-11-09 that Jev "is not real-time" and never drives moment-to-moment choices.

### 1.2 What a character perceives of a fight

- **On novelty and danger** (`saw`): "A wolf is close: 7 tiles west, attack → person." What a creature is doing, how far and which way, with hysteresis, not every second.
- **Blows taken** (`attacked`): "A wolf attacked you (13 damage)." The attacker as the victim knows it; not which skill, nor from how far.
- **One's own melee outcome** (`own`): "You finished: attack → wolf. hit for 7." Defences: "You blocked Grim's blow", "Grim dodged your attack", "Your blow missed: …".
- **Refusals and failed decisions:** "You failed to bowshot → #308: bowshot is not ready yet (0.2 s)", "What you had decided did not work out: …".
- **Fight reports** (`act.rs` `fight_report`): while people fight, at least 3 s apart, when health crosses a quarter, three blows come to nothing, three land or one's defence works three times, else after 12 s: "The fight with Grim: you have been hit 3 times … Your health 61; theirs looks about 70%." It is a reason to think. *(Finding: "theirs looks about 70%" is exact health; others otherwise see only a band, `fighter.band`. That is a perception leak, separate from this design.)*
- **The deliberation scene** shows what those in sight are doing; a mind in b5 wrote "a wolf is on me in daylight, winding up an attack at two paces".

### 1.3 The slow mind

- **Deliberation** = a think step (decide in words: thought, intentions, speech, stances, places) then a compile step (the graph, a `combat` patch, acts). A mind may patch only its labelled `combat` branch mid-fight. Urgent reasons (being attacked, a fight report, badly hurt) are never held by the rethink gate.
- **Memory** ([LIVING_CORE](LIVING_CORE.md#data-model-game-state-vs-mind-agreed-2026-09-26)): a personal Neo4j graph. Stances written in the think step (`self -JUDGES-> stance:<key>`) are projected to the `judgment` table, which `believes` reads. Consolidation turns experiences into beliefs with evidence; sleep merges duplicates and **generalizes repeated specifics into patterns**. Unreinforced beliefs fade (`c · exp(−age / 40 min)`), stances relax, memories fade over about 3 h, hearsay twice as fast.
- **Situational recall** (4–15 ms): cues from the situation (who is perceived, what was said or happened, words of the reason) spread through the character's own concepts; words in percepts match concept keys and memory gists.
- **Know-how and practice:** techniques are learned by practice, teaching, tablets and experimentation; a routine can be "taught by <name>". Hearsay is attributed and fades faster.
- **Model latencies** ([MODEL_COST](MODEL_COST.md)): a full deliberation 15–30 s p50 on the shipped mixes; GLM Flash `low` think 5.2 s and compile 9.1 s p50; DeepSeek V4.1 Flash compile 3.8 s p50 in a good hour and 10–11 s in a loaded one; talk-sized calls about 1.8 s; Jev about 150 ms. One afternoon is not a latency profile.

### 1.4 Coming: stamina and focus (`stamina-1`)

The [stamina proposal](https://github.com/devteapot/slop-art-online/blob/design-stamina/docs/STAMINA_PROPOSAL.md) (`origin/design-stamina`, being built on `stamina-1`) moves combat off `energy`. The numbers below are the proposal's and may change in the build.

| Skill | Pool and cost | Windup / recovery / cooldown | Reach |
|---|---|---|---|
| strike | 10 stamina | 350 / 250 / 650 ms | 1.6 m + lunge 0.6 |
| bowshot | 6 stamina + an arrow | 300 / 250 / 900 ms | 22 m at 30 m/s |
| firebolt | 30 focus | 450 / 350 / 4,000 ms | 16 m at 16 m/s |
| block | 5, then 4 a second held | raised at once, up to 8 s / – / 400 ms | ±75° in front |
| heal | 35 focus | 600 / 300 / 8,000 ms | 8 m |
| dodge | 20 stamina | – / 200 / 900 ms | 2.6 m at 5.2 m/s |
| attack (older, heavy) | 8 stamina | 650 ms (750 with a spear) | 1.4 m + lunge |
| run | 4 stamina a second | – | ×1.85 walk |

Stamina comes back 1 s after the last drain at 25 a second (empty to full in 5 s); focus 2 s after, at 3 a second. Graphs and minds get `run: true` and a `{"stamina": {"below": 30}}` condition. A fight becomes paced by breath: about ten strikes or five dodges from full.

### 1.5 Players and AI already share

The same skills, checks, costs, timing gate, reach, guard arc and dash; the same steering, collisions and roads; the same perception rules (sight, facing, hearing). A player's intention comes from keys; a mind's from its graph. A player's character has no mind until the AI takes it over, and then lives with what it lived ([PLAYER_MEMORY](PLAYER_MEMORY.md)).

## 2. What a fight asks, and how far the existing mind gets

### 2.1 The measurement

`fight_mind_audit.py` read the evidence of every real-model `wolves` and `wolves-valley` run of batches b4, b5, b6 and b6b on the Spark (32 runs; GLM Flash and DeepSeek Flash; 15-minute trials, a fresh newcomer each, a bold pack of four set down at nightfall). It reads files only. A fight is a run of blows the subject took with gaps under 20 s.

```bash
python3 living/tools/fight_mind_audit.py ~/dev/slop-trials/.local/living/trials/{b4,b5}/wolves* \
    ~/dev/slop-trials-cb/.local/living/trials/{b6,b6b}/wolves* --json .local/living/combat-mind/fight_audit-20261111.json
```

Evidence: `.local/living/combat-mind/fight_audit-20261111.json` on the Spark (git-ignored). Limits: one opponent kind (wolves, one way of fighting), fresh characters each run, 2 s samples that miss 300 ms moves (ranged use is counted from experiences instead), and stances, lessons and "how it fights" thoughts counted by word lists that the JSON shows verbatim. The counts show what minds wrote and did. They are not a classifier the mind depends on.

| | Value |
|---|---:|
| Runs / runs where the subject was attacked | 32 / 11 |
| Fights / later fights in the same life | 25 / 14 |
| Fight length p50 / p90 / max (first to last blow) | 0 s (one blow) / 19.4 s / 40.6 s |
| Model calls (think or compile) started during a fight / finished before it ended | 42 / 30 |
| Fights in which at least one call finished in time | 9 of 25 |
| Per-call latency in fights, p50 / p90 / max | 3.3 / 11.5 / 72.5 s |
| Graph revisions installed during fights | 10 |
| Stances naming wolves, written in fights or within 2 minutes after | 81 |
| Thoughts describing how the wolves fight | 21 |
| Thoughts carrying a lesson from an earlier encounter | 27 |
| Wolf-related deliberations stating a spatial intent (wall at my back, keep distance, between me and it) | 18 of 140 (13%) |
| Thinks meaning to shoot a wolf / next compile had a ranged skill / melee only | 102 / 46 / 14 |
| Runs whose body tried a ranged skill (refusals, "broke off to shoot") | 4 of 11 |
| Lines telling the shooter how its own shot went / melee outcome lines | **0 / 42** |
| Wolf-related compiled graphs that read a stance (`believes`) | 4 of 170 |

### 2.2 One fight, traced (b5 `wolves-default-r1`, GLM Flash)

1. 726.4 s: a wolf bites (11 damage). It is the subject's fourth encounter with the same wolf by the same houses.
2. 728.1 s, think, 2.0 s: *"The wolf is on me again, barely two paces off — running got me cornered last time, so I stand and put an arrow in it."* Intentions: shoot the wolf (#310) with the bow; fall back to the house if badly hurt. Stance `wolf_must_die` 0.98, *"it has attacked me three times in one day by these houses; killing it is safer than fleeing."*
3. 731.5 s, compile, 3.4 s: a `safety` desire whose branch is `attack` (melee) the nearest wolf, and an act `attack #310`. The bow became a melee blow.
4. 735.4 s, think: *"The wolf's not in sight now — it may be circling beyond my vision."* The wolf had broken off; the plan arrived after the exchange.

The existing machinery did all of this, with nothing combat-specific: it noticed a repetition across encounters, revised an approach because of it, held the lesson as a stance, and answered within 5 s of the blow. It also shows the three ways it falls short: **the compile lost the intention** (bow → melee), **the revision landed after the exchange**, and **the body had no way to say "stand at range and shoot"** except one skill against one target.

### 2.3 Each thing the owner wants to see, against the evidence

| Wanted | Existing path | How far it gets (evidence) | Where it falls short |
|---|---|---|---|
| **Notice the opponent's skills, ranges and timings within a fight** | Percepts, the scene, fight reports → the think step writes stances and thoughts | Partly. 81 wolf stances, 21 thoughts on how wolves fight ("this is a pack: the lone-folk rule is out the window"; "it may be circling beyond my vision"; "winding up an attack at two paces"). | Percepts say what a creature does on novelty, not each move it shows; an `attacked` line has no skill and no distance; one's own shots report nothing (0 of 10 tries). Only one opponent kind tested. **Not shown against a person with a skill kit.** |
| **Change approach while the fight is on** | Urgent reason → think → compile → `combat` patch | Sometimes. A call finished in 9 of 25 fights; per call 3.3 s p50, so a full decision is about 5 s in the best case and 15–40 s in a loaded hour. | Most fights are one blow or under 20 s. The revision often lands after the exchange it answers (§2.2). Compile fidelity: of 102 thinks meaning to shoot, the next compile had a ranged skill in 46 and only melee in 14; one reply's act named `fire_bolt`, the technique, as a skill. |
| **Prepared schemes that apply on their own conditions** | Routines the mind writes, with `if` conditions; `desires` weigh them | Not measured. The runs show plans rewritten wholesale after each blow, not alternatives prepared before. | Graph conditions cannot name the move an opponent winds up, its phase, or a time; movement cannot express "hold this range" or "keep the wall between us" (18 of 140 thoughts tried). |
| **Beliefs steer behaviour without a re-plan** | `believes` reads stances the think step wrote | Barely used: 4 of 170 wolf-related graphs read a stance. | The cheap path from noticing to doing (write a stance; a routine that already reads it changes course on the next tick) exists and is unused. Whether minds would use it if prompted only by the grammar is the first thing to test (R2). |
| **A decision model times what the mind prepared** | `judged` (off by default) | The mechanism works: the graph reacted within one tick of the cache changing; it changed outcomes for the worse because the graph's answer was wrong (n = 3 per arm). | One declared question, refreshed every 4 s; its state lacks what the mind believes about the opponent. There is nothing prepared to choose among (row above). |
| **Lessons carry to the next encounter** | Experience → stance/belief → recall by cue | Yes within a life: 27 thoughts carried a lesson from an earlier encounter across 14 repeat fights (§2.2). | Not tested across separate fights with sleep between, nor to a different opponent. Fight beliefs fade with everything else (40 min effective confidence, stances relax), which may be too fast for "next week" (owner question 3). |
| **Transfer to another of its kind, or a stranger who fights alike** | Sleep generalizes specifics into patterns; recall by kind and by words | Generalization exists (`wolves_hunt_in_pack_here`). | A stranger who fights alike can only be recognised from words in percepts. Today those words are coarse ("attacked you"), so "throws fire from range, backs off when closed" never appears to be matched. |
| **Know one's own skills well enough to plan** | Skill reference (spec, takes, gives, cost from the script); practice; feedback | Specs give reach and cost; "a short windup" in words. | No windup, recovery or cooldown in ms in the minds' reference, although `skill_card` has them; no outcome for one's own shots (0 lines). What a skill is good against can only be learned from outcomes, and ranged outcomes never arrive. |
| **React inside a windup** | The graph's `threatened` at combat cadence | Instincts and minds' graphs use it (block, dodge, flee when threatened). | `threatened` is one bit: a 350 ms strike and a 750 ms heavy blow look the same, so a graph cannot answer them differently. |

### 2.4 What the shape "large model prepares, decision model times, execution stays live" holds and doesn't

The owner, on the middle layer:

> "Yes, exactly. And I think the big model basically prepares a bunch of schemes, and then the decision model decides more or less real-time when it's the good time to apply them. But then there is still live real-time execution of things, so that we are not bounded by the decision model."

Under the rule above, **a scheme is an ordinary routine the mind writes for itself**, with its own `if` conditions and its own reflexes. Nothing new is needed for that. What holds and what doesn't, with the numbers this project has:

| Layer | Runs on | Speed | Fit for | Too slow for |
|---|---|---|---|---|
| Reflex inside a routine | the tick | 67 ms combat cadence | answering a seen windup (strike 350 ms, heavy 650–750 ms), a punish window (strike recovery 250 ms), dodge and guard timing | — |
| Choosing among prepared routines | `desires` weights, `if` order, or `judged` read on the tick; a decision model refreshes `judged` | the read is instant; Jev 136–174 ms p50, 166–240 ms p95, plus delivery and a reducer call: about 0.25–0.4 s from a change to the graph acting on it | which prepared way to fight for the next seconds; when to commit, break off or rest one's breath | anything inside a 350 ms windup, a 250 ms recovery window, aiming |
| Revising one routine | a fast single-call model (proposed, §3.4) | about 1.8–4 s on talk-class calls | answering what the opponent showed in the last exchanges, between exchanges | the exchange it answers |
| Re-planning | think + compile | 5 s best, 15–40 s loaded | the next approach; what to do after the fight | most fights' exchanges (§2.1) |
| Learning | consolidation, sleep | minutes to a night | lessons about this opponent and its kind | anything in the fight |

- **Holds:** a body never waits for a model. Routines and their reflexes run on the tick while every model is slow or silent; a `judged` read with no fresh answer takes its `else`, which is the character's own fallback order.
- **Holds with a limit:** the decision model can decide *when* only at the scale of seconds. Timing inside an exchange belongs to the routine's own conditions. So "more or less real-time" is 2–4 choices a second at most. It does not conflict with the 2026-11-09 decision: the decision model chooses among what the mind prepared; it never answers a windup.
- **Doesn't hold yet:** there is nothing prepared to choose from. In the evidence, minds rewrite their plan after each blow and seldom prepare alternatives. Whether they would prepare routines for a fight if the grammar and feedback allowed it is an empirical question (R2) and must be answered before a decision model is worth adding.
- **Doesn't hold for the first fight against something new:** a mind cannot prepare for what it has not seen. That first fight is decided by the reflexes it already has and by revisions between exchanges. The second fight is where preparation pays, which is the owner's "much easier" (§4.3).
- **Doesn't hold if the decision model is given numbers:** Jev's documentation says it "is not a calculator" and "does not count reliably". Whatever it is given must be words and bands, built in code from the character's own perception, as the rethink gate's state already is.

## 3. The smallest general changes that would close each gap

Each change is general: it serves any time-critical thing a character does, with combat as the case that shows the need. None of them recognises a pattern, lists tactics, models an opponent or rewards a win. Each is to be shown necessary by a run before it is built (§5), and each comes with its own off switch so the arena can compare with and without.

### 3.1 The outcome of one's own act reaches the doer (perception, authority)

- **Gap:** 0 lines told a shooter how its shot went, against 42 for melee (§2.1). A mind cannot learn what its bow is good for. The same holds for a thrown spear, and for any act whose effect lands away from the doer: a rope thrown to someone in the water, a call that reaches no one.
- **Change:** the release and the impact of a ranged move become the doer's experience as the doer perceives them, like melee's "You finished: attack → wolf. hit for 7": "Your arrow struck the wolf (14)", "your arrow went past it", "your fire bolt hit the wall", or nothing seen if it flew out of sight. This is the existing outcome rule (truthful feedback, "Distinguish intention, attempt, failure, accepted operation and actual physical outcome") applied to the acts it missed.
- **Data path:** one `experience` row per ranged release to its doer, at most one per cooldown (900 ms for a bow); `act.rs` already writes the missile's outcome to `skill_use` and `combat_seen`. No new table. Novelty folding (as for repeated failures) keeps a long exchange from flooding consolidation.

### 3.2 Seeing what someone is doing, as it looks, with its timing (perception, rules)

- **Gap:** `threatened` is one bit. A graph cannot answer a 750 ms heavy blow differently from a 350 ms strike, a raised guard differently from a lowered one, or "they are drawing a bow". Percepts name a creature's activity only on novelty, so the words a stranger "fights like" never reach memory or recall.
- **Change, condition:** `{"doing": {"who": T, "is": "<what it looks like>", "phase": "winding up" | "releasing" | "recovering" | "holding"}}` reads the perceived target's `fighter`/`doing` row: what a player sees drawn on screen, under the same sight and facing rules. `is` takes the presentation words of a skill card or act card (`strike`, `bow shot`, `guard`, and so on), so a new skill works without Rust. `phase` with an optional `left_ms` bound lets a routine time itself ("strike while they recover").
- **Change, percept:** when a creature someone is fighting or watching starts a move aimed at them, the observer's experience names it and the distance once per move kind and fight, then folds repeats ("Grim winds up a fire bolt at you from 12 m" once, then "… again (×3)"). These are words for memory and recall to work on; nothing counts or classifies them for the mind.
- **General use:** a child reaching the edge of a terrace, a seller packing up a stall, someone reaching for what you hold.
- **Data path:** the condition is one primary-key read of a row the tick already reads in the chunk cache; percepts are bounded per move and witness and folded; no new table. Players already receive the same rows through `seen_fighters`.
- **Built** (`doing-percept`, 2026-11-12; [perception](PERCEPTION.md#what-someone-is-visibly-doing)): the condition as `{"doing": {"who", "is", "phase", "at_me", "within"}}` and each seen creature's `visibly` in a mind's scene. Changes from the text above: `is` takes a skill's name, its label or a kind word (`hostile`, `melee`, `missile`, `guard`, `dash`, an act card's look); the windup is split into `winding up` and `about to release` (its halves, as the clip's run-up and its approach to the peak), plus `under way` for an act card; no `left_ms` (the drawing shows a phase, not milliseconds). The folded experience percept above is not built yet.
- **Committed moves** (`committed-moves`, 2026-11-12, [combat](COMBAT.md#committed-moves)): a routine's dodge started on `doing` (or `threatened`) runs its course when the dash turns its back on the attacker, as a player's does; a started windup or dash is never ended by its condition going.

### 3.3 Movement as intent the body carries out (steering, rules)

- **Gap:** 18 of 140 wolf-related deliberations stated a spatial intent the grammar can only approximate with a `goto` to a point: "keep the wall at my back", "put distance and a shot into this one", "keep the house between me and the pack". There is no way to hold a range, circle, or keep something between oneself and a creature.
- **Change:** steering goals that already half exist (`follow` keeps a distance, `flee` keeps away), made general and offered as movement skills with specs in the script:
  - `keep_range {target, from, to}`: stay within a distance band, closing or backing off as it moves;
  - `circle {target, side, range}`: move around it at a range;
  - `screen {target}`: put the nearest thing that blocks sight or passage (a wall, a house, a shut gate) between oneself and it, by scoring nearby points with the sight rule;
  - `back_off {from, to}`: step away to a distance and stop, facing it.
- **Same for every controller:** these are ways for a graph to steer, as WASD is for a player; speed, turning, running costs (stamina), collisions and sight are the shared rules. A player gets nothing a mind lacks, and the reverse.
- **General use:** herding, escorting a child, keeping a polite distance, following someone unseen, a chase.
- **Data path:** new goal kinds in the private `steer` table, written when a goal changes; steering keeps its cadence (8 Hz in a fight). `screen` scores a bounded set of points (on start and on each re-plan) with the existing sight sweep. To be measured at the 216-character gate before it counts as accepted.

### 3.4 A fast lane between the routine and the slow mind (mind architecture)

- **Gap:** a full decision is think then compile, 5 s at best and 15–40 s when loaded (§2.1, §1.3). The compile is also where intentions are lost (14 ranged intentions compiled melee-only, against 46 kept; `fire_bolt` written as a skill).
- **Change:** for urgent reasons the mind already never holds (being attacked, a fight report, a child in danger), one call on the fastest acceptable model that writes **one routine or one labelled patch** in the graph grammar, in the character's own words and stances, instead of a full think and compile. The slow deliberation still follows when it is due. This is a lane in the mind service, chosen by urgency, not by subject.
- **Model:** DeepSeek V4.1 Flash with thinking off answered talk-sized prompts at 1.8 s p50 and compiled at 3.8 s p50 in a good hour (MODEL_COST); its compile quality without thinking was judged weak (5/24), so this lane must be measured for intention fidelity, not assumed.
- **What it must not become:** a combat planner. Its prompt is the character's own situation, stances and routines and the grammar; it holds no tactic text, and the rules text keeps physics only.

### 3.5 A decision model that picks among what the mind prepared (mind architecture)

- **Gap:** minds rarely use the cheap path from belief to behaviour (4 of 170 graphs read a stance) and have no way to switch between prepared approaches faster than a re-plan.
- **Change:** generalize `judged` from declared questions to one general question per character, "which of your prepared ways fits this moment?", whose options are the routines the mind itself has named as alternatives (an `or` group in its top level, or routines it marks as ways of doing one thing), and whose state is the character's current perception and the stances and beliefs recall brings for who is in sight, in words and bands. The graph reads it with the existing `{"judged": {"q": …, "is": …}}`; each routine's own `if` still guards it, and with no fresh answer the graph falls to the mind's own order.
- **When asked:** on a salient change in what the character perceives (a new move shown, a band of distance or health crossed, a routine failing), at most 2–4 times a second, only for on-stage characters. Never per tick.
- **Too slow for** everything in the first row of the table in §2.4.
- **Not before R2:** only if minds, given §3.1–3.4, prepare alternative routines at all. Without alternatives, a chooser has nothing to choose.
- **Data path:** the existing private `judged` table (at most 8 rows per character; the reducer `mind_judged`) and the existing Jev request; at 216 on-stage fighters and 4 Hz this is up to about 860 reducer calls a second and must be measured before it counts as accepted. Jev cost at about 900 input tokens: $0.00004 a judgment.

### 3.6 Memory readable within seconds (mind architecture, small)

- **Gap:** the think step writes stances at once (`wolf_must_die` 0.98, two seconds after the bite), and recall takes 4–15 ms, so most of "memory within seconds" exists. What is missing is that the fast readers do not see it: the decision model's state (`judge.rs` `judge_state`) holds goals, plan, temperament, body and the last ten experiences, not what the character believes about the one in front of it.
- **Change:** the fast lane (§3.4) and the decision model (§3.5) are given the same situational recall the slow deliberation gets, with a smaller budget: the stances, beliefs and memories that the perceived creature, its kind and the latest percepts' words bring to mind.

### 3.7 Rules facts the minds are told (prompts, small)

The minds' skill reference gives reach and cost but says "a short windup". Windup, recovery and cooldown in ms, and under `stamina-1` each skill's pool, are rules facts like reach, and `skill_card` already holds them. Add them to the reference from the same script numbers. Nothing about what a skill is good against: that stays for the character to learn from outcomes (§3.1).

### 3.8 What the owner's three descriptions become under these changes

- **Schemes** are routines a mind writes for itself, with conditions it chooses (§3.2's `doing`, `near`, `believes`, stamina), movement it can now say (§3.3) and its own reflexes. Prepared between exchanges by the fast lane (§3.4), between fights by deliberation, retired by the mind as any routine is (`routine_stat` shows how each has gone). At most 40 routines, shared with the rest of life.
- **The working picture of an opponent** is what the mind holds about that person or creature: the stances, beliefs and memories it writes as it perceives the fight, from percepts that now name each move and its outcome (§3.1, §3.2). It is the market's "who cheats" machinery. It changes choices while the fight is on through `believes` in its routines, through the decision model's state (§3.6) and through the fast lane's next routine. Nothing tabulates it for the mind.
- **What carries over** is what consolidation keeps and sleep generalizes: beliefs about `person:<id>`, about `kind:wolf`, and patterns the mind forms itself ("those who throw fire keep their distance"). Routines it wrote stay until it retires them. The same opponent is found again because perceiving it cues its concept; another of its kind through `kind:`; a stranger who fights alike through the words of the moves it shows, which recall matches against the mind's own keys and gists. How early: by kind at first sight; by way of fighting after the first moves are perceived and named, seconds into the fight, if the mind thinks then (being attacked is an urgent reason). Nothing is copied: what a character learns is what it lived, what it watched (witnessed percepts, under sight rules), or what it was told (hearsay, attributed, fading twice as fast) or taught (a routine "taught by <name>"). It fades like everything else unless used.

## 4. How we would tell it emerged and wasn't put there

### 4.1 Arenas are trials

An arena is a [trial](TRIALS.md): a JSON file in `living/trials/` with a cast whose graphs come from the trial file through `set_behavior`, timeline steps, variants and probes, run by `trials.py` on the trials stack. No engine code knows about arenas.

- **Opponents are fixtures**, written with the shared skills only and kept in the trial files. Each has one learnable pattern built from a pool of conditions (not a fixed loop, or a mind learns a loop and nothing that transfers):
  - **heavy telegraph:** opens with `attack` (650–750 ms windup) at close range, strikes otherwise; the answer that fits is leaving reach, dodging or guarding during the heavy windup, and striking in its recovery;
  - **kiter:** `bowshot` beyond 8 m, backs off when closed (`flee` until §3.3 exists, then `keep_range`); the answer that fits is closing through cover or a dodge, breaking sight, or out-ranging;
  - **guard that punishes greed:** raises `block` when threatened and strikes after its guard has taken a blow; the answer that fits is fewer strikes into a raised guard, timing a strike after it drops, or a flank when facing matters (`fov_on`);
  - **switcher:** one pattern, then another from a timeline step mid-fight; the answer that fits is dropping the first answer and finding the second;
  - **control:** the same skills at random, no pattern.
- **Nothing learned is installed.** Characters keep what they learn only in their own world's memory; arena worlds are deleted after the evidence is taken; no routine, stance or prompt text moves from an arena into a seed.
- **Guards against putting it there:**
  - an audit of every prompt sent in the run for the fixture's pattern words or tactic text (none may appear outside the character's own experiences and memory);
  - the rules text unchanged from main: the runner records the installed skills file's sha256 (`skills.sha256`), to be compared with main's;
  - arms that remove the cause: a control opponent with no pattern; a fresh character against a veteran; each change of §3 switched off, to show which one the behaviour depends on.

### 4.2 Measure 1, first: adaptation within one fight

Against a fixture with a learnable pattern, within a single fight:

- **Does behaviour change after the pattern has been seen?** For each exposure *k* (a perceived occurrence of the pattern, from the authority's `skill_use` and the subject's experiences), whether the subject's response fits the pattern (as declared above), against its rate in the control arm.
- **How many exposures does it take?** The first *k* after which the response fits at three exposures running, per replicate, reported as the distribution over replicates.
- **Does the change fit what was seen?** The share of the behaviour change that fits the pattern, against change that does not (a subject that switches to anything different on being hurt has changed, not adapted). The switcher arm checks that the answer follows the pattern, not the time.
- **Which layer produced it?** From the journal and graph revisions: an existing reflex, a stance a routine read, a fast-lane routine, a full re-plan, or the decision model's choice.
- **What did it notice?** After the fight, the character's stances and beliefs about the opponent against what the opponent actually showed in its sight: listed and correct, listed and wrong, shown and missed, and anything it could not have perceived (a leak).

### 4.3 Measure 2: across fights, and transfer

"Much easier", the owner's words, should show in the outcome, the damage taken and how quickly the right approach appears.

- **Setup:** a character fights fixture A (pattern P) several times with real time and a night of sleep between (so consolidation and generalization run as in life), then meets fixture B: a different identity with a similar pattern. Arms:
  - **veteran → same kind:** B is another of A's kind with P;
  - **veteran → stranger:** B is a different kind or person that fights with P;
  - **fresh:** the same authored sheet, no earlier fights, meets B;
  - **veteran → lookalike:** B is A's kind with a different pattern, to show the lesson is not applied blindly.
- **Measures:** survived and won; damage taken; time and exposures to the first fitting response (Measure 1's *k* against B); the first moment the veteran's thoughts or recall connect B with A or with the pattern; routines it had ready at the start of the fight with B and whether it used them.
- **Reading:** easier is the veteran ahead of the fresh character on these, by more than the spread between replicates. No threshold is set before the first baseline shows the spread.

### 4.4 The other measures, decided before any run

- **Who wins and how:** outcome, time, health at the end, breath and focus spent.
- **Skill-use fitness:** per skill, uses, outcomes (from `skill_use`) and damage per stamina or focus spent; refusals by reason ("not ready", "out of breath").
- **Reaction against the rules' windows:** from a perceived windup's start to the answer's start, against the windup's length; how often an answer lands inside it.
- **Cost and latency per fight:** calls, tokens and money by purpose and model; latency per layer, p50 and p95.
- **Reads as a player:** the owner's ratings of short recordings (the reference), with the character's own account after the fight beside them. An automatic score only screens; the [feel-score caveats](TRIALS.md#owner-tuned-player-score) apply.
- **A human-played condition, when the laptop can supply one.** The owner's own fights are the reference for "reads as a player". A recorded session of the owner's character fighting a fixture (the laptop's play-tests: the `skill_use` rows with source `player`, the `combat_seen` feed and the client recording) is scored with the same measures as the minds: Measure 1's exposures and fit, damage taken, reaction against the windows. The minds' numbers are then read against a person's on the same fixture, and the owner's ratings compare recordings of both, unlabelled. Until a session exists, this condition is empty, not estimated.

### 4.5 Which existing tools fit

| Tool | Fit |
|---|---|
| [`trials.py`](../living/tools/trials.py) | The home: cast, timeline, variants, probes, replicates, evidence, ledger. Arenas are trial files plus probes. |
| [`judged_fight.py`](../living/tools/judged_fight.py) | The pattern for a defender against scripted attackers with fake and real arms and 1 s samples; its scene setup ports to a trial file. |
| [`duel.py`](../living/tools/duel.py) | Two minds with a feud; the base for LLM against LLM. Dated (September): its own publish path, `spawn_crowd` walkers, 2 s samples, the journal's old layout. Port to the trials format rather than revive. |
| [`combat_scene.py`](../living/tools/combat_scene.py) | Puts a connected game client among residents for photographs; the way the owner can fight the fixtures personally and compare. |
| `scenes.py skirmish` (verify-core) | Two sides of graph fighters; for group combat, later. |
| [`fight_mind_audit.py`](../living/tools/fight_mind_audit.py) | The read-only audit of §2.1; extend with `skill_use` once trial evidence keeps it. |

**The baseline waits** for `stamina-1` (fights paced by breath), the facing-sight law on main (`fov_on`, so guards, flanks and backstabs mean what they will in the game) and the dev-box's `look-2` (not on origin yet; not read here).

## 5. Runs to schedule

Nothing below was run this turn. Free runs first; paid runs only when authorized.

| Run | What it shows | Tier | Command / setup | Cost |
|---|---|---|---|---|
| **R0** (done) | What existing minds do in fights | read-only | §2.1 | none |
| **R1** (done 2026-11-11, §5.1) | The pipeline's floor: from a blow to an installed revision with an instant model, so the model's share of §2.1's latency is known | free, `--fake` | in a trials checkout ([the Spark setup](TRIALS.md#the-spark-setup)): `trials.py build wolves`, `trials.py run --batch cm0 wolves --replicates 4 --fake`, then `fight_mind_audit.py .local/living/trials/cm0/wolves-*` | none |
| **R2** | With nothing changed: against the heavy-telegraph and kiter fixtures, does a mind on main notice the pattern within a fight, change, and prepare routines for it? Measure 1 with today's machinery | small paid | two trial files (`arena-heavy`, `arena-kiter`): the island seed, a spawned subject with a bow and spear, one fixture placed 6 m away after 60 s; 10 minutes; 6 replicates each on `default`. `trials.py run --batch cm1 arena-heavy arena-kiter --replicates 6` | about 12 runs × $0.05–0.10 (b5 averaged $0.04 a run, wolves the dearest) ≈ **$1** |
| **R3** | Across fights with what exists: fixture A met four times over two game days with sleep between, then B, against fresh subjects meeting B (Measure 2) | small paid | a life-length trial (`arena-veteran`) with timeline steps placing A at four times and B at the end, `life.stop_on_death: false`; fresh arm = the same file without the A steps; 4 replicates per arm, 60 minutes | about 8 runs × $0.15 ≈ **$1.20** |
| **R4** | Each change of §3 against R2 and R3, as arms with their switches | free first (`--fake`, plumbing), then small paid | after each change is built and verified on its surface skill | about **$2** per change |

### 5.1 R1: the pipeline's floor (2026-11-11)

Batch `cm0`: `wolves`, 4 replicates, `--fake` (every model call answered at once by the fake server), built from `design-combat-mind` at 2f74f801 (main 4b76ef41 plus docs). Two of the four subjects were attacked: 5 fights, one death. Measured from each fight's first blow (`at_ms` of the `attacked` experience) to the first think reply (journal) and to the first installed plan (the deliberate thought row), against the same measure over the 32 real-model runs of §2.1:

| From the first blow | Fake model (R1), n = 5: p50 / max | Real models (b4–b6b), n = 24 / 23: p50 |
|---|---:|---:|
| to the think reply | 0.7 / 1.4 s | 3.8 s |
| to the plan installed | 1.4 / 2.2 s | 8.6 s |

- **The model is about 84% of the delay** from a blow to a new plan (7.2 of 8.6 s at p50). The rest, about 1.4 s, is the pipeline: the authority's reason, the deliberation request, the mind's pickup, two calls and the install. That floor is four times a strike's windup, so no deliberation, however fast its model, answers inside an exchange; it is the budget a fast lane (§3.4) starts from.
- **Against the table in §2.3:** R1 confirms the "change approach while the fight is on" row's cause: the shortfall is mostly the model's time, not the plumbing. A fast lane with one call at about 2 s would put a new routine about 3 s after a blow, inside the 19 s p90 fight, where the two-call path at 8.6 s p50 mostly is not. The rows about noticing, carrying lessons and using stances cannot be shown with a fake model (its replies are fixed); R1 shows nothing about them, by design.
- **Evidence:** `.local/living/trials/cm0/` and `.local/living/combat-mind/fight_audit-cm0-fake.json` on the Spark (git-ignored); `fight_mind_audit.py --fake` reads them. The batch's databases and minds were removed with `trials.py clean --batch cm0`; the evidence stays.

### 5.2 What the told outcome lines cost in a battle (2026-11-12)

§3.1's lines (`force_outcomes`) measured in a battle of minds, as agreed before R2. Build: origin/main `5d5ce4e1` (stamina-1, both combat facts and the attack-timing text in), module built on the Spark, trial service `slop-trials-stdb`. Scene: a scratch `verify-core` world on the default seed (`core-r2cost-025725`), **about 187 people alive** (186–188), plus **20 mind-held spear fighters** (`spawn_crowd(20, true)`, so their outcomes are told; no mind service), packed 1.5 m apart, each striking the nearest person in reach. Each arm is a fresh battle, timed by `bench.py` over a 22 s window (profiled tick spans, no subscribers); the fighters' new experience rows were read during the window, so the lines of those who died are counted. Tool: `living/tools/outcome_cost.py` (branch `arena-r2`).

| | `force_outcomes` on | off |
|---|---:|---:|
| Blows a second (hits, dodged, blocked) | **9.2** | 8.9 |
| Told strike lines a second (done + failed) | 14.4 (10.6 + 3.8) | 3.8 (failed only) |
| `act_outcome` rows | 0 | 0 |
| Tick p50 / p95 / p99 / max (ms) | 1.68 / 3.60 / 5.58 / 7.21 | 1.72 / 3.40 / 5.12 / 6.59 |
| `tick.combat` work (ms a second) | 8.29 | 8.23 |
| `tick.activity` work (ms a second) | 3.89 | 3.81 |

- The law adds one experience row per resolved blow, to the striker only: about 10.6 rows a second at 9.2 blows a second. Failures are told either way, each refusal once per `repeat_failure_s`.
- The tick does not show it: the differences between the arms are within one battle's variation. **At 20 fighters it is not material.**
- `act_outcome` rows are written only for a character a person plays (`outcomes::write`): none here. A played character gets one per told line, kept with its newest 64 lines (`frame::LINES_SHOWN`).
- Not measured: the contract's 200-character battle of minds, where the same rate would be about ten times this (a row per blow).

R2 and R3 need the trial files written (fixtures only); this turn is docs-only, so they are described, not added. R2 before any of §3 is built: if minds already prepare and use routines for a pattern, §3.5 is not needed yet, and §3.2–3.4 are judged by how much they add.

## 6. What stays the same for players and AI, and what must never become a guard

**The same for every controller:** skills, costs, pools, timing, reach, guard arcs, dashes, steering, running costs, perception and the outcome of every act. A player decides with hands; a mind with routines, a fast lane, a decision model and deliberation. The movement intents of §3.3 are steering for graphs, not abilities a player lacks. No artificial reaction delay is added for AI: a mind's answers already pass through a 67 ms cadence and, above reflexes, a model.

**Never a guard on what a character decides:**

- no engine rule that limits who may attack whom or when (no attack tokens, no turn-taking);
- no automatic dodge, block or flee;
- no tactic text in the rules, prompts or seeds; the rules keep physics;
- no fixture behaviour, routine or lesson from an arena in a seed or a character;
- no veto by the decision model: its answer is a cached value the character's own graph may read or ignore;
- no code that decides what an opponent "is" or how it fights for the mind;
- no reward for winning;
- no limit on what a routine may contain beyond the grammar's validity and its size limits.

## 7. SpacetimeDB documentation consulted (2026-11-11)

Pinned: `spacetimedb = "=2.14.1"`; docs version 2.0.0.

- [Tables](https://spacetimedb.com/docs/tables/) and [access permissions](https://spacetimedb.com/docs/tables/access-permissions): private tables are "visible only to reducers and the database owner"; "clients cannot query, subscribe to, or see private tables". The mind service already reads private tables (`vitals`, `judged`, `routine`) as the owner, which is this repository's versioned evidence that the owner's client can.
- [Performance](https://spacetimedb.com/docs/tables/performance/): "break large tables into smaller, more focused tables"; fewer fields touched per update. §3.1–3.3 add no table and no column to a hot public row.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): "keep subscriptions small" with precise filters. Nothing here widens the mind service's subscriptions; §3.5 reads its cache.
- [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/): new steering goal kinds live inside the existing private `steer` row's encoding; no new column is planned.

## 8. Open questions for the owner

Open: the owner has not decided these. Each carries the general coordinator's recommendation (2026-11-11), which is not a decision.

1. **Fight length.** By today's numbers a 1v1 lasts seconds to tens of seconds, and the wolves' exchanges were one to a few blows. Revision between exchanges needs exchanges to be seconds apart. Stamina paces fights by breath; is a longer, breath-paced duel the feel you want, or should adaptation mostly show in the second fight?
   - *Recommendation:* fights between equals last long enough for several exchanges, tens of seconds, not one blow. The way there is health, damage and stamina pacing as law values in the script, not modes: every blow still does its full damage (the "one damage rule" of 2026-11-09 stands).
2. **The first fight against something new** is decided by reflexes and quick revisions, not preparation. Is that acceptable, with "much easier" expected from the second?
   - *Recommendation:* yes. The first fight is decided by the reflexes the character already has and by quick revisions; "much easier" is expected from the second (Measure 2, §4.3).
3. **How long fight lessons last.** Beliefs fade with a 40-minute effective confidence and stances relax unless reinforced. Should knowing how a wolf fights last longer, and if so as a rule for all lived lessons, not only combat?
   - *Recommendation:* lessons from what happened to the character last longer, for every kind of lesson, not only combat, with their strength tied to how much the event mattered (its salience).
4. **Watching.** A character that watches a fight in sight perceives it under the sight rules. Should it learn from that as it learns from its own fights (weaker, but lived)?
   - *Recommendation:* yes: a character learns from a fight it watches, under the sight rules, more weakly than from fighting it and more strongly than from being told.
5. **The fast lane's model.** DeepSeek without thinking is the fastest measured, and its compile quality without thinking was judged weak. Is a paid fidelity check (R4, about $2) acceptable before choosing?
