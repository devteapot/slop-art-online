# Arena scorer evidence, 2026-11-19

The tables use milliseconds. Each pair below a latency column gives unanswered / unobservable.
Unanswered means an observed two-second window with no qualifying event. Unobservable means the
capture cannot establish the causal join. Percentiles use answered stimuli. The proxy is the old
geometric stimulus-to-body-segment calculation (with pre-call clock sampling for N1). It can
include ordinary steering. It is retained for comparison with the original evidence.

The original p95 limits for physical response are 300 ms for N1 and 150 ms for N2. N3 additionally
requires p50 ≤ 50 ms, and N4 requires p50 ≤ 70 ms, both with p95 ≤ 150 ms. First write is diagnostic
and has no separately specified acceptance threshold.

The pose score tests a start from rest, a speed drop over 30%, or a travel-heading change over
15° against the immediate predecessor motion. It follows a recorded turn inside a segment at
10 ms resolution. The Input Latency trace joins queue ID to start ID and then the body write
inside that same goto invocation. It attributes only the trajectory written by that invocation.

The live recorder reuses the actor-indexed queue and the subject-keyed activity/steer/body
subscriptions. It uses committed deltas to join queue consumption to activity and motion in the
same transaction. A synchronous queue insert/delete may leave no committed queue row; an exact
act ID is then unavailable from the stock recorder. See [SpacetimeDB subscription semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics/).

The two older archives lack queued act IDs and act-scoped motion writes. Their causal latency
percentiles cannot be recovered from the archived rows. The two early N1-a trace tails are
supplemented with the archive's full marker exports. N2 gate closure is external to the walker.
A dispatched goto and a later reaction to closure are separate measurements. The pre-dispatch
N2 fixtures cannot establish a mid-walk route change.

## Archived reports

All recovered matrix attempts are shown, including duplicate arms with a different capture directory.
Use the published recovery arms for like-for-like verdicts. Response-only replay does not
recompute map optima. Arrival figures refer to the original start-time true optimum.

### arenas, law off

