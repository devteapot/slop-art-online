#!/usr/bin/env python3
"""Player kin, courting offers, and community views (`my_kin`, `my_bond_offers`, `my_community`).

Two players (Wren and Moss) stand near each other, with a third bystander player (Fern) and an
anonymous client.
1. Wren makes a courting offer (`conceive`) to Moss: Wren reads it outgoing in `my_bond_offers`,
   Moss reads it incoming, Fern and anonymous read none; `bond_offer` stays private.
2. With a short-gestation script overlay (reinstalled to the tree's script in `finally`), Moss
   accepts (`conceive` toward Wren): the offer leaves `my_bond_offers`, an infant is born with
   both parents, and `my_kin` shows the child (`relation: "child"`) and the other parent
   (`relation: "partner"`) to both Wren and Moss, nothing to Fern or anonymous, and no name/hp/
   alive column.
3. Wren founds a community (`found`): Wren reads it in `my_community` (`founder`, `name`,
   `since_ms`), Moss, Fern and anonymous read none; `community` and `membership` stay private.

    kin.py --run RUN

Needs `verify.py launch --run RUN` (any seed); joins a player if the run has none.
Writes `RUN/kin.json`. Python standard library only.
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
SKILLS = (HERE.parents[3] / "living/scripts/skills.rhai").read_text()
FAST_BIRTH = '''
fn life_years_law() { #{ about: "Short gestation for kin verification.", cadence: "compile" } }
fn life_years(t) { if t.kind == "person" { t.gestation = 0.000001; } t }
'''


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
    t2, other = mint_join(p, "Moss")
    t3, third = mint_join(p, "Fern")

    # Place Wren and Moss beside each other; hold all three still.
    for who in (me, other, third):
        p.call("set_behavior", [who, json.dumps({"wait": 120})], "admin")
    p.call("place_near", [other, me], "admin")
    time.sleep(1.0)

    installed_fast = False
    try:
        # 1. Courting offer: Wren -> Moss.
        since = now_ms()
        code, body = p.act({"do": "conceive", "target": {"id": other}})
        check(p, "Wren's conceive act is accepted", code == 200, f"{code} {body[:120]}")
        mine_bo = wait_for(lambda: p.sql("SELECT * FROM my_bond_offers", "player"), 12) or []
        theirs_bo, _ = sql_as(p, "SELECT * FROM my_bond_offers", t2)
        third_bo, _ = sql_as(p, "SELECT * FROM my_bond_offers", t3)
        anon_bo, _ = sql_as(p, "SELECT * FROM my_bond_offers", None)
        check(p, "Wren reads its courting offer as outgoing in my_bond_offers",
              len(mine_bo) == 1 and mine_bo[0]["incoming"] is False and mine_bo[0]["from"] == me and mine_bo[0]["to"] == other and mine_bo[0]["at_ms"] >= since - 2000,
              f"{mine_bo}")
        check(p, "Moss reads Wren's courting offer as incoming in my_bond_offers",
              theirs_bo and len(theirs_bo) == 1 and theirs_bo[0]["incoming"] is True and theirs_bo[0]["from"] == me and theirs_bo[0]["to"] == other,
              f"{theirs_bo}")
        check(p, "my_bond_offers carries ids only, no name column",
              mine_bo and not any(k in mine_bo[0] for k in ("name", "label", "from_name")), f"columns {sorted(mine_bo[0]) if mine_bo else []}")
        check(p, "third player and anonymous see no bond offers", third_bo == [] and (anon_bo == [] or anon_bo is None), f"third={third_bo} anon={anon_bo}")
        for who, tok in (("player", p.st["token"]), ("anonymous", None)):
            rows, err = sql_as(p, "SELECT * FROM bond_offer", tok)
            check(p, f"bond_offer is private to {who}", rows is None or rows == [], f"{err or rows}")

        # 2. Family relation via real birth: install short gestation, Moss accepts, wait for birth.
        code, body = p.call("install_script", [SKILLS + FAST_BIRTH], "admin")
        installed_fast = code == 200
        check(p, "short-gestation overlay installs for birth fixture", installed_fast, f"{code} {body[:120]}")
        code, body = V.http(f"/v1/database/{p.db}/call/human_act", [json.dumps({"do": "conceive", "target": {"id": me}})], t2)
        V.log(p.st, f"call human_act[conceive] as Moss -> {code} {body.strip()}", sys.stderr)
        gone = wait_for(lambda: not p.sql("SELECT * FROM my_bond_offers", "player"), 12)
        check(p, "accepted courting offer leaves my_bond_offers", bool(gone), f"{p.sql('SELECT * FROM my_bond_offers', 'player')}")
        child_rows = wait_for(lambda: p.sql(f"SELECT id, parent_a, parent_b FROM character WHERE parent_a = {me} AND parent_b = {other}"), 30)
        child_id = child_rows[0]["id"] if child_rows else None
        check(p, "birth creates a child with both parents",
              child_id is not None and {child_rows[0]["parent_a"], child_rows[0]["parent_b"]} == {me, other}, f"{child_rows}")

        kin1 = p.sql("SELECT * FROM my_kin", "player")
        kin2, _ = sql_as(p, "SELECT * FROM my_kin", t2)
        kin3, _ = sql_as(p, "SELECT * FROM my_kin", t3)
        kin_anon, _ = sql_as(p, "SELECT * FROM my_kin", None)
        pairs1 = {(r["id"], r["relation"]) for r in kin1}
        pairs2 = {(r["id"], r["relation"]) for r in (kin2 or [])}
        check(p, "Wren's my_kin lists Moss as partner and the newborn as child",
              pairs1 == {(other, "partner"), (child_id, "child")}, f"{kin1}")
        check(p, "Moss's my_kin lists Wren as partner and the newborn as child",
              pairs2 == {(me, "partner"), (child_id, "child")}, f"{kin2}")
        check(p, "my_kin carries only id and relation (no alive, hp or position)",
              kin1 and all(set(r.keys()) == {"id", "relation"} for r in kin1), f"{kin1}")
        check(p, "third player and anonymous see no kin rows",
              kin3 == [] and (kin_anon == [] or kin_anon is None), f"third={kin3} anon={kin_anon}")

        # 3. Community membership: Wren founds a community.
        code, body = p.act({"do": "found", "text": "HearthKin"})
        check(p, "Wren's found act is accepted", code == 200, f"{code} {body[:120]}")
        com1 = wait_for(lambda: p.sql("SELECT * FROM my_community", "player"), 12) or []
        com2, _ = sql_as(p, "SELECT * FROM my_community", t2)
        com3, _ = sql_as(p, "SELECT * FROM my_community", t3)
        com_anon, _ = sql_as(p, "SELECT * FROM my_community", None)
        check(p, "Wren reads its founded community in my_community",
              len(com1) == 1 and com1[0]["name"] == "HearthKin" and com1[0]["founder"] == me and com1[0]["since_ms"] > 0,
              f"{com1}")
        check(p, "other players and anonymous see no community row",
              com2 == [] and com3 == [] and (com_anon == [] or com_anon is None), f"moss={com2} fern={com3} anon={com_anon}")
        for tbl in ("community", "membership"):
            for who, tok in (("player", p.st["token"]), ("anonymous", None)):
                rows, err = sql_as(p, f"SELECT * FROM {tbl}", tok)
                check(p, f"{tbl} is private to {who}", rows is None or rows == [], f"{err or rows}")
    finally:
        if installed_fast:
            code, _ = p.call("install_script", [SKILLS], "admin")
            check(p, "the tree's script is installed again", code == 200, f"{code}")

    (V.run_dir(p.st["run"]) / "kin.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
