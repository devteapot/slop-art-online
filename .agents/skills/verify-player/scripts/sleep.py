#!/usr/bin/env python3
"""What wakes a player's sleeping character, by the same rule as anyone's (perceive::wakes): a
sound at least the `wake_loudness` law loud (its spec's `loudness`) within `wake_reach` metres.

The player sleeps through its own command (`human_act` with a run of sleeps), then:

- a quiet line to it (a resident's `say`) does not wake it, and is not in its log
  (`my_experience`) while it sleeps; a resident calling its name (`call`) wakes it, the log says
  "You woke up: … calls out to you …", and the quiet line comes after it as "While you slept, you
  heard: …";
- someone else's baby crying about 3 m away wakes it;
- a fight beyond the reach does not wake it; the same fight about 3 m away does.

    sleep.py --run RUN

Needs `verify.py launch --run RUN --seed $PWD/.agents/skills/verify-core/scripts/infant` (a
baby and four AI adults). Admin reducers set the scene only: `place_at`, `set_behavior` and
`mind_say` (the residents' lines, as their minds would say them). Writes `RUN/sleep.json`.
Python standard library only.
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
THOUGHT = {"kind": "deliberate", "summary": "verify-player sleep", "detail": "", "latency_ms": 0, "tokens": 0, "model": "fake", "reference": ""}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    st = V.load(a.run)
    db = st["db"]
    admin = V.admin_token()
    if not st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        st["token"], st["identity"] = j["token"], j["identity"]
        V.save(st)

    def sql(q, token):
        code, body = V.http(f"/v1/database/{db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(reducer, args, as_admin=False):
        code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, admin if as_admin else st["token"])
        V.log(st, f"call {reducer}{json.dumps(args)[:200]} as {'admin' if as_admin else 'player'} -> {code} {body.strip()[:200]}", sys.stderr)
        if code != 200:
            raise RuntimeError(f"{reducer}: {code} {body}")
        return code, body

    results, snaps = [], {}

    def check(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + f": {json.dumps(detail)[:300]}", flush=True)

    def wait_for(pred, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v = pred()
            if v:
                return v
            time.sleep(0.5)
        return pred()

    def log(words, kind=None):
        return [r for r in sql("SELECT id, kind, text, at_ms FROM my_experience", st["token"]) if words in r["text"] and (kind is None or r["kind"] == kind)]

    def woken(words):
        return [r for r in log("You woke up: ", "body") if words in r["text"]]

    live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    if not live:
        call("join", ["Sleeper"])
        live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    me = live[0]["id"]
    people = sql("SELECT id, name, kind, ai, alive, stage FROM character", admin)
    baby = next(c for c in people if c["kind"] == "person" and c["alive"] and c["stage"] == 0)
    adults = [c for c in people if c["kind"] == "person" and c["ai"] and c["alive"] and c["stage"] >= 2]
    speaker, f1, f2 = adults[0]["id"], adults[1]["id"], adults[2]["id"]
    name = next(c["name"] for c in people if c["id"] == me)
    snaps["cast"] = {"player": me, "speaker": speaker, "fighters": [f1, f2], "baby": baby["id"]}
    for who in (speaker, f1, f2, baby["id"]):
        call("set_behavior", [who, json.dumps({"wait": 120})], as_admin=True)
    body = lambda who: sql(f"SELECT x, y FROM body WHERE id = {who}", admin)[0]
    home = body(me)
    hx, hy = home["x"], home["y"]

    def at(who, dx):
        call("place_at", [who, hx + dx, hy], as_admin=True)
        b = body(who)
        return round(math.hypot(b["x"] - body(me)["x"], b["y"] - body(me)["y"]), 1)

    park = lambda who: at(who, 40)
    for who in (speaker, f1, f2, baby["id"]):
        park(who)

    def sleep():
        call("human_act", [json.dumps({"seq": [{"do": "sleep"}] * 30})])
        ok = wait_for(lambda: sql(f"SELECT * FROM slumber WHERE actor = {me}", admin), 20)
        check("the player's character is asleep (its slumber row)", ok, ok)

    asleep = lambda: bool(sql(f"SELECT * FROM slumber WHERE actor = {me}", admin))

    # 1. A quiet line, then a called name.
    d = at(speaker, 3)
    sleep()
    quiet = f"{name}, are you awake? verify quiet line"
    call("mind_say", [speaker, quiet, me, "", 0, THOUGHT], as_admin=True)
    time.sleep(4)
    check("a quiet line does not wake it", asleep() and not woken(""), {"distance": d, "asleep": asleep()})
    check("the quiet line is not in its log while it sleeps", not log("verify quiet line"), log("verify quiet line"))
    call("mind_say", [speaker, f"{name}!", me, "call", 0, THOUGHT], as_admin=True)
    got = wait_for(lambda: woken("calls out"), 15)
    snaps["called"] = got
    check("a called name wakes it, and its log says why", got, got)
    heard = wait_for(lambda: log("verify quiet line", "heard_asleep"), 5)
    snaps["heard_asleep"] = heard
    check("then the quiet line is in its log, as heard while asleep", len(heard) == 1 and heard[0]["text"].startswith("While you slept, you heard: "), heard)
    park(speaker)

    # 2. Someone else's baby crying about 3 m away.
    d = at(baby["id"], 3)
    sleep()
    call("set_behavior", [baby["id"], json.dumps({"do": {"skill": "signal", "item": "cry"}})], as_admin=True)
    got = wait_for(lambda: woken("crying"), 60)
    call("set_behavior", [baby["id"], json.dumps({"wait": 120})], as_admin=True)
    snaps["cry"] = got
    check("someone else's baby crying nearby wakes it", got, {"distance": d, "told": got})
    park(baby["id"])

    # 3. A fight beyond the reach, then about 3 m away.
    far1, far2 = at(f1, 12), at(f2, 13)
    sleep()
    before = len(woken(""))
    call("set_behavior", [f1, json.dumps({"do": "attack", "target": {"nearest": "person"}})], as_admin=True)
    time.sleep(8)
    check("a fight beyond the reach does not wake it", asleep() and len(woken("")) == before, {"distances": [far1, far2], "asleep": asleep()})
    near1, near2 = at(f2, 3), at(f1, 4)
    got = wait_for(lambda: woken("fight"), 30)
    for who in (f1, f2):
        call("set_behavior", [who, json.dumps({"wait": 120})], as_admin=True)
    snaps["fight"] = got
    snaps["fighters_after"] = sql(f"SELECT id, alive FROM character WHERE id = {f1} OR id = {f2}", admin)
    snaps["woken_all"] = woken("")
    check("a fight about 3 m away wakes it", got, {"distances": [near1, near2], "told": got, "woken": snaps["woken_all"][-3:], "fighters": snaps["fighters_after"]})
    call("human_act", [json.dumps({"wait": 1})])

    out = V.run_dir(a.run) / "sleep.json"
    out.write_text(json.dumps({"results": results, "snapshots": snaps}, indent=2) + "\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
