#!/usr/bin/env python3
"""Timed click-to-move walks on a living world, through the player reducers (docs/PATHS.md).

usage: walk_times.py --db DB [--from NAME] [--to NAME,NAME…|all] [--clicks N] [--out FILE]
                     [--timeout S]
       walk_times.py --db DB --residents N [--secs S] [--out FILE]

Each walker is a fresh player identity (POST /v1/identity) that joins, clicks on the `--from`
settlement (`human_act` goto) and, once there, on its own target settlement: one walker per
target, all walking at once. `--clicks N` adds one walker making N short clicks 30–60 m away in
random directions (the soak's hops). Per walk it records the click, the outcome the character
experienced (its `act` experience row), the time to arrival and the walked length (positions
from the `body` row every 2 s). Each poll is also a call as the walker, which keeps its person
present (an HTTP call is a connection), so the world's minds do not take the character over.

The server: LIVING_STDB_URL (default http://127.0.0.1:3300) and LIVING_STDB_CONTAINER for the
owner's token (as .agents/skills/verify/scripts/verify.py). Standard library only.

`--residents N` instead sends N adult residents (no players) walking: each gets a graph of
`goto`s to three settlements at least 600 m from its home (admin `set_behavior`, which sets a
scene only), then every body is sampled every 10 s for `--secs`. It reports per resident the
distance walked and the settlements reached, and how many were moving at each sample: a walking
load for measuring the tick (`living/tools/bench.py` on the same database meanwhile).
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
import urllib.request

URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
CONTAINER = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")


def http(path, body=None, token=None, raw=False):
    data = None if body is None else (body.encode() if raw else json.dumps(body).encode())
    req = urllib.request.Request(URL + path, data=data, method="POST" if data is not None else "GET")
    req.add_header("Content-Type", "text/plain" if raw else "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def owner_token():
    out = subprocess.run(["docker", "exec", CONTAINER, "spacetime", "login", "show", "--token"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "auth token" in line and " is " in line:
            return line.rsplit(" is ", 1)[1].strip()
    sys.exit("could not read the owner token")


def sql(db, q, token):
    code, body = http(f"/v1/database/{db}/sql", q, token, raw=True)
    if code != 200:
        raise RuntimeError(f"sql {code}: {body[:200]}")
    res = json.loads(body)[-1]
    names = [c["name"]["some"] if isinstance(c["name"], dict) else c["name"] for c in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def pose(b, now_ms):
    """Position on a body's segment at `now_ms` (living_rules::steer::pose)."""
    dt = max(0.0, (min(now_ms, b["next_ms"]) - b["t_ms"]) / 1000.0)
    v = math.hypot(b["vx"], b["vy"])
    x, y, h, turn, ts = b["x"], b["y"], b["heading"], b["turn"], b["turn_s"]

    def arc(x, y, h, turn, dt):
        if dt <= 0 or v == 0:
            return x, y, h
        if abs(turn) < 1e-4:
            return x + v * math.cos(h) * dt, y + v * math.sin(h) * dt, h
        h1 = h + turn * dt
        r = v / turn
        return x + r * (math.sin(h1) - math.sin(h)), y - r * (math.cos(h1) - math.cos(h)), h1

    if turn == 0 or ts <= 0:
        return arc(x, y, h, 0, dt)[:2]
    if dt <= ts:
        return arc(x, y, h, turn, dt)[:2]
    x1, y1, h1 = arc(x, y, h, turn, ts)
    return arc(x1, y1, h1, 0, dt - ts)[:2]


class Walker:
    def __init__(self, db, owner, name):
        self.db, self.owner, self.name = db, owner, name
        code, body = http("/v1/identity", {})
        j = json.loads(body)
        self.token = j["token"]
        code, body = http(f"/v1/database/{db}/call/join", [name], self.token)
        if code != 200:
            raise RuntimeError(f"join {name}: {code} {body}")
        self.id = sql(db, "SELECT * FROM my_characters", self.token)[0]["id"]
        self.seen = set()

    def body(self):
        rows = sql(self.db, f"SELECT * FROM body WHERE id = {self.id}", self.owner)
        return rows[0] if rows else None

    def here(self):
        b = self.body()
        return pose(b, time.time() * 1000) if b else None

    def alive(self):
        return sql(self.db, f"SELECT alive FROM character WHERE id = {self.id}", self.owner)[0]["alive"]

    def outcomes(self):
        """New goto outcomes this character experienced, in order."""
        rows = sql(self.db, f"SELECT id, at_ms, text FROM experience WHERE observer = {self.id}", self.owner)
        new = [r for r in sorted(rows, key=lambda r: r["id"]) if r["id"] not in self.seen and "goto" in r["text"]]
        self.seen.update(r["id"] for r in rows)
        return new

    def click(self, at):
        node = json.dumps({"do": "goto", "target": {"at": [at[0], at[1]]}})
        code, body = http(f"/v1/database/{self.db}/call/human_act", [node], self.token)
        return code, body

    def keepalive(self):
        sql(self.db, "SELECT * FROM my_characters", self.token)

    def walk(self, at, timeout, label):
        """Click on `at` and wait for the outcome; returns a record."""
        self.outcomes()
        start = self.here()
        t0 = time.time()
        code, body = self.click(at)
        rec = {"walker": self.name, "id": self.id, "to": label, "click": [round(at[0], 1), round(at[1], 1)], "from": [round(start[0], 1), round(start[1], 1)], "straight_m": round(math.dist(start, at), 1), "call": code}
        if code != 200:
            rec.update(outcome=f"call refused: {body.strip()[:200]}")
            return rec
        track = [start]
        while time.time() - t0 < timeout:
            time.sleep(2)
            self.keepalive()
            p = self.here()
            if p:
                track.append(p)
            out = self.outcomes()
            if out:
                o = out[-1]
                rec["outcome"] = o["text"]
                rec["secs"] = round(o["at_ms"] / 1000 - t0, 1)
                break
            if not self.alive():
                rec["outcome"] = "died on the way"
                break
        else:
            rec["outcome"] = "timeout"
        # Settle, then the final position.
        time.sleep(2)
        end = self.here()
        if end:
            track.append(end)
        rec["walked_m"] = round(sum(math.dist(a, b) for a, b in zip(track, track[1:])), 1)
        rec["end"] = [round(end[0], 1), round(end[1], 1)] if end else None
        rec["left_m"] = round(math.dist(end, at), 1) if end else None
        rec["track"] = [[round(x, 1), round(y, 1)] for x, y in track]
        return rec


