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
| `budget.tokens`, `budget.calls_per_min` | The trial's token cap (the runner stops the mind when the journal reaches it) and `LIVING_LLM_PER_MIN`. |
| `subject.pick` | Who the subject is: `kind`, `stage`, `bg` (background fields, e.g. `{"town": "Elmwick"}`), `group`/`not_group` (the k-th town or band in id order), `lacks` (techniques not known), `fewest_know_how`, `nearest` (an anchor), `count`. |
| `subject.clear_items`, `subject.background` | Drop everything carried (through the ordinary `drop` act), and replace the background, usually with an authored sheet ([authored worlds](AUTHORED_WORLDS.md)) so that the subject starts as the same person in every replicate and world without a model call. |
| `cast.<role>.pick` | Scripted characters, picked the same way. |
| `timeline` | Steps. `"at": "prepare"` runs right after publishing, `"at": "start"` at the start hour before the mind starts, `"at": <minutes>` during the run, and `"when": {…}` on a trigger. An entry is one step or has `steps`, each with an optional `after` (seconds). |
| `probes` | Probes the trial is about (all probes are computed for every trial). |

Steps (`do`): `place` (`to`: an anchor), `graph` (a graph, `instinct:<name>` from `instincts.json`, or `original`: the graph the character had before the trial changed it), `items`, `know`, `say` (`text`, `to`), `act` (`act` or `acts`: `do` nodes), `structure`, `background`, `kill`, `clear_routines`, `clear_items`, `call` (any admin reducer), `note`.

Anchors: `{"arrival": true}` (the island's `land.arrive_*`), `{"town": "<name>"}` or `{"group": k}` (a settlement's `town_center`, a band's `camp`), `{"who": "<role>"}`, `{"structure": "<kind>", "near": …}`, `{"far_from": …}`, `{"xy": [x, y]}`; then `offset: [dx, dy]`, or `away: <anchor>, distance: d` (d tiles from the point, directly away from another anchor).

Substitutions in steps: `"$<role>"` is that character as a target (`{"id": n}`), `"$addressee"` the person the subject just spoke to (in a `said` trigger), `"$<role>_xy"` where the role stands now (`"$subject_xy+9,0"` with an offset, `"$subject_xy@pack:9"` 9 tiles from the subject toward the pack).

Triggers (`when`): `said` (`by`, `to`: a role or `any` person, `words`/`without`: word stems), `near` (`who`, `of`, `within`), `hour`; with `max`, `per_addressee`, `after_min`.

**Variants** ([`variants.json`](../living/trials/variants.json)) are named mind settings: a patch to [`living/configs/models.json`](../living/configs/models.json) (for example `"default": "luna"`) and environment (`LIVING_LESSONS`, `LIVING_GROUNDS`, `LIVING_LOD`, …). The runner removes the config's `groups`, `assign`, `rotate` and `stages`, so the subject always thinks with the variant's default profile and its overflow.

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
python3 living/tools/trials.py run --batch b2 wolves hungry --variants default,luna --replicates 3
python3 living/tools/trials.py report --batch b2         # .local/living/trials/b2/report.md
python3 living/tools/trials.py clean --batch b2          # delete databases and Neo4j minds; evidence kept
python3 living/tools/trials.py ledger                    # real tokens per batch against the total cap
python3 living/tools/trials.py down                      # stop the containers (kept)
```

Each instance is a database `verify-trial-<batch>-<trial>-<variant>-r<k>` on the trial service and one `living-mind` process. Its evidence directory, `.local/living/trials/<batch>/<trial>-<variant>-r<k>/`, holds:

- `cast.json`: who played whom, their backgrounds, and the subject's genome (temperament differs between worlds);
- `actions.log`: every reducer call with its status; `events.jsonl`: every step and trigger as it fired, and any refusal;
- `samples.jsonl`: the subject every 2 s (hour, position, health, hunger, energy, activity and target, inventory, plan, distance to each role, how many of each role are alive);
- `graphs.jsonl` (each behaviour graph revision), `thoughts.jsonl`, `experiences.jsonl` (the subject's percepts, which the authority deletes once consolidated), `chronicle.jsonl` (rows touching the subject or the cast), `mind_rows.jsonl` (relation, judgment, persona, know-how, place and structure rows whenever they change);
- `journal/`: the mind's journal, with the actual requests and replies; `mind.log`, `models.json`, `mind-env.json` (no secrets);
- `final.json`: the subject's rows at the end; `summary.json`: the probes.

The run stops at `minutes`, at the trial's token cap, at the batch's total cap (`TRIALS_TOTAL_TOKENS`, default 6,000,000, counted across real batches in `.local/living/trials/ledger.json`), 20 s after the subject dies, or when the mind exits. A batch whose worst case (instances × each trial's cap) exceeds what is left is refused unless `--allow-partial`.

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
| [`life-pressure`](../living/trials/life-pressure.json): a pressure | berry bushes at 30%; a second bold pack of five ranging 120–200 m from the arrival point beside the shipped pack of four | survive the first nights on a wolf road → safety (the walled town and its gates, fire, shelter) → food where berries are scarce (the bow, fishing, trapping, the town's gardens and stores) → a place that holds |

Measured: `resource_scale` thins the land's wild bushes but not the planted garden and field bushes. On the island, `life-ruin` has 12,158 berry bushes and `life-pressure` 9,219, against 18,216 in the control (67% and 51%, not 40% and 30%). `life-pressure` has 15 wolves (6 + 4 + 5).

**Engine features presets would need and do not have** (listed, not built):
- a wolf range that grows over the days (packs have a fixed home; the runner could move them on a schedule, but that is a script, not a world);
- a scarcity knob per season or region (winter already stops regrowth; nothing makes one season or one place leaner);
- resources by region, for a richer, more dangerous frontier such as the unroaded eastern massif (`resource_scale` is global);
- residents who respond: instinct-only residents never teach, trade or answer a request, so a social hook (an ailing elder, a household short of a worker, a stall that needs goods) has no one to make it a hook; town life layer 1 answers gestures only;
- residents with minds beside the subject: that is a lab, and costs one mind each.

### Watching a run live

The trial service listens on the LAN: `http://192.168.1.103:3320` (container `slop-trials-stdb`, started with `TRIALS_STDB_BIND=0.0.0.0`). Anonymous connections see the public tables, which is everything a watcher needs; no admin identity is involved.

- **Observer (read-only, recommended):** native, from a checkout on any LAN machine: `LIVING_SERVER=http://192.168.1.103:3320 LIVING_DB=<database> cargo run --manifest-path living/Cargo.toml --release -p living-viewer`; or the web observer, `just living-web` and then `http://127.0.0.1:8330/?server=http://192.168.1.103:3320&db=<database>`. It subscribes and never calls a reducer. Life-run databases are `verify-trial-<batch>-life-<preset>-<variant>-r1`, listed by `trials.py report --batch <batch>`.
- **Game client:** `LIVING_SERVER=http://192.168.1.103:3320 LIVING_DB=<database> cargo run --release --manifest-path living/Cargo.toml -p living-game` connects, but it always calls `join` when its identity has no living character. That puts a player newcomer into the trial world, who is perceived by the main character and changes the run. The client has no spectator mode, so a watcher cannot attach without joining. Joining needs no admin rights (a fresh identity, its token kept in `.local/living/game/<db>.token` or `LIVING_GAME_TOKEN`), but it is not watching. Following the main character from the game client needs a watch mode in the client, not built (UI work, listed).

## Results

(Filled in from the batches below.)
