#!/usr/bin/env python3
"""Compare an iteration's arms from their evidence (docs/TRIALS.md, "Fast iterations").

  iter_report.py BATCH

One row per instance and a mean (range) per variant: survival, calls and tokens, and the
counts that the overnight hypotheses look at: people and deer killed by a pack, writing
learned and how, signs read, failed reads, deliberations by reason (the longing for a
child, feelings), lines said. Read-only.
"""
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

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


def row(d):
    s = json.loads((d / "summary.json").read_text())
    exps = jl(d / "experiences.jsonl")
    chron = jl(d / "chronicle.jsonl")
    thoughts = jl(d / "thoughts.jsonl")
    cast = json.loads((d / "cast.json").read_text())["roles"]
    S = cast["subject"][0]["id"]
    people = {c["id"] for c in []}
    r = {"run": d.name, "variant": s["variant"], "stopped": s["stopped_by"][:24], "min": s["minutes_run"], "calls": s["calls"], "tokens": s["tokens"],
         "lines": s.get("lines_said"), "learned": ",".join(s.get("learned", [])) or "-"}
    pack = s.get("pack")
    if pack:
        sub = {m["id"] for m in cast["subject"]}
        deaths = [c for c in chron if c.get("kind") == "death" and c.get("b") in sub]
        r["kills_people"] = sum(1 for c in deaths if not re.search(r"\bthe (deer|wolf)\b", c["text"]))
        r["kills_deer"] = sum(1 for c in deaths if re.search(r"\bthe deer\b", c["text"]))
        r["pack_alive"] = pack["alive_end"]
        r["pack_m"] = pack["mean_pairwise_m"]
        lost = [c for c in chron if c.get("kind") == "death" and c.get("a") in sub]
        r["pack_lost"] = len(lost)
    r["writing"] = next((round(c["t"] / 60, 1) for c in chron if c.get("kind") == "learn" and c.get("a") == S and "writing" in c["text"]), None)
    r["signs_read"] = sum(1 for e in exps if e.get("text", "").startswith("You read"))
    r["read_fails"] = sum(1 for e in exps if "you can't read" in e.get("text", ""))
    r["asked_scribe"] = sum(1 for e in jl(d / "events.jsonl") if e.get("trigger") is not None)
    delib = [t for t in thoughts if t.get("kind") == "deliberate"]
    reasons = []
    for t in delib:
        try:
            reasons.append(json.loads(t.get("detail") or "{}").get("reason", ""))
        except ValueError:
            reasons.append("")
    r["delibs"] = len(delib)
    r["longing"] = sum(1 for x in reasons if "long for a child" in x)
    r["feelings"] = sum(1 for x in reasons if "You feel something" in x)
    r["meals"] = s.get("skills", {}).get("eat", 0)
    return r


def main():
    batch = sys.argv[1]
    rows = [row(p.parent) for p in sorted((OUT / batch).glob("*/summary.json"))]
    keys = [k for k in rows[0] if k not in ("run", "variant")]
    print("| run | " + " | ".join(keys) + " |")
    print("| --- |" + " --- |" * len(keys))
    for r in rows:
        print(f"| {r['run']} | " + " | ".join(str(r.get(k)) for k in keys) + " |")
    by = defaultdict(list)
    for r in rows:
        by[re.sub(r"-r\d+$", "", r["run"])].append(r)
    print()
    for v, rs in by.items():
        parts = []
        for k in keys:
            xs = [r.get(k) for r in rs if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)]
            if xs:
                parts.append(f"{k} {statistics.mean(xs):.1f} ({min(xs):g}-{max(xs):g})")
        print(f"{v} (n={len(rs)}): " + "; ".join(parts))


if __name__ == "__main__":
    main()
