# verify-core: laws-about-list

## 2026-11-13 laws-about-list on main `ec80c341` (Spark)

The world constants' words are asked one constant at a time (`law_about(l, name)` in `skills.rhai`, a `switch` of 126 arms) and joined in Rust (`Scripts::read_laws_about`), so no value the script returns holds them all: Rhai 1.27 counts every string inside one value against `max_string_size` (`calc_array_sizes` and `calc_map_sizes` add their strings up), so a list or map of them would have kept the ceiling. A script with only the old `laws_about(l)` map is still read.

- Cargo `living-rules`: 318 passed. New `many_long_words_for_the_constants_install`: a world with 150 more constants and long words for every one (about 50,000 characters, over 3× the 6,144 limit and today's total) installs and reads each constant's own words. `the_constants_words_are_read_with_the_compile_s_budget` rewritten for `law_about` (one constant's words past the running world's operations still read at compile; unreadable words refused as such); `world_text_is_built_from_the_laws`'s missing-words case on the new form.
- `just living-check` through the build slot: passed (exit 0, 666 s).
- Scenes on scratch `slop-move-stdb` (:3361), never the trial server or the paused reference worlds:
  - `core-lal-042145` (default seed): `tick` 6/6.
  - `core-lal2-042253` (`--seed cullet-laws`, a world whose own `laws.rhai` overlay, 24,215 bytes, composes over the shipped script and is checked at install): `laws` day part 9/9, including "the installed script is the shipped one with the seed's laws composed over it", the seed's need rates and the seed's day and known-figure distances. The night part did not run: the run's own 1,500 s timeout ended it while it waited, without changing the clock, for 21:00 on the world's clock (about 6 real minutes later). Not a failure; rerun the night part after the 04:55-07:30 quiet window.
  - Evidence: `.local/living/verify/core-lal-042145/`, `.local/living/verify/core-lal2-042253/`.
