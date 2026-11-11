#!/usr/bin/env python3
"""Hospitality on a scratch island world (docs/TOWN_LIFE.md, "Layer 2", `host`).

A resident whose household owns a store takes the player in as a guest through the ordinary
skill path (its behaviour graph runs the `host` skill; admin `set_behavior` and `place_at`
set the scene and are named in the report). The player perceives it, learns its `lodging`
place, and its stay is a private `guest` row until the morning hour the rules name. Taking
from that household's store is seen by onlookers as taking from someone's store before the
stay, and not during it. The player's own `host` goes through `human_act` and is refused
without a house; hosting oneself is refused by the rules. `guest` is private.

    host.py --run RUN

Needs `verify.py launch --run RUN --seed island`; joins a player if the run has none.
Writes `RUN/host.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import re
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
RULES = (HERE.parents[3] / "living/scripts/skills.rhai").read_text()
UNTIL_HOUR = float(re.search(r'op:\s*"host",\s*until_hour:\s*([0-9.]+)', RULES).group(1))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def took_lines(p, since):
    """Onlookers' perceptions of someone taking from a store that is not theirs (every
    resident has a mind, so they are its experiences)."""
    rows = [r for r in p.sql("SELECT text, at_ms FROM experience") if r["at_ms"] >= since]
    return [r["text"] for r in rows if "'s storage" in r["text"] and " took " in r["text"]]


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
    mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not mine:
        p.call("join", ["Wren"])
        mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = mine[0]["id"]
    p.call("set_weather", [False, 3600], "admin")

    # The player has no house: its own `host` is refused by the engine, and hosting itself by the rules.
    since = now_ms()
    p.act({"do": "host", "target": "self"})
    told = wait_for(lambda: [t for t in p.told(me, since) if "own guest" in t], 5)
    check(p, "taking oneself in is refused by the rules", told, f"{told}")

    # A household that owns a stocked store, and an adult of it.
    people = {c["id"]: c for c in p.sql("SELECT id, name, home_x, home_y, alive, stage, ai FROM character WHERE kind = 'person'")}
    stores = p.sql("SELECT id, x, y, owner FROM structure WHERE kind = 'storage'")
    held = {}
    for r in p.sql("SELECT owner, item, qty FROM inventory"):
        held.setdefault(r["owner"], {})[r["item"]] = r["qty"]
    bit = 1 << 40
    pick = None
    for s in stores:
        o = people.get(s["owner"])
        stock = {k: v for k, v in held.get(bit | s["id"], {}).items() if v > 0}
        if not o or not stock:
            continue
        home = (o["home_x"], o["home_y"])
        house = [h for h in p.sql("SELECT id, x, y FROM structure WHERE kind = 'house'") if dist((h["x"], h["y"]), home) <= 1.5]
        hosts = [c for c in people.values() if c["alive"] and c["stage"] == 2 and (c["home_x"], c["home_y"]) == home]
        if house and hosts:
            pick = (s, sorted(stock)[0], hosts[0], house[0])
            break
    if not pick:
        check(p, "a household with a house and a stocked store of its own", False, f"{len(stores)} storages")
        return finish(p)
    store, item, host, house = pick
    check(p, "a household with a house and a stocked store of its own", True,
          f"host {host['name']} (#{host['id']}), store #{store['id']} ({item}), house #{house['id']}")

    # Before the stay: taking from that store is seen as taking from someone's store.
    p.call("place_at", [me, store["x"] + 1.0, store["y"]], "admin")
    time.sleep(1.0)
    since = now_ms()
    p.act({"do": "take", "target": {"nearest": "storage"}, "item": item, "qty": 1})
    before = wait_for(lambda: took_lines(p, since), 8)
    check(p, "before the stay, onlookers see the newcomer take from the household's store", before, f"{before[:2]}")

    # The resident takes the player in, through its graph (the ordinary skill path).
    hx, hy = next((b["x"], b["y"]) for b in p.sql(f"SELECT x, y FROM body WHERE id = {host['id']}"))
    p.call("place_at", [me, hx + 1.5, hy + 0.5], "admin")
    time.sleep(0.8)
    since = now_ms()
    p.call("set_behavior", [host["id"], json.dumps({"seq": [{"do": "host", "target": {"id": me}}, {"wait": 600}]})], "admin")
    row = wait_for(lambda: [g for g in p.sql(f"SELECT * FROM guest WHERE guest = {me}")], 12)
    check(p, "the resident's `host` makes the player its household's guest (a private guest row)", row and row[0]["host"] == host["id"] and row[0]["house"] == house["id"], f"{row}")
    told = [t for t in p.told(me, since) if "takes you in as their guest" in t]
    check(p, "the player perceives it as an experience", told, f"{told}")
    lodging = [pl for pl in p.sql("SELECT * FROM my_places", "player") if pl["name"] == "lodging"]
    check(p, "the player learns where its bed is (`lodging` in my_places, at the house)", lodging and dist((lodging[0]["x"], lodging[0]["y"]), (house["x"], house["y"])) < 0.5, f"{lodging}")
    if row:
        w = p.sql("SELECT day_ms, epoch_ms FROM world")[0]
        hour_ms = w["day_ms"] / 24
        # As living_rules::hour_of: the world starts at 07:00.
        hour = ((row[0]["since_ms"] - w["epoch_ms"] + w["day_ms"] * 7 // 24) % w["day_ms"]) / hour_ms
        ahead = (UNTIL_HOUR - hour) % 24
        want = row[0]["since_ms"] + ahead * hour_ms
        check(p, "the stay lasts until the morning hour the rules name", abs(row[0]["until_ms"] - want) < 2 * hour_ms / 60,
              f"until_hour {UNTIL_HOUR}: ends {(row[0]['until_ms'] - row[0]['since_ms']) / 1000:.0f} s after it began")
    chron = [c for c in p.sql("SELECT kind, a, b, text FROM chronicle") if c["kind"] == "host" and c["b"] == me]
    check(p, "the chronicle records it", chron, f"{chron[-1:]}")

    # During the stay: taking from the household's store is not seen as theft.
    p.call("place_at", [me, store["x"] + 1.0, store["y"]], "admin")
    time.sleep(1.0)
    since = now_ms()
    code, _ = p.act({"do": "take", "target": {"nearest": "storage"}, "item": item, "qty": 1})
    took = wait_for(lambda: [t for t in p.told(me, since) if "took 1" in t], 6)
    time.sleep(2)
    during = took_lines(p, since)
    check(p, "a guest takes from the household's store and nobody sees theft", took and not during, f"{took}; onlookers {during}")

    # Private.
    for who in ("player", "anonymous"):
        token = p.st["token"] if who == "player" else None
        code, body = V.http(f"/v1/database/{p.db}/sql", "SELECT * FROM guest", token, raw=True)
        check(p, f"guest is private to {who}", code != 200 or not json.loads(body)[-1]["rows"], f"{code} {body.strip()[:100]}")
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "host.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
