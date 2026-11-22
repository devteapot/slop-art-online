#!/usr/bin/env python3
"""Microsecond re-read of gate-case step intervals (general coordinator, 2026-11-24).

The strict line is FIXED HERE, before any result was computed, and is the same for both hosts:
  - ticks/s >= 59.9 (the server's own tick counter over the window, as before);
  - p99 of step intervals from `arrival_us` <= 17.5 ms (the contract's "approximately 16.7 ms"
    plus 0.8 ms stated allowance for measurement and scheduling jitter);
  - <= 0.5% of intervals over 25 ms.

Method (identical on every host):
  - input: a run's `ticks-watch.csv` (lines `c|u,tick,last_ms,arrival_us` from `gate-load watch`)
    and its `v0/result.json` (`window.t0`/`window.t1` in seconds, `ticks_per_s`);
  - use ONLY the unconfirmed connection's lines (`u`), as `battle_viewers.steps_from` does;
  - keep each tick's FIRST arrival whose arrival_us lies in [t0, t1);
  - intervals = arrival_us(tick+1) - arrival_us(tick), only for consecutive ticks, in ms (float);
  - p99 = the value at index int(0.99 * n) of the sorted intervals (same nearest-rank as steps_from);
  - over-25 share = intervals > 25.0 ms / all intervals.
Caveat: arrival_us is the client's receive time, so it includes delivery jitter on top of the
server's step timing; `last_ms` is the server's step time at 1 ms resolution.
"""
import json
import sys
from pathlib import Path

LINE = {"ticks_per_s_min": 59.9, "p99_ms_max": 17.5, "over25_pct_max": 0.5}


def read(run):
    run = Path(run)
    res = json.loads((run / "v0" / "result.json").read_text())
    t0, t1 = res["window"]["t0"] * 1e6, res["window"]["t1"] * 1e6
    first = {}
    for line in open(run / "ticks-watch.csv"):
        f = line.strip().split(",")
        if len(f) != 4 or f[0] != "u":
            continue
        tick, arr = int(f[1]), int(f[3])
        if t0 <= arr < t1:
            first.setdefault(tick, arr)
    ks = sorted(first)
    iv = sorted((first[b] - first[a]) / 1000.0 for a, b in zip(ks, ks[1:]) if b == a + 1)
    n = len(iv)
    p = lambda q: iv[min(n - 1, int(q * n))]
    tps = res.get("ticks_per_s")
    tps = tps if isinstance(tps, (int, float)) else (tps or {}).get("window") if isinstance(tps, dict) else None
    out = {"run": run.name, "intervals": n, "ticks_per_s": tps,
           "p50_ms": round(p(0.5), 3), "p95_ms": round(p(0.95), 3), "p99_ms": round(p(0.99), 3),
           "max_ms": round(iv[-1], 3), "over25_pct": round(100 * sum(x > 25.0 for x in iv) / n, 3)}
    out["pass"] = (tps is not None and tps >= LINE["ticks_per_s_min"] and out["p99_ms"] <= LINE["p99_ms_max"]
                   and out["over25_pct"] <= LINE["over25_pct_max"])
    return out


if __name__ == "__main__":
    print(json.dumps({"line": LINE, "runs": [read(r) for r in sys.argv[1:]]}, indent=1))
