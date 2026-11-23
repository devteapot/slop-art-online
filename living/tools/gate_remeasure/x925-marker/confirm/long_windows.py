#!/usr/bin/env python3
"""gate216-confirm: the 30-minute run cut into 60 s windows and 5-minute blocks, each judged by dev-box's
marker_steps.py (e16a43e5e, imported unmodified: its `intervals` and `summary`, the same method and line)
against the idle bound. A window's ticks/s is the marker's ticks counted in it over its length (the whole
run's verdict keeps the server counter's ticks/s, marker_steps.read). Drift: mem.jsonl (server RSS, cgroup
memory, relay and gate-load RSS every 10 s; /metrics table rows and memory every 60 s).
Usage: long_windows.py RUN_DIR IDLE_P99_MS > out.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "analysis"))
import marker_steps as ms  # noqa: E402
run, idle = Path(sys.argv[1]), float(sys.argv[2])
res = json.loads((run / "v0" / "result.json").read_text())
t0, t1 = res["window"]["t0"] * 1e6, res["window"]["t1"] * 1e6
lines = [(int(f[1]), int(f[2])) for f in (l.strip().split(",") for l in open(run / "ticks-watch.csv")) if len(f) == 4 and f[0] == "m"]

def cut(span_s):
    out, a = [], t0
    while a + span_s * 1e6 <= t1 + 1:
        b = a + span_s * 1e6
        iv, n = ms.intervals(lines, a, b)
        s = ms.summary(iv, round(n / span_s, 2), n, idle)
        why = [w for w, bad in (("ticks/s", s["ticks_per_s"] < ms.LINE["ticks_per_s_min"]), ("p99", s["p99_ms"] > s["p99_bound_ms"]),
                                ("over 25 ms", s["over25_pct"] > ms.LINE["over25_pct_max"])) if bad]
        out.append({"from_s": round((a - t0) / 1e6), **{k: s[k] for k in ("ticks_per_s", "p50_ms", "p95_ms", "p99_ms", "max_ms", "over25_pct", "pass")}, "fails_on": why})
        a = b
    return out

whole = ms.read(run, idle)
w60, b300 = cut(60), cut(300)
mem = [json.loads(l) for l in open(run / "mem.jsonl")] if (run / "mem.jsonl").exists() else []
def rss(r):
    return sum(v.get("VmRSS", 0) for v in r["server"].values())
inw = [r for r in mem if t0 / 1e6 <= r["t"] <= t1 / 1e6]
drift = {}
if inw:
    drift["server_rss_mb"] = {"start": round(rss(inw[0]) / 1024, 1), "end": round(rss(inw[-1]) / 1024, 1), "max": round(max(rss(r) for r in inw) / 1024, 1)}
    cg = [r["cgroup_bytes"] for r in inw if "cgroup_bytes" in r]
    if cg:
        drift["cgroup_mb"] = {"start": round(cg[0] / 2**20, 1), "end": round(cg[-1] / 2**20, 1), "max": round(max(cg) / 2**20, 1)}
    for name in ("relay-proto", "gate-load"):
        v = [sum(x or 0 for x in r.get(name, {}).values()) for r in inw]
        drift[name + "_rss_mb"] = {"start": round(v[0] / 1024, 1), "end": round(v[-1] / 1024, 1), "max": round(max(v) / 1024, 1)}
    snaps = [r for r in inw if r.get("metrics")]
    def series(snap):
        d = {}
        for l in snap["metrics"]:
            name, val = l.rsplit(" ", 1)
            d[name] = float(val)
        return d
    if snaps:
        first, last = series(snaps[0]), series(snaps[-1])
        drift["metrics_first_to_last"] = {k: [first.get(k), last.get(k)] for k in sorted(set(first) | set(last)) if first.get(k) != last.get(k)}
        drift["metrics_samples"] = len(snaps)
print(json.dumps({"run": run.name, "idle_p99_ms": idle, "p99_bound_ms": ms.p99_bound(idle), "whole": whole,
                  "windows_60s": {"n": len(w60), "pass": sum(w["pass"] for w in w60), "rows": w60},
                  "blocks_300s": b300, "drift": drift}, indent=1))
