#!/usr/bin/env python3
"""Other processes' CPU in a run's window: host busy cores (runners.log, /proc/stat every 2 s) minus our
own (cores.jsonl: server + gate-load/relay/driver threads). Usage: others.py RUN_DIR RUNNERS_LOG"""
import json, sys
from pathlib import Path
d = Path(sys.argv[1]); w = json.loads((d / "battle-viewers.json").read_text())["rows"][0]["window"]
ours = {}
for l in open(d / "cores.jsonl"):
    r = json.loads(l); ours[round(r["t"])] = sum(t["ms"] for t in r["threads"]) / 1000
rl = [l.split() for l in open(sys.argv[2])]
rows = []
for a, b in zip(rl, rl[1:]):
    t0, t1 = float(a[0]), float(b[0])
    if not (w["t0"] - 10 <= t0 and t1 <= w["t1"]):
        continue
    busy = (int(b[1]) - int(a[1])) / 100 / (t1 - t0)
    own = sum(ours.get(s, 0) for s in range(round(t0) + 1, round(t1) + 1)) / max(1, round(t1) - round(t0))
    rows.append((round(t0 - w["t0"]), round(busy, 2), round(own, 2), round(busy - own, 2)))
oth = [r[3] for r in rows if r[0] >= 0]
print(json.dumps({"others_cores_mean": round(sum(oth) / len(oth), 2), "others_cores_max": max(oth), "samples": rows}))
