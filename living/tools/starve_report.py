#!/usr/bin/env python3
"""Did the newcomer feed itself on the square? (docs/TRIALS.md, "Fast iterations" 9)

  starve_report.py BATCH [BATCH...]

Per run: whether the newcomer starved and when, how far it went past the edge of the town it
arrived in and for how long, store takes, gathers, food received, the highest hunger, how
often it was told a nearest target was not in sight (and with the sight-range wording), and
cost. A mean (range) per variant. Read-only.
"""
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (prices: trials.cost)

OUT = Path(__file__).resolve().parents[2] / ".local/living/trials"


def jl(p):
    out = []
    if not p.exists():
        return out
    for line in p.read_bytes().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def run(d):
    s = json.loads((d / "summary.json").read_text())
    samples = [x for x in jl(d / "samples.jsonl") if x.get("pos")]
    exps = jl(d / "experiences.jsonl")
    snap = json.loads(sorted((d / "snapshots").glob("*.json"))[0].read_text())
    town = min(snap["settlement"], key=lambda t: math.dist(samples[0]["pos"], (t["x"], t["y"])))
    past = [math.dist(x["pos"], (town["x"], town["y"])) - town["radius_m"] for x in samples]
    skills = s.get("skills") or {}
    nearest = [e for e in exps if re.search(r"did not work out: [^:]*→ nearest [^:]*: no nearest", e.get("text", ""))]
    return {
        "run": d.name, "variant": s["variant"], "min": round(s["minutes_run"]),
        "starved": 1 if (s.get("death") or "").endswith("(starvation)") else 0, "died_min": s.get("died_min"),
        "hunger_max": s.get("hunger_max"),
        "outside_share": round(sum(1 for p in past if p > 0) / len(past), 2), "max_past_edge_m": round(max(past)),
        "takes": skills.get("take", 0), "gathers": skills.get("gather", 0), "meals": skills.get("eat", 0),
        "given_food": sum(1 for e in exps if "gave you" in e.get("text", "") and e.get("kind") not in ("said", "repeat")),
        "nearest_not_in_sight": len(nearest), "told_sight_range": sum(1 for e in nearest if "you see about" in e["text"]),
        "cost": round(sum(trials.cost(m, b["prompt"], b["completion"], b["cached"]) or 0 for m, b in (s.get("by_model") or {}).items()), 2),
    }


def main():
    rows = [run(p.parent) for b in sys.argv[1:] for p in sorted((OUT / b).glob("*/summary.json"))]
    keys = [k for k in rows[0] if k not in ("run", "variant")]
    print("| run | " + " | ".join(keys) + " |")
    print("| --- |" + " --- |" * len(keys))
    for r in rows:
        print(f"| {r['run']} | " + " | ".join(str(r.get(k)) for k in keys) + " |")
    by = defaultdict(list)
    for r in rows:
        by[r["variant"]].append(r)
    print()
    for v, rs in by.items():
        parts = []
        for k in keys:
            xs = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
            if xs:
                parts.append(f"{k} {statistics.mean(xs):.2f} ({min(xs):g}-{max(xs):g})")
        print(f"{v} (n={len(rs)}): " + "; ".join(parts))


if __name__ == "__main__":
    main()
