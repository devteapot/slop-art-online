#!/usr/bin/env python3
"""Town life scenes on a scratch island world (docs/TOWN_LIFE.md).

Residents live on their own instinct graphs (`rules.minds = false`); this driver only watches
the authority's rows at the world's hours and sets scenes with admin reducers:
`set_weather` (rain, and a dry sky for the rest of the run so natural rain does not mix in),
`place_at` (a wolf into town, the player beside a resident) and `kill` (the wolf afterwards).
The player acts through its own identity (`human_act`, `human_move`). The day is the world's
own 12 real minutes (no clock compression): the full run takes about 14 minutes.

    town.py --run RUN [--scene all|census|work|greet|approach|speak|aside|rain|wolf|evening|night|morning]

`census` records, once per world hour for a day, where adults are and what everyone does
(evidence only, on an undisturbed world with its own weather).

Needs `verify.py launch --run RUN --seed island`. Writes `RUN/town.json` and, per scene,
`RUN/town-<scene>.json` (positions, activities, doing rows, places and skill uses).
Python standard library only.
"""

import argparse
from collections import Counter
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

WALKABLE = {0, 1, 3, 5, 6}  # living_rules::map::Terrain: grass, forest, sand, dirt, road
WORK = {"keep", "gather", "cook", "read", "tend", "store", "take", "plant", "craft"}
SHELTER = {"house", "inn", "hall"}


