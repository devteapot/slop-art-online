#!/usr/bin/env python3
"""Remembered resources, as a player's character sees them (talk-places, docs/COMMUNICATION.md §20).

    remembered.py --run knowledge-...   (a run launched with verify.py launch, any seed)

The player joins (its own identity); `takeover_s` is set to an hour so its character stays the
player's own (a joined player has no open connection, and the world's minds would take it over
after 30 s). On an open line with no berry bush within 18 m of its near end, three berry bushes
holding one berry each are placed beside the player. Its character looks when it comes into a
chunk (`stock::look`, at its perception sweep), so the player steps 43 m off and back:

1. `seen_stock` gains one row for the player's character, kind `berry_bush`, holding the three,
   count 3, a time, not gone.
2. The player goes 43 m off again (out of sight). A stranger (minded, no mind service: it keeps its graph) gathers the three
   (admin `mind_act`), and they are empty. The row is unchanged: the character did not see it.
3. The player comes back: the row is gone (its time set, the count kept), and the character is
   told once: "Nothing is left to gather on the berry bush around (x, y): 3 had some when you
   saw them, day N HH:MM."
4. A fourth bush is placed and the player steps off and back again: a new row for it, not the
   gone one (a gone row is replaced only by its own nodes bearing again).

Admin calls (`set_world_law`, `spawn_crowd`, `set_behavior`, `place_at`, `place_resource`,
`mind_act`) set the scene. Writes `RUN/remembered.json`. Python standard library only.
"""

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
KIND = "berry_bush"


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r.stdout


def sql(rid, query, *flags):
    out = run(V, "sql", "--run", rid, query, *flags)
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def call(rid, reducer, args, *flags):
    run(V, "call", "--run", rid, reducer, json.dumps(args), *(flags or ("--as-admin",)))


