#!/usr/bin/env python3
"""Stage 1 at a glance: population timeline per species (births and deaths by cause per
window), people's generations and a few of the stage's criteria, from one lab database.

  living/tools/stage1_report.py living stage1-wolves stage1-scarce [--window 10]
"""
import argparse
import collections
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


def report(db, window_min):
    chars = rows(db, "SELECT id, kind, alive, born_ms, died_ms, cause, parent_a, parent_b, stage FROM character")
    if not chars:
        print(f"== {db}: unreachable or empty")
        return
    t0 = min(int(c["born_ms"]) for c in chars)
    now = max([int(c["born_ms"]) for c in chars] + [int(c["died_ms"] or 0) for c in chars])
    w = window_min * 60_000
    print(f"== {db}  ({(now - t0) / 60000:.0f} min)")
    for kind in ("person", "deer", "wolf"):
        cs = [c for c in chars if c["kind"] == kind]
        alive = sum(1 for c in cs if c["alive"] == "true")
        line = []
        for k in range(int((now - t0) / w) + 1):
            a, b = t0 + k * w, t0 + (k + 1) * w
            born = sum(1 for c in cs if c["parent_a"] != "0" and int(c["born_ms"]) > t0 + 60_000 and a <= int(c["born_ms"]) < b)
            died = collections.Counter(
                ("killed" if c["cause"].startswith("killed") else c["cause"]) for c in cs if c["alive"] == "false" and a <= int(c["died_ms"] or 0) < b
            )
            line.append(f"+{born}/-{sum(died.values())}")
        causes = collections.Counter(("killed" if c["cause"].startswith("killed") else c["cause"]) for c in cs if c["alive"] == "false")
        print(f"  {kind:6s} alive {alive:3d}  per {window_min} min (born/died): {' '.join(line)}")
        print(f"         deaths: {dict(causes.most_common())}")
    people = {c["id"]: c for c in chars if c["kind"] == "person"}

    def gen(i, seen=()):
        c = people.get(i)
        if not c or c["parent_a"] == "0" or i in seen:
            return 1
        return 1 + max(gen(c["parent_a"], seen + (i,)), gen(c["parent_b"], seen + (i,)))

    born_here = [i for i, c in people.items() if c["parent_a"] != "0" and int(c["born_ms"]) > t0 + 60_000]
    gens = collections.Counter(gen(i) for i, c in people.items() if c["alive"] == "true")
    print(f"  people born in the world: {len(born_here)}; generations alive: {dict(sorted(gens.items()))}; deepest: {max((gen(i) for i in people), default=0)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dbs", nargs="+")
    ap.add_argument("--window", type=int, default=10)
    a = ap.parse_args()
    for db in a.dbs:
        report(db, a.window)


if __name__ == "__main__":
    main()
