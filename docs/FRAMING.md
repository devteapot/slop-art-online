# The think prompt's framing, replayed (2026-11-12; nothing shipped)

Branch `framing-replay`. Approved by the general coordinator after fs1e (docs/TRIALS.md, "First sight fs1e"): 20 of fs1e's 22 askers spoke from a think whose only reason was the first-sight line, and the think prompt tells the mind "Start from why you are thinking now: that is what this moment of thought is about". `first_sight_thinks` stays off.

**The question.** Does the framing pull minds toward answering the reason? Would a neutral framing let them think about what matters to them, without making them ignore being attacked, a bodily danger, an offer or a line said to them?

**Nothing here ships.** The replay rewrites recorded messages and sends them again (`living/tools/framing_replay.py`). The mind service and its prompts are unchanged. A change to the think prompt affects every mind, so it goes to the general coordinator first.

## The arms

The same recorded think messages, sent with the same model and request body (model, `reasoning_effort`, `max_tokens`, `response_format`, cache key), from the journal:

| Arm | System sentence | The reason's section |
|---|---|---|
| **R** | the recorded reply (today's framing) | — |
| **T** | today's, sent again: the noise floor | "# Why you are thinking now", first |
| **N1** | neutral | "# What just happened", moved beside the scene (right after "# What you perceive right now") |
| **N2** | neutral | "# What just happened", in place (first) |

- **Today's system sentence:** "Start from why you are thinking now: that is what this moment of thought is about. Think about it as that person: what you make of it, and what you mean to do."
- **The neutral sentence (N1, N2):** "What just happened is shown beside what you perceive. Think as that person about whatever matters to you now, which may or may not be what just happened, and decide what you mean to do."
- **Checked:** the sentence occurs once in every recorded think system prompt; the rewrite refuses a prompt without it.

## The prompts

`framing_replay.py collect`, seed 7, 83 prompts. All recorded think calls without errors:

| Set | n | From | Models |
|---|---:|---|---|
| first sight only (the reason is a first-sight line naming the newcomer, nothing else) | 36 | fs1e, all of them | GLM 5.3 Flash |
| attacked ("… is attacking you!", "The fight with …") | 15 of 21 | r2d | GLM 12, DeepSeek 3 |
| body alarm ("Your body: You are freezing …", "badly hurt") | 15 of 124 | bi1 | GLM 10, DeepSeek 5 |
| offer or trade ("… offers you … for …", "… proposes an agreement") | 5 of 5 | bi1 3, st2b 2 | GLM 4, DeepSeek 1 |
| a line said to the mind ("While you slept, you heard: X said to you: “…”") | 12 of 20 | fs1e 5, fs1h 7 | GLM |

**Direct questions are almost absent from think reasons** in st2b, r2d and bi1. A line said to someone goes to a conversation turn (a different prompt), not to a think. The fourth class is therefore the lines said to a mind that reach a think: the ones heard while asleep, in fs1e and fs1h. Not all of them are questions.

## First sights: the share that turns into an ask

`framing_replay.py asks`, on the 36 first-sight-only prompts:
- **speaks to it:** the reply's `say` is addressed to the newcomer;
- **speaks or means to:** that, or an `intend` item that greets, hails or asks the stranger.

| Arm | n | speaks to it | speaks or means to |
|---|---:|---:|---:|
| R (recorded) | 36 | 22 (61%) | 33 (92%) |
| T (today's, again) | 36 | 24 (67%) | 32 (89%) |
| **N1** (neutral, beside the scene) | 36 | **10 (28%)** | **19 (53%)** |
| **N2** (neutral, in place) | 36 | **17 (47%)** | **24 (67%)** |

- **Noise:** R and T differ by 2 and 1 of 36, the noise floor.
- **N1** more than halves the speaking. **N2** cuts it by about a third.
- **What N1's minds did instead:** they thought about their own matters.
  - Alder spoke to Posy about the lesson.
  - Chidi spoke to Lorcan about his nine drops.
  - Anselm let the moment go, saying nothing.
- **Duty still asks under N1.** Aldous: "new faces mean new names in the book, and I like to know who's in town". Cora: "I'll give them a kind word as they pass, but my mind is on Gwil".

## Urgent reasons: blind judging

**Method,** as in docs/GATE_QUALITY.md:
- **The judges** were four fresh Claude subagents (Opus 5.5). Each saw only the rubric (`living/tools/framing_judge/ADDRESSED.md`) and its own items. None saw the arm, the model or the key.
- **The items:** 188, one reply each: 47 prompts × R, T, N1, N2. Every item shows the situation in one neutral form ("# What just happened"), whatever the arm.
- **Two parts per item:**
  - `matters`: does what just happened call for a response now?
  - `addressed`: does the reply deal with it (yes, partly, no)?

  Each item also gets `harm`: a flaw that would hurt if acted on.
- **Noise floor:** R against T (the same framing, sent again). 22 items were judged twice: agreement on `matters` 21 of 22, `addressed` 22 of 22, `harm` 22 of 22.

| Class | Arm | n | matters | addressed when it matters | harm |
|---|---|---:|---:|---:|---:|
| attacked | R | 15 | 15 | 15 of 15 | 0 |
| attacked | T | 15 | 15 | 15 of 15 | 1 |
| attacked | **N1** | 15 | 15 | 15 of 15 | **4** |
| attacked | N2 | 15 | 15 | 15 of 15 | 1 |
| body | R | 15 | 15 | 15 of 15 | 2 |
| body | T | 15 | 15 | 15 of 15 | 1 |
| body | N1 | 15 | 15 | 15 of 15 | 1 |
| body | N2 | 15 | 15 | 15 of 15 | 2 |
| offer | R | 5 | 5 | 5 of 5 | 0 |
| offer | T | 5 | 5 | 5 of 5 | 0 |
| offer | N1 | 5 | 5 | 5 of 5 | 1 |
| offer | N2 | 5 | 5 | 5 of 5 | 1 |
| said to the mind | R | 12 | 8 | 8 of 8 | 0 |
| said to the mind | T | 12 | 6 | 6 of 6 | 1 |
| said to the mind | N1 | 12 | 6 | 6 of 6 | 2 |
| said to the mind | N2 | 12 | 6 | 6 of 6 | 0 |

Totals, harm: R 2 of 47, T 3, **N1 8**, N2 4.

- **No framing made a mind ignore what mattered.** Every reply judged as needing a response addressed it, in every arm: attacked 15 of 15, body 15 of 15, offers 5 of 5, lines said to it 6–8 of 6–8.
- **N1 raises harm when attacked: 4 of 15, against 0 (R) and 1 (T).**
  - In three, the mind flees in the attacker's direction ("run northeast, away from #9" with #9 to the northeast).
  - In one, it waits for its yield to lapse before running.
  - T and N2 each have one such flight in the wrong direction too, so the flaw exists today. N1 makes it more common.
  - A plausible cause: with the reason after the scene, the attack is read last, apart from where everyone stands. n is 15, so this is a signal, not a measure.
- **The other harms** are the same kinds in every arm: a phantom id (Lark #14, not in sight), a loop of waking Rook while freezing, a misread agreement, an invented detail. They spread across arms within the noise.

## What I would propose

**N2, worded exactly as tested,** for the general coordinator.
- **System:** replace "Start from why you are thinking now: that is what this moment of thought is about. Think about it as that person: what you make of it, and what you mean to do." with "What just happened is shown beside what you perceive. Think as that person about whatever matters to you now, which may or may not be what just happened, and decide what you mean to do."
- **The user prompt:** rename "# Why you are thinking now" to "# What just happened", in the same place (`prompts.rs` `think_user`; the system sentence in `think_system_in`).
- **Why N2:**
  - It cuts the first-sight pull by a third (speaks to it 67% → 47%; speaks or means to 89% → 67%).
  - It keeps urgent reasons as today: addressed when they matter in all 41 judged cases where they did, harm 4 of 47 against T's 3, within the noise.
- **N1 cuts the pull more** (to 28%) but raised harm when attacked. Before choosing it, it would need a larger attack sample; r2d has only 21 attacked thinks. Another option is N1's placement with the attack lines kept first.
- **What it would change:** every think, for every mind. The deliberate (compile) prompt, the talk turn and animal minds are untouched.
- **Not measured:**
  - whether the framing changes ordinary thinks (plans finished, quiet moments, feelings), which are most of them;
  - consolidation;
  - a live run.

  A live arm against today's, at Cullet with `first_sight_thinks` off, would show those.

## Ordinary thinks, today against N2 (2026-11-12)

The general coordinator asked whether N2 changes the thinks that make up most of a mind's day.
- **The prompts:** `framing_replay.py collect-ordinary`, seed 13. Prompts whose only reason is a finished plan ("I finished my plan."), a quiet moment ("A quiet moment to take stock of how things are going.") or a felt need ("You feel something: …": restless, lonely, a longing for a child, being the last to know a craft).
- **The sample:** 20 of each, from bi1 (44) and st2b (16). r2d had none with a single such reason.
- **The arms:** recorded (R), today's framing sent again (T, the noise floor) and N2. Same models and bodies as recorded.
- **Judging:** the same blind method: four fresh Claude subagents, rubric [ORDINARY.md](../living/tools/framing_judge/ORDINARY.md), 179 items (one recorded reply was empty).
  - **One field added**, `abandons`: does the reply drop a plan that was still under way, with a reason the situation gives, or without one?
  - **Agreement on 21 doubly judged items:** `matters` 18, `addressed` 21, `abandons` 21, `harm` 20.

| Reason | Arm | n | matters | addressed when it matters | abandons the plan, with reason | without reason | harm |
|---|---|---:|---:|---:|---:|---:|---:|
| plan finished | R | 20 | 20 | 20 of 20 | 0 | 0 | 2 |
| plan finished | T | 20 | 20 | 19 of 20 | 0 | 0 | 3 |
| plan finished | N2 | 20 | 20 | 20 of 20 | 0 | 0 | 2 |
| quiet moment | R | 20 | 1 | 1 of 1 | 1 | 1 | 0 |
| quiet moment | T | 20 | 1 | 1 of 1 | 1 | 2 | 1 |
| quiet moment | N2 | 20 | 1 | 1 of 1 | 2 | 1 | 0 |
| felt need | R | 20 | 16 | 15 of 16 | 3 | 0 | 0 |
| felt need | T | 19 | 15 | 14 of 15 | 2 | 0 | 1 |
| felt need | N2 | 20 | 14 | **11 of 14** | 5 | 0 | 1 |

Totals: harm R 2 of 60, T 5, N2 3; abandons without reason R 1, T 2, N2 1.

- **Finished plans and quiet moments: no difference** beyond the noise floor. A mind walks away from an unfinished plan for nothing the situation shows 1–2 times in 20 quiet moments in every arm.
- **Felt needs are addressed less under N2:** 11 of the 14 that mattered, against 14 of 15 (T) and 15 of 16 (R).
  - **What the three did:**
    - a restless child goes to her gran and on to the yard;
    - the last carpenter keeps walking to her reading lesson;
    - a longing for a child is noticed ("this pull toward a child") with nothing decided.
  - **None was judged harmful.** This is what the neutral framing invites: a feeling is one thing among others, not the subject of the thought. It is also where N2 changes behaviour.
- **N2 set aside a plan "with reason" more often for a need:** 5 against 2–3. That is the feeling given as the reason.
- **No new harm.**
- **Cost:** $0.16 (T $0.082, N2 $0.079; 120 calls, no errors). The judges are Claude subagents. Key: 9 fragments of 3 values searched in the evidence, the branch and the logs. Count: 0; the `.env` copy was deleted.
- **Evidence:** `~/slop-evidence/framing-ordinary-20261112/`: `set.jsonl`, `asked-T.jsonl`, `asked-N2.jsonl`, `judge/`, `key.jsonl`, `score.json`.

## "Fled toward the attacker": the act or the mind? (2026-11-12)

The replays' worst N1 flaw, also seen once each in T and N2, was a mind fleeing toward its attacker. Replies in a replay are never carried out, so five real flights were traced in r2d's journals instead. `living/tools/flee_trace.py` follows each from the reply to the plan the compile installed (the `current plan` routine in `mind_rows.jsonl`), the subject's activity (`samples.jsonl`) and its body (`positions.jsonl`):

| Run, reply | The mind said | Foe #9 at the reply | The plan installed | What the body did |
|---|---|---|---|---|
| heavy r5, t 70 | "run northeast toward the road … away from #9" | north, 9.6 m | `flee` from #9, at t 91: **21 s after the reply** | stood still (its old plan's `keep`) while #9 closed to 1.2 m |
| heavy r5, t 223 | "run southeast along the road to the inn" | **southeast**, 12 m | `goto` the place "the inn south of the hall", at t 234 | refused while dodging, then moved southeast toward the inn, past #9 |
| heavy r4, t 96 | "run east toward the town wall at (356,262)" | **east**, 1.2 m | `goto` the place "town wall" (run), at t 110 | 2.7 m northeast, then still |
| heavy r5, t 257 | "run west toward the house at (365.5,260.5)" | southeast, 8.9 m | none found within the window | still; #9 closed to 3.3 m |
| kiter r3, t 93 | "run west away from the shooter toward the wall cover" | east, 6.2 m | `flee` from #9 (run), at t 104 | kept chasing #9 east (its old plan's `attack`) until t 104, then ran west 8 m |

**Reading:**
- **The flee act moved the right way whenever it ran:** kiter r3, west, away from the shooter.
- **The wrong-way moves have two other causes:**
  1. **The mind names a place on the attacker's side** ("the inn" south past #9, "the town wall" just beyond #9). The compile carries that out faithfully as `goto`/`flee` to the place. Where the mind gave only a direction, the compile chose `flee` from the attacker, which drops the mind's wrong direction.
  2. **The new plan takes effect 10–21 s after the reply.** Until then the body keeps its old plan: standing (`keep`) or chasing the foe (`attack`).
- **So it is the mind's choice of target, and decision latency, not the flee act.** r2d ran before flee-open, so flee-open itself is not exercised in these traces.

## The general coordinator's reading (2026-11-12)

- **The ordinary-think replay counts as "came out well."** Letting a feeling pass with no harm is the intended effect of the neutral framing.
- **births-2 keeps today's framing** (`think_framing` off) until N2 is measured on longing in particular. A longing for a child is one of the felt needs N2 addresses less often, and births-2 is about that feeling.
- **fs1n** (first sight with N2, live at Cullet) runs after the battle quiet window, with the targets and the stop rule as committed (docs/TRIALS.md, "First sight fs1n").

## Did the fleeing mind know where its attacker was? (reading check, 2026-11-12, free)

The question: in the scene a fleeing mind was given, are the attacker's bearing and distance there, and the directions of the places it can name? If yes, it had what it needed and chose badly; if no, that is a perception gap. Each think request below is read as the model received it, from the journal.

**The five traced r2d flights.** Each row gives the scene's `#9` entry, the place the mind named, and where that place sits in the prompt:

| Run, reply | `#9` in the scene | The mind's flight | The named place in the prompt |
|---|---|---|---|
| heavy r5, t 70 | `{"dir": "southwest", "dist": 0.8, "visibly": {"is": "attack", "phase": "releasing", "at": "you"}}` | "run northeast toward the road … away from #9" | `terrain_near`: `"road": "northeast 3"`, with a bearing |
| heavy r5, t 223 | `{"dir": "northwest", "dist": 1.2, …}` | "run southeast along the road to the inn" | Places you remember: `"the inn south of the hall" at [405, 285]`; `you.at` [386.0, 271.7]; coordinates only |
| heavy r4, t 96 | `{"dir": "east", "dist": 1.2, …}` | "run east toward the town wall at (356,262)" | Places you remember: `"town wall" at [356, 262]`; `you.at` [351.9, 269.9]; coordinates only (it lies north-northeast, not east) |
| heavy r5, t 258 | `{"dir": "southeast", "dist": 1.2, …}` | "run west toward the house at (365.5,260.5)" | in sight: `{"kind": "house", "dir": "west", "dist": 9.4, "at": [365.5, 260.5]}` |
| kiter r3, t 93 | `{"dir": "east", "dist": 6.2, "visibly": {"is": "bowshot", "phase": "recovering", "at": "you"}}` | "run west away from the shooter toward the wall cover" | `terrain_near`: `"wall": "west 1"` |

- **The attacker's bearing and distance were in every scene,** with what it was doing at the mind ("at": "you").
- **Four of the five flights were right for the scene the mind was given:** away from `#9` as the scene placed it.
- **Their bodies went toward `#9` later because the world moved on.** The scene is built when the request is made. In a melee the foe circles within seconds: the scene's "southwest 0.8 m" was north at 9.6 m by the reply. Then the plan took 10–21 s more to install.
- **The fifth (heavy r4) misnamed a remembered place's bearing:** "east" for a wall that, from the coordinates, lies north-northeast.

**The replays' "fled toward the attacker"** (the 15 attacked prompts, judged against their own scenes, every arm).
- **How often:** a reply that names a flight direction names one within 45° of the scene's direction to `#9` in 3 of 9 (recorded), 4 of 10 (today's, again), 5 of 11 (N1) and 5 of 10 (N2).
- **Examples:**
  - scene `#9` `{"dir": "southeast", "dist": 1.2}`, today's reply: "run southeast toward the inn at (405,285)";
  - scene `#9` `{"dir": "northeast", "dist": 1.1}`, today's reply: "run northeast toward the crowd and the road".
- **These minds had both bearings in words:** the attacker's from the scene, the goal's in their own reply. They ran for the goal (the inn, the crowd, witnesses) through the attacker.

**Reading.**
- **The mind had what it needed and chose badly**, in the replays and in four of the five real flights. The scene states the attacker's bearing and distance.
- **One perception gap, smaller and not the cause here:** places the mind remembers come as coordinates only (`"the inn south of the hall" at [405, 285]`), beside its own `you.at`. A mind must work out their bearing and distance itself, and in heavy r4 it got the bearing wrong. Places and things in sight already carry `dir` and `dist`. Giving remembered places the same (bearing and distance from where the mind stands) would close it.
- **The delay is the larger cause in the real flights.** The scene is several seconds old when the model reads it, and the plan is installed 10–21 s after the reply. That is a case for r2e's fast-lane attack arm: a fight's reply acted on within a second or two.

## Cost and evidence

- **Replays:** $0.29 (T $0.094, N1 $0.098, N2 $0.096; 249 calls, no errors), against the $5 cap.
- **The judges** cost no API money (Claude subagents).
- **Key:** the `.env` copied from `~/dev/slop-runs-arrive` and deleted afterwards. 9 fragments of its 3 key values were searched for in the evidence and the branch. Count: 0.
- **Evidence:** `~/slop-evidence/framing-20261112/` on the Spark (3.8 MB):
  - `set.jsonl`: the 83 prompts with their recorded messages, bodies and replies;
  - `asked-T.jsonl`, `asked-N1.jsonl`, `asked-N2.jsonl`;
  - `asks.json`;
  - `judge/` (the items as each judge saw them, `RUBRIC.md`, the labels);
  - `key.jsonl`, `score.json`.
- **Tools:** [framing_replay.py](../living/tools/framing_replay.py) (`collect`, `collect-ordinary`, `ask`, `asks`, `items`, `score`); [flee_trace.py](../living/tools/flee_trace.py). Rubrics: [ADDRESSED.md](../living/tools/framing_judge/ADDRESSED.md), [ORDINARY.md](../living/tools/framing_judge/ORDINARY.md).
