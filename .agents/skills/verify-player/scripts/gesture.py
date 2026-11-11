#!/usr/bin/env python3
"""Gestures for a player on a scratch island world (docs/TOWN_LIFE.md).

The player's own identity gestures through `human_act` (the deliberate-act path every player
command takes): it waves and nods at a resident and gets an answer, turns to face someone,
and is refused what the rules refuse. `use_skill` is refused for a gesture (it takes only the
skill bar). Admin `place_at` sets the scene (named in the report). Results are read from the
authority's rows: `skill_use` (intention to outcome), `doing`, `body` and the player's
`experience` rows.

    gesture.py --run RUN

Needs `verify.py launch --run RUN --seed island`; joins a player if the run has none.
Writes `RUN/gesture.json`. Python standard library only.
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

RESULTS = []


class P:
    def __init__(self, run):
        self.st = V.load(run)
        self.db = self.st["db"]
        self.admin = V.admin_token()

    def sql(self, q, who="admin"):
        token = self.admin if who == "admin" else self.st["token"] if who == "player" else None
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

    def act(self, node):
        return self.call("human_act", [json.dumps(node)])

    def uses(self, actor, since):
        return [u for u in self.sql(f"SELECT * FROM skill_use WHERE actor = {actor}") if u["at_ms"] >= since]

    def told(self, me, since):
        return [e["text"] for e in self.sql(f"SELECT text, at_ms FROM experience WHERE observer = {me}") if e["at_ms"] >= since]


def check(p, name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    V.log(p.st, f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


def now_ms():
    return int(time.time() * 1000)


def wait_for(fn, secs=8.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        r = fn()
        if r:
            return r
        time.sleep(0.4)
    return fn()


def resident(p, near):
    """The resident standing at a post now (keeping a stall, a workshop, a gate) nearest `near`,
    the player's arrival point inside a town. Not just the first found: since world creation
    repeats (2026-11-10) that was always the same outlaw keeping the road, whose fellows
    threaten a stranger who comes near, and the commotion took its attention from the greeting."""
    acts = {a["id"]: a for a in p.sql("SELECT id, skill, phase FROM activity")}
    ppl = {c["id"]: c for c in p.sql("SELECT id, name, stage, alive FROM character WHERE kind = 'person'") if c["alive"] and c["stage"] >= 2}
    posts = [b for b in p.sql("SELECT id, x, y, next_ms FROM body") if b["id"] in ppl and (a := acts.get(b["id"])) and a["skill"] == "keep" and a["phase"] == 1 and b["next_ms"] > 10**18]
    if not posts:
        return None
    b = min(posts, key=lambda b: math.dist((b["x"], b["y"]), near))
    return {"id": b["id"], "name": ppl[b["id"]]["name"], "at": (b["x"], b["y"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = P(a.run)
    if not p.st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        p.st["token"], p.st["identity"] = j["token"], j["identity"]
        V.save(p.st)
    mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not mine:
        p.call("join", ["Visitor"])
        mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = mine[0]["id"]
    my_name = p.sql(f"SELECT name FROM character WHERE id = {me}")[0]["name"]
    here = p.sql(f"SELECT x, y FROM body WHERE id = {me}")[0]
    r = wait_for(lambda: resident(p, (here["x"], here["y"])), 60)
    if not r:
        check(p, "a resident is standing at a post", False, "none found within 60 s")
        return finish(p)
    x, y = r["at"]
    # A spot 3 m from the resident from which the player sees it: gestures are seen, so since
    # 2026-11-09 a wall or a building between them hides the resident (and the act at it is
    # refused, as for anyone out of sight); since eye-2 an open stall does not.
    sees = lambda: any(c["id"] == r["id"] for c in p.sql("SELECT id FROM seen_characters", "player"))
    for dx, dy in [(3.0, 0.5), (-3.0, 0.5), (0.5, 3.0), (0.5, -3.0)]:
        p.call("place_at", [me, x + dx, y + dy], "admin")
        time.sleep(1.0)
        if sees():
            break
    check(p, "the player stands where it sees the resident", sees(), f"{r['name']} (#{r['id']}) in the player's seen_characters")
    time.sleep(0.5)

    # 1. A wave, answered.
    since = now_ms()
    code, _ = p.act({"do": "wave", "target": {"id": r["id"]}})
    shown = wait_for(lambda: [d for d in p.sql(f"SELECT * FROM doing WHERE id = {me}")], 3)
    mine_u = wait_for(lambda: next((u for u in p.uses(me, since) if u["skill"] == "wave" and u["outcome"]), None))
    answer = wait_for(lambda: next((u for u in p.uses(r["id"], since) if u["skill"] in ("wave", "nod") and u["target"] == me and u["outcome"]), None))
    card = {c["code"]: c["skill"] for c in p.sql("SELECT skill, code FROM act_card")}
    # Names follow what one knows (docs/PERCEPTION.md): the newcomer greets "a stranger", unless
    # its view already names the resident.
    seen = next((c for c in p.sql("SELECT * FROM seen_characters", "player") if c["id"] == r["id"]), None)
    label = seen["label"] if seen else r["name"]
    check(p, "human_act wave is accepted and recorded (player's skill_use)", code == 200 and mine_u and mine_u["source"] == "act" and mine_u["accepted_ms"] and mine_u["outcome"] == f"greeted {label}", f"{mine_u}; the player perceives the resident as {label!r}")
    check(p, "others see the wave (doing row with the wave's act_card code)", shown and card.get(shown[0]["code"]) == "wave" and shown[0]["target"] == r["id"], f"{shown}")
    check(p, "the resident answers the player's wave", answer and answer["source"] == "graph" and answer["outcome"] in (f"answered {my_name}", "answered a stranger"), f"{r['name']} (#{r['id']}): {answer}")
    told = wait_for(lambda: [t for t in p.told(me, since) if "answers your greeting" in t])
    check(p, "the player perceives the answer as an experience", bool(told), f"{told}")

    # 2. Answering does not start another round: the resident is not greeted back by the answer.
    time.sleep(3)
    again = [u for u in p.uses(r["id"], since) if u["skill"] in ("wave", "nod")]
    check(p, "an answer closes the greeting (one answer, no endless exchange)", len(again) == 1, f"{len(again)} gestures by the resident")

    # 3. A nod, after the greeting has closed, greets them anew.
    time.sleep(8)
    since = now_ms()
    p.act({"do": "nod", "target": {"id": r["id"]}})
    nod = wait_for(lambda: next((u for u in p.uses(me, since) if u["skill"] == "nod" and u["outcome"]), None))
    answer2 = wait_for(lambda: next((u for u in p.uses(r["id"], since) if u["skill"] in ("wave", "nod") and u["target"] == me and u["outcome"]), None))
    check(p, "a nod greets and is answered", nod and nod["outcome"].startswith("greeted") and answer2, f"player {nod}; resident {answer2}")

    # 4. Facing: the body turns where it stands.
    p.call("place_at", [me, x - 3.0, y], "admin")
    time.sleep(1.0)
    p.act({"do": "face", "target": {"id": r["id"]}})
    time.sleep(1.5)
    b = p.sql(f"SELECT x, y, heading, turn, turn_s FROM body WHERE id = {me}")[0]
    h = b["heading"] + b["turn"] * b["turn_s"]
    want = math.atan2(y - b["y"], x - b["x"])
    off = abs((h - want + math.pi) % (2 * math.pi) - math.pi)
    check(p, "human_act face turns the player's body to face the resident", off < 0.4, f"heading {h:.2f}, toward them {want:.2f}, off {off:.2f} rad")

    # 5. Refusals, told back as experiences.
    since = now_ms()
    p.act({"do": "wave", "target": "self"})
    told = wait_for(lambda: [t for t in p.told(me, since) if "did not work out" in t or "not to yourself" in t])
    check(p, "waving at oneself is refused by the rules", any("not to yourself" in t for t in told), f"{told}")
    code, body = p.call("use_skill", ["wave", r["id"], 0.0, 0.0])
    refused = [u for u in p.uses(me, since) if u["skill"] == "wave" and not u["accepted_ms"]]
    check(p, "use_skill takes only the skill bar: a gesture goes through human_act", code != 200 or refused or "bar" in body, f"{code} {body.strip()[:160]} {refused}")
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "gesture.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
