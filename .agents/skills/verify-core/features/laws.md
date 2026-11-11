# A world's own day and laws

Since `rules-1` (2026-11-11, [Cullet's rules](../../../../docs/CULLET_RULES.md)). A seed may set its day's length (`day_minutes`) and carry a Rhai laws overlay (`laws`, or `laws_file` under `living/seeds`), composed over the shipped script and installed when the world is created. Need rates are written per game hour (`rates` returns `per: "hour"`) and the engine turns them into real time for the world's day. Night is the `daylight(hour)` law over `night_hours()` (half light is night; a world may ease dusk and dawn). A creature may be seen farther than an onlooker's sight by a light on it (`glow(a)`, bounded by `senses_law`'s `reach.glow`; lamplight is `a.actor.lit`, within a structure kind's `lights`), and `perceived_of` may read the distance (`p.dist`).

## Sub-features

- The world's `day_ms` is the seed's `day_minutes`; the installed `script` row is the shipped script with the overlay after `// ---- floor overlay ----` (replaced functions as `base_NAME`).
- A person's live need rates (`vitals.hunger_rate`, `energy_rate`) are the overlay's per-hour numbers times 60,000 over the game hour's real milliseconds, times the body's appetite or over its endurance.
- By day a player perceives figures to the day sight (Cullet: 48 m) and not beyond; a figure is named, with a health band, only within the knowing distance (24 m): beyond it the `projected` row has no name, the stranger's label and band 255. The name is known because the figure said it beside the player (an introduction, `acquaintance`).
- At full dark (21:00): the dark's sight (14 m: 10 m seen, 16 m not), a figure carrying a torch seen from the carried light's distance (44 m), someone standing at the seed's lamp seen from about 21 m (between the dark's 14 and lamplight's 28), and the same distance off the other way, away from any light, not seen.
- An ordinary night outside costs no health.
- **People's life table as a law** (since `lives-3`): `life_years(t)`, given a species' table in years (`kind`, `lifespan`, `infant`, `child`, `elder`, `old_age`, `gestation`, `interbirth`), returns it with any changed (`Scripts::life`, read by `common::life_of(ctx, kind)` for stages, deaths of old age, ages at seeding and the minds' life line). The shipped script has none, so every other world keeps `species.json`'s tables bit for bit (`cullet_check::life_tests::worlds_without_the_law_keep_the_species_tables`). Cullet's: lifespan 90, a child until 15, deaths of old age from 75; infancy, elder from 59.5 and pregnancy keep their years (`cullet_people_live_longer_and_grow_up_sooner`); a law whose ages are out of order is refused at install (`a_wrong_life_table_is_refused`). Live: `rhythm.py drive` checks the cast's 15- and 16-year-olds start adults and the 70-year-old an elder.
- Unit checks (`cargo test -p living-rules`): `cullet_check` (the survival targets computed from the composed script, sight values, eased dusk with night where it was, names within 24 m, the island unchanged), `floors::tests`, the install checks on twilight and lamplight samples.

## Driving it

```bash
R=core-laws-$(date +%H%M%S)
python3 "$V" launch --run "$R" --seed cullet-laws > ".local/living/verify/$R/launch.txt" 2>&1
python3 "$V" doctor --run "$R"
python3 .agents/skills/verify-core/scripts/scenes.py laws --run "$R" > ".local/living/verify/$R/laws.txt" 2>&1
python3 "$V" cleanup --run "$R"
```

Start it right after launch: the day checks need the world's morning, then the scene waits for 21:00 by the world's own clock (28 real minutes after creation on the 48-minute day; no clock is changed). It reads the expected distances and rates from the seed's laws file (`sight_in`, `known_within`, `lamplight_seen`, `carried_light_seen`, `hunger_awake`, `energy_awake`), so it follows the laws when their values change. It finds an open ray of the day sight plus 6 m in any of 32 directions (the valley map is 96 m), spawns minded people, joins one player (`Watcher`; a player of an earlier attempt on the run keeps its character) and places everyone with `place_at`. Evidence: `laws-world.json`, `laws-awake-vitals.json`, `laws-line.json`, `laws-perceived-*.json`, `laws-projected-*.json`, `laws-night-out.json`, `laws-actions.jsonl`, `laws-results.json`.

## Gotchas

- The player is an HTTP identity: after the `takeover_s` law (30 s) without a call the world's minds take its character over and nobody is swept for it (the first attempt's night checks saw nothing). The scene makes a player call (`move 0 0`) before each snapshot, which hands the character back.
- Started at night (a rerun on the same database), the scene skips the day checks and says so; launch afresh for them. The mirrored dark spot is skipped when it is not open ground with a clear line.
- `launch` does not install the plain `skills.rhai` on a seed with its own laws (it would drop them); `state.json` records `seed_laws`.
- `install_script` installs a whole script: installing the shipped one on such a world removes its laws until it is created again.
- The scene needs the seed's lamp (`structure` kind `lamp`) with an open line from it; without one it fails "the seed has a lamp with an open line of sight from it". Since `goods-1` the lamp burns oil and lights only while lit: the seed gives it 8 units (32 game hours, past the scene's night at 21:00); a lamp seeded without fuel is dark and the lamplight check fails.
- These checks do not measure cost: longer sight and re-projection every sweep cost more per player (docs/CULLET_RULES.md, "Costs").

## Decay

Since `rates-2` (docs/CULLET_RULES.md, "The other rates in game time"): spoiling (`spoil_per_h(item)`), resource regrowth (a kind's `regrow_per_h`, read by `regrow_per_h(kind)`), grass regrowth (`laws().pasture_regen_per_h`), traps (`trap_every_h`) and remains (a kind's `remains_h`) are written in game time; the engine keeps them in real time for the world's day (`Scripts::spoil_per_min`, `regrow_per_min`, `trap_every_ms`, `remains_ms`, `Laws::pasture_regen`; `resource_node.regen` stays per real minute). A script that defines the old real-time law (`spoil_rate`, `regrow`, `trap_every_s`, `remains_s`, `pasture_regen`) is read as before.

### Sub-features

- On a `cullet-laws` world (48-minute day): a new node's `regen` is its kind's `regrow_per_h` × 60,000 / the game hour's real ms (exact to 1e-6).
- 1,000 raw fish carried and about 600 in a storage spoil once a real minute at `spoil_per_h("fish")` turned into real minutes (a storage at its `kept_spoil` third): after `--game-hours` the stacks lie within the band of `q (1 − r)^k` for the real minutes passed, give or take one sweep and each sweep's chance (`decay-samples.json` keeps the trajectory).
- An emptied greens bed, gathered once beside it after the watch, held what its `regen` grew over the real minutes since it was emptied (the row's new amount plus one, within 0.01; growing time). Gathering more would count the wild beds `nearest` walks on to.
- Unit checks: `rates_check::rates_are_bit_identical` (ignored; `LIVING_OLD_SKILLS=<the script before rates-2>`): on the 12-minute day every spoiling loss, regrowth, pasture, trap catch, remains due time, need rate, sleep and law description is bit-identical to the old script's. `script::tests::game_time_rates_follow_the_day_and_real_time_laws_stay_real` (a 48-minute day quarters them; an overlay in real time keeps its numbers). `cullet_check::tests::cullet_s_goods_meet_their_targets_in_a_game_day` (Cullet's spoiling, stores, traps, remains and the plan's daily yield against SMALL_CITY §2 and §4).

### Driving it

```bash
R=core-decay-$(date +%H%M%S)
python3 "$V" launch --run "$R" --seed cullet-laws > ".local/living/verify/$R/launch.txt" 2>&1
python3 .agents/skills/verify-core/scripts/scenes.py decay --run "$R" [--game-hours 24] > ".local/living/verify/$R/decay.txt" 2>&1
python3 "$V" cleanup --run "$R"
```

A whole game day (the default) is 48 real minutes on Cullet's day; `--game-hours 2` takes about 5 minutes and checks the same rates, with fewer sweeps.

### Gotchas

- Person `a` holds the 1,000 fish, so its pack is full and it cannot gather: person `b` stores its fish first and does the gathering.
- Regrowth follows the kind's share in each season (rules-3): Cullet's greens bed grows at half its rate in winter, so a watch across winter fails the regrowth check, which reads the elapsed time at the full rate. A `cullet-laws` world reaches winter after about five real hours.
- The storage the fish go into is the shipped `storage` (`holds: 120`); the 100 stored fit.
- The two people are held on `wait` for an hour; they grow hungry over a whole Cullet day but do not starve, and nobody eats the fish.

## Winter

Since `rules-3` (docs/CULLET_RULES.md, "Storage, household stores and winter"): a resource kind's `regrow_by_season` gives the share of its `regrow_per_h` in each season (none: the shipped full, full, full, none). The authority weights the time since a node was written by season (`living_rules::regrowth_ms`); minds are told what winter does from the same table (`Scripts::seasons_words`, the script's `seasons_text()`).

### Sub-features

- On the winter fixture (`scripts/winter.json`: Cullet's laws on a 4-minute day and a 4-day year, no wild nodes), in the world's own winter (the year's last quarter, from day 4's midnight; about 11 real minutes after creation): a placed fishing spot, emptied in winter and gathered once about 45 s later, held its `regen` × Cullet's winter share (0.75) over the time since, within 0.01 (the full-rate figure is in the detail); a placed root plot, emptied first and gathered once its full rate would have grown at least a unit (about 150 s), is refused ("no nearest root_plot": a node under one unit is not `nearest`) with its row unchanged (share 0).
- Unit checks: `rules3_check::rules3_is_bit_identical` (ignored; `LIVING_OLD_SKILLS=<main's script before rules-3>`): store and take answers for every structure kind, every skill's and law's words, the minds' world text and 52,920 node amounts across the seasons are bit-identical for the shipped kinds. `script::tests::a_store_holds_what_its_kind_holds`, `script::tests::regrowth_by_season_is_a_value_on_each_kind`, `season_tests::seasons_split_time_on_growings_quarters`.

### Driving it

```bash
R=core-winter-$(date +%H%M%S)
python3 "$V" launch --run "$R" --seed "$PWD/.agents/skills/verify-core/scripts/winter" > ".local/living/verify/$R/launch.txt" 2>&1
python3 .agents/skills/verify-core/scripts/scenes.py winter --run "$R" > ".local/living/verify/$R/winter.txt" 2>&1
python3 "$V" cleanup --run "$R"
```

Start the scene right after launch: the world's clock runs from creation and winter lasts 4 real minutes (the scene needs about 2 of them). No clock is changed.

### Gotchas

- Launch must keep the seed's own laws (`seed_laws` in `state.json`, "kept as installed at creation"); a harness that installs the plain script over them leaves the world without Cullet's laws, and the scene's first check fails.
- The CLI reads a negative number as a flag: `place_resource` offsets are positive (`spacetime call ... -1.0` is refused as "unexpected argument").
- Every person is held on `wait`: the fixture's band runs instinct graphs and, hungry, forages from the placed nodes (a stranger's harvest moved the fishing spot's row in `core-r3-winter3`).
- The people grow hungry on the 4-minute day (hunger 2.4 a game hour is about 14 a real minute) and start starving after about 7 minutes; at Cullet's −0.5 a game hour they are far from death when the scene ends.
