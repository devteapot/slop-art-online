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

- `launch` does not install the plain `skills.rhai` on a seed with its own laws (it would drop them); `state.json` records `seed_laws`.
- `install_script` installs a whole script: installing the shipped one on such a world removes its laws until it is created again.
- The scene needs the seed's lamp (`structure` kind `lamp`) with an open line from it; without one it fails "the seed has a lamp with an open line of sight from it".
- These checks do not measure cost: longer sight and re-projection every sweep cost more per player (docs/CULLET_RULES.md, "Costs").
