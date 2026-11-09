# Town life: what clients see of residents

## Sub-features

- `act_card`, `doing` and `weather` are public (`town-public.json`). `act_card` holds one row per skill the installed script shows (`<skill>_shows()` in `living/scripts/skills.rhai`: 17 with the shipped script), with its presentation `code`, `look`, `faces` and `aside`; codes are stable across script installs (private `skill_code`), but they are the world's, not fixed numbers: read them from `act_card`. `doing` holds, per character performing a shown skill, its code, target, point and `since_ms`/`until_ms`; `weather` is one row written by housekeeping.
- `set_weather` is admin-only, like the other scene reducers (`reducers.md`).
- Like `fighter`, `doing` is joined to a body window by clients (`SELECT doing.* FROM doing JOIN body ON doing.id = body.id WHERE …`); the window is not a permission boundary. `place` rows (a resident's `work`, `square`, `inn`, `evening`) are public too, as before.

## How to get to it (user POV)

`drive.py --run "$R"` probes the three tables anonymously after the combat checks, and the permission matrix calls `set_weather` as every non-admin identity. Design: `docs/TOWN_LIFE.md`.

## Gotchas

- On the default `realm-4` seed `doing` has rows (people gather, eat and sleep); its count varies with the moment.
