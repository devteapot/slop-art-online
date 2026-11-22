#!/usr/bin/env python3
"""NPC-MEASURE (branch npc-measure only; docs/NPC_CLIENT_SERVICE.md): reflex latencies from a run's
`fighters.csv` (gate-load `npc`, which records every fighter row it receives, in both arms).

A windup is a fighter row with a move under way that is not a guard, a dodge, a heal or a jump, a
release still ahead of its start, and a target: keyed by (attacker, act, act_ms). Its answer is the
target's first `dodge` or `block` row that started at or after the windup's start and no later than
its release. The latency is the answer's start less the windup's start, both the authority's ms: the
same measure for an AI's in-tick reaction and for a reaction sent by an NPC body service.

    reflex.py RUN_DIR [--share Q] [--json]
Only windups aimed at fighters with `id % 4 < Q` are counted (the driven ones in an NPC arm, the
same ids in the AI arm; Q 4 counts every fighter). The window is battle-viewers.json's
`npc.window` (seconds), applied to each row's receipt time.
"""
import csv
import json
import sys
from pathlib import Path


def pairs(rows, codes, share=4, window=None):
    """rows: (local_us, id, act, act_ms, release_ms, until_ms, target) tuples of ints; codes: skill
    -> code. Returns (latencies in ms, windups counted)."""
    dodge, block = codes.get("dodge"), codes.get("block")
    passive = {codes.get(s) for s in ("dodge", "block", "heal", "jump")} - {None}
    windups, answers = {}, {}
    for t, i, act, act_ms, rel, _, tgt in rows:
        if window and not (window[0] * 1e6 <= t < window[1] * 1e6):
            continue
        if act and act not in passive and rel > act_ms and tgt and tgt % 4 < share:
            windups.setdefault((i, act, act_ms), (tgt, rel))
        if act in (dodge, block):
            answers.setdefault(i, set()).add(act_ms)
    lat = []
    for (_, _, start), (tgt, rel) in windups.items():
        got = [a for a in answers.get(tgt, ()) if start <= a <= rel]
        if got:
            lat.append(min(got) - start)
    return sorted(lat), len(windups)


def quant(v, q):
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def read(run, share):
    run = Path(run)
    bv = json.loads((run / "battle-viewers.json").read_text())
    r = bv["rows"][0] if "rows" in bv else bv
    codes = r["npc_ready"]["codes"]
    window = r["npc"]["window"]
    rows = [tuple(int(x) for x in l) for l in csv.reader(open(run / "fighters.csv")) if len(l) == 7]
    lat, n = pairs(rows, codes, share, window)
    out = {"run": run.name, "windups": n, "answered": len(lat), "answered_share": round(len(lat) / n, 3) if n else None,
           "p50_ms": quant(lat, 0.5), "p90_ms": quant(lat, 0.9), "p99_ms": quant(lat, 0.99), "max_ms": lat[-1] if lat else None}
    rf = run / "reflex.csv"
    if rf.exists():
        rr = [tuple(int(x) for x in l) for l in csv.reader(open(rf)) if len(l) == 6]
        rr = [x for x in rr if window[0] * 1e6 <= x[0] < window[1] * 1e6]
        seen = sorted((x[0] - x[3] * 1000) / 1000 for x in rr)  # windup start (authority) to receipt here
        dec = sorted((x[5] - x[0]) / 1000 for x in rr)  # receipt to send
        out["service"] = {"reflexes": len(rr), "seen_after_ms": {"p50": quant(seen, 0.5), "p99": quant(seen, 0.99)},
                          "decided_in_ms": {"p50": quant(dec, 0.5), "p99": quant(dec, 0.99)}}
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    share = int(a[a.index("--share") + 1]) if "--share" in a else 4
    runs = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--share")]
    print(json.dumps([read(r, share) for r in runs], indent=1))
