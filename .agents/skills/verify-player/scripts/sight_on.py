#!/usr/bin/env python3
"""Cover sight and gaze as a world ships them on (no law set by the scene before its checks).

A non-admin player looks at residents placed by the admin: one behind a trunk, one behind a
hedge (when the world has hedges), a control on open ground 4 m away, and one across a terrace
overlook. Then `human_gaze` changes the player's applied field. Before every assertion the
world is checked to be unpaused and ticking (the orphan guard pauses a world whose launcher
exited, and a paused world never updates `seen_characters`). The hedge check proves its cause
afterwards: the same pair is seen with `cover_brush_on` off, and the law is put back.

    sight_on.py --run player-sighton-<x> --fixture fixture.json [--hedges '[[x0,y0,x1,y1],...]']

The fixture is `living/rules/examples/cover_fixture.rs`'s output for the run's seed.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verify/scripts"))
import verify as v

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--run", required=True)
p.add_argument("--fixture", required=True, type=Path)
p.add_argument("--hedges", default="[]", help="JSON list of hedge rectangles in land metres [x0, y0, x1, y1]")
p.add_argument("--brush", default="true", help="the cover_brush_on value the world ships")
a = p.parse_args()
if not a.run.startswith("player-sighton-") or v.CONTAINER == v.SHARED:
    p.error("use a fresh player-sighton-* world on your own scratch server")
fixture = json.loads(a.fixture.read_text())
hedges = json.loads(a.hedges)
st = v.load(a.run)
db = st["db"]
owner = v.admin_token()
player = st["token"]
out = v.run_dir(a.run) / "sight-on-proof.jsonl"
failures = []


def sql(query, token=owner):
    code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
    assert code == 200, (query, code, body)
    res = json.loads(body)[0]
    fields = [c["name"]["some"] for c in res["schema"]["elements"]]
    return [dict(zip(fields, r)) for r in res["rows"]]


def call(reducer, args, token=owner):
    return v.http(f"/v1/database/{db}/call/{reducer}", args, token, timeout=90)


def do(reducer, args, token=owner):
    code, body = call(reducer, args, token)
    assert code == 200, (reducer, args, code, body)
    return body


def live():
    """The world is unpaused and its tick advances; returns the evidence."""
    # The world clock moves every tick; `stats.ticks` is written only every few seconds.
    paused = sql("SELECT paused FROM world")[0]["paused"]
    t0 = sql("SELECT last_ms FROM clock")[0]["last_ms"]
    time.sleep(0.3)
    t1 = sql("SELECT last_ms FROM clock")[0]["last_ms"]
    return dict(paused=paused, clock_ms=[t0, t1], ok=(not paused and t1 > t0))


def record(name, ok, data=None, hard=True):
    world = live()
    ok = bool(ok) and world["ok"]
    with out.open("a") as f:
        f.write(json.dumps({"check": name, "passed": ok, "world": world, "data": data}) + "\n")
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if not ok and hard:
        failures.append(name)
    return ok


def seen(id):
    return id in {r["id"] for r in sql("SELECT id FROM seen_characters", player)}


def steady(id, settle=1.2, reads=4):
    """Visibility after the sweep settles, read several times; None if it flickers."""
    time.sleep(settle)
    got = set()
    for _ in range(reads):
        got.add(seen(id))
        time.sleep(0.25)
    return got.pop() if len(got) == 1 else None


def resident():
    before = max(r["id"] for r in sql("SELECT id FROM character"))
    do("spawn_crowd", [1, True])
    id = sql(f"SELECT id FROM character WHERE id > {before}")[0]["id"]
    do("set_behavior", [id, json.dumps({"wait": 900})])
    return id


def stage(eye, other, who):
    """The player at `eye` facing `other`, standing; resident `who` at `other`."""
    do("place_at", [actor, *eye])
    do("place_at", [who, *other])
    dx, dy = other[0] - eye[0], other[1] - eye[1]
    n = math.hypot(dx, dy) or 1.0
    do("human_face", [dx / n, dy / n], player)
    do("human_move", [0.0, 0.0, False], player)


actor = sql("SELECT id FROM my_characters", player)[0]["id"]
# A land made with cover off, its overlay installed after (the play-test world), derives its cover
# geometry in steps first (docs/COVER_SIGHT.md, "Cover geometry"): cover is in force once
# `cover_law` says so. A world made with cover on has it from creation.
t_geometry = time.time()
while time.time() - t_geometry < 300 and not any(r["cover_sight_on"] for r in sql("SELECT cover_sight_on FROM cover_law", player)):
    time.sleep(1)
record("cover in force (its geometry complete) before the checks", True, {"waited_s": round(time.time() - t_geometry, 1)})
law = sql("SELECT * FROM cover_law", player)
want = dict(id=0, cover_sight_on=True, cover_eye_height_m=1.6, cover_brush_on=a.brush == "true",
            cover_brush_min_fill=0.6, cover_cliff_step_m=2.0)
record("cover_law as shipped by the overlay (player's view)", law == [want], law)
# The world's own law values: `law_override` since law-override (docs/LAW_OVERRIDE.md), public;
# `world_law` before it (no longer written).
overrides = [o for o in sql("SELECT * FROM law_override", player) if o["name"].startswith(("cover_", "gaze_", "fov_"))]
record("no admin law overrides of cover, gaze or facing before the checks (law_override, player's view)", not overrides, overrides)
senses = sql("SELECT * FROM my_senses_v_2", player)
record("gaze on as shipped: the player's applied field exists at Middle", len(senses) == 1 and senses[0]["band"] == 0, senses)
legacy = sql("SELECT * FROM my_senses", player)
record("facing sight on: the player's field is directional", bool(legacy) and legacy[0]["field"], legacy)

trunk_r, control_r, far_r = resident(), resident(), resident()

# Trunk: the fixture pair is 4 m apart with a procedural trunk between.
t = fixture["trunk"]
stage(t["from"], t["to"], trunk_r)
got = steady(trunk_r)
record("resident behind a trunk is hidden", got is False, dict(t, seen=got))

# Control: 4 m from the same eye on open ground, the opposite way and then the two sides.
fx, fy = t["from"]
dx, dy = t["to"][0] - fx, t["to"][1] - fy
n = math.hypot(dx, dy)
ux, uy = dx / n, dy / n
tried = []
for cx, cy in [(-ux, -uy), (-uy, ux), (uy, -ux)]:
    spot = [fx + 4 * cx, fy + 4 * cy]
    do("place_at", [trunk_r, fx + 30 * ux, fy + 30 * uy])   # out of the way
    stage(t["from"], spot, control_r)
    got = steady(control_r)
    tried.append(dict(at=spot, seen=got))
    if got:
        break
record("control resident 4 m away on open ground is seen", tried[-1]["seen"] is True, tried)
do("place_at", [control_r, fx + 30 * -ux, fy + 30 * -uy])

# Overlook: the terrace drop is no blocker at eye height.
o = fixture.get("overlook")
if o:
    stage(o["from"], o["to"], control_r)
    got = steady(control_r)
    record("terrace overlook stays clear", got is True, dict(o, seen=got))

c = fixture.get("cliff")
if c:
    stage(c["from"], c["to"], control_r)
    got = steady(control_r)
    record("resident across a cliff face is hidden", got is False, dict(c, seen=got))

b = fixture.get("brush")
if b and a.brush == "true":
    stage(b["from"], b["to"], control_r)
    got = steady(control_r)
    record("resident in brush is hidden", got is False, dict(b, seen=got))

# Hedges: a pair across each hedge's short side, 2-4 m out; the first pair whose line is clear
# with brush off is checked with the law as shipped, then with brush off as the cause.
for i, (x0, y0, x1, y1) in enumerate(hedges):
    found = None
    wide = (x1 - x0) < (y1 - y0)           # the hedge runs north-south: look east-west across it
    # Lines along tile centres inside the hedge: a line on a tile edge is traced through either
    # row depending on direction and small body offsets, and an edge row can be under min fill.
    lo, hi = (y0, y1) if wide else (x0, x1)
    centres = [k + 0.5 for k in range(math.ceil(lo), math.floor(hi)) if lo + 0.5 <= k + 0.5 <= hi - 0.5]
    span = sorted(centres, key=lambda c: abs(c - (lo + hi) / 2))
    for along in span:
        for out_m in (2.5, 3.5, 2.0):
            if wide:
                eye, other = [x0 - out_m, along], [x1 + out_m, along]
            else:
                eye, other = [along, y0 - out_m], [along, y1 + out_m]
            for e, o2 in ((eye, other), (other, eye)):
                stage(e, o2, control_r)
                shipped = steady(control_r)
                if shipped is not False:
                    continue
                do("set_world_law", ["cover_brush_on", "false"])
                try:
                    stage(e, o2, control_r)
                    without = steady(control_r)
                finally:
                    do("set_world_law", ["cover_brush_on", "true"])
                if without is True:
                    found = dict(eye=e, target=o2, shipped=shipped, brush_off=without)
                    break
            if found:
                break
        if found:
            break
    record(f"resident behind hedge {i} is hidden (and seen with brush off)", found is not None, found)
    if found:
        restored = [r["cover_brush_on"] for r in sql("SELECT cover_brush_on FROM cover_law", player)]
        stage(found["eye"], found["target"], control_r)
        got = steady(control_r, settle=2.0)
        found = dict(found, cover_law_brush=restored)
        record(f"hedge {i}: hidden again with brush back on", got is False, dict(found, seen=got))

# Gaze: Far and Near change the applied field, and Far reaches a resident Middle does not.
def applied(band):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        rows = sql("SELECT * FROM my_senses_v_2", player)
        if rows and rows[0]["band"] == band:
            return rows[0]
        time.sleep(0.1)
    return None


do("human_gaze", [0], player)
middle = applied(0)
time.sleep(0.3)
do("human_gaze", [1], player)
far = applied(1)
time.sleep(0.3)
do("human_gaze", [2], player)
near = applied(2)
keys = ("band", "ceiling", "ground", "senses")
record("human_gaze changes the applied field (Middle, Far, Near)",
       middle and far and near and near["ceiling"] < middle["ceiling"] < far["ceiling"]
       and middle["senses"] != far["senses"] and far["senses"] != near["senses"],
       {k: [r and r.get(k) for r in (middle, far, near)] for k in keys})

reach = legacy[0]["sight"]   # Middle's sight: the field the world had before gaze
cases = []
for eye in [t["from"]] + ([o["from"]] if o else []) + ([c["from"]] if c else []):
    for ddx, ddy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        cases.append((eye, [eye[0] + ddx * reach * 1.15, eye[1] + ddy * reach * 1.15]))
result = None
for eye, other in cases:
    time.sleep(0.3)
    do("human_gaze", [0], player)
    applied(0)
    stage(eye, other, far_r)
    mid = steady(far_r)
    time.sleep(0.3)
    do("human_gaze", [1], player)
    applied(1)
    farv = steady(far_r, settle=0.8)
    if mid is False and farv is True:
        result = dict(eye=eye, target=other, middle=mid, far=farv, reach=reach)
        break
record("Far sees a resident beyond Middle's reach that Middle does not", result is not None, result or cases)

print(json.dumps({"failures": failures, "proof": str(out)}))
sys.exit(1 if failures else 0)