| Arm | Capture | Stimuli | First write p50 / p90 / p95 | Unanswered / unobservable | Physical effect p50 / p90 / p95 | Unanswered / unobservable | Legacy proxy p50 / p90 / p95 | Proxy unanswered |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n1-a-off-body` | `core-nav-free-n1-a` | 15 | — | 0 / 15 | — | 0 / 15 | 44.50 / 543.90 / 993.90 | 1 |
| `n1-a-off-click` | `core-nav-free-n1-a` | 15 | — | 0 / 15 | — | 0 / 15 | 26.00 / 519.70 / 939.85 | 1 |
| `n1-b-off-body` | `core-nav-free-n1-b` | 15 | — | 0 / 15 | — | 0 / 15 | 225.00 / 534.70 / 630.70 | 1 |
| `n1-b-off-click` | `core-nav-free-n1-b` | 15 | — | 0 / 15 | — | 0 / 15 | 20.00 / 1646.60 / 1720.10 | 0 |
| `n1-c-off-body` | `core-nav-free-n1-c` | 15 | — | 0 / 15 | — | 0 / 15 | 243.00 / 460.80 / 548.90 | 0 |
| `n1-c-off-click` | `core-nav-free-n1-c` | 15 | — | 0 / 15 | — | 0 / 15 | 25.00 / 368.40 / 427.30 | 0 |
| `n1-d-off-body` | `core-nav-free-n1-d` | 15 | — | 0 / 15 | — | 0 / 15 | 141.00 / 490.20 / 493.30 | 0 |
| `n1-d-off-click` | `core-nav-free-n1-d` | 15 | — | 0 / 15 | — | 0 / 15 | 18.00 / 38.80 / 101.65 | 3 |
| `n2-a-off-body` | `core-nav-free-n2-a` | 5 | — | 0 / 5 | — | 0 / 5 | 1828.00 / 1898.20 / 1902.60 | 0 |
| `n2-a-off-click` | `core-nav-free-n2-a` | 5 | — | 0 / 5 | — | 0 / 5 | 1810.00 / 1922.60 / 1950.80 | 0 |
| `n2-b-off-body` | `core-nav-free-n2-b` | 5 | — | 0 / 5 | — | 0 / 5 | 1876.00 / 1955.30 / 1971.65 | 1 |
| `n2-b-off-body` | `core-nav-free-n2-b-recovery` | 5 | — | 0 / 5 | — | 0 / 5 | 1753.00 / 1927.40 / 1949.20 | 2 |
| `n2-b-off-click` | `core-nav-free-n2-b` | 5 | — | 0 / 5 | — | 0 / 5 | 1742.00 / 1878.00 / 1895.00 | 2 |
| `n2-b-off-click` | `core-nav-free-n2-b-recovery` | 5 | — | 0 / 5 | — | 0 / 5 | — | 5 |
| `n2-c-off-body` | `core-nav-free-n2-c` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-off-body` | `core-nav-free-n2-c-recovery` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-off-click` | `core-nav-free-n2-c` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-off-click` | `core-nav-free-n2-c-recovery` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n3-run-off-body` | `core-nav-free-n3-run` | 118 | — | 0 / 118 | — | 0 / 118 | 1196.00 / 1577.50 / 1671.00 | 102 |
| `n3-run-off-click` | `core-nav-free-n3-run` | 91 | — | 0 / 91 | — | 0 / 91 | — | 91 |
| `n3-stop-off-body` | `core-nav-free-n3-stop` | 129 | — | 0 / 129 | — | 0 / 129 | 488.00 / 1758.80 / 1788.90 | 121 |
| `n3-stop-off-click` | `core-nav-free-n3-stop` | 126 | — | 0 / 126 | — | 0 / 126 | 994.00 / 1717.20 / 1831.60 | 112 |
| `n3-w200-off-body` | `core-nav-free-n3-w200` | 609 | — | 0 / 609 | — | 0 / 609 | 920.00 / 1799.20 / 1958.70 | 390 |
| `n3-w200-off-click` | `core-nav-free-n3-w200` | 720 | — | 0 / 720 | — | 0 / 720 | 838.50 / 1804.40 / 1914.50 | 398 |
| `n3-w50-off-body` | `core-nav-free-n3-w50` | 157 | — | 0 / 157 | — | 0 / 157 | 1203.00 / 1805.80 / 1950.20 | 132 |
| `n3-w50-off-click` | `core-nav-free-n3-w50` | 149 | — | 0 / 149 | — | 0 / 149 | 1234.00 / 1665.60 / 1794.50 | 121 |
| `n4-fk-off-body-day` | `core-nav-free-n4-fk` | 15 | — | 0 / 15 | — | 0 / 15 | 866.00 / 1549.00 / 1584.00 | 7 |
| `n4-fk-off-body-night` | `core-nav-free-n4-fk` | 11 | — | 0 / 11 | — | 0 / 11 | 378.00 / 904.80 / 980.40 | 6 |
| `n4-fk-off-click-day` | `core-nav-free-n4-fk` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-fk-off-click-night` | `core-nav-free-n4-fk` | 4 | — | 0 / 4 | — | 0 / 4 | — | 4 |
| `n4-fu-off-body-day` | `core-nav-free-n4-fu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-fu-off-body-night` | `core-nav-free-n4-fu` | 8 | — | 0 / 8 | — | 0 / 8 | 874.00 / 969.00 / 984.00 | 4 |
| `n4-fu-off-click-day` | `core-nav-free-n4-fu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-fu-off-click-night` | `core-nav-free-n4-fu` | 1 | — | 0 / 1 | — | 0 / 1 | — | 1 |
| `n4-pk-off-body-day` | `core-nav-free-n4-pk` | 1 | — | 0 / 1 | — | 0 / 1 | 64.00 / 64.00 / 64.00 | 0 |
| `n4-pk-off-body-night` | `core-nav-free-n4-pk` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-pk-off-click-day` | `core-nav-free-n4-pk` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-pk-off-click-night` | `core-nav-free-n4-pk` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-pu-off-body-day` | `core-nav-free-n4-pu` | 1 | — | 0 / 1 | — | 0 / 1 | 233.00 / 233.00 / 233.00 | 0 |
| `n4-pu-off-body-night` | `core-nav-free-n4-pu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-pu-off-click-day` | `core-nav-free-n4-pu` | 2 | — | 0 / 2 | — | 0 / 2 | 175.50 / 307.10 / 323.55 | 0 |
| `n4-pu-off-click-night` | `core-nav-free-n4-pu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |

### arenas, law on

