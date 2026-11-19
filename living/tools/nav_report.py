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
5. **Response**: report command-to-first-write and command-to-physical-effect from
   act-correlated evidence, with a two-second window for each. A missing join is
   unobservable. Older geometric stimulus-to-segment results are retained as proxies.
   For N2 mid-close, report the first observed gate-bypassing route and velocity
   change on that route, timed separately from closure and geometric visibility.
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
import tempfile
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


def load_tracks(path):
    tracks, ground = {}, {}
    if path.exists():
        with path.open() as stream:
            for line in stream:
                if not line.startswith("{"):
                    continue
                try:
                    update = json.loads(line)
                except ValueError:
                    continue
                for row in update.get("body", {}).get("inserts", []):
                    tracks.setdefault(row["id"], []).append(row)
                for row in update.get("known_ground", {}).get("inserts", []):
                    ground.setdefault(row["actor"], []).append(row["last_ms"])
    return {k: Track(v) for k, v in tracks.items()}, ground


def ground_write_rate(walks, ground):
    by_actor = {}
    for walk in walks:
        start = walk.get("start_ms") if "start_ms" in walk else walk["order_ms"][1]
        end = walk.get("end_ms")
        if start is not None and end is not None and end > start:
            actor = walk["subject"]
            counts = by_actor.setdefault(actor, [0, 0])
            counts[0] += sum(start <= stamp < end for stamp in ground.get(actor, ()))
            counts[1] += end - start
    writes = sum(n for n, _ in by_actor.values())
    actor_ms = sum(ms for _, ms in by_actor.values())
    max_rate = max((1000 * n / ms for n, ms in by_actor.values()), default=None)
    return {"writes": writes, "actor_seconds": round(actor_ms / 1000, 2),
            "writes_per_actor_s": round(1000 * writes / actor_ms, 3) if actor_ms else None,
            "max_writes_per_actor_s": round(max_rate, 3) if max_rate is not None else None}


def changed(v0, v1):
    s0, s1 = math.hypot(*v0), math.hypot(*v1)
    if s0 < 0.05:
        return s1 >= 0.05
    if s1 < 0.05 or (s0 - s1) / s0 > 0.3:
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
        q.append({"start": w["start"], "goal": w["goal"], "shut": w.get("shut_tiles", []), **snap, "road_speed": road, "unknown_cost": unknown})
    f = folder / "report-optimal.json"
    f.write_text(json.dumps(q))
    out = subprocess.run([str(TARGET / "release/examples/nav_optimal"), str(tiles_file), str(W), str(H), str(f)], capture_output=True, text=True, timeout=1800)
    if out.returncode:
        raise RuntimeError(out.stderr[-400:])
    return [json.loads(l) for l in out.stdout.splitlines() if l.startswith("{")]


def json_lines(path):
    if path.exists():
        with path.open() as stream:
            for line in stream:
                if line.startswith("{"):
                    yield json.loads(line)


def response_summary(samples, key):
    values = [s[key] for s in samples if s[key] is not None]
    return {"p50_ms": pct(values, .5), "p90_ms": pct(values, .9), "p95_ms": pct(values, .95),
            "answered": len(values),
            "unanswered": sum(s[key] is None and s.get(key + "_observed", s["observed"])
                              for s in samples),
            "unobservable": sum(not s.get(key + "_observed", s["observed"]) for s in samples)}


