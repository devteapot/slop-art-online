#!/usr/bin/env python3
"""Read-only density analysis for docs/ATTENTION_BUDGET.md.

Given a saved battle run directory (a verify-minds or trials run with `combat-samples.jsonl.gz`,
`measure-start-ms.txt` and `journal/*.jsonl`), print:

- how many others stand within 3, 8, 20 and 48 m of each fighter (distance only: no facing, cover
  or light, so an upper bound on what is in sight), and how many open attacks aim at it;
- with an attention budget of N, how many are left over as crowd, and how many crowd cells they
  fill at each cell size (world-aligned square cells);
- what the minds' think prompts listed under "What you perceive right now": creatures listed,
  scene characters, and the size of a compact per-creature entry (the shape an attention state
  would send).

Every 5th sample from minute 2 on (the act trial's measured window). Reads files only.

    python3 -I living/tools/attention_density.py RUN_DIR [--n 16] [--cells 4,6,8]
"""

import argparse
import glob
import gzip
import json
import math
import os


def q(v):
    v = sorted(v)
    if not v:
        return "n=0"
    return f"p10={v[len(v) // 10]} p50={v[len(v) // 2]} p90={v[9 * len(v) // 10]} max={v[-1]} (n={len(v)})"


def positions(e):
    t = e["at_ms"]
    pos = {}
    for b in e["bodies"]:
        end = b["next_ms"] if b["next_ms"] < 1e18 else t
        dt = max(0, min(t, end) - b["t_ms"]) / 1000
        pos[b["id"]] = (b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt)
    return pos


def density(run, n, cells):
    start = int(open(os.path.join(run, "measure-start-ms.txt")).read().strip())
    radii = (3, 8, 20, 48)
    within = {r: [] for r in radii}
    aimed, crowd = [], []
    by_cell = {c: [] for c in cells}
    samples = 0
    for i, line in enumerate(gzip.open(os.path.join(run, "combat-samples.jsonl.gz"), "rt")):
        e = json.loads(line)
        if e["at_ms"] < start + 60_000 or i % 5:
            continue
        samples += 1
        pos = positions(e)
        open_at = {}
        for u in e["uses"]:
            if not u["outcome"]:
                open_at[u["target"]] = open_at.get(u["target"], 0) + 1
        for f in (int(k) for k in e["fighters"]):
            if f not in pos:
                continue
            x, y = pos[f]
            ds = sorted((math.hypot(p[0] - x, p[1] - y), o) for o, p in pos.items() if o != f)
            for r in radii:
                within[r].append(sum(1 for d, _ in ds if d <= r))
            aimed.append(open_at.get(f, 0))
            rest = [o for d, o in ds if d <= 48][n:]
            crowd.append(len(rest))
            for c in cells:
                by_cell[c].append(len({(int(pos[o][0] // c), int(pos[o][1] // c)) for o in rest}))
    print(f"samples: {samples}")
    for r in radii:
        print(f"others within {r} m: {q(within[r])}")
    print(f"open attacks aimed at a fighter: {q(aimed)}")
    print(f"crowd beyond the {n} nearest within 48 m: {q(crowd)}")
    for c in cells:
        print(f"crowd cells at {c:g} m: {q(by_cell[c])}")


def word(d):
    return "within reach" if d <= 2 else "close" if d <= 8 else "a stone's throw" if d <= 20 else "far"


def scenes(run):
    listed, chars, compact, tokens = [], [], [], []
    for f in glob.glob(os.path.join(run, "journal", "*.jsonl")):
        for line in open(f):
            e = json.loads(line)
            if e.get("purpose") != "think":
                continue
            msgs = e["request"].get("messages", [])
            u = msgs[-1].get("content", "") if msgs else ""
            head = "# What you perceive right now\n"
            i = u.find(head)
            if i < 0:
                continue
            s = u[i + len(head):u.find("\n", i + len(head))]
            try:
                cr = json.loads(s).get("creatures", [])
            except ValueError:
                continue
            listed.append(len(cr))
            chars.append(len(s))
            tokens.append(e.get("prompt_tokens") or 0)
            for k, c in enumerate(cr):
                v = c.get("visibly") or {}
                o = {"h": f"c{k + 1}", "who": c.get("who") or c.get("name"), "form": c.get("form"), "dir": c.get("dir"), "dist": word(c.get("dist", 99))}
                if v:
                    o["visibly"] = f"{v.get('is')}" + (f" at {'you' if v.get('at') == 'you' else 'c?'}" if v.get("at") else "") + f", {v.get('phase')}"
                if c.get("looks"):
                    o["looks"] = c["looks"]
                compact.append(len(json.dumps(o, ensure_ascii=False)))
    print(f"think prompts: creatures listed {q(listed)}")
    print(f"think prompts: scene characters {q(chars)}")
    print(f"think prompts: prompt tokens {q(tokens)}")
    print(f"compact creature entry, characters: {q(compact)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--cells", default="4,6,8")
    a = ap.parse_args()
    density(a.run, a.n, [float(c) for c in a.cells.split(",")])
    scenes(a.run)


if __name__ == "__main__":
    main()
