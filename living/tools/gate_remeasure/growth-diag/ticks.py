#!/usr/bin/env python3
"""growth-diag: per profile window, each tick reducer call's spans (the module log's `Timing span` lines of
function "tick" up to and including its `"tick"` span). Reports per window: ticks, tick duration p50/p95/p99/max,
the mean ms per tick of each span over all ticks and over the slowest 5% of ticks, and the spans whose
slow-tick excess (slow mean - all mean) is largest. Also other reducers' spans (function != tick) as ms/s.
Usage: ticks.py RUN_DIR [TOP=25] > ticks.json"""
import collections, io, json, re, sys, tarfile
from pathlib import Path

run = Path(sys.argv[1])
TOP = int(sys.argv[2]) if len(sys.argv) > 2 else 25
prof = [json.loads(l) for l in open(run / "prof.jsonl")]
wins = [(r["k"], r["on_t"] * 1e6, r["off_t"] * 1e6) for r in prof if r.get("tag") == "prof"]
t0 = next(r["t"] for r in prof if r.get("tag") == "start")
SPAN = re.compile(r'"ts":(\d+),"function":"([^"]*)","message":"Timing span \\"([^"\\]+)\\": ([\d.]+)(ns|µs|ms|s)"')
UNIT = {"ns": 1e-6, "µs": 1e-3, "ms": 1.0, "s": 1e3}


def lines():
    tar = run / "replica-module-logs.tar"
    with tarfile.open(tar) as t:
        for m in t.getmembers():
            if m.isfile() and m.name.endswith(".log"):
                yield from io.TextIOWrapper(t.extractfile(m), encoding="utf-8", errors="replace")


per = {k: {"ticks": [], "other": collections.defaultdict(float)} for k, _, _ in wins}
cur = collections.defaultdict(float)
wi = 0
for l in lines():
    if "Timing span" not in l:
        continue
    m = SPAN.search(l)
    if not m:
        continue
    ts = int(m.group(1))
    while wi < len(wins) and ts > wins[wi][2] + 2e6:
        wi += 1
        cur = collections.defaultdict(float)
    if wi >= len(wins):
        break
    k, a, b = wins[wi]
    if ts < a:
        continue
    fn, name, ms = m.group(2), m.group(3), float(m.group(4)) * UNIT[m.group(5)]
    if fn != "tick":
        per[k]["other"][f"{fn}:{name}"] += ms
        continue
    cur[name] += ms
    if name == "tick":
        per[k]["ticks"].append((ms, dict(cur)))
        cur = collections.defaultdict(float)


def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, max(0, int(round(q * len(v) + 0.5)) - 1))], 2) if v else None


out = []
for k, a, b in wins:
    ticks = per[k]["ticks"]
    if not ticks:
        continue
    secs = (b - a) / 1e6
    durs = [t for t, _ in ticks]
    n = len(ticks)
    slow = sorted(ticks, key=lambda x: -x[0])[: max(1, n // 20)]
    names = set().union(*(s.keys() for _, s in ticks))
    mean_all = {s: sum(t.get(s, 0) for _, t in ticks) / n for s in names}
    mean_slow = {s: sum(t.get(s, 0) for _, t in slow) / len(slow) for s in names}
    excess = sorted(((mean_slow[s] - mean_all[s], s) for s in names if s != "tick"), reverse=True)[:TOP]
    out.append({"k": k, "min": round((a / 1e6 - t0) / 60, 2), "secs": round(secs, 2), "ticks": n,
                "tick_ms": {"mean": round(sum(durs) / n, 2), "p50": pct(durs, .5), "p95": pct(durs, .95), "p99": pct(durs, .99), "max": round(max(durs), 2),
                            "over_16_7": sum(d > 16.67 for d in durs)},
                "mean_ms_per_tick": dict(sorted(((s, round(v, 3)) for s, v in mean_all.items()), key=lambda x: -x[1])[:TOP + 15]),
                "slow5_ms_per_tick": dict(sorted(((s, round(v, 3)) for s, v in mean_slow.items()), key=lambda x: -x[1])[:TOP + 15]),
                "slow_excess": [(s, round(v, 3)) for v, s in excess],
                "other_ms_per_s": dict(sorted(((s, round(v / secs, 3)) for s, v in per[k]["other"].items()), key=lambda x: -x[1])[:TOP])})
print(json.dumps({"run": run.name, "windows": out}, indent=0))
