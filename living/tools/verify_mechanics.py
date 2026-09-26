#!/usr/bin/env python3
"""Deterministic end-to-end checks of checkpoint-2 mechanics on a benchmark database.

Two scripted characters (installed behavior graphs, no LLM) exercise writing and reading a
tablet that teaches a technique, crafting with the learned technique, an atomic trade,
planting, teaching and consensual conception. Each check reads the authority's tables.

Usage: living/tools/verify_mechanics.py [--db living-verify] [--out FILE]
Publishes the database fresh (deletes its data).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")


def stdb(*args):
    r = subprocess.run([STDB, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[-300:]}")
    return r.stdout


def rows(db, q):
    out = stdb("sql", "-s", "local", db, q)
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    res = []
    for l in lines[1:]:
        r = {}
        for h, v in zip(head, [v.strip() for v in l.split("|")]):
            r[h] = v.strip('"')
        res.append(r)
    return res


def call(db, reducer, *args):
    """Numbers (or numeric strings) go raw; other strings are JSON-encoded (the CLI parses JSON)."""
    enc = []
    for a in args:
        if isinstance(a, (int, float)) or (isinstance(a, str) and a.isdigit()):
            enc.append(str(a))
        else:
            enc.append(json.dumps(a))
    stdb("call", "-s", "local", db, reducer, *enc)


def wait_for(pred, timeout=40, every=1.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living-verify")
    ap.add_argument("--out")
    a = ap.parse_args()
    db = a.db
    stdb("publish", "-s", "local", "-b", "/wasm/living_authority.wasm", db, "--delete-data", "-y")
    time.sleep(3)
    stdb("call", "-s", "local", db, "spawn_crowd", "2", "true")
    time.sleep(1.5)
    walkers = sorted(int(r["id"]) for r in rows(db, "SELECT id, name FROM character") if r["name"].startswith("Walker"))
    A, B = walkers[:2]
    name_a = f"Walker1"
    call(db, "place_near", str(B), str(A))
    for t in ["writing", "spear", "planting"]:
        call(db, "grant_know_how", str(A), t)
    call(db, "grant_know_how", str(B), "writing")
    call(db, "grant_items", str(A), "wood", "6")
    call(db, "grant_items", str(A), "berries", "6")
    call(db, "grant_items", str(B), "stone", "3")
    call(db, "grant_items", str(B), "wood", "4")
    idle = json.dumps({"wait": 120})
    results = {}

    def seq(*steps):
        return json.dumps({"seq": list(steps) + [{"wait": 120}]})

    # 1. Write a tablet describing spear-making and hand it over.
    call(db, "set_behavior", str(B), idle)
    call(db, "set_behavior", str(A), seq(
        {"do": {"skill": "write", "item": "tablet", "text": "Two wood and a stone make a spear. Bind them tight.", "topic": "spear"}},
        {"do": {"skill": "give", "target": {"id": B}, "item": "tablet", "qty": 1}},
    ))
    got = wait_for(lambda: [r for r in rows(db, "SELECT * FROM artifact") if r["kind"] == "tablet" and int(r["holder"]) == B])
    results["tablet written and given"] = bool(got)
    # 2. Read it (learning spear) and craft a spear with what was learned.
    call(db, "set_behavior", str(B), seq({"do": {"skill": "read"}}, {"do": {"skill": "craft", "item": "spear"}}))
    learned = wait_for(lambda: [r for r in rows(db, f"SELECT technique, source FROM know_how WHERE actor = {B}") if r["technique"] == "spear"])
    results["reading taught spear"] = bool(learned) and "tablet" in learned[0]["source"]
    crafted = wait_for(lambda: [r for r in rows(db, f"SELECT item, qty FROM inventory WHERE owner = {B}") if r["item"] == "spear"])
    results["learned technique used (spear crafted)"] = bool(crafted)
    # 3. Atomic trade: A offers 2 wood for 1 stone; B accepts.
    call(db, "set_behavior", str(A), seq({"do": {"skill": "offer", "target": {"id": B}, "item": "wood", "qty": 2, "want": "stone", "want_qty": 1}}))
    time.sleep(2.5)
    call(db, "set_behavior", str(B), seq({"do": {"skill": "accept", "target": {"id": A}}}))
    traded = wait_for(lambda: [r for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] == "trade"])
    results["atomic trade"] = bool(traded)
    # 4. Teaching: A teaches B planting.
    call(db, "set_behavior", str(A), seq({"do": {"skill": "teach", "target": {"id": B}, "item": "planting"}}))
    taught = wait_for(lambda: [r for r in rows(db, f"SELECT technique, source FROM know_how WHERE actor = {B}") if r["technique"] == "planting"], timeout=40)
    results["teaching"] = bool(taught) and taught[0]["source"].startswith("taught by")
    # 5. Planting a berry bush (off-winter: a fresh world starts in spring).
    before = len(rows(db, "SELECT id, kind FROM resource_node"))
    # Planting needs arable ground: walk onto the nearest berry bush's tile first (bushes grow on grass).
    body = rows(db, f"SELECT x, y FROM body WHERE id = {A}")[0]
    ax, ay = float(body["x"]), float(body["y"])
    bushes = [(float(r["x"]), float(r["y"])) for r in rows(db, "SELECT x, y FROM resource_node WHERE kind = 'berry_bush'")]
    bush = min(bushes, key=lambda p: (p[0] - ax) ** 2 + (p[1] - ay) ** 2)
    call(db, "set_behavior", str(A), seq({"do": {"skill": "goto", "target": {"at": [bush[0], bush[1]]}}}, {"do": {"skill": "plant"}}))
    planted = wait_for(lambda: len(rows(db, "SELECT id, kind FROM resource_node")) > before, timeout=90)
    results["planting"] = bool(planted)
    # 6. Consensual conception beside a shelter (B joins A, who walked off to plant).
    call(db, "place_near", str(B), str(A))
    call(db, "place_structure", str(A), "shelter")
    time.sleep(1)
    # Both must be fed ("too hungry to think of a family" otherwise).
    call(db, "grant_items", str(A), "cooked_meat", "3")
    call(db, "grant_items", str(B), "cooked_meat", "3")
    eat = {"do": {"skill": "eat", "item": "food"}}
    call(db, "set_behavior", str(A), seq(eat, eat, {"do": {"skill": "conceive", "target": {"id": B}}}))
    call(db, "set_behavior", str(B), seq(eat, eat, {"wait": 2}, {"do": {"skill": "conceive", "target": {"id": A}}}))
    expecting = wait_for(lambda: rows(db, "SELECT * FROM expecting"), timeout=30)
    results["consensual conception"] = bool(expecting)
    # 7. Tending wounds: A strikes B once, lets the fight cool down, then tends B.
    def hp(i):
        v = rows(db, f"SELECT hp, hp_rate, at_ms FROM vitals WHERE id = {i}")[0]
        return float(v["hp"]) + float(v["hp_rate"]) * (time.time() * 1000 - float(v["at_ms"])) / 60000
    call(db, "set_behavior", str(B), idle)
    call(db, "set_behavior", str(A), seq({"do": {"skill": "attack", "target": {"id": B}}}))
    hurt = wait_for(lambda: hp(B) < 95, timeout=20)
    call(db, "set_behavior", str(A), idle)
    time.sleep(11)
    before_hp = hp(B)
    call(db, "set_behavior", str(A), seq({"do": {"skill": "tend", "target": {"id": B}}}))
    healed = wait_for(lambda: hp(B) >= min(before_hp + 8, 99.5), timeout=20)
    results["tending wounds"] = bool(hurt) and bool(healed)
    ok = all(results.values())
    for k, v in results.items():
        print(("PASS " if v else "FAIL ") + k)
    report = {"db": db, "results": results, "story": [r["text"] for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] not in ("arrival", "time", "speech")]}
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
