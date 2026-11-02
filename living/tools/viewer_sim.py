#!/usr/bin/env python3
"""Replay recorded `body` arrivals through the observer's display logic, frame by frame.

Input: a recording from `jitter_probe.py --record` (local arrival time and the body rows of
each transaction). Simulates a viewer at `--fps` that sees each transaction at the first
frame after it arrives (plus optional extra latency/jitter and a clock offset, as a viewer
on another device or behind a tunnel would), with two display methods:

- `wall`: the viewer before 2026-09-28: the segment of the latest row at the local wall
  clock (held at `next_ms`), eased towards it (rate 14/s), snapping beyond 4 tiles;
- `sync`: `living/viewer/src/sync.rs`: an authority clock estimated from row times and
  shown slightly in the past, segments switched in time order, late rows blended out
  (time constant 40 ms), snapping beyond 2 tiles.

For every frame and moving body it compares the displayed movement since the previous
frame with the authority's own motion over the same display interval (the rows in effect
at those instants: what the authority computes, including any stand at a segment end):
`speed_error` (tiles/s) and `stutter` (frames where the body moves at under half the
authority's speed, or over 1.5 times it). It also reports the authority's own stands:
frames in which a body with a moving row is held at the end of its segment.

Usage: living/tools/viewer_sim.py REC.jsonl [--fps 120] [--offset-ms 0] [--latency-ms 0]
       [--jitter-ms 0] [--seed 1]
"""
import argparse
import bisect
import collections
import json
import math
import random

import os
WINDOW_MS, LATE_SHARE, MARGIN_MS, SLEW, RESYNC_MS = 4000.0, float(os.environ.get("LATE_SHARE", 0.02)), 4.0, 0.1, 1000.0
BLEND_MAX, BLEND_TAU = 2.0, 0.04


def pose(r, t):
    vx, vy = r["vx"], r["vy"]
    v = math.hypot(vx, vy)
    dt = max(0.0, (min(t, r["next_ms"]) - r["t_ms"]) / 1000)
    turn, ts = r.get("turn", 0.0) or 0.0, r.get("turn_s", 0.0) or 0.0
    if v == 0 or not turn or ts <= 0:
        return r["x"] + vx * dt, r["y"] + vy * dt
    h = r["heading"]
    a = min(dt, ts)
    h1 = h + turn * a
    x = r["x"] + v / turn * (math.sin(h1) - math.sin(h))
    y = r["y"] - v / turn * (math.cos(h1) - math.cos(h))
    return x + v * math.cos(h1) * (dt - a), y + v * math.sin(h1) * (dt - a)


def seg_key(r):
    return (r["x"], r["y"], r["t_ms"], r["vx"], r["vy"], r["heading"], r["turn"], r["turn_s"], r["next_ms"])


class Truth:
    """The authority's motion: per body, rows in time order; at time t the row with the
    latest `t_ms` <= t."""

    def __init__(self):
        self.rows = collections.defaultdict(list)

    def add(self, r):
        rows = self.rows[r["id"]]
        rows.append(r)

    def finish(self):
        self.ts = {}
        for i, rows in self.rows.items():
            rows.sort(key=lambda r: r["t_ms"])
            self.ts[i] = [r["t_ms"] for r in rows]

    def at(self, i, t):
        k = bisect.bisect_right(self.ts[i], t) - 1
        if k < 0:
            return None
        return self.rows[i][k]


class Wall:
    def __init__(self, offset):
        self.offset = offset
        self.rows = {}
        self.shown = {}

    def frame(self, local, dt):
        now = math.floor(local)
        k = 1 - math.exp(-dt * 14)
        out = {}
        for i, r in self.rows.items():
            tx, ty = pose(r, now)
            p = self.shown.get(i, (tx, ty))
            if math.hypot(tx - p[0], ty - p[1]) > 4:
                p = (tx, ty)
            else:
                p = (p[0] + (tx - p[0]) * k, p[1] + (ty - p[1]) * k)
            self.shown[i] = p
            out[i] = p
        return now, out


class Sync:
    def __init__(self, offset, wall0):
        self.off = -100.0  # assumes the local clock is the authority's until rows arrive
        self.synced = False
        self.lags = collections.deque()
        self.latest = 0
        self.last = None
        self.tracks = {}
        self.rows = {}

    def clock(self, local):
        dt = 0.0 if self.last is None else max(0.0, local - self.last)
        self.last = local
        if self.latest:
            self.lags.append((local, self.latest - local))
            self.latest = 0
        while self.lags and local - self.lags[0][0] > WINDOW_MS:
            self.lags.popleft()
        if self.lags:
            s = sorted(l for _, l in self.lags)
            k = min(len(s) - 1, int(len(s) * LATE_SHARE))
            target = s[k] - MARGIN_MS
            gap = target - self.off
            if not self.synced or abs(gap) > RESYNC_MS:
                self.off = target
                self.synced = True
            else:
                self.off += max(-SLEW * dt, min(SLEW * dt, gap))
        return local + self.off

    def frame(self, local, dt):
        now = self.clock(local)
        decay = math.exp(-dt / BLEND_TAU)
        out = {}
        for i, r in self.rows.items():
            tr = self.tracks.get(i)
            if tr is None:
                tr = self.tracks[i] = {"cur": r, "queue": [], "seen": seg_key(r), "corr": (0.0, 0.0)}
            if seg_key(r) != tr["seen"]:
                tr["seen"] = seg_key(r)
                if r["t_ms"] > now:
                    while tr["queue"] and tr["queue"][-1]["t_ms"] >= r["t_ms"]:
                        tr["queue"].pop()
                    tr["queue"] = tr["queue"][-7:] + [r]
                else:
                    tr["queue"] = []
                    self.switch(tr, r, now)
            while tr["queue"] and tr["queue"][0]["t_ms"] <= now:
                q = tr["queue"].pop(0)
                self.switch(tr, q, q["t_ms"])
            c = tr["corr"]
            tr["corr"] = (c[0] * decay, c[1] * decay)
            x, y = pose(tr["cur"], now)
            out[i] = (x + tr["corr"][0], y + tr["corr"][1])
        return now, out

    @staticmethod
    def switch(tr, r, now):
        bx, by = pose(tr["cur"], now)
        bx, by = bx + tr["corr"][0], by + tr["corr"][1]
        ax, ay = pose(r, now)
        c = (bx - ax, by - ay)
        tr["corr"] = (0.0, 0.0) if math.hypot(*c) > BLEND_MAX else c
        tr["cur"] = r


