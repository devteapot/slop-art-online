#!/usr/bin/env python3
"""Subscription-cost probe driver (docs/VIEWER_FLOOR.md, M1; branch viewer-floor only).

    LIVING_STDB_CONTAINER=vf-probe LIVING_STDB_URL=http://127.0.0.1:3361 \
      python3 living/tools/sub_probe.py --wasm sub-probe.wasm --counts 216,64,16,1 --out DIR

Publishes `living/tools/sub_probe` (built to /wasm/<wasm> in the container) as a fresh
`verify-subprobe-<stamp>` database, starts the most subscribers first (each an anonymous
`spacetime subscribe` in the container, subscribed to `ri`, `ru`, `pb` and `my_pv`), and for each
count and mode: `setup` (rows per subscriber), `set(mode, k)`, a warm-up, then a window over
which it reads the server's metrics and the database thread's CPU. Fewer subscribers: the newest
are stopped (by PID) and `setup` runs again. Writes one JSON per arm and `summary.json`.

Per arm: ticks a second, database-thread ms/s, the tick's reducer ms/s (`txn_cpu` Reducer) and its
subscription evaluation (`txn_cpu` Update), view time, bytes and rows sent, and from these µs per
written row. The tokio threads (the send worker, websockets) are reported apart: they are not
the database thread.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost as lc  # noqa: E402
import tick_cost as tc  # noqa: E402

MODES = {1: "rls_indexed", 2: "rls_unindexed", 3: "public_all", 4: "view", 5: "tick_only"}
QUERIES = ["SELECT * FROM ri", "SELECT * FROM ru", "SELECT * FROM pb", "SELECT * FROM my_pv"]


def metric(m, name, **labels):
    tot = 0.0
    for k, v in m.items():
        if not k.startswith(name + "{"):
            continue
        if all(f'{lk}="{lv}"' in k for lk, lv in labels.items()):
            tot += v
    return tot


def window(ident, pid, seconds):
    m0, th0 = tc.scrape(ident), tc.thread_cpu(pid)
    t0 = time.time()
    time.sleep(seconds)
    m1, th1 = tc.scrape(ident), tc.thread_cpu(pid)
    dur = time.time() - t0
    hz = os.sysconf("SC_CLK_TCK")
    by = {}
    for tid, (name, c1) in th1.items():
        c0 = th0.get(tid, (name, 0))[1]
        by[name] = by.get(name, 0.0) + (c1 - c0) / hz / dur * 1000
    d = {k: m1.get(k, 0.0) - m0.get(k, 0.0) for k in set(m0) | set(m1)}
    return d, by, dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wasm", default="sub-probe.wasm")
    ap.add_argument("--counts", default="216,64,16,1")
    ap.add_argument("--modes", default="5,1,2,4,3")
    ap.add_argument("--k", type=int, default=50, help="rows written a tick")
    ap.add_argument("--k-public", type=int, default=10, help="rows a tick in the public mode (every subscriber receives each)")
    ap.add_argument("--rows", type=int, default=50, help="rows per subscriber in each table")
    ap.add_argument("--warmup", type=float, default=5)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = f"verify-subprobe-{time.strftime('%Y%m%d%H%M%S')}"
    lc.stdb("publish", "-s", "local", "-b", str(Path("/wasm") / a.wasm), db, "-y")
    ident = json.loads(lc.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
    token = lc.admin_token()
    pid = tc.server_pid()
    counts = sorted((int(c) for c in a.counts.split(",")), reverse=True)
    procs = []
    log = open(out / "subscribers.log", "w")
    for i in range(counts[0]):
        p = subprocess.Popen(["docker", "exec", "-e", "TOKIO_WORKER_THREADS=1", lc.CONTAINER, "spacetime", "subscribe", "-s", "local", "--anonymous", "-y", db, *QUERIES],
                             stdout=subprocess.DEVNULL, stderr=log)
        procs.append(p)
        if i % 16 == 15:
            time.sleep(1)
    all_procs = list(procs)
    want = counts[0]
    for _ in range(120):
        n = lc.sql(db, "SELECT COUNT(*) AS n FROM sub", token)[0]["n"]
        if n >= want:
            break
        time.sleep(1)
    summary = {"db": db, "k": a.k, "k_public": a.k_public, "rows": a.rows, "arms": []}
    for count in counts:
        while len(procs) > count:
            # Stopping `docker exec` does not stop the process inside the container: the newest
            # subscriber there goes first, then its exec.
            subprocess.run(["docker", "exec", lc.CONTAINER, "pkill", "-n", "-f", "spacetime subscribe"], capture_output=True)
            procs.pop()  # (its exec ends with whichever subscriber pkill took; all are reaped at the end)
        for _ in range(60):
            n = lc.sql(db, "SELECT COUNT(*) AS n FROM sub", token)[0]["n"]
            if n == count:
                break
            time.sleep(1)
        lc.call(db, "set", [0, 0], token)
        lc.call(db, "setup", [a.rows], token)
        time.sleep(3)
        for mode in (int(m) for m in a.modes.split(",")):
            k = a.k_public if mode == 3 else a.k
            lc.call(db, "set", [mode, k], token)
            time.sleep(a.warmup)
            n0 = lc.sql(db, "SELECT COUNT(*) AS n FROM sub", token)[0]["n"]
            d, by, dur = window(ident, pid, a.seconds)
            lc.call(db, "set", [0, 0], token)
            n = lc.sql(db, "SELECT COUNT(*) AS n FROM sub", token)[0]["n"]
            if n != n0 or n != count:
                print(f"WARNING: subscribers {n0} -> {n} during the window (wanted {count})", file=sys.stderr, flush=True)
            ticks = metric(d, "spacetime_txn_cpu_time_sec_count", txn_type="Reducer", reducer="tick") / dur
            arm = {
                "subscribers": n, "mode": MODES[mode], "k": k if mode != 5 else 0, "seconds": round(dur, 2), "ticks_per_s": round(ticks, 2),
                "db_thread_ms_s": round(sum(v for t, v in by.items() if t.startswith("wasm-")), 2),
                "tokio_ms_s": round(sum(v for t, v in by.items() if t.startswith("tokio")), 2),
                "reducer_ms_s": round(metric(d, "spacetime_txn_cpu_time_sec_sum", txn_type="Reducer", reducer="tick") / dur * 1000, 3),
                "update_ms_s": round(metric(d, "spacetime_txn_cpu_time_sec_sum", txn_type="Update", reducer="tick") / dur * 1000, 3),
                "view_ms_s": round(metric(d, "view_total_time_usec") / dur / 1000, 3),
                "view_calls_s": round(metric(d, "view_calls") / dur, 1),
                "rows_sent_s": round(metric(d, "spacetime_websocket_sent_num_rows_sum") / dur, 1),
                "kB_sent_s": round(metric(d, "spacetime_num_bytes_sent_to_clients_total") / dur / 1000, 2),
                "rows_scanned_s": round(metric(d, "spacetime_num_rows_scanned_total") / dur, 1),
                "index_seeks_s": round(metric(d, "spacetime_num_index_seeks_total") / dur, 1),
                "load1": float(open("/proc/loadavg").read().split()[0]),
            }
            w = arm["k"] * ticks
            arm["writes_s"] = round(w, 1)
            print(json.dumps(arm), flush=True)
            summary["arms"].append(arm)
            (out / f"arm-{n}-{MODES[mode]}.json").write_text(json.dumps({"arm": arm, "diff": d, "threads": by}, indent=1) + "\n")
    subprocess.run(["docker", "exec", lc.CONTAINER, "pkill", "-f", "spacetime subscribe"], capture_output=True)
    for p in all_procs:
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()
    lc.call(db, "stop", [], token)
    # Per written row: each mode against the tick-only arm at the same count.
    base = {x["subscribers"]: x for x in summary["arms"] if x["mode"] == "tick_only"}
    for x in summary["arms"]:
        b = base.get(x["subscribers"])
        if b and x["writes_s"]:
            for key in ("db_thread_ms_s", "reducer_ms_s", "update_ms_s", "view_ms_s"):
                x[f"{key.removesuffix('_ms_s')}_us_per_row"] = round((x[key] - b[key]) / x["writes_s"] * 1000, 2)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(f"db {db}: delete it with world_delete when done (no world: a plain delete)", file=sys.stderr)


if __name__ == "__main__":
    main()
