#!/usr/bin/env python3
"""The player's look, `human_face(dx, dy)` (docs/PERCEPTION.md, "The player's look"): it turns
the body's facing (`face_off`/`face_turn`/`face_turn_s` over the travel `heading`), and `(0, 0)`
releases it.

With the world's `fov_on` law on (admin `set_world_law`), a resident R is held still 5.5 m west
of the player, who faces east (the `face` act).

1. Standing: `human_face(-1, 0)` turns the body west at its turn rate (`my_body`), and R comes
   into view (`seen_bodies`).
2. A look within the `look_slack_deg` law (10 degrees) of the one held writes nothing (`my_body`
   unchanged); a release while standing keeps the facing.
3. Walking: `human_move(1, 0)` (east) on open ground off the road, each look its own walk from
   the same spot, with a look 45, 90, 135 and 180 degrees north of the way: the travel, measured
   from successive position anchors (`my_body` rows' x, y at t_ms), stays east at the cruise
   speed with no sideways part; the facing turns at the turn rate (`face_turn` = 6 rad/s for
   span / 6 s) and, sampled only after that turn has settled, is 45, 75, 75 degrees north and,
   for 180 from a facing on the travel, 75 south (wrap(pi) = +pi); after a look north first, a
   180 look keeps the north shoulder. Released (`human_face(0, 0)`), the facing returns to the
   way at the turn rate. Facing sight follows the facing, not the travel: a second resident Q
   behind and north of the walker (beyond side vision of the travel) is in view while it walks
   east looking north, out of view when it lets the look go. Looking north again and stopping
   (`human_move(0, 0)`), the body finishes the turn north once it stands.
3b. The walk reversing with the look held aside (look-4): a play-test's moment of walk keys
   reversing and turning sharply while the look swings and is held far aside (only its keys and
   looks, at their own timing), from a stand on open ground facing the first walk's way. Four
   threads read `my_body` throughout. No row turns the facing faster than the turn rate (the
   travel's turn and the offset's together, row by row); at every row seen, the facing goes on
   from where the row before left it, within what one row written and replaced between two
   reads could explain (twice the turn rate over the time between reads, its 99th percentile,
   plus one 60 Hz tick); and the facing rebuilt every 10 ms has no stretch over 90 degrees in 0.25 s.
   `--scene reversal` runs only this.
4. The input bucket (`input_hz`/`input_burst`, shared with `human_move`), narrowed by the admin's
   `set_world_law` to one a second (the laws' least) and three in a burst: of eight looks 90 degrees
   apart, three (or four, with a refill meanwhile) are taken and the rest refused ("too many movement inputs"), and a `human_move` right
   after is refused too. The laws are put back to 30 and 15.
5. Anonymous: refused ("you have no living character").

    face.py --run RUN [--scene all|reversal]

Needs `verify.py launch --run RUN` (any seed; scoped build). Admin `place_at`, `set_behavior`
and `set_world_law` set the scene. Writes `RUN/face.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import sys
import threading
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
    """Where the body travels (its legs point) once the turn under way ends."""
    return math.remainder(b["heading"] + b["turn"] * b["turn_s"], math.tau)


def facing_end(b):
    """Where the body faces once its turns end: the travel heading plus the facing offset
    (`living_rules::steer::facing`)."""
    return math.remainder(heading_end(b) + b["face_off"] + b["face_turn"] * b["face_turn_s"], math.tau)


WALKABLE = {0, 1, 3, 5}  # grass, forest, sand, dirt (living_rules::map::Terrain); no road, which speeds a walker up
OPAQUE = {4, 7}  # rock, wall: they stop sight
CHUNKS = {}


def tile(p, x, y):
    """Terrain of the tile under (x, y), from the public `terrain_chunk` rows (16 x 16 tiles)."""
    c = (int(y) // 16 << 16) | (int(x) // 16)
    if c not in CHUNKS:
        rows = p.sql(f"SELECT tiles FROM terrain_chunk WHERE id = {c}")
        t = rows[0]["tiles"] if rows else []
        CHUNKS[c] = bytes.fromhex(t) if isinstance(t, str) else bytes(t)
    t = CHUNKS[c]
    k = (int(y) % 16) * 16 + int(x) % 16
    return t[k] if k < len(t) else 255


def line_open(p, a, b):
    """No rock or wall on the straight line from a to b (sampled every 0.25 m)."""
    n = int(math.dist(a, b) * 4) + 1
    return all(tile(p, a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) not in OPAQUE for i in range(n + 1))


def open_ground(p, around, box=(-4, 22, -7, 2), reach=80):
    """A spot near `around` with walkable ground off the road and no body in the box east of it (x from
    `box[0]` to `box[1]`, y from `box[2]` to `box[3]` metres off it): room to walk east for
    seven seconds without steering round anything (terrain from the public `terrain_chunk`)."""
    tile_at = lambda x, y: tile(p, x, y)

    bodies = [(b["x"], b["y"]) for b in p.sql("SELECT x, y FROM body")]
    for r in range(0, reach, 4):
        for k in range(max(1, r // 2)):
            ang = k * math.tau / max(1, r // 2)
            x, y = around[0] + r * math.cos(ang), around[1] + r * math.sin(ang)
            x, y = math.floor(x) + 0.5, math.floor(y) + 0.5
            if all(tile_at(x + dx, y + dy) in WALKABLE for dx in range(box[0], box[1] + 1) for dy in range(box[2], box[3] + 1)) and not any(x + box[0] - 1 <= bx <= x + box[1] + 1 and y + box[2] - 1 <= by <= y + box[3] + 1 for bx, by in bodies):
                return (x, y)
    return None


RATE = 6.0  # the shipped `motion` law's turn_rate for people, rad/s (verify-core `moves` checks it)
TRAVEL_TOL_DEG = 0.5  # travel direction from positions, either side of the keys
SPEED_TOL = 0.01  # speed along the keys within 1% of the cruise speed; sideways under 1%
FACE_TOL_DEG = 0.5  # facing after its turn has settled


def now_ms():
    return time.time() * 1000.0


def facing_at(b, t):
    """The facing at world time t (ms) from a `my_body` row, as the authority evaluates it
    (`common::facing_at`: the travel heading on its turn, plus the facing offset on its own)."""
    dt = (min(t, b["next_ms"]) - b["t_ms"]) / 1000.0
    h = b["heading"] + (b["turn"] * min(max(dt, 0.0), b["turn_s"]) if b["turn_s"] > 0 else 0.0)
    off = b["face_off"] + (b["face_turn"] * min(max(dt, 0.0), b["face_turn_s"]) if b["face_turn_s"] > 0 else 0.0)
    return math.remainder(h + off, math.tau)


def walk_look(p, me, at, deg, release=False, pre=None):
    """Walk east from `at` with the look `deg` north of the way (or, `release`, with it then let
    go; or, `pre`, after a look `pre` degrees north has turned the facing first). Returns the
    travel measured over at least 4 s of position anchors after the facing's turn settled, the
    facing segment the look started, and the facing sampled after it."""
    p.call("human_face", [0.0, 0.0])
    p.call("human_move", [0.0, 0.0, False])
    p.call("place_at", [me, at[0], at[1]], "admin")
    time.sleep(0.5)
    p.call("human_move", [1.0, 0.0, False])
    time.sleep(0.6)
    ang = -math.radians(deg)
    if release or pre is not None:
        first_ang = ang if release else -math.radians(pre)
        p.call("human_face", [math.cos(first_ang), math.sin(first_ang)])
        time.sleep(0.6)
    t_look = now_ms()
    code, out = p.call("human_face", [0.0, 0.0] if release else [math.cos(ang), math.sin(ang)])
    # The row the look wrote: its facing segment starts there.
    first = None
    end = time.monotonic() + 3
    while time.monotonic() < end:
        b = body(p)
        if b and b["t_ms"] >= t_look - 100:
            first = b
            break
        time.sleep(0.05)
    if first is None:
        return {"look_deg": deg, "code": code, "anchors": 0, "span_s": 0, "travel_deg": None, "speed_mps": None, "speed_ratio": 0, "sideways_ratio": 1, "turn_ok": False, "face_turn": None, "face_turn_s": None, "off0_deg": None, "want_deg": None, "settled_samples": 0, "facing_deg": None, "facing_err_deg": 999}
    off0 = first["face_off"]
    want = 0.0 if release else (math.copysign(1, math.remainder(ang, math.tau) or 1.0) * min(math.radians(deg), math.radians(75)))
    if not release and deg == 180:
        # Straight behind: from a facing on the travel, wrap(pi) is +pi, so the south side; from
        # a facing already turned to one side, that side (`steer::BEHIND_BAND`).
        want = math.copysign(math.radians(75), off0) if off0 != 0 else math.radians(75)
    span = abs(want - off0)
    turn_ok = abs(abs(first["face_turn"]) - RATE) < 1e-3 and math.copysign(1, first["face_turn"]) == math.copysign(1, want - off0) and abs(first["face_turn_s"] - span / RATE) < 1e-3 if span > 1e-3 else first["face_turn"] == 0.0
    settled_at = first["t_ms"] + first["face_turn_s"] * 1000.0 + 300.0
    anchors = {first["t_ms"]: first}
    samples = []
    while now_ms() < settled_at + 4500:
        b = body(p)
        t = now_ms()
        if b:
            anchors.setdefault(b["t_ms"], b)
            if t >= settled_at:
                samples.append(math.degrees(facing_at(b, t)))
        time.sleep(0.15)
    rows = [anchors[k] for k in sorted(anchors)]
    a, z = rows[0], rows[-1]
    span_s = (z["t_ms"] - a["t_ms"]) / 1000.0
    dx, dy = z["x"] - a["x"], z["y"] - a["y"]
    v = math.hypot(dx, dy) / span_s if span_s > 0 else 0.0
    cruise = first["speed"]
    errs = [abs(math.remainder(math.radians(f) - want, math.tau)) for f in samples]
    return {
        "look_deg": deg, "code": code, "release": release,
        "anchors": len(rows), "span_s": round(span_s, 3),
        "travel_deg": round(math.degrees(math.atan2(dy, dx)), 3) if span_s > 0 else None,
        "speed_mps": round(v, 4), "cruise_mps": round(cruise, 4),
        "speed_ratio": round(dx / span_s / cruise, 4) if span_s > 0 and cruise else 0,
        "sideways_ratio": round(dy / span_s / cruise, 4) if span_s > 0 and cruise else 1,
        "turn_ok": bool(turn_ok), "face_turn": round(first["face_turn"], 4), "face_turn_s": round(first["face_turn_s"], 4),
        "off0_deg": round(math.degrees(off0), 2), "want_deg": round(math.degrees(want), 2),
        "settled_samples": len(samples),
        "facing_deg": round(sum(samples) / len(samples), 3) if samples else None,
        "facing_err_deg": round(math.degrees(max(errs)), 3) if errs else 999,
        "rows": rows,
    }


# A play-test's moment (2026-11-12 22:04:12, look-4): the walk keys reversing and turning sharply
# while the look swings and is held far aside, as (ms from the first, M walk / L look, degrees
# with +y south, None to stop or let go). Only the movement keys and the looks.
REVERSAL = [(0, 'M', 157.5), (343, 'M', None), (468, 'L', 146.9), (574, 'L', 137.5), (675, 'L', 129.2), (701, 'M', -22.5), (774, 'L', 121.5), (892, 'L', 90.6), (993, 'L', 20.8), (1099, 'L', 8.8), (1725, 'M', 22.5), (1799, 'L', 4.5), (1849, 'M', -22.5), (1899, 'L', -8.2), (2018, 'L', -2.0), (2117, 'M', None), (2124, 'L', 3.8), (2458, 'L', -0.6), (2683, 'L', -4.6), (2751, 'M', 67.5), (2792, 'L', -10.1), (2866, 'M', None), (2891, 'L', -21.4), (3076, 'L', -26.2), (3150, 'L', None), (3250, 'L', 140.6), (3366, 'L', 112.3), (3483, 'L', 95.4), (3584, 'L', 86.3), (3690, 'L', 80.0), (3800, 'L', 75.7), (3923, 'M', -112.5), (3957, 'M', -67.5), (4017, 'L', 80.9), (4118, 'L', 101.2), (4249, 'L', 108.0), (4317, 'M', None), (4350, 'L', 114.7), (4516, 'L', 120.8), (4634, 'L', 129.8), (4734, 'L', 134.2), (4940, 'L', 139.0), (5040, 'L', 153.8), (5142, 'L', 167.5)]


def row_rate(b):
    """The fastest the facing turns in the world on one `my_body` row (rad/s): the travel's turn
    plus the facing offset's while both turn, each alone after."""
    both = min(b["turn_s"], b["face_turn_s"]) if b["turn"] and b["face_turn"] else 0.0
    rates = [abs(b["turn"] + b["face_turn"])] if both > 0 else []
    if b["turn"] and b["turn_s"] > both:
        rates.append(abs(b["turn"]))
    if b["face_turn"] and b["face_turn_s"] > both:
        rates.append(abs(b["face_turn"]))
    return max(rates, default=0.0)


