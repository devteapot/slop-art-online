#!/usr/bin/env python3
"""Model load per person from a run's mind journal, extrapolated to a larger population, and
replayed under the off-stage level of detail (see docs/LIVING_CORE.md, "Minds at scale").

Usage: living/tools/mind_load.py <db> <run> [--minutes 60] [--people 2000]
                                 [--think-s 600] [--prompt-s 120] [--consolidate-s 900] [--talk-s 120]

Reads `.local/living/journal/<run>/*.jsonl` (purpose, tokens, latency_ms, at_ms, the exact
request) and the database's `character` table (read-only) to tell people from animals by
name. The replay assumes nobody is on stage (no human player anywhere), the case of a large
world with few players: a routine reason is taken only when the gap since the person's last
thought has passed, a prompt one (other bodily alarms, calls of one's kind) after the
shorter gap, an urgent one (attacked, fight, starving, badly hurt, being asked) at once.
It counts calls; waiting requests that merge several reasons into one are counted once.
"""
import argparse
import glob
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = os.environ.get("LIVING_STDB", str(ROOT / "living/tools/stdb"))
NOW = re.compile(r"is attacking you|The fight with|Your body: You are starving|Your body: You are badly hurt|offers you|asks to join|asks to start a family with you|asked to start a family with you")
PROMPT = re.compile(r"^Your body:|gave .+\)\.$")


def characters(db):
    out = subprocess.run([STDB, "sql", "-s", "local", db, "SELECT name, kind, alive FROM character"], capture_output=True, text=True).stdout
    rows = [l.split("|") for l in out.splitlines() if "|" in l and not l.strip().startswith("-")][1:]
    kinds = defaultdict(set)
    alive = 0
    for r in rows:
        name, kind, live = (x.strip().strip('"') for x in r)
        kinds[name].add(kind)
        alive += kind == "person" and live == "true"
    return {n for n, k in kinds.items() if k == {"person"}}, alive


def urgency(request):
    msgs = (request or {}).get("messages", [])
    user = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
    m = re.search(r"# Why you are thinking now\n(.*?)\n\n", user, re.S)
    lines = [x.strip() for x in (m.group(1) if m else "").split("\n") if x.strip()]
    if any(NOW.search(x) for x in lines):
        return 2
    if any(PROMPT.search(x) for x in lines):
        return 1
    return 0


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("run")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--people", type=int, default=2000)
    ap.add_argument("--think-s", type=float, default=600)
    ap.add_argument("--prompt-s", type=float, default=120)
    ap.add_argument("--consolidate-s", type=float, default=900)
    ap.add_argument("--talk-s", type=float, default=120)
    a = ap.parse_args()
    people, alive = characters(a.db)
    recs = []
    for f in glob.glob(str(ROOT / ".local/living/journal" / a.run / "*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("actor") in people:
                recs.append(r)
    if not recs:
        raise SystemExit("no person calls in that journal")
    end = max(r["at_ms"] for r in recs)
    recs = [r for r in recs if r["at_ms"] >= end - a.minutes * 60000]
    span = (end - min(r["at_ms"] for r in recs)) / 60000
    n = len({r["actor"] for r in recs})
    by = defaultdict(lambda: {"calls": 0, "tokens": 0, "lat": []})
    per_actor = defaultdict(list)
    for r in recs:
        b = by[r.get("purpose")]
        b["calls"] += 1
        b["tokens"] += r.get("tokens") or 0
        b["lat"].append(r.get("latency_ms") or 0)
        per_actor[r["actor"]].append((r["at_ms"], r.get("purpose"), urgency(r.get("request")) if r.get("purpose") == "think" else 0))
    # Replay under the off-stage level of detail.
    kept = defaultdict(int)
    gap = {"think": a.think_s, "consolidate": a.consolidate_s, "talk": a.talk_s}
    for xs in per_actor.values():
        xs.sort()
        last = {}
        for at, p, urg in xs:
            if p == "deliberate":
                continue
            g = gap.get(p)
            if p == "think":
                g = 0 if urg == 2 else (a.prompt_s if urg == 1 else a.think_s)
            if g is None or p not in last or at - last[p] >= g * 1000:
                kept[p] += 1
                last[p] = at
    kept["deliberate"] = kept["think"]
    print(f"{a.db} / {a.run}: {n} people over {span:.1f} min ({alive} alive now)")
    print(f"{'purpose':12s} {'calls/person/min':>16s} {'tokens/call':>11s} {'tokens/person/min':>17s} {'p50 s':>6s} {'p95 s':>6s} {'off stage calls/person/min':>27s}")
    tc = tt = kc = kt = 0.0
    for p, b in sorted(by.items()):
        cpm = b["calls"] / span / n
        tpc = b["tokens"] / b["calls"]
        k = kept[p] / span / n
        tc, tt, kc, kt = tc + cpm, tt + cpm * tpc, kc + k, kt + k * tpc
        print(f"{p:12s} {cpm:16.3f} {tpc:11.0f} {cpm * tpc:17.0f} {pct(b['lat'], 50) / 1000:6.1f} {pct(b['lat'], 95) / 1000:6.1f} {k:27.3f}")
    print(f"{'all':12s} {tc:16.3f} {'':11s} {tt:17.0f} {'':6s} {'':6s} {kc:27.3f}")
    mean_lat = sum(sum(b["lat"]) for b in by.values()) / sum(b["calls"] for b in by.values()) / 1000
    for label, c, t in (("as measured", tc, tt), ("all off stage", kc, kt)):
        calls = c * a.people
        print(f"{a.people} people, {label}: {calls:,.0f} calls/min ({calls / 60:,.1f}/s), {t * a.people / 1e6:,.1f}M tokens/min, "
              f"~{calls / 60 * mean_lat:,.0f} calls in flight at the measured mean latency {mean_lat:.1f} s")


if __name__ == "__main__":
    main()
