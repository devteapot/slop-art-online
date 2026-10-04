# Scheduled work

## Sub-features

- Actual tick counts advance near the nominal 60 Hz cadence.
- Housekeeping refreshes `stats`.
- Pause stops tick counters, housekeeping writes and activity completion.
- Resume completes overdue work.
- `set_profile` emits real tick spans.

## How to get to it (user POV)

Characters move and complete actions while the world runs. An admin can pause the lab. Scheduled work lives in `living/authority/src/tick.rs:12,298`; `living/authority/src/lib.rs:61,62` installs 16,667 microsecond and one-second intervals.

## Driving it with scenes.py

Run the `tick` command in [SKILL.md](../SKILL.md). Two actors check private `clock` and public `stats`. Pause a three-second wait before a gift. The target receives no stone while paused and exactly one after resume. Keep paused before and after rows and `tick-profile.txt`.

## Gotchas

- `stats.ticks` lags behind the clock. Sample `clock.tick` and `last_ms` with the admin CLI.
- The five-second cadence check has a 52 to 65 Hz tolerance. It is not performance acceptance.
- Pause skips scheduled work. It does not freeze wall time, aging, analytic needs or pending deadlines.
- Disable profiling and unpause in `finally`. Delete the scratch database through shared cleanup.