READERS = 4


def reversal(p, me, at):
    """Replay `REVERSAL` from a stand at `at`, facing the first walk's way with no look held (as
    the play-test's body stood), through `human_move` and `human_face` at its own timing, while
    `READERS` threads read `my_body` without pause. The facing is rebuilt every 10 ms from the rows
    seen (each from its `t_ms`, the latest row that had begun). Returns:
    - `max_row_rate`: the fastest any seen row turns the facing (exact, row by row);
    - `steps`: at each seen row, how far its facing at its `t_ms` is from the row before it then.
      A jump shows there; so does a row written and replaced between two reads, by at most
      twice the turn rate over the time between reads (`read_gap_ms`, the 99th percentile);
    - the track's largest change within 0.25 s and its stretches over 90 degrees."""
    first = math.radians(REVERSAL[0][2])
    p.call("human_face", [0.0, 0.0])
    p.call("human_move", [0.0, 0.0, False])
    p.call("place_at", [me, at[0], at[1]], "admin")
    time.sleep(0.8)
    p.call("human_face", [math.cos(first), math.sin(first)])
    time.sleep(1.0)
    p.call("human_face", [0.0, 0.0])
    time.sleep(0.5)
    rows, reads, done, lock = {}, [], threading.Event(), threading.Lock()

    def watch():
        while not done.is_set():
            b = body(p)
            with lock:
                reads.append(time.monotonic())
                if b:
                    rows[b["t_ms"]] = b

    ws = [threading.Thread(target=watch, daemon=True) for _ in range(READERS)]
    for i, w in enumerate(ws):
        w.start()
        time.sleep(0.007)
    time.sleep(0.3)
    t0 = time.monotonic()
    for at_ms, kind, deg in REVERSAL:
        wait = at_ms / 1000.0 - (time.monotonic() - t0)
        if wait > 0:
            time.sleep(wait)
        v = [0.0, 0.0] if deg is None else [math.cos(math.radians(deg)), math.sin(math.radians(deg))]
        if kind == 'M':
            p.call("human_move", v + [False])
        else:
            p.call("human_face", v)
    time.sleep(1.5)
    done.set()
    for w in ws:
        w.join()
    reads.sort()
    gaps = sorted(b - a for a, b in zip(reads, reads[1:]))
    gap = gaps[int(0.99 * (len(gaps) - 1))]
    order = sorted(rows)
    steps = [[t - order[0], round(math.degrees(math.remainder(facing_at(rows[t], t) - facing_at(rows[order[i - 1]], t), math.tau)), 2)] for i, t in enumerate(order[1:], 1)]
    track = []
    t, j = order[0], 0
    while t <= order[-1] + 1000:
        while j + 1 < len(order) and order[j + 1] <= t:
            j += 1
        track.append((t, facing_at(rows[order[j]], t)))
        t += 10
    unwrapped, acc = [], None
    for i, (t, f) in enumerate(track):
        acc = f if acc is None else acc + math.remainder(f - track[i - 1][1], math.tau)
        unwrapped.append((t, acc))
    worst, jumps, inside = 0.0, 0, False
    for i, (t, f) in enumerate(unwrapped):
        win = [g for u, g in unwrapped[i:i + 26] if u <= t + 250]
        span = max(win) - min(win)
        worst = max(worst, span)
        if span > math.radians(90) and not inside:
            jumps += 1
        inside = span > math.radians(90)
    return {"rows_seen": len(order), "reads": len(reads), "read_gap_ms": round(gap * 1000.0, 1), "max_row_rate": round(max(row_rate(rows[t]) for t in order), 3),
            "steps": [s for s in steps if abs(s[1]) > 0.05], "max_step_deg": max((abs(s[1]) for s in steps), default=0.0), "max_change_deg_0_25s": round(math.degrees(worst), 1), "jumps_over_90": jumps,
            "track_20hz": [[t, round(math.degrees(f), 1)] for t, f in track[::5]], "rows": [rows[t] for t in order]}


