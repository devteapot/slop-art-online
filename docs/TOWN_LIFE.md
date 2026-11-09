# Town life, layer 1: daily rhythm and non-verbal social behaviour

Started 2026-11-09. This note records how residents of the island's settlements live a visible daily rhythm with no model calls: what they do hour by hour, the skills and starting graphs that do it, the data clients read to draw it, the SpacetimeDB documentation the design rests on, and what was measured and verified.

**Layers (agreed with the user).** Layer 1: routines and non-verbal social behaviour on behaviour graphs, run by the authority every tick. Layer 2 ([below](#layer-2-residents-who-answer)): a resident someone engages gets a live mind through the mind service, under level of detail. Nothing in either layer is canned speech.

**Status.** Implemented on branch `townlife-1` and verified on scratch `verify-*` databases on the dev-box (SpacetimeDB 2.14.1, scratch container `slop-townlife-stdb`). No lab or reference world was touched and no model was called.

## Rules this follows

- **Routines are made of skills.** Everything a resident does is a skill the rules define (`living/scripts/skills.rhai`: `_check`, `_duration`, `_done`), chosen by the resident's own starting graph. The graphs are seed content (`living/seeds/island.json`, `ways`), not Rust: there is no routine library and no decision in the engine. They are starting graphs; a mind can rework them like any other.
- **Gestures are skills.** `wave`, `nod`, `face`, `step_aside`, `keep` and `play` have their rules in the script and their catalog entries in `living/rules/src/catalog.rs`. Players use them through `human_act`, residents through their graphs: the same `act::begin`, checks, durations and effects.
- **The engine picks primitives by trait, never by skill name**, as combat does: `<skill>_shows()` declares what others see and which primitive applies (`faces`, `turn`, `aside`, `record`). The meaning of a gesture to the one it is made at is an effect the script returns (`hail`).
- **Presentation goes through public data**, like `skill_card` and `fighter`: `act_card` and `doing`, plus a `weather` row. `living/game` was not edited; what it must draw is listed below.

## SpacetimeDB documentation consulted (2026-11-09)

Pinned: `spacetimedb = "=2.14.1"`, `spacetimedb-sdk = "=2.14.1"`, image `clockworklabs/spacetime:v2.14.1`. The live pages' version selector reads 2.0.0. The one claim that needed the pinned source (row-level security on event tables is not enforced in 2.14.1) was checked there for [combat](COMBAT.md#spacetimedb-documentation-consulted-2026-11-09), and is relied on as recorded.

| Page | What it says | What follows here |
|---|---|---|
| [Tables](https://spacetimedb.com/docs/tables/) | Public tables are "Exposed for client read access through subscriptions. Writes still occur only through reducers"; private ones are "Visible only to reducers and the database owner". "organize data by access pattern, not by the entity it describes"; "Separate data you read at different times or frequencies." | What anyone looking sees (`doing`, `act_card`, `weather`) is public and small. What a gesture means to its target (`mind_state.hailed_ms`, `hailer`) stays in the private-in-spirit runtime row graphs read. Static cards are apart from the per-character row. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/) | Splitting tables "Improves update performance by touching fewer rows" and "Reduces data transferred to clients who don't need all fields"; "Be mindful of unbounded table growth". | `doing` is about 30 B, written only when a shown skill starts and deleted when it ends: one row per character at most. `skill_use` keeps the last 24 uses per character, as before. No table grows with time. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | Indexes "consume additional memory and slow down inserts and updates"; "Primary keys and unique constraints automatically create indexes." | No new btree index. `doing` and `weather` have only primary keys; places are found through the existing `place.actor` index. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | "Subscriptions with the same lifetime should be grouped together"; "subscribe to the new set before unsubscribing from the old one." | `act_card` and `weather` are subscribed once per connection; `doing` joins the body window like `fighter`. |
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) | Rows "exist only for the duration of the transaction that created them"; clients get `on_insert` only and cache nothing. | Not used. A sleep or a stall kept lasts minutes, and a client that walks up later must see it; a gesture is short but needs the same row shape. Their only filter, RLS, is unenforced in 2.14.1 (above). |
| [Views](https://spacetimedb.com/docs/functions/views/) | Per-sender views use `ctx.sender`; "views can only access table data through indexed lookups"; per-sender views cost "1,000 separate view computations" for 1,000 users. | A player perceives an answer to its greeting as an `experience` row (already per-controller). No new view. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) | "Adding new tables" is always allowed; "New columns must be added at the end of the table definition" with a default value. | `weather`, `act_card` and `doing` are new tables; `mind_state.hailed_ms` and `hailer` are appended last with `#[default(0)]`, so a running world updates in place with `--keep-data`. |
| [Default values](https://spacetimedb.com/docs/tables/default-values) | "The expression must be const-evaluable"; new columns with defaults go at the end. | `#[default(0u64)]`, `#[default(0u32)]`. |
| [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables) | Repeating reducers come from `ScheduleAt::Interval`; missed ticks are skipped. | Weather needs no schedule of its own: the existing 1 Hz housekeeping refreshes the row and writes only on a change. |

## Design

### Places a resident knows

A resident finds home, work, the square and an evening spot as remembered places: `place` rows (`actor`, `name`, `x`, `y`), the table minds already project their named places into and graphs already read through `{"place": NAME}` (indexed by `place.actor`). World creation writes them once per resident (`town::seat`, called from `island::settle`), from seed data:

```json
"town_life": {
  "places": {"square": ["plaza"], "inn": ["inn", "hall", "plaza"]},
  "evening": ["inn", "square"],
  "work": {"farmer": ["field", "garden", "plaza"], "fisher": ["fishing_spot", "plaza"], "trader": ["market_stall", "plaza"], …}
}
```

- A kind is a lot kind of the resident's own settlement (`lot.settlement`; fields and gardens at their centre, buildings at their door), a resource or structure kind within 1.5 × the settlement's radius (`fishing_spot`, `gate`), or `plaza` (the settlement's square). The first kind that has a spot wins.
- Work is spread over the settlement's matching lots: the nearest of the least used. Only a spot a path reaches from home counts (`Map::path`, at most four candidates per kind); a fishing spot across a river or a walled yard is skipped.
- `evening` alternates by household between the inn and the square.
- `home` needs no row: it is the household's door (`character.home_x/home_y`, set when the household claims the house at its door; `Target::Home` already falls back to it).
- Cost at world creation: 158 ms for 262 residents in 8 settlements (`init.town.seat` spans); 942 place rows, never rewritten. Nothing per tick scans settlements, lots or households.

### Starting ways

A seed may carry its own `ways` (`island.json`): `common` routines that replace or add to `repertoire.json`'s by name, an `occupations` entry per occupation (routine name and graph), and the desires `top`. `seed::give_repertoire` takes the seed's entry first, then the seed's `habits` set, then the repertoire. Lab seeds have no `ways` and are unchanged.

The island top level, in the order a resident weighs it (each is a routine of skills; a desire that cannot act now falls through to the next):

| Desire | Weight | Routine | What it does |
|---|---|---|---|
| safety | 2.0 + threatened × 3 + hurt × 1.2 | stay safe | Hurt and losing near a wolf: flee; losing otherwise: yield; still struck: flee; hurt: attack the attacker; a wolf within 10 with two others near and in good health: attack it; a wolf within 12: flee. Fails at once when none applies. |
| shelter | −0.2 + rain × 1.2 | get out of the rain | Under a roof (within 2.5 of home, an inn, a hall or any house door): rest. Far from home: the nearest inn, hall or house. Else home. |
| food | −0.5 + hunger × 2 + starving × 1.5 | find food and eat | The repertoire's: eat what one carries, take food from a store in sight, gather. |
| sleep | −0.7 + tired × 1.3 + night × 0.6 + exhausted | sleep | At home: sleep; else go home and sleep. |
| greet | hailed × 2.2 | answer a greeting | Nod back within 5 tiles, else wave back. |
| look | commotion × 1.6 | watch what happens | Face the fight or death, then pause. |
| manners | 0.9 | mind the people near me | Face whoever just spoke to me; standing still with someone within 2.5 tiles: step aside if they come at me in a narrow place, else face them. Fails at once when nobody is there or they are already faced. |
| evening | 0.8 | spend the evening out | 17:30–22:00, not raining: go to my evening place, nod to someone now and then (chance 0.03 a check), rest. |
| work | 0.2 + day × 0.5 | the occupation's routine | Go to work and keep the post (below). |
| home at night | −0.1 + night × 0.5 + winter × 0.3 | keep warm | At home: sleep below 90 energy, else rest; else go home. |
| a family, company | as in the repertoire | keep close to my partner, be with people | Unchanged. |

Work routines (`ways.occupations`): every one goes to `{"place": "work"}` when more than a few tiles away and then `keep`s its post, with the trade's own work first: farmers gather at the field's bushes and store a full pack at the square; fishers gather fish at their spot and store it; cooks and innkeepers cook fish at a fire in sight; scribes read the nearest sign; healers tend someone in sight below 70% health; guards face a wolf in sight. Children's work is `play`: back home when more than 14 tiles from both home and the square, else play, wander, play.

### Gestures and what they mean

| Skill | Takes | Gives | `_shows()` |
|---|---|---|---|
| `wave` | someone in sight within 12 tiles, 1.2 s | `hail`: they see you wave at them | gesture; faces, record |
| `nod` | someone within 6 tiles, 0.7 s | `hail` | gesture; faces, record |
| `face` | something or someone in sight, 0.6 s | the body turns where it stands | turn; faces, turn, record |
| `step_aside` | someone coming at you where at most 19 of the 25 tiles around are open | a pace (1.2 tiles) to the side of their path | step; aside, record |
| `keep` | 10 s at one's post, not a child | being seen at work | work |
| `play` | 4 s, not a baby | a little fun, 0.5 energy | play |

Engine primitives, chosen by trait (`living/authority/src/act.rs`, `motion.rs`, `town.rs`):

- **`faces`**: when the skill starts being performed, a standing body turns on the spot toward its target at the `turn_rate` law (`motion::face`): one `body` write, drawn as the segment's turn. A walking body keeps its steering heading.
- **`turn`**: turning is all the skill does, so facing its target already (within the `face_slack` law, 0.35 rad) it is refused before its rules are asked. Without this, every standing resident asked the script once a second whether it already faced its neighbour (about 160 checks a second in town).
- **`aside`**: a short walk to a point a pace to the side of the creature it targets (`living_rules::social::aside_point`: the side of their path one already stands on, else the other), at 0.8 × walking speed. It needs that creature to be coming toward the actor; otherwise it is refused before its rules are asked ("no one is coming your way"). The rules weigh how fast (`closing` ≥ 0.5 tiles/s) and how narrow (`a.actor.room`).
- **`record`**: each use is kept in `skill_use` from intention to outcome, like a combat move.
- **`hail`** (an effect): the target's `mind_state.hailed_ms` and `hailer` are set and it is woken; it perceives "X greets you (wave)." A gesture back at someone who greeted me within 10 s *answers* them: they perceive "X answers your greeting (nod).", and they are not greeted again. Without that, two residents waving at each other would keep answering forever.

New facts for the script (`living_rules::script`): `a.raining`, `a.target.bearing` (how far the actor would turn to face the target), `a.target.closing` (how fast a creature comes at the actor), and `a.actor.room` (walkable tiles in the 5 × 5 square, filled only for an `aside` skill).

### Weather

`weather` (one public row): `raining`, `since_ms`, `until_ms`, `forced_until_ms`. A world's climate is seed content: the island seed says `"weather": {"spell_s": 180, "rain_share": 0.2}` (the sky changes every 180 real seconds, four spells a 12-minute day, and a spell rains with probability 0.2). Housekeeping (1 Hz) draws the current spell from the world seed and the spell's index, the first spell of a world always dry, and writes the row only when it changes. A seed without `weather` never rains, so lab worlds keep the weather they had (none) and their needs are unchanged. The admin scene reducer `set_weather(raining, secs)` holds the weather for `secs` seconds (`0` hands it back). The day length is unchanged.

- Graphs read it as `{"raining": true}` and the desire signal `rain`.
- Rain is felt: a person out from under a roof (`near_shelter`) tires faster in the rain (energy −2.5 a minute, −1 with a cloak; `wet(a)` in `rates`), and the needs rate key includes the rain, so rates settle when it starts or stops.

### Commotion

Target `"commotion"` and desire signal `commotion`: the nearest `attack`, `assault`, `threat`, `killing` or `death` chronicle row of the last 8 s within sight. A fight's row is refreshed at every blow (the chronicle merges repeats), so it stays recent while the fight lasts. The recent rows are read once per transaction through the `chronicle.at_ms` index and shared by every evaluation in it.

### New conditions, targets and weights (the behaviour grammar)

`{"raining": bool}`, `{"hailed": seconds}`, `{"moving": bool}`; targets `"hailer"`, `"commotion"`; weights `rain`, `hailed`, `commotion`. The normalizer accepts `rain`, `greeted`, `walking`, `standing` and `greeter` as aliases; the mind service's grammar text names them (`living/mind/src/prompts.rs`). Varying ways for the young draws the new weights after the older ones, so ways without them vary exactly as before.

### Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| World creation: places | the settlement's planned lots (in memory), resources and structures in the chunks round it, members by community, backgrounds | `place` (about 4 per resident) | `membership.community`, `resource_node.chunk`, `structure.chunk` | place subscribers | once | none |
| Weather refresh | `weather` (1 row) | `weather` when it changes | PK | weather subscribers | 1 Hz read, about 4 writes a day | none |
| Raining, in an evaluation | `weather` once per transaction | — | PK | — | per evaluation (cached) | — |
| A place target | `place` rows of the actor | — | `place.actor` | — | per resolution | — |
| Commotion | `chronicle` rows of the last 8 s, once per transaction | — | `chronicle.at_ms` | — | when a graph weighs `commotion` | — |
| A shown skill starts or ends | — | `doing` (insert or update; delete) | PK | body-window subscribers | per shown activity | at most one row per character |
| A gesture lands (`hail`) | both `mind_state` rows | target's `mind_state`; `experience` for a player or mind; `wake` | PK | the target's controller | per gesture | experiences as before |
| `face` | body | body (a turn) | PK | body-window subscribers | per turn | none |
| A walk to an unreachable spot | a 15 s module cache per body and tile | — | — | — | per retry | bounded (4,096 entries, pruned) |

No whole-world scan was added to a routine action or the tick.

## What residents do, hour by hour

A census of an undisturbed island world (`core-town-census`: no scenes, no player, the world's own weather), once per world hour for a day: 189 adults and 52 children, 34 animals. "Home" is within 3 tiles of the household's door, "work" within 6 of the resident's `work` place, "evening place" within 8 of its `evening` place. Rows: `.local/living/verify/core-town-census/town-census.json` on the dev-box.

| Hour | Home | Work | Evening place | Elsewhere | Most common activities (all residents) |
|---:|---:|---:|---:|---:|---|
| 07:54 | 6 | 115 | 0 | 68 | keep 105, goto 73, play 19, wait 15, gather 14 |
| 08:48 | 6 | 143 | 3 | 36 | keep 127, goto 32, gather 24, play 20 |
| 10:48 | 6 | 141 | 8 | 31 | keep 134, goto 25, play 21, gather 12 |
| 12:48 | 6 | 143 | 10 | 27 | keep 133, goto 20, play 18, gather 13 |
| 14:48 | 6 | 141 | 12 | 27 | keep 125, goto 20, play 19, face 13 |
| 16:48 | 7 | 139 | 13 | 27 | keep 133, play 21, goto 19, face 16 |
| 17:48 | 6 | 43 | 67 | 70 | rest 120, goto 85, face 11, nod 2 |
| 18:48 | 6 | 43 | 109 | 28 | rest 167, goto 21, face 14, nod 9 |
| 19:48 | 6 | 43 | 125 | 12 | rest 190, face 15, nod 7 |
| 21:48 | 6 | 43 | 125 | 12 | rest 178, wait 13, nod 9, face 9 |
| 22:48 | 104 | 6 | 14 | 62 | sleep 107, goto 65, face 25 |
| 23:48 | 155 | 6 | 13 | 12 | sleep 183, face 16, wander 10 |
| 01:48 (rain) | 172 | 3 | 4 | 7 | rest 223, wait 12, goto 7, eat 3 |
| 04:42 (rain) | 175 | 3 | 4 | 2 | rest 227, wait 12, eat 3 |
| 06:42 (rain) | 175 | 3 | 4 | 2 | rest 198, wait 13, eat 3 |

- **Morning (06:00–08:00):** work outweighs staying home once it is day, and people walk to their workplaces (73 walking at 07:54). On this world it rained from 01:48 into the morning, so at 06:42 everyone was still under a roof: the shelter desire outweighs work while it rains.
- **Day (08:00–17:30):** about three in four adults are at their workplace, keeping stalls, workshop doors, gates and the inn, gathering at fields and fishing spots, storing at the square. 17–24 children are playing at any moment, near home or the square. The 27–36 "elsewhere" are walking between work and the square's stores, eating, or at a workplace more than 6 tiles from its marked spot.
- **Evening (17:30–22:00):** the inn and the square fill (125 of 189 adults by 19:48), people sit (rest), turn to whoever comes near and nod to one another. The 43 still "at work" work at the inn or on the square (cooks, innkeepers, traders), which is also their evening place.
- **Night (22:00–06:00):** they go home (104 at 22:48, 155 at 23:48, 175 from 02:00) and sleep there until rested, then rest at home until morning.

The scripted scenes on fresh worlds (below) record the same rhythm as rows, and the reactions to a player, rain and a wolf.

## Measurements

**Tick cost at rest, base against this change** (`living/tools/bench.py`, one 600 s window each, the module's tick spans). Dev-box: 32-thread AMD x86_64, Fedora, rootless podman, SpacetimeDB 2.14.1 in the scratch container. Each arm is a fresh `island` world (seed 7, 2048 m), measured from 32 s after publishing, with no minds, no subscribers and no players. The arms ran back to back (`~/townlife-bench.sh`): base `b12fa45` 09:00:47–09:10:52 UTC, then this change 09:11:33–09:21:39. Other users were logged in; the 1-minute load average, sampled every 30 s, was 1.83–3.52 during the base window and 2.59–3.79 during this change's.

| Arm | People + animals | Ticks/s | Evaluations/s | Completions/s | Steering updates/s | p50 | p95 | p99 | Max | Over 16.7 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base `b12fa45` | 259 + 34 | 60.0 | 366 | 80.1 | 147.7 | 1.15 | 2.23 | 3.12 | 6.01 | 0 of 36,016 |
| town life | 264 + 33 | 60.0 | 366 | 69.6 | 44.2 | 1.33 | 2.25 | 2.80 | 8.60 | 0 of 36,015 |

Times in ms. Phases (ms of work per second, base → change): slot evaluations 39.2 → 40.7 (p99 2.70 → 1.66), wakes 13.4 → 15.9, activity timers 8.6 → 17.4, motion 9.1 → 3.5. Residents now spend their day keeping a post rather than wandering, so steering updates fall to about a third. Activity timers, which complete keeps, rests and gestures, double. The p50 is 0.18 ms higher. The p99 is 0.3 ms lower, because the base's wandering and gathering ticks are spikier, and it stays under the 4 ms bar. The maximum is 8.6 ms, a single tick, against 6.0. The island's own weather was dry in the base window and rained for the last two minutes of this change's (`~/townlife-bench/branch-load.txt`), so the window includes people walking to shelter. This is one window per arm; the spread between repeated windows was not measured here. This is the island at rest for 10 minutes. It is not the contract's 216-character gate with observers and players, nor its 8 hours.

**On the way there** (60 s windows at minutes 1–2 of fresh worlds, same machine; [validation](../.agents/skills/verify-core/references/validation.md)):
- The first version measured p50 1.99, p99 4.74 ms, against the base's 1.37 and 2.59 at the same world age.
- Temporary spans (not committed) showed two causes. The "mind the people near me" routine asked the rules about 330 times a second whether to step aside or turn: a full skill context each time, refused by the script (32 ms/s). And about 11 walks a second to unreachable places spent the whole A* budget, retried every second.
- Fixes: `turn` and `aside` refuse cheaply in the engine before the script is asked; seeding gives only reachable places; a 15 s cache remembers unreachable destinations per body. After these: p50 1.33, p99 2.60 against the base's 1.37 and 2.59.

**World creation:** `init.town.seat` took 158 ms in all for 8 settlements (92 ms for the walled town), checking paths from homes to candidate places. The island's `init` is otherwise unchanged (`init.land.generate` 2.2 s on a loaded box).

**Rows:** about 942 `place` rows (four per resident), written once; `doing` holds one row per character performing a shown skill (176 a minute into a world, 44 on the default seed); `act_card` 17 rows; `weather` one row. `skill_use` stays bounded at 24 per character. No table grows with time.

## What the client must draw

The list below is what the game client needed; it draws all of it since 2026-11-09 ([game brief, "Town life in the client"](GAME_BRIEF.md#town-life-in-the-client-2026-11-09)). To show town life it needs:

1. **Subscribe** `act_card` and `weather` once per connection (both small and static or nearly so), and join `doing` to its near body window as it joins `fighter`: `SELECT doing.* FROM doing JOIN body ON doing.id = body.id WHERE <window>`.
2. **Activities** from `doing.code` → `act_card.skill`, and by `act_card.look` for a skill it does not know: `work` (keeping a stall or a workshop door, gathering at a field bush or a fishing spot, cooking at a fire, storing, reading a sign, tending someone), `eat`, `sleep` (lying at the house door), `rest` (sitting), `play` (a child skipping or running about), `gesture`, `turn`, `step`. `doing.x/y` is where its target is (the bush, the fire, the person); `doing.target` the creature it is aimed at; `since_ms`/`until_ms` the timing.
3. **Gestures**: `wave` (an arm raised, 1.2 s) and `nod` (0.7 s), toward `doing.target`. The authority has already turned the body to face them (`body.heading` + `turn` × `turn_s`), so the client only plays the clip.
4. **Facing and turning on the spot**: a standing body's segment now often carries a turn at zero speed (`face`, and the turn before every gesture). `living_rules::steer::pose` already evaluates it; a client that draws a standing body's heading from `heading` alone would miss it.
5. **Making way**: `step_aside` is ordinary body motion (a short walk); `doing` with look `step` names it.
6. **Weather**: draw rain from `weather.raining` (from `since_ms`), not from the client's own clock, so everyone sees the same rain the residents shelter from. The look-dev weather can stay for non-connected mode.
7. **A player's own gestures**: send `human_act` with `{"do": "wave" | "nod" | "face", "target": {"id": N}}` (F to interact is the natural key). The answer arrives as the resident's `doing` row and as the player's `experience` "… answers your greeting (nod)."; the player's own use is in `my_skill_uses`.
8. **Places** (optional): `place` rows name a resident's `work`, `square`, `inn` and `evening`, if the client wants to show where someone works.

## Verification

Free tiers only: scratch `verify-*` databases on the run's own container (`slop-townlife-stdb`, SpacetimeDB 2.14.1, behind a `docker` name shim, as in [island authority](ISLAND_AUTHORITY.md#verification)), no mind service, no model call. Evidence is under the dev-box worktree's `.local/living/verify/`.

**Scenes** (`.agents/skills/verify-core/scripts/town.py`, [feature map](../.agents/skills/verify-core/features/town.md)). Admin scene reducers used: `set_weather` (new: rain for 120 s in the rain scene, and a dry sky held for the rest of each run so the seed's own weather does not mix in), `place_at` (the player beside a resident; a bold wolf into town) and `kill` (the wolf afterwards). The player acts only through its own identity (`human_act`, `human_move`, `human_say`). No clock compression: the scenes wait for the world's own hours in its 12-minute day.

| Scene | Rows recorded | Result (final full run `core-town-6`; reruns noted) |
|---|---|---|
| Workers reach their workplace by day | positions, activity, `doing`, places | 151 of 191 workers within 6 tiles of their `work` place at 10:00, 132 of them keeping or gathering; Damobor (#22) gathering 4.6 tiles from a workplace 268 tiles from home |
| Children play near home or the square | same | 50 of 58 within 14 tiles of home or the square, 38 playing, wandering or pausing |
| A player's wave gets a wave or nod back | `skill_use` of both, the player's `experience` | the player's wave `greeted Iseosvik`; Iseosvik (#1) nodded from its graph, `answered Visitor`; the player perceived "Iseosvik answers your greeting (nod)." |
| Someone who comes up behind is faced | the resident's `skill_use` | failed in `core-town-6` (the driver placed the player on unwalkable ground); passed in `core-town-7` after the driver fix (Elno #4 faced the player) |
| Someone who speaks is faced | same | Iseosvik faced the player who spoke to it |
| Stepping aside in a narrow way | `skill_use` (outcome `made way`), body before and after | Aripegar (#7), 17 of 25 tiles open around, moved 1.20 tiles; across runs 3 of 4 single approaches got a step (residents look once a second) |
| Rain sends people indoors | positions against shelters, activity | under a roof: 37 of 191 before, 179 of 191 after 40 s of rain (162 resting); 65 of 189 30 s after it stopped |
| A wolf near town | activities, `skill_use` of faces, chronicle | of 32 residents within 14 tiles, 16 fled and 24 fought; 41 residents turned to face the commotion |
| The square fills in the evening | positions, `skill_use` of nods | 142 adults at their evening place at 18:36 (55 at midday); 215 nods or waves by residents in 30 s |
| Sleep at home at night | positions, activity | 153 of 188 adults within 3 tiles of home at 00:30, 132 of them asleep or resting |
| Leave in the morning, for work | positions, activity | at 07:12 128 of 153 had left home, 122 at work or on their way |
| Eat when hungry | `vitals` | after a day, hunger p50 47 and max 85; nobody at 90 or more |

Earlier full runs: `core-town-4` 18 of 19 and `core-town-5` 21 of 21 (both on the rules before the last three fixes: the step aside's latch, the climate moving into the seed, the outcome bookkeeping).

**Surfaces:**

| Surface | What was driven | Result |
|---|---|---|
| Core | `cargo_checks.py`; `scenes.py` tick, needs, seize; skirmish on an island run; `verify_mechanics.py` twice; `verify_steering.py`; the town scenes above | rules 87, authority 10, mind 47, viewer sync 3; tick, needs, seize pass; skirmish 8 of 8; mechanics 21 and 23 of 23 (the documented conception pair failed once), and 23 of 23 on the final code; steering 5 of 5 |
| Player | `verify-player/scripts/gesture.py` (new) and `combat.py` on an island run | gestures 9 of 9 (wave and nod answered, an answer closes the greeting, face turns the body, refusals); combat 23 of 23 |
| Client | `verify-client/scripts/run.py` | all pass with the two known XFAILs; the permission matrix 184 calls, 0 mismatches (`set_weather` admin-only); `act_card`, `doing`, `weather` public |
| Generation | `generation.py` | every seed passes; the island 71 of 71, with the new town-life checks (places, workplaces, starting ways). The first run also found that the wolf count ignored the seed's `packs` (drift from the combat change), now counted |
| Project | `set -o pipefail; just living-check` | exit 0 |
| Bindings | regenerated as `living-generate` does, then `rustfmt` | 7 new files (`act_card`, `doing`, `weather`, `set_weather`), `mind_state` and `mod.rs` changed |

The verification skills' maps were brought up to date for what this change touched (`maintain-verification-skill`, scoped): `verify-core` (new `town.md`, `town.py`), `verify-player` (new `gestures.md`, `gesture.py`), `verify-client` (new `town.md`, the probe's tables, the matrix's `set_weather`), `verify-generation` (the land checks and `seeded-world.md`). Each touched feature was driven live. The other features' maps were not re-read from source.

## Open risks and limits

- **Reactions run at the evaluation rate.** Residents weigh their desires once a second (immediately on a wake). Someone who walks past within a second can be passed by without being faced or made way for: across runs, 3 of 4 single approaches through a narrow lane got a step aside. Waking a resident when someone comes close would close that gap at a cost per approach; it was not built.
- **Long commutes lean on the path budget.** Workplaces are spread over a settlement's lots, so some residents walk far (268 tiles from home to a fishing spot in one run). `Map::path` keeps its 6,000-expansion budget; a resident whose place it cannot reach gets "no path there" and the 15 s cache stops it searching again every second, but it keeps standing. Seeding chooses only reachable places, so this happens only when the map changes (a shut gate, a new wall). Hierarchical routing remains the fix ([island open risks](ISLAND_AUTHORITY.md#open-risks)).
- **The unreachable cache is module state**, like the map cache: it relies on module instances being reused, and a lost entry only costs one search.
- **Evening greetings are frequent.** With the chance of a nod at 0.03 a check, a full square makes about 7 gestures a second (each a rules check, a `doing` row and a `skill_use` row). It is a starting graph; a resident can rework it, and the number is the seed's.
- **Everyone shelters from all rain.** The shelter desire outweighs work, so a rainy morning keeps the whole town at home until it stops (the census world's rain from 01:48 did). Outdoor work in the rain is a graph a resident could learn; rain only tires.
- **Children and old people** follow the same top level, scaled by their own needs; elders do not retire from work.
- **Perception.** `doing`, like `fighter` and `body`, is public and windowed by clients; it is not a permission boundary ([game brief, core work 1](GAME_BRIEF.md)).

## Left for layer 2

The items below were the list when layer 1 shipped; [layer 2](#layer-2-residents-who-answer) answers speech, remembering and the minds' places. Greeting choice stays with the minds.

- **Speech.** Residents still never speak, and nothing here writes a line. A resident turns to face someone who speaks to it (`heard_within`) but cannot answer. Conversation through the mind service, with level of detail for residents far from any player, is layer 2.
- **Minds keep their places.** With `rules.minds = true` the mind service replaces `place` rows from the mind graph after every change, which would drop the seeded `work`, `square`, `inn` and `evening` places. A mind-driven world needs those anchors in the starting mind (`place:work`), or the projection must keep authority-seeded places.
- **Greeting is not yet chosen.** Residents answer greetings and nod to someone now and then in the evening; whom one greets and how warmly (friends, strangers, enemies) is left to relations a mind would write.
- **Remembering who greeted whom** is not kept: `hailed` is a moment, not a memory. A mind would integrate the experience.

# Layer 2: residents who answer

Started 2026-11-09. **Status:** phase 1 (the authority side) is on main as `6f0d9d7`. Phase 2 (the mind service side, the stage cap, the `host` act, the free tier end to end and a small paid run) is on branch `townlife-2`, built on main after the `harness-1` merge (`015707b`); see [phase 2](#phase-2-what-was-built).

**Why.** The island's life runs (TRIALS.md on `trials-1`, "Life runs" and "Architecture limits") had newcomers speak 100–182 lines to residents and get no answer; nobody taught, traded or offered shelter, and every survivor ended up a forager outside the walls. Instinct-only residents answer gestures only.

## Decisions (the user, 2026-11-09)

- Live LLM minds, no canned speech.
- Only residents someone engages get a mind. The others stay instinct-only, with no model cost.
- **A woken resident stays a mind.** It perceives, remembers, writes its graph, decides acts and talks, like any AI character; it does not go back to instinct only. "Asleep" means off stage under the mind service's level of detail, where it thinks about every 10 minutes (€0.03 a person-hour against €0.19–0.20 on stage, [model cost](MODEL_COST.md)).
- **Before waking, residents keep a bounded ring of what they perceived**, so a resident met for the first time remembers the newcomer from the market yesterday. The mind internalizes it in one batch at waking, the way player memory does, before its first deliberation.
- Talk uses the fastest good model; thinking and planning happen on stage under level of detail.
- **Tunables are laws or seed values, not Rust constants or trial flags.** No test-only branches in the engine: tests and trials drive the ordinary paths (player reducers, acts, graphs, generic admin scene reducers). Trial content stays in trial files and seeds.

## SpacetimeDB documentation consulted (2026-11-09)

Pinned 2.14.1 (`living/Cargo.toml`, image `v2.14.1`); the live pages' selector shows 2.0.0. What the pages left open was checked on the running 2.14.1 server (below).

| Page | What it says | What follows here |
|---|---|---|
| [Tables](https://spacetimedb.com/docs/tables/) | Private tables are "Visible only to reducers and the database owner. Clients cannot access them"; "organize data by access pattern, not by the entity it describes"; "Separate data you read at different times or frequencies." | `woken`, `prior` and `prior_head` are private, like `presence`: the mind service reads them as the owner. Checked on 2.14.1: the owner reads them over SQL; a player and an anonymous client get `no such table` (`wake.py`). The ring's per-write head (`prior_head`, 8 B) is apart from its slots, which the mind reads once, at waking. |
| [Access permissions](https://spacetimedb.com/docs/tables/access-permissions/) | "Private tables can only be accessed by reducers and views running on the server." | No view exposes them. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/) | "Be mindful of unbounded table growth". | The ring is a fixed number of slots per resident, overwritten in place (the `woken_ring("slots")` law); `woken` is one row per woken resident; both go at death. Nothing grows with time. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | B-trees support "equality lookups … and range queries"; "Primary keys and unique constraints automatically create indexes"; indexes "slow down inserts and updates". | The page does not say a primary key supports a range scan, so the ring is read through a btree index on `prior.resident` (one per resident), and written through its primary key (`resident << 8 | slot`). `woken.settlement` has a btree for the per-settlement stage cap. Two new indexes, on tables written only by residents' perceptions and by waking. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | "keep subscriptions small"; a filter on a unique column "will use an index". | Phase 2: the mind service subscribes to `woken` (one row per woken resident) and reads a resident's ring once, by `resident`, when it wakes, instead of subscribing to every ring. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) | "Adding new tables" is among the "Safe Changes (Always Allowed)". | Three new tables, no new columns: a running world updates in place. |

## Design

### Waking

**What engages a resident.** The engine reports the facts of an engagement as `"<what>:<by>"` and the `wakes` law in [`skills.rhai`](../living/scripts/skills.rhai) decides (1 wakes, 0 does not; no law, nobody wakes):

- *what:* `speech` (addressed: spoken to by name or id, or the only one close by, as for any listener), the name of a skill aimed at the resident **as it starts being performed** (`wave`, `nod`, `give`, `offer`, `accept`, `teach`, `tend`, `heal`, `join`, `welcome`, `attack`, `strike`, `shoot`, `threaten`, `seize`…), `hurt` (a blow or missile landed) or `theft` (taking from its household's store while it watches);
- *by:* `player` (a person's character), `mind` (what a character under the world's minds decided: a deliberate act, words its mind chose; a woken resident included), `habit` (what such a character's behaviour graph did by itself: its routines' greetings, a graph's `say`) or `instinct`.

The shipped law wakes on all of these when `by` is a player or a mind, and never for a habit or an instinct: a neighbour's evening nod, a wolf's bite or a guard's blow on an island wolf stays at the level of detail it happens at, whether or not the neighbour has a mind. `habit` was added after the first paid run, where woken residents' starting graphs kept nodding to neighbours each evening and woke 11 residents in 9 minutes ([below](#the-paid-runs)). Blows and thefts count as decided. An act wakes its target when it *starts*, not when its effect lands, so a 15 s lesson to someone walking past wakes them and lets their mind decide to stay (the first scene run, which woke at the effect, showed a resident walking off mid-lesson as an instinct-only body).

**Where.** One function, `woken::engage` ([woken.rs](../living/authority/src/woken.rs)), called from `act::perform` (any skill with a creature target), `perceive::speak` (an addressed listener, before it hears the line), `act::damage` (`hurt`) and the store `take` effect (`theft`). Nothing else in the engine knows about waking.

**What waking does.** Per character, independent of the seed's `rules.minds`, the way presence's takeover does it (9ea831f): the resident's `controller` becomes the world admin and `ai` true, so the running mind service takes it up like any AI character (`Minds::mine`), and the engagement it is about to perceive is already an experience of its mind. A private `woken` row records who woke it and how, its settlement, the places it knew, how many perceptions its ring took in, and the last engagement (`engaged_ms`, `engaged_by`, `engagements`) for the stage cap. A first deliberation is requested ("A stranger spoke to you."): the instinct era's graph install is not counted as a thought, so `think_min_s` does not hold it back. Under level of detail that request waits like any other off stage, unless a player is on stage, which an engaging player is.

**The graph.** The resident's starting ways keep running until its mind writes another graph. Nothing is swapped: the mind owns its graph from then on, and because it never goes back to instinct only there is no second graph to restore.

**Places.** The places it knew (its `work`, `square`, `inn`, `evening`) are world facts its starting ways walk to. A mind's projection with a store replaces a character's place rows with the mind graph's set, which would drop them ("Minds keep their places" in the list above); `mind_update` now keeps the places on the `woken` row unless the mind names them itself.

### Who the woken mind is

It starts from what the world holds about the resident, read at waking: its household and family (`parent_a/b`, `home_x/y`), its occupation and background (`background`, the authored sheet where the seed has one), its genome, its lot and settlement (`woken.settlement`), its community, its relations if any, its places, and its ring. The mind service seeds its Neo4j mind from these facts (the same bootstrap an authored resident's sheet gets), then **internalizes the ring in one batch** before the first deliberation, through player memory's internalize path (`lived.rs`, reused once `harness-1` lands): the ring's lines are first-person perceptions with positions and times, like a player's experience rows. Anything the model writes beyond those facts (a persona narrative, values, goals) is marked as the mind's own, `lived_under = ["ai"]` and an `inferred_from: woken` mark, so an experiment can tell world facts from what a model made up. No backstory is invented by the engine.

### The ring before waking

- **What goes in:** every percept an instinct-only person past infancy would have received had it a mind: `perceive::percept` sends it to the ring instead of dropping it. `minds_near` now includes instinct-only people while the rules keep rings, so they witness events (deaths, fights, gifts, trades, crafts, building) by the same sight rule, hear speech, signals and babies, and are told what is done to them (a greeting, a gift). One more source: a player's character coming into view of a resident who sees it back (the player's perceived-set sweep, the only place entering sight is already computed), "A stranger came into view.", noted again only after `sighted_s`.
- **Worded as perceived:** names follow `perceived_of` (a stranger stays "a stranger" until introduced). A resident out of sight or earshot gets nothing. Nothing from other residents' rings, the chronicle or any mind is copied in.
- **Bounded:** `woken_ring("slots")` slots per resident (shipped 24, at most 256), keyed `resident << 8 | slot` and overwritten in place, so the ring holds the newest perceptions; `prior_head` counts how many it took in. The same perception again within `repeat_s` (120 s) is counted in its slot (`times`) instead of taking a new one, so a neighbour's nods do not flush a newcomer's visit. Rows go at death. Laws: `woken_ring("slots" | "repeat_s" | "sighted_s")`.
- **Not knowledge:** it is a buffer of perceptions for one mind, not memory, and nothing reads it but the mind service at waking. No behaviour reads it; instinct-only residents act exactly as before.

### Cost controls

- Waking happens only on an engagement by a player or a mind (the `wakes` law).
- Talk turns go to the talk purpose; phase 2 routes them to the fastest good talker (DeepSeek Flash without thinking: 12/12 judged, p50 1.8 s), through `harness-1`'s per-purpose mixes when they land.
- Deliberation is held off stage by the level of detail (`LIVING_LOD`); a woken resident off stage thinks about every 10 minutes.
- **A stage cap per settlement:** how many woken residents of one settlement may be on stage at full rate at once, the law `woken_stage("cap")` (shipped 6) that the mind service reads from the rules it already subscribes to (`script`). A resident who would go over it takes the stage from the least recently engaged (`woken.engaged_ms`) when it was engaged more recently, else stays off stage. When it binds the service logs it and writes a `stage_cap` entry in the resident's journal (settlement, cap, who is on stage, admitted, displaced). It is engineering, not a rule of behaviour: a capped resident still talks at the off-stage rate.

**Estimates** (prices and rates from [model cost](MODEL_COST.md); not measured for woken residents yet):

| Item | Basis | Tokens | Cost |
|---|---|---:|---:|
| One talk turn (DeepSeek Flash, no thinking) | 1,819 prompt + 122 out | ≈ 1,940 | €0.0005 |
| A conversation, 10 resident turns | 10 turns | ≈ 19,400 | €0.005 |
| Waking: ring internalization, one batch | player memory's measured shape: ≈ 2,300 prefix + 24 lines × 40 + ≈ 700 out; DeepSeek Flash, batch API half price | ≈ 4,000 | €0.001 |
| Waking: first deliberation (think + compile) | two calls at the recommended mix's average for planning (€0.124 an on-stage hour over 92 think and compile calls) | — | €0.003 |
| An engaged resident-hour on stage | recommended mix (GLM Flash low/high) / with talk and consolidation on DeepSeek Flash | — | €0.20 / €0.24 |
| A woken resident-hour off stage | same mixes | — | €0.030 / €0.034 |
| **Every island resident woken, all off stage** | 264 × off-stage rate | — | **€7.9–9.0 an hour** |
| A stage cap of 6 in Brackenford, all on stage, plus 258 off | 6 × €0.24 + 258 × €0.034 | — | €10.2 an hour |

The off-stage rate is the labs' (think and compile 0.125 a minute, talk 0.14, consolidation 0.06); residents keeping a daily routine may think less often than lab characters, which would lower it. A world where every resident has a mind is the labs' cost; waking makes it the worst case, reached only if somebody engages each of them.

### What residents can do

Through the existing acts path (`mind_act` → `acts::submit` → the skill rules), shared by players and minds: `give`, `offer`/`accept` (trade), `teach`, `join`/`welcome` (a community), `found`/`leave`, `wave`/`nod`/`face`, `tend`/`heal`, `write`/`read`, `store`/`take`, `build`, `open`/`close` a gate, `appraise`, and refusing, which is not acting (a mind that declines an offer simply does not accept it; the asker perceives no answer, or the words the mind chose).

**What a newcomer needs that does not exist: shelter.** Sleep near any house is already restful (`near_shelter` is distance only, with no owner), so a newcomer can sleep at a stranger's door, and nothing says whether they may; houses have owners (`structure.owner`) but no guests. The shared skill, built in phase 2 as designed here except that the stay's end is the rules' (`host_done` returns `#{ op: "host", until_hour: 7.0 }`) instead of a separate `host_s` law:

- **`host`** (an act, aimed at a person within 3 tiles; 2 s): `host_check` in `skills.rhai` refuses no living person, oneself and a child. The engine primitive finds the house at the actor's home door (its household's) and refuses without one ("you have no house to offer"); it writes a private `guest` row (`guest`, `host`, `house`, `until_ms`: the next `until_hour` of the world's day), replacing any stay the guest had, gives the guest a `place` row `lodging` at the house (so a graph finds it as `{"place": "lodging"}`), and tells the guest ("X takes you in as their guest until 07:00: a bed in their house (…) and food from their household's store."). It is witnessed and chronicled. Housekeeping ends stays through the `guest.until_ms` index and removes the `lodging` place; a guest's death removes its rows.
- **What it changes:** taking from the house's store is no longer `theft` for a guest; the house owner's household sees the guest as a guest (a stance minds can read). Sleep stays as restful anywhere near a house: the rules gain no new physical effect, only the consent.
- **Players** get it through `human_act` like any act; the client needs one control. It belongs to `verify-player`, `verify-core` (the rule) and `verify-client` (the new table, private).

### No knowledge copying

A woken resident knows the newcomer only from what it perceived: its ring (perceptions worded through its own `perceived_of`), then its experience rows. A resident's ring holds only its own percepts (`wake.py` checks that a resident in earshot keeps an overheard line and that 40 residents out of earshot have none of it). Talking does not move memory: each mind records the same exchange from its side.

## Phase 1: what was built (main, `6f0d9d7`)

| Part | Where |
|---|---|
| `woken`, `prior`, `prior_head` (private) | [tables.rs](../living/authority/src/tables.rs) |
| Engagement, waking, the ring, death cleanup | [woken.rs](../living/authority/src/woken.rs) |
| Hooks: an act aimed at someone starts; addressed speech; a landed blow; a watched theft; a player's character comes into view | `act::perform`, `perceive::speak`, `act::damage`, the store `take` effect, `perception::sweep_one` |
| Percepts of instinct-only people go to their ring; `minds_near` includes them while rings are kept | `perceive::percept`, `perceive::minds_near` |
| A woken resident's places survive a replacing projection | `mind::mind_update` |
| Laws `wakes` and `woken_ring` | [skills.rhai](../living/scripts/skills.rhai) |

No new reducer, no new column, no change to `living/mind`. The verification drivers are listed under [Phase 1 verification](#phase-1-verification).

## Phase 1 measurements

**Tick cost, base against this change** (`living/tools/bench.py`, one 300 s window per arm, the module's tick spans; driver `core-wakebench`, evidence `.local/living/verify/core-wakebench/`). Mac: Apple M4 Pro, 14 cores, 48 GB, Docker Desktop, SpacetimeDB 2.14.1 in `sao-living_spacetimedb_1`. Each arm is a fresh island world (seed 7) published by `verify.py launch --seed island`, measured from 32 s after publishing, with no mind service, no subscriber, and (in the third arm) one player. The arms ran back to back: base 19:40–19:45 UTC, at rest 19:46–19:51, 20 woken 19:53–19:58. The base is a worktree of `14f3a72` with its own rules (no laws, no ring). Other sessions were working on the Mac: the 1-minute load average, sampled every 30 s, was 3.8–6.3 in the base window, 4.0–6.6 at rest and 3.5–8.2 with 20 woken.

| Arm | People + animals | Ticks/s | Evaluations/s | p50 | p95 | p99 | Max | Over 16.7 ms | Tick work, ms/s | Ring entries/s | Experience rows at end |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base `14f3a72` | 256 + 34 | 59.9 | 374 | 2.16 | 3.73 | 4.58 | 11.3 | 0 of 15,320 | 114.5 | — | 0 |
| this change, at rest | 275 + 34 | 59.9 | 394 | 2.12 | 3.84 | 4.92 | 10.0 | 0 of 15,114 | 113.0 | 1.45 | 0 |
| this change, 20 woken | 249 + 33 | 60.0 | 366 | 2.14 | 3.86 | 5.07 | 12.0 | 0 of 15,308 | 113.9 | 2.27 | 1,059 |

Times in ms; "tick work" is the sum of tick durations per second. Phases (ms of work per second, base → at rest → 20 woken): slot evaluations 59.5 → 59.6 → 57.4, wakes 20.4 → 20.7 → 21.8, activity timers 21.2 → 19.2 → 21.0, motion 6.1 → 6.3 → 6.0. The ring's writes happen inside these phases (a percept is written where its event happens) and are not a span of their own.

- **At rest** the p50 and the tick work are unchanged within this machine's noise; p99 is 0.34 ms higher and max lower. One window per arm on a loaded laptop cannot separate a difference this small; it shows no cost at the scale of the 4 ms p99 bar.
- **With 20 woken residents** (woken by the player speaking to them, `wake_many.py`, 53 s before the window) and no mind service: they write experiences instead of ring entries (about 2.4 a second for the 20 and the player) and hold pending deliberations (0.1 requests a second merging into them). p99 is 0.49 ms over the base; tick work is unchanged.
- The worlds differ: 256, 275 and 249 people were alive at the end of the windows of three fresh worlds of the same seed (old age and births in the first minutes, and the third window started 53 s later). Not investigated.
- This is the island at rest for 5 minutes per arm, not the contract's 216-character gate with observers, nor its 8 hours; the mind service's cost is phase 2's.

**The ring** (measured before the `min_salience` floor was added):

| | At rest | 20 woken, a player about |
|---|---:|---:|
| Residents with a ring after 6 min | 201 | 227 |
| New entries a second (two primary-key writes each) | 1.45 | 2.27 |
| Repeats counted in a slot instead (`times` above 1) | 142 | 315 |
| Rows | 504 | 898 |
| Text per row | 42 B | 42 B |
| Most kept slots per resident | 16 | 17 |

- **What filled them** (20 woken arm): residents greeting one another 45% (`… greets you (nod).` 209, `… answers your greeting (nod).` 193), spoiled berries 10%, the player's overheard request 8%, "A stranger came into view." 6%, fights with wolves 4%, babies crying 15%, old-age deaths 1%. Answered greetings (salience 0.15) took a fifth of the slots, so the law now keeps perceptions of salience 0.2 and above (`woken_ring("min_salience")`).
- **Storage:** a row is about 110 B (42 B of text), so a full island (264 residents × 24 slots) is about 6,300 rows and 0.7 MB, plus 264 heads of 8 B. Fixed: slots are overwritten in place and nothing is deleted while a resident lives.
- **Fill time:** one new entry per resident every 140 s at rest, so a ring holds roughly the last hour of a resident's life (less in a busy square, more at night).

## Phase 1 verification

Free tiers only, on the Mac's shared container (`sao-living_spacetimedb_1`, 2.14.1), scratch `verify-*` databases, main `14f3a72` plus this change. No model was called. Evidence under `.local/living/verify/`.

| Surface | What was driven | Result |
|---|---|---|
| Player | `verify-player/scripts/wake.py` (new) on island runs: a player's speech, wave, gift, offer and lesson, an overhearing resident, residents out of earshot, privacy; `gesture.py`, `combat.py` | wake 25 of 25 (`player-wake-4`, final code); gestures 10 of 10; combat 25 of 25 on a fresh world (`player-l2b`; a first world, `player-l2`, had a bolt strike a resident who stepped into its path and an arrow strike a wall) |
| Minds | `verify_minds.py`, all cases, with the new `wake` case: the real `living-mind` and the fake model on an island world | `minds-l2-210035`: 11 pass, consolidation its known XFAIL. In `wake` an offer woke the resident; it answered the newcomer (the think step's `say`, since the line came while it deliberated), took two talk turns answered through `mind_say`, accepted the trade and taught basketry through its own acts, consolidated, and kept its four places through a replacing `mind_update` |
| Core | `cargo_checks.py`; `town.py` on an island run; the three-arm tick bench with `wake_many.py` (new) | rules 108, authority 10, mind 49, viewer sync 3; town 21 of 21; tick as above |
| Client | `verify-client/scripts/run.py` | 30 of 30; 57 private tables refused (the three new ones to the player too); permission matrix 184 calls, 0 mismatches |
| Project | `set -o pipefail; just living-check` (private `CARGO_TARGET_DIR`) | exit 0, before and after regenerating the bindings |
| Bindings | regenerated as `living-generate` does, from the private build | `woken`, `prior`, `prior_head` (table and type each) added, `mod.rs` changed |

What the scenes found and changed on the way: the first deliberation was held back by `think_min_s` because the starting graph's install counted as a thought (waking now clears it); a lesson to a resident walking past never woke it because waking happened when the effect landed (it now happens when the act starts); answered greetings filled a fifth of the rings (`min_salience`).

Not covered: generation (no seed or generation change); the paid tier; Neo4j, recall and the ring's internalization (phase 2); a woken resident's life over hours, off stage under level of detail; the stage cap (phase 2); the `host` act (designed, not built); the contract's 216-character gate.

The verification skills' maps were updated for what changed: verify-player (`waking.md`, `wake.py`), verify-minds (`wake.md`, the `wake` case; `verify_llm.py`'s `start` takes a seed), verify-core (`town.md`, `wake_many.py`), verify-client (`PRIVATE` and the player refusals in `drive.py`, `visibility.md`). Each was driven live. The other features' maps were not re-read from source.

## Phase 2: what was built

Branch `townlife-2`, on main after the `harness-1` merge (`015707b`).

| Part | Where |
|---|---|
| Making a woken resident's mind: identity from the world's facts, then its ring, before its first thought | [mind/woken.rs](../living/mind/src/mind/woken.rs); the wait in `Minds::schedule` |
| The ring taken in through player memory's path (`Source::Ring`: its own system prompt, `lived_under = ["instinct"]`, `woken_upto` on the `self` node instead of `lived_upto`) | [mind/lived.rs](../living/mind/src/mind/lived.rs), `prompts::ring_system`, `Store::woken_upto` |
| The identity's marks: `written_by` and `from_facts` on the identity version | `Store::set_identity` |
| The stage cap, in the level of detail's `watched` and on contact | `Minds::admit` (woken.rs) |
| The `woken` route: woken residents take the models file's `woken` route (shipped: the `people` mix, talk on DeepSeek Flash, on-stage deliberation on DeepSeek Flash `@low`, the rest on GLM Flash) | `ModelsFile::woken`, `Llm::woken_route`, [models.json](../living/configs/models.json) |
| `LIVING_ONLY=woken` (also `12,woken`): this service thinks for residents as they wake, for labs and trials | `Minds::allowed` |
| The `woken` subscription (one row per woken resident); the ring and the settlement's lots read once, at waking, through a subscription dropped after | `main.rs`, `Minds::read_once` |
| Laws `woken_stage("cap" \| "wait_s")` | [skills.rhai](../living/scripts/skills.rhai) |
| Decided against habitual engagements: the `wakes` law's `by` gains `habit` (a minded character's graph doing it by itself), which wakes nobody; speech and acts say whether they were decided | `woken::engage`, `perceive::speak(…, decided, …)`, `act::perform` (`ACT`/`PLAYER` nodes), skills.rhai |
| Names only when known, in what minds are sent: a ring integration writes no feelings toward someone the ring never names (the authority would count the name known) and names them "a stranger" in memory; talk prompts, transcripts and agreements name people as the authority does (`knows_name`: self, family, community, a relation, an introduction) | `lived.rs` (`strangers_stay_strangers`), `Minds::known_as`, `talk.rs`; the `acquaintance` subscription (private) |
| `host`: the skill (`host_check`, `host_duration`, `host_done`, its `skill_io`), the `host` effect, the private `guest` table, the `lodging` place, the theft exemption, the stay's end in housekeeping, death cleanup | skills.rhai, `catalog.rs`, `script.rs`, `town.rs`, `tables.rs`, `tick.rs`; minds learn it from the skill reference and the ACTS list (`prompts.rs`); `wakes` includes `host` |

**Making the mind.** The first engagement wakes the resident (phase 1); this service then:

1. reads its ring and its settlement's lots through one subscription, applied and dropped;
2. without a persona, makes its identity: one `consolidate` call with the identity prompt whose background is the world's facts: its background row (town, occupation, household), stage, settlement, community, parents and children, places with the lot each stands at, relations, know-how and the genome's inborn temperament. The people and places in the facts go into its mind marked `world`; the feelings the model wrote about them `ai`; the identity version carries `written_by: model` and `from_facts`; the thought (`kind: awaken`) lists what the model wrote;
3. takes in the ring as one integration (`internalize`, the resident's own route), citing ring lines by synthetic ids above any experience id, and sets `woken_upto`;
4. lets its first deliberation go (a line spoken meanwhile is left to that deliberation, as for anyone deliberating, and answered by its first thought).

A restart finds what is made (a persona; `woken_upto`) and does not repeat it.

**Not built:** the trial runner's support for `life-social.json` (its `needs`), which lives on `trials-1`; batch mode for the ring (a resident's first answer waits for it, and batch jobs took 24–47 s); a cap on how many residents a mind may wake.

## Phase 2 verification

Free tiers on the Mac's shared container (2.14.1), scratch databases and a scratch Neo4j, main `015707b` merged into `townlife-2`.

| Surface | What was driven | Result |
|---|---|---|
| Knowledge | `verify-knowledge/scripts/woken_mind.py` (new): the whole flow with the real `living-mind`, the fake model and a scratch Neo4j, `LIVING_ONLY=woken`, level of detail on | `knowledge-woken-10` (final code): 7 of 7, the seventh that nothing sent to any woken resident's model names a newcomer who never said its name. `knowledge-woken-4` (before the name fixes): 6 of 6. A resident in earshot kept the overheard "I am Wren, new here…" and stayed instinct only; spoken to, it woke and its mind was made before its first deliberation (awaken, internalize, deliberate, in that order); the identity request carried the facts and no perception; the ring request carried the overheard line and nothing after waking; the graph marks `world`, `ai` and `instinct`; it answered, a later line took a talk turn on the woken route's talk model; its acts gave the newcomer berries, taught it cooking and took it in (`guest`, `lodging`); the seventh woken resident of Brackenford took the stage from the least recently engaged (cap 6, logged and journaled); all stayed minds |
| Player | `host.py` (new), `wake.py`, `gesture.py` on fresh island runs | host 11 of 11 (twice) (a resident's graph hosts the player; the player learns `lodging`; the stay ends at the rules' 07:00; onlookers see theft from the household's store before the stay and none during it; a player hosting itself is refused; `guest` private); wake 25 of 25 (one world, `player-tl2b-wake`, 22 of 25: no second resident stood within 8 m of the first; two fresh worlds after, 25 of 25); gestures 10 of 10 |
| Minds | `verify_minds.py`, all cases | MINDS_RESULT |
| Core | `cargo_checks.py`; `town.py` on an island run | rules 109, authority 10, mind 64, viewer sync 3; town 20 of 21 (`core-town-tl2`: the step-aside scene's three approaches got no step; residents look once a second, the gap recorded under layer 1's open risks) |
| Client | `verify-client/scripts/run.py` (`guest` in `PRIVATE`; also `harness-1`'s `judged` table and `mind_judged` reducer, which the inventory lacked on main and stopped the driver) | `client-tl2c`: 30 of 30; 59 private tables refused (the new `guest` to the player too); permission matrix 194 calls, 0 mismatches |
| Project | `set -o pipefail; just living-check` (private `CARGO_TARGET_DIR`) | exit 0 |
| Bindings | regenerated from the module | `guest_table.rs`, `guest_type.rs`, `mod.rs` |

What the free tier found on the way: verify-knowledge's `player_session.py` read `character` as the player, which the scoped default refuses (it now reads `my_characters`); a lesson the model chose had a prerequisite the newcomer lacked and was refused by the rules (correct; the driver now picks a lesson from the rules' `requires`); the newcomer's real name reached a woken resident's talk prompt though the resident was never told it (fixed: `Minds::known_as`, below).

REALRUN

## Open risks (layer 2)

- **Cascades.** A mind's decided engagement still wakes (`by = mind`): in the second paid run one resident proposed a family to a neighbour and would have woken it. Routines no longer do (`habit`, after the first paid run woke 11 residents through routine nods in 9 minutes). The stage cap bounds the cost on stage, not the number of minds; the law can stop `mind` wakes if trials show runaway waking.
- **A relation still reveals a name.** The authority counts a name known when a mind has feelings about someone (`knows_name`, docs/PERCEPTION.md). A ring integration now writes no feelings toward someone it never heard named, and the mind service names people in talk prompts, transcripts and agreements only as the authority does (`Minds::known_as`). Ordinary consolidation of any mind can still write a feeling toward a stranger it met, after which the authority gives that mind their name. That rule predates this work; changing it is a perception decision, left open.
- **Rings are reset by nothing but death.** A resident woken after years keeps only its last `slots` perceptions; that is the intent, but an hour of a resident's life is little.
- **The sighting note comes from players' sweeps only.** A newcomer under a mind (a trial's spawned newcomer) is noted when it speaks, acts or is witnessed, not when it merely comes into view.
- **Woken residents with no mind service** (a world without one running) hold a pending deliberation and write experiences (bounded at 400 rows each) on their starting ways; they act as before.
