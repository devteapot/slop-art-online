#!/usr/bin/env python3
"""A player answers what was asked of it by its id: accept or decline a trade offer
(`"offer": id` from `my_offers`) or a proposal of terms (`"record": id` from `my_records`),
through `human_act` (docs/WORLD_RULES.md, "Answering").

A scene walker (an AI resident, acting through admin `mind_act` as a mind would) proposes terms
to the player and offers it a trade. The player:

- accepts the trade by its id although terms stand (an accept without a name would take the
  terms): the goods move, the terms stay offered;
- accepts that offer again by the same id: refused ("that offer is gone"), told in
  `my_experience`;
- declines the walker's next offer by its id: the row leaves `my_offers`, and the walker is told
  "declined your offer of …" (kind `record`, owner's read of its experience);
- declines the terms by the record id from `my_records`: the record reads `declined`, and the
  walker is told "declined your terms: …".

    answers.py --run RUN

Needs `verify.py launch --run RUN` (any seed); joins a player if the run has none.
Writes `RUN/answers.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gesture", HERE / "gesture.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
V = G.V
RESULTS = G.RESULTS
check, wait_for, now_ms = G.check, G.wait_for, G.now_ms


def inv(p, owner, item):
    return sum(r["qty"] for r in p.sql(f"SELECT item, qty FROM inventory WHERE owner = {owner}") if r["item"] == item)


def mine(p, words, since):
    return [e for e in p.sql("SELECT kind, text, at_ms FROM my_experience", "player") if e["at_ms"] >= since and words.lower() in e["text"].lower()]


def told(p, who, words, since, kind="record"):
    return [e for e in p.sql(f"SELECT kind, text, at_ms FROM experience WHERE observer = {who}") if e["at_ms"] >= since and e["kind"] == kind and words in e["text"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = G.P(a.run)
    if not p.st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        p.st["token"], p.st["identity"] = j["token"], j["identity"]
        V.save(p.st)
    alive = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not alive:
        p.call("join", ["Wren"])
        alive = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = alive[0]["id"]
    before = {c["id"] for c in p.sql("SELECT id FROM character")}
    p.call("spawn_crowd", [1, True], "admin")
    walker = next(c["id"] for c in p.sql("SELECT id FROM character") if c["id"] not in before)
    for who in (walker, me):
        p.call("set_behavior", [who, json.dumps({"wait": 120})], "admin")
    p.call("place_near", [walker, me], "admin")
    p.call("grant_items", [walker, "wood", 6], "admin")
    p.call("grant_items", [me, "berries", 4], "admin")
    time.sleep(1.0)

    def walker_acts(node):
        p.call("mind_act", [walker, [json.dumps(node)], "verify-player"], "admin")

    # Terms first, then a trade: both stand for the player.
    walker_acts({"do": "offer_terms", "target": {"id": me}, "item": "wood", "qty": 3, "want": "berries", "want_qty": 2})
    rec = wait_for(lambda: [r for r in p.sql("SELECT * FROM my_records", "player") if r["kind"] == "agreement" and r["status"] == "offered"], 12)
    walker_acts({"do": "offer", "target": {"id": me}, "item": "wood", "qty": 2, "want": "berries", "want_qty": 1})
    offers = wait_for(lambda: p.sql("SELECT * FROM my_offers", "player"), 12)
    check(p, "the player reads the terms in my_records and the trade in my_offers", rec and offers and offers[0]["incoming"], f"{rec} {offers}")
    rid, oid = rec[0]["id"], offers[0]["id"]

    # Accept the trade by its id: it, not the terms, is taken.
    w0, b0 = inv(p, me, "wood"), inv(p, me, "berries")
    since = now_ms()
    code, body = p.act({"do": "accept", "target": {"id": walker}, "offer": oid})
    gone = wait_for(lambda: not p.sql("SELECT * FROM my_offers", "player"), 12)
    w1, b1 = inv(p, me, "wood"), inv(p, me, "berries")
    still = [r for r in p.sql("SELECT * FROM my_records", "player") if r["id"] == rid]
    check(p, "accept with the offer's id takes that trade", code == 200 and gone and (w1 - w0, b1 - b0) == (2, -1), f"wood {w0}->{w1} berries {b0}->{b1}")
    check(p, "the terms the player did not name still stand", still and still[0]["status"] == "offered", f"{still}")

    # The same id again: refused, told.
    since = now_ms()
    code, body = p.act({"do": "accept", "target": {"id": walker}, "offer": oid})
    refused = wait_for(lambda: mine(p, "that offer is gone", since), 12)
    check(p, "a stale offer id is refused with the reason", code == 200 and refused, f"{code} {[e['text'] for e in refused]}")

    # Decline the next offer by its id.
    walker_acts({"do": "offer", "target": {"id": me}, "item": "wood", "qty": 1, "want": "berries", "want_qty": 3})
    nxt = wait_for(lambda: p.sql("SELECT * FROM my_offers", "player"), 12)
    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": walker}, "offer": nxt[0]["id"] if nxt else 0})
    ended = wait_for(lambda: not p.sql("SELECT * FROM my_offers", "player"), 12)
    heard = wait_for(lambda: told(p, walker, "declined your offer of 1 wood for 3 berries.", since), 12)
    check(p, "decline by id ends the offer", code == 200 and nxt and ended, f"{nxt}")
    check(p, "the walker is told the player declined (kind record)", heard, f"{heard}")
    outcome = wait_for(lambda: mine(p, "declined", since), 8)
    check(p, "the player's outcome says it declined", outcome, f"{[e['text'] for e in outcome]}")

    # Decline the terms by the record id.
    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": walker}, "record": rid})
    closed = wait_for(lambda: [r for r in p.sql("SELECT * FROM my_records", "player") if r["id"] == rid and r["status"] == "declined"], 12)
    heard = wait_for(lambda: told(p, walker, "declined your terms: you give 3 wood, they give 2 berries.", since), 12)
    check(p, "decline by record id closes the proposal as declined (my_records)", code == 200 and closed and not closed[0]["open"], f"{closed}")
    check(p, "the walker is told its terms were declined", heard, f"{heard}")

    (V.run_dir(p.st["run"]) / "answers.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
