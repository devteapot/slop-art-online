# 2026-11-13 0448 UTC: Cullet after island-pack-check (animals on their own stream)

- **Branch and module:** main after `island-pack-check` (6e2e6483) and `sex-1` (2020ea1e6), built in the dev-box coordinator worktree.
- **Command:** `generation.py --run generation-cullet-animals-20261113-054621 --feature worlds --seeds cullet`, on dev-box's `coord-stdb` (127.0.0.1:3319), holding the scene-gate lock.
- **Result:** `cullet` passes 350 of 350 checks. These include the animal counts and placement, the plan checks, and the `sex-1` body-sex and looks-by-sex checks. Cleanup passes, and the original seeds are unchanged.
- **Animal placement moved once, by design.** `island-pack-check` gives animals their own seeded stream (`STEP_ANIMALS`), so every world's animals now have a new layout per seed, new geneses only. Any record before this one that compares Cullet's animal positions refers to the old layout.
- **Evidence:** `.local/living/verify/generation-cullet-animals-20261113-054621*` in the coordinator worktree.
- **Not covered:** other worlds (the Spark ran `--feature all` on island-pack-check), and repeatability across two geneses of the new layout beyond the driver's own `worlds` repeat.
