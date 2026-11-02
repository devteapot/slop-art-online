#!/usr/bin/env python3
"""How people move: sampled positions over a window.

Reports the share of people who moved, who stayed still, who flickered (reversed direction
three or more times), distance from home (median, and who is far away exploring), and
people from different groups within earshot of each other (group = the town, village or
band in their background, else their community).

Usage: living/tools/movement.py [--db living] [--seconds 30] [--far 40]
"""
import argparse
import collections
import json
import math
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, [v.strip() for v in l.split("|")])} for l in lines[1:]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--far", type=float, default=40.0)
    a = ap.parse_args()
    people = {r["id"]: r for r in rows(a.db, "SELECT id, name, home_x, home_y FROM character WHERE kind = 'person' AND alive = true")}
    group = {}
    for r in rows(a.db, "SELECT id, text FROM background"):
        try:
            bg = json.loads(r["text"].replace('\\"', '"'))
            group[r["id"]] = bg.get("town") or bg.get("band")
        except ValueError:
            pass
    comm = {r["id"]: r["name"] for r in rows(a.db, "SELECT id, name FROM community")}
    for m in rows(a.db, "SELECT community, member FROM membership"):
        group.setdefault(m["member"], comm.get(m["community"]))
    tracks = collections.defaultdict(list)
    for _ in range(a.seconds):
        now = time.time() * 1000
        for b in rows(a.db, "SELECT id, x, y, vx, vy, t_ms FROM body"):
            if b["id"] in people:
                dt = (now - float(b["t_ms"])) / 1000
                tracks[b["id"]].append((float(b["x"]) + float(b["vx"]) * dt, float(b["y"]) + float(b["vy"]) * dt))
        time.sleep(1)
    moved = still = flicker = 0
    home_d = []
    far = []
    for pid, tr in tracks.items():
        span = max(math.dist(p, tr[0]) for p in tr)
        if span < 0.5:
            still += 1
        else:
            moved += 1
        steps = [(b[0] - a_[0], b[1] - a_[1]) for a_, b in zip(tr, tr[1:])]
        rev = sum(1 for s1, s2 in zip(steps, steps[1:]) if s1[0] * s2[0] + s1[1] * s2[1] < -0.01)
        if rev >= 3 and span < 6:
            flicker += 1
        p = people[pid]
        d = math.dist(tr[-1], (float(p["home_x"]), float(p["home_y"])))
        home_d.append(d)
        if d > a.far:
            far.append(f'{p["name"]} ({group.get(pid, "?")}) {d:.0f} tiles from home')
    last = {pid: tr[-1] for pid, tr in tracks.items()}
    contacts = set()
    ids = list(last)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            gx, gy = group.get(x), group.get(y)
            if gx and gy and gx != gy and math.dist(last[x], last[y]) <= 9:
                contacts.add(f'{people[x]["name"]} ({gx}) and {people[y]["name"]} ({gy})')
    report = {
        "people": len(tracks),
        "moved": moved,
        "still": still,
        "flickering": flicker,
        "median_tiles_from_home": round(statistics.median(home_d), 1) if home_d else None,
        "far_from_home": far,
        "cross_group_within_earshot": sorted(contacts),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
