# Model cost per task (2026-11-09)

Which model, at which reasoning effort, is the cheapest acceptable choice for each mind task? This was measured by replaying 84 real prompts from the mind journals on the Mistral platform, 2,520 paid calls in all, and judging the replies blind. The tool is [model_cost.py](../living/tools/model_cost.py). The evidence is under `.local/living/model-cost/20261109/`.

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
| tool | [living/tools/model_cost.py](../living/tools/model_cost.py) (`sample`, `rates`, `replay`, `validate`, `pairs`, `report`, `hourly`, `spend`) |
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
