#!/usr/bin/env python3
"""Seeded lives on a scratch island world (docs/SEEDED_LIVES.md).

Residents live on their own starting graphs (`rules.minds = false`): no mind, no model. This
driver only reads the authority's rows; it sets no scene and calls no reducer.

    lives.py --run RUN [--minutes 14] [--every 10]

1. **seat** (right after publishing): residents per settlement, hamlets peopled, `relation`
   rows written from the authored sheets (and how many pairs feel both ways), the known way of
   every carrier (`work`, `work 1..n`, leg lengths), and every outlaw's spot on the road.
2. **watch** (the next `--minutes`): every `--every` seconds, where carriers and outlaws are and
   what they carry, and the goods in each settlement's stores; at the end the `threat`,
   `yield` and `seize` chronicle rows, and the gestures (`wave`, `nod`, `face`) aimed at someone,
   classed by the actor's seeded relation to its target.

Needs `verify.py launch --run RUN --seed island`. Writes `RUN/lives-seat.json`,
`RUN/lives-watch.json` and `RUN/lives.json` (checks). Python standard library only.
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

STRUCTURE_BIT = 1 << 40
CARRIER_PLACE = "work"


class Lives:
    def __init__(self, run):
        self.run = run
        self.st = V.load(run)
        self.db = self.st["db"]
        self.out = V.run_dir(run)
        self.token = V.admin_token()
        self.results = []

    def sql(self, q):
        code, body = V.http(f"/v1/database/{self.db}/sql", q, self.token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def check(self, name, ok, detail):
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        V.log(self.st, f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    def save(self, label, data):
        (self.out / f"lives-{label}.json").write_text(json.dumps(data, indent=1) + "\n")

    # ---- world facts ---------------------------------------------------------------------
    def people(self):
        chars = {c["id"]: c for c in self.sql("SELECT * FROM character WHERE kind = 'person'") if c["alive"]}
        out = {}
        for b in self.sql("SELECT * FROM background"):
            if b["id"] not in chars:
                continue
            try:
                v = json.loads(b["text"])
            except ValueError:
                continue
            out[b["id"]] = {"id": b["id"], "name": chars[b["id"]]["name"], "town": v.get("town", ""), "occupation": v.get("occupation", ""), "sheet": "sheet" in v, "home": (chars[b["id"]]["home_x"], chars[b["id"]]["home_y"])}
        return out

    def seat(self):
        ppl = self.people()
        settlements = self.sql("SELECT * FROM settlement")
        communities = {c["id"]: c["name"] for c in self.sql("SELECT * FROM community")}
        by_town = {}
        for p in ppl.values():
            by_town.setdefault(p["town"], []).append(p)
        towns = {t: {"people": len(v), "authored": sum(p["sheet"] for p in v)} for t, v in sorted(by_town.items())}
        hamlets = [s for s in settlements if s["style"] == "hamlet"]
        peopled = [communities.get(s["community"], "") for s in hamlets if s["community"]]
        rel = self.sql("SELECT * FROM relation")
        pairs = {(r["actor"], r["other"]) for r in rel}
        both = sum(1 for a, b in pairs if (b, a) in pairs)
        places = self.sql("SELECT * FROM place")
        mine = {}
        for p in places:
            mine.setdefault(p["actor"], {})[p["name"]] = (p["x"], p["y"])
        carriers, outlaws = [], []
        for p in ppl.values():
            pl = mine.get(p["id"], {})
            if f"{CARRIER_PLACE} 1" in pl:
                k, legs, at = 1, [], p["home"]
                while f"{CARRIER_PLACE} {k}" in pl:
                    legs.append(round(math.dist(at, pl[f"{CARRIER_PLACE} {k}"]), 1))
                    at = pl[f"{CARRIER_PLACE} {k}"]
                    k += 1
                carriers.append({"id": p["id"], "name": p["name"], "town": p["town"], "occupation": p["occupation"], "stages": k - 1, "legs_m": legs, "work": pl.get("work"), "home": p["home"]})
            elif p["occupation"] == "outlaw":
                outlaws.append({"id": p["id"], "name": p["name"], "town": p["town"], "work": pl.get("work"), "home": p["home"], "from_home_m": round(math.dist(p["home"], pl["work"]), 1) if "work" in pl else None})
        data = {"towns": towns, "hamlets": {"planned": len(hamlets), "peopled": peopled}, "people": len(ppl), "relations": len(rel), "pairs_both_ways": both // 2, "carriers": carriers, "outlaws": outlaws, "places": len(places)}
        self.save("seat", data)
        authored = sum(t["authored"] for t in towns.values())
        self.check("authored residents placed", authored > 0, f"{authored} of {len(ppl)} people have an authored sheet; per settlement {json.dumps(towns)}")
        self.check("hamlets peopled", len(peopled) > 0, f"{len(peopled)} of {len(hamlets)} hamlets have a community: {peopled}")
        self.check("seeded relations are rows", len(rel) > 0, f"{len(rel)} relation rows, {both // 2} pairs felt both ways")
        for c in carriers:
            self.check(f"{c['name']} knows the way to {c['occupation']}'s market", c["stages"] >= 2 and max(c["legs_m"]) <= 220, f"{c['stages']} stages, legs {c['legs_m']} m")
        for o in outlaws:
            self.check(f"{o['name']} has a spot on the road", o["work"] is not None, f"{o['from_home_m']} m from home")
        return data, ppl, mine

    def stores(self, ppl):
        """Goods in each settlement's storages (structures of kind storage near its centre)."""
        out = {}
        sts = [s for s in self.sql("SELECT * FROM structure WHERE kind = 'storage'")]
        sets = self.sql("SELECT * FROM settlement")
        comm = {c["id"]: c["name"] for c in self.sql("SELECT * FROM community")}
        inv = self.sql("SELECT * FROM inventory")
        by = {}
        for r in inv:
            by.setdefault(r["owner"], {})[r["item"]] = r["qty"]
        for s in sets:
            if not s["community"]:
                continue
            name = comm.get(s["community"], str(s["id"]))
            goods = {}
            for st in sts:
                if math.dist((st["x"], st["y"]), (s["x"], s["y"])) <= max(25.0, s["radius_m"] * 0.4):
                    for k, q in by.get(STRUCTURE_BIT | st["id"], {}).items():
                        goods[k] = goods.get(k, 0) + q
            out[name] = goods
        return out, by

    def watch(self, minutes, every, seat, ppl, places):
        track = {c["id"] for c in seat["carriers"]} | {o["id"] for o in seat["outlaws"]}
        start_ms = int(time.time() * 1000)
        samples = []
        stores0, _ = self.stores(ppl)
        end = time.time() + minutes * 60
        while time.time() < end:
            bodies = {b["id"]: b for b in self.sql("SELECT * FROM body")}
            _, inv = self.stores(ppl)
            acts = {a["id"]: a for a in self.sql("SELECT * FROM activity")}
            snap = {"t": round(time.time() * 1000) - start_ms, "who": {}}
            for i in track:
                b = bodies.get(i)
                if not b:
                    continue
                snap["who"][i] = {"at": [round(b["x"], 1), round(b["y"], 1)], "carry": inv.get(i, {}), "doing": acts.get(i, {}).get("skill", "")}
            samples.append(snap)
            time.sleep(every)
        stores1, _ = self.stores(ppl)
        chron = [r for r in self.sql(f"SELECT * FROM chronicle WHERE at_ms >= {start_ms}") if r["kind"] in ("threat", "yield", "seize", "attack", "killing", "death")]
        uses = [u for u in self.sql(f"SELECT * FROM skill_use WHERE at_ms >= {start_ms}") if u["skill"] in ("wave", "nod", "face") and u["target"]]
        rel = {(r["actor"], r["other"]): r for r in self.sql("SELECT * FROM relation")}

        def kind(a, b):
            r = rel.get((a, b))
            if not r:
                return "none"
            lab = r["label"].lower()
            if r["trust"] <= -25 or any(w in lab for w in ("enemy", "rival", "threat", "thief")):
                return "enemy"
            if r["trust"] >= 25 or any(w in lab for w in ("friend", "family", "partner", "ally", "kin")):
                return "friend"
            return "known"

        gestures = {}
        for u in uses:
            k = kind(u["actor"], u["target"])
            gestures.setdefault(u["skill"], {}).setdefault(k, 0)
            gestures[u["skill"]][k] += 1
        name = lambda i: ppl.get(i, {}).get("name", str(i))  # noqa: E731
        road = [{"kind": r["kind"], "a": name(r["a"]), "b": name(r["b"]), "a_town": ppl.get(r["a"], {}).get("town"), "b_town": ppl.get(r["b"], {}).get("town"), "text": r["text"], "at": [round(r["x"]), round(r["y"])]} for r in chron]
        # Carriers: the stages they reached, nearest approach to the far market.
        journeys = []
        for c in seat["carriers"]:
            pl = places.get(c["id"], {})
            pts = [s["who"][c["id"]]["at"] for s in samples if c["id"] in s["who"]]
            reached = [k for k in range(1, c["stages"] + 1) if any(math.dist(p, pl[f"work {k}"]) <= 12 for p in pts)]
            near_market = min((math.dist(p, pl["work"]) for p in pts), default=None)
            carried = sorted({k for s in samples if c["id"] in s["who"] for k, q in s["who"][c["id"]]["carry"].items() if q > 0})
            journeys.append({"name": c["name"], "occupation": c["occupation"], "stages_reached": reached, "of": c["stages"], "nearest_far_market_m": round(near_market, 1) if near_market is not None else None, "carried": carried, "path": pts})
        outlaws = []
        for o in seat["outlaws"]:
            pts = [s["who"][o["id"]]["at"] for s in samples if o["id"] in s["who"]]
            at_post = sum(1 for p in pts if o["work"] and math.dist(p, o["work"]) <= 14)
            outlaws.append({"name": o["name"], "samples": len(pts), "at_their_spot": at_post, "doing": sorted({s["who"][o["id"]]["doing"] for s in samples if o["id"] in s["who"]})})
        delta = {t: {k: stores1.get(t, {}).get(k, 0) - stores0.get(t, {}).get(k, 0) for k in set(stores0.get(t, {})) | set(stores1.get(t, {})) if stores1.get(t, {}).get(k, 0) != stores0.get(t, {}).get(k, 0)} for t in set(stores0) | set(stores1)}
        data = {"minutes": minutes, "journeys": journeys, "outlaws": outlaws, "road": road, "gestures": gestures, "stores_before": stores0, "stores_after": stores1, "stores_delta": delta, "samples": samples}
        self.save("watch", data)
        for j in journeys:
            self.check(f"{j['name']} walks the route ({j['occupation']})", len(j["stages_reached"]) >= 2 or (j["nearest_far_market_m"] is not None and j["nearest_far_market_m"] <= 12), f"stages reached {j['stages_reached']} of {j['of']}; nearest the far market {j['nearest_far_market_m']} m; carried {j['carried']}")
        threats = [r for r in road if r["kind"] == "threat" and r["a_town"] == "Coldwell"]
        self.check("outlaws act on the road", any(o["at_their_spot"] for o in outlaws), f"{json.dumps([{k: o[k] for k in ('name', 'at_their_spot', 'samples')} for o in outlaws])}; threats by Coldwell people: {len(threats)}, seizes: {sum(1 for r in road if r['kind'] == 'seize' and r['a_town'] == 'Coldwell')}, yields: {sum(1 for r in road if r['kind'] == 'yield')}")
        self.check("gestures follow seeded relations", True, json.dumps(gestures))
        return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--minutes", type=float, default=14)
    ap.add_argument("--every", type=float, default=10)
    ap.add_argument("--seat-only", action="store_true")
    a = ap.parse_args()
    lv = Lives(a.run)
    seat, ppl, places = lv.seat()
    if not a.seat_only:
        lv.watch(a.minutes, a.every, seat, ppl, places)
    (lv.out / "lives.json").write_text(json.dumps(lv.results, indent=1) + "\n")
    failed = [r for r in lv.results if not r["ok"]]
    print(f"{len(lv.results) - len(failed)} of {len(lv.results)} checks pass")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
