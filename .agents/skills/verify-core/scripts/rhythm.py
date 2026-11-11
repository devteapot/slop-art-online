#!/usr/bin/env python3
"""Personal rhythms and Cullet's trades on a scratch world (docs/SEEDED_LIVES.md, docs/CULLET_RULES.md).

    rhythm.py seed --run RUN            # writes RUN/cullet-rhythm.json; launch with --seed RUN/cullet-rhythm
    rhythm.py drive --run RUN           # about 15 minutes

The seed is `living/seeds/cullet.json` (its plan, laws, starting ways and town life) with eight of
its residents as `author_world.py` compiled them (their sheets, and the rhythm and places of
`cast.json`; without residents in the seed, `compile_residents` without sheets), on a 12-minute day (Cullet's own is 48)
so one game day passes in the scene. A few goods are added to their packs, the scene's own and
not the cast's: peat for the stokers, ash and sand for the blower, roots for the baker, and food
for everyone (the seed has no stores yet, so hunger would otherwise send them foraging).

Who and why:
- Thessaly Marl, stoker: rises 14:00, works the night watch 22:00-06:00 (a rising after noon).
- Fenn Brandt, stoker, and Corvin Hollin, blower: the day watch at the Cone, 06:00-14:00.
- Pieter Achterberg, baker: up 02:30, bakes until 10:00, a second sleep 13:00-19:00.
- Anselm Faro, lamp keeper: rises 13:00, works 19:30-06:00.
- Tobiah Dunmore (16, stoker) and Col Roon (15): adults under Cullet's life law (a child until 15).
- Halvard Dunmore (70): an elder, alive (old age from 75).

The driver places a furnace beside Fenn at the Cone once he is there (the plan places none yet)
and watches, at the world's own hours: rows (`rhythm`, `routine`, `place`), what each does and
where, and the furnace's `lit_until_ms`. No mind service runs: people live on their starting
graphs. Writes `RUN/rhythm.json` (checks) and `RUN/rhythm-samples.jsonl`. Standard library only.
"""

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("town", HERE / "town.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
V = T.V

PEOPLE = ["Thessaly Marl", "Fenn Brandt", "Corvin Hollin", "Pieter Achterberg", "Anselm Faro", "Tobiah Dunmore", "Col Roon", "Halvard Dunmore"]
# The scene's own goods (Cullet's seed has no stores yet, and the cast's packs no food): a watch's
# peat for each stoker (a furnace burns 3 units a game hour), melt for the blower, and food for
# everyone so that hunger does not send them foraging (a person carries at most 40 things).
FOOD = {"baked_roots": 6}
PACKS = {"Thessaly Marl": {"peat": 25}, "Fenn Brandt": {"peat": 25}, "Tobiah Dunmore": {"peat": 12}, "Corvin Hollin": {"ash": 4, "sand": 8}, "Pieter Achterberg": {"roots": 6, "peat": 6}}


def make_seed(run):
    sys.path.insert(0, str(ROOT / "living/tools"))
    import author_world as aw

    wd = ROOT / "living/seeds/worlds/cullet"
    cast = json.loads((wd / "cast.json").read_text())
    town = aw.compile_residents(wd, cast, None, [])[0]
    seed = json.loads((ROOT / "living/seeds/cullet.json").read_text())
    # Cullet's own compiled residents (with their sheets) once the seed has them, else the cast
    # compiled without sheets; both carry the cast's rhythm and places.
    compiled = seed["towns"][0].get("residents") or town["residents"]
    residents = [json.loads(json.dumps(r)) for r in compiled if r["name"] in PEOPLE]
    for r in residents:
        r["parents"] = [p for p in r["parents"] if p in PEOPLE]
        for k, v in (FOOD | PACKS.get(r["name"], {})).items():
            r["inventory"][k] = r["inventory"].get(k, 0) + v
    houses = {r["household"] for r in residents}
    t = seed["towns"][0]
    t["residents"] = residents
    t["homes"] = {k: v for k, v in town["homes"].items() if k in houses}
    seed["run"] = "cullet-rhythm"
    seed["day_minutes"] = 12
    seed["setting"] = "A scene world: Cullet's plan, laws and ways with eight of its cast on a 12-minute day (verify-core rhythm.py)."
    out = V.run_dir(run) / "cullet-rhythm.json"
    out.write_text(json.dumps(seed, indent=1, ensure_ascii=False) + "\n")
    print(out)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Scene(T.Town):
    def sample(self, log):
        ppl = self.people()
        by = {p["name"]: p for p in ppl.values()}
        f = self.sql("SELECT id, x, y, lit_until_ms FROM structure WHERE kind = 'furnace'")
        row = {"ms": self.now_ms(), "hour": round(self.hour(), 2), "furnace": f[0] if f else None,
               "people": {n: {"at": [round(p["at"][0], 1), round(p["at"][1], 1)], "skill": p["skill"], "stage": p["stage"],
                              "home_m": round(dist(p["at"], p["home"]), 1),
                              "work_m": round(dist(p["at"], p["places"]["work"]), 1) if "work" in p["places"] else None} for n, p in by.items()}}
        log.write(json.dumps(row) + "\n")
        log.flush()
        return row


def window(s, log, lo, hi, every=4.0):
    """Samples while the world's hour is in [lo, hi)."""
    s.wait_hour(lo, hi)
    rows = []
    while True:
        h = s.hour()
        if not (lo <= h < hi if lo < hi else (h >= lo or h < hi)):
            return rows
        rows.append(s.sample(log))
        time.sleep(every)


def share(rows, name, pred):
    xs = [pred(r["people"][name]) for r in rows if name in r["people"]]
    return (sum(xs) / len(xs) if xs else 0.0), len(xs)


def drive(run):
    s = Scene(run)
    out = V.run_dir(run)
    log = (out / "rhythm-samples.jsonl").open("a")
    ids = {c["name"]: c["id"] for c in s.sql("SELECT id, name FROM character WHERE kind = 'person'")}
    s.check("the scene's residents are in the world", all(n in ids for n in PEOPLE), sorted(ids))
    rh = {r["id"]: r for r in s.sql("SELECT * FROM rhythm")}
    r = {n: rh.get(ids.get(n)) for n in PEOPLE}
    (out / "rhythm-rows.json").write_text(json.dumps(r, indent=1) + "\n")
    th, pi, an = r["Thessaly Marl"], r["Pieter Achterberg"], r["Anselm Faro"]
    s.check("a night worker's rhythm rises after noon", th and (th["rise_h"], th["bed_h"], th["work_from_h"], th["work_to_h"]) == (14.0, 31.0, 22.0, 30.0), th)
    s.check("the lamp keeper rises at 13:00 and works 19:30-06:00", an and (an["rise_h"], an["bed_h"], an["work_from_h"], an["work_to_h"]) == (13.0, 30.0, 19.5, 30.0), an)
    s.check("the baker has a second sleep 13:00-19:00", pi and (pi["rise_h"], pi["bed_h"], pi["nap_from_h"], pi["nap_to_h"]) == (2.5, 22.0, 13.0, 19.0), pi)
    stages = {c["name"]: c["stage"] for c in s.sql("SELECT name, stage FROM character")}
    s.check("Cullet's childhood ends at 15: Tobiah (16) and Col (15) are adults", stages.get("Tobiah Dunmore") == 2 and stages.get("Col Roon") == 2, stages)
    s.check("Halvard (70) is an elder", stages.get("Halvard Dunmore") == 3, stages)
    routines = {}
    for x in s.sql("SELECT actor, name FROM routine"):
        routines.setdefault(x["actor"], []).append(x["name"])
    s.check("stokers and the blower start with their trade's routine", "stoke the cone" in routines.get(ids["Fenn Brandt"], []) and "stoke the cone" in routines.get(ids["Thessaly Marl"], []) and "blow glass" in routines.get(ids["Corvin Hollin"], []),
            {n: routines.get(ids.get(n)) for n in ("Fenn Brandt", "Thessaly Marl", "Corvin Hollin", "Pieter Achterberg")})
    places = {p["name"]: (p["x"], p["y"]) for p in s.sql(f"SELECT name, x, y FROM place WHERE actor = {ids['Fenn Brandt']}")}
    s.check("the stoker knows a workplace (his cast's lot:cone)", "work" in places, {"places": places})

    # Morning: the day watch works at the Cone; the night stoker sleeps at home.
    window(s, log, 8.0, 9.0)
    fenn = ids["Fenn Brandt"]
    if not s.sql("SELECT id FROM structure WHERE kind = 'furnace'"):
        s.call("place_structure", [fenn, "furnace"])
    morning = window(s, log, 9.0, 13.5)
    at_cone, n = share(morning, "Fenn Brandt", lambda p: p["work_m"] is not None and p["work_m"] < 8)
    s.check("the day stoker is at the Cone in his hours (09:00-13:30)", at_cone >= 0.6, {"share": round(at_cone, 2), "samples": n})
    fed = [r for r in morning if r["furnace"] and r["furnace"]["lit_until_ms"] > r["ms"]]
    s.check("the furnace is fed and burns in the day watch", len(fed) >= 0.5 * max(1, len(morning)), {"lit_samples": len(fed), "samples": len(morning)})
    skills = {p["skill"] for r in morning for nm, p in r["people"].items() if nm in ("Fenn Brandt", "Corvin Hollin")}
    s.check("the day watch feeds the furnace and makes glass", "feed" in skills and "make" in skills, sorted(skills))
    asleep, n = share(morning, "Thessaly Marl", lambda p: p["skill"] == "sleep" and p["home_m"] < 4)
    s.check("the night stoker is asleep at home in the morning", asleep >= 0.6, {"share": round(asleep, 2), "samples": n})

    # Afternoon: the night stoker is up (not at work, not asleep); the baker sleeps again.
    noon = window(s, log, 15.0, 18.5)
    up, n = share(noon, "Thessaly Marl", lambda p: p["skill"] != "sleep")
    s.check("the night stoker rises in the afternoon (15:00-18:30 awake)", up >= 0.8, {"share": round(up, 2), "samples": n})
    off, _ = share(noon, "Thessaly Marl", lambda p: p["skill"] not in ("feed", "keep"))
    s.check("she is not at her work before her watch", off >= 0.7, {"share": round(off, 2)})
    nap, n = share(noon, "Pieter Achterberg", lambda p: p["skill"] == "sleep")
    s.check("the baker sleeps a second time in the afternoon", nap >= 0.5, {"share": round(nap, 2), "samples": n})

    # Night: the night stoker works the Cone; the day stoker sleeps.
    night = window(s, log, 23.0, 4.0)
    at_cone, n = share(night, "Thessaly Marl", lambda p: p["work_m"] is not None and p["work_m"] < 8)
    s.check("the night stoker works at the Cone 23:00-04:00", at_cone >= 0.6, {"share": round(at_cone, 2), "samples": n})
    feeds = sum(1 for r in night if r["people"].get("Thessaly Marl", {}).get("skill") == "feed")
    burn = [r for r in night if r["furnace"] and r["furnace"]["lit_until_ms"] > r["ms"]]
    s.check("she keeps the furnace burning through the night", len(burn) >= 0.6 * max(1, len(night)) and feeds >= 1, {"feed_samples": feeds, "lit_samples": len(burn), "samples": len(night)})
    asleep, n = share(night, "Fenn Brandt", lambda p: p["skill"] == "sleep" and p["home_m"] < 4)
    s.check("the day stoker sleeps at home at night", asleep >= 0.6, {"share": round(asleep, 2), "samples": n})
    lamp, n = share(night, "Anselm Faro", lambda p: p["work_m"] is not None and p["work_m"] < 8)
    s.check("the lamp keeper is at the Watchglass at night", lamp >= 0.5, {"share": round(lamp, 2), "samples": n})
    alive = {c["name"] for c in s.sql("SELECT name, alive FROM character") if c["alive"]}
    s.check("nobody died of old age (Halvard, 70, lives on)", set(PEOPLE) <= alive, sorted(set(PEOPLE) - alive))
    (out / "rhythm.json").write_text(json.dumps(s.results, indent=1) + "\n")
    bad = [x for x in s.results if not x["ok"]]
    print(f"{len(s.results) - len(bad)} of {len(s.results)} pass")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["seed", "drive"])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    if not a.run.startswith("core-"):
        sys.exit("run names start with core-")
    if a.what == "seed":
        make_seed(a.run)
        return 0
    return drive(a.run)


if __name__ == "__main__":
    sys.exit(main())
