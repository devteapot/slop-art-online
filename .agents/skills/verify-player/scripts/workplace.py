#!/usr/bin/env python3
"""A player makes glass at a furnace that burns fuel, as an AI character would: refused while
it is out and while it holds too little fuel, with the rules' reasons in the player's own log;
made once it is fed, drawing one unit of the furnace's fuel; and seen working while it lasts
(`make_shows`, `feed_shows`: a `doing` row at the furnace). docs/WORLD_RULES.md, "Goods,
recipes and fuel" and "What a client shows (goods-2)".

The authority has no list of offered acts: a client runs the rules' `_check` on facts it
builds. This proves the authority's side: the same `human_act` a client sends is checked on
the authority's facts of the furnace (`lit`, `fuel` from `structure.lit_until_ms`).

    workplace.py --run RUN

Needs `verify.py launch --run RUN --seed cullet-laws` (Cullet's laws: its goods and a 48-minute
day, so a unit of the furnace's fuel lasts 40 s). Admin reducers set the scene only:
`grant_know_how` (fire, glassmaking), `grant_items` (ash, sand, peat) and `place_structure`
(the furnace). Writes `RUN/workplace.json`. Python standard library only.
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

    def wait_for(pred, seconds, every=0.5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v = pred()
            if v:
                return v
            time.sleep(every)
        return pred()

    def now():
        return sql("SELECT last_ms FROM clock", admin)[0]["last_ms"]

    def pack():
        out = {}
        for r in sql("SELECT item, qty FROM my_inventory", st["token"]):
            out[r["item"]] = out.get(r["item"], 0) + r["qty"]
        return out

    def told(words, since):
        return [r["text"] for r in sql("SELECT kind, text, at_ms FROM my_experience", st["token"]) if r["at_ms"] >= since and words in r["text"]]

    def act(skill, item, qty=1):
        node = {"do": {"skill": skill, "item": item, "qty": qty, "target": {"nearest": "furnace"}}}
        return call("human_act", [json.dumps(node)])

    world = sql("SELECT day_ms FROM world", admin)[0]
    unit_ms = world["day_ms"] / 24 / 3.0
    check("a world with Cullet's day (a unit of the furnace's fuel lasts 40 s)", abs(unit_ms - 40_000) < 1, world)

    live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    if not live:
        call("join", ["Glazier"])
        live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    me = live[0]["id"]
    for t in ("fire", "glassmaking"):
        call("grant_know_how", [me, t], as_admin=True)
    for item, n in (("ash", 1), ("sand", 2), ("peat", 6)):
        call("grant_items", [me, item, n], as_admin=True)
    call("place_structure", [me, "furnace"], as_admin=True)
    furnace = max((r for r in sql(f"SELECT * FROM structure WHERE owner = {me}", admin) if r["kind"] == "furnace"), key=lambda r: r["id"])
    fid = furnace["id"]

    def fire():
        return sql(f"SELECT id, kind, x, y, lit_until_ms FROM structure WHERE id = {fid}", admin)[0]

    snaps["furnace_placed"] = furnace
    check("the placed furnace starts out", furnace["lit_until_ms"] == 0, furnace)
    cards = {r["skill"]: r["code"] for r in sql("SELECT skill, code FROM act_card", st["token"])}
    snaps["act_cards"] = cards
    check("make and feed have act cards a client reads", "make" in cards and "feed" in cards, cards)
    before = pack()
    snaps["pack_before"] = before

    # 1. Out: refused with the rules' reason; nothing taken.
    t0 = now()
    code, body = act("make", "glass")
    check("human_act make glass is accepted by the reducer", code == 200, body.strip()[:200])
    got = wait_for(lambda: told("is out: feed it first", t0), 20)
    snaps["refused_out"] = got
    check("making glass at an out furnace is refused: 'is out: feed it first'", got, told("", t0))
    check("nothing is taken from the pack", pack() == before, pack())

    # 2. Fed one unit: lit, but a unit is already burning down, so glass (1 unit) is refused.
    t0 = now()
    act("feed", "peat", 1)
    seen = wait_for(lambda: [r for r in sql(f"SELECT * FROM doing WHERE id = {me}", admin) if r["code"] == cards.get("feed")], 10, every=0.05)
    snaps["doing_feed"] = seen
    check("feeding the furnace is seen while it lasts (doing at the furnace)", seen and abs(seen[0]["x"] - furnace["x"]) < 0.01 and abs(seen[0]["y"] - furnace["y"]) < 0.01, seen)
    lit = wait_for(lambda: fire()["lit_until_ms"] > 0 and fire(), 20)
    snaps["furnace_fed_one"] = lit
    check("one peat lights it for one unit (40 s)", lit and abs(lit["lit_until_ms"] - t0 - unit_ms) < 6000, {"furnace": lit, "fed_after": t0})
    t0 = now()
    act("make", "glass")
    got = wait_for(lambda: told("too little fuel left", t0), 20)
    snaps["refused_short"] = got
    check("glass at a furnace holding less than a unit is refused: 'too little fuel left'", got, told("", t0))
    check("nothing is taken from the pack", {k: v for k, v in pack().items() if k != "peat"} == {k: v for k, v in before.items() if k != "peat"}, pack())

    # 3. Fed three more: glass is made, drawing one unit; seen at work while it lasts.
    act("feed", "peat", 3)
    wait_for(lambda: pack().get("peat", 0) == 2, 20)
    fed = fire()
    snaps["furnace_fed_four"] = fed
    t0 = now()
    act("make", "glass")
    work = wait_for(lambda: [r for r in sql(f"SELECT * FROM doing WHERE id = {me}", admin) if r["code"] == cards.get("make")], 20)
    snaps["doing_make"] = work
    check("making glass is seen at the furnace while it lasts (doing)", work and abs(work[0]["x"] - furnace["x"]) < 0.01 and abs(work[0]["y"] - furnace["y"]) < 0.01, work)
    made = wait_for(lambda: pack().get("glass", 0) == 1, 60)
    after, inv = fire(), pack()
    snaps["furnace_after"], snaps["pack_after"] = after, inv
    check("glass is made from one ash and two sand", made and inv.get("ash", 0) == 0 and inv.get("sand", 0) == 0, inv)
    check("the glass drew one unit of the furnace's fuel (40 s of its burn)", abs((fed["lit_until_ms"] - after["lit_until_ms"]) - unit_ms) < 1500, {"before": fed["lit_until_ms"], "after": after["lit_until_ms"], "unit_ms": unit_ms})
    done = told("glass", t0)
    snaps["told_made"] = done
    check("the player is told the outcome in its own log", any("You did what you had decided" in t for t in done), done)
    check("the doing row is gone once the work is done", not sql(f"SELECT * FROM doing WHERE id = {me}", admin) or sql(f"SELECT * FROM doing WHERE id = {me}", admin)[0]["code"] != cards.get("make"), None)

    out = V.run_dir(a.run) / "workplace.json"
    out.write_text(json.dumps({"results": results, "snapshots": snaps}, indent=2) + "\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
