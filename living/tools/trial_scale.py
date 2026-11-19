#!/usr/bin/env python3
"""Per-world cost of a running trial batch on the trial service (docs/TRIALS.md, "Running
wide"). Read-only apart from turning each world's tick profiling on for the window.

  trial_scale.py BATCH [--seconds 60]

For every live database of the batch: tick duration p50/p95/p99/max and ticks over the
16.7 ms budget, from the module's profile spans (as living/tools/bench.py reads them). For
the host: the SpacetimeDB and Neo4j containers' CPU and memory (`docker stats`), each mind
process's resident memory, the trial volume's size, MemAvailable and the load average.
Appends one JSON line to .local/living/trials/BATCH/scale.jsonl and prints a summary.
"""
import argparse
import json
import re
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials as T  # noqa: E402

SPAN = re.compile(r'Timing span "tick": ([\d.]+)(µs|ms|s)\b')


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 2) if xs else None


def host():
    mem = dict(l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines())
    avail_gb = int(mem["MemAvailable"].split()[0]) / 1048576
    load = Path("/proc/loadavg").read_text().split()[:3]
    stats = {}
    for name in (T.CONTAINER, T.NEO4J):
        r = T.sh("docker", "stats", "--no-stream", "--format", "{{.CPUPerc}} {{.MemUsage}}", name, check=False).stdout.strip()
        stats[name] = r
    vol = T.sh("docker", "exec", T.CONTAINER, "du", "-sm", "/home/spacetime/.local/share/spacetime/data/replicas", check=False).stdout.split()
    return {"mem_available_gb": round(avail_gb, 1), "load": load, "containers": stats, "replicas_mb": int(vol[0]) if vol else None}


def minds(bdir):
    out = {}
    for st in bdir.glob("*/state.json"):
        s = json.loads(st.read_text())
        pid = s.get("mind_pid")
        if s.get("status") == "running" and pid and T.proc_start(pid) == s.get("mind_start"):
            rss = next((l.split()[1] for l in Path(f"/proc/{pid}/status").read_text().splitlines() if l.startswith("VmRSS")), None)
            out[st.parent.name] = round(int(rss) / 1024) if rss else None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch")
    ap.add_argument("--seconds", type=int, default=60)
    a = ap.parse_args()
    T.guard()
    bdir = T.OUT / a.batch
    # The batch's own records (the runner's names), not `spacetime list`.
    dbs = [d for d in T.batch_databases(a.batch) if T.database_identity(d)]
    token = T.admin_token()
    before = host()
    started = time.time()
    for db in dbs:
        T.http(f"/v1/database/{db}/call/set_profile", [True], token)
    time.sleep(a.seconds)
    for db in dbs:
        T.http(f"/v1/database/{db}/call/set_profile", [False], token)
    worlds = {}
    lock = threading.Lock()

    def read(db):
        logs = T.sh("docker", "exec", T.CONTAINER, "spacetime", "logs", "-s", "local", db, "-n", str(a.seconds * 60 * 12 + 4000), check=False).stdout
        ticks = []
        for m in SPAN.finditer(logs):
            v = float(m.group(1)) * {"µs": 0.001, "ms": 1, "s": 1000}[m.group(2)]
            ticks.append(v)
        ticks = ticks[-a.seconds * 60:]
        with lock:
            worlds[db.removeprefix(f"{T.PREFIX}{a.batch}-")] = {"ticks": len(ticks), "p50": pct(ticks, 0.5), "p95": pct(ticks, 0.95), "p99": pct(ticks, 0.99),
                                                                 "max": round(max(ticks), 2) if ticks else None, "over_16_7ms": sum(1 for t in ticks if t > 16.7)}

    threads = [threading.Thread(target=read, args=(db,)) for db in dbs]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "window_s": a.seconds, "worlds": len(dbs), "host_before": before, "host_after": host(),
           "minds_rss_mb": minds(bdir), "per_world": worlds}
    with open(bdir / "scale.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    p99 = [w["p99"] for w in worlds.values() if w["p99"] is not None]
    rss = [v for v in row["minds_rss_mb"].values() if v]
    print(f"{len(dbs)} worlds, {a.seconds} s window from {time.strftime('%H:%M:%S', time.localtime(started))}")
    print(f"tick p99 per world: median {statistics.median(p99) if p99 else '–'} ms, max {max(p99) if p99 else '–'} ms; ticks over 16.7 ms: {sum(w['over_16_7ms'] for w in worlds.values())}")
    print(f"host: {row['host_after']}")
    print(f"minds: {len(rss)} running, RSS median {statistics.median(rss) if rss else '–'} MB, max {max(rss) if rss else '–'} MB")
    for k, w in sorted(worlds.items()):
        print(f"  {k}: {w}")


if __name__ == "__main__":
    main()
