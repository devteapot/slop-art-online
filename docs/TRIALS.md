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

The verify harness runs there too, against the trial container: `VERIFY_STDB_CONTAINER=slop-trials-stdb VERIFY_STDB_PORT=3320` make `verify.py`, `living/tools/stdb`, `verify-llm` and `verify-minds` use it instead of `sao-living_spacetimedb_1` on 3300. Other surface scripts (`verify-client`, `verify-generation`, `verify-knowledge`) still assume 3300.

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

A life trial (`"kind": "life"`, [`life.json`](../living/trials/life.json)) has no timeline. One mind-backed newcomer lives in the island world for `minutes` (360: six hours, 30 game days at the 12-minute day). Every other character is an instinct-only resident: the island as shipped (`rules.minds` false), with town life layer 1 (daily rhythm, gestures, weather, the wolves of the town road, guards).

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

Batch b4 is the reference for current rules. Its island predates the buildings-table update in 3f3caf0 (lots and footprints changed; rules did not). b1–b3 are kept as history. Every variant is single-profile for people: one profile thinks, compiles, talks and consolidates for a person. The models config has no per-purpose mix for people yet. When it does, a variant names one through its `models` patch, which is merged into the config as given.

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

No mind-written graph in force at the release kept a flee branch (b4: 4 mind graphs, none with `flee`). The two subjects still on the starting instinct (which has one) split one survival, one death, so these runs do not show that dropping the reflex killed them. The difference between worlds has a row-level cause, not a mental one. Under town life, the island's arrival road is a fight zone, and Brackenford's guards killed a held pack outright in b1 (`b1/wolves-default-r1`). In the valley, family members were nearer the wolves than the subject.

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
- **Architecture: reflexes under a slow mind.** No mind-written graph kept a flee branch, and a slow mind leaves the body on whatever graph it has (GLM subjects wandered away from a lesson). A bodily `first` layer the mind cannot silently drop would be injected behaviour, so it is not proposed. Better feedback is: tell a deliberation which reflexes its new graph drops ("your new plan has no answer to being attacked"), as the prune warnings already do for invalid branches.
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
- **Recurring wants that the world cannot meet.** Every long run's identity grew "the ache for a child of my own" (default effort: from day 20; ruin: "At dawn I admitted it plainly: I long for a child of my own") with no partner reachable.

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
