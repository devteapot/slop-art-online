# A world's own day and laws

Since `rules-1` (2026-11-11, [Cullet's rules](../../../../docs/CULLET_RULES.md)). A seed may set its day's length (`day_minutes`) and carry a Rhai laws overlay (`laws`, or `laws_file` under `living/seeds`), composed over the shipped script and installed when the world is created. Need rates are written per game hour (`rates` returns `per: "hour"`) and the engine turns them into real time for the world's day. Night is the `daylight(hour)` law over `night_hours()` (half light is night; a world may ease dusk and dawn). A creature may be seen farther than an onlooker's sight by a light on it (`glow(a)`, bounded by `senses_law`'s `reach.glow`; lamplight is `a.actor.lit`, within a structure kind's `lights`), and `perceived_of` may read the distance (`p.dist`).

## Sub-features

- The world's `day_ms` is the seed's `day_minutes`; the installed `script` row is the shipped script with the overlay after `// ---- floor overlay ----` (replaced functions as `base_NAME`).
- A person's live need rates (`vitals.hunger_rate`, `energy_rate`) are the overlay's per-hour numbers times 60,000 over the game hour's real milliseconds, times the body's appetite or over its endurance.
- By day a player perceives figures to the day sight (Cullet: 48 m) and not beyond; a figure is named, with a health band, only within the knowing distance (24 m): beyond it the `projected` row has no name, the stranger's label and band 255. The name is known because the figure said it beside the player (an introduction, `acquaintance`).
- At full dark (21:00): the dark's sight (14 m: 10 m seen, 16 m not), a figure carrying a torch seen from the carried light's distance (44 m), someone standing at the seed's lamp seen from about 21 m (between the dark's 14 and lamplight's 28), and the same distance off the other way, away from any light, not seen.
- An ordinary night outside costs no health.
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
- The scene needs the seed's lamp (`structure` kind `lamp`) with an open line from it; without one it fails "the seed has a lamp with an open line of sight from it".
- These checks do not measure cost: longer sight and re-projection every sweep cost more per player (docs/CULLET_RULES.md, "Costs").

## Who heard a line (`speech_audience`, 2026-11-11, branch `exp-greet`)

A shipped law, off by default. With it on, `speak` (`living/authority/src/perceive.rs`) writes one row per line to the private `audience` table (`tables.rs` `Audience`, `Hearer`). The row lists each person who heard the line (the speaker's hearers within hearing), the distance to each and how far each stood off the speaker's facing (`common::heading`, radians, 0 straight ahead). Rows older than 60 s are deleted by the next line (range on the `at_ms` index). Nothing reads it but the mind service under `LIVING_GREET` (verify-minds `greet`). With the law off nothing is written, so the cost is one law lookup per line. With it on, a line costs one insert, the distance and angle per hearer, and the expired rows' deletes, and the only subscriber is the mind service.

```bash
R=core-audience-$(date +%H%M%S)
python3 "$V" launch --run "$R" && python3 "$V" doctor --run "$R"
python3 .agents/skills/verify-core/scripts/scenes.py audience --run "$R" > ".local/living/verify/$R/audience.txt" 2>&1
python3 "$V" cleanup --run "$R"
```

The scene places a speaker, a person 1 m east, one 4 m east and one 13 m east (beyond the shipped 9 m hearing), turns the speaker east (`face`) and speaks through `mind_say`. Checks: law off, no row. Law on (the shipped script with `speech_audience: true`, installed with `install_script`): one row, said to no one, with the two within hearing and not the third, distances about 1 and 4 m, both under 0.35 rad off the facing. A line 61 s later deletes the first row. The shipped script is installed again at the end. Evidence: `audience-line.json`, `audience-audience-off.json`, `audience-audience-on.json`, `audience-audience-later.json`, `audience-results.json`.