def act_response(sent, act_id, tagged_segments, previous, end, segment_end=None):
    """Score a command from only its own authoritative writes in the response window.

    Each tagged segment is (act id, authoritative write time, body row). 'previous'
    carries the predecessor of that exact row, even if it was written after dispatch.
    """
    result = {"act_id": act_id, "first_write_ms": None, "physical_effect_ms": None,
              "observed": act_id is not None}
    baseline = None
    for key, stamp, row in tagged_segments:
        if act_id is None or key != act_id or not sent <= stamp <= min(end, sent + 2000):
            continue
        if result["first_write_ms"] is None:
            result["first_write_ms"] = stamp - sent
        if row is None:
            continue
        before = previous.get(id(row))
        if baseline is None and before is not None:
            baseline = pose(before, stamp)[1]
        if baseline is None:
            continue
        # A continuous turn can cross the threshold between writes. End the
        # observation at the next segment or at the end of this segment's motion.
        stop = min(end, sent + 2000, row["next_ms"] - 1)
        if segment_end is not None:
            stop = min(stop, segment_end[id(row)])
        timing = [stamp]
        if row.get("turn"):
            timing.extend(range(math.ceil(stamp + 1), math.floor(stop) + 1, 10))
        for at in timing:
            _, velocity = pose(row, at)
            if changed(baseline, velocity) and (before is None or changed(pose(before, at)[1], velocity)):
                result["physical_effect_ms"] = at - sent
                return result
    return result


def transaction_acts(path):
    """Consume the queued ID and open its activity in the same committed update."""
    pending, active, writes = {}, {}, {}
    captured = False
    for update in json_lines(path):
        captured |= "act_queue" in update or "activity" in update
        queue = update.get("act_queue", {})
        activities = update.get("activity", {})
        inserted = {a["id"]: a for a in activities.get("inserts", [])}
        started = set()
        removed = {}
        for act in queue.get("deletes", []):
            removed.setdefault(act["actor"], []).append(act)
        for act in queue.get("inserts", []):
            pending[act["id"]] = act
        for actor, acts in removed.items():
            activity = inserted.get(actor)
            if (activity and activity["node"] == 65534 and activity["skill"] == "goto"
                    and len(acts) == 1 and json.loads(acts[0]["node"]).get("do") == "goto"):
                act = acts[0]
                if act["id"] in pending:
                    active[actor] = (act["id"], activity["started_ms"])
                    started.add(actor)
        ended = {a["id"] for a in activities.get("deletes", []) if a["id"] not in inserted}
        for actor in inserted.keys() - started:
            if actor in active and inserted[actor]["started_ms"] != active[actor][1]:
                active.pop(actor, None)
        for row in update.get("body", {}).get("inserts", []):
            actor = row["id"]
            if actor in active:
                key, start = active[actor]
                # A first write in the activity's transaction has the reducer's
                # authoritative start stamp. Later rows can be anchor rewrites.
                if actor in started or (actor not in ended and row["t_ms"] > start):
                    stamp = start if actor in started else row["t_ms"]
                    writes.setdefault(actor, []).append((key, stamp, row))
        body_actors = {row["id"] for row in update.get("body", {}).get("inserts", [])}
        for row in update.get("steer", {}).get("inserts", []):
            actor = row["id"]
            if actor in started and actor not in body_actors:
                key, start = active[actor]
                writes.setdefault(actor, []).append((key, start, None))
        for actor in ended:
            active.pop(actor, None)
    return captured, pending, writes


def trace_acts(folder):
    """Read the latency branch's queue and synchronous goto-start write markers.

    The body marker inside goto's begin call precedes its act_started marker in
    the same reducer. Later body writes have no activity provenance in this trace.
    """
    markers = {}
    path = folder / "input-latency-authority-full.jsonl"
    if not path.exists():
        path = folder / "input-latency-authority.jsonl"
    for row in json_lines(path):
        message = row.get("message", "")
        if message.startswith("input_latency "):
            _, stage, actor, key, reducer, _, _, *detail = message.split()
            markers.setdefault(int(actor), []).append(
                (row["ts"] / 1000, stage, int(key), int(reducer), detail))
    return markers


