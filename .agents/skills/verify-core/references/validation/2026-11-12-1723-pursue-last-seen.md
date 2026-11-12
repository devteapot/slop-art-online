# verify-core: pursue-last-seen

## 2026-11-12 pursue-last-seen on main `33b50ced` (Spark)

Change: every steering goal toward or away from a creature is held by the sight rule (`motion::held`, now with a pursuit mode); a pursuit goes to the last-seen place and ends "lost sight of them" there; a flight runs from it; graph leaves for `flee`, `goto` and approaches keep running while their target is out of sight; `chase_lost_share` removed; the flee map counts how far a spot lets the body keep running (`FLEE_ON_M`). Trial server, private target dir `~/slop-move-target`. Evidence copies: `~/slop-evidence/pursue-last-seen/`.

- Cargo `a_flight_looks_for_open_ground` with the default seed's ground at (92.5, 12.5) at night sight: the old flee-map scoring is cornered at (16.4, 17.8), the notch where a fleer was cornered live; the new passes.
- New scene `pursue_last_seen` (`core-pls-20261112-153834`, `core-pls-20261112-155342`, and after the rebase `core-pls3-*`): 6/6 each time. Two pursuits ended 0.8 m from the last-seen place, 9–12 m from the hidden target, told "You failed to goto → person: lost sight of them"; the flight ran 17.7 m from the threat's last-seen place.
- `flee_wall` with a chasing threat added: 8 flights a run, none cornered; from a still threat 16.9–23.5 m, from a walking chaser 29–48 m (where the fleer stopped, from where the threat began). On the first world before the notch fix, one flight at (92.5, 12.5) at night was cornered in a one-tile notch: the fix above.
- `intents`, `moves` pass; `flee` on `stage1-acts` 4/4.
- Wolves before and after (`chase`, `fights`, `wolf_ecology.py`): docs/MOVEMENT_MIND.md, "Built: pursue-last-seen". The before eco worlds were paused for the quiet window and their clock jumped 22.7 game hours on resuming: compared over the first 13.6 game hours only.
- `just living-check`: see the branch's final record line in the report.
