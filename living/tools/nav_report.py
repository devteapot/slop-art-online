#!/usr/bin/env python3
"""The navigation arenas' measures (docs/MOVEMENT_MIND.md §4, as §4.1 fixes them).

  living/tools/nav_report.py report DIR… [--json OUT]
  living/tools/nav_report.py selftest

Each DIR is a phase folder written by `nav_arena.py` (or a folder of them). Read-only, except
for `nav_optimal`'s input file per phase (`report-optimal.json`) beside the phase's evidence.

Per phase:
1. **Arrival rate**: walks ending within 2.5 m of their goal within 3 × the true optimal time.
2. **Time ÷ known-map optimal**: walked time over the optimal on the subject's belief at the
   order (`nav_optimal` on the snapshot): the path chosen on the belief, timed on the ground as
   it is at the subject's own pace (roads at road pace), so the ratio measures the hands and the
   planner and not the knowledge. A belief path through ground blocked in truth is reported.
3. **Time ÷ true optimal**: walked time over the true-map optimal at the order.
4. **Stuck events**: a subject with a walk under way that moves less than 0.15 m in 2 s while
   more than 2.5 m from its goal; per 10 walk-minutes, and the longest.
5. **Input latency**: from a stimulus to the subject's first body segment at or after it whose
   velocity turns more than 15° or changes speed by more than 30% against the velocity just
   before the stimulus (from standing, starting to move counts); none within 2 s is "no
   response", counted apart. Stimuli: N1 the order; N2 the first moment a shut gate tile is within
   the subject's ground sight (`ground_sight_m`) with a clear line; N3 a walker entering a 4 m,
   ±30° cone ahead; N4 the chaser or fixture turning more than 30° within the subject's sight.
Guards: body row updates per second (the subscription), `tick.motion` from `bench.txt`,
known_ground rows and bytes, re-plans per walk (a subject's `path` changing between orders).
A subject's pace is the median speed of its moving segments on non-road tiles (on roads, the
speed ÷ `road_speed`), so optimal metres at walking pace become seconds.
"""
import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "living/target")))
OPAQUE = (4, 7)
ROAD = 6


def pose(b, t):
    """Position and velocity of a body row at time t (ms): a turn for `turn_s`, then straight;
    still once its segment ends (`next_ms`)."""
    dt = max(0.0, (min(t, b["next_ms"]) - b["t_ms"]) / 1000.0)
    v = math.hypot(b["vx"], b["vy"])
    turn, ts = b.get("turn", 0.0) or 0.0, b.get("turn_s", 0.0) or 0.0
    if v == 0 or not turn or ts <= 0:
        p = (b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt)
        return p, ((0.0, 0.0) if t >= b["next_ms"] else (b["vx"], b["vy"]))
    h = b.get("heading", math.atan2(b["vy"], b["vx"]))
    a = min(dt, ts)
    h1 = h + turn * a
    x = b["x"] + v / turn * (math.sin(h1) - math.sin(h))
    y = b["y"] - v / turn * (math.cos(h1) - math.cos(h))
    p = (x + v * math.cos(h1) * (dt - a), y + v * math.sin(h1) * (dt - a))
    return p, ((0.0, 0.0) if t >= b["next_ms"] else (v * math.cos(h1), v * math.sin(h1)))


