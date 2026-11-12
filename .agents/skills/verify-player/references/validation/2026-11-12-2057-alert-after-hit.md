# verify-player: alert-after-hit

## 2026-11-12 alert-after-hit: a player's sleep in a fight (Spark)

Branch `alert-after-hit` (`0d2782cf`), the trial service.

- `scripts/sleep.py` on the infant fixture (`player-alert1`): 13/13, with two new checks:
  - Struck by a resident, the player's own `human_act` sleep is refused: its log reads "You failed to sleep: you cannot sleep: you were struck moments ago".
  - With both alert laws off (`set_world_law`, restored after), a sleeping player is woken by the fight's second blow ("You woke up: A stranger is attacking you!", 1.3 s after the first, which also woke it).
- `scripts/combat.py --scene all` on the island (`player-alert4`): 47/50. The three failures are flakes under load (load average 40–56), not this change:
  - "movement keys during a throw's windup wait for it" failed in 2 of 3 runs here.
  - "letting go of the run: its breath back from a second later" fails when `breath` runs after `committed` on one world, on main too: main `619e0f9a` failed it in `player-mainbr3` (`committed,breath`). It passes run alone: main `player-mainbr1`, `player-mainbr2`; this branch `player-alert6`, `player-alert7`, all 8/8.
  - "dodging on without a pause is refused out of breath" failed in `player-alert4` and `player-alert5` and passed in `player-alert8` with the same order.
- Maintain pass, scoped to the touched feature: the `Sleep` row of `features/README.md` and `features/sleep.md` name the mid-fight cases and the `set_world_law` admin call. Rows are sorted, with no dead links. Outcome: changed. The full per-feature source wave was not run.
