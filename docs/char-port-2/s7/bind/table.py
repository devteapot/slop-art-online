#!/usr/bin/env python3
"""The bind re-measure's tables (the GC, 2026-11-21): old (idle 2.0 s, camera pitch 8) against new (bind, pitch 8 and
pitch 0), each number with its pose, from the runs' JSON in .local/char-port-2/s7 (bindmeasure.sh, pitch0.sh).
    python3 table.py LOCAL OUT.json   # prints the markdown tables"""
import json, sys
from pathlib import Path

L = Path(sys.argv[1])
j = lambda p: json.loads((L / p).read_text())
sq = lambda p: {Path(d["source"]).parts[-3]: d for d in map(json.loads, (L / p).read_text().splitlines())}
sets = dict(s6b=dict(idle=j("../s6b/twod/fp21j.json"), bind8=j("bind/s6b-fp21j.json"), bind0=j("bind/p0/s6b-fp21j.json"), sq8=sq("bind/s6b-fp21j-square.jsonl")),
            s7=dict(idle=j("twod/fp21b.json"), bind8=j("bind/s7-fp21b.json"), bind0=j("bind/p0/s7-fp21b.json"), sq8=sq("bind/s7-fp21b-square.jsonl")))
out = {}
print("| Type | S6b idle·p8 | S6b bind·p8 | S6b bind·p0 | S7 idle·p8 | S7 bind·p8 | S7 bind·p0 | eyes off axis, bind·p8 / p0 (px) |")
print("|---|---|---|---|---|---|---|---|")
for t in sets["s6b"]["idle"]:
    row = {}
    cells = []
    for s in ("s6b", "s7"):
        for k in ("idle", "bind8", "bind0"):
            v = sets[s][k][t]["face_over_eyes"]
            row[f"{s}_{k}"] = dict(pose="idle" if k == "idle" else "bind", pitch=8 if k != "bind0" else 0, face_over_eyes=v, ear_on_cheek_row=sets[s][k][t]["ear_on_cheek_row"])
            cells.append(f"{v:.3f}" + ("" if sets[s][k][t]["ear_on_cheek_row"] else "°"))
    o8, o0 = sets["s7"]["sq8"][t]["eyes_off_px"], sets["s7"]["bind0"][t]["square"]["eyes_off_px"]
    print(f"| {t} | " + " | ".join(cells) + f" | {o8} / {o0} |")
    out[t] = row
means = {}
for s in ("s6b", "s7"):
    for k in ("idle", "bind8", "bind0"):
        for cls in ("adult-f", "adult-m", "youth-f", "youth-m", "elder-f", "elder-m", "child-u"):
            vs = [sets[s][k][t]["face_over_eyes"] for t in sets[s][k] if t.startswith(cls)]
            means.setdefault(cls, {})[f"{s}_{k}"] = round(sum(vs) / len(vs), 3)
print("\n| Class mean | " + " | ".join(f"{s} {k}" for s in ("S6b", "S7") for k in ("idle·p8", "bind·p8", "bind·p0")) + " |")
print("|---|" + "---|" * 6)
for cls, m in means.items():
    print(f"| {cls} | " + " | ".join(f"{v:.3f}" for v in m.values()) + " |")
Path(sys.argv[2]).write_text(json.dumps(dict(types=out, class_means=means, drawing_face_over_eyes=dict(review=1.751, stage1=1.701)), indent=1))
