# verify-minds: fix-sleep-thinking after merging skills-layout

## 2026-11-12 fix-sleep-thinking, merged with main `f7af6d49` (Spark)

The trial service `slop-trials-stdb`, the fake model, a private target dir. The `sleeper` case registers itself with `@case('sleeper')` (`verify_minds.py --list` names it). `minds-stm2-sleeper` passes (`--no-unit-tests`): an offer to the sleeping actor waits in `slumber` with no thought, pending row or model call, and an attack wakes it with "You woke up: … is attacking you!" and the offer on the next line. `just living-check` passes on the merged head. `latest_validation.py --check`: ok. Not run again: the verify-core scenes (no authority change since `19dc327b`, `core-stm2`: `sleeper` 13/13, `cues` 13/13; `core-stm1` `tick` 6/6) and `cues_mind` (`minds-cues-stm1` 6/6).
