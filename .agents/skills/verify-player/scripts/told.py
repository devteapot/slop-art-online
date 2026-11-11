#!/usr/bin/env python3
"""A player is told when its command fails, as an AI character is told: the same words, one
`own` line in its log (`my_experience`), once per `repeat_failure_s` (120 s).

Two commands, each beside an AI character given the same graph as the control:

- refused at start: `{"do":"graze"}` ("only deer graze"); sent twice, the second inside the
  window must add no line;
- failed after starting: a gift (`{"seq":[give]}`, so it runs as a graph, not a deliberate
  act) whose receiver is moved 6 m away (out of reach, still in sight) while it is handed over
  ("they moved away"). A
  target out of sight is no use here (a `follow`, or a receiver moved 40 m): the evaluator drops
  the node without a report,
  for an AI too.

The player reads its lines through `my_experience` with its own identity. The AI's lines, and
`character.ai`/`presence.ai` (the person still plays it, the minds have not taken over), are
read as the owner. Before 2026-11-11 a player got no line for either.

    told.py --run RUN

Needs `verify.py launch --run RUN` on a seed with AI people (the default `world`). Admin
reducers set the scene only: `place_near`, `place_at`, `set_behavior`, `grant_items`. Writes `RUN/told.json`.
Python standard library only.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


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
        V.log(st, f"call {reducer}{json.dumps(args)} as {'admin' if as_admin else 'player'} -> {code} {body.strip()}", sys.stderr)
        if as_admin and code != 200:
            raise RuntimeError(f"{reducer}: {code} {body}")
        return code, body

    results, snaps = [], {}

    def check(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + f": {json.dumps(detail)[:300]}", flush=True)

    def mine(words):
        return [r for r in sql("SELECT id, kind, text, at_ms FROM my_experience", st["token"]) if r["kind"] == "own" and words in r["text"]]

    def theirs(actor, words):
        return [r for r in sql(f"SELECT id, kind, text, at_ms FROM experience WHERE observer = {actor}", admin) if r["kind"] == "own" and words in r["text"]]

    def played(me):
        c = sql(f"SELECT ai, controller FROM character WHERE id = {me}", admin)[0]
        p = sql(f"SELECT ai, present FROM presence WHERE id = {me}", admin)
        return {"character_ai": c["ai"], "presence": p}

    def wait_for(pred, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v = pred()
            if v:
                return v
            time.sleep(0.5)
        return pred()

    live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    if not live:
        call("join", ["Told"])
        live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    me = live[0]["id"]
    people = [c["id"] for c in sql("SELECT id, kind, ai, alive, stage FROM character", admin)
              if c["kind"] == "person" and c["ai"] and c["alive"] and c["stage"] == 2 and c["id"] != me]
    ai, other = people[0], people[1]
    snaps["cast"] = {"player": me, "ai_control": ai, "followed": other}
    for who in (ai, other):
        call("set_behavior", [who, json.dumps({"wait": 120})], as_admin=True)
    call("place_near", [ai, me], as_admin=True)
    call("place_near", [other, me], as_admin=True)

    # 1. Refused at start.
    call("set_behavior", [ai, json.dumps({"seq": [{"do": "graze"}, {"wait": 120}]})], as_admin=True)
    code, body = call("human_act", [json.dumps({"do": "graze"})])
    check("human_act {do:graze} is accepted (refused in the tick, not by the reducer)", code == 200, f"{code} {body.strip()[:120]}")
    got = wait_for(lambda: mine("graze"), 6)
    snaps["refused_player"] = got
    snaps["refused_ai"] = theirs(ai, "graze")
    snaps["refused_played"] = played(me)
    snaps["refused_plan"] = sql(f"SELECT plan, source FROM brain WHERE id = {me}", admin)
    check("the person still plays the character (no takeover)", not snaps["refused_played"]["character_ai"], snaps["refused_played"])
    check("refused at start: exactly one line in the player's log", len(got) == 1, got)
    check("refused at start: the same text as the AI's", len(got) == 1 and len(snaps["refused_ai"]) == 1 and got[0]["text"] == snaps["refused_ai"][0]["text"],
          {"player": [r["text"] for r in got], "ai": [r["text"] for r in snaps["refused_ai"]]})
    check("the failed command falls back to waiting for you", snaps["refused_plan"] and snaps["refused_plan"][0]["plan"] == "waiting for you", snaps["refused_plan"])
    code, body = call("human_act", [json.dumps({"do": "graze"})])
    time.sleep(4)
    again = mine("graze")
    snaps["refused_again"] = again
    check("the same refusal inside the window adds no line", code == 200 and len(again) == 1, again)

    # 2. Failed after starting: a gift whose receiver is taken away while it is handed over
    #    (`complete`: "they moved away"). The player's command, then the AI's graph.
    give = {"seq": [{"do": {"skill": "give", "target": {"id": other}, "item": "berries", "qty": 1}}]}

    def break_off(actor, start):
        call("grant_items", [actor, "berries", 3], as_admin=True)
        call("place_near", [other, actor], as_admin=True)
        call("set_behavior", [other, json.dumps({"wait": 120})], as_admin=True)
        start()
        end, seen = time.monotonic() + 8, None
        while time.monotonic() < end and not seen:
            r = sql(f"SELECT skill, phase, label FROM activity WHERE id = {actor}", admin)
            seen = r[0] if r and r[0]["skill"] == "give" and r[0]["phase"] == 1 else None
            time.sleep(0.05)
        b = sql(f"SELECT x, y FROM body WHERE id = {other}", admin)[0]
        call("place_at", [other, b["x"] + (6.0 if b["x"] < 300 else -6.0), b["y"]], as_admin=True)
        return seen

    started = break_off(me, lambda: call("human_act", [json.dumps(give)]))
    check("the player's gift started (performing)", started, started)
    got = wait_for(lambda: mine("they moved away"), 6)
    snaps["broken_player"] = got
    snaps["broken_played"] = played(me)
    snaps["broken_plan"] = sql(f"SELECT plan, source FROM brain WHERE id = {me}", admin)
    started = break_off(ai, lambda: call("set_behavior", [ai, json.dumps({"seq": [give["seq"][0], {"wait": 120}]})], as_admin=True))
    check("the AI's gift started (performing)", started, started)
    snaps["broken_ai"] = wait_for(lambda: theirs(ai, "they moved away"), 6)
    check("the person still plays the character (no takeover)", not snaps["broken_played"]["character_ai"], snaps["broken_played"])
    check("failed after starting: exactly one line in the player's log", len(got) == 1, got)
    check("failed after starting: the same text as the AI's", len(got) == 1 and len(snaps["broken_ai"]) == 1 and got[0]["text"] == snaps["broken_ai"][0]["text"],
          {"player": [r["text"] for r in got], "ai": [r["text"] for r in snaps["broken_ai"]]})
    check("the failed command falls back to waiting for you", snaps["broken_plan"] and snaps["broken_plan"][0]["plan"] == "waiting for you", snaps["broken_plan"])

    out = V.run_dir(a.run) / "told.json"
    out.write_text(json.dumps({"results": results, "snapshots": snaps}, indent=2) + "\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
