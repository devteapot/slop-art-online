# verify-core: correction to `2026-11-12-1316-battle-scale.md`

Corrects `2026-11-12-1316-battle-scale.md`: the ticks per second of the first quiet window's acceptance runs (`minds-q100-141730`, `minds-q200-144827`: 55.0 and 26.8 ticks/s) and the diagnosis runs quoted as their before (19.5 and 10.0).

`bench.py` divided the `stats` row's tick count, which housekeeping writes once a second, by the wall time around two SQL calls. So each window's ticks/s could gain or lose one second's ticks, about ±2 a second over 30 s, and a run kept one offset throughout. Those rates carry up to about ±3% from that division. Ticks over 16.7 ms and the p99 come from the tick log and are unaffected. Fixed in `battle-cheap` (on main as `27d3b183`): the count is divided by the stamps' interval. An idle world then reads 60.0 ticks/s in a window with no slow tick, and agrees with the tick log within half a tick a second (`minds-idle-002623`, 2026-11-13).