class Track:
    """One body's segments in time order."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: r["t_ms"])
        self.ts = [r["t_ms"] for r in self.rows]

    def at(self, t):
        import bisect
        i = bisect.bisect_right(self.ts, t) - 1
        return self.rows[i] if i >= 0 else None

    def where(self, t):
        r = self.at(t)
        return pose(r, t) if r else (None, None)

    def segments_from(self, t, until):
        return [r for r in self.rows if t <= r["t_ms"] <= until]


def load_bodies(path):
    tracks = {}
    if not Path(path).exists():
        return tracks
    for line in Path(path).read_text().splitlines():
        if not line.startswith("{"):
            continue
        try:
            u = json.loads(line)
        except ValueError:
            continue
        for r in (u.get("body") or {}).get("inserts", []):
            tracks.setdefault(r["id"], []).append(r)
    return {k: Track(v) for k, v in tracks.items()}


def changed(v0, v1):
    s0, s1 = math.hypot(*v0), math.hypot(*v1)
    if s0 < 0.05:
        return s1 >= 0.05
    if s1 < 0.05 or abs(s1 - s0) / s0 > 0.3:
        return True
    d = abs((math.atan2(v1[1], v1[0]) - math.atan2(v0[1], v0[0]) + math.pi) % (2 * math.pi) - math.pi)
    return d > math.radians(15)


def latency(track, t):
    """ms from a stimulus at t to the first segment at or after it that changes the velocity."""
    _, v0 = track.where(t - 1)
    if v0 is None:
        # No row before the stimulus: the body stood where it was placed.
        v0 = (0.0, 0.0)
    for r in track.segments_from(t, t + 2000):
        _, v1 = pose(r, r["t_ms"])
        if changed(v0, v1):
            return r["t_ms"] - t
    return None


def pace_of(track, tiles, W, road_speed):
    speeds = []
    for r in track.rows:
        v = math.hypot(r["vx"], r["vy"])
        if v < 0.3:
            continue
        x, y = int(r["x"]), int(r["y"])
        on_road = 0 <= x < W and tiles and tiles[y * W + x] == ROAD
        speeds.append(v / road_speed if on_road else v)
    return statistics.median(speeds) if speeds else None


def stuck_events(track, t0, t1, goal):
    events, start, t = [], None, t0 + 2000
    while t <= t1:
        (p, _), (q, _) = track.where(t), track.where(t - 2000)
        if p is None or q is None:
            t += 250
            continue
        still = math.dist(p, q) < 0.15 and math.dist(p, goal) > 2.5
        if still and start is None:
            start = t - 2000
        elif not still and start is not None:
            events.append((start, t))
            start = None
        t += 250
    if start is not None:
        events.append((start, t1))
    return events


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def optimal_beliefs(folder, walks, tiles_file, W, H, road, unknown):
    q = []
    for w in walks:
        snap = json.loads((folder / w["belief_file"]).read_text()) if (folder / w["belief_file"]).exists() else {"known": [], "edits": [], "gates_seen": []}
        q.append({"start": w["start"], "goal": w["goal"], "shut": [], **snap, "road_speed": road, "unknown_cost": unknown})
    f = folder / "report-optimal.json"
    f.write_text(json.dumps(q))
    out = subprocess.run([str(TARGET / "release/examples/nav_optimal"), str(tiles_file), str(W), str(H), str(f)], capture_output=True, text=True, timeout=1800)
    if out.returncode:
        raise RuntimeError(out.stderr[-400:])
    return [json.loads(l) for l in out.stdout.splitlines() if l.startswith("{")]


def gate_stimuli(track, t0, t1, tiles, W, shut, sight, line_clear):
    """The first moment within [t0, t1] a shut tile is within `sight` m with a clear line."""
    t = t0
    while t <= t1:
        p, _ = track.where(t)
        if p:
            for g in shut:
                c = (g[0] + 0.5, g[1] + 0.5)
                if math.dist(p, c) <= sight and line_clear(p, c):
                    return t
        t += 100
    return None


def cone_stimuli(sub, others, t0, t1, step=100):
    """Moments a body enters a 4 m, ±30° cone ahead of the subject (its direction of travel)."""
    out, inside = [], set()
    t = t0
    while t <= t1:
        p, v = sub.where(t)
        if p is None or math.hypot(*v) < 0.1:
            inside = set()
            t += step
            continue
        h = math.atan2(v[1], v[0])
        now = set()
        for oid, tr in others.items():
            q, _ = tr.where(t)
            if q is None:
                continue
            d = math.dist(p, q)
            if 0.01 < d <= 4.0 and abs((math.atan2(q[1] - p[1], q[0] - p[0]) - h + math.pi) % (2 * math.pi) - math.pi) <= math.radians(30):
                now.add(oid)
        out += [t] * len(now - inside)
        inside = now
        t += step
    return out


def contacts(sub, others, t0, t1, step=100):
    n, t, near = 0, t0, set()
    while t <= t1:
        p, _ = sub.where(t)
        cur = set()
        if p:
            for oid, tr in others.items():
                q, _ = tr.where(t)
                if q and math.dist(p, q) < 0.4:
                    cur.add(oid)
        n += len(cur - near)
        near = cur
        t += step
    return n


def chase_report(folder, ph, walks, tracks, line_clear):
    """N4: escapes, cornered flights, the chaser's turns and the subject's answers; for a pursuit,
    sight lost and regained, and capture."""
    sight = 48.0 if 6.0 <= (ph.get("hour") or 12) < 20.0 else 14.0
    rows, lat, no_resp = [], [], 0
    for w in walks:
        me, him = tracks.get(w["subject"]), tracks.get(w["fixture"])
        if not me or not him:
            rows.append({"subject": w["subject"], "missing_track": True})
            continue
        t0, t1 = w["start_ms"], w["end_ms"]
        p0, q0 = me.where(t0)[0], him.where(t0)[0]
        d0 = math.dist(p0, q0) if p0 and q0 else None
        r = {"subject": w["subject"], "start_gap_m": round(d0, 1) if d0 else None, "told": w.get("told")}
        unseen_from, escaped, lost, regained, captured, last_seen = None, None, 0, 0, None, None
        prev_vis, prev_h = True, None
        t = t0
        while t <= t1:
            p, q = me.where(t)[0], him.where(t)[0]
            if p and q:
                d = math.dist(p, q)
                vis = d <= sight and line_clear(p, q)
                if ph["variant"] in ("fu", "fk"):
                    if escaped is None and d0 and d >= d0 + (ph.get("flee_clear") or 9.0):
                        escaped = ("distance", t - t0)
                    if not vis:
                        unseen_from = unseen_from or t
                        if escaped is None and t - unseen_from >= 10000:
                            escaped = ("out of sight 10 s", t - t0)
                    else:
                        unseen_from = None
                else:
                    if prev_vis and not vis:
                        lost += 1
                        last_seen = q
                    if not prev_vis and vis:
                        regained += 1
                    if captured is None and d <= 1.5:
                        captured = t - t0
                prev_vis = vis
                # The chaser's (or fixture's) turns within the subject's sight are stimuli.
                _, v = him.where(t)
                if math.hypot(*v) > 0.1:
                    h = math.atan2(v[1], v[0])
                    if prev_h is not None and vis and abs((h - prev_h + math.pi) % (2 * math.pi) - math.pi) > math.radians(30):
                        l = latency(me, t)
                        if l is None:
                            no_resp += 1
                        else:
                            lat.append(l)
                    prev_h = h
            t += 100
        told = " ".join(w.get("told") or [])
        if ph["variant"] in ("fu", "fk"):
            r.update(escaped=escaped[0] if escaped else None, escape_ms=escaped[1] if escaped else None, cornered="cornered" in told)
        else:
            r.update(sight_lost=lost, sight_regained=regained, captured_ms=captured)
        rows.append(r)
    flights = [r for r in rows if "escaped" in r]
    pursuits = [r for r in rows if "sight_lost" in r]
    out = {"phase": folder.name, "arena": "n4", "variant": ph.get("variant"), "law": ph.get("law"), "kind": ph.get("kind"), "hour": ph.get("hour"), "walks": len(rows),
           "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95), "no_response": no_resp, "stimuli": len(lat) + no_resp, "walks_detail": rows}
    if flights:
        out.update(escape_rate=round(sum(r["escaped"] is not None for r in flights) / len(flights), 3), cornered_rate=round(sum(r["cornered"] for r in flights) / len(flights), 3))
    if pursuits:
        lost = sum(r["sight_lost"] for r in pursuits)
        out.update(sight_lost=lost, reacquired=sum(min(r["sight_regained"], r["sight_lost"]) for r in pursuits), captured=sum(r["captured_ms"] is not None for r in pursuits))
    return out


def phase_report(folder):
    folder = Path(folder)
    ph = json.loads((folder / "phase.json").read_text())
    walks = [json.loads(l) for l in (folder / "walks.jsonl").read_text().splitlines() if l.strip()] if (folder / "walks.jsonl").exists() else []
    tracks = load_bodies(folder / "bodies.jsonl")
    tiles_file = Path(ph["tiles_file"]) if ph.get("tiles_file") else None
    W, H = ph.get("W"), ph.get("H")
    tiles = tiles_file.read_bytes() if tiles_file and tiles_file.exists() else b""
    road = ph.get("laws", {}).get("road_speed") or 1.4
    unknown = ph.get("laws", {}).get("unknown_cost") or 1.5
    sight = ph.get("laws", {}).get("ground_sight_m") or 24

    def tile(x, y):
        x, y = int(math.floor(x)), int(math.floor(y))
        return tiles[y * W + x] if tiles and 0 <= x < W and 0 <= y < H else 4

    def line_clear(a, b):
        n = int(math.dist(a, b) * 2) + 1
        return all(tile(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) not in OPAQUE for k in range(n + 1))

    if ph["arena"] == "n4":
        out = chase_report(folder, ph, walks, tracks, line_clear)
        g = folder / "guards.json"
        if g.exists():
            out["guards"] = json.loads(g.read_text())
        return out
    test = walks
    if ph["arena"] == "n2":
        # The test walks are the last walk of each subject (after the warm-up).
        last = {}
        for w in walks:
            last[w["subject"]] = w
        test = list(last.values())
    beliefs = optimal_beliefs(folder, test, tiles_file, W, H, road, unknown) if tiles and test else [{}] * len(test)
    rows, lat, no_resp, stuck, walk_min, replans = [], [], 0, [], 0.0, []
    for w, b in zip(test, beliefs):
        tr = tracks.get(w["subject"])
        t_order = w["order_ms"][1]
        t_end = w.get("end_ms", t_order)
        walked = (t_end - t_order) / 1000
        pace = pace_of(tr, tiles, W, road) if tr else None
        true_s = w["true"]["time_m"] / pace if pace and w.get("true") else None
        bel = (b or {}).get("belief")
        known_s = bel["time_m"] / pace if pace and bel else None
        ok = w.get("outcome") == "arrived" and true_s is not None and walked <= 3 * true_s
        r = {"subject": w["subject"], "walk": w["walk"], "outcome": w.get("outcome"), "told": w.get("told"), "arrived_in_3x": ok, "belief_blocked_in_truth": bel.get("blocked_in_truth") if bel else None, "walked_s": round(walked, 1), "pace": round(pace, 2) if pace else None,
             "ratio_known": round(walked / known_s, 3) if known_s else None, "ratio_true": round(walked / true_s, 3) if true_s else None,
             "belief_unseen_tiles": bel.get("unseen_tiles") if bel else None, "prior_cells_in_box": w.get("prior_cells_in_box")}
        if tr:
            ev = stuck_events(tr, t_order, t_end, w["goal"])
            stuck += [(e[1] - e[0]) / 1000 for e in ev]
            walk_min += walked / 60
            paths = [json.dumps(s.get("path")) for s in tr.segments_from(t_order, t_end)]
            replans.append(sum(1 for a, c in zip(paths, paths[1:]) if a != c))
            stims = []
            if ph["arena"] in ("n1",):
                stims = [t_order]
            elif ph["arena"] == "n2":
                g = gate_stimuli(tr, t_order, t_end, tiles, W, [tuple(x) for x in ph["gate_a"]["tiles"]], sight, line_clear) if ph.get("variant") in ("a", "b") else None
                r["gate_seen_ms_after_order"] = (g - t_order) if g else None
                stims = [g] if g else []
                # Leak check: before the gate is seen, does the walk head for gate A?
                p0 = tr.segments_from(t_order, t_order + 1500)
                first = p0[0].get("path") if p0 else None
                pts = [(c["x"], c["y"]) if isinstance(c, dict) else tuple(c) for c in (first or [])]
                r["first_path_by_gate_a"] = any(math.dist(q, tuple(ph["gate_a"]["centre"])) < 8 for q in pts) if pts else None
                r["passed_gate_b"] = any(math.dist(tr.where(t)[0], tuple(ph["gate_b"]["centre"])) < 5 for t in range(int(t_order), int(t_end), 500) if tr.where(t)[0])
            if ph["arena"] == "n3":
                others = {k: v for k, v in tracks.items() if k in set(ph.get("walkers", []))}
                stims = cone_stimuli(tr, others, t_order, t_end)
                r["contacts_under_0_4m"] = contacts(tr, others, t_order, t_end)
            for s in stims:
                l = latency(tr, s)
                if l is None:
                    no_resp += 1
                else:
                    lat.append(l)
            r["latency_ms"] = [latency(tr, s) for s in stims]
        rows.append(r)
    arrived = sum(r["arrived_in_3x"] for r in rows)
    out = {"phase": folder.name, "arena": ph["arena"], "variant": ph.get("variant"), "law": ph.get("law"), "kind": ph.get("kind"), "walks": len(rows),
           "arrival_rate": round(arrived / len(rows), 3) if rows else None,
           "ratio_known_p50": pct([r["ratio_known"] for r in rows], 0.5), "ratio_known_p90": pct([r["ratio_known"] for r in rows], 0.9),
           "ratio_true_p50": pct([r["ratio_true"] for r in rows], 0.5), "ratio_true_p90": pct([r["ratio_true"] for r in rows], 0.9),
           "stuck_per_10min": round(len(stuck) / (walk_min / 10), 2) if walk_min else None, "stuck_longest_s": round(max(stuck), 1) if stuck else 0.0,
           "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95), "no_response": no_resp, "stimuli": len(lat) + no_resp,
           "replans_per_walk": round(statistics.mean(replans), 2) if replans else None, "walks_detail": rows}
    if ph["arena"] == "n3":
        out["contacts_under_0_4m"] = sum(r.get("contacts_under_0_4m", 0) for r in rows)
    g = folder / "guards.json"
    if g.exists():
        out["guards"] = json.loads(g.read_text())
    bench = folder / "bench.txt"
    if bench.exists():
        txt = bench.read_text()
        try:
            j = json.loads(txt[txt.index("{"):])
            sp = j.get("spans_ms", {}).get("tick.motion") or {}
            out["tick_motion"] = {k: sp.get(k) for k in ("ms_per_s", "p99", "max", "n")}
            out["tick_ms"] = {k: (j.get("tick_ms") or {}).get(k) for k in ("p99", "max", "over_16_7ms")}
            out["body_writes_per_s"] = (j.get("body_writes") or {}).get("row_updates_per_s")
        except (ValueError, AttributeError):
            out["bench"] = "unreadable"
    return out


def folders(paths):
    for p in map(Path, paths):
        if (p / "phase.json").exists():
            yield p
        else:
            yield from sorted(q for q in p.iterdir() if (q / "phase.json").exists())


def selftest():
    # A body standing, then walking east at 1.4 m/s from t=1000, then stopping for 3 s at t=5000.
    rows = [{"id": 1, "x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "t_ms": 0, "next_ms": 2**63, "heading": 0.0, "path": []},
            {"id": 1, "x": 0.0, "y": 0.0, "vx": 1.4, "vy": 0.0, "t_ms": 1040, "next_ms": 2**63, "heading": 0.0, "path": [[10, 0]]},
            {"id": 1, "x": 5.544, "y": 0.0, "vx": 0.0, "vy": 0.0, "t_ms": 5000, "next_ms": 2**63, "heading": 0.0, "path": [[10, 0]]},
            {"id": 1, "x": 5.544, "y": 0.0, "vx": 0.0, "vy": 1.4, "t_ms": 8000, "next_ms": 2**63, "heading": 1.57, "path": [[5.5, 10]]}]
    tr = Track(rows)
    assert latency(tr, 1000) == 40, latency(tr, 1000)
    assert latency(tr, 6500) == 1500 and latency(tr, 5500) is None
    ev = stuck_events(tr, 1000, 9000, (5.5, 10))
    assert len(ev) == 1 and 3000 <= ev[0][1] - ev[0][0] <= 3500 and abs(ev[0][0] - 5000) <= 250, ev
    assert changed((1.4, 0), (1.4 * math.cos(0.3), 1.4 * math.sin(0.3)))
    assert not changed((1.4, 0), (1.3, 0.1))
    assert pace_of(tr, b"", 0, 1.4) == 1.4
    assert pct([1, 2, 3, 4], 0.5) == 2.5
    print("nav_report selftest: ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("dirs", nargs="+")
    r.add_argument("--json")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    reps = [phase_report(f) for f in folders(a.dirs)]
    keys = ["phase", "walks", "arrival_rate", "ratio_known_p50", "ratio_known_p90", "ratio_true_p50", "ratio_true_p90", "stuck_per_10min", "stuck_longest_s", "latency_p50_ms", "latency_p95_ms", "no_response", "replans_per_walk"]
    chase = ["phase", "walks", "hour", "escape_rate", "cornered_rate", "sight_lost", "reacquired", "captured", "latency_p50_ms", "latency_p95_ms", "no_response"]
    for ks, sel in ((keys, lambda r: r["arena"] != "n4"), (chase, lambda r: r["arena"] == "n4")):
        group = [r for r in reps if sel(r)]
        if group:
            print("\t".join(ks))
            for rep in group:
                print("\t".join(str(rep.get(k)) for k in ks))
    if a.json:
        Path(a.json).write_text(json.dumps(reps, indent=1))


if __name__ == "__main__":
    sys.exit(main())
