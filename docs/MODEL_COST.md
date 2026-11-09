# Model cost per task (2026-11-09)

Which model, at which reasoning effort, is the cheapest acceptable choice for each mind task? This was measured by replaying 84 real prompts from the mind journals on the Mistral platform, 2,520 paid calls in all, and judging the replies blind. The tool is [model_cost.py](../living/tools/model_cost.py). The evidence is under `.local/living/model-cost/20261109/`.

[Part 2](#part-2-planning-sleep-reorganization-and-internalization-2026-11-09) revises item 2 below with four times as many planning prompts: compile (`deliberate`) needs `high`, not `low`. It also covers reorganization and internalization.

## Answer

1. **GLM 5.3 Flash is set up wrong today, and that dominates everything else.** `models.json` sends GLM Flash without `reasoning_effort`. The platform then thinks as hard as at `max`.
   - Person compile: 7,750 reasoning tokens per call.
   - Most of these calls hit the mind's 8,000-token `max_tokens` cap before any answer is written.
   - Usable replies: 8% of person compiles and 54% of person consolidations.
   - p50 latency: 81 s for compile and 37 s for think.
   - Spend, retries included: about €0.85 per person-hour, with 77% of decisions failing even after three attempts.
   - At `low`: €0.17 per person-hour, every reply usable, compile p50 9 s.
2. **Set the effort per purpose:**
   - `think` and `deliberate` (compile): `low`.
   - `talk` and `consolidate`: `high`.
   - `internalize`: `high`. It was not measured, but it must not be left unset.

   Leaving any purpose unset means max-level thinking for that purpose. The `models.json` change is [below](#modelsjson-change).
3. **Ministral is not worth keeping anywhere.** The blind judge found it acceptable 0/8 for animal memory, 5/12 for animal impulses, 0–3/12 for talk and 0–1/12 for people's decisions. Animal memory is the job `ministral-14b` does today.
   - Ministral 8B costs the same per input token as GLM Flash (€0.1275/M). These calls are input-heavy, so its cheaper output saves almost nothing: person compile costs €1.33 per 1k calls on 8B against €1.73 on GLM Flash at `low`.
   - Ministral 3B is the only real saving, but its replies are the worst.
   - Animals should move to GLM Flash: `low` for impulses and compiles, `high` for memory. GLM at `high` costs less than `ministral-14b` for animal memory (€0.70 against €0.74 per 1k calls), and it was the best memory writer.
4. **DeepSeek V4.1 Flash with thinking off is the fastest model with good quality,** but it costs 1.5–2.5× more per call because its input price is double GLM's.
   - Blind judging: it matched or beat GLM Flash at `high` on talk (12/12 acceptable, p50 1.8 s) and on person consolidation (8/8, p50 6.6 s).
   - Moving talk and person consolidation to it would need per-purpose routing, which `models.json` cannot express today. That routing is already queued as mind-harness work.
   - It would add about €0.02–0.03 per person-hour on stage.
5. **Prefix caching helps less than hoped.** Sending `prompt_cache_key` (`"prompt_cache_key": true`, already supported by `llm.rs`) raised GLM's cached share on person compile from 15% to 58% and saved 7–10% overall. GLM caches only in blocks of 1,152 tokens, so prompts with a short shared prefix (talk, animal impulses and animal memory) never hit its cache. A [prompt-order change](#prompt-order-for-caching) could extend the cached prefix per character.

Total spend: **€2.95** ($3.47) on Mistral for the replays. Probes and smoke tests added under €0.01. The blind judges were Claude subagents: about 1.8M tokens on the Claude side, not billed to Mistral.

## Prices

Source: [docs.mistral.ai/inference/pricing](https://docs.mistral.ai/inference/pricing), read 2026-11-09, Standard tier, USD.

The user's EUR figures are exactly 0.85 × USD; for example, GLM Flash input is $0.15 → €0.1275. This document uses EUR at 0.85.

| Model (API id) | Input $/M | Cached input $/M | Output $/M | Input €/M | Cached €/M | Output €/M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `zai-glm-5-3-flash` | 0.15 | 0.03 | 0.50 | 0.1275 | 0.0255 | 0.425 |
| `deepseek-v4-1-flash-1017` | 0.30 | 0.007 | 1.20 | 0.255 | 0.006 | 1.02 |
| `ministral-3b-latest` (→ `ministral-3b-2512`) | 0.10 | 0.01 | 0.10 | 0.085 | 0.0085 | 0.085 |
| `ministral-8b-latest` (→ `ministral-8b-2512`) | 0.15 | 0.015 | 0.15 | 0.1275 | 0.0128 | 0.1275 |
| `ministral-14b-latest` (→ `ministral-14b-2512`) | 0.20 | 0.02 | 0.20 | 0.17 | 0.017 | 0.17 |

- **Aliases:** the `-latest` aliases resolve to the Ministral 3 (2512) models (checked with `GET /v1/models`). The retired `ministral-*-2410` models are not involved.
- **Reasoning tokens** have no separate price. They are counted in `completion_tokens` and billed as output. For example, on GLM at `high`, completion 186 included reasoning 121.
- **Batch API:** 50% off ([docs.mistral.ai/capabilities/batch](https://docs.mistral.ai/capabilities/batch/), and "reduces the price by 50%" on [mistral.ai/pricing](https://mistral.ai/pricing)). Per-model batch prices were not published on the page read. `llm.rs` already uses batch for `internalize`.
- **Cached-input discount:** it differs by model. GLM's cached input is 20% of its input price, DeepSeek's about 2.3% and the ministrals' 10%. The caching page's general "10% of the input price" does not hold for every model; the per-model table is used here.

### Prompt caching on the Mistral platform

Docs: [docs.mistral.ai/inference/conversations/advanced/prompt-caching](https://docs.mistral.ai/inference/conversations/advanced/prompt-caching) and the [API reference](https://docs.mistral.ai/api/).

**What the docs say:**
- Caching reuses a shared prefix.
- `prompt_cache_key` "increases the chance of a cache hit, but it doesn't guarantee one".
- Usage reports it as `usage.prompt_tokens_details.cached_tokens`; billable uncached input is `prompt_tokens − cached_tokens`. `llm.rs` already journals this as `cached_tokens`.
- The docs state 64-token blocks.
- The docs do not say whether caching happens without the key, or how long a cache lives.

**What the replays measured (2,520 calls):**
- **Caching is automatic but scattered without the key.** Two identical consecutive calls often got 0 cached tokens on the second call, then 4,608 on another, as if requests landed on different replicas. With `prompt_cache_key`, GLM's first-call cached share on person compile rose from 15% to 58%.
- **Block sizes differ by model** (greatest common divisor of all cached counts seen):

  | Model | Block size | Smallest hits seen |
  | --- | --- | --- |
  | GLM Flash | 1,152 tokens | 1,152, 2,304, 4,608 … |
  | DeepSeek Flash | 128 tokens | 384, 512, 896 … |
  | Ministrals | 128 tokens after a 100-token start | 100, 228, 356 … |

  A prompt whose shared prefix is under 1,152 tokens never caches on GLM. Talk (system prompt ≈ 450 tokens), animal impulses and animal memory got 0% on GLM in every run, with or without the key.
- **Cache lifetime:** not measured. All repeat calls came within seconds.

### Reasoning-effort controls (verified on the API)

Docs: [docs.mistral.ai/capabilities/reasoning](https://docs.mistral.ai/capabilities/reasoning/). It lists `low`, `high` and `max` for `zai-glm-5-3-flash`, with "`none` is not supported". The request schema's enum is `none|minimal|low|medium|high|xhigh` and omits `max`, but the API accepts it.

| Model | Accepted `reasoning_effort` | Rejected | Omitted means |
| --- | --- | --- | --- |
| GLM 5.3 Flash | `low`, `high`, `max` | `none`, `minimal`, `medium`, `xhigh` (HTTP 400, "supported values: ['low', 'high', 'max']") | like `max`: same reasoning tokens (3,856 against 3,623 on person think; 7,791 against 7,742 on compile) |
| DeepSeek V4.1 Flash | `none`, `low`, `high`, `xhigh`, `max` (from the 400 message; not in the docs) | `minimal`, `medium` | `none`: no reasoning tokens |
| Ministral 3B/8B/14B | none ("reasoning_effort is not enabled for this model") | every value | no thinking |

- **GLM at `low` still thinks a little:** a mean of 83 reasoning tokens on person think, 156 on compile, and 6–54 on the rest. Its content then comes back as a plain string.
- **GLM at `high`/`max`, and DeepSeek with thinking on,** return content as `[{"type":"thinking",…},{"type":"text",…}]`. `content_text` in `llm.rs` keeps the text parts, which is correct.
- **`llm.rs` sends effort in a form these models honour.** `request_body` writes top-level `"reasoning_effort": "<value>"` from the profile's per-purpose map, and that is the field the platform reads. Effort changed reasoning tokens as expected in every probe and replay.
- **The map is keyed by the call's purpose:** `think`, `deliberate`, `talk`, `consolidate` and `internalize`. A person's compile and both of an animal's calls (impulse and compile) are all `deliberate`. They share one setting on a given profile.

## Method

- **Samples** (`model_cost.py sample`): 12 prompts per call class from the two most recent real-model runs, `aske-coast-1792435287` and `-1792391919` (2026-10-19/20, 6 h each, about 71 people and about 108 animals, Mistral Small 4).
  - Only the later half of each run, so the contexts are mature.
  - First attempts only.
  - Distinct characters where possible.
  - People and animals (21 deer, 9 wolf), with exact messages kept ([samples.jsonl](../.local/living/model-cost/20261109/samples.jsonl)).

  The seven classes:

  | Class | Journal purpose | What it is |
  | --- | --- | --- |
  | person think | `think` | the decision, without the grammar |
  | person compile | `deliberate` | the decision into acts or a graph |
  | talk | `talk` | a conversation turn |
  | person consolidate | `consolidate` | memory integration |
  | animal think | `deliberate` | the impulse |
  | animal compile | `deliberate` | the impulse into a graph |
  | animal remember | `consolidate` | memory integration |

  Reorganization (`consolidate`, about 0.003 calls per person per minute) was left out.
- **Replays** (`replay`): every sample on nine configs, each called **twice in a row**.
  - Configs: `ministral-3b`, `-8b` and `-14b`; GLM Flash with no effort field (as sent today), `@low`, `@high` and `@max`; DeepSeek Flash with no effort field (that is, `none`) and `@high`.
  - A second pass sent `prompt_cache_key` exactly as `llm.rs` builds it (`sao:<len>:<profile>:<purpose>`) for GLM `@low`/`@high`, DeepSeek and the ministrals (`+key` configs).
  - Request shape: the mind's own, which is `model`, `messages`, `max_tokens: 8000`, `response_format: json_object`, plus `reasoning_effort` when set. The only addition was `stream: true`, used to time the first token and the first answer text; usage arrives in the final chunk.
  - Run from the Mac at concurrency 16.
- **Validation** (`validate`): every reply went through the mind's `parse_json`, with the repair copied verbatim from `llm.rs` because the mind is a binary crate.
  - Graph replies (person and animal compile) then went through the rules' own lenient normalizer and validation: `living_rules::graph::from_value_lenient` for people and `from_value_for` with the species body for animals. The main graph is checked in the same order as `mind.rs`: `intent.graph`, then `graph`, then `patch.graph`. `graph` null or `"keep"` counts as carry-on, which is usable.
  - Routine graphs were checked as well, and warnings (pruned branches) were counted.
  - Other classes are usable when they have what the mind reads: `thought`+`intend`, `impulse`, `summary`, `say`/`end`.
  - The harness is at `.local/living/model-cost/harness`. The journals' original Mistral Small replies validate at 100%, except person compile at 92%.
- **Blind quality** (`pairs`): 290 pairs, each judged by fresh Claude subagents that saw only one file of prompts and A/B replies, with sides randomised. The key stayed in a separate file.
  - Reference: GLM Flash at `high`. Candidates: GLM `@low`, DeepSeek Flash and the three ministrals.
  - The judges covered talk (12 prompts), person and animal consolidation (8 each), person think and animal think (12 each), and person compile (6).
  - Unusable replies were not judged; they are counted in "usable".
  - Each verdict scores both replies 1–5, marks each acceptable or not, and picks the better one.

## Results per purpose

The cost columns are € per 1,000 calls:
- "first call" is the measured first call, already helped by other characters' calls of the same class, as in production;
- "with key" is the same with `prompt_cache_key`;
- "repeat" is the identical call again.

Latency is the total time from the Mac. "Usable" is out of 24 calls. "Judged acceptable" is out of the prompts judged; the reference's majority over its repeated ratings is counted as one. Full table: [report.md](../.local/living/model-cost/20261109/report.md).

#### Person think (decision; on stage 0.74–0.81 calls per person per minute)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable | Judged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 7,142 | 659 (0) | 0.54 / 0.54 / 0.43 | 3.5 / 5.5 | 0.4 | 100% | 0/12 |
| ministral-8b | 7,142 | 565 (0) | 0.89 / 0.85 / 0.50 | 7.4 / 10.3 | 0.5 | 100% | 1/12 |
| ministral-14b | 7,142 | 614 (0) | 1.22 / 1.24 / 1.22 | 8.1 / 10.5 | 0.6 | 100% | 1/12 |
| glm-flash (today) | 6,480 | 3,856 (3,337) | 2.46 / – / 2.26 | 37.0 / 60.0 | 35.1 | 100% | – |
| **glm-flash@low** | 6,480 | 386 (83) | 0.99 / 1.01 / 0.78 | 5.2 / 10.6 | 2.1 | 100% | **12/12**, beat `@high` 7–3–2 |
| glm-flash@high | 6,480 | 851 (477) | 1.20 / 1.26 / 0.93 | 13.2 / 30.7 | 8.4 | 100% | 12/12 (ref) |
| glm-flash@max | 6,480 | 3,623 (3,136) | 2.23 / – / 2.06 | 41.9 / 75.3 | 37.3 | 100% | – |
| deepseek-flash | 6,602 | 273 (0) | 1.65 / 1.65 / 1.15 | 6.0 / 9.7 | 4.5 | 100% | 9/12 |
| deepseek-flash@high | 6,627 | 1,369 (1,004) | 2.66 / – / 2.17 | 10.2 / 14.7 | 8.7 | 100% | – |

#### Person compile (`deliberate`; 0.79–0.81 per person per minute)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable (graph failures) | Judged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 13,824 | 899 (0) | 0.86 / 0.86 / 0.54 | 5.1 / 7.3 | 0.5 | 92% (1) | 1/6 |
| ministral-8b | 13,824 | 1,249 (0) | 1.33 / 1.47 / 1.53 | 13.6 / 23.8 | 0.6 | 96% (1) | 0/6 |
| ministral-14b | 13,824 | 1,524 (0) | 2.37 / 1.95 / 2.15 | 15.5 / 38.0 | 0.9 | 96% (1) | 2/6 |
| glm-flash (today) | 12,940 | 7,791 (7,752) | 4.58 / – / 4.19 | 81.4 / 95.4 | 35.9 | **8%**: 22 of 24 ran out of tokens while thinking | – |
| **glm-flash@low** | 12,940 | 670 (156) | 1.73 / **1.17** / 1.73 | 9.1 / 21.7 | 5.3 | 100% (0); 0.41 warnings per graph | 2/6 |
| glm-flash@high | 12,940 | 2,345 (1,729) | 2.28 / 1.84 / 2.22 | 21.5 / 44.6 | 17.0 | 100% (0) | 3/6 (ref) |
| glm-flash@max | 12,940 | 7,742 (7,700) | 4.40 / – / 4.14 | 84.0 / 102.3 | 32.3 | 8% | – |
| deepseek-flash | 13,120 | 497 (0) | 2.57 / 2.75 / 2.11 | **3.8** / 10.8 | 2.2 | 100% (0); 0.12 warnings | 3/6, beat ref 4–0–2 |
| deepseek-flash@high | 13,145 | 3,922 (3,325) | 6.24 / – / 5.52 | 15.9 / 42.6 | 13.9 | 92% | – |

The judges rated person compile poorly for every model, the reference included (3/6). Their reasons:
- acts written as `say`/`wait` although the prompt shows that failing;
- additions to the decision;
- unconditional branches that block the rest.

The decision being compiled came from the original Mistral Small think step, so this tests the compiler alone. With six prompts, the differences between GLM `@low`, `@high` and DeepSeek are within noise.

#### Talk (0.07 per person per minute on aske-coast, 0.28–0.42 in the labs)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable | Judged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 1,932 | 236 (0) | 0.15 / 0.16 / 0.12 | 1.4 / 2.3 | 0.3 | 96% | 0/12 |
| ministral-8b | 1,932 | 185 (0) | 0.23 / 0.24 / 0.20 | 2.6 / 3.9 | 0.4 | 96% | 1/12 |
| ministral-14b | 1,932 | 208 (0) | 0.34 / 0.36 / 0.34 | 2.9 / 4.6 | 0.4 | 100% | 3/12 |
| glm-flash (today) | 1,808 | 820 (675) | 0.56 / – / 0.60 | 8.9 / 16.9 | 6.4 | 100% | – |
| glm-flash@low | 1,808 | 137 (6) | 0.29 / 0.28 / 0.29 | 3.3 / 5.1 | 1.0 | 100% | 11/12 |
| **glm-flash@high** | 1,808 | 182 (46) | 0.31 / 0.32 / 0.31 | 2.2 / 4.2 (5.5 / 27.0 in the key pass) | 1.1 | 100% | 12/12 (ref) |
| glm-flash@max | 1,808 | 753 (607) | 0.54 / – / 0.56 | 7.9 / 12.7 | 7.0 | 100% | – |
| deepseek-flash | 1,819 | 122 (0) | 0.51 / 0.47 / 0.47 | **1.8 / 3.4** | 0.6 | 100% | **12/12**, beat ref 7–1–4 |
| deepseek-flash@high | 1,844 | 256 (133) | 0.71 / – / 0.58 | 2.5 / 14.5 | 1.5 | 100% | – |

The ministrals' talk failures were mostly invented acts:
- `conceive` aimed at children, allies or five people at once;
- acts that don't exist, such as `send`, `assign` or `urge`;
- trades for "warmth".

#### Person consolidate (0.46–0.63 per person per minute)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable | Judged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 8,475 | 1,888 (0) | 0.73 / 0.73 / 0.58 | 9.5 / 12.2 | 0.4 | 100% | 0/8 |
| ministral-8b | 8,475 | 2,340 (0) | 1.23 / 1.25 / 1.17 | 26.8 / 43.3 | 0.5 | 100% | 0/8 |
| ministral-14b | 8,475 | 2,385 (0) | 1.75 / 1.81 / 1.72 | 29.8 / 35.7 | 0.7 | 100% | 0/8 |
| glm-flash (today) | 7,614 | 6,915 (5,862) | 3.87 / – / 3.46 | 56.9 / 80.8 | 48.4 | **54%** (11 of 24 ran out of tokens) | – |
| glm-flash@low | 7,614 | 842 (48) | 1.29 / 1.39 / 1.00 | 7.6 / 13.1 | 1.7 | 100% | 4/8 |
| **glm-flash@high** | 7,614 | 1,907 (604) | 1.83 / 2.01 / 1.42 | 18.3 / 38.5 | 7.9 | 100% | 7/8 (ref) |
| glm-flash@max | 7,614 | 6,516 (5,294) | 3.69 / – / 3.16 | 58.7 / 92.5 | 49.8 | 62% | – |
| deepseek-flash | 7,680 | 978 (0) | 2.63 / 2.66 / 1.68 | 6.6 / 18.4 | 2.6 | 100% | **8/8**, beat ref 5–0–3 |
| deepseek-flash@high | 7,705 | 3,596 (2,045) | 5.17 / – / 4.47 | 17.6 / 43.3 | 12.0 | 96% | – |

The weak memory replies broke the graph's rules:
- timestamps or strings used as experience ids;
- the prompt's example merge key copied;
- stances written as nodes;
- identity rewrites that dropped values;
- invented events.

#### Animal think (impulse, `deliberate`)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable | Judged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 1,137 | 42 (0) | 0.09 / 0.09 / 0.05 | 0.5 / 1.5 | 0.3 | 100% | 5/12 |
| ministral-8b (today) | 1,137 | 96 (0) | 0.15 / 0.15 / 0.13 | 1.8 / 2.8 | 0.4 | 100% | 5/12 |
| ministral-14b | 1,137 | 85 (0) | 0.21 / 0.21 / 0.20 | 1.4 / 3.4 | 0.4 | 100% | 5/12 |
| **glm-flash@low** | 1,018 | 96 (10) | 0.17 / 0.16 / 0.17 | 1.9 / 5.2 | 0.7 | 100% | **12/12** |
| glm-flash@high | 1,018 | 161 (47) | 0.20 / 0.19 / 0.20 | 2.6 / 4.8 | 1.3 | 100% | 12/12 (ref) |
| glm-flash (no effort) / @max | 1,018 | 436 / 389 | 0.29 / 0.29 | 6.1 / 5.3 p50 | 4.4 / 3.8 | 100% | – |
| deepseek-flash | 1,036 | 71 (0) | 0.34 / 0.31 / 0.27 | 1.4 / 6.0 | 0.5 | 100% | 12/12 |

The ministral impulses that failed:
- invented terrain or wounds;
- deer running to berry bushes;
- wolves hunting their own pup;
- human motives ("bite to make her scream").

#### Animal compile (`deliberate`)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable (graph failures) | Warnings per graph |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 3,519 | 708 (0) | 0.26 / 0.23 / 0.17 | 4.4 / 8.2 | 0.4 | 75% (5) | 1.61 |
| ministral-8b | 3,519 | 685 (0) | 0.40 / 0.46 / 0.38 | 8.0 / 28.0 | 0.4 | 100% (0) | 1.08 |
| ministral-14b (today) | 3,519 | 563 (0) | 0.63 / 0.60 / 0.64 | 7.2 / 12.0 | 0.5 | 92% (2) | 0.64 |
| glm-flash (no effort) | 3,341 | 5,754 (5,650) | 2.83 / – / 2.83 | 57.0 / 111.7 | 42.5 | 67% | 0.06 |
| **glm-flash@low** | 3,341 | 194 (54) | 0.51 / 0.44 / 0.48 | 3.0 / 16.6 | 1.9 | 96% (1) | 0.05 |
| glm-flash@high | 3,341 | 722 (576) | 0.76 / 0.57 / 0.70 | 7.6 / 23.7 | 7.3 | 100% (0) | 0.04 |
| deepseek-flash | 3,384 | 144 (0) | 0.88 / 0.57 / 0.77 | 1.6 / 4.4 | 0.8 | 100% (0) | 0.33 |

Animal compiles were checked by the validator only, not judged.

#### Animal remember (`consolidate`)

| Config | Prompt tok | Out (reasoning) | € first / key / repeat | p50 / p95 s | First text p50 | Usable | Judged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ministral-3b | 2,250 | 1,688 (0) | 0.32 / 0.31 / 0.24 | 9.0 / 11.5 | 0.3 | 100% | 0/8 |
| ministral-8b | 2,250 | 2,606 (0) | 0.61 / 0.61 / 0.54 | 25.9 / 40.6 | 0.4 | 100% | 0/8 |
| ministral-14b (today) | 2,250 | 2,186 (0) | 0.74 / 0.72 / 0.69 | 24.2 / 42.3 | 0.4 | 100% | **0/8** |
| glm-flash (no effort) | 1,944 | 4,093 (3,183) | 1.94 / – / 2.00 | 28.9 / 63.5 | 23.3 | 92% | – |
| glm-flash@low | 1,944 | 611 (12) | 0.51 / 0.57 / 0.48 | 6.1 / 20.5 | 1.1 | 100% | 7/8 |
| **glm-flash@high** | 1,944 | 1,068 (269) | 0.70 / 0.69 / 0.70 | 9.6 / 18.7 | 3.5 | 100% | 8/8 (ref) |
| deepseek-flash | 1,911 | 1,231 (0) | 1.73 / 1.67 / 1.65 | 3.9 / 7.3 | 0.8 | 100% | 6/8 |

The ministral memories were bloated and corrupting:
- one node or edge for every person seen;
- invented coordinates;
- retractions of "home" or of everyone just added;
- people's remains recorded as dead deer.

### Where the cost goes

For GLM `@low` person compile, input is about 85% of the cost: 12,940 tokens × €0.1275/M = €1.65 per 1k calls, against 670 output tokens × €0.425/M = €0.28. That is why a cheaper output price buys little.

At default/`max` effort it is the reverse. About 7,750 reasoning tokens cost €3.30 per 1k calls, about 70% of the call, and they usually produce no answer.

## Cost per character-hour

`model_cost.py hourly`: calls per character per minute × measured € per call × expected attempts.

The mind asks again after an unusable reply:

| Call | Attempts |
| --- | --- |
| person compile, animal compile | up to 3 |
| person think | 2 (the profile, then the default) |
| animal memory | 2 (remember, then the compile profile) |
| talk, person consolidation | 1 |

Call rates:

| Scenario | Source | Rates per character per minute |
| --- | --- | --- |
| person, aske-coast | `model_cost.py rates` on both runs, 6 h, no LOD | think 0.805, compile 0.81, talk 0.067, consolidate 0.48 |
| person, labs on stage | [LIVING_CORE.md](LIVING_CORE.md#minds-at-scale-level-of-detail-stage-6-design-note-2026-09-27) | think 0.74, compile 0.79, talk 0.35, consolidate 0.63 |
| person, off stage | `LIVING_LOD=1` replay with nobody on stage | think 0.125, compile 0.125, talk 0.14, consolidate 0.06 |
| animal, aske-coast | measured over all animals | think 0.0135, compile 0.0135, remember 0.0165 |
| animal, near people | labs: 0.14–0.34 calls per animal per minute, midpoint, split like aske-coast | think 0.074, compile 0.074, remember 0.092 |

As sent today, without `prompt_cache_key` ([hourly.md](../.local/living/model-cost/20261109/hourly.md)):

| Mix | Person, aske-coast | Person, labs on stage | Person, off stage | Animal, aske-coast | Animal near people | Requests lost after retries |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| today (GLM Flash with no effort; animals 8B/14B) | €0.846 | €0.866 | €0.132 | €0.001 | €0.008 | 77% of person compiles, 46% of person consolidations |
| GLM Flash `@low` everywhere | €0.170 | €0.181 | €0.027 | €0.001 | €0.006 | 0% |
| GLM Flash `@high` everywhere | €0.223 | €0.237 | €0.035 | €0.001 | €0.008 | 0% |
| DeepSeek Flash (no thinking) everywhere | €0.283 | €0.305 | €0.045 | €0.003 | €0.015 | 0% |
| Ministral 8B everywhere | €0.147 | €0.157 | €0.023 | €0.001 | €0.006 | 4% of talk; judged quality unacceptable |
| **recommended:** GLM Flash think/deliberate `low`, talk/consolidate `high` | **€0.186** | **€0.202** | **€0.030** | €0.001 | €0.007 | 0% |
| later: as recommended, with talk and person consolidation on DeepSeek Flash | €0.210 | €0.236 | €0.034 | €0.001 | €0.007 | 0% |

With `prompt_cache_key: true`, the recommended mix is €0.170 / €0.188 / €0.027, 7–10% less.

At 2,000 people on stage that is about €340–€400 an hour; off stage under LOD it is about €55–€60. The recommendation costs about 22% of today's spend and turns 77% failed decisions into 0%.

**Animals are noise in the total.** At the labs' near-people rate, an animal-hour costs about €0.007, what a person spends in 2–3 minutes. Moving animals from the ministrals to GLM Flash changes that by €0.0004 per hour or less; it is a quality decision.

## Prompt order for caching

**What is stable today:**
- **People's system prompts** are byte-identical across characters within each class: think 7,696 chars, compile 25,933, consolidate 9,615, talk 1,919. They come first, which is right, and on GLM only the compile prompt's system part (about 5.8k tokens, 4–5 GLM blocks) is cached reliably.
- **Animal system prompts** are constant per species (one distinct system per class and species in the sample).

**What breaks the per-character prefix:** consecutive calls by the same character share only 51 to about 1,450 characters of the user message. 33 consecutive pairs of Ulf's think, compile and consolidate calls were checked. The prefix breaks in one of two places, both inside or right after `# Who you are`:
1. **At character 51–239 (15 of 33 pairs):** the self-description line under `# Who you are (Ulf)` ("A hunter drowning in guilt…" / "I am Ulf, a hunter…") changed. Consolidation rewrites it.
2. **At characters 1.1–1.45k (18 of 33 pairs):** `# People you know` changed order (Ylva and Maren swap places) or a label changed ("Partner"/"partner", "Unknowing"/"Unknowing confidant").

Everything after that, including the routines and places that rarely change, is uncacheable for that character.

**Recommended order for people's user messages** (think, compile, consolidate):
1. **Stable per character, in this order:** name, traits, values, skills (`You know how to`), group (`You belong to`); then routines (compile) or habits (think); then places.
2. **Then** `# People you know` in a fixed order (by id). Their trust/affinity numbers change rarely; their labels and status words (Starving, Unknowing) more often, so put those at the end of each line or in the perception section.
3. **Then the volatile parts:** the self-description and mood, `# Why you are thinking now`, recall, memories, stances, recent experiences, perception, the current top level and, for compile, `# What you decided`.

That would make roughly 3–6k characters (about 1–1.5k tokens) of each character's prompt stable after the shared system prompt. That is about one more GLM block per call, and more on DeepSeek, whose 128-token blocks and 2%-of-input cache price make it the model that gains most from a long stable prefix: with 90% of input cached, DeepSeek's input would cost less than GLM's.

**Untested follow-up:** reusing a character's own prefix needs the cache to see that character's calls together. The current key (`sao:<len>:<profile>:<purpose>`) groups all characters per purpose; that is good for the shared system prompt but does not keep one character's calls together. A key that includes the character id, like `prompt_cache_key` per actor, is an untested A/B. It might trade the shared-system hits for per-character hits. Talk cannot gain on GLM (its shared prefix is under one 1,152-token block), and it is cheap anyway.

Don't merge think and compile into one prompt to share context: compile's large system prompt (the grammar) is the most cacheable part, and it would then sit after the per-character context.

## Recommendation per purpose

| Purpose | Recommended | Evidence | Alternative |
| --- | --- | --- | --- |
| person think | GLM Flash `low` | 12/12 acceptable, beat `@high` 7–3–2; €0.99 per 1k calls; p50 5.2 s (37 s today) | – |
| person compile (`deliberate`) | GLM Flash `low` | 100% valid graphs; €1.73 per 1k calls (€1.17 with the key); p50 9.1 s; judged 2/6 against the reference's 3/6 (n=6, noise) | DeepSeek Flash: p50 3.8 s, 0 failures, fewest warnings, 1.5× the cost; worth it if decision latency matters, once per-purpose routing exists |
| talk | GLM Flash `high` | 12/12 (ref); p50 2.2 s; €0.31 per 1k calls; thinks only about 46 tokens on talk | DeepSeek Flash: 12/12 and beat GLM `high` 7–1–4, p50 1.8 s, first text 0.6 s, €0.51 per 1k calls; best for players in conversation |
| person consolidate | GLM Flash `high` | 7/8 acceptable (`low`: 4/8); €1.83 per 1k calls; background lane, latency doesn't matter | DeepSeek Flash: 8/8 and beat GLM `high` 5–0–3, €2.63 per 1k calls |
| internalize (player memory) | GLM Flash `high` | not measured (no journals yet); same kind of task as consolidation; must not be left unset | batch API halves it |
| animal think | GLM Flash `low` | 12/12 against 5/12 for every ministral; €0.17 per 1k calls against €0.15 for 8B | DeepSeek Flash 12/12 at 2× |
| animal compile | GLM Flash `low` (shares `deliberate` with animal think) | 96% valid, 0.05 warnings per graph against 0.64–1.61 for the ministrals; €0.51 per 1k calls, cheaper than 14B's €0.63 | GLM `high`: 100% valid, €0.76 |
| animal remember | GLM Flash `high` | 8/8 against 0/8 for every ministral; €0.70 per 1k calls, cheaper than 14B's €0.74 | GLM `low` 7/8 at €0.51 |

**Is Ministral worth keeping anywhere?** No.
- **Animal impulses:** Ministral 3B is the cheapest, at €0.09 per 1k calls against GLM `low`'s €0.17. The difference is €0.0001 per call, while its judged quality is 5/12 against 12/12. Its only clear advantage is latency: 0.5 s p50 against 1.9 s.
- **Talk for speed:** DeepSeek Flash is as fast as the ministrals (first text 0.6 s against 0.3–0.4 s) and judged far better.
- **Input-heavy tasks:** for people's tasks, 8B costs the same as or more than GLM `low`. It writes more output, and it bills about 10% more prompt tokens for the same messages (7,142 against 6,480 on think).

### models.json change

Proposed, not applied. It makes GLM Flash's effort explicit per purpose, turns on the cache key that `llm.rs` already supports, and moves animals to GLM Flash:

```json
"glm-flash": {
  "base_url": "https://api.mistral.ai/v1",
  "model": "zai-glm-5-3-flash",
  "key_env": "MISTRAL_API_KEY",
  "overflow": "deepseek-flash",
  "reasoning_effort": {
    "think": "low",
    "deliberate": "low",
    "talk": "high",
    "consolidate": "high",
    "internalize": "high"
  },
  "prompt_cache_key": true
},
```

```json
"species": {
  "deer": { "think": "glm-flash", "remember": "glm-flash", "compile": "glm-flash" },
  "wolf": { "think": "glm-flash", "remember": "glm-flash", "compile": "glm-flash" }
},
```

- **`deepseek-flash`:** leave it without a map. Omitted already means `none`, which is the setting that was judged. Brandholm and overflow then run DeepSeek without thinking.
- **Ministral profiles:** they can stay defined but unused.
- **If a separate effort is wanted for animals:** add a profile such as `glm-flash-animal` with its own map and point `species` at it, because animals' impulse and compile share the purpose `deliberate`.
- **Before relying on it:** apply it in a lab and check with [llm_load.py](../living/tools/llm_load.py) (reasoning share, `cached_tokens`, latency by purpose). Run `verify-llm` (requests, journals) and `verify-minds` for the routing change. None of these were run here, because no code or config was changed.

## Limitations

- **Old prompts:** the prompts are from 2026-10-19/20 (the Mistral Small era). `prompts.rs` has changed since, so sizes and wording may differ from what minds send today. The cost ratios between models should hold; the absolute token counts may not.
- **Judging:**
  - Judging is by one model family (Claude), blind to the model but not neutral.
  - The reference reply recurred in every pair of its prompt, and the judges noticed. Its acceptability is the majority of its repeated ratings.
  - Samples are small: 6–12 prompts per class.
  - Animal compile was validated, not judged.
- **Compile inputs:** person compile replays used the original think decision, not each model's own think.
- **Latency:** measured from the Mac, with streaming, at concurrency 16, at one time of day. p95 values swing between passes, for example GLM `@high` talk p95 4.2 s in the first pass and 27 s in the key pass.
- **Not measured:** cache lifetime, per-actor cache keys, batch prices and the `internalize` and reorganize purposes.
- **A probable prompt bug:** in sample `talk-00` (Pim, aske-coast-1792435287), the other speaker's lines appear as the literal `“text”` three times. Check whether the current `talk.rs` still renders lines like this.

## Evidence

Everything is under `.local/living/model-cost/20261109/` unless noted:

| What | Where |
| --- | --- |
| tool | [living/tools/model_cost.py](../living/tools/model_cost.py) (`sample`, `rates`, `replay`, `validate`, `pairs`, `report`, `hourly`, `spend`; Part 2 adds `sample2`, `chain`, `batch`, `judge`, `verdicts`, `patches`, `ids`, `planning`, `nights`) |
| validator | `.local/living/model-cost/harness/` (Rust; `living-rules` path dependency) |
| the 84 prompts, exact messages and original replies | `samples.jsonl` |
| all 2,520 replays | `replays.jsonl`: config, run number, usage, first-token and first-text times, total time, reply text, thinking text, request parameters |
| validation per reply, journal originals included | `validated.jsonl` |
| tables | `report.md`, `report.json`, `combined.md`, `hourly.md`, `hourly.json` |
| replay logs | `replay-main.log`, `replay-key.log` |
| blind judging, talk and consolidation | `pairs.jsonl`, `pairs_key.jsonl`, `judge/*.md` (what the judges saw), `judge/*.verdicts.jsonl` |
| blind judging, think | `pairs-think*.jsonl`, `judge-think/` |
| blind judging, compile | `pairs-compile*.jsonl`, `judge-compile/` |
| effort probes | `/private/tmp/claude-501/-Users-carlid-dev-slop-art-online/63d4b7b8-af33-41ef-97ac-489cdc1f53c4/scratchpad/probe/` (session scratch; the results are quoted above) |

Reproduce:

```bash
set -a; . ./.env; set +a
python3 living/tools/model_cost.py sample --runs aske-coast-1792435287 aske-coast-1792391919 --per 12
python3 living/tools/model_cost.py replay --concurrency 16
python3 living/tools/model_cost.py replay --concurrency 16 --configs glm-flash@low+key glm-flash@high+key deepseek-flash+key ministral-3b+key ministral-8b+key ministral-14b+key
python3 living/tools/model_cost.py validate && python3 living/tools/model_cost.py report && python3 living/tools/model_cost.py hourly && python3 living/tools/model_cost.py spend
python3 living/tools/model_cost.py rates --runs aske-coast-1792435287 aske-coast-1792391919
```

## Part 2: planning, sleep reorganization and internalization (2026-11-09)

The user's questions, the same afternoon:
1. Is GLM Flash `low` good enough for planning (think and compile), or is DeepSeek Flash needed, perhaps only on stage?
2. What should the sleep-like reorganization (`reorganize`) and player memory (`internalize`) run on? Can a settlement's night be sent as one batch job, and should reorganization follow the character's actual sleep?

The evidence is under `.local/living/model-cost/20261109-part2/` (and `-part2-latency/`); the tool is the same [model_cost.py](../living/tools/model_cost.py).

### Answer

1. **GLM `low` is good enough for think, not for compile.**
   - **Think** (24 prompts, blind 4-way): GLM `low` was acceptable 20/24 and GLM `high` 22/24, close to noise. GLM `high` was better in fights (8/8 against 6/8).
   - **Compile** (24 prompts, two independent blind passes): GLM `low` was acceptable 5/24 and 8/24. With reasoning it was 13/23 and 13/23 on GLM `high`, and 18/24 and 16/24 on DeepSeek `low`, the best compiler.
   - 98–100% of replies were valid in every config. The failures are in meaning: dropped or added intentions, speech written as a failing act, acts aimed at people out of sight, unconditional branches that block the rest.
   - Part 1's "compile at `low`" rested on 6 prompts and is withdrawn.
2. **Set `deliberate` to `high`.** It needs no new routing. It costs €0.157 per on-stage person-hour for planning, against €0.124 at `low`, and €0.025 against €0.020 off stage. It also raises animals' impulses and compiles to `high`, because they share `deliberate`; Part 1 judged animals at `high` 12/12 and 100% valid.
3. **DeepSeek is worth it for compile quality, not for latency.**
   - **Not faster this afternoon.** DeepSeek's first token took 7–11 s from 14:45 to 15:10, with or without `prompt_cache_key`, against 2–4.5 s in Part 1's morning pass. GLM `low` stayed at 1.4–2.9 s.
   - **Thinking off** (DeepSeek's default), it compiled worst of all: 5/24 in both passes.
   - **On stage only:** DeepSeek `low` for compile on stage costs about **€0.06 more per on-stage person-hour** than GLM `high` (€0.217 against €0.157 for planning). It saved 5.6 s per decision this afternoon (compile p50 18.4 s against 24.0 s).
   - **Needs routing:** per-purpose, per-stage routing for people does not exist yet ([below](#which-recommendations-need-new-routing)).
4. **Reorganization: GLM `high`, but the 8,000-token cap must rise.**
   - **What runs today:** reorganization goes out with purpose `consolidate` (`mind.rs` `reorganize`), so it runs at consolidation's `high`. At the mind's `max_tokens` of 8,000, 35% of those replies are cut off and fail to parse.
   - **With room:** given 24,000 tokens, GLM `high` finished 24/24 and was judged acceptable 22/24, the best of all configs.
   - **Alternatives:** GLM `low` fits under 8,000 (98% usable) but was judged 13/23. DeepSeek with thinking off was judged 4/21: it merges different people and retracts family ties and core stances.
   - **`max`, and DeepSeek `high`:** unusable. They write 18–23k tokens and still mostly run out at 24,000 (17–54% usable).
5. **Internalize: DeepSeek Flash with thinking off, in batch.**
   - **Judged:** acceptable 11/12, against 11/11 for DeepSeek `high` (one reply cut off) and 1/12 for GLM `high`.
   - **Why GLM fails:** it writes experience ids as strings (`"392903"`, even `"215713-216671"`) in 76% of memories and 80% of `because` ids. `memory.rs` `patch_from` reads them with `as_u64` and drops them silently, so most of a player's memories are lost. Its judged replies also invented events in 4 of 12.
   - **No new routing:** `LIVING_PLAYER_MEMORY_MODEL=deepseek-flash` selects DeepSeek today.
6. **The string-id defect reaches beyond player memory.** GLM writes string ids in 86–98% of animal-memory `because` ids and in 9–12% of person-consolidation memories at `low` and `high`. DeepSeek does so in 10–19% of animal-memory `because` ids and never in people's memories or internalization. A lenient id parse in `patch_from` would fix it for every model ([proposals](#code-and-prompt-changes-proposed)).
7. **Night batches work, but not inline.**
   - **Inline limit:** Mistral's front proxy refuses an inline `requests` body above about 2.5 MiB (HTML 400 before the API). A night of 100–190 reorganizations is 2.5–4.7 MB, so the job needs an uploaded file (`POST /v1/files`, purpose `batch`, then `input_files`). `Llm::batch` sends inline today.
   - **Turnaround, 200 reorganizations:** 150 s on GLM `low`, 219 s on GLM `high`, 949 s on DeepSeek. A game night lasts 300 real seconds.
   - **Cost:** at batch price, a town of 200 reorganizing every other night costs about €1.1 per real hour, €0.005 per person-hour.
8. **Reorganization is not sleep-aligned today, and it is rare because consolidation preempts it.**
   - **Timing:** 40–60% of reorganizations fall in the game night, which is 42% of the day.
   - **Who reorganizes:** only 28–46 of about 71 people reorganized at all in 4–6 h.
   - **If aligned to sleep:** with the eligibility kept (≥2 integrations and ≥20 real minutes since the last), about half the town is due each night: about 100 of 200 on stage, about 70 off stage. That is 14–28 times today's rate.

Spend: **€5.60** ($6.59) on Mistral for 1,693 calls, six batch jobs included. Probes cost under €0.01. The 19 blind judges were fresh Claude subagents, about 2.8M tokens on the Claude side.

### Method

- **Samples** (`sample2`): from all five aske-coast runs (2026-10-19/20, Mistral Small era), later half, first attempts, distinct characters, none of Part 1's prompts.
  - **Think:** 24 person think prompts, 8 per situation. The situation comes from the first telling line of `# Why you are thinking now`:

    | Situation | Reasons sampled |
    | --- | --- |
    | combat | "X is attacking you", "is threatening you", fight reports, a wolf attack |
    | survival | a `Your body:` line: freezing, starving, very hungry, badly hurt |
    | social | a baby crying, longing for a child, a trade offer |

  - **Compile:** each think prompt brings the compile request that followed it, so there are 24 compile prompts on the original decision.
  - **Reorganize:** 200 real requests (301 in the journals). The first 24 were replayed directly; all 200 went into the batch jobs.
  - **Internalize:** 12 prompts. Eleven were built the way `lived.rs` builds them: today's `internalize_system()`, copied verbatim from the real request below, over real `consolidate_user` contexts. The twelfth is the one real internalize request (`knowledge-pmem-real-132616`, Wren).
- **Replays:** the mind's request shape with `prompt_cache_key`, as `models.json` sends today. Concurrency 16, from the Mac.
  - **Think and compile:** two calls each.
  - **Chained compile** (`chain`, `person_compile_own`): each config compiled its own think reply, once.
  - **Reorganize:** two calls each at the mind's 8,000 cap, plus one call each at 24,000 (`+24k`) for the `high` and `max` efforts.
  - **Internalize:** one Mistral batch job per config.
- **Validation:** `parse_json` and the rules' graph normalizer, as in Part 1. For reorganize and internalize, the harness now also runs a verbatim copy of `memory.rs` `patch_from`:
  - **Ops kept:** merges, anchor merges refused, retracts, edges, memories kept with integer ids.
  - **Effect** (`patches`): what the ops would actually change against the mind shown in the prompt. A merge whose `from` is absent and a retract of a missing link are no-ops.
- **Blind judging** (`judge`, `verdicts`): fresh Claude subagents, one file each.
  - **Format:** each prompt once, then every config's usable reply under a label shuffled per prompt (R1…Rn). Keys are in `keys/`, apart from what judges read.
  - **Verdict:** each reply got a score of 1–5, acceptable or not, and a rank.
  - **Compile was judged twice** with reshuffled labels by different judges. The two passes agree on "acceptable" for 78% of the 95 replies judged twice.

### Planning results

#### Person think (24 prompts × 2 calls)

| Config | Prompt tok | Out (reasoning) | € per 1k, first call | p50 / p95 s | First text p50 | Usable | Judged acceptable | Ranked first | Combat / social / survival |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| glm-flash@low | 6,299 | 404 (96) | 0.97 | 5.6 / 12.0 | 2.8 | 100% | 20/24 | 3 | 6/8 · 7/8 · 7/8 |
| glm-flash@high | 6,299 | 972 (570) | 1.21 | 9.7 / 24.2 | 6.8 | 100% | **22/24** | **13** | 8/8 · 7/8 · 7/8 |
| deepseek-flash | 6,407 | 258 (0) | 1.53 | 11.3 / 22.2 | 9.8 | 100% | 18/24 | 0 | 5/8 · 6/8 · 7/8 |
| deepseek-flash@low | 6,432 | 952 (638) | 2.26 | 11.3 / 40.8 | 10.2 | 100% | 20/24 | 8 | 6/8 · 7/8 · 7/8 |

GLM `low`'s rejected decisions included the following:
- ignoring that Ulf was beating him right now;
- a night deer hunt at energy 12 with no spear;
- relying on fish in an unseen storage and on cooking it did not know.

#### Person compile (24 prompts × 2 calls; the original decision)

| Config | Out (reasoning) | € per 1k, first call | p50 / p95 s | First text p50 | Usable (warnings per graph) | Acceptable, pass A / B | Ranked first, A+B | A: combat / social / survival |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| glm-flash@low | 778 (282) | 1.72 | 9.3 / 16.9 | 4.2 | 100% (0.48) | 5/24 · 8/24 | 5 | 2/8 · 3/8 · 0/8 |
| glm-flash@high | 2,133 (1,616) | 2.34 | 24.0 / 52.8 | 17.5 | 98% (0.52) | 13/23 · 13/23 | 16 | 5/7 · 6/8 · 2/8 |
| deepseek-flash | 444 (0) | 2.53 | 11.6 / 23.1 | 10.4 | 98% (0.37) | 5/24 · 5/24 | 4 | 2/8 · 1/8 · 2/8 |
| deepseek-flash@low | 1,837 (1,304) | 3.67 | 18.4 / 40.9 | 16.5 | 100% (0.23) | **18/24 · 16/24** | **23** | 5/8 · 7/8 · 6/8 |

Prompts averaged about 12.7k tokens. The judges' recurring reasons against GLM `low` and DeepSeek with thinking off:
- `say` written as an act;
- `rest` used as an act;
- gifts and attacks aimed at people out of sight;
- an intent that opens with a failing attack, so the walk to the fire never runs;
- unconditional branches;
- dropped intentions, such as a teaching step;
- added speech.

**Own decisions, compiled** (`person_compile_own`, 24 × 1): every config's compile of its own think was usable at 96–100%. Warnings per graph were 0.25 for GLM `low`, 0.14 for GLM `high`, 0.21 for DeepSeek and 0.04 for DeepSeek `low`. Those calls came seconds after the fixed-decision ones, so their 62–70% cache share is warmer than production.

#### Latency: provider load, not the cache key

During the planning replays, DeepSeek's first token took about 10 s. Part 1's key pass had shown the same, against 2–4.5 s without the key earlier in the day. An interleaved A/B at 15:10 (48 prompts, concurrency 16, nothing else running) separates the two:

| Class | Config | p50 / p95 s | First token p50 / p95 s |
| --- | --- | ---: | ---: |
| think | glm-flash@low | 7.6 / 35.2 | 1.8 / 32.4 |
| think | glm-flash@low + key | 8.0 / 12.1 | 1.4 / 5.7 |
| think | deepseek-flash | 10.7 / 18.6 | 8.4 / 17.7 |
| think | deepseek-flash + key | 8.6 / 23.0 | 7.1 / 21.5 |
| compile | glm-flash@low | 10.4 / 18.5 | 2.9 / 11.6 |
| compile | glm-flash@low + key | 10.0 / 18.8 | 2.0 / 6.7 |
| compile | deepseek-flash | 10.9 / 25.3 | 9.7 / 22.4 |
| compile | deepseek-flash + key | 13.7 / 21.1 | 11.0 / 18.9 |

- The key does not slow DeepSeek; keep `prompt_cache_key` on both profiles.
- DeepSeek generates fast (230–310 tokens/s against GLM's 90–100), but this afternoon it queued requests for 7–11 s before the first token. In Part 1's 13:21–13:29 pass the same model answered compile at p50 3.8 s.
- One afternoon is not a latency profile. Choose DeepSeek for compile quality. Don't count on it for speed without measuring at the hours that matter.

#### € per person-hour, planning only

From `planning`: on-stage rates are think 0.74 and compile 0.79 per minute; off stage (LOD) both are 0.125. The costs are first calls with the cache key, retries included.

| Think | Compile | On stage | Off stage | p50 think + compile |
| --- | --- | ---: | ---: | ---: |
| glm-flash@low | glm-flash@low | €0.124 | €0.020 | 14.9 s |
| **glm-flash@low** | **glm-flash@high** | **€0.157** | **€0.025** | 29.6 s |
| glm-flash@high | glm-flash@high | €0.167 | €0.027 | 33.7 s |
| glm-flash@low | deepseek-flash | €0.165 | €0.027 | 17.2 s |
| **glm-flash@low** | **deepseek-flash@low** | **€0.217** | €0.035 | 24.0 s |
| deepseek-flash@low | deepseek-flash@low | €0.274 | €0.044 | 29.7 s |

- **Compile on DeepSeek `low` on stage only:** +€0.060 per on-stage person-hour against the recommendation, and nothing extra off stage. With a share *s* of person-hours on stage, that is *s* × €0.06 overall. For example, it adds €0.012 per person-hour when one in five is on stage.
- **Think on GLM `high` on stage:** +€0.011 per on-stage person-hour. It is defensible for fights (8/8 against 6/8), but n = 8.
- **Effect on Part 1's person totals:** `deliberate: high` adds about €0.030 per on-stage person-hour and €0.005 off stage. The recommended person mix becomes about €0.23 on stage (labs rates) and €0.035 off stage.

### Sleep reorganization (`reorganize`)

#### Replays (24 prompts; at the mind's 8,000 cap unless marked 24k)

The prompts averaged about 9.5k tokens: about 60 concepts and 90–120 links.

| Config | Out (reasoning) | € per 1k, first call | p50 / p95 s | Usable (cut off at the cap) | Concepts → after | Links → after | Judged acceptable | Ranked first |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| glm-flash@low | 2,931 (370) | 2.48 | 21.5 / 35.2 | 98% (1/48) | 58 → 52 | 97 → 89 | 13/23 | 3 |
| glm-flash@high (**today**, via `consolidate`) | 6,336 (4,053) | 3.88 | 43.2 / 76.3 | **65%** (17/48) | 57 → 51 | 86 → 79 | – | – |
| **glm-flash@high, 24k** | 7,704 (4,595) | 4.46 | 57.4 / 131.0 | **100%** (0/24) | 58 → 54 | 97 → 89 | **22/24** | **9** |
| glm-flash@max | 8,000 (8,000) | 4.60 | 66.2 / 94.9 | 0% (48/48) | – | – | – | – |
| glm-flash@max, 24k | 20,483 (18,329) | 9.88 | 189 / 295 | 42% (14/24) | 58 → 51 | 84 → 78 | 6/10 | 3 |
| deepseek-flash | 4,393 (0) | 6.22 | 20.8 / 41.6 | 88% (6/48) | 58 → 53 | 94 → 83 | **4/21** | 0 |
| deepseek-flash@high | 7,989 (7,885) | 10.56 | 37.0 / 62.5 | 2% (47/48) | – | – | – | – |
| deepseek-flash@high, 24k | 18,751 (16,632) | 21.26 | 70.7 / 126 | 54% (11/24) | 57 → 49 | 80 → 72 | 11/13 | 6 |
| deepseek-flash@max | 8,000 (8,000) | 10.57 | 37.9 / 57.1 | 0% (48/48) | – | – | – | – |
| deepseek-flash@max, 24k | 23,149 (22,357) | 25.35 | 81.7 / 198 | 17% (20/24) | 52 → 44 | 52 → 52 | 4/4 | 3 |
| journal original (Mistral Small) | – | – | – | 91% | 55 → 55 | 84 → 84 | – | – |

How to read it:
- **Usable** is what the mind's code accepts: a reply that `parse_json` reads; every JSON object is applied.
- **Concepts and links after** are averages over the accepted replies, against the mind each prompt shows. They are computed from the sanitized ops: effective merges, retracts that match a link, new edges and new concepts. GLM `high` output reached 15,935 tokens (p95 15,199), so 16,000 is too tight a cap; 24,000 is what was measured.
- **Judged:** the judges asked whether a reply merges true duplicates only, generalizes sensibly, retracts what is stale without erasing what matters, and invents nothing. GLM `high` with room produced "collapses dozens of duplicate stances into clear patterns while keeping the FEELS ties, know-how and the Oath".
- **GLM `low`'s errors:** merging "the oath must be read" into its opposite, two different people, or different campfires.
- **DeepSeek with thinking off:** merges different people (Pim into Rafe; three relatives into one), retracts rivals, formative values and promises, re-asserts and then retracts nearly every edge, and copies the prompt's example (`kind:wolf -HUNTS_NEAR-> place:ford`) as if it were a fact.
- **Mistral Small** (the journals) shrank nothing on net. It tried 4.1 anchor merges per reply, which the mind refuses.
- **Evidence ids:** no reorganization keeps any. The prompt asks for `because` "experience ids from the edges you generalize", but the edge lines show no ids, and the mind passes only unintegrated inbox ids as `known`. So generalized patterns carry no evidence.

#### When it runs, and how often it would run at night

`model_cost.py nights` simulated the rules on all five aske-coast timelines. It reads 71–72 people, 20–30 game days per run, with the clock calibrated from the first think after each dawn (12.0 real minutes per game day, measured).

| Rule (per person, once per game night) | Due per night, share of people | Off stage (LOD, ≤ 1 integration per 15 min) | Town of 200, on / off stage |
| --- | ---: | ---: | ---: |
| today (timer, preempted by consolidation) | 0.035 per game day | – | about 7 |
| ≥ 2 integrations since the last | 0.93 | 0.35 | 186 / 70 |
| ≥ 6 integrations | 0.91 | 0.10 | 182 / 20 |
| **≥ 2 integrations and ≥ 20 real minutes** | **0.49** | **0.35** | **98 / 70** |

- **Today:** reorganization runs when a person is "rested" and has nothing salient to integrate (`check_consolidation`, `Some(!wanted)`). In a busy town that is rare: 45–81 reorganizations per run, 7–18 integrations between them for a person, 17–37 minutes apart. Only 28–46 of the about 71 people reorganized at all. Night share is 0.40–0.60 against 0.42 for the night's part of the day, so the timer is not sleep-aligned.
- **Aligning it:** the cleanest rule keeps today's eligibility (≥ 2 integrations, ≥ 20 minutes) and runs it at the character's first sleep after it becomes due, at most once a night. A tired mind then tidies while the body sleeps, instead of whenever the town goes quiet. Consolidation would no longer starve it.
- **The mind cannot see sleep.** Sleep is `activity.skill = "sleep"`, and `activity` is not among `living-mind`'s subscriptions. There are two options:
  - Use the world clock the mind already subscribes to (`world`) and treat 20:00–06:00 as night. It needs no new data path and matches town residents, who sleep at night ([TOWN_LIFE.md](TOWN_LIFE.md)).
  - Subscribe to sleepers only (`activity` where `skill = 'sleep'`).

  The [subscription docs](https://spacetimedb.com/docs/clients/subscriptions/) (read 2026-11-09, docs version 2.0.0) support filtered subscriptions and advise "keep subscriptions small". The [index docs](https://spacetimedb.com/docs/tables/indexes/) say unindexed filters scan, and `activity` has no `skill` index. Before building the second option, check it against the pinned 2.14.1 and measure its update volume. The clock is the smaller first step.

#### Night batch: design and cost

The measured jobs:

| Job | Requests | Payload | Turnaround (create → output) | Usable | € per 1k (batch price) |
| --- | ---: | --- | ---: | ---: | ---: |
| reorganize, glm-flash@low | 200 | 5.07 MB, file | **150 s** | 100% (199 accepted) | 1.03 |
| reorganize, glm-flash@high (8k cap) | 200 | 5.07 MB, file | 219 s | 80% | 1.66 |
| reorganize, deepseek-flash | 200 | 5.07 MB, file | 949 s | 90% | 3.15 |
| internalize, glm-flash@high | 12 | inline | 54 s | 100% (but string ids) | 0.79 |
| internalize, deepseek-flash | 12 | inline | 43 s | 100% | 1.34 |
| internalize, deepseek-flash@high | 12 | inline | 58 s | 92% | 2.74 |

- Every job went QUEUED → RUNNING within 6–12 s. `timeout_hours` (default 24) is the only time control the [batch docs](https://docs.mistral.ai/capabilities/batch/) give.
- The docs state a 50% discount but publish no per-model batch price, and billing was not checked. The batch costs here are list price × 0.5.
- `reasoning_effort` and `prompt_cache_key` pass through in batch bodies. The `high` replies thought as they do directly.
- Batch and direct replies of the same config validated alike: GLM `low` 100% against 98%, DeepSeek 90% against 88%.

Design, for the mind:
1. **Collect.** At dusk (20:00 game time, from `world`), take every person of the settlement who is due under the rule above. Mark them `consolidating`, so no integration interleaves, then fade and read each mind as `reorganize` does now.
2. **Send** one batch job per profile. Above about 2.4 MB, upload the JSONL (`POST /v1/files`, purpose `batch`) and pass `input_files`; below that, send inline as `Llm::batch` does. Inline tops out at about 100 reorganizations.
3. **Apply** each patch when the job returns and clear the flags. GLM finished 200 within one game night. A job that is not done by dawn plus one night is cancelled, and its people go direct the next night.
4. **Keep the evidence:** journal each answer with the job id, as `Llm::batch` already does.

Cost for a town of 200 at the recommended GLM `high` with a 24k cap, €4.46 per 1k direct and about €2.23 per 1k batch (assumed half):

| Rule | Due per night | Per night, batch / direct | Per real hour (5 nights) | Per person-hour |
| --- | ---: | ---: | ---: | ---: |
| ≥ 2 and ≥ 20 min, on stage | 98 | €0.22 / €0.44 | €1.09 / €2.19 | €0.005 / €0.011 |
| ≥ 2, on stage | 186 | €0.41 / €0.83 | €2.07 / €4.15 | €0.010 / €0.021 |
| ≥ 2 and ≥ 20 min, off stage (LOD) | 70 | €0.16 / €0.31 | €0.78 / €1.56 | €0.004 / €0.008 |

Sleep-aligned reorganization costs 2–7% of what planning costs. Batching halves a small number; its real use is that nobody waits on these calls and the service's concurrent slots stay free during the night.

### Internalize (`internalize`, batch mode)

| Config | Out (reasoning) | € per 1k (batch) | Job turnaround | Usable | Memories kept per reply | Judged acceptable | Ranked first |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| glm-flash@high | 1,579 (576) | 0.79 | 54 s | 100% | **0.9** of 3.8 written | 1/12 | 0 |
| **deepseek-flash** | 1,173 (0) | 1.34 | 43 s | 100% | 3.4 | 11/12 | 4 |
| deepseek-flash@high | 3,775 (2,340) | 2.74 | 58 s | 92% (1 cut off) | 4.0 | 11/11 | 8 |

- The judges were told how the mind reads ids, so GLM's dropped memories counted against it.
- Without that, GLM still invented in 4 of 12 replies: "Elin tended Mira", a plan to share news with Walker1, the claim that wolves there do not fear people, and a reversed yield.
- DeepSeek's slips were smaller: one `you` anchor instead of `self`, one misattributed yield, invented coordinates.

#### Experience ids as strings (`ids`)

Share of ids that are not integers. `patch_from` reads each with `as_u64` and drops it.

| Class | GLM Flash (`low` / `high` / none / `max`) | DeepSeek Flash | Ministral 3B / 8B / 14B |
| --- | --- | --- | --- |
| internalize memories | 76% (`high`) | 0% | – |
| internalize `because` | 80% (`high`) | 0% | – |
| person consolidation memories | 12% / 9% / 0% / 0% | 0% | 96% / 0% / 0% |
| animal memory `because` | 98% / 98% / 86% / 95% | 10–19% | 100% / 100% / 100% |

Animal memory comes from Part 1's replays (`ids-part1.md`); it is what GLM does for every animal since this morning's switch.

### Recommended settings

#### models.json proposal

Proposed, not applied. Two lines change from the current file:
- `deliberate` becomes `high`;
- `max_tokens` becomes 24,000 so a `high` reorganization can finish.

The keys that are never read (`compile`, `remember`, `reorganize`, `identity`, `birth`) are dropped. The mind sends only `think`, `deliberate`, `talk`, `consolidate` and `internalize`; reorganization, identity, birth identity and animal memory all go out as `consolidate`. DeepSeek gets explicit efforts for Brandholm and overflow.

```json
"glm-flash": {
  "base_url": "https://api.mistral.ai/v1",
  "model": "zai-glm-5-3-flash",
  "key_env": "MISTRAL_API_KEY",
  "overflow": "deepseek-flash",
  "max_tokens": 24000,
  "reasoning_effort": {
    "think": "low",
    "deliberate": "high",
    "talk": "high",
    "consolidate": "high",
    "internalize": "high"
  },
  "prompt_cache_key": true
},
"deepseek-flash": {
  "base_url": "https://api.mistral.ai/v1",
  "model": "deepseek-v4-1-flash-1017",
  "key_env": "MISTRAL_API_KEY",
  "overflow": "glm-flash",
  "reasoning_effort": {
    "think": "low",
    "deliberate": "low"
  },
  "prompt_cache_key": true
},
```

With the mind's environment:

```bash
LIVING_PLAYER_MEMORY_MODEL=deepseek-flash   # internalize on DeepSeek, thinking off (its map leaves internalize unset = none)
LIVING_PLAYER_MEMORY_MODE=batch
```

- **`deliberate: high`** covers person compile (13/23 on both passes against 5–8/24 at `low`) and animals' impulse and compile (Part 1: 12/12, 100% valid at `high`). The cost is +€0.033 per on-stage person-hour. Animals stay noise.
- **`max_tokens: 24000`** applies to every glm-flash purpose; the profile has no per-purpose cap. Elsewhere GLM's p95 output is under 3.5k (talk 287, person consolidation 3,409). The cap is there to stop runaways, and a runaway at 24k costs €0.01.
- **DeepSeek `think`/`deliberate` `low`** affects Brandholm (group-routed to deepseek-flash) and GLM overflow. Thinking off judged worst on both: think 18/24, compile 5/24. Talk and consolidation stay unset (`none`), as Part 1 judged them.
- **Brandholm reorganizes on DeepSeek with thinking off,** judged 4/21, because it goes out as `consolidate` on the group's profile. Fixing that without moving Brandholm to glm-flash needs per-purpose routing.
- **Before relying on it,** apply it in a lab and check reasoning share, cut-offs (`finish_reason`), latency by purpose and judged behavior with [llm_load.py](../living/tools/llm_load.py). Then run `verify-llm` and `verify-minds`. None of these were run here, since no code or config was changed.

#### Which recommendations need new routing

| Recommendation | Possible today? | What it needs |
| --- | --- | --- |
| compile at `high`, think at `low` | yes, `models.json` | – |
| reorganization at GLM `high` that finishes | yes, `max_tokens: 24000` | – |
| internalize on DeepSeek in batch | yes, environment | – |
| compile on DeepSeek `low` **on stage only** | no | per-purpose and per-stage profile choice for people. `Llm` picks a person's profile once (`assign`, `rotate`, `groups`, `stages`, `default`); `lod.rs` knows who is on stage but does not choose models. A shape such as `"purposes": {"deliberate": {"on_stage": "deepseek-flash"}}` |
| reorganization with its own model or effort | no | `mind.rs` `reorganize` to send purpose `reorganize` (`Lane::for_purpose` already treats it as background), then a `reorganize` key in the effort map or the routing above |
| Brandholm reorganizing on GLM | no | the same per-purpose routing |
| sleep-aligned night batches | no | mind changes (below) |

#### Code and prompt changes proposed

Not made here; they belong to the mind's owners.
1. **`memory.rs` `patch_from`:** accept an integer written as a string (`"392903"`, `"#392903"`) for `remember[].exp` and `edges[].because`, and note what is still dropped. This restores most of GLM's player memories and its animal-memory evidence. *Done 2026-11-09 (with the perception and presence change, uncommitted):* one parser, `living_rules::normalize::reply_id` (an integer, `"392903"` or `"#392903"`; a range such as `"215713-216671"`, a word, a negative or fractional number is not an id), reads `remember[].exp`, `edges[].because` and `relations[].id` in `patch_from`/`sugar_into`, `say.to` and talk ids in the mind service, and graph and act targets (`{"id": "12"}`, `"#12"`) in the rules' normalizer. What is still dropped is noted in the thought's `notes` ("memory of exp … dropped: not one of these experiences"). Tests: `memory::tests::experience_ids_written_as_strings_are_kept` (a GLM-shaped reply) and `normalize::tests::ids_written_as_strings_are_ids`.
2. **`mind.rs` reorganization:**
   - make it due by the rule above and run it at night (world clock first);
   - collect the due sleepers per settlement into one job;
   - send purpose `reorganize`.
3. **`llm.rs` `Llm::batch`:** upload a JSONL file and use `input_files` when the inline body would exceed about 2.4 MB.
4. **The reorganize prompt (`prompts.rs`):**
   - **Cap the ops**, as internalize does ("at most 12 nodes and 20 edges"), so replies fit a smaller cap.
   - **Evidence:** either render each link's evidence ids or stop asking for `because`.
   - **Example:** replace `kind:wolf -HUNTS_NEAR-> place:ford` with a visibly abstract placeholder; DeepSeek and GLM `low` copied it into minds as a fact.

### Limitations

- **Old prompts:** the planning and reorganization prompts are from the Mistral Small era (2026-10-19/20). The internalize prompts combine today's system prompt with old consolidation contexts. Their experience lines lack the `@[x, y] in <place>` suffix that `lived.rs` adds, and they are AI characters' lives, not players'.
- **Compile inputs:** the compile prompts compile Mistral Small's decisions. The chained replays show each config's own decisions compile validly, but those were not judged.
- **Judging:**
  - One model family judged (Claude), blind to the model but not neutral.
  - Think, reorganize and internalize had one pass each.
  - Reorganize judged 4–24 replies per config, because cut-off replies were not judged. The `max` rows are small samples.
- **Latency:** from the Mac, at concurrency 16, over 14:45–15:45. DeepSeek's latency swung threefold within hours.
- **Batch:**
  - Price assumed at half the list price; billing was not checked.
  - GLM `high` was batched only at the 8k cap. The 24k batch cost is extrapolated from the direct call.
  - Turnaround was measured on one account at one time of day, with other jobs sometimes running at once.
- **Night counts:** simulated from aske-coast, a world without LOD whose integration rates stand in for "on stage". The off-stage column thins those same timelines to one integration per 15 minutes. The ≥ 25-link minimum for reorganization (5% of rests in the logs) is not applied.

### Spend

| What | Calls | € | $ |
| --- | ---: | ---: | ---: |
| Part 2 replays and batch jobs (`spend`) | 1,500 | 5.34 | 6.28 |
| Cache-key latency A/B | 192 | 0.26 | 0.31 |
| Probes: one 5-token batch job; seven size probes refused with 422 before inference | 1 | < 0.01 | < 0.01 |
| **Total on Mistral** | **1,693** | **5.60** | **6.59** |

By model: DeepSeek Flash €3.78 and GLM Flash €1.82. Most of DeepSeek's share is reorganization at `high`/`max`: 18–23k tokens per call at 24k.

Claude side: 19 judge subagents and one documentation fetch, about 2.8M tokens, not billed to Mistral.

### Evidence

Everything is under `.local/living/model-cost/20261109-part2/` unless noted:

| What | Where |
| --- | --- |
| samples (think, compile, chained compile, 200 reorganize, 12 internalize), exact messages | `samples.jsonl` |
| direct replays (usage, first token and first text, total time, reply, thinking, request parameters) | `replays.jsonl`; logs `replay.log`, `replay-24k.log` |
| batch answers and jobs (timeline, payload size, inline or file) | `batch-replays.jsonl`, `batches.jsonl`, `batch*.log` |
| validation, patch effects, id types | `validated.jsonl`, `patches.json`, `patches.md`, `ids.md`, `ids-part1.md` |
| tables | `report.md`, `report.json`, `planning.md`, `planning.json`, `nights.json`, `reorganize-timing.json`, `spend.txt` |
| blind judging | `judge-person_think/`, `judge-person_compile/`, `judge-person_compile-b/`, `judge-reorganize/`, `judge-internalize/` (what judges saw, `*.verdicts.jsonl`); keys in `keys/`; `verdicts-*.md`; `judge-agreement-compile.txt` with `judge-agreement.py` |
| cache-key latency A/B | `.local/living/model-cost/20261109-part2-latency/` (`samples.jsonl`, `replays.jsonl`, `report.md`, `spend.txt`) |
| validator with `patch_from` | `.local/living/model-cost/harness/src/main.rs` |

Reproduce:

```bash
set -a; . ./.env; set +a
D=.local/living/model-cost/20261109-part2
RUNS="aske-coast-1792352109 aske-coast-1792366782 aske-coast-1792391919 aske-coast-1792413603 aske-coast-1792435287"
python3 living/tools/model_cost.py sample2 --dir $D --runs $RUNS
python3 living/tools/model_cost.py replay --dir $D --concurrency 16 --classes person_think person_compile --configs glm-flash@low+key glm-flash@high+key deepseek-flash+key deepseek-flash@low+key
python3 living/tools/model_cost.py chain --dir $D
python3 living/tools/model_cost.py replay --dir $D --concurrency 16 --once --classes person_compile_own --configs glm-flash@low+key glm-flash@high+key deepseek-flash+key deepseek-flash@low+key
python3 living/tools/model_cost.py replay --dir $D --concurrency 16 --classes reorganize --configs glm-flash@low+key glm-flash@high+key glm-flash@max+key deepseek-flash+key deepseek-flash@high+key deepseek-flash@max+key
python3 living/tools/model_cost.py replay --dir $D --concurrency 16 --once --classes reorganize --configs glm-flash@high+key+24k glm-flash@max+key+24k deepseek-flash@high+key+24k deepseek-flash@max+key+24k
python3 living/tools/model_cost.py batch --dir $D --cls internalize --configs glm-flash@high+key deepseek-flash+key deepseek-flash@high+key
python3 living/tools/model_cost.py batch --dir $D --cls reorganize --pool --configs glm-flash@high+key deepseek-flash+key glm-flash@low+key
python3 living/tools/model_cost.py validate --dir $D && python3 living/tools/model_cost.py report --dir $D && python3 living/tools/model_cost.py patches --dir $D
python3 living/tools/model_cost.py planning --dir $D && python3 living/tools/model_cost.py ids --dir $D && python3 living/tools/model_cost.py spend --dir $D
python3 living/tools/model_cost.py nights --dir $D --runs $RUNS
python3 living/tools/model_cost.py judge --dir $D --cls person_compile --configs glm-flash@low+key glm-flash@high+key deepseek-flash+key deepseek-flash@low+key --chunk 8   # then judges write judge-*/…verdicts.jsonl
python3 living/tools/model_cost.py verdicts --dir $D --tag person_compile
```
