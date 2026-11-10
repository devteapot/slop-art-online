# Mind harness (2026-11-09)

How the mind service chooses models, schedules sleep, thinks for animals, keeps fast judgments, bounds recall and decides when to rethink. Six items, each behind its own switch where it changes behavior, each with its own evidence. Branch `harness-1` (items 1–5) and `rethink-1` (item 6). The evidence base is [MODEL_COST.md](MODEL_COST.md) Parts 1 and 2.

| Item | What changed | Switch | Default |
| --- | --- | --- | --- |
| 1. Model mixes | per-purpose and per-stage model choice; effort per purpose | `mixes` in `models.json` | defined; Brandholm uses `deepseek-people` |
| 2. Sleep at night | purpose `reorganize`; night scheduling; night batches, uploaded above 2.4 MB | `LIVING_REORGANIZE` | `night-batch` |
| 3. Cheaper animal minds | pick among built options; one mind per pack; think on salient change | `LIVING_ANIMAL_MINDS` | off |
| 4. Jev judgments | `judged` graph condition; background refresh through TypeSafe | `LIVING_JEV` | off |
| 5. Recall budget | token budget on recalled lines; no repeated `rel` property | `LIVING_RECALL_TOKENS` | `decide=800` |
| 6. Rethink gate | a fast judge (Jev, or a cheap LLM) in front of non-urgent deliberations decides when the slow mind thinks | `LIVING_RETHINK` (`jev`, `llm`) | off |

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
- **Effort** comes from the choice's `@effort`, else from the profile's map for the purpose, else for its parent: `reorganize` inherits `consolidate`. An older profile therefore never sends reorganization at GLM's default effort, which behaves like `max` (MODEL_COST Part 1). Since 2026-11-10 a map entry may be `null` (send none on purpose), and every purpose a route can reach without an entry is logged at start (see [the 2026-11-10 fixes](#fixes-from-the-rules2-r2-review-2026-11-10)).
- **`purpose_max_tokens`** caps one purpose apart from the profile's `max_tokens`. Since 2026-11-10 every profile caps every purpose (below).
- **Stage of attention** is the level of detail's: on stage while a human player is in the character's scene or was part of what it lived within `LIVING_LOD_STICKY_S` (600 s). It is tracked when `LIVING_LOD=1` or when any mix is staged; otherwise everyone is on stage. A staged mix changes which model is called, never how often.
- **Startup refuses a file that names what does not exist**, a mix that names a mix, an unknown purpose, or a default mix without `*`. A mix with an unkeyed profile is disabled with a warning and passed over. A purpose sent with no effort entry is warned about (`MODEL CONFIG: …`).
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
  - **`night-batch` (default).** Everyone due goes out as one provider job per route, with later rounds in the same night at most every 60 s. People in a job are marked consolidating, so no integration interleaves. A job not done within a game day is cancelled, and its people go direct the next night. Since 2026-11-10 a few failed polls do not lose the job, an abandoned job is cancelled, and a job left by a stopped service is collected at the next start (below).
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

## 6. Rethink gate

Decided 2026-11-09 with the user: Jev (about 150 ms) is not real-time, so it never drives moment-to-moment choices; the behaviour graph stays the real-time layer. Jev's place is between the graph and the slow mind, deciding **when the slow mind should think**. Branch `rethink-1`.

**Why.** Every trigger the authority raises becomes a full deliberation (think, then compile): a plan that finished, a plan with no applicable branch, failing actions, a quiet moment, dawn, a feeling, a call. The trials ([TRIALS.md](TRIALS.md) on `trials-1`) found the waste there: subjects re-deliberating every 25–60 s to re-ask residents who never answer, and plans resting on remembered things that are gone. In the replay below, the theft subjects deliberated back to back every 6–8 s.

**Built** ([rethink.rs](../living/mind/src/mind/rethink.rs), [rethink.json](../living/configs/rethink.json)). The switch is `LIVING_RETHINK=jev` or `llm` (alias `glm`); it is off by default.

