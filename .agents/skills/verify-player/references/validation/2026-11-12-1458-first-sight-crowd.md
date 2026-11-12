# Player validation record

## 2026-11-12 first-sight-crowd: a walker's target named as the resident perceives it (Spark)

Branch `first-sight-crowd`, origin/main merged, the trial service.
- **Island, `approach.py`:**
  - `player-fsc-island-153133`: 4 PASS, 2 FAIL. R's first sight read "…, 9 tiles west, walk → you." (pass). The player's walk step found no scene entry, and the bystander saw the body at rest (vx 0): the walk did not happen in that window.
  - `player-fsc-island2-155641` (fresh): 5/5. The scene reads `walk → you` for the walking player and `goto → you` for the AI walker, `wait` standing, and both clients see the bodies move with no `doing` row. The first-sight step was not observed that time.
- **Default seed, `first_sight.py`** (`player-fsc-world-153133`): 7/7.
- **Cleanup:** worlds paused before cleanup.