| Arm | Capture | Stimuli | First write p50 / p90 / p95 | Unanswered / unobservable | Physical effect p50 / p90 / p95 | Unanswered / unobservable | Legacy proxy p50 / p90 / p95 | Proxy unanswered |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n1-a-on-body` | `core-nav-free-n1-a` | 15 | — | 0 / 15 | — | 0 / 15 | 282.00 / 1827.20 / 1849.20 | 2 |
| `n1-a-on-click` | `core-nav-free-n1-a` | 15 | — | 0 / 15 | — | 0 / 15 | 28.00 / 1559.80 / 1888.00 | 2 |
| `n1-b-on-body` | `core-nav-free-n1-b` | 15 | — | 0 / 15 | — | 0 / 15 | 59.00 / 540.60 / 626.60 | 0 |
| `n1-b-on-click` | `core-nav-free-n1-b` | 15 | — | 0 / 15 | — | 0 / 15 | 31.00 / 1711.40 / 1747.50 | 0 |
| `n1-c-on-body` | `core-nav-free-n1-c` | 15 | — | 0 / 15 | — | 0 / 15 | 108.50 / 784.90 / 900.35 | 1 |
| `n1-c-on-click` | `core-nav-free-n1-c` | 15 | — | 0 / 15 | — | 0 / 15 | 41.00 / 688.80 / 843.10 | 0 |
| `n1-d-on-body` | `core-nav-free-n1-d` | 15 | — | 0 / 15 | — | 0 / 15 | 101.00 / 450.40 / 753.70 | 1 |
| `n1-d-on-click` | `core-nav-free-n1-d` | 15 | — | 0 / 15 | — | 0 / 15 | 37.00 / 272.40 / 386.60 | 2 |
| `n2-a-on-body` | `core-nav-free-n2-a` | 5 | — | 0 / 5 | — | 0 / 5 | 1741.00 / 1741.00 / 1741.00 | 4 |
| `n2-a-on-click` | `core-nav-free-n2-a` | 5 | — | 0 / 5 | — | 0 / 5 | 1602.00 / 1602.00 / 1602.00 | 4 |
| `n2-b-on-body` | `core-nav-free-n2-b` | 5 | — | 0 / 5 | — | 0 / 5 | 405.00 / 671.00 / 678.50 | 1 |
| `n2-b-on-body` | `core-nav-free-n2-b-recovery` | 5 | — | 0 / 5 | — | 0 / 5 | 352.00 / 840.00 / 901.00 | 2 |
| `n2-b-on-click` | `core-nav-free-n2-b-recovery` | 5 | — | 0 / 5 | — | 0 / 5 | 1441.00 / 1777.40 / 1871.20 | 0 |
| `n2-c-on-body` | `core-nav-free-n2-c` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-on-body` | `core-nav-free-n2-c-recovery` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-on-click` | `core-nav-free-n2-c` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-on-click` | `core-nav-free-n2-c-recovery` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n3-run-on-body` | `core-nav-free-n3-run` | 112 | — | 0 / 112 | — | 0 / 112 | 1137.50 / 1682.10 / 1735.60 | 84 |
| `n3-run-on-click` | `core-nav-free-n3-run` | 105 | — | 0 / 105 | — | 0 / 105 | 869.00 / 1331.00 / 1597.55 | 85 |
| `n3-stop-on-body` | `core-nav-free-n3-stop` | 125 | — | 0 / 125 | — | 0 / 125 | 777.00 / 1868.20 / 1946.40 | 106 |
| `n3-stop-on-click` | `core-nav-free-n3-stop` | 112 | — | 0 / 112 | — | 0 / 112 | 867.00 / 1784.00 / 1877.00 | 95 |
| `n3-w200-on-body` | `core-nav-free-n3-w200` | 706 | — | 0 / 706 | — | 0 / 706 | 654.00 / 1696.40 / 1822.40 | 307 |
| `n3-w200-on-click` | `core-nav-free-n3-w200` | 560 | — | 0 / 560 | — | 0 / 560 | 1033.50 / 1874.00 / 1919.25 | 334 |
| `n3-w50-on-body` | `core-nav-free-n3-w50` | 150 | — | 0 / 150 | — | 0 / 150 | 801.50 / 1338.40 / 1429.70 | 132 |
| `n3-w50-on-click` | `core-nav-free-n3-w50` | 153 | — | 0 / 153 | — | 0 / 153 | 1394.00 / 1850.00 / 1903.95 | 123 |
| `n4-fk-on-body-day` | `core-nav-free-n4-fk` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-fk-on-body-night` | `core-nav-free-n4-fk-recovery` | 7 | — | 0 / 7 | — | 0 / 7 | 666.00 / 706.00 / 711.00 | 5 |
| `n4-fk-on-click-day` | `core-nav-free-n4-fk` | 15 | — | 0 / 15 | — | 0 / 15 | 110.00 / 110.00 / 110.00 | 14 |
| `n4-fk-on-click-night` | `core-nav-free-n4-fk-recovery` | 6 | — | 0 / 6 | — | 0 / 6 | 298.00 / 298.00 / 298.00 | 5 |
| `n4-fu-on-body-day` | `core-nav-free-n4-fu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-fu-on-body-night` | `core-nav-free-n4-fu` | 3 | — | 0 / 3 | — | 0 / 3 | 625.00 / 665.00 / 670.00 | 1 |
| `n4-fu-on-click-day` | `core-nav-free-n4-fu` | 11 | — | 0 / 11 | — | 0 / 11 | 801.00 / 984.60 / 1042.80 | 6 |
| `n4-fu-on-click-night` | `core-nav-free-n4-fu` | 6 | — | 0 / 6 | — | 0 / 6 | — | 6 |
| `n4-pk-on-body-day` | `core-nav-free-n4-pk` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-pk-on-body-night` | `core-nav-free-n4-pk` | 1 | — | 0 / 1 | — | 0 / 1 | 108.00 / 108.00 / 108.00 | 0 |
| `n4-pk-on-click-day` | `core-nav-free-n4-pk` | 1 | — | 0 / 1 | — | 0 / 1 | 70.00 / 70.00 / 70.00 | 0 |
| `n4-pk-on-click-night` | `core-nav-free-n4-pk` | 1 | — | 0 / 1 | — | 0 / 1 | 492.00 / 492.00 / 492.00 | 0 |
| `n4-pu-on-body-day` | `core-nav-free-n4-pu` | 1 | — | 0 / 1 | — | 0 / 1 | 100.00 / 100.00 / 100.00 | 0 |
| `n4-pu-on-body-night` | `core-nav-free-n4-pu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n4-pu-on-click-day` | `core-nav-free-n4-pu` | 1 | — | 0 / 1 | — | 0 / 1 | 128.00 / 128.00 / 128.00 | 0 |
| `n4-pu-on-click-night` | `core-nav-free-n4-pu` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |

### planner, law off

| Arm | Capture | Stimuli | First write p50 / p90 / p95 | Unanswered / unobservable | Physical effect p50 / p90 / p95 | Unanswered / unobservable | Legacy proxy p50 / p90 / p95 | Proxy unanswered |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n1-a-off-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 118.50 / 1414.50 / 1790.85 | 1 |
| `n1-a-off-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 21.50 / 1680.10 / 1799.70 | 1 |
| `n1-b-off-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 277.00 / 597.00 / 683.70 | 0 |
| `n1-b-off-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 22.00 / 1788.20 / 1850.90 | 0 |
| `n1-c-off-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 192.00 / 531.20 / 544.00 | 0 |
| `n1-c-off-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 215.00 / 794.20 / 828.20 | 0 |
| `n1-d-off-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 275.00 / 460.80 / 485.00 | 0 |
| `n1-d-off-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 15.00 / 404.80 / 504.70 | 0 |
| `n2-a-off-body` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | 1880.00 / 1902.70 / 1904.35 | 1 |
| `n2-a-off-click` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | 1923.50 / 1944.90 / 1948.95 | 1 |
| `n2-b-off-body` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | 1888.50 / 1975.10 / 1977.05 | 1 |
| `n2-b-off-click` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | 1923.00 / 1964.40 / 1965.20 | 0 |
| `n2-c-off-body` | `matrix` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-off-click` | `matrix` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |

### planner, law on

| Arm | Capture | Stimuli | First write p50 / p90 / p95 | Unanswered / unobservable | Physical effect p50 / p90 / p95 | Unanswered / unobservable | Legacy proxy p50 / p90 / p95 | Proxy unanswered |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n1-a-on-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 67.00 / 522.40 / 1192.85 | 3 |
| `n1-a-on-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 65.50 / 1724.00 / 1926.55 | 3 |
| `n1-b-on-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 195.00 / 573.60 / 580.50 | 0 |
| `n1-b-on-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 23.00 / 1846.60 / 1867.20 | 0 |
| `n1-c-on-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 251.00 / 603.20 / 874.30 | 0 |
| `n1-c-on-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 118.00 / 360.60 / 670.00 | 0 |
| `n1-d-on-body` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 51.00 / 289.20 / 394.70 | 0 |
| `n1-d-on-click` | `matrix` | 15 | — | 0 / 15 | — | 0 / 15 | 105.00 / 488.80 / 810.20 | 0 |
| `n2-a-on-body` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | 42.00 / 42.00 / 42.00 | 4 |
| `n2-a-on-click` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | 349.00 / 1500.30 / 1708.65 | 1 |
| `n2-b-on-body` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | — | 5 |
| `n2-b-on-click` | `matrix` | 5 | — | 0 / 5 | — | 0 / 5 | — | 5 |
| `n2-c-on-body` | `matrix` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |
| `n2-c-on-click` | `matrix` | 0 | — | 0 / 0 | — | 0 / 0 | — | 0 |

