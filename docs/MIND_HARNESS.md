# Mind harness (2026-11-09)

How the mind service chooses models, schedules sleep, thinks for animals, keeps fast judgments and bounds recall. Five items, each behind its own switch where it changes behavior, each with its own evidence. Branch `harness-1`. The evidence base is [MODEL_COST.md](MODEL_COST.md) Parts 1 and 2.

| Item | What changed | Switch | Default |
| --- | --- | --- | --- |
| 1. Model mixes | per-purpose and per-stage model choice; effort per purpose | `mixes` in `models.json` | defined; Brandholm uses `deepseek-people` |
| 2. Sleep at night | purpose `reorganize`; night scheduling; night batches, uploaded above 2.4 MB | `LIVING_REORGANIZE` | `night-batch` |
| 3. Cheaper animal minds | pick among built options; one mind per pack; think on salient change | `LIVING_ANIMAL_MINDS` | off |
| 4. Jev judgments | `judged` graph condition; background refresh through TypeSafe | `LIVING_JEV` | off |
| 5. Recall budget | token budget on recalled lines; no repeated `rel` property | `LIVING_RECALL_TOKENS` | `decide=800` |

## 1. Per-purpose model mixes

**Built.** A **mix** in [models.json](../living/configs/models.json) names a model per purpose:

```json
"mixes": {
  "people": {
    "think": "glm-flash",
    "deliberate": {"on_stage": "deepseek-flash@low", "off_stage": "glm-flash"},
    "talk": "deepseek-flash",
    "consolidate": "glm-flash",
    "reorganize": "glm-flash",
    "*": "glm-flash"
  },
  "deepseek-people": {"*": "deepseek-flash", "reorganize": "glm-flash"}
}
```

- **Where a name is accepted, a mix is too:** `default`, `assign`, `rotate`, `stages`, `groups` and `species`.
- **A choice** is a profile, a profile with its own effort for that purpose (`deepseek-flash@low`), or one per stage of attention. `*` covers the purposes a mix leaves out; a purpose it does not cover goes to the default.
- **Effort** comes from the choice's `@effort`, else from the profile's map for the purpose, else for its parent: `reorganize` inherits `consolidate`. An older profile therefore never sends reorganization at GLM's default effort, which behaves like `max` (MODEL_COST Part 1).
- **`purpose_max_tokens`** caps one purpose apart from the profile's `max_tokens`.
- **Stage of attention** is the level of detail's: on stage while a human player is in the character's scene or was part of what it lived within `LIVING_LOD_STICKY_S` (600 s). It is tracked when `LIVING_LOD=1` or when any mix is staged; otherwise everyone is on stage. A staged mix changes which model is called, never how often.
- **Startup refuses a file that names what does not exist**, a mix that names a mix, an unknown purpose, or a default mix without `*`. A mix with an unkeyed profile is disabled with a warning and passed over.
- **The journal** records `profile`, `effort` (what was sent), `mix` and `attention` on every exchange, so purpose × profile × effort can be read back with [llm_load.py](../living/tools/llm_load.py) or `jq`.

**What the file now does:**
- **The default stays `glm-flash`.** `people` is defined but not assigned; it is the mix MODEL_COST Part 2 recommends trying: compile on DeepSeek `low` on stage only (+€0.06 per on-stage person-hour, the best compiler judged), talk on DeepSeek (12/12 judged, beat GLM `high` 7–1–4).
- **Brandholm moves from the `deepseek-flash` profile to `deepseek-people`.** It thinks exactly as before but reorganizes on GLM `high`; DeepSeek with thinking off was judged 4/21 at reorganization.
- **GLM Flash's map** gains an explicit `reorganize: high`.

**Evidence.**
- Cargo tests in `llm.rs`:
  - `mixes_route_each_purpose_and_stage_with_its_effort`: every purpose, both stages, `@effort` over the profile's map, the parent purpose, the default fallback, an unusable mix passed over, a mix through `groups`;
  - `a_models_file_naming_what_does_not_exist_is_refused`;
  - `the_request_body_carries_the_picked_effort_and_the_purpose_cap`;
  - `the_projects_models_file_is_valid`.