def q(xs, f):
    return round(xs[min(len(xs) - 1, int(f * (len(xs) - 1)))], 3) if xs else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec")
    ap.add_argument("--fps", type=float, default=120.0)
    ap.add_argument("--offset-ms", type=float, default=0.0, help="viewer clock minus authority clock")
    ap.add_argument("--latency-ms", type=float, default=0.0, help="extra delivery delay")
    ap.add_argument("--jitter-ms", type=float, default=0.0, help="extra random delay 0..J per transaction (order kept)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    recs = [json.loads(l) for l in open(a.rec)]
    initial, txs = recs[0], recs[1:]
    truth = Truth()
    for r in initial["body"].get("inserts", []):
        truth.add(r)
    arrivals = []
    last = 0.0
    for t in txs:
        at = max(last, t["recv"] + a.latency_ms + rnd.random() * a.jitter_ms)
        last = at
        arrivals.append((at, t["body"].get("inserts", [])))
        for r in t["body"].get("inserts", []):
            truth.add(r)
    truth.finish()
    start, end = txs[0]["recv"] + 5000, txs[-1]["recv"]
    views = {"wall": Wall(a.offset_ms), "sync": Sync(a.offset_ms, start)}
    for v in views.values():
        for r in initial["body"].get("inserts", []):
            v.rows[r["id"]] = r
    period = 1000.0 / a.fps
    k = 0
    prev = {name: None for name in views}
    res = {name: {"err": [], "stutter": 0, "frames": 0, "delay": []} for name in views}
    held = moving_frames = 0
    wall = txs[0]["recv"]
    while wall < end:
        while k < len(arrivals) and arrivals[k][0] <= wall:
            for r in arrivals[k][1]:
                for name, v in views.items():
                    v.rows[r["id"]] = r
                    if name == "sync":
                        v.latest = max(v.latest, r["t_ms"])
            k += 1
        for name, v in views.items():
            local = wall + a.offset_ms
            now, out = v.frame(local, period / 1000)
            if prev[name] is not None and wall >= start:
                pnow, pout = prev[name]
                for i, p in out.items():
                    if i not in pout:
                        continue
                    r1, r0 = truth.at(i, now), truth.at(i, pnow)
                    if r1 is None or r0 is None:
                        continue
                    if not (r1["vx"] or r1["vy"]):
                        continue
                    t1, t0 = pose(r1, now), pose(r0, pnow)
                    tv = math.hypot(t1[0] - t0[0], t1[1] - t0[1]) / (period / 1000)
                    speed = math.hypot(r1["vx"], r1["vy"])
                    if speed < 0.3:
                        continue
                    dv = math.hypot(p[0] - pout[i][0], p[1] - pout[i][1]) / (period / 1000)
                    # The display's error against the authority's own motion.
                    e = math.hypot((p[0] - pout[i][0]) - (t1[0] - t0[0]), (p[1] - pout[i][1]) - (t1[1] - t0[1])) / (period / 1000)
                    res[name]["err"].append(e)
                    res[name]["frames"] += 1
                    if dv < 0.5 * tv or dv > 1.5 * tv + 0.05:
                        res[name]["stutter"] += 1
                    if name == "sync":
                        moving_frames += 1
                        if now >= r1["next_ms"]:
                            held += 1
                    res[name]["delay"].append(wall - now)
            prev[name] = (now, out)
        wall += period
    report = {"rec": a.rec, "fps": a.fps, "offset_ms": a.offset_ms, "latency_ms": a.latency_ms, "jitter_ms": a.jitter_ms,
              "authority_held_share_of_moving_frames": round(held / max(1, moving_frames), 4)}
    for name, r in res.items():
        e = sorted(r["err"])
        report[name] = {
            "moving_body_frames": r["frames"],
            "speed_error_tiles_per_s": {"p50": q(e, 0.5), "p95": q(e, 0.95), "p99": q(e, 0.99), "max": q(e, 1.0)},
            "stutter_share": round(r["stutter"] / max(1, r["frames"]), 4),
        }
    for name in views:
        d = sorted(res[name]["delay"])
        report[name]["display_behind_authority_ms"] = {"p50": q(d, 0.5), "p95": q(d, 0.95)}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
