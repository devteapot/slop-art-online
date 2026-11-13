#!/usr/bin/env python3
"""The navigation arenas' driver (docs/MOVEMENT_MIND.md §4, built as §4.1 says).

  living/tools/nav_arena.py ARENA --run core-nav-… [--variant V …] [--law off|on …]
                            [--subject body|click …] [--reps 5] [--out DIR]

ARENA is n1 (unfamiliar town), n2 (blocked route), n3 (moving crowd) or n4 (chase and flight).
The run is a published verify-core run on the island seed (`verify.py launch --run core-nav-…
--seed island`), on a scratch server: LIVING_STDB_URL / LIVING_STDB_CONTAINER as verify.py.
Never a paused reference world, never the trial server while the merge gate runs.

Each phase (arena, variant, law, subject kind) uses fresh subjects: spawned adults (`body`, a
walk ordered with `mind_act`) or player identities that join and click (`click`, `human_act`).
Fixtures are characters acting through the ordinary skills (a gate-keeper closes a gate, walkers
walk, a chaser chases). Nothing is installed in a subject and the subject is told nothing.

Writes, per phase, `<out>/<arena>-<variant>-<law>-<subject>/`:
  walks.jsonl     one line per walk: who, start, goal, the order's authority time, arrival or
                  timeout, the goto outcome told, prior known cells in the arena box, the true
                  optimal from `nav_optimal`, the belief snapshot file
  belief-*.json   the subject's known_ground, remembered gates and the world's ground edits at
                  the order (what `nav_optimal` reads for the known-map optimal)
  bodies.jsonl    every body row update of the arena's characters (a subscription)
  stimuli.jsonl   what the driver did and when (authority time), with the clock's spread
  bench.json      `bench.py` over the phase: tick spans (`tick.motion`), body writes
  phase.json      the setup: sites, laws, cast, guards (known_ground rows and bytes)
`living/tools/nav_report.py` computes the measures from these folders.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/verify-core/scripts"))
sys.path.insert(0, str(ROOT / "living/tools"))
import scenes  # noqa: E402
import walk_times  # noqa: E402

STDB = str(ROOT / "living/tools/stdb")
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "living/target")))
BLOCKS = (2, 4, 7, 8, 9)  # water, rock, wall, drop, low: not walked
OPAQUE = (4, 7)  # rock and wall stop sight
ARRIVE_M = 2.5


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class World:
    """The arena's world: tiles, sites, the clock, calls and rows."""

    def __init__(self, run):
        self.s = scenes.Scene(run, "nav")
        self.run = run
        w = self.s.rows("SELECT width, height FROM world")[0]
        self.W, self.H = w["width"], w["height"]
        self.tiles = bytearray(self.W * self.H)
        for row in self.s.rows("SELECT * FROM terrain_chunk"):
            data = row["tiles"]
            data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
            cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
            for k, t in enumerate(data):
                x, y = cx * 16 + k % 16, cy * 16 + k // 16
                if x < self.W and y < self.H:
                    self.tiles[y * self.W + x] = t
        self.tiles_file = self.s.out / "nav-tiles.bin"
        self.tiles_file.write_bytes(bytes(self.tiles))
        self.owner = walk_times.owner_token()

    # ---- ground ----
    def tile(self, x, y):
        x, y = int(math.floor(x)), int(math.floor(y))
        if not (0 <= x < self.W and 0 <= y < self.H):
            return 4
        return self.tiles[y * self.W + x]

    def walk(self, x, y, shut=()):
        return self.tile(x, y) not in BLOCKS and (int(x), int(y)) not in shut

    def nearest_walkable(self, p, shut=(), within=12):
        cx, cy = int(math.floor(p[0])), int(math.floor(p[1]))
        for r in range(within + 1):
            best = None
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    q = (cx + dx + 0.5, cy + dy + 0.5)
                    # Room on every side, so a body's centre can stand there.
                    if all(self.walk(q[0] + i, q[1] + j, shut) for i in (-1, 0, 1) for j in (-1, 0, 1)):
                        d = math.dist(q, p)
                        if best is None or d < best[0]:
                            best = (d, q)
            if best:
                return best[1]
        return None

    def line_clear(self, a, b):
        n = int(math.dist(a, b) * 2) + 1
        return all(self.tile(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) not in OPAQUE for k in range(n + 1))

    # ---- calls and rows ----
    def now(self):
        return self.s.http_rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def call(self, *a, check=True):
        return self.s.call(*a, check=check)

    def rows(self, q):
        return self.s.http_rows(q)

    def law(self, name, value):
        scenes.set_law(self.s, name, value)

    def law_value(self, name):
        return scenes.law_value(self.s, name)

    def meta(self):
        """What the report needs of the world in every phase.json."""
        return {"tiles_file": str(self.tiles_file), "W": self.W, "H": self.H,
                "laws": {k: self.law_value(k) for k in ("nav_belief", "ground_sight_m", "unknown_cost", "road_speed", "known_cells_pass")}}

    def bodies(self, ids):
        if not ids:
            return {}
        q = " OR ".join(f"id = {i}" for i in ids)
        return {b["id"]: b for b in self.rows(f"SELECT * FROM body WHERE {q}")}

    def pos(self, b, at=None):
        return walk_times.pose(b, at if at is not None else time.time() * 1000)

    def people(self, n):
        before = {c["id"] for c in self.rows("SELECT id FROM character")}
        for k in range(0, n, 50):
            self.call("spawn_crowd", min(50, n - k), True)
        made = sorted(c["id"] for c in self.rows("SELECT id FROM character") if c["id"] not in before)
        for a in made:
            self.call("set_behavior", a, json.dumps({"wait": 3600}))
        return made

    def known_rows(self, actor):
        return self.rows(f"SELECT * FROM known_ground WHERE actor = {actor}")

    def snapshot(self, actor, path):
        """What `nav_optimal` needs of a walker's belief, as it is now."""

        def ints(v):
            if isinstance(v, str):
                return list(bytes.fromhex(v.removeprefix("0x")))
            return list(v)

        known = [{"block": r["block"], "cells": ints(r["cells"]), "seen_at": ints(r["seen_at"])} for r in self.known_rows(actor)]
        gates = {g["id"]: g for g in self.rows("SELECT * FROM gate")}
        seen = [[gates[r["target"]]["x"], gates[r["target"]]["y"], r["state"] == 1] for r in self.rows(f"SELECT * FROM remembered WHERE observer = {actor}") if r["target"] in gates]
        edits = [{"chunk": e["chunk"], "epoch": e["id"], "tile": e["tile"], "before": e["before"]} for e in self.rows("SELECT * FROM ground_edit")]
        snap = {"known": known, "gates_seen": seen, "edits": edits}
        Path(path).write_text(json.dumps(snap))
        return snap

    def shut_tiles(self):
        return [[g["x"], g["y"]] for g in self.rows("SELECT * FROM gate") if not g["open"]]

    def cells_in_box(self, actor, box):
        """Known 4 m cells of `actor` inside box (x0, y0, x1, y1)."""
        n = 0
        for r in self.known_rows(actor):
            cells = r["cells"]
            cells = list(bytes.fromhex(cells.removeprefix("0x"))) if isinstance(cells, str) else list(cells)
            block = r["block"]
            bx, by = block & 0xFFFF, block >> 16
            for slot in range(64):
                mask = cells[2 * slot] | (cells[2 * slot + 1] << 8) if 2 * slot + 1 < len(cells) else 0
                if not mask:
                    continue
                cx, cy = bx * 8 + slot % 8, by * 8 + slot // 8
                for bit in range(16):
                    if mask >> bit & 1:
                        x, y = cx * 16 + (bit % 4) * 4 + 2, cy * 16 + (bit // 4) * 4 + 2
                        if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                            n += 1
        return n

    def optimal(self, walks, shut):
        """True-map optimal per walk (`nav_optimal`, no belief): time and length in metres."""
        q = [{"start": w["start"], "goal": w["goal"], "shut": shut, "known": [], "edits": [], "gates_seen": [], "road_speed": self.road, "unknown_cost": self.unknown} for w in walks]
        f = self.s.out / f"nav-opt-{time.time_ns()}.json"
        f.write_text(json.dumps(q))
        out = subprocess.run([str(TARGET / "release/examples/nav_optimal"), str(self.tiles_file), str(self.W), str(self.H), str(f)], capture_output=True, text=True, timeout=600)
        if out.returncode:
            raise RuntimeError(f"nav_optimal: {out.stderr[-400:]}")
        return [json.loads(l) for l in out.stdout.splitlines() if l.startswith("{")]


class Phase:
    """One phase's recording: a body subscription, the stimulus log, bench alongside."""

    def __init__(self, world, folder, ids, seconds, bench=True):
        self.w, self.dir = world, Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stim = (self.dir / "stimuli.jsonl").open("a")
        q = "SELECT * FROM body WHERE " + " OR ".join(f"id = {i}" for i in ids) if len(ids) <= 60 else "SELECT * FROM body"
        self.sub = subprocess.Popen([STDB, "subscribe", "-s", "local", world.s.db, q, "-t", str(int(seconds))], stdout=(self.dir / "bodies.jsonl").open("w"), stderr=subprocess.DEVNULL)
        self.bench = None
        if bench:
            # A fixed window from the phase's start (its busiest walking), left to finish.
            self.bench = subprocess.Popen([sys.executable, str(ROOT / "living/tools/bench.py"), "--db", world.s.db, "--seconds", "90", "--body-writes"],
                                          stdout=(self.dir / "bench.txt").open("w"), stderr=subprocess.STDOUT, env={**os.environ, "LIVING_STDB": STDB})
        time.sleep(1.5)

    def mark(self, what, **kw):
        t0 = self.w.now()
        rec = {"what": what, "wall_ms": int(time.time() * 1000), "clock_ms": t0, **kw}
        self.stim.write(json.dumps(rec) + "\n")
        self.stim.flush()

    def close(self):
        self.stim.close()
        if self.bench:
            try:
                self.bench.wait(240)
            except subprocess.TimeoutExpired:
                pass
        for p in (self.sub, self.bench):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()


class Subject:
    """A walker: a spawned adult ordered with `mind_act` (body), or a player who clicks."""

    def __init__(self, world, kind, name, id=None):
        self.w, self.kind = world, kind
        if kind == "click":
            self.p = walk_times.Walker(world.s.db, world.owner, name)
            self.id = self.p.id
        else:
            self.id = id

    def go(self, at, run=False):
        node = {"do": "goto", "target": {"at": [round(at[0], 2), round(at[1], 2)]}}
        if run:
            node["run"] = True
        if self.kind == "click":
            code, body = walk_times.http(f"/v1/database/{self.w.s.db}/call/human_act", [json.dumps(node)], self.p.token)
            if code != 200:
                raise RuntimeError(f"human_act {code}: {body[:200]}")
        else:
            self.w.call("mind_act", self.id, [json.dumps(node)], "nav-arena")

    def keepalive(self):
        if self.kind == "click":
            self.p.keepalive()


def subjects(world, kind, n, tag):
    if kind == "click":
        return [Subject(world, "click", f"Nav{tag}{k}") for k in range(n)]
    return [Subject(world, "body", None, i) for i in world.people(n)]


def spread(world, centre, n, across, step=6.0, shut=()):
    """`n` starts `step` apart along the direction `across` (a unit vector) through `centre`."""
    out = []
    for k in range(n):
        off = (k - (n - 1) / 2) * step
        p = world.nearest_walkable((centre[0] + across[0] * off, centre[1] + across[1] * off), shut)
        out.append(p or centre)
    return out


def walks_to(world, phase, subs, legs, law, timeout_x=3.0, extra_s=20.0, run=False, box=None, record=None, on_order=None):
    """Walk every subject through its `legs` (a list per subject of lists of points: one walk's
    waypoints, the last its goal), all at once, each walk ordered when the last ended. Returns
    the walk records."""
    out = []
    state = []
    shut = world.shut_tiles()
    for sub, walks in zip(subs, legs):
        state.append({"sub": sub, "walks": walks, "k": -1, "wp": 0, "rec": None})

    def order(st):
        st["k"] += 1
        st["wp"] = 0
        if st["k"] >= len(st["walks"]):
            st["rec"] = None
            return
        sub = st["sub"]
        b = world.bodies([sub.id])[sub.id]
        here = world.pos(b)
        pts = st["walks"][st["k"]]
        goal = pts[-1]
        opt = world.optimal([{"start": list(here), "goal": list(goal)}], shut)[0]
        snapf = phase.dir / f"belief-{sub.id}-{st['k']}.json"
        world.snapshot(sub.id, snapf)
        t0 = world.now()
        sub.go(pts[0], run)
        t1 = world.now()
        true_s = (opt["true"]["time_m"] / 1.3) if opt.get("true") else None
        st["rec"] = {"subject": sub.id, "kind": sub.kind, "law": law, "walk": st["k"], "start": [round(here[0], 2), round(here[1], 2)], "goal": [round(goal[0], 2), round(goal[1], 2)],
                     "waypoints": [[round(p[0], 2), round(p[1], 2)] for p in pts[:-1]], "order_ms": [t0, t1], "true": opt.get("true"), "belief_file": snapf.name,
                     "prior_cells_in_box": world.cells_in_box(sub.id, box) if box else None, "deadline_s": (timeout_x * true_s + extra_s) if true_s else 240.0}
        phase.mark("order", subject=sub.id, walk=st["k"], to=pts[0], goal=goal, kind=sub.kind)
        if on_order:
            on_order(st)

    for st in state:
        order(st)
    while any(st["rec"] for st in state):
        time.sleep(0.4)
        live = [st for st in state if st["rec"]]
        bodies = world.bodies([st["sub"].id for st in live])
        t = time.time() * 1000
        for st in live:
            sub, rec = st["sub"], st["rec"]
            sub.keepalive()
            b = bodies.get(sub.id)
            if not b:
                rec.update(outcome="no body", end_ms=world.now())
                out.append(rec)
                order(st)
                continue
            here = world.pos(b, t)
            pts = st["walks"][st["k"]]
            target = pts[st["wp"]]
            # A walk told as failed ends there (the body stands; that is not being stuck).
            failed = None
            if int(t / 400) % 5 == 0:
                for e in world.rows(f"SELECT id, at_ms, kind, text FROM experience WHERE observer = {sub.id}"):
                    if e["kind"] == "act" and e["at_ms"] >= rec["order_ms"][0] and "did not work out" in e["text"] and "goto" in e["text"]:
                        failed = e["text"]
            if failed and math.dist(here, pts[-1]) > ARRIVE_M:
                rec.update(outcome="failed", end_ms=world.now(), end=[round(here[0], 2), round(here[1], 2)], left_m=round(math.dist(here, pts[-1]), 2))
            elif math.dist(here, target) <= ARRIVE_M:
                if st["wp"] + 1 < len(pts):
                    st["wp"] += 1
                    sub.go(pts[st["wp"]], run)
                    phase.mark("waypoint", subject=sub.id, walk=st["k"], to=pts[st["wp"]])
                    continue
                rec.update(outcome="arrived", end_ms=world.now(), end=[round(here[0], 2), round(here[1], 2)])
            elif (world.now() - rec["order_ms"][1]) / 1000 > rec["deadline_s"]:
                rec.update(outcome="timeout", end_ms=world.now(), end=[round(here[0], 2), round(here[1], 2)], left_m=round(math.dist(here, pts[-1]), 2))
            else:
                continue
            told = world.rows(f"SELECT id, at_ms, kind, text FROM experience WHERE observer = {sub.id}")
            rec["told"] = [e["text"] for e in sorted(told, key=lambda e: e["id"]) if e["at_ms"] >= rec["order_ms"][0] and e["kind"] == "act"][-3:]
            if record:
                record(rec)
            out.append(rec)
            order(st)
    with (phase.dir / "walks.jsonl").open("a") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    return out


# ---- sites ----

def town(world, community):
    st = next(s for s in world.rows("SELECT * FROM settlement") if s["community"] == community)
    return (st["x"], st["y"]), st["radius_m"]


def gate_groups(world, community):
    tiles = [(g["x"], g["y"], g["id"]) for g in world.rows("SELECT * FROM gate") if g["community"] == community]
    left = {(x, y): i for x, y, i in tiles}
    groups = []
    while left:
        (x, y), i = left.popitem()
        grp, todo = [(x, y, i)], [(x, y)]
        while todo:
            a, b = todo.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (a + dx, b + dy)
                    if q in left:
                        grp.append((q[0], q[1], left.pop(q)))
                        todo.append(q)
        cx = sum(g[0] for g in grp) / len(grp) + 0.5
        cy = sum(g[1] for g in grp) / len(grp) + 0.5
        groups.append({"centre": (cx, cy), "tiles": [(g[0], g[1]) for g in grp], "ids": [g[2] for g in grp]})
    return groups


def outside(world, centre, gate, metres):
    d = math.dist(gate, centre) or 1.0
    u = ((gate[0] - centre[0]) / d, (gate[1] - centre[1]) / d)
    return world.nearest_walkable((gate[0] + u[0] * metres, gate[1] + u[1] * metres)), u


def structure_near(world, kind, centre, radius):
    rows = [s for s in world.rows(f"SELECT * FROM structure WHERE kind = '{kind}'") if math.dist((s["x"], s["y"]), centre) <= radius]
    rows.sort(key=lambda s: math.dist((s["x"], s["y"]), centre))
    return rows


def through(world, start, goal, shut, parts=3):
    """Waypoints along the true optimal path from start to goal, at 1/parts, 2/parts …"""
    q = [{"start": list(start), "goal": list(goal), "shut": shut, "known": [], "edits": [], "gates_seen": [], "road_speed": world.road, "unknown_cost": world.unknown, "path": True}]
    f = world.s.out / f"nav-path-{time.time_ns()}.json"
    f.write_text(json.dumps(q))
    out = subprocess.run([str(TARGET / "release/examples/nav_optimal"), str(world.tiles_file), str(world.W), str(world.H), str(f)], capture_output=True, text=True, timeout=600)
    r = json.loads(next(l for l in out.stdout.splitlines() if l.startswith("{")))
    path = (r.get("true") or {}).get("path") or []
    if len(path) < parts + 1:
        return []
    return [world.nearest_walkable((path[len(path) * k // parts][0] + 0.5, path[len(path) * k // parts][1] + 0.5)) for k in range(1, parts)]


# ---- arenas ----

def n1(world, out, variant, law, kind, reps):
    """N1 unfamiliar town: from outside the south gate, three places in turn."""
    if variant == "c":
        centre, radius = town(world, 7)  # Kettlebridge, on its terraces
        start, _ = outside(world, centre, (centre[0] - radius * 0.7, centre[1] + radius * 0.7), radius * 0.45)
        inn = structure_near(world, "inn", centre, radius) or structure_near(world, "hall", centre, radius)
        far = structure_near(world, "house", centre, radius)
        goals = [(inn[0]["x"], inn[0]["y"]), centre, (far[-1]["x"], far[-1]["y"])]
        box = (centre[0] - radius - 40, centre[1] - radius - 40, centre[0] + radius + 40, centre[1] + radius + 40)
    else:
        centre, radius = town(world, 1)  # Brackenford
        groups = gate_groups(world, 1)
        south = max(groups, key=lambda g: g["centre"][1])
        north = min(groups, key=lambda g: g["centre"][1])
        start, _ = outside(world, centre, south["centre"], 10)
        inn = structure_near(world, "inn", centre, radius)
        goals = [(inn[0]["x"], inn[0]["y"]), centre, north["centre"]]
        box = (centre[0] - radius - 40, centre[1] - radius - 40, centre[0] + radius + 40, centre[1] + radius + 40)
    goals = [world.nearest_walkable(g) for g in goals]
    told = list(goals)
    if variant == "d":
        rng = random.Random(6)
        for _ in range(64):
            a = rng.uniform(0, 2 * math.pi)
            p = world.nearest_walkable((goals[1][0] + 6 * math.cos(a), goals[1][1] + 6 * math.sin(a)), within=1)
            if p and 5.0 <= math.dist(p, goals[1]) <= 7.0:
                told[1] = p
                break
    world.law("nav_belief", law == "on")
    subs = subjects(world, kind, reps, f"n1{variant}{law}")
    d = math.dist(start, centre) or 1.0
    across = (-(centre[1] - start[1]) / d, (centre[0] - start[0]) / d)
    starts = spread(world, start, reps, across)
    for sub, p in zip(subs, starts):
        world.call("place_at", sub.id, p[0], p[1])
    time.sleep(3.0)
    folder = Path(out) / f"n1-{variant}-{law}-{kind}"
    phase = Phase(world, folder, [s.id for s in subs], 1500)
    shut = world.shut_tiles()
    legs = []
    for p in starts:
        walks, here = [], p
        for g in told:
            wps = through(world, here, g, shut) if variant == "b" else []
            walks.append([*wps, g])
            here = g
        legs.append(walks)
    (folder / "phase.json").write_text(json.dumps({"arena": "n1", "variant": variant, "law": law, "kind": kind, "start": start, "starts": starts, "goals": goals, "told": told, "box": box,
                                                   "subjects": [s.id for s in subs], **world.meta()}, indent=1))
    recs = walks_to(world, phase, subs, legs, law, box=box)
    phase.close()
    guards(world, folder, [s.id for s in subs])
    return recs


def keeper_act(world, keeper, gid, tile, skill):
    p = world.nearest_walkable((tile[0] + 0.5, tile[1] + 0.5))
    world.call("place_at", keeper, p[0], p[1])
    time.sleep(0.6)
    world.call("mind_act", keeper, [json.dumps({"do": skill, "target": {"id": gid}})], "nav-arena")


def set_gate(world, keeper, group, open_):
    for gid, tile in zip(group["ids"], group["tiles"]):
        g = next(iter(world.rows(f"SELECT * FROM gate WHERE id = {gid}")), None)
        if g and g["open"] != open_:
            keeper_act(world, keeper, gid, tile, "open" if open_ else "close")
            end = time.monotonic() + 12
            while time.monotonic() < end and next(iter(world.rows(f"SELECT open FROM gate WHERE id = {gid}")))["open"] != open_:
                time.sleep(0.3)
    return all(g["open"] == open_ for g in world.rows("SELECT * FROM gate") if g["id"] in group["ids"])


def n2(world, out, variant, law, kind, reps):
    """N2 blocked route: a route walked once, its gate shut out of sight, the walk again."""
    centre, radius = town(world, 1)
    groups = gate_groups(world, 1)
    a = max(groups, key=lambda g: g["centre"][1])
    b = min((g for g in groups if g is not a), key=lambda g: math.dist(g["centre"], a["centre"]))
    start, u = outside(world, centre, a["centre"], 10)
    goal = world.nearest_walkable(centre)
    b_out, _ = outside(world, centre, b["centre"], 10)
    far = world.nearest_walkable((a["centre"][0] + u[0] * 75, a["centre"][1] + u[1] * 75), within=20)
    keeper = next(m["member"] for m in world.rows("SELECT * FROM membership WHERE community = 1") if world.bodies([m["member"]]))
    world.call("set_behavior", keeper, json.dumps({"wait": 3600}))
    set_gate(world, keeper, a, True)
    world.law("nav_belief", law == "on")
    subs = subjects(world, kind, reps, f"n2{variant}{law}")
    across = (-u[1], u[0])
    starts = spread(world, start, reps, across)
    for sub, p in zip(subs, starts):
        world.call("place_at", sub.id, p[0], p[1])
    time.sleep(3.0)
    folder = Path(out) / f"n2-{variant}-{law}-{kind}"
    phase = Phase(world, folder, [s.id for s in subs] + [keeper], 1800)
    box = (centre[0] - radius - 80, centre[1] - radius - 80, centre[0] + radius + 80, centre[1] + radius + 80)
    # Warm-up: start → goal → start (through gate A); with the alternative known, also out by B.
    warm = [[[goal], [p]] + ([[b_out], [goal], [p]] if variant == "a" else []) for p in starts]
    phase.mark("warmup")
    walks_to(world, phase, subs, warm, law, box=box)
    # Out of sight of gate A: 75 m out along its road.
    fars = spread(world, far, reps, across)
    for sub, p in zip(subs, fars):
        world.call("place_at", sub.id, p[0], p[1])
    time.sleep(2.0)
    ok = set_gate(world, keeper, a, False)
    phase.mark("gate shut", gate=a["ids"], tiles=a["tiles"], all_shut=ok)
    world.call("place_at", keeper, goal[0], goal[1])
    remembered_open = {}
    for sub in subs:
        r = world.rows(f"SELECT * FROM remembered WHERE observer = {sub.id}")
        remembered_open[sub.id] = sorted(x["state"] for x in r if x["target"] in a["ids"])

    def reopen(st):
        if variant == "c" and st["k"] == 0 and not getattr(reopen, "done", False):
            reopen.done = True
            threading.Thread(target=lambda: (time.sleep(4.0), phase.mark("gate reopened", ok=set_gate(world, keeper, a, True), gate=a["ids"]))).start()

    (folder / "phase.json").write_text(json.dumps({"arena": "n2", "variant": variant, "law": law, "kind": kind, "gate_a": a, "gate_b": b, "start": start, "far": far, "goal": goal,
                                                   "keeper": keeper, "subjects": [s.id for s in subs], "remembered_a_states_at_order": remembered_open, "box": box,
                                                   **world.meta()}, indent=1, default=list))
    phase.mark("test walks")
    recs = walks_to(world, phase, subs, [[[goal]] for _ in subs], law, box=box, on_order=reopen)
    phase.close()
    set_gate(world, keeper, a, True)
    guards(world, folder, [s.id for s in subs])
    return recs


def guards(world, folder, ids):
    rows = world.rows("SELECT * FROM known_ground")
    mine = [r for r in rows if r["actor"] in ids]

    def size(r):
        c = r["cells"]
        return (len(c) - 2) // 2 if isinstance(c, str) else len(c)

    g = {"known_ground_rows": len(rows), "known_ground_rows_subjects": len(mine), "subject_cells_bytes": sum(size(r) for r in mine) * 3,
         "ground_edits": len(world.rows("SELECT id FROM ground_edit"))}
    (Path(folder) / "guards.json").write_text(json.dumps(g, indent=1))


def open_square(world, centre, size, within):
    """The centre of a size × size square of walkable tiles nearest `centre` (within `within`)."""
    best = None
    half = size // 2
    for r in range(0, int(within), 2):
        for k in range(max(1, int(2 * math.pi * r / 2))):
            a = 2 * math.pi * k / max(1, int(2 * math.pi * r / 2))
            c = (int(centre[0] + r * math.cos(a)), int(centre[1] + r * math.sin(a)))
            if all(world.walk(c[0] + i + 0.5, c[1] + j + 0.5) for i in range(-half, half + 1) for j in range(-half, half + 1)):
                return (c[0] + 0.5, c[1] + 0.5)
    return best


def goto_node(at, run=False):
    return {"do": {"skill": "goto", "target": {"at": [round(at[0], 2), round(at[1], 2)]}, "run": run}}


def n3(world, out, variant, law, kind, reps):
    """N3 moving crowd: the subject crosses a square through two opposing streams at a run."""
    n = 200 if variant == "w200" else 50
    centre, radius = town(world, 1)
    sq = open_square(world, centre, 32, radius) or open_square(world, centre, 32, 600)
    half = 15
    if not hasattr(world, "crowd"):
        world.crowd = []
    if len(world.crowd) < n:
        world.crowd += world.people(n - len(world.crowd))
    walkers = world.crowd[:n]
    lanes = {0: sq[1] - 4.0, 1: sq[1] + 4.0}
    rng = random.Random(3)
    for k, wid in enumerate(walkers):
        lane = k % 2
        y = lanes[lane] + rng.uniform(-2.5, 2.5)
        x = sq[0] + rng.uniform(-half, half)
        world.call("place_at", wid, x, y)
        a, b = (sq[0] - half, y), (sq[0] + half, y)
        if lane == 1:
            a, b = b, a
        if variant == "stop" and lane == 1:
            node = {"seq": [goto_node((sq[0] + rng.uniform(-6, 6), y), True), {"wait": 3600}]}
        else:
            node = {"seq": [goto_node(b, True), goto_node(a, True)] * 30}
        world.call("set_behavior", wid, json.dumps(node))
    # Idle walkers past n stay out of the square.
    for wid in world.crowd[n:]:
        world.call("set_behavior", wid, json.dumps({"wait": 3600}))
        world.call("place_at", wid, sq[0] + 60, sq[1] + 60)
    world.law("nav_belief", law == "on")
    subs = subjects(world, kind, reps, f"n3{variant}{law}")
    starts = spread(world, (sq[0], sq[1] - half - 3), reps, (1.0, 0.0))
    goals = [world.nearest_walkable((p[0], sq[1] + half + 3)) for p in starts]
    for sub, p in zip(subs, starts):
        world.call("place_at", sub.id, p[0], p[1])
    time.sleep(6.0)
    folder = Path(out) / f"n3-{variant}-{law}-{kind}"
    phase = Phase(world, folder, [s.id for s in subs] + walkers, 900)
    (folder / "phase.json").write_text(json.dumps({"arena": "n3", "variant": variant, "law": law, "kind": kind, "square": sq, "half": half, "walkers": walkers, "lanes": lanes,
                                                   "subjects": [s.id for s in subs], "starts": starts, "goals": goals, **world.meta()}, indent=1))
    recs = []
    # Three crossings each: there, back, there.
    legs = [[[g], [p], [g]] for p, g in zip(starts, goals)]
    recs = walks_to(world, phase, subs, legs, law, run=(variant == "run"))
    phase.close()
    for wid in walkers:
        world.call("set_behavior", wid, json.dumps({"wait": 3600}))
    guards(world, folder, [s.id for s in subs])
    return recs


def edge_spot(world, centre, radius, avoid):
    """Outside the town wall, away from gates: a point 8 m out from the wall with open field
    beyond; returns (spot, outward unit, wall point)."""
    for k in range(64):
        a = 2 * math.pi * k / 64
        u = (math.cos(a), math.sin(a))
        wall = None
        for r in range(int(radius * 0.4), int(radius * 1.4)):
            p = (centre[0] + u[0] * r, centre[1] + u[1] * r)
            if world.tile(*p) == 7:
                wall = p
            elif wall and world.walk(*p):
                break
        if not wall or any(math.dist(wall, g) < 40 for g in avoid):
            continue
        spot = (wall[0] + u[0] * 8, wall[1] + u[1] * 8)
        if all(world.walk(spot[0] + u[0] * d + u[1] * t, spot[1] + u[1] * d - u[0] * t) for d in range(-5, 30) for t in (-14, -7, 0, 7, 14)):
            return spot, u, wall
    return None


def n4(world, out, variant, law, kind, reps):
    """N4 chase and flight at a town edge: `fu`/`fk` flight from a chaser (ground unknown or
    known), `pu`/`pk` the subject pursuing a fixture round a corner. Night is when the world's
    clock says (the hour is recorded); no clock is changed."""
    centre, radius = town(world, 1)
    gates = [g["centre"] for g in gate_groups(world, 1)]
    found = edge_spot(world, centre, radius, gates)
    if not found:
        raise RuntimeError("no town edge with open field away from gates")
    spot, u, wall = found
    tang = (-u[1], u[0])
    world.law("nav_belief", law == "on")
    subs = subjects(world, kind, reps, f"n4{variant}{law}")
    fixtures = world.people(reps)
    hour = scenes.world_hour(world.s)[0]
    folder = Path(out) / f"n4-{variant}-{law}-{kind}"
    starts = []
    for k, (sub, fx) in enumerate(zip(subs, fixtures)):
        # Each pair along the wall, 40 m apart, so pairs do not meet.
        base = (spot[0] + tang[0] * (k - (reps - 1) / 2) * 40, spot[1] + tang[1] * (k - (reps - 1) / 2) * 40)
        p = world.nearest_walkable(base)
        starts.append(p)
        world.call("place_at", sub.id, p[0], p[1])
    if variant in ("fk", "pk"):
        # Warm-up: a walk out into the field and back, so the ground around is known.
        warm = [[[world.nearest_walkable((p[0] + u[0] * 25, p[1] + u[1] * 25))], [world.nearest_walkable((p[0] + tang[0] * 18, p[1] + tang[1] * 18))], [p]] for p in starts]
        tmp = Phase(world, folder / "warmup", [s.id for s in subs], 600, bench=False)
        walks_to(world, tmp, subs, warm, law)
        tmp.close()
    phase = Phase(world, folder, [s.id for s in subs] + fixtures, 600)
    meta = {"arena": "n4", "variant": variant, "law": law, "kind": kind, "spot": spot, "outward": u, "wall": wall, "hour": round(hour, 2), "subjects": [s.id for s in subs],
            "fixtures": fixtures, "starts": starts, "flee_clear": world.law_value("flee_clear"), **world.meta()}
    recs = []
    for sub, fx, p in zip(subs, fixtures, starts):
        if variant in ("fu", "fk"):
            c = world.nearest_walkable((p[0] + tang[0] * 12, p[1] + tang[1] * 12))
            world.call("place_at", fx, c[0], c[1])
        else:
            c = world.nearest_walkable((p[0] + tang[0] * 8, p[1] + tang[1] * 8))
            world.call("place_at", fx, c[0], c[1])
    time.sleep(2.0)
    t0 = world.now()
    for sub, fx, p in zip(subs, fixtures, starts):
        if variant in ("fu", "fk"):
            world.call("set_behavior", fx, json.dumps({"seq": [{"do": {"skill": "close_in", "target": {"id": sub.id}, "distance": 1, "run": True}}] * 20}))
            if sub.kind == "click":
                # A player flees by clicking away from the chaser, 30 m off, each second.
                pass
            else:
                world.call("set_behavior", sub.id, json.dumps({"seq": [{"do": {"skill": "flee", "target": {"id": fx}}}, {"wait": 600}]}))
        else:
            # The fixture walks round the town wall's corner away from the subject (out of its
            # sight past the wall), then on; the subject pursues it.
            route = [world.nearest_walkable((p[0] + tang[0] * d - u[0] * i, p[1] + tang[1] * d - u[1] * i)) for d, i in ((20, 0), (30, 10), (34, 30))]
            route = [q for q in route if q]
            world.call("set_behavior", fx, json.dumps({"seq": [goto_node(q, False) for q in route] + [{"wait": 600}]}))
            if sub.kind == "body":
                world.call("set_behavior", sub.id, json.dumps({"seq": [{"do": {"skill": "close_in", "target": {"id": fx}, "distance": 1.2, "run": True}}, {"wait": 600}]}))
    phase.mark("start", variant=variant)
    end = time.monotonic() + 60
    clicks = {s.id: 0 for s in subs if s.kind == "click"}
    while time.monotonic() < end:
        bodies = world.bodies([s.id for s in subs] + fixtures)
        for sub, fx in zip(subs, fixtures):
            sub.keepalive()
            if sub.kind == "click" and variant in ("fu", "fk") and time.monotonic() - clicks.get(sub.id, 0) > 1.0 and sub.id in bodies and fx in bodies:
                me, him = world.pos(bodies[sub.id]), world.pos(bodies[fx])
                d = math.dist(me, him) or 1.0
                away = world.nearest_walkable((me[0] + (me[0] - him[0]) / d * 30, me[1] + (me[1] - him[1]) / d * 30), within=6)
                if away:
                    sub.go(away, True)
                    clicks[sub.id] = time.monotonic()
                    phase.mark("click", subject=sub.id, to=away)
            elif sub.kind == "click" and variant in ("pu", "pk") and time.monotonic() - clicks.get(sub.id, 0) > 1.0 and sub.id in bodies and fx in bodies:
                # A player pursues by clicking where it sees the fixture, else where it last saw it
                # (a clear line within the day's 48 m or the night's 14 m sight).
                me, him = world.pos(bodies[sub.id]), world.pos(bodies[fx])
                sight = 48.0 if 6.0 <= scenes.world_hour(world.s)[0] < 20.0 else 14.0
                if math.dist(me, him) <= sight and world.line_clear(me, him):
                    sub.go(him, True)
                    phase.mark("click", subject=sub.id, to=him, seen=True)
                clicks[sub.id] = time.monotonic()
        time.sleep(0.25)
    for sub, fx in zip(subs, fixtures):
        told = world.rows(f"SELECT id, at_ms, kind, text FROM experience WHERE observer = {sub.id}")
        rec = {"subject": sub.id, "fixture": fx, "kind": sub.kind, "law": law, "walk": 0, "start_ms": t0, "end_ms": world.now(),
               "told": [e["text"] for e in sorted(told, key=lambda e: e["id"]) if e["at_ms"] >= t0 and e["kind"] == "act"][-6:]}
        recs.append(rec)
        world.call("set_behavior", fx, json.dumps({"wait": 3600}))
        if sub.kind == "body":
            world.call("set_behavior", sub.id, json.dumps({"wait": 3600}))
    with (folder / "walks.jsonl").open("a") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    (folder / "phase.json").write_text(json.dumps(meta, indent=1))
    phase.close()
    guards(world, folder, [s.id for s in subs])
    return recs


ARENAS = {"n1": (n1, ["a", "b", "c", "d"]), "n2": (n2, ["a", "b", "c"]), "n3": (n3, ["w50", "w200", "stop", "run"]), "n4": (n4, ["fu", "fk", "pu", "pk"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arena", choices=sorted(ARENAS))
    ap.add_argument("--run", required=True)
    ap.add_argument("--variant", action="append")
    ap.add_argument("--law", action="append", choices=["off", "on"])
    ap.add_argument("--subject", action="append", choices=["body", "click"])
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--out")
    a = ap.parse_args()
    fn, variants = ARENAS[a.arena]
    world = World(a.run)
    world.road = float(world.law_value("road_speed") or 1.4)
    world.unknown = float(world.law_value("unknown_cost") or 1.5)
    out = Path(a.out or ROOT / ".local/living/nav" / a.run)
    out.mkdir(parents=True, exist_ok=True)
    for v in a.variant or list(variants):
        for law in a.law or ["off", "on"]:
            for kind in a.subject or ["body", "click"]:
                log(f"{a.arena} {v} {law} {kind}")
                recs = fn(world, out, v, law, kind, a.reps)
                arrived = sum(r.get("outcome") == "arrived" for r in recs)
                log(f"  {arrived}/{len(recs)} arrived")
    world.law("nav_belief", False)


if __name__ == "__main__":
    main()
