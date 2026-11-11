#!/usr/bin/env python3
"""What a resident perceives of someone walking up to it: a player under motion intent and an
AI character under `goto` (docs/PERCEPTION.md, "What an observer perceives of a target",
"Activity derived from the body").

A resident R is held still, and a side of it with a clear way in is chosen (the bystander
probes four). First, in a fresh world, the player walks into R's sight from beyond it, and R's
first-sight experience line says what it saw the player doing. Then the player starts 8 m out
and walks at R by `human_move` (motion intent: its plan is "moving yourself", its activity
`wait`). While it walks, the admin gives R's graph a `think` leaf, which asks R's mind to
deliberate (speech no longer does); R's deliberation scene (what its mind is sent) lists the
walker with what R perceives it doing. The player stops and R thinks again. Then an AI resident
W walks the same line to R by a `goto` leaf and R thinks once more. A second identity (the
bystander) watches from beside R; its `seen_doing` and `seen_bodies` rows for each walker are
recorded (the client stream: motion in `seen_bodies`, no `doing` row for a walk, whoever
controls the body).

    approach.py --run RUN [--expect-wait]

`--expect-wait` checks the pre-fix behaviour (the player perceived as `wait` while walking);
without it the script checks the fix (`walk → person`). Needs `verify.py launch --run RUN --seed
island`. Admin `place_at` and `set_behavior` set the scene. Writes `RUN/approach.json`. Python
standard library only.
"""

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("appraise", HERE / "appraise.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
V = A.V

RESULTS = A.RESULTS
EVIDENCE = {}


def stamp(p, rid):
    rows = p.sql(f"SELECT updated_ms FROM deliberation WHERE actor = {rid}")
    return rows[0]["updated_ms"] if rows else -1


def scene_of(p, rid, since):
    """R's deliberation scene once it was written after `since` (its row's previous stamp; the
    world's clock is not the wall clock)."""
    rows = [d for d in p.sql(f"SELECT actor, updated_ms, reason, scene FROM deliberation WHERE actor = {rid}") if d["updated_ms"] > since]
    return json.loads(rows[0]["scene"]) if rows else None


def think(p, rid):
    """Ask R's mind to deliberate now: a `think` leaf, then hold still (admin `set_behavior`)."""
    p.call("set_behavior", [rid, json.dumps({"seq": [{"think": "a look around"}, {"wait": 300}]})], "admin")


def entry(scene, id):
    return next((c for c in (scene or {}).get("creatures", []) if c.get("id") == id), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--expect-wait", action="store_true", help="check the pre-fix behaviour")
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Walker")
    other = p.me("bystander", "Onlooker")
    r = A.wait_for(lambda: A.resident(p, {me, other}), 60)
    w = r and A.wait_for(lambda: A.resident(p, {me, other, r["id"]}), 60)
    if not r or not w:
        A.check(p, "two residents stand still", False, f"{r} {w}")
        return finish(p)
    x, y = r["at"]
    p.call("set_behavior", [r["id"], json.dumps({"wait": 300})], "admin")
    p.call("set_behavior", [w["id"], json.dumps({"wait": 300})], "admin")
    EVIDENCE["cast"] = {"resident": r, "ai_walker": w["id"], "player": me, "bystander": other}

    def at(k, l=0.0):
        """k metres out from R along the chosen side, l to its left."""
        return [x + k * u[0] - l * u[1], y + k * u[1] + l * u[0]]

    # The side to walk in from: one where the bystander, put 8 m out, lands where it was put and
    # sees R (the sight line is the same both ways). Towns differ from world to world.
    u, probes = None, []
    for side in ((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)):
        u = side
        p.call("place_at", [other, *at(8.0)], "admin")
        ok = A.wait_for(lambda: p.seen("bystander", r["id"]), 3)
        b = p.sql(f"SELECT x, y FROM body WHERE id = {other}")[0]
        landed = ((b["x"] - at(8.0)[0]) ** 2 + (b["y"] - at(8.0)[1]) ** 2) ** 0.5 < 1.0
        probes.append({"side": side, "sees_r": bool(ok), "landed": landed})
        if ok and landed:
            break
    else:
        u = None
    EVIDENCE["side"] = {"chosen": u, "probes": probes}
    if not u:
        A.check(p, "a clear side to walk in from", False, f"{probes}")
        return finish(p)
    p.call("place_at", [other, *at(0.0, -2.0)], "admin")

    def walk(walker, go):
        """`walker` starts 8 m out from R on the chosen side (the same line for both) and walks
        at it; R thinks while it walks. Returns R's scene entry for it and the client rows."""
        p.call("place_at", [walker, *at(8.0)], "admin")
        time.sleep(1.5)
        go()
        time.sleep(0.8)
        since = stamp(p, r["id"])
        think(p, r["id"])
        sc = A.wait_for(lambda: scene_of(p, r["id"], since), 8)
        return {"scene_entry": entry(sc, walker), "activity": p.sql(f"SELECT id, skill, label, phase FROM activity WHERE id = {walker}"),
                "steer": p.sql(f"SELECT id, goal, flags FROM steer WHERE id = {walker}"),
                "bystander_seen_doing": [d for d in p.sql("SELECT * FROM seen_doing", "bystander") if d["id"] == walker],
                "bystander_seen_bodies": [b for b in p.sql("SELECT * FROM seen_bodies", "bystander") if b["id"] == walker]}

    def moving_unshown(ev):
        b = ev["bystander_seen_bodies"]
        return bool(b) and abs(b[0]["vx"]) + abs(b[0]["vy"]) > 0.1 and not ev["bystander_seen_doing"]

    def player_go():
        b = p.sql(f"SELECT x, y FROM body WHERE id = {me}")[0]
        p.call("human_move", [x - b["x"], y - b["y"], False])

    # 0. The player comes into R's sight walking, from 14 m out on that side (day sight is
    # 11 m): R's first sight of it is an experience line that says what it was doing. Once per
    # world (R remembers the player afterwards), and not in a crowd (where strangers are not
    # announced): no line at all is recorded as not observed; a line saying `wait` fails. Its
    # way in may bend round something, so any walk counts here, not only `walk → person`.
    def saw():
        return [e["text"] for e in p.sql(f"SELECT text, kind, subject FROM experience WHERE observer = {r['id']}") if e["kind"] == "saw" and e["subject"] == me]
    if saw():
        EVIDENCE["first_sight"] = {"skipped": "R has already seen the player in this world", "lines": saw()}
    else:
        p.call("place_at", [me, *at(14.0)], "admin")
        time.sleep(1.5)
        player_go()
        lines = A.wait_for(saw, 8)
        p.call("human_move", [0.0, 0.0, False])
        EVIDENCE["first_sight"] = lines
        if not lines:
            V.log(p.st, "NOT OBSERVED R's first sight of the walking player (no line; a crowd, or the way in is blocked)")
        elif a.expect_wait:
            A.check(p, "before the fix: R's first sight of the walking player reads 'wait'", any(t.endswith(", wait.") for t in lines), f"{lines}")
        else:
            A.check(p, "R's first sight of the walking player reads a walk", any(re.search(r", (walk|run)( → [a-z]+| [a-z]+)\.$", t) for t in lines), f"{lines}")

    # 1. The player walks at R by motion intent (W stands aside, off the line).
    p.call("place_at", [w["id"], *at(3.0, 3.0)], "admin")
    ev = EVIDENCE["player_walking"] = walk(me, player_go)
    pe = ev["scene_entry"]
    if a.expect_wait:
        A.check(p, "before the fix: the walking player is perceived as wait", pe and pe.get("doing") == "wait", f"player {pe}")
    else:
        A.check(p, "the walking player is perceived walking toward a person", pe and pe.get("doing") == "walk → person", f"player {pe}")
    A.check(p, "the bystander's client sees the player's body move (seen_bodies), no doing row", moving_unshown(ev), f"{ev['bystander_seen_bodies']} {ev['bystander_seen_doing']}")

    # 2. The player stops: standing with nothing to do reads as wait, as before.
    p.call("human_move", [0.0, 0.0, False])
    time.sleep(1.5)
    since = stamp(p, r["id"])
    think(p, r["id"])
    pe2 = entry(A.wait_for(lambda: scene_of(p, r["id"], since), 8), me)
    EVIDENCE["player_stopped"] = pe2
    A.check(p, "the player standing still is perceived as wait", pe2 and pe2.get("doing") == "wait", f"player {pe2}")

    # 3. The AI resident walks the same line at R by a goto leaf (the player stands aside).
    p.call("place_at", [me, *at(3.0, 3.0)], "admin")
    goto = json.dumps({"seq": [{"do": {"skill": "goto", "target": {"id": r["id"]}}}, {"wait": 300}]})
    ev = EVIDENCE["ai_walking"] = walk(w["id"], lambda: p.call("set_behavior", [w["id"], goto], "admin"))
    we = ev["scene_entry"]
    A.check(p, "the AI walker is perceived by its goto (unchanged)", we and we.get("doing") == "goto → person", f"ai {we}")
    A.check(p, "the bystander's client sees the AI's body move (seen_bodies), no doing row", moving_unshown(ev), f"{ev['bystander_seen_bodies']} {ev['bystander_seen_doing']}")
    EVIDENCE["resident_saw"] = [e["text"] for e in p.sql(f"SELECT text, kind, subject FROM experience WHERE observer = {r['id']}") if e["kind"] == "saw" and e["subject"] in (me, w["id"])]
    return finish(p)


def finish(p):
    out = V.run_dir(p.st["run"]) / "approach.json"
    out.write_text(json.dumps({"results": RESULTS, "evidence": EVIDENCE}, indent=1, ensure_ascii=False) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed; evidence {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
