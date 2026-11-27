#!/usr/bin/env python3
"""A human player declines an incoming bond (courting / family) offer and withdraws their own
through `human_act` (`decline` with `"bond": id` from `my_bond_offers`, and unnamed).

1. A scene walker (AI adult, via admin `mind_act`) offers to start a family (`conceive`) with
   player Wren. Wren reads the incoming offer in `my_bond_offers`, declines it by `bond` id
   via `human_act`, the row leaves `my_bond_offers`, the walker is told
   "declined your offer to start a family." (`kind = "record"`), and Wren's `my_experience`
   records the outcome. Retrying the same id is refused ("that offer is gone").
2. Wren offers to start a family (`conceive`) with second player Moss. Both read the offer in
   `my_bond_offers` (outgoing for Wren, incoming for Moss) and Moss perceives it in
   `my_experience`. A third player Fern trying to decline/withdraw it by id is refused
   ("that offer is not yours") and the offer stays. Wren withdraws it by `bond` id via
   `human_act`: the row leaves `my_bond_offers` for both, Moss is told
   "withdrew their offer to start a family." in `my_experience`, and Wren gets its outcome.
3. Wren offers to Moss again and withdraws unnamed (`{"do": "decline", "target": {"id": moss}}`):
   the row goes and Moss is told.

    bond_decline.py --run RUN

Needs `verify.py launch --run RUN` (any seed). Writes `RUN/bond_decline.json`.
"""

import argparse
import importlib.util
import json
import math
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


def mint_join(p, name):
    _, body = V.http("/v1/identity", {})
    tok = json.loads(body)["token"]
    code, body = V.http(f"/v1/database/{p.db}/call/join", [name], tok)
    V.log(p.st, f"call join[{name!r}] -> {code} {body.strip()}", sys.stderr)
    rows, _ = sql_as(p, "SELECT id, alive FROM my_characters", tok)
    cid = next(c["id"] for c in rows if c["alive"])
    return tok, cid


def act_as(p, node, token):
    code, body = V.http(f"/v1/database/{p.db}/call/human_act", [json.dumps(node)], token)
    V.log(p.st, f"call human_act[{node}] -> {code} {body.strip()}", sys.stderr)
    return code, body


def exp_as(p, token, words, since, kind=None):
    rows, _ = sql_as(p, "SELECT kind, text, at_ms FROM my_experience", token)
    return [
        e for e in (rows or [])
        if e["at_ms"] >= since
        and (kind is None or e["kind"] == kind)
        and words.lower() in e["text"].lower()
    ]