def residents(a, owner, places):
    rng = random.Random(a.seed)
    players = {r["id"] for r in sql(a.db, "SELECT id FROM presence", owner)}
    people = [r for r in sql(a.db, "SELECT id, kind, stage, alive, home_x, home_y FROM character", owner) if r["kind"] == "person" and r["stage"] == 2 and r["alive"] and r["id"] not in players]
    people.sort(key=lambda r: r["id"])
    rng.shuffle(people)
    chosen = []
    for r in people[: a.residents]:
        home = (r["home_x"], r["home_y"])
        far = sorted(n for n, p in places.items() if math.dist(p, home) >= 600)
        rng.shuffle(far)
        goals = far[:3]
        graph = {"seq": [{"do": {"skill": "goto", "target": {"at": [places[n][0], places[n][1]]}}} for n in goals]}
        code, body = http(f"/v1/database/{a.db}/call/set_behavior", [r["id"], json.dumps(graph)], owner)
        if code != 200:
            print(f"set_behavior {r['id']}: {code} {body}", file=sys.stderr)
            continue
        chosen.append({"id": r["id"], "home": home, "goals": goals, "reached": [], "walked_m": 0.0, "last": None})
    by_id = {c["id"]: c for c in chosen}
    print(f"{len(chosen)} residents walking", file=sys.stderr, flush=True)
    t0 = time.time()
    samples = []
    while time.time() - t0 < a.secs:
        now = time.time() * 1000
        moving = 0
        for b in sql(a.db, "SELECT * FROM body", owner):
            c = by_id.get(b["id"])
            if not c:
                continue
            p = pose(b, now)
            if c["last"]:
                c["walked_m"] += math.dist(c["last"], p)
            c["last"] = p
            moving += b["vx"] != 0 or b["vy"] != 0
            for n in c["goals"]:
                if n not in c["reached"] and math.dist(p, places[n]) < 30:
                    c["reached"].append(n)
        samples.append({"t": round(time.time() - t0), "moving": moving})
        print(json.dumps(samples[-1]), file=sys.stderr, flush=True)
        time.sleep(10)
    rows = [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in c.items() if k != "last"} for c in chosen]
    summary = {"residents": len(chosen), "secs": a.secs, "walked_m_total": round(sum(c["walked_m"] for c in chosen)), "reached": sum(len(c["reached"]) for c in chosen), "still": sum(1 for c in chosen if c["walked_m"] < 20), "samples": samples}
    out = open(a.out, "w") if a.out else sys.stdout
    json.dump({"summary": summary, "residents": rows}, out, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--from", dest="start", default="Brackenford")
    ap.add_argument("--to", default="all")
    ap.add_argument("--clicks", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--residents", type=int, default=0)
    ap.add_argument("--secs", type=float, default=600)
    ap.add_argument("--out")
    a = ap.parse_args()
    owner = owner_token()
    places = {r["name"]: (r["home_x"], r["home_y"]) for r in sql(a.db, "SELECT name, home_x, home_y FROM community", owner)}
    if a.residents:
        return residents(a, owner, places)
    targets = [n for n in places if n != a.start] if a.to == "all" else a.to.split(",")
    results, lock = [], threading.Lock()
    out = open(a.out, "a") if a.out else sys.stdout

    def emit(rec):
        with lock:
            results.append(rec)
            print(json.dumps(rec), file=out, flush=True)
            short = {k: v for k, v in rec.items() if k != "track"}
            print(json.dumps(short), file=sys.stderr, flush=True)

    def journey(i, target):
        w = Walker(a.db, owner, f"Walker{i:02d}")
        rec = w.walk(places[a.start], 600, a.start)
        rec["leg"] = "to the start"
        emit(rec)
        if "did what" not in rec.get("outcome", ""):
            return
        rec = w.walk(places[target], a.timeout, target)
        rec["leg"] = "journey"
        emit(rec)

    def clicker():
        rng = random.Random(a.seed)
        w = Walker(a.db, owner, "Clicker")
        for k in range(a.clicks):
            here = w.here()
            ang = rng.uniform(0, math.tau)
            r = rng.uniform(30, 60)
            at = (here[0] + r * math.cos(ang), here[1] + r * math.sin(ang))
            rec = w.walk(at, 120, f"click {k}")
            rec["leg"] = "short click"
            emit(rec)
            if not w.alive():
                break

    threads = [threading.Thread(target=journey, args=(i, t)) for i, t in enumerate(targets)]
    if a.clicks:
        threads.append(threading.Thread(target=clicker))
    for t in threads:
        t.start()
        time.sleep(0.5)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
