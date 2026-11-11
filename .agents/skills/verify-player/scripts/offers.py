#!/usr/bin/env python3
"""Trade offers a player receives and accepts (`my_offers`, docs/PERCEPTION.md "Offers").

A scene walker (an AI resident, acting through admin `mind_act` as a mind would) offers the
player 2 wood for 1 hide (a newcomer carries berries, never hide). The player reads it in
`my_offers` (incoming, from the walker,
`until_ms` the law's window after `at_ms`) and is told of it in `my_experience`. A second
player makes its own offer to the walker and reads it in its `my_offers` as outgoing; neither
player sees the other's offer, and an anonymous client sees none. The player's `accept`
without the hide is refused with the rules' words and leaves the offer standing; with
them, the goods move both ways and the row goes. `trade_offer` stays private.

    offers.py --run RUN

Needs `verify.py launch --run RUN` (any seed); joins a player if the run has none.
Writes `RUN/offers.json`. Python standard library only. Expiry past the 180 s window is not
waited for (housekeeping drops an offer within a second of `until_ms`; read, not run).
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


def sql_as(p, q, token):
    code, body = V.http(f"/v1/database/{p.db}/sql", q, token, raw=True)
    if code != 200:
        return None, f"{code} {body.strip()[:160]}"
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]], ""


def inv(p, owner, item):
    return sum(r["qty"] for r in p.sql(f"SELECT item, qty FROM inventory WHERE owner = {owner}") if r["item"] == item)


def mine(p, words, since):
    return [e for e in p.sql("SELECT kind, text, at_ms FROM my_experience", "player") if e["at_ms"] >= since and words.lower() in e["text"].lower()]


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
    # A second player (its token only in memory).
    code, body = V.http("/v1/identity", {})
    t2 = json.loads(body)["token"]
    code, body = V.http(f"/v1/database/{p.db}/call/join", ["Moss"], t2)
    V.log(p.st, f"call join[\"Moss\"] as second player -> {code} {body.strip()}", sys.stderr)
    rows, _ = sql_as(p, "SELECT id, alive FROM my_characters", t2)
    other = next(c["id"] for c in rows if c["alive"])

    before = {c["id"] for c in p.sql("SELECT id FROM character")}
    p.call("spawn_crowd", [1, True], "admin")
    walker = next(c["id"] for c in p.sql("SELECT id FROM character") if c["id"] not in before)
    for who in (walker, me, other):
        p.call("set_behavior", [who, json.dumps({"wait": 120})], "admin")
    p.call("place_near", [walker, me], "admin")
    p.call("place_near", [other, me], "admin")
    p.call("grant_items", [walker, "wood", 4], "admin")
    p.call("grant_items", [other, "berries", 2], "admin")
    time.sleep(1.0)
    law = p.sql("SELECT name, value FROM world_law")
    window_ms = int(float(next((w["value"] for w in law if w["name"] == "trade_window_s"), 180)) * 1000)

    # The resident offers the player 2 wood for 1 hide (the newcomer's kit has berries, not hide).
    since = now_ms()
    p.call("mind_act", [walker, [json.dumps({"do": "offer", "target": {"id": me}, "item": "wood", "qty": 2, "want": "hide", "want_qty": 1})], "verify-player"], "admin")
    got = wait_for(lambda: p.sql("SELECT * FROM my_offers", "player"), 12)
    o = got[0] if got else {}
    check(p, "the player reads the resident's offer in my_offers", len(got) == 1 and o.get("incoming") is True and o.get("from") == walker and o.get("to") == me
          and (o.get("give_item"), o.get("give_qty"), o.get("want_item"), o.get("want_qty")) == ("wood", 2, "hide", 1), f"{got}")
    check(p, "until_ms is the law's window after at_ms", o and o["until_ms"] - o["at_ms"] == window_ms and o["at_ms"] >= since - 2000, f"window {window_ms} ms: {o}")
    check(p, "the row names no one: ids, no name column", o and not any(k in o for k in ("name", "label", "from_name")), f"columns {sorted(o)}")
    told = wait_for(lambda: mine(p, "offers you 2 wood for 1 hide", since), 8)
    check(p, "the player is told of the offer in my_experience", told, f"{[e['text'] for e in told]}")

    # The second player offers the walker 1 berries for 1 wood: its own row, outgoing.
    code, body = V.http(f"/v1/database/{p.db}/call/human_act", [json.dumps({"do": "offer", "target": {"id": walker}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 1})], t2)
    V.log(p.st, f"call human_act[offer] as second player -> {code} {body.strip()}", sys.stderr)
    out = wait_for(lambda: sql_as(p, "SELECT * FROM my_offers", t2)[0], 12) or []
    check(p, "the second player reads its own offer as outgoing", len(out) == 1 and out[0]["incoming"] is False and out[0]["from"] == other and out[0]["to"] == walker, f"{out}")
    first = p.sql("SELECT * FROM my_offers", "player")
    check(p, "neither player sees the other's offer", [r["id"] for r in first] == [o.get("id")] and o.get("id") not in [r["id"] for r in out], f"player: {first}; second: {out}")
    anon, err = sql_as(p, "SELECT * FROM my_offers", None)
    check(p, "an anonymous client gets no offers", anon == [] or anon is None, f"{anon} {err}")
    for who, token in (("player", p.st["token"]), ("anonymous", None)):
        rows, err = sql_as(p, "SELECT * FROM trade_offer", token)
        check(p, f"trade_offer is private to {who}", rows is None or rows == [], f"{err or rows}")
    owner = p.sql("SELECT * FROM trade_offer")
    check(p, "the authority holds both offers (owner's read)", {(r["from"], r["to"]) for r in owner} >= {(walker, me), (other, walker)} and all(r["until_ms"] > 0 for r in owner), f"{owner}")

    # Accepting without the hide is refused with the rules' words; the offer stands.
    since = now_ms()
    code, body = p.act({"do": "accept", "target": {"id": walker}})
    refused = wait_for(lambda: mine(p, "you don't have 1 hide", since), 10)
    check(p, "accept without the goods is refused and told", code == 200 and refused, f"{code} {[e['text'] for e in refused]}")
    check(p, "the refused accept leaves the offer standing", [r["id"] for r in p.sql("SELECT * FROM my_offers", "player")] == [o.get("id")], "")

    # With the hide the trade goes through the ordinary accept path.
    p.call("grant_items", [me, "hide", 1], "admin")
    w0, b0, ww0, wb0 = inv(p, me, "wood"), inv(p, me, "hide"), inv(p, walker, "wood"), inv(p, walker, "hide")
    since = now_ms()
    code, body = p.act({"do": "accept", "target": {"id": walker}})
    gone = wait_for(lambda: not p.sql("SELECT * FROM my_offers", "player"), 10)
    w1, b1, ww1, wb1 = inv(p, me, "wood"), inv(p, me, "hide"), inv(p, walker, "wood"), inv(p, walker, "hide")
    check(p, "accept moves the goods both ways", code == 200 and (w1 - w0, b1 - b0, ww1 - ww0, wb1 - wb0) == (2, -1, -2, 1), f"player wood {w0}->{w1} hide {b0}->{b1}; walker wood {ww0}->{ww1} hide {wb0}->{wb1}")
    check(p, "the accepted offer leaves my_offers", gone, f"{p.sql('SELECT * FROM my_offers', 'player')}")
    mine_inv = {r["item"]: r["qty"] for r in p.sql("SELECT item, qty FROM my_inventory", "player")}
    check(p, "my_inventory shows the wood", mine_inv.get("wood", 0) == w1, f"{mine_inv}")
    traded = wait_for(lambda: mine(p, "traded with", since), 8)
    check(p, "the player's outcome names the trade", traded, f"{[e['text'] for e in traded]}")
    out = sql_as(p, "SELECT * FROM my_offers", t2)[0] or []
    check(p, "the second player's offer is untouched", len(out) == 1 and out[0]["incoming"] is False, f"{out}")

    (V.run_dir(p.st["run"]) / "offers.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
