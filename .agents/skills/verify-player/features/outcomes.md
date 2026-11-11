# How the player's acts and death came out

Since 2026-11-11 (branch `rules-senses-outcomes`; docs/PERCEPTION.md "Act outcomes"). A private `act_outcome` row per experience line that tells an outcome, keyed by the line's id, read through `my_act_outcomes`: `kind` (`act`, `own`, `death`), `ok`, `skill`, `code` (`living_rules::outcome`), `what`, `why`, `other` (the killer).

## Recipe

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-outcomes-$(date +%m%d-%H%M%S)
$V launch --run $R && $V doctor --run $R
.agents/skills/verify-player/scripts/outcomes.py --run $R
$V cleanup --run $R
```

The default seed. Admin calls set the scene only: `grant_items`, `kill`. About 40 s. Writes `RUN/outcomes.json`. A death by killing (code `killed`, the killer in `other`, the line "You were killed by …" with the killer as the dead knew them) is checked by `combat.py --scene death` on an island run ([combat.md](combat.md)).

## What it checks

1. `eat berries` with none: an `act` row, not ok, code `check`, skill `eat`, the check's words in `why`; the row's id is its `act` line's in `my_experience`.
2. The same with berries granted: ok, code `done`, `why` empty.
3. `{"do":"graze"}` (a moment skill, run as a one-shot graph): an `own` row, not ok, code `check`, skill `graze`. The row can arrive up to one release (100 ms) before its line; the script waits for the line.
4. 70 refused acts in a row: at most 64 rows, the owner's count equal to the view's, and every row's line still in `my_experience`.
5. A second identity (`token2`, joined) reads none of the player's rows; `act_outcome` is refused to anonymous SQL.
6. The admin's `kill` with its own words: a `death` row, code `other`, its line "You died (verify outcomes)." in `my_experience`, read while the character is dead.
7. `join` again: the dead character's rows are gone (`set_player`).

## Not covered

- `unreadable`, `busy`, `expired`, `timing`, `reach`, `broken_off` and `set_aside` live: the same write path as the codes above; `unreadable` cannot come from `human_act` (its parse error is a reducer error).
- `starved`, `cold`, `exhausted` and `old_age` live: set at their `die` call sites.
- The game client drawing from the rows: the laptop's client change (`verify-ui`).