def walk_response(walk, track, trace, transactions, next_send):
    actor = walk["subject"]
    sent, ack = walk.get("order_send_wall_ms"), walk.get("order_ack_wall_ms")
    result = {"act_id": None, "first_write_ms": None, "physical_effect_ms": None, "observed": False}
    if sent is None or not track:
        return result
    captured, pending, writes = transactions
    stop = min(walk.get("end_ms", sent + 2000), next_send)
    previous = {id(row): before for before, row in zip(track.rows, track.rows[1:])}
    segment_end = {id(row): following["t_ms"] - 1 for row, following in zip(track.rows, track.rows[1:])}
    if track.rows:
        segment_end[id(track.rows[-1])] = stop
    target = walk["waypoints"][0] if walk.get("waypoints") else walk["goal"]
    candidates = []
    segments = []
    if trace:
        candidates = [key for stamp, stage, key, _, detail in trace
                      if stage == "act_queued" and sent <= stamp <= ack and detail[-1] == "goto"]
        if len(candidates) == 1:
            key = candidates[0]
            for i, (stamp, stage, started, txn, _) in enumerate(trace):
                if stage != "act_started" or started != key or stamp > stop:
                    continue
                # Only writes inside this invocation of the actor's goto begin.
                for written, event, segment, other_txn, detail in reversed(trace[:i]):
                    if other_txn != txn or event == "act_attempt":
                        break
                    if event == "body_written":
                        rows = [row for row in track.segments_from(segment, segment)
                                if all(math.isclose(row[field], float(value), abs_tol=1e-5)
                                       for field, value in zip(("vx", "vy"), detail))]
                        segments.append((key, written, rows[0] if len(rows) == 1 else None))
                segments.reverse()
                break
    elif captured:
        source = "human" if walk.get("kind") == "click" else "nav-arena"
        candidates = [key for key, act in pending.items()
                      if act["actor"] == actor and act["source"] == source
                      and sent < act["at_ms"] + 1 and act["at_ms"] <= ack
                      and json.loads(act["node"]).get("target", {}).get("at") == target]
        # Reuse the track's row objects so the predecessor lookup is unambiguous.
        segments = [(key, max(sent, stamp), next((r for r in track.segments_from(row["t_ms"], row["t_ms"])
                                      if r == row), None) if row is not None else None)
                    for key, stamp, row in writes.get(actor, ())]
    if len(candidates) == 1:
        result = act_response(sent, candidates[0], segments, previous, stop, segment_end)
        if trace and result["physical_effect_ms"] is None:
            # The historical trace stops attributing writes when begin returns.
            result["physical_effect_ms_observed"] = False
    return result


def path_crosses(start, path, tiles):
    """Whether the remaining waypoint polyline crosses any of the specified tiles."""
    for point in path:
        end = (point["x"], point["y"]) if isinstance(point, dict) else tuple(point)
        steps = max(1, math.ceil(math.dist(start, end) * 8))
        if any(tuple(math.floor(a + (b - a) * n / steps) for a, b in zip(start, end))
               in tiles for n in range(steps + 1)):
            return True
        start = end
    return False


def reroute_response(track, closed, visible, end, tiles, goal):
    """Require a complete alternative route to the same goal after closure."""
    write, effect, baseline = None, None, None
    for before, row in zip(track.rows, track.rows[1:]):
        stamp = row["t_ms"]
        if not closed <= stamp <= end or not row["path"]:
            continue
        last = row["path"][-1]
        endpoint = (last["x"], last["y"]) if isinstance(last, dict) else tuple(last)
        if math.dist(endpoint, goal) > 0.1 or path_crosses((row["x"], row["y"]), row["path"], tiles):
            continue
        if write is None:
            write = stamp
            baseline = pose(before, stamp)[1]
        if changed(baseline, pose(row, stamp)[1]):
            effect = stamp
            break
    return {"reroute_segment_ms": write, "reroute_effect_segment_ms": effect,
            "closure_to_reroute_ms": write - closed if write is not None else None,
            "closure_to_effect_ms": effect - closed if effect is not None else None,
            "visibility_to_reroute_ms": write - visible if write is not None and visible is not None else None,
            "visibility_to_effect_ms": effect - visible if effect is not None and visible is not None else None}


