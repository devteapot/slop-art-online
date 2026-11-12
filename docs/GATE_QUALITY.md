# The rethink gate's quality against its cost (cloud only, 2026-11-12)

Branch `trials-gate-quality`. Idea #3 of [MIND_RESEARCH_IDEAS](MIND_RESEARCH_IDEAS.md), run as designed in [LOCAL_MINDS §5](LOCAL_MINDS.md#5-two-ways-to-cut-cost-the-gate-and-a-local-model-with-idea-3) with the cloud models only.
- **Two ways to cut a deliberation's cost.** Hold it with the gate (fewer calls), or make each call cheaper. Here the cheaper call is GLM 5.3 Flash for the think step against DeepSeek V4.1 Flash, the cloud pair our people's mix already uses.
- **How quality is measured.** A blind two-part judge, on the same recorded requests.

**Spend: [removed: Jev pricing] of the [removed: Jev pricing] ceiling.**

| Item | Cost |
|---|---:|
| Jev gate replay, 1,282 points | [removed: Jev pricing] |
| GLM gate replay, 1,198 calls | $0.230 |
| think re-asked: 171 on DeepSeek, 129 on GLM (60 of them the noise floor) | $0.455 |

- **The judges cost nothing in API money.** They were nine fresh Claude subagents.
- **Key.** The `.env` copied from `~/dev/slop-runs-arrive` holds three variables (`CARLID_NPC_API_KEY`, `MISTRAL_API_KEY`, `TYPESAFE_API_KEY`); the last two were used.

## What was run

