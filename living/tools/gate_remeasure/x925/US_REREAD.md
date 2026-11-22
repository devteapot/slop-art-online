# Gate case on X925: microsecond re-read (2026-11-24)

The line was fixed by the general coordinator and committed in `us_reread.py` at 5956bc2da BEFORE any µs number was computed. No µs number had been looked at before that commit. Line: ticks/s ≥ 59.9; p99 of `arrival_us` step intervals ≤ 17.5 ms; ≤ 0.5% of intervals over 25 ms. The method is in the script's docstring.

Results (`us_reread_results.json`, the 8 kept runs of the X925 series, pre-fair-ties modules):

| Run | ticks/s | p50 | p95 | p99 | max | > 25 ms | Pass |
|---|---|---|---|---|---|---|---|
| main-r1 | 58.74 | 16.73 | 23.66 | 29.51 | 38.50 | 3.77% | no |
| main-r2 | 58.84 | 16.75 | 23.30 | 28.36 | 42.57 | 2.86% | no |
| relay-r1 | 59.93 | 16.62 | 20.86 | 23.79 | 27.87 | 0.39% | no (p99) |
| relay-r2 | 59.91 | 16.73 | 21.43 | 24.15 | 30.22 | 0.53% | no (p99, >25) |
| relaycut-r1 | 59.96 | 16.62 | 20.99 | 23.61 | 29.48 | 0.39% | no (p99) |
| relaycut-r2 | 59.93 | 16.65 | 21.05 | 23.65 | 31.21 | 0.28% | no (p99) |
| relayd40-r1 | 59.96 | 16.65 | 20.81 | 23.27 | 29.68 | 0.33% | no (p99) |
| relayd40-r2 | 59.96 | 16.62 | 21.16 | 24.10 | 32.98 | 0.47% | no (p99) |

**Verdict by the fixed line: no arm passes on X925.** The relay arms pass ticks/s and (all but relay-r2) the >25 ms share, and fail p99 by about 6 ms (23.3–24.2 against 17.5).

**Reading:** `arrival_us` is the watcher's receive time, so it carries delivery jitter (the watcher, gate-load's 216 connections and the relay all on the A725 cores) on top of the server's stepping. The server's own `last_ms` gave p99 18 ms at 1 ms resolution for the same runs. Neither is a clean sub-ms measure of the server's step times; that would need µs step timestamps written by the server. This note does not change the line.

**Module logs in the windows:** no panic in any run; every error-level line (5–11 per run, 60 total) is the reducer refusal "you have no living character" (dead fighters' inputs before they rejoin). The container's own log was removed unread (see the series report).
