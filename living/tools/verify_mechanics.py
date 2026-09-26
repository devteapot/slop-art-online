#!/usr/bin/env python3
"""Deterministic end-to-end checks of checkpoint-2 mechanics on a benchmark database.

Two scripted characters (installed behavior graphs, no LLM) exercise writing and reading a
tablet that teaches a technique, crafting with the learned technique, an atomic trade,
planting, teaching and consensual conception, then the same kind of interactions as
deliberate acts decided outside the graph (`mind_act`: a gift, conception chosen by both, a
failure reported back). Each check reads the authority's tables.

Usage: living/tools/verify_mechanics.py [--db living-verify] [--wasm NAME] [--out FILE]
Publishes the database fresh (deletes its data).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = os.environ.get("LIVING_STDB", str(ROOT / "living/tools/stdb"))


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
    ap.add_argument("--wasm", default="living_authority.wasm", help="module file in the server's /wasm mount")
    ap.add_argument("--out")
    a = ap.parse_args()
    db = a.db
    stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
    time.sleep(3)
    stdb("call", "-s", "local", db, "spawn_crowd", "4", "true")
    time.sleep(1.5)
    walkers = sorted(int(r["id"]) for r in rows(db, "SELECT id, name FROM character") if r["name"].startswith("Walker"))
    A, B, C, D = walkers[:4]
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
    # 8. Settlements: lay road underfoot, build a wall and a gate beside, shut and open the gate.
    for t in ["masonry", "carpentry", "shelter"]:
        call(db, "grant_know_how", str(A), t)
    call(db, "grant_items", str(A), "stone", "6")
    call(db, "grant_items", str(A), "wood", "6")
    body = rows(db, f"SELECT x, y FROM body WHERE id = {A}")[0]
    ax, ay = float(body["x"]), float(body["y"])
    wall_at = [int(ax) + 2 + 0.5, int(ay) + 0.5]
    gate_at = [int(ax) + 2 + 0.5, int(ay) + 1.5]
    call(db, "set_behavior", str(B), idle)
    call(db, "set_behavior", str(A), seq(
        {"first": [{"do": {"skill": "pave"}}, {"wait": 1}]},
        {"do": {"skill": "build", "item": "wall", "target": {"at": wall_at}}},
        {"do": {"skill": "build", "item": "gate", "target": {"at": gate_at}}},
    ))
    built = wait_for(lambda: rows(db, f"SELECT * FROM gate WHERE changed_by = {A}"), timeout=60)
    story = [r["text"] for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] == "build"]
    results["road, wall and gate built"] = bool(built)
    if built:
        gid = int(built[0]["id"])
        call(db, "set_behavior", str(A), seq({"do": {"skill": "close", "target": {"nearest": "gate"}}}))
        shut = wait_for(lambda: [g for g in rows(db, f"SELECT id, open FROM gate WHERE id = {gid}") if g["open"] == "false"], timeout=20)
        call(db, "set_behavior", str(A), seq({"do": {"skill": "open", "target": {"nearest": "gate"}}}))
        reopened = wait_for(lambda: [g for g in rows(db, f"SELECT id, open FROM gate WHERE id = {gid}") if g["open"] == "true"], timeout=20)
        results["gate shut and opened"] = bool(shut) and bool(reopened)
    # 9. Deliberate acts (decided by a mind, outside the graph; the walkers are controlled by
    # this admin identity like minds). C and D rest in a loop: if the graph could take the
    # body back, rest would cancel the acts. C gives D berries, then both choose each other.
    call(db, "place_near", str(C), str(A))
    call(db, "place_near", str(D), str(C))
    call(db, "grant_items", str(C), "cooked_meat", "3")
    call(db, "grant_items", str(D), "cooked_meat", "3")
    call(db, "grant_items", str(C), "berries", "4")
    rest = json.dumps({"first": [{"do": {"skill": "rest"}}]})
    call(db, "set_behavior", str(C), rest)
    call(db, "set_behavior", str(D), rest)
    time.sleep(1.5)
    act = lambda who, *nodes: stdb("call", "-s", "local", db, "mind_act", str(who), json.dumps([json.dumps(n) for n in nodes]), json.dumps("test"))
    act(C, {"do": "eat", "item": "food"}, {"do": "give", "target": {"id": D}, "item": "berries", "qty": 2})
    act(D, {"do": "eat", "item": "food"})
    gave = wait_for(lambda: [r for r in rows(db, f"SELECT item, qty FROM inventory WHERE owner = {D}") if r["item"] == "berries"], timeout=30)
    told = lambda who, words: [r for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {who}") if r["kind"] == "act" and words in r["text"]]
    results["act: a gift decided outside the graph, reported back"] = bool(gave) and bool(wait_for(lambda: told(C, "You did what you had decided"), timeout=10))
    call(db, "place_structure", str(C), "shelter")
    time.sleep(1)
    act(C, {"do": "conceive", "target": {"id": D}})
    time.sleep(2)
    act(D, {"do": "conceive", "target": {"id": C}})
    both = wait_for(lambda: [r for r in rows(db, "SELECT a, b FROM expecting") if {int(r["a"]), int(r["b"])} == {C, D}], timeout=30)
    results["act: conception chosen by both as acts"] = bool(both)
    # A cannot teach what A does not know: the act fails, and A is told why.
    act(A, {"do": "teach", "target": {"id": B}, "item": "cloak"})
    results["act: a failed act is reported with its reason"] = bool(wait_for(lambda: told(A, "did not work out"), timeout=30))
    # Real-time behavior is not an act: it is refused with feedback.
    act(A, {"do": "flee", "target": {"nearest": "wolf"}})
    results["act: real-time behavior refused as an act"] = bool(wait_for(lambda: told(A, "behavior graph"), timeout=10))
    ok = all(results.values())
    for k, v in results.items():
        print(("PASS " if v else "FAIL ") + k)
    report = {"db": db, "results": results, "story": [r["text"] for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] not in ("arrival", "time", "speech")]}
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