def gate_stimuli(track, t0, t1, shut, sight, line_clear):
    """The first moment within [t0, t1] a shut tile is within `sight` m with a clear line."""
    t = t0
    while t <= t1:
        p, _ = track.where(t)
        if p:
            for g in shut:
                c = (g[0] + 0.5, g[1] + 0.5)
                if math.dist(p, c) <= sight(t) and line_clear(p, c):
                    return t
        t += 16
    return None


def cone_stimuli(sub, others, t0, t1, step=16):
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


def contacts(sub, others, t0, t1, step=16):
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


def chase_stalls(folder, tracks, walks):
    path = folder / "intents.jsonl"
    if not path.exists():
        return {}
    windows = {w["subject"]: (w["start_ms"], w["end_ms"]) for w in walks if w["start_ms"] is not None}
    active_ms, stamps, still, lengths = 0, {}, {}, []
    for line in path.read_text().splitlines():
        sample = json.loads(line)
        stamp = sample["at_ms"]
        active = set()
        for row in sample["steer"]:
            actor, goal = row["id"], row["goal"]
            start, end = windows.get(actor, (0, 0))
            track = tracks.get(actor)
            if goal not in (1, 2, 4) or not track or not start <= stamp <= end:
                continue
            at, _ = track.where(stamp)
            if at is None:
                continue
            active.add(actor)
            prev = stamps.get(actor, stamp)
            active_ms += stamp - prev
            stamps[actor] = stamp
            target = tracks.get(row["target"])
            if target and not row.get("unseen_ms"):
                dest, _ = target.where(stamp)
            else:
                dest = (row["gx"], row["gy"])
            before, _ = track.where(stamp - 2000)
            distance = math.dist(at, dest) if dest else 0
            left = row["keep"] - distance if goal == 4 else distance - row["keep"]
            if before and stamp - start >= 2000 and left > 2.5 and math.dist(at, before) < 0.15:
                still.setdefault(actor, stamp)
            elif actor in still:
                lengths.append(max(2000, prev - still.pop(actor) + 2000))
        for actor in stamps.keys() - active:
            if actor in still:
                lengths.append(stamps[actor] - still.pop(actor) + 2000)
            del stamps[actor]
    lengths.extend(stamps[actor] - start + 2000 for actor, start in still.items())
    return {"stuck_per_10min": round(len(lengths) * 600_000 / active_ms, 2) if active_ms else None,
            "stuck_longest_s": round(max(lengths, default=0) / 1000, 1), "active_s": round(active_ms / 1000, 1)}


