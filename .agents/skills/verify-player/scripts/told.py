#!/usr/bin/env python3
"""A player is told when its command fails, as an AI character is told: the same words, one
`own` line in its log (`my_experience`), once per `repeat_failure_s` (120 s).

Two commands, each beside an AI character given the same graph as the control:

- refused at start: `{"do":"graze"}` ("only grazing animals graze"); sent twice, the second inside the
  window must add no line;
- failed after starting: a gift (`{"seq":[give]}`, so it runs as a graph, not a deliberate
  act) whose receiver is moved 4.5 m away (out of reach, still in sight even unlit at night, 6 m)
  while it is handed over ("they moved away");
- lost from sight while it is handed over (give-out-of-sight-line, 2026-11-26): the receiver is
  moved 20 m away (beyond sight in any light). A graph's gift (the player's command, the AI's
  graph) is broken off by its leaf's next look ("lost sight of them", `act::lost`) unless its 1 s
  timer finds them gone first ("they moved away"); a deliberate act (`human_act {do:give}`, a
  mind's `mind_act`, here called as the admin) only by its timer. Each attempt must give exactly
  one line; each graph form retries (a new item each time, so the repeat window does not hold
  the line back) until the leaf's look has told it at least once. Before the fix the leaf's look
  told nothing, for an AI too (only `stuck: give: no #N in sight` in its status).

The player reads its lines through `my_experience` with its own identity. The AI's lines, and
`character.ai`/`presence.ai` (the person still plays it, the minds have not taken over), are
read as the owner. Before 2026-11-11 a player got no line for either.

    told.py --run RUN

Needs `verify.py launch --run RUN` on a seed with AI people (the default `world`). Admin
reducers set the scene only: `place_near`, `place_at`, `set_behavior`, `grant_items` (and
`mind_act` for the AI's deliberate act). Writes `RUN/told.json`.
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
        # Out of reach (1.8 m and 1 m slack) but in sight even unlit at night (6 m): 6 m could
        # leave sight at night, where the leaf's look tells "lost sight of them" (part 3).
        b = sql(f"SELECT x, y FROM body WHERE id = {other}", admin)[0]
        call("place_at", [other, b["x"] + (4.5 if b["x"] < 300 else -4.5), b["y"]], as_admin=True)
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

    # 3. Lost from sight while it is handed over: the receiver moved 20 m away.
    def gift(item):
        return {"do": {"skill": "give", "target": {"id": other}, "item": item, "qty": 1}}

    def failed_gift(actor, item, since):
        rows = (sql("SELECT id, kind, text, at_ms FROM my_experience", st["token"]) if actor == me
                else sql(f"SELECT id, kind, text, at_ms FROM experience WHERE observer = {actor}", admin))
        return [r for r in rows if r["kind"] in ("own", "act") and r["at_ms"] >= since and f"give {item} " in r["text"]
                and ("You failed to" in r["text"] or "did not work out" in r["text"])]

    def out_of_sight(actor, start, item):
        call("set_behavior", [other, json.dumps({"wait": 120})], as_admin=True)
        if actor == ai:
            call("set_behavior", [ai, json.dumps({"wait": 120})], as_admin=True)
        call("grant_items", [actor, item, 2], as_admin=True)
        call("place_near", [other, actor], as_admin=True)
        since = sql("SELECT last_ms FROM clock", admin)[0]["last_ms"]
        start(item)
        end, seen = time.monotonic() + 8, None
        while time.monotonic() < end and not seen:
            r = sql(f"SELECT skill, phase, node, item FROM activity WHERE id = {actor}", admin)
            seen = r[0] if r and r[0]["skill"] == "give" and r[0]["phase"] == 1 and r[0]["item"] == item else None
            time.sleep(0.03)
        if not seen:
            return {"item": item, "performing": None, "lines": failed_gift(actor, item, since)}
        b = sql(f"SELECT x, y FROM body WHERE id = {other}", admin)[0]
        call("place_at", [other, b["x"] + (20.0 if b["x"] < 300 else -20.0), b["y"]], as_admin=True)
        got = wait_for(lambda: failed_gift(actor, item, since), 6)
        time.sleep(3)  # a second line would come within the leaf's next looks
        got = failed_gift(actor, item, since)
        return {"item": item, "performing": seen, "lines": got,
                "status": sql(f"SELECT status FROM mind_state WHERE id = {actor}", admin)}

    forms = [
        ("the player's command", me, True, lambda item: call("human_act", [json.dumps({"seq": [gift(item)]})])),
        ("the AI's graph", ai, True, lambda item: call("set_behavior", [ai, json.dumps({"seq": [gift(item), {"wait": 120}]})], as_admin=True)),
        ("the player's deliberate act", me, False, lambda item: call("human_act", [json.dumps(gift(item))])),
        ("the AI's deliberate act", ai, False, lambda item: call("mind_act", [ai, [json.dumps(gift(item))], "told"], as_admin=True)),
    ]
    # Not berries for a graph's gift: part 2 told "give berries → person: they moved away" less
    # than `repeat_failure_s` ago, so the timer's path would be held back as that repeat.
    items = ["meat", "stone", "wood", "fiber", "stick", "hide"]
    for name, actor, graph, start in forms:
        tries = []
        # A try whose gift never reached its handing over (a slow look) proves nothing: another.
        for item in items:
            t = out_of_sight(actor, start, item)
            tries.append(t)
            if t["performing"] and (not graph or any("lost sight of them" in r["text"] for r in t["lines"])):
                break
        snaps[f"sight_{name}"] = tries
        started = [t for t in tries if t["performing"]]
        check(f"out of sight, {name}: a gift started (performing)", started, [t["performing"] for t in tries])
        check(f"out of sight, {name}: exactly one line for each gift", all(len(t["lines"]) == 1 for t in started),
              [[r["text"] for r in t["lines"]] for t in tries])
        texts = [r["text"] for t in started for r in t["lines"]]
        check(f"out of sight, {name}: each line says what happened", all("lost sight of them" in x or "they moved away" in x for x in texts), texts)
        if graph:
            check(f"out of sight, {name}: the leaf's look told it at least once (\"lost sight of them\")", any("lost sight of them" in x for x in texts), texts)
    lost = [r["text"] for name in ("the player's command", "the AI's graph") for t in snaps[f"sight_{name}"] for r in t["lines"] if "lost sight of them" in r["text"]]
    check("out of sight: the player's line is the AI's (item aside)", len({x.split(" → ")[1] for x in lost}) == 1 and len(lost) >= 2, lost)
    snaps["sight_played"] = played(me)
    check("out of sight: the person still plays the character (no takeover)", not snaps["sight_played"]["character_ai"], snaps["sight_played"])

    out = V.run_dir(a.run) / "told.json"
    out.write_text(json.dumps({"results": results, "snapshots": snaps}, indent=2) + "\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