- **Where:** in `schedule`, after the level of detail lets a request go and before `deliberate`. Only `kinds` (people) are gated.
- **Never gated:**
  - reasons the level of detail grades `Prompt` or `Now`: being attacked or threatened, a fight report, starving, badly hurt, other bodily alarms (a need crossing danger), calls of one's own kind, offers, family and join requests;
  - a deliberation lane other than `routine`: anything a human player did, and reasons with combat words;
  - the config's `urgent` substrings (deaths);
  - the first thought after the service starts.
- **Held, not dropped:** a held request stays pending in the authority, which merges every later reason into it (up to its 900-byte reason cap) and refreshes its scene. Each merge, and each new percept, asks the gate again. The deliberation that finally runs sees everything that gathered. A held character is `deferring`, as under the level of detail, so it still takes conversation turns.
- **Re-raised triggers** with the same reasons and nothing perceived since the last judgment are held without asking. Example: "I finished my plan." is raised every 8 s while a sequence plan keeps finishing.
- **Release:** a yes; an urgent merge; `max_hold_s` (600 s; the 2 s tick lets the request through); or a failing or slow judge (`fallback` past `timeout_ms`), which proceeds as without the gate.
- **The state** is built in code, because Jev is weak at counting, times and numbers ([model jaggedness](https://docs.typesafe.ai/model-jaggedness.md)). It holds only the character's own plans and perception:
  - the plan and its outline, the pending reasons and the needs as words (`hungry`, `badly hurt`);
  - since the last thought: what it perceived, what succeeded and what failed, folded with counts;
  - lines to people who did not answer in the last 10 minutes, with counts;
  - the plans of its last three thoughts, with their ages.
- **Percepts:** the authority deletes consolidated experiences, so the gate keeps its own ring per character (128 percepts, 30 minutes). It is fed by the experience insert callback that already exists, and only when the gate is on.
- **Jev arm:** one `POST /v1/systemone` (`jev-1.14.0`) per character with three nouls over one state:
  - `plan_broken`: has the plan stopped working?
  - `unhandled`: has something happened that it does not handle?
  - `would_repeat`: would thinking again end in the same plan as the recent thoughts?
  - Combined in code: p = max(`plan_broken`, `unhandled`) × (1 − `would_repeat`), deliberating at p ≥ `jev.proceed_above` (0.3).
- **The cheap-LLM arm:** the same state and one yes/no question with a probability on `glm-flash@low` (purpose `rethink`), deliberating at p ≥ `llm.proceed_above` (0.7).
- **Configuration:** thresholds, questions, the combination, timeouts, `max_hold_s`, the urgent list and the state's limits are configuration, not code.
- **Batching:** TypeSafe answers several questions against **one** `state`. Several characters in one state would mix private minds in one prompt, which this project rules out ([JEV_BEHAVIOR_RESEARCH.md](JEV_BEHAVIOR_RESEARCH.md)), and would grow the state, which Jev handles worse. So each character gets its own request, its three questions share one state, and requests run concurrently. There is no multi-state batch endpoint.
- **Records:**
  - every decision: a journal entry with purpose `rethink-gate` (verdict, p, the answers, threshold, reasons, how long it was held, the state, any error);
  - the judge's exchange: purpose `rethink`, with `cost_usd` for Jev;
  - a `rethink gate (<arm>): Stats {…}` log line every minute.
- **Replay:** `living-mind rethink-replay --arm jev|llm --out FILE DIR...` rebuilds the same state at every deliberation of trial evidence directories (from `thoughts`, `experiences`, `graphs`, `samples` and `mind_rows`) and asks the same gate. [rethink_report.py](../living/tools/rethink_report.py) scores replays against blind labels, and live trial batches by rows and journals.
- **SpacetimeDB:** no schema, reducer, view or subscription change. The gate reads rows the service already subscribes to (`brain`, `persona`, `my_deliberations`) from the client cache and uses the existing `experience` insert callback ([subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), docs version 2.0.0, read 2026-11-09: row callbacks and local-cache reads cost no server work). What changes on the authority is that a held `deliberation` row lives longer and absorbs merges at the trigger rate, as under the level of detail: one row per character, rebuilt per merge (about 0.15 ms, LIVING_CORE "Minds at scale").

**Replay** (`living-mind rethink-replay`, [rethink_report.py](../living/tools/rethink_report.py) `replay`). The gate was asked at every real deliberation of 16 Spark trial runs (b1: theft, hungry, hungry-village and teacher × 3; w1: life-default r1 and r3; w2: life-valley and life-pressure r1). Those are 714 trigger points. 64 were urgent or a first thought and are never judged, which leaves 650.

| | Jev (`jev-1.14.0`) | GLM Flash `low` |
| --- | ---: | ---: |
| Latency p50 / p95 | 135 / 171 ms | 1,436 / 3,956 ms |
| Input tokens per question | 1,420 | about 910 (+43 output) |
| Cost per question | $0.00006 | $0.00016 |
| All 650 questions | $0.039 | about $0.10 |
| Held at the replay's threshold of 0.5 | 450 (69%) | 158 (24%) |

The two arms agree on 48% of triggers. The disagreements run one way: 313 triggers that Jev holds and GLM lets through, against 22 the other way.

*Blind judging.* 142 points were sampled across the four agreement cells (50, 35, 35 and 22) and weighted back to the 650. Two fresh Claude subagents judged them, 71 each, from the state and what the deliberation actually produced: its thought, new plan, speech and acts. They never saw a gate verdict. Each point was labelled `useful`, `marginal` or `wasted`, with a waste kind and whether skipping it would have hurt the character (the reasons waiting for a later thought).

- **Of the 650 non-urgent deliberations:** 37% useful, 20% marginal and **42% wasted**. **16%** would have hurt to skip.
- **The waste is mostly restated plans:** of the 93 wasted or marginal points (unweighted), 57 were restated plans, 15 phantom targets, 12 asking loops and 9 other.
- **In the theft runs** the subjects re-deliberated back to back every 6–8 s with nothing new between thoughts.

*Operating points.* Each row lists the share of triggers held; the share of wasted deliberations caught; the share of harmful-to-skip and of useful deliberations held; and the ratio of wasted caught to harmful held. A random gate holding h% catches h% of each kind, a ratio of 2.6.

| Rule | Held | Wasted caught | Harmful held | Useful held | Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jev, unless × 1.0, p ≥ 0.5 (as replayed) | 69% | 87% | 59% | 52% | 3.9 |
| **Jev, unless × 1.0, p ≥ 0.3 (configured)** | **46%** | **62%** | **19%** | **30%** | **8.4** |
| Jev, unless × 0.5, p ≥ 0.4 | 34% | 51% | 19% | 14% | 7.0 |
| Jev, no `would_repeat`, p ≥ 0.6 | 37% | 56% | 25% | 17% | 5.8 |
| GLM, p ≥ 0.5 (as replayed) | 24% | 32% | 13% | 10% | 6.3 |
| **GLM, p ≥ 0.7 (configured)** | **41%** | **54%** | **30%** | **22%** | **4.7** |
| GLM, p ≥ 0.8 | 48% | 58% | 36% | 31% | 4.3 |

- **Both judges discriminate, Jev somewhat better.** At about the same hold rate (46% against 41%), Jev at 0.3 catches more waste (62% against 54%) and holds fewer harmful skips (19% against 30%).
- **Asking loops:** Jev at 0.5 held 98% of them, GLM 44%.
- **What the `would_repeat` question does.** It accounts for most of Jev's holds. It is also where Jev's harmful holds come from: plans plainly broken ("You keep turning back and forth", an empty pack at nightfall) were held because the last thoughts looked alike.
- **The thresholds were chosen on this sample.** 0.3 for Jev and 0.7 for GLM give the two arms similar hold rates. The live run below is the out-of-sample check.
- **Evidence:** `.local/living/rethink/` on the dev-box worktree: `replay-jev.jsonl`, `replay-llm.jsonl`, `judge-items.jsonl`, `judge-key.jsonl`, `labels1.jsonl` and `labels2.jsonl`.

**Live run** ([rethink_report.py](../living/tools/rethink_report.py) `live`, batch `rlive`, 2026-11-09 22:58–23:48).

- **Setup:** the trials' `life` trial (the shipped island, one mind-backed newcomer, instinct-only residents) in three arms (gate off, Jev at 0.3, GLM at 0.7), 3 replicates of 45 minutes each, all 9 at once.
- **Where:** on the dev-box, in a local checkout of main plus `trials-1` plus this change (not pushed), with the variants `rethink-jev` and `rethink-glm`, private containers `rethink-trials-stdb` (2.14.1) and `rethink-trials-neo4j`.
- **Models:** people on `glm-flash` as configured; paid calls.
- **Units:** a game hour is 30 real seconds. Rates pool every run's own duration, so the runs cut short by a death count for the time they lived.

| | Off | GLM gate | Jev gate |
| --- | ---: | ---: | ---: |
| Real hours (game hours) | 1.94 (232) | 2.25 (270) | 1.64 (196) |
| Deliberations per game hour | 0.43 | 0.27 (−37%) | 0.21 (−50%) |
| Think + compile tokens per game hour | 6,798 | 4,324 (−36%) | 3,495 (−49%) |
| All mind tokens per game hour (with consolidation, without the gate) | 7,623 | 5,024 (−34%) | 4,167 (−45%) |
| Gate calls per real hour (and tokens per game hour) | – | 49 (433) | 47 (570) |
| Gate verdicts | – | 71 rethink, 40 hold, 1 fallback | 39 rethink, 38 hold, 2 urgent |
| Mind $ per real hour | 0.137 | 0.096 | 0.080 |
| Gate $ per real hour | – | 0.009 | 0.003 |
| **Total $ per real hour** | **0.137** | **0.105 (−24%)** | **0.082 (−40%)** |
| Survived 45 min | 2/3 | 3/3 | 1/3 |
| Food gathered per game hour | 0.25 | 0.15 | 0.15 |
| Techniques learned (per run) | 0, 4, 0 | 0, 0, 4 | 0, 0, 0 |
| Structures built (per run) | 0, 2, 0 | 0, 0, 2 | 0, 0, 0 |
| Asking loops (3+ unanswered lines to one person in 10 min) | 0, 1, 0 | 0, 0, 1 | 1, 1, 0 |

- **The saving holds out of sample.** Jev held 49% of what it judged live (38 of 77), against 46% in the replay. GLM held 36% (40 of 111), against 41%. Re-raised triggers with nothing new were held without a call, beyond these counts.
- **Jev's cost:** about $0.003 per real hour, under 6% of what the gate saves.
- **The deaths are not the gate's.** All three were a wolf on the town road (Rook twice, Frost once) attacking from 5–10 tiles and killing in about 10 s. In the two Jev runs the attack went through as `urgent` within a second. The last holds before it were unrelated triggers ("no branch applies", "you feel something") 80–160 s earlier. The same wolf killed a b1 subject with no gate. A deliberation takes seconds and could not have changed those fights.
- **Quality is not established.** Both gated arms gathered less food per game hour (0.15 against 0.25), and the Jev runs learned and built nothing (the off and GLM arms each had one run that learned 4 techniques and built 2 structures). With 3 runs per arm, 2 of them shortened by deaths, this is a possible cost, not an effect size. Asking loops were rare in these life runs in every arm; the replay, where they were common, is the better evidence for them.
- **Evidence:** dev-box `~/dev/slop-rethink/.local/living/rethink/rlive/`, which holds each instance's journal (with every `rethink-gate` decision), `mind.log`, samples, experiences, `summary.json` and `rethink-report.json`. *(Removed by mistake on 2026-11-10 when the coordinator cleaned up the dev-box worktree; the raw journals are gone and the figures in this document are the remaining record.)*

### Answer: does Jev's speed and typedness matter?

- **Speed does not matter here.** The gate is off the real-time path: a held trigger waits by design, and GLM's 1.4 s (4 s at p95) is still small next to a deliberation.
- **Typed, calibrated answers matter somewhat.** In the blind replay, Jev separated waste from harmful skips better at the same hold rate, 8.4 against 4.7 wasted caught per harmful held. A random gate scores 2.6.
- **Cost:** Jev's question costs a third of GLM's. Its three nouls cost 1.5× GLM's input tokens and nothing for output.
- **Any cheap classifier gets most of the saving:** GLM saved 24% live and Jev 40%. The difference is mostly where each was set, Jev holding more, and part of Jev's extra holds are the harmful ones.

### Recommendation: iterate, not adopt yet

The gate does what it was built for. It cuts deliberations by 37–50% and cost by 24–40%, it costs little (Jev under 6% of what it saves), urgent paths are untouched, and every skip is journaled. Adopting it as a default needs evidence that the held thoughts are not costing the minds. Next steps:

1. **Narrow `would_repeat`.** The replay's harmful holds came from it overriding a plainly broken plan ("turning back and forth", an empty pack at nightfall). Try `unless` only when `plan_broken` is low, or a weight of 0.5 (34% held, 51% of waste caught, 19% of harmful skips held, 14% of useful).
2. **Test quality with power.** Run the Spark trials with more replicates, longer lives and a preset without the road wolves, so food, learning and building can be compared. Add the gate to the hungry, theft and teacher trials, where the asking loops were.
3. **Keep Jev over GLM** for this gate: better separation at a third of the price per question. Revisit if the TypeSafe dependency matters more than about $0.003 per person-hour.
4. **The cost at scale is small.** 2,000 people at the live rate (about 47 Jev calls per person-hour at about 1,450 tokens) come to about $5.7 per hour of Jev. On TypeSafe's rate limits, that is 26 requests per second.

### Verification (rethink-1)

Dev-box worktree `~/dev/slop-rethink`, private SpacetimeDB 2.14.1 container `rethink-stdb` on `127.0.0.1:3397`, private `CARGO_TARGET_DIR`.

| Surface | Run | Result |
| --- | --- | --- |
| `set -o pipefail; just living-check` | before the commit | exit 0 |
| Mind unit tests | `cargo test -p living-mind` | rethink: state counts, combination, urgent bypass, ages as words, unchanged re-triggers |
| verify-minds | `minds-full-232622` (all 17 cases, the new `rethink` and `rethink-llm` included) | all pass; `consolidation` stays the known XFAIL |
| verify-llm | `llm-rethink-230523` (all 16 cases) | all pass |
| After merging main (`townlife-2`, `trials-1`; conflicts in `mind.rs` only, additive) | `just living-check`; mind tests; `minds-merged-010653`: rethink, rethink-llm, wake, conversation, lod, roundtrip, jev | exit 0; 69 passed; all pass |
| Final, after merging main `fe6ec66` (`feedback-1`, `iter-6`, `lives-1`, `soak-1`; no conflicts; the gate is unchanged, since feedback-1's gone-thing note is added inside `deliberate`, after the gate, which still sees the original failure) | `just living-check`; mind tests; `minds-final-091241` (all 17 cases); `llm-final-094629` (all 16) | exit 0; 71 passed; all pass, `consolidation` the known XFAIL; all pass |

- **Failed attempts first:** the fake's Jev endpoint crashed on the gate's needs-in-words body, which exercised the fallback path; the case asserted before the mind had started; `max_hold_s` 25 released the request mid-case; a poll raced the fake mind; and the container's mount needed the `z` SELinux label on Fedora. All were fixed in the harness. The "unchanged" rule moved to a unit test, because whether a re-raised trigger finds a new percept depends on the world's timing.
- **`maintain-verification-skill` on the minds surface, scoped to this change:**
  - new `features/rethink.md`, the feature index row, the case list and description in `SKILL.md`;
  - the fake server (`verify-llm`): a `rethink` purpose on the chat and Jev endpoints, `contains` rule matching, and per-question nouls; its reference was updated to match;
  - source checked for the features the diff touches (deliberation scheduling, conversation turns while held, level of detail, the Jev endpoint); the live pass is the full suite above;
  - no separate per-feature source readers.
- **Not covered:** a paid `verify-minds` or `verify-llm` tier. The paid evidence is the replay and the live trials above.
- **Measurement checkout:** the trials runner on this Fedora host needed two local changes: the `z` label on its `/wasm` mount, and the full Neo4j image name, since podman refuses short names. They stay in the measurement checkout; `trials-1` should take them.

### Spend (rethink-1)

| What | Provider | Calls | $ |
| --- | --- | ---: | ---: |
| Replay, Jev arm (650 questions) | TypeSafe | 650 | 0.039 |
| Replay, GLM arm (650 questions; 222 journaled, priced from those) | Mistral | 650 | about 0.10 |
| Live, 9 runs of up to 45 min (minds) | Mistral | – | 0.61 |
| Live, gate calls | TypeSafe / Mistral | 77 / 112 | 0.005 / 0.020 |
| **Total** | | | **about $0.78** |

Claude side, not billed to a provider here: two blind judges (about 120k tokens each).

### Files (rethink-1)

- **New:**
  - `living/mind/src/mind/rethink.rs`: the gate, the state builder, both arms, the replay;
  - `living/configs/rethink.json`;
  - `living/tools/rethink_report.py`;
  - `.agents/skills/verify-minds/features/rethink.md`.
- **Shared mind files, kept to the deliberation-trigger path:**
  - `living/mind/src/mind.rs`: a module, an event, four fields, the gate call in `schedule`, the tick hook;
  - `living/mind/src/mind/talk.rs`: `thinking` honours `deferring` with the level of detail off too;
  - `living/mind/src/main.rs`: percept events when the gate is on, the `rethink-replay` subcommand.
- **Harness:**
  - `.agents/skills/verify-minds/scripts/verify_minds.py` (`rethink`, `rethink-llm`), `SKILL.md` and `features/README.md`;
  - `.agents/skills/verify-llm/scripts/fake_llm.py` and `references/fake-llm.md`.
- **Docs:** this section, the table at the top, and LIVING_CORE.md ("Deliberation hygiene").
- **Not changed:** authority, rules, bindings, `models.json` and `judgments.json`.
- **Other branches:** `townlife-2` also edits `mind.rs`, `talk.rs` and `main.rs`. This diff touches `schedule`, `run`, `thinking` and the experience callback only.

## Fixes from the rules2-r2 review (2026-11-10)

Reviewers measured the `rules2-r2` trial journals (1,129 real calls, `.local/living/trials/rules2-r2/journal/`) and read the code at 6c8d1002. Each defect below was confirmed against the code and the journal before it was fixed. Branch `fix-mind-small`, one commit each; prompt edits are separate commits.

| Defect | Evidence | Fix |
| --- | --- | --- |
| One output cap (24,000 on GLM Flash) for every purpose | A compile ran 24,000 tokens of `"places", …` for 166 s; one DeepSeek compile ran to 8,000. Normal p99: think 465, compile 1,008 (DeepSeek `low` 3,857), consolidate 2,388, reorganize 11,879. The longest usable compile was 4,547 tokens (GLM `low`, about 4,100 of them reasoning). | `purpose_max_tokens` on every profile: think 1,500; talk and rethink 1,000; deliberate, consolidate and internalize 6,000; reorganize 24,000. A test keeps every profile capped. |
| A timeout gated the whole base URL | Two GLM compiles hit the 180 s timeout; GLM and DeepSeek share `api.mistral.ai`, so both were held. | Only a failed connection marks a host unreachable. verify-llm `timeout` asserts no gate. |
| Background work overflowed to the other profile at that profile's settings | `deepseek-flash` mapped only think and deliberate, so a failed consolidation, integration or reorganization went to DeepSeek with thinking off (reorganize judged 4/21). | `Lane::Background` never overflows; its caller retries later with a backoff on its own model. A 429 keeps its one paced retry. Startup logs each purpose a route can send without an effort entry; `null` says "none on purpose" (DeepSeek's talk, consolidate, internalize). The project file has no gaps (a test). |
| A failed batch poll lost the whole batch and paid twice | Poll and download used `?`; one error failed every member, the night's people went direct at full price, and the orphaned job still billed. | Up to 5 failed polls or reads in a row are tolerated; an abandoned job is cancelled; each sent job is kept in `<journal>/batches/<job>.json` and collected at the next start (reorganizations applied, player memory journaled). Fake provider: `batch.poll_errors`. |
| The compile wrote fields the mind discards, and lost speech | `keep()` replaces the compiler's `thought`, `say`, `judgments` and `places` with the think step's, but the format asked for them (30% of compile reply characters). 13 of 434 compiles put speech in a `{"do": "say"}` act, which the authority refuses. | Code: a compiled say act becomes the turn's speech when the decision has none, and never reaches the authority. Prompt: the compile format asks for acts, plan, intent and graph or patch only. |
| The persona listed every community member | 77 names, 11–20% of think and consolidation input, growing with the town. | A count, and by name only the members one has feelings about (at most 12). |
| A failed deliberation consumed its trigger | A model error called `mind_skip`, clearing the request and its reasons; the rethink gate then counted the old plan as a new thought; "carries on" replies dropped their stances and places. | A model error keeps the request; it is retried after 5 s, doubling to 5 minutes, with conversation turns meanwhile; the gate records only successful thoughts; stances and places apply on both paths. verify-llm `outage` asserts the request survives. |
| Every feeling or stance cited the whole consolidation batch | Shorthand relations and judgments carried every experience id; `because` was unioned without bound; every kept memory then GROUNDED every stance of its batch. | Shorthand entries cite their own `because` (default none); an edge cites at most 8 experiences, the newest kept on re-assertion. Prompt: the memory formats show `because` on relations and judgments. |
| Adults could get a newborn's identity | A person with no sheet narrative and a recorded parent went to `birth_persona` at any age; authored towns give sheet parents to adults. A woken resident whose mind could not be made was marked made. | `Origin::of` chooses by life stage, then background (unit-tested); a failed waking is retried 3 times, then at most every 5 minutes. |
| Smaller | The weakening id pattern matched `exp:<id>` keys; `missed_upto` was memory-only; the animal retry resent the whole reply; the journal had no `finish_reason` and repeated the system prompt (57% of journal bytes, 5.4 MB per mind per trial). | `exp:` excluded; the bound is derived from the mind's `weakened_by` after a restart; the retry keeps 3,000 characters; journal entries record `finish_reason` and `reasoning_tokens`, and each distinct system prompt is stored once (`system/<hash>.txt`, `content_ref`; `living/tools/journal_io.py` restores it). |

Not changed: how memory fades (wall clock against game time; the owner has not decided).

SpacetimeDB: no table, reducer, view or subscription changed. A failed deliberation now leaves its `deliberation` row pending (one row per character, as under the level of detail and the rethink gate) instead of calling `mind_skip`; an error thought is added through the existing `mind_update`.

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

- **No `vitals` subscription** (fixed on `feedback-1`, [mind feedback](MIND_FEEDBACK.md#1-the-body-in-prompts)): the service now subscribes, as the owner, to the vitals of the characters it thinks for, so `repertoire_text`'s "how that need stands now" shows, prompts say how the body feels, and judgments read the body at the moment of the request.
- **Real-time judgment is slower than the fights:** a 4 s refresh on a 2 s tick, plus about 1 s for Jev, against fights decided in 7–30 s. Faster refresh or event-triggered asks are the next step.
- **Animal menus are single steps:** `choose` cannot chain a stalk, a signal and an attack.
- **The 2.5 MiB inline limit** is from one measurement (MODEL_COST Part 2); the 2.4 MB threshold leaves 4% margin.
- **`just living-generate` fails on the dev-box** at its compose step (podman-compose). The bindings were generated with the same `spacetime generate` in a v2.14.1 container.
- **Processes killed by another session:** at 20:51 another session's cleanup ran `pkill -f living-mind`, which killed every mind on the host. Affected: `sleep-n1`, `animals-real1`, verify-llm `routing-assign` and verify-minds `animals` (h3). All were rerun; the evidence directories of the killed runs are kept.
