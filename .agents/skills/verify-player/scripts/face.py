#!/usr/bin/env python3
"""The player's look, `human_face(dx, dy)` (docs/PERCEPTION.md, "The player's look"): it turns
the body's one facing, `body.heading`, and `(0, 0)` releases it.

With the world's `fov_on` law on (admin `set_world_law`), a resident R is held still 5.5 m west
of the player, who faces east (the `face` act).

1. Standing: `human_face(-1, 0)` turns the body west at its turn rate (`my_body`), and R comes
   into view (`seen_bodies`).
2. A look within the `look_slack_deg` law (10 degrees) of the one held writes nothing (`my_body`
   unchanged); a release while standing keeps the facing.
3. Walking: `human_move(1, 0)` (east) with the look north (`human_face(0, -1)`): the heading,
   which is the travel, bends toward the look by the `look_walk_deg` law (30 degrees), not more.
   Released (`human_face(0, 0)`), it returns to the way it walks. Looking north again and
   stopping (`human_move(0, 0)`), the body finishes the turn to the north once it stands.
4. The input bucket (`input_hz`/`input_burst`, shared with `human_move`), narrowed by the admin's
   `set_world_law` to one every five seconds and three in a burst: of eight looks 90 degrees
   apart, three (or four, with a refill meanwhile) are taken and the rest refused ("too many movement inputs"), and a `human_move` right
   after is refused too. The laws are put back to 30 and 15.
5. Anonymous: refused ("you have no living character").

    face.py --run RUN

Needs `verify.py launch --run RUN` (any seed; scoped build). Admin `place_at`, `set_behavior`
and `set_world_law` set the scene. Writes `RUN/face.json`. Python standard library only.
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


def body(p):
    rows = p.sql("SELECT * FROM my_body", "player")
    return rows[0] if rows else None


def heading_end(b):
    """Where the body faces once the turn under way ends."""
    return math.remainder(b["heading"] + b["turn"] * b["turn_s"], math.tau)


def near(a, b, tol):
    return abs(math.remainder(a - b, math.tau)) <= tol


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Looker")
    r = A.wait_for(lambda: A.resident(p, {me}), 60)
    if not r:
        A.check(p, "a resident stands still", False, "none found within 60 s")
        return finish(p)
    rid = r["id"]
    p.call("set_behavior", [rid, json.dumps({"wait": 600})], "admin")
    x, y = r["at"]
    p.call("place_at", [me, x + 5.5, y], "admin")
    time.sleep(1.0)
    b0 = body(p)
    px, py = b0["x"], b0["y"]
    EVIDENCE["cast"] = {"player": me, "resident": rid, "player_at": [px, py], "resident_at": [x, y]}
    seen = lambda: any(m["id"] == rid for m in p.sql("SELECT id FROM seen_bodies", "player"))

    def face(dx, dy, wait=1.2):
        code, out = p.call("human_face", [dx, dy])
        time.sleep(wait)
        return code, out

    try:
        p.call("set_world_law", ["fov_on", "true"], "admin")
        # Face east with the `face` act: R is behind.
        p.call("human_act", [json.dumps({"do": "face", "target": {"at": [px + 4.0, py]}})])
        time.sleep(1.6)
        A.check(p, "set up: R behind is not in view", A.wait_for(lambda: not seen(), 3), "seen_bodies")

        # 1. Standing.
        code, out = face(-1.0, 0.0)
        b1 = body(p)
        A.check(p, "standing: human_face turns the body (my_body heading west)", code == 200 and b1 and near(heading_end(b1), math.pi, 0.05), f"{code} {out.strip()[:100]} heading {b1 and round(heading_end(b1), 2)}")
        A.check(p, "and R comes into view", A.wait_for(seen, 3), "seen_bodies")

        # 2. Within the slack: nothing written; a release keeps the facing.
        before = body(p)
        code, out = face(math.cos(math.pi - math.radians(5)), math.sin(math.pi - math.radians(5)), 0.6)
        after = body(p)
        A.check(p, "a look within 10 degrees of the one held writes nothing", code == 200 and after == before, f"{code} t_ms {before['t_ms']} -> {after['t_ms']}")
        code, out = face(0.0, 0.0, 0.6)
        b2 = body(p)
        A.check(p, "a release while standing keeps the facing", code == 200 and near(heading_end(b2), math.pi, 0.1), f"{code} heading {round(heading_end(b2), 2)}")

        # 3. Walking east, looking north (-y is north).
        p.call("place_at", [me, px, py - 0.0], "admin")
        p.call("human_move", [1.0, 0.0, False])
        time.sleep(1.0)
        code, out = face(0.0, -1.0, 1.0)
        bw = body(p)
        limit = math.radians(30)
        travel = math.atan2(bw["vy"], bw["vx"]) if (bw["vx"] or bw["vy"]) else None
        EVIDENCE["walking_look"] = bw
        A.check(p, "walking: the heading turns toward the look, no more than 30 degrees off the way", code == 200 and travel is not None and near(heading_end(bw), -limit, 0.12), f"{code} heading {round(heading_end(bw), 2)} travel {travel and round(travel, 2)} (want {round(-limit, 2)})")
        code, out = face(0.0, 0.0, 1.0)
        br = body(p)
        A.check(p, "released while walking: the heading returns to the way it walks", code == 200 and near(heading_end(br), 0.0, 0.12), f"heading {round(heading_end(br), 2)}")
        face(0.0, -1.0, 0.6)
        p.call("human_move", [0.0, 0.0, False])
        time.sleep(2.0)
        bs = body(p)
        EVIDENCE["stopped"] = bs
        A.check(p, "stopping with the look held: the body stands and finishes the turn north", bs["vx"] == 0 and bs["vy"] == 0 and near(heading_end(bs), -math.pi / 2, 0.1), f"heading {round(heading_end(bs), 2)} v {bs['vx']},{bs['vy']}")
        face(0.0, 0.0, 0.3)

        # 4. The input bucket, narrowed for the check by the laws (`set_world_law`): one input a
        #    every five seconds, three in a burst. HTTP calls are slower than the shipped refill
        #    of 30 a second.
        p.call("set_world_law", ["input_hz", "0.2"], "admin")
        p.call("set_world_law", ["input_burst", "3"], "admin")
        time.sleep(16.0)  # the bucket fills to its burst of 3
        codes = []
        for k in range(8):
            ang = k * math.pi / 2
            c, out = p.call("human_face", [math.cos(ang), math.sin(ang)])
            codes.append((c, out.strip()[:60]))
        c, out = p.call("human_move", [1.0, 0.0, False])
        codes.append(("human_move", c, out.strip()[:60]))
        refused = [c for c in codes[:8] if c[0] != 200 and "too many movement inputs" in c[1]]
        EVIDENCE["burst"] = codes
        A.check(p, "looks are rate-limited by the movement input bucket (3 in a burst)", 3 <= 8 - len(refused) <= 4, f"{8 - len(refused)} of 8 accepted")
        A.check(p, "and the bucket is shared with human_move", c != 200 and "too many movement inputs" in out, f"{c} {out.strip()[:80]}")
        p.call("set_world_law", ["input_hz", "30"], "admin")
        p.call("set_world_law", ["input_burst", "15"], "admin")
        time.sleep(1.0)
        p.call("human_move", [0.0, 0.0, False])

        # 5. Anonymous.
        code, out = V.http(f"/v1/database/{p.db}/call/human_face", [1.0, 0.0], None)
        A.check(p, "human_face without a character is refused", code != 200 and "you have no living character" in out, f"{code} {out.strip()[:100]}")
    finally:
        p.call("human_face", [0.0, 0.0])
        p.call("set_world_law", ["fov_on", "false"], "admin")
        p.call("set_world_law", ["input_hz", "30"], "admin")
        p.call("set_world_law", ["input_burst", "15"], "admin")
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "face.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
