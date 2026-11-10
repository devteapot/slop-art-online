#!/usr/bin/env python3
"""A player's agreement and a demand on them (docs/WORLD_RULES.md).

The player proposes terms to a scene walker with the node the client's verbs build
(`offer_terms`: 1 berries for 2 wood), the walker accepts and delivers (admin `mind_act`, as a
mind would), the player is told what it owes and pays with `human_act` give; the agreement is
kept and the player is told so. The player reads the record through `my_records` and its
experiences through `my_experience`; `record` and `record_party` are private. Then the walker
demands a berry of the player, who does not pay: when the demand falls due the player is told
it did not pay. The world's own rules run, with no short-hours overlay.

    deal.py --run RUN

Needs `verify.py launch --run RUN` (any seed); joins a player if the run has none.
Writes `RUN/deal.json`. Python standard library only.
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


def mine(p, words, since, kind=None):
    """What the player reads of its own experiences (its view), since a time."""
    return [e for e in p.sql("SELECT kind, text, at_ms FROM my_experience", "player")
            if e["at_ms"] >= since and words.lower() in e["text"].lower() and (kind is None or e["kind"] == kind)]


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
    p.call("set_behavior", [walker, json.dumps({"wait": 120})], "admin")
    p.call("place_near", [walker, me], "admin")
    p.call("grant_items", [me, "berries", 3], "admin")
    p.call("grant_items", [walker, "wood", 4], "admin")
    p.call("set_behavior", [me, json.dumps({"wait": 120})], "admin")
    time.sleep(1.0)

    # The player proposes terms with the node the client's verbs build for this choice.
    since = now_ms()
    node = {"do": "offer_terms", "target": {"id": walker}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 2}
    code, body = p.act(node)
    check(p, "human_act takes the verbs' offer_terms node", code == 200, f"{code} {body[:120]}")
    proposed = wait_for(lambda: mine(p, "proposed to", since, "act"), 10)
    check(p, "the player's outcome is the rules' own words", proposed, f"{[e['text'] for e in proposed]}")
    rec = wait_for(lambda: [r for r in p.sql("SELECT * FROM my_records", "player") if r["kind"] == "agreement"], 8)
    check(p, "the player reads its offered agreement through my_records", rec and rec[0]["status"] == "offered" and rec[0]["role"] == "from" and f"to={walker}" in rec[0]["others"], f"{rec}")

    # The walker accepts and delivers, as a mind would decide it.
    p.call("mind_act", [walker, [json.dumps({"do": "accept", "target": {"id": me}})], "verify-player"], "admin")
    told = wait_for(lambda: mine(p, "accepted your terms", since, "record"), 10)
    check(p, "the player is told its terms were accepted", told, f"{[e['text'] for e in told]}")
    p.call("mind_act", [walker, [json.dumps({"do": "give", "target": {"id": me}, "item": "wood", "qty": 2})], "verify-player"], "admin")
    owed = wait_for(lambda: mine(p, "You owe them 1 berries", since, "record"), 12)
    check(p, "the player is told the other side delivered and what it owes", owed, f"{[e['text'] for e in owed]}")

    # The player pays through the ordinary act path.
    p.act({"do": "give", "target": {"id": walker}, "item": "berries", "qty": 1})
    kept = wait_for(lambda: mine(p, "kept on both sides", since), 12)
    check(p, "paying keeps the agreement, and the player is told", kept, f"{[e['text'] for e in kept]}")
    rec = [r for r in p.sql("SELECT * FROM my_records", "player") if r["kind"] == "agreement"]
    check(p, "my_records shows it kept", rec and rec[0]["status"] == "kept" and not rec[0]["open"], f"{rec}")

    # Records are private: the player and an anonymous client read none directly.
    for table in ("record", "record_party"):
        for who in ("player", "anonymous"):
            token = p.st["token"] if who == "player" else None
            code, body = V.http(f"/v1/database/{p.db}/sql", f"SELECT * FROM {table}", token, raw=True)
            check(p, f"{table} is private to {who}", code != 200 or not json.loads(body)[-1]["rows"], f"{code} {body.strip()[:100]}")

    # A demand on the player, not paid: refusing is not an act, and the player is told when it falls due.
    since = now_ms()
    p.call("mind_act", [walker, [json.dumps({"do": "demand", "target": {"id": me}, "item": "berries", "qty": 1, "text": "for the road"})], "verify-player"], "admin")
    demanded = wait_for(lambda: mine(p, "demands 1 berries of you", since, "record"), 10)
    check(p, "the player is told of a demand on it", demanded, f"{[e['text'] for e in demanded]}")
    w = p.sql("SELECT day_ms FROM world")[0]
    due_s = 3 * w["day_ms"] / 24000 + 15
    unpaid = wait_for(lambda: mine(p, "You did not pay", since, "record"), due_s)
    check(p, "not paid, it falls due and the player is told", unpaid, f"{[e['text'] for e in unpaid]} (waited up to {due_s:.0f} s)")
    (V.run_dir(p.st["run"]) / "deal.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