- The verify-llm case `mix` drives the real mind against two fake providers. One adult on a staged mix is compiled off stage; a player joins, is placed beside them and speaks; the next compile is on stage. Every journal entry's profile, effort, mix and stage matched the mix, and the fake logs saw the same `(model, reasoning_effort)` pairs. Evidence: `.local/living/verify/llm-h2-200554-mix/` (on the dev-box worktree).

**Spark trials should test:** assign `people` to one town and compare its decisions and spend against a GLM-only town, with players walking in and out; watch DeepSeek's first-token latency at the hours that matter (it swung threefold in Part 2).

## 2. Reorganization as its own purpose, at night, in night batches

**Built** ([sleep.rs](../living/mind/src/mind/sleep.rs)):
- **Purpose.** Reorganization goes out as `reorganize`, a background-lane purpose, with its own effort and cap. On GLM Flash that is `high` and 24,000 tokens: MODEL_COST Part 2 found 35% cut off at 8,000 and 24/24 usable at 24,000.
- **When.** At night by the world clock: `LIVING_NIGHT`, default `20-6`, which the mind already subscribes to. The mind cannot see the body's sleep. A mind is due after at least 2 integrations and 1,200 s since its last sleep, at most once a night (`LIVING_REORGANIZE_MIN`, `_GAP_S`). This is the rule that MODEL_COST's simulation put at about half a town per night. Consolidation no longer preempts it.
- **How** (`LIVING_REORGANIZE`):
  - **`night-batch` (default).** Everyone due goes out as one provider job per route, with later rounds in the same night at most every 60 s. People in a job are marked consolidating, so no integration interleaves. A job not done within a game day is cancelled, and its people go direct the next night.
  - **`night`.** The same rule, with direct calls.
  - **`timer`.** The old rule.
- **Uploads.** `Llm::batch` uploads a JSONL file (`POST /v1/files`, then `input_files`) once the inline body would pass 2.4 MB; Mistral's proxy refuses about 2.5 MiB.
- **Animals** are due by the same rule and only fade.

**Evidence.**

*How many sleep.* [sleep_nights.py](../living/tools/sleep_nights.py) ran the world seed (167–177 people with minds, fake model, Neo4j off) for 45 real minutes, about three game nights, in `timer` and `night-batch` modes side by side:

