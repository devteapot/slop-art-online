#!/usr/bin/env python3
"""growth-diag: per profile window (prof.jsonl `prof` records), each span's total time (ms per second of
window) and count, from the replica module log (JSON lines, ts in µs). Also per window, from the prof
snapshots: the unprofiled interval before it ([S2(k-1), S1(k)]): DB-thread CPU (ms/s, threads named
like the wasm worker), tick wasm time, ticks/s (reducer counter), and table rows at S1(k).
Usage: spans.py RUN_DIR > spans.json   (RUN_DIR holds prof.jsonl and replica-module-logs.tar or module_logs/)"""
import collections, io, json, re, sys, tarfile
from pathlib import Path

run = Path(sys.argv[1])
prof = [json.loads(l) for l in open(run / "prof.jsonl")]
wins = [(r["k"], r["on_t"] * 1e6, r["off_t"] * 1e6) for r in prof if r.get("tag") == "prof"]
SPAN = re.compile(r'"ts":(\d+),"function":"([^"]*)","message":"Timing span \\"([^"\\]+)\\": ([\d.]+)(ns|µs|ms|s)"')
UNIT = {"ns": 1e-6, "µs": 1e-3, "ms": 1.0, "s": 1e3}
acc = {k: collections.defaultdict(lambda: [0.0, 0]) for k, _, _ in wins}
fn_acc = {k: collections.defaultdict(lambda: [0.0, 0]) for k, _, _ in wins}


def lines():
    tar = run / "replica-module-logs.tar"
    if tar.exists():
        with tarfile.open(tar) as t:
            for m in t.getmembers():
                if m.isfile() and m.name.endswith(".log"):
                    yield from io.TextIOWrapper(t.extractfile(m), encoding="utf-8", errors="replace")
    else:
        for p in sorted(run.glob("module_logs/**/*.log")):
            yield from open(p, encoding="utf-8", errors="replace")


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
    if wi >= len(wins):
        break
    k, a, b = wins[wi]
    if not (a <= ts <= b + 2e6):
        continue
    ms = float(m.group(4)) * UNIT[m.group(5)]
    e = acc[k][m.group(3)]
    e[0] += ms
    e[1] += 1
    if m.group(3) == m.group(2) or m.group(3) == "tick":
        pass
    f = fn_acc[k][m.group(2)]
    f[1] += 1

snaps = {(r["tag"], r["k"]): r for r in prof if r.get("tag") in ("S0", "S1", "S2")}


def parse(r):
    d = {}
    for l in r["metrics"]:
        name, val = l.rsplit(" ", 1)
        d[name] = float(val)
    return d


def by(d, metric, label):
    out = collections.Counter()
    for k, v in d.items():
        if k.startswith(metric + "{"):
            m = re.search(label + r'="([^"]*)"', k)
            out[m.group(1) if m else ""] += v
    return out


def db_thread(r):
    return sum(v for n, v in r["threads"].items() if n.startswith(("wasm", "tokio-runtime-w", "main")))


rows = []
t0 = next(r["t"] for r in prof if r.get("tag") == "start")
for k, a, b in wins:
    secs = (b - a) / 1e6
    rec = {"k": k, "min": round((a / 1e6 - t0) / 60, 2), "secs": round(secs, 2)}
    rec["spans_ms_per_s"] = {n: round(v[0] / secs, 3) for n, v in sorted(acc[k].items(), key=lambda x: -x[1][0])}
    rec["spans_n"] = {n: v[1] for n, v in acc[k].items()}
    lo, hi = snaps.get(("S2", k - 1)), snaps.get(("S1", k))
    if lo and hi:
        dt = hi["t"] - lo["t"]
        pl, ph = parse(lo), parse(hi)
        rec["unprof_secs"] = round(dt, 1)
        rec["threads_ms_per_s"] = {n: round((hi["threads"].get(n, 0) - lo["threads"].get(n, 0)) * 10 / dt, 1) for n in hi["threads"] if hi["threads"].get(n, 0) - lo["threads"].get(n, 0) > 0}
        wl, wh = by(pl, "reducer_wasm_time_usec", "reducer"), by(ph, "reducer_wasm_time_usec", "reducer")
        rec["wasm_ms_per_s"] = {n: round((wh[n] - wl[n]) / 1e3 / dt, 1) for n in wh if wh[n] - wl[n] > 0}
        cl = by(pl, "spacetime_reducer_plus_query_duration_sec_count", "reducer")
        ch = by(ph, "spacetime_reducer_plus_query_duration_sec_count", "reducer")
        rec["ticks_per_s"] = round((ch["tick"] - cl["tick"]) / dt, 2) if ch.get("tick") else None
        for metric, label, key in (("spacetime_num_rows_scanned_total", "txn_type", "rows_scanned_per_s"),
                                   ("spacetime_num_bytes_scanned_total", "txn_type", "bytes_scanned_per_s"),
                                   ("spacetime_num_rows_inserted_total", "table_name", "inserted_per_s"),
                                   ("spacetime_num_rows_deleted_total", "table_name", "deleted_per_s")):
            ml, mh = by(pl, metric, label), by(ph, metric, label)
            d = {n: round((mh[n] - ml[n]) / dt, 1) for n in mh if mh[n] - ml[n] > 0}
            rec[key] = dict(sorted(d.items(), key=lambda x: -x[1])[:12])
        rec["rows"] = {n: int(v) for n, v in by(ph, "spacetime_data_size_table_num_rows", "table_name").items()}
        rec["row_bytes"] = {n: int(v) for n, v in by(ph, "spacetime_data_size_bytes_used_by_rows", "table_name").items()}
        rec["wasm_memory"] = sum(by(ph, "spacetime_worker_wasm_memory_bytes", "database_identity").values())
        rec["jemalloc_allocated"] = sum(v for n, v in ph.items() if n.startswith("jemalloc_allocated_bytes"))
        rec["cgroup_bytes"] = hi.get("cgroup_bytes")
        rec["load1"] = hi.get("load1")
    rows.append(rec)
print(json.dumps({"run": run.name, "windows": rows}, indent=0))