### latency, law off

| Arm | Capture | Stimuli | First write p50 / p90 / p95 | Unanswered / unobservable | Physical effect p50 / p90 / p95 | Unanswered / unobservable | Legacy proxy p50 / p90 / p95 | Proxy unanswered |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n1-a-off-body` | `nav` | 15 | 2.13 / 476.73 / 732.28 | 0 / 0 | 52.73 / 476.73 / 732.28 | 0 / 0 | 65.00 / 361.80 / 710.30 | 0 |
| `n1-a-off-click` | `nav` | 15 | 1.80 / 1.96 / 2.04 | 0 / 0 | 1.85 / 32.37 / 52.74 | 0 / 0 | 21.00 / 1584.60 / 1679.90 | 0 |
| `n1-b-off-body` | `nav` | 15 | 464.24 / 883.34 / 1050.34 | 0 / 0 | 464.24 / 883.34 / 1050.34 | 0 / 0 | 379.50 / 701.90 / 727.05 | 1 |
| `n1-b-off-click` | `nav` | 15 | 1.28 / 2.02 / 2.28 | 0 / 0 | 1.87 / 53.09 / 53.38 | 0 / 0 | 14.00 / 1715.70 / 1814.75 | 1 |
| `n1-c-off-body` | `nav` | 15 | 61.32 / 595.31 / 665.06 | 0 / 0 | 61.32 / 595.31 / 665.06 | 0 / 0 | 131.00 / 599.20 / 669.10 | 0 |
| `n1-c-off-click` | `nav` | 15 | 1.53 / 1.96 / 2.15 | 0 / 0 | 1.79 / 53.42 / 53.54 | 0 / 0 | 20.00 / 717.20 / 771.90 | 0 |
| `n1-d-off-body` | `nav` | 15 | 85.39 / 955.86 / 1049.16 | 0 / 0 | 85.39 / 955.86 / 1049.16 | 0 / 0 | 130.00 / 393.40 / 470.40 | 0 |
| `n1-d-off-click` | `nav` | 15 | 1.56 / 2.72 / 3.94 | 0 / 0 | 1.57 / 54.14 / 55.62 | 0 / 0 | 22.00 / 184.60 / 286.90 | 0 |
| `n2-a-off-body` | `nav` | 5 | — | 0 / 5 | — | 0 / 5 | 1864.00 / 1954.00 / 1965.00 | 0 |
| `n2-a-off-click` | `nav` | 5 | — | 0 / 5 | — | 0 / 5 | 1829.00 / 1955.40 / 1969.20 | 0 |
| `n2-b-off-body` | `nav` | 5 | — | 0 / 5 | — | 0 / 5 | 1829.00 / 1910.50 / 1917.25 | 1 |
| `n2-b-off-click` | `nav` | 5 | — | 0 / 5 | — | 0 / 5 | 1844.00 / 1905.30 / 1912.65 | 1 |

## Effect on the release verdict

The instrumented law-off N1 archive has 120/120 act-ID joins. Body p95 misses 300 ms in all
four scenarios, with the tail present at the first write. Click p95 is below 300 ms in all
four scenarios for both measures. This replay explains the previous click latency misses
without making any claim about performance with the law on. Both recorded N1 threshold misses
show an act-linked effect using the corrected timing and trajectory.

The archived law-on N2 rerun had 20/20 closed-gate arrivals after the planner fix, versus 6/20
in the original arena. The rerun's closed-gate arm ordered the walks after closure, so its
arrivals do not demonstrate a reaction by an actor already walking an open-gate route. The
Input Latency N2 archive shows gate memory and arrival for both of its former unanswered
stimuli. It does not establish that the later motion was caused by observing the gate.

The release gate remains unmet. The corrected archive cannot establish the law-on response
targets. The reported terraced-town arrival and belief-route misses and the 6/14 motion-cost
pairs above 2× remain independent of the scorer. The default stays off.

## N2 mid-close

An offline replay of the archived island terrain found the same 44.58 m-at-walk-pace route
before and after closing the 25 surrounding tiles. It crossed six channel tiles. Closing all
33 yielded a 49.02 m route across zero gate-A tiles. This verifies the setup geometry.

Each arm uses one walker and no mind. A route qualifies after the driver records it as crossing the open channel and verifies the channel shut. Only measurements in the two-second window appear in the percentile columns. The raw JSON retains later effects and negative times relative to geometric visibility.

| Arm | Valid setup | Arrived within 3× | Dispatch → first write p50 / p90 / p95 | Unanswered / unobservable | Dispatch → effect p50 / p90 / p95 | Unanswered / unobservable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| n2-mid-close-off-body | 0/1 | 0/1 | — | 1 / 0 | — | 1 / 0 |
| n2-mid-close-off-click | 1/1 | 1/1 | — | 0 / 1 | — | 0 / 1 |
| n2-mid-close-on-body | 1/1 | 0/1 | — | 0 / 1 | — | 0 / 1 |
| n2-mid-close-on-click | 1/1 | 0/1 | — | 0 / 1 | — | 0 / 1 |

| Arm | closure → alternate route p50 / p90 / p95 | Unanswered / unobservable | closure → effect p50 / p90 / p95 | Unanswered / unobservable | Route / effect before stimulus |
| --- | ---: | ---: | ---: | ---: | ---: |
| n2-mid-close-off-body | — | 0 / 0 | — | 0 / 0 | 0 / 0 |
| n2-mid-close-off-click | — | 1 / 0 | — | 1 / 0 | 0 / 0 |
| n2-mid-close-on-body | — | 1 / 0 | — | 1 / 0 | 0 / 0 |
| n2-mid-close-on-click | — | 1 / 0 | — | 1 / 0 | 0 / 0 |

| Arm | visibility → alternate route p50 / p90 / p95 | Unanswered / unobservable | visibility → effect p50 / p90 / p95 | Unanswered / unobservable | Route / effect before stimulus |
| --- | ---: | ---: | ---: | ---: | ---: |
| n2-mid-close-off-body | — | 0 / 0 | — | 0 / 0 | 0 / 0 |
| n2-mid-close-off-click | — | 1 / 0 | — | 1 / 0 | 0 / 0 |
| n2-mid-close-on-body | — | 1 / 0 | — | 1 / 0 | 0 / 0 |
| n2-mid-close-on-click | — | 1 / 0 | — | 1 / 0 | 0 / 0 |

### Live interpretation

| Law | Controller | Dispatch → first write | Dispatch → physical effect | Mid-walk route change | Arrival |
| --- | --- | --- | --- | --- | --- |
| Off | Body | 67,493 ms, outside the 2 s window | 67,493 ms, started from rest in the same body write | Ineligible. The route started after the fixture stopped checking for an open-channel path, so the driver left the gate open. | Raw body track reached the goal in 86.59 s, outside 3× the open-route optimum. |
| Off | Click | Unobservable by act ID | Unobservable by act ID | Yes. Alternate route and velocity change first appear 11,428 ms after the first tile closed and 8,948 ms after estimated visibility. The last tile was still open at that write. | Arrived in 20.1 s, within 3×. |
| On | Body | Unobservable by act ID | Unobservable by act ID | No qualifying alternate route or effect. The authority reported “could not get there.” | Failed. |
| On | Click | Unobservable by act ID | Unobservable by act ID | No qualifying alternate route or effect. The authority reported “could not get there.” | Failed. |

The law-off body’s queue ID 28 was consumed in the committed update that installed the test
goto and wrote its moving body row. The driver ended its walk record on a failure line for the
preceding warm-up goal (540,358) that appeared in that update. The continuing subscription
shows the test goto (508,322) arriving. This setup cannot supply law-off body reroute evidence.

The three eligible approaches all missed the 150 ms visibility-to-effect target. The law-on
walkers had already recorded a closed tile before reporting failure. The off-click recovery
began during staged closure and occurred outside the two-second scoring window. With one
walker per arm and the off-body setup ineligible, this capture demonstrates a mid-walk failure
in each law-on controller and a late recovery in one law-off controller. It cannot estimate a
population percentile or isolate the effect of the law on the scripted-body comparison.

The nav_belief release verdict remains **unmet**. The law-on cases add direct evidence of
failed recovery during staged closure. Earlier pre-dispatch arrivals did not cover that
behavior. Existing arrival, route-ratio and motion-cost findings still apply.

All four launch and post-run checks showed advancing ticks. The verification harness paused and
deleted all four owned scratch databases. No model process ran.
