#!/usr/bin/env python3
"""How big the mind service's model-call pool should be (docs/POOL_STUDY.md). Free: fake model.

  pool_study.py samples --journal DIR [--journal DIR ...] --out DIR
      Recorded calls from real journals (the act-trial's), one file per model, for the fake
      server's `samples` rule field (fake-llm.md): each call's latency, usage and, for think,
      deliberate, talk and act repair, its reply (memory work gets the fake's valid empty patch).
  pool_study.py script --samples DIR --out FILE [--limits-scale K]
      The fake server's script: every call answered from the samples of its model, with the
      rate-limit headers Mistral sent in the act-trial (`model limits` lines of its mind.log:
      1,333 requests and 10,666,666 (GLM) / 10,000,000 (DeepSeek) tokens a minute), each
      multiplied by K (a higher tier: what the slots alone do once the provider's limits are out
      of the way).
  pool_study.py proc --db DB --out FILE [--fake-match TEXT] [--every 2]
      Samples the CPU seconds, RSS and threads of the mind service thinking for DB (found by its
      LIVING_DB) and of the fake server, with the host's load, until the mind has gone.
  pool_study.py report --journal DIR [--from-ms T] [--skip-s S] [--to-ms T] [--minds N] [--proc FILE] [--json OUT]
      Per lane and purpose: calls, queue wait (enqueue to grant, the journal's `queue_wait_ms`)
      p50/p90/p99, model latency; throughput (calls and tokens a minute by profile), calls in
      flight, calls per mind-hour by purpose; the mind's CPU and RSS from a `proc` file.
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPLAYED = {"think", "deliberate", "talk", "act_repair"}
# What Mistral advertised in the act-trial (x-ratelimit-limit-*-minute, read back from the mind's
# `model limits` lines: ceiling = 0.9 × the header).
LIMITS = {"zai-glm-5-3-flash": {"x-ratelimit-limit-req-minute": "1333", "x-ratelimit-limit-tokens-minute": "10666666"},
          "deepseek-v4-1-flash-1017": {"x-ratelimit-limit-req-minute": "1333", "x-ratelimit-limit-tokens-minute": "10000000"}}


def entries(directory):
    for path in sorted(glob.glob(os.path.join(directory, "*.jsonl"))):
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "latency_ms" in r and "purpose" in r:
                yield r


def pct(values, p):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def samples(a):
    by_model = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for d in a.journal:
        for r in entries(d):
            if r.get("error") or not r.get("model"):
                continue
            usage = {"prompt_tokens": r.get("prompt_tokens") or 0, "completion_tokens": r.get("completion_tokens") or 0,
                     "total_tokens": (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0),
                     "prompt_tokens_details": {"cached_tokens": r.get("cached_tokens") or 0},
                     "completion_tokens_details": {"reasoning_tokens": r.get("reasoning_tokens") or 0}}
            s = {"latency_ms": r["latency_ms"], "usage": usage, "content": r.get("reply") if r["purpose"] in REPLAYED else None}
            by_model[r["model"]][r["purpose"]][r.get("actor") or "*"].append(s)
            by_model[r["model"]][r["purpose"]]["*"].append(s)
    # A purpose a model never answered (an overflow's) takes the other model's calls.
    purposes = {p for m in by_model.values() for p in m}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for model, table in by_model.items():
        for p in purposes - set(table):
            other = next(m for m in by_model.values() if p in m)
            table[p] = other[p]
        (out / f"{model}.json").write_text(json.dumps(table))
        print(model, {p: len(t["*"]) for p, t in sorted(table.items())})


def script(a):
    rules = []
    for path in sorted(Path(a.samples).glob("*.json")):
        model = path.stem
        rule = {"model": f"fake-{model}", "samples": str(path.resolve()), "times": -1}
        if model in LIMITS:
            rule["headers"] = {k: str(round(int(v) * a.limits_scale)) for k, v in LIMITS[model].items()}
        rules.append(rule)
    Path(a.out).write_text(json.dumps({"about": "pool_study.py script: recorded act-trial calls replayed by model"
                                       + f", with Mistral's advertised rate limits x {a.limits_scale:g}",
                                       "log_body": False, "rules": rules}, indent=1))


def proc_stat(pid):
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    ticks = os.sysconf("SC_CLK_TCK")
    cpu = (int(fields[11]) + int(fields[12])) / ticks
    status = {}
    for line in open(f"/proc/{pid}/status"):
        k, _, v = line.partition(":")
        status[k] = v.strip()
    kb = lambda k: int(status.get(k, "0 kB").split()[0])
    return {"cpu_s": cpu, "rss_kb": kb("VmRSS"), "hwm_kb": kb("VmHWM"), "threads": int(status.get("Threads", 0))}


def find(db, fake_match):
    """The mind service thinking for `db` (its LIVING_DB), and the fake server whose command line
    holds `fake_match` (its log path: the run's or the batch's directory)."""
    mind = fake = None
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            cmd = open(f"/proc/{d}/cmdline", "rb").read().split(b"\0")
            if cmd and cmd[0].endswith(b"living-mind"):
                env = open(f"/proc/{d}/environ", "rb").read().split(b"\0")
                if f"LIVING_DB={db}".encode() in env:
                    mind = int(d)
            elif fake_match and any(c.endswith(b"fake_llm.py") for c in cmd) and fake_match.encode() in b" ".join(cmd):
                fake = int(d)
        except OSError:
            continue
    return mind, fake


def proc(a):
    out = open(a.out, "a")
    mind = fake = None
    gone = 0
    start = time.time()
    while True:
        if mind is None:
            mind, fake = find(a.db, a.fake_match)
            if mind is None and time.time() - start > a.wait_s:
                print("no mind found", file=sys.stderr)
                return 1
        row = {"t": time.time(), "load": open("/proc/loadavg").read().split()[:3]}
        if mind:
            try:
                row["mind"] = proc_stat(mind)
                gone = 0
            except OSError:
                gone += 1
                if gone >= 3:
                    return 0
        if fake:
            try:
                row["fake"] = proc_stat(fake)
            except OSError:
                fake = None
        out.write(json.dumps(row) + "\n")
        out.flush()
        time.sleep(a.every)


def report(a):
    rows = [r for d in a.journal for r in entries(d)]
    for r in rows:
        r["end"] = r["at_ms"]
        r["send"] = r["at_ms"] - r["latency_ms"]
        r["enq"] = r["send"] - (r.get("queue_wait_ms") or 0)
    t0 = (a.from_ms or min(r["enq"] for r in rows)) + int(a.skip_s * 1000)
    t1 = a.to_ms or max(r["end"] for r in rows)
    # Calls granted in the window (the queue's view: what waited, for how long).
    win = [r for r in rows if t0 <= r["send"] < t1]
    minutes = (t1 - t0) / 60000
    lanes = defaultdict(list)
    for r in win:
        if r.get("error"):
            continue
        lane = r.get("lane") or "?"
        lanes[(lane, "*")].append(r)
        lanes[(lane, r["purpose"])].append(r)
        lanes[("all", "*")].append(r)
    table = {}
    for (lane, purpose), rs in sorted(lanes.items()):
        q = [r.get("queue_wait_ms") or 0 for r in rs]
        lat = [r["latency_ms"] for r in rs]
        table[f"{lane}/{purpose}"] = {"n": len(rs), "per_min": round(len(rs) / minutes, 1),
                                      "wait_p50_s": round(pct(q, 50) / 1000, 2), "wait_p90_s": round(pct(q, 90) / 1000, 2),
                                      "wait_p99_s": round(pct(q, 99) / 1000, 2), "wait_mean_s": round(sum(q) / len(q) / 1000, 2),
                                      "latency_p50_s": round(pct(lat, 50) / 1000, 2), "latency_p90_s": round(pct(lat, 90) / 1000, 2)}
    by_profile = defaultdict(lambda: [0, 0])
    for r in win:
        if r.get("error"):
            continue
        by_profile[r.get("profile")][0] += 1
        by_profile[r.get("profile")][1] += (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0)
    throughput = {p: {"calls_per_min": round(n / minutes, 1), "mtok_per_min": round(t / minutes / 1e6, 2)} for p, (n, t) in by_profile.items()}
    # In flight and waiting, sampled each second of the window.
    inflight, waiting = [], []
    marks = sorted([(r["send"], 1, 0) for r in rows] + [(r["end"], -1, 0) for r in rows]
                   + [(r["enq"], 0, 1) for r in rows] + [(r["send"], 0, -1) for r in rows])
    i = n_in = n_wait = 0
    for t in range(int(t0), int(t1), 1000):
        while i < len(marks) and marks[i][0] <= t:
            n_in += marks[i][1]
            n_wait += marks[i][2]
            i += 1
        inflight.append(n_in)
        waiting.append(n_wait)
    errors = Counter((r["purpose"], str(r["error"])[:60]) for r in win if r.get("error"))
    purposes = Counter(r["purpose"] for r in win if not r.get("error"))
    out = {"window_ms": [int(t0), int(t1)], "window_min": round(minutes, 2), "calls": len(win), "errors": sum(errors.values()), "error_kinds": dict(errors.most_common(5)),
           "lanes": table, "throughput": throughput,
           "in_flight": {"mean": round(sum(inflight) / max(1, len(inflight)), 1), "p90": pct(inflight, 90), "max": max(inflight, default=0)},
           "waiting": {"mean": round(sum(waiting) / max(1, len(waiting)), 1), "p90": pct(waiting, 90), "max": max(waiting, default=0)}}
    if a.minds:
        out["per_mind_hour"] = {p: round(n / a.minds / minutes * 60, 2) for p, n in sorted(purposes.items())}
        out["per_mind_hour"]["all"] = round(sum(purposes.values()) / a.minds / minutes * 60, 2)
    if a.proc and Path(a.proc).exists():
        ps = [json.loads(l) for l in open(a.proc) if l.strip()]
        ps = [p for p in ps if "mind" in p and t0 / 1000 <= p["t"] < t1 / 1000]
        if len(ps) >= 2:
            dt = ps[-1]["t"] - ps[0]["t"]
            out["mind_proc"] = {"cpu_cores_mean": round((ps[-1]["mind"]["cpu_s"] - ps[0]["mind"]["cpu_s"]) / dt, 3),
                                "rss_mb_mean": round(sum(p["mind"]["rss_kb"] for p in ps) / len(ps) / 1024, 1),
                                "rss_mb_max": round(max(p["mind"]["rss_kb"] for p in ps) / 1024, 1),
                                "threads_max": max(p["mind"]["threads"] for p in ps),
                                "load_max": max(float(p["load"][0]) for p in ps)}
            fk = [p for p in ps if "fake" in p]
            if len(fk) >= 2:
                out["fake_proc"] = {"cpu_cores_mean": round((fk[-1]["fake"]["cpu_s"] - fk[0]["fake"]["cpu_s"]) / (fk[-1]["t"] - fk[0]["t"]), 3),
                                    "rss_mb_max": round(max(p["fake"]["rss_kb"] for p in fk) / 1024, 1)}
    text = json.dumps(out, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("samples")
    p.add_argument("--journal", action="append", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(f=samples)
    p = sub.add_parser("script")
    p.add_argument("--samples", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limits-scale", type=float, default=1.0)
    p.set_defaults(f=script)
    p = sub.add_parser("proc")
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fake-match", help="text in the fake server's command line (its log's directory)")
    p.add_argument("--every", type=float, default=2)
    p.add_argument("--wait-s", type=float, default=900, help="how long to wait for the mind to start")
    p.set_defaults(f=proc)
    p = sub.add_parser("report")
    p.add_argument("--journal", action="append", required=True)
    p.add_argument("--from-ms", type=int)
    p.add_argument("--to-ms", type=int)
    p.add_argument("--skip-s", type=float, default=0, help="seconds after the start (or --from-ms) left out: the fill")
    p.add_argument("--minds", type=int)
    p.add_argument("--proc")
    p.add_argument("--json")
    p.set_defaults(f=report)
    a = ap.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
