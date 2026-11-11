#!/usr/bin/env python3
"""How much of a life is about living rather than surviving (docs/TRIALS.md, "Fast iterations" 11).

  life_share.py BATCH [BATCH...]

Per run: starved or not; the share of the mind's plans (each installed plan's text) and of its
decided acts that are not about food or warmth; what it did with the rest (people spoken to,
lines, techniques and how, structures other than fires and shelters, writing, teaching, trades
and agreements); cost per hour. A mean (range) per variant. The plan and act classes are keyword
and skill matches; read the examples it prints before trusting a share.
"""
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (prices: trials.cost)

OUT = Path(__file__).resolve().parents[2] / ".local/living/trials"
FOOD = re.compile(r"\b(eat|ate|food|berr\w*|fish\w*|meat|hunger|hungry|starv\w*|cook\w*|forag\w*|meal|feed|fed|fruit|bush\w*|store\w* food)\b", re.I)
WARM = re.compile(r"\b(warm\w*|cold|fire|campfire|shelter\w*|cloak|freez\w*|winter|night)\b", re.I)
FOOD_ACTS = {"eat", "cook", "smoke", "plant", "fish"}
WARM_ACTS = {"sleep", "rest"}


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


def reply(r):
    m = re.search(r"\{.*\}", r.get("reply") or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


MOVES = {"goto", "wander", "wait", "follow", "face", "flee"}
MATERIALS = re.compile(r"tree|wood|reeds|clay|boulder|stone|fiber", re.I)


def act_class(a):
    """food, warmth, move (walking and waiting: left out of the share, since a walk serves
    whatever the plan is) or other. A gather is food unless its target or item names a material."""
    do = a.get("do")
    item = str(a.get("item") or "")
    target = json.dumps(a.get("target") or "")
    if do in MOVES:
        return "move"
    if do == "gather":
        return "warmth" if re.search(r"tree|wood", item + target, re.I) else ("other" if MATERIALS.search(item + target) else "food")
    if do in FOOD_ACTS or (do in ("take", "give", "store", "offer") and FOOD.search(item + " " + target)):
        return "food"
    if do in WARM_ACTS or (do == "build" and item in ("campfire", "shelter")) or (do == "craft" and item == "cloak"):
        return "warmth"
    return "other"


def run(d):
    s = json.loads((d / "summary.json").read_text())
    S = int(s["subject"].split("#")[1])
    name = s["subject"].split("#")[0]
    graphs = [g for g in jl(d / "graphs.jsonl") if g.get("source") == "mind"]
    plans = [g.get("plan") or "" for g in graphs]
    plan_other = [p for p in plans if not FOOD.search(p) and not WARM.search(p)]
    acts = []
    for r in jl(d / "journal" / f"{name}.jsonl"):
        for a in reply(r).get("acts") or []:
            if isinstance(a, dict) and a.get("do"):
                acts.append(a)
    classes = Counter(act_class(a) for a in acts)
    other_acts = Counter(a["do"] for a in acts if act_class(a) == "other")
    chron = jl(d / "chronicle.jsonl")
    # A learn row's a is the teacher and b the learner (0 when one worked it out alone).
    learned = [c["text"] for c in chron if c.get("kind") == "learn" and ((c.get("a") == S and not c.get("b")) or c.get("b") == S)]
    built = s.get("built") or {}
    sk = s.get("skills") or {}
    cost = sum(trials.cost(m, b["prompt"], b["completion"], b["cached"]) or 0 for m, b in (s.get("by_model") or {}).items())
    hours = s["minutes_run"] / 60
    return {
        "run": d.name, "variant": s["variant"], "min": round(s["minutes_run"]),
        "starved": 1 if (s.get("death") or "").endswith("(starvation)") else 0, "died": 0 if s.get("survived") else 1,
        "plans": len(plans), "plans_other_share": round(len(plan_other) / len(plans), 2) if plans else None,
        "acts": len(acts), "acts_other_share": round(classes["other"] / (len(acts) - classes["move"]), 2) if len(acts) > classes["move"] else None,
        "people": len([k for k in (s.get("said_to") or {}) if k != "nobody"]), "lines": s.get("lines_said"),
        "learned": len(learned), "learned_from_someone": sum(1 for t in learned if "worked out" not in t),
        "built_other": sum(v for k, v in built.items() if k not in ("campfire", "shelter")) if isinstance(built, dict) else 0,
        "wrote": sk.get("write", 0), "taught": sk.get("teach", 0), "traded": sk.get("offer", 0) + sk.get("offer_terms", 0) + sk.get("accept", 0) + sk.get("give", 0),
        "cost_per_h": round(cost / hours, 3) if hours else None,
        "_plan_other": plan_other[:3], "_other_acts": dict(other_acts.most_common(6)),
    }


def main():
    rows = [run(p.parent) for b in sys.argv[1:] for p in sorted((OUT / b).glob("*/summary.json"))]
    keys = [k for k in rows[0] if k not in ("run", "variant") and not k.startswith("_")]
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
        acts = sum((Counter(r["_other_acts"]) for r in rs), Counter())
        print("   other acts:", dict(acts.most_common(8)))
        for r in rs[:2]:
            print(f"   e.g. {r['run']} plans not about food or warmth: {r['_plan_other']}")


if __name__ == "__main__":
    main()
