#!/usr/bin/env python3
"""Cost of what player clients receive, with real connections (docs/PERCEPTION.md).

Usage: living/tools/perception_bench.py --db verify-perc-bench --wasm FILE --mode open|scoped
       --players N --placement spread|square [--seconds 60] [--settle 20] [--out FILE]

Publishes `--wasm` (a file in the server's /wasm mount) fresh as `--db` (a `verify-*` scratch
database only), installs the skill script, joins N player identities over HTTP, places them
with the admin `place_at` (`spread`: round the island's settlements, one lot apart in turn;
`square`: within 6 m of the walled town's centre), and connects them with
`living/tools/perception_load` subscribing as the game client does (`open`: the tables and
chunk windows of b7cf7fb; `scoped`: the perception views). The characters stand still, or
with `--walk` keep walking in small circles where they were placed.

Over the window it reports:
- the tick's own code (the module's LogStopwatch spans, as `bench.py`): p50/p95/p99/max;
- the tick transaction with its view refresh and subscription evaluation
  (`spacetime_reducer_plus_query_duration_sec{reducer="tick"}`: its mean, and how many went
  over 5 and 10 ms, the histogram's smallest buckets), beside the tick's own WASM time;
- view calls per second by the reducer that triggered them, and each view's WASM time per
  second (`reducer_wasm_time_usec{reducer=<view>}`; materializing the rows is in the mean);
- bytes sent to clients per second, in all and per player (`spacetime_num_bytes_sent_to_clients_total`);
- the server container's CPU (cgroup `cpu.stat`) and memory (`memory.current`), and the
  database's WASM memory and the server's jemalloc resident bytes.
The server must serve no other active database during the window.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("bench", ROOT / "living/tools/bench.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
CONTAINER = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")
LOAD = Path(os.environ.get("PERCEPTION_LOAD", ROOT / ".local/living/perception-load/release/perception-load"))


def http(path, body=None, token=None, raw=False):
    data = body.encode() if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL + path, data=data, method="POST" if data is not None or path == "/v1/identity" else "GET")
    if not raw and data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def admin_token():
    out = B.stdb("login", "show", "--token")
    return next(l.rsplit(" is ", 1)[1].strip() for l in out.splitlines() if "auth token" in l and " is " in l)


def sql(db, q, token):
    code, body = http(f"/v1/database/{db}/sql", q, token, raw=True)
    if code != 200:
        sys.exit(f"sql {q!r}: {code} {body[:400]}")
    res = json.loads(body)[0]
    names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def metrics():
    return urllib.request.urlopen(f"{URL}/v1/metrics", timeout=30).read().decode()


def series(text, name, ident):
    """Samples of a metric for this database: {label string: value}."""
    out = {}
    for m in re.finditer(rf'^{name}\{{([^}}]*)\}} (\S+)$', text, re.M):
        labels = m.group(1)
        if ident in labels:
            out[labels] = float(m.group(2))
    return out


def label(labels, key):
    m = re.search(rf'{key}="([^"]*)"', labels)
    return m and m.group(1)


def cgroup():
    r = subprocess.run(["docker", "exec", CONTAINER, "sh", "-c", "cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current"], capture_output=True, text=True)
    usage = int(re.search(r"usage_usec (\d+)", r.stdout).group(1))
    mem = int(r.stdout.strip().splitlines()[-1])
    return usage, mem


def placements(db, token, n, how):
    settlements = sql(db, "SELECT * FROM settlement", token)
    if how == "square":
        town = next(s for s in settlements if s["kind"] == "town")
        out = []
        for i in range(n):
            a, r = i * 2.399963, 6.0 * math.sqrt((i + 0.5) / max(n, 1))
            out.append((town["x"] + r * math.cos(a), town["y"] + r * math.sin(a)))
        return out
    lots = sql(db, "SELECT * FROM lot", token)
    by = {}
    for l in sorted(lots, key=lambda l: l["id"]):
        by.setdefault(l["settlement"], []).append(l)
    order = sorted(by)
    out, k = [], 0
    while len(out) < n:
        s = by[order[k % len(order)]]
        lot = s[(k // len(order)) * 7 % len(s)]
        out.append((lot["door_x"], lot["door_y"]))
        k += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--wasm", required=True)
    ap.add_argument("--mode", choices=["open", "scoped"], required=True)
    ap.add_argument("--players", type=int, required=True)
    ap.add_argument("--placement", choices=["spread", "square"], default="spread")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--settle", type=int, default=20)
    ap.add_argument("--walk", action="store_true", help="the players keep walking in small circles")
    ap.add_argument("--keep", action="store_true", help="reuse the published database (no republish)")
    ap.add_argument("--out")
    a = ap.parse_args()
    if not a.db.startswith("verify-"):
        sys.exit("benchmarks run only on verify-* scratch databases")
    if not a.keep:
        B.stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", a.db, "--delete-data", "-y")
        B.stdb("call", "-s", "local", a.db, "install_script", json.dumps((ROOT / "living/scripts/skills.rhai").read_text()))
    admin = admin_token()
    ident = json.loads(http(f"/v1/database/{a.db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
    tokens = []
    for i in range(a.players):
        code, body = http("/v1/identity", {})
        tokens.append(json.loads(body)["token"])
        code, body = http(f"/v1/database/{a.db}/call/join", [f"Bench{i}"], tokens[-1])
        if code != 200:
            sys.exit(f"join {i}: {code} {body}")
    people = sql(a.db, "SELECT * FROM character WHERE kind = 'person'", admin)
    mine = sorted((c for c in people if c["name"].startswith("Bench") and c["alive"]), key=lambda c: int(c["name"][5:]))
    for c, (x, y) in zip(mine, placements(a.db, admin, a.players, a.placement)):
        code, body = http(f"/v1/database/{a.db}/call/place_at", [c["id"], x, y], admin)
        if code != 200:
            sys.exit(f"place_at #{c['id']}: {code} {body}")
    time.sleep(a.settle)
    load = subprocess.Popen([str(LOAD)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    load.stdin.write(json.dumps({"uri": URL, "db": a.db, "mode": a.mode, "seconds": a.seconds, "tokens": tokens, "walk": a.walk}))
    load.stdin.close()
    ready = json.loads(load.stdout.readline() or "null")
    if not ready or ready.get("event") != "ready":
        sys.exit(f"load did not get ready: {ready} {load.stderr.read()[-3000:]}")
    # The window.
    m0, c0, s0, t0 = metrics(), cgroup(), B.stats(a.db), time.time()
    B.stdb("call", "-s", "local", a.db, "set_profile", "true")
    mem_peak = c0[1]

    def sample():
        nonlocal mem_peak
        while load.poll() is None:
            mem_peak = max(mem_peak, cgroup()[1])
            time.sleep(5)

    threading.Thread(target=sample, daemon=True).start()
    done = json.loads(load.stdout.readline() or "null")
    B.stdb("call", "-s", "local", a.db, "set_profile", "false")
    m1, c1, s1, t1 = metrics(), cgroup(), B.stats(a.db), time.time()
    load.wait(timeout=60)
    if not done or done.get("event") != "done":
        sys.exit(f"load failed: {load.stderr.read()[-3000:]}")
    dt = t1 - t0
    w = sql(a.db, "SELECT * FROM world", admin)[0]
    hour = lambda t: ((int(t * 1000) - w["epoch_ms"] + w["day_ms"] * 7 // 24) % w["day_ms"]) / w["day_ms"] * 24
    logs = B.stdb("logs", "-s", "local", a.db, "-n", str(a.seconds * 60 * 10 + 4000))
    spans = {}
    for m in re.finditer(r'^(\S+Z)\s.*Timing span "([^"]+)": ([\d.]+)(µs|ms|s)\b', logs, re.M):
        stamp = m.group(1)[:26].rstrip("Z")
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        if at < t0 - 1:
            continue
        spans.setdefault(m.group(2), []).append(float(m.group(3)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[m.group(4)])
    tick = spans.get("tick", [])
    # The tick transaction with its views and subscription evaluation (histogram).
    hist0 = {label(k, "le"): v for k, v in series(m0, "spacetime_reducer_plus_query_duration_sec_bucket", ident).items() if label(k, "reducer") == "tick"}
    hist1 = {label(k, "le"): v for k, v in series(m1, "spacetime_reducer_plus_query_duration_sec_bucket", ident).items() if label(k, "reducer") == "tick"}
    buckets = sorted(((float("inf") if le == "+Inf" else float(le), hist1[le] - hist0.get(le, 0)) for le in hist1), key=lambda x: x[0])
    total = buckets[-1][1] if buckets else 0

    def delta(name, key="reducer"):
        v0, v1 = series(m0, name, ident), series(m1, name, ident)
        return {label(k, key): v - v0.get(k, 0) for k, v in v1.items()}

    wasm_us, calls = delta("reducer_wasm_time_usec"), delta("view_calls_triggered_by_reducer")
    views = {v: round(us / dt / 1000, 2) for v, us in sorted(wasm_us.items()) if v.startswith(("seen_", "my_"))}
    tx_sum, tx_count = delta("spacetime_reducer_plus_query_duration_sec_sum"), delta("spacetime_reducer_plus_query_duration_sec_count")
    bytes0, bytes1 = series(m0, "spacetime_num_bytes_sent_to_clients_total", ident), series(m1, "spacetime_num_bytes_sent_to_clients_total", ident)
    sent = {label(k, "txn_type"): (v - bytes0.get(k, 0)) / dt for k, v in bytes1.items()}
    wasm_mem = series(m1, "spacetime_worker_wasm_memory_bytes", ident)
    jemalloc = re.search(r"^jemalloc_resident_bytes(?:\{[^}]*\})? (\S+)$", m1, re.M)
    events = {}
    for p in done["players"]:
        for t, e in p["events"].items():
            agg = events.setdefault(t, {"insert": 0, "update": 0, "delete": 0})
            for k in agg:
                agg[k] += e[k]
    n = a.players
    report = {
        "db": a.db, "wasm": a.wasm, "mode": a.mode, "players": n, "placement": a.placement, "walk": a.walk, "seconds": round(dt, 1), "world_hours": [round(hour(t0), 1), round(hour(t1), 1)],
        "people": s1["alive_people"], "animals": s1["alive_animals"], "ticks_per_s": round((s1["ticks"] - s0["ticks"]) / dt, 1),
        "motions_per_s": round((s1["motions"] - s0["motions"]) / dt, 1), "max_tick_gap_ms_last_s": s1["max_tick_gap_ms"],
        "tick_code_ms": {"samples": len(tick), "p50": round(B.pct(tick, 50), 3), "p95": round(B.pct(tick, 95), 3), "p99": round(B.pct(tick, 99), 3), "max": round(max(tick, default=0), 3)},
        "tick_spans_ms_per_s": {k: round(sum(v) / dt, 2) for k, v in sorted(spans.items()) if k.startswith("tick.")},
        "tick_spans_p99_ms": {k: round(B.pct(v, 99), 3) for k, v in sorted(spans.items()) if k.startswith("tick.")},
        "tick_tx_with_views_ms": {"count": total, "mean": round(tx_sum.get("tick", 0) / max(tx_count.get("tick", 0), 1) * 1000, 3),
                                   "over_5ms": total - dict(buckets).get(0.005, total), "over_10ms": total - dict(buckets).get(0.01, total)},
        "tick_wasm_mean_ms": round(wasm_us.get("tick", 0) / max(tx_count.get("tick", 0), 1) / 1000, 3),
        "view_calls_per_s_by_trigger": {k: round(v / dt, 1) for k, v in sorted(calls.items()) if v},
        "view_wasm_ms_per_s": views,
        "view_wasm_us_per_call": round(sum(us for v, us in wasm_us.items() if v.startswith(("seen_", "my_"))) / max(sum(calls.values()), 1), 1),
        "bytes_per_s": {k: round(v) for k, v in sorted(sent.items())},
        "bytes_per_s_per_player": round(sum(sent.values()) / max(n, 1)),
        "update_bytes_per_s_per_player": round(sent.get("Update", 0) / max(n, 1)),
        "server_cpu_cores": round((c1[0] - c0[0]) / 1e6 / dt, 3),
        "server_memory_mb": {"start": round(c0[1] / 2**20), "end": round(c1[1] / 2**20), "peak_sampled": round(mem_peak / 2**20)},
        "wasm_memory_mb": {label(k, "database_identity") and "db" or k: round(v / 2**20, 1) for k, v in wasm_mem.items()},
        "jemalloc_resident_mb": round(float(jemalloc.group(1)) / 2**20) if jemalloc else None,
        "client_events_per_s_per_player": {t: {k: round(v / dt / max(n, 1), 1) for k, v in e.items()} for t, e in sorted(events.items())},
        "held_at_ready": ready["held"][:5], "held_mean_bodies": round(sum(h["bodies"] for h in ready["held"]) / max(n, 1), 1),
    }
    print(json.dumps(report, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