def open_line(rid, length, kind, free_m, clear=30.0):
    """A row of `length` open tiles, five wide, with no body within `clear` m and no `kind`
    within `free_m` of its near end (tile 4)."""
    w = sql(rid, "SELECT width, height FROM world")[0]
    W, H = w["width"], w["height"]
    tiles = bytearray(W * H)
    for row in sql(rid, "SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    bodies = [(b["x"], b["y"]) for b in sql(rid, "SELECT x, y FROM body")]
    same = [(n["x"], n["y"]) for n in sql(rid, "SELECT kind, x, y FROM resource_node") if n["kind"] == kind]
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    for y in range(8, H - 8, 3):
        for x in range(8, W - length - 8, 2):
            if not all(walk(x + i, y + d) for i in range(length) for d in (-2, -1, 0, 1, 2)):
                continue
            mid = (x + length / 2, y + .5)
            near = (x + 4.5, y + .5)
            if all(math.dist(mid, b) > clear + length / 2 for b in bodies) and all(math.dist(near, p) > free_m for p in same):
                return [(x + i + .5, y + .5) for i in range(length)]
    raise RuntimeError("no open line clear of bodies and berry bushes on this map")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    out = ROOT / ".local/living/verify" / rid
    call(rid, "set_world_law", ["takeover_s", "3600"])
    run(V, "player", "--run", rid, "join", "Bush Watcher")
    me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
    before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
    call(rid, "spawn_crowd", [1, True])
    g = next(x["id"] for x in sql(rid, "SELECT id FROM character") if x["id"] not in before)
    call(rid, "set_behavior", [g, json.dumps({"wait": 600})])
    line = open_line(rid, 48, KIND, 18.0)
    near, far = line[4], line[47]
    call(rid, "place_at", [me, *near])
    call(rid, "place_at", [g, *line[40]])
    time.sleep(1.0)
    nodes_before = {n["id"] for n in sql(rid, "SELECT id FROM resource_node")}
    spots = [(near[0] + dx, near[1] + dy) for dx, dy in ((2.0, 0.0), (3.0, 1.0), (2.0, -1.0))]
    for dx, dy in ((2.0, 0.0), (3.0, 1.0), (2.0, -1.0)):
        call(rid, "place_resource", [me, KIND, dx, dy, 1.0, 0])
    ours = sorted(n["id"] for n in sql(rid, "SELECT id, kind, x, y FROM resource_node") if n["id"] not in nodes_before and n["kind"] == KIND and any(math.dist((n["x"], n["y"]), p) < 0.6 for p in spots))

    def rows():
        return [r for r in sql(rid, f"SELECT * FROM seen_stock WHERE actor = {me}") if r["kind"] == KIND]

    def step_off_and_back(wait=2.0):
        call(rid, "place_at", [me, *far])
        time.sleep(wait)
        call(rid, "place_at", [me, *near])
        time.sleep(wait)

    step_off_and_back()
    seen = rows()
    first = next((r for r in seen if set(ours) <= set(r["nodes"])), None)
    # 2. Out of sight, a stranger strips them.
    call(rid, "place_at", [me, *far])
    time.sleep(1.0)
    call(rid, "place_at", [g, near[0] + 2.0, near[1]])
    call(rid, "mind_act", [g, [json.dumps({"do": "gather", "target": {"nearest": KIND}})] * 3, "verify-knowledge"])
    empty = False
    end = time.monotonic() + 45
    while time.monotonic() < end and not empty:
        time.sleep(1.5)
        amounts = {n["id"]: n["amount"] for n in sql(rid, "SELECT id, amount FROM resource_node") if n["id"] in ours}
        empty = all(a < 1.0 for a in amounts.values())
    call(rid, "place_at", [g, *line[40]])
    time.sleep(2.0)
    away = next((r for r in rows() if first and r["id"] == first["id"]), None)
    # 3. Back: seen without them.
    t_back = sql(rid, "SELECT last_ms FROM clock")[0]["last_ms"]
    call(rid, "place_at", [me, *near])
    time.sleep(3.0)
    back = next((r for r in rows() if first and r["id"] == first["id"]), None)
    told = [e["text"] for e in sql(rid, f"SELECT * FROM experience WHERE observer = {me}") if e["at_ms"] >= t_back and e["text"].startswith("Nothing is left to gather on the berry bush")]
    # 4. A fourth bush: its own row.
    nodes_before = {n["id"] for n in sql(rid, "SELECT id FROM resource_node")}
    call(rid, "place_resource", [me, KIND, -2.0, 0.0, 1.0, 0])
    # The new berry bush at that spot (the world may grow other nodes meanwhile).
    fourth = [n["id"] for n in sql(rid, "SELECT id, kind, x, y FROM resource_node") if n["id"] not in nodes_before and n["kind"] == KIND and math.dist((n["x"], n["y"]), (near[0] - 2.0, near[1])) < 0.6]
    step_off_and_back()
    after = rows()
    presence = sql(rid, f"SELECT * FROM presence WHERE id = {me}")
    checks = {
        "three bushes placed": len(ours) == 3,
        "the player's character is still its own (not taken over)": bool(presence) and not presence[0]["ai"],
        "1. one row holds the three, count 3, seen, not gone": first is not None and first["count"] == 3 and first["seen_ms"] > 0 and first["gone_ms"] == 0 and len([r for r in seen if set(r["nodes"]) & set(ours)]) == 1,
        "the spot is the middle of the three": first is not None and math.dist((first["x"], first["y"]), (near[0] + 7 / 3, near[1])) < 0.6,
        "2. stripped out of sight: the three are empty": empty,
        "2. ... and the row is unchanged (never from the world's truth)": away is not None and away["gone_ms"] == 0 and away["count"] == 3 and away["seen_ms"] == first["seen_ms"],
        "3. back: gone, at the look's time, the count and seen time kept": back is not None and back["gone_ms"] >= t_back and back["count"] == 3 and back["seen_ms"] == first["seen_ms"],
        "3. told once, with how many and when": len(told) == 1 and "3 had some when you saw them, day " in told[0],
        "4. a fourth bush: a row of its own, the gone row kept": len(fourth) == 1 and any(r["nodes"] == fourth and r["count"] == 1 and r["gone_ms"] == 0 for r in after) and any(back and r["id"] == back["id"] and r["gone_ms"] > 0 for r in after),
    }
    result = {"player": me, "stranger": g, "near": near, "far": far, "ours": ours, "fourth": fourth, "first": first, "away": away, "back": back, "told": told, "after": after, "presence": presence, "checks": checks}
    (out / "remembered.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
