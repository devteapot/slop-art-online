# verify-core: alert-after-hit

## 2026-11-12 alert-after-hit: no sleep in a fight, every blow wakes (Spark)

Branch `alert-after-hit` (`0d2782cf`, main `da3ff142` merged), the trial service `slop-trials-stdb`, private `CARGO_TARGET_DIR`.

- `alert_after_hit` (new; default seed): `core-alert1` 8/8, `core-alert3` 8/8. One blow, then sleep is refused ("you cannot sleep: you were struck moments ago") and not taken for 15 s; it begins 15–25 s after the blow. With the attacker 2 m off, past 15 s it is refused as "you cannot sleep: someone who struck you is close"; it begins once they walk away, under 30 s from the blow. With both laws off, a sleeper is woken by a fight's second blow (within 30 s, not a first), "You woke up: … is attacking you!".
- Regressions: `tick` 6/6, `skirmish` 8/8 (`core-alert3`); `sleeper` on the infant fixture 25/25 (`core-alert2`).
- Rules unit tests 297 pass. `just living-check` passes (all steps). The script bench needed the new field in its fixtures.
- Maintain pass (maintain-verification-skill), scoped to the features this change touches; the full per-feature source wave was not run. Index hygiene: two pairs of rows were out of order after merges (Attention cues / Battle scale; Speech / Speech when another spoke first), now re-sorted. The new row "A body does not fall asleep in a fight" is in `features/README.md` with its section `needs.md#sleep-in-a-fight`. No dead links or unlinked files. Outcome: changed.
