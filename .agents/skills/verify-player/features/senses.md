# What the player's character senses

Since 2026-11-11 (branch `rules-senses-outcomes`; docs/PERCEPTION.md "My senses"). The world's `senses(a)` law, run by the authority with all the character's facts, reaches the player through `my_senses`, so the game client no longer runs the law on the few facts it has.

## Recipe

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-senses-$(date +%m%d-%H%M%S)
$V launch --run $R && $V doctor --run $R
.agents/skills/verify-player/scripts/senses.py --run $R
$V cleanup --run $R
```

Any seed with the shipped senses law (the default `world`). Admin calls set the scene only: `set_world_law fov_on`, `grant_items` (a torch, at night), `kill` (the second identity's character). About 30 s. Writes `RUN/senses.json`.

## What it checks

1. After `join`, `my_senses` holds one row, the player's character's: sight 11 m by day, 6 at night, 9 with a torch at night; hearing 9 m; no field (its five numbers 0).
2. For 6 s with nothing changing, the row is not written again: the same `at_ms` and values (the authority asks the law at the player's frames, every 250 ms, and writes only a change).
3. `set_world_law fov_on true`: within 3 s the row has the field (focal 70°, side 110°, a third, near 3 m, or 2 m in the dark, margin 10°) and a later `at_ms`; off again, no field and its numbers 0.
4. At night only (skipped by day, with the reason in the evidence): a torch granted into the pack takes sight from 6 m to 9 m.
5. A second identity (`token2`, joined) reads only its own row; the owner's `character_senses` has one row per played character (`presence`).
6. The second identity's character killed (`kill`): its row is gone and its view empty.

## Not covered

- The game client reading the view instead of running the law: the laptop's client change (`verify-ui`).
- A world whose law reads more than night and a torch (a stage, a gene, lamplight): the row is the authority's own `senses_of`, the same answer every look uses, so `verify-core`'s `senses` scene covers the law itself.
