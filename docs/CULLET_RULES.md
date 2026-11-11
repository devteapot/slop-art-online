# Cullet's rules: the day, the needs, light and sight

Built on branch `rules-1`, 2026-11-11: the first part of Cullet's phase 4 ([small city](SMALL_CITY.md#8-build-plan)). It carries out the owner's answers to decisions 4 (a 48-minute day), 5 (the survival targets) and 6 (sight 48 m by day, 14 m in the dark, 28 m in lamplight, names at 24 m, kept as law values). Goods, recipes and fires that eat fuel are another task (`goods-1`); the authored city plan is `plan-1`.

Everything here is a general rule for every world. Cullet only chooses values, in its own laws file, [`living/seeds/worlds/cullet/laws.rhai`](../living/seeds/worlds/cullet/laws.rhai). The island and the labs keep their behaviour exactly (see [the labs are unchanged](#the-labs-are-unchanged)).

## What was built

### The day length in the seed

A seed may set `day_minutes` (real minutes in one game day, 1 to 1440; none: the shipped 12). `floor::begin` writes it to `World.day_ms` when the world is created, for a compiled seed (`init`) and for `create_floor` alike, and moves `clock.scripts_rev` so every cache compiles the laws for that day. No column was added: `World.day_ms` existed and only `init` wrote it.

### Rates per game hour, converted by the engine

`rates(a)` now says its unit: `per: "hour"` (a game hour) or `per: "minute"` (a real minute; also when `per` is missing, as every script before this change was written). The engine finishes the rates as before ([`NeedLaw::rates`](../living/rules/src/script.rs)) and multiplies them last by 60,000 ms over the real length of a game hour. On the 12-minute day that factor is exactly 2.

`Scripts::with_day(source, day_ms)` compiles a script for a world's day; `Scripts::new` keeps the shipped day. The authority (`common::scripts`, installs, seed checks) and the mind service (`prompts::set_day_ms`, from the `world` row) compile with the world's day. A law may read the day too: `hour_ms()` (real milliseconds in a game hour) and `day_minutes()` are registered in the engine, so a duration written in game time (`sleep_duration`) or a description ("One day lasts 48 real minutes") follows the world.

The shipped `rates` is now written per game hour: every number is the old per-minute number halved, since the 12-minute day's game hour is half a real minute. `sleep_duration` divides by the same halved rates and multiplies by `hour_ms()`. Halving and doubling are exact in floating point, so the island's rates in real time are bit for bit what they were (below).

**What was still per real minute** after rules-1: spoiling, grass regrowth, resource regrowth, traps and remains. Since `rates-2` they are in game time too ([below](#the-other-rates-in-game-time-rates-2)). Still in real time: the windows about people's real time, on purpose (`bond_window_s`, `trade_window_s`, `join_window_s`, `takeover_s`, `repeat_failure_s`, `follow_s`), steering and sensing cadences, `longing_after_min` (a grown person's longing for a child, in real minutes since a birth) and the wild animals' return (`species.json` `every_min`). `gestation_days` and lifespans were already in game days.

### `person_pace`, reconciled

Plainly: `person_pace` (0.3, `skills.rhai`) was added in iter-11 to pace people's needs to real time on the island's 12-minute day. It is kept, with the same value, so the island's people have exactly the rates they had: hunger 1.2 a real minute, which is 0.6 a game hour. What changed is its meaning. It now scales game-hour rates, so it is "people's needs at 0.3 of the shipped game-time rates", not "paced to real time". If someone lengthened the island's day, its people would get hungry more slowly per real minute and at the same pace per game day.

Cullet does not use it. Its laws write people's rates for its own day directly (its `rates` overrides people's numbers and keeps the base's for animals), from the game-time targets of [SMALL_CITY §4](SMALL_CITY.md#targets-in-game-time). The coordinator should report this to the owner: the iter-11 real-time pacing is now a property of the island's chosen numbers, not a mechanism.

### A seed's own laws

A seed may carry a Rhai overlay over the shipped script: `laws` (the source) or `laws_file` (a path relative to `living/seeds`; Cullet's is `worlds/cullet/laws.rhai`). When the world is created, the overlay is composed with `floors::compose` (each replaced base function stays callable as `base_NAME`), compiled for the world's day, run on the install samples (`Scripts::validate`), and installed through the same function as `install_script` (`install_source`: card tables, codes, a new script revision). A seed whose overlay fails is refused before anything is written, by `init` or `create_floor` (`floor::check`). `create_floor`'s signature is unchanged.

- A compiled seed's `laws_file` is read into `laws` by `living/authority/build.rs`. For `create_floor`, [`living/tools/seed_text.py`](../living/tools/seed_text.py) does the same (`just living-floor` uses it). A seed that names a file without its text is refused.
- **A fix in composition.** The base functions an overlay replaces were taken by the engine for laws of their own: `base_move_speed` for a dash speed, `base_sleep_duration` for the rules of a skill called `base_sleep`, `base_calendar_law` for a second calendar. `Scripts` now leaves every `base_` function out of what the engine asks; only the overlay calls them.
- `install_script` still installs a whole script. Installing the plain `skills.rhai` on a world made from a seed with laws drops those laws. The verification harness now skips its usual install for such a seed. A reducer that installs an overlay over the shipped script would make this safe in play; it is not built.

### Night as a law

`daylight(hour)` gives how light it is, from 0 (night) to 1 (day). Night is less than half light. Both are the script's: the shipped law reads `night_hours()` (dusk 20:00, dawn 06:00, twilight 0, so the light turns at once as before), and a world may ease it over a twilight (`ease`, a smooth step, half light at dusk and at dawn). The calendar's words for minds are built from `night_hours()` and `day_minutes()`.

- **Cost.** `Scripts::daylight` reads the law once per game minute of the day, lazily, and keeps the 1,440 answers for the script revision. Asking it is a lookup. `is_night` in Rust is gone from the authority and the mind service; the developer observer's clock label, which has no script, uses `shipped_night`.
- **What follows it.** Every context's `night` (cold, sight in the shipped `light_of`, wolves' daring, the bedtime of a body without a rhythm, deaths by exposure, minds' `time.night`) is `daylight < 0.5`. Laws may read `a.daylight` (in steps of 1/20, so laws kept per state share answers). A behaviour graph's `night` weight, which drives sleepiness, is now the darkness itself (1 − daylight). With the shipped step law that is exactly the old 0 or 1, so the labs are unchanged; with an eased twilight it rises over the hour.
- **Need rates** are asked again when the darkness changes only if `rates` reads `a.daylight` (the rate key gains the step); otherwise as before.

So in Cullet light, sight and sleepiness change over the hour around dusk and dawn, while cold still begins at 20:00. The game client's own sky (`living/game/src/daylight.rs`) is presentation and was not changed; it should read `night_hours()`'s twilight when the client compiles the rules.

### Light on people: `glow` and lamplight

Two new facts, as general primitives:

- **Lamplight.** A structure kind may give light: the `lights` trait (metres; in `structure_traits()` here, a trait of `structures()` since `goods-1`). `a.actor.lit` is true within that radius of such a structure (`common::lit_at`, one look round the body; it returns at once when no kind gives light, which is the shipped script). `lamp` is a structure kind for a seed or an authored plan to place; the shipped script gives it no traits and the clients draw nothing particular for it yet. **Since `goods-1`** a kind that `burns` gives its light only while lit, and Cullet's lamp burns oil (0.25 a game hour, holds 8): a lamp out of oil is dark. `cullet-laws.json` seeds its lamp with 8 units, 32 game hours ([goods](WORLD_RULES.md#goods-recipes-and-fuel)).
- **Glow.** `glow(a)` is a hot law like `senses`: how far a creature is seen from because of a light on it (0: only by an onlooker's own sight). An onlooker sees a creature within the wider of its own sight and the creature's glow, with a clear sight line. `senses_law()`'s `reach.glow` bounds it, and onlookers are gathered within it. The shipped script has no `glow`, and then nothing changes: the reach is 0, no glow is asked, the gather radius is the sight.
- **Where it applies.** The sight rule everywhere the authority uses it: players' perceived sets (`perception::sweep_one`), graph scenes and minds' percepts (`perception::visible`), witnesses (`perceive::witnessed`), the combat feed and witnesses of a death (`combat.rs`), a player's act on someone (`act.rs`), and what a predator senses.

### Who someone is depends on distance

`perceived_of(p)` may read `p.dist` (whole metres, rounded up). The engine gives the distance only to a law that reads it (`Scripts::regard_reads_dist`), so the shipped law's cache key is unchanged. When the law reads it, a player's projections are worked out again at every sweep (every 200 ms per player) and written only when they change, since a target crossing the knowing distance changes what the player is told. That is the cost this adds; it is bounded by the creatures each player perceives, and is measured below only at small numbers.

### People's lives: the life table as a law

Added on branch `lives-3` (2026-11-11), at the owner's decision through the general coordinator: Cullet's people live longer (old age from about 75) and childhood ends at 15, so the cast's 15- and 16-year-olds (Col Roon, Tobiah Dunmore) start as adults and its elders (61 to 70) keep their ages without dying of age early.

Before this, a species' life table was species data only: `species.json` (a person lives 70 years, a child until 0.23 of it, 16.1 years; old from 0.85, 59.5; deaths of old age between 0.87, 60.9, and the lifespan), which a compiled seed could replace with its own `species` map, but no law could read or change. It is now a law over that data, general for every world:

- **`life_years(t)`** is given a species' table in years: `kind`, `lifespan`, and the ages `infant`, `child`, `elder` and `old_age` where those stages end or begin, `gestation`, `interbirth`. It returns the table with any of them changed. An age it leaves alone keeps its years under a new lifespan. The engine asks it once per species and keeps the answer for the script revision (`Scripts::life`), and everything that reads a life table reads it through the world's rules (`common::life_of(ctx, kind)`): stages and their changes in the tick, deaths of old age, ages at seeding, what a body's laws see (`a.actor.stage`, `a.actor.life`), gestation, the years between births, a person's own "age" in their perception, and the life line the minds are told (`prompts::life_line`).
- **The shipped script has no `life_years`**, and then the table is `species.json`'s exactly (no conversion, the same `f32` values): every other world is unchanged. `cullet_check::life_tests::worlds_without_the_law_keep_the_species_tables` checks every species of `species.json` bit for bit under the shipped script.
- **Install check.** A world's law is run on a person's and a wolf's table when it is installed; a table whose ages are not in order (`infant <= child <= elder <= old_age <= lifespan`) or not numbers is refused (`a_wrong_life_table_is_refused`). The law has a description (`life_years_law`, with no topic of its own: the minds' LIFE line is built from the table it gives).
- **`author_world.py --check`** cannot run Rhai: it reads Cullet's `person_years()` map, the form Cullet's law gives its ages in, and says which source it used ("rule life stages (living/seeds/worlds/cullet/laws.rhai life_years, ...)"). A world whose law has another form stops the check with a message.

**Cullet's values** (`living/seeds/worlds/cullet/laws.rhai`, `person_years()`): a person lives up to **90** years; a child until **15**; deaths of old age from **75** (each person's own point between 75 and 90, fixed by their id, as before); a baby until 2.1, old (the elder stage, which tires sooner and heals slower) from 59.5, pregnancy and the years between births keep the shipped ages. Animals keep their tables. Under it the cast's stages are child 14, adult 44, elder 6, as the cast counts them, and nobody is seeded within reach of old age (the eldest, Halvard Dunmore, is 70).

## Cullet's laws

Values per game hour unless noted; in brackets per real minute on that world's day. A Cullet game hour is two real minutes; an island game hour is half a real minute. "Island" is the shipped script with `person_pace` 0.3, the old value in game time.

| Law | Island | Cullet | Target ([SMALL_CITY §4–5](SMALL_CITY.md#targets-in-game-time)) |
| --- | ---: | ---: | --- |
| Day length | 12 min | 48 min (`day_minutes`) | Decision 4 |
| Night (half light) | 20:00–06:00, at once | 20:00–06:00, eased over 1 h at each end (`night_hours`) | Light, sight and sleepiness do not flip in one tick |
| Hunger awake | 0.6 (1.2) | 2.4 (1.2) | Two meals a day |
| Hunger asleep | 0.3 (0.6) | 1.2 (0.6) | |
| Energy awake | −0.45 (−0.9) | −2.5 (−1.25) | About 16 hours awake |
| Energy asleep in a bed / rough | +3.9 / +2.4 (7.8 / 4.8) | +5.0 / +2.5 (2.5 / 1.25) | 7 to 8 hours asleep; rough at half a bed |
| Resting | +0.9 | +2.5 | |
| Slow walk below energy | 10 | 35 (×0.8), and 10 (×0.6) as everywhere (`tired_below`, `move_speed`) | One sleepless night means a slow walk the next day |
| Starving at / health | 100 / −0.6 (−1.2) | 100 / −0.5 (−0.25) | Harm after about two days; death about eight days after |
| Healing, fed (under 70) and rested (over 15) | +0.45 (0.9) | +1.5 (0.75) | |
| Out of energy, health | −0.3 (−0.6) | −0.4 (−0.2) | Harm only after two sleepless nights |
| Cold tiring, an ordinary night outside | −0.225 | 0 | Costs nothing but poorer rest |
| Cold health, winter night outside, no coat, fire or roof | −0.45, cancelled by healing when fed and rested | −1.5, and no healing while freezing | About 15 a winter night; never kills a healthy person in a night |
| Cold health, a rainy night | −0.225 | 0 (`freezing` is winter only) | Rain is not harmful |
| Rain outside, no coat / coat | −0.375 / −0.15 | −1.2 / −0.5 (−0.6 / −0.25) | Tiring |
| Sight by day | 11 m | 48 m (`sight_in`) | Decision 6 |
| Sight in the dark / carrying a torch | 6 / 9 m | 14 / 20 m, easing with the light at dusk and dawn | Decision 6 |
| Seen at night, standing in lamplight | 6 m | 28 m (`lamplight_seen`, `glow`) | Decision 6 |
| Seen at night, carrying a light | 6 m | 48 m (`carried_light_seen`) | §5 |
| What gives light | nothing | campfire, hall and inn 6 m; lamp 8 m while it has oil (`structures`) | |
| Name and health band shown | within sight | within 24 m (`known_within`, `perceived_of`) | Decision 6 |
| Speech | 9 m | 12 m (`hearing_of_people`) | §5 |
| A person's life | 70 years; a child until 16.1, old from 59.5, deaths of old age from 60.9 (`species.json`) | up to 90 years; a child until 15, old from 59.5, deaths of old age from 75 (`life_years`, `person_years`) | The owner's decision, 2026-11-11 |
| A shout | none | none (not built) | 30 m |
| Spoiling, raw fish (carried; a storage a third) | 2.5% a game hour (5% a real minute) | 2.5% a game hour (1.25% a real minute; `spoil_per_h`) | Gone in about a day: half in 1.1 game days |
| Spoiling, smoked fish / roots / greens | 0.1% / none / none | 0.1% / 0.2% / 3% a game hour | Smoked keeps weeks, roots a fortnight, greens a day |
| A trap's catch | a meat every 8 game hours | none (`trap_every_h` 0: no small game on the Wrack) | The world does not restock |
| A person's remains lie | 120 game hours (an hour real) | 48 game hours (96 real minutes; `remains_h`) | |

**Sight that depends on facing** (`fov-1`, 2026-11-11; [perception](PERCEPTION.md#the-field-of-view-seventh-change)) is a world law, `fov_on`, off on both worlds as shipped; `set_world_law fov_on true` turns it on for a running world. Cullet's `senses` carries the shipped field, so the values are the same law values on both:

| Law | Island | Cullet | |
| --- | ---: | ---: | --- |
| `fov_on` | false | false | sight depends on facing |
| `fov_focal_deg` | 70 | 70 | full sight (48 m by day on Cullet) within ±70° of facing |
| `fov_side_deg`, `fov_side_share` | 110, 0.3333 | 110, 0.3333 | a third of sight (16 m by day on Cullet) out to ±110° |
| `fov_near_m`, `fov_near_dark_m` | 3, 2 | 3, 2 | all round within 3 m, 2 m in the dark |
| `fov_margin_deg` | 10 | 10 | someone already seen stays seen 10° past an edge |
| `heard_near_m`, `heard_close_m`, `heard_linger_s` | 5, 15, 2 | 5, 15, 2 | what is heard and not seen: near, close, far (out to hearing: 9 m on the island, 12 m on Cullet); kept 2 s |

With the field on, `glow` (lamplight 28 m, a carried light 48 m) shows someone only within the field: a lit figure behind you is not seen.

**Where this differs from SMALL_CITY §4's proposed column**, which was written per real minute before `person_pace` existed, and what I chose:

- Hunger: the proposal's +1.0 a real minute is 48 a game day if it never slowed. Here hunger halves in sleep (as on the island), so awake it is 1.2 a real minute and the day still totals 48.
- Energy and sleep: the proposal's −1.6 awake and +7.5 in bed (a real minute) rest a person in under three game hours of a night it spends in bed, and harm a sleepless person after 31 hours, against "harm starts after two" nights. I chose the drain and the gain so that 16 hours awake and 8 in bed balance (−40, +40), a rough night restores half, a sleepless night slows the walk the next morning (energy below 35 after 26 hours) and harm starts in the second night (40 hours). The slow walk below 35 is Cullet's `move_speed`.
- Cold: the proposal's −0.75 a real minute on winter nights is kept. On the island and in the proposal, healing (+0.75) cancels it exactly for a fed, rested body, so a winter night would cost nothing; Cullet stops healing while freezing, so a winter night outside costs 15 whoever it is.
- Spoiling: set since `rates-2` (`spoil_per_h`), with SMALL_CITY §4's 1.25% a real minute for raw fish, which is 2.5% a game hour, as the island's per game day.

### The outcomes, computed from the script

[`living/rules/src/cullet_check.rs`](../living/rules/src/cullet_check.rs) runs a person's needs minute by minute through the composed script, exactly as the engine finishes them for the world's day, and checks the targets (`cargo test -p living-rules cullet`). It prints this table with `cargo test -p living-rules print_cullet_table -- --ignored --nocapture`. An ordinary day is awake 07:00–23:00 under a roof and asleep in bed 23:00–07:00; genes are all 1.

| Outcome | Island (12-minute day) | Cullet (48-minute day) | Target | Met |
| --- | ---: | ---: | --- | --- |
| Hunger gained in a game day | 12.0 | 48.0 | 48, two meals of about 24 | yes |
| Game hours from a meal (hunger 5) to hungry (over 50) | 87.0 | 21.5 | about a day; missing one meal changes nothing | yes |
| Game days from a meal to starving (100) | 7.9 | 2.0 | about 2 | yes |
| Game days starving until death, from full health | 6.9 | 8.3 | about 8 | yes |
| Energy spent in 16 waking hours | 7.2 | 40.0 | | |
| Game hours in a bed to be rested again | 1.8 | 8.0 | 7 to 8 | yes |
| Game hours sleeping rough to be rested again | 3.0 | 16.0 | twice a bed's | yes |
| Game hours awake until a slow walk | 200.0 | 26.0 | the morning after a sleepless night | yes |
| Game hours awake until harm (energy 0) | 222.2 | 40.0 | after two sleepless nights (in the second) | yes |
| Health lost sleeping out an ordinary night, no coat | 0.0 | 0.0 | nothing | yes |
| Health lost sleeping out a winter night, no coat | 0.0 | 15.0 | about 15 | yes |
| Energy a rainy day outside costs, no coat | 6.0 | 19.2 | tiring | yes |
| Health a rainy day outside costs | 0.0 | 0.0 | none | yes |
| Health healed in a game day, fed and rested | 10.8 | 36.0 | | |

The island's people tire 0.45 a game hour awake, so its sleepless rows are over eight game days (under two real hours).

Goods, in the same test (`cullet_s_goods_meet_their_targets_in_a_game_day`; spoiling as the authority sweeps it, once a real minute, so 12 sweeps an island day and 48 a Cullet day):

| Outcome | Island (12-minute day) | Cullet (48-minute day) | Target | Met |
| --- | ---: | ---: | --- | --- |
| Raw fish left after a game day, carried | 0.540 | 0.547 | gone in about a day | yes |
| Game days until half of raw fish is gone, carried / in a storage | 1.13 / 3.44 | 1.15 / 3.46 | | |
| Game days until half of smoked fish is gone, carried | 28.9 | 28.9 | keeps weeks | yes |
| Game days until half of roots / greens are gone, carried | none on the island | 14.4 / 0.96 | a fortnight / a day | yes |
| Smoked fish / roots left in a storage after 6 game days | 0.953 / – | 0.953 / 0.908 | the six days' store lasts | about 5% and 9% lost if none is eaten |
| Meat a trap catches in a game day | 3 | 0 | no restocking from nothing | yes |
| Game days a person's remains lie | 5 | 2 | | |
| The land's yield, a game day of growing time, against what 74 eat | | 1.32 times (fish 55%, roots 30%, greens 15%) | 1.3 times | yes |
| Peat cut a game day, against the Cone at full firing and the homes as much | | 101 of 144 (70%) | 70% | yes |

Not met, because not built: the shout (30 m), keen eyes, the spyglass, high ground (the authority does not read height for sight), fog and rain taking sight, kin recognised at 36 m, and a fisher's darkness sight. Each is a line in `senses`, `glow` or `perceived_of` once its fact exists (the shout needs a speech volume on `say` and a hearing law per volume; high ground needs the body's height in the context). Warm places with their own radius (a lit furnace) and needs in minds' prompts only past a threshold are other tasks in SMALL_CITY §4.

## The other rates in game time (rates-2)

Built on branch `rates-2`, 2026-11-11. The rates rules-1 left in real time are written per game hour, and the engine turns them into real time for the world's day, as it does for `rates`:

| What | The law now (game time) | Before (real time) | The engine's real-time value |
| --- | --- | --- | --- |
| Spoiling | `spoil_per_h(item)`: share of a stack a game hour | `spoil_rate(item)`, a real minute | `Scripts::spoil_per_min`, read by the spoiling sweep (`tick::spoil`, once a real minute per stack) |
| Resource regrowth | a kind's `regrow_per_h` in `resources()`, read by `regrow_per_h(kind)`; a plan's or seed node's `regrow_per_h` | `regrow` and `regrow(kind)`, a real minute | `Scripts::regrow_per_min`, kept per real minute in `resource_node.regen` as before |
| Grass regrowth | `laws().pasture_regen_per_h` per grassy tile a growing game hour | `pasture_regen`, a growing minute | `Laws::pasture_regen`, still per real minute |
| Traps | `trap_every_h(x)`: game hours between catches | `trap_every_s`, real seconds | `Scripts::trap_every_ms` |
| Remains | a kind's `remains_h` in `kinds()`, read by `remains_h(kind)` | `remains_s`, real seconds | `Scripts::remains_ms`, the `rot` row's due time |

- **The conversion** multiplies a game-hour rate by 60,000 ms over the real length of a game hour (`Scripts::per_minute`, 2 on the 12-minute day, ½ on Cullet's), and a game-hour duration by that length (`hour_ms`). The shipped numbers are the old ones halved (rates) or the old seconds over 30 (durations): halving, doubling and multiplying whole numbers by 30,000 are exact in floating point.
- **Older scripts keep their meaning.** A script that defines the real-time law (`spoil_rate`, `regrow`, `trap_every_s`, `remains_s`, or `pasture_regen` in `laws()`) is read in real time as before, whatever its day: a script installed before this change, or an overlay that still writes real time. The name says the unit, so a law is never read in the wrong one.
- **The words minds read** are unchanged on the island: remains are "gone after about 30 minutes (a person's after 60)", now computed as `remains_h × hour_ms()` in real minutes.
- **A seed's nodes** (`resource_nodes[]`) take `regrow_per_h`; goods-1's `regrow` (a real minute) is still read when `regrow_per_h` is absent.
- No table, column, reducer or view changed; `resource_node.regen` stays per real minute, so clients that draw regrowth (the viewer, the game client) are unchanged.

### Cullet's values

In its laws file: raw fish 2.5% a game hour (§4's 1.25% a real minute), cooked fish 0.6%, smoked fish 0.1% (as the island per game day); roots 0.2%, baked roots 1%, greens 3%. No trap catches anything (there is no small game on the Wrack). A person's remains lie two game days. A storage holds up to 1,000 things (`storage_holds`; the shipped 120 is a crate's): the Store's 509 foods and the Cone's 824 peat are placed in storages, and at 120 nobody could store anything in them until they were nearly empty. It applies to every storage in Cullet, a person's own too. A capacity per kind of store would be the better rule; none exists yet. Its resource kinds regrow per game hour as computed from §2 ([placed below](#cullets-goods-placed-rates-2)). The outcomes are in the [goods table above](#the-outcomes-computed-from-the-script).

## Cullet's goods, placed (rates-2)

All through [`living/tools/cullet_plan.py`](../living/tools/cullet_plan.py), which writes `plan.json` and `cullet.json`; amounts and regrowth are computed there from SMALL_CITY §2's sustainability targets, as starting values for the soak (not tuned). The assumptions are written beside them: 64 residents and 10 players eat 48 a game day; the land gives 1.3 times that; fish 55% counted as eaten smoked (24), roots 30% counted baked (30), greens 15% raw (10); the Cone makes about 12 glass a day; nodes hold about two days of regrowth. Every node regrows only in growing time (no regrowth in winter, for every kind).

**Resources** (`plans[].resources`, the laws' kind names):

| Where | Kind | Nodes | Each holds | Regrowth, a game hour | A game day |
| --- | --- | ---: | ---: | ---: | ---: |
| The Fish Steps | `fishing_spot`, pool "the Fish Steps" | 2 | one stock of 21.2 | 0.441 (the stock) | 10.6 fish |
| The quay's edge (the jetties) | `fishing_spot`, pool "the quay" | 4 | one stock of 42.3 | 0.882 | 21.2 fish |
| The mole | `fishing_spot`, pool "the mole" | 6 | one stock of 63.5 | 1.323 | 31.7 fish |
| The Weirs | `weir`, pool "the Weirs" | 10 | one stock of 84.7 | 1.764 | 42.3 fish |
| The Wrack Strand | `kelp_bed` | 12 | 10 | 0.208 | 60 kelp |
| The Sand Spit | `sand_bank` | 6 | 8 | 0.167 | 24 sand |
| The Moss | `peat_bank` | 18 | 11.2 | 0.233 | 101 peat |
| The 18 root plots | `root_plot` | 18 | 6 | 0.107 | 46 roots |
| The 11 working glasshouses | `greens_bed` | 11 | 12.6 | 0.262 | 69 greens |

The root plots are open lots now, not `garden` lots: a garden is planted with berry bushes (the rule is a Rust constant in `seed::town`), and a root plot grows roots. The seed turns the wild spawn of these kinds off (`resource_scale` 0), so these are all there are. The Hanger's 70 trees and the clay bank are unchanged.

**Fires and lamps** (`plans[].structures`, each lit from creation for its fuel at its kind's rate):

| What | Where | Fuel | Lasts |
| --- | --- | ---: | --- |
| The Cone's furnace | the Cone's front mouth | 40 peat (full) | 13 game hours at 3 a game hour |
| The Cone's peat store | a storage in the Cone yard | 824 peat | with the furnace's, 864: 12 days of full firing (§2) |
| The Batch's oven | the oven mouth | 8 (full) | 8 game hours |
| The Marver's hearth | the hearth bench | 12 (full) | a game day |
| 21 home hearths | the door of every home lived in | 12 each (full) | a game day |
| 2 smokehouses | their doors | 8 each (full) | 16 game hours |
| 7 lamps | the top of the Fish Steps, the quay by the net lofts, the quay by the Store, the Counting House yard, the Marver's door, the mole by the lamp house, the Watchglass | 8 oil each (full) | 32 game hours: about three nights |

**Stores.** The Store (its storage at the door, `lots[].contents`) holds 212 smoked fish and 297 roots: three of §2's six days for 64 residents (the fish share smoked, the roots' and greens' share as roots, counted raw at 14, since greens do not keep). The other three days belong in the households: the plan's `household_stores` note gives them per household (4 smoked fish and 5 roots a person), with peat for each hearth beyond its first fill. They are not placed. The cast landed on main (`13dac1c2`, merged here), but a household's store must be the household's own (the theft law reads a store's owner), and a plan's `structures[]` has no owner field yet; a general `owner` naming a household would place them.

**The checks.** `floor::check` refuses a plan that names a resource or structure kind, or a stored item, the world's tables do not have, before anything is written (bible-1 found the plan-2 names `kelp`, `peat`, `roots`, `greens` and `sand` silently left out). verify-generation checks that every planned resource stands where written with its max, regrowth and pool, every planned structure stands at its point, lot door or spot, lit for as long as its fuel lasts at its kind's rate, and every store holds what the plan says.

## The labs are unchanged

- **Rates in game time, rates-2.** `rates_check::rates_are_bit_identical` (`living/rules/src/rates_check.rs`, ignored: it reads main's script from `LIVING_OLD_SKILLS`) compares `f2d803fa`'s script with this one on the 12-minute day over 12,325 states, computing what the authority computes from each law: a stack's loss in one spoiling sweep for every item, 14 stack sizes, four carrier kinds and every structure kind; a node's amount after 12 growing times from four amounts for every resource kind with both defaults; a pasture of 0 to 256 tiles after each growing time; a trap's catches over 2,000 s; remains due for four kinds at four times; and every law's words for minds. None differs (`rates-bit-identical.txt` in the evidence).
- **Rates.** A temporary test compared the shipped script at `origin/main` with this branch's over 19,200 need states (3 kinds × 4 stages × 5 activities × 64 combinations of cloak, fire, shelter, night, winter and rain × 5 hunger and energy levels): every rate and every sleep duration is bit-identical on the 12-minute day.
- **The world text.** The minds' text is unchanged: "One day lasts 12 real minutes; night is 20:00-06:00." and "hunger rises ~1.2/min … energy falls ~0.9/min" (`world_text_is_built_from_the_laws`).
- **Night, sight, reach.** The shipped `daylight` is the old step, so `night` is the same at every minute (`dusk_and_dawn_take_an_hour_and_night_is_where_it_was` checks both scripts), and the graphs' `night` weight is the same 0 or 1. The shipped script has no `glow`, no `lights` and a `perceived_of` that does not read `p.dist`, so the gather radius, the sight rule, the projection cache and the perception sweep take the old paths (`cullet_s_sight_is_its_law_values` checks the island's 11 / 6 / 9 / 9 m).
- `cargo test -p living-rules` passes (138 tests, 8 ignored printers and benches); the verify-core baseline on the default seed passes 45 of 45 scene checks ([verification](#verification)).

## Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- | --- |
| World creation with `day_minutes` and `laws` | the seed | `world` (day), `script` (composed source, a revision), `clock` (revision), the card tables as `install_script` writes them | PKs | `world` and `script` subscribers, once | once | none |
| `daylight` | the script, once per game minute of the day per revision | — | — | — | lookup per ask | 1,440 floats per module instance |
| Lamplight (`a.actor.lit`) | structures in the chunks within the widest `lights` | — | `structure.chunk` | — | only for a law that reads it (Cullet's `glow`), per creature per moment (the hot-law cache) | — |
| `glow` | the creature's lamplight and its torch | — | — | — | per creature per moment, kept per state | the hot memo (1,024 states) |
| Perceived sets and graph scenes with a glow | bodies within the widest glow instead of the sight | `perceived` rows as before | `body.chunk` | the player (`seen_*`) | as before | more creatures per scene at night (bounded by the reach) |
| Projections with a distance law | as before, every sweep | `projected` rows only when changed | PK | the player (`seen_characters`) | each player every 200 ms | — |

| Rates in game time (rates-2): spoiling, regrowth, traps, remains | the script's name tables, once per revision (`num_of`), converted by `Scripts::per_minute` / `hour_ms` | the same rows as before (`inventory` by the spoiling sweep, `resource_node.regen` when a node is made, `rot.due_ms` at a death) | as before | as before | as before | none |
| A plan's resources, structures and stores at creation (rates-2) | the hosted plan; `lot` rows by id for a lot's own structure | 158 `resource_node` rows (Cullet), 34 `structure` rows with `lit_until_ms`, their `inventory` rows (3 stores) | PK | `resource_node`, `structure` and `inventory` subscribers by chunk, once | once, in `init` or the staged creation's last step | none after creation |
| `floor::check`'s plan kinds (rates-2) | the seed's plans against the compiled script's tables | — | — | — | once, before creation | — |

No whole-World scan was added. SpacetimeDB documentation consulted (2.0.0 pages; the service is 2.14.1): [views](https://spacetimedb.com/docs/functions/views/) (a view re-runs when a row in its read set changes; so a projection is written only when it changed, never rewritten unchanged), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [table performance](https://spacetimedb.com/docs/tables/performance/), and, as read by the coordinator for this task, [tables](https://spacetimedb.com/docs/tables/), [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) and [reducers](https://spacetimedb.com/docs/functions/reducers/). No table, column, reducer, view or subscription was added or changed; bindings are unchanged. rates-2 changed none either: its plan structures and resources are ordinary rows inserted in the creating transaction, as plan-2's resources were ([reducer lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle/): a failed `init` publishes nothing, so a plan refused in `floor::check` leaves no world); no documentation page needed re-reading for it, and `just living-generate` was not run.

## Costs

**Perception at Cullet's sight**, measured cheaply as asked, on an existing kind of scratch world: the island seed (277 people, 33 animals, at rest by day, graph-driven, no minds, no players, no subscribers), on my own SpacetimeDB 2.14.1 container on the dev-box (`rules1-stdb`). One world; arm A is the shipped script, arm B the shipped script with Cullet's light-and-sight laws only (sight 48 / 14 / 20 m, `glow`, lamplight, names within 24 m, an eased dusk; not its needs), installed with `install_script`; arms alternated A B B A, 20 s settling after each install, 60 s profiled with `living/tools/bench.py`. Window 1 overlapped a short verify-core scene on another database of the same server. Evidence: `.local/rules1/evidence/bench/`.

| Window | Arm | Tick p50 / p99 ms | Tick work ms/s | `tick.slots` (graph scenes) ms/s | `tick.wakes` ms/s | Experiences/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | shipped (11 m) | 1.74 / 3.95 | 78.4 | 40.0 | 15.2 | 14.8 |
| 2 | Cullet's sight (48 m) | 2.97 / 6.67 | 127.2 | 77.1 | 22.1 | 17.7 |
| 3 | Cullet's sight | 3.19 / 6.92 | 138.6 | 81.7 | 26.0 | 18.5 |
| 4 | shipped | 1.42 / 3.36 | 63.7 | 34.5 | 12.1 | 21.1 |

At 48 m every graph scene holds about 19 times the area, and on the island's crowded towns that doubles the graph work (`tick.slots` 35–40 → 77–82 ms a second) and the tick (p99 3.4–4.0 → 6.7–6.9 ms; no tick over 16.7 ms in any window). This is the island's density, not Cullet's: Cullet has 64 residents on a smaller, broken-up town. It says nothing about the 216-character gate except that sight this long is not free there. Not measured: a player's perceived set and the re-projection every sweep that `p.dist` adds (no players in these windows), lamplight's structure look per creature at night, and anything at 64 Cullet residents, which waits for Cullet's seed (as the task said).

## Verification

### rates-2

On the worker's own server (`rates2-stdb`, 2.14.1, port 3320), scratch databases only, no mind service, no model calls. Evidence under `.local/living/verify/<run>/` and `.local/rates2/evidence/` on the dev-box (git-ignored).

- **Rules.** `cargo test -p living-rules`: 161 pass, 9 ignored, on the last merge of main. New: `rates_check::rates_are_bit_identical` (ignored, run with `LIVING_OLD_SKILLS`: 50,725 states, none differ, `rates-bit-identical.txt`), `script::tests::game_time_rates_follow_the_day_and_real_time_laws_stay_real`, `cullet_check::tests::cullet_s_goods_meet_their_targets_in_a_game_day`, `settle::plan::tests::a_plans_structures_and_stores_are_kept_on_the_land`. `cargo test -p living-authority --lib`: 17 pass, with `seed::tests::a_plan_naming_kinds_the_world_lacks_is_refused`.
- **verify-core** (before the merges of main unless noted): `goods` and `stock` on the goods fixture (`core-rates2-goods`), `needs`, `food` and `refusal` on the default seed (`core-rates2`), `remains` on `stage1-acts` with `remains_h` (`core-rates2-remains`), `laws` on `cullet-laws` (`core-rates2-laws`: 15 pass, the mirrored dark spot skipped as on rules-1): all pass. `tick` failed once on `core-rates2`: the 3 s wait had finished before the pause landed while four worlds shared the server, a race in the scene. Rerun after merging the cast (`core-rates2-tick`): 6 of 6. The new `decay` scene over a whole Cullet game day (`core-rates2-decay2`): 543 of 1,000 raw fish carried left after 48 real minutes (the law gives 547) and 87 of 100 in a storage; the node's `regen` is `regrow_per_h` turned into real minutes. Its regrowth check counted the greens gathered, and `nearest` walked on to the valley's wild beds once the placed one was spent (7 gathered against 5.86 grown). The scene now reads the bed's own row; The rerun on a fresh world (`core-rates2-decay3`, a whole game day) passes all five: 553 of 1,000 carried and 78 of 100 stored raw fish left after 48.0 real minutes (the law: 547 and about 82), and the emptied greens bed had regrown 5.891 units over 22.06 game hours, its `regen` of 0.131 a real minute (`regrow_per_h` 0.262) exactly.
- **verify-generation** after merging the cast: `generation-rates2-20261111-174238`, cullet 305, plan-test 76, island 977, floor-megacity-4k 90, all pass (see [verify-generation's validation](../.agents/skills/verify-generation/references/validation.md)).
- **`just living-check`**: exits 0 after the first merge of main (`living-check.txt`). After the last merge of main (`d538967f`, tool-7's lanes): `just living-check` passes, all five steps (`living-check2.txt`).
- `python3 living/tools/cullet_plan.py --check` and `python3 living/tools/author_world.py cullet --check` pass (0 errors, 5 warnings about the cast), with the 64 residents and 22 homes in the seed.
- **Fuel gate** (`living/tools/script_bench/gate.sh`, dev-box): rates 8,585, rates-law 194,609, strike 274,315, cooldown 1,704, perceived 68,775, hook 448,042, senses 3,139, senses-law 58,604, moves 1,956 (`gate-branch2/`); re-scored against the re-based budgets, every law is within budget (`gate-rebudgeted.txt`). After the last merge of main (lives-3, `2e9f19d9`) the gate passes with rates-law at 218,311 against 245,000 (`gate-final/`). That merge did not change the script or the rates path, and the rise is not explained.
- **Not run:** verify-player, verify-client, verify-minds, verify-llm, verify-knowledge (no table, reducer, view, subscription or mind protocol changed; the minds' words for remains, food and making are bit-identical on the island); skirmish, dealings, town, lives, infant, lifecycle, wildlife, flee, mechanics, steering.

### rules-1

All on my own server (`rules1-stdb`, 2.14.1, port 3312), scratch databases only, no mind service, no model calls. Evidence under `.local/living/verify/<run>/` and `.local/rules1/evidence/` on the dev-box (git-ignored).

- **Rules.** `cargo test -p living-rules`: 138 pass. New: `cullet_check` (6 tests: install checks, survival targets, sight values, dusk and dawn, names by distance, the island unchanged). The bit-identical comparison of rates and sleep durations against `origin/main`'s script (19,200 states) was a temporary test, run once (`rates-bit-identical.txt`) and removed.
- **`just living-check`**: passes (`living-check.txt`).
- **verify-core**, baseline on the default seed (`core-rules1-base`): cargo checks (rules 138, authority 12, mind 82, viewer sync 5) and the scenes tick, needs, food, refusal, seize, sight, senses, moves: 45 of 45 checks pass. Not rerun: skirmish, dealings, town, lives, infant, lifecycle, wildlife, remains, flee, mechanics and steering (each tens of minutes; their rules are unchanged on the shipped script, and the shipped rates are bit-identical).
- **verify-core `laws`** (new scene) on a `cullet-laws` world (`core-rules1-cullet`): the day is 48 minutes, the composed laws are installed, live rates are the per-hour law in real time; by day figures seen to 48 m and not at 52, a known figure named at 20 m and only "a stranger" with no health band at 28 and 30 m; at full dark 13 m seen and 19 m not, a torch carrier seen at 44 m, someone at the lamp seen from 21 m; an ordinary night outside costs no health. The first night attempt failed (the player had been taken over by the world's minds after 30 s without a call, so nobody was swept for it); the scene now keeps the player present, and the rerun passed. The mirrored dark spot was skipped (not open ground on that map).
- **verify-generation** (`generation-rules1-135536`): `cullet-laws` compiled in (41 checks) and `cullet-laws-floor` given to a floor module by `create_floor` (46 checks, including the refusals of an unread laws file, broken laws and a zero day): all pass, seeds unchanged. Every other seed now also checks the 12-minute day and the shipped script; the other seeds were not rerun.
- **Not run:** verify-player (what a player perceives changes only on a world whose laws use `glow` or `p.dist`; the `laws` scene drove a real player identity's perceived and projected rows as the owner, not its `seen_*` views), verify-minds and verify-llm (the perceive JSON and the prompts are the same shape; the mind compiles the rules for the world's day, and its tests pass), verify-client (no table, reducer, view or subscription changed), verify-knowledge (it hard-codes the shared server's port).

## Files

- Rules crate: `script.rs` (`with_day`, `hour_ms`, `NeedLaw`'s `per`, `daylight`, `glow`, `Reach.glow`, `lights`, `RegardIn.dist`, `base_` functions left out), `script/context.rs` (`a.daylight`, `a.actor.lit`), `script/check.rs` (samples in twilight and lamplight, the `daylight` and `glow` checks), `catalog.rs` (`lamp`), `lib.rs` (`shipped_night`), `cullet_check.rs` (new).
- Script: `living/scripts/skills.rhai`: `rates` and `sleep_duration` per game hour, `night_hours`, `ease`, `daylight`, `calendar_law`, `needs_law`'s words.
- Cullet: `living/seeds/worlds/cullet/laws.rhai` (new); `living/seeds/cullet-laws.json` (new), a small rules test world: the valley's camps, a lamp, Cullet's laws and day, until the Cullet seed exists.
- Authority: `floor.rs` (`check`, `set_day`, `begin` installs the laws), `lib.rs` (`install_source`), `seed.rs` (`day_minutes`, `laws`, `laws_file`), `common.rs` (`night`, `dark`, `glow_of`, `sight_to`, `gather_radius`, `lit_at`), `act.rs`, `brain.rs`, `perception.rs`, `perceive.rs`, `combat.rs`, `records.rs`, `build.rs`.
- Mind: `prompts.rs`, `mind.rs` (the world's day). Viewer: `panels.rs`. Tools: `seed_text.py` (new), the script bench's fixtures. Justfile: `living-floor`.
