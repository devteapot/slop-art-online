# The balanced fast frame: cases, maintenance pass and the paid frame trial

Branch `fast-lane-frame` (code `ba6fabec`, trial driver `6533b711`, base main `97858bbb`). See docs/FAST_LANE_FRAME.md.

## Free cases (fake model, trial container)

- **`minds-flf-1021`.** `fast-lane` and `fast-takeover` passed, and so did the mind's cargo tests (128 passed, 14 ignored). Those tests include `the_balanced_frame_shows_four_ways_and_sells_none`, `the_request_says_how_one_is_and_what_one_sees`, `no_patch_is_refused_for_retreating` and `the_prompt_has_no_count_and_no_tactic`.
- **`fast-frame`, first three attempts: case faults, not product faults.**
  - `minds-flf-1021`: the check for "no identity call" also matched an ordinary consolidation. It now matches the identity prompt.
  - `minds-flf2-1025` and `minds-flf3-1027`: no second request came under `fast_frame` 1. The installed flight took the eye away, and the attacker was not re-armed. The case now re-places both and re-arms the attacker, as `fast-lane` does.
- **`minds-flf4-1028-fast-frame`: pass.**
  - The persona was `martial-1`, installed from its sheet, with the genome's traits equal to the sheet's.
  - The How you are now line was "2 people; of them 1 visibly in a hostile move (1 at you), 1 you count as friends or family, 0 you count as enemies". It equals the `fast_sight` row for the issue. The stranger 28–40 m away was not counted.
  - The unconditioned flee was installed.
  - SHA-256 of the v1 text is `f15786af…` and of the v2 text `d95af1a6…`, both on that world's rules text.

## Maintenance pass (scoped)

Outcome: **changed**, scoped to the fast lane. The other 26 feature files were not source-read or re-driven: nothing they map changed.

- **Index.** `features/README.md` has a new row for `fast-frame` under `fast-lane.md`. No missing, dead or duplicate entries were found among the fast-lane rows.
- **Source.** `fast-lane.md` had drifted. Its sources did not name `fast_sight`, the `fast_frame` law or `fast_now`. They do now, and the file says that `change_of` checks only a reply's form. The case registers itself with `@case`.
- **Live.** `fast-frame`, `fast-lane` and `fast-takeover` were driven, as above. The trial below drives `trials.md`'s battle path with real fast calls.

## The paid trial (authorized by the general coordinator)

`living/tools/flf-all.sh --authorized` runs `flf_trial.py`. Arm B, 100 fighters, v1 v2 v1 v2, five minutes each, from 13:07 to 13:35 CET. It held `battle.lock` across all four runs, after waiting 86 minutes for it.

- Each run held 60 ticks a second. Load averaged 2.1–2.8. Every tick watch saw the clock advance.
- The v1 system text is byte for byte the replicates' (`f50c888e…`).
- Spend was $1.1441 against the $2 stop. All four worlds were deleted. The key copy was removed, and 0 files held key fragments.
- **Result.** Frame 2 cut unconditioned retreats from 40% to 13% of installs. Contact (42.2% → 37.4%), engagements (2.15 → 1.23 a fighter-minute), attacks (6.47 → 5.45) and timed defence (62.6% → 55.6%) all fell. Breath-guarded retreats dominate both frames. The tables, per arm and per persona, are in docs/FAST_LANE_FRAME.md.

**Not covered.**
- Lane-off runs with personas.
- Arms without How you are now.
- Ten-minute runs.
- The `LIVING_FRAME=player` frame with `fast_frame` 2. It shares the opening, but was not driven.

Evidence: `.local/living/verify/minds-flf*`, `.local/living/flf-trial-20261119T104130Z/` (report.json, summary.json, per-run logs and watch files) and `.local/flf/`, archived in `~/slop-evidence/fast-lane-frame-20261119.tar.zst`.
