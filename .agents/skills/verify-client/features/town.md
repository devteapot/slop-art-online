# Town life: what clients see of residents

## Sub-features

- `act_card` and `weather` are public, and `doing` too in an open build (`town-public.json`); in a scoped build `doing` is private and a player receives its own row through `my_doing` and what the creatures it perceives are doing through `seen_doing` (frame copies of others only; [perception.md](perception.md)). `act_card` holds one row per skill the installed script shows (`<skill>_shows()` in `living/scripts/skills.rhai`: 18 with the shipped script), with its presentation `code`, `look`, `faces` and `aside`; codes are stable across script installs (private `skill_code`), but they are the world's, not fixed numbers: read them from `act_card`. `doing` holds, per character performing a shown skill, its code, target, point, `since_ms`/`until_ms` and `indoors` (a rest taken at home, out of sight of the street); `weather` is one row written by housekeeping.
- `set_weather` is admin-only, like the other scene reducers (`reducers.md`).
- The game client reads `doing` only through `my_doing` (its own) and `seen_doing` (the creatures it perceives). In an open build a client could still join `doing` to a body window (`SELECT doing.* FROM doing JOIN body ON doing.id = body.id WHERE …`); that window is not a permission boundary. `place` rows (a resident's `work`, `square`, `inn`, `evening`) are public only in an open build; a player reads its own through `my_places`.

## How to get to it (user POV)

`drive.py --run "$R"` probes the public tables anonymously after the combat checks, and the permission matrix calls `set_weather` as every non-admin identity. Design: `docs/TOWN_LIFE.md`.

## Gotchas

- On the default `realm-4` seed `doing` has rows (people gather, eat and sleep); its count varies with the moment.
