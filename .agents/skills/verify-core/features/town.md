# Town life

Residents of a land world's settlements live a daily rhythm on their own graphs. Every resident has a mind (since 2026-11-11); this skill starts no mind service, so they live on their starting ways with a deliberation pending. Design and measurements: `docs/TOWN_LIFE.md`; personal rhythms: `docs/SEEDED_LIVES.md`.

## Sub-features

- **Places a resident knows.** World creation seeds `place` rows per settled resident (`work`, `square`, `inn`, `evening`) from the seed's `town_life` (`living/authority/src/town.rs` `seat`): lot kinds of the resident's own settlement, a resource or structure kind near it, or `plaza`; only spots a path reaches from home. Graphs reach them as `{"place": "work"}`; `home` stays `character.home_x/home_y` (the household's door).
- **Starting ways.** The seed's `ways` (`living/seeds/island.json`) override the repertoire's `common` routines by name, give each occupation its work routine, and replace the desires `top` (`seed.rs` `give_repertoire`). Rules test `graph::seed_repertoire_tests::island_ways_are_valid` checks every routine fits a person's body and every occupation compiles within limits.
- **Daily rhythm, each their own.** Each person has a `rhythm` row (private): when they rise and go to bed and how long their evening is, from the seed's `residents[].rhythm` or drawn per person at birth (`seed::drawn_rhythm`, from the person's id alone). Graphs read it as the `bedtime` and `evening` weights and conditions (`common::day_phase`); without a row, the world's night and 18–22. Starting desires are varied per person (`genes::vary_ways` at seeding). Work by day at the workplace (`keep`, `gather`, `cook`, `read`, `tend`, `store`); children `play` near home or the square; one's own evening at the household's evening place (inn, square, home or work: `town_life.evening`) resting and nodding; one's own bedtime at home asleep or resting; mornings away to work. A person's new day begins at its own rising (a deliberation request, once a day), not at a dawn broadcast.
- **Weather.** One public `weather` row, drawn per spell from the world's seed and its climate (the seed's `weather`: `spell_s`, `rain_share`; none, never rain) by housekeeping, or held by the admin scene reducer `set_weather(raining, secs)` (`secs = 0` hands it back). `{"raining": true}` and the `rain` weight read it; rain out from under a roof is tiring (`rates` in `skills.rhai`, `wet(a)`).
- **Gestures and their meaning.** `wave`, `nod`, `face`, `step_aside`, `keep`, `play` are skills in `skills.rhai` with `_check`/`_duration`/`_done` and a `<skill>_shows()` trait map (`look`, `faces`, `turn`, `aside`, `record`; `living_rules::social`). `hail` (an effect) greets the target: `mind_state.hailed_ms`/`hailer`, `{"hailed": N}`, target `"hailer"`, weight `hailed`. A gesture back within 10 s answers instead of greeting again.
- **Commotion.** Target `"commotion"` and weight `commotion`: the nearest `attack`/`threat`/`killing`/`death` chronicle row of the last 8 s within sight.
- **What clients see.** `act_card` (one row per shown skill: code, look, faces, aside) and `doing` (per character: code, target, point, since/until), public; `skill_use` keeps each `record` gesture from intention to outcome.

## How to get to it (user POV)

Launch an island run (`$V launch --run core-<x> --seed island`) and drive `scripts/town.py --run core-<x>`. It holds the sky dry with `set_weather(false, 3600)` and waits for the world's own hours (12-minute day, no compression), so a full run takes about 14 minutes. Scenes: `work` (10–15 h), `greet`, `approach`, `speak`, `aside` (8–16 h; the player identity through `human_act`, `human_move` and `human_say`), `rain` (11–15 h; `set_weather(true, 120)`), `wolf` (13–17 h; admin `place_at` a bold wolf beside workers, `kill` afterwards), `evening` (18.6–19.8 h), `night` (0.5–4 h; also checks that each keeps their own hours: the spread of `rhythm` rises and bedtimes), `morning` (7.2–9.5 h). `--scene NAME` runs one. `--scene census` records, once per world hour for a day, where adults are and what everyone does, on an undisturbed world with its own weather (evidence, no checks).

## Evidence

`town.json` (every check) and `town-<scene>.json` (positions now, activity, `doing` code and places per resident; skill uses; chronicle for the wolf) in the run directory; `actions.log` holds every call.

## Gotchas

- Positions are evaluated from each `body` segment at the driver's clock (`pose`), which is the host clock the container shares.
- The natural weather is held dry for the run; without that a natural spell can rain on any scene.
- `aside` needs a resident standing where at most 17 of the 25 surrounding tiles are walkable with a clear 6-tile approach; it retries for 30 s and reports when none is found.
- Scenes assert shares and kinds, not exact counts: who stands where depends on the RNG and the hour the run started.

## Hospitality

`host` (docs/TOWN_LIFE.md, "What residents can do"): `host_check`, `host_duration` and `host_done` in `living/scripts/skills.rhai`; `host_done` names the morning hour the stay ends (`until_hour`). The engine (`town::host`) finds the house at the actor's home door, refuses without one, writes a private `guest` row and the guest's `lodging` place, and chronicles it. `town::guests_leave` (housekeeping, 1 Hz) ends stays through the `guest.until_ms` index; `town::guest_of` makes taking from the host household's store no theft during a stay. Driven by verify-player's `host.py` (a resident's graph runs the skill).
