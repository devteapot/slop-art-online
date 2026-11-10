#!/usr/bin/env python3
"""Summarize `eco_sample.py` samples: deaths per hour by kind and cause, the population over
time, and for wolves what hunting looked like (how near the nearest deer was, attack episodes,
kills, meat carried, hunger).

  living/tools/eco_report.py DIR [--json]
"""
import json, math, sys
from collections import Counter, defaultdict
from pathlib import Path


def main():
    d = Path(sys.argv[1])
    rows = [json.loads(l) for l in (d / "samples.jsonl").open()]
    if not rows:
        sys.exit("no samples")
    start = min(c["born_ms"] for c in rows[0]["chars"] if c["born_ms"])  # the world's creation
    last = rows[-1]
    now_ms = last["clock"][0]["last_ms"]
    span_min = (now_ms - start) / 60000
    chars = {}
    for r in rows:
        for c in r["chars"]:
            chars[c["id"]] = c
    # Deaths by kind, cause class and hour.
    def cls(cause):
        c = cause.lower()
        if "starv" in c: return "starved"
        if "killed by" in c: return "killed by " + ("wolf" if any(w in c for w in ["wolf", "the wolf"]) else "person/other")
        if "old age" in c or "age" in c: return "old age"
        return cause or "?"
    deaths = defaultdict(Counter)
    by_hour = defaultdict(Counter)
    for c in chars.values():
        if not c["alive"] and c["died_ms"]:
            k = cls(c["cause"])
            deaths[c["kind"]][k] += 1
            by_hour[(c["kind"], int((c["died_ms"] - start) / 3600000))][k] += 1
    print(f"world span {span_min:.1f} min, {len(rows)} samples")
    for kind in ["wolf", "deer"]:
        born = [c for c in chars.values() if c["kind"] == kind]
        alive = [c for c in last["chars"] if c["kind"] == kind and c["alive"]]
        seeded = [c for c in born if c["born_ms"] - start < 60000]
        print(f"{kind}: seeded {len(seeded)}, born or arrived later {len(born) - len(seeded)}, alive at end {len(alive)}; deaths {dict(deaths[kind])}")
        for h in range(0, int(span_min // 60) + 1):
            if by_hour[(kind, h)]:
                print(f"   hour {h + 1}: {dict(by_hour[(kind, h)])}")
    # Population every 10 minutes.
    print("population (min: wolves, deer):", end=" ")
    seen = set()
    for r in rows:
        m = int((r["clock"][0]["last_ms"] - start) / 60000 // 10 * 10)
        if m in seen: continue
        seen.add(m)
        w = sum(1 for c in r["chars"] if c["kind"] == "wolf" and c["alive"])
        de = sum(1 for c in r["chars"] if c["kind"] == "deer" and c["alive"])
        print(f"{m}: {w},{de}", end="; ")
    print()
    # Wolves: nearest deer distance, attacks, meat, hunger.
    near = defaultdict(list)
    attacks = defaultdict(set)
    hunger = defaultdict(list)
    meat = defaultdict(int)
    act_counts = Counter()
    for r in rows:
        pos = {b["id"]: (b["x"], b["y"]) for b in r["bodies"]}
        alive = {c["id"]: c for c in r["chars"] if c["alive"]}
        deer = [pos[i] for i, c in alive.items() if c["kind"] == "deer" and i in pos]
        acts = {a["id"]: a for a in r["activity"]}
        vit = {v["id"]: v for v in r["vitals"]}
        for i, c in alive.items():
            if c["kind"] != "wolf" or i not in pos: continue
            p = pos[i]
            dmin = min((math.dist(p, q) for q in deer), default=1e9)
            near[i].append(dmin)
            a = acts.get(i)
            act_counts[a["skill"] if a else "-"] += 1
            if a and a["skill"] == "attack":
                attacks[i].add((a["victim"], a["started_ms"] // 1000))
            if i in vit: hunger[i].append(vit[i]["hunger"])
        for m in r["meat"]:
            if m["owner"] in alive and alive[m["owner"]]["kind"] == "wolf":
                meat[m["owner"]] = max(meat[m["owner"]], m["qty"])
    total = sum(act_counts.values())
    print("wolf activity share:", ", ".join(f"{k} {v / total:.0%}" for k, v in act_counts.most_common(8)))
    within = lambda r: sum(1 for i in near if min(near[i]) <= r)
    print(f"wolves ever within 7/20/60 m of a deer: {within(7)}/{within(20)}/{within(60)} of {len(near)}")
    share60 = [sum(1 for x in v if x <= 60) / len(v) for v in near.values() if v]
    print(f"share of a wolf's samples with a deer within 60 m: median {sorted(share60)[len(share60)//2]:.0%}" if share60 else "")
    print(f"attack starts by wolves (on any target): {sum(len(v) for v in attacks.values())}; wolves that ever carried meat: {len(meat)}")
    kills = [c for c in chars.values() if c["kind"] == "deer" and "killed by" in c["cause"].lower()]
    print(f"deer killed: {len(kills)}: " + ", ".join(f"{(c['died_ms'] - start) / 60000:.0f} min ({c['cause']})" for c in kills))


if __name__ == "__main__":
    main()
