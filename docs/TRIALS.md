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
| `subject.pick` | Who the subject is: `kind`, `stage`, `bg` (background fields, e.g. `{"town": "Elmwick"}`), `group`/`not_group` (the k-th town or band in id order), `lacks` (techniques not known), `fewest_know_how`, `nearest` (an anchor), `count`. |
| `subject.clear_items`, `subject.background` | Drop everything carried (through the ordinary `drop` act), and replace the background, usually with an authored sheet ([authored worlds](AUTHORED_WORLDS.md)) so that the subject starts as the same person in every replicate and world without a model call. |
| `cast.<role>.pick` | Scripted characters, picked the same way. |
| `timeline` | Steps. `"at": "prepare"` runs right after publishing, `"at": "start"` at the start hour before the mind starts, `"at": <minutes>` during the run, and `"when": {…}` on a trigger. An entry is one step or has `steps`, each with an optional `after` (seconds). |
| `probes` | Probes the trial is about (all probes are computed for every trial). |

Steps (`do`): `place` (`to`: an anchor), `graph` (a graph, `instinct:<name>` from `instincts.json`, or `original`: the graph the character had before the trial changed it), `items`, `know`, `say` (`text`, `to`), `act` (`act` or `acts`: `do` nodes), `structure`, `background`, `kill`, `clear_routines`, `clear_items`, `call` (any admin reducer), `note`.

Anchors: `{"arrival": true}` (the island's `land.arrive_*`), `{"town": "<name>"}` or `{"group": k}` (a settlement's `town_center`, a band's `camp`), `{"who": "<role>"}`, `{"structure": "<kind>", "near": …}`, `{"far_from": …}`, `{"xy": [x, y]}`; then `offset: [dx, dy]`, or `away: <anchor>, distance: d` (d tiles from the point, directly away from another anchor).

Substitutions in steps: `"$<role>"` is that character as a target (`{"id": n}`), `"$addressee"` the person the subject just spoke to (in a `said` trigger), `"$<role>_xy"` where the role stands now (`"$subject_xy+9,0"` with an offset, `"$subject_xy@pack:9"` 9 tiles from the subject toward the pack).

Triggers (`when`): `said` (`by`, `to`: a role or `any` person, `words`/`without`: word stems), `near` (`who`, `of`, `within`), `hour`; with `max`, `per_addressee`, `after_min`.

**Variants** ([`variants.json`](../living/trials/variants.json)) are named mind settings: a whole models file (`models_file`) or a patch to [`living/configs/models.json`](../living/configs/models.json) (for example `{"default": "deepseek-flash"}`, or `{"species": {"wolf": {"think": "ministral-3b"}}}`), and environment (`LIVING_LESSONS`, `LIVING_GROUNDS`, `LIVING_LOD`, …). The runner removes the config's `groups`, `assign`, `rotate` and `stages`, so people think with the variant's default profile and its overflow; the `species` map (animals' `think`, `remember` and `compile`) is kept. The current variants are `default` (glm-flash, `zai-glm-5-3-flash`, overflow deepseek-flash), `deepseek-flash` (`deepseek-v4-1-flash-1017`, overflow glm-flash), `glm`, `mistral-large`, `ministral-14b`, `lessons`, `grounds` and `lod`. In `--fake` runs every profile keeps its place in the routing but is answered by the fake server under the name `fake-<model>`, so the journal shows where each call was routed.

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

Each instance is a database `verify-trial-<batch>-<trial>-<variant>-r<k>` on the trial service and one `living-mind` process. Its evidence directory, `.local/living/trials/<batch>/<trial>-<variant>-r<k>/`, holds:

- `cast.json`: who played whom, their backgrounds, and the subject's genome (temperament differs between worlds);
- `actions.log`: every reducer call with its status; `events.jsonl`: every step and trigger as it fired, and any refusal;
- `samples.jsonl`: the subject every 2 s (hour, position, health, hunger, energy, activity and target, inventory, plan, distance to each role, how many of each role are alive);
- `graphs.jsonl` (each behaviour graph revision), `thoughts.jsonl`, `experiences.jsonl` (the subject's percepts, which the authority deletes once consolidated), `chronicle.jsonl` (rows touching the subject or the cast), `mind_rows.jsonl` (relation, judgment, persona, know-how, place and structure rows whenever they change);
- `journal/`: the mind's journal, with the actual requests and replies; `mind.log`, `models.json`, `mind-env.json` (no secrets);
- `final.json`: the subject's rows at the end; `summary.json`: the probes.

The run stops at `minutes`, at a token cap if the trial or `TRIALS_TOTAL_TOKENS` sets one (none does by default), when the runaway watchdog fires (below), 20 s after the subject dies, or when the mind exits (a life run restarts it instead). Deleted databases leave their replica directories in the volume (about 0.4 GB each for an island world); run `trials.py reclaim` after large batches.

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

### Results of the wide batch (finished 22:58)

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

**Measurement, not caps.** Trials run with `LIVING_LLM_PER_MIN` off and no token cap (a trial file can still set `budget.tokens` or `budget.calls_per_min`). The runner counts calls and tokens per model, per purpose and per game day from the journal. A watchdog stops a run and records why when it shows a runaway: 30 failed calls in 5 minutes, the same failure 15 times in 5 minutes, more than 60 calls in a minute, or five mind restarts in 30 minutes.

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

