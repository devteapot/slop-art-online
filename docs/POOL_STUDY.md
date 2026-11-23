# How big the model-call pool should be (pool-study, 2026-11-21)

Branch `pool-study`. The question, from the general coordinator: how many slots should the mind service's model-call pool have (`LIVING_CONCURRENCY`, default 192)? In the [real-model act trial](INPUT_LATENCY.md#real-model-trial-act-trial-2026-11-21) at 200 minds, calls waited a median 12 s for a slot; in the [fast-dispatch A/B](INPUT_LATENCY.md#ab-main--timing-vs-fast-dispatch) at 64 slots, the minds sent 1.7–2.2× the thinks once their preparation was fast, and the lower lanes' in-queue wait rose. No paid model calls were made for this study.

## What the pool is (the code on main `7f73c04c`)

`living/mind/src/llm.rs`, `Queue` and `Lane`:

- **Shared pool:** `LIVING_CONCURRENCY` slots (default 192). Interactive calls may take any free slot and go first. The three lower lanes together may hold at most `concurrency − max(1, concurrency/4)` slots (144 of 192, 48 of 64); a quarter is kept for interactive calls.
- **Lanes:**
  - *Interactive:* talk with a player in it, and a player's own act deliberation (`Lane::deliberation(_, true)`).
  - *Fast:* the fast lane's own slots (`fast_lane_inflight`, default 4), outside the pool. The world law `fast_lane_on` is off since the Nov 19 verdict, so no fast asks run in these loads.
  - *Urgent:* a deliberation whose reason names combat, a fight, an attack, an alarm, a hit, danger or a wound: its think, its compile (`deliberate`) and its act repair.
  - *Routine:* every other deliberation (think, deliberate, act repair, the rethink gate) and talk between minds.
  - *Background:* consolidation, reorganization (sleep), identity, internalization. Consolidations and birth identities also wait for a second semaphore of `concurrency/2` before they queue (`Minds::slow`), outside the measured queue wait.
  - The lower lanes are admitted 6 urgent : 3 routine : 1 background among those with calls waiting.
- **Per-profile pacing, before any slot:** requests a minute start at 600 and rise by 5% of the ceiling every 10 s to 0.9 × the provider's `x-ratelimit-limit-req-minute`; tokens a minute are held under 0.9 × `x-ratelimit-limit-tokens-minute`, counting each call in flight at an estimate (prompt characters / 3 + 8 a message + the purpose's `max_tokens`) until its usage arrives. A call that would pass either waits in the queue with a slot free. `LIVING_LLM_PER_MIN` (a global cap) is 0, off.

The journal's `queue_wait_ms` is the time from entering this queue to the grant: slot wait and pacing wait together.

## What the act trial's journals already show (read-only, `~/slop-evidence/act-trial-20261121.tar.zst`)

Every call's `queue_wait_ms`, `latency_ms`, lane, purpose, profile and tokens, from the mind's own journals (`pool_study.py report`; battle minutes 2–8, town minutes 2–30):

| | Battle, 200 minds, 192 slots (off / on arm) | Town, 40 minds, 64 slots (four arms) |
| --- | --- | --- |
| Urgent wait p50 / p90 / p99 (s) | 12.4 / 14.4 / 15.3; 12.2 / 13.7 / 14.9 | none urgent |
| Routine wait p50 / p90 / p99 (s) | 0.64 / 3.6 / 8.0; 0.55 / 2.8 / 8.5 | 0.00 / 0.00–0.05 / 0.09–0.12 |
| Background (consolidation) wait p50 / p90 (s) | 33.2 / 42.7; 34.2 / 40.8 | 0.00 / 0.15–0.24 |
| Calls in flight: mean, p90, max | 73, 87, 100; 72, 86, 96 | 5–7, 9–14, 41–43 |
| Calls waiting in the queue: mean | 185; 181 | 0.0–0.1 |
| GLM calls a minute; GLM tokens a minute | 889, 7.63 M; 893, 7.68 M | 51–53, 0.51–0.53 M |
| Calls per mind-hour | 320; 318 | 89–90 |

- **The battle was not short of slots.** The lower lanes could hold 144 calls; at most 100 were in flight, 73 on average, while 180 waited, and the grant-stall watch (`Queue::watch`: a call whose pacing allows it, a free slot, no grant for 1 s) never fired. What held them was **GLM's request pacing**. Mistral advertises 1,333 requests a minute per model; the mind paces each profile at 0.9 × that, one GLM call every 50.0 ms. In both arms the gaps between consecutive GLM grants (after the 150 s ramp from 600 a minute) have a hard floor at 50 ms: p1 50 ms, p50 61 ms, mean 66.9 ms, p90 89–90 ms, almost none over 110 ms. That is about 897 grants a minute, below the 1,200 the pacing allows, because a waiting call held only by that spacing is not woken at its deadline when its profile also has a token limit (`Queue::spacing_deadline` returns `None` when `rate.tpm` is set). It waits for the next 50 ms poll or for any other call's grant or completion, about 17 ms on average. Tokens did not bind: a token-limited queue would show multi-second gaps as the window rolls over, and GLM used 7.6–7.9 M of its 9.6 M paced tokens a minute.
- **The 12 s is urgent, not everyone's.** Urgent calls are 64% of the battle's; with the urgent lane always full, a routine call (a talk turn, mostly) waits under a second at the median, and consolidation, at 1 in 10 admissions, 33–34 s.
- **The town never queues.** 5–7 calls in flight on average; the 41–43 peaks are the start, when every resident's memory work (identity, consolidation, sleep) goes out at once.

