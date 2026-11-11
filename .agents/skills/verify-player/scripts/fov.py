#!/usr/bin/env python3
"""What a player perceives when sight depends on facing (docs/PERCEPTION.md, "The field of
view", "Heard, not seen"), switched on a running world by the admin's `set_world_law fov_on`.

A resident R is held still 5.5 m west of the player (beyond the near ring and side vision,
with the keep metre, by day and in the dark; within night sight). The player turns with the `face` act
(`human_act`), which turns its body (`body.heading`, read through `my_body`).

1. Off (as shipped): R is in the player's view (`seen_bodies`) whichever way the player faces,
   and `heard_sounds` is empty.
2. The player may not change a law: `set_world_law` as the player is refused ("admin only").
3. On, the player facing east (R behind): R is not in `seen_bodies` and is in `heard_sounds` as
   "person", bearing west (6), band close (1); the row carries only `key`, `kind`, `bearing`,
   `band`, and `key` is not R's id.
4. The player turns west (`face`): R comes into view and its heard row goes.
5. The field's edge, with R 5.5 m off: at 65 degrees off facing R is seen; turned on through 40 to
   75 degrees it stays seen (the 10 degree margin for someone already seen); at 100 degrees it is
   gone; back at 75 degrees it is not seen afresh (no margin for a newcomer).
6. Off again: R is seen behind, and `heard_sounds` empties within the linger.

    fov.py --run RUN

Needs `verify.py launch --run RUN` (any seed; scoped build). Admin `place_at`, `set_behavior`
and `set_world_law` set the scene. Writes `RUN/fov.json`. Python standard library only.
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


def law(p, name, value):
    return p.call("set_world_law", [name, json.dumps(value)], "admin")


def body(p):
    rows = p.sql("SELECT * FROM my_body", "player")
    return rows[0] if rows else None


def heading_now(b):
    """The heading at the end of the body's turn (`my_body`: a turn under way ends at `turn_s`)."""
    return math.remainder(b["heading"] + b["turn"] * b["turn_s"], math.tau)


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
    # The player 5.5 m east of R (R lies west of it).
    p.call("place_at", [me, x + 5.5, y], "admin")
    time.sleep(1.0)
    b = body(p)
    px, py = b["x"], b["y"]
    EVIDENCE["cast"] = {"player": me, "resident": rid, "resident_at": [x, y], "player_at": [px, py]}
    west = math.atan2(y - py, x - px)

    def face(angle_off):
        """Turn so that R lies `angle_off` degrees off facing (0: facing it)."""
        h = west - math.radians(angle_off)
        code, out = p.call("human_act", [json.dumps({"do": "face", "target": {"at": [px + 4.0 * math.cos(h), py + 4.0 * math.sin(h)]}})])
        time.sleep(1.6)  # the turn (600 ms) and a sweep (200 ms) or two
        return code, out, h

    def seen():
        return any(m["id"] == rid for m in p.sql("SELECT id FROM seen_bodies", "player"))

    def heard():
        return p.sql("SELECT * FROM heard_sounds", "player")

    try:
        # 1. Off.
        code, out, h = face(180.0)
        b1 = body(p)
        turned = b1 and abs(math.remainder(heading_now(b1) - h, math.tau)) < 0.1
        A.check(p, "the face act turns the player's body (my_body heading)", code == 200 and turned, f"{code} {out.strip()[:120]} want {h:.2f} got {b1 and heading_now(b1):.2f}")
        A.check(p, "off: R 5.5 m behind is in view", A.wait_for(seen, 3), "seen_bodies")
        A.check(p, "off: nothing is told as heard", not heard(), heard())

        # 2. Players may not change laws.
        code, out = p.call("set_world_law", ["fov_on", "true"], "player")
        A.check(p, "set_world_law is refused to a player", code != 200 and "admin only" in out, f"{code} {out.strip()[:120]}")

        # 3. On, facing away.
        code, out = law(p, "fov_on", True)
        A.check(p, "the admin turns fov_on on", code == 200, f"{code} {out.strip()[:120]}")
        time.sleep(1.0)
        A.check(p, "on, R behind: not in view", A.wait_for(lambda: not seen(), 3), "seen_bodies")
        # Others may be heard too: R is the one close to the west.
        mine = lambda: [h for h in heard() if h["bearing"] == 6 and h["band"] == 1]
        rows = A.wait_for(mine, 3)
        EVIDENCE["heard_behind"] = heard()
        row = rows[0] if rows else {}
        A.check(p, "on, R behind: heard as a person to the west, close", len(rows) >= 1 and row.get("kind") == "person", EVIDENCE["heard_behind"])
        A.check(p, "the heard row names no one (key, kind, bearing, band; the key is not an id)", rows and set(row) == {"key", "kind", "bearing", "band"} and row["key"] != rid and row["key"] > 2**32, rows)
        key = row.get("key")
        time.sleep(1.0)
        A.check(p, "the key holds while the sound lasts", any(h["key"] == key for h in heard()), heard())

        # 4. Turn to it.
        face(0.0)
        A.check(p, "facing R: it comes into view", A.wait_for(seen, 3), "seen_bodies")
        A.check(p, "and its heard row goes", A.wait_for(lambda: not any(h["key"] == key for h in heard()), 3), heard())

        # 5. The field's edge.
        face(65.0)
        e65 = seen()
        face(40.0)
        face(75.0)
        e75_kept = seen()
        face(100.0)
        e100 = A.wait_for(lambda: not seen(), 2)
        face(75.0)
        e75_new = seen()
        EVIDENCE["edge"] = {"65": e65, "75_kept": e75_kept, "100_gone": bool(e100), "75_new": e75_new}
        A.check(p, "edge: seen at 65 degrees off facing (focal 70)", e65, EVIDENCE["edge"])
        A.check(p, "edge: kept at 75 degrees once seen (margin 10)", e75_kept, EVIDENCE["edge"])
        A.check(p, "edge: gone at 100 degrees (side vision reaches a third of sight)", e100, EVIDENCE["edge"])
        A.check(p, "edge: not seen afresh at 75 degrees", not e75_new, EVIDENCE["edge"])

        # 6. Off again.
        face(180.0)
        law(p, "fov_on", False)
        A.check(p, "off again: R behind is in view", A.wait_for(seen, 3), "seen_bodies")
        A.check(p, "off again: the heard rows go within the linger", A.wait_for(lambda: not heard(), 4), heard())
        changes = p.sql("SELECT name, old, new, by FROM law_change")
        EVIDENCE["law_change"] = changes
        A.check(p, "both changes are recorded, by the admin", [(c["name"], c["old"], c["new"]) for c in changes][-2:] == [("fov_on", "false", "true"), ("fov_on", "true", "false")], changes)
    finally:
        law(p, "fov_on", False)
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "fov.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
