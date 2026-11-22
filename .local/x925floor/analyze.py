#!/usr/bin/env python3
"""Roll up the x925-floor series: per run and per arm (valid runs: rc 0, window load max <= 8)."""
import json, math, re, statistics as st, sys
from pathlib import Path
RUNS = Path(sys.argv[1] if len(sys.argv) > 1 else ".local/x925floor/runs")
HZ = 100

def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q / 100
    f = math.floor(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)

def hist_pct(buckets, q):
    """Per-tick duration percentile (ms) from cumulative Prometheus buckets [(le, count)], linear in-bucket."""
    total = buckets[-1][1]
    want = total * q / 100
    prev_le, prev_c = 0.0, 0.0
    for le, c in buckets:
        if c >= want:
            if le == math.inf:
                return f">{prev_le * 1000:g}"
            return round((prev_le + (le - prev_le) * ((want - prev_c) / (c - prev_c) if c > prev_c else 0)) * 1000, 2)
        prev_le, prev_c = le, c
    return None

def one(d):
    s = json.loads((d / "series-run.json").read_text())
    n = s["viewers"]
    v = d / f"v{n}"
    res = json.loads((v / "result.json").read_text())
    th = json.loads((v / "threads.json").read_text())
    wasm = {k: x for k, x in th["threads_cpu_ms_per_s"].items() if k.startswith("wasm-")}
    db_thread = max(sum(x) for x in wasm.values())
    wname = max(wasm, key=lambda k: sum(wasm[k]))
    met = json.loads((v / "metrics.json").read_text())
    diff, secs = met["diff"], met["seconds"]
    def g(prefix, **lab):
        tot = 0.0
        for k, x in diff.items():
            if k.startswith(prefix + "{") and all(f'{a}="{b}"' in k for a, b in lab.items()):
                tot += x
        return tot
    tick_call = g("spacetime_reducer_plus_query_duration_sec_sum", reducer="tick") / secs * 1000
    tick_n = g("spacetime_reducer_plus_query_duration_sec_count", reducer="tick")
    bk = []
    for k, x in diff.items():
        m = re.match(r'spacetime_reducer_plus_query_duration_sec_bucket\{.*reducer="tick".*le="([^"]+)"', k)
        if m:
            bk.append((math.inf if m.group(1) == "+Inf" else float(m.group(1)), x))
    # buckets with zero diff are dropped from `diff`; rebuild from before/after
    bk = []
    for k in met["after"]:
        m = re.match(r'spacetime_reducer_plus_query_duration_sec_bucket\{.*reducer="tick".*le="([^"]+)"', k)
        if m:
            bk.append((math.inf if m.group(1) == "+Inf" else float(m.group(1)), met["after"][k] - met["before"].get(k, 0.0)))
    bk.sort()
    txn = {}
    for k, x in diff.items():
        m = re.match(r'spacetime_txn_cpu_time_sec_sum\{.*reducer="([^"]+)".*txn_type="([^"]+)"', k)
        if m:
            key = f"{m.group(1)}/{m.group(2)}"
            txn[key] = round(txn.get(key, 0) + x / secs * 1000, 2)
    views = sum(x for k, x in diff.items() if k.startswith("view_total_time_usec")) / secs / 1000 if any(k.startswith("view_total_time_usec") for k in diff) else None
    # per-second DB-thread ms/s from the sampler, inside the window
    t0, t1 = res["window"]["t0"], res["window"]["t1"]
    per_s, ticks_s = [], []
    prev = None
    for l in open(d / "samples.jsonl"):
        r = json.loads(l)
        cpu = sum(c for _, (nm, c, _) in r["threads"].items() if nm == wname)
        tk = sum(x for kk, x in r.get("tick", {}).items() if kk.startswith("spacetime_reducer_plus_query_duration_sec_count"))
        if prev and t0 <= prev[0] and r["t"] <= t1 + 0.5:
            dt = r["t"] - prev[0]
            per_s.append((cpu - prev[1]) / HZ / dt * 1000)
            ticks_s.append((tk - prev[2]) / dt)
        prev = (r["t"], cpu, tk)
    wl = [float(l.split()[1]) for l in open(v / "load.log")]
    kw = res.get("keeper_window", {})
    return {"name": d.name, "viewers": n, "valid": s["rc"] == 0 and max(wl) <= 8, "rc": s["rc"],
            "start_load": s["start"]["load1"], "window_load_median": round(sorted(wl)[len(wl) // 2], 2), "window_load_max": max(wl),
            "cpuset": s["start"]["cpuset"], "ticks_per_s": res["ticks_per_s"], "db_thread_ms_s": round(db_thread, 1),
            "tick_call_ms_s": round(tick_call, 1), "tick_ms_p50": hist_pct(bk, 50), "tick_ms_p95": hist_pct(bk, 95), "tick_ms_p99": hist_pct(bk, 99),
            "tick_ms_mean": round(tick_call / (tick_n / secs), 3) if tick_n else None,
            "per_s_db_ms": {"n": len(per_s), "mean": round(st.mean(per_s), 1), "p50": round(pct(per_s, 50), 1), "p95": round(pct(per_s, 95), 1), "max": round(max(per_s), 1)} if per_s else None,
            "per_s_ticks": {"p5": round(pct(ticks_s, 5), 1), "min": round(min(ticks_s), 1)} if ticks_s else None,
            "process_ms_s": th["process_cpu_ms_per_s"], "views_ms_s": round(views, 2) if views is not None else None,
            "txn_cpu_ms_s_top": dict(sorted(txn.items(), key=lambda kv: -kv[1])[:8]),
            "fighters_alive_mean": kw.get("alive_mean"), "fighters_alive_min": kw.get("alive_min"), "refills_per_s": kw.get("refills_per_s"),
            "viewer_deaths": res.get("viewer_deaths"), "keep_alive_window": res.get("keep_alive_window"),
            "seen_characters_at_ready": (res.get("held_at_ready_mean") or {}).get("seen_characters_mean"), "window_s": round(t1 - t0, 1)}

def summ(xs):
    return {"n": len(xs), "mean": round(st.mean(xs), 2), "sd": round(st.stdev(xs), 2) if len(xs) > 1 else None, "min": min(xs), "max": max(xs)}

runs = [one(d) for d in sorted(RUNS.iterdir()) if (d / "series-run.json").exists() and (d / f"v{json.loads((d / 'series-run.json').read_text())['viewers']}" / "result.json").exists()]
arms = {}
for r in runs:
    if r["valid"]:
        arms.setdefault(r["viewers"], []).append(r)
out = {"runs": runs, "arms": {}}
for n, rs in sorted(arms.items()):
    out["arms"][n] = {k: summ([r[k] for r in rs]) for k in ("db_thread_ms_s", "tick_call_ms_s", "ticks_per_s")}
    out["arms"][n]["per_s_db_ms_p50_mean"] = round(st.mean(r["per_s_db_ms"]["p50"] for r in rs), 1)
    out["arms"][n]["per_s_db_ms_p95_mean"] = round(st.mean(r["per_s_db_ms"]["p95"] for r in rs), 1)
    out["arms"][n]["runs"] = [r["name"] for r in rs]
if 0 in arms and 16 in arms:
    per = {}
    for key in ("db_thread_ms_s", "tick_call_ms_s"):
        a0 = [r[key] for r in arms[0]]; a16 = [r[key] for r in arms[16]]
        m = (st.mean(a16) - st.mean(a0)) / 16
        se = math.sqrt((st.variance(a16) / len(a16) if len(a16) > 1 else 0) + (st.variance(a0) / len(a0) if len(a0) > 1 else 0)) / 16
        per[key] = {"per_viewer": round(m, 2), "se": round(se, 2), "range": [round((min(a16) - max(a0)) / 16, 2), round((max(a16) - min(a0)) / 16, 2)]}
    out["per_viewer"] = per
print(json.dumps(out, indent=1))
