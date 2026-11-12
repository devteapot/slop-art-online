#!/usr/bin/env python3
"""Who would hear you now, as a real client receives it (earshot, docs/COMMUNICATION.md §17).

    earshot.py --run client-...      (a run launched with verify.py launch, any seed)

The player joins (its own identity). The admin spawns three minded strangers, A, B and C, holds
them still, and puts the player on a quiet open line with A and C beside it. A and C tell their
names ("I'm …", admin `mind_say`). Then A stands 3 m east (seen, within a said line), B 10 m east
(seen by day, beyond a said line, within a call) and C 15 m west (beyond sight, within a call).
With the `earshot` law off (as shipped) the player has no `my_earshot` row; the admin turns it
on (`set_world_law`). The player's `my_earshot` row, read through the Rust SDK probe (`drive.py --query --as-player`),
must list A at `say`, add B at `call` by day, never list C, and say the same in words with A by
name, B as "a stranger" and no word of C's name. The player then says a line to the room
(`human_say`) and calls one (`human_speak … "call"`): the people who receive each, among the
three, are the row's list at that way, and C, unseen, receives the call. Turned off again, the row
goes. Admin calls
(`spawn_crowd`, `set_behavior`, `place_at`, `mind_say`, `set_world_law`) set the scene; they are not something a
player can do. Writes `RUN/earshot-seen.jsonl` and `RUN/earshot.json`. Python standard library
only.
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
DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
THOUGHT = {"kind": "talk", "summary": "verify-client earshot line", "detail": "", "latency_ms": 0, "tokens": 0, "model": "", "reference": ""}


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


def open_line(rid, length, clear=30.0):
    """A row of `length` open tiles, five wide, that nothing blocks the sight along, with no body
    within `clear` m (verify-core's `quiet_line`)."""
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
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    for y in range(8, H - 8, 3):
        for x in range(8, W - length - 8, 2):
            if not all(walk(x + i, y + d) for i in range(length) for d in (-2, -1, 0, 1, 2)):
                continue
            mid = (x + length / 2, y + .5)
            if all(math.dist(mid, b) > clear + length / 2 for b in bodies):
                return [(x + i + .5, y + .5) for i in range(length)]
    raise RuntimeError("no quiet open line on this map")


def earshot_row(rid, name):
    """The player's my_earshot row through the SDK probe: the last one it held."""
    run(DRIVE, "--run", rid, "--query", "SELECT * FROM my_earshot", "--as-player", "--seconds", 4, "--save", name)
    last = None
    for line in (ROOT / ".local/living/verify" / rid / f"{name}.jsonl").read_text().splitlines():
        ev = json.loads(line)
        for r in (ev.get("tables") or {}).get("my_earshot", []) + [x for k in ("inserts", "inserted") for x in ev.get(k) or []]:
            if isinstance(r, dict) and "ways" in r:
                last = r
    return last or {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    out = ROOT / ".local/living/verify" / rid
    run(V, "player", "--run", rid, "join", "Ear Probe")
    me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
    before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
    call(rid, "spawn_crowd", [3, True])
    a, b, c = sorted(x["id"] for x in sql(rid, "SELECT id FROM character") if x["id"] not in before)
    names = {x["id"]: x["name"] for x in sql(rid, "SELECT id, name FROM character")}
    for x in (a, b, c):
        call(rid, "set_behavior", [x, json.dumps({"wait": 300})])
    line = open_line(rid, 28)
    call(rid, "place_at", [me, *line[15]])
    call(rid, "place_at", [a, *line[16]])
    call(rid, "place_at", [c, *line[14]])
    time.sleep(1.5)
    for x in (a, c):
        call(rid, "mind_say", [x, f"I'm {names[x]}.", 0, "say", 0, THOUGHT])
    time.sleep(1.0)
    for x, i in ((a, 18), (b, 25), (c, 0)):
        call(rid, "place_at", [x, *line[i]])
    time.sleep(3.0)
    bodies = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body") if x["id"] in (me, a, b, c)}
    dist = {x: round(math.dist(bodies[me], bodies[x]), 1) for x in (a, b, c)}
    sight = (sql(rid, "SELECT * FROM my_senses", "--as-player") or [{"sight": 11.0}])[0]["sight"]
    off = earshot_row(rid, "earshot-off")
    call(rid, "set_world_law", ["earshot", "true"])
    time.sleep(1.0)
    row = earshot_row(rid, "earshot-seen")
    ways = {w["way"]: set(w["hearers"]) for w in row.get("ways", [])}
    text = row.get("text", "")
    ours = {a, b, c}
    # By night (sight 6 m) B at 10 m is out of sight too: a call then adds no one the player sees.
    night = sight < dist[b]
    unseen = {c} | ({b} if night else set())
    listed = set().union(*ways.values()) if ways else set()
    call(rid, "human_say", ["Is anyone near enough to hear me?", 0], "--as-player")
    time.sleep(2.6)
    call(rid, "human_speak", ["Hello out there!", 0, "call"], "--as-player")
    time.sleep(1.5)
    rows = sql(rid, f"SELECT * FROM experience WHERE subject = {me}")
    call(rid, "set_world_law", ["earshot", "false"])
    time.sleep(1.0)
    off_again = earshot_row(rid, "earshot-off-again")
    got = lambda words: {r["observer"] for r in rows if r["kind"] == "speech" and words in r["text"]} & ours
    heard_say, heard_call = got("near enough to hear me"), got("Hello out there")
    checks = {
        "off as shipped: no my_earshot row": not off,
        "turned off again: the row goes": not off_again,
        "placed as planned (A within a said line, B beyond it, C beyond sight)": dist[a] <= 6.0 and 9.0 < dist[b] <= 11.0 and 11.0 < dist[c] <= 22.5,
        "my_earshot is my character's one row": row.get("id") == me,
        "say lists A": ways.get("say", set()) & ours == {a},
        "call lists A and B by day (A alone by night)": ways.get("call", set()) & ours == ({a} if night else {a, b}),
        "the unseen are never listed": not (unseen & listed),
        "the words name A, B as a stranger by day, and never C": text.startswith(f"Within earshot if you say it: {names[a]}") and names[c] not in text
        and (("a call would reach no one more" in text) if night else ("a call would also reach: a stranger" in text)),
        "a said line reaches exactly the say list": heard_say == ways.get("say", set()) & ours,
        "a call reaches the call list and the unseen": heard_call - unseen == ways.get("call", set()) & ours and unseen <= heard_call,
    }
    result = {"player": me, "a": a, "b": b, "c": c, "night": night, "sight": sight, "dist": dist, "row": row, "heard_say": sorted(heard_say), "heard_call": sorted(heard_call), "checks": checks}
    (out / "earshot.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
