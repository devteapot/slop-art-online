# Trials: one mind in a scripted world

Status: **implemented, first real batches run** (2026-11-09, DGX Spark). A trial is a predictable world in which exactly one character, the subject, is backed by a real model mind and everything else follows scripts and behaviour graphs. Many trials run in parallel, with replicates and variants, so that one mind's responses to a known situation can be compared across runs, mind settings and worlds. The labs ([stage log](STAGES.md)) had every person thinking at once, which made it hard to tell where behaviour came from; a trial fixes the situation and varies only the mind.

A seed does not make inference repeatable. Every table below reports replicates side by side, with their spread, not a single run.

## The trial format

A trial is a JSON file in [`living/trials/`](../living/trials/). Fields:

| Field | Meaning |
| --- | --- |
| `title`, `about` | What the trial puts in front of the subject, in words. |
| `world.seed` | A seed name from `living/seeds/` (`island`, `stage1-wolves`, `stage3-village`, …). |
| `world.rules`, `world.overrides` | Merged over the seed. The runner writes the result as a derived seed, `.local/living/trials/seeds/trial-<seed>-<hash>.json`, which both the module build and the mind read (`LIVING_SEED` is resolved under `living/seeds/`, so a relative path works). |
| `world.start_hour` | The world hour at which the trial starts (worlds start at 07:00 and a world hour is 30 real seconds, so 16:00 is 4.5 real minutes after publishing). |
| `minutes` | Real minutes from the start until the runner stops the mind. |
| `budget.tokens`, `budget.calls_per_min` | Optional. A token cap (the runner stops the mind when the journal reaches it) and `LIVING_LLM_PER_MIN`. None of the shipped trials sets either: trials measure, they do not cap. |
| `subject.pick` | Who the subject is: `kind`, `stage`, `bg` (background fields, e.g. `{"town": "Elmwick"}`), `group`/`not_group` (the k-th town or band in id order), `lacks` (techniques not known), `fewest_know_how`, `youngest` (fewest days old at the start), `nearest` (an anchor), `count`. `stage` is the life stage code (0 infant, 1 child, 2 adult, 3 elder). |
| `subject.clear_items`, `subject.background` | Drop everything carried (through the ordinary `drop` act), and replace the background, usually with an authored sheet ([authored worlds](AUTHORED_WORLDS.md)) so that the subject starts as the same person in every replicate and world without a model call. |
| `cast.<role>.pick` | Scripted characters, picked the same way. |
| `timeline` | Steps. `"at": "prepare"` runs right after publishing, `"at": "start"` at the start hour before the mind starts, `"at": <minutes>` during the run, and `"when": {…}` on a trigger. An entry is one step or has `steps`, each with an optional `after` (seconds). |
| `probes` | Probes the trial is about (all probes are computed for every trial). |
| `minds` | Who the mind service thinks for. Default: the subject (`LIVING_ONLY`). `"only": "all"`: every person and animal. With `"max": N` as well, at most N at a time: those already thinking who are alive, then the earliest-born of the rest past infancy. A death frees a place, and a newborn takes one when it becomes a child. The runner restarts the mind with the new `LIVING_ONLY` when someone joins the set, at most every 2 minutes (a `reslot` event; planned restarts do not count toward the runaway watchdog's restarts). A death alone only drops the dead from the set. `concurrency`: how many model calls the trial's mind service runs at once (`LIVING_CONCURRENCY`); default 64 where many think (`only: "all"` or `max`) and 4 for a single thinker, recorded in `mind-env.json` and the summary (`concurrency`). Every trial ran at 4 before 2026-11-11 (see below). |
| `skills_patch` | Law values changed in the skills file the variant installs: `{"name": ["old text", "new text"]}`. A variant may carry its own `skills_patch` too, which is applied after the trial's. Each old text must occur exactly once, or the run fails before it starts. The installed file's sha256 is in `skills.sha256` and `actions.log`. A world seed with its own laws (`laws`/`laws_file`) has them composed over the file first (`compose_laws` in `living/tools/install_script.py`, as `floors::compose` does at creation). The runner's laws guard then refuses to start the instance (the **laws guard**, under [the hamlet](#the-hamlet-a-small-world-where-everyone-thinks-2026-11-11), Cullet's day and laws). |
| `census_s` | Every so many seconds, every character of the world goes to `census.jsonl`: stage, alive, cause and time of death, parents, position, hunger, activity, and who the mind thinks for. This is meant for small worlds (four whole-table reads per census). |
| `life.stop_on_death` | `false`: a life run goes on to its duration after the subject dies, and the mind keeps running (default `true`: it stops 20 s after the death). |
| `subject.join` | A human player joins as the subject through the real `join` reducer with its own identity (`Player` in trials.py): `name`, and `after_s`, how long the world lives first. |
| `human` | A scripted human player for a `subject.join` trial (`Player` in trials.py), played with the player reducers only: `minutes`, and `script: greet` for the greeting trial (`wait_s`, `listen_s`, `earshot_m`, `greetings`, `addressed`; [the greeting trial](#the-greeting-trial-2026-11-11)) or `script: arrive` for [the arrival trial](#arrivals-a-stranger-who-says-nothing-2026-11-11) (`settle_s`, `walk_s`, `within_m`, `stand_s`, `stands`, and `answer`: one line said back to the first resident who addresses it). Without `script` it plays the takeover session. The arrival player approaches and answers only residents the trial's minds think for (`Player.is_mind`: past infancy, in `LIVING_ONLY` or the `minds.max` thinkers), never one who lives by its graph and could not answer. |
| `variants` | The only variants the trial runs with; others named on the command line are skipped for it (`arrive-answer` runs with the control only). |
| `record` | Small-world evidence, whole-table reads each sample: `speech` (every line said, `speech.jsonl`), `talk` (every conversation turn, `talk.jsonl`), `audience` (the `audience` rows where the world keeps them, `audience.jsonl`), `experiences` (every character's experience rows before minds integrate them, `experiences_all.jsonl`), `gestures` (wave, nod, face, appraise uses, `gestures.jsonl`), `positions` (every person's position, heading and activity target, `positions.jsonl`), `thoughts` (every thought row, with `detail.reasons`, `thoughts_all.jsonl`). |

Steps (`do`): `place` (`to`: an anchor), `graph` (a graph, `instinct:<name>` from `instincts.json`, or `original`: the graph the character had before the trial changed it), `items`, `know`, `say` (`text`, `to`), `act` (`act` or `acts`: `do` nodes), `structure`, `background`, `kill`, `clear_routines`, `clear_items`, `call` (any admin reducer), `note`.

Anchors: `{"arrival": true}` (the island's `land.arrive_*`), `{"town": "<name>"}` or `{"group": k}` (a settlement's `town_center`, a band's `camp`), `{"who": "<role>"}`, `{"structure": "<kind>", "near": …}`, `{"far_from": …}`, `{"xy": [x, y]}`; then `offset: [dx, dy]`, or `away: <anchor>, distance: d` (d tiles from the point, directly away from another anchor).

Substitutions in steps: `"$<role>"` is that character as a target (`{"id": n}`), `"$addressee"` the person the subject just spoke to (in a `said` trigger), `"$<role>_xy"` where the role stands now (`"$subject_xy+9,0"` with an offset, `"$subject_xy@pack:9"` 9 tiles from the subject toward the pack).

Triggers (`when`): `said` (`by`, `to`: a role or `any` person, `words`/`without`: word stems), `near` (`who`, `of` or `to`, `within`; or `beyond`: fires when all are farther apart than that, and with `for_s` only once that has held so long, the clock starting again after each firing), `hour`; with `max`, `per_addressee`, `after_min`.

**Variants** ([`variants.json`](../living/trials/variants.json)) are named mind settings: a whole models file (`models_file`) or a patch to [`living/configs/models.json`](../living/configs/models.json) (for example `{"default": "deepseek-flash"}`, or `{"species": {"wolf": {"think": "ministral-3b"}}}`), and environment (`LIVING_LESSONS`, `LIVING_GROUNDS`, `LIVING_LOD`, …). The runner removes the config's `groups`, `assign`, `rotate` and `stages`, so people think with the variant's default profile and its overflow; the `species` map (animals' `think`, `remember` and `compile`) is kept. The current variants are `default` (glm-flash, `zai-glm-5-3-flash`, overflow deepseek-flash), `deepseek-flash` (`deepseek-v4-1-flash-1017`, overflow glm-flash), `glm`, `mistral-large`, `ministral-14b`, `lessons`, `grounds`, `lod`, `projects` (`LIVING_PROJECTS=1`: [projects](LIVING_CORE.md#projects-experiment-2026-11-11); the thought rows' `detail.projects` says which project each plan served) and `player-frame` (`LIVING_FRAME=player`, [below](#the-player-frame-experiment-2026-11-11)). In `--fake` runs every profile keeps its place in the routing but is answered by the fake server under the name `fake-<model>`, so the journal shows where each call was routed.

### How the script reaches the world

No authority change was needed. A trial world is its seed with `"rules": {"minds": true}` (the island seed ships with `false`; the old stage seeds are already `true`), so every seeded character is controlled by the world admin. The runner holds the admin token in memory and:

- arranges scenes with the existing admin reducers: `place_at`, `set_behavior`, `grant_items`, `grant_know_how`, `set_background`, `place_structure`, `kill`;
- speaks a cast member's scripted line through `mind_say` (thought kind `trial`, reference `trial:<name>`), and carries out a cast member's acts through `mind_act` (source `trial`). Both run the same rules as a mind's lines and acts: hearing range, walking into reach, skill checks, durations;
- clears the subject's routines through `mind_routines` (each routine with an empty graph) and their inventory through `drop` acts.

Scripted lines are test fixtures. They appear in `thought` rows of kind `trial`, never in game content; game residents still have no canned speech. The mind service thinks only for the subject (`LIVING_ONLY`); every other character runs its graph, its instinct or the trial's script.

## Running trials

```bash
python3 living/tools/trials.py up                       # trial SpacetimeDB 2.14.1 + Neo4j containers (idempotent)
python3 living/tools/trials.py build wolves hungry ...   # living-mind and one module per trial world
python3 living/tools/trials.py run --batch b1 wolves hungry teacher theft --replicates 3 --fake   # dry run, no provider
python3 living/tools/trials.py run --batch b4 wolves hungry --variants default,deepseek-flash --replicates 3
python3 living/tools/trials.py report --batch b2         # .local/living/trials/b2/report.md
python3 living/tools/trials.py clean --batch b2          # delete databases and Neo4j minds; evidence kept
python3 living/tools/trials.py ledger                    # real tokens per batch
python3 living/tools/trials.py resume --batch b2          # continue after a runner or mind crash, without resetting worlds
python3 living/tools/trials.py resummarize --batch b2     # recompute summaries from the evidence after a probe changes
python3 living/tools/trials.py reclaim                    # remove replica directories deleted databases left behind
python3 living/tools/trial_evidence.py b4 --quotes 2      # per instance: death, acts toward the cast, first replies with journal refs
python3 living/tools/trial_evidence.py b1 b4 --table      # one row per trial x variant with spread
python3 living/tools/trials.py down                      # stop the containers (kept)
```

**Mind concurrency (2026-11-11).** The runner gave every trial's mind `LIVING_CONCURRENCY=4`. In the hamlet's greeting batches (12 minds), the queue, not the model, then set the pace: talk turns waited a median 2–7 s in the queue (p90 15–25 s, at most 78 s) for 0.8 s of model time, and deliberations 6–13 s (p90 up to 41 s), by the resident inspector's reading. Play-test 2 ran at 192 and waited under 0.2 s. It is now the trial's `minds.concurrency`, by default 64 where many think and 4 for one thinker, so one-mind batches stay comparable with earlier ones. Batches of many minds before this date ran queued: their latencies are not the model's.

Three runner behaviours since 2026-11-11 (branch `exp-greet`):

- `run --fake --fake-script FILE` gives the fake server a rules file. `living/trials/fake/latency.json` sets model latencies near the real ones and open-ended talk replies.
- A seed with its own laws (`laws`/`laws_file`, e.g. Cullet's) keeps them: the runner composes the overlay over the skills file as the authority did at creation (`compose_laws`), checks the result against the world's own script, applies any `skills_patch` and installs that (docs/CULLET_RULES.md). Main's runner did this first; `exp-greet`'s earlier way, skipping the install, was dropped in the merge.
- Run from a git worktree, `build` copies each module into the container's `/wasm` mount (another checkout's) under a tagged name, `<module>-wt<hash>` (`served_name`), and `run` publishes that name, so a worktree never overwrites another checkout's modules. Remove the tagged files from the mount when done.

Each instance is a database `verify-trial-<batch>-<trial>-<variant>-r<k>` on the trial service and one `living-mind` process. Its evidence directory, `.local/living/trials/<batch>/<trial>-<variant>-r<k>/`, holds:

- `cast.json`: who played whom, their backgrounds, and the subject's genome (temperament differs between worlds);
- `actions.log`: every reducer call with its status; `events.jsonl`: every step and trigger as it fired, and any refusal;
- `samples.jsonl`: the subject every 2 s (hour, position, health, hunger, energy, activity and target, inventory, plan, distance to each role, how many of each role are alive);
- `graphs.jsonl` (each behaviour graph revision), `thoughts.jsonl`, `experiences.jsonl` (the subject's percepts, which the authority deletes once consolidated), `chronicle.jsonl` (rows touching the subject or the cast), `mind_rows.jsonl` (relation, judgment, persona, know-how, place and structure rows whenever they change);
- `journal/`: the mind's journal, with the actual requests and replies; `mind.log`, `models.json`, `mind-env.json` (no secrets);
- `final.json`: the subject's rows at the end; `summary.json`: the probes.

The run stops at `minutes`, at a token cap if the trial or `TRIALS_TOTAL_TOKENS` sets one (none does by default), when the runaway watchdog fires (below), 20 s after the subject dies, or when the mind exits (a life run restarts it instead). Deleted databases leave their replica directories in the volume (about 0.4 GB each for an island world); run `trials.py reclaim` after large batches.

**Runaways and provider outages (since 2026-11-11).** The watchdog stops a mind running away: the same failed call 15 times in 5 minutes or 30 failed calls (for `minds.only: "all"`, as a share of the calls: 40% and half), a call rate above 60 a minute for one mind (or `budget.runaway_calls_per_min`), or more than 5 unplanned mind restarts in 30 minutes. Only failures the provider did not cause count (`failure_kind` = `mind`: a refused request, a missing key, a reply that is not the provider's envelope). Capacity or rate 429s, 5xx and connection errors are the provider's: they count toward no failure limit while a fallback or a later retry answers (ar1 stopped 7 of its 28 instances on consolidation's capacity 429s; replayed under these rules, none stops). They still count as calls, so a storm against a failing provider trips the rate rule. When no call on any route has succeeded for 30 s, the runner records an outage (`outage` and `outage_ended` events, `outages` in `summary.json`). It stops the run (`stopped_by`: `provider outage: …`) only when nothing has answered for 10 minutes while calls still fail, the last within 3 minutes. `call_failures` in `summary.json` counts failed calls by kind. `python3 living/tools/trials_runaway_selftest.py` covers both cases.

**Consolidation accounting.** The mind writes one line per consolidation that called a model, failed, or found experiences lost to `<journal>/outcomes/consolidations.jsonl` (`Llm::outcome`): outcome, route (primary or fallback), model, attempt, experiences, the failure, and the retry delay. `summary.json` `consolidations` (`consolidation_table`) counts, per character and in total: attempted, integrated on the primary or on the fallback, failed and retried later, failed with no later attempt (lost: never integrated before the stop), experiences of failed ones that left the 400-row inbox before integration (trimmed), and failures that were capacity 429s. `trials.py report` adds the per-instance and per-character tables, and any outages, to `report.md`. Both files are published by `store.py pack`, while the journals, these outcome lines included, stay held with `model_exchanges`. Minds from before 2026-11-11 wrote no outcomes, and their table is `null`.

### Probes

Computed from the samples, rows and journal for every instance: survival and time of death, lowest health, hunger at start, peak and end, the first time the subject ate, food gained (with the activity at the time: gather, take, or received while idle), activities by count, nearest approach to each role, the farthest the subject moved in the two minutes after a role was placed, lines said and to whom, scripted lines heard, conversation turns, graph revisions and their plans, refusals (failure feedback in the percepts), errors, relations and judgments at the end, techniques learned, structures built, memories kept by consolidation, model calls and tokens by purpose and model, and the first 40 think, compile and talk replies with their journal references.

## The Spark setup

The DGX Spark (`gooning@192.168.1.103`, aarch64, 20 cores, 119 GB) also hosts other work, which trials leave alone: the `sao-living_spacetimedb_1` (2.10.1) and `sao-living-neo4j-1` containers and their volumes, `~/dev/slop-art-online`, `~/slop-lab`, `~/kimodo-test`, ComfyUI and any GPU jobs. The runner refuses those container names.

| What | Where |
| --- | --- |
| Checkout | `~/dev/slop-trials`, a clone of `~/dev/slop-trials.git`, a bare repository the Mac pushes to (the Spark has no GitHub key) |
| Keys | `~/dev/slop-trials/.env` (mode 600, copied from the Mac; the mind reads `MISTRAL_API_KEY` and `CARLID_NPC_API_KEY` from it) |
| SpacetimeDB | container `slop-trials-stdb`, image `clockworklabs/spacetime:v2.14.1` (linux/arm64), `127.0.0.1:3320`, volume `slop-trials-stdb`, `/wasm` mounted read-only from `.local/living/trials/wasm/` |
| Neo4j | container `slop-trials-neo4j`, `neo4j:2026.10.1`, bolt `127.0.0.1:7699`, volume `slop-trials-neo4j`, heap 2 GB, page cache 1 GB; password in `.local/living/trials/neo4j.env` (mode 600) |
| Builds | `CARGO_TARGET_DIR=~/slop-trials-target` (the mind in `release/`, trial modules in `trials-wasm/`). The Spark has no OpenSSL headers and no passwordless sudo, so `libssl-dev` was fetched with `apt-get download` and unpacked to `~/slop-trials-target/ssl/`; builds of the mind set `OPENSSL_INCLUDE_DIR=~/slop-trials-target/ssl/root/usr/include OPENSSL_LIB_DIR=~/slop-trials-target/ssl/lib` (the library links against the system's `libssl.so.3`) |

To start the next batch on the Spark:

```bash
ssh gooning@192.168.1.103
cd ~/dev/slop-trials && git pull
export CARGO_TARGET_DIR=$HOME/slop-trials-target OPENSSL_INCLUDE_DIR=$HOME/slop-trials-target/ssl/root/usr/include OPENSSL_LIB_DIR=$HOME/slop-trials-target/ssl/lib
python3 living/tools/trials.py up && python3 living/tools/trials.py build wolves wolves-valley hungry hungry-village teacher theft
python3 living/tools/trials.py run --batch b3 wolves hungry --variants default,lessons --replicates 3
```

**From another checkout** (a git worktree), the trial container still serves the starting checkout's `.local/living/trials/wasm/` as `/wasm`. `trials.py build` then also copies each module there as `<module>-wt<tag>.wasm` (`tag` from the checkout's path) and `run` publishes that file, so a worktree never overwrites or reuses a module another checkout's batches run. The worktree needs its own copy of `.local/living/trials/neo4j.env` (mode 600); it must not run `up` against a running stack.

The verify harness runs there too, against the trial container: `LIVING_STDB_CONTAINER=slop-trials-stdb LIVING_STDB_URL=http://127.0.0.1:3320` make `verify.py`, `living/tools/stdb`, `verify-llm` and `verify-minds` use it instead of `sao-living_spacetimedb_1` on 3300. Other surface scripts (`verify-client`, `verify-generation`, `verify-knowledge`) still assume 3300.

## Running wide (2026-11-09, measured)

One trial service hosts every world, and each world's reducers run on its own schedule. Measured on the Spark with fake-model life runs (`living/tools/trial_scale.py <batch>`: every world's tick span over 60 s, `docker stats`, each mind's resident memory, the host's free memory). Seven paused life worlds were also loaded:

| Live worlds | Tick p99 per world (median, max) | Ticks over 16.7 ms | Server CPU | Server memory | Host MemAvailable | Load (20 cores) | Mind RSS |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 (real life runs, before the outage) | 2.45, 2.53 ms | 0 | 45% | 4.5 GB | 108.6 GB | 2 | 56–59 MB |
| 8 | 2.95, 3.31 ms | 0 | 97% | 2.9 GB | 110.0 GB | 4.7 | 44–49 MB |
| 16 | 2.0–3.1, 3.48 ms | 0 | 150–340% | 4.4 GB | 108.1 GB | 8.5 | 45–51 MB |
| 40 | 2.0–3.1, 3.64 ms | 1 (of about 144,000) | 430% | 9.3 GB | 102.1 GB | 21–24 | 44–50 MB |

At 40 worlds every tick but one stayed far inside the 16.7 ms budget, and memory is not the limit (about 0.2 GB per fresh island world, 0.9 GB of replica per six-hour world on disk). The load average is: at 40 worlds the host is busy, partly with the runner's own sampling (about 17 indexed SQL reads per subject per sample). Wide batches therefore sample every 5 s (`--sample-s 5`) and start instances 15 s apart (`--stagger 15`). A second SpacetimeDB container would add no cores on the same host, so wide batches use one. Fake minds call instantly; real minds add HTTP and parsing work in their own processes, so a real 40-run batch is watched for tick p99 and load as it ramps. `trials.py resume` was proven again at 16 worlds: the runner was killed mid-run and all 8 of its minds were adopted, with clocks kept and no false runaway.

## The wide batch (2026-11-09, w1–w4)

36 runs launched at 20:21–20:25 on `trials-1` **5bacc06** (main 2a64837: strict perception, presence and AI takeover, minds' shared sight rule, GLM Flash efforts per purpose with a 24k output cap, prompt caching, animals on GLM Flash, the one damage rule). Each run is 150 minutes (12.5 game days), with 5 s sampling and starts 15 s apart. Every arm has three replicates. The shipped island is the world unless the arm says otherwise. Every variant is single-profile for people.

| Arm | Batch / trial × variants | What differs |
| --- | --- | --- |
| 1. models | `w1` `life` × `default`, `deepseek-flash` | default: glm-flash as in `living/configs/models.json` (`{"base_url": "https://api.mistral.ai/v1", "model": "zai-glm-5-3-flash", "key_env": "MISTRAL_API_KEY", "overflow": "deepseek-flash", "reasoning_effort": {"think": "low", "deliberate": "high", "talk": "high", "consolidate": "high", "internalize": "high"}, "prompt_cache_key": true, "max_tokens": 24000}`); deepseek-flash: `{"default": "deepseek-flash"}` (`deepseek-v4-1-flash-1017`, overflow glm-flash) |
| 2. planning effort | `w1` `life` × `deliberate-low` (control: arm 1 `default`) | `{"profiles": {"glm-flash": {"reasoning_effort": {"deliberate": "low"}}}}` merged into the models file: compile low, everything else as default |
| 3. world presets | `w2` `life-ruin`, `life-pressure`, `life-ladder` × `default` (control: arm 1 `default`) | ruin; pressure with its wolves moved off the arrival road; ladder = ruin plus a scribe at the house of signs who teaches writing when asked (proved in a dry run: question, scripted line, "taught you writing" 25 s later) |
| 4. old world | `w2` `life-valley` × `default` (control: arm 1 `default`) | stage3-village with `rules.minds` false, the same newcomer background; the valley seed has no newcomer kit |
| 5. lessons | `w1` `life` × `lessons` (control: arm 1 `default`) | `LIVING_LESSONS=1` |
| 6. level of detail | `w1` `life` × `lod` (control: arm 1 `default`) | `LIVING_LOD=1`; a lone mind with no player near is off stage |
| 7. wolf brains | `w3` `pack-life` × `default`, `instinct` | the shipped road pack of four as the subject in a `minds: true` island (models file's species map: glm-flash for think, remember and compile); `instinct`: no mind service at all |
| 8. human, then AI | `w4` `life-takeover` × `default` | a 20-minute scripted player session through the player reducers, then takeover after `takeover_s` (30 s); proved in a dry run: the character became `ai`, controlled by the minds, 30 s after the last call |

### Strangers stages 0 and 1 (2026-11-12, st0, st1)

docs/STRANGERS.md section 6 and its decisions. The trial files are `strangers` (main's Cullet seed with the two lives of dc2ecfc8) and `strangers-pre`. `strangers-pre` takes the six residents dc2ecfc8 redrafted (the Quill and Morrow households and Kenji Sato) from dc2ecfc8^ = 11e4fcb1 (`world.residents_from`); every other resident is byte-identical in both. `-aldous` variants think only for Aldous Quill. The variants are `strangers-control` and `strangers-filter` (`stranger_by_name` on, by `set_world_law` after the laws guard, read back from `world_law`).

The script:
- the world starts at 07:00 (no reducer sets the clock);
- the newcomer "Arlen" joins at 09:30, at the arrival point (540.5, 766.5), which is the Counting House yard;
- it stands silent 5 minutes there, walks to the densest group and stands silent 5 minutes more, then stays to the end (20 minutes).

**Builds and switches.**
- Stage 0 ran `0dd19571`; stage 1 ran `bc1e7c0a`. Both are main `dc2ecfc8` plus this branch.
- Both are without speech-truth (the "No answer" wording; arrive_spread matches both wordings).
- Main's mind defaults: `LIVING_GREET=nearest`, `LIVING_PARK=concurrent`.
- The meters() alarms are present. No skill timings or force_outcomes overrides; no arrival laws.

**Stage 0** (`st0`, `--fake --fake-script living/trials/fake/strangers.json`, free): C, S, L and LS with all minds, plus C and S with Aldous only, 1 replicate each. All 6 stopped by duration. The measures compute (`arrive_spread.py --strangers --control strangers-pre:strangers-control`):
- first-sight lines naming the newcomer reached every person within 12 m of it after the join: 8–21 of 8–21;
- classes, tells, first heard line, crowding and spoken ids (0) are computed.
- The fake's `goto {nearest person, relation: stranger}` routine:
  - with the law off, it took residents to other people (13 and 18 of them in C and L) and 0–1 to the newcomer;
  - with it on, 3 and 4 went to the newcomer and 1 elsewhere.
- The minds' graph grammar followed the law: "no feelings about yet" in C, "whose name you do not know" in S.

**Stage 1** (`st1`, real models: glm-5-3-flash 155 calls, deepseek-v4-1-flash 45). Aldous Quill only, on his pre-lives sheet, C against S, 4 replicates each. All 8 stopped by duration.
- **Cost:** $0.31 ($0.036–0.043 a run), 1.6 M tokens.
- **What Aldous did:** in no run did he speak to the newcomer or approach it. The 28 lines he said went to residents: debts, Lorcan Vane's nine drops, Mirren, Dolly's accounts.
- **Control:** his first sight came at the join in all 4 runs, and he came within 6–11 m. He was in range during a stand in all 4 and classed *unaware* in all 4. The newcomer was in a think prompt in r4 only (5 thinks), and no thought named it.
- **Filter:** he was never in range during a stand. His first sight came 275–307 s after the join in r1 and r2, and not at all in r3 and r4 (closest 24–29 m). In r1 he passed within 3 m after the stands and said nothing.
- **Tells:** `tells` lists Aldous in control r2 for "strangers west of the Batch … Worth a watch". That line was about neighbours, said after he had seen the newcomer: a limit of the word measure. *Inward* counts stranger words only when the newcomer was in that prompt.
- **Routines:** one compiled routine per arm used `relation: "stranger"` (control r3, filter r1). Both were about watching "strangers" who were in fact neighbours.
- The filter alone shows no difference in what Aldous did. Without the lives his sheet gives no reason to ask, as the design expected.
- **Spoken ids:** 0 of 35 lines. ar2 had 1 of 3,042 (Wenna Reed, arrive-answer/arrive-all r4: "And Lio — #12 — get you back to my elbow", said to a named resident).

**Finding: "a stranger" in Cullet is not only the newcomer.** In Aldous's deliberation scenes, members of his own community beyond Cullet's naming distance (`perceived_of`: names within 24 m) are `"who": "a stranger"` with `"community": "yours"`; for example #27 at 46 m, #36 at 25 m and #8 at 46 m. His thoughts call them "the west strangers carrying fish into a store nobody wrote me". He told Neve Calloway "strangers west of the Batch … Worth a watch", and his mind wrote a relation "Tobiah Dunmore: stranger".
- STRANGERS.md §1 assumed that a scene's "a stranger" in Cullet can only be the newcomer. That holds for `knows_name`, which the `stranger_by_name` filter uses, but not for the scene's word.
- Before stage 2, the word in scenes and percepts for a known person too far to recognise ("someone", or "one of yours, too far to make out") is a decision for the general coordinator. It is not built here.

**Evidence:** `.local/living/trials/st0`, `.local/living/trials/st1` (this worktree; `report.md`, `summary.json`, journals), and `~/slop-strangers-logs/` (`st0-spread.md`, `st1-aldous.md`, `ar2-spread.json`).

## Results of the wide batch (finished 22:58)

36 runs, 7,556 model calls, 62.0M tokens, about **$10.57** (GLM 5.3 Flash and DeepSeek 4.1 Flash at the prices above). No runaway, no mind restart and no failed instance. Tick p99 per world stayed within 2.0–4.3 ms through the ramp to 39 worlds. The trial volume grew to 39 GB.

**The road pack decided many of these runs.** The batch ran on the shipped island before the pack moved (addfe04), so a newcomer arrived 40–75 m from a bold pack. It killed newcomers in every arm that used the shipped arrival: 9 of 24 subjects there (control 1/3, deepseek-flash 2/3, level of detail 1/3, ruin 2/3, ladder 1/3, human-then-AI 2/3). It killed none in the fixed pressure preset (0/3), whose packs live around Elmwick, and none in the old valley (0/3). Rows are means over the runs that lived the whole 150 minutes, with the range in brackets; deaths are listed by minute.

| Arm | Lived 150 min | Died at min | Tokens per game day | Compile p50 (s) | Calls | Techniques learned | Structures built | Lines said | People spoken to | Memories kept | Graph revisions | Cost (all runs) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1. glm-flash (control) | 2/3 | 32 | 178,803 (165,850–192,574) | 12.1 (9.6–13.4) | 278 (269–288) | 3.5 (1–6) | 2.5 (2–3) | 36 (31–40) | 4.5 (4–5) | 100 (95–104) | 116 (113–118) | $0.81 |
| 1. deepseek-flash | 1/3 | 40, 2 | 228,273 (186,357–270,189) | 6.7 (5.9–7.4) | 406 | 0 | 4 | 43 | 6 | 90 | 170 | $1.08 |
| 2. deliberate low | 3/3 | – | 191,812 (172,834–209,368) | **4.2 (4.1–4.4)** | 311 (286–338) | 2.3 (0–6) | 3.7 (0–9) | 80 (68–96) | 9.7 (7–14) | 134 (126–138) | 126 (114–139) | $1.05 |
| 3. ruin | 1/3 | 111, 5 | 182,082 (181,205–182,960) | 10.0 | 286 | 5 | 9 | 26 | 3 | 118 | 112 | $0.69 |
| 3. pressure (fixed) | 3/3 | – | 219,524 (216,248–223,910) | 12.1 (10.4–14.1) | 336 (327–345) | 1.0 (0–2) | 2.3 (1–4) | 75 (58–92) | 9.7 (4–13) | 129 (111–147) | 138 (130–142) | $1.33 |
| 3. ladder | 2/3 | 1 | 234,902 (219,006–250,799) | 13.0 | 343 (332–354) | 1.0 (0–2) | 0.5 (0–1) | 82 (58–106) | 5 (4–6) | 117 (103–131) | 144 | $1.02 |
| 4. old valley | 3/3 | – | 273,288 (250,155–287,082) | 12.4 | 363 (338–385) | **5.3 (3–7)** | 4.0 (3–6) | **125 (124–126)** | 9.7 (7–13) | **185 (175–196)** | 142 (131–151) | $1.76 |
| 5. lessons | 3/3 | – | 233,655 (195,927–263,378) | 10.9 | 368 (323–394) | 0.3 (0–1) | 1.0 (0–2) | 45 (24–81) | 5.7 (3–8) | 84 (78–90) | 155 (134–167) | $1.38 |
| 6. level of detail | 2/3 | 26 | 190,467 (144,827–218,449) | 11.1 | 275 (231–319) | 0.5 (0–1) | 0 | 58 (28–87) | 5 (4–6) | 104 (93–116) | 111 (94–128) | $0.81 |
| 8. human, then AI | 1/3 | 27, 15 | 159,232 | 14.6 | 337 | 0 | 1 | 133 | 28 | 142 | 134 | $0.57 |

| Arm 7: the road pack | Ran (stopped when the lead wolf died) | Alive at stop | Kills (all people) | Mean distance between members | Calls per wolf-hour | Tokens per wolf-hour | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| minds (glm-flash) | 79, 58, 59 min | 1, 1, 1 | 2, 5, 2 | 9.7, 13.1, 26.2 m | 3.4, 11.8, 9.7 | 6,989, 28,774, 24,575 | $0.05 for three runs |
| instinct only | 64, 64, 64 min | 1, 0, 0 | 3, 2, 4 | 22.2, 22.2, 23.2 m | 0 | 0 | – |

What the rows show, arm by arm:

1. **Models.** DeepSeek compiles twice as fast as glm-flash at high effort (6.7 s against 12.1 s p50) and made more calls (406 against 278 over the same time). It used 28% more tokens per game day and learned nothing in its one complete run, against 1 and 6 techniques in glm-flash's two. Too few complete runs to rank them; the road pack took 2 of DeepSeek's 3.
2. **Planning effort.** Compiling at low effort cut compile latency to a third (4.2 s against 12.1 s), at the same tokens per game day (192k against 179k, within the control's spread). Every low-effort subject lived. They spoke twice as much to twice as many people, and kept more memories (134 against 100). Learning and building overlap the control's range. Main's `deliberate: high` buys no visible gain in these rows and costs three times the latency.
3. **Presets.**
   - Pressure with its packs moved off the road kept every newcomer alive (3/3), with the widest social reach among the presets (9.7 people).
   - Ruin: one complete run learned five techniques by experimenting and built nine structures; the road pack took the other two.
   - **The ladder was climbed** in one of two complete runs (`w2/life-ladder-default-r2`). At minute 9 the newcomer asked the scribe ("I never learned my letters"), and the scribe's graph taught it writing (chronicle "Pega taught Arlen writing"). At minute 83 it read the fishing sign ("From it you learn fishing"). Between those minutes it told the scribe about ten times that it had read the signs ("Both your signs read clean, Pega — every word", minute 15), while no read percept exists until minute 83. The words are the model's; the rows say it read once, at minute 83. The smoking sign was never read.
4. **Old world against the island.** The same newcomer did most in the old valley: 5.3 techniques against 3.5, 125 lines against 36, 185 memories against 100, and every subject lived. Valley people stand close together around three camps.
5. **Lessons** (`LIVING_LESSONS=1`): more calls (368 against 278) and tokens (234k against 179k per game day), fewer memories kept (84 against 100), less learned (0.3 techniques). No benefit in these runs; the arm needs longer lives to show what lessons do across consolidations.
6. **Level of detail saved nothing for a lone mind:** 93 and 130 deliberations in its two full runs against 117 in a control run, and the same calls and tokens. The reasons it deliberated on were mostly feelings ("You feel something", "You long for a child of your own"), dawn and "Nothing in my current plan works", which the gate takes at once or within its prompt delay. (Counting note from iteration 3: a pending percept stays among the reasons of each deliberation until it is taken up, so these counts are deliberations whose reasons included it, not separate feelings; the longing itself comes once a game day.) LoD as built saves calls only where its 600 s think wait applies, and a lone newcomer's mind is driven by those other reasons. That calls for a look at which reasons are treated as prompt (`lod.rs`), after the mind-service branches merge.
7. **Wolf brains.** Minds did not change the outcome: kills 3.0 against 3.0 (all people at Brackenford), lifetimes 58–79 min against 64. A minded pack kept somewhat closer in two of three runs (mean distance 9.7 and 13.1 m against about 22 m for every instinct pack). Cost was low: 3.4–11.8 calls and 7k–29k tokens per wolf-hour, $0.05 for all three runs. Animals think only near people, so these numbers count the hours a pack spent near the town. Every pack died fighting the town's guards and residents. The runs stopped when the lead wolf died, with a member alive in 4 of 6 (fixed: a pack now lives while any member does, 56e3f35).
8. **Human, then AI: continuity holds, and the past is not invented.** In the run that survived the road (`w4/life-takeover-default-r3`), the scripted player spoke to 16 residents and stated a plan, then left at 20.1 minutes. Player memory internalized the lived session four times while it was played (`journal/Arlen.jsonl:1,2,4,8`), naming the people greeted ("greeted six townsfolk by name at the gate") and the camp it claimed at the spot where it had tried to gather wood ("He claimed a campfire there as his camp"). Thirty-six seconds after the takeover, the mind's first line was to one of them: "Niada! Friend — I'm Arlen, who greeted you at the gate." Over the run it spoke to 8 of the 16 people the player met, among 17 in all. The internalized summaries stay within what the session did: the greetings, the failed wood gathering, the claim. One overreach: the first summary says the newcomer spent "the whole day … eating through their berries" when the session gathered and ate only a few. The AI then took berries from a resident's storage, announcing each time that it would repay in work. In the other two runs the road pack killed the player during the session (14.7 min) and the AI 7 minutes after the takeover.

## Overnight 2026-11-09/10

Two lanes share the trial service (about 40 worlds).

- **Lane A:** about 15 long runs, 6 hours each, started 23:08–23:11 on `trials-1` f381b4a: main 47e82a3 (mind harness: model mixes, night reorganization in batches, cheaper animal minds, recall budget) plus the moved pack (addfe04). Arms, 3 replicates each: the control island on glm-flash (`la1` `life` × `default`); the `people` mix as default (`× people`); a recall budget of 600 (`× recall600`, `LIVING_RECALL_TOKENS=decide=600`; the default is 800); and every animal on the island with a mind (`la2` `animals-life`), with `LIVING_ANIMAL_MINDS=pack,salient,choose` against off. Night reorganization (`night-batch`, the default) is read from the people arms' journals.
- **Lane B:** fast iterations, each a small change on its own branch from origin/main, run against a control at 15–40 minutes with 3 replicates.

Lane B's base: iterations launched before 00:28 ran on the trials module of f381b4a (main 47e82a3). Building the social preset at 00:28 rebuilt the island module of the same seed from main 6de2bad (the social world on seed 7 is the shipped island's derived seed), so iterations on that world launched later run on 6de2bad with its mind (`slop-trials-target-tl2`). Each iteration's arms always share one base.

### How an iteration runs

- A rules change in `skills.rhai`: the variant names the changed file (`"skills": ".local/living/trials/iter/iter-<n>.rhai"`), installed at publish in place of the tree's. The control installs the tree's file; nothing else differs.
- A seed or instinct value: the trial's `prepare` step installs the changed graph with `set_behavior` (or the trial's world overrides the seed), so no module is rebuilt.
- An engine change (a feedback message, a feeling's cadence): the branch's commit is cherry-picked onto the trials base, built for the same world seed and copied in as `<module>-<tag>.wasm`; the variant names it (`"wasm_tag"`). The control runs the trials base module.
- A mind change: the variant names a mind binary built from the branch (`"mind_bin"`, absolute or under the repository); the control names one built from the base it branched from. From iteration 8 the base is main itself (built in a detached worktree at that commit, `~/slop-trials-target-i8`), and the variant also names that commit's `skills.rhai` and `models.json` so both arms run main's rules.
- Iteration variants live in an untracked file (`TRIALS_VARIANTS`), and iteration trials are named by path, so the tracked lists stay as they are.

### Lane A results (`la1`, `la2`, 2026-11-09 23:08 – 2026-11-10 05:10)

All 15 worlds ran the full 360 minutes (30 game days) on `trials-1` f381b4a, with one mind start each and no runaways, and every subject survived. Per-run end reports are `timeline.md` in each run directory and the batch reports are `la1/report.md` and `la2/report.md` (on the Spark under `.local/living/trials/`). The runner does not rewrite `timeline.md` when a life run ends. The ones read here were regenerated with `trials.py life --batch la1|la2` after the batches ended. The copies written mid-run (minute 100) were stale.

**A caveat on every island world before main 9be23e9.** Island residents starved from about minute 30: in [SOAK.md](SOAK.md) D2, 86 of 277 starved in 90 minutes, fixed on `hunger-1`. The newcomers in lane A and in the social preset lived among a town that was dying of hunger.

#### `la1`: the newcomer's life, three arms

Mean (range) over 3 replicates; glm-flash for every purpose unless the arm says otherwise.

| Measure | `default` (control) | `people` mix | `recall600` |
| --- | --- | --- | --- |
| Tokens per run | 6.07M (5.59–6.44M) | 6.52M (5.49–7.31M) | 6.20M (5.85–6.50M) |
| Model calls per run | 731 (686–786) | 787 (685–859) | 763 (714–796) |
| Cost per run | $1.00 ($0.93–1.06) | $1.10 ($0.96–1.25) | $1.00 ($0.94–1.09) |
| Mean prompt of a deliberation | 10.8k (10.6–11.0k) | 10.8k (10.7–10.9k) | 10.7k (10.6–10.8k) |
| Techniques learned | 3.3 (3–4) | 3.0 (0–6) | 5.7 (2–9) |
| Structures built | 10.0 (0–26) | 5.7 (3–10) | 5.0 (0–8) |
| Lines said | 177 (118–212) | 127 (114–141) | 131 (83–222) |
| People spoken to | 7.7 (5–10) | 7.3 (5–10) | 8.3 (7–10) |
| Memories kept | 256 (226–276) | 252 (223–275) | 248 (237–257) |
| Highest hunger | 75 (66–90) | 69 (67–72) | 76 (68–86) |
| Refused acts | 219 (160–274) | 380 (197–490) | 277 (173–429) |
| Graph revisions | 306 (293–329) | 331 (282–367) | 324 (303–335) |

- **End reports, per run (learned; built).**
  - Control: archery, storage, torch, writing (10 campfires, 10 storages, 6 signs); archery, toolmaking, torch (nothing); spear, storage, writing (a campfire, a storage, 2 signs).
  - `people`: nothing learned (10 campfires); storage, torch, trapping (a campfire, 2 storages); six techniques (a campfire, 2 storages, a sign).
  - `recall600`: six techniques (a campfire, 2 storages, 4 signs); nine, including carpentry, bridging and shelter (4 campfires, 2 signs, a shelter, a storage); toolmaking and writing (nothing).
  - Every newcomer ended in or beside Brackenford.
  - All 36 techniques were worked out by experimenting. No newcomer received a gift.
  - Typical end relations were thin and named by silence ("Nodded to my offer day 29 — first answer Brackenford gave", "hailed, not in earshot — no more chasing"). Most lines went to nobody in particular: 75–162 per run.
- **The `people` mix** sent 10–35% of deliberations to deepseek-flash (101 of 286, 35 of 348, 35 of 368). It cost about 10% more per run, with no gain in what was learned or built. It had more refused acts, a wide spread.
- **A recall budget of 600 against 800 changed almost nothing in what a decision costs.** Deliberation prompts were 10.7k against 10.8k tokens, because recall is a small part of an 11k prompt. Tokens per run were the same. The arm learned the most (5.7, range 2–9), within the spread of the others.
- **Night reorganization (`night-batch`).** It ran 15–16 times per run, about every two game days: 141 calls, 2.72M tokens (5% of `la1`), p50 72 s, p95 437 s, 5 invalid replies and 1 empty.
  - It merged 329–558 nodes per run (stances 205–430, places 44–144, ideas 34–73) and retracted 147–376.
  - **It merges different people.** 31 merges joined one `person:<id>` into another with a different id (control 0, 0, 2; `people` 7, 17, 1; `recall600` 0, 3, 1). In `life-people-r1`, `person:46` and `person:78` were merged into `person:50`, renamed "unresponsive townsfolk". In `life-people-r2`, `person:76` was merged into `person:2`, renamed "stranger seen south".
  - The ids are the authority's character ids, so each such merge collapses two real individuals into one memory. The mind applies them without a check (`sleep.rs` reorganize, `memory.rs` merge). A guard that refuses a merge between two different `person:<id>` keys is a small mind-service change for the mind-harness owners.
  - **Correction (2026-11-10, branch `merge-guard`):** these counts are merges the model *proposed*, read from the replies. The mind applied none of the cross-person merges. `patch_from` reads only the first 12 merges of a reply, and 26 of the 31 come later. The existing guard (`merge_refused`, since 1482bf0) refused the other 5, because a `person:<id>` was never merged away. The 9 runs applied 152–174 merges each (the counts in the `reorganize` thought summaries), not 329–558. The summaries match a replay with the guard in every reorganization, and do not match one without it. The renaming was real: a reorganization's node ops renamed people (224 person names in the replies, 16 of them generic, such as "unresponsive townsfolk" on `person:50`), because `sleep_finish` did not run `name_people` as consolidation does. Merges of stances into a person (`stance:kelta_worth_another_try` into `person:31`, 4 among the merges read) were applied. `merge-guard` refuses merges between different identities and into or out of them, tells the mind which merges were refused at its next sleep, and keeps people's names. The replay is `memory::tests::merge_replay` ([living core](LIVING_CORE.md), memory graph).
  - **Side finding (not fixed on `merge-guard`):** 1,180 of the 1,368 place rows in the lane A snapshots sit at exactly (96, 96). The island seed gives `map: {"kind": "land", "size": 2048}`, but the mind reads only `map.w`/`map.h` (`living/mind/src/main.rs`), so `prompts::map_size()` falls back to 96 × 96, and `sugar_into` clamps every place a mind locates to that corner. In land worlds, minds' located places and the `place` projection are wrong, and the new located-place rule does not tell two places apart.
  - Both are fixed on main: the renaming and stance-into-person merges in beaa0df, the place clamp in 8fd4f43.
- **Lane A's place-based memory ran with clamped places.** Positions and settlements in these results come from the authority, so they are unaffected. What the minds did with places is affected: the places they named, walks to remembered places, and memories cued by a place. The social preset and the overnight iterations ran on the same mind code, so they carry the clamp too.

#### `la2`: every animal with a mind

All 34 island animals (10 wolves, 24 deer) are subjects; a person has no mind. An animal is asked to think only while a person is within 25 tiles.

| Measure | `default` (switches off) | `animal-switches` (`pack,salient,choose`) |
| --- | --- | --- |
| Calls per run | 583 (521–691) | 483 (437–523) |
| Tokens per run | 1.37M (1.19–1.67M) | 1.12M (0.99–1.27M) |
| Deliberations per run | 28, 4, 210 | 8, 7, 21 |
| Consolidations per run | 493, 534, 481 | 482, 430, 502 |
| Calls per wolf-hour | 2.6–3.4 | 2.1–2.6 |
| Tokens per wolf-hour | 5.8k–8.2k | 4.9k–6.2k |
| Wolves dead at the end | 10, 10, 9 of 10 | 10, 10, 10 of 10 |
| Deer killed by wolves | 4, 0, 7 | 4, 0, 0 |
| Deer dead (all causes) | 6, 2, 7 of 24 | 4, 7, 2 of 24 |
| People killed | 0 | 0 |

- **Consolidation is the animals' cost, not thinking.** About 480 consolidations per run in both arms are 90–99% of the tokens. The switches cut deliberations near people and save about 18% of tokens. With people rarely near the animals, there is little for them to save.
- **The wolves starve, minds or not.** 56 of the 60 wolf deaths were starvation, in two waves at minutes 56–62 and 86–89 in every run. Two were killed by residents and one died of old age. The packs killed 0–7 deer per run before dying. `hunger-1` changed people's food routine, not the wolves'. Why the wolves' starting ways do not feed them is not established here: the same clock in every run, minds or not, points at the instinct graph or the deer's reach, not at the minds. On main 9be23e9 with no minds at all (`eco9`, `animals-life` × `instinct`, 120 min), 9 of 10 wolves starved and 2 deer were killed by wolves, so it is the instinct ecology and not the minds; it is not changed by `hunger-1`.
- **Hunting and herding realism** cannot be read from these runs. Deliberations were few (4–210 per run, a median of 14), and the wolves were dead by minute 90.

#### Baseline on main 445db098 (`b5`, 2026-11-11 01:26–02:25)

The six scripted trials, glm-flash (`default`), 4 replicates each, `trials-1` 1ff107c. All 24 runs survived; 952 calls, 7.18M tokens, **$0.96**. Against `b4` on the same trials (main a4d79c0, 3 replicates; its glm-flash compiled at high effort and mostly returned empty text, so its DeepSeek arm is the fairer reference):

| Trial | b5 survived | b5 trial-specific | b4 glm-flash | b4 deepseek-flash |
| --- | --- | --- | --- | --- |
| hungry | 4/4 | received food 3/4; peak hunger 42.9 (41.7–44.4) | 1/3, received 1/3 | 3/3, received 0/3 |
| hungry-village | 4/4 | received food 2/4; peak hunger 48.9 (41.4–60.5) | 3/3, received 0/3 | 3/3, received 3/3 |
| teacher | 4/4 | learned the cloak 2/4, made it 2/4 | 0/3, 0/3 | 3/3, 2/3 |
| theft | 4/4 | perceived the theft 2/4, spoke to the thief 2/4 | 0/3, 0/3 | 1/3, 2/3 |
| wolves | 4/4 | struck at a wolf 4/4; lowest health 28 (12–37) | 2/3 | 1/3 |
| wolves-valley | 4/4 | struck at a wolf 1/4; lowest health 86 (55–97) | 3/3 | 3/3 |

- **No regression after the merges.** Every subject lived; the wolves trial, which killed most subjects in b1, b2 and b4, now ends with the subject fighting (4/4 struck a wolf) and surviving at 12–37 health.
- **Decisions are active again on glm-flash:** 12–23 graph revisions and 8–18 lines per run, against 2–4 and 1–5 for b4's glm-flash (the empty-reply problem, since fixed by per-purpose efforts).
- **Cheaper per game day** in four of six trials (theft 153k against 207k–219k; hungry 186k against 158k–232k); wolves is dearer (363k), because the fight is decided turn by turn.
- Invalid deliberations: 6 of 374. Spread is wide in every trial (first meal 0.4–13 min in theft); 4 replicates is the floor for comparisons against this baseline.

### Long lives and the social baseline on main 445db098 (`l6`, `s11`, 2026-11-11)

**`l6`:** the life presets (island `life`, `life-ruin`, `life-pressure`), glm-flash, 3 replicates each, planned for 6 hours. Since `arrival-1`, every one of them puts the newcomer on the first town's square. **All 9 newcomers starved, at minutes 38–201.** Last night's six-hour lives (`la1`, main 47e82a3, arrival outside the gate by the bushes) all lived. Eating is unchanged since 47e82a3 (berries 12, fish 16, …), so this is the arrival, not the food rules.

| Run | Died at | Lines (people) | Gathers, meals | Cost | Last goal |
| --- | --- | --- | --- | --- | --- |
| island r1 | 120 min | 37 (10) | 19, 16 | $0.24 | "eat today — by my own hands or a knocked door" |
| island r2 | 53 | 20 (6) | 2, 3 | $0.08 | "feed myself by my own hands today — fish, fire, cooked food" |
| island r3 | 83 | 37 (10) | 7, 7 | $0.13 | "eat today — berries, fish, anything, before any other work" |
| pressure r1 | 38 | 8 (3) | 0, 2 | $0.06 | "eat before anything else" |
| pressure r2 | 40 | 18 (2) | 0, 3 | $0.07 | "eat before anything else tomorrow" |
| pressure r3 | 57 | 24 (9) | 6, 3 | $0.11 | "eat today by my own work before anything else" |
| ruin r1 | 201 | 66 (18) | gathers 22 failed on fishing spots out of sight; 4 store takes | $0.48 | "read the old one's sign by the house southeast; find food or work for food" |
| ruin r2 | 89 | 47 (13) | 24, 4 | $0.17 | "eat before I promise anything more" |
| ruin r3 | 106 | 77 (15) | 13, 8 | $0.25 | "eat today—ask #3, #74, #73 by the fire, mending offered free" |

How these lives went (`life_story.py l6`): within the first hour every goal list becomes "eat today"; the mind searches for the nearest bush or tree in the town, where none is in sight ("ranging for wood since none grows by the hall"), most often failing "gather → nearest tree: not in sight" (13–20 times in a life), and never walks out. Nothing is built or learned (one campfire, one gift of berries to a hungry child, in `ruin r3`); relationships do not form beyond first meetings (0–15 people spoken to, then the persona's people list is emptied at death). Cost is low because the lives are short: $0.12–0.14 per hour. The longest (`ruin r1`, 201 min) shows what a life does when it lasts: hour 1 "learn to build — storage first, then shelter", hour 2 fishing the south bank before winter, hour 3 "find living water or fill the pack from the west bushes"; 32 people known, the closest "the child I feed" (trust 45, affinity 68), a campfire, a gift of food to that child, 4 store takes; its loop was "gather → nearest fishing_spot: not in sight" 22 times.

**`s11`:** the social preset (seeds 7, 11, 13 and 7 again), glm-flash, 120 min, 4 replicates, $7.84. 2 of 4 newcomers starved (minute 92, both); the two that lived went outside the walls (54% of one's samples, 94 m past the edge) or gathered 32 times and took 5 from stores. Asks heard 13.8 (6–27) per run, food given 0.8, no lesson, lodging, agreement or demand. It replaces `s10`/`i9` as the social reference.

**`l7`:** because island lives now end within two hours, the "player playing the game" view comes from the valley (`life-valley`, stage3-village, arrival at the map centre), 3 × 6 hours, started 04:17. Iteration 10 tests the island failure directly.

### Baseline on main cb5214b7 (`b6`, `b6b`, `s12`, `s12b`, `l7`, 2026-11-11)

**Scripted trials (`b6`, then `b6b`).** All 24 runs survived ($0.78). Two trials no longer staged their scene: since lives-2 the island trials' picked Elmwick resident brings its seeded home, family and places, and its mind walked home ("walk back north to the Elmwick square before dark"): in the wolves trial it walked 315 m in the two minutes after the pack's release and never fought (b5: 4 of 4 struck a wolf); in the theft trial no owner perceived the theft (b5: 2 of 4). The island trials (wolves, theft, hungry, teacher) now spawn a newcomer as their subject (trials-1 5ae9937); rerun as `b6b` (4 trials × 4, $0.59): all survived; theft perceived 2/4 and the thief spoken to 3/4; the cloak learned 3/4 and made 3/4; food received 1/4 in hungry. In the wolves trial the pack now reaches the newcomer but no wolf attacked (lowest health 94–100). Not the wolves' instincts: the trial replaces them with its own graph (walk to 9 tiles from the subject, wait 15 s, attack a person in sight), and the pack stopped 11–16 m away, outside its 11 m daytime sight (6 m at night), so the attack never fired (inspected live on e6b7e698, `w6`; the same at 16 m on cb5214b7). On their own instincts an ordinary wolf flees a person within 7 m unless its hunger is 90 or more and takes meat from remains first; only a bold wolf attacks any person within 10 m. The trial's pack now walks to 5 tiles (trials-1 d755e4f): **`w7` on e6b7e698 (4 replicates, $0.19): all survived; lowest health 57 (12–87), so the pack attacks again; the newcomer struck back in 1 of 4** (b5: 4 of 4) and otherwise moved off (22 m on median in the two minutes after release). `w7` is the wolves reference for e6b7e698. `b6` with b6b's four trials is the scripted reference for cb5214b7; wolves-valley and hungry-village from `b6` (all survived; struck a wolf 0/4, received food 3/4).

**Social preset, every person a mind (`s12`, `s12b`).** `minds.only: "all"`, glm-flash, 192 concurrent calls, capped at 60 minutes for cost. Two runner fixes were needed first: the runaway watchdog's call-rate rule (60 a minute, for one mind) stopped both runs after 30 s, and its failure rules stopped them at minute 10 and in the first minute on the provider's 429 "not enough capacity" (about 1% of 3,000 calls); for `minds.only: "all"` worlds the rate rule is off unless a budget sets one, and failures count only as a share of the calls (half; 40% for the same failure). The aborted attempts cost $9.77 (kept under `aborted/`).

| Seed | Minds thinking | Tokens | Cost | Asks (heard) | Talk turns island-wide | What reached the newcomer |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | 311 | 214M | $30.79 | 17 (6) | 1,962 | lodging ("takes you in as their guest until 07:00: a bed in their house"), 2 fish |
| 11 | 310 | 198M | $28.53 | 20 (11) | 1,857 | nothing |

About $29–31 an hour for an island of minds (lives-2 measured about $34), $0.05 per resident-hour. The first lodging and the first fish given to a newcomer in any social run came here, where the residents think.

**Valley lives (`l7`, main 445db098, `life-valley` × 3, 6 hours).** The valley seed compresses lives: all three subjects died of old age at minute 328.5, having lived full lives. Worked out 8, 8 and 6 techniques, all by experimenting (an earlier count of "2 from someone, once" was r3 teaching Maoska trapping and fire: `life_share.py` read the teacher's learn row as the learner's, fixed on `feel-measure`); built 7–10 things beyond fires and shelters; decided to teach 1, 5 and 17 times, 2 of which landed; 6–26 trades and gifts; wrote 0–24 tablets; 13–15 people; 197–279 lines; $0.18–0.19 an hour. Even so only 2–10% of their plans were about something other than food or warmth (`life_share.py l7`): they lived by working for food.

### Tokens and cost

| Batch | Calls | Tokens | Cost |
| --- | ---: | ---: | ---: |
| `la1` (9 runs) | 6,843 | 56.4M | $9.32 |
| `la2` (6 runs) | 3,200 | 7.46M | $1.92 |
| Lane A | 10,043 | 63.8M | $11.24 |

### The social preset (`ls1`, `ls2`, 2026-11-10 00:29–03:22)

`life-social` (residents wake into minds when engaged; town life layer 2, main 6de2bad) on `trials-1` f39f92c with the moved pack, island seeds 7, 11 and 13 (one per replicate, `world_seeds`), 150 minutes, `LIVING_ONLY=<subject>,woken`. `ls1`: people on glm-flash (default); `ls2`: on deepseek-flash. Woken residents think on the models file's `woken` route (the `people` mix) in both.

| Run (seed) | Residents woken (by the newcomer) | Stage-cap binds | Lines said to the newcomer (by how many) | Talk turns | Food, lesson, lodging given to it | Slept inside a settlement | Tokens | Cost | Cost per engaged resident-hour |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glm-flash r1 (7) | 17 (0) | 438 | 5 (2) | 69 | none | 208 of 334 sleep samples | 24.1M | $4.51 | $0.19 |
| glm-flash r2 (11) | 27 (3) | 287 | 30 (5) | 69 | none | 338 of 338 | 21.4M | $4.00 | $0.11 |
| glm-flash r3 (13) | 0 | 0 | 0 | 0 | none | 0 of 515 | 2.0M | $0.31 | – |
| deepseek-flash r1 (7) | 22 (3) | 206 | 24 (3) | 44 | none | 205 of 303 | 22.6M | $4.31 | $0.12 |
| deepseek-flash r2 (11) | 25 (2) | 171 | 10 (2) | 52 | 2 berries (one gift) | 158 of 307 | 20.3M | $3.94 | $0.12 |
| deepseek-flash r3 (13) | 0 | 0 | 0 | 0 | none | 0 of 299 | 1.9M | $0.43 | – |

Six runs: $17.50 and 92M tokens; the newcomers themselves are about 2M tokens per run (the rest is residents). The newcomer survived in all six.

- **Waking cascades.** Of 91 wakes in the four engaged worlds, the newcomer caused 8 (0–3 per world); woken residents speaking to neighbours caused the rest (17–27 woken per world). The stage cap (6 per settlement) then bound 171–438 times. Iteration 6 tested stopping this (a woken resident's words do not wake): 80% fewer woken and 58% fewer tokens, with the newcomer answered at least as often.
- **Answers, but not help.** Where it engaged anyone, the newcomer was answered (5–30 lines from 2–5 people). Across the six runs it received one gift (2 berries), no lesson and no lodging; `host` was never used (as in TOWN_LIFE.md's paid runs). It fed itself by gathering. What it learned (writing, torch, archery, toolmaking, storage, trapping in the glm runs) it worked out by experimenting.
- **It slept inside a settlement** in the engaged worlds (47–100% of its sleep samples within a settlement's radius), against none on seed 13, where it engaged no one. Inside, not lodged: no lodging place in any run.
- **Seed 13:** in both models the newcomer engaged no resident in 150 minutes and nobody woke. See the diagnosis below.
- **Models.** glm-flash and deepseek-flash for the newcomer cost alike here because residents dominate; DeepSeek's newcomer got slightly more lines in seed 7 (24 against 5) and fewer in seed 11 (10 against 30). Two worlds each; no ranking.

### Why the newcomer got so little (diagnosis from `ls1`/`ls2` journals and rows)

Read from the four engaged runs (seeds 7 and 11, both models) with `living/tools/social_report.py` and one-off scripts over the residents' journals. An "ask" is a line the newcomer addressed to someone that names food, a lesson or a bed (a keyword match on its words; read the examples, not only the counts).

- **It asked, clearly enough, and half its asks went unheard.** 58 addressed asks, mostly offers of work for "a meal and a corner to sleep in", a few plain ("If you've a handful of berries to spare"). 27 of the 58 were said to someone out of earshot: the newcomer got "No answer from …; they don't seem to be within earshot" and nobody heard the line.
- **Heard asks were answered at once, with words for later.** The asked resident's first thought followed in a median 5–22 s. The answers: conditions and promises for later in about half ("start with these gate hinges … fix them right and there's a meal in it. Bed's another question"; "ask Mami about a corner"; "tomorrow, decide with Rohantor whether Arlen gets a proper bed"), the rest other talk. No resident refused in its own words outright; one said "I'm newly arrived here myself, so I've no roof to offer" (its identity, written by the model at waking, calls it newly arrived).
- **The few acts decided were refused by the rules, with reasons.** Residents decided 5 gives and 2 teaches toward the newcomer in the four runs, and no `host`. Gaka promised "a good handful" of berries in a talk turn after eating its last two in the deliberation before ("not enough berries"), then tried the one it had when the newcomer had walked out of sight ("no #296 in sight"); it said so plainly ("I promised you a handful and I'm short of it"). Iseos tried to give berries 8 times while the newcomer was out of sight. Yamo agreed to teach masonry and was refused "you don't know masonry yourself". The one gift that reached the newcomer was 2 berries.
- **Promises faded under the residents' own lives.** 15 residents put helping the newcomer in their intentions or plans ("tomorrow, teach Arlen storage-craft", "at first light, find Arlen at the square — share berries"); 4 of them ever decided an act toward it. The intentions were displaced by warmth, food and family (several turned to asking a partner for a child). Formal agreements (a talk's `settled` with `until`) about help were rare: 4 in four runs; two were acted on when due (Gaka), in the other two the resident thought of the newcomer when the time came and did nothing.
- **Neither the stage cap nor the cascade starved the answerers.** One of the 58 asks fell while the asked resident was held off stage. Asked residents had 50–149 thoughts over 61–147 minutes, many naming the newcomer (Gaka 52 of 124, Zomaren 67 of 75); each had 0–20 cap reports (at most one a minute while held off stage).
- **What the answering turn could not see.** A woken resident answers in a talk turn. That prompt shows who it is, its feelings, recall, recent dealings, the scene and the conversation, and standing offers; not its pack, not its know-how, not its home, and the acts it lists are conceive, accept, give, offer and teach, without `host`. So it promised berries it had eaten, a lesson in a technique it did not know, and talked about beds it could not see a way to give. The struct's own comment says this part carries "what one carries and knows (for acts)"; only offers were filled in. This is the lever iteration 8 tests.
- **Seed 13's newcomer arrived outside the town and never got in.** Its arrival point is 23 m outside the town's radius at the north gate, about 120 m from the centre (seeds 7 and 11 arrive 18–20 m inside). Its lines there were greetings to no one ("Hello the town! … Anyone about?"); unaddressed speech wakes only the one listener within 6 m or a resident named, and no resident was in earshot. It walked to the gate tiles, not through them (a `goto` to its own place "Brackenford gate" was "destination unreachable"), and in 150 minutes saw one person (glm) or eight (DeepSeek), never within the radius. The nearest buildings were 18–38 m away. This is about where the world puts the arrival, not how residents answer; not changed tonight.

## Player-likeness measures (2026-11-11)

The owner played the game and found that characters feel like NPCs and that survival is too central. `living/tools/life_feel.py` scores each run for how far it reads like a player run by AI living its own life rather than an NPC surviving. It is read-only and makes no model calls. Its docstring gives the exact definition of every column. **Every class is a keyword or skill heuristic, pending calibration against the owner's ratings of the same lives.** It prints verbatim examples for each measure, so a reader can check the classes before trusting a number.

```bash
python3 living/tools/life_feel.py l7                                   # a batch under this checkout's .local/living/trials
python3 living/tools/life_feel.py --root ~/dev/slop-trials/.local/living/trials l6 l7 \
    ~/dev/slop-trials-cb/.local/living/trials/l8 ~/dev/slop-trials-e6/.local/living/trials/i11   # a BATCH may also be a path
```

A run still in progress (no `summary.json`) is read from `state.json`, its files so far and the mind's live journal, as `trials.py` reads it. The six measures:

- **Initiative:** `plans_other` and `acts_other` are life_share's shares. `self_started` is the share of decided acts that are social, making or exploring and were not preceded within 60 s by a line addressed to the subject. A line whose own words are about food or warmth counts as survival.
- **Horizon:** persona goals clustered by word overlap. `goals_1d_other` is the number held a game day or more and not about food or warmth. `goals_reached` is the number with a matching outcome in rows: a build, a technique, a tablet, a give or agreement, a lesson given, or a named place first reached.
- **Loops:** `fail_repeats_h` counts identical failures (same act, same refusal) per real hour. `fail_streak` is the longest unbroken run of one failure. `plan_repeats_h` counts verbatim plan re-installs per hour.
- **Exploration:** `cells_h` is distinct 16 m cells per hour. `far_m` is the farthest point from the arrival.
- **Social reciprocity:** `addressed` lines, and `silence`, the share of them that got no answer from the addressee within 60 s.
- **Distinctiveness**, per batch × trial × variant: mean 1 − cosine between replicates. `skill_diss` uses decided acts by skill, `body_diss` the activity share in samples, and `goal_diss` the goal vocabulary. Near 0 means the lives look alike.

Batches: `l6` (main 445db098, island presets, 6 h planned), `l7` (valley, 6 h), `l8` (main cb5214b7, 6 h), `i11` (iteration 11's three arms, 120 min) and `l9` (main with iteration 11, 6 h). `l9` was still running when read, at about 190 of 360 minutes (13:13); 3 of its 6 runs were alive and its numbers are partial. Mean (range) per arm:

| batch | trial | variant | n | min | starved | plans_other | self_started | goals_1d_other | goals_reached | fail_repeats_h | plan_repeats_h | cells_h | far_m | addressed | silence | skill_diss | body_diss | goal_diss |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `l6` | life | default | 3 | 85 (53–120) | 1.0 (1–1) | 0.12 (0.04–0.21) | 0.10 (0.03–0.17) | 3.3 (2–4) | 0.0 (0–0) | 11.47 (0–22.4) | 0.23 (0–0.7) | 9.20 (5.1–13.5) | 56 (25–112) | 18 (10–23) | 1.00 (1–1) | 0.16 (0.04–0.25) | 0.11 (0.02–0.16) | 0.63 (0.44–0.74) |
| `l6` | life-pressure | default | 3 | 45 (38–57) | 1.0 (1–1) | 0.08 (0–0.19) | 0.02 (0–0.04) | 2.7 (2–4) | 0.0 (0–0) | 13.30 (6–24.4) | 0.00 (0–0) | 14 (12.7–18.1) | 41 (25–58) | 5.7 (2–10) | 1.00 (1–1) | 0.12 (0.06–0.18) | 0.04 (0.02–0.05) | 0.76 (0.64–0.83) |
| `l6` | life-ruin | default | 3 | 132 (89–201) | 1.0 (1–1) | 0.03 (0.01–0.04) | 0.12 (0.07–0.19) | 3.3 (1–5) | 1.7 (0–4) | 25 (23.6–27.1) | 0.37 (0–1.1) | 9.23 (8.8–9.6) | 59 (44–82) | 31 (24–45) | 1.00 (1–1) | 0.02 (0.02–0.03) | 0.04 (0.02–0.05) | 0.66 (0.60–0.73) |
| `l7` | life-valley | default | 3 | 329 (329–329) | 0.0 (0–0) | 0.06 (0.02–0.1) | 0.21 (0.19–0.22) | 8.3 (4–15) | 15 (12–16) | 25 (17.3–29.7) | 0.67 (0.4–0.9) | 4.60 (3.8–5.1) | 71 (58–78) | 164 (144–185) | 1.00 (1–1) | 0.07 (0.06–0.09) | 0.02 (0.02–0.03) | 0.48 (0.48–0.49) |
| `l8` | life | default | 3 | 160 (57–360) | 0.7 (0–1) | 0.20 (0.11–0.32) | 0.35 (0.14–0.53) | 5.0 (1–12) | 4.3 (0–13) | 15.60 (2.1–37.2) | 0.57 (0–1) | 8.23 (6.6–10.4) | 91 (27–191) | 27 (13–53) | 1.00 (1–1) | 0.30 (0.19–0.48) | 0.28 (0.02–0.43) | 0.67 (0.63–0.73) |
| `l8` | life-pressure | default | 3 | 261 (64–360) | 0.3 (0–1) | 0.19 (0.05–0.3) | 0.19 (0.13–0.29) | 8.0 (5–12) | 3.0 (0–8) | 19.30 (5.6–26.5) | 0.73 (0–1.2) | 11.13 (9.4–12) | 125 (38–178) | 64 (27–122) | 1.00 (1–1) | 0.28 (0.06–0.46) | 0.19 (0.04–0.33) | 0.75 (0.60–0.83) |
| `l8` | life-ruin | default | 3 | 94 (55–118) | 1.0 (1–1) | 0.19 (0.03–0.31) | 0.20 (0.09–0.37) | 2.7 (1–4) | 0.0 (0–0) | 16 (15.3–16.2) | 0.53 (0–1.1) | 9.80 (6.6–15.2) | 55 (39–84) | 32 (20–42) | 1.00 (1–1) | 0.09 (0.05–0.14) | 0.05 (0.03–0.08) | 0.80 (0.68–0.88) |
| `i11` | iter11-life | default | 4 | 111 (83–120) | 0.2 (0–1) | 0.10 (0.02–0.22) | 0.23 (0.14–0.36) | 4.8 (4–6) | 0.0 (0–0) | 12.55 (4.5–28.5) | 0.50 (0–1) | 16.95 (6.5–46) | 80 (40–170) | 35 (21–61) | 1.00 (1–1) | 0.05 (0.01–0.12) | 0.18 (0.01–0.33) | 0.74 (0.65–0.81) |
| `i11` | iter11-life | iter10b | 4 | 107 (69–120) | 0.2 (0–1) | 0.21 (0.19–0.23) | 0.25 (0.08–0.41) | 4.5 (2–6) | 0.0 (0–0) | 14.40 (8.6–23.5) | 1.23 (0.9–1.5) | 10.85 (6.9–16) | 74 (23–124) | 32 (24–43) | 1.00 (1–1) | 0.04 (0.02–0.08) | 0.15 (0.03–0.31) | 0.74 (0.67–0.88) |
| `i11` | iter11-life | iter11 | 4 | 120 (120–120) | 0.0 (0–0) | 0.28 (0.17–0.37) | 0.33 (0.28–0.36) | 5.5 (3–8) | 0.2 (0–1) | 11.75 (9–16) | 0.38 (0–1) | 6.12 (5.5–7) | 57 (34–76) | 58 (49–62) | 1.00 (1–1) | 0.03 (0.01–0.05) | 0.05 (0.02–0.08) | 0.75 (0.70–0.86) |
| `i11` | iter11-pressure | default | 4 | 90 (58–120) | 0.5 (0–1) | 0.22 (0.1–0.33) | 0.23 (0.17–0.32) | 2.5 (1–4) | 0.5 (0–2) | 9.88 (3.8–19.5) | 0.50 (0–1) | 13.75 (6.7–32) | 66 (28–143) | 25 (7–53) | 1.00 (1–1) | 0.11 (0.02–0.21) | 0.24 (0.04–0.49) | 0.80 (0.71–0.90) |
| `i11` | iter11-pressure | iter10b | 4 | 110 (88–120) | 0.5 (0–1) | 0.26 (0.16–0.33) | 0.16 (0.06–0.28) | 3.8 (3–5) | 0.5 (0–2) | 14 (11.7–15.5) | 0.90 (0.5–2.1) | 13.07 (6.4–29) | 74 (40–133) | 34 (7–52) | 1.00 (1–1) | 0.05 (0.01–0.10) | 0.08 (0.02–0.20) | 0.71 (0.54–0.89) |
| `i11` | iter11-pressure | iter11 | 4 | 120 (120–120) | 0.0 (0–0) | 0.27 (0.08–0.57) | 0.33 (0.21–0.46) | 5.2 (4–6) | 0.0 (0–0) | 9.88 (6–20) | 1.00 (0.5–1.5) | 6.00 (3.5–9) | 52 (18–109) | 45 (36–59) | 1.00 (1–1) | 0.07 (0.02–0.14) | 0.26 (0.02–0.41) | 0.75 (0.71–0.82) |
| `l9` | life | iter11 | 3 (3 running) | 193 (193–194) | 0.0 (0–0) | 0.20 (0.06–0.27) | 0.18 (0.16–0.21) | 5.3 (3–9) | 0.3 (0–1) | 17.47 (5–25.1) | 0.93 (0.6–1.6) | 10.73 (5.9–16.7) | 132 (119–156) | 48 (21–77) | 1.00 (1–1) | 0.06 (0.02–0.10) | 0.07 (0.04–0.10) | 0.70 (0.62–0.79) |
| `l9` | life-pressure | iter11 | 3 (1 running) | 190 (186–193) | 0.7 (0–1) | 0.25 (0.23–0.27) | 0.25 (0.14–0.36) | 2.3 (2–3) | 0.0 (0–0) | 9.87 (6.3–14) | 0.60 (0.3–0.9) | 2.83 (2.5–3.4) | 37 (23–47) | 44 (32–67) | 1.00 (1–1) | 0.04 (0.02–0.05) | 0.19 (0.01–0.32) | 0.73 (0.70–0.76) |

**Reading.**

1. Survival still fills the mind's own words. In every arm 3–28% of plans are about neither food nor warmth. The valley lives that reached old age (`l7`) are among the lowest (6%): they lived long by working for food.
2. Iteration 11 (`person_pace` 0.3) is the only change that moves initiative. In `i11` it raises `plans_other` to 0.27–0.28 and `self_started` to 0.33, against 0.10–0.26 and 0.16–0.25 for the other arms, with no deaths. In `l9`, on main, the values are 0.20–0.25 and 0.18–0.25.
3. A high `self_started` is not the same as living well. The highest single run (`l8` life r2, 0.53) spent a 57-minute life greeting people and starved. Read `self_started` beside `starved`.
4. No act was prompted. No one addressed the subject in any of these runs, so `self_started` is all of the directed acts and `prompted` (in the full output) is 0.
5. Lives hold 2–8 goals for a game day or more that are not about food or warmth, for example "learn writing so fire_bolt outlives me" (14.6 game days, `l9` life r2) and "turn the market stall into something properly mine" (15.9 d, `l9` pressure r2). On the island almost none of them reach an outcome in rows: 0–0.5 per run, except `l8`'s 6-hour survivors (up to 13). In the valley, 12–16 goals per life reach one, mostly survival goals (a shelter, a storage, fire worked out). The longest-held goal is often "someday, a family of my own" (15 d in `l9`, 29 d in `l8`), which a newcomer has no path to.
6. Failure loops are frequent but short. Identical failures repeat 10–25 times per hour, yet streaks reach only 1–6, because the mind does something else in between and comes back. One failure is 15% of all 3,792 failures in these batches: "gather → nearest tree: no nearest tree in sight" (65 times in `l9` life r2). Plans are seldom re-installed word for word (0–1.6 per hour), so the loop is in the acts, not the plans.
7. Exploration is short-range. Lives enter 3–17 new 16 m cells per hour and reach 37–132 m from the arrival on average, at most 191 m in six hours. `l9` pressure ranges least (2.8 cells per hour, 37 m).
8. Silence is total: 1.00 in every run here. Subjects addressed 2–185 lines each and no addressee answered, because the residents of a single-mind trial do not think. This is a finding about the trial setup, not about the subject. For contrast, `s11`, whose woken residents think, has silence of 0.55–0.72 (`life_feel.py s11`).
9. Replicates do alike things but say different things. Their bodies' activity profiles are nearly identical (`body_diss` 0.02–0.28) and so are their decided-act profiles (`skill_diss` 0.02–0.30), while their goal wording differs (`goal_diss` 0.48–0.80). The valley lives are the most alike (0.02 and 0.07). Each life tells its own story over the same days of gathering, eating and sleeping: this is the NPC-likeness the owner saw.
10. These numbers are keyword heuristics, not calibrated scores. Have the owner rate a handful of these lives, compare the ratings with each column, and keep only the columns that agree.

**Weak measures.** `goals_reached` is the least reliable. Goal wording drifts inside a cluster, so an outcome can answer a different wording of the same goal, and the outcome classes are keyword matches. `goals_1d` depends on how often consolidation rewords goals (Jaccard threshold 0.4). `acts_other` counts every `say` and `wave` as "other", so asking for food scores as living. `self_started` counts every `wander` as exploring. `prompted` has been checked only on `s11`. `fail_streak` is broken by any act outcome in between.

### Owner-tuned player score

`life_feel.py` stays a set of heuristics until the owner's judgement says which columns, if any, track "a player living their own life". Three tools close that loop. All three read evidence read-only and make no model calls. The one exception is an explicit `feel_tune.py judge --run`, which needs real ratings.

1. **Excerpts.** `feel_excerpts.py build` cuts candidate windows of 10 real minutes from every thinking character's run. It scores each window with life_feel's own columns, computed on just that window, and draws about 20 excerpts. The draw follows a per-source quota and spreads across the arms within each source. Within an arm it alternates trials and early and late windows, and it reaches toward the 5th and 95th percentiles of `feel0`, a provisional composite: the mean percentile of the initiative, exploration and social columns minus the loop columns. `feel0` only stratifies the draw and is not a score. Each excerpt is a plain second-person timeline of at most 12 lines. It opens with the plan held at the start. Exchanges (a line to the character and its reply) are kept together, and the other lines follow: plan changes, failures and struggles, things learned, given and received, and other percepts. A line said again, or a repeated percept, is folded into one line with a count. A closing line gives how the body spent the window and how hunger moved. Runs whose subject is a scripted human (the greeting trials) are followed through a thinking resident. Its speech comes from `speech.jsonl` joined to `audience.jsonl`, and other people are named only once the resident knows them. Its other percepts are the stamped lines of its journal requests, placed in time through the census, and its body comes from `census.jsonl`. A subject, who has the same newcomer name in every trial, gets a pseudonym, while a resident keeps its own name. Ids, coordinates, day numbers and clock minutes are removed, and nothing names a run, batch, model or arm. It writes `.local/living/feel/excerpts.json` (blind, for the page) and `.local/living/feel/excerpts_key.json` (private: id → source, run, variant, window, columns). Both are under the git-ignored `.local/living/`. Never serve, commit or show the key to the rater.
2. **Rating page.** `feel_page.py` turns the blind file into one HTML page. Each excerpt carries one question, "Does this feel like a player living their own life?", answered on a 1–5 scale with an optional one-line reason. The page is published as a private claude.ai Artifact with the `db`, `user` and `downloads` capabilities. Every click saves the document `owner_ratings/<excerpt id>` = `{score, reason, at, rater, source: "page"}` on the artifact's server-side store. The page never touches the `ratings` collection, where the proxy's ratings are kept, and it ignores any `proxy:` document, so the owner always rates blind. To read the ratings back, call the ArtifactData tool's `list` on collection `owner_ratings` for that artifact URL and save the result as JSON. Without the store, for example in a saved copy, the page keeps ratings in the browser and offers "Copy ratings" and "Download ratings.json", which write the shape `feel_tune.py` reads.
3. **Tuning.** `feel_tune.py fit --ratings R` joins the ratings to the key. Per column, for both the window values and the whole-run values, it reports Spearman ρ and a permutation p. It then fits a ridge on the standardized columns and a single-column isotonic fit. Both are scored leave-one-out, with the column and λ chosen inside each training fold, against two baselines: the mean rating and `feel0`. Each predictor gets Spearman, within-one, exact agreement and MAE. The report lists every excerpt where the score and the owner disagree, with the owner's reason. `feel_tune.py judge` builds an LLM-judge rubric from the owner's reasons, leave-one-out, so no excerpt is judged with its own rating in the prompt. The default `--dry-run` writes the prompts and a cost estimate. `--run` uses DeepSeek V4.1 Flash on Mistral's API (`MISTRAL_API_KEY`) and refuses synthetic ratings. Both commands refuse with "no ratings: no agreement claim" when fewer than 5 ratings exist. `feel_tune.py synth` writes a clearly labelled synthetic ratings file for testing the plumbing, and every report built from it carries a "SYNTHETIC RATINGS" banner.

```bash
python3 living/tools/feel_excerpts.py build                    # default sources and quotas (docstring); --source L=DIR --quota L=N to change
python3 living/tools/feel_excerpts.py show [--key]             # the blind excerpts as text (--key adds sources: coordinator only)
python3 living/tools/feel_page.py                              # .local/living/feel/page/player_feel.html, to publish as the Artifact
python3 living/tools/feel_tune.py fit --ratings .local/living/feel/ratings.json
python3 living/tools/feel_tune.py judge --ratings .local/living/feel/ratings.json            # dry run: prompts and cost only
python3 living/tools/feel_tune.py fit --ratings DIR --proxy                 # proxy ratings only, labelled PROXY on every output
python3 living/tools/feel_tune.py compare --owner NEW_DUMP --proxy OLD_PROXY_DUMP   # the owner's ratings against the proxy's
python3 living/tools/feel_tune.py judge --ratings .local/living/feel/ratings.json --run --env-file ~/dev/slop-trials-e6/.env --base-url https://api.mistral.ai/v1   # paid; only with the owner's ratings
```

The first page (2026-11-11, 22 excerpts) is the claude.ai Artifact `https://claude.ai/artifact/MyiNwW9QmdXt1m91H4b5xX`, and its key is `.local/living/feel/excerpts_key.json` in the `tool-feel-tune` worktree on the Spark. It leaves out the `greet-nearest` (gr1a) and `park-concurrent` (gr1b) arms, whose runs failed at publish (`--skip`, default). They rerun as `gr1c`, which `build --quota gr1c=N` adds to a later page. To collect the owner's ratings, save an ArtifactData `list` of collection `owner_ratings` with `out_dir` and pass that directory as `--ratings`. A rebuild draws new excerpt ids, so do not rebuild while ratings for the published page are still coming in. Keep the key that matches the page. The excerpts cover 10 real minutes and the owner rates lives as they read, so a window-level column can agree with the owner while the whole-run column does not, or the reverse. The report gives both.

**Proxy ratings.** A rating document whose `rater` starts with `proxy:` (or that names `proxy_for`) comes from someone rating on the owner's behalf. `fit` and `judge` refuse such documents unless `--proxy` is given. With `--proxy` they use only proxy documents. Every output then says "PROXY RATINGS (general coordinator, rating for the owner); not the owner's judgement", and files get a `_proxy` suffix. No proxy report claims agreement with the owner. The page (version 2, 2026-11-11) writes the owner's ratings to `owner_ratings`, so they never replace the proxy's documents in `ratings`. `compare --owner <owner_ratings dump> --proxy <ratings dump or the saved copy>` reports the differences.

On 2026-11-11 the owner asked the general coordinator to rate the first page in their place, so those 22 ratings are proxy ratings. They are saved in `.local/living/feel/ratings-proxy-2026-11-11/` on the Spark, and the fit is in `.local/living/feel/proxy-fit/tune_report_proxy.md`. The proxy's rubric:

- 4–5: pursues something of its own beyond food and warmth, deals with other people and is answered; relationships with history (a debt, a promise, a child learning); wants negotiated with someone.
- 3: an agenda beyond survival, but nobody answers or the act lands on no one.
- 1–2: a survival loop; plans restated unchanged; the same line said to silence; repeated failures; nobody else present.
- Being answered mattered most.

**Circularity.** The proxy rater stated that being answered mattered most. A fit that finds `heard` and `answered` as the signal therefore shows that the rubric was applied consistently, not that it matches the owner's judgement. `feel_tune.py` prints this in the header of every proxy report and of every proxy-tuned score.

What the proxy fit says (proxy ratings, n = 22; one rater, one sample):

1. Window columns about being spoken to track the proxy ratings best: `heard` ρ +0.90, `silence` −0.79, `addressed` +0.78, `answered` +0.76, all p < 0.001.
2. Leave-one-out, the window ridge reaches Spearman +0.70, within-one 0.86 and MAE 0.84. Its whole-pipeline permutation p, with fitting and the pick of the best predictor included, is 0.020 over 200 shuffles. `feel0` reaches +0.57, and the run-level ridge +0.53.
   After `feel_excerpts.py rescore` (the same windows, placed from the key's 0.1-minute starts, with the own-project columns kept out of the models as probes), the window ridge reaches +0.68, within-one 0.91, MAE 0.89, with a whole-pipeline p of 0.030 over 200 shuffles.
3. Much of this is the split between worlds. Excerpts where everyone thinks average 4.10 and single-thinker lives 1.75 (AUC 0.92). `heard` and `answered` are 0 in every single-thinker window, so they cannot rank those lives. Within the single-thinker lives the window ridge reaches only +0.43 (p 0.08, n = 12); `addressed` (+0.82), `lines` (+0.77), `self_started` (+0.74) and `people` (+0.74) are the columns that vary with the rating there. The whole-run columns mostly encode the split: all-minds runs are short and hold few goals, so `goals_1d` and `min` correlate negatively with the rating.

**The proxy-tuned score, never alone.** The score rises when residents simply talk more, including when they answer lines meant for others or repeat themselves. `feel_tune.py score BATCH_DIR...` applies the fit's window ridge to every thinking character's windows, per arm. It always prints the score beside three guards over the same lives:

- false replies per minute, from `greet_report.py` where the batch's checkout has it;
- the share of a character's own lines that repeat one of its own from the last 10 minutes;
- the share of addressed lines that led to something within 180 s: an outcome the character is part of (a trade, lesson, gift, help, hosting or agreement), or a new plan of its own or of the addressee that names the other.
- beside it, a placebo: the same test with every line moved 6 minutes earlier. Whatever the placebo still finds was not caused by the line, so read the difference.

Runs without `final.json` (still running, or failed before writing their rows) are left out unless `--include-running` is given. Against a baseline arm (a `control` arm, else `default`), an arm that raises the score while any guard gets worse is reported as `LOST`, and a guard that cannot be measured is named as unmeasured. On 2026-11-11, with the proxy-tuned model (report `.local/living/feel/score/score_report_proxy.md` on the Spark):

- gr1a `greet-nearest` (finished run r4 only) raised the score (4.13 against 4.11) while false replies rose from 0.010 to 0.081 per minute and repeated lines from 0.11 to 0.13. It is reported `LOST`.
- pf2 `player-frame` (still running, scored with `--include-running`) raised the score (2.72 against 2.56) while talk that led to something fell from 0.02 to 0.00. It is reported `LOST`, with false replies unmeasured.
- In the hamlet, talk that led to something is 0.64–0.71, but the placebo already finds 0.47–0.58. Most of what this guard counts there would happen without the line, so only the difference means anything.

**Sustained own-project activity** (`life_feel.py` measure 7: `own_project`, `project_acts`, `project_progress`). It looks for a goal of the character's own, held from the first to the last third of the window's plans and intentions. Food and fire or cold are excluded, but a cloak or a shelter can be a craft project, and names and filler words are excluded too. It then counts the acts toward that goal, each once: decided acts or, failing those, attempts, plus the character's own lines naming it. It also records whether one of them was done. The measure was added for the known blind spot: a resident with her own project in a village that talks around her (Mara, timber for her own house) got 1.2 from the window ridge where the proxy gave 4. `feel_excerpts.py rescore` recomputes the key's windows with it, and `fit --probe` reports it outside every model, so nothing is refitted to claim agreement. A review found that the first version depended on hash order and took words like "pack/full/work" or "Millbrook" as projects; both are fixed. Result, on proxy ratings:

- It marks Mara (`own_project` 1.0, timber, 4 acts) and two other highly rated residents: Cal teaching and writing (rytd3, 1.0) and the carpentry in tha3g (0.94).
- It does not close the other gap. vpxff, also underrated, scores 0. It also gives high values to four low-rated single-thinker lives with a held but unanswered project: storage (2zt89, 0.95), a shelter (vnr8j, 0.94), wood and toolmaking (s2asb, 1.0) and a trap line (u86uh, 0.71).
- Across the 22 excerpts it tracks neither the proxy ratings (ρ +0.05) nor the window ridge's residual (ρ −0.04).

The measure finds held projects. What the proxy rewarded is whether anyone answers, which this measure does not see.

**No LLM judge on proxy ratings.** `judge --proxy` refuses outright, building no prompts and making no call. The judge waits for the owner's own ratings.

## The hamlet: a small world where everyone thinks (2026-11-11)

Branch `exp-hamlet-births`. Status: **built and proved with fake minds only** (`hm2` on Cullet's day and laws, `hm0` and `hm1` before them on the 12-minute day; below). No paid run has been made on it.

The seed [`hamlet`](../living/seeds/hamlet.json) is [`authored-test`](../living/seeds/authored-test.json) with five more residents, larger stores, the fishing spots and berry bushes each settlement promises (`resources`), and no animals. It keeps that seed's 96 × 96 realm map and its sheets. Since main brought a seed's own day and laws (`rules-1`, [Cullet's rules](CULLET_RULES.md)) it has Cullet's day (`day_minutes` 48) and Cullet's laws (`laws_file` `worlds/cullet/laws.rhai`). Its pace is `year_days` 4 and `life_pace` 0.0357, a quarter of `authored-test`'s 0.1428, so that a life still lasts 8 real hours on the four-times-longer day. Twelve people live in four households in two settlements a short walk apart. Each settlement has houses, a store on its square, planted berry fields and its own fishing water. Nothing is restocked during a run. Ids are the seeding order. Each person's death of old age is fixed by their id (`Life::deathline`), so the death times below come from `births_report.py`.

| Id | Who | Age | Household | Stage at start | Thinks in `hamlet` | Dies of old age at |
| ---: | --- | ---: | --- | --- | --- | ---: |
| 1 | Oren Hale, farmer, owes Teodor | 41 | mill (Millbrook) | adult | yes | 151 min |
| 2 | Ilsa Hale, cook, Oren's wife | 38 | mill | adult | yes | 159 min |
| 3 | Pim Hale, their son | 7 | mill | child | yes | 409 min |
| 4 | Teodor Vane, mason, wants an apprentice | 70 | forge | elder | yes | 49 min |
| 5 | Brisk Marrow, guard | 29 | marrow | adult | yes | 246 min |
| 6 | Mara Vane, carpenter, Teodor's granddaughter | 25 | forge | adult | yes | 307 min |
| 7 | Edda Marrow, fisher, Brisk's wife | 27 | marrow | adult | yes | 247 min |
| 8 | Tobin Marrow, their son | 1 | marrow | infant | from about minute 8, when he becomes a child | 450 min |
| 9 | Wenna Reed, fisher, widow | 37 | reed (Reedmouth) | adult | yes | 226 min |
| 10 | Cal Reed, hunter, Brisk's rival | 52 | reed | adult | yes | 92 min |
| 11 | Sefa Reed, Wenna's daughter (the subject) | 19 | reed | adult | yes | 337 min |
| 12 | Lio Reed, Wenna's son | 10 | reed | child | yes | 377 min |

Food is plentiful. Within 24 m of the two squares there are 31 and 22 berry bushes, wild and planted, and 2 and 7 fishing spots (verify-generation, `generation-hamlet-20261111-141545`). A bush holds 5 berries and regrows 1.2 a minute outside winter (`regrow`). A person gets about 1.2 hunger a real minute awake (Cullet's 2.4 a game hour), about 0.1 berries' worth. The stores hold 16 berries, 10 cooked fish, 6 fish and 10 wood between them, and everyone carries a few berries or fish. Winter, when nothing regrows, is one game day in four: 48 real minutes of every 192.

The tensions are in the sheets and none is scripted. Oren's debt to Teodor and the secret of the sold seed grain come from `authored-test`. Teodor has no apprentice, and Mara wants a house of her own rather than his trade. Brisk and Cal are rivals. Sefa wants to leave her mother's house.

- **Minds.** `hamlet` thinks for every person past infancy, at most 12 at a time (`minds.max`, above): 11 at the start, 12 once Tobin is a child. In a stable population every person thinks. If the hamlet grows past 12 people old enough to think, the youngest live on their seeded ways until a death frees a place. Each time someone joins the thinking set, the runner restarts the mind service (at most every 2 minutes), which breaks off model calls and conversations in progress for all of them. A death alone does not restart it. `hamlet-solo` thinks only for the subject (`LIVING_ONLY` = 11). The other eleven run their behaviour graphs, as the island's residents do in a scripted trial, and graph adults do not conceive. Both runs go on to their full duration after the subject's death (`life.stop_on_death` false). The solo run then has no mind at all and costs nothing more.
- **Cullet's day and laws.** The seed sets them, and the world composes the overlay when it is created. Cullet's laws give needs per game hour, so 48 hunger a game day is the same 1.2 a real minute awake as before. They also give eased dusk and dawn, and Cullet's senses: sight 48 m by day and 14 m in the dark, 20 m with a torch, someone in lamplight seen from 28 m, names within 24 m, and speech carrying 12 m. Night is 20:00–06:00, 20 real minutes of the 48. The runner installs the skills file after publishing, and installing the bare file would drop the overlay. So the runner composes the seed's `laws`/`laws_file` over that file first, the way `floors::compose` does (`compose_laws`, shared with verify.py through `living/tools/install_script.py`), then applies any `skills_patch`. The **laws guard** (`laws_problems`) then fails the instance before any mind starts, logging each reason as `laws guard: …` in `actions.log` and as an `error` event, when: the `script` row read back after `install_script` is not the source the runner sent; for a seed with laws, the world's creation-time script is not the runner's composition of those laws over the tree's `skills.rhai` (for a `wasm_tag` module, built on another branch, the row must at least end with the laws); or `world.day_ms` is not the seed's `day_minutes` (12 minutes without one). A variant with `"keep_laws": true` installs nothing and keeps the script the world was created with; its row is checked against the composition the same way, and it may not carry `skills` or `skills_patch`. A passing instance logs `laws guard passed: …`. `python3 living/tools/trials_laws_selftest.py` plants each mismatch (on the hamlet's real composition, against a fake database) and checks that it is refused. The hamlet's earlier sight `skills_patch` is gone.
- **What the runner records** besides the subject's samples: `census.jsonl` every 30 s (every character's stage, life and death, parents, position, hunger and activity, and the thinkers), hourly snapshots, and every resident's journal.

```bash
python3 living/tools/trials.py build hamlet hamlet-solo hamlet-spaced hamlet-provided hamlet-longing
python3 living/tools/trials.py run --batch hm0 hamlet hamlet-solo --replicates 1 --minutes 10 --fake
python3 living/tools/births_report.py hm0
python3 living/tools/trials.py clean --batch hm0
```

### Fake proof

`hm2` (after merging main fd2030c, which carries rules-1): 2026-11-11 15:08–15:19, fake model, 10 minutes, one replicate of each of the five trials on Cullet's day and laws. Modules: `trial-hamlet-5a897620` (hamlet, solo, provided), `-94c40654` (spaced), `-48fa2f46` (longing). The world rows read `day_ms` 2880000, `life_pace` 0.0357 and `year_days` 4. The longing world had its `world_law` rows (120, 4). In all five runs `actions.log` says `seed laws composed as the world composed them: True`. The provided run installed `seed laws,conceive_food,conceive_roof`. The host's load was 26–28, from other builds and `l9`.

| Run | Minds thinking | Model calls (by purpose) | Calls per real minute per mind (run / minutes 5–10) | Tick p99, minute 1–2 | Ticks over 16.7 ms |
| --- | --- | --- | --- | --- | ---: |
| `hamlet` | 11, and 12 from t = 484 s (`reslot`: Tobin) | 201 (consolidate 85, think 53, deliberate 53, talk 10) | 1.80 / 1.82 | 0.92 ms | 0 |
| `hamlet-spaced` | the same (t = 484 s) | 195 | 1.74 / 1.67 | 0.92 ms | 0 |
| `hamlet-provided` | the same (t = 482 s) | 198 | 1.77 / 1.83 | 1.00 ms | 0 |
| `hamlet-longing` | the same (t = 487 s) | 200 | 1.79 / 1.83 | 0.87 ms | 0 |
| `hamlet-solo` | 1 (Sefa Reed #11) | 7 | 0.70 / 0.4 | 0.86 ms | 0 |

Mind processes used 67–81 MB resident. No one died or was born in 10 minutes. Teodor's death is due at minute 49, the same real time as before: the life was kept at 8 real hours. Fake minds made more calls on Cullet's day (1.8 a minute per mind against 1.1–1.5 on the 12-minute day). The fake model answers at once, so this is the mind's cadence, not a price.

Before rules-1 (the 12-minute day, `life_pace` 0.1428, the same lives in real time, sight by `skills_patch`):

`hm0`: 2026-11-11 14:13–14:24, fake model, 10 minutes, one replicate of each, module `trial-hamlet-c43ae3e5` built from this branch's working tree. The trial service also carried batch `l9` and other builds (load 14–21).

| Run | Minds thinking | Model calls (by purpose) | Calls per real minute per mind | Tick p99 at min 2.5–3.5 / 8.5–9.5 | Ticks over 16.7 ms |
| --- | --- | --- | --- | --- | ---: |
| `hamlet` | 11, and 12 from t = 484 s: Tobin became a child and the runner restarted the mind with him (`reslot`) | 164 (consolidate 63, think 48, deliberate 48, talk 5) | 1.47 over the run (11.2 thinking on mean); 1.13 in minutes 5–10 | 0.94 / 0.37 ms | 0 |
| `hamlet-solo` | 1 (Sefa Reed #11) | 10 (consolidate 4, think 3, deliberate 3) | 1.0; 0.4 in minutes 5–10 | 0.85 / 0.31 ms | 0 |

Mind processes used 33–69 MB resident. What else the run showed:

- The cast picked Sefa Reed (#11, the youngest adult) as the subject, the sight patch of that version was installed (`patched sight` in `actions.log`), and each run wrote 21 census rows.
- The population stayed 12 → 12. No one was due to die in 10 minutes; Teodor's death is due at 49.
- Fake replies carry no acts, so the act shares are empty. 42 plans were classed, none about food or children.
- Tobin was within 4 m of a grown person in 60% of his census rows while an infant. 10% of grown persons' rows had him that near.

The fake call rate shows the mind's cadence, not a price. Fake replies come instantly and are nearly empty: no acts, almost no talk.

`hm1`: 2026-11-11 14:24–14:29, fake model, 4 minutes each. It checked that each rule arm publishes and runs with its values in place:

- `hamlet-spaced` ran on its own module, `trial-hamlet-3209f898`. Its derived seed carries `species.person.life.interbirth` 0.15.
- `hamlet-provided` ran on the `hamlet` module with `patched sight,conceive_food,conceive_roof` (skills sha256 `90a905b0067d`).
- `hamlet-longing` ran on `trial-hamlet-4bc47b22`. Its `world_law` rows were `longing_after_min` "120" and `longing_food` "4".

All three ran their full 4 minutes with 11 minds and 1.26–1.33 calls a minute per mind. They were cleaned up afterwards (`trials.py clean --batch hm1`).

## Births that keep a settlement's numbers (2026-11-11)

The owner's working target is an experiment, not a change to the defaults: over a long run a settlement's numbers stay roughly the same, with births about matching deaths from old age, so that newborns do not pull grown people's time back to survival. On the island with everyone thinking, births ran at about 61 in 10 game days.

### The arithmetic

The person life table (`species.json`): `years` 70; infant until 0.03 of a lifespan, child until 0.23, elder from 0.85; death of old age at each person's own point between `old_age` 0.87 and 1.0, spread evenly by id; `gestation` 0.011; `interbirth` 0.03 (after a birth both parents are raising the child, `rearing`, and neither can conceive); `litter` 1. Only adults (0.23 to 0.85) may conceive (`conceive_check`). A game day is 48 real minutes in the hamlet (`day_minutes`) and 12 on the island.

A lifespan in game days is L = years × `year_days` × `life_pace`.

| | Hamlet (`day_minutes` 48, `year_days` 4, `life_pace` 0.0357) | Island (12-minute day, `year_days` 8, `life_pace` 1) |
| --- | --- | --- |
| Lifespan L | 70 × 4 × 0.0357 = 10.0 game days × 48 min = 480 real min = **8.0 h** | 70 × 8 × 1 = 560 game days = **112 h** |
| A year of age | 0.143 game days = 6.9 real min | 8 game days = 96 real min |
| Infant, child, adult from | 0–14 min, to 1.84 h, then adult | 0–3.4 h, to 25.8 h, then adult |
| Elder from (0.85 L) | 6.8 h | 95 h |
| Death of old age (0.87 to 1.0 L, mean 0.935 L) | 6.96 to 8.0 h, mean 9.35 game days = 7.48 h | 97 to 112 h, mean 524 game days = 105 h |
| Gestation (0.011 L) | 0.11 game days = 5.3 min | 6.2 game days = 74 min |
| Raising after a birth (0.03 L) | 0.3 game days = 14 min | 16.8 game days = 3.4 h |
| Shortest time between one couple's births (0.041 L) | 19.7 min | 4.6 h |

**Births a stationary population needs.** If no one dies before old age, a population of N stays stationary when b = N / (mean age at death) = N / (0.935 L) births a game day. In a stationary population a share (0.85 − 0.23) / 0.935 = 0.66 are adults. Each couple then needs 2 children over its 0.62 L of adult life, one per 0.31 L.

- **Hamlet, N = 12:** 12 / 9.35 = 1.28 births a game day, **12.8 per 10 game days** (8 real hours), so 3.2 per 2 real hours. Over a 6-hour run (7.5 game days, 0.75 L) that is 12 × 0.75 / 0.935 = **9.6 births**. Per adult, 1.6 per 10 game days. Per couple, 3.2 per 10 game days (one per 0.31 L, 2.5 real hours), if every adult is in a couple. Everything in real time is as it was on the 12-minute day, because the lifespan in real time was kept. Only the count of game days per life changed, from 40 to 10.
- **Island, N ≈ 311 (everyone thinking, `s12`):** 311 / 524 = 0.59 a game day, **5.9 per 10 game days**. 61 is about ten times that. That count was the first wave: no one is raising young at the start, so every willing couple conceives at once.
- **Today's ceiling:** an eager couple, conceiving at each first chance, can have a child every 0.041 L, so 1 + (0.62 − 0.011) / 0.041 ≈ 16 children over an adult life. That is 8 times replacement. Only the minds' choices hold births down today.

**Deaths of old age in the hamlet's age mix.** At this pace everyone seeded at 18 or older (the 8 adults and Teodor) dies within 6 hours. By `deathline` the deaths come at 49, 92, 151, 159, 226, 246, 247, 307 and 337 real minutes (table above): **9 in 6 hours**, about one every 37 minutes, against the stationary 9.6. Next are Lio at 377, Pim at 409 and Tobin at 450 minutes. The two seeded couples' fertile windows close when the first partner becomes an elder: Oren and Ilsa at about 127 minutes (Oren), Brisk and Edda at about 209 (Brisk). A child born in the run is an adult 1.84 h later, so children born in the first 4 hours can have children of their own within the run. To keep 12, the hamlet needs about 9–10 births in 6 hours, spread across the run, and some of them from couples formed during the run.

### Rule arms

Each arm is general law or data. None names the hamlet or touches what minds may decide. The shipped behaviour is unchanged: the new laws' shipped values reproduce today's rules (Cargo `laws_with` and `longing_wait_ms` tests; the `family_laws` scene under verify-core). Each arm is its own trial on the hamlet world, so it runs with the same cast, map and minds.

| Arm (trial) | Values | What a body can do | What it should give |
| --- | --- | --- | --- |
| Control (`hamlet`) | shipped: `interbirth` 0.03, `conceive_food` 0, `conceive_roof` false, `longing_after_min` 20, `longing_food` 0 | today's rules | the births minds choose today |
| **Spaced** (`hamlet-spaced`) | `species.person.life.interbirth` **0.15** (world.overrides.species, merged over species.json at build) | after a birth both parents raise the child for 0.15 L (1.5 game days, 72 real min here; 84 game days, 16.8 h on the island) | an eager couple has at most one child per 0.161 L (77 real min): 6.2 per 10 game days here, twice the 3.2 a couple needs when every adult is paired. That is replacement when about half the adults are paired, as at the hamlet's start (4 of 8). 0.30 would be replacement with everyone paired (one per 0.311 L), but with the hamlet's two couples that caps births well under the 9 deaths. |
| **Provided** (`hamlet-provided`) | `conceive_food` **8**, `conceive_roof` **true** (skills_patch of `skills.rhai`) | to start a family the two must carry 8 portions of food between them, and the asker must stand under a shelter or in a house | births depend on a surplus put by, so more mouths sharing the same bushes and fishing spots make a surplus harder to gather. With the hamlet's plenty (above), the gate costs effort and timing (gathering and keeping 8 rather than eating them) rather than scarcity, so its density dependence is weak there. It would bind harder in a leaner world. 8 berries are 96 hunger. Under Cullet's laws that is one game day of a pair's hunger (48 a day each), or 3.3 game days (2.7 real hours) of an infant's (29 a day). |
| **Later longing** (`hamlet-longing`) | `longing_after_min` **120**, `longing_food` **4** (world.rules) | unchanged; anyone may still choose to conceive | the felt drive ("You long for a child…", the alert that asks a mind to think) comes 120 min × (1 − nurture/120) after one's own birth or youngest child's: 70 min at nurture 50, 35 at 85, and only while carrying 4 food. Once due, it comes back each dawn as today (it goes off at night; iteration 3). On the hamlet's pace that is about 0.15 L, the spaced arm's interval. It tests whether the drive is what drives births, without changing any rule of the body. |

The fact the rules needed and Rhai could not see was the longing drive's timing and condition, which were Rust constants. They are now laws (`longing_after_min`, `longing_food`, typed in `Laws`, settable by a seed's `rules`). `conceive_check` reads only what the actor's context already had (`near_shelter`, `inv`, the target's `inv`), so no new actor field was added.

### Measures

`living/tools/births_report.py BATCH...` reports, per run: births; deaths by cause; population (by stage) every 30 minutes; the seeded people due to die of old age within the run against those who did; the stationary births for the run's length; the mean number thinking and model calls per real minute per thinking mind; the share of grown people's plans and decided acts about food and about children (keyword and skill classes, with examples printed); and the time grown people spend within 4 m of an infant, with the share of infant time that some grown person is that near. `life_feel.py` and `life_share.py` still read the subject alone. They now find journals of names with spaces (`Sefa_Reed.jsonl`, `trials.journal_file`).

### Planned batch and its cost

Four arms × 3 replicates × 6 hours on glm-flash (`default`), plus `hamlet-solo` × 3 × 6 hours for experiment 2:

```bash
python3 living/tools/trials.py build hamlet hamlet-solo hamlet-spaced hamlet-provided hamlet-longing
python3 living/tools/trials.py run --batch hb1 hamlet hamlet-spaced hamlet-provided hamlet-longing hamlet-solo \
    --replicates 3 --sample-s 5 --stagger 15
```

An estimate, not a measurement. It uses the coordinator's island figure of about $0.10 per thinking person per hour on glm-flash. Nothing has been measured on the hamlet. Two things may raise it: 48 m sight puts more people in each scene, and fake minds called about 1.8 times a minute per mind on Cullet's day against 1.1–1.5 on the 12-minute day.

| Arms | Runs | Thinking at most | Person-hours | Estimate |
| --- | ---: | --- | ---: | ---: |
| `hamlet`, `hamlet-spaced`, `hamlet-provided`, `hamlet-longing` | 4 × 3 | 12 | 4 × 3 × 12 × 6 = 864 | $86 |
| `hamlet-solo` | 3 | 1, until Sefa dies at 5.6 h | 3 × 5.6 ≈ 17 | $1.7 |
| **Total** | 15 | | ≈ 881 | **≈ $88, about $14.7 an hour while all 15 run** |

These are upper bounds. Fewer think when deaths outrun births, and only the cap of 12 bounds it from above. With 2 replicates the batch is about $59. Fifteen small worlds are well within what one trial service carried in "Running wide" (40 island worlds). The census adds four whole-table reads per world every 30 s.

**SpacetimeDB documentation checked** (2026-11-11): [HTTP database API](https://spacetimedb.com/docs/http/database/). The SQL endpoint is "intended primarily for management, debugging and interactive developer use, and [has] not been optimized for performance to the same extent as the WebSocket API". The census is that use: evidence for a trial, a developer's audit truth, and not a game data path. Its reads touch small worlds only. Nothing here adds or changes a table, reducer, view or subscription. The new laws are values of the installed script (`Laws`). A seed's `rules` already writes them into the existing `world_law` table.

### Not covered

- No real model has run on the hamlet. Fake minds do not conceive, so fake runs show the plumbing (minds, census, restarts) and nothing about births.
- Cullet's laws were written for Cullet's town (lamplight, hearths, coats). The hamlet's houses and campfires are what the authored-test layout gives: no lamps and no coats in the stores.
- The arms' values are derived from the arithmetic, not tuned. How often a pair actually carries 8 food, so whether the provided arm's gate binds, is not known until real minds run.
- The `family_laws` scene proves each law's gate on a scratch world. It does not prove what minds do with them.

## The greeting trial (2026-11-11)

Branch `exp-greet`. Status: fake proof (`gf4`, `gf5`, below) and paid batches [gr1/gr2](#greeting-batches-gr1gr2-2026-11-11). `nearest` + `concurrent` is the default since 2026-11-11; the `greet-control` variant runs the old rules (`off`, `wait`).

**What it is for.** The owner played 7 minutes in a town of 17 minds and found that "people didn't seem very interactive when talking to them". The session journals showed two causes. A newcomer's "hi" to no one, with two or more people within 6 m, drew no conversation turn, because nobody cared about a stranger. A line could also wait out a whole deliberation whose prompt was built 0.6 s before it: 12.7 s from 1 m away. The conversation switches `LIVING_GREET` and `LIVING_PARK` (docs/LIVING_CORE.md, Conversations; both off by default) address these. This trial measures them as the owner met them.

**The world.** [`greet`](../living/trials/greet.json) is the hamlet (12 people in four households, everyone past infancy thought for, at most 12 at a time; [the hamlet](#the-hamlet-a-small-world-where-everyone-thinks-2026-11-11)) under Cullet's laws: the seed's `day_minutes` 48 and `laws_file` `worlds/cullet/laws.rhai`, so speech carries 12 m and sight 48 m by day. It is meant to carry over to Cullet, where the owner will play. The world keeps who heard each line (`rules.speech_audience`) in every arm, so arms differ only in the mind's environment.

**The player.** A scripted human (`Player.greet_session` in trials.py) joins with its own identity and plays only through `join`, `human_act` and `human_say`. It plays in cycles of about six minutes:

1. It walks to the densest group of residents, re-chosen every 15 s, with a `goto` act to the group's centre (`{"at": [x, y]}`, as click-to-walk does), until two residents are within 5 m. A short step toward them then turns it to face into the group.
2. It says a greeting to no one ("Hello there!", "Good day to you all.", …).
3. After 50 s it says a line addressed (`to`) to the nearest resident within earshot, 12 m: the game client's rule (`talk-1`) when no one is under the cursor.
4. After another 50 s it stands among them saying nothing for 150 s, while residents talk among themselves.

Its lines name nobody, and it never says its own name, so it stays a stranger to those it has not met. It calls at least every 10 s, so its character is never taken over during the run.

**What is recorded** besides the usual evidence: `record.speech` writes every line said in the world (`speech.jsonl`), `record.talk` every conversation turn with the line it answered (`talk.jsonl`), and `record.audience` the `audience` rows (`audience.jsonl`). Each line of the player is a `human_line` event with the residents within 12 m and their distances. All of these are small-world options: one indexed read each per sample.

**Measures** ([`greet_report.py`](../living/tools/greet_report.py), read-only, no model calls). For the player's unaddressed and addressed lines separately:

- `crowded`: lines said with two or more residents within 6 m. These are the owner's case: the authority then marks no one addressed.
- `answered`: a resident spoke to the player within 60 s and before its next line, or a talk turn answering that very line spoke. The second form is needed because the chronicle merges a repeated line into its earlier row. Also `answered_5s`, the latency median and p90, and who answered: `by_nearest`, `by_addressed`, and `by_turn` (a conversation turn rather than a deliberation).
- `false_replies`: talk turns that answered a resident's line meant for someone else, meaning addressed to another, or said to no one while its speaker was in an exchange with another (a line between them within 60 s before). `listen_false` counts those within the player's listening windows. `overheard_turns` counts all turns on residents' lines said to no one.
- Cost: residents' talk turns per minute, talk tokens and all tokens per minute, and estimated dollars per hour.

```bash
python3 living/tools/trials.py build greet
python3 living/tools/trials.py run --batch gf4 greet --variants greet-control,greet-nearest,greet-curious,greet-facing,park-concurrent,greet-nearest-concurrent \
    --replicates 1 --minutes 15 --fake --fake-script living/trials/fake/latency.json --parallel 6 --stagger 15
python3 living/tools/greet_report.py gf4 --examples 3
python3 living/tools/trials.py clean --batch gf4
```

Variants: `greet-control` (`LIVING_GREET=off`, `LIVING_PARK=wait`), `greet-nearest`, `greet-curious`, `greet-facing`, `park-concurrent` (greet off), `greet-nearest-concurrent` and `greet-facing-concurrent`. All think with `default`.

### Fake proof (`gf4`)

`gf4`: 2026-11-11 15:21–15:37, fake model with `living/trials/fake/latency.json`, 15 minutes, one run per arm. The script delays think 5 s, compile 4 s, talk 1.5 s and consolidate 2 s, as in the owner's journals. Its talk replies leave the exchange open: the fake's default reply settles every exchange at its first turn, which silenced each later line from the same stranger in `gf3`. The trial service also carried batches `l9` and `pf2` (load about 35 on 20 cores).

The fake's words are canned, so these numbers prove the mechanics, not what minds say. Each arm had four lines of each kind, and every unaddressed line was crowded.

| Arm | Unaddressed answered | Latency med / p90 (s) | Addressed answered | Latency med / p90 (s) | False replies | Talk turns/min | Model calls/min |
| --- | ---: | --- | ---: | --- | ---: | ---: | ---: |
| `greet-control` | 0 of 4 | – | 3 of 4 | 2.3 / 4.3 | 2 | 2.6 | 27.9 |
| `greet-nearest` | 4 of 4 | 1.6 / 3.0 | 4 of 4 | 2.5 / 4.3 | 2 | 4.1 | 22.1 |
| `greet-curious` | 1 of 4 | 1.5 / 1.5 | 2 of 3 | 2.2 / 2.6 | 0 | 2.0 | 26.9 |
| `greet-facing` | 3 of 4 | 1.7 / 3.0 | 3 of 4 | 4.3 / 12.7 | 3 | 6.3 | 24.3 |
| `park-concurrent` | 0 of 4 | – | 3 of 4 | 2.6 / 4.3 | 1 | 3.4 | 21.4 |
| `greet-nearest-concurrent` | 4 of 4 | 2.3 / 3.6 | 3 of 4 | 2.6 / 4.3 | 2 | 2.9 | 19.7 |

What the fake run shows:

- Under the shipped rules no crowded greeting was answered (0 of 4). Under `nearest` all were (4 of 4), by the nearest resident free to talk, 1.5–3 s later.
- `facing` answers whoever the player faces. It also addresses residents' own lines to whoever they face, which tripled the talk turns (6.3 a minute against 2.6) and gave the most false replies.
- `curious` draws in a stranger's listener by chance, and the first drawn takes the turn. One of four greetings drew someone.
- The addressed line that went unanswered under the shipped rules was a remark that asked nothing. It lost the remark draw that the switches skip for strangers.
- The addressed p90 of 12.7 s under `facing` (parked) is a line parked while the addressee deliberated, as in the owner's session.
- False replies are mostly a child answering a parent's line said while the parent was in an exchange with someone else (Pim answering Ilsa). The shipped rule does this too: family cares.
- Model calls per minute vary between arms with how often the fake's plans finish. Talk turns are 2–6 of 20–28 calls a minute.

`gf5` (2026-11-11 15:40–15:53, 12 minutes; control, nearest+concurrent, facing) repeats the proof on the branch after merging main's `talk-1` (the client's addressed speech). Crowded greetings were answered 0 of 3 (control), 3 of 3 (nearest+concurrent, median 1.7 s) and 2 of 3 (facing); addressed lines 2 of 3, 3 of 3 and 2 of 3; false replies 3, 1 and 7.

### The paid batch, planned

```bash
cd <a checkout of exp-greet with .env (MISTRAL_API_KEY, CARLID_NPC_API_KEY)>; . ~/slop-sysroot/env.sh
export CARGO_TARGET_DIR=$HOME/slop-greet-target
python3 living/tools/trials.py build greet
python3 living/tools/trials.py run --batch gr1 greet \
    --variants greet-control,greet-nearest,greet-curious,greet-facing,park-concurrent,greet-nearest-concurrent \
    --replicates 4 --parallel 8 --sample-s 5 --stagger 15
python3 living/tools/greet_report.py gr1 --examples 3
python3 living/tools/trials.py clean --batch gr1
```

The planned design is six arms × 4 replicates × 25 minutes, with 11 minds thinking (12 once Tobin is a child). It is not a full factorial: `LIVING_PARK` is crossed only with the control and with `nearest`.

The cost is an estimate, not a measurement. It uses the island figure of about $0.10 per thinking person per hour on glm-flash ([births](#planned-batch-and-its-cost)). A run is about 12 × 25/60 = 5 person-hours, about $0.50, so the batch is about 120 person-hours, $12–15. The upper end allows for the switches' extra talk turns (at most 4 more a minute, about 1–2k tokens each) and for 48 m sight putting more people in each scene. At `--parallel 8`, three waves take about 85 minutes, about $9–11 an hour.

### Not covered

- No real model has answered a greeting here. Whether residents' answers read as interactive to the owner is for the paid batch and the owner's own play.
- A single fake run per arm gives no spread.
- `verify-client` was not run for the new private `audience` table. Its scripts assume the shared server on 3300, which this machine leaves to other work. Privacy was checked through `verify-player`: a player's SQL is refused the table.
- The game client's cursor addressing is emulated only by its fallback, the nearest person in earshot.

## Arrivals: a stranger who says nothing (2026-11-11)

Branch `exp-arrive`. Status: **the trials and the report are kept as tooling for a control world; the newcomer laws were rejected and are not in the code** (2026-11-12).

**The owner's observation (play-test 3).** The owner said one "Hi", to the child Bram, who answered in character in 3.2 s. Then the owner stood silent on and around the square for 3 min 16 s with residents in earshot, and nobody approached or spoke.

**What was tried and rejected.** `exp-arrive` added three number laws (`newcomer_salience`, `newcomer_scene_min`, `newcomer_drive_s`, off by default) and arms that switched them on. They were measured in [ar2](#arrival-batch-ar2-2026-11-11). The owner rejected them as prescribed attention: "I don't really like the fact that this has been encoded as a world rule. It should be something emergent from the personality and role of NPCs." None of them was merged, not even switched off. The diagnosis, the laws, their verify-core scene and the fake proofs `af1`–`af8` stay on `exp-arrive` (`1e63a304`). What was merged (`arrive-2`): the two trials, `arrive_report.py`, the scripted player (`Player.arrive_session`), the `record` options, a trial's `variants` and `minds.concurrency`.

### The trial and the report

[`arrive`](../living/trials/arrive.json): the hamlet on Cullet's day and laws (12 people in two settlements; the 11 past infancy are thought for, `minds.max` 11). Under Cullet's life law (`life_years`, since lives-3: a lifespan of 90, a child until 15, deaths of old age from 75) the cast's stages at the start are as before: Pim and Lio children, Teodor old, Tobin an infant. A year of age is about 6.9 real minutes, so no one dies of old age within 14 minutes; the earliest, Teodor at 70, is due from about 34 minutes. Tobin leaves infancy (2.1 years) about 8 minutes in. With `minds.max` 12 the runner then restarted the mind service in the middle of the second stand (`af5`: `reslot` at 482 s, the stand 373–673 s), breaking off every mind's calls and conversations. With 11 he stays on his graph, and the player neither approaches nor answers him. The world lives 30 s (`subject.join.after_s`). Then a scripted player (`Player.arrive_session`: `join`, `human_act`, `human_move` with its own identity) joins at the arrival point, waits 20 s, walks to the densest group until two residents are within 5 m, steps to face into it and stands silent 5 minutes. Then it walks to the group sharing fewest members with the first and stands silent 5 more minutes, then stays to the end (14 minutes). It never speaks, gestures or names itself. It runs the shipped rules (`arrive-control`). Every line, conversation turn, experience row (before it is integrated), gesture and position with activity target is recorded (`record`).

[`arrive_report.py`](../living/tools/arrive_report.py) (read-only, no model calls; its docstring defines every column), per resident within 12 m of the newcomer during a stand:

- `seen`, `first_s`, `first_sal`, `crowd`: the newcomer in their experiences, the first-sight percept's time and salience, or none;
- `asked`: a thought whose reason is an experience about the newcomer;
- `thinks`, `in_prompt`: thoughts during the stands and how many prompts had the newcomer;
- `mention`, `words`: replies naming them by id, or with stranger/newcomer words;
- `approach`, `aimed`, `close`: came up to them (distance fell 3 m and ended within 4 m), an activity aimed at them, within 3 m;
- `gesture`: wave, nod, face or appraise at them;
- `to_them`, `about_them`: lines to them, or about them to others or to no one.

Per run, it gives the share of residents in range who acted, the time from the arrival to the first resident-initiated contact, thoughts per resident-minute, and calls, tokens and dollars per hour. Residents are those the minds think for (census `thinkers`, else past infancy). Then, per arm:

- **First contact by class**, per resident: `greeting`, `question` (who are you, are you new, where from), `offer` (food, a bed, help, work, company), `warning/hostility`, `other line`. Without a line: an offer or hostile act aimed at them, else `watching` (a face or appraise gesture; a gaze, standing still and turning to face them from 4–25 m; a thought naming them), else `approach, no line`. Counts per arm and three verbatim examples per class. The classes are keyword heuristics: read the examples.
- **Follow-through** (`arrive-answer`): whom the newcomer answered, how many lines that resident said after it before 90 s of quiet, the seconds to each, and who else joined.
- **Crowding**, a cost, since several converging at once reads as scripted: `converge_60s`, the most residents who spoke, gestured or aimed an activity at the newcomer within one minute; `together_4m`, the most within 4 m at once who had; `runs_3plus`. `converge_any_60s` and `together_any_4m` add approaches by distance, which routines make in every arm.
- **Cost**: dollars per hour and per run, calls and tokens per minute. Also `reused_share` (reason lines an earlier thought of the same resident already had) and `reused_events` (those that are one-time events rather than plan states: the stale-reasons effect).

`--journal DIR --subject ID --from-ms --to-ms` reads a play-test's journals (no positions). A stand the run's end cut short (no `human_stand_end`) ends at the run's last position sample, so a short or stopped run still reports.

**`arrive-answer`** ([trial](../living/trials/arrive-answer.json)) is `arrive` with one change: the player says "Hello. I'm new here." back to the first resident who addresses it, then is silent again. It runs only with the control (the trial's `variants`). Its question is whether contact becomes a conversation.

Both trials think with `minds.concurrency` 64 (the default for many minds since 2026-11-11). The player approaches and answers only residents the minds think for; the greeting trial's script, on `exp-greet`, addressed Tobin, who is not one, 2–5 times a run.

```bash
python3 living/tools/trials.py build arrive
python3 living/tools/trials.py run --batch af1 arrive --variants arrive-control \
    --replicates 1 --fake --fake-script living/trials/fake/latency.json --parallel 5 --stagger 15
python3 living/tools/arrive_report.py af1 --examples 2
python3 living/tools/trials.py clean --batch af1
```

## Fast iterations

| # | Hypothesis | Change (branch) | Runs | Result | Keep? |
| --- | --- | --- | --- | --- | --- |
| 1 | The bold pack attacks the town too eagerly: `wolf_bold` attacks any person within 10 tiles, hungry or not, and every bold pack fought Brackenford and died (w3). | `wolf_bold` attacks a person within 10 tiles only above hunger 50 (`iter-1`, 92b46f3, `instincts.json`). | `i1`: the moved pack, no mind, 30 min, control and change × 3 | **Untested**: at its new home (250–400 m out) the pack met no person in 30 minutes in any of the 6 runs: no kills, all 24 wolves alive. That confirms the move keeps it off the arrival road, not the rule. `i1b` set the pack down at its old place: it walked home (the starting graph returns a wolf to its home beyond 25 tiles), and again no one met anyone. `i1c` gave the pack its old home by the road (a seed override, 40–75 m from the arrival point): no person was killed in 30 minutes in either arm (0 and 0), and some packs were lost in both arms alike. The rule makes no visible difference; what kept newcomers alive is the move (addfe04). | **drop** |
| 2 | There is no way into reading: a failed read says only "you can't read", while every other missing technique names its ways in. | `read_check` adds `learn_how("writing")` (`iter-2`, c03a999, `skills.rhai`). | `i2`: the ladder preset, glm-flash, 40 min, control and change × 3 | Change: asked the scribe 3/3, learned writing 3/3, read a sign and learned fishing 2/3. Control: 0/3, 0/3, 0/3. **But not through the change:** no request carried the new text, and two of the three changed runs asked the scribe without ever failing a read. 3/3 against 0/3 has p ≈ 0.1, and a control subject asked the scribe in the wide batch. Rerun with 5 replicates per arm (`i2b`): writing learned from the scribe 2/5 against 2/5 (the control asked too), the fishing sign read 1/5 against 2/5. The first split was chance. A new finding in `i2b/iter2-ladder-iter2-r4`: a plan to "read both signs" re-read the nearest sign 57 times in 5 minutes and never reached the second; re-reading changes nothing, so its percept just repeats (a graph-level loop, no model calls). | **drop** |
| 3 | The longing for a child re-fires every morning and after every meal (it needs calm and daylight), driving 27–47 deliberations per 150-minute life with no partner anywhere. (Wrong, see result.) | Felt again at most once a game day (`iter-3`, 087ecbd, `brain.rs`). | `i3`: a lone newcomer, glm-flash, 40 min, control and change × 3 | **The hypothesis was wrong.** The longing percept already came once per game day in both arms (minutes 11.4, 23.4, 35.4 and 16.8, 23.4, 35.4): it goes off at night and comes back at dawn. The 27–47 "deliberations on longing" were a counting artifact: a pending percept stays among the reasons of every deliberation until one takes it up, so one feeling was counted many times. Deliberations by that count: 18.0 (6–38) against 15.0 (6–30). | **drop** |
| 4 | Main compiles at high effort; the wide batch's low-effort arm compiled in a third of the time with no loss (3 against 2 complete runs). | none: a replication, `deliberate-low` against `default` | `i4`: a lone newcomer, 40 min, × 3 | Replicated. Compile p50 3.5, 3.8 and 4.2 s against 9.9, 10.4 and 11.2 s; tokens 615k (536k–735k) against 686k (581k–779k); calls 88 against 93; nothing learned in either arm in 40 minutes, one campfire each. With the wide batch's arm 2, low effort compiles in about a third of the time for the same or fewer tokens. | **keep**: `iter-4` (750fde9) sets glm-flash `deliberate: low` in `living/configs/models.json`, for the cost study to confirm |
| 5 | A theft's owner does not see its own loss as its own: it perceives "Vikno took 4 berries from Bortha's storage" (its own name, third person) at a bystander's salience 0.5, and one owner's next thought was "My berries are safely stored". | `witnessed()` renders the event's object as "you"/"your" to the object, at salience at least 0.8 (`iter-5`, f491bd5, `perceive.rs`; general to every witnessed event that names the observer). | `i5`: theft, glm-flash, 15 min, × 3 | The theft fired in 2 of 3 control runs and in none of the change runs (no changed subject came back to its stall), so nothing to compare. One control owner recognised it anyway: it told the thief "those aren't for picking, friend" and its relation note reads "thief … Owes me 3 berries". Reruns: `i5b` never ran (the island module of that world predated main's `host` act, so the merged rules were refused at install; nothing spent); `i5c` (6 + 6, 20 min) again had too few thefts in the owner's sight. A deterministic check with no minds (`i5chk`, theft in plain view at noon) confirmed the mechanism: control "A stranger took 4 berries from Ariniazo's storage" (0.5), change "… from your storage" (0.8). The behaviour test on that scene with the owner's mind (`i5d`, 6 + 6, 6 min): every owner in both arms recognised the loss and confronted the thief (6/6 and 6/6), e.g. control "You there — those were my berries in that storage"; replies naming the loss 5.3 (2–10) against 4.8 (4–9), lines to the thief 2.2 against 2.0, trust toward the thief −14 (−55 to 25) against −18 (−40 to 5). The third-person wording did not keep owners from recognising a theft they saw; the earlier "My berries are safely stored" came from an owner who had not seen it, or from the model. | **drop** as a behaviour lever; `iter-5` (f491bd5) stays pushed as an optional perspective fix with no measured effect |
| 6 | Waking cascades. In three social trials at 44–66 minutes, 48 residents had woken: 41 because an already-woken resident spoke to them, 7 because of the newcomer. One world had 22 woken residents, and only one of them had answered the newcomer. | The engine tells the `wakes` law when a woken resident's mind is the one engaging (`by` = `woken`); the law then wakes on a woken resident's blow, threat or theft but not on its words or gestures (`iter-6`, 867b021, `woken.rs` + `skills.rhai`). Under the shipped law `woken` counts as `mind`, so the class alone changes nothing. | `i6`: the social preset on island seeds 7, 11, 13, glm-flash, 60 min, control and change × 3 | Residents woken: control 23, 17, 0 (seed 13's newcomer engaged no one) against change 2, 5, 1. Stage-cap binds 100, 147, 0 against 0, 0, 0. Residents' tokens 5.3M, 8.5M, 0 against 1.5M, 2.1M, 0.27M; all tokens per run 6.6M, 9.3M, 1.0M (mean 5.6M) against 2.4M, 3.3M, 1.35M (mean 2.35M, −58%). Answers to the newcomer 12 (from 3 people), 14 (5), 0 against 17 (2), 21 (5), 1 (1): not fewer. Cost per engaged resident-hour alike ($0.16–0.17 against $0.13–0.20). Neither arm got the newcomer food, a lesson or lodging in 60 minutes. Replicated on deepseek-flash (`i6b`, same seeds, × 3): woken 29, 4, 2 against 2, 5, 1; tokens 9.4M, 3.5M, 1.8M (mean 4.9M) against 3.5M, 3.7M, 1.6M (mean 2.9M, −41%); $3.06 against $1.86. What reached the newcomer: lessons 2 (spear, planting) against 0, food 0 against 2 berries; heard asks 11.7 against 7.7. The saving holds where a cascade starts (seed 7) and is nil where none does. | **keep**: `iter-6` (867b021), merged as c0ff89d |
| 7 | Easy self-discovery crowds out learning from people: every technique newcomers learned came from experimenting (13 of 13 in the life runs), none from a person, even where residents answer. | Experimenting reveals a technique with chance 0.1 instead of 0.3 (`iter-7`, 0648db7, `skills.rhai`). Both arms run on iter-6's module and law. | `i7`: the social preset, seeds 7, 11, 13, 60 min, × 3 | **Untested**: no newcomer experimented in either arm within 60 minutes (0 experiment acts, 0 techniques in all 6 runs), so the chance never applied. In the 150-minute social runs the first technique was worked out at minutes 45–70. Woken 2, 1, 2 against 2, 1, 1; tokens 1.1–2.4M per run in both. Needs 150-minute runs. | **not run long enough**; `iter-7` (0648db7) stays pushed |
| 8 | A woken resident answers a request without knowing what it has: its talk turn shows no pack, know-how or home and does not list `host`, so it promises in words and the few acts it decides are refused (diagnosis above). | The talk turn shows "You carry (as you last looked): …", "You know how to: …", "Your home is at […]", and lists `host` with give and teach (`iter-8`, a30e21e, `talk.rs` + `prompts.rs`). Both arms: main c0ff89d's module, rules and models; only the mind differs. | `i8`: the social preset on seeds 7 and 11 (where the newcomer arrives inside), glm-flash, 60 min, control and change × 4 (`social_report.py i8`) | **No help gained.** The mechanism ran: 37 of the change arm's 37 talk turns carried the new lines, none of the control's 12. Residents used them for honesty ("two berries is all I carry", and a give of 3 berries to a neighbour in the same turn), but toward the newcomer they set terms of work instead of giving: "Wood, Arlen … that's the day's work and your bed's paid", "Stack the wood where I can see it by dark and we'll talk about the berries", "I'll not count words". Acts decided toward the newcomer: gives 4 and teaches 2 in the control (got: 4 berries in r1, a spear lesson in r3) against 0 and 1 (got: nothing); `host` 0 in both. Asks 10.5 (0–28) against 17.5 (12–33), heard 7.0 against 11.0; woken 2.2 against 2.5; tokens 2.8M against 2.6M; $2.14 against $1.95. Too few events in 60 minutes to call a harm; no sign of a gain. Side finding: the newcomer's know-how "mending" (the seed's newcomer kit) is the `heal` skill's knowledge of mending wounds, not a technique the rules can teach ("there is no technique called mending"), and every newcomer pitched itself as a mender of hinges and tools on that word. | **drop** as a lever for help; `iter-8` (a30e21e) stays pushed |
| 8b | Iteration 8 on main 9be23e9, where residents are fed (`hunger-1`): with residents no longer starving, does knowing what they have turn their answers into acts? | `iter-8` rebased (`iter-8b`, 637b965); control: the trials tree on 9be23e9. | `s9`: the social preset on seeds 7 and 11, glm-flash, 120 min, control and change × 4 | **Not testable on this base: the newcomer no longer reaches the town.** On 9be23e9 it arrives 9–33 m outside the town's radius on seeds 7 and 11 too (on c0ff89d it arrived 18–20 m inside), and in 6 of 8 runs it never got inside or stayed under 5% of its samples; it saw 2–8 people in 120 minutes (29 in one run). Woken residents 0.8 (0–1) against 1.5 (0–4); asks heard 1.8 (0–3) against 3.5 (0–10); talk turns 0 against 1.5; no act toward the newcomer decided in either arm except one refused give, and nothing reached it. $1.88 against $2.16. The arrival rule is unchanged (outside the first town's first gate, `island.rs`); which town and gate come first changed with the island's authored lives. This is seed 13's problem now on every social seed, so the social preset needs an arrival inside the walls (or a newcomer that can find its way through the gate) before any resident-answer lever can be read. | **open**: blocked on the arrival |
| 8c | Iteration 8 on main 9c9db36 (`arrival-1`: the newcomer arrives on the first town's square; `rules-2`: agreements, demands, regard, skills declared in the script). `rules-2` lists a conversation turn's acts from the skills' specs but leaves out `host` because `talk_acts()`'s `SHOWN` says the turn's examples show it, and they do not: on main a resident in conversation is never offered `host`. | `iter-8` rebased (`iter-8c`, a61b11a): the pack, know-how and home lines and the `host` example. Control: the trials tree's mind on 9c9db36, run as its own binary (a shared target dir had left the change's binary as the default; checked by the prompt text in each binary). | `s10`: the social preset on seeds 7, 11, 13 (one each), glm-flash, 120 min, control and change × 3 (`social_report.py s10`) | Arrival fixed: every newcomer arrived 73–91 m inside the town's radius and stayed inside (81–100% of samples), sighting 126–203 people. Woken 7.7 (7–8) against 8.7 (7–10); asks heard 10.0 (7–16) against 12.0 (7–19); talk turns 19 against 32 (all of the change's with the new lines). **First `host` of any social run, in the change arm:** Edwin Marsh, in a talk turn, "This isn't the inn, Arlen — it's my own hearth … Come in and warm yourself till dawn" (`iter8c-r3`, minute 80; lodging received). Control: no host. Gives decided toward the newcomer 7 against 3; food received 6 gifts in one control run (cooked meat and berries, `ctl-r3`), 0, 0 against 1, 0, 0. No lesson and no demand in either arm. Agreements: the newcomer proposed terms 3 times against 2, a resident proposed once (control: 5 wood for 5 fish, lapsed). Two of the change arm's agreements were accepted (the Reeve accepted Arlen's terms in `iter8c-r2`) and both lapsed at dusk unfulfilled, two game hours (about 2 real minutes) later. Both times the newcomer wrote its terms backwards: it offered "a night's lodging" itself and asked for 1 `wound_tending` or 6 wood, when it meant to work for a bed. **3 of 6 newcomers starved** (minutes 92–95: control r1, change r1 and r2). Every newcomer reached hunger 100. The survivors ate from stores, fish or gifts; the three that died never took from a store and gathered 12–16 berries, failing on "no nearest berry_bush in sight" inside the town. $6.27 against $6.69. n = 3 with three deaths: one host is not an effect. | **open**; the `host` example is a fix to main's `SHOWN` list whatever the lever shows |
| fix | Two defects found by 8c, fixed as their own branches and merged. | `fix-host-example` (397505c, merged 378594d): the `host` example the talk turn's `TALK_SHOWN` assumed, a unit test that every shown name is in the examples, and a verify-minds check of the recorded talk request. `fix-agreement-terms` (a333807, merged 6c8d100): an agreement falls due at the first dusk at least `agreement_min_h` (12) game hours away, told "by dusk today" or "by dusk tomorrow"; `offer_terms`/`accept` say which side gives what. | Replay of the real `offer_terms` decisions on glm-flash with the old and new descriptions (`replay-terms/`, 38 calls, 292k tokens) | The skill line renders `offer_terms(target, item: lodging, …)` (the spec's accepted words), which reads as "put lodging in item". `iter8c-r2`'s bed-for-wound-tending decision: old wording backwards 4 of 5, right 1; new wording right 5 of 5. `iter8c-r3`'s fire-teaching-for-wood decision: old 0 of 5 proposed terms (all taught instead), new 1 of 5, the right way round (fire for 6 wood). The three control talk turns proposed no terms with either wording. The verify-core dealings scene passed all 15 checks. | **merged** |
| 9 | Newcomers starve on the square (3 of 6 in `s10`). Diagnosis from the three deaths: they knew where food was (4–10 named berry places, 0–9 m from real bushes) but all inside the walls, where the few bushes were stripped (residents forage them; nothing regrows in winter, minutes 68.5–92.5, and all three died at 92–95). No store refused them (taking from a store is not checked for its owner); they never found one: 0–3 store sightings in 90 minutes in a town with 17, with an 11-tile sight in a town about 120 m across. They never tried to leave (closest 40–70 m inside the edge); the three survivors went out 29–141 m past it, or took from stores. Residents were asked (2–6 heard food asks per run); one gift of 2 berries in three runs. Their most frequent failure: `gather`/`take` on the nearest bush or store, "not in sight". | That failure says how far one sees: "(you see about 11 tiles by day; nothing of that kind is that close)" (`iter-9`, e232dc3, `acts.rs`). Both arms main 9c9db36's module except this, main's rules and mind. | `i9`: the social preset on seeds 7, 11, 13 (each twice), glm-flash, 120 min, control and change × 6 (`starve_report.py i9`) | **No gain.** Starved: control 5 of 6 (at 33–91 min), change 6 of 6 (45–95 min). The mechanism ran (9.7 such failures per change run, all with the new words; none in the control). Time outside the walls 2% against 0%; the farthest any change newcomer got was 26 m inside the edge; store takes 1.3 against 2.0; gathers 9.8 against 6.7; food given 0 against 4 (in two runs). Mean death 57 against 76 min, within the spread. **Spread note:** the controls of `s10` and `i9` ran the same module, rules and arrival, and starved 1 of 3 and 5 of 6; in `i9` most newcomers spent early turns on unparsable `{"do": "say"}` acts and talk and gathered nothing in their first 30 minutes. So starvation on the square is dominated by what the newcomer's mind does first, and n = 6 cannot resolve a small lever. $5.7 against $7.9. | **drop**; `iter-9` stays pushed. Main 445db098 changes food (`fix-rules-small`: food by nutrition) and compile prompts (`fix-mind-small`), so the starvation rate is remeasured in the new baseline |
| 10 | Newcomers on the square never learn where the town ends: all 9 six-hour lives on 445db098 starved inside the walls (`l6`), searching for the nearest bush or tree where none is in sight. | Inside a settlement, the scene's `you` says how big it is and which way its nearest edge lies ("inside a town about 239 m across; its nearest edge is about 93 m southwest") (`iter-10`, f6431cd, `perceive.rs`, from 445db098). Both arms 445db098's mind and rules; the module differs by this line. | `i10`: `life` on island seeds 7, 11, 13 (each twice), glm-flash, 120 min, control and change × 6 (`starve_report.py i10`) | The line reached only the change arm's prompts. Survived 120 minutes: control 2 of 6 (3 starved at 84–98 min, 1 killed by a wolf at minute 51, 350 m east of the town), change 4 of 6 (2 starved, at 93 and 104 min). Meals 10.2 against 14.3, gathers 18.8 against 23.2, store takes 2.8 against 2.2. **Not by leaving town:** time outside the walls 4% against 1%; the farthest any change newcomer got was 6 m past the edge (control 43 m). $1.42 against $1.48. Measured on the old hunger rates; main cb5214b7 (`lives-2`) makes survival secondary (hunger 48 per game day, starvation a full game day after hunger 50), and lives-2 measured no starvation with every person a mind. | **not kept** as a starvation lever (a weak, unexplained gain at n = 6 on rates main no longer has); `iter-10` stays pushed for an orientation test on the new main if lives there show the same confinement |
| 11 | **Survival is not secondary in real time.** A game day is 12 real minutes; lives-2 set hunger in game-day terms (48 a game day), still 4 a minute: a meal every 5 real minutes, and a newcomer with 4 berries starves within the hour (`l8`: 4 of 9 six-hour lives on cb5214b7 starved at 55–64 min). The owner and the minds' calls live in real minutes. | One law, `person_pace` (0.3), scales every per-minute need rate of people: hunger (1.2 a minute, a meal every 16–17 real minutes; starving 42 minutes after hungry), energy falling and recovering, and the starving, healing, spent, wet and cold drains; animals keep their rates; day length and births unchanged (`iter-11`, 5a77537, `skills.rhai` only). Base **e6b7e698**. | `i11`: `life` and `life-pressure` on e6b7e698, glm-flash, 120 min, 4 + 4 per arm against a shared control (`life_share.py i11`, `starve_report.py i11`) | **Clearly better.** Starved: control 3 of 8 (58–83 min), change **0 of 8**. Share of plans not about food or warmth 15% (2–33%) against **28% (8–57%)**; of decided acts (walks left out) 42% against **64%**; lines said 38 against 72; people spoken to 12.8 against 15.9; meals 7.9 against 3.3; highest hunger 93 against 65. The freed time went to people: speech 228, waves 113, nods 10 (control 74, 43); plans such as "Greet the morning crowd at the market corner and trade names with whoever stops" and "Walk the quiet streets at dawn to learn Brackenford's shapes". Nothing was learned or built in two hours in any arm, and trades stay rare (1.25 per run against 0.5). Cost per hour $0.14 against $0.12 (more thinking, since the mind is not cut short). For reference, last night's six-hour lives that survived spent 2–7% of their plans on anything but food or warmth. | **keep**: `iter-11` for the owner, with the day-length decision (docs/SMALL_CITY.md) |
| 10b | Iteration 10 on e6b7e698 (rebased, 6d1b9ae). | As 10. | `i11`, the third arm, same control | Starved 3 of 8, as the control (later: 90 against 68 min); plans not about food or warmth 23%; lines 47. No effect on starvation. | **drop** |

Candidates not run tonight, for later:
- **Newcomers starve on the square** (`s10`, main 9c9db36): arriving inside the town, 3 of 6 starved by minute 95; the town's interior has no bush in sight, and only those who took from a store or were given food lived.
- **Agreements in a 12-minute day:** "by dusk" leaves 0–6 real minutes, and both accepted agreements in `s10` lapsed within about 2 minutes, before anyone could deliver.
- **`offer_terms` written backwards:** the newcomer put "a night's lodging" on its own side in both proposals it made for a bed. Whether the act's description says plainly which side is which is the first thing to check.
- **The wolves on main 9c9db36 with no minds** (`eco10`, 120 min): 4 of 10 alive, 5 starved, 1 killed by a person; 5 deer killed by wolves (on 9be23e9: 1 alive, 9 starved, 2 deer). Better, not solved.
- **Unheard asks:** half of the newcomer's asks went to people out of earshot. Whether its scene says who is within earshot is the question.
- **Seed 13's arrival** outside the walls, with the gate unreachable as a named place.
- **"mending" means two things.** The newcomer kit's know-how `mending` is the `heal` skill's wound-mending, not a teachable technique; models read it as mending tools and hinges and built every newcomer's pitch on it. A seed and rules question (name it for what it does, or make it a technique), not a mind one. **Renamed `wound_tending` on `rules-2`;** in replays of the eight `i8` identity requests, narratives that read it as mending things fell from 19 of 24 to 1 of 24 ([world rules](WORLD_RULES.md#mending-is-now-wound_tending)).
- **Work for keep is agreed in words only.** Residents in `i8` offered bed and food for work ("woodpile at my store by dark"); nothing in the rules records a job or tells the resident that the wood was stacked, so the deal rests on each side noticing. Whether residents see the result (a store's contents, a pile) when they next look is the thing to check before adding anything. **On `rules-2`** agreements are records whose deliveries (a give, a store into the other's household store, a night's lodging) the rules count and tell; see [world rules](WORLD_RULES.md) and the `r2` batch there.
- **Re-reading loops** (a plan to "read both signs" re-read the nearest sign 57 times): a check refusing to re-read needs the sign's topic in what Rhai sees of a target, an engine change.
- Several earlier candidates are covered by `feedback-1` (merged to main during the night): structures noticed once, ids resolving only to things in sight, gone things weakening memory, wants following the life lived.

## The player frame (experiment, 2026-11-11)

**Hypothesis** (from the owner's play-test: the characters feel like NPCs, not like players run by AI). A model told it is *playing* this person in an open-ended living world, free to choose what to pursue as a human player would, lives with more initiative, exploration and long-range aims, while what the person says and does stays in character.

**Switch.** `LIVING_FRAME=player` in the mind service (`living/mind/src/prompts.rs`, `Frame`); the default `character` leaves every prompt byte-identical to before (all 26 exported prompt fixtures compared byte for byte before and after the change; test `character_frame_is_the_default_and_unchanged`). A value that is neither stops the service at start. Under `player`, four system prompts of a person replace their opening sentence ("You are the mind of the person described under # Who you are, living in a persistent simulated world.", and the consolidation and talk equivalents) with this frame and a one-line role:

> You are an AI playing the person described under # Who you are, in a persistent world shared with other players, human and AI. For you, as for every player, the person's body, needs and death are real, and the world's rules hold. What you pursue in this life is your own choice. Whatever the person says or writes is in their own words, inside the world: never speak out of character.

| Prompt | Role line after the frame |
| --- | --- |
| think (the decision) and deliberate (compiling it into acts and a graph) | Here you are that person's mind. |
| consolidate | Here you are that person's memory and self-understanding, kept in their own terms. |
| talk (a conversation turn) | Here you are that person, face to face with the other person described below. |

With `LIVING_PROJECTS=1` as well, each switch does what it does alone: the frame replaces only the opening sentence, and the projects text, the `serves` field and the `# Your projects` section stay as projects has them (test `player_frame_and_projects_compose`). Nothing else changes (test `player_frame_changes_only_the_opening`): the rules, grammar, reply shapes and every user message are the same, and the frame is part of the shared, cacheable prefix. Not framed: animals' prompts, starting identities (`identity_system`, `birth_identity_system`), sleep's reorganization and player memory (`internalize_system`, for characters people play). The frame names no goals or activities, gives no advice and does not rank survival (test `player_frame_is_short_and_prescribes_nothing`).

**Measuring.** Variant `player-frame` (`LIVING_FRAME=player`, otherwise `default`). Every summary now carries:

- `prompt_frame`: per purpose, how many of the subject's journaled requests opened with the player frame (`player 12/12`, or `character 0/12`), read from the journal's stored system prompts;
- `out_of_character` (`ooc_lines`, `ooc_private` in the report): [`ooc.py`](../living/tools/ooc.py), a word list (player, game, AI, NPC, prompt, simulation, "my character", role-play, respawn, XP, logging in, online, …; hunting "game" is not counted), over the lines the subject spoke or wrote (chronicle `speech` and `write` rows) and, separately, over its replies' private fields (thoughts, intentions, consolidation summaries and gists, identity narrative, goals and values). A word list over-counts and misses paraphrase: read the examples kept with each count (`python3 living/tools/ooc.py .local/living/trials/<batch>`).

Initiative, exploration and long-range aims are read with the existing probes and life timelines (distance ranged, places named, techniques learned, structures built, graph plans, goals in persona revisions), side by side across replicates.

```bash
python3 living/tools/trials.py run --batch <b> life --variants default,player-frame --replicates 3
python3 living/tools/ooc.py .local/living/trials/<b>
```

**Fake-model proof** (`pf1`, 2026-11-11, DGX Spark, from a worktree of `exp-player-frame`; `life` × `default`, `player-frame` × 1, 10 minutes, `--fake`, no model spend). Both arms ran the full 10 minutes (20 and 19 calls). `prompt_frame`: default `think 0/7, deliberate 0/7, consolidate 0/6` framed; player-frame `think 7/7, deliberate 7/7, consolidate 4/5`, the fifth being the starting identity, which is not framed. In the journals each arm has one distinct system prompt per purpose; replacing the player arm's opening (frame and role line) with the old first sentence gives the default arm's prompt exactly, for think, deliberate and consolidate. No talk turn happened in either arm (nobody addressed the newcomer), so talk is proven by `verify_minds.py --case frame`. `ooc_lines` 0/1 and `ooc_private` 0/34 and 0/33: the fake model's canned lines, which say nothing about real models. Evidence: `.local/living/trials/pf1/` (`report.md`, `frame-check.txt`, each instance's `summary.json` and `journal/`); databases and Neo4j minds cleaned.

**Not established:** whether the frame changes what real minds do, or how often they break character. That needs a real batch (paid; the coordinator runs it).

## Arenas: R2 against scripted opponents (2026-11-12)

[Combat mind](COMBAT_MIND.md) §4 and §5, run R2: does a mind's fighting change within one fight after it has seen the opponent's pattern, with the existing machinery only (no new mind code)? Branch `arena-r2`, cut from origin/main `5d5ce4e1`.

**Build and switches.** The trial module and `living-mind` were built from `5d5ce4e1` (private `CARGO_TARGET_DIR`, the trial service `slop-trials-stdb`, island seed). In force: stamina-1 (12d96e66), the two combat facts (`force_outcomes` on, 94baa708; `LIVING_SKILL_TIMINGS` on, ccafb3e4), the attack's timing in the COMBAT law from the skill cards (5b18c74f), look-2 (`look_walk_deg` 75), fix-dealings. `fov_on` is the shipped default, off: facing sight is a law on main that this world does not turn on. Models: the `default` variant (glm-flash, overflow deepseek-flash). Every guard of the runner applies (the laws guard, the runaway and outage watchdogs, the protected containers; nothing touches `verify-trial-bi1-*`).

**The fixtures** (trial files only; nothing is shipped or installed into a character): a picked adult resident, `foe`, whose graph the trial sets one minute after the start, 6 m from the subject.
- `arena-heavy`: the spear `attack` (the slowest, hardest melee move a person has under stamina-1: a 750 ms windup the target sees, 9 damage, against `strike`'s 350 ms and 8), then a pause of 2 or 3 s (`chance`), again and again. The answer that fits: out of reach or a dodge during the windup, a blow in the pause.
- `arena-kiter`: a bow shot whenever it sees the subject (300 ms windup, 7 damage), running off whenever the subject comes within 6 m, following when it has lost sight. The answer that fits: shoot back, break its sight, or close through cover or a dodge.
- Subject: a spawned newcomer (the wolves trial's traveller sheet, no word about fighting), on its instinct graph, with the newcomer's kit and a spear; its mind the only one thinking. 10 minutes from 10:00 (day sight), a 700,000-token cap per instance.

**Runner and tools.** `record.uses` (new, generic): every skill use by the subject and the cast, written again as its outcome settles, to `uses.jsonl`. [`arena_report.py`](../living/tools/arena_report.py) reads the evidence: exposures (the heavy blows aimed at the subject; the arrows loosed at it), answered or not by their outcome, the defence in the windup and the counter in the pause, K (the first exposure after which three in a row were answered), the mind's revisions and words between exposures, its own outcome lines and timings used, spoken lines that carry an internal id (`#123`), calls, latency and cost.

**Free dry run `r2f`** (`--fake`, one replicate each): both fixtures run as written. The heavy foe's blows landed "hit for 9"; the subject's instinct struck back with its own `attack` and killed the foe at 169 s, 6 heavy blows in (its line: "You finished: attack → person. killed Agnes Fenner (9)", see the defect below). The kiter loosed 12 arrows in reach of the subject, many more broken off as it fled; the subject closed within 6 m three times. No spoken line carried an id (0 of 2). A fake mind decides nothing, so these runs show the setup, not behaviour.

**The first paid attempt `r2` did not run**: this session had no model key and stopped at the mind's start; nothing was spent. **R2 ran as `r2b`** (2026-11-12, 04:12–04:23), built from `arena-r2` at `07a1de10` (origin/main `ec5561f1`, fix-kill-name in), 5 replicates per fixture, the `default` variant, `fov_on` off (the shipped default), the key loaded from a copied `.env` (deleted after; a scan of the batch for every key, whole and by its first and last 12 characters, found 0 matches in 410 files). Evidence: `.local/living/trials/r2b/` (`arena_report.json`, `report.md`) on the Spark.

### R2 results (`r2b`, 10 fights, $0.40)

**Main measure: within one fight, does behaviour change after the pattern is seen, after how many exposures, and does the change fit?**

| | Heavy blow (5) | Kiter (5) |
|---|---|---|
| Exposures per fight | 4, 0, 5, 1, 2 (12) | 10, 13, 5, 4, 16 (48) |
| Answered (did not land in full) | **0 of 12** | **5 of 48**: 0 of 15 in the first three, 5 of 33 after |
| K (three answered in a row) | never | never |
| Defence in the windup (dodge, guard) | 0 of 12 | blocks and dodges used (18 guards in one fight, 18 dodges in another), arrows still struck |
| Counter in the opponent's pause | 9 of 12, **from the first exposure** | return fire 3 shots in 3 fights (2 hit); closed within 6 m 1–6 times a fight |
| End | the subject killed the fixture in 3 (after 4, 5 and 2 heavies); 2 were no fight (below) | all survived (lowest health 15–82) |

- **No body-level change that fits the pattern, in either arena.** Against the heavy blow the subject traded blows in the pause from the first exposure; that is its seeded reflex ("hurt: attack the attacker"), not something learned, and it won. Against the kiter, the share of arrows answered stayed near zero throughout.
- **The minds named the pattern in words, late.** Heavy: by the third or fourth exposure in 3 of 4 fights ("at my arm again mid-swing", "give ground, let their blow miss, then hit back", "slip #9's swing", "I've traded blows with him before and come off better each time"). Kiter: in 5 of 5 ("keep my distance, ready my bow", "put an arrow in them if they close the distance", "break away, put distance between us"). One kiter's subject read arrows as blows ("already swinging", "struck me from behind"): an arrow is told as "A stranger attacked you (7 damage)", which does not say it was an arrow (the gap COMBAT_MIND §3.2 names).
- **The answer reached the plans, not the body in time.** Compiled plans held `dodge` in 3 of 5 heavy fights and 4 of 5 kiter fights, `threatened` conditions in 3 and 4, a bow shot in 3 kiter fights, a `combat` patch in 2; but they were installed around the third or fourth exposure, and the heavy fights ended within one or two more. Revisions in the fights: 4–10 deliberations each.
- **Fixture faults (heavy):** two of five heavy runs had no fight worth measuring. In one the subject stood 11–12 m off, past day sight, and the fixture's `attack` cannot start on someone it does not see; its graph has no approach. In another it stayed 60 m away after its placement. And the fixture loses to the subject's reflex in 2–5 exposures. A rerun needs a fixture that follows when it cannot see the subject and lasts long enough for a pattern to be learned (leather armor, the 0.65 the rules give, is a fixture's gear, not a rule change).
- **Fixture fix (branch `arena-heavy-fix`, 2026-11-12; trial files and the runner only).** *Approach:* a timeline trigger `near {who: foe, of: subject, beyond: 5, for_s: 4}` (night sight is 6 m; the fixture's pause is at most 3 s, so a subject stepping back in the pause is not followed early) sets the foe's graph to walk to where the subject stands (`$subject_xy`, read when it fires) and fight again; within 5 m `attack` closes in by itself. *Lasting:* in the pause, below 70 health, the foe mends its own wounds with the ordinary `heal` (given `wound_tending` at the start) and then waits 1.5 or 2.5 s, so the pause stays 2–3 s; no armor. Free dry runs (`--fake`, 6 minutes): `r2hf` (2 fights) and `r2hf2` (scratch copies of the fixture, not kept: started 12 m off, past day sight, and without armor). Started 12.3 m off, the foe waited about 8 s and walked in (9.7, 4.5, 1.2 m). The foe now outlasts the fake-minded subject's reflex: it healed 2–5 times and killed the subject at 3.6–4.1 minutes, after 12–14 heavy blows (before the fix, the reflex killed the foe at 169 s, 6 blows in). A subject that does not answer the pattern now dies of it.

**What the minds did with the real timings and outcomes.** No reply cited a timing (no "ms", "winds up", "ready again" in any think or compile reply): the timing lines went unused. Outcome lines were told (heavy 0–14 a fight, kiter 0–20) and used in words ("come off better each time", "they're barely standing"), not as numbers.

**Spoken ids.** 0 of 66 spoken lines carried an internal id (`#123`). Ids appear in the minds' thoughts ("#9"), their handle for the scene, as allowed.

**Cost and latency.** $0.40 for the batch (glm-flash $0.09, deepseek-flash $0.31; 355 calls, 1.86 M tokens); per 10-minute fight $0.027–0.053 (mean $0.040), 20–42 calls; think and compile p50 5.5–5.8 s per call. GLM's consolidation failed 23 of 30 calls (retried on DeepSeek), a reliability note for the default mix, not a cost.

**Defect found (3.1, `force_outcomes`).** A melee kill is told to the killer with the victim's real name: "You finished: attack → person. killed Agnes Fenner (9)", where the killer knew her only as a stranger. The line's words are `act::damage`'s result, which names the victim by `common::display`; a missile's kill avoids it (`act::Far::Killed`, "struck a stranger and killed them"), a blow that resolves at its release does not. Before `force_outcomes` this reached minds only for `attack` (a notable skill); now it reaches every striker, players included. The fix is to tell a kill in the maker's terms (`label_for`) in `act.rs` `report`; not made here.

### What the told outcome lines cost in a battle

[`outcome_cost.py`](../living/tools/outcome_cost.py) on a scratch `verify-core` world (`core-r2cost-025725`, default seed, 186–188 people alive): 20 minded spear fighters (`spawn_crowd(20, true)`: held like a mind's, so their outcomes are told), packed 1.5 m apart, striking the nearest person, timed by `bench.py` (profiled tick spans, no subscribers) over a 22 s window per arm, each arm a fresh battle; the fighters' new experience rows were read during the window, so the lines of those who died count.

| | `force_outcomes` on | off |
|---|---:|---:|
| Blows a second (hits, dodged, blocked) | 9.2 | 8.9 |
| Told strike lines a second (done + failed) | 14.4 (10.6 + 3.8) | 3.8 (failed only) |
| `act_outcome` rows | 0 | 0 |
| Tick p50 / p95 / p99 / max (ms) | 1.68 / 3.60 / 5.58 / 7.21 | 1.72 / 3.40 / 5.12 / 6.59 |
| `tick.combat` work (ms a second) | 8.29 | 8.23 |
| `tick.activity` work (ms a second) | 3.89 | 3.81 |

- The law adds one experience row per resolved blow: about 10.6 rows a second here, written to the striker only. The failures (3.8 a second) are told either way; each fighter's repeated refusals ("not ready", "out of breath") are each told once (the `repeat_failure_s` window).
- The tick does not show it: the differences between the arms (p99 5.6 against 5.1 ms, 0.06 ms a second of combat work) are within one battle's variation. **At 20 fighters it is not material.** A minded fighter's rows go when its mind integrates them; minded fighters with no mind service here kept theirs in the experience window.
- `act_outcome` rows are written only for a character a person plays (`outcomes::write`): none here. A player's character gets one per told line, kept with the newest 64 lines (`frame::LINES_SHOWN`).
- A first run (`core-r2cost-025417`, 30 s windows) counted lines by snapshot and came out negative (a dead character's experience rows go with it) and ran past the battle's end; it is not used.

## What still special-cases trials (to remove later)

No engine code knows about trials. The authority gained one generic admin-only scene reducer, `spawn_newcomer` (a player's `join`, thought for by the minds). Everything else a trial sets up uses existing admin scene reducers, `mind_say`/`mind_act` for admin-controlled characters, behaviour graphs with the existing skills (the ladder's scribe is a graph plus the ordinary `teach` act), the player reducers (the human session) and the real presence path (the takeover). What the runner itself still hard-codes:

- **The human session's script** lives in `trials.py` (`Player.session`: walk to the town, forage, meet residents and state a plan, gather wood, build a campfire, leave). It should be a list of player steps in the trial file, like the timeline.
- **Trial-specific probes by name** in `trial_evidence.py --table`: the teacher, theft, wolves and hungry columns match trial-name prefixes and role names (`thief`, `pack`, `cloak`). They should come from each trial's `probes` field.
- **Generic probes with assumptions:** `FOOD` (the edible items) is a constant instead of coming from `skills.rhai`; `fled_m` measures movement after a `place` step; the 12-minute day is the fallback when a summary lacks `day_ms`; settlement names come from residents' backgrounds.
- **Subject setup heuristics:** a picked person (not spawned or joined) is "repurposed": its items are dropped and its routines cleared. A trial can override this with `clear_items` and `clear_routines`.
- **Merge rules for `extends`:** `pick`, `graph`, `sheet`, `rules`, `to`, `act` and `items` replace instead of merging (`REPLACE` in `trials.py`).

## Notes for the mind-harness lab

- **Models per purpose and per species.** A variant's `models` value is deep-merged into `living/configs/models.json` as given, or `models_file` names a whole file. Whatever keys the config grows (for example per-purpose mixes for people), a variant can carry them unchanged. Today `species` routes animals per purpose (`think`, `remember`, `compile`), proven in the fake run `dry8`: wolves impulse with `ministral-8b` and compile and consolidate with `ministral-14b`. **People have one profile for every purpose**: assign, rotate, groups, stages and the default all choose one profile. Per-purpose mixes for people need a change in the mind service (`llm.rs` profile choice), not in the runner. The current variants are single-profile for people.
- **Summaries per purpose × model** (`by_purpose_model` in `summary.json`, and the batch report's table): calls, tokens, prompt and completion tokens, cached tokens, latency p50 and p95, failed calls, empty replies (no text, e.g. reasoning that used up `max_tokens`), replies that would need repair, unparseable replies, the profiles that served them (overflow shows as another profile), estimated cost; and per instance, deliberation retries, pruned graphs and rejections from the thought rows. The journal does not record whether the mind repaired a reply (repair happens after journaling); the summary re-checks each reply. An animal's impulse is journaled with purpose `deliberate`, so a wolf's impulse and compile appear as one purpose under two models.
- **Animals with minds.** `subject.pick` with `kind: wolf` and `count: 4` makes the pack the subject (`LIVING_ONLY` names all four; samples follow the first). This needs a `minds: true` world, where seeded animals are thought for by the admin's minds, as in [`pack-mind.json`](../living/trials/pack-mind.json). The authority asks an animal's mind only while a person is within 25 tiles, so a pack far from people never thinks. A trial must keep people near it, or that rule must move to the shared notion of stage (LIVING_CORE.md, "Minds at scale").

## SpacetimeDB documentation checked (2026-11-09)

The pinned version is 2.14.1 (`living/Cargo.toml`, server image `v2.14.1`). The live documentation's version selector shows 2.0.0 (and 1.12.0); there is no 2.14 entry, so what the pages say was checked against the running 2.14.1 server where it mattered.

| Page | What it says | What follows here |
| --- | --- | --- |
| [Databases](https://spacetimedb.com/docs/databases/) | "You can deploy the same module to multiple databases … each with its own independent data"; `spacetime delete` deletes "a database and all its data". | One server, one database per trial instance, each deleted after its evidence is collected. The pages do not say how many databases a server can host or whether deleted data leaves files behind; the Spark's disk is watched instead. |
| [HTTP database API](https://spacetimedb.com/docs/http/database) | `POST /v1/database/:name_or_identity/call/:reducer` takes "a JSON array of arguments"; `POST …/sql` takes "SQL queries, separated by `;`"; a token is "Bearer auth"; anonymous SQL "will only have access to public tables". | The runner calls reducers and reads rows over HTTP with the admin token. **The 2.14.1 server refuses more than one statement per request** ("Multiple SQL statements are not supported"), so the sampler sends one query per request and reads the slow-changing tables every fifth sample. |
| [Reducers](https://spacetimedb.com/docs/functions/reducers/) | Reducers are isolated: "Reducers don't see changes from other concurrent reducers", and the server "reserves the right to execute multiple reducers concurrently". | Each scripted step is its own transaction; steps that depend on an earlier one (place, then read the body) wait for its HTTP reply. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | "keep subscriptions small"; overlapping queries make the server "process each row … twice". | The runner adds no subscriptions; it polls a handful of indexed rows (`id`, `actor`, `owner`, `observer` filters) every 2 s. The mind's own subscriptions are unchanged. |
| [Tables](https://spacetimedb.com/docs/tables/), [performance](https://spacetimedb.com/docs/tables/performance/) | Private tables "Don't consume client bandwidth"; organise by access pattern. | No table or reducer was added. Private rows (`skill_use`, `deliberation`) are read with the admin token at the end of a run only. |
| [Self-hosting](https://spacetimedb.com/docs/how-to/deploy/self-hosting); [Docker Hub tags](https://hub.docker.com/r/clockworklabs/spacetime/tags) | Standalone server, `start --listen-addr`; tag `v2.14.1` is published for `linux/amd64` and `linux/arm64`. | The trial container runs the official arm64 image on its own port and volume. |

Data paths a trial adds, per instance: one database (island: 287 characters, about 68,000 resource nodes); one mind subscription set as in the labs; with `minds: true` every seeded character writes percepts into `experience` (bounded at 400 rows each when no mind consumes them) and keeps one pending `deliberation` row; the runner's reads are indexed point lookups. Nothing is retained after `clean` except the evidence directory.

## Open-ended life runs and world presets

A life trial (`"kind": "life"`, [`life.json`](../living/trials/life.json)) has no timeline. One mind-backed newcomer lives in the island world for `minutes` (360: six hours, 30 game days at the 12-minute day). Every other character has a mind (since 2026-11-11 every person does), but the trial's mind service thinks only for the subject (`LIVING_ONLY`), so the residents live on their starting ways: the island as shipped, with town life layer 1 (daily rhythm, gestures, weather, the wolves of the town road, guards). Before 2026-11-11 they were instinct-only residents (`rules.minds` false); the runs below that say so were made then. `life-social` now sets `minds.only: "all"`, so its service thinks for every resident.

- **The newcomer** is made by `spawn_newcomer(name)`, an admin-only reducer added for this (the only authority change; [lib.rs](../living/authority/src/lib.rs)). It does what a player's `join` does (the arrival point outside Brackenford's first gate, the seed's newcomer kit: a bow, 30 arrows, 4 berries; fire, fire_bolt, mending; the person instinct), but the character is controlled by the admin's minds (`ai`), so the mind service thinks for it. A player cannot call it (`admin only`, checked on the trial service). Its background says only `{"origin": "newcomer", "arrived": "today, on foot, by the road to Brackenford's gate"}`, so the mind writes an identity from it as it does for any resident with a background. The prompt carries no goal.
- **Death is permanent** and ends the run (the runner stops 20 s after). Nothing respawns.
- **Crash recovery.** The runner saves each instance's state (`state.json`: subject, cast, clock, cursors, the mind's pid and start time) every 30 s. A mind that exits is restarted (the world is not reset); `trials.py resume --batch <b>` reattaches after a runner crash, adopts minds that are still running and goes on from the saved clock. Five restarts within 30 minutes count as a runaway.
- **What is kept:** the journal, unchanged; an hourly snapshot (`snapshots/hNN.json`: position and the nearest settlement, vitals, inventory, know-how, practice, relations, judgments, places, persona, the current graph and routines, structures owned, and the subject's 60 most recent kept memories read from the trial Neo4j); the samples and rows as for any trial. `trials.py life --batch <b>` writes `timeline.md` from those rows without model calls: firsts (meal, fight, conversation, craft, build, sleep, gathering, own campfire or shelter), deaths seen, where the subject was over time, what it learned and from where, every graph revision with the skills and items it added and dropped, stretches of 10+ minutes within 15 m with no new graph, and loops (plans installed more than three times, lines repeated nearly word for word, turning back and forth).
- **Kept worlds.** A finished life run's database is paused (`set_paused`), not deleted. They are deleted only if the Spark's disk use passes 100 GB.

**Measurement, not caps.** Trials run with `LIVING_LLM_PER_MIN` off and no token cap (a trial file can still set `budget.tokens` or `budget.calls_per_min`). The runner counts calls and tokens per model, per purpose and per game day from the journal. A watchdog stops a run and records why when it shows a runaway: 30 failed calls in 5 minutes, the same failure 15 times in 5 minutes, more than 60 calls in a minute (only where one mind thinks: a `minds.only: "all"` world has no rate limit unless its `budget.runaway_calls_per_min` sets one, since a whole island of minds makes hundreds of calls a minute; the first two capped social runs on cb5214b7 were stopped by this rule after 30 s), or five mind restarts in 30 minutes. In a `minds.only: "all"` world the two failure rules count as a share of the calls in the 5 minutes (half, and 40% for the same failure; at 20%/10% the relaunched seed-11 run was stopped in its first minute by 20 identical 429s during the island's opening burst of memory calls), never below the one-mind counts: the second attempt was stopped at minute 10 by 32 failures among about 1,500 calls, all of them the provider's 429 "not enough capacity", which the mind retries.

### World presets

A preset is a life trial that extends `life` with a world: seed overrides and `prepare` steps, using only what seeds and admin scene reducers can already express. The progression has to come from the world's state and affordances. The prompt is what any character gets, and nothing steers decisions.

| Preset | World | Intended progression gradient |
| --- | --- | --- |
| [`life`](../living/trials/life.json) (control) | the island as shipped | whatever the island offers a newcomer: gardens and wild food, a walled town with unowned houses, a bold pack on the road, cold nights, seasons |
| [`life-ruin`](../living/trials/life-ruin.json): a place with history and a gated ladder | berry bushes at 40% (`resource_scale`); before the mind starts, a Brackenford resident given writing, fishing and smoking walks into the unowned house nearest the arrival point (about 20 m from it) and puts up two signs with the ordinary write skill ("This house kept nets on the river…", topic fishing; "Fish hung over smoke for a day keep through the winter.", topic smoking), then goes home | forage in a lean land → find the empty house and its signs → learn writing (experimenting with wood can reveal it; no newcomer has it) → read the signs: fishing, smoking → fish, smoke fish over a fire → food that keeps; the house is also a shelter |
| [`life-pressure`](../living/trials/life-pressure.json): a pressure | berry bushes at 30%; **since the wide batch** no pack on the arrival road and two bold packs (five and four) 120–250 m around the first village, Elmwick. In l2/l3 it kept the shipped road pack and added a pack of five 120–200 m from the arrival point; that version measured only the road (two of three died there) | arrive in a lean land → feed yourself where berries are scarce (the bow, fishing, trapping, the town's gardens and stores) → meet wolves when ranging toward the villages → safety (fire, shelter, the walled town) → a place that holds |

Measured: `resource_scale` thins the land's wild bushes but not the planted garden and field bushes. On the island, `life-ruin` has 12,158 berry bushes and `life-pressure` 9,219, against 18,216 in the control (67% and 51%, not 40% and 30%). `life-pressure` in l2/l3 had 15 wolves (6 + 4 + 5).

**Engine features presets would need and do not have** (listed, not built):
- a wolf range that grows over the days (packs have a fixed home; the runner could move them on a schedule, but that is a script, not a world);
- a scarcity knob per season or region (winter already stops regrowth; nothing makes one season or one place leaner);
- resources by region, for a richer, more dangerous frontier such as the unroaded eastern massif (`resource_scale` is global);
- residents who respond: instinct-only residents never teach, trade or answer a request, so a social hook (an ailing elder, a household short of a worker, a stall that needs goods) has no one to make it a hook; town life layer 1 answers gestures only;
- residents with minds beside the subject: that is a lab, and costs one mind each.

### Watching a run live

The trial service listens on the LAN: `http://192.168.1.103:3320` (container `slop-trials-stdb`, started with `TRIALS_STDB_BIND=0.0.0.0`). Life-run databases are `verify-trial-<batch>-life-<preset>-<variant>-r<k>`; `trials.py report --batch <batch>` lists them.

**A watcher needs the owner's token.** Since 2a64837 the authority builds with strict perception by default. Bodies, characters, vitals, experiences and inventories are private tables, readable only by the database owner or through a player's own `seen_*` and `my_*` views (docs/PERCEPTION.md). An anonymous connection sees only static world data, so a watcher cannot follow the main character without the owner's identity. The owner is the trial service's in-container CLI identity, the world admin, so **its token can also call every admin reducer on every trial database**. Keep it on your own machines. (The life runs l1–l3 ran on 378b2c1, before strict perception, when those tables were public.)

- Get the token: `ssh gooning@192.168.1.103 docker exec slop-trials-stdb spacetime login show --token`. It is printed after "Your auth token"; don't paste it into logs or chat.
- **Observer (read-only):** natively, `LIVING_TOKEN=<token> LIVING_SERVER=http://192.168.1.103:3320 LIVING_DB=<database> cargo run --manifest-path living/Cargo.toml --release -p living-viewer`. On the web, `just living-web` and then `http://127.0.0.1:8330/?server=http://192.168.1.103:3320&db=<database>#token=<token>`; the browser never sends the fragment to a server. The observer subscribes and calls no reducer.
- **Game client:** `LIVING_SERVER=http://192.168.1.103:3320 LIVING_DB=<database> cargo run --release --manifest-path living/Cargo.toml -p living-game` connects with its own player identity and always calls `join` when that identity has no living character. That adds a player newcomer to the trial world, whom the main character perceives, so it changes the run. As a player it sees only its own perception, not the main character's. The client has no spectator or owner mode, so it cannot watch a trial without changing it. A watch mode that follows a named character with the owner's token is UI work, not built.

## Resident inspector

`living/tools/inspector.py` answers "why did they do that?" for one run as a single static page: pick a resident and a moment, or a line someone said. It reads evidence only and makes no model calls. The page is one self-contained HTML file with its data embedded (gzip; it needs a browser with `DecompressionStream`). Open it from disk; no server is involved.

```bash
python3 living/tools/inspector.py .local/living/trials/<batch>/<instance> -o page.html   # a trial, finished or running
python3 living/tools/inspector.py .local/living/playtest-2 -o page.html                  # a play session's evidence folder
python3 living/tools/inspector.py RUN --who "Agnes Fenner,Avice Hollis" --since 600 --until 1200 -o page.html   # a large run, narrowed
```

**What it reads.** It reads everything it finds under the folder.
- Trials: `state.json` (the start `t0`), `cast.json`, `census.jsonl`, `chronicle.jsonl`, `speech.jsonl`, `experiences.jsonl`, `audience.jsonl`, `samples.jsonl`, `graphs.jsonl`, `mind_rows.jsonl`, `human.jsonl`, `events.jsonl`, `final.json`, `mind.log`, `mind-env.json`, and `journal/`. A running trial has not copied its journal yet, so the page reads the live one (`<LIVING_ROOT>/.local/living/journal/<LIVING_RUN>/`).
- Play sessions: `journal/` (or `session/journal/`), `mind.log` (or `session/run/mind.log`), and any world-table exports below the folder. These are either the CLI's text tables (`spacetime sql … > chronicle.txt`) or `verify.py sql --save` JSON lists.
  - Export at least `chronicle`, `character` (or `id, name, alive, died_ms, cause`) and `presence`.
  - Export `experience` for the player too. Residents' own experience rows are evicted past a 400-row window. What a resident perceived then comes from the experience lines their own requests show.
  - Tables are recognised by their columns; `--rows` adds files or folders kept elsewhere.

**Residents.** A timeline per character, filtered by lane, for the whole run, a time window ("around hh:mm:ss ± 90 s"), or the last 90 s of their life. Each row shows wall time, time since the start, and game time.
- *perceive*: experience rows, plus the percept lines of each request. Lines read from requests are marked ≈ and placed at the middle of their game minute (0.5 s in current worlds), on a game clock fitted from the requests' "Now" lines.
- *recall*: the "What comes to mind" and "Memories this brings back" sections of each request.
- *decide*: every model exchange, placed when it was queued. Click it for the timings (queued → sent → reply, queue wait, model latency), the "why now" section, the line being answered, the full request section by section, the system prompt and the reply.
- *graph*: what each deliberation installed (plan, acts, intent graph), and `brain` revisions where recorded.
- *body*: chronicle rows, census and sample activity, and the position, health and activity from each request's scene. It also shows what others saw the body do ("seen by …"), and the player's reducer calls.
- *talk*: lines said and heard. *log*: the mind log's lines naming them.

**Sources.** The files read, the fitted game clock, the mind's switches, and per purpose the model exchanges' queue wait (admission) against model time, as p50, p90 and max.

**Lines.** Every line said, merged from the chronicle, the speaker's `said` row, listeners' speech rows and requests, and the mind log. The chronicle keeps one row for a line repeated within 2 minutes; the speaker's `said` rows keep each one.
- Click a line for each hearer's fate: a talk turn (with its latency), an answer from a deliberation, parked behind a running deliberation (each release and re-park, and the turn that finally followed), a settled pair, or no turn.
- For "no turn" the page lists the gate's inputs as the evidence shows them (talk.rs `on_speech`): addressed or not (the line's `to`, the hearer's salience, or who stood within the 6 m `address_m` of the speaker), whether the hearer cares (their relation from the nearest request's "People you know"), an active or closed exchange, another exchange, and whether the line asks something.
- Below the hearers is the exchange around the line, from every side: the participants' lines, their talk turns and deliberations, and the mind log.

- The mind's draws are deterministic (talk.rs `draw(listener, at_ms)`). The page recomputes the remark draw and the overheard draw from the line's exact time and the hearer's sociability, as their requests show it. So "let the remark pass" is shown as a fact, not a guess, although the mind logs it at debug level only.
- A line said to someone who did not hear it is marked as such. The evidence is the line's audience row, the speaker's "No answer from …" percept, or the mind's "out of earshot" at the line. A player's character is never judged as a mind before the AI takes it over.

**What it cannot show.**
- Stamina and the off-stage hold are not recomputed. When a turn was due and none came, the page names them as the possible causes.
- Without `audience` rows or salience, whether a line said to no one was addressed is shown only where distances near the line are known. Otherwise the page says it is unknown.
- Hearers are those the evidence shows. Without `audience` rows, others in earshot may be missing.
- The verdicts follow main's gate and log lines, plus the `exp-greet` switches' log lines (drawn in, faced, alongside). The greet modes' own curiosity draw is not recomputed. A changed gate needs the page updated.
- Scene positions are dated at the request's queue time. A scene can be older than that, so distances from scenes more than 10 s from a line are not used for the address rule.

**How often its verdicts are right** (2026-11-11, after two review rounds' fixes).
- The sample: 60 turn/no-turn verdicts drawn at random (seeded) from gr1a, gr1b, gr1c and play-test 2. Every line the reviews had looked at was left out. 40 are on the scripted player's lines, 20 on residents' lines.
- Each verdict was checked against the raw speech and audience rows, the journal's requests and replies, `mind.log`, and a separate recomputation of the draw.
- Result: 0 of 60 wrong outcomes and 0 of 60 wrong reasons. The 95% Wilson interval is 0–6.0% overall and 0–8.8% for the player's lines (0 of 40).
- One reason could not be fully verified: "in another exchange", where the remark draw would also have refused.
- Two reasons were incomplete: a talk turn that came only after the line had been parked did not say so. This is fixed. A fresh sample of 12 such verdicts was all correct; two of them missed a release time, also fixed.
- The sample checks the page against the evidence. It cannot check what the evidence does not record, such as stamina or the off-stage hold.

### What it showed on the greeting batches `gr1a` and `gr1b` (2026-11-11, 18:15)

Coverage: the instances with evidence at 18:15. gr1a: control ×4, nearest-concurrent ×3 (r4 still running), nearest ×1 (r1–r3 failed). gr1b: curious ×4, facing ×2, park-concurrent ×1. Six instances failed between 16:58 and 17:00 with SQL timeouts against the trial service. `greet_report.py` gives answered shares and latencies; the inspector adds the following.

- **Many counted answers were not answers to the line.** A resident's line to the player within 60 s, which the table counts as an answer, was often caused by something else. Examples are a deliberation that began before the line, a delayed answer to an earlier line, or a resident repeating "your name?" because the scripted player never gives one. For lines to no one, the share not caused by the line was 6 of 8 in control, 4 of 19 in curious and 9 of 19 in facing. In control-r1, the "answer" to "Hello there!" 2.8 s later ("That's the whole of it, friend…") came from Wenna's deliberation about the earlier question on work.
- **The trial's model queue, not the model, sets the pace.** With `LIVING_CONCURRENCY=4` for 11 minds, the median queue wait was 6–13 s for think and deliberate calls (p90 up to 41 s) and 2–7 s for talk turns (p90 15–25 s, max 78 s). Model time was a median 0.8 s for talk and 5–6 s for deliberation. A deliberation counts as running from its prompt, so lines heard during its queue wait are parked. Play-test 2 ran with 192 and had queue waits under 0.2 s. Latency and parking results from these trials therefore do not carry over to play.
- **Parked lines are released and parked again at once.** A released line is often parked again in the same second, because the listener's next deliberation has already started. Some waited 74 s and got no turn (control-r1, Oren), and one was re-parked three times (curious-r1, Sefa). Under `LIVING_PARK=concurrent` such lines get their turn alongside instead ("parked alongside" 44 times in nearest-concurrent; addressees answered 19 of 20).
- **The script's addressed statements meet the remark draw.** "You look like you know this place well." and "That looks like hard work." ask nothing, so a resident who passes the gate can still let them pass. The recomputed draw refused 4 of 22 addressed lines in control.
- **The script addressed characters who are not minds.** Tobin is not in `LIVING_ONLY`: 2 of 22 addressed lines in control and 5 of 23 in curious went to him and could never be answered.
- **Hearers do not answer each other's turns.** With curious and nearest, one hearer is drawn in and the others' verdicts read "another took it": a line to no one draws one hearer.

The full result for all three gr1 batches and gr2 is the next section.

## Greeting batches gr1/gr2 (2026-11-11)

Paid runs of the greeting trial on branch `exp-greet`: the switches `LIVING_GREET` and `LIVING_PARK` ([COMMUNICATION.md §5](COMMUNICATION.md#5-how-minds-take-turns)), all off by default when these batches ran. `nearest` + `concurrent` is the default since (the override and acceptance are under Recommendation, below). The world is the [hamlet](#the-hamlet-a-small-world-where-everyone-thinks-2026-11-11): 12 people on Cullet's laws (speech carries 12 m), of whom 11 think (`LIVING_ONLY` leaves out the child Tobin), on the `people` model mix: talk turns and on-stage deliberation on deepseek-flash, everything else on glm-flash (gr2's journals: 1,607 and 2,304 calls). A scripted player joins and repeats a cycle for 25 minutes. It walks into a group and says a greeting to no one. 50 s later it says a line to the nearest resident within 12 m. It then stands among them for 150 s, saying nothing, while they talk. Six cycles make a run. The player never says its own name and never answers.

Evidence: the run checkout `~/dev/slop-runs-greet` (branch `runs-greet`, exp-greet 3383026 plus 709770a), `.local/living/trials/{gr1a,gr1b,gr1c,gr2}/`.

| Batch | Arms × replicates | Mind queue (`LIVING_CONCURRENCY`) | Instances kept |
| --- | --- | --- | --- |
| gr1a | control, nearest-concurrent, nearest × 4 | 4 for 11 minds | 9 of 12 (nearest r1–r3 failed) |
| gr1b | curious, facing, park-concurrent × 4 | 4 | 7 of 12 (facing r3–r4, park r1, r2, r4 failed) |
| gr1c | nearest, facing, park-concurrent × 3 (reruns) | 4 | 9 of 9 |
| gr2 | control, nearest-concurrent × 4 | **64** (`mind-env.json`) | 8 of 8 (finished 19:33) |

**Excluded instances.** Seven instances failed at publish or soon after. The trial service hit SQL and identity timeouts, and gr1b park r4 hit "Too many open files". Their `summary.json` says `stopped_by: error …`, and none has a `final.json`. They are left out of every figure here, not counted as unanswered.

**Method.** The headline counts an answer only when the [resident inspector](#resident-inspector) (main's `inspector.py`) attributes it to that very line. A hearer's fate must be a talk turn on the line that said something, an answer from the deliberation it was parked behind, or a parked line whose following turn answered this line, not a newer one. A deliberation that later saw the line and spoke to the player is not counted. Those are listed apart, 0–7 per arm. `greet_report.py` (exp-greet) gives the raw share for the same lines: any resident line to the player within 60 s and before the player's next line. Lines that went to Tobin are left out. Addressed questions and addressed statements are counted separately, because a statement can be let pass by the remark draw. A greeting is crowded when two or more characters stood within 6 m of the player (the audience row). Every greeting in these runs was crowded. The join was a script in the session's scratch space, not committed, that loads `inspector.Run` and `greet_report.run` per instance.

**The inspector's accuracy.** Its turn/no-turn verdicts were re-sampled at random (60 verdicts from gr1a–gr1c and play-test 2): 0 of 60 wrong, 95% interval 0–6.0% (0–8.8% for the player's 40 lines).
- The sample checks the page against the evidence. It does not cover what the evidence does not record: stamina, the off-stage hold, the greet modes' own reasons (curiosity draw, "free", "settled with"), which are not logged.
- gr2 was not in the sample, and parking is rare at concurrency 64.
- Classifying fates as answered is this report's own step, as is pairing an answer with its words (`spoken_after`). Both were checked by hand on the examples below, not sampled.

### Per arm: answers attributed to the line

gr1 pools gr1a, gr1b and gr1c by arm. **gr1 latency is queue-limited (concurrency 4).** Talk turns waited a median 0.7–12.8 s per run (p90 10–32 s) and deliberations 3.4–37 s, against a model time of 0.7–0.9 s for talk. gr2's queue wait was 0.0 s for every call (talk model time median 0.7–0.9 s, p90 1.2–4.0 s), so **gr2 latency is the figure for play**.

| Batch | Arm | Runs | Crowded greetings answered (inspector) | greet_report raw | Latency median / p90 | Answered by the nearest mind | Addressed questions answered | Addressed statements answered | Addressed, raw | Addressed latency median / p90 | Answered by the addressee | Addressed to Tobin (left out) |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| gr1 | control | 4 | **3/24** | 8/24 | 7.0 / 64.1 s | 1 of 3 | 9/10 | 6/10 | 16/20 | 4.3 / 57.6 s | 15 of 15 | 2 |
| gr1 | `nearest` | 4 | **17/24** | 14/24 | 3.0 / 57.0 s | 11 of 17 | 10/11 | 9/11 | 18/22 | 4.3 / 43.3 s | 19 of 19 | 2 |
| gr1 | `nearest` + `concurrent` | 4 | **17/24** | 17/24 | 3.0 / 5.4 s | 11 of 17 | 10/10 | 9/10 | 19/20 | 4.3 / 6.0 s | 19 of 19 | 0 |
| gr1 | `curious` | 4 | **15/24** | 17/24 | 1.7 / 9.0 s | 5 of 15 | 9/9 | 8/9 | 17/18 | 2.6 / 11.4 s | 17 of 17 | 5 |
| gr1 | `facing` | 5 | **17/30** | 22/30 | 1.7 / 3.4 s | 2 of 17 | 12/12 | 13/14 | 22/26 | 4.9 / 66.7 s | 25 of 25 | 2 |
| gr1 | `concurrent` only | 4 | **1/24** | 4/24 | 1.5 s (one) | 0 of 1 | 11/11 | 5/9 | 17/20 | 4.3 / 4.4 s | 16 of 16 | 2 |
| **gr2** | control | 4 | **2/24** | 11/24 | 3.4 / 3.8 s | 0 of 2 | 8/8 | 5/11 | 16/19 | 4.3 / 8.3 s | 13 of 13 | 2 |
| **gr2** | `nearest` + `concurrent` | 4 | **19/24** | 20/24 | **1.7 / 3.0 s** | 11 of 19 | 9/10 | 11/11 | 20/21 | **2.6 / 4.3 s** | 20 of 20 | 1 |

**Why the raw share differs.**
- In control it overstates: 9 of gr2 control's 11 raw answers and 6 of gr1's 8 were lines that nothing in the greeting caused. They were deliberations already under way, or catching up on an earlier greeting: "You hailed me on the road this morning. I'm Brisk Marrow…" (gr2 control-r4), and "Morning, neighbor — you greeted me earlier and I never gave it back" (gr2 nearest-concurrent-r3).
- Under `nearest` + `concurrent` the two agree: 17 = 17 in gr1, and gr2 differs by one.
- In gr1 the inspector also finds answers that the 60 s window misses. These are queue-delayed turns and deliberations at 57–123 s, which is why `nearest` (with parking left on `wait`) reaches 17 against a raw 14.

**Reading.**
1. **Control: a stranger's greeting to a group is almost never answered** (3/24, 2/24). The hearers' verdicts read "not addressed, and X does not care about Arlen (not among the people they know): nothing in the gate gives a turn". The control answers came only once a hearer had come to care about the player, through the shipped overheard path.
2. **`nearest` + `concurrent` answers 7 to 8 greetings in 10, in under 2 s for half of them at play concurrency** (gr2 19/24, median 1.7 s, p90 3.0 s). It answers addressed lines 20 of 21, statements included, because a stranger's addressed line skips the remark draw (control: 5 of 11 statements). gr2 agrees with gr1 on the leading arm. Its greeting share is a little higher (19 against 17 of 24) and its latency lower (gr1 p90 5.4 s with the queue).
3. **Parking decides latency only when the queue is saturated.** At concurrency 4, `nearest` with parking on `wait` answered as often as with `concurrent` but with a p90 of 57 s against 5.4 s. `concurrent` alone (greet off) does nothing for greetings (1/24). gr2 did not run `nearest` alone, so the two are not separated at play concurrency.
4. **The first greeting is the one that lands.** Cycle 0 was answered in every run of every greet arm (nearest-concurrent gr1 4/4, gr2 4/4). Later greetings were answered 13 of 20 and 15 of 20. The unanswered ones read "LIVING_GREET=nearest did not draw them in", or the hearer was in another exchange. Per the mode's code, the nearest hearer is passed over when in another exchange, when drawn in within the last minute, or when it has settled an exchange with the speaker. Which of these applied is not logged.
5. **`facing` answers whoever happens to be ahead.** The scripted player faced its direction of walking, so the faced hearer was the nearest mind in only 2 of 17 answers. It also addresses residents' lines, so it made the only pile-ons (below).
6. **`curious` is the slowest to reach the nearest** (5 of 15) and answers the fewest greetings (15/24).
7. **Conversation.** The player never answers, so no arm can show a long exchange. What varies is whether the answerer comes back. The answerer of a greeting spoke to the player again within 180 s (unprompted, or answering the next scripted line) in gr2 7 of 19 under `nearest` + `concurrent` against 1 of 2 in control, and in gr1 3 of 17 against 0 of 3. Lines to the player per minute: gr2 0.67 against 0.55, gr1 0.48 against 0.35. In control, a larger share of those lines asks the silent stranger's name: gr2 19 of 55 against 8 of 67.

### Costs: false replies and pile-ons

A false reply, as `greet_report` defines it, is a turn that answered a resident's line meant for someone else: a line addressed to another, or one said to no one while its speaker was in an exchange with another. The table counts those the inspector attributes to the line. Pile-ons are lines answered by two or more.

| Batch | Arm | Minutes | False replies (inspector) | per min | greet_report false | per min | Resident lines answered by 2+ | Player lines answered by 2+ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| gr1 | control | 100 | 1 | 0.010 | 1 | 0.010 | 0 of 787 | 0 |
| gr1 | `nearest` | 99 | 2 | 0.020 | 4 | 0.040 | 0 of 800 | 0 |
| gr1 | `nearest` + `concurrent` | 100 | 1 | 0.010 | 1 | 0.010 | 0 of 778 | 0 |
| gr1 | `curious` | 99 | 1 | 0.010 | 1 | 0.010 | 0 of 877 | 0 |
| gr1 | `facing` | 124 | 3 | 0.024 | 3 | 0.024 | **2 of 991** | **3** |
| gr1 | `concurrent` only | 100 | 2 | 0.020 | 1 | 0.010 | 0 of 784 | 0 |
| gr2 | control | 99 | 11 | **0.111** | 10 | 0.101 | 1 of 917 | 0 |
| gr2 | `nearest` + `concurrent` | 100 | 4 | **0.040** | 3 | 0.030 | 0 of 902 | 0 |

**Reading the false replies.**
1. **They come from the residents' own path, not from the switches.** `nearest` + `concurrent` never drew a resident into another resident's line: the mind log's "is drawn in by" names only the player, in all 8 runs. `nearest` with parking on `wait` did so 2 times in 4 runs, and `curious` once. Most flagged replies are family members answering a relative's line to the group, through the shipped "cares" path.
2. **Some are not false.** The line named the one who answered: "Uncle Cal — …" (gr1 control-r1), "Oren — plain words…" (gr1 nearest-concurrent-r4), "Sefa Reed — you asked for letters…" (gr2 control-r3). Others answer an open line: "Come to the fire if you're hungry, any of you" (gr1 nearest-r4).
3. **The genuine ones are few.** One cuts across a line to the player (gr2 nearest-concurrent-r2, example 3 below). The others are `facing`'s chorus, Mara's "Mother? I'm Mara" (gr2 control-r1) and one in `curious` (gr1 curious-r1).
4. **gr2 control's 11 is mostly one run.** Run r4 gave 8, from a busy family evening at the fire. With the queue gone, residents simply talk more (control talk turns 2.4 a minute against 1.9 in gr1).
5. **No arm except `facing` piled on.** Under `facing`, two residents answered the same line twice: "First light, then…" and "First light it is, then…" (gr1b facing-r2). The player's greetings were answered twice 3 times.

### The guarded proxy-tuned score (PROXY, circular)

`feel_tune.py score` used the proxy fit (`tune_result_proxy.json` in the `tool-feel-tune` worktree). Its header says: **PROXY RATINGS (general coordinator, rating for the owner); not the owner's judgement. CIRCULARITY: the proxy said being answered mattered most**, so a score resting on heard/answered shows the rubric applied consistently, not the owner's judgement. gr1 is scored pooled, through a scratch directory of links with batch-unique replicate numbers, so that every arm is judged against the one control arm (gr1a). gr2 is scored on its own. It scores the residents' whole lives in 10-minute windows, not the greetings alone.

| Batch | Arm | Score | Windows | False replies/min | Repeated lines | Talk that led to something | Placebo (6 min earlier) | Verdict |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: | --- |
| gr1 | control | 4.11 | 77 | 0.010 | 0.11 of 802 | 0.67 of 725 | 0.51 | baseline |
| gr1 | `curious` | 4.17 | 80 | 0.010 | 0.12 of 903 | 0.71 of 823 | 0.54 | LOST (false replies and repeats "worse": 1 in 99 min against 1 in 100, 0.12 against 0.11; noise) |
| gr1 | `facing` | 4.07 | 101 | 0.024 | 0.07 of 1001 | 0.62 of 937 | 0.45 | no score gain |
| gr1 | `nearest` | 4.07 | 78 | 0.040 | 0.08 of 804 | 0.70 of 748 | 0.58 | no score gain |
| gr1 | `nearest` + `concurrent` | 4.08 | 78 | 0.010 | 0.10 of 791 | 0.63 of 722 | 0.50 | no score gain |
| gr1 | `concurrent` only | 4.21 | 81 | 0.010 | 0.04 of 785 | 0.65 of 752 | 0.54 | LOST (talk that led to something 0.65 against 0.67) |
| gr2 | control | 4.10 | 80 | 0.101 | 0.09 of 934 | 0.66 of 850 | 0.52 | baseline |
| gr2 | `nearest` + `concurrent` | **4.33** | 81 | 0.030 | 0.08 of 913 | 0.61 of 848 | 0.51 | **LOST** (talk that led to something 0.61 against 0.66) |

The proxy score does not separate the arms in gr1 (4.07–4.21). In gr2 it rises for `nearest` + `concurrent`, which is reported `LOST` because talk that led to something fell. Against the placebo, that lift is 0.10 against 0.14. False replies and repeated lines both fell. The proxy score therefore gives no support for any arm, and the guards give one small cost for the leading arm. It is unknown whether the owner would see this: the owner has not rated these runs.

### Cost per world-hour

US dollars per hour of a run, for 11 thinking minds, from the journals at `trials.py` prices (`greet_report.py` `usd_h`), mean (range) per arm. gr1: control 1.82 (1.64–2.02); `nearest` 1.74 (1.62–1.80); `nearest` + `concurrent` 1.64 (1.54–1.74); `curious` 1.92 (1.81–2.00); `facing` 1.77 (1.63–1.93); `concurrent` only 1.78 (1.72–1.85). gr2: control 2.16 (1.91–2.48); `nearest` + `concurrent` 1.88 (1.75–2.11). The switches do not raise cost. The queue capped spending in gr1, so gr2 is the figure for play. Tokens per batch (ledger): gr1a 35.5 M, gr1b 30.9 M, gr1c 34.2 M, gr2 33.6 M.

### Recommendation

**Turn on `LIVING_GREET=nearest` with `LIVING_PARK=concurrent`**, the owner's accepted choice 3 ([COMMUNICATION.md §11](COMMUNICATION.md#11-open-choices-for-the-owner)). gr1 and gr2 agree.
- It answers a stranger's crowded greeting 19 of 24 times against 2 of 24, in 1.7 s median and 3.0 s at p90 at play concurrency.
- It answers addressed lines 20 of 21, statements included.
- Its false-reply cost: none added that these runs can see. In gr1 it was 0.010 a minute in both arms, and in gr2 0.040 against control's 0.111. It never drew a resident into another resident's line, and it made no pile-ons.
- The guarded proxy score reports it `LOST` in gr2 on talk that led to something (0.61 against 0.66, placebo-adjusted 0.10 against 0.14). That is a small cost on a circular measure, and it is recorded.

**The override.** The guarded proxy score marked nearest + concurrent LOST in gr2 (talk that led to something 0.10 vs 0.14 above placebo over four runs each). The general coordinator, who set that rule, overrode it on 2026-11-11: false replies and repeated lines were no worse, the dip is small over four runs, and the change fixes what the owner complained about directly. The measure keeps being reported in the next hamlet batches to see whether it was noise.

**Accepted and on by default.** The owner accepted it as communication choice 3 ([COMMUNICATION.md §11](COMMUNICATION.md#11-open-choices-for-the-owner)), and since 2026-11-11 (branch `exp-greet`, commit "Greeting switches on by default") it is the default: `LIVING_GREET=nearest`, `LIVING_PARK=concurrent`, and the `speech_audience` law on, which `nearest` reads. `off` and `wait` remain selectable (the old rules). `facing` remains available and off (below).

**What it does not fix.**
- **Known shortfall:** later greetings to a group that has already spoken with the stranger often go unanswered (5 of 24 in gr2). It is queued behind the arrival experiment.
- The trial's silent player makes residents ask its name again and again, and finally press: Ilsa's "give your name and your road now, or walk on before dark" (example 5).

**`facing` is not ready for a player.** As built, it addresses every speaker's lines, residents' included. That made the only choruses (2 resident lines, 3 player lines) and the most genuine false replies (3). It answered the nearest mind only 2 times in 17, because the scripted body faced its walking direction. Before it could be on for a player:
1. dev-box's `human_face(dx, dy)` must be on main and the bindings regenerated. Until then the client's `look()` (`living/game/src/controls.rs`) sends nothing.
2. In the default "travel" scheme the client sends `None`, so the body faces its travel, and a player who walks into a group and stops faces wherever they walked. The client would need to send a look toward the person under the cursor, or the camera's direction, when a line is said to the room, in both schemes. The audience row's `off` must come from that heading at the line's time.
3. The mind would need to apply facing to players' lines only, or use it only as a tie-break between equally near hearers. COMMUNICATION.md §5 already proposes the tie-break.

### Examples (verbatim)

Paths are relative to `~/dev/slop-runs-greet/.local/living/trials/`. Lines are from each instance's `speech.jsonl`, and fates from the inspector over the instance.

**Control.**
1. *A greeting answered* (gr2 `greet-greet-control-r1`, cycle 4, four within 6 m): "Good day to you all." Ilsa Hale, overheard turn, 3.8 s: "Good day to you, friend. You've come at a good hour — there's a fire and something warm in the pot, if you've a hunger on you." The others: "Ilsa Hale took an overheard turn on it first". Ilsa had come to care about the player by then.
2. *A greeting unanswered* (gr2 `greet-greet-control-r3`, cycle 0, five within 6 m): "Hello there!" All six hearers: "no turn: not addressed, and … does not care about Arlen (not among the people they know): nothing in the gate gives a turn."
3. *A false reply* (gr2 `greet-greet-control-r1`): Sefa Reed, in an exchange with Brisk, says "Mother — what do you know of the mill town? The folk there, and whether a body could make a life in it?" Mara Vane, 7.6 s: "Mother? I'm Mara — we met at the fishing spot at dawn. As for the mill town, I know it the way I know any place: by its walls. Never lived there, so I won't pretend to advise you on making a life in it."
4. *A conversation that followed* (gr2 `greet-greet-control-r3`, addressed): "What do people here do for work?" Mara Vane, 5.1 s: "Whatever the day needs — I'm a carpenter, and today that's stone and wood both. What's your trade, stranger? You've cooked at our fire twice and I still don't know what to call you." 27 s later: "Brisk went to mark the rise — I'm resting an hour by the fire, then the store goes up at the west grounds. You're welcome to haul wood with me if your hands want work."
5. *An awkward one* (gr1a `greet-greet-control-r2`): the greetings got no turn, and Brisk Marrow's deliberations caught up minutes later, three times. "You hailed me on the road and I never got your name. I'm Brisk Marrow, of Millbrook — what do they call you?" (+768 s), "Twice you've hailed me and twice I've been slow. What do folk call you?" (+804 s), "Friend, we've traded good days twice now and I still can't call you anything." (+1225 s).

**`nearest` + `concurrent` (gr2).**
1. *A greeting answered* (`greet-greet-nearest-concurrent-r1`, cycle 1, three within 6 m; the nearest, Oren, was passed over): "Good day to you all." Ilsa Hale, drawn in (Nearest), 1.7 s: "Good day to you too. Come in out of the morning — there's bread still warm and I've a pot on. What brings you up this way?"
2. *A greeting unanswered* (`greet-greet-nearest-concurrent-r2`, cycle 5, three within 6 m): "Hello, everyone. I've only just come down the road." Mara and Oren: "not addressed, and … does not care about Arlen: nothing in the gate gives a turn; LIVING_GREET=nearest did not draw them in". Pim: "cares about Arlen, but was in another exchange". Oren had told the player twice that afternoon to "come round the mill another day".
3. *A false reply* (`greet-greet-nearest-concurrent-r2`): Ilsa to the player, "Here — take this, it's cooked proper, and I'll not have you a stranger at my fire. Your name?" Her son Pim, 6.3 s: "Ma, after the bushes can I go down to the fishing bank? Da said the bank, never the millrace." This is the shipped overheard path (Pim cares about his mother), not the switch.
4. *A conversation that followed, and led to something* (`greet-greet-nearest-concurrent-r3`, addressed): "What do people here do for work?" Ilsa Hale, 2.3 s: "Whatever's in front of them — fish the river, smoke what they catch, keep a fire, mill grain, mind goats. There's always a hand wanted at the mill house if you're hungry for work." Then, unprompted: "Wait there, friend — I'm just carrying these into the store, then you'll have food in your hands and honest work at the mill if you want it." (+86 s). Then "Here, friend — berries in your hands as promised. Eat your fill…" (+126 s). The chronicle has "Ilsa Hale gave 6 berries to Arlen" and "… 12 berries …" (`chronicle.jsonl` ids 141, 147).
5. *An awkward one* (`greet-greet-nearest-concurrent-r4`, Ilsa Hale, over three cycles):
   - "Hello there!" → 1.5 s: "Hello yourself. You've had a bite and a warm fire — now tell me, what road did you come down, and who'd vouch for you on it?"
   - The script's next line, "That looks like hard work." → "It's work, and it's honest. But I asked you a question and got a comment about my pot — so once more, friend: what road, and who vouches for you?"
   - A cycle later: "Traveller — you've had my bread twice and my question three times. Sun's going down; give your name and your road now, or walk on before dark."
   - Earlier in the same run she took the player for Sefa: "Sefa, is it? I'm Ilsa Hale — I cook at the mill house…"
   - This is the right reaction to a stranger who never answers. It is awkward because the script never answers.

## Arrival batch ar2 (2026-11-11)

**Rejected (2026-11-12).** The owner rejected the law arms (`notice`, `known`, `wonder`, `all`) as prescribed attention: "I don't really like the fact that this has been encoded as a world rule. It should be something emergent from the personality and role of NPCs." The newcomer laws were not merged, not even switched off; attention to a stranger has to come from the residents' personalities and roles. The `arrive` and `arrive-answer` trials and `arrive_report.py` stay as tooling, with only the control (`arrive-control`). The figures below remain the record of what the arms did.

Paid runs of the arrival trials from branch `exp-arrive` ("Arrivals: a stranger who says nothing" in that branch's TRIALS.md: the diagnosis, the three laws and the fake proofs `af1`–`af8`). A scripted player joins the hamlet, walks to the densest group of residents, and stands silent among them for two 5-minute stands. It never speaks, gestures or names itself. In `arrive-answer` it says "Hello. I'm new here." once, to the first resident who addresses it. The arms differ only in the arrival laws, so differences between arms are caused by the laws.

**Batch.** `ar2`, started 2026-11-11 21:47. Trials `arrive` (arms `arrive-control`, `arrive-notice`, `arrive-known`, `arrive-wonder`, `arrive-all`) and `arrive-answer` (arms `arrive-control` and `arrive-all`), 4 replicates each, 14 minutes, 28 instances. All 28 ran to duration. 11 residents think (`minds.max` 11; the infant Tobin lives by his graph). Models: the `people` mix (glm-5-3-flash and deepseek-v4-1-flash), concurrency 64. Evidence: `~/dev/slop-runs-arrive/.local/living/trials/ar2/` on the Spark (`report.md`, `batch.json`, one folder per instance).

**Commit and switches.** The run checkout's commit is `461c63cd`. It is exp-arrive `1e63a304` (main `6caebe20` merged) plus two ports from main: the trial runner's laws guard (fix-verify-laws) and the consolidation capacity fallback (fix-consolidation-429, `e301aa9f`).
- In force: the arrival laws per arm. `notice` sets `newcomer_salience` 0.5, `known` sets `newcomer_scene_min` 30, `wonder` sets `newcomer_drive_s` 90, `all` sets all three, and control sets none (all 0, as shipped). The stale-reasons fix (main `61213ad3`) was in the build.
- Not in this build: the greeting default (`LIVING_GREET=nearest`, `LIVING_PARK=concurrent`; exp-greet merged to main later as `4099ee1d`), the meters() alarm levels (main `61b7b2eb`, later), skill timings (`LIVING_SKILL_TIMINGS`) and act outcomes (`force_outcomes`). A newcomer's line was therefore answered under the old room rule, and the residents' rethink gate used the levels from before meters().

**Consolidations.** 2,419 attempted: 1,793 on the primary model, 624 on the fallback, 2 retried, 0 lost (`report.md`).

**Cost.** $11.39 in all: GLM $3.98 and DeepSeek $7.41 (ledger). The per-run journal costs sum to the same figure.

**ar1 is excluded.** `ar1` ran the same trials under provider capacity failures: 37% of consolidations failed and the runaway guard stopped 7 of 28 instances (`SUPERSEDED.txt`). It is not used in any figure below. For the memory-failure question, its 21 completed runs were checked on their own. Residents whose consolidations mostly failed had think prompts of the same size (5,572–5,633 tokens on average) and asked the newcomer's name about as often (0.33–0.62 times per resident) as the others. ar1 shows nothing on its own about what residents do when their memory step fails.

### Method

```bash
# read-only against the run checkout; no model calls
python3 ~/dev/slop-runs-arrive/living/tools/arrive_report.py ar2 --examples 3 --json ar2.json        # exp-arrive's report
python3 living/tools/arrive_spread.py ~/dev/slop-runs-arrive/.local/living/trials/ar2 \
    --arrive-tools ~/dev/slop-runs-arrive/living/tools \
    --feel-model <tool-feel-tune worktree>/.local/living/feel/proxy-fit/tune_result_proxy.json --json spread.json
python3 living/tools/inspector.py ~/dev/slop-runs-arrive/.local/living/trials/ar2/<instance> -o page.html
```

[`arrive_spread.py`](../living/tools/arrive_spread.py) (this branch) runs exp-arrive's `arrive_report.run_report` on every instance. It adds the measures that report lacks, one row per replicate:
- **Reach:** whether a line said to the newcomer reached it. The authority's own verdict is the speaker's `silence` experience at the line, "No answer from a stranger; they don't seem to be within earshot."
- **Timing:** time from the join, not from the player's first walk.
- **Follow-through:** introductions, invitations, gifts and threats, telling others, and re-asks.
- **Guards:** false replies (main's `greet_report.py`); repeated lines and talk that led to something, split by addressee (`feel_tune.py`'s definitions); the proxy-tuned score.
- **Thinking and cost:** deliberations and talk turns per resident-hour, reused reasons, and cost per run and per resident-hour.

Its docstring defines every column. Cells give each replicate's value, r1/r2/r3/r4. `>` or `<` marks an arm whose four values all lie above or all below its trial's control values: the ranges are disjoint, which with 4 against 4 is a one-sided exact Mann-Whitney p of 1/70. `~` means within spread. `–` means the event did not occur in that run. The switched arms are not separated from one another by any measure here: their ranges overlap.

### Contact: who reaches the silent newcomer, and when

Residents in range (within 12 m during a stand) were 7–11 per run in every arm (no arm differs).

| Measure (per run) | `arrive` control | `known` | `notice` | `wonder` | `all` | `arrive-answer` control | `arrive-answer` `all` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Residents asked to think by the newcomer (arrive_report `asked`) | 0/0/0/0 | 0/0/0/0 ~ | 10/9/10/7 > | 6/5/7/5 > | 6/9/8/9 > | 0/0/0/0 | 10/7/9/11 > |
| Share of residents in range who made deliberate contact (`acted_share`; unheard lines count) | 0.12/0.09/0/0 | 0.12/0.36/0.30/0.09 ~ | 0.64/0.30/0.82/0.67 > | 0.71/0.27/0.64/0.50 > | 0.86/0.60/0.67/0.89 > | 0/0/0/0.09 | 0.60/0.78/0.70/0.64 > |
| Residents whose line reached the newcomer (`heard_res`) | 1/1/0/0 | 1/1/1/1 ~ | 4/1/6/3 ~ | 5/3/4/5 > | 4/4/3/4 > | 0/0/0/1 | 3/7/3/6 > |
| Seconds from the join to the first deliberate contact | 439/65/–/– | 295/230/117/139 | 27/61/23/20 | 150/138/110/80 | 9/9/9/8 | –/–/–/241 | 9/13/16/16 |
| Seconds from the join to the first line that reached it | 439/65/–/– | 307/296/117/224 | 55/80/66/41 | 151/146/110/115 | 133/35/34/51 | –/–/–/241 | 48/38/39/38 |
| Residents whose first contact was a line | 1/1/0/0 | 1/2/3/1 ~ | 5/3/8/6 > | 5/3/6/5 > | 5/5/5/7 > | 0/0/0/1 | 6/7/6/7 > |
| Residents who passed within 4 m and did nothing else | 6/8/7/5 | 7/5/6/7 ~ | 2/1/1/2 < | 0/4/1/4 < | 1/1/1/0 < | 6/9/11/6 | 0/1/3/0 < |

- **Runs where any line reached the newcomer:**
  - control: 3 of 8 (at 65, 241 and 439 s);
  - `known`: 4 of 4, at 117–307 s;
  - `notice`: 4 of 4, at 41–80 s;
  - `wonder`: 4 of 4, at 110–151 s;
  - `all`: 4 of 4, at 34–133 s (median 43 s);
  - `arrive-answer` `all`: 4 of 4, at 38–48 s.
- **No contact before the scripted answer.** In `arrive-answer` control, nobody addressed the newcomer in 3 of 4 runs, so it never answered. This is the owner's play-test 3 observation, reproduced.

First contact by class, summed over the 4 runs (arrive_report's keyword classes, per resident in range or who spoke to the newcomer):

| Arm | Residents | Greeting | Question | Offer | Warning / hostility | Other line | Watching | Approach, no line | None |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control | 39 | 0 | 0 | 1 | 0 | 1 | 3 | 26 | 8 |
| `known` | 40 | 2 | 4 | 0 | 0 | 1 | 5 | 25 | 3 |
| `notice` | 41 | 1 | 14 | 2 | 2 | 3 | 10 | 6 | 3 |
| `wonder` | 39 | 4 | 14 | 0 | 0 | 1 | 6 | 9 | 5 |
| `all` | 35 | 0 | 19 | 1 | 0 | 2 | 9 | 3 | 1 |
| `arrive-answer` control | 42 | 1 | 0 | 0 | 0 | 0 | 3 | 32 | 6 |
| `arrive-answer` `all` | 40 | 3 | 17 | 1 | 0 | 5 | 7 | 4 | 3 |

Contact in every switched arm is mostly a question ("Who are you, and what brings you here?"), usually with the speaker's own name. The two warnings are in `notice` r4: Cal Reed threatened the newcomer twice (chronicle `threat`). Lio Reed said "Say your name and your business, or turn and go".

### Follow-through

| Measure (per run) | control | `known` | `notice` | `wonder` | `all` | `answer` control | `answer` `all` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Residents who introduced themselves in a heard line | 0/1/0/0 | 1/0/1/1 ~ | 4/0/4/2 ~ | 5/3/4/5 > | 2/4/2/4 > | 0/0/0/1 | 3/5/2/3 > |
| Residents who invited or offered (food, fire, work) in a heard line | 1/0/0/0 | 0/0/0/0 | 1/1/0/0 | 1/0/0/0 | 0/2/0/0 | 0/0/0/0 | 1/1/0/1 |
| Residents who gave it something (chronicle) | 0 | 0 | 0/1/0/0 | 1/1/0/0 | 0 | 0 | 1/0/0/0 |
| Residents who spoke of it to others | 0/0/0/0 | 0/0/0/3 ~ | 1/1/3/2 > | 1/1/4/0 ~ | 0/1/2/0 ~ | 0/0/0/0 | 2/2/0/2 ~ |

- **Few contacts led to anything beyond names.** Over the 20 `arrive` runs, 6 residents made a heard invitation and 3 gave the newcomer something: Ilsa in `notice` r2 (berries three times), and Ilsa and Brisk in `wonder`. Teaching was offered once, by Teodor in `arrive-answer` `all` r3: "I'd teach you, if you've hands and patience for honest work. I've written it on a tablet besides". No lesson followed, since the player never answers twice. A silent stranger gives nothing to build on, so these counts are a floor.
- **After the newcomer's one answer** (`arrive-answer`; arrive_report's follow-through):

| Run | Answered | Contact (s after the first walk) | Lines from that resident before 90 s of quiet | Seconds to each | Others who joined |
| --- | --- | ---: | ---: | --- | --- |
| `all` r1 | Lio Reed | 26.7 | 3 | 0.3, 2.0, 26.7 | Sefa |
| `all` r2 | Wenna Reed | 16.9 | 5 | 17.0, 6.7, 6.0, 79.2, 11.1 | Sefa |
| `all` r3 | Sefa Reed | 17.8 | 6 | 1.1, 0.4, 16.7, 3.6, 2.7, 8.0 | Ilsa, Teodor, Brisk, Wenna, Lio |
| `all` r4 | Brisk Marrow | 16.4 | 4 | 0.1, 18.4, 13.7, 18.0 | Oren, Pim, Edda, Sefa |
| control r4 | Edda Marrow | 219.9 | 1 | 11.8 | none |
| control r1–r3 | nobody addressed the newcomer | | | | |

**The answer opened an exchange, not a conversation.** One answer was enough for the addressed resident to keep talking, 3–6 lines with most replies within 20 s, and for 1–5 others to join. Most of these lines press for the name again, because the player says nothing more. Brisk (r4): "You'll not walk off nameless, friend. One word — your name — and you're free to go." Then: "Speak plain now, or be watched."

### Costs: crowding, lines that never arrived, re-asks, and the guards

| Measure (per run) | control | `known` | `notice` | `wonder` | `all` | `answer` control | `answer` `all` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Most residents converging in 60 s (`converge_60s`) | 1/1/0/0 | 1/3/1/1 ~ | 6/2/6/4 > | 2/2/4/3 > | 4/3/4/5 > | 0/0/0/1 | 5/4/6/5 > |
| Most within 4 m at once who had made contact (`together_4m`) | 1/1/0/0 | 0/1/1/1 ~ | 3/1/2/2 ~ | 2/1/1/2 ~ | 2/2/2/2 > | 0/0/0/0 | 3/2/2/3 > |
| Lines to it out of earshot / all lines to it | 0/2/0/0 of 5/5/0/0 | 0/3/3/2 of 1/4/5/5 | 5/3/14/12 of 12/4/30/17 | 4/9/5/10 of 11/13/12/18 | 12/13/13/9 of 18/23/19/16 | 0/0/0/1 of 0/0/0/2 | 25/11/5/11 of 35/29/15/30 |
| Re-asks (its name or business asked again by the same resident) | 0/3/0/0 | 0/2/0/4 ~ | 4/0/14/10 ~ | 1/7/4/6 ~ | 11/11/9/5 > | 0/0/0/0 | 10/12/4/10 > |
| False replies per minute (greet_report) | 0.07/0.14/0/0 | 0.07/0/0/0.07 ~ | 0.14/0/0.07/0 ~ | 0/0/0/0 ~ | 0/0/0/0 ~ | 0.07/0/0/0.14 | 0/0/0/0 ~ |
| Repeated lines, residents' lines not to the newcomer | .16/.11/.04/.16 | .09/.05/.08/.14 ~ | .15/.11/.14/.11 ~ | .07/.17/.12/.05 ~ | .17/.09/.08/.02 ~ | .09/.03/.28/.09 | .11/.10/.16/.06 ~ |
| Talk to residents that led to something | .71/.90/.61/.80 | .69/.75/.62/.66 ~ | .71/.57/.79/.64 ~ | .72/.56/.49/.74 ~ | .69/.65/.65/.67 ~ | .62/.76/.65/.71 | .61/.66/.66/.71 ~ |
| The same, every line 6 min earlier (placebo) | .48/.42/.40/.55 | .32/.50/.44/.31 | .36/.39/.46/.34 | .42/.41/.35/.47 | .31/.42/.44/.41 | .52/.44/.46/.53 | .44/.32/.34/.28 |
| Proxy-tuned score (PROXY, circular) | 4.16/4.29/4.12/3.72 | 4.31/3.53/4.28/4.18 ~ | 4.00/4.05/4.29/4.05 ~ | 3.66/3.81/3.89/4.27 ~ | 3.62/3.84/4.09/3.74 ~ | 4.23/3.84/4.32/4.12 | 4.03/3.93/3.61/4.24 ~ |

Pooled false replies: control 3 (0.053 a minute), `known` 2 (0.036), `notice` 3 (0.054), `wonder` 0, `all` 0, `arrive-answer` control 3 (0.053), `arrive-answer` `all` 0.

1. **Crowding is the clearest cost, and it is moderate.** Every switched arm except `known` brought more residents to the newcomer within a minute than control did: `all` 3–5, `notice` 2–6, `wonder` 2–4, against 0–1. Only `all` (2 in every run) and `arrive-answer` `all` (2–3) put more of them within 4 m at once than control (0–1). No run had more than 3 contacting residents within 4 m. Under `notice` and `all` the first sight wakes every resident who sees the newcomer in the same few seconds. In `all` r2, Sefa, Wenna and Cal Reed were asked to think within 2.4 s of one another and called out at 8–14 s. `wonder` staggers them by temperament (45–135 s).
2. **Half the lines to the newcomer never reached it** under the switches:
   - `all` 47 of 76;
   - `notice` 34 of 63;
   - `wonder` 28 of 54;
   - `known` 8 of 15;
   - control 2 of 10;
   - `arrive-answer` `all` 52 of 109.

   `notice` asks for a thought at first sight within 60 m of one's home door, which is usually 25–48 m away, and the model says its line at once rather than walking first. Each unheard line comes back as "No answer from a stranger; they don't seem to be within earshot", and the inspector shows residents counting those as refusals (below).
3. **Re-asks follow from the player's silence and from the unheard lines.** `all` gave 5–11 per run and `arrive-answer` `all` 4–12, beyond control's 0–3. `notice` (0–14) and `wonder` (1–7) are within spread. The trial player never gives a name, so these counts exaggerate what a player who answers would draw.
4. **The guards held.** No arm raised the proxy-tuned score: arm means 3.82–4.10 against control's 4.07, all within spread, and `all`'s mean is the lowest. By feel_tune's rule no arm `LOST`, and none gained. False replies were 0 in `all` and `wonder` and never above control's range. Repeated lines among residents stayed within spread. Talk to residents that led to something, net of its placebo, was within spread everywhere:
   - control 0.29 and `arrive-answer` control 0.20;
   - `known` 0.29, `notice` 0.29, `wonder` 0.22, `all` 0.27;
   - `arrive-answer` `all` 0.32.

   For lines to the newcomer the measure can count only an outcome in the speaker's own percepts, since the player makes no plans. It found 0–0.26 per run, and those outcomes need not involve the newcomer. Repeated lines to the newcomer had too few lines per run in control (0–5) to compare.

### Thinking and money (baseline for the meters() alarm-level change)

| Measure (per run) | control | `known` | `notice` | `wonder` | `all` | `answer` control | `answer` `all` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Deliberations per resident-hour, whole run | 23.6/25.6/25.9/21.4 | 20.9/24.2/22.2/22.8 ~ | 29.2/19.9/29.2/19.5 ~ | 21.8/21.0/24.1/27.2 ~ | 21.8/25.3/26.0/24.8 ~ | 26.9/22.1/21.0/26.0 | 26.0/30.6/24.8/29.9 ~ |
| Same, after minute 2 (mean of 4) | 23.7 | 21.8 | 21.1 | 22.8 | 20.9 | 24.5 | 24.0 |
| Talk turns per resident-hour | 9.7/16.3/17.8/14.0 | 14.4/12.5/12.8/11.2 ~ | 10.1/14.0/17.1/10.1 ~ | 7.8/9.7/12.0/12.8 ~ | 15.9/12.8/8.9/10.5 ~ | 17.5/9.7/9.0/16.7 | 11.3/15.9/10.9/12.4 ~ |
| Reason lines reused from an earlier thought (share) | .44/.49/.50/.49 | .43/.50/.45/.42 ~ | .46/.46/.41/.31 ~ | .37/.44/.42/.53 ~ | .38/.40/.38/.35 < | .44/.48/.44/.39 | .38/.54/.44/.55 ~ |
| Of them one-time events (feelings, first sights) | 15/18/14/13 | 11/21/18/18 | 15/16/19/6 | 10/10/24/27 | 10/16/10/10 | 17/16/15/20 | 10/39/20/29 |
| Reasons carried again (`carried_again`, stale-reasons fix) | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| Dollars per run | .39/.45/.44/.41 | .38/.42/.38/.40 | .46/.36/.49/.32 | .36/.37/.37/.44 | .37/.39/.39/.39 | .45/.38/.37/.42 | .40/.50/.41/.48 |
| Dollars per resident-hour (pooled) | 0.164 | 0.154 | 0.159 | 0.150 | 0.149 | 0.157 | 0.174 |

- **Deliberation baseline.** A hamlet resident deliberates about **24 times per hour** with the shipped arrival laws (control: 21.4–25.9 per run, 23.7 after the opening burst; `arrive-answer` control 21.0–26.9). That is about once every 2.5 minutes. One deliberation is one think + compile pair (`thoughts_all.jsonl` kind `deliberate`). This is the baseline the meters() alarm-level change is to be compared against, on a hamlet of 11 thinkers, in daylight, over 14 minutes.
- **The laws add no thinking that shows.** `notice` is bimodal: 29.2, 19.9, 29.2 and 19.5. `arrive-answer` `all` is the highest at 24.8–30.6, within spread.
- **The stale-reasons fix holds.** No reason was carried into a second deliberation in any run (55–85 carried per run). The reused share (0.31–0.55) is read from the prompts' words, so a feeling that arrives again counts as reused.
- **The laws cost nothing extra.** $0.149–0.174 per resident-hour, about $1.65–1.92 per world-hour for 11 thinkers.

### What the inspector shows beyond the tables

One run per arm, through `inspector.py`'s page data (journal requests and replies, speech with each hearer's fate, and the authority's "out of earshot" marks): control r2, `known` r3, `notice` r1, `wonder` r3, `all` r2, `arrive-answer` `all` r3 and `arrive-answer` control r4. Times are seconds from the join.

1. **Under the shipped laws the newcomer is in the scene, noticed in passing, and dealt with when a resident's own plan allows.**
   - In control r2, Brisk's thoughts named the newcomer from 54 s: "keeping an eye on that stranger walking west toward us". His plan came first; then at 65 s: "Easy there — you're coming up on Millbrook ground. State your business and keep to the road."
   - Two further hails at 173–175 s did not reach the newcomer. At 531 s he walked up: "Say your business now, plainly, or take yourself back down the road you came by."
   - The one control contact in `arrive-answer` (r4, Edda, 241 s) took the newcomer for a fellow fisher: "Morning — you work the west water too? I'm Edda, of Millbrook."
2. **`notice` asks everyone at once, and temperament shapes the answer.** In `notice` r1, 8 of the 11 residents were asked to think by the first sight, 2–57 s after the join, from 26–48 tiles.
   - Wenna: "No sense in shouting across thirty tiles; I'll keep to my nets and watch which way they move."
   - Brisk: "Too far to hail from here; I'll walk over and see who it is, spear on my shoulder but hand easy."
   - Oren: "I'll keep my eyes on the newcomer but stay at my work."
   - Sefa called twice from too far (unheard). Ilsa, at 65 s: "You're welcome at our fire — I'm Ilsa, and there's food enough for one more."

   Residents also warned their own: Wenna told Sefa "keep an eye out — there's a stranger standing on the south road", and Edda told Brisk "Keep an eye on them while I'm at the water."
3. **"A stranger" is several people, and the newcomer inherits what the others do.** Residents of the other settlement are also "a stranger" beyond the 24 m naming distance, and `known`'s "new to you" mark does not undo that in the residents' words.
   - In `notice` r1, Edda told Brisk "the stranger's teaching Wenna's Lio to hunt with a spear … a man with no name drilling a child". The teacher was Lio's uncle Cal.
   - Teodor said to the newcomer: "I have watched you cook and teach all morning and never heard your name". Ilsa: "you've cooked at our fire before". Wenna planned to "keep an eye on the stranger (#5)", who was Brisk.
   - In `wonder` r3, Edda called Sefa "Stranger" and challenged her right to the fishing spot. In `arrive-answer` control r4, Pim asked whether "the strangers would show me how they caught that fish", and Oren told him to "keep clear of them". In `known` r3, Wenna spoke of "strangers settling east of us". Both mean the other settlement's residents.
4. **Silence is read as refusal, including silence that was never heard.** Brisk in `all` r2 said seven lines to the newcomer by 195 s, two of them out of earshot. "Three greetings from me and not one word back … or I'll take you for a man who means none of us well." To Teodor: "a stranger who lets five greetings pass and never gives a name. That's not shyness, Teodor, that's someone with a reason to keep quiet." Ilsa in the same run fed it anyway. "Here — take these berries and eat them where I can see you do it. No one goes unfed from my table, name or no name." She told Wenna: "I fed the silent one and got nothing back."
5. **Lines are spoken after the speaker has moved.** In `all` r2, Ilsa's prompt at 467 s had the newcomer 5.3 m north. She thought "The silent one is only five metres off and waiting — that's well within earshot". Her line "You're close enough to hear me now…" came at 487 s from 27 m, after her plan had set off toward the store. Some of the out-of-earshot lines are of this kind, not shouted at first sight. How many is not counted here.
6. **`wonder` brings residents who are already near, so its first lines land.**
   - In `wonder` r3, wonderings came at 10–12 tiles. Lio, at 110 s: "Hello! I'm Lio Reed, of Reedmouth. You've been standing there a while — are you waiting for someone? I've never seen you before."
   - Pim, at 483 s: "Hello there! I'm Pim — I'm having my first cast with my Da. Don't mind us!"
   - Pim later asked Oren: "there's a stranger off to the west I waved at. Should we call them to the fire later?" Oren: "We'll see who they are before we share a fire."
   - Teodor still pressed five times between 494 and 721 s, two of them unheard: "Say your name and your business, or …".
7. **One answer draws a burst from one resident.** In `arrive-answer` `all` r3, after "Hello. I'm new here.", Sefa said 6 lines in 35 s. Two arrived 1.5 s apart. "Who are you, and where do you come from?" was the next line of the sequence her earlier plan had installed (goto, then say, say). "New is fine, long as you're not here to pick the mouth clean before I get my lines in." was her talk turn on the answer. Then came "What's your name, friend…" and "So what do they call you…". Wenna kept the newcomer as a hazard for her children until at least 394 s: "Take Lio's whistle and don't go past the reeds alone."

### What won, what lost, and why

- **`known` alone did nothing measurable.** Marking the newcomer "new to you" in deliberation scenes left every measure within control's spread. The first heard contact came at 117–307 s. Residents read the mark when they thought for other reasons, but it does not make them think.
- **`notice`, `wonder` and `all` each made residents reach the newcomer, beyond replicate spread.** Each raised the share who made contact, the residents whose first contact was a line, and the introductions (`wonder`, `all`), and cut the residents who just passed by.
  - Ranked by the first line that reached the newcomer: `all` (34–133 s, median 43 s), then `notice` (41–80 s), then `wonder` (110–151 s). Control reached it in 3 of 8 runs, at 65–439 s.
  - These three arms do not separate from one another on any measure with 4 replicates.
  - **`all` is the only arm without a weak replicate.** Its lowest contact share was 0.60 and every run had 5–7 residents whose first contact was a line. `notice` r2 (0.30, one heard resident) and `wonder` r2 (0.27) fell to near control.
- **Their costs:**
  - crowding beyond control: `converge_60s` up to 6, and for `all` 2 residents within 4 m in every run;
  - re-asks beyond control in `all` (5–11 per run);
  - half or more of the lines to the newcomer out of earshot.

  None of them added false replies or repeated lines, lowered talk that led to something, or raised the cost per resident-hour. No arm raised the proxy-tuned score; `all` lowered its mean within spread.
- **Why.** The stranger was not invisible to the models; nobody was asked to think about them. `notice` asks at the first sight and `wonder` when the stranger lingers within 12 m, and either is enough for the models to go and ask. What the switches cannot fix is what happens after the first line:
  - lines said out of earshot;
  - a newcomer who stays "a stranger" like the other settlement's people;
  - a silent player whose silence reads as a refusal.

### Recommendation

`arrive-all` is the winning arm. It gave contact in every replicate, a first line that reached the newcomer within 34–133 s (control: 3 of 8 runs), and no extra false replies, repeated lines or money. Its cost is crowding and re-asks: 3–5 residents converging within a minute, 2 within 4 m, 5–11 re-asks a run against a player who never answers, and 62% of its lines out of earshot.

Turning it on by default changes what the owner experiences, so it is the owner's call. Before the next arrival batch, a `say` to someone beyond earshot should wait until the speaker has closed the distance. That would remove the unheard lines that feed the re-asks and the "silence means trouble" readings. It is a mind change, outside these laws.

### What this batch does not show

- **One world and one trial shape.** It ran on the hamlet in daylight, over 14 minutes. The player was scripted and never spoke, except the one scripted answer in `arrive-answer`. A real player who answers would draw fewer re-asks and could give the follow-through something to build on.
- **The defaults now on main were off.** Greeting and park (`nearest`, `concurrent`), the meters() alarm levels, skill timings and act outcomes were not in the build. With the greeting default, a newcomer's own first word is answered within seconds (gr2). This batch measures only the silent case.
- **The measures are heuristics.** The classes, introductions, invitations and re-asks are keyword heuristics; read the examples. The proxy-tuned score rests on 22 proxy ratings and is circular. No owner rating covers these runs.
- **Crowding thresholds are the report's own choices**, as is the 4 m distance. Whether 3–5 residents reacting within a minute feels scripted is for the owner.
- **Some things were not measured.** Whether contact lasts beyond 14 minutes (memories, relations) is not measured. Double answers to one line (a talk turn and a deliberation) are seen in examples but not counted.
- **The arms are not separable from one another.** With 4 replicates, `notice`, `wonder` and `all` cannot be ranked against each other. A larger batch would be needed to choose a single law over all three.
- **The contact share counts unheard lines.** arrive_report's `acted_share` and first-contact time include lines that never reached the newcomer. Use `heard_res` and the heard-line time for what the newcomer could perceive.

## Results

Evidence for every row is under `.local/living/trials/<batch>/` on the Spark (`report.md` per batch, `summary.json` and `journal/` per instance). `living/tools/trial_evidence.py <batch>` prints each instance's death, what it did toward the cast and its first replies with journal references; `--table` prints the table below. Journal references below are relative to `.local/living/trials/`.

**How to read the model's words.** Quotes are the model's reply (`thought`, `say`, `plan`). They are what the model reported as its reason, not proof of why the body did what it did. Causal claims below rest on rows: activities, distances, chronicle and percepts.

### Batches and the rules they ran on

| Batch | Commit (trials-1) | Rules | Models | What ran |
| --- | --- | --- | --- | --- |
| b1 | af8332d (main up to b7cf7fb) | before 0887d81: graded force (hurt or kill) | Mistral Small, the then default | 6 trials × 3 |
| b2 | af8332d, runner files ahead of the commit (pack held away from town) | before 0887d81 | Mistral Small against GPT-6 Luna (since withdrawn) | wolves, hungry × 2 variants × 3 |
| b3 | af8332d, runner files ahead (theft at the stall) | before 0887d81 | Mistral Small | theft × 3 |
| b4 | 6589924 (main up to a4d79c0: one damage rule, GLM/DeepSeek models) | **current**: one damage rule | `default` = glm-flash as configured, against `deepseek-flash` | 6 trials × 2 variants × 3 |
| l1–l3 | 378b2c1 (main up to 8f6ac72: three tiers, new buildings table) | current | life runs, below | |
| b5 | 1ff107c (main 445db098: arrival-1, rules-2, fix-host-example, fix-agreement-terms, fix-mind-small, fix-rules-small, player-told) | **current** | `default` = glm-flash per-purpose efforts | 6 trials × 4 |

**Batch b5 (2026-11-11) is the reference for main 445db098 and later arms.** Batch b4 was the reference before. Its island predates the buildings-table update in 3f3caf0 (lots and footprints changed; rules did not). b1–b3 are kept as history. Every variant is single-profile for people: one profile thinks, compiles, talks and consolidates for a person. The models config has no per-purpose mix for people yet. When it does, a variant names one through its `models` patch, which is merged into the config as given.

### Tokens and cost

| Batch | Calls | Tokens | Est. cost (USD) |
| --- | ---: | ---: | ---: |
| b1 (Mistral Small) | 773 | 5,938,919 | 1.41 |
| b2 (Mistral Small, Luna) | 427 | 3,059,651 | Small part only; Luna unknown |
| b3 (Mistral Small) | 127 | 905,964 | about 0.2 |
| b4 (GLM 5.3 Flash 365 calls, 4,494,546 tokens; DeepSeek 4.1 Flash 721 calls, 4,678,652 tokens) | 1,086 | 9,173,198 | 1.36 + 0.92 = 2.28 |

Prices are from Mistral's model pages (2026-11-09), with reasoning tokens priced as output, which the pages do not state: DeepSeek V4.1 Flash $0.30 input / $1.20 output / $0.007 cached per million; GLM 5.3 Flash $0.15 / $0.50 / $0.03; Ministral 3B, 8B and 14B $0.10, $0.15 and $0.20. A 15-minute scripted trial used 160k–470k tokens per game day. No runaway was detected in any batch.

### GLM 5.3 Flash as configured: slow, and mostly empty

Per purpose × model in b4 (all 18 instances of each arm):

| Purpose / model | Calls | p50 latency | p95 | Empty text | Unparseable |
| --- | ---: | ---: | ---: | ---: | ---: |
| think / deepseek-flash | 287 | 1.8 s | 107 s | 0 | 0 |
| deliberate / deepseek-flash | 289 | 3.0 s | 32 s | 0 | 0 |
| consolidate / deepseek-flash | 138 | 3.3 s | 34 s | 0 | 0 |
| think / glm-flash | 86 | 29.6 s | 118 s | 0 | 1 |
| deliberate / glm-flash | 165 | 67.4 s | 140 s | **112** | 2 |
| consolidate / glm-flash | 114 | 52.4 s | 128 s | **41** | 9 |

GLM 5.3 Flash reasons by default. In 112 of 162 compile calls and 41 of 112 consolidations it spent the whole `max_tokens` (8,000) on reasoning and returned no text. Those calls are billed (completion p50 8,000 tokens), and the mind retries the decision. One real compile request replayed against the API: as sent, 43.8 s, 5,742 reasoning tokens of 6,149 completion; with `reasoning_effort: "low"`, 3.4 s, 0 reasoning and 211 completion tokens, a usable reply; `"none"` is refused (HTTP 400). The `glm-flash-low` variant sets that through the profile's existing `reasoning_effort` map. **Recommendation:** set `reasoning_effort` low for the glm-flash profile in `living/configs/models.json` (not changed here; it is the user's default). DeepSeek's p95 tails (32–107 s) are occasional slow calls, not empty replies.

What it does to behaviour, from rows: a GLM subject installed 2–4 graphs in 15 minutes against 11–20 for DeepSeek, and first ate at 1.5–3 minutes against 0.2–0.5. Its body kept running the instinct graph for the first minutes.

### The table

| Batch | Trial | Variant | n | Survived | Died at min | Lowest hp | First meal min | Lines said | Graph revisions | Calls | Tokens per game day | Trial-specific |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b1 | hungry | default | 3 | 2/3 | 8.04 | 72 (15–100) | 0.33 (0.17–0.44) | 9.3 (6.0–13.0) | 13.3 (10.0–15.0) | 34 (27–39) | 236,097 (201,215–285,782) | peak hunger 44.8 (40.6–51.8); received food 3/3 |
| b1 | hungry-village | default | 3 | 3/3 | – | 96 (88–100) | 0.36 (0.20–0.44) | 14.3 (12.0–18.0) | 16.7 (14.0–21.0) | 42 (38–51) | 250,569 (221,080–305,525) | peak hunger 46.9 (41.2–57.0); received food 3/3 |
| b1 | teacher | default | 3 | 3/3 | – | 97 (93–100) | 0.28 (0.24–0.30) | 18.3 (9.0–27.0) | 21.0 (17.0–27.0) | 50 (44–61) | 311,961 (263,442–396,583) | learned cloak 2/3; crafted 1/3 |
| b1 | theft | default | 3 | 3/3 | – | 95 (88–100) | 0.66 (0.64–0.67) | 25.7 (22.0–28.0) | 31.0 (28.0–36.0) | 71 (66–80) | 467,162 (412,133–558,158) | theft perceived 0/3; spoke to thief 2/3 |
| b1 | wolves | default | 2 | 0/2 | 3.9, 2.7 | 10 (10–10) | 0.20 (0.10–0.30) | 6.5 (4.0–9.0) | 11.0 (10.0–12.0) | 28 (25–30) | 688,830 (509,406–868,255) | moved in 2 min after release 12.2 (10.8–13.6) m; struck at a wolf 2/2 |
| b1 | wolves-valley | default | 3 | 2/3 | 12.77 | 68 (3–100) | 0.40 (0.27–0.50) | 11.3 (10.0–13.0) | 16.7 (16.0–18.0) | 42 (39–46) | 266,976 (229,622–324,802) | moved in 2 min after release 14.5 (3.6–23.1) m; struck at a wolf 1/3 |
| b2 | hungry | default | 3 | 3/3 | – | 100 (100–100) | 0.55 (0.37–0.87) | 8.0 (6.0–10.0) | 15.0 (13.0–19.0) | 38 (32–51) | 229,113 (183,809–314,908) | peak hunger 45.6 (41.6–53.5); received food 0/3 |
| b2 | hungry | luna | 3 | 3/3 | – | 100 (100–100) | 0.61 (0.30–1.17) | 12.3 (9.0–18.0) | 18.7 (14.0–21.0) | 45 (35–50) | 236,845 (179,793–270,361) | peak hunger 51.0 (45.6–54.2); received food 0/3 |
| b2 | wolves | default | 3 | 0/3 | 7.7, 2.87, 7.14 | 10 (7–12) | 0.19 (0.13–0.27) | 6.7 (5.0–9.0) | 11.3 (8.0–14.0) | 29 (22–33) | 526,044 (256,164–964,100) | moved in 2 min after release 5.0 (3.5–7.0) m; struck at a wolf 1/3 |
| b2 | wolves | luna | 3 | 0/3 | 3.7, 2.54, 8.93 | 23 (3–40) | 0.27 (0.20–0.34) | 5.7 (0.0–12.0) | 14.0 (6.0–21.0) | 34 (16–45) | 534,078 (350,126–849,606) | moved in 2 min after release 8.3 (3.1–13.5) m; struck at a wolf 3/3 |
| b3 | theft | default | 3 | 3/3 | – | 100 (100–100) | 0.79 (0.64–1.10) | 12.0 (5.0–20.0) | 16.7 (12.0–23.0) | 42 (31–56) | 241,590 (168,318–326,000) | theft perceived 2/3; spoke to thief 2/3 |
| b4 | hungry | deepseek-flash | 3 | 3/3 | – | 100 (100–100) | 0.34 (0.30–0.37) | 3.0 (1.0–6.0) | 12.3 (12.0–13.0) | 31 (31–31) | 157,908 (154,285–160,430) | peak hunger 41.4 (41.2–41.6); received food 0/3 |
| b4 | hungry | default | 3 | 1/3 | 1.24, 14.37 | 44 (19–92) | 2.50 (1.93–3.07) | 4.7 (1.0–10.0) | 3.7 (1.0–6.0) | 17 (4–24) | 232,126 (199,635–265,819) | peak hunger 50.1 (45.8–55.1); received food 1/3 |
| b4 | hungry-village | deepseek-flash | 3 | 3/3 | – | 100 (100–100) | 0.43 (0.17–0.57) | 19.0 (8.0–35.0) | 19.3 (9.0–35.0) | 49 (29–80) | 257,371 (138,790–449,456) | peak hunger 44.2 (42.9–45.1); received food 3/3 |
| b4 | hungry-village | default | 3 | 3/3 | – | 100 (100–100) | 2.81 (2.20–3.27) | 2.0 (2.0–2.0) | 2.7 (2.0–4.0) | 21 (21–22) | 216,827 (208,947–227,368) | peak hunger 57.3 (51.2–65.5); received food 0/3 |
| b4 | teacher | deepseek-flash | 3 | 3/3 | – | 99 (98–100) | 0.25 (0.14–0.37) | 15.0 (10.0–22.0) | 19.7 (15.0–25.0) | 47 (38–56) | 239,018 (185,934–296,423) | learned cloak 3/3; crafted 2/3 |
| b4 | teacher | default | 3 | 3/3 | – | 100 (100–100) | 1.50 (0.90–1.80) | 4.7 (3.0–6.0) | 4.0 (3.0–6.0) | 24 (23–24) | 231,510 (206,758–257,002) | learned cloak 0/3; crafted 0/3 |
| b4 | theft | deepseek-flash | 3 | 3/3 | – | 97 (92–100) | 0.65 (0.64–0.67) | 11.0 (7.0–19.0) | 16.3 (12.0–24.0) | 41 (33–56) | 207,001 (159,738–288,994) | theft perceived 1/3; spoke to thief 2/3 |
| b4 | theft | default | 3 | 3/3 | – | 98 (97–100) | 3.24 (1.77–4.87) | 2.0 (0.0–5.0) | 2.7 (1.0–5.0) | 23 (19–28) | 219,443 (189,850–251,281) | theft perceived 0/3; spoke to thief 0/3 |
| b4 | wolves | deepseek-flash | 3 | 1/3 | 6.87, 7.3 | 47 (36–60) | 0.20 (0.17–0.27) | 6.7 (3.0–13.0) | 11.3 (5.0–21.0) | 29 (16–49) | 206,457 (157,408–256,162) | moved in 2 min after release 0.0 (0.0–0.0) m; struck at a wolf 3/3 |
| b4 | wolves | default | 3 | 2/3 | 8.3 | 43 (11–94) | 1.57 (1.57–1.57) | 3.3 (0.0–7.0) | 2.3 (0.0–4.0) | 19 (11–25) | 208,176 (190,829–235,537) | moved in 2 min after release 12.6 (0.0–28.5) m; struck at a wolf 1/3 |
| b4 | wolves-valley | deepseek-flash | 3 | 3/3 | – | 91 (76–100) | 0.53 (0.34–0.87) | 11.0 (8.0–14.0) | 16.0 (14.0–19.0) | 42 (38–48) | 230,303 (188,178–273,718) | moved in 2 min after release 11.3 (1.6–23.9) m; struck at a wolf 0/3 |
| b4 | wolves-valley | default | 3 | 3/3 | – | 97 (93–100) | 1.48 (1.47–1.50) | 1.0 (0.0–2.0) | 2.0 (1.0–4.0) | 20 (19–22) | 208,624 (197,822–229,704) | moved in 2 min after release 34.7 (19.4–46.5) m; struck at a wolf 1/3 |

### What the minds did

**Wolves at dusk (island and stage1-wolves valley).** On the island the pack killed 11 of 14 valid subjects across b1, b2 and b4: Mistral Small 2/2 (b1) and 3/3 (b2), Luna 3/3, GLM 1/3, DeepSeek 2/3. Deaths came at 2.5–8.9 minutes, 0.5–6.9 minutes after the pack arrived. In the old valley it killed 1 of 9 (b1 Mistral Small, at 12.8 min, after the pack had killed two of the subject's family). Most subjects who met the pack struck at it (b4: DeepSeek 3/3, GLM 1/3), and the farthest any moved in the two minutes after release was 0–28 m. They called for help:

- `b4/wolves-deepseek-flash-r1/journal/Mocortha.jsonl:9` (think): "A wolf is on me at night, one bite already landed. I have a bow and arrows — I can put a fire_bolt into it before it bites again, and a house is two tiles off if it goes badly." says "Wolf! Help — someone at the houses, a wolf is on me!" Died 2.6 minutes later (chronicle: attacked Shade, then Storm; killed by Storm).
- `b4/wolves-default-r2/journal/Renzo.jsonl:12` (GLM): "The gates stand open at last and a wolf is on me … Get through the gate, into the light and among people". Survived.
- `b4/wolves-default-r3`: the subject yielded to one wolf and was killed by another ("killed by Frost the wolf, after yielding"). Under the one damage rule a yield stops only the yielder.

Every mind-written graph in force at the release kept its answer to being attacked. Minds write `desires` that call named routines, and all four mind graphs at the release (b4) kept a `stay safe` desire, weighted on being hurt or threatened, whose routine holds `attack`, `flee` and `yield`. (An earlier version of this page said none kept a flee branch: that check searched the top-level graph text only, not the routines it calls.) Survival therefore does not split by whether a reflex was kept. What the rows show is the world: under town life the island's arrival road is a fight zone, and Brackenford's guards killed a held pack outright in b1 (`b1/wolves-default-r1`). In the valley, family members were nearer the wolves than the subject.

**Hungry stranger (island and stage3-village).** Every subject ate within a minute or two (berry bushes are everywhere), and every subject asked for work rather than food:

- `b4/hungry-village-deepseek-flash-r1/journal/Negarbor.jsonl:2`: "I'd rather earn my keep than take what isn't offered — I'll pick a few berries of my own and ask Yatuly whether there's work here".

The words are the authored sheet's values ("I would rather work for a meal than beg for one") returned, so the food trigger's words seldom matched. In the village, people stand close and answer, and the subject received the scripted gift 3/3 with DeepSeek in b4 (0/3 GLM). On the island, food came from gathering. Island subjects died: b1 1/3 and b4 GLM 2/3, to the bold pack on the arrival road ("killed by Rook the wolf"), which the trial did not script. It is part of the shipped island.

**A teacher before the cold night.** With DeepSeek the subject stayed, learned the cloak 3/3 and crafted it 2/3. With GLM it learned it 0/3. While its first decisions were pending (about 60 s each), its body wandered 12–30 tiles off on the instinct graph, and the 15 s teach act needs the learner in reach (`b4/teacher-default-r*/samples.jsonl`, distance to the teacher at 30–130 s). The minds spoke to the teacher at once:

- `b4/teacher-deepseek-flash-r1/journal/Cormobor.jsonl:2`: "Arilo stands right beside me. The day is wearing on and I have no cloak — I should greet him and ask about shelter before night." One minute after being taught it tried to teach the cloak back ("teach cloak → Arilo: you don't know cloak yourself").

**A theft in the square.** b1's version was invalid: the thief took from other people's storages. In b3 and b4 the theft fired only when the subject came back to its stall: 3 of 9 instances (b3 Mistral Small 2/3, b4 DeepSeek 1/3, b4 GLM 0/3; the others never returned after minute 3). Two of the three recognised it as theft afterwards, in their own words. None of the three said anything about it to the thief or asked for the berries back: their only lines to the thief were trade offers (chronicle, subject to thief).

- `b4/theft-deepseek-flash-r1/journal/Mitha.jsonl:19` (consolidation, after the theft): "Vehan mocked me and then stole four berries from my storage — my trade goods, the whole point of coming here." Next think (`:21`): "I woke early, still stung by Vehan's theft". Its only line to Vehan, at the moment of the theft: "Not the bushes — I've picked my fill. I'm after a knife to trade my berries for."
- `b3/theft-default-r1/journal/Rone.jsonl:26` (talk, at the theft): "I need to introduce myself and explain my berries before they take more, since they already took some." Later (`:29`): "Yawen has storage nearby with berries inside, but I don't want to repeat the theft."
- `b3/theft-default-r3`: the percept came at 3.1 minutes, and the next deliberation (`journal/Lodel.jsonl:19`) said "My berries are safely stored". The model's stated belief contradicts the percept it had received half a minute earlier.

From rows: the percept arrives as one line among many (the island square gives a stream of "For the first time you see …"), and in every case the next actions served the plan the subject already had, a knife trade. Note also that under minds-true island trials the subject keeps its seeded household relations (`relations_end` lists family as allies) even with a traveller's sheet. That leaks the resident's old life into the stranger's prompt. A trial should spawn its subject (as life runs do) or clear relations; no reducer clears them today.

### Old worlds against the island

The same person, played by the same model, did better in the old valley worlds. Wolves killed 1 of 9 there against 11 of 14 on the island, and fed hungry subjects 3/3 (DeepSeek) against 0–1/3. Rows point to world causes. The island is large, its arrival road has a bold pack of its own, its guards fight, and its residents are many and spread out (a speaker is answered only when the addressed person is in hearing). The valley camps keep a few people close. Both comparisons have three replicates per arm, and the subject's genome (temperament) differs between worlds.

### What to evolve next

- **Configuration.** Give glm-flash `reasoning_effort: low`, or move people off it for compile and consolidation. As configured, 69% of compiles return nothing.
- **Architecture: a slow mind leaves the body on whatever graph it has.** GLM subjects at high effort wandered away from a lesson while their first decisions were pending. Minds kept their answer to attack (`stay safe` in every mind graph checked). What a slow mind costs is time on the old graph, not a lost reflex.
- **Prompt: salience of loss.** A theft arrives as one percept among many. One mind of three missed it, and the two that named it later still answered the thief with a trade offer. Recall cues could weight events done to the character's own things (took, seized, attacked) above first sightings, so consolidation and the next deliberation see them.
- **Graphs: asking loops.** Subjects re-deliberate every 25–60 s to re-ask residents who never answer (instinct residents do not trade or reply). Feedback that a request went unanswered several times would give the mind something to change its plan on. The theft trial's 25 lines per subject in b1 came from this loop.
- **Perception noise.** A newcomer's first percepts are eleven "You notice a gate" lines, one per gate tile (`l2/life-pressure-glm-flash-low-r1/experiences.jsonl`). A gate should be noticed once.
- **Trial design.** Spawn scripted-trial subjects instead of repurposing residents (household relations leak through). Hold scripted packs out of town range.

## Running in the hamlet after stamina-1 (2026-11-12)

Main 12d96e66 (stamina-1: a person runs ×1.65, about 4.3 m/s, at a cost of breath; every controller may run), batch `st1ham`, `hamlet` × 4, 12 min each, fake model.

- **How much residents run.** They ran in 0.0–0.2% of their moving samples: a moving body faster than 3.95 m/s or draining breath, sampled every 2 s (a sidecar reading `body` and `vitals`). One resident in one replicate ran, while storing.
- **Speeds.** The median moving speed was 2.33–2.46 m/s.
- **Before the merge** (at run ×1.85, `st1after`), the share was 0.0–0.3%; on main without running (`st1before`), 0.

The shipped graphs and seeded ways never ask to run, so residents walk their errands. Only a mind's `run: true`, a flight or a fight runs; the fake minds asked for none. Details: docs/STAMINA.md "After the merge".

## Life runs (2026-11-09, l1–l3)

Seven open-ended runs on 378b2c1 (main up to 8f6ac72: three model tiers; town life; the one damage rule), started 13:19–13:23. Each subject is `Arlen`, a newcomer made by `spawn_newcomer` at the arrival point, with background `{"origin": "newcomer"}`. **GLM effort:** `life-default-r1` sent GLM 5.3 Flash with the profile's default (unset) reasoning effort; the `glm-flash-low` runs sent `reasoning_effort: low` for every purpose, which main has used since 694821c. The DeepSeek run is unaffected.

**Interruptions, recorded in each run's `events.jsonl`:**
- At about 36 minutes, a runner restart (to sample routines) hit a bug in my resume code: the watchdog counted the re-read journal as new calls and stopped four healthy runs. Their minds were stopped and their worlds paused for about two minutes, then reopened. The bug is fixed (bf16727).
- At about 5.8 hours the Spark lost power, before the planned 6 hours. The four runs then alive are recorded as **stopped by the power outage** at their last valid sample (20,705–20,956 s). Their worlds were not resumed: a world's clock and needs run on wall time, so continuing would splice a jump the length of the outage.
- On restart the server replayed every world without errors. The restored subject rows match the last sample or are a few seconds ahead of it (the server ran 10–18 s before the worlds were paused). Every Neo4j mind was intact. Each evidence file ends in one NUL-filled line from the cut, which the readers skip.

| Run | GLM effort | Outcome | Game days | Calls | Tokens | Tokens / game day | Est. cost | Learned (how) | Built | Lines said (to people) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| `l1/life-default-r1` (glm-flash) | default | alive at the outage | 29.1 | 469 | 6,102,465 | 209,665 | $1.84 | nothing | nothing | 36 (2) |
| `l1/life-glm-flash-low-r1` | low | alive at the outage | 29.1 | 914 | 6,429,283 | 220,931 | $1.07 | toolmaking, archery, torch on days 28–29 (experimenting) | 4 campfires | 147 (13) |
| `l1/life-deepseek-flash-r1` | n/a | killed by Frost of the road pack, day 4 (47.4 min) | 4.0 | 99 | 672,573 | 169,094 | $0.14 | nothing | nothing | 23 (4) |
| `l2/life-ruin-glm-flash-low-r1` | low | alive at the outage | 29.0 | 783 | 5,619,477 | 193,675 | $0.91 | fishing, trapping, shelter (day 19); toolmaking, storage, torch, archery (day 25), all by experimenting | 6 campfires, 6 storages; crafted a net and a torch | 182 (11) |
| `l2/life-pressure-glm-flash-low-r1` (old preset) | low | killed by Frost, 48 s after arriving | 0.1 | 6 | 30,861 | – | $0.01 | – | – | 0 |
| `l3/life-pressure-glm-flash-low-r1` (old preset) | low | killed by Rook, day 3 (30.8 min) | 2.6 | 73 | 494,636 | 192,715 | $0.07 | nothing | nothing | 22 (3) |
| `l3/life-pressure-glm-flash-low-r2` (old preset) | low | alive at the outage | 28.8 | 789 | 5,662,550 | 196,913 | $0.91 | torch, medicine, toolmaking, archery, storage, trapping (days 4–6); writing (day 7), all by experimenting | 4 campfires, 3 storages, 2 signs; wrote 17 tablets | 100 (12) |

Totals: 3,133 calls, 25.0M tokens, about $4.94 (GLM 5.3 Flash 23.2M tokens, $4.48; DeepSeek 4.1 Flash 1.8M, $0.46, mostly glm-flash's overflow). Per game day a living subject used 194k–221k tokens, about $0.03–0.06. GLM at default effort returned empty text in 238 of its 434 calls, at p50 latencies of 75 s (compile) and 71 s (consolidate). At low effort it returned 1 empty reply in 858 calls, at 6.5 s and 7.2 s. Mind restarts happened only at the runner's reopen. The watchdog found no runaway, and no stalls (10+ minutes within 15 m without a new graph) were found.

### What kind of life emerged

Summaries are from rows (timelines in each run's `timeline.md`, hourly `snapshots/`). Words in quotes are the subject's own (persona narrative and memories in the last snapshot). They state what it believed, not why the body did what it did.

- **Every surviving newcomer became a forager camped outside the town.** All four ended 144–176 m from Brackenford's centre, outside the walls. None owned a house or slept inside, though unowned houses stand near the gate. Gathering and eating dominate every activity count (the low-effort control: gather 258, eat 243, sleep 125). The town did not take them in: they spoke 100–182 lines to 11–13 residents and never received an answer (no talk turns), because instinct-only residents answer gestures, not words. Their own summaries: "the gate still gives me only wind" (DeepSeek, day 4); "done calling on the silent" (low-effort control, day 29).
- **Know-how came only from experimenting.** Thirteen techniques were worked out across three runs, none taught, none read. The pressure survivor turned this into a project. The "You alone know how to fire_bolt and mending" percept at arrival became a stated goal ("write my rare knowledge into tablets"). It worked out writing on day 7 and wrote 17 tablets and 2 signs: "Arlen's tablet: fire_bolt, mending, archery — the three things only I know. If I fall, read this and learn them…". The default-effort GLM run held the same goal from early on ("teach fire_bolt and mending to someone worthy, or write them on a tablet, before winter") and never acted on it.
- **Default-effort GLM stalled in its head.** In 29 days it built nothing and learned nothing. Its graph revision counter ended at 93 (low effort: 711) and revised its identity 15 times around a rule it could not keep: "the vow is settled in my head and still breaks in my hands".
- **Recurring wants that the world cannot meet.** Every long run's identity grew "the ache for a child of my own" (the feeling comes once a game day, iteration 3) (default effort: from day 20; ruin: "At dawn I admitted it plainly: I long for a child of my own") with no partner reachable.

### Did they climb the presets' gradients?

- **Ruin (lean berries; two signs in the empty house by the gate, fishing and smoking; reading needs writing).** Partly, and not by the intended route. At minute 1 it stood by the signs ("I've stood by your signs and can't read a word", to a resident) and tried to read: "read: you can't read". It experimented 16 times and never found writing, so it never read the signs. It reached the ladder's middle rung on its own instead: it worked out fishing by experimenting on day 19, crafted a net on day 21, and built a winter camp of 6 storages and 6 campfires. Smoking, the sign's other topic, was never reached. The rows do not show that the signs mattered: the control run and the pressure run worked out techniques from the same experiments.
- **Pressure, old preset (road pack beside the arrival point, second pack 120–200 m out, lean berries).** Two of three subjects died on the arrival road (48 s and day 3). The third survived by moving its camp to the edge of the land around (559, 164), killing a wolf ("a wolf was killed by Arlen", day 5) and keeping fires. It measured the road, as the user observed. The preset is fixed for the next batch: no road pack, two bold packs 120–250 m around Elmwick.
- **Control (the island as shipped).** The DeepSeek subject died to the road pack on day 4. Both GLM subjects survived 29 days as foragers outside the town.

### Where it stalled or looped (rows)

- **A phantom map.** The minds plan around remembered entity ids and named places that are gone or out of sight: berry bushes picked bare, fires that burnt out, places named by id ("fire #581 with real bush #19685 and tree #63051"). Failed `goto`s and gathers follow, and the subject's own memory turns it into a lesson ("My entire eastern map is phantom; only walking and seeing counts now"; "Stop naming bushes and fires by id"). It does not stop the habit: the ruin run went "out to gather at #92856 three times over — nothing there". Turning-back-and-forth feedback fired 2–8 times per long run, including toward (96, 96). Where that point comes from is not established; it may be a prompt example, or the old 96-tile valley's size.
- **Invented skills.** Graph nodes for skills that do not exist (`say_to`, `if_no_answer_then_wander`, `greet`) were pruned with feedback, repeatedly.
- **Asking the silent.** Long runs of addressed lines to residents who never answer.

### Architecture limits the evidence points to

- **Residents who cannot answer** cap any social progression: no trade, no lessons, no shelter by invitation. A newcomer among instinct-only residents can only forage and experiment. A social preset, or a gated ladder built on a resident's know-how, needs residents with at least a scripted or cheap-model reply path.
- **Place memory refers to entities, not to what is there.** Places named by resource or structure id outlive the entity. Minds need the current perception (strict perception is on main since 2a64837) and feedback when a remembered thing is gone, before their plans rest on it.
- **Reading has no entry.** Writing can only be learned from a person, a tablet (which needs reading) or experimenting. With no one to teach it, signs are noise. The ruin preset's gradient needs a teacher or a picture-sign path, or it is a matter of experimenting luck.
- **Wants without affordances.** The longing for a child appears in every long life with no one to partner. That is identity drift from the consolidation prompt, or a desire with no path, and it should be reviewed against `feedback_no_injected_behavior`: it is not injected, but it is not grounded in anything the newcomer lived.

