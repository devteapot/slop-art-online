#!/usr/bin/env python3
"""What winter does to Cullet's food, from the plan's and the laws' own numbers.

Food in and food out per game day across the year for Cullet's 64 residents and about 10
players, under the old rule (nothing regrows in winter) and under Cullet's winter shares
(`winter_regrowth()` in living/seeds/worlds/cullet/laws.rhai). Prints markdown tables for
docs/CULLET_RULES.md ("Winter"). No model calls, no server: it reads

- the plan (living/seeds/worlds/cullet/plan.json): every food node's max, regrowth a game
  hour and pool (a fishing ground's spots share one stock), the Store's and the households'
  stores;
- Cullet's laws: what each kind yields, the winter shares, hunger a game hour, nutrition,
  spoiling and the stores' sizes; the shipped script for what Cullet's laws do not replace.

The town is counted as one pantry, hour by hour from 07:00 on day 1 (spring): every node
regrows at its kind's share of the rate in the season, up to its max; the eaters eat their
day's hunger evenly, from the land first (greens, which do not keep, then fish, then roots),
then from the stores (smoked fish, then roots), which spoil at a third of the carried rate.
What nobody can eat is the town's hunger. Food is counted as it is eaten, as the plan counted
the land: fish smoked (24), roots baked (30), greens raw (10). Not modelled: how fast people
gather (the plan's 16 food workers about five game hours a day), carrying, who eats where.

Scenarios:
- "eat from the land": nobody lays anything by; regrowth past a node's max is lost.
- "lay by in autumn": in autumn the fishers and growers also take what the land gives past
  that day's eating and put it in the stores (fish smoked), up to the stores' room for food.
- "bare land": the same as eating from the land, but the land is empty when winter comes
  (everything eaten, traded or spoilt in autumn): the stores alone carry the winter.
"""

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "living/seeds/worlds/cullet/plan.json"
LAWS = ROOT / "living/seeds/worlds/cullet/laws.rhai"
SKILLS = ROOT / "living/scripts/skills.rhai"

EATERS = 64 + 10
YEAR_DAYS = 8  # the seed sets no year_days: the shipped 8 (living_rules::YEAR_DAYS)
SEASONS = ["spring", "summer", "autumn", "winter"]
AWAKE_H = 16  # an ordinary day: 16 hours awake, 8 asleep at half the hunger (Cullet's rates)
EATEN_AS = {"fish": "smoked_fish", "roots": "baked_roots", "greens": "greens"}
KEPT_AS = {"smoked_fish": "fish", "roots": "roots"}  # what the stores hold, by the food it counts as


def fn_body(src, name):
    m = re.search(r"fn %s\([^)]*\)\s*\{" % name, src)
    assert m, name
    i, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i - 1]


def switch_numbers(body):
    return {k: float(v) for k, v in re.findall(r'"(\w+)"\s*=>\s*([\d.]+)', body)}


def read():
    laws, skills = LAWS.read_text(), SKILLS.read_text()
    yields = dict(re.findall(r'name: "(\w+)", yields: "(\w+)"', skills + laws))
    winter = {k: float(v) for k, v in re.findall(r"(\w+): ([\d.]+)", fn_body(laws, "winter_regrowth"))}
    nutrition = switch_numbers(fn_body(skills, "nutrition")) | switch_numbers(fn_body(laws, "nutrition"))
    spoil = switch_numbers(fn_body(laws, "spoil_per_h"))
    kept = eval(fn_body(skills, "kept_spoil").strip().replace(" ", ""))  # 1.0 / 3.0
    holds = {k: float(v) for k, v in re.findall(r'name: "(\w+)", like: "storage", holds: (\d+)', laws)}
    hunger_h = float(fn_body(laws, "hunger_awake").strip())
    day_hunger = hunger_h * AWAKE_H + hunger_h * 0.5 * (24 - AWAKE_H)
    plan = json.loads(PLAN.read_text())
    stocks = {}  # one per pool, or per node
    for i, r in enumerate(plan["resources"]):
        food = yields.get(r["kind"])
        if food not in EATEN_AS or "max" not in r:
            continue
        key = r.get("pool") or f"{r['kind']}#{i}"
        stocks.setdefault(key, {"kind": r["kind"], "food": food, "max": r["max"], "per_h": r["regrow_per_h"]})
    stores = {k: 0 for k in KEPT_AS}
    room = 0.0
    for l in plan["lots"]:
        for k in KEPT_AS:
            stores[k] += l.get("contents", {}).get(k, 0)
        if l.get("structure") in holds:
            room += holds[l["structure"]] - sum(l.get("contents", {}).get(k, 0) for k in l.get("contents", {}) if k not in KEPT_AS)
    for st in plan["structures"]:
        c = st.get("contents", {})
        if st["kind"] not in holds:
            continue
        for k in KEPT_AS:
            stores[k] += c.get(k, 0)
        food_here = sum(v for k, v in c.items() if k in KEPT_AS)
        if food_here:
            room += holds[st["kind"]] - sum(v for k, v in c.items() if k not in KEPT_AS)
    return {"stocks": stocks, "winter": winter, "nutrition": nutrition, "spoil": spoil, "kept": kept, "day_hunger": day_hunger, "stores": stores, "room": room, "hunger_h": hunger_h}


