#!/usr/bin/env python3
"""gate216-x925 per-run table: tables.py's fields (cc_tables.one) plus step p95, the window's load,
core placement (cores.jsonl) and the strict 60 Hz verdict. Usage: summarize.py GR_CHECKOUT RUNS_DIR"""
import collections, json, statistics, sys
from pathlib import Path
GR, R = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
sys.path.insert(0, str(GR / "living/tools")); sys.path.insert(0, str(GR / "living/tools/gate_remeasure"))
import cc_tables as ct  # noqa: E402
ct.R = R
X925 = set(range(5, 10)) | set(range(15, 20))
rows = []
for d in sorted(R.iterdir()):
    if not (d.is_dir() and (d / "battle-viewers.json").exists()):
        continue
    one = ct.one(d)
    bv = json.loads((d / "battle-viewers.json").read_text())["rows"][0]
    w = bv["window"]; iv = (bv.get("steps") or {}).get("interval_ms") or {}
    loads = [float(l.split()[1]) for l in open(d / f"v{bv['viewers']}" / "load.log")]
    srv, host, wasm = collections.Counter(), collections.Counter(), collections.Counter()
    fx = []
    for line in open(d / "cores.jsonl"):
        r = json.loads(line)
        if not (w["t0"] <= r["t"] <= w["t1"]):
            continue
        fx.append(min(v for c, v in r["freq_mhz"].items() if int(c) in X925))
        for t in r["threads"]:
            (srv if t["server"] else host)[t["cpu"]] += t["ms"]
            if t["server"] and t["name"].startswith("wasm"):
                wasm[t["cpu"]] += t["ms"]
    sx = sum(v for c, v in srv.items() if c in X925); hx = sum(v for c, v in host.items() if c in X925)
    ticks, p99 = one.get("ticks"), iv.get("p99")
    rows.append({"run": d.name, "arm": d.name.rsplit("-r", 1)[0], "ticks_s": ticks, "p50": iv.get("p50"), "p95": iv.get("p95"),
                 "p99": p99, "max": iv.get("max"), "over25_pct": one.get("over25"), "skipped": one.get("skipped"),
                 "db_ms_s": one.get("db"), "human_inputs_s": one.get("human_inputs_s"), "human_deaths_s": one.get("human_deaths_s"),
                 "relay_cpu_ms_s": one.get("relay_cpu"), "privacy": one.get("privacy"),
                 "strict60": bool(ticks is not None and p99 is not None and ticks >= 59.9 and p99 <= 17),
                 "load_max": max(loads), "load_end": loads[-1], "load_rise": round(max(b - min(loads[:i + 1]) for i, b in enumerate(loads)), 2),
                 "server_cpu_on_x925_pct": round(100 * sx / max(1, sum(srv.values())), 2), "server_cpu_ms_s": round(sum(srv.values()) / 60, 1),
                 "db_thread_cpu_ms": dict(sorted(wasm.items())), "host_side_cpu_on_x925_pct": round(100 * hx / max(1, sum(host.values())), 2),
                 "host_side_cpu_ms_s": round(sum(host.values()) / 60, 1), "x925_freq_min_mhz": min(fx) if fx else None, "host": one.get("host"),
                 "window_t0": w["t0"]})
    print(json.dumps({k: v for k, v in rows[-1].items() if k not in ("db_thread_cpu_ms", "host")}))
(R / "x925-summary.json").write_text(json.dumps(rows, indent=1) + "\n")
