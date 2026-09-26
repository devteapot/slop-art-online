#!/usr/bin/env python3
"""Measure the living authority's tick cost and cadence on a benchmark database.

Usage: living/tools/bench.py [--db living-bench] [--seconds 60] [--crowd N] [--fresh]

--fresh republishes the database from the seed (deletes its data); --crowd adds N
instinct-driven people (no LLM). Tick durations come from the module's LogStopwatch
(enabled only during the window); cadence and work counters from the `stats` row.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")


def stdb(*args, check=True):
    r = subprocess.run([STDB, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"stdb {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def stats(db):
    out = stdb("sql", "-s", "local", db, "SELECT * FROM stats")
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    head = [h.strip() for h in lines[0].split("|")]
    vals = [v.strip() for v in lines[1].split("|")]
    return {h: int(v) for h, v in zip(head, vals) if v.isdigit()}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living-bench")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--crowd", type=int, default=0)
    ap.add_argument("--minded", action="store_true", help="crowd produces experiences and deliberation requests like LLM characters")
    ap.add_argument("--battle", type=int, default=0, help="add N spear fighters packed in one locality")
    ap.add_argument("--subscribe", action="store_true", help="attach a live subscriber to all admin-controlled experiences")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--settle", type=int, default=5)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.fresh:
        stdb("publish", "-s", "local", "-b", "/wasm/living_authority.wasm", a.db, "--delete-data", "-y")
    if a.crowd:
        stdb("call", "-s", "local", a.db, "spawn_crowd", str(a.crowd), "true" if a.minded else "false")
    if a.battle:
        stdb("call", "-s", "local", a.db, "spawn_battle", str(a.battle))
    sub = None
    if a.subscribe:
        admin = stdb("sql", "-s", "local", a.db, "SELECT admin FROM world").strip().splitlines()[-1].strip()
        sub = subprocess.Popen([STDB, "subscribe", "-s", "local", a.db, f"SELECT * FROM experience WHERE controller = {admin}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(a.settle + 1.2)
    s0, t0 = stats(a.db), time.time()
    stdb("call", "-s", "local", a.db, "set_profile", "true")
    time.sleep(a.seconds)
    stdb("call", "-s", "local", a.db, "set_profile", "false")
    s1, t1 = stats(a.db), time.time()
    if sub:
        sub.terminate()
    logs = stdb("logs", "-s", "local", a.db, "-n", str(a.seconds * 70 + 500))
    durs = []
    for m in re.finditer(r'^(\S+Z)\s.*Timing span "tick": ([\d.]+)(µs|ms|s)\b', logs, re.M):
        at = datetime.strptime(m.group(1)[:26].rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
        if at < t0 - 1:
            continue
        durs.append(float(m.group(2)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[m.group(3)])
    dt = t1 - t0
    rate = lambda k: round((s1[k] - s0[k]) / dt, 1)
    report = {
        "db": a.db,
        "seconds": round(dt, 1),
        "people": s1["alive_people"],
        "animals": s1["alive_animals"],
        "ticks_per_s": rate("ticks"),
        "evals_per_s": rate("evals"),
        "motions_per_s": rate("motions"),
        "completions_per_s": rate("completions"),
        "experiences_per_s": rate("percepts"),
        "deliberation_requests_per_s": rate("deliberations"),
        "max_tick_gap_ms_last_s": s1["max_tick_gap_ms"],
        "combat": {"hits": s1.get("hits", 0) - s0.get("hits", 0), "dodged": s1.get("dodged", 0) - s0.get("dodged", 0), "blocked": s1.get("blocked", 0) - s0.get("blocked", 0), "people_left": s1["alive_people"]},
        "tick_ms": {
            "samples": len(durs),
            "p50": round(pct(durs, 50), 3),
            "p95": round(pct(durs, 95), 3),
            "p99": round(pct(durs, 99), 3),
            "max": round(max(durs, default=0), 3),
            "over_16_7ms": sum(d > 16.667 for d in durs),
        },
    }
    print(json.dumps(report, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
