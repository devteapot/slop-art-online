# relation-fight-on: the player's strike under the law on by default

This run is on branch `relation-fight-on`, commit `0f743d6ab`, on origin/main `9cbb8d50c`. It used a private SpacetimeDB 2.14.1 (`slop-rfon-20261126`) and the fake model, with no paid calls. The full record is verify-core's `2026-11-26-1305-relation-fight-on.md`.

- `combat.py`, all scenes, on a fresh island world (`player-rfon-133729`): **60/60**. This includes "the player's strike makes the one struck its character's enemy (relation_fight: enemy, by player)".
- Scene `strike` now sets `relation_fight_on` on explicitly and no longer sets it off afterwards, since on is now the shipped value.
- A first attempt stopped before any check, because no player was joined (`combat-nojoin.txt`). After `verify.py player join`, the run passed.
- Not covered: the other verify-player scripts. This change does not touch a player reducer.
