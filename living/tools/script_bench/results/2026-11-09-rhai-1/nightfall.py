#!/usr/bin/env python3
"""Tick cost around nightfall on a fresh scratch world: the evidence behind docs/SCRIPT_ENGINES.md
("What changed on rhai-1", item 4). Run it only against a private server and a verify-* database.

  nightfall.py --db verify-rhai-a --wasm base_island.wasm --out a.json [--battle 0]

Publishes the module fresh (the world starts at 07:00 with a 12-minute day, so night falls at
20:00, 6.5 minutes in), turns profiling on 25 s before nightfall and off 35 s after, and reports
per-second tick p50/max and the `needs.rates` span (rates recomputes: count and ms) relative to
the moment night fell. Uses LIVING_STDB for the CLI wrapper.
"""
import argparse, json, os, re, subprocess, time
from datetime import datetime, timezone

STDB = os.environ["LIVING_STDB"]
DAY_MS = 12 * 60 * 1000


def stdb(*a, check=True):
    r = subprocess.run([STDB, *a], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"stdb {' '.join(a[:3])}: {r.stderr[-2000:]}")
    return r.stdout


def sql1(db, q):
    lines = [l for l in stdb("sql", "-s", "local", db, q).splitlines() if l.strip() and not l.strip().startswith("-")]
    return [v.strip() for v in lines[1].split("|")]


ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--wasm", required=True)
ap.add_argument("--battle", type=int, default=0)
ap.add_argument("--out", required=True)
a = ap.parse_args()
stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", a.db, "--delete-data", "-y")
epoch_ms, day_ms = (int(x) for x in sql1(a.db, "SELECT epoch_ms, day_ms FROM world"))
# Hour 20 is 13 hours after the 07:00 start.
night_ms = epoch_ms + day_ms * 13 // 24
if a.battle:
    stdb("call", "-s", "local", a.db, "spawn_battle", str(a.battle))
wait = night_ms / 1000 - 25 - time.time()
print(f"night falls in {night_ms / 1000 - time.time():.0f} s; profiling from {wait:.0f} s", flush=True)
time.sleep(max(0, wait))
load0 = os.getloadavg()
stdb("call", "-s", "local", a.db, "set_profile", "true")
time.sleep(max(0, night_ms / 1000 + 35 - time.time()))
stdb("call", "-s", "local", a.db, "set_profile", "false")
load1 = os.getloadavg()
people = sql1(a.db, "SELECT alive_people, alive_animals FROM stats")
logs = stdb("logs", "-s", "local", a.db, "-n", "400000")
per = {}
for m in re.finditer(r'^(\S+Z)\s.*Timing span "([^"]+)": ([\d.]+)(µs|ms|s)\b', logs, re.M):
    stamp = m.group(1)[:26].rstrip("Z")
    at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    sec = int((at * 1000 - night_ms) // 1000)
    if not -25 <= sec <= 34:
        continue
    d = float(m.group(3)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[m.group(4)]
    per.setdefault(sec, {}).setdefault(m.group(2), []).append(d)
rows = []
for sec in sorted(per):
    t = sorted(per[sec].get("tick", []))
    n = per[sec].get("needs.rates", [])
    rows.append({"s": sec, "ticks": len(t), "tick_p50": round(t[len(t) // 2], 3) if t else None, "tick_max": round(t[-1], 3) if t else None,
                 "rates_n": len(n), "rates_ms": round(sum(n), 3), "rates_max": round(max(n), 3) if n else None})
before = [r for r in rows if r["s"] < 0]
after = [r for r in rows if 0 <= r["s"] < 5]
summary = {
    "db": a.db, "wasm": a.wasm, "battle": a.battle, "people_animals": people, "load_before_after": [load0, load1],
    "before_night": {"tick_max": max(r["tick_max"] or 0 for r in before), "rates_per_s": round(sum(r["rates_n"] for r in before) / max(len(before), 1), 1), "rates_ms_per_s": round(sum(r["rates_ms"] for r in before) / max(len(before), 1), 2)},
    "first_5_s_of_night": {"tick_max": max(r["tick_max"] or 0 for r in after), "rates": sum(r["rates_n"] for r in after), "rates_ms": round(sum(r["rates_ms"] for r in after), 2)},
    "per_second": rows,
}
open(a.out, "w").write(json.dumps(summary, indent=1) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "per_second"}, indent=1))
for r in rows:
    if -3 <= r["s"] <= 6:
        print(r)
