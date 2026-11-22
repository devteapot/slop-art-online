# A player's lines as rows (`experience-incremental`): the player surface

Validated on the dev-box on branch `experience-incremental` from `origin/main` `9ed12f51d` (authority as at `48e401906`). Server `so-stdb` (private, `127.0.0.1:3378`); `performance` governor. No paid model calls. Scoped `maintain-verification-skill` pass: the change keeps `my_experience` and adds `experience_copy`, the same rows as a table the game client reads ([verify-client](../../../verify-client/features/perception.md#lines-as-rows-experience-incremental)). This skill's scripts read `my_experience` as the player, which is unchanged, so its map has no drift. Outcome: **clean**.

## Runs

- `player-ei-11221728-default` (default seed): `outcomes.py` 14 PASS, `told.py` 12 PASS, `speak.py` 20 PASS, no FAIL.
- `player-ei-11221728-island`: `combat.py --scene death` 4 of 4 (a rejoin gets only the newcomer's kit).

## Not covered

The other scenes; nothing they read changed.