def chase_report(folder, ph, walks, tracks, line_clear):
    """N4: escapes, cornered flights, the chaser's turns and the subject's answers; for a pursuit,
    sight lost and regained, and capture."""
    sight = ph.get("sight_m", 11.0 if 6.0 <= ph["hour"] < 20.0 else 6.0)
    rows, lat, no_resp = [], [], 0
    for w in walks:
        me, him = tracks.get(w["subject"]), tracks.get(w["fixture"])
        if not me or not him:
            rows.append({"subject": w["subject"], "missing_track": True})
            continue
        t0, t1 = w["start_ms"], w["end_ms"]
        if t0 is None:
            rows.append({"subject": w["subject"], "chase_did_not_start": True})
            continue
        p0, q0 = me.where(t0)[0], him.where(t0)[0]
        d0 = math.dist(p0, q0) if p0 and q0 else None
        r = {"subject": w["subject"], "start_gap_m": round(d0, 1) if d0 else None, "told": w.get("told")}
        unseen_from, escaped, lost, regained, captured, last_seen = None, None, 0, 0, None, None
        still_near = False
        eligible = 0
        prev_vis, prev_h = None, None
        t = t0
        while t <= min(t1, t0 + 60_000):
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
                    if prev_vis is True and not vis:
                        lost += 1
                        still_near = True
                    if last_seen is not None and (not vis or prev_vis is False):
                        still_near &= math.dist(last_seen, q) <= 10
                    if prev_vis is False and vis and still_near:
                        eligible += 1
                        regained += 1
                    if vis:
                        last_seen = q
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
            r.update(sight_lost=lost, sight_lost_within_10m=eligible + int(prev_vis is False and still_near),
                     sight_regained=regained, captured_ms=captured)
        rows.append(r)
    flights = [r for r in rows if "escaped" in r]
    pursuits = [r for r in rows if "sight_lost" in r]
    out = {"phase": folder.name, "source_run": folder.parent.name, "arena": "n4", "variant": ph.get("variant"), "law": ph.get("law"), "kind": ph.get("kind"), "hour": ph.get("hour"), "light": ph.get("light"), "walks": len(rows),
           "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95), "no_response": no_resp, "stimuli": len(lat) + no_resp, "walks_detail": rows}
    samples = [{"first_write_ms": None, "physical_effect_ms": None, "observed": False}
               for _ in range(len(lat) + no_resp)]
    out.update(first_write=response_summary(samples, "first_write_ms"),
               physical_effect=response_summary(samples, "physical_effect_ms"),
               proxy_latency_p90_ms=pct(lat, .9))
    out.update(chase_stalls(folder, tracks, walks))
    if flights:
        out.update(escape_rate=round(sum(r["escaped"] is not None for r in flights) / len(flights), 3), cornered_rate=round(sum(r["cornered"] for r in flights) / len(flights), 3))
    if pursuits:
        out.update(sight_lost=sum(r["sight_lost"] for r in pursuits),
                   sight_lost_within_10m=sum(r["sight_lost_within_10m"] for r in pursuits),
                   reacquired=sum(r["sight_regained"] for r in pursuits), captured=sum(r["captured_ms"] is not None for r in pursuits))
    out["valid_chases"] = len(flights) + len(pursuits)
    return out


def phase_report(folder, response_only=False):
    folder = Path(folder)
    ph = json.loads((folder / "phase.json").read_text())
    walks = [json.loads(l) for l in (folder / "walks.jsonl").read_text().splitlines() if l.strip()] if (folder / "walks.jsonl").exists() else []
    tracks, ground = load_tracks(folder / "bodies.jsonl")
    tiles_file = Path(ph["tiles_file"]) if ph.get("tiles_file") else None
    W, H = ph.get("W"), ph.get("H")
    if tiles_file and not tiles_file.exists():
        for parent in folder.resolve().parents:
            candidate = parent / "verify" / tiles_file.parent.name / tiles_file.name
            if candidate.exists():
                tiles_file = candidate
                break
    tiles = tiles_file.read_bytes() if tiles_file and tiles_file.exists() else b""
    road = ph.get("laws", {}).get("road_speed") or 1.4
    unknown = ph.get("laws", {}).get("unknown_cost") or 1.5
    sight = ph.get("laws", {}).get("ground_sight_m") or 24
    calendar = ph.get("calendar")

    def sight_at(t):
        if calendar:
            day_ms = calendar["day_ms"]
            hour = ((t - calendar["epoch_ms"] + day_ms * 7 // 24) % day_ms) * 24 / day_ms
            if not 6 <= hour < 20:
                return min(sight, 6.0)
        return sight

    def tile(x, y):
        x, y = int(math.floor(x)), int(math.floor(y))
        return tiles[y * W + x] if tiles and 0 <= x < W and 0 <= y < H else 4

    def line_clear(a, b):
        n = int(math.dist(a, b) * 2) + 1
        return all(tile(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) not in OPAQUE for k in range(n + 1))

    if ph["arena"] == "n4":
        out = chase_report(folder, ph, walks, tracks, line_clear)
        if ground or (folder / "subscribe.log").exists():
            out["known_ground_writes"] = ground_write_rate(walks, ground)
        return add_guards(out, folder)
    test = walks
    if ph["arena"] == "n2":
        # The test walks are the last walk of each subject (after the warm-up).
        last = {}
        for w in walks:
            last[w["subject"]] = w
        test = list(last.values())
    beliefs = optimal_beliefs(folder, test, tiles_file, W, H, road, unknown) if tiles and test and not response_only else [{}] * len(test)
    trace = trace_acts(folder)
    transactions = transaction_acts(folder / "bodies.jsonl") if not trace else (False, {}, {})
    stimuli_log = {s["what"]: s for s in json_lines(folder / "stimuli.jsonl")}
    gate_memory = {}
    if ph["arena"] == "n2" and ph["variant"] == "mid-close":
        gate_ids = set(ph["gate_a"]["ids"])
        for update in json_lines(folder / "bodies.jsonl"):
            for row in update.get("remembered", {}).get("inserts", []):
                if row["kind"] == 1 and row["state"] == 0 and row["target"] in gate_ids:
                    gate_memory.setdefault(row["observer"], []).append(row["seen_ms"])
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
        completed = w.get("outcome") == "arrived"
        r = {"subject": w["subject"], "walk": w["walk"], "outcome": w.get("outcome"), "told": w.get("told"), "failure": w.get("failure"), "reachable": w.get("true") is not None, "arrived_in_3x": ok, "belief_blocked_in_truth": bel.get("blocked_in_truth") if bel else None, "walked_s": round(walked, 1), "pace": round(pace, 2) if pace else None,
             "ratio_known": round(walked / known_s, 3) if completed and known_s else None, "ratio_true": round(walked / true_s, 3) if completed and true_s else None,
             "belief_unseen_tiles": bel.get("unseen_tiles") if bel else None, "prior_cells_in_box": w.get("prior_cells_in_box")}
        if ph["arena"] in ("n1", "n2"):
            next_send = min((s["order_send_wall_ms"] for s in test
                             if s["subject"] == w["subject"] and s["walk"] > w["walk"]
                             and "order_send_wall_ms" in s), default=math.inf)
            response = walk_response(w, tr, trace.get(w["subject"], ()), transactions, next_send)
            if ph["arena"] == "n1":
                r["responses"] = [response]
            else:
                r["dispatch_response"] = response
        if tr:
            ev = stuck_events(tr, t_order, t_end, w["goal"])
            stuck += [(e[1] - e[0]) / 1000 for e in ev]
            walk_min += walked / 60
            paths = [json.dumps(s.get("path")) for s in tr.segments_from(t_order, t_end)]
            replans.append(sum(1 for a, c in zip(paths, paths[1:]) if a != c))
            stims = []
            if ph["arena"] in ("n1",):
                stims = [w["order_ms"][0]]
            elif ph["arena"] == "n2":
                closed = stimuli_log.get("gate shut", {})
                gate_tiles = {tuple(x) for x in ph["gate_a"]["tiles"]}
                close_ms = closed.get("completed_ms")
                mid = ph["variant"] == "mid-close"
                g = None
                if ph["variant"] in ("a", "b", "mid-close") and tiles and (not mid or closed.get("all_shut")):
                    g = gate_stimuli(tr, max(t_order, close_ms or t_order), t_end,
                                     gate_tiles, sight_at, line_clear)
                if mid:
                    before = stimuli_log.get("before gate close", {})
                    planned = before.get("routes", {}).get(str(w["subject"]), False)
                    close_started = closed.get("started_ms")
                    memory = min((stamp for stamp in gate_memory.get(w["subject"], ())
                                  if close_started is not None and close_started <= stamp <= t_end), default=None)
                    r.update(route_via_gate_before_close=planned, gate_closed_ms=close_ms,
                             gate_first_closed_ms=close_started, gate_memory_ms=memory)
                    if planned and closed.get("all_shut") and close_started is not None:
                        r.update(reroute_response(tr, close_started, g, t_end, gate_tiles, w["goal"]))
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
            if ph["arena"] != "n1":
                r["responses"] = [{"first_write_ms": None, "physical_effect_ms": None,
                                   "observed": False} for _ in stims]
        rows.append(r)
    arrived = sum(r["arrived_in_3x"] for r in rows)
    reachable = sum(r["reachable"] for r in rows)
    out = {"phase": folder.name, "source_run": folder.parent.name, "arena": ph["arena"], "variant": ph.get("variant"), "law": ph.get("law"), "kind": ph.get("kind"), "walks": len(rows),
           "reachable": reachable, "arrived_in_3x": arrived, "arrival_rate": round(arrived / reachable, 3) if reachable else None,
           "could_not_get_there": sum("could not get there" in (r["failure"] or " ".join(r["told"] or ())) for r in rows),
           "ratio_known_p50": pct([r["ratio_known"] for r in rows], 0.5), "ratio_known_p90": pct([r["ratio_known"] for r in rows], 0.9),
           "ratio_true_p50": pct([r["ratio_true"] for r in rows], 0.5), "ratio_true_p90": pct([r["ratio_true"] for r in rows], 0.9),
           "stuck_per_10min": round(len(stuck) / (walk_min / 10), 2) if walk_min else None, "stuck_longest_s": round(max(stuck), 1) if stuck else 0.0,
           "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95), "no_response": no_resp, "stimuli": len(lat) + no_resp,
           "replans_per_walk": round(statistics.mean(replans), 2) if replans else None, "walks_detail": rows}
    samples = [response for row in rows for response in row.get("responses", ())]
    out["first_write"] = response_summary(samples, "first_write_ms")
    out["physical_effect"] = response_summary(samples, "physical_effect_ms")
    out["proxy_latency_p90_ms"] = pct(lat, .9)
    if ph["arena"] == "n2":
        dispatch = [row["dispatch_response"] for row in rows]
        out["dispatch_first_write"] = response_summary(dispatch, "first_write_ms")
        out["dispatch_physical_effect"] = response_summary(dispatch, "physical_effect_ms")
    if ph["arena"] == "n3":
        out["contacts_under_0_4m"] = sum(r.get("contacts_under_0_4m", 0) for r in rows)
    if ph["arena"] == "n2":
        out["gate_a_shut_at_test_start"] = ph.get("gate_a_shut_at_test_start")
        out["gate_a_reopened_at_test_start"] = ph.get("gate_a_reopened_at_test_start")
        out["warmup_arrivals"] = [ph.get("warmups_arrived"), ph.get("warmups")]
        out["gate_a_remembered_open"] = sum(1 in states for states in ph["remembered_a_states_at_order"].values())
        out["gate_a_remembered_shut"] = sum(0 in states for states in ph["remembered_a_states_at_order"].values())
        out["gate_b_remembered_open"] = sum(1 in states for states in ph.get("remembered_b_states_at_order", {}).values())
        out["first_path_by_gate_a"] = sum(r.get("first_path_by_gate_a") is True for r in rows)
        out["passed_gate_b"] = sum(r.get("passed_gate_b") is True for r in rows)
        out["bench_window"] = ph.get("bench_window", "warmup")
    if ph["arena"] == "n1" and ph["variant"] == "d":
        goal = ph["goals"][1]
        out["offset_goal_error_m"] = [
            round(math.dist(w["end"], goal), 2) for w in test if w["walk"] == 1 and w.get("end")]
    if ground or (folder / "subscribe.log").exists():
        out["known_ground_writes"] = ground_write_rate(test, ground)
    return add_guards(out, folder)


def add_guards(out, folder):
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
            out["tick_ms"] = {k: (j.get("tick_ms") or {}).get(k) for k in (
                "samples", "p99", "max", "over_16_7ms", "over_16_7ms_without_motion_within_budget")}
            out["population"] = {"people": j.get("people"), "animals": j.get("animals"), "ticks_per_s": j.get("ticks_per_s")}
            ticks, samples = j["seconds"] * j["ticks_per_s"], out["tick_ms"]["samples"]
            if ticks > 0 and samples:
                # The CLI log tail can cover only part of the profile window. Express motion
                # time per second of sampled ticks at the clock's measured tick rate.
                out["tick_ms"]["sample_fraction"] = round(samples / ticks, 3)
                if sp.get("ms_per_s") is not None and abs(sp["n"] - samples) <= 1:
                    out["tick_motion"]["sample_ms_per_s"] = round(sp["ms_per_s"] * ticks / samples, 2)
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
    assert not changed((1.4, 0), (2.0, 0))
    assert pace_of(tr, b"", 0, 1.4) == 1.4
    assert pct([1, 2, 3, 4], 0.5) == 2.5
    writes = ground_write_rate([{"subject": 1, "order_ms": [900, 1000], "end_ms": 6000}], {1: [900, 1000, 5000, 6000]})
    assert writes == {"writes": 2, "actor_seconds": 5.0, "writes_per_actor_s": 0.4, "max_writes_per_actor_s": 0.4}
    # An unrelated write after send and before the accepted act cannot answer.
    _, early, same, turn = rows
    sent = 1000
    same = dict(same, t_ms=1100, vx=1.4)
    turn = dict(turn, t_ms=1200)
    previous = {id(same): early, id(turn): same}
    tags = [(7, 990, early), (6, 1040, early), (7, 1100, same), (7, 1200, turn)]
    assert act_response(sent, 7, tags[:2], previous, 3000)["first_write_ms"] is None
    write = act_response(sent, 7, tags[:3], previous, 3000)
    assert write["first_write_ms"] == 100 and write["physical_effect_ms"] is None
    effect = act_response(sent, 7, tags, previous, 3000)
    assert effect["first_write_ms"] == 100 and effect["physical_effect_ms"] == 200
    assert path_crosses((0.5, 0.5), [{"x": 2.5, "y": 0.5}], {(1, 0)})
    queued = {"id": 7, "actor": 1, "at_ms": 1005, "source": "nav-arena",
              "node": json.dumps({"do": "goto", "target": {"at": [9, 9]}})}
    activity = {"id": 1, "skill": "goto", "node": 65534, "started_ms": 1100}
    updates = [
        {"act_queue": {"inserts": [queued]}, "body": {"inserts": [rows[0]]}},
        {"body": {"inserts": [early]}},
        {"act_queue": {"deletes": [queued]}, "activity": {"inserts": [activity]},
         "body": {"inserts": [same]}},
        {"body": {"inserts": [turn]}},
        {"activity": {"deletes": [activity]}, "body": {"inserts": [rows[-1]]}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bodies.jsonl"
        path.write_text("".join(json.dumps(update) + "\n" for update in updates))
        tx = transaction_acts(path)
        sample = walk_response({"subject": 1, "order_send_wall_ms": 1000, "order_ack_wall_ms": 1010,
                                "end_ms": 3000, "goal": [9, 9]}, Track([rows[0], early, same, turn]),
                               (), tx, math.inf)
        assert sample == effect, sample
        assert len(tx[2][1]) == 2, tx
    print("nav_report selftest: ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("dirs", nargs="+")
    r.add_argument("--json")
    r.add_argument("--response-only", action="store_true", help="skip the archived optimal-path calculation")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    reps = [phase_report(f, a.response_only) for f in folders(a.dirs)]
    keys = ["phase", "walks", "arrival_rate", "ratio_known_p50", "ratio_known_p90", "ratio_true_p50", "ratio_true_p90", "stuck_per_10min", "stuck_longest_s", "latency_p50_ms", "latency_p95_ms", "no_response", "replans_per_walk", "first_write", "physical_effect"]
    chase = ["phase", "walks", "hour", "escape_rate", "cornered_rate", "sight_lost", "reacquired", "captured", "latency_p50_ms", "latency_p95_ms", "no_response", "first_write", "physical_effect"]
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
