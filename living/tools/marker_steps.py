#!/usr/bin/env python3
"""The tick's cadence from the server's own step marker (the `tick_marker_on` law; docs/TICK_RATE.md
"The step marker"). The coordinator's line, fixed before any result was computed and the same on
every host:
  - ticks/s >= 59.9 (the run's own `ticks_per_s`, the server's tick count over the window);
  - p99 of step intervals from the marker <= 17.5 ms;
  - <= 0.5% of step intervals over 25 ms.

Method (the same on every host):
  - input: a run's `ticks-watch.csv`, the lines `m,tick,start_us,arrival_us` gate-load `watch` writes
    with `"marker": true`, and its `v0/result.json` (`window.t0`/`window.t1` in seconds, `ticks_per_s`);
  - a tick counts when its `start_us` (the tick's reducer timestamp, server time) lies in
    [t0, t1), each tick once (its first line);
  - intervals = start_us(tick + 1) - start_us(tick), only between consecutive ticks, in ms (float);
  - p99 = the sorted intervals at index int(0.99 * n) (the nearest rank of `us_reread.py` and
    `battle_viewers.steps_from`); over-25 share = intervals > 25.0 ms / all intervals.
Unlike `us_reread.py`, nothing here depends on delivery: arrival times are only reported.

    marker_steps.py RUN_DIR...
"""
import json
import sys
from pathlib import Path

LINE = {"ticks_per_s_min": 59.9, "p99_ms_max": 17.5, "over25_pct_max": 0.5}


def intervals(lines, t0_us, t1_us):
    """lines: (tick, start_us) pairs. Returns the sorted step intervals in ms and the ticks counted."""
    first = {}
    for tick, start in lines:
        if t0_us <= start < t1_us:
            first.setdefault(tick, start)
    ks = sorted(first)
    return sorted((first[b] - first[a]) / 1000.0 for a, b in zip(ks, ks[1:]) if b == a + 1), len(ks)


def summary(iv, ticks_per_s, counted):
    n = len(iv)
    p = lambda q: iv[min(n - 1, int(q * n))]
    out = {"intervals": n, "ticks_counted": counted, "ticks_per_s": ticks_per_s,
           "p50_ms": round(p(0.5), 3), "p95_ms": round(p(0.95), 3), "p99_ms": round(p(0.99), 3),
           "max_ms": round(iv[-1], 3), "over25_pct": round(100 * sum(x > 25.0 for x in iv) / n, 3)}
    out["pass"] = (ticks_per_s is not None and ticks_per_s >= LINE["ticks_per_s_min"] and out["p99_ms"] <= LINE["p99_ms_max"]
                   and out["over25_pct"] <= LINE["over25_pct_max"])
    return out


def read(run):
    run = Path(run)
    res = json.loads((run / "v0" / "result.json").read_text())
    t0, t1 = res["window"]["t0"] * 1e6, res["window"]["t1"] * 1e6
    lines, arrival = [], []
    for line in open(run / "ticks-watch.csv"):
        f = line.strip().split(",")
        if len(f) == 4 and f[0] == "m":
            lines.append((int(f[1]), int(f[2])))
            arrival.append(int(f[3]) - int(f[2]))
    iv, counted = intervals(lines, t0, t1)
    tps = res.get("ticks_per_s")
    out = {"run": run.name, **summary(iv, tps if isinstance(tps, (int, float)) else None, counted)}
    if arrival:
        arrival.sort()
        out["marker_to_arrival_ms"] = {"p50": round(arrival[len(arrival) // 2] / 1000, 3), "p99": round(arrival[min(len(arrival) - 1, int(0.99 * len(arrival)))] / 1000, 3)}
    return out


if __name__ == "__main__":
    print(json.dumps({"line": LINE, "runs": [read(r) for r in sys.argv[1:]]}, indent=1))
