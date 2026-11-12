#!/usr/bin/env python3
"""Who lives where: what minds were shown and kept about other people's homes.

Read-only over trial evidence (journals, `final.json`, `mind_rows.jsonl`): no model
calls, no database. For each batch:

1. **Shown.** Every house in a think or deliberate scene (`structures`, kind
   `house`), with the authority's `home_of` label: the owner's name; the owner as
   a far or unnamed figure ("someone too far away to make out", "a stranger":
   `owner_label` labels the owner by `label_for`, which reads where the owner
   stands now); or absent (the owner is not known by name; `owner_shown`). The truth for each house is the owner's name wherever
   any observer was shown it, and the house's position.
2. **Kept.** Every place a mind named (`place` rows in `mind_rows.jsonl` and
   `final.json`, and the `places` arrays of think and consolidate replies) whose
   name says it is someone's home, as the head of the name ("<Name>'s house|home|hearth|door|doorstep|
   hut|stead|steading|cottage|cabin|roof", or "<Name> house"). It is checked
   against that person's true home: the houses a scene named as theirs, and their
   own seeded `home` place (a household's home, so a partner or child of the
   house's owner counts). **right** if one lies within 10 m, **wrong** if the named owner has a
   known house farther than 10 m and none nearer, **unknown** otherwise (no house
   of that owner was ever shown, or the name is not a resident's).
3. **Said.** Lines (chronicle `speech`) and thoughts that place someone's home in
   words: "<Name>'s house/home ..." and "I live ...", counted, with examples.

Usage: homes_audit.py BATCH_DIR [BATCH_DIR ...] [--out FILE.json]
"""
import argparse
import glob
import json
import os
import re
from collections import Counter, defaultdict

HOME_WORDS = r"(?:house|home|hearth|door|doorstep|hut|stead|steading|cottage|cabin|roof)"
FAR = "someone too far away to make out"


def jl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            line = line.strip().strip("\x00")
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def scene_houses(content):
    for m in re.finditer(r'\{"at":\[([-\d.]+),([-\d.]+)\][^{}]*?"kind":"house"[^{}]*\}', content):
        try:
            o = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        yield o


