#!/usr/bin/env python3
"""E4b's side asymmetry (docs/ATTENTION_E4.md §5): in the two-sided melee, does the side with the
lower ids, or Side A as such, lose more often? Read-only, over heed_e4_melee.py run folders.

  heed_e4b_side.py DIR... [--json OUT]

Per arm group (heed off; symmetric heed on by instinct), per id order (r0: Side A has the lower
ids; r1: Side B has them): which side broke, the low-id side's share of decided fights, and the
low-id side's dead less the other's at 60 s, 90 s and the end; exact two-sided binomial tests
against an even split."""
import argparse
import json
import statistics
import sys
from collections import defaultdict
from math import comb
from pathlib import Path


def binom_p(k, n):
    if n == 0:
        return None
    tail = sum(comb(n, i) for i in range(max(k, n - k), n + 1)) / 2 ** n
    return min(1.0, 2 * tail) if k != n - k else 1.0


def runs(dirs):
    for d in dirs:
        d = Path(d)
        for p in ([d] if (d / "roles.json").exists() else sorted(d.iterdir())):
            if (p / "summary.json").exists() and (p / "roles.json").exists():
                yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    groups = defaultdict(list)
    for p in runs(a.dirs):
        r = json.loads((p / "roles.json").read_text())
        s = json.loads((p / "summary.json").read_text())
        base, inst, rot = r.get("base", r["arm"]), r.get("instinct", "v2"), r.get("rotation", 0)
        if base not in ("off", "formula"):
            continue
        key = ("off" if base == "off" else f"formula.{inst}") + (".mixed" if r.get("laws", {}).get("sides_mixed_defence") else "")
        A, B = r["side_a"], r["side_b"]
        low = r.get("low_id_side", "A")
        t0 = s["t0"]

        def dead_low_minus_high(sec=None):
            xs = s["samples"] if sec is None else [q for q in s["samples"] if q["ms"] - t0 <= sec * 1000]
            q = xs[-1]
            da, db = len(A) - q["a"], len(B) - q["b"]
            return (da - db) if low == "A" else (db - da)
        groups[(key, rot)].append({"broke": s["broke"], "low": low, "low_broke": None if s["broke"] is None else s["broke"] == low,
                                   "d60": dead_low_minus_high(60), "d90": dead_low_minus_high(90), "dend": dead_low_minus_high()})
    out = {}
    for key in sorted({k for k, _ in groups}):
        rows = []
        for rot in (0, 1, "both"):
            rs = groups.get((key, rot), []) if rot != "both" else groups.get((key, 0), []) + groups.get((key, 1), [])
            if not rs:
                continue
            dec = [x for x in rs if x["low_broke"] is not None]
            k = sum(1 for x in dec if x["low_broke"])
            a_broke = sum(1 for x in rs if x["broke"] == "A")
            b_broke = sum(1 for x in rs if x["broke"] == "B")
            row = {"rotation": rot, "n": len(rs), "A_broke": a_broke, "B_broke": b_broke, "none": len(rs) - a_broke - b_broke,
                   "low_id_side_broke": f"{k} of {len(dec)}", "p_low_vs_even": binom_p(k, len(dec)),
                   "side_A_broke_p_vs_even": binom_p(a_broke, a_broke + b_broke),
                   "low_minus_high_dead_60_median": statistics.median(x["d60"] for x in rs),
                   "low_minus_high_dead_90_median": statistics.median(x["d90"] for x in rs),
                   "low_minus_high_dead_end_median": statistics.median(x["dend"] for x in rs),
                   "low_minus_high_dead_end_positive": sum(1 for x in rs if x["dend"] > 0), "negative": sum(1 for x in rs if x["dend"] < 0)}
            rows.append(row)
            print(key, json.dumps(row))
        out[key] = rows
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
