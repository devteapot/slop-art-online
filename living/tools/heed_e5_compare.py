#!/usr/bin/env python3
"""E5's decision rule on the scored arms (docs/ATTENTION_E5.md §3; docs/ATTENTION_E3.md §5). Read-only.

  heed_e5_compare.py --arm NAME NAMED.json SCORE.json [--arm ...] --base a10 [--json OUT]

Each arm gives its `attention_e3.py named --scene-only` output (M2'' rows) and its `score` output
(M1, flicker per state). The comparison uses only the states every arm covers (a paid arm stopped
at its cap covers a prefix of the frozen states), so every arm is scored on the same moments.

Per arm: M2'' named heeded beyond the 8 nearest (decisive), beyond capacity and overall; M1 first
blows from the unheeded per 100 first blows; flicker per subject-minute; mean heeded.
Against the base arm, for each other arm: the M2'' beyond-8 difference in points, the events where
the two disagree (one heeds the named person, the other does not), the exact two-sided sign test
on them, the M1 difference and the flicker ratio, and whether the rule's three conditions hold:
  - M2'' beyond the 8 nearest higher by at least 5 points, sign test p < 0.05;
  - M1 no worse by more than 1 per 100 first blows;
  - flicker at most 1.5 times the base's.
"""
import argparse
import json
import math
import sys


def sign_test(plus, minus):
    """Exact two-sided binomial test of plus vs minus at p = 0.5."""
    n = plus + minus
    if n == 0:
        return 1.0
    k = min(plus, minus)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load(named_path, score_path):
    named = json.load(open(named_path))
    score = json.load(open(score_path))
    rows = {(r["state"], r["id"]): r for r in named["rows"]}
    per = {p["state"]: p for p in score["per_state"]}
    return rows, per


def summarize(rows, per, states):
    rs = [r for k, r in rows.items() if k[0] in states]
    share = lambda f: (round(100.0 * sum(1 for r in rs if f(r) and r["heeded"]) / max(1, sum(1 for r in rs if f(r))), 1), sum(1 for r in rs if f(r)))
    ps = [per[s] for s in states if s in per]
    first = sum(p.get("first_blows", 0) for p in ps)
    first_un = sum(p.get("first_blows_unheeded", 0) for p in ps)
    later = sum(p.get("later_blows", 0) for p in ps)
    later_un = sum(p.get("later_blows_unheeded", 0) for p in ps)
    return {"M2_beyond8": share(lambda r: r["beyond8"]), "M2_beyond_capacity": share(lambda r: r.get("beyond_capacity")), "M2_all": share(lambda r: True),
            "M1_first_blows_unheeded_per_100": round(100.0 * first_un / first, 2) if first else None, "first_blows": first, "first_blows_unheeded": first_un,
            "later_blows_unheeded": later_un, "later_blows": later,
            "flicker_per_min_mean": round(sum(p.get("flicker_per_min") or 0 for p in ps) / max(1, len(ps)), 3),
            "heeded_mean": round(sum(p.get("heeded_mean") or 0 for p in ps) / max(1, len(ps)), 2),
            "capacity_p50": sorted(p.get("capacity") or 0 for p in ps)[len(ps) // 2] if ps else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", nargs=3, action="append", metavar=("NAME", "NAMED", "SCORE"), required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--json")
    a = ap.parse_args()
    arms = {n: load(nm, sc) for n, nm, sc in a.arm}
    states = None
    for rows, per in arms.values():
        s = set(per)
        states = s if states is None else states & s
    out = {"states": len(states), "arms": {}, "against_base": {}}
    for n, (rows, per) in arms.items():
        out["arms"][n] = summarize(rows, per, states)
    brows, bper = arms[a.base]
    base = out["arms"][a.base]
    for n, (rows, per) in arms.items():
        if n == a.base:
            continue
        plus = minus = both = 0
        for k, r in brows.items():
            if k[0] not in states or not r["beyond8"] or k not in rows:
                continue
            x, y = rows[k]["heeded"], r["heeded"]
            plus += x and not y
            minus += y and not x
            both += 1
        me = out["arms"][n]
        d = round(me["M2_beyond8"][0] - base["M2_beyond8"][0], 1)
        p = sign_test(plus, minus)
        m1 = None if me["M1_first_blows_unheeded_per_100"] is None or base["M1_first_blows_unheeded_per_100"] is None else round(me["M1_first_blows_unheeded_per_100"] - base["M1_first_blows_unheeded_per_100"], 2)
        fr = round(me["flicker_per_min_mean"] / base["flicker_per_min_mean"], 3) if base["flicker_per_min_mean"] else None
        conds = {"m2_gain_5pt_p05": d >= 5 and p < 0.05 and plus > minus, "m1_within_1_per_100": m1 is not None and m1 <= 1.0, "flicker_within_1_5x": fr is not None and fr <= 1.5}
        out["against_base"][n] = {"M2_beyond8_diff_pts": d, "events": both, "arm_only": plus, "base_only": minus, "disagree_pct": round(100.0 * (plus + minus) / max(1, both), 1),
                                  "sign_test_p": round(p, 5), "M1_diff_per_100": m1, "flicker_ratio": fr, "conditions": conds, "preferred": all(conds.values())}
    print(json.dumps(out, indent=1))
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