def told_owner(p, who, words, since, kind="record"):
    return [
        e for e in p.sql(f"SELECT kind, text, at_ms FROM experience WHERE observer = {who}")
        if e["at_ms"] >= since and e["kind"] == kind and words in e["text"]
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = G.P(a.run)
    if not p.st.get("token"):
        _, body = V.http("/v1/identity", {})
        j = json.loads(body)
        p.st["token"], p.st["identity"] = j["token"], j["identity"]
        V.save(p.st)
    alive = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not alive:
        p.call("join", ["Wren"])
        alive = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = alive[0]["id"]
    t2, moss = mint_join(p, "Moss")
    t3, fern = mint_join(p, "Fern")

    before = {c["id"] for c in p.sql("SELECT id FROM character")}
    p.call("spawn_crowd", [1, True], "admin")
    walker = next(c["id"] for c in p.sql("SELECT id FROM character") if c["id"] not in before)

    for who in (me, moss, fern, walker):
        p.call("set_behavior", [who, json.dumps({"wait": 120})], "admin")
    for who in (moss, fern, walker):
        p.call("place_near", [who, me], "admin")
    time.sleep(1.0)

    # 1. Walker offers bond to Wren; Wren declines by bond id.
    p.call("mind_act", [walker, [json.dumps({"do": "conceive", "target": {"id": me}})], "verify-player"], "admin")
    incoming = wait_for(lambda: [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["incoming"] and o["from"] == walker], 15)
    check(p, "Wren sees walker's incoming bond offer in my_bond_offers", bool(incoming), f"{incoming}")
    bid = incoming[0]["id"] if incoming else 0

    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": walker}, "bond": bid})
    gone = wait_for(lambda: not [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["id"] == bid], 15)
    heard = wait_for(lambda: told_owner(p, walker, "declined your offer to start a family.", since), 15)
    outcome = wait_for(lambda: exp_as(p, p.st["token"], "offer to start a family", since, "act"), 15)
    check(p, "player decline by bond id removes the offer from my_bond_offers", code == 200 and bool(gone), f"{code} {body[:120]}")
    check(p, "walker (maker) is told player declined (kind record)", bool(heard), f"{heard}")
    check(p, "player's my_experience records the decline outcome", bool(outcome), f"{outcome}")

    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": walker}, "bond": bid})
    refused = wait_for(lambda: exp_as(p, p.st["token"], "that offer is gone", since), 15)
    check(p, "re-declining a gone bond offer is refused truthfully", code == 200 and bool(refused), f"{refused}")

    # 2. Wren offers bond to Moss; Fern cannot withdraw it; Wren withdraws by bond id.
    since_offer = now_ms()
    code, body = p.act({"do": "conceive", "target": {"id": moss}})
    mine_bo = wait_for(lambda: [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if not o["incoming"] and o["to"] == moss], 15)
    moss_bo = wait_for(lambda: [o for o in (sql_as(p, "SELECT * FROM my_bond_offers", t2)[0] or []) if o["incoming"] and o["from"] == me], 15)
    moss_saw = wait_for(lambda: exp_as(p, t2, "wants to start a family with you", since_offer, "family"), 15)
    check(p, "Wren offers bond to Moss and Moss perceives it", code == 200 and bool(mine_bo) and bool(moss_bo) and bool(moss_saw), f"mine={mine_bo} moss={moss_bo}")
    bid2 = mine_bo[0]["id"] if mine_bo else 0

    since = now_ms()
    act_as(p, {"do": "decline", "target": {"id": me}, "bond": bid2}, t3)
    fern_ref = wait_for(lambda: exp_as(p, t3, "that offer is not yours", since), 15)
    still = [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["id"] == bid2]
    check(p, "third player Fern cannot withdraw Wren's bond offer", bool(fern_ref) and bool(still), f"ref={fern_ref} still={still}")

    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": moss}, "bond": bid2})
    gone_wren = wait_for(lambda: not [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["id"] == bid2], 15)
    gone_moss = wait_for(lambda: not [o for o in (sql_as(p, "SELECT * FROM my_bond_offers", t2)[0] or []) if o["id"] == bid2], 15)
    moss_told = wait_for(lambda: exp_as(p, t2, "withdrew their offer to start a family.", since, "record"), 15)
    wren_out = wait_for(lambda: exp_as(p, p.st["token"], "withdrew your offer to start a family", since, "act"), 15)
    check(p, "player withdraw by bond id deletes offer for both sides", code == 200 and bool(gone_wren) and bool(gone_moss), f"{code} {body[:120]}")
    check(p, "receiver Moss is told in my_experience it was withdrawn", bool(moss_told), f"{moss_told}")
    wren_outs, _ = sql_as(p, "SELECT * FROM my_act_outcomes", p.st["token"])
    wren_o = [o for o in (wren_outs or []) if o["at_ms"] >= since and o["ok"]]
    check(p, "maker Wren's outcome carries withdraw label (not decline)",
          bool(wren_out) and "withdraw → person" in wren_out[-1]["text"] and "decline →" not in wren_out[-1]["text"]
          and bool(wren_o) and wren_o[-1]["what"].startswith("withdraw"),
          f"line={wren_out} row={wren_o}")

    # 3. Wren offers bond to Moss again and withdraws unnamed.
    p.act({"do": "conceive", "target": {"id": moss}})
    mine_bo2 = wait_for(lambda: [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if not o["incoming"] and o["to"] == moss], 15)
    bid3 = mine_bo2[0]["id"] if mine_bo2 else 0
    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": moss}})
    gone_u = wait_for(lambda: not [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["id"] == bid3], 15)
    moss_told2 = wait_for(lambda: exp_as(p, t2, "withdrew their offer to start a family.", since, "record"), 15)
    check(p, "unnamed decline withdraws player's own bond offer and tells Moss",
          code == 200 and bool(mine_bo2) and bool(gone_u) and bool(moss_told2), f"{moss_told2}")

    # 4. Out-of-sight withdraw for a player (unnamed and by id) works without sight or approach;
    #    declining an out-of-sight incoming offer is refused cleanly without raw `#id`.
    wren_pos = [(r["x"], r["y"]) for r in p.sql(f"SELECT x, y FROM body WHERE id = {me}")][0]
    bodies = [(r["x"], r["y"]) for r in p.sql("SELECT id, x, y FROM body") if r["id"] not in (me, moss, fern, walker)]
    far_x, far_y = next((pt for pt in bodies if math.dist(pt, wren_pos) > 50.0), (wren_pos[0] + 60.0, wren_pos[1]))
    p.act({"do": "conceive", "target": {"id": moss}})
    mine_far = wait_for(lambda: [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if not o["incoming"] and o["to"] == moss], 15)
    bid_far = mine_far[0]["id"] if mine_far else 0
    p.call("place_at", [moss, far_x, far_y], "admin")
    time.sleep(1.0)
    since = now_ms()
    code, body = p.act({"do": "decline", "target": {"id": moss}})
    gone_far = wait_for(lambda: not [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["id"] == bid_far], 15)
    moss_far_told = wait_for(lambda: exp_as(p, t2, "withdrew their offer to start a family.", since, "record"), 15)
    wren_far_out = wait_for(lambda: exp_as(p, p.st["token"], "withdrew your offer to start a family", since, "act"), 15)
    wren_pos_after = [(r["x"], r["y"]) for r in p.sql(f"SELECT x, y FROM body WHERE id = {me}")][0]
    check(p, "player out-of-sight unnamed withdraw deletes offer, tells Moss, does not walk, labelled withdraw",
          code == 200 and bool(mine_far) and bool(gone_far) and bool(moss_far_told)
          and bool(wren_far_out) and "withdraw → person" in wren_far_out[-1]["text"]
          and math.dist(wren_pos, wren_pos_after) < 1.0,
          f"out={wren_far_out} moss={moss_far_told} moved={math.dist(wren_pos, wren_pos_after):.2f}")

    p.call("place_near", [walker, me], "admin")
    time.sleep(0.8)
    p.call("mind_act", [walker, [json.dumps({"do": "conceive", "target": {"id": me}})], "verify-player"], "admin")
    inc_far = wait_for(lambda: [o for o in p.sql("SELECT * FROM my_bond_offers", "player") if o["incoming"] and o["from"] == walker], 15)
    p.call("place_at", [walker, far_x, far_y], "admin")
    time.sleep(1.0)
    since = now_ms()
    p.act({"do": "decline", "target": {"id": walker}})
    unseen_rows = wait_for(lambda: [o for o in (sql_as(p, "SELECT * FROM my_act_outcomes", p.st["token"])[0] or []) if o["at_ms"] >= since and not o["ok"]], 15)
    unseen_row = unseen_rows[-1] if unseen_rows else None
    check(p, "player declining out-of-sight incoming offer is refused as unseen without raw #id",
          bool(inc_far) and unseen_row is not None and unseen_row["code"] == "unseen"
          and unseen_row["why"] == "a stranger is not in sight" and "#" not in unseen_row["why"],
          f"{unseen_row}")

    (V.run_dir(p.st["run"]) / "bond_decline.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