def near(a, b, tol):
    return abs(math.remainder(a - b, math.tau)) <= tol


def reversal_check(p, me, around):
    """3b. The walk reversing with the look held aside (look-4): the facing turns on from where it
    was, never faster than the turn rate, so it never jumps."""
    spot = open_ground(p, around, box=(-12, 12, -12, 12))
    A.check(p, "open ground to reverse on", spot is not None, f"{spot}")
    if spot is None:
        return None
    rev = reversal(p, me, spot)
    EVIDENCE["reversal"] = rev
    # A steering update runs at the first tick after it falls due and starts where the last
    # segment ended (`motion::resume_at`): a sample may take in one tick of turning at once.
    tick = 1.0 / 60.0
    A.check(p, "walk reversing with the look held aside: no row turns the facing faster than the turn rate", rev["max_row_rate"] <= RATE + 1e-3, f"{rev['rows_seen']} rows seen, fastest {rev['max_row_rate']} rad/s")
    bound = math.degrees(2 * RATE * rev["read_gap_ms"] / 1000.0 + RATE * tick) + 0.5
    A.check(p, "and the facing goes on where the last row left it (any step within what a row missed between reads explains)", rev["max_step_deg"] <= bound, f"largest step at a row {rev['max_step_deg']} deg (bound {bound:.1f} deg from {rev['read_gap_ms']} ms between reads at the 99th percentile, {rev['reads']} reads); steps {rev['steps']}")
    A.check(p, "and over any 0.25 s it changes at most the turn rate allows: no stretch over 90 degrees", rev["jumps_over_90"] == 0 and rev["max_change_deg_0_25s"] <= math.degrees(RATE * (0.25 + tick)) + rev["max_step_deg"] + 0.5, f"largest change in 0.25 s {rev['max_change_deg_0_25s']} deg, {rev['jumps_over_90']} stretches over 90")
    p.call("human_move", [0.0, 0.0, False])
    p.call("human_face", [0.0, 0.0])
    time.sleep(1.0)
    return rev


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", choices=["all", "reversal"], default="all", help="reversal: only the walk reversing with the look held aside")
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Looker")
    # A resident R standing still with an open line to the spot 5.5 m east of it, where the
    # player stands (`place_at` takes the nearest walkable tile, which may be behind a wall).
    tried = {me}
    for _ in range(8):
        r = A.wait_for(lambda: A.resident(p, tried), 60)
        if not r:
            A.check(p, "a resident stands still", False, "none found within 60 s")
            return finish(p)
        rid = r["id"]
        tried.add(rid)
        x, y = r["at"]
        p.call("place_at", [me, x + 5.5, y], "admin")
        time.sleep(1.0)
        b0 = body(p)
        px, py = b0["x"], b0["y"]
        if line_open(p, (px, py), (x, y)) and abs(math.dist((px, py), (x, y)) - 5.5) < 1.0:
            break
    p.call("set_behavior", [rid, json.dumps({"wait": 600})], "admin")
    EVIDENCE["cast"] = {"player": me, "resident": rid, "player_at": [px, py], "resident_at": [x, y]}
    seen = lambda: any(m["id"] == rid for m in p.sql("SELECT id FROM seen_bodies", "player"))

    def face(dx, dy, wait=1.2):
        code, out = p.call("human_face", [dx, dy])
        time.sleep(wait)
        return code, out

    try:
        if a.scene == "reversal":
            reversal_check(p, me, (px, py))
            return finish(p)
        p.call("set_world_law", ["fov_on", "true"], "admin")
        # Face east with the `face` act: R is behind.
        p.call("human_act", [json.dumps({"do": "face", "target": {"at": [px + 4.0, py]}})])
        time.sleep(1.6)
        A.check(p, "set up: R behind is not in view", A.wait_for(lambda: not seen(), 3), "seen_bodies")

        # 1. Standing.
        code, out = face(-1.0, 0.0)
        b1 = body(p)
        A.check(p, "standing: human_face turns the body (my_body heading west)", code == 200 and b1 and near(heading_end(b1), math.pi, 0.05), f"{code} {out.strip()[:100]} heading {b1 and round(heading_end(b1), 2)}")
        A.check(p, "standing: the facing is the heading (no offset)", b1 and near(facing_end(b1), heading_end(b1), 1e-3), f"facing {b1 and round(facing_end(b1), 3)}")
        A.check(p, "and R comes into view", A.wait_for(seen, 3), "seen_bodies")

        # 2. Within the slack: nothing written; a release keeps the facing.
        before = body(p)
        code, out = face(math.cos(math.pi - math.radians(5)), math.sin(math.pi - math.radians(5)), 0.6)
        after = body(p)
        A.check(p, "a look within 10 degrees of the one held writes nothing", code == 200 and after == before, f"{code} t_ms {before['t_ms']} -> {after['t_ms']}")
        code, out = face(0.0, 0.0, 0.6)
        b2 = body(p)
        A.check(p, "a release while standing keeps the facing", code == 200 and near(heading_end(b2), math.pi, 0.1), f"{code} heading {round(heading_end(b2), 2)}")

        # 3. Walking east with a look 45..180 degrees north of the way (-y is north), on open
        #    ground off the road so steering has nothing to go round. Each look is its own walk
        #    from the same spot, the look let go and the body facing its travel at the start.
        #    Travel is measured from successive position anchors (each `my_body` row's x, y at
        #    its t_ms is where the body was then), not from `heading`; the facing is sampled
        #    only after its turn has settled, computed from the turn rate.
        spot = open_ground(p, (px, py))
        A.check(p, "open ground to walk on", spot is not None, f"{spot}")
        if spot is None:
            return finish(p)
        px, py = spot
        EVIDENCE["walk_from"] = spot
        table = []
        for deg in (45, 90, 135, 180):
            row = walk_look(p, me, (px, py), deg)
            table.append(row)
            want = math.radians(row["want_deg"])
            A.check(p, f"walking, look {deg} off: travel along the keys at full speed (from positions)", row["anchors"] >= 3 and abs(row["travel_deg"]) <= TRAVEL_TOL_DEG and abs(row["speed_ratio"] - 1.0) <= SPEED_TOL and abs(row["sideways_ratio"]) <= SPEED_TOL, f"{row['anchors']} anchors over {row['span_s']} s: travel {row['travel_deg']} deg, speed {row['speed_mps']} m/s = {row['speed_ratio']} x cruise, sideways {row['sideways_ratio']}")
            A.check(p, f"walking, look {deg} off: the facing turns at the turn rate ({RATE} rad/s)", row["turn_ok"], f"face_turn {row['face_turn']} rad/s for {row['face_turn_s']} s from {row['off0_deg']} to {row['want_deg']} deg")
            A.check(p, f"walking, look {deg} off: settled, the facing is min(look, 75) off the travel", row["settled_samples"] >= 3 and row["facing_err_deg"] <= FACE_TOL_DEG, f"{row['settled_samples']} samples, facing {row['facing_deg']} deg (want {row['want_deg']}), worst error {row['facing_err_deg']} deg")
        EVIDENCE["walking_looks"] = table
        # Released while walking: the facing comes back to the travel at the turn rate.
        # Straight behind with the facing already 75 degrees north: it keeps the north shoulder.
        back = walk_look(p, me, (px, py), 180, pre=90)
        EVIDENCE["walking_back_after_north"] = back
        A.check(p, "walking, look 180 off with the facing already north: it stays on the north shoulder", back["turn_ok"] and back["settled_samples"] >= 3 and back["facing_err_deg"] <= FACE_TOL_DEG and back["want_deg"] == -75.0, f"from {back['off0_deg']} deg: face_turn {back['face_turn']}, facing {back['facing_deg']} deg (want -75)")
        rel = walk_look(p, me, (px, py), 90, release=True)
        EVIDENCE["walking_release"] = rel
        A.check(p, "released while walking: the facing returns to the travel at the turn rate", rel["turn_ok"] and rel["settled_samples"] >= 3 and rel["facing_err_deg"] <= FACE_TOL_DEG and abs(rel["travel_deg"]) <= TRAVEL_TOL_DEG, f"face_turn {rel['face_turn']} for {rel['face_turn_s']} s, facing {rel['facing_deg']} deg, travel {rel['travel_deg']} deg")

        # Facing sight while walking: Q 3 m behind and 5.5 m north (118.6 degrees off the travel
        # east: beyond side vision), in view while the walker's facing is 75 degrees north of its
        # travel east, out of view when the look is let go.
        q = A.wait_for(lambda: A.resident(p, {me, rid}), 30)
        if q:
            qid = q["id"]
            p.call("set_behavior", [qid, json.dumps({"wait": 600})], "admin")
            p.call("place_at", [me, px, py], "admin")
            p.call("place_at", [qid, px - 3.0, py - 5.5], "admin")
            p.call("human_act", [json.dumps({"do": "face", "target": {"at": [px + 4.0, py]}})])
            time.sleep(1.6)
            seen_q = lambda: any(m["id"] == qid for m in p.sql("SELECT id FROM seen_bodies", "player"))
            standing_unseen = A.wait_for(lambda: not seen_q(), 2)
            # Look north standing (the whole body turns), then walk east: the travel is east at
            # once and the facing stays 75 degrees north of it, so Q is seen while walking away.
            face(0.0, -1.0, 0.5)
            p.call("human_move", [1.0, 0.0, False])
            # Several sweeps (200 ms) into the walk: had sight read the travel east, Q (more than
            # 118 degrees off it, beyond side vision's reach) would be gone by now.
            time.sleep(0.8)
            came = seen_q()
            mid = body(p)
            # Released while walking: the facing comes back to the travel east, and Q (now more
            # than 120 degrees off it) goes out of view.
            face(0.0, 0.0, 0.0)
            went = A.wait_for(lambda: not seen_q(), 1.5)
            qb = next((b for b in p.sql("SELECT id, x, y FROM body") if b["id"] == qid), None)
            EVIDENCE["facing_sight"] = {"q": qid, "q_at": qb and [qb["x"], qb["y"]], "walker_looking": mid, "walker_released": body(p), "unseen_standing_east": standing_unseen, "seen_walking_east_looking_north": came, "unseen_walking_east_released": went}
            A.check(p, "facing sight: standing facing east, Q behind to the north is out of view", standing_unseen, "seen_bodies")
            A.check(p, "walking east while looking north, Q comes into view (sight reads the facing)", came and mid and abs(mid["vy"]) < 1e-3 and mid["vx"] > 0, f"seen {bool(came)}, walker v ({mid and round(mid['vx'], 2)}, {mid and round(mid['vy'], 2)}) facing {mid and round(math.degrees(facing_end(mid)), 1)}")
            A.check(p, "and released while walking east, Q goes out of view (the facing is the travel again)", went, "seen_bodies")
            p.call("human_move", [0.0, 0.0, False])
            time.sleep(1.5)
            face(0.0, 0.0, 0.3)
            p.call("place_at", [me, px, py], "admin")
        else:
            A.check(p, "a second resident for facing sight", False, "none found within 30 s")

        p.call("human_move", [1.0, 0.0, False])
        time.sleep(0.8)
        face(0.0, -1.0, 0.6)
        p.call("human_move", [0.0, 0.0, False])
        time.sleep(2.0)
        bs = body(p)
        EVIDENCE["stopped"] = bs
        A.check(p, "stopping with the look held: the body stands and finishes the turn north", bs["vx"] == 0 and bs["vy"] == 0 and near(facing_end(bs), -math.pi / 2, 0.05) and near(heading_end(bs), -math.pi / 2, 0.05), f"facing {round(facing_end(bs), 2)} heading {round(heading_end(bs), 2)} v {bs['vx']},{bs['vy']}")
        face(0.0, 0.0, 0.3)

        reversal_check(p, me, (px, py))

        # 4. The input bucket, narrowed for the check by the laws (`set_world_law`): one input a
        #    second (the least the laws take: `input_hz` is clamped to 1..120), three in a burst.
        #    HTTP calls are slower than the shipped refill of 30 a second.
        p.call("set_world_law", ["input_hz", "1"], "admin")
        p.call("set_world_law", ["input_burst", "3"], "admin")
        time.sleep(4.0)  # the bucket fills to its burst of 3
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