class Town:
    def __init__(self, run):
        self.run = run
        self.st = V.load(run)
        self.db = self.st["db"]
        self.out = V.run_dir(run)
        self.token = V.admin_token()
        self.results = []
        self.world = self.sql("SELECT * FROM world")[0]

    # ---- authority access ----------------------------------------------------------------
    def sql(self, q, who="admin"):
        token = self.token if who == "admin" else self.st.get("token") if who == "player" else None
        code, body = V.http(f"/v1/database/{self.db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, reducer, args, who="admin"):
        token = self.token if who == "admin" else self.st["token"]
        code, body = V.http(f"/v1/database/{self.db}/call/{reducer}", args, token)
        V.log(self.st, f"call {reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}")
        return code, body

    def check(self, name, ok, detail):
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        V.log(self.st, f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    def save(self, label, data):
        (self.out / f"town-{label}.json").write_text(json.dumps(data, indent=1) + "\n")

    # ---- time ----------------------------------------------------------------------------
    def now_ms(self):
        return int(time.time() * 1000)

    def hour(self):
        w = self.world
        t = self.now_ms() - w["epoch_ms"] + w["day_ms"] * 7 // 24
        return (t % w["day_ms"]) / w["day_ms"] * 24

    def wait_hour(self, lo, hi):
        """Sleep until the world's hour is within [lo, hi) (wrapping past midnight)."""
        while True:
            h = self.hour()
            inside = lo <= h < hi if lo < hi else (h >= lo or h < hi)
            if inside:
                return h
            ahead = (lo - h) % 24
            time.sleep(max(1.0, min(20.0, ahead / 24 * self.world["day_ms"] / 1000 - 1)))

    # ---- the town now ----------------------------------------------------------------------
    def people(self):
        """Every living resident with where its body is now, what it does and where it knows."""
        now = self.now_ms()
        chars = {c["id"]: c for c in self.sql("SELECT id, name, kind, stage, alive, ai, home_x, home_y FROM character WHERE kind = 'person'") if c["alive"]}
        players = {c["id"] for c in self.sql("SELECT id FROM my_characters", "player")} if self.st.get("token") else set()
        bodies = {b["id"]: b for b in self.sql("SELECT id, x, y, t_ms, vx, vy, heading, turn, turn_s, next_ms FROM body")}
        acts = {a["id"]: a for a in self.sql("SELECT id, skill, phase, label FROM activity")}
        doing = {d["id"]: d for d in self.sql("SELECT * FROM doing")}
        places = {}
        for p in self.sql("SELECT actor, name, x, y FROM place"):
            places.setdefault(p["actor"], {})[p["name"]] = (p["x"], p["y"])
        out = {}
        self.meals = getattr(self, "meals", set()) | {cid for cid, a in acts.items() if a["skill"] == "eat" and cid in chars}
        for cid, c in chars.items():
            b = bodies.get(cid)
            if not b or cid in players:
                continue
            out[cid] = {
                "id": cid, "name": c["name"], "stage": c["stage"], "home": (c["home_x"], c["home_y"]),
                "at": pose(b, now), "moving": now < b["next_ms"] and (b["vx"] or b["vy"]),
                "skill": acts.get(cid, {}).get("skill", ""), "phase": acts.get(cid, {}).get("phase", -1),
                "doing": doing.get(cid, {}).get("code", 0), "places": places.get(cid, {}),
            }
        return out

    # ---- terrain (for scenes that need a clear way) ----------------------------------------
    def tile(self, x, y):
        self.grid = getattr(self, "grid", {})
        c = ((int(y) // 16) << 16) | (int(x) // 16)
        if c not in self.grid:
            rows = self.sql(f"SELECT id, tiles FROM terrain_chunk WHERE id = {c}")
            raw = rows[0]["tiles"] if rows else bytes([4] * 256)
            self.grid[c] = bytes.fromhex(raw) if isinstance(raw, str) else bytes(raw)
        return self.grid[c][(int(y) % 16) * 16 + int(x) % 16]

    def walkable(self, x, y):
        return self.tile(x, y) in WALKABLE

    def room(self, p):
        return sum(self.walkable(p[0] + dx, p[1] + dy) for dx in range(-2, 3) for dy in range(-2, 3))

    def lanes(self, p, length=6):
        """Unit directions d from which a straight walkable way of `length` tiles leads to p."""
        out = []
        for k in range(8):
            a = k * math.pi / 4
            d = (math.cos(a), math.sin(a))
            if all(self.walkable(p[0] + d[0] * r, p[1] + d[1] * r) for r in range(1, length + 1)):
                out.append(d)
        return out

    def walk_to(self, me, goal, stop_within, secs=6.0):
        """Walk the player straight at `goal` (human_move) until within `stop_within`, then stop."""
        end = time.monotonic() + secs
        b = self.sql(f"SELECT * FROM body WHERE id = {me}")[0]
        at = pose(b, self.now_ms())
        dx, dy = goal[0] - at[0], goal[1] - at[1]
        n = math.hypot(dx, dy) or 1.0
        self.call("human_move", [dx / n, dy / n, False], "player")
        while time.monotonic() < end:
            time.sleep(0.25)
            b = self.sql(f"SELECT * FROM body WHERE id = {me}")[0]
            at = pose(b, self.now_ms())
            if dist(at, goal) <= stop_within:
                break
        self.call("human_move", [0.0, 0.0, False], "player")
        return at

    def structures(self, kinds):
        return [(s["x"], s["y"], s["kind"]) for s in self.sql("SELECT id, kind, x, y FROM structure") if s["kind"] in kinds]

    def uses(self, actor=None, since=0):
        q = "SELECT * FROM skill_use" + (f" WHERE actor = {actor}" if actor else "")
        return [u for u in self.sql(q) if u["at_ms"] >= since]

    def snapshot(self, label, extra=None):
        ppl = self.people()
        data = {"at_ms": self.now_ms(), "hour": round(self.hour(), 2), "people": list(ppl.values())}
        if extra:
            data.update(extra)
        self.save(label, data)
        return ppl


def pose(b, now):
    """`living_rules::steer::pose`: where a body's segment has it now."""
    dt = max(0.0, (min(now, b["next_ms"]) - b["t_ms"]) / 1000.0)
    v = math.hypot(b["vx"], b["vy"])
    x, y, h, turn, turn_s = b["x"], b["y"], b["heading"], b["turn"], b["turn_s"]

    def arc(x, y, h, v, w, dt):
        if dt <= 0:
            return x, y, h
        if v == 0:
            return x, y, h + w * dt
        if abs(w) < 1e-4:
            return x + v * math.cos(h) * dt, y + v * math.sin(h) * dt, h
        h1 = h + w * dt
        r = v / w
        return x + r * (math.sin(h1) - math.sin(h)), y - r * (math.cos(h1) - math.cos(h)), h1

    if turn == 0 or turn_s <= 0:
        x, y, _ = arc(x, y, h, v, 0, dt)
    elif dt <= turn_s:
        x, y, _ = arc(x, y, h, v, turn, dt)
    else:
        x, y, h = arc(x, y, h, v, turn, turn_s)
        x, y, _ = arc(x, y, h, v, 0, dt - turn_s)
    return (x, y)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def adults(ppl):
    return [p for p in ppl.values() if p["stage"] >= 2]


# ---- scenes --------------------------------------------------------------------------------
def scene_work(t, state):
    """Day: workers at their workplaces, doing their work; children playing near home or square."""
    h = t.wait_hour(10.0, 15.0)
    ppl = t.snapshot("work")
    workers = [p for p in adults(ppl) if "work" in p["places"]]
    at_work = [p for p in workers if dist(p["at"], p["places"]["work"]) <= 6]
    working = [p for p in at_work if p["skill"] in WORK]
    t.check("by day, workers are at their workplaces", len(workers) > 50 and len(at_work) >= 0.5 * len(workers), f"hour {h:.1f}: {len(at_work)} of {len(workers)} within 6 tiles of their work place")
    t.check("at work they do their work (keep, gather, cook, read, tend, store)", len(working) >= 0.6 * max(1, len(at_work)), f"{len(working)} of {len(at_work)} at work are doing {sorted({p['skill'] for p in working})}")
    kids = [p for p in ppl.values() if p["stage"] == 1]
    near = [p for p in kids if dist(p["at"], p["home"]) <= 14 or ("square" in p["places"] and dist(p["at"], p["places"]["square"]) <= 14)]
    playing = [p for p in near if p["skill"] in ("play", "wander", "wait")]
    t.check("children play near home or the square", kids and len(near) >= 0.6 * len(kids) and playing, f"{len(near)} of {len(kids)} children within 14 tiles of home or the square; {len(playing)} playing, wandering or pausing")
    # One worker's day so far: from home (seeded there at dawn) to work.
    w = max(at_work, key=lambda p: dist(p["home"], p["places"]["work"]), default=None)
    if w:
        state["worker"] = w["id"]
        t.check("a worker reached a workplace away from home", dist(w["home"], w["places"]["work"]) > 15, f"{w['name']} (#{w['id']}) is {dist(w['at'], w['places']['work']):.1f} tiles from work, {dist(w['home'], w['places']['work']):.0f} tiles from home, doing {w['skill']}")
    state["midday_square"] = sum(1 for p in adults(ppl) if evening_out(p) and dist(p["at"], p["places"]["evening"]) <= 8)


def standing_resident(t, ppl, near=None, skills=("keep",)):
    cands = [p for p in adults(ppl) if p["skill"] in skills and p["phase"] == 1 and not p["moving"]]
    if near:
        cands.sort(key=lambda p: dist(p["at"], near))
    return cands[0] if cands else None


def ensure_player(t):
    if not t.st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        t.st["token"], t.st["identity"] = j["token"], j["identity"]
        V.save(t.st)
    mine = [c for c in t.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not mine:
        t.call("join", ["Visitor"], "player")
        mine = [c for c in t.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    return mine[0]["id"]


def scene_greet(t, state):
    """A player's wave gets a wave or nod back, through the same skills."""
    t.wait_hour(8.0, 16.0)
    me = ensure_player(t)
    ppl = t.people()
    r = standing_resident(t, ppl)
    if not r:
        return t.check("a resident answers a player's wave", False, "no resident standing at a post")
    x, y = r["at"]
    t.call("place_at", [me, x + 3.0, y + 0.5])
    time.sleep(1.5)
    since = t.now_ms()
    code, body = t.call("human_act", [json.dumps({"do": "wave", "target": {"id": r["id"]}})], "player")
    answer, mine = None, None
    for _ in range(20):
        time.sleep(0.5)
        mine = next((u for u in t.uses(me, since) if u["skill"] == "wave"), None)
        answer = next((u for u in t.uses(r["id"], since) if u["skill"] in ("wave", "nod") and u["target"] == me), None)
        if answer and answer["outcome"] and mine and mine["outcome"]:
            break
    exp = t.sql(f"SELECT text, at_ms FROM experience WHERE observer = {me}", "admin")
    told = [e["text"] for e in exp if e["at_ms"] >= since and "greeting" in e["text"]]
    t.save("greet", {"player": me, "resident": r, "player_use": mine, "answer": answer, "player_experiences": told})
    t.check("the player's wave is accepted and greets the resident", code == 200 and mine and mine["accepted_ms"] and mine["outcome"].startswith("greeted"), f"{mine}")
    t.check("the resident answers the player's wave with a wave or nod", answer and answer["source"] == "graph" and answer["accepted_ms"] and answer["outcome"].startswith("answered"), f"{r['name']} (#{r['id']}): {answer}")
    t.check("the player perceives the answer", bool(told), f"{told}")


def scene_approach(t, state):
    """Someone who comes up to a standing resident from behind is faced."""
    t.wait_hour(8.0, 16.0)
    me = ensure_player(t)
    pick = None
    for _ in range(6):
        for p in adults(t.people()):
            if p["skill"] in ("keep", "gather", "rest") and p["phase"] == 1 and not p["moving"]:
                h = t.sql(f"SELECT heading FROM body WHERE id = {p['id']}")[0]["heading"]
                # A clear way in from behind (against the way they face) or from the side.
                behind = [d for d in t.lanes(p["at"]) if d[0] * math.cos(h) + d[1] * math.sin(h) < 0.3]
                if behind:
                    pick = (p, min(behind, key=lambda d: d[0] * math.cos(h) + d[1] * math.sin(h)))
                    break
        if pick:
            break
        time.sleep(5)
    if not pick:
        return t.check("a resident faces someone who comes up behind them", False, "no standing resident with a clear way in from behind")
    r, d = pick
    x, y = r["at"]
    t.call("place_at", [me, x + 6 * d[0], y + 6 * d[1]])
    time.sleep(1.0)
    since = t.now_ms()
    stopped = t.walk_to(me, (x, y), 1.8)
    faced = None
    for _ in range(16):
        time.sleep(0.5)
        faced = next((u for u in t.uses(r["id"], since) if u["skill"] == "face" and u["target"] == me and u["accepted_ms"]), None)
        if faced:
            break
    t.save("approach", {"player": me, "resident": r, "from": d, "player_stopped": stopped, "face": faced})
    t.check("a resident faces someone who comes up behind them", faced is not None, f"{r['name']} (#{r['id']}) -> {faced}; player stopped {dist(stopped, r['at']):.1f} tiles away")


def scene_speak(t, state):
    """Someone who speaks to a standing resident from behind is faced."""
    t.wait_hour(8.0, 16.0)
    me = ensure_player(t)
    r = standing_resident(t, t.people(), skills=("keep", "gather", "rest"))
    if not r:
        return t.check("a resident faces someone who speaks to them", False, "no standing resident")
    b = t.sql(f"SELECT heading FROM body WHERE id = {r['id']}")[0]
    x, y = r["at"]
    t.call("place_at", [me, x - 3 * math.cos(b["heading"]), y - 3 * math.sin(b["heading"])])
    time.sleep(1.5)
    since = t.now_ms()
    t.call("human_say", ["Good day to you.", r["id"]], "player")
    faced = None
    for _ in range(12):
        time.sleep(0.5)
        faced = next((u for u in t.uses(r["id"], since) if u["skill"] == "face" and u["target"] == me and u["accepted_ms"]), None)
        if faced:
            break
    t.save("speak", {"player": me, "resident": r, "face": faced})
    t.check("a resident faces someone who speaks to them", faced is not None, f"{r['name']} (#{r['id']}) -> {faced}")


def scene_aside(t, state):
    """Where the way is narrow (a lane between buildings, a gateway), a resident standing in it
    steps aside for someone walking at them. Residents look once a second and a walker crosses
    the 2.5 tiles in about one, so the scene makes up to three approaches and says which worked."""
    t.wait_hour(8.0, 16.0)
    me = ensure_player(t)
    tried, result = [], None
    for attempt in range(3):
        pick = None
        for _ in range(6):
            for p in adults(t.people()):
                if p["id"] not in tried and p["skill"] in ("keep", "gather", "rest") and p["phase"] == 1 and not p["moving"] and t.room(p["at"]) <= 17:
                    ways = t.lanes(p["at"])
                    if ways:
                        pick = (p, ways[0], t.room(p["at"]))
                        break
            if pick:
                break
            time.sleep(5)
        if not pick:
            break
        r, d, space = pick
        tried.append(r["id"])
        x, y = r["at"]
        t.call("place_at", [me, x + 6 * d[0], y + 6 * d[1]])
        time.sleep(1.0)
        since = t.now_ms()
        t.call("human_move", [-d[0], -d[1], False], "player")
        stepped = None
        for _ in range(12):
            time.sleep(0.5)
            stepped = next((u for u in t.uses(r["id"], since) if u["skill"] == "step_aside"), None)
            if stepped and stepped["outcome"]:
                break
        t.call("human_move", [0.0, 0.0, False], "player")
        rb = t.sql(f"SELECT * FROM body WHERE id = {r['id']}")
        moved = dist(pose(rb[0], t.now_ms()), r["at"]) if rb else 0.0
        result = {"attempt": attempt + 1, "resident": r, "room": space, "approach": d, "use": stepped, "resident_after": rb, "moved": moved}
        t.save(f"aside-{attempt + 1}", result)
        if stepped and stepped["accepted_ms"] and stepped["outcome"] == "made way" and moved >= 0.6:
            break
        time.sleep(2)
    if not result:
        return t.check("a resident in a narrow way steps aside", False, "no resident standing in a narrow spot with a clear approach")
    r, stepped, moved = result["resident"], result["use"], result["moved"]
    t.check("a resident standing in a narrow way steps aside for someone walking at them", stepped is not None and stepped["accepted_ms"] and stepped["outcome"] == "made way" and moved >= 0.6, f"approach {result['attempt']} of up to 3: {r['name']} (#{r['id']}), {result['room']} open tiles of 25 around, doing {r['skill']}, moved {moved:.2f} tiles -> {stepped}")


def scene_rain(t, state):
    """Rain sends people under a roof; when it stops they go back."""
    t.wait_hour(11.0, 15.0)
    shelters = t.structures(SHELTER)

    def under_roof(ppl):
        out = [p for p in adults(ppl) if p["skill"] != "sleep" and min((dist(p["at"], (s[0], s[1])) for s in shelters), default=99) <= 2.5]
        return out, [p for p in adults(ppl) if p["skill"] != "sleep"]

    before, awake = under_roof(t.snapshot("rain-before"))
    t.call("set_weather", [True, 120])
    time.sleep(40)
    ppl = t.snapshot("rain-during", {"weather": t.sql("SELECT * FROM weather")})
    during, awake2 = under_roof(ppl)
    resting = [p for p in during if p["skill"] == "rest"]
    t.check("rain sends people under a roof", len(during) >= 0.6 * len(awake2) and len(during) > len(before) + 0.2 * len(awake2), f"under a roof: {len(before)} of {len(awake)} before, {len(during)} of {len(awake2)} after 40 s of rain ({len(resting)} resting)")
    t.call("set_weather", [False, 3600])
    time.sleep(30)
    after, awake3 = under_roof(t.snapshot("rain-after"))
    t.check("when the rain stops they go back out", len(after) < len(during), f"under a roof 30 s after: {len(after)} of {len(awake3)}")


def scene_wolf(t, state):
    """A wolf in town: residents near it flee or fight, others turn to look."""
    t.wait_hour(13.0, 17.0)
    wolves = [c["id"] for c in t.sql("SELECT id, alive FROM character WHERE kind = 'wolf'") if c["alive"]]
    bold = [b["id"] for b in t.sql("SELECT id, text FROM background") if b["id"] in wolves and '"bold":true' in b["text"]]
    wolf = (bold or wolves or [None])[0]
    ppl = t.people()
    workers = [p for p in adults(ppl) if p["skill"] in WORK and not p["moving"]]
    # Where several are at work together.
    target = max(workers, key=lambda p: sum(1 for q in workers if dist(q["at"], p["at"]) <= 10), default=None)
    if not wolf or not target:
        return t.check("a wolf in town makes residents flee or fight", False, f"wolf {wolf}, target {target}")
    x, y = target["at"]
    since = t.now_ms()
    t.call("place_at", [wolf, x + 6.0, y])
    seen = {}
    for _ in range(14):
        time.sleep(1.0)
        for a in t.sql("SELECT id, skill, label FROM activity"):
            if a["skill"] in ("flee", "attack", "strike", "face", "yield"):
                seen.setdefault(a["id"], set()).add(a["skill"])
    near = {cid for cid, p in ppl.items() if dist(p["at"], (x + 6.0, y)) <= 14}
    fled = [c for c, s in seen.items() if c in ppl and "flee" in s]
    fought = [c for c, s in seen.items() if c in ppl and s & {"attack", "strike"}]
    looks = [u for u in t.uses(since=since) if u["skill"] == "face" and u["target"] == 0 and u["accepted_ms"]]
    story = [c for c in t.sql("SELECT kind, a, b, text, at_ms FROM chronicle") if c["at_ms"] >= since and c["kind"] in ("attack", "death", "killing", "assault")]
    t.save("wolf", {"wolf": wolf, "at": [x + 6.0, y], "near": sorted(near), "activities": {k: sorted(v) for k, v in seen.items()}, "looks": looks, "chronicle": story})
    t.check("a wolf in town makes residents flee or fight", fled or fought, f"wolf #{wolf} at ({x + 6:.0f},{y:.0f}): {len(near)} residents within 14 tiles; {len(fled)} fled, {len(fought)} fought")
    t.check("others turn to look at the fight", bool(looks) or not story, f"{len(looks)} turned to face the commotion; {len(story)} fight or death entries")
    t.call("kill", [wolf, "removed after the scene"])


def evening_out(p):
    """Its evening place is out (the inn or the square), not its home or its work (an evening
    in, or working late: `town_life.evening`)."""
    ev = p["places"].get("evening")
    return ev is not None and dist(ev, p["home"]) > 8 and ("work" not in p["places"] or dist(ev, p["places"]["work"]) > 8)


def scene_evening(t, state):
    """Evening: the square and the inn fill; people nod to each other there."""
    h = t.wait_hour(18.6, 19.8)
    since = t.now_ms() - 30_000
    ppl = t.snapshot("evening")
    there = [p for p in adults(ppl) if evening_out(p) and dist(p["at"], p["places"]["evening"]) <= 8]
    nods = [u for u in t.uses(since=since) if u["skill"] in ("nod", "wave") and u["source"] == "graph" and u["accepted_ms"]]
    mid = state.get("midday_square")
    t.check("the square and the inn fill in the evening", len(there) >= 20 and (mid is None or len(there) >= 2 * max(1, mid)), f"hour {h:.1f}: {len(there)} adults whose evening is out at their evening place (midday: {mid})")
    t.check("people greet each other there", len(nods) > 0, f"{len(nods)} nods or waves by residents in the last 30 s")


def scene_night(t, state):
    """Night: people sleep at home."""
    h = t.wait_hour(0.5, 4.0)
    ppl = t.snapshot("night")
    a = adults(ppl)
    home = [p for p in a if dist(p["at"], p["home"]) <= 3]
    asleep = [p for p in home if p["skill"] in ("sleep", "rest")]
    state["home_at_night"] = [p["id"] for p in home]
    t.check("at night people are at home", len(home) >= 0.7 * len(a), f"hour {h:.1f}: {len(home)} of {len(a)} adults within 3 tiles of home")
    t.check("at home at night they sleep or rest", len(asleep) >= 0.8 * max(1, len(home)), f"{len(asleep)} of {len(home)} asleep or resting")
    # Each keeps their own hours (the `rhythm` table: seeded or drawn per person), so the town
    # does not turn in for the night, or rise, at one moment.
    rows = [r for r in t.sql("SELECT * FROM rhythm") if r["id"] in ppl]
    rises, beds = [r["rise_h"] for r in rows], [r["bed_h"] for r in rows]
    sd = lambda xs: (sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)) ** 0.5 if xs else 0.0
    t.check("each keeps their own hours", len(rows) >= 0.9 * max(1, len(a)) and sd(rises) >= 0.4 and sd(beds) >= 0.6,
            f"{len(rows)} rhythms for {len(a)} adults; rising {min(rises or [0]):.1f}-{max(rises or [0]):.1f} h (sd {sd(rises):.2f}), bed {min(beds or [0]):.1f}-{max(beds or [0]):.1f} h (sd {sd(beds):.2f})")


def scene_morning(t, state):
    """Morning: they leave home for work."""
    h = t.wait_hour(7.2, 9.5)
    ppl = t.snapshot("morning")
    ids = state.get("home_at_night") or [p["id"] for p in adults(ppl)]
    left = [ppl[i] for i in ids if i in ppl and dist(ppl[i]["at"], ppl[i]["home"]) > 4]
    workers = [p for p in left if "work" in p["places"] and (dist(p["at"], p["places"]["work"]) <= 6 or p["skill"] == "goto")]
    t.check("in the morning they leave home", len(left) >= 0.5 * max(1, len(ids)), f"hour {h:.1f}: {len(left)} of {len(ids)} who slept at home are away from it")
    # A day and a night of meals: hunger now (anchored value + rate × elapsed) stays bounded.
    now = t.now_ms()
    hungers = [v["hunger"] + v["hunger_rate"] * (now - v["at_ms"]) / 60000 for v in t.sql("SELECT id, hunger, hunger_rate, at_ms FROM vitals") if v["id"] in ppl]
    starving = [x for x in hungers if x >= 90]
    t.check("they eat when hungry: after a day nobody is starving", hungers and len(starving) <= 0.02 * len(hungers), f"hunger p50 {sorted(hungers)[len(hungers) // 2]:.0f}, max {max(hungers):.0f}; {len(starving)} of {len(hungers)} at 90 or more; {len(t.meals)} residents seen eating during the run")
    t.check("and go to work", len(workers) >= 0.5 * max(1, len(left)), f"{len(workers)} of them at work or on their way")
    # A new day begins once a day for each person, at its own rising (rhythm.last_day): never
    # again and again through the morning, and not for everyone at the world's creation.
    days = Counter(e["observer"] for e in t.sql("SELECT observer, text FROM experience WHERE kind = 'feeling'") if e["text"].startswith("A new day begins"))
    began = [r["last_day"] for r in t.sql("SELECT last_day FROM rhythm")]
    t.check("each person's new day begins once, at their own rising", days and max(days.values()) <= 2 and len(set(began)) >= 1,
            f"{len(days)} people felt a new day; most by one person: {max(days.values()) if days else 0}; days begun: {sorted(Counter(began).items())}")


def census(t, hours=24):
    """Evidence, not a check: once per world hour for a day, where the adults are (home, work,
    their evening place, elsewhere) and what everyone is doing. Run on an undisturbed world."""
    rows = []
    for _ in range(hours):
        h = t.hour()
        ppl = t.people()
        a = adults(ppl)
        where = {"home": 0, "work": 0, "evening place": 0, "elsewhere": 0}
        for p in a:
            if dist(p["at"], p["home"]) <= 3:
                where["home"] += 1
            elif "work" in p["places"] and dist(p["at"], p["places"]["work"]) <= 6:
                where["work"] += 1
            elif "evening" in p["places"] and dist(p["at"], p["places"]["evening"]) <= 8:
                where["evening place"] += 1
            else:
                where["elsewhere"] += 1
        doing = {}
        for p in ppl.values():
            k = p["skill"] or "idle"
            doing[k] = doing.get(k, 0) + 1
        kids = [p for p in ppl.values() if p["stage"] == 1]
        row = {"hour": round(h, 1), "adults": len(a), "where": where, "doing": dict(sorted(doing.items(), key=lambda kv: -kv[1])), "children_playing": sum(1 for p in kids if p["skill"] == "play"), "children": len(kids), "weather": t.sql("SELECT raining FROM weather")[0]["raining"]}
        rows.append(row)
        top = ", ".join(f"{k} {v}" for k, v in list(row["doing"].items())[:6])
        print(f"{h:5.1f}  home {where['home']:3d}  work {where['work']:3d}  evening {where['evening place']:3d}  elsewhere {where['elsewhere']:3d}  | {top}", flush=True)
        t.save("census", {"rows": rows})
        time.sleep(max(1.0, t.world["day_ms"] / 24000 - 0.5))
    return rows


SCENES = {"work": scene_work, "greet": scene_greet, "approach": scene_approach, "speak": scene_speak, "aside": scene_aside, "rain": scene_rain, "wolf": scene_wolf, "evening": scene_evening, "night": scene_night, "morning": scene_morning}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", default="all", choices=["all", "census", *SCENES])
    a = ap.parse_args()
    t = Town(a.run)
    if a.scene == "census":
        # The world's own weather: a census shows the day as it comes, rain included.
        census(t)
        return
    # The seed's own weather is held dry for the run, so only the rain scene's rain falls.
    t.call("set_weather", [False, 3600])
    state = {}
    order = list(SCENES) if a.scene == "all" else [a.scene]
    for name in order:
        try:
            SCENES[name](t, state)
        except Exception as e:  # keep driving the other scenes; the failure is recorded
            t.check(f"scene {name} ran", False, repr(e))
    t.call("set_weather", [False, 0])
    (t.out / "town.json").write_text(json.dumps(t.results, indent=1) + "\n")
    failed = [r for r in t.results if not r["ok"]]
    print(f"{len(t.results) - len(failed)} of {len(t.results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