| Mode | People | Reorganizations in 45 min | People who reorganized | Per game night | By day | Rounds sent |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| `night-batch` | 178 | 356 | 178 | nights 1 and 3: 178 each; nights 2 and 4: 0 | 0 | two rounds a night, all batched (175 + 3, 174 + 4) |
| `timer` (today's rule) | 177 | 476 | 174 | 56, 95, 81, 70 | 118 (25%) | – |

- **Every other night:** with 12-minute game days, the 20-minute gap makes each person due every other night. That averages 0.5 per person per night, about 100 a night in a town of 200. It matches MODEL_COST's simulated 98 for a town on stage.
- **Against today:** on the real aske-coast runs, 28–46 of about 71 people reorganized in 4–6 hours, about 7 a night scaled to 200. Night batches reorganize about 14 times as many.
- **The fake model overstates the timer.** It answers instantly, so minds are rested and idle far more often than with a real model. The timer's 476 here is not today's production rate. What it does show is that the timer is not aligned to night: a quarter of its sleeps fell by day.
- **Integrations:** the two modes made the same number (4,275 against 4,236). A night round holds people for only seconds with the fake, and for one job's turnaround (about 300 s, below) with a real model.
- **Evidence:** `.local/living/sleep-nights/n2/report.json` and `.local/living/verify/sleep-n2-*/mind.log`. A first attempt (`n1`) lost its minds at 20:51, when another session's cleanup ran `pkill -f living-mind` (that session confirmed it). It was stopped, cleaned up and rerun as `n2`, with both minds alive from start to end.

*A real night, end to end through the mind's batch path.* The 200 real reorganization prompts of MODEL_COST Part 2 went out as one job through `Llm::batch` on the `people` mix (`night_batch_replay`, an ignored Cargo test):

| Requests | How it went up | Turnaround (create → done) | Usable replies | Prompt / completion tokens | € list | € at batch price |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 200 | uploaded file (`input_files`), 5.0 MB | 296 s (300 s for the client) | 199/200 | 1,747,917 / 1,172,630 (31,104 cached) | 0.72 | about 0.36 |

- **Effort and cap:** every request was sent at `high` with the 24,000 cap. The job id is `aa98720b-84b6-4c3a-b614-a8565a935cfa`, and the journal is in `.local/living/night-batch/journal/`.
- **Fit in a night:** a game night lasts 300 real seconds, so a town of 200 sending everyone due at dusk gets its answers back within the same night.
- **Cost:** €0.0018 per reorganization at batch price. A town of 200 with about half due per night (five nights an hour) costs about €0.9 per real hour, or €0.0045 per person-hour. That matches MODEL_COST's estimate of 2–7% of planning.

*Correctness.*
- `night_of`/`due` Cargo tests in `sleep.rs`.
- `a_large_batch_is_uploaded_as_a_file`: the fake provider, one inline job and one uploaded job, each line carrying the mix's `high` and the 24k cap.
- verify-minds `night`: a round of one and the end of its sleep in the live mind.
- verify-knowledge `sleep_batch`: a fresh mind with Neo4j; the request is uploaded, answered under a batch job and applied, and the thought is marked `batch`.

**Spark trials should test:** night-batch on a real town over several game days; reorganizations per person-night, judged quality of what they merge and retract, and whether minds stay compact.

## 3. Cheaper animal minds

**Built** ([animal.rs](../living/mind/src/mind/animal.rs)). Three switches in `LIVING_ANIMAL_MINDS`, any combination:
- **(a) `pack`:** the animal that thinks decides for the others of its kind it sees. For `LIVING_ANIMAL_PACK_S` (60 s), their requests reuse that decision without a call, each weighed by its own temperament (0.6× to 1.4× by the trait that drives the option).
- **(b) `salient`:** the animal thinks only on a salient change since its last thought: a new kind of creature seen or smelled, being attacked or threatened, a wound band crossed, a death among its kind, or hunger crossing a band. Otherwise the request is answered by instinct, with no call.
- **(c) `choose`:** one call, not two. The model picks a numbered option built from the scene and the species' skills (carry on; flee from, hunt or attack the nearest other creatures; keep close to its kind; rest; roam; signal), with a strength. The graph comes from a template, so it is valid by construction, and it still goes through `from_value_for` and `mind_install`.
- **The rules are not touched.**

**Evidence.** [animal_minds.py](../living/tools/animal_minds.py), seed `stage1-wolves` (40 deer and 6 wolves by a family of people on instinct; animals think only near people). Each variant had its own scratch world for 20 real minutes, with a fake model that rotates through the choices offered:

| Variant | Animal-hours | Decision calls per animal-hour | Est. prompt tokens per animal-hour (decisions) | Memory calls per animal-hour | Thoughts installed | Invalid graphs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| today | 15.9 | 8.8 | 18,000 | 5.2 | 55 | 0 |
| salient | 15.7 | 7.4 | 15,100 | 5.1 | 44 (13 by instinct) | 0 |
| choose | 15.6 | 5.9 | 5,400 | 5.3 | 76 | 0 |
| pack (+choose) | 15.5 | 4.4 | 4,300 | 5.5 | 81 (24 shared) | 0 |
| all three | 15.4 | 2.7 | 2,600 | 5.3 | 65 (28 shared, 11 by instinct) | 0 |

- **Totals:** all three cut decision calls by 70% and decision prompt tokens by 86%.
- **Behavior coverage:** every valid pick was installed; across the runs the choices flee, rest, roam, keep close, signal and carry on were all taken.
- **Memory is now the larger cost.** Memory calls are untouched by these switches.

Real model, GLM Flash (the project's profile, `deliberate: high`). `today` against all three switches, 15 minutes each, about 11.5 animal-hours per variant. Tokens and € are from the journals' billed usage:

| Variant | Decision calls per animal-hour | Decision prompt / completion tokens per animal-hour | € per animal-hour, decisions | € per animal-hour, memory | p50 decision latency | Choices taken | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| today | 7.9 | 17,783 / 3,022 | 0.0031 | 0.0019 | 3.2 s | – | 0 |
| all three | 4.1 | 4,526 / 551 | 0.0008 | 0.0019 | 1.8 s | flee 31, keep close 7, hunt 4, rest 1 (plus 21 pack-shared and 9 by instinct) | 0 |

- **Decisions:** 74% cheaper and faster. An animal-hour falls from €0.0050 to €0.0027 in all, because memory, untouched, is now 70% of it.
- **The first real attempt (`real1`)** lost its minds in the 20:51 kill. It was rerun as `real2`; `real1` cost €0.08 and is not used.
- **A bug the real run found:** a deer whose top level no longer parsed got "no top level to weigh the impulse against". The impulse now becomes its top level, as with an animal's flat plan, and the verify-minds `animals` case passes.

- verify-minds `animals`: three deer by a person, with all switches on. The lead deer's request is answered by one `choose` call and its graph installed; the other two reuse its decision with no call; the lead asked again at dawn is answered by instinct. The fake log holds exactly one choice and no compile.

**Spark trials should test:** whether hunts, flights and herding still look like animals with `choose` (the menu has no multi-step plans; an impulse could chain a goto, an attack and a signal); and whether `salient` misses changes that matter, such as a slow threat or prey that comes back.

## 4. Jev judgment layer (prototype)

**Built.**

*The rules (`living/rules/src/graph.rs`, `normalize.rs`).* A graph condition reads a cached typed judgment and never waits:
- **Shape:** `{"judged": {"q": "fight_risk", "above": 0.6, "else": false}}` compares a noul's probability or a score's level; `{"judged": {"q": "stranger", "is": "hostile"}}` matches a choice.
- **Fallback:** with no fresh judgment (none yet, expired or failed), the condition is its `else`, default false, so the branch after it runs.
- **Lenient parsing** accepts `question`, `id` and `fallback`.

*The authority: the minimal change.*
- A private table `judged` (`actor` btree index; at most 8 rows per character) holds the cache.
- The reducer `mind_judged`, which only the character's controller may call, upserts by question with a TTL of at most 10 minutes.
- `brain.rs` evaluates `Cond::Judged` with one indexed filter.
- The rows die with the character.
- No change to `script.rs` or `skills.rhai`. Bindings were regenerated with the 2.14.1 CLI; the diff only adds the table and the reducer.
- SpacetimeDB documentation read before the change (docs version 2.0.0, read 2026-11-09):
  - [tables](https://spacetimedb.com/docs/tables/): private by default, visible only to reducers and the owner;
  - [indexes](https://spacetimedb.com/docs/tables/indexes/): prefer indexed filters over scans;
  - [performance](https://spacetimedb.com/docs/tables/performance/): keep hot data in small, focused tables, private unless clients need them;
  - [reducers](https://spacetimedb.com/docs/functions/reducers/): batch work into one call;
  - [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/).
- Data path: the mind writes at most one row per question per refresh (every 4 s per fighting character whose graph reads it); the tick reads by `actor` index. Nobody subscribes; growth is bounded per character.

*The mind ([judge.rs](../living/mind/src/mind/judge.rs)).*
- **Declarations** live in [judgments.json](../living/configs/judgments.json): question, type, criteria, `refresh_s` 4, `ttl_s` 15, `when: fighting`.
- **Who is asked:** a character whose installed graph reads the question and which fought in the last 20 s. Its due questions go in one `POST https://api.typesafe.ai/v1/systemone` (TypeSafe's docs, read 2026-11-09: Bearer key, `{"model", "state", "questions"}`; model pinned `jev-1.14.0`; $0.042 per million input tokens; output free).
- **What the state holds:** the character's own goals, plan and temperament; its body as last felt in a deliberation scene, with its age (the service does not subscribe to `vitals`); its last ten experiences; and its feelings about who is in them.
- **Bounds:** one request in flight per character, everything off the tick.
- **Journal:** every exchange is journaled with purpose `judge`, latency, input tokens and cost.
- **Prompts:** when on, the compile grammar lists the judgments a graph may read.

**The first judgment:** `fight_risk`, "is continuing the fight you are in an unacceptable risk to what you want most?"

**Evidence.**
- Rules: `judged_reads_a_cached_value_or_its_fallback`.
- Mind: `answers_become_cache_values`, `the_projects_declarations_parse`.
- verify-minds `jev`: a defender whose graph flees above 0.6 is struck; the fake Jev answers 0.9; the row is cached with its expiry; the authority's tick takes the flee branch. The request carries only the defender's state.

**Did it change outcomes?** [judged_fight.py](../living/tools/judged_fight.py) ran a defender with that graph (flee while `fight_risk` > 0.6, else strike back) against attackers that strike every two seconds. There were three arms, three repeats each, 90 s per run. `real` is TypeSafe's `jev-1.14.0`, called from the dev-box:

| Attackers | Arm | Survived | Fled (first flee) | Died at | Judgments per fight | Values seen | Jev p50 / p95 latency |
| ---: | --- | ---: | --- | --- | ---: | --- | --- |
| 1 | none | 3/3 | – | – | 0 | – | – |
| 1 | fake | 3/3 | 0/3 | – | 5–6 | 0.0–0.24 | 1 / 2 ms (local) |
| 1 | real | 3/3 | 0/3 | – | 5–6 | 0.22–0.56 | 141–152 / 166–201 ms |
| 2 | none | 2/3 | – | 14 s | 0 | – | – |
| 2 | fake | 0/3 | 3/3 (5–10 s) | 16–22 s | 2–4 | 0.01 → 0.89 | 1 ms |
| 2 | real | 1/3 | 2/3 (5–13 s) | 22–25 s | 4–7 | 0.21 → 0.94 | 136–174 / 174–240 ms |

- **The judgment works as built.** It stays low in a fight the defender is winning and rises with its wounds, and the graph reacts within one tick of the cache changing.
- **It changed outcomes, for the worse.** Against two attackers, fleeing on foot gets the defender cut down from behind: 2/3 survived without Jev, 0/3 and 1/3 with it. The fault is the response the graph gives the judgment, not the judgment: here fleeing stops the strikes back while the attackers keep reach.
- **Cost:** about 900 input tokens per judgment, about $0.00004 each. The 18 real fights cost $0.0012 in all.
- **Not established:** with n = 3 per arm and random hits (none-arm survival swung from 7 to 84 hp), these runs show the mechanism and its latency, not an effect size.
- **Evidence:** `.local/living/jev/r1/`, `.local/living/jev/r2/` and `.local/living/verify/jev-r*-*/`. Earlier tries `f1`–`f4` had setup faults and are not used: the mind's needs repair replaced a non-desires test graph; the release binary predated Jev; with three attackers the defender died in 7 s, before a judgment could refresh; and a seq-graph attacker stopped after one blow.

**Spark trials should test:** the judgment on fights between minds rather than a fixed attacker; a `choice` judgment ("is this stranger hostile?") on first meetings; refresh cadence against how fast fights are decided here (seconds); and letting the compile prompt use `judged` when a mind writes its own graphs.

## 5. Recall budget

**Measured** with [recall_budget.py](../living/tools/recall_budget.py) on 900 first-attempt prompts (300 per purpose) from two aske-coast runs: real model, real Neo4j recall, 71 people.

| Purpose | Recall tokens, median (p90) | Share of the prompt | Lines | Lines the reply uses | Use by activation rank (top 4 → last) |
| --- | ---: | ---: | ---: | ---: | --- |
| think | 1,203 (1,358) | 17% | 25 | 20% | 31% → 20% |
| compile (`deliberate`) | 1,189 (1,362) | 8% | 25 | 16% | 26% → 18% |
| consolidate | 1,990 (2,299) | 24% | 40 | 60% | 82% → 61% |

- **"Used":** the reply names something only that line holds, or both of its ends. This is a proxy, not a judgment.
- **What it shows:** a decision carries about 1,200 tokens of recall, of which the reply uses about a fifth, and activation order predicts use only weakly.
- **Embeddings:** `mistral-embed` similarity between each line and the situation (the reason, perception and decision, or the experiences being integrated), 100 prompts per purpose, 800k tokens, $0.08. AUC for predicting use: think 0.59 against 0.57 by activation, compile 0.61 against 0.61, consolidate 0.54 against 0.74. Not worth a call per prompt: activation stays the ranking.
- **Redundancy:** 8% of recalled text was a `rel:` property repeating the relationship's type.

**Built** ([recall.rs](../living/mind/src/mind/recall.rs), [memory.rs](../living/mind/src/memory.rs)):
- **No repeated `rel`:** a `rel` property equal to the relationship's type is no longer rendered (a different one is kept).
- **Token budget:** recalled lines are kept in the order they came to mind while they fit a token budget per call (`LIVING_RECALL_TOKENS`, default `decide=800`; `consolidate`, `animal` and `talk` have no budget unless set; `off` disables).
- **Expected saving:** on the measured prompts, `decide=800` saves about 410 tokens per think or compile prompt (6% of a think prompt, 3% of a compile) and keeps about 70% of the lines the reply used. Consolidation, which uses most of what it recalls, is left alone.

**Quality check:**
- **Setup:** 10 think prompts from two other aske-coast runs were sent twice on GLM Flash `low`, once as recorded and once with recall cut to a deliberately tight **600** tokens and `rel` deduplicated (623 tokens saved per prompt, €0.02).
- **Judging:** one fresh Claude judge, blind to which was which.
- **Result:** full recall acceptable 10/10, budgeted 9/10. The budgeted reply was better 5 times, worse 3 and tied 2, with equal mean scores (3.6). The one failure invented berries in a storage. With n = 10 no loss shows; the default is the more conservative 800.

**Spark trials should test:** `decide=600` against `decide=800` on judged decision quality, and a budget for talk.

## Verification

Dev-box worktree `~/dev/slop-harness`, private SpacetimeDB 2.14.1 container `harness-stdb` on `127.0.0.1:3393` (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`; the harness change was taken unchanged from rhai-1 21491a9), private `CARGO_TARGET_DIR`. Free tiers only; the opt-in live probes were not run.

| Surface | Run | Result |
| --- | --- | --- |
| `just living-check` | before the first commit and after the merge with main | exit 0 both times |
| verify-llm | `llm-full-204908` (all cases, the new `mix` included), `llm-ra-*` (`routing-assign` rerun) | all pass. `routing-assign`'s first run lost its mind in the 20:51 kill. |
| verify-minds | `minds-full-211116` (all 14 cases), earlier `minds-h1`/`h2` for the new cases | all pass; `consolidation` stays the known XFAIL. The first `animals` runs failed on two case faults and one fake-server fault, all fixed (see its validation record). |
| verify-knowledge | `knowledge-h1-213225` | all proofs pass, the night batch (uploaded file, applied) included. Three failed runs before: the new stage counted the deliberately stopped first mind as a dead process; Oren's mind was too small to send; and an existing step raced the mind's first decision (now waited out). One run timed out in an existing authority step under heavy load. |
| verify-core | `core-h1-210220`: Cargo (rules 101, authority 10, mind 63, viewer sync 3), scenes needs, seize and sight; `tick` rerun as `core-tick-214545` | pass. The first `tick` timed out after its first three checks while the box was loaded; the rerun passed all six. |
| verify-player | `player-h1-210225`, combat scenes on the island | 25/25 |

Skills changed (`maintain-verification-skill`, scoped to the features whose shape changed: the maps were rewritten from this branch's source and each was driven live in the runs above; no separate per-feature source readers):
- verify-llm: new `mixes.md`; `batch.md`, `routing.md`, the feature index and the fake-server reference rewritten for mixes, uploads and the `reorganize`, `judge` and `choose` purposes.
- verify-minds: new `animals.md`, `sleep.md`, `judgments.md` and cases `animals`, `night`, `jev`.
- verify-knowledge: new `sleep.md` and stage `sleep_batch`; the knowledge scripts follow `LIVING_STDB_URL`.
- verify-core: `graphs.md` covers `judged`.

## Spend

| What | Provider | Calls | € (or $) |
| --- | --- | ---: | ---: |
| Night batch, 200 real reorganizations (GLM `high`, 24k), one job | Mistral | 200 | 0.36 at batch price, assumed half (0.72 list) |
| Real animal minds, `real2` (`today` and all switches, 15 min each) | Mistral | 186 | 0.09 |
| Real animal minds, `real1` (killed at 20:51, not used) | Mistral | about 150 | 0.08 |
| Recall: `mistral-embed` relevance test (800k tokens) | Mistral | 200 batches of 64 | $0.08 (€0.07) |
| Recall: 10 think prompts × 2 on GLM `low` | Mistral | 20 | 0.02 |
| Jev: 18 real fights | TypeSafe | 98 | $0.0012 |
| **Total** | | | **Mistral about €0.62 (€0.98 at list); TypeSafe $0.0012** |

Claude side, not billed to a provider here: one blind judge (about 130k tokens) and three documentation fetches (about 165k tokens).

## Files

- **Mind:** `living/mind/src/llm.rs` (mixes, `Pick`, effort per purpose, `purpose_max_tokens`, batch upload, journal fields); `mind.rs` (attention, wiring); new `mind/sleep.rs`, `mind/animal.rs`, `mind/judge.rs`; `mind/recall.rs` (token budget); `memory.rs` (no repeated `rel`); `prompts.rs` (animal choose, `judged` grammar); `main.rs` (contact events when staged); `mind/lived.rs` and `mind/talk.rs` (new call signatures).
- **Rules and authority (the minimal change for item 4):** `living/rules/src/graph.rs` and `normalize.rs` (`judged`); `living/authority/src/tables.rs` (`judged` table), `mind.rs` (`mind_judged`), `brain.rs` (evaluation), `act.rs` (death cleanup); `living/bindings` regenerated. `script.rs` and `skills.rhai` are untouched.
- **Configuration:** `living/configs/models.json` (mixes, `reorganize: high`, Brandholm on `deepseek-people`); new `living/configs/judgments.json`.
- **Tools:** new `living/tools/animal_minds.py`, `sleep_nights.py`, `judged_fight.py` and `recall_budget.py`.
- **Skills:** listed under Verification.
- **Docs:** this file; [LIVING_CORE.md](LIVING_CORE.md) (the Models row and sleep).

## Known gaps and defects found

- **No `vitals` subscription:** the mind service does not subscribe to `vitals`, so `repertoire_text`'s "how that need stands now" never shows. Judgments use the last deliberation scene instead.
- **Real-time judgment is slower than the fights:** a 4 s refresh on a 2 s tick, plus about 1 s for Jev, against fights decided in 7–30 s. Faster refresh or event-triggered asks are the next step.
- **Animal menus are single steps:** `choose` cannot chain a stalk, a signal and an attack.
- **The 2.5 MiB inline limit** is from one measurement (MODEL_COST Part 2); the 2.4 MB threshold leaves 4% margin.
- **`just living-generate` fails on the dev-box** at its compose step (podman-compose). The bindings were generated with the same `spacetime generate` in a v2.14.1 container.
- **Processes killed by another session:** at 20:51 another session's cleanup ran `pkill -f living-mind`, which killed every mind on the host. Affected: `sleep-n1`, `animals-real1`, verify-llm `routing-assign` and verify-minds `animals` (h3). All were rerun; the evidence directories of the killed runs are kept.
