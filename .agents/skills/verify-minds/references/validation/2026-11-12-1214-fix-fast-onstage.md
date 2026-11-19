# verify-minds: fix-fast-onstage

Branch `fix-fast-onstage` from origin/main `ca14ab3e` (fast-lane in), the trial service `slop-trials-stdb`.

- The fault, found by r2e's free run (`r2ef`, `arena-heavy` and `arena-kiter`, `--fake`, the `fast-lane` variant): every fast request was answered "kept: off stage" (8 and 2), and no fast call was made. With the shipped staged model mix, a character no player watches is off stage for model routing; the fast lane read that as the level of detail's off stage. In an arena, with no player, the lane never ran.
- The fix: the lane skips a character only when the level of detail is on (`LIVING_LOD`) and says off stage.
- `fast-lane` now routes the eye through a staged mix, as the shipped models do. It passes (`minds-fos2-131311`): 2 fast requests, the reason "Kelkelly attacked you (10 damage)", one refused by the plan check. The first attempt (`minds-fos-131023`) stopped in the harness ("KeyError: 'staged'": the default must name a profile), so the mix is assigned to the eye instead.
- Not run here: the same case on main without the fix. The `r2ef` run is that evidence.
