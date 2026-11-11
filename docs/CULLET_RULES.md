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

**What is still per real minute** (not converted here, and listed so nobody assumes they are): `spoil_rate` (goods, `goods-1`'s), `pasture_regen` (grass regrowth per growing minute), `regrow` of resources, `trap_every_s`, `remains_s`, and the real-time windows (`bond_window_s`, `trade_window_s`, `join_window_s`, `takeover_s`), which are about people's real time on purpose. On a 48-minute day the first five run four times faster per game day than on the island. `gestation_days` and lifespans were already in game days.

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

- **Lamplight.** A structure kind may give light: the `lights` trait in `structure_traits()` (metres). `a.actor.lit` is true within that radius of such a structure (`common::lit_at`, one look round the body; it returns at once when no kind gives light, which is the shipped script). `lamp` is a new structure kind (in `catalog::STRUCTURES`), for a seed or an authored plan to place; the shipped script gives it no traits and the clients draw nothing particular for it yet.
- **Glow.** `glow(a)` is a hot law like `senses`: how far a creature is seen from because of a light on it (0: only by an onlooker's own sight). An onlooker sees a creature within the wider of its own sight and the creature's glow, with a clear sight line. `senses_law()`'s `reach.glow` bounds it, and onlookers are gathered within it. The shipped script has no `glow`, and then nothing changes: the reach is 0, no glow is asked, the gather radius is the sight.
- **Where it applies.** The sight rule everywhere the authority uses it: players' perceived sets (`perception::sweep_one`), graph scenes and minds' percepts (`perception::visible`), witnesses (`perceive::witnessed`), the combat feed and witnesses of a death (`combat.rs`), a player's act on someone (`act.rs`), and what a predator senses.

### Who someone is depends on distance

`perceived_of(p)` may read `p.dist` (whole metres, rounded up). The engine gives the distance only to a law that reads it (`Scripts::regard_reads_dist`), so the shipped law's cache key is unchanged. When the law reads it, a player's projections are worked out again at every sweep (every 200 ms per player) and written only when they change, since a target crossing the knowing distance changes what the player is told. That is the cost this adds; it is bounded by the creatures each player perceives, and is measured below only at small numbers.

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
| What gives light | nothing | campfire, hall and inn 6 m; lamp 8 m (`structure_traits`) | |
| Name and health band shown | within sight | within 24 m (`known_within`, `perceived_of`) | Decision 6 |
| Speech | 9 m | 12 m (`hearing_of_people`) | §5 |
| A shout | none | none (not built) | 30 m |
| Spoiling, raw fish | 5% a real minute | unchanged (goods) | About a day |

**Where this differs from SMALL_CITY §4's proposed column**, which was written per real minute before `person_pace` existed, and what I chose:

- Hunger: the proposal's +1.0 a real minute is 48 a game day if it never slowed. Here hunger halves in sleep (as on the island), so awake it is 1.2 a real minute and the day still totals 48.
- Energy and sleep: the proposal's −1.6 awake and +7.5 in bed (a real minute) rest a person in under three game hours of a night it spends in bed, and harm a sleepless person after 31 hours, against "harm starts after two" nights. I chose the drain and the gain so that 16 hours awake and 8 in bed balance (−40, +40), a rough night restores half, a sleepless night slows the walk the next morning (energy below 35 after 26 hours) and harm starts in the second night (40 hours). The slow walk below 35 is Cullet's `move_speed`.
- Cold: the proposal's −0.75 a real minute on winter nights is kept. On the island and in the proposal, healing (+0.75) cancels it exactly for a fed, rested body, so a winter night would cost nothing; Cullet stops healing while freezing, so a winter night outside costs 15 whoever it is.
- Spoiling is not set: it is goods (`goods-1`), and `spoil_rate` is still per real minute.

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

Not met, because not built: the shout (30 m), keen eyes, the spyglass, high ground (the authority does not read height for sight), fog and rain taking sight, kin recognised at 36 m, and a fisher's darkness sight. Each is a line in `senses`, `glow` or `perceived_of` once its fact exists (the shout needs a speech volume on `say` and a hearing law per volume; high ground needs the body's height in the context). Warm places with their own radius (a lit furnace) and needs in minds' prompts only past a threshold are other tasks in SMALL_CITY §4.

## The labs are unchanged

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

No whole-World scan was added. SpacetimeDB documentation consulted (2.0.0 pages; the service is 2.14.1): [views](https://spacetimedb.com/docs/functions/views/) (a view re-runs when a row in its read set changes; so a projection is written only when it changed, never rewritten unchanged), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [table performance](https://spacetimedb.com/docs/tables/performance/), and, as read by the coordinator for this task, [tables](https://spacetimedb.com/docs/tables/), [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) and [reducers](https://spacetimedb.com/docs/functions/reducers/). No table, column, reducer, view or subscription was added or changed; bindings are unchanged.

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
