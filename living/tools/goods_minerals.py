#!/usr/bin/env python3
"""What making minerals finite would do to Cullet's peat (docs/GOODS_PROPOSALS.md), from the
plan's and the laws' own numbers, on the pattern of `cullet_winter.py`. No model, no server.

It reads
- the plan (living/seeds/worlds/cullet/plan.json): the peat banks (max, regrowth a game hour),
  the fires (kind, first fill) and the peat in every store;
- Cullet's laws: each fire's burn rate (`goods_structures`), the peat bank's gathering time and
  winter share, the day length; the shipped YEAR_DAYS (8).

The town is one peat heap, counted a game day at a time: the cutters bring in what the rule
lets them, the fires burn what the scenario burns, from the heap; a day the heap cannot cover
is a day short (fires go out). Cutters cut only what the town has room to keep: the peat barn,
the Cone yard's store, the fires' own fill and each household's 24 (`ROOM`, from the plan).
Rules:

- "regrows" (today): the 18 cuttings regrow at their rate in growing seasons (none in winter),
  up to their max; the cutters take what has grown.
- "finite": a cutting is a deposit with no regrowth; the cutters cut up to their day's labour;
  a cutting that is spent is replaced by opening a new one (a day's work of one cutter), until
  the Moss has no more.
- "finite, drying": as finite, but cut peat is wet and burns only after drying `DRY_DAYS` game
  days; nothing dries in winter (so winter's peat is cut by the end of autumn).

Burn scenarios, peat a game day:
- "design": SMALL_CITY §2, the Cone at full firing and the homes about as much again;
- "evenings": the Cone at full firing, each home hearth lit 6 game hours a day, the oven and the
  smokehouses 8;
- "all lit": every fire the plan places kept lit around the clock (the laws' ceiling).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "living/seeds/worlds/cullet/plan.json"
LAWS = ROOT / "living/seeds/worlds/cullet/laws.rhai"
SEED = ROOT / "living/seeds/cullet.json"

YEAR_DAYS = 8
SEASONS = ["spring", "summer", "autumn", "winter"]
YEARS = 12
CUTTERS = 3
CUT_HOURS = 5  # game hours a cutter cuts a day (the plan's working day for food workers)
# The proposal's numbers (game units: one peat is one gathering).
DEPOSIT = 330  # a cutting: a 10 m face 1 m deep, about 10 cubic metres of sods
MOSS_CUTTINGS = 200  # cuttings the Moss holds at that size (about 6.6 ha of its 7 worked 1 m deep: see the doc)
OPEN_HOURS = 5  # one cutter's day to open a new cutting
DRY_DAYS = 2


def fn_body(src, name):
    m = re.search(r"fn %s\([^)]*\)\s*\{" % name, src)
    assert m, name
    i, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i - 1]


def read():
    laws = LAWS.read_text()
    plan = json.loads(PLAN.read_text())
    seed = json.loads(SEED.read_text())
    rates = {k: float(v) for k, v in re.findall(r'name: "(\w+)",[^}]*burns: #\{ fuel: "fuel", rate: ([\d.]+)', fn_body(laws, "goods_structures"))}
    bank = re.search(r'name: "peat_bank".*?gather_ms: (\d+)', laws).group(1)
    winter = float(re.search(r"peat_bank: ([\d.]+)", fn_body(laws, "winter_regrowth")).group(1))
    banks = [r for r in plan["resources"] if r["kind"] == "peat_bank"]
    fires = {}
    stock = 0.0
    for s in plan["structures"]:
        if s["kind"] in rates:
            fires[s["kind"]] = fires.get(s["kind"], 0) + 1
            stock += s.get("fuel", 0.0)
        stock += s.get("contents", {}).get("peat", 0)
    for l in plan["lots"]:
        stock += l.get("contents", {}).get("peat", 0)
    for t in seed["towns"]:
        for r in t["residents"]:
            stock += r.get("inventory", {}).get("peat", 0)
    hour_ms = seed["day_minutes"] * 60_000 / 24
    per_cutter_h = hour_ms / int(bank)
    # Room for peat: the stores that hold it (the peat barn starts empty), the fires' fill and
    # the households' peat share (the plan's 24 each).
    holds = {k: float(v) for k, v in re.findall(r'name: "(\w+)", like: "storage", holds: (\d+)', laws)}
    holds_fire = {k: float(v) for k, v in re.findall(r'name: "(\w+)",[^}]*burns: #\{[^}]*holds: ([\d.]+)', fn_body(laws, "goods_structures"))}
    room = holds["peat_barn"] + holds["yard_store"] + sum(holds_fire.get(k, 0) * n for k, n in fires.items()) + 24 * sum(1 for s in plan["structures"] if s["kind"] == "house_store")
    return {"rates": rates, "fires": fires, "banks": banks, "winter": winter, "stock": stock, "per_cutter_h": per_cutter_h, "room": room}


def burns(w):
    r, f = w["rates"], w["fires"]
    cone = r["furnace"] * 24 * f["furnace"]
    return {
        "design": cone * 2,
        "evenings": cone + f["hearth"] * r["hearth"] * 6 + f["oven"] * r["oven"] * 8 + f["smokehouse"] * r["smokehouse"] * 8,
        "all lit": sum(f[k] * r[k] * 24 for k in f),
    }


def season(day):
    return SEASONS[((day - 1) % YEAR_DAYS) * 4 // YEAR_DAYS]


def run(w, rule, burn, years=YEARS):
    labour = CUTTERS * CUT_HOURS * w["per_cutter_h"]
    heap = w["stock"]
    banks = [dict(max=b["max"], per_h=b["regrow_per_h"], amount=b["max"]) for b in w["banks"]]
    cuttings = [DEPOSIT] * len(banks)
    unopened = MOSS_CUTTINGS - len(banks)
    drying = []  # (ready day, units)
    days = []
    for day in range(1, years * YEAR_DAYS + 1):
        s = season(day)
        cut = 0.0
        if rule == "regrows":
            share = w["winter"] if s == "winter" else 1.0
            for b in banks:
                b["amount"] = min(b["max"], b["amount"] + b["per_h"] * 24 * share)
            for b in banks:
                take = min(b["amount"], labour - cut)
                b["amount"] -= take
                cut += take
        else:
            hours = CUTTERS * CUT_HOURS
            want = max(0.0, w["room"] - heap - sum(u for _, u in drying))
            hours = min(hours, want / w["per_cutter_h"])
            while hours > 1e-9 and (cuttings or unopened):
                if not cuttings or cuttings[0] <= 0:
                    if cuttings:
                        cuttings.pop(0)
                    if not cuttings:
                        if unopened <= 0:
                            break
                        unopened -= 1
                        hours -= OPEN_HOURS
                        cuttings.append(DEPOSIT)
                        continue
                take = min(cuttings[0], hours * w["per_cutter_h"])
                cuttings[0] -= take
                hours -= take / w["per_cutter_h"]
                cut += take
        if rule == "finite, drying":
            # Wet peat dries in DRY_DAYS days, but not in winter (it waits for spring).
            ready = day + DRY_DAYS
            while season(ready) == "winter":
                ready += 1
            drying.append((ready, cut))
            dried = sum(u for d, u in drying if d <= day)
            drying = [(d, u) for d, u in drying if d > day]
            heap += dried
        else:
            heap += cut
        burnt = min(heap, burn)
        heap -= burnt
        days.append({"day": day, "season": s, "cut": cut, "burnt": burnt, "short": burn - burnt, "heap": heap, "left": (sum(max(c, 0) for c in cuttings) + unopened * DEPOSIT) if rule != "regrows" else None})
    return days


def fmt(v):
    return f"{v:,.0f}"


def main():
    w = read()
    b = burns(w)
    grow_day = sum(x["regrow_per_h"] for x in w["banks"]) * 24
    labour = CUTTERS * CUT_HOURS * w["per_cutter_h"]
    print("## Inputs\n")
    print(f"- Peat banks: {len(w['banks'])}, each up to {w['banks'][0]['max']:g}, regrowing {w['banks'][0]['regrow_per_h']:g} a game hour: {fmt(grow_day)} a growing day, {w['winter']:g} of that in winter; a year ({YEAR_DAYS} game days, the last {YEAR_DAYS // 4} winter) {fmt(grow_day * YEAR_DAYS * 3 / 4)}.")
    print(f"- Peat in the town at the start (stores, packs and the fires' first fill): {fmt(w['stock'])}.")
    print(f"- Fires: {', '.join(f'{n} {k} at {w['rates'][k]:g} a game hour' for k, n in w['fires'].items())}.")
    print(f"- Cutting: one gathering a {1 / w['per_cutter_h'] * 60:.1f} game minutes ({w['per_cutter_h']:g} a game hour); {CUTTERS} cutters {CUT_HOURS} game hours a day can cut {fmt(labour)} a day.")
    print(f"- Room for peat in the town: {fmt(w['room'])} (the peat barn, the Cone yard's store, the fires' fill, 24 a household).")
    print(f"- The proposal's numbers: a cutting holds {DEPOSIT}; the Moss {MOSS_CUTTINGS} cuttings ({fmt(DEPOSIT * MOSS_CUTTINGS)} peat); opening one takes {OPEN_HOURS} cutter-hours; wet peat dries in {DRY_DAYS} game days, not in winter.\n")
    print("| Burn | A game day | A year | Regrowth covers | The start's stock lasts (no cutting) |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for k, v in b.items():
        print(f"| {k} | {fmt(v)} | {fmt(v * YEAR_DAYS)} | {grow_day * 3 / 4 / v * 100:.0f}% of a year's burning | {w['stock'] / v:.1f} days |")
    print("\n## A year at the design burn (peat a game day: cut / burnt / heap at day's end)\n")
    rules = ("regrows", "finite", "finite, drying")
    runs = {(r, k): run(w, r, v) for r in rules for k, v in b.items()}
    print("| Day | Season | " + " | ".join(rules) + " |")
    print("| ---: | --- | " + " | ".join("---:" for _ in rules) + " |")
    for i in range(YEAR_DAYS):
        cells = [f"{fmt(runs[(r, 'design')][i]['cut'])} / {fmt(runs[(r, 'design')][i]['burnt'])} / {fmt(runs[(r, 'design')][i]['heap'])}" for r in rules]
        print(f"| {i + 1} | {season(i + 1)} | " + " | ".join(cells) + " |")
    print(f"\n## Over {YEARS} years\n")
    print("| Burn | Rule | Heap after year 1 | Heap after year 3 | First day short | Days short | Peat short | Moss left at the end |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for k in b:
        for r in rules:
            d = runs[(r, k)]
            short = [x for x in d if x["short"] > 0.5]
            left = d[-1]["left"]
            print(f"| {k} | {r} | {fmt(d[YEAR_DAYS - 1]['heap'])} | {fmt(d[3 * YEAR_DAYS - 1]['heap'])} | {short[0]['day'] if short else 'none'} | {len(short)} | {fmt(sum(x['short'] for x in short))} | {'-' if left is None else fmt(left)} |")
    print()
    for k, v in b.items():
        print(f"- {k}: the Moss's {fmt(DEPOSIT * MOSS_CUTTINGS)} last {DEPOSIT * MOSS_CUTTINGS / (v * YEAR_DAYS):.0f} game years at {fmt(v * YEAR_DAYS)} a year.")


if __name__ == "__main__":
    main()
