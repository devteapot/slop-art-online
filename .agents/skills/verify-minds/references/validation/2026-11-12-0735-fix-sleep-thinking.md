# verify-minds: fix-sleep-thinking

Moved from `references/validation.md` by `latest_validation.py --split`.

## 2026-11-12 fix-sleep-thinking (Spark)

Branch `fix-sleep-thinking`, the trial service `slop-trials-stdb`, the fake model, private target dir.

- `sleeper` (new). The first two attempts failed on the case itself, not the change: an admin `set_behavior` before the mind started cleared the first request, so no first thought came. The case now asks it with `run.request`. `minds-sleeper3-sleeper` passes, and after merging main `49dfc2cd` `minds-sleepreg1-sleeper` passes. An offer to the sleeping actor waited in `slumber` with 0 deliberate model calls, no thought and no pending row for 15 s. The other adult's graph attack woke it, and the next thought's reason was "You woke up: Femi is attacking you!\nFemi offers you 1 stone for 1 wood. …". The percept read "You woke up: Femi is attacking you!".
- After merging main `c67bb6e1`, `minds-sleepm3-sleeper` passes ("You woke up: Kelkelly is attacking you!" with the offer on the next line).
- After merging main `2b163773` (attention-cues): `minds-stm1-sleeper` passes; `cues_mind.py` (`minds-cues-stm1`, trial Neo4j) 6/6, 0 nodes left; the mind's non-ignored tests 108 pass.
- `minds-sleepreg1` also ran `roundtrip`, `reasons` and `takeover`: all pass. The mind's non-ignored tests pass (105).
- Measurement, fake hamlet batch `sleep1` (55 min, one game day including its night, `latency.json` fake latencies, 12 thinkers). Variant `default` ran this branch; variant `main` (`wasm_tag`) ran origin/main `49dfc2cd` with the same seed and mind. Counted from the per-character journals:
  - main: 290 deliberations, 26.7 per resident-hour; 42 began while the resident was asleep (at the census samples on both sides).
  - branch: 256 deliberations, 23.5 per resident-hour; 6 began while asleep.
  - On the branch, 27 deliberations were "You woke up." requests, and only 1 "new day" was asked on its own (11 on main). The rest of those new days now wait and are asked on waking.
  - The remaining 6 "asleep" deliberations are what 30 s census sampling cannot separate: bodies that woke, thought, and slept again between two samples.
  - The fake's replies make "acts keep failing" the main cause in both variants (about 160), so the cut in a real-model batch should be larger. bi1 measured 23% of deliberations asked while asleep.
