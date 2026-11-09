# Town life, layer 1: daily rhythm and non-verbal social behaviour

Started 2026-11-09. This note records how residents of the island's settlements live a visible daily rhythm with no model calls: what they do hour by hour, the skills and starting graphs that do it, the data clients read to draw it, the SpacetimeDB documentation the design rests on, and what was measured and verified.

**Layers (agreed with the user).** Layer 1, this note: routines and non-verbal social behaviour on behaviour graphs, run by the authority every tick. Layer 2, later: conversation through the mind service with level of detail. Nothing here speaks: there are no canned lines of any kind.

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

- **Speech.** Residents still never speak, and nothing here writes a line. A resident turns to face someone who speaks to it (`heard_within`) but cannot answer. Conversation through the mind service, with level of detail for residents far from any player, is layer 2.
- **Minds keep their places.** With `rules.minds = true` the mind service replaces `place` rows from the mind graph after every change, which would drop the seeded `work`, `square`, `inn` and `evening` places. A mind-driven world needs those anchors in the starting mind (`place:work`), or the projection must keep authority-seeded places.
- **Greeting is not yet chosen.** Residents answer greetings and nod to someone now and then in the evening; whom one greets and how warmly (friends, strangers, enemies) is left to relations a mind would write.
- **Remembering who greeted whom** is not kept: `hailed` is a moment, not a memory. A mind would integrate the experience.
