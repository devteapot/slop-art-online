#!/usr/bin/env python3
"""A world's pulse over time: one snapshot per interval, appended to a JSONL file, so long
runs can be read as trends (population, hunger, wildlife, talk, model load) instead of
single reports.

Each snapshot records, for the last interval:
- people alive, born and dead (with causes) in all, hunger by settlement (mean, starving);
- deer and wolves alive;
- speech lines per person per minute and the share mentioning babies;
- model calls per minute (by purpose and model), the share that errored, tokens per minute.

Usage:
  living/tools/pulse.py <db> <run> [--every 900] [--once]   # record (loops until the world pauses)
  living/tools/pulse.py <db> --show                          # print the trend table
Output: .local/living/pulse/<db>.jsonl
"""
import argparse
import collections
import glob
import gzip
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
BABY = re.compile(r"\b(baby|babies|infant|little one)\b", re.I)


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [dict(zip(head, [v.strip().strip('"') for v in l.split("|")])) for l in lines[1:]]


def journal(run, since_ms):
    for f in glob.glob(str(ROOT / ".local/living/journal" / run / "*.jsonl*")):
        with (gzip.open(f, "rt") if f.endswith(".gz") else open(f)) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("at_ms", 0) >= since_ms:
                    yield d


def snapshot(db, run, window_s):
    now = time.time() * 1000
    since = now - window_s * 1000
    town = {}
    for b in rows(db, "SELECT id, text FROM background"):
        m = re.search(r'town\\?":\\?"([^"\\]+)', b["text"])
        town[b["id"]] = m.group(1) if m else "?"
    chars = rows(db, "SELECT id, kind, alive, cause, born_ms, died_ms, parent_a FROM character")
    people = [c for c in chars if c["kind"] == "person"]
    group = {}
    for c in sorted(people, key=lambda c: int(c["id"])):
        group[c["id"]] = town.get(c["id"]) or group.get(c["parent_a"], "?")
    vit = {v["id"]: v for v in rows(db, "SELECT id, hunger, hunger_rate, at_ms FROM vitals")}
    hunger = collections.defaultdict(list)
    for c in people:
        v = vit.get(c["id"])
        if c["alive"] == "true" and v:
            hunger[group[c["id"]]].append(min(100.0, float(v["hunger"]) + float(v["hunger_rate"]) * (now - float(v["at_ms"])) / 60000))
    alive = [c for c in people if c["alive"] == "true"]
    speech = [s["text"] for s in rows(db, "SELECT text, at_ms FROM chronicle WHERE kind = 'speech'") if float(s["at_ms"]) >= since]
    calls, err, tokens = collections.Counter(), 0, 0
    for d in journal(run, since):
        calls[(d["purpose"], d["model"])] += 1
        err += bool(d.get("error"))
        tokens += d.get("tokens") or 0
    n = sum(calls.values())
    mins = window_s / 60
    return {
        "t": time.strftime("%Y-%m-%d %H:%M"),
        "people": len(alive),
        "born": sum(1 for c in people if c["parent_a"] != "0" and int(c["born_ms"]) > 0 and c["id"] not in town),
        "dead": collections.Counter(c["cause"] for c in people if c["alive"] == "false"),
        "hunger": {t: {"mean": round(sum(h) / len(h)), "starving": sum(1 for x in h if x >= 90)} for t, h in sorted(hunger.items())},
        "deer": sum(1 for c in chars if c["kind"] == "deer" and c["alive"] == "true"),
        "wolves": sum(1 for c in chars if c["kind"] == "wolf" and c["alive"] == "true"),
        "speech_per_person_min": round(len(speech) / max(1, len(alive)) / mins, 2),
        "baby_talk": round(sum(1 for s in speech if BABY.search(s)) / max(1, len(speech)), 2),
        "calls_per_min": round(n / mins),
        "calls_by_purpose": {p: round(sum(v for (pp, _), v in calls.items() if pp == p) / mins) for p in sorted({p for p, _ in calls})},
        "calls_by_model": {m: round(sum(v for (_, mm), v in calls.items() if mm == m) / mins) for m in sorted({m for _, m in calls})},
        "error_share": round(err / max(1, n), 3),
        "tokens_per_min": round(tokens / mins),
    }


def show(db):
    f = ROOT / ".local/living/pulse" / f"{db}.jsonl"
    snaps = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    print(f"{'time':16s} {'ppl':>4s} {'dead':>4s} {'hunger by settlement (mean/starving)':44s} {'deer':>4s} {'wolf':>4s} {'talk':>5s} {'baby':>5s} {'calls':>6s} {'err':>5s} {'Mtok':>5s}")
    for s in snaps:
        h = " ".join(f"{k[:5]}:{v['mean']}/{v['starving']}" for k, v in s["hunger"].items())
        print(f"{s['t']:16s} {s['people']:4d} {sum(s['dead'].values()):4d} {h:44s} {s['deer']:4d} {s['wolves']:4d} {s['speech_per_person_min']:5.2f} {s['baby_talk']:5.2f} {s['calls_per_min']:6d} {s['error_share']:5.2f} {s['tokens_per_min'] / 1e6:5.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("run", nargs="?")
    ap.add_argument("--every", type=int, default=900)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.show:
        return show(a.db)
    out = ROOT / ".local/living/pulse" / f"{a.db}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    while True:
        s = snapshot(a.db, a.run, a.every)
        with open(out, "a") as fh:
            fh.write(json.dumps(s) + "\n")
        print(json.dumps(s), flush=True)
        paused = rows(a.db, "SELECT paused, run FROM world")
        if a.once or (paused and paused[0].get("paused") == "true"):
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
