#!/usr/bin/env python3
"""Score the temperament replay (docs/TRIALS.md, fs1n): per arm and sheet class, the judges'
codes (speak, mean_to, inward, unaware) and false claims; agreement on doubly judged items.
  temperament_score.py EVIDENCE_DIR"""
import json, glob, sys, collections
E = sys.argv[1]
CLASS = {}
for n in ["Bram Calloway", "Ife Okoro", "Lark Morrow", "Oswin Greave", "Ren Sato", "Roos Achterberg", "Greta Dunmore", "Nell Tarn", "Neve Calloway", "Wick Marl", "Lorcan Vane"]:
    CLASS[n] = "outgoing"
for n in ["Aldous Quill", "Benedikt Orme", "Amara Okoro", "Eamon Tarn"]:
    CLASS[n] = "both"
for n in ["Hana Sato", "Suri Greave", "Davin Vane", "Petra Tarn", "Rafe Dunlin"]:
    CLASS[n] = "reserved"
for n in ["Gwil Stannard", "Ingrid Morrow", "Joss Tarn", "Chidi Okoro", "Magda Tarn"]:
    CLASS[n] = "none"
key = {k["item"]: k for k in (json.loads(l) for l in open(f"{E}/key.jsonl"))}
labels = collections.defaultdict(list)
for f in sorted(glob.glob(f"{E}/judge/labels-*.jsonl")):
    for l in open(f):
        d = json.loads(l)
        labels[d["item"]].append(d)
agree = [ls[0]["code"] == ls[1]["code"] for ls in labels.values() if len(ls) > 1]
fagree = [ls[0]["false_claim"] == ls[1]["false_claim"] for ls in labels.values() if len(ls) > 1]
cell = collections.defaultdict(lambda: collections.Counter())
for iid, ls in labels.items():
    k = key[iid]
    c = CLASS[k["actor"]]
    lab = ls[0]
    for cls in (c, "all"):
        cell[(k["arm"], cls)][lab["code"]] += 1
        cell[(k["arm"], cls)]["n"] += 1
        cell[(k["arm"], cls)]["false"] += lab["false_claim"] is True
print("| arm | sheet | n | speak | mean to | speak or mean to | inward | unaware | false claims |")
print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
for arm in ("R", "A", "B", "C"):
    for cls in ("outgoing", "both", "reserved", "none", "all"):
        c = cell[(arm, cls)]
        if not c["n"]:
            continue
        sm = c["speak"] + c["mean_to"]
        print(f"| {arm} | {cls} | {c['n']} | {c['speak']} | {c['mean_to']} | {sm} ({sm / c['n']:.0%}) | {c['inward']} | {c['unaware']} | {c['false']} |")
print(f"agreement: code {sum(agree)} of {len(agree)}, false claim {sum(fagree)} of {len(fagree)}")
json.dump({f"{a}/{c}": dict(v) for (a, c), v in cell.items()}, open(f"{E}/score.json", "w"), indent=1)
