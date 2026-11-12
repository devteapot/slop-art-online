#!/usr/bin/env python3
"""A Cullet world at a lab pace for verify-ui's `looks-band` (features/looks.md): people's look
bands change within a minute of genesis, so a connected client sees real key changes.

    looks_seed.py RUN        writes .local/living/verify/RUN/cullet-pace.json and prints the launch

Cullet's seed (its laws, looks and residents unchanged) with `year_days` 1 and `life_pace`
20/2880: on its 48-minute day a year is 20 real seconds. Then Benedikt Orme (59) is an elder at
59.5 years, about 10 s after genesis; Zeke Okoro (11) is a youth at 12, about 20 s; Magda Tarn
(58) about 30 s; Tilly Dunlin (10) about 40 s; Oswin Greave (57) about 50 s; Ife Okoro (9) about
60 s. Launch it straight away and drive as soon as it is up: `check.py --run RUN looks-band`.
Everyone ages a year every 20 s, so the world is for this one scenario.
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../.."))
DAY_S = 48 * 60
YEAR_S = 20.0
PACE = YEAR_S / DAY_S
CHANGERS = ["Benedikt Orme", "Zeke Okoro", "Magda Tarn", "Tilly Dunlin", "Oswin Greave", "Ife Okoro"]

if __name__ == "__main__":
    run = sys.argv[1]
    seed = json.load(open(os.path.join(ROOT, "living/seeds/cullet.json")))
    assert seed.get("day_minutes") == 48, "the pace assumes Cullet's 48-minute day"
    seed["year_days"] = 1
    seed["life_pace"] = PACE
    names = {r["name"] for t in seed["towns"] for r in t["residents"]}
    missing = [n for n in CHANGERS if n not in names]
    assert not missing, f"not in Cullet's seed: {missing}"
    out = os.path.join(ROOT, ".local/living/verify", run)
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "cullet-pace.json")
    json.dump(seed, open(path, "w"), indent=1)
    print(f"wrote {path}\nlaunch: .agents/skills/verify/scripts/verify.py launch --run {run} --seed {path[:-5]} --target-dir .local/living/verify/{run}/target")
