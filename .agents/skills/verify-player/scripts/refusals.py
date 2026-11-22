#!/usr/bin/env python3
"""Truthful refusals for a player (docs/TRUTHFUL_REFUSALS.md): a player's
`human_act` is refused saying what actually happened, with its code in `my_act_outcomes`, as a
mind's act is (verify-core `scenes.py truthful_refusals` drives the same through `mind_act`).

1. A place name the character does not hold: code `unknown`, "you know no place called …".
2. A role nobody fills for it now (`attacker`): code `unknown`, "nobody has hurt you in the last
   minute".
3. A resident beyond sight by id: code `unseen`, "no #N in sight" (sight stays sight).
4. Control: a wave at the resident beside the player is done.
5. Control: `{"place": "home"}` with no "home" row walks to the player's own home position.
6. The resident beside the player killed (admin `kill`): code `refused`, "#N is dead: their
   remains lie in sight".

Each refusal's line in `my_experience` carries the same words, and none says "in sight" unless
it is about sight.

    refusals.py --run RUN

Needs `verify.py launch --run RUN` on a seed with residents (the default `world`). Admin calls set
the scene only: `place_near`, `place_at`, `set_behavior`, `kill`. Writes `RUN/refusals.json`.
Python standard library only.
"""

import argparse
import importlib.util
import json
import math
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Truthful")
    try:
        near = A.resident(p, {me})
        bodies = {b["id"]: b for b in p.sql("SELECT id, x, y FROM body")}
        people = {c["id"] for c in p.sql("SELECT id, kind, alive, stage FROM character WHERE kind = 'person'") if c["alive"] and c["id"] != me}
        far = next(i for i, b in sorted(bodies.items()) if i in people and i != near["id"] and math.dist((b["x"], b["y"]), near["at"]) > 60)
        p.call("set_behavior", [near["id"], json.dumps({"wait": 300})], "admin")
        p.call("place_near", [me, near["id"]], "admin")
        time.sleep(1.5)
        EVIDENCE["scene"] = {"me": me, "near": near, "far": far}
        outs = lambda: p.sql("SELECT * FROM my_act_outcomes", "player")
        last = lambda: max([r["id"] for r in outs()] or [0])
        lines = lambda: {r["id"]: r for r in p.sql("SELECT id, kind, text FROM my_experience", "player")}

        def refused(node, code, why, name):
            mark = last()
            p.call("human_act", [json.dumps(node)])
            got = A.wait_for(lambda: [r for r in outs() if r["id"] > mark and not r["ok"]], 6)
            row = got[-1] if got else None
            line = A.wait_for(lambda: lines().get(row["id"]) if row else None, 3)
            EVIDENCE[name] = {"node": node, "row": row, "line": line}
            A.check(p, f"{name}: code {code}, \"{why}\", told in its line",
                    row and row["code"] == code and row["why"] == why and line and why in line["text"]
                    and (code == "unseen" or "in sight" not in line["text"].replace(why, "")), EVIDENCE[name])
            time.sleep(0.5)

        wave = lambda t: {"do": "wave", "target": t}
        refused({"do": "goto", "target": {"place": "verify nowhere"}}, "unknown", 'you know no place called "verify nowhere"', "unknown place")
        refused(wave("attacker"), "unknown", "nobody has hurt you in the last minute", "no attacker")
        refused(wave({"id": far}), "unseen", f"no #{far} in sight", "beyond sight")
        # Control: a wave at the one beside me.
        mark = last()
        p.call("human_act", [json.dumps(wave({"id": near["id"]}))])
        done = A.wait_for(lambda: [r for r in outs() if r["id"] > mark], 8)
        EVIDENCE["wave beside"] = done
        A.check(p, "control: a wave at the resident beside me is done", done and done[-1]["ok"] and done[-1]["code"] == "done", done)
        time.sleep(0.5)
        # Control: home without a "home" row.
        own = p.sql(f"SELECT home_x, home_y FROM character WHERE id = {me}")[0]
        homes = [r for r in p.sql(f"SELECT name FROM place WHERE actor = {me}") if r["name"].lower() == "home"]
        mark = last()
        p.call("human_act", [json.dumps({"do": "goto", "target": {"place": "home"}})])
        walk = A.wait_for(lambda: [d for d in p.sql(f"SELECT skill, node FROM activity WHERE id = {me}") if d["skill"] == "goto"], 6)
        steer = p.sql(f"SELECT gx, gy FROM steer WHERE id = {me}")
        bad = [r for r in outs() if r["id"] > mark and not r["ok"]]
        EVIDENCE["home"] = {"home": own, "home_rows": homes, "activity": walk, "steer": steer, "refused": bad}
        A.check(p, "control: {\"place\": \"home\"} with no home row walks to my own home position",
                not homes and walk and not bad and steer and math.dist((steer[0]["gx"], steer[0]["gy"]), (own["home_x"], own["home_y"])) < 1.5, EVIDENCE["home"])
        p.call("place_near", [me, near["id"]], "admin")
        time.sleep(1.0)
        # Dead in sight.
        p.call("kill", [near["id"], "verify truthful refusals"], "admin")
        A.wait_for(lambda: [r for r in p.sql("SELECT owner, kind FROM structure") if r["kind"] == "remains" and r["owner"] == near["id"]], 6)
        refused(wave({"id": near["id"]}), "refused", f"#{near['id']} is dead: their remains lie in sight", "dead in sight")
    finally:
        finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "refusals.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1, default=str) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
