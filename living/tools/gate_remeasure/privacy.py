#!/usr/bin/env python3
"""RELAY_PROTOTYPE's privacy check: every item a relay client received was, at the authority
transaction it came from, about a creature in that viewer's authority-written set (or, for a fight
event, its actor or target was, or the viewer's own character took part). Uses the checker's log
(set changes by transaction) and the clients' item log. Prints counts; exits 1 on any violation.
    privacy.py RUN_DIR"""
import bisect
import json
import sys
from collections import defaultdict
from pathlib import Path

run = Path(sys.argv[1])
ids = json.loads((run / "relay-ids.json").read_text())
hist = defaultdict(lambda: defaultdict(list))  # viewer -> body -> [(tx, present)]
chars = defaultdict(list)  # viewer -> [(tx, character)]
for line in open(run / "checker.log"):
    t, i, op, v, x = line.split()
    tx = (int(t), int(i))
    if op == "P":
        chars[v].append((tx, int(x)))
    else:
        hist[v][int(x)].append((tx, op == "+"))


def member(v, b, tx):
    h = hist[v].get(b)
    if not h:
        return False
    k = bisect.bisect_right(h, (tx, True))
    return k > 0 and h[k - 1][1]


def own(v, tx):
    c = [ch for (t, ch) in chars[v] if t <= tx]
    return c[-1] if c else None


n = bad = early = 0
kinds = defaultdict(int)
examples = []
for line in open(run / "clients.json.items"):
    i, t, idx, k, a, b = line.split()
    v, tx, k, a, b = ids[int(i)], (int(t), int(idx)), int(k), int(a), int(b)
    if tx[0] == 0:
        early += 1
        continue
    kinds[k] += 1
    if k in (4, 6):  # "gone" and hearing buckets name no one outside the set
        continue
    n += 1
    ok = (member(v, a, tx) or member(v, b, tx) or own(v, tx) in (a, b)) if k == 5 else member(v, a, tx)
    if not ok:
        bad += 1
        if len(examples) < 5:
            examples.append({"viewer": v[:16], "tx": tx, "kind": k, "body": a})
print(json.dumps({"checked": n, "violations": bad, "before_first_tick": early, "by_kind": dict(kinds), "examples": examples}))
sys.exit(1 if bad else 0)
