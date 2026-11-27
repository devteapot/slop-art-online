# player-bow-launch: `combat.py` `bow` scene under load

Branch `player-bow-launch` from `origin/main` `a2daf9842` (test-only fix in `.agents/skills/verify-player/scripts/combat.py`), private SpacetimeDB `v2.14.1` (`slop-bow-20261127`), `island` seed.

- **Cause:** `scene_bow` observes missile launch (`kind=10`) and impact (`kind=11`) by polling `my_combat` (`combat_seen`) over HTTP, where rows expire after `SEEN_MS = 4_000` ms (`living/authority/src/combat.rs:27`, deleted in `living/authority/src/frame.rs:1142-1145`). Previously `scene_bow` ran 4 sequential HTTP SQL queries (`struck()` calling `seen(st)`, `character`, `vitals`, plus `inventory`) between `wait_outcome` and the `ev = seen(st)` check. Under heavy host load (55–58 in the `relation-fight-prune` gate, where 6.5 s elapsed between impact at `01:45:57.514` and the check at `01:46:04`), `combat_seen` had already pruned the `LAUNCH` row.
- **Repro on `origin/main` (`a2daf9842`):**
  - Quiet (`bow-base`): 10/10 pass (`0` failures).
  - Loaded (private container + `combat.py` + 70–80 CPU spinners pinned to core 0): `4/7` `launch speed []` failures (`REPRO #1` 1/2 under 80 spinners; `REPRO5` wave 1: 3/5 under 70 spinners across 5 parallel worlds `bow-f1..5`).
- **Fix (test-only):** `scene_bow` now reads `ev = seen(st)` immediately after `wait_outcome` and passes `ev` into `struck(..., ev=ev)` (removing 4 HTTP round-trips before the read), filters `launch`/`impact` to `at_ms >= t0`, and retries (up to 4 attempts) only when `not (launch and impact)` and authority timestamps prove the poll completed `>= 3500` ms after `u["released_ms"]` (`SEEN_MS = 4000`). Assertions are unchanged.
- **After fix:** 12/12 pass (`0` first-run failures) across 2 clean daytime waves of 6 parallel worlds (`bow-v1..6`, `bow-v7..12`) under 70 spinners pinned to core 0; 10/12 passed on attempt 1 (`retries=0`), and 2/12 (`bow-v7`, `bow-v11`) hit 4378 ms and 7585 ms poll delays, re-staged, and passed on attempt 2.
- **Evidence:** `~/slop-evidence/player-bow-launch-20261127.tar.zst` (`.sha256`).
- **Not run:** Other `combat.py` scenes (only `struck`'s optional `ev=None` parameter and `scene_bow` changed).
