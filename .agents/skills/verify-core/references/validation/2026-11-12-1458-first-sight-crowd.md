# Core validation record

## 2026-11-12 first-sight-crowd: whom someone goes to, named; a line that waits when another spoke first (Spark)

Branch `first-sight-crowd` (`fc4dd88f` plus the records), origin/main merged; the trial service `slop-trials-stdb`, default seed, `scoped`, private `CARGO_TARGET_DIR`.

- **`core-fsc3-152222`** (the merged head):
  - `heard_first` (new) 12/12;
  - `doing` 7/7, with its checks now "goto → you" and "follow → a stranger";
  - `first_sight` 22/22, `sight` 6/6, `say` 34/34.
- **Earlier runs on this branch:**
  - `core-fsc-…`: `heard_first` failed "O's mind is asked to think". The held line's request was refused within `think_min_s`, because the delivery being held had just set `deliberated_ms`. Fixed with `perceive::ask_again`.
  - `core-fsc2-…`: `heard_first` failed "no one else spoke to U: said". That was a scene bug: the step's 10 s decision window still held the previous step's line. The scene now waits 11 s.
  - On that same module: `doing` 7/7, `first_sight` 22/22, `crowd_sight` 8/8, `sight` 6/6, `say` 34/34.
- **Cargo:** rules `script::tests` 50 passed, with `heard_first_rethinks_is_the_world_s_law`; authority `perception` and `brain` tests.
- **`just living-check`** passes (794 s).
- **Cleanup:** every run's world was paused (read back paused) before cleanup.