## Provider limits (no calls made to probe them)

**Verified** (from what the provider sent, recorded in the act trial's and earlier runs' logs):

- Mistral advertises per model, in its response headers, **1,333 requests a minute** for both models and **10,666,666 tokens a minute for `zai-glm-5-3-flash`, 10,000,000 for `deepseek-v4-1-flash-1017`** (the mind's `model limits` lines, which log 0.9 × the headers: `rpm_ceiling=1199.70`, `tpm_ceiling=9599999` / `9000000`; act trial, every run). The same figures were learned in [lives-2](SEEDED_LIVES.md#measured-on-the-spark) ("about 1,333" and "about 10.7 M") and in aske-coast-5's key change ("about 10M tokens a minute", [STAGES.md](STAGES.md)).
- **No rate-limit 429 in the act trial.** Its 7,957 + 7,911 battle calls and the four full town arms failed none. The partial town arms `at7on`/`at8off` (stopped by the guard) failed 29 and 12 calls within 45 s, all provider capacity: HTTP 429 `backend_out_of_capacity` (code 3505, "Not enough capacity available for this request") on DeepSeek and HTTP 503 "Service unavailable" on GLM. Those are the provider's capacity, not a limit on this caller, and they came at a town's 50–60 calls a minute, so a smaller pool would not have avoided them. lives-2 saw the same 429 on 0.13% of calls, the full island 1.7% of GLM calls at about 350 a minute ([SEEDED_LIVES.md](SEEDED_LIVES.md#every-person-a-mind)).
- The mind paces itself under 0.9 × the advertised limits; in these runs no call came back rate-limited.

**From the provider's public documentation** (read 2026-11-21):

- [help.mistral.ai, "Why am I hitting API rate limits, and how do I increase them?"](https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them) (dated 2026-08-12): limits "are set at the organization level and apply across all your workspaces"; "Rate limits are applied per model"; three measures: "Requests per second (RPS): concurrent requests", "Tokens per minute: input + output throughput", "Tokens per month: overall consumption cap". Tiers rise with cumulative billing (Tier 1 with pay-as-you-go; Tier 2 over $20, Tier 3 over $100, Tier 4 over $500, higher over $2,000 then by contacting support); "Adding credits does not raise your rate limits". **No numbers are published**; the account's own are at `admin.mistral.ai/plateforme/limits` (login only, not read).
- [docs.mistral.ai, Priority Tier](https://docs.mistral.ai/inference/priority-tier): custom, model-specific limits ("requests per minute, tokens per minute, or other limits agreed with Mistral"); with `service_tier: auto` a request over them falls back to the Standard tier instead of failing.
- [docs.mistral.ai, workspaces](https://docs.mistral.ai/getting-started/quickstarts/admin/manage-workspaces): a workspace's monthly budget, when reached, returns 429 until the next billing cycle (a spending cap, not a rate limit).
- No page documents the `x-ratelimit-*` headers, the 3505 error or a cap on calls in flight. The tier page `docs.mistral.ai/deployment/laplateforme/tier/` is gone (404).

**Assumed, not verified:**

- *Whether the token limit is per model or shared.* The help page says per model, and the headers differ by model (10.67 M against 10 M), so the mind's per-profile pacing (each profile its own budget) matches; the study did not test a shared limit, and the battle's DeepSeek share (0.35 M tokens a minute) is too small to tell.
- *What "RPS: concurrent requests" means in numbers.* The account's RPS limit is not in the headers the mind reads. Up to 100 calls were in flight in the act-trial battle (about 18 a second sent) and none was refused; a higher concurrency is untested against the provider.
- *That model latency does not depend on how many calls are in flight.* The fake replays the act trial's recorded latencies, which were measured at 5–100 calls in flight; real battle latencies were higher than the town's (think p50 3.2 s against 2.3 s, consolidation 13 s against 6 s), which may be load, prompt size or the hour, and is not separated here.

## Method: the act trial replayed on the fake model

- **The fake answers like the act trial's models.** `pool_study.py samples` turns the act trial's journals into recorded calls per model and purpose: each call's model latency, its usage (prompt, cached, completion tokens) and, for think, deliberate, talk and act repair, its reply. The memory purposes (consolidation, sleep) get the fake's valid empty patch, since their recorded patches name the act trial's experience ids. The fake server's new `samples` rule ([fake-llm.md](../.agents/skills/verify-llm/references/fake-llm.md#recorded-calls-samples)) replays a person's own calls in order when the prompt names them (`# Who you are (Walker17)`), else the purpose's pool. The battle replays the act-trial battle's 15,868 calls; the town replays the four full town arms' 7,007.
- **The provider's limits as Mistral sent them.** Every reply carries `x-ratelimit-limit-req-minute: 1333` and `x-ratelimit-limit-tokens-minute: 10666666` (GLM) / `10000000` (DeepSeek), so the mind learns the same pacing as against Mistral (`pool_study.py script`). Two what-ifs scale them: both × 4 (a higher tier), and each alone × 4 (which limit binds).
- **The real models config.** `battle_diag.py --real-minds --fake-provider --fake-real-profiles` and `trials.py run --fake --fake-real-profiles` keep each profile's `max_tokens`, `purpose_max_tokens` and pacing (no fixed `requests_per_minute`), which the token estimate and the learned ceilings read. Only the endpoint, model name and key change. `--concurrency` sets the pool.
- **Loads.** *Battle:* `battle_diag.py --battle 200 --walkers 16 --minutes 8 --keep-plans`, every fighter and refill a mind on the `people` mix, as in the act trial, measured over minutes 2–8. *Town:* `trials.py run act-town --variants act-replace-off --minutes 20`, the island's first 40 adults of Brackenford as thinkers (Neo4j memory on), measured over minutes 2–20. Fast lane off, laws as on main, rethink gate and level of detail off.
- **Host.** A private SpacetimeDB 2.14.1 (`slop-poolstudy-20261121`, CPUs 5–9,15–19) and Neo4j. Driver, mind and fake were pinned to 5–9,15–19 and the samplers to 0–4,10–14. All under one `~/slop-mq/battle.lock` hold per series. Each run started with the 1-minute load under 4 and the merge lock free. A run whose load passed 8 in its measured window was redone (`b192` try 1 at 12.7, `b256` try 1 at 30.3, `t384` try 1 at 9.5; their reports are kept as `*-rejected-1`). The mind's CPU, RSS and threads were read from `/proc` every 2 s (`pool_study.py proc`). One run per cell; at 192 battle slots the rejected try agrees with the kept one within 2% on every figure.
- **Fidelity.** At 192 slots the fake battle reproduces the real one: urgent wait p50 / p90 12.1 / 13.2 s (real 12.4 / 14.4), GLM 916 calls and 7.8 M tokens a minute (real 889 and 7.6 M), 72 in flight (real 73), 323 calls per mind-hour (real 320). By purpose: think 101 (99), deliberate 102 (101), act repair 43 (39), talk 48 (53), consolidation 29 (28). The fake town at 64 slots: 81 calls per mind-hour (real 89–90; main has changed since: iter-11's needs pace, arm-replies), the same zero wait.

## Results

### Battle, 200 minds, Mistral's limits as advertised

| Slots | Urgent wait p50 / p90 / p99 (s) | Routine | Background (consolidation) | Calls a minute (GLM; GLM tokens) | In flight mean / max | Calls per mind-hour | Consolidations a minute | Mind CPU (cores), RSS mean / max (MB), threads |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | --- |
| 64 | 22.5 / 25.3 / 29.9 | 1.05 / 3.67 / 9.23 | 11.4 / 14.4 / 16.1 | 702 (591; 5.0 M) | 47 / 48 | 211 | 71 | 0.41, 628 / 639, 24 |
| 128 | 12.1 / 13.5 / 14.0 | 0.45 / 2.79 / 10.17 | 16.9 / 23.4 / 26.7 | 1,086 (918; 7.9 M) | 73 / 94 | 326 | 101 | 0.72, 619 / 624, 24 |
| 192 | 12.1 / 13.2 / 14.4 | 0.38 / 2.68 / 6.80 | 24.8 / 39.8 / 42.8 | 1,077 (916; 7.8 M) | 72 / 96 | 323 | 97 | 0.72, 614 / 619, 25 |
| 256 | 12.4 / 13.5 / 14.1 | 0.42 / 4.52 / 7.83 | 30.8 / 57.1 / 68.3 | 1,072 (905; 7.8 M) | 72 / 94 | 322 | 94 | 0.75, 610 / 618, 25 |
| 384 | 12.2 / 13.5 / 14.2 | 0.39 / 2.34 / 6.03 | 24.5 / 100.9 / 126.2 | 1,077 (912; 7.8 M) | 71 / 89 | 323 | 92 | 0.77, 621 / 630, 25 |
| *real, 192* | *12.4 / 14.4 / 15.3* | *0.64 / 3.63 / 8.04* | *33.2 / 42.7 / 44.9* | *1,065 (889; 7.6 M)* | *73 / 100* | *320* | *94* | – |

- **64 slots bind; 128 and more do not.** At 64 the lower lanes' 48 slots are always full: urgent calls wait twice as long (22.5 s), and the battle gets two-thirds of the calls (211 per mind-hour against 323). From 128 to 384 every figure is the same within run-to-run spread. In flight stays at 71–73 (at most 89–96) whatever the pool, because GLM's request pacing (above) gives out about 15 grants a second.
- **Background's queue wait moves; its throughput does not.** Consolidations also wait for `Minds::slow` (half the pool) before they queue, and that wait is not in `queue_wait_ms`. A bigger pool lets more of them into the queue, so their measured wait rises (p90 23 s at 128 slots, 101 s at 384), while integrations a minute stay at 92–101. 64 slots run fewer (71 a minute) because the battle runs fewer of everything.
- **Slots cost the mind service nothing measurable.** CPU follows the calls made (0.41 cores at 64 slots for 702 calls a minute; 0.72–0.77 at 128–384 for about 1,080); RSS stays at 610–630 MB and threads at 24–25. A slot is a counter in the queue, not a thread or a connection. The fake server used 0.01–0.03 cores.

### Which provider limit binds (192 slots unless named)

| Limits | Urgent wait p50 / p90 / p99 (s) | Calls a minute (GLM; GLM tokens) | In flight mean / max | Calls per mind-hour | $ per mind-hour |
| --- | --- | --- | --- | ---: | ---: |
| As advertised | 12.1 / 13.2 / 14.4 | 1,077 (916; 7.8 M) | 72 / 96 | 323 | 0.268 |
| Tokens a minute × 4 | 12.1 / 13.7 / 14.2 | 1,082 (910; 7.8 M) | 72 / 92 | 325 | 0.267 |
| Requests a minute × 4 | **0.3 / 23.2 / 27.7** | 1,275 (1,063; 9.0 M) | 81 / 117 | 383 | 0.309 |
| Both × 4 | 2.6 / 3.7 / 4.6 | 2,139 (1,837; 15.7 M) | 126 / 144 | 642 | 0.515 |
| Both × 4, 64 slots | 22.4 / 26.8 / 28.9 | 706 (592; 5.1 M) | 47 / 48 | 212 | 0.175 |
| Both × 4, 384 slots | 2.5 / 3.6 / 4.8 | 2,182 (1,859; 15.9 M) | 128 / 166 | 655 | 0.524 |

- **Requests a minute bind first.** Raising the token limit alone changes nothing. Raising the request limit alone lets GLM up to 1,063 calls a minute, until its 9.6 M paced tokens bind (9.0 M actual). Urgent waits then turn bimodal: half the calls are granted at once, and the rest wait 20–28 s, as the 60 s token window fills and rolls over.
- **With both raised (a higher tier), the pool would bind at 192.** In flight reaches the lower lanes' 144 and urgent waits fall to 2.6 s. 384 slots add 2% more calls (128 in flight on average, 166 at most) and the same waits, because GLM's request pacing (12.5 ms a grant plus the wake delay) holds it at about 31 grants a second. At 64 slots the higher tier changes nothing: the same 22 s wait.

### Town, 40 minds, Mistral's limits as advertised

| Slots | Routine wait p50 / p90 / p99 (s) | Background | Calls a minute (GLM) | In flight mean / max | Calls per mind-hour | $ per mind-hour | Mind CPU, RSS mean / max (MB) |
| ---: | --- | --- | --- | --- | ---: | ---: | --- |
| 32 | 0.00 / 0.00 / 0.20 | 0.0 / 0.1 / 0.6 | 57 (50) | 4 / 24 | 85 | 0.096 | 0.02, 241 / 261 |
| 64 | 0.00 / 0.01 / 0.10 | 0.0 / 0.3 / 1.4 | 54 (49) | 4 / 33 | 81 | 0.093 | 0.02, 259 / 276 |
| 192 | 0.00 / 0.00 / 0.08 | 0.0 / 0.3 / 1.5 | 56 (51) | 4 / 35 | 85 | 0.096 | 0.02, 251 / 269 |
| 384 | 0.00 / 0.00 / 0.10 | 0.0 / 0.3 / 1.5 | 56 (48) | 4 / 35 | 83 | 0.094 | 0.02, 248 / 263 |
| *real, 64* | *0.00 / 0.00–0.05 / 0.09–0.12* | *0.0 / 0.15–0.24 / 0.6–1.4* | *59–60 (51–53)* | *5–7 / 41–43* | *89–90* | *0.105* | – |

- **A town never fills a pool.** 40 minds keep 4 calls in flight. The one burst is the first two minutes: every resident's identity, consolidation or sleep at once (79 background calls). It waited p90 2.3 s at 64 slots and 3.1–3.2 s at 192 and 384, and only 0.7 s at 32, where `Minds::slow` (16) held the burst before the queue. The wait is the request pacing's start at 600 a minute (one GLM call per 100 ms), not slots.

## Cost of a slot

Model cost is per call. Prices per call by purpose come from the act trial's journals: tokens (prompt less cached, cached, completion) × [MODEL_COST.md "Prices"](MODEL_COST.md#prices) (GLM 5.3 Flash $0.15 / $0.03 / $0.50 per million; DeepSeek V4.1 Flash $0.30 / $0.007 / $1.20). These totals reproduce the trial's $13.41 battle and $8.32 for the four full town arms.

| $ per call | think | deliberate | act repair | talk | consolidate | reorganize |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Battle | 0.000751 | 0.001277 | 0.0000802 | 0.000338 | 0.001463 | – |
| Town | 0.000963 | 0.001564 | 0.0000950 | 0.000628 | 0.001373 | 0.003102 |

$ per mind-hour = Σ (calls per mind-hour of a purpose × $ per call):

- **Battle, 192 slots:** think 100.9 × 0.000751 + deliberate 101.7 × 0.001277 + act repair 43.3 × 0.0000802 + talk 48.3 × 0.000338 + consolidate 29.0 × 0.001463 = 0.0758 + 0.1299 + 0.0035 + 0.0163 + 0.0424 = **$0.268 per fighter-hour, $53.6 an hour for 200** (the act trial spent $6.74 in 8 minutes, about $50 an hour).
- **Battle, 64 slots:** 63.5 × 0.000751 + 63.2 × 0.001277 + 29.1 × 0.0000802 + 33.4 × 0.000338 + 21.4 × 0.001463 = 0.0477 + 0.0807 + 0.0023 + 0.0113 + 0.0313 = **$0.173, $34.7 an hour for 200.**
- **Battle, both limits × 4, 192 slots:** 213.0 × 0.000751 + 213.3 × 0.001277 + 94.1 × 0.0000802 + 90.8 × 0.000338 + 30.8 × 0.001463 = 0.1599 + 0.2723 + 0.0075 + 0.0307 + 0.0450 = **$0.515, $103 an hour for 200.**
- **Town, 64 slots:** 20.3 × 0.000963 + 20.5 × 0.001564 + 6.5 × 0.0000950 + 8.2 × 0.000628 + 25.7 × 0.001373 + 0.08 × 0.003102 = 0.0195 + 0.0321 + 0.0006 + 0.0051 + 0.0353 + 0.0002 = **$0.093 per resident-hour, $3.7 an hour for 40** (real arms: $0.105).

- **In a town, slots change nothing:** 81–85 calls per mind-hour at every size from 32 to 384. The minds ask what their lives ask for.
- **In a battle, calls follow supply:** a fighter has a deliberation pending most of the time, so each grant freed is used. Calls per mind-hour track throughput exactly: 211 at 64 slots, 323 at 128–384, 383 with the request limit raised, 642–655 with both raised. In the 40-fighter functional run before the series (`minds-pss-b40`, minutes 1–3, not under the measurement rules), where nothing waited, fighters made 860. The extra calls are rethinks: think and deliberate rise together (about 100 each per hour at 192, 213 each at × 4), act repair and talk in proportion, and consolidation stays at 28–31 (paced by `consolidate_min_s`). So the cost of more battle throughput is linear in it, about $0.00083 a call ($0.268 / 323).
- **Per added slot, at today's limits:** 64 → 128 slots adds 113 calls per fighter-hour, about **$0.095 per fighter-hour, $19 an hour for 200 fighters**, and halves urgent waits (22.5 → 12.1 s). Each slot from 128 to 384 adds **$0**, since calls do not change. At a × 4 tier, 192 → 384 adds 13 calls per fighter-hour (+2%, $0.009) and no wait.

## Recommendation

1. **Keep `LIVING_CONCURRENCY` at 192.** At Mistral's limits as advertised, a 200-mind battle needs about 100 calls in flight at most, so 128 is the smallest pool that does not bind, with nothing to spare (96 lower-lane slots against a peak of 94). 192 leaves room for about 45% more calls in flight (144 lower-lane slots), for the interactive quarter, and for the full island of minds that set it ([SEEDED_LIVES.md](SEEDED_LIVES.md#every-person-a-mind): about 120 in flight). A town of 40 needs 32 or fewer. Do not go back to 64: it doubles battle waits (12 → 22.5 s urgent). Going above 192 buys nothing, even at a × 4 tier (+2% calls at 384). It costs the service nothing either, but it lets more consolidations into the model queue (`Minds::slow` is half the pool), where they wait behind urgent work instead of before it.
2. **The battle's 12 s wait is GLM's request pacing, not the pool.** The levers, in order of effort:
   - *The pacing wake* (code, free to test): `Queue::spacing_deadline` skips the deadline wake for any profile with a token limit, which Mistral always sends, so a call held by request spacing waits for the next 50 ms poll or event. GLM gets about 897 grants a minute of the 1,200 it is paced to. Waking at the deadline when tokens are not what holds the call would recover up to about a third. The tokens-a-minute pacing would then bind near 1,060 a minute (the "requests × 4" row: 383 calls per fighter-hour, +18%), with bimodal urgent waits. *Done on `pacing-wake`: 1,057 a minute, 375 calls per fighter-hour, urgent waits 9.2 s ("After the pacing wake", below).*
   - *Spreading purposes over models.* Mistral's limits are per model, and the battle sends 85% of its calls to GLM (think, compile off stage, act repair, consolidation). Compiles on DeepSeek, as the `people` mix already does on stage, would have DeepSeek's own 1,333 a minute. That is a model choice with a price and a behaviour; it is for the owner, not this study.
   - *The token estimate.* A GLM call is reserved at 14.8 k tokens while in flight (prompt bytes / 3 + its purpose's `max_tokens`) and uses 8.7 k. Once requests stop binding, that over-reservation is what holds tokens at 9.0 M actual against a 9.6 M ceiling. *On `pacing-wake` the completion part is reserved from observed usage (13.9 k → 12.1 k by a recount from the request bodies; +1.5% grants, within one run's noise); the prompt part is kept.*
   - *A higher Mistral tier.* It raises the account's per-model limits (the help page; no numbers published). At × 4 the battle runs at 2.6 s urgent waits and 192 slots just hold.
   - *Level of detail* (`LIVING_LOD`), which lowers what the minds ask for instead.

   In a battle every lever that raises throughput raises spend with it, about $0.00083 a call. At × 2 throughput that is $0.52 instead of $0.27 per fighter-hour, $103 instead of $54 an hour for 200 fighters. In a town none of them changes anything.

## After the pacing wake (branch `pacing-wake`, 2026-11-21)

Two commits on main `e09365be` merged with `pool-study` (`6346a266`; the study is on main since `67521779`), measured on the same fake replay. **`LIVING_CONCURRENCY` stays 192.** After both commits 128 is still the smallest pool that does not bind (the same calls and waits as 192, below), but its calls in flight now reach its 96 lower-lane slots at peaks; 192 keeps the margin for the interactive quarter and for a whole island of minds. Do not lower it to save something: a slot costs nothing (above), and 128 would save no call.

### 1. A call held only by request spacing wakes at its deadline (`ca9ae5f2`)

**Cause, confirmed.** `Queue::spacing_deadline` (`living/mind/src/llm.rs`) returned `None` when `rate.tpm.is_some()`. Every Mistral profile has a token limit once its first reply's `x-ratelimit-limit-tokens-minute` arrives (`Rate::feedback`), so a lane head held only by spacing fell back to `admit`'s 50 ms poll, or to the next grant, completion or feedback (`changed`). **Fix:** the deadline is returned with a token limit too, when the head call's reservation fits the last minute's tokens now. It then still fits at the deadline: the window only drains, and any grant in between notifies every waiter. Which call is granted, and the lanes' order, are unchanged; only when a waiter wakes changes. **Test:** `a_call_held_only_by_spacing_wakes_at_its_deadline_with_a_token_limit` (explicit clock: 1,200 a minute, 100,000 tokens) fails on the code before (`left: None`) and passes after; it also checks that a call the token window holds gets no deadline.

### 2. Pacing reserves a call's expected completion; a hard bound covers the rest (`ee4fc2a4`)

A call in flight was reserved at prompt bytes / 3 + 8 a message + its purpose's whole `max_tokens`. Recounted from the act-trial battle's request bodies (13,521 GLM calls, both arms), that is 13.9 k a call, against 8.7 k used. The prompt part is 23% over GLM's actual prompt tokens (0.27–0.30 tokens a byte against the third reserved); the completion part is the cap, which few calls approach:

| GLM purpose (cap) | Calls | Completion p50 / p90 / p99 / p99.9 / max | At the cap | Now reserved (2 × p99, at most the cap) | Calls over it |
| --- | ---: | --- | ---: | ---: | ---: |
| think (1,500) | 5,162 | 268 / 354 / 462 / 655 / 1,500 | 1 (0.02%) | 926 | 3 (0.06%) |
| deliberate (6,000) | 5,045 | 293 / 492 / 1,115 / 6,000 / 6,000 | 36 (0.71%) | 2,234 | 36 (0.71%) |
| consolidate (6,000) | 1,468 | 1,342 / 2,212 / 3,334 / 5,536 / 6,000 | 2 (0.14%) | 6,000 | 0 |
| act repair (1,500) | 1,846 | 44 / 130 / 253 / 423 / 530 | 0 | 516 | 1 (0.05%) |

- **The rule** (`Scheduler::reserve`): pacing reserves the prompt estimate (unchanged) plus twice the 99th percentile of that profile's last 512 completions for the purpose, at most the cap, and the whole cap until 100 replies have said their usage. It learns from the live replies, so it follows a model or prompt change. On the act trial's calls it reserves 12.1 k a GLM call instead of 13.9 k. The prompt estimate is kept: a third of a byte is a bound for any text this tokenizer has seen, and tightening it is a tokenizer-dependent bet.
- **The hard bound** (`Rate::tpm_hard`, `Rate::ready_at`): every grant must also fit a second count, in which each call in flight stands at its prompt estimate plus its whole cap and each answered call at its reported usage, under the limit the provider advertises (10,666,666 for GLM, the header before the 10% headroom). Pacing's own count stays under 0.9 × that (9.6 M).
- **What happens when a call uses more than it reserved.** Its reply replaces the reservation with its actual usage, so the minute's count can rise above pacing's 9.6 M by at most that call's overrun (the act trial's worst: a deliberate 3,766 tokens over its 2,234). Later grants then wait until the window drains under 9.6 M again. The overrun cannot take the minute past the advertised 10.67 M, because the hard count already had every call in flight at its cap: a completion cannot pass `max_tokens` (the request sends it), and the prompt estimate was above the actual prompt on all 13,521 calls. The guarantee before was the same at 90% of the limit; now the expected case is held at 90% and the worst case at 100%. A profile with only a configured `tokens_per_minute` (no headers) gets no looser rule than before: its configured limit is the hard one.
- **The provider counts what is used.** In the real act-trial battle, the GLM calls sent in a 60 s window would have reserved prompt + `max_tokens` = 11.45–11.56 M at the peak, above the advertised 10.67 M, and no call came back rate-limited. Mistral did not count the caps at admission.
- **Not changed:** a 429 still halves the rate and honours `Retry-After`; zero remaining tokens still pauses the profile for a minute. Two risks are as before: the provider's minute may be a fixed bucket where the mind's is rolling, and a prompt in a script with more than a third of a token a byte would be under-estimated.
- **Tests:** `a_reservation_below_max_tokens_never_lets_the_worst_case_pass_the_advertised_limit`, `the_completion_reservation_learns_twice_the_p99_and_starts_at_max_tokens`.

### Measured: the fake battle before and after

The pool study's method (above): `battle_diag.py --battle 200 --walkers 16 --minutes 8 --keep-plans --real-minds --fake-provider --fake-real-profiles --concurrency 192`, the act-trial battle's recorded calls replayed under Mistral's advertised limits (`pool_study.py samples` / `script`, the same script as the study's), minutes 2–8. Each commit's release `living-mind` was built before the series and run through `LIVING_VERIFY_MIND_BIN`. Private SpacetimeDB 2.14.1 `slop-pacingwake-20261121`; container, driver, mind and fake on CPUs 5–9,15–19, samplers and builds on 0–4,10–14, no build during the series; one `~/slop-mq/battle.lock` hold, the merge lock free and the 1-minute load under 4 at each start (0.4–3.2); the measured windows' load peaked at 3.8–6.0, so no run was redone. Fast lane off, laws as on main.

| Commit (slots) | Urgent wait p50 / p90 / p99 (s) | Routine | Background | Calls a minute (GLM; GLM tokens) | GLM grant gap p1 / p50 / mean / p90 (ms) | In flight mean / max | Calls per mind-hour | $ per fighter-hour ($ an hour for 200) |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: |
| Before: `6346a266` (192) | 11.8 / 13.4 / 14.3 | 0.40 / 5.35 / 10.86 | 24.9 / 40.5 / 43.2 | 1,076 (913; 7.80 M) | 50 / 58 / 65.5 / 89 | 72 / 96 | 323 | 0.267 (53.4) |
| Before, again (192) | 12.0 / 13.4 / 14.1 | 0.40 / 3.24 / 8.03 | 23.6 / 39.5 / 42.1 | 1,074 (906; 7.77 M) | 50 / 59 / 66.0 / 90 | 72 / 94 | 322 | 0.266 (53.3) |
| 1. Wake `ca9ae5f2` (192) | 9.2 / 10.7 / 14.2 | 0.30 / 1.43 / 4.65 | 4.7 / 29.1 / 33.6 | 1,251 (1,057; 9.04 M) | 50 / 52 / 56.5 / 68 | 82 / 106 | 375 | 0.309 (61.7) |
| 2. + reservation `ee4fc2a4` (192) | 9.2 / 10.6 / 11.9 | 0.26 / 1.57 / 5.97 | 3.2 / 27.5 / 33.4 | 1,259 (1,073; 9.12 M) | 50 / 52 / 55.8 / 63 | 82 / 107 | 378 | 0.310 (62.0) |
| 2. + reservation (128) | 9.1 / 10.6 / 13.0 | 0.30 / 1.55 / 4.52 | 3.4 / 19.0 / 21.7 | 1,252 (1,071; 9.12 M) | 50 / 52 / 55.9 / 62 | 81 / 96 | 376 | 0.308 (61.7) |

- **The wake brings GLM's grants to the 50 ms spacing.** The median gap falls from 58 to 52 ms and the mean from 65.5 to 56.5; GLM gets 1,057 grants a minute instead of 906–913 (+16%), as the study's "requests × 4" row predicted (1,063). Urgent waits fall by about a fifth (p50 11.8 → 9.2 s); routine and background waits fall more.
- **Tokens now bind, as predicted.** The rest of the gap to 1,200 a minute is GLM's token pacing: 9.0–9.1 M used plus the reservations of the calls in flight fill the 9.6 M. The reservation change gives 1,073 grants a minute against 1,057 (+1.5%) and a tighter tail (gap p90 63 against 68 ms, urgent p99 11.9 against 14.2 s). Two runs of the same "before" binary differed by 0.8%, so one run each does not separate this from noise; the mechanism is small by construction (12.1 k against 13.9 k reserved on about 70 GLM calls in flight, some 0.13 M of 9.6 M).
- **Never over the limit.** GLM's actual tokens in any 60 s window peaked at 9.27 M (wake) and 9.41 M (reservation), under both the 9.6 M pacing and the advertised 10.67 M. No call failed in any run.
- **Cost follows throughput.** Calls per fighter-hour rise 323 → 375 → 378, think and deliberate together (about 100 → 118 each), consolidation stays at 29–31. By the study's prices per call: $0.267 → $0.309 → $0.310 per fighter-hour (reservation run: think 118.7 × 0.000751 + deliberate 119.4 × 0.001277 + act repair 52.7 × 0.0000802 + talk 55.8 × 0.000338 + consolidate 31.1 × 0.001463 = 0.0891 + 0.1525 + 0.0042 + 0.0188 + 0.0455), $53 → $62 an hour for 200 fighters. In a town nothing changes: it never queues.
- **The pool.** At 128 slots the reservation commit gives the same calls (376 against 378 a mind-hour) and waits (urgent p50 9.1 s) as at 192, so 128 still does not bind; its in flight reaches 96, all its lower lanes' slots, at peaks. The mind used 0.76–0.86 cores and 607–620 MB in every run.
- **Evidence:** `.local/pacingwake/` (drivers, plan, `chain.log`, per-run `report.json`, loads and binary hashes) and `.local/living/verify/minds-pw*` (journals, mind logs), archived to `~/pacing-wake/pacing-wake-20261121.tar.zst` on the Spark; the analysis scripts (`analyze.py`, `reserve.py`, `completions.py`) beside it.

## Paid confirmation run (a proposal; not run)

**None is needed for the pool size.** The question is answered by the act trial's own journals: the 12 s came with at most 100 of 144 slots in use, and grants held to GLM's 50 ms spacing. The fake replay reproduces that run within a few percent on every queue figure. A paid run at another pool size would only repeat it: at 128, 256 or 384 slots the model calls are the same.

**With the pacing wake (`pacing-wake`),** one paid battle would check what the fake cannot:

- *What it checks:* whether Mistral accepts about 1,100–1,300 GLM calls a minute without 429s or capacity errors, with 80–120 calls in flight. And whether GLM latency stays at its act-trial values at that rate, since the fake replays latencies recorded at up to 100 in flight.
- *Size:* `battle_diag.py --battle 200 --walkers 16 --minutes 8 --keep-plans --real-minds --allow-live --concurrency 192`, main plus the change, guarded by `act_trial.py watch` (spend, failures, backlog), under `battle.lock`, one run.
- *Estimate:* the "requests × 4" row's 1,275 calls a minute × 8 minutes ≈ 10,200 calls × $0.000845 (the act-trial battle's $13.41 / 15,868 calls) ≈ **$8.6; cap $11**. At today's rate, the act trial's 8 minutes cost $6.74.

## What this does not show

- One run per cell (at 192 battle slots, a rejected try agrees within 2%). One seed, one battle layout and one town.
- The fake returns real latencies regardless of how many calls are in flight; a provider that slows under concurrency would make a bigger pool worth less, not more. The × 4 rows assume Mistral would serve that rate as it served 1,060 a minute.
- Replayed replies are another moment's replies: a fighter may be told to strike someone not there. The battle's call mix still matched the act trial's by purpose within about 12%; the town's main purposes within 10%, its small ones less well (talk 8 against 13 per mind-hour).
- Queue wait excludes `Minds::slow` (consolidation and identity before the queue) and the mind's preparation (20–30 ms since fast-dispatch). Consolidation's whole delay is not measured; its throughput is.
- The fast lane (off) and interactive calls (no player) are not exercised. A player's calls go first and may use the whole pool.

## Tools and evidence

- `living/tools/pool_study.py`: `samples` (recorded calls from journals), `script` (the fake's script with rate-limit headers, `--limits-scale`), `proc` (the mind's and fake's CPU, RSS and threads), `report` (queue wait per lane and purpose, throughput, in flight, calls per mind-hour).
- `fake_llm.py` rule fields `samples` and `latency_scale`, and a top-level `log_body: false` ([fake-llm.md](../.agents/skills/verify-llm/references/fake-llm.md#recorded-calls-samples)). `fake_contract.py` gains a `samples` scenario (11 of 11 pass).
- `battle_diag.py --fake-script --fake-real-profiles`; `trials.py run --fake-real-profiles --concurrency N`.
- Evidence: `~/slop-poolstudy/pool-study-20261121.tar.zst` on the Spark (SHA-256 sidecar and a per-file `.files.sha256`; to be moved into `~/slop-evidence` by its owner), with `.local/poolstudy/` (the drivers, plan, per-run `report.json`, `proc.jsonl`, loads, mind logs and journals of every run, the real-run reports, no keys). Recorded-call files are rebuilt from the act-trial archive with `pool_study.py samples`.
