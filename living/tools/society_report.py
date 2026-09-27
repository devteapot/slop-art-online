#!/usr/bin/env python3
"""Stages 3–4 at a glance: who belongs where, emerging roles (what each person practises
most), what is built and stored, communities, and what passes within and between groups
(gifts, trades, teaching, fights, speech) — from one lab database.

  living/tools/society_report.py stage3-village stage4-two
"""
import argparse
import collections
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
STRUCTURE_BIT = 1 << 40


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, l.split("|"))} for l in lines[1:]]


def report(db):
    people = {c["id"]: c for c in rows(db, "SELECT id, name, kind, alive, parent_a, parent_b, home_x, home_y FROM character") if c["kind"] == "person"}
    if not people:
        print(f"== {db}: no people")
        return
    group = {}
    for b in rows(db, "SELECT id, text FROM background"):
        try:
            bg = json.loads(b["text"].replace('\\"', '"'))
        except ValueError:
            continue
        group[b["id"]] = bg.get("town") or bg.get("band") or "?"
    # The young belong where their parents do.
    for _ in range(4):
        for i, c in people.items():
            if i not in group:
                g = group.get(c["parent_a"]) or group.get(c["parent_b"])
                if g:
                    group[i] = g
    alive = {i: c for i, c in people.items() if c["alive"] == "true"}
    by_group = collections.Counter(group.get(i, "?") for i in alive)
    print(f"== {db}: {len(alive)} people alive by group {dict(by_group)}")
    # Roles: each person's most practised skill (ignoring walking and eating).
    practice = collections.defaultdict(collections.Counter)
    for p in rows(db, "SELECT actor, skill, uses FROM practice"):
        if p["actor"] in alive and p["skill"] not in ("eat", "goto", "wander", "follow", "sleep", "rest", "wait"):
            practice[p["actor"]][p["skill"]] += int(p["uses"])
    roles = collections.Counter()
    for i, cnt in practice.items():
        if cnt:
            skill, n = cnt.most_common(1)[0]
            share = n / sum(cnt.values())
            roles[(group.get(i, "?"), skill)] += 1
            print(f"   {alive[i]['name']:10s} ({group.get(i, '?')}): {skill} {n} uses ({share:.0%} of their work)")
    print(f"   roles by group: {dict(roles)}")
    structs = rows(db, "SELECT id, kind, owner, x, y FROM structure")
    print(f"   structures: {dict(collections.Counter(s['kind'] for s in structs))}")
    stored = collections.Counter()
    store_ids = {s["id"] for s in structs if s["kind"] == "storage"}
    for r in rows(db, "SELECT owner, item, qty FROM inventory"):
        o = int(r["owner"])
        if o >= STRUCTURE_BIT and str(o - STRUCTURE_BIT) in store_ids:
            stored[r["item"]] += int(r["qty"])
    print(f"   stored: {dict(stored)}")
    comms = rows(db, "SELECT id, name, founder FROM community")
    members = collections.Counter(m["community"] for m in rows(db, "SELECT member, community FROM membership"))
    print(f"   communities: {[(c['name'], members.get(c['id'], 0)) for c in comms]}")
    name_group = {c["name"]: group.get(i, "?") for i, c in people.items()}
    within, between = collections.Counter(), collections.Counter()
    examples = []
    for r in rows(db, "SELECT kind, text FROM chronicle"):
        k, t = r["kind"], r["text"]
        m = None
        if k == "give":
            m = re.match(r"([A-Z][a-z]+) gave .* to ([A-Z][a-z]+)", t)
        elif k == "teach":
            m = re.match(r"([A-Z][a-z]+) taught ([A-Z][a-z]+)", t)
        elif k in ("trade", "accept"):
            m = re.match(r"([A-Z][a-z]+) .*?([A-Z][a-z]+)", t)
        elif k == "attack":
            m = re.match(r"([A-Z][a-z]+) attacked ([A-Z][a-z]+)$", t)
        elif k == "speech":
            m = re.match(r"([A-Z][a-z]+) to ([A-Z][a-z]+):", t)
        if not m or m.group(1) not in name_group or m.group(2) not in name_group:
            continue
        a, b = name_group[m.group(1)], name_group[m.group(2)]
        (within if a == b else between)[k] += 1
        if a != b and k != "speech" and len(examples) < 5:
            examples.append(t[:120])
    print(f"   within groups: {dict(within)}")
    print(f"   between groups: {dict(between)}")
    for e in examples:
        print(f"     e.g. {e}")
    # Travel: living people far from their own home (e.g. visiting the other town).
    far = []
    for b in rows(db, "SELECT id, x, y FROM body"):
        c = alive.get(b["id"])
        if c:
            d = math.dist((float(b["x"]), float(b["y"])), (float(c["home_x"]), float(c["home_y"])))
            if d > 40:
                far.append(f"{c['name']} {d:.0f}")
    print(f"   far from home (>40 tiles): {far}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dbs", nargs="+")
    for db in ap.parse_args().dbs:
        report(db)


if __name__ == "__main__":
    main()
