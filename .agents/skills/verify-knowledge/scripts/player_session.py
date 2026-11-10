#!/usr/bin/env python3
"""A scripted human-player session on a scratch island world (docs/PLAYER_MEMORY.md).

The player's own non-admin identity joins, walks, gathers, talks to a resident, waves at them
and fights a wolf, through the player reducers (`join`, `human_move`, `human_act`,
`human_say`, `use_skill`). Admin `place_at` sets two scenes (beside the resident, near a bold
wolf) and is named in the output, because a player cannot do it. The session's ground truth
is read back from the authority's rows: the player's `experience` window, its `skill_use`
record and the `chronicle` lines it spoke.

    player_session.py --run RUN [--name Wren] [--out session.json] [--resident ID]

Needs `verify.py launch --run RUN --seed island`. Python standard library only.
"""

import argparse
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


class Session:
    def __init__(self, run):
        self.run = run
        self.st = V.load(run)
        self.db = self.st["db"]
        self.admin = V.admin_token()
        self.steps = []

    def sql(self, q, who="admin"):
        token = self.admin if who == "admin" else self.st.get("token") if who == "player" else None
        code, body = V.http(f"/v1/database/{self.db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, reducer, args, who="player"):
        token = self.admin if who == "admin" else self.st["token"]
        code, body = V.http(f"/v1/database/{self.db}/call/{reducer}", args, token)
        V.log(self.st, f"call {reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}", sys.stderr)
        return code, body

    def step(self, what, **detail):
        self.steps.append({"at_ms": int(time.time() * 1000), "step": what, **detail})
        print(f"- {what} {json.dumps(detail) if detail else ''}", flush=True)

    def ensure_player(self, name):
        if "token" not in self.st:
            code, body = V.http("/v1/identity", {})
            if code != 200:
                raise RuntimeError(f"identity: {code} {body}")
            j = json.loads(body)
            self.st["token"], self.st["identity"] = j["token"], j["identity"]
            V.save(self.st)
        if self.me() is None:
            code, body = self.call("join", [name])
            if code != 200:
                raise RuntimeError(f"join: {code} {body}")
            time.sleep(0.5)
        return self.me()

    def me(self):
        # The player's own characters through its view: `character` is private in the default
        # scoped build (docs/PERCEPTION.md).
        rows = self.sql("SELECT id, name, alive FROM my_characters", "player")
        alive = [r for r in rows if r["alive"]]
        return alive[0]["id"] if alive else None

    def body(self, cid):
        r = self.sql(f"SELECT x, y FROM body WHERE id = {cid}")
        return (r[0]["x"], r[0]["y"]) if r else None

    def hp(self, cid):
        r = self.sql(f"SELECT hp FROM vitals WHERE id = {cid}")
        return r[0]["hp"] if r else None

    def resident_near(self, me, avoid=()):
        here = self.body(me)
        best = None
        for r in self.sql("SELECT id, name, ai, alive, kind FROM character WHERE kind = 'person' AND ai = true AND alive = true"):
            if r["id"] in avoid:
                continue
            b = self.body(r["id"])
            if not b:
                continue
            d = math.dist(here, b)
            if best is None or d < best[0]:
                best = (d, r)
        return best[1] if best else None

    def wolves(self):
        rows = self.sql("SELECT id, text FROM background")
        bold = {r["id"] for r in rows if '"bold":true' in r["text"]}
        alive = {r["id"] for r in self.sql("SELECT id FROM character WHERE kind = 'wolf' AND alive = true")}
        return sorted(bold & alive) or sorted(alive)


def run_session(s, name, resident=None, fight_s=12.0):
    me = s.ensure_player(name)
    s.step("joined", character=me, name=name)
    time.sleep(2)

    # Walk east for 4 s, then north for 3 s, then stop.
    start = s.body(me)
    s.call("human_move", [1.0, 0.0, False])
    time.sleep(4)
    s.call("human_move", [0.0, -1.0, True])
    time.sleep(3)
    s.call("human_move", [0.0, 0.0, False])
    s.step("walked", start=start, end=s.body(me))
    time.sleep(1)

    # Gather from the nearest tree, then berries.
    for target in ("tree", "berry_bush"):
        code, body = s.call("human_act", [json.dumps({"do": {"skill": "gather", "target": {"nearest": target}}})])
        s.step("gather", target=target, status=code, body=body.strip()[:200])
        time.sleep(9)
    inv = s.sql(f"SELECT item, qty FROM inventory WHERE owner = {me}")
    s.step("inventory", items={r["item"]: r["qty"] for r in inv})

    # Talk to a resident (admin place_at sets the scene beside them), then wave.
    r = s.sql(f"SELECT id, name FROM character WHERE id = {resident}")[0] if resident else s.resident_near(me)
    if r is None:
        # The island's residents live on instinct (no mind): admin `spawn_crowd` adds one
        # minded person (controlled by the mind service's identity) to talk to.
        s.call("spawn_crowd", [1, True], "admin")
        time.sleep(1)
        r = s.resident_near(me)
        s.step("scene: admin spawn_crowd 1 minded resident", resident=r["id"])
    here = s.body(me)
    s.call("place_at", [r["id"], here[0] + 1.6, here[1]], "admin")
    s.call("set_behavior", [r["id"], json.dumps({"wait": 90})], "admin")
    rb = s.body(r["id"])
    s.step("scene: admin place_at resident beside the player, set_behavior wait", resident=r["id"], resident_name=r["name"])
    time.sleep(1.5)
    for line in (f"Hello {r['name']}, I just arrived on this island. Where can I find food?",
                 "Thank you. I gathered some wood and berries by the shore."):
        code, body = s.call("human_say", [line, r["id"]])
        s.step("said", to=r["id"], text=line, status=code)
        time.sleep(8)
    code, body = s.call("human_act", [json.dumps({"do": "wave", "target": {"id": r["id"]}})])
    s.step("waved", to=r["id"], status=code)
    time.sleep(5)

    # Fight a wolf: admin place_at 5 tiles from a bold wolf, strike when it is in reach.
    ws = s.wolves()
    if ws:
        w = ws[0]
        wp = s.body(w)
        s.call("place_at", [me, wp[0] + 5.0, wp[1]], "admin")
        s.step("scene: admin place_at near a wolf", wolf=w)
        end = time.time() + fight_s
        strikes = 0
        while time.time() < end and s.me() == me:
            mp, wp = s.body(me), s.body(w)
            if not mp or not wp:
                break
            hp = s.hp(me)
            if hp is not None and hp < 55:
                break
            if math.dist(mp, wp) <= 1.8:
                s.call("use_skill", ["strike", w, wp[0], wp[1]])
                strikes += 1
                time.sleep(0.9)
            else:
                time.sleep(0.3)
        s.step("fought", wolf=w, strikes=strikes, my_hp=s.hp(me), wolf_hp=s.hp(w), alive=s.me() == me)
        # Leave the fight: back beside the resident.
        if s.me() == me:
            s.call("place_at", [me, rb[0] + 2.5, rb[1] + 1.0], "admin")
            s.call("human_move", [0.0, 0.0, False])
            s.step("scene: admin place_at back to town")
    time.sleep(3)
    return me, r["id"]


def evidence(s, me):
    exps = sorted(s.sql(f"SELECT * FROM experience WHERE observer = {me}"), key=lambda e: e["id"])
    uses = s.sql(f"SELECT * FROM skill_use WHERE actor = {me}")
    said = [c for c in s.sql("SELECT * FROM chronicle WHERE kind = 'speech'") if c["a"] == me]
    return {"experiences": exps, "skill_uses": uses, "spoke": said}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--name", default="Wren")
    ap.add_argument("--resident", type=int)
    ap.add_argument("--out", default="session.json")
    a = ap.parse_args()
    s = Session(a.run)
    me, resident = run_session(s, a.name, a.resident)
    out = {"run": a.run, "player": me, "resident": resident, "steps": s.steps, **evidence(s, me)}
    path = V.run_dir(a.run) / a.out
    path.write_text(json.dumps(out, indent=1))
    kinds = {}
    for e in out["experiences"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"player #{me}: {len(out['experiences'])} experiences {kinds}; {path}")


if __name__ == "__main__":
    main()
