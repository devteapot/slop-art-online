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

## Built behind a law (think-framing, 2026-11-12)

The general coordinator decided to build N2 behind a world law, off by default.
- **The law:** `think_framing` (`skills.rhai` `laws()`, `script.rs` `Laws`, `laws_about`), switched at runtime by `set_world_law`.
  - **Off:** a mind starts from why it is thinking now, today's wording.
  - **On:** N2, word for word as replayed.
- **Where:** `living/mind/src/prompts.rs` `think_system` and `think_user`. With the law on, the finished text gets exactly one replacement each (`framed_system`, `framed_user`):
  - the sentence `TODAY_FRAMING` becomes `NEUTRAL_FRAMING`;
  - the section `# Why you are thinking now` becomes `# What just happened`, where it stands.

  With the law off, the builders' text is returned untouched. The compile (deliberate) prompt, the talk turn and animal minds are unchanged.
- **What it adds:** no table, column, reducer, view or binding. The law is a value of the world's script, read by the mind service from the rules it already loads.
- **Checks:**
  - mind unit test `prompts::tests::think_framing_is_n2_on_and_today_off`: both frames, with and without projects. Off is identical. On replaces exactly once, and undoing the replacement gives today's text back.
  - rules test `script::tests::think_framing_is_the_world_s_law`;
  - verify-minds `think-framing` (the real mind, the fake model). With the law off, the think request carries today's sentence once and "# Why you are thinking now". With it on, the system prompt equals the off one with the sentence replaced, and the user prompt has the same sections in the same order, the reason's renamed.
  - `just living-check` passes.

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
- **Tool:** [framing_replay.py](../living/tools/framing_replay.py) (`collect`, `ask`, `asks`, `items`, `score`). Rubric: [ADDRESSED.md](../living/tools/framing_judge/ADDRESSED.md).
