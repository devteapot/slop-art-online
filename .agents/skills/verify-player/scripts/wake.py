#!/usr/bin/env python3
"""A player wakes island residents by engaging them (docs/TOWN_LIFE.md, "Layer 2").

On an island world (`rules.minds = false`) residents live on their behaviour graphs alone and
keep a small ring of what they perceive (`prior`). The player's own identity engages them
through the player reducers only (`human_say` to someone, `human_act` wave, give, offer,
teach): each engaged resident becomes a mind (`woken` row, `ai`, controlled by the world
admin), hears or sees the engagement as an ordinary experience, and has a first deliberation
pending. A resident who only overhears keeps the line in its ring and stays instinct only; one
out of earshot has nothing of it. Nobody the player did not engage wakes, whatever residents
do to one another meanwhile. `woken` and `prior` are private. Admin calls only set the scene
(`place_at`, `grant_items`, `grant_know_how`), named in the report. No mind service runs: the
mind side is verify-minds' `wake` case.

    wake.py --run RUN

Needs `verify.py launch --run RUN --seed island`; joins a player if the run has none.
Writes `RUN/wake.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gesture", HERE / "gesture.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
V = G.V
RESULTS = G.RESULTS
check, wait_for, now_ms = G.check, G.wait_for, G.now_ms

# The laws this scene depends on, read from the rules the run installs.
RULES = (HERE.parents[3] / "living/scripts/skills.rhai").read_text()
HEARING = float(re.search(r"hearing:\s*([0-9.]+)", RULES).group(1))
SLOTS = int(re.search(r'"slots"\s*=>\s*(\d+)', RULES).group(1))


def people(p):
    rows = p.sql("SELECT id, name, kind, ai, controller, alive, stage FROM character WHERE kind = 'person'")
    bodies = {b["id"]: (b["x"], b["y"]) for b in p.sql("SELECT id, x, y FROM body")}
    return [dict(c, at=bodies[c["id"]]) for c in rows if c["alive"] and c["id"] in bodies]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def ring(p, rid):
    return sorted(p.sql(f"SELECT * FROM prior WHERE resident = {rid}"), key=lambda r: r["seq"])


def woken(p):
    return {w["id"]: w for w in p.sql("SELECT * FROM woken")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = G.P(a.run)
    world = p.sql("SELECT admin FROM world")[0]
    if not p.st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        p.st["token"], p.st["identity"] = j["token"], j["identity"]
        V.save(p.st)
    mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not mine:
        p.call("join", ["Wren"])
        mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = mine[0]["id"]
    my_name = p.sql(f"SELECT name FROM character WHERE id = {me}")[0]["name"]

    # 0. Before anyone engages anyone: no woken resident; rings bounded and per resident.
    check(p, "a fresh island has no woken resident", not woken(p), f"{len(woken(p))} woken rows")
    rows = wait_for(lambda: p.sql("SELECT resident, seq, key FROM prior"), 60)
    per = {}
    for r in rows:
        per[r["resident"]] = per.get(r["resident"], 0) + 1
    check(p, "rings are fixed size and keyed by resident", rows and max(per.values()) <= SLOTS and all(r["key"] >> 8 == r["resident"] for r in rows),
          f"{len(rows)} prior rows over {len(per)} residents, at most {max(per.values()) if per else 0} each")

    r1 = wait_for(lambda: G.resident(p), 60)
    if not r1:
        check(p, "a resident is standing at a post", False, "none found within 60 s")
        return finish(p)
    x, y = r1["at"]
    sees = lambda: any(c["id"] == r1["id"] for c in p.sql("SELECT id FROM seen_characters", "player"))
    for dx, dy in [(3.0, 0.5), (-3.0, 0.5), (0.5, 3.0), (0.5, -3.0)]:
        p.call("place_at", [me, x + dx, y + dy], "admin")
        time.sleep(1.0)
        if sees():
            break
    here = (x, y)
    sighting = wait_for(lambda: [r for r in ring(p, r1["id"]) if r["kind"] == "sighted" and r["subject"] == me], 4)
    check(p, "a resident who sees the player keeps that it came into view (its ring)", sighting,
          f"{r1['name']} (#{r1['id']}): {[r['text'] for r in sighting]}")

    # 1. Speech to one resident: it wakes; a resident in earshot keeps the line; one far off has nothing.
    crowd = [c for c in people(p) if not c["ai"] and c["stage"] >= 1 and c["id"] not in (me, r1["id"])]
    near = sorted((c for c in crowd if dist(c["at"], here) <= HEARING - 3), key=lambda c: dist(c["at"], here))
    far = [c for c in crowd if dist(c["at"], here) > 60]
    line = "verify wake: is there food and a bed in this town?"
    since = now_ms()
    code, _ = p.call("human_say", [line, r1["id"]])
    w = wait_for(lambda: woken(p).get(r1["id"]), 4)
    c1 = next(c for c in people(p) if c["id"] == r1["id"])
    heard = [e for e in p.sql(f"SELECT * FROM experience WHERE observer = {r1['id']}") if e["at_ms"] >= since and "verify wake" in e["text"]]
    pending = p.sql(f"SELECT * FROM deliberation WHERE actor = {r1['id']}")
    check(p, "speaking to a resident wakes it (woken row, why speech, by the player)", code == 200 and w and w["why"] == "speech" and w["by"] == me, f"{w}")
    check(p, "the woken resident is a mind: ai, controlled by the world's minds", c1["ai"] and c1["controller"] == world["admin"], f"ai {c1['ai']}")
    check(p, "it hears the line as an ordinary experience of its mind", heard and heard[0]["kind"] == "speech" and heard[0]["controller"] == world["admin"], f"{[e['text'] for e in heard]}")
    check(p, "its first deliberation is pending", pending and "spoke to you" in pending[0]["reason"], f"{[d['reason'] for d in pending]}")
    check(p, "its ring from before waking is counted on the woken row", w and w["prior"] >= 1, f"prior {w and w['prior']}")
    check(p, "it keeps the places it knew before", w and "work" in w["places"], f"{w and w['places']}")
    if near:
        r2 = near[0]
        got = [r for r in ring(p, r2["id"]) if "verify wake" in r["text"]]
        check(p, "a resident who overhears keeps the line in its ring and stays instinct only",
              got and r2["id"] not in woken(p), f"{r2['name']} (#{r2['id']}, {dist(r2['at'], here):.1f} m): {[r['text'] for r in got]}")
        # Names follow what it knows (docs/PERCEPTION.md): the player has not said its name.
        check(p, "the overheard line names the speaker only as that resident perceives them",
              got and my_name not in got[0]["text"], f"{got[0]['text'] if got else None}")
    else:
        check(p, "a resident is within earshot of the player", False, "none within 6 m")
    if far:
        leaked = [c["id"] for c in far[:40] if any("verify wake" in r["text"] for r in ring(p, c["id"]))]
        check(p, "residents out of earshot have nothing of it (no copying)", not leaked, f"{min(len(far), 40)} far residents checked; {leaked}")

    # 2. A wave, a gift, an offer and a lesson, each to a resident in sight.
    def next_target(exclude):
        for c in sorted(people(p), key=lambda c: dist(c["at"], here)):
            if not c["ai"] and c["stage"] >= 2 and c["id"] not in exclude and c["id"] != me and dist(c["at"], here) <= 8:
                if any(s["id"] == c["id"] for s in p.sql("SELECT id FROM seen_characters", "player")):
                    return c
        return None

    engaged = {r1["id"]: "speech"}
    p.call("grant_items", [me, "berries", 6], "admin")
    lessons = ("fire", "fishing", "basketry", "cooking", "trapping", "planting")
    for t in lessons:
        p.call("grant_know_how", [me, t], "admin")
    plans = [("wave", lambda c: {"do": "wave", "target": {"id": c["id"]}}),
             ("give", lambda c: {"do": "give", "target": {"id": c["id"]}, "item": "berries", "qty": 1}),
             ("offer", lambda c: {"do": "offer", "target": {"id": c["id"]}, "item": "berries", "qty": 2, "want": "wood", "want_qty": 1}),
             ("teach", None)]
    for why, node in plans:
        c = next_target(set(engaged))
        if c is None:
            check(p, f"a resident in sight for the {why}", False, "none within 8 m in sight")
            continue
        if why == "teach":
            knows = {k["technique"] for k in p.sql(f"SELECT technique FROM know_how WHERE actor = {c['id']}")}
            tech = next((t for t in lessons if t not in knows), None)
            if tech is None:
                check(p, "a resident who lacks a technique the player knows", False, f"{c['name']} knows {sorted(knows)}")
                continue
            n = {"do": "teach", "target": {"id": c["id"]}, "item": tech}
        else:
            n = node(c)
        code, _ = p.act(n)
        w = wait_for(lambda: woken(p).get(c["id"]), 8)
        told = [e["text"] for e in p.sql(f"SELECT * FROM experience WHERE observer = {c['id']}")] if w else []
        check(p, f"`{why}` aimed at a resident wakes it as it starts", code == 200 and w and w["why"] == why and w["by"] == me,
              f"{c['name']} (#{c['id']}): {w and {k: w[k] for k in ('why', 'by', 'prior')}}; it perceived {told[-2:]}")
        engaged[c["id"]] = why

    # 3. Nobody else wakes, though residents greet one another meanwhile; a woken resident stays a mind.
    time.sleep(20)
    now_woken = woken(p)
    check(p, "only the residents the player engaged are woken", set(now_woken) == set(engaged),
          f"woken {sorted(now_woken)}; engaged {sorted(engaged)}")
    still = [c for c in people(p) if c["id"] in engaged]
    check(p, "a woken resident stays a mind (no return to instinct only)", all(c["ai"] for c in still), f"{[(c['id'], c['ai']) for c in still]}")
    again = woken(p).get(r1["id"])
    p.call("human_say", ["verify wake: thank you", r1["id"]])
    after = wait_for(lambda: (lambda w: w if w and w["engagements"] > again["engagements"] else None)(woken(p).get(r1["id"])), 4)
    check(p, "engaging a woken resident again marks it engaged (no second wake)", after and after["woken_ms"] == again["woken_ms"],
          f"engagements {again['engagements']} -> {after and after['engagements']}")

    # 4. Private: the player and an anonymous client cannot read woken, prior or prior_head.
    for table in ("woken", "prior", "prior_head"):
        for who in ("player", "anonymous"):
            token = p.st["token"] if who == "player" else None
            code, body = V.http(f"/v1/database/{p.db}/sql", f"SELECT * FROM {table}", token, raw=True)
            check(p, f"{table} is private to {who}", code != 200 or not json.loads(body)[-1]["rows"], f"{code} {body.strip()[:120]}")
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "wake.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