def audit_run(path):
    res = {"shown": Counter(), "houses": {}, "kept": [], "said": [], "minds": 0, "residents": set()}
    final = json.load(open(os.path.join(path, "final.json"))) if os.path.exists(os.path.join(path, "final.json")) else {}
    for c in jl(os.path.join(path, "census.jsonl"))[:1]:
        res["residents"] = {p["name"] for p in c.get("people", [])}
    names = set(res["residents"])
    for c in jl(os.path.join(path, "census.jsonl")):
        names |= {p["name"] for p in c.get("people", [])}
    jdir = os.path.join(path, "journal")
    names |= {os.path.basename(f)[:-6].replace("_", " ") for f in glob.glob(os.path.join(jdir, "*.jsonl"))}
    replies = []
    for f in glob.glob(os.path.join(jdir, "*.jsonl")):
        res["minds"] += 1
        actor = os.path.basename(f)[:-6].replace("_", " ")
        names.add(actor)
        for r in jl(f):
            req = r.get("request") or {}
            if r.get("purpose") in ("think", "deliberate"):
                for m in req.get("messages", []):
                    for o in scene_houses(m.get("content") or ""):
                        lab = o.get("home_of")
                        if not lab:
                            res["shown"]["no owner shown"] += 1
                        elif lab in names:
                            res["shown"]["owner named"] += 1
                            res["houses"][o["id"]] = {"owner": lab, "at": o["at"]}
                        else:
                            # the owner's label as seen from here: far, or a stranger (owner_label → label_for)
                            res["shown"]["owner as a far or unnamed figure: " + lab] += 1
                        res["houses"].setdefault(o["id"], {"owner": None, "at": o["at"]})
            if r.get("purpose") in ("think", "consolidate", "reorganize") and r.get("reply"):
                replies.append((actor, r))
    # The truth: houses whose owner a scene named, and each resident's own `home` place (the
    # seeded household home, `given`), so a partner or child of the house's owner counts too.
    idname = {}
    for c in jl(os.path.join(path, "census.jsonl")):
        for pe in c.get("people", []):
            idname[pe["id"]] = pe["name"]
    owners = defaultdict(list)
    for h in res["houses"].values():
        if h["owner"]:
            owners[h["owner"].split()[0].lower()].append(h["at"])
    for tab in [final.get("place", [])] + [r["rows"] for r in jl(os.path.join(path, "mind_rows.jsonl")) if r.get("table") == "place"]:
        for p in tab:
            if p["name"] == "home" and p.get("actor") in idname:
                owners[idname[p["actor"]].split()[0].lower()].append([p["x"], p["y"]])
    first_names = {n.split()[0].lower() for n in names if n}
    # The home must be the place itself ("Wenna's house", "Aldous Quill's door"), not a place
    # beside it ("the ground by Wenna's house").
    pat = re.compile(r"^(?:the )?([A-Z][a-z]+)(?: [A-Z][a-z]+)?(?:'s|’s)? " + HOME_WORDS + r"\b")

    def judge(place_name, x, y):
        m = pat.search(place_name)
        if not m or m.group(1).lower() not in first_names:
            return None
        who = m.group(1).lower()
        hs = owners.get(who, [])
        if not hs:
            return who, "unknown", None
        d = min(((x - a) ** 2 + (y - b) ** 2) ** 0.5 for a, b in hs)
        return who, ("right" if d <= 10 else "wrong"), round(d, 1)

    seen_places = set()
    rows = []
    for tab in [final.get("place", [])] + [r["rows"] for r in jl(os.path.join(path, "mind_rows.jsonl")) if r.get("table") == "place"]:
        for p in tab:
            rows.append((p.get("actor"), p["name"], p["x"], p["y"], "place row"))
    for actor, r in replies:
        try:
            rep = json.loads(r["reply"]) if isinstance(r["reply"], str) else r["reply"]
        except (json.JSONDecodeError, TypeError):
            continue
        for p in (rep.get("places") or []) if isinstance(rep, dict) else []:
            if isinstance(p, dict) and "name" in p and isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float)):
                rows.append((actor, p["name"], p["x"], p["y"], r["purpose"] + " reply"))
    for actor, name, x, y, src in rows:
        key = (actor, name, round(x), round(y))
        if key in seen_places:
            continue
        seen_places.add(key)
        j = judge(name, x, y)
        if j:
            res["kept"].append({"by": actor, "name": name, "at": [x, y], "src": src, "whose": j[0], "verdict": j[1], "nearest_house_m": j[2],
                                "houses_of_owner": owners.get(j[0], [])[:3]})
    said_pat = re.compile(r"\b(?:[A-Z][a-z]+(?:'s|’s) (?:house|home|hearth|door)\b[^.!?]{0,60}|I live\b[^.!?]{0,60}|lives (?:in|at|by|on|past|up|down|near)\b[^.!?]{0,60})")
    for x in final.get("chronicle", []):
        if x["kind"] == "speech":
            for m in said_pat.finditer(x["text"]):
                res["said"].append(x["text"][:220])
                break
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    report = {}
    for b in a.batches:
        bn = os.path.basename(b.rstrip("/"))
        agg = {"runs": 0, "shown": Counter(), "kept": Counter(), "kept_examples": [], "said": 0, "said_examples": []}
        for rd in sorted(glob.glob(os.path.join(b, "*/final.json"))):
            r = audit_run(os.path.dirname(rd))
            agg["runs"] += 1
            agg["shown"].update(r["shown"])
            for k in r["kept"]:
                agg["kept"][k["verdict"]] += 1
                k["run"] = os.path.basename(os.path.dirname(rd))
                agg["kept_examples"].append(k)
            agg["said"] += len(r["said"])
            agg["said_examples"] += r["said"][:5]
        report[bn] = agg
        print(f"## {bn}: {agg['runs']} runs")
        print("  houses shown in scenes:", dict(agg["shown"]))
        print("  homes kept as places:", dict(agg["kept"]))
        for k in agg["kept_examples"][:6]:
            print(f"    {k['verdict']}: {k['by']} kept \"{k['name']}\" at {k['at']} ({k['src']}); nearest house of {k['whose']}: {k['nearest_house_m']} m")
        print("  lines placing a home:", agg["said"])
        for s in agg["said_examples"][:4]:
            print("    ", s)
    if a.out:
        json.dump(report, open(a.out, "w"), indent=1, default=lambda o: dict(o) if isinstance(o, Counter) else list(o), ensure_ascii=False)


if __name__ == "__main__":
    main()