def points(w, food):
    return w["nutrition"][EATEN_AS[food]]


def season_of(hour):
    # The world starts at 07:00 on day 1; seasons are quarters of the year from day 1's midnight.
    day = (hour + 7) // 24
    return SEASONS[(day % YEAR_DAYS) * 4 // YEAR_DAYS], day + 1


YEARS = 12


def run(w, winter_rule, scenario, years=YEARS):
    stocks = {k: dict(v, amount=v["max"]) for k, v in w["stocks"].items()}
    stores = dict(w["stores"])
    need_h = EATERS * w["day_hunger"] / 24
    days = {}
    for hour in range(YEAR_DAYS * 24 * years - 7):
        season, day = season_of(hour)
        d = days.setdefault(day, {"day": day, "season": season, "in": 0.0, "out": 0.0, "hungry": 0.0, "laid": 0.0})
        if scenario == "bare land" and season == "winter" and season_of(hour - 1)[0] != "winter":
            for s in stocks.values():
                s["amount"] = 0.0
        for s in stocks.values():
            share = (w["winter"].get(s["kind"], 0.0) if winter_rule == "new" else 0.0) if season == "winter" else 1.0
            grown = min(s["max"] - s["amount"], s["per_h"] * share)
            s["amount"] += grown
            d["in"] += grown * points(w, s["food"])
        need = need_h
        for food in ("greens", "fish", "roots"):
            for s in stocks.values():
                if s["food"] != food or need <= 0:
                    continue
                take = min(s["amount"], need / points(w, food))
                s["amount"] -= take
                need -= take * points(w, food)
        for k, food in KEPT_AS.items():
            take = min(stores[k], need / points(w, food))
            stores[k] -= take
            need -= take * points(w, food)
        d["out"] += need_h - need
        d["hungry"] += need
        if scenario == "lay by in autumn" and season == "autumn":
            for s in stocks.values():
                if s["food"] in ("fish", "roots"):
                    item = "smoked_fish" if s["food"] == "fish" else "roots"
                    take = min(s["amount"], max(0.0, w["room"] - sum(stores.values())))
                    s["amount"] -= take
                    stores[item] += take
                    d["laid"] += take * points(w, s["food"])
        for k in stores:
            stores[k] *= 1 - w["spoil"].get(k, 0.0) * w["kept"]
        d["land"] = sum(s["amount"] * points(w, s["food"]) for s in stocks.values())
        d["stores"] = sum(stores[k] * points(w, f) for k, f in KEPT_AS.items())
    return list(days.values())


def fmt(v):
    return f"{v:,.0f}"


def main():
    w = read()
    eat_day = EATERS * w["day_hunger"]
    by_food = {}
    for s in w["stocks"].values():
        by_food.setdefault(s["food"], [0.0, 0.0])
        by_food[s["food"]][0] += s["per_h"] * 24 * points(w, s["food"])
        by_food[s["food"]][1] += s["max"] * points(w, s["food"])
    grow_day = sum(v[0] for v in by_food.values())
    print("## Inputs\n")
    print(f"- Eaters: {EATERS} (64 residents, 10 players), {w['day_hunger']:g} hunger points a game day each (hunger {w['hunger_h']:g} a game hour awake, half asleep, {AWAKE_H} hours awake): {fmt(eat_day)} a day.")
    print(f"- Year: {YEAR_DAYS} game days, winter the last {YEAR_DAYS // 4}. Food counted as eaten: fish smoked {points(w, 'fish'):g}, roots baked {points(w, 'roots'):g}, greens {points(w, 'greens'):g}.")
    print(f"- Stores at the start: {w['stores']['smoked_fish']} smoked fish and {w['stores']['roots']} roots ({fmt(w['stores']['smoked_fish'] * points(w, 'fish') + w['stores']['roots'] * points(w, 'roots'))} points; {w['stores']['smoked_fish'] * points(w, 'fish') / eat_day + w['stores']['roots'] * points(w, 'roots') / eat_day:.1f} days of the {EATERS}). Room for food in the stores: {fmt(w['room'])} things.")
    print(f"- Stored food spoils at a third of the carried rate: smoked fish {w['spoil']['smoked_fish'] * w['kept'] * 100:.3f}%, roots {w['spoil']['roots'] * w['kept'] * 100:.3f}% a game hour.\n")
    print("| Food | Nodes (stocks) | A growing day gives | Held when full | Winter share (new) | A winter day gives (new) |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for food in ("fish", "roots", "greens"):
        ss = [s for s in w["stocks"].values() if s["food"] == food]
        kinds = sorted({s["kind"] for s in ss})
        wd = sum(s["per_h"] * 24 * points(w, food) * w["winter"].get(s["kind"], 0.0) for s in ss)
        print(f"| {food} ({', '.join(kinds)}) | {len(ss)} | {fmt(by_food[food][0])} | {fmt(by_food[food][1])} | {', '.join(f'{w['winter'].get(k, 0.0):g}' for k in kinds)} | {fmt(wd)} |")
    win_new = sum(s["per_h"] * 24 * points(w, s["food"]) * w["winter"].get(s["kind"], 0.0) for s in w["stocks"].values())
    print(f"| all | | {fmt(grow_day)} ({grow_day / eat_day:.2f} times what is eaten) | {fmt(sum(v[1] for v in by_food.values()))} | | {fmt(win_new)} ({win_new / eat_day:.2f} times) |\n")

    wdays = YEAR_DAYS // 4
    for rule, wd in (("old", 0.0), ("new", win_new)):
        year = (YEAR_DAYS - wdays) * grow_day + wdays * wd
        print(f"- A year's land, {rule} rule: {fmt(year)} points against {fmt(YEAR_DAYS * eat_day)} eaten, {year / (YEAR_DAYS * eat_day):.3f} times; {fmt(year - YEAR_DAYS * eat_day)} a year to lay by, before spoiling.")
    print()
    runs = {(rule, sc): run(w, rule, sc) for rule in ("old", "new") for sc in ("eat from the land", "lay by in autumn", "bare land")}
    print("## A year, eating from the land (points a game day)\n")
    print("| Day | Season | In, old | In, new | Out | Land at day's end, old / new | Stores at day's end, old / new | Hungry, old / new |")
    print("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    o, n = runs[("old", "eat from the land")], runs[("new", "eat from the land")]
    for a, b in zip(o[: YEAR_DAYS + 1], n[: YEAR_DAYS + 1]):
        print(f"| {a['day']} | {a['season']} | {fmt(a['in'])} | {fmt(b['in'])} | {fmt(a['out'])} | {fmt(a['land'])} / {fmt(b['land'])} | {fmt(a['stores'])} / {fmt(b['stores'])} | {fmt(a['hungry'])} / {fmt(b['hungry'])} |")
    print("\n(Day 1 starts at 07:00, so it has 17 hours; out is what was eaten, in what the land grew.)\n")
    print("## Each winter, by scenario (points)\n")
    print("| Scenario | Rule | Winter | Land when winter comes | Stores when winter comes | Eaten from stores in winter | Hungry in winter | Lowest stores |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for sc in ("eat from the land", "lay by in autumn", "bare land"):
        for rule in ("old", "new"):
            days = runs[(rule, sc)]
            for y in range(2):
                wd = [d for d in days if (d["day"] - 1) // YEAR_DAYS == y and d["season"] == "winter"]
                before = [d for d in days if d["day"] == wd[0]["day"] - 1][0]
                print(f"| {sc} | {rule} | {y + 1} | {fmt(before['land'])} | {fmt(before['stores'])} | {fmt(before['stores'] - wd[-1]['stores'])} | {fmt(sum(d['hungry'] for d in wd))} | {fmt(min(d['stores'] for d in days))} |")
    print(f"\n## Over {YEARS} years\n")
    print("| Scenario | Rule | Stores fall a year (years 2 to 3) | First winter with hunger | Hungry that winter | Hungry over all winters |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for sc in ("eat from the land", "lay by in autumn", "bare land"):
        for rule in ("old", "new"):
            days = runs[(rule, sc)]
            at_end = lambda y: [d for d in days if d["day"] == y * YEAR_DAYS][0]["stores"]
            winters = [sum(d["hungry"] for d in days if (d["day"] - 1) // YEAR_DAYS == y and d["season"] == "winter") for y in range(YEARS)]
            first = next((y for y, h in enumerate(winters) if h > 0), None)
            print(f"| {sc} | {rule} | {fmt(at_end(2) - at_end(3))} | {'none' if first is None else first + 1} | {'-' if first is None else fmt(winters[first]) + f' ({winters[first] / eat_day:.1f} days of eating)'} | {fmt(sum(winters))} |")
    # When the stores alone carry winters, year after year (nobody restocks them).
    print("\n## The stores alone\n")
    for rule in ("old", "new"):
        gap = eat_day * YEAR_DAYS / 4 - (win_new * YEAR_DAYS / 4 if rule == "new" else 0.0)
        start = w["stores"]["smoked_fish"] * points(w, "fish") + w["stores"]["roots"] * points(w, "roots")
        print(f"- {rule}: a winter on bare land needs {fmt(gap)} points from the stores ({gap / eat_day:.2f} days of eating); the starting stores ({fmt(start)}) carry {start / gap:.1f} such winters if nobody ever lays anything by.")


if __name__ == "__main__":
    main()
