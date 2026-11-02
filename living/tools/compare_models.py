#!/usr/bin/env python3
"""Compare people's behavior by the model their mind runs on (from one lab's journal and
database): calls and latency, what they decide (acts by kind), how much they say and how
often they repeat themselves, and how they fare (hunger now, deaths, children, teaching).

  living/tools/compare_models.py stage1-wolves [--run <journal run dir name>] [--since-min 0]
"""
import argparse
import collections
import glob
import json
import re
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, l.split("|"))} for l in lines[1:]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--run")
    ap.add_argument("--since-min", type=float, default=0, help="only journal entries from the last N minutes (0 = all)")
    a = ap.parse_args()
    scenario = {"living": "stage1-base"}.get(a.db, a.db)
    run = ROOT / ".local/living/journal" / (a.run or sorted(p.name for p in (ROOT / ".local/living/journal").glob(f"{scenario}-*"))[-1])
    people = {c["name"]: c for c in rows(a.db, "SELECT id, name, kind, alive, cause, stage FROM character") if c["kind"] == "person"}
    model_of = {}
    stats = collections.defaultdict(lambda: {"calls": 0, "errors": 0, "lat": [], "tokens": 0, "acts": collections.Counter(), "thinks": 0})
    newest = 0
    entries = []
    for f in glob.glob(str(run / "*.jsonl")):
        name = Path(f).stem
        if name not in people:
            continue
        for l in open(f):
            r = json.loads(l)
            entries.append((name, r))
            newest = max(newest, r.get("at_ms", 0))
    cutoff = newest - a.since_min * 60_000 if a.since_min else 0
    for name, r in entries:
        if r.get("at_ms", 0) < cutoff:
            continue
        m = r.get("profile") or r.get("model")
        if r.get("purpose") in ("think", "deliberate", "talk"):
            model_of.setdefault(name, collections.Counter())[m] += 1
        s = stats[(name, m)]
        s["calls"] += 1
        s["errors"] += bool(r.get("error"))
        s["lat"].append(r.get("latency_ms") or 0)
        s["tokens"] += r.get("tokens") or 0
        if r.get("purpose") == "think":
            s["thinks"] += 1
        rep = r.get("reply") or ""
        try:
            v = json.loads(rep[rep.find("{"): rep.rfind("}") + 1])
        except ValueError:
            v = {}
        for act in v.get("acts") or []:
            if isinstance(act, dict):
                s["acts"][act.get("do")] += 1
    who = {n: c.most_common(1)[0][0] for n, c in model_of.items()}
    speech = collections.Counter()
    lines = collections.defaultdict(list)
    for r in rows(a.db, "SELECT kind, text FROM chronicle"):
        if r["kind"] != "speech":
            continue
        m = re.match(r"([A-Z][a-z]+)( to [A-Z][a-z]+)?: “(.*)", r["text"])
        if m:
            speech[m.group(1)] += 1
            lines[m.group(1)].append(m.group(3)[:80])
    hunger = {r["id"]: float(r["hunger"]) for r in rows(a.db, "SELECT id, hunger FROM vitals")}
    kids = collections.Counter()
    for c in rows(a.db, "SELECT parent_a, parent_b FROM character WHERE kind = 'person'"):
        for p in (c["parent_a"], c["parent_b"]):
            kids[p] += 1
    taught = collections.Counter(re.match(r"([A-Z][a-z]+) taught", r["text"]).group(1) for r in rows(a.db, "SELECT kind, text FROM chronicle") if r["kind"] == "teach" and re.match(r"([A-Z][a-z]+) taught", r["text"]))
    groups = collections.defaultdict(list)
    for n, m in who.items():
        groups[m].append(n)
    print(f"{a.db} ({run.name}){f', last {a.since_min:.0f} min' if a.since_min else ''}")
    for m, names in sorted(groups.items()):
        s = [stats[(n, m)] for n in names]
        lat = [x for st in s for x in st["lat"]]
        acts = sum((st["acts"] for st in s), collections.Counter())
        repeats = sum(sum(1 for _, k in collections.Counter(lines[n]).items() if k >= 3) for n in names)
        alive = [n for n in names if people[n]["alive"] == "true"]
        print(f"== {m}: {len(names)} people ({len(alive)} alive): {', '.join(sorted(names))}")
        print(f"   calls {sum(st['calls'] for st in s)}, thinks {sum(st['thinks'] for st in s)}, errors {sum(st['errors'] for st in s)}, latency p50 {statistics.median(lat) if lat else 0:.0f} ms, tokens {sum(st['tokens'] for st in s)}")
        print(f"   acts: {dict(acts.most_common(10))}")
        print(f"   speech lines {sum(speech[n] for n in names)} (per person {sum(speech[n] for n in names) / max(1, len(names)):.0f}), lines said 3+ times {repeats}")
        print(f"   hunger now (alive): {[round(hunger.get(people[n]['id'], 0)) for n in alive]}; deaths: {[people[n]['cause'] for n in names if people[n]['alive'] == 'false']}")
        print(f"   children: {sum(kids[people[n]['id']] for n in names)}; taught: {sum(taught[n] for n in names)}")


if __name__ == "__main__":
    main()