- **Trigger points.** `living-mind rethink-replay --arm jev` and `--arm llm` (the shipped `rethink.json`: Jev `jev-1.14.0`, GLM `glm-flash@low`) asked the gate at every deliberation of two sets of trial evidence on the Spark. The subject is the one character a trial records in full; urgent reasons and first thoughts are never judged.
  - **All-minds** (new): bi1 (4 hamlet runs, 6 h each) and st2b (4 Cullet runs), where every resident thinks. 526 deliberations; 509 can be gated.
  - **Newcomer** (rebuilt): the same 16 runs as [MIND_HARNESS §6](MIND_HARNESS.md#6-rethink-gate)'s replay (b1 theft, hungry, hungry-village, teacher × 3; w1 life-default r1, r3; w2 life-valley, life-pressure r1). A lone mind among instinct residents, models of the Mistral Small and GLM era. 756 deliberations; 689 can be gated (§6 counted 714 and 650).
  - **The old labels are lost.** §6's replays and blind labels went with the dev-box worktree `~/dev/slop-rethink` when it was removed on 2026-11-10 (searched for on the dev-box 2026-11-12; not on any branch). Every label here is new.
- **Recorded think calls.** `gate_quality.py points` takes each gateable point's recorded think call from the run's journal, with its exact messages and reply. All 509 and 689 were found.
- **The model axis** (all-minds only: 240 sampled points).
  - Each point's exact think messages were sent again to the *other* cloud model: 171 recorded on GLM went to DeepSeek, 69 recorded on DeepSeek went to GLM (`gate_quality.py ask`, the same request body as `llm.rs` with the model and its effort swapped).
  - **The noise floor:** 60 points recorded on GLM went to GLM again.
- **Blind judges.** Fresh Claude subagents; each saw only its own items and the rubric. No judge saw the gate's verdict, which model wrote what, or the key. Rubrics: [VALUE.md](../living/tools/gate_quality_judge/VALUE.md) and [PAIRS.md](../living/tools/gate_quality_judge/PAIRS.md).
  - **(a) Value of the recorded deliberation**, 400 points (240 all-minds, 160 newcomer), four judges. Each point is labelled `useful`, `marginal` or `wasted`, with the waste kind, and `hurt_if_skipped`: would holding it for up to ten minutes, its reasons kept, have hurt?
  - **(b) Pairs of think replies**, 298 pairs, five judges, in random order: which is better or `same`, and for each reply whether it has a flaw that would hurt if acted on. Such flaws are a phantom target, an invented act, a need or danger ignored, or a plan kept that is plainly broken.
  - **Agreement on doubly judged items:**
    - value label 68% (n = 40);
    - `hurt_if_skipped` 78% (n = 40);
    - pair verdict 77% (n = 30).
- **Scoring** (`gate_quality.py curve`):
  - **Holding.** A held point costs its gate question and nothing else; it counts as harm when its label says `hurt_if_skipped`.
  - **Passing.** A passed point costs its gate question, its think and its recorded compile; it counts as harm when the judge flagged that setup's reply as harmful.
  - **Gate rules** are scored offline from each point's recorded answers, so one replay per arm covers every threshold.

## What the deliberations were worth

| Set | n | useful | marginal | wasted | hurt if skipped | waste kinds (restated, phantom, asking loop, other) | $ a deliberation |
|---|---:|---:|---:|---:|---:|---|---:|
| all-minds | 240 | 40% | 34% | 26% | 21% | 50, 4, 1, 8 | 0.0033 |
| newcomer | 160 | 36% | 31% | 33% | 49% | 26, 22, 4, 1 | 0.0020 |

**Against §6.** §6 found 42% wasted and 16% harmful to skip on the newcomer runs; these judges found 33% and 49%. The rubric asks "would holding it up to ten minutes hurt?", and the judges read the lone newcomer's broken plans as urgent far more often. Read the two sets against each other, not against §6.

**The all-minds worlds waste less.** A quarter of deliberations is wasted, almost all as restated plans. Phantom targets and asking loops nearly vanish once residents answer.

## The gate's curve

Held share; share of the wasted it catches; share of the harmful-to-skip it holds; harm (harmful holds as a share of all triggers); cost against the gate off. Random holding at h% holds h% of each kind.

**All-minds** (n = 240):

| Gate | Held | Wasted caught | Harmful held | Harm | Cost vs off |
|---|---:|---:|---:|---:|---:|
| off | 0% | – | – | 0.0% | 100% |
| Jev p ≥ 0.2 | 13% | 22% | 6% | 1.2% | [removed: Jev pricing] |
| **Jev p ≥ 0.3 (shipped config)** | **27%** | **37%** | **16%** | **3.3%** | [removed: Jev pricing] |
| Jev p ≥ 0.4 | 43% | 54% | 28% | 5.8% | [removed: Jev pricing] |
| Jev p ≥ 0.5 | 61% | 76% | 44% | 9.2% | [removed: Jev pricing] |
| Jev, unless × 0.5, p ≥ 0.5 | 29% | 38% | 16% | 3.3% | [removed: Jev pricing] |
| Jev, no `would_repeat`, p ≥ 0.7 | 32% | 44% | 16% | 3.3% | [removed: Jev pricing] |
| GLM p ≥ 0.5 | 44% | 60% | 28% | 5.8% | 61% |
| GLM p ≥ 0.7 (shipped config) | 63% | 75% | 40% | 8.3% | 42% |
| GLM p ≥ 0.8 | 72% | 84% | 50% | 10.4% | 32% |

**Newcomer** (n = 160):

| Gate | Held | Wasted caught | Harmful held | Harm | Cost vs off |
|---|---:|---:|---:|---:|---:|
| Jev p ≥ 0.2 | 36% | 47% | 21% | 10.0% | [removed: Jev pricing] |
| **Jev p ≥ 0.3** | **49%** | **57%** | **35%** | **16.9%** | [removed: Jev pricing] |
| Jev, unless × 0.5, p ≥ 0.3 | 22% | 34% | 8% | 3.8% | [removed: Jev pricing] |
| Jev, unless × 0.5, p ≥ 0.4 | 39% | 45% | 19% | 9.4% | [removed: Jev pricing] |
| Jev, no `would_repeat`, p ≥ 0.5 | 31% | 36% | 14% | 6.9% | [removed: Jev pricing] |
| GLM p ≥ 0.5 | 23% | 26% | 12% | 5.6% | 87% |
| GLM p ≥ 0.7 | 40% | 45% | 23% | 11.2% | 70% |

The full grid (20 rules per set) is in `curve.json`.

- **Both gates discriminate in both sets.** At equal holds they catch more waste than random and hold fewer of the harmful.
  - In the all-minds worlds Jev 0.3 holds 27% but only 16% of the harmful.
  - At equal hold rates the two judges are about equal: GLM p ≥ 0.5 holds 44% and 28% of the harmful, Jev p ≥ 0.4 43% and 28%. Jev is cheaper ([removed: Jev pricing] against [removed: Jev pricing] a question) and faster (about 150 ms against 1.4 s).
- **The gate holds much less where minds answer each other.** Jev 0.3 holds 27% of triggers in the all-minds worlds against 49% for the lone newcomer. So its saving there is about [removed: Jev pricing], not the [removed: Jev pricing] measured live with a newcomer.
- **`would_repeat` is still where harmful holds come from, as in §6.**
  - Halving it ("unless × 0.5") at p ≥ 0.3 holds only 8% of the newcomer's harmful deliberations, against 35%, at a cost of [removed: Jev pricing] against [removed: Jev pricing].
  - Among the all-minds residents it makes almost no difference at the same hold rate (p ≥ 0.5: 29% held, 16% harmful).

## Cheaper calls: GLM against DeepSeek for think (all-minds)

| Same messages | n | first better | second better | same | first's reply harmful | second's | first $ a think | second $ a think |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| recorded GLM against DeepSeek | 169 | 21 | **64** | 84 | **17 (10%)** | 6 (4%) | 0.00094 | 0.00189 |
| recorded DeepSeek against GLM | 69 | 18 | 13 | 38 | 4 (6%) | 5 (7%) | 0.00186 | 0.00102 |
| **noise:** recorded GLM against GLM again | 60 | 12 | 13 | 35 | 4 (7%) | 2 (3%) | 0.00093 | 0.00098 |

- **The noise floor.** The same model on the same messages differs in about 4 of 10 pairs, split evenly (12 against 13). Its harm flags vary by a few points (7% against 3%).
- **DeepSeek is judged better than GLM well beyond the noise** where the points were recorded on GLM: 64 against 21. Its replies are flagged harmful less often (4% against 10%). Where the points were recorded on DeepSeek, the two are close (18 against 13; 6% against 7%).
  - Both sets are the same hamlet and Cullet worlds. The first is the residents of groups the mix gives GLM; the second, those it gives DeepSeek (`groups`).
  - Pooled over 238 pairs: DeepSeek better 82 times and GLM 34 (122 same); harmful replies 10 for DeepSeek (4%) and 22 for GLM (9%).
- **The price of that quality:** DeepSeek's think costs about twice GLM's ($0.0019 against $0.0009 here), about $0.001 more per think.
- **Caveat: judges may favour fuller replies.** The rubric says style and length are not harm, but a judge can still prefer the more complete reply. DeepSeek's replies were more often complete plans. MODEL_COST's 12-prompt judging had found GLM `low` 12/12 and DeepSeek 9/12 on think; this sample is 20 times larger, from the worlds the gate is meant for.

## How the two combine (all-minds, 238 points)

For each pair (gate, think model):
- **Harm** = (held and harmful to skip) + (passed and that model's reply harmful), as a share of triggers.
- **Cost** = gate questions + the think of the model used + the recorded compile, for passed points.

The frontier, cheapest first:

| Gate | Think on | Harm | $ a trigger |
|---|---|---:|---:|
| GLM p ≥ 0.8 | GLM | 12.6% | 0.0010 |
| Jev p ≥ 0.5 | DeepSeek | 9.7% | [removed: Jev pricing] |
| Jev p ≥ 0.4 | DeepSeek | 7.6% | [removed: Jev pricing] |
| **Jev, no `would_repeat`, p ≥ 0.7** | **DeepSeek** | **5.5%** | [removed: Jev pricing] |
| **Jev p ≥ 0.3** | **DeepSeek** | **5.9%** | [removed: Jev pricing] |
| *off (today's mix on these points)* | *GLM* | *9.2%* | *0.0031* |
| Jev p ≥ 0.2 | DeepSeek | 4.6% | [removed: Jev pricing] |
| off | DeepSeek | 4.2% | 0.0040 |

- **The combination beats either lever alone.** Gating with Jev and spending the saving on DeepSeek for think costs what today costs: [removed: Jev pricing] against [removed: Jev pricing] a trigger. Its harm is 5.9% against 9.2%. Today's setting (no gate, GLM think) is off the frontier.
- **Each lever alone.**
  - Gating with GLM think saves money at the same judged harm: Jev 0.3 with GLM is 9.2%, as with no gate, at [removed: Jev pricing] of the cost.
  - DeepSeek with no gate lowers harm (4.2%) at 29% more cost.
- **The difference is small against the noise.** 5.9% against 9.2% is 14 against 22 points of 238. The harm flags' own variation is about ±4 points (the noise rows). The direction is consistent with the pairwise preference, which is well beyond noise; the size is not established.

## Which gate I would ship

**Jev at p ≥ 0.3, the configuration already in `rethink.json`, turned on together with DeepSeek for think** (the `deepseek-people` mix's think, or `people` with think on `deepseek-flash`).

- **What it buys in the worlds the gate is for:**
  - about [removed: Jev pricing] fewer deliberation dollars from the gate alone, not [removed: Jev pricing];
  - 37% of the waste caught;
  - a harmful hold on about 1 trigger in 30.
- **Paired with DeepSeek for think,** total cost stays at today's level and the judged harm falls.
- **Not "unless × 0.5" or "no `would_repeat`".** They protect the lone newcomer better (8% and 14% of its harmful held, against 35%). Among residents who answer they give the same harm for the same saving. The newcomer case is better served by keeping the shipped rule and its 600 s release.
- **Before default-on, the live check idea #3 planned.** Hamlet `default` against `rethink-jev`, 4 × 1 h, with the think model held constant across the arms, plus one Cullet pair; about [removed: Jev pricing]. It measures:
  - the time from a failed act to a changed plan;
  - the talk guards and `plans_other`;
  - deliberations and dollars per resident-hour.
  - **Live, a held request is merged and released later.** The replay counts a hold as lost, which overstates the harm.

## Limits

- **Only the subjects.** The trials record one subject's full rows a run, so the points are 4 + 4 subjects in the all-minds worlds, not every resident.
- **Approximations in scoring.**
  - A hold counts as a loss, not a delay.
  - The compile is the recorded one (on stage DeepSeek, off stage GLM) and was not re-run with the other model. The judges saw the think reply, not the compiled graph.
- **Judges.** Claude subagents, two-thirds to three-quarters agreement. Labels are noisy; read the shares to about ±5 points.
- **Not done here.** A local model (later, only for narrow cases), the gate's latency (Jev about 150 ms; unchanged), and anything about scale.

## Evidence

**The store's run record: `gq1`** (an analysis batch, `"kind": "analysis"` in its `batch.json`; docs/STORE.md). It is at `~/dev/slop-gate-live/.local/living/trials/gq1/` on the Spark, so the store's manifest scans it.
- **What it holds:** the replays and their gate journals, `points.jsonl`, the samples, the re-asked replies, the judge rubrics, items, labels and key, `curve.json`, and a copy of this page. `batch.json` lists every file with its sha256, the sources, the switches and the spend.
- **The models whose words it carries** (`models_in_outputs`):

  | Model | Count |
  |---|---:|
  | `zai-glm-5-3-flash` | 2,158 |
  | `deepseek-v4-1-flash-1017` | 315 |
  | `mistral-small-latest` | 223 (the newcomer runs' recorded thinks) |
  | `jev-1.14.0` | 1,198 |
  | `claude-opus-5-5` | 768 (judge labels) |

- **Publishing is held, and nothing was uploaded.** The store's model gate holds three of these until the owner reads their terms: `mistral-small-latest` (as for b1–b3), `jev-1.14.0` and `claude-opus-5-5`.
- **Checked 2026-11-12:**
  - `store.py scrub --dry-run`: 77 files ok; the only redactions are home paths (3,850).
  - `store.py pack batch` to `~/store-dryrun-2026-11-12/gq1-pack` (8.7 MB).
  - A grep of the record and of the pack for every 12-character window of the three key values in the `.env` used, and for key-like patterns: **0 found**.

`~/slop-evidence/gate-quality-20261112/` on the Spark:
- `out/`: replays, `points.jsonl`, the re-asked replies, the samples, `judge-key.jsonl`, `curve.json`;
- `judge/`: the items as each judge saw them, and the labels.

Tool: [gate_quality.py](../living/tools/gate_quality.py) (`points`, `sample`, `ask`, `items`, `curve`).
