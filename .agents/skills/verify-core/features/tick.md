# Scheduled work

## Sub-features

- Actual tick counts advance near the nominal 60 Hz cadence.
- Housekeeping refreshes `stats`.
- Pause stops tick counters, housekeeping writes and activity completion.
- Resume completes overdue work.
- `set_profile` emits real tick spans.
- Due rows (motion events by `body.next_ms`, activity timers by `activity.ends_ms`) go in due-time order; rows due at the same millisecond in an order drawn from (id, tick) every tick (`tick::tie_order`), never the index's storage order. The combat cadence's classes (`id % every`) hold phases permuted every second (`tick::cadence_turn`). Cargo `tick::tie_tests`; the scope by `det_compare.py` against builds with `LIVING_DET_NOTIEBREAK` / `LIVING_DET_NOCADENCETURN` (docs/COMBAT.md, "Two blows due at the same millisecond, and the cadence's order").

## How to get to it (user POV)

Characters move and complete actions while the world runs. An admin can pause the lab. Scheduled work lives in `living/authority/src/tick.rs:12,298`; `living/authority/src/lib.rs:61,62` installs 16,667 microsecond and one-second intervals.

## Driving it with scenes.py

Run the `tick` command in [SKILL.md](../SKILL.md). Two actors check private `clock` and public `stats`. Pause a three-second wait before a gift. The target receives no stone while paused and exactly one after resume. Keep paused before and after rows and `tick-profile.txt`.

## Gotchas

- `stats.ticks` lags behind the clock. Sample `clock.tick` and `last_ms` with the admin CLI.
- The cadence check samples across a 20-second wait and requires at least 18 seconds of
  authority clock progress at 50–65 Hz. This smoke check catches stalled or half-rate ticking.
- Pause skips scheduled work. It does not freeze wall time, aging, analytic needs or pending deadlines.
- Disable profiling and unpause in `finally`. Delete the scratch database through shared cleanup.
