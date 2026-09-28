#!/usr/bin/env python3
"""Deer and wolf populations: a small stochastic model from the rules' own numbers, and a
sampler for a live world.

  living/tools/wildlife.py model [--rev HEAD] [--hours 12] [--seeds 5]
  living/tools/wildlife.py sample <db> [--every 180] [--minutes 60]

`model` reads the life tables and migration floors from seeds/species.json and the needs,
food and pasture numbers from scripts/skills.rhai (at `--rev`, default the working tree),
then steps a population minute by minute at a world's pace (default the Aske Coast: 12-min
days, 8-day years, life_pace 1.5, 256x256 realm seed 3). Behavior is reduced to the seeded
ways: deer graze a shared pasture pool (no geography: this overestimates what a herd can
find), pair when fed, and flee; wolves hunt when hungry, eat until the food desire fades,
carry the rest (it spoils) and breed one pair per pack. Search and chase are an assumed
kill rate (see KILL_*), not measured. It is a reasoning check for the numbers, not a second
simulator: the authority's scratch world is the evidence.

`sample` prints the living deer and wolves (by stage) of a database every few minutes.
"""
import argparse
import json
import math
import random
import re
import subprocess
import sys
import time
from pathlib import Path

LIVING = Path(__file__).resolve().parents[1]

# Behavior assumptions (not rules data): a hunting adult wolf kills at most one deer per
# KILL_MIN minutes when deer are plentiful, half as often at KILL_HALF deer in the world;
# a juvenile hunts at JUVENILE times that.
KILL_MIN = 6.0
KILL_HALF = 10.0
JUVENILE = 0.5
# Wolves start hunting at this hunger (the food desire outweighs pack and mate), eat while
# above EAT_TO after a kill, and eat what they carry again above EAT_AGAIN.
HUNT_AT, EAT_TO, EAT_AGAIN = 40.0, 20.0, 30.0
# Deer graze above this hunger; an adult not raising young finds a partner with this chance
# a minute (seeded ways: the mate desire wins when fed); wolves likewise.
GRAZE_AT, PAIR_DEER, PAIR_WOLF = 45.0, 0.2, 0.1


def read(rel, rev):
    if rev:
        return subprocess.run(["git", "show", f"{rev}:living/{rel}"], cwd=LIVING, capture_output=True, text=True, check=True).stdout
    return (LIVING / rel).read_text()


def fn_body(src, name):
    m = re.search(r"fn %s\([^)]*\)\s*\{" % re.escape(name), src)
    if not m:
        return ""
    i, depth = m.end(), 1
    while depth and i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i]


def arm(body, key, default):
    m = re.search(r'"%s"\s*=>\s*(-?[\d.]+)' % re.escape(key), body)
    return float(m.group(1)) if m else default


def numbers(rev):
    sp = json.loads(read("seeds/species.json", rev))
    rh = read("scripts/skills.rhai", rev)
    rates = fn_body(rh, "rates")
    infant = re.search(r'stage == "infant"\s*\{\s*hunger \*= (?:if a\.actor\.kind == "person" \{ ([\d.]+) \} else \{ ([\d.]+) \}|([\d.]+))', rates)
    infant_animal = float(infant.group(2) or infant.group(3)) if infant else 0.6
    carried = re.search(r"_ => ([\d.]+)", fn_body(rh, "carried_spoil"))
    return {
        "life": {k: sp[k]["life"] for k in ("deer", "wolf")},
        "migrate": {k: sp[k].get("migrate") for k in ("deer", "wolf")},
        "hunger": {k: arm(rates, k, 5.0) for k in ("deer", "wolf")},
        "infant_hunger": infant_animal,
        "meat": arm(fn_body(rh, "nutrition"), "meat", 20.0),
        # Meat a wolf carries: the item's rate times the carrier's share (none: the item's rate).
        "spoil": arm(fn_body(rh, "spoil_rate"), "meat", 0.05) * (float(carried.group(1)) if carried else 1.0),
        "carcass": arm(fn_body(rh, "carcass_meat"), "deer", 3),
        "graze": -float(re.search(r"hunger:\s*(-?[\d.]+)", fn_body(rh, "graze_done")).group(1)),
        "pasture_regen": float(re.search(r"pasture_regen:\s*([\d.]+)", fn_body(rh, "laws")).group(1)),
        "max_hp": {k: arm(fn_body(rh, "max_hp"), k, 50.0) for k in ("deer", "wolf")},
        "carry": float(re.search(r"_ => ([\d.]+)", fn_body(rh, "carry_limit")).group(1)),
    }


class Beast:
    __slots__ = ("kind", "age", "death", "hunger", "hp", "busy", "meat", "id", "born")

    def __init__(self, kind, age, death, hp, i):
        self.kind, self.age, self.death, self.hunger, self.hp, self.busy, self.meat, self.id = kind, age, death, 25.0, hp, 0.0, 0, i
        # Born in the world (starts on its young instinct) rather than seeded or migrated.
        self.born = age == 0.0


def run(n, a, seed):
    rng = random.Random(seed)
    day, year_days, pace = a.day_min, a.year_days, a.life_pace
    span = {k: n["life"][k]["years"] * year_days * pace * day for k in ("deer", "wolf")}  # minutes
    frac = lambda b: b.age / span[b.kind]
    L = n["life"]
    stage = lambda b: 0 if frac(b) < L[b.kind].get("infant", 0.004) else 1 if frac(b) < L[b.kind].get("child", 0.05) else 2
    tiles = a.tiles
    pmax, regen = tiles * 0.02, tiles * n["pasture_regen"]
    pool = pmax
    year = year_days * day
    beasts, ids, expecting = [], [0], []  # expecting: (due, kind, parents)
    migrations = {"deer": 0, "wolf": 0}
    last_mig = {"deer": 0.0, "wolf": 0.0}

    def spawn(kind, f):
        ids[0] += 1
        d = L[kind].get("old_age", 0.8)
        b = Beast(kind, f * span[kind], (d + (1 - d) * rng.random()) * span[kind], n["max_hp"][kind], ids[0])
        beasts.append(b)
        return b

    for kind, count in (("deer", a.deer), ("wolf", a.wolves)):
        for _ in range(count):
            u = rng.random()
            spawn(kind, 0.05 + 0.75 * u * u)
    rows, kills, births, starved, wolf_min = [], 0, 0, 0, 0
    for t in range(int(a.hours * 60)):
        winter = (t + 7 / 24 * day) % year >= year * 0.75
        if not winter:
            pool = min(pmax, pool + regen)
        deer = [b for b in beasts if b.kind == "deer"]
        wolves = [b for b in beasts if b.kind == "wolf"]
        nd = len(deer)
        wolf_min += len(wolves)
        # Grazing: every hungry deer takes a grazing a minute while the pool lasts.
        hungry = [b for b in deer if b.hunger > GRAZE_AT]
        rng.shuffle(hungry)
        for b in hungry:
            bites = min(2, math.ceil((b.hunger - GRAZE_AT) / n["graze"]))
            for _ in range(bites):
                if pool >= 1:
                    pool -= 1
                    b.hunger = max(0.0, b.hunger - n["graze"])
        # Wolves: eat, hunt, kill.
        for w in wolves:
            if w.meat and w.hunger > EAT_AGAIN:
                while w.meat and w.hunger > EAT_TO:
                    w.meat -= 1
                    w.hunger = max(0.0, w.hunger - n["meat"])
            s = stage(w)
            # The young instinct (follow a parent, eat what it holds) does not hunt; before this
            # change a young one born in the world kept it until grown.
            if w.meat or w.hunger < HUNT_AT or not deer or w.born and (s == 0 or a.old_young and s < 2):
                continue
            rate = (1 / KILL_MIN) * nd / (nd + KILL_HALF) * (JUVENILE if s == 1 else 1.0)
            if rng.random() < rate:
                prey = rng.choice(deer)
                if prey.hp <= 0:
                    continue
                prey.hp = 0
                kills += 1
                meat = int(n["carcass"])
                while meat and w.hunger > EAT_TO:
                    meat -= 1
                    w.hunger = max(0.0, w.hunger - n["meat"])
                w.meat = min(int(n["carry"]), meat)
        # Spoilage of carried meat.
        for w in wolves:
            if w.meat:
                w.meat -= sum(rng.random() < n["spoil"] for _ in range(w.meat))
        # Needs, health, age.
        for b in beasts:
            r = n["hunger"][b.kind] * (n["infant_hunger"] if stage(b) == 0 else 1.0)
            b.hunger = min(100.0, b.hunger + r)
            if b.hunger >= 100:
                b.hp -= 6
            elif b.hunger < 70:
                b.hp = min(n["max_hp"][b.kind], b.hp + 3)
            b.age += 1
        before = len(beasts)
        starved += sum(1 for b in beasts if b.hp <= 0 and b.hunger >= 100)
        beasts = [b for b in beasts if b.hp > 0 and b.age < b.death]
        alive = {b.id for b in beasts}
        # Births.
        for e in [e for e in expecting if e[0] <= t]:
            expecting.remove(e)
            _, kind, ps = e
            if any(p.id in alive for p in ps):
                for _ in range(rng.randint(1, max(1, int(L[kind].get("litter", 1))))):
                    spawn(kind, 0.0).hunger = 25.0
                    births += 1
                for p in ps:
                    p.busy = t + L[kind].get("interbirth", 0.0) * span[kind]
        # Pairing.
        for kind, chance in (("deer", PAIR_DEER), ("wolf", PAIR_WOLF)):
            ready = [b for b in beasts if b.kind == kind and stage(b) == 2 and b.busy <= t and b.hunger <= 60]
            rng.shuffle(ready)
            if kind == "wolf":
                grown = sum(1 for b in beasts if b.kind == "wolf" and stage(b) >= 2)
                breeding = sum(1 for b in beasts if b.kind == "wolf" and b.busy > t) // 2
                slots = max(1, math.ceil(grown / 5)) - breeding
            else:
                slots = len(ready)
            while len(ready) >= 2 and slots > 0:
                x, y = ready.pop(), ready.pop()
                if rng.random() < chance:
                    g = L[kind].get("gestation", 0.01) * span[kind]
                    x.busy = y.busy = t + g + 1e9  # until the birth resets it
                    expecting.append((t + g, kind, (x, y)))
                    slots -= 1
        # Migration floor.
        for kind in ("deer", "wolf"):
            m = n["migrate"].get(kind)
            if not m or a.no_migrate:
                continue
            count = sum(1 for b in beasts if b.kind == kind)
            if count < m["below"] and t - last_mig[kind] >= m["every_min"]:
                for _ in range(m["group"]):
                    spawn(kind, rng.uniform(0.15, 0.5))
                migrations[kind] += 1
                last_mig[kind] = t
        if t % a.every == 0:
            ws = [b for b in beasts if b.kind == "wolf"]
            rows.append((t, sum(1 for b in beasts if b.kind == "deer"), len(ws), sum(1 for w in ws if stage(w) < 2), round(pool), kills, births))
    return rows, migrations, starved, kills / max(1, wolf_min / 60)


def model(a):
    n = numbers(a.rev)
    for kv in a.set:
        k, v = kv.split("=")
        kind, field = k.split(".")
        n["life"][kind][field] = float(v)
    per_year = a.year_days * a.life_pace * a.day_min / 60
    print(f"numbers ({a.rev or 'working tree'}): {json.dumps(n)}")
    for k in ("deer", "wolf"):
        l = n["life"][k]
        h = lambda f: f * l["years"] * per_year
        print(f"  {k}: life {h(1):.1f} h, infant {h(l.get('infant', 0)):.1f} h, adult at {h(l.get('child', 0)):.1f} h, gestation {h(l.get('gestation', 0)):.2f} h, interbirth {h(l.get('interbirth', 0)):.2f} h, litter <= {l.get('litter', 1)}")
    print(f"  pasture: {a.tiles} grassy tiles, regrowth {a.tiles * n['pasture_regen']:.1f} grazings/min -> feeds {a.tiles * n['pasture_regen'] * n['graze'] / n['hunger']['deer']:.0f} deer in growing time")
    print(f"  a wolf needs {n['hunger']['wolf'] * 60 / n['meat']:.1f} meat/h = {n['hunger']['wolf'] * 60 / n['meat'] / n['carcass']:.2f} deer/h if it eats every piece; carried meat spoils {n['spoil'] * 100:.2f}%/min")
    finals = []
    for s in range(a.seeds):
        rows, mig, starved, per_wolf = run(n, a, s)
        last = [r for r in rows if r[0] >= (a.hours - a.tail) * 60]
        md = sum(r[1] for r in last) / max(1, len(last))
        mw = sum(r[2] for r in last) / max(1, len(last))
        finals.append((md, mw))
        if s == 0 or a.verbose:
            print(f"\nseed {s}: t(h)  deer  wolves (young)  pasture  kills  births")
            for r in rows:
                print(f"        {r[0] / 60:5.1f} {r[1]:5d} {r[2]:6d} ({r[3]:2d}) {r[4]:8d} {r[5]:6d} {r[6]:6d}")
        print(f"seed {s}: last {a.tail} h mean deer {md:.0f}, wolves {mw:.1f}; min deer {min(r[1] for r in rows)}, min wolves {min(r[2] for r in rows)}; migrations {mig}; starved {starved}; {per_wolf:.2f} deer per wolf-hour")
    print(f"\nmean over seeds, last {a.tail} h: deer {sum(f[0] for f in finals) / len(finals):.0f}, wolves {sum(f[1] for f in finals) / len(finals):.1f}")


def sql(db, q):
    """Rows of a query as lists of strings (the CLI prints a header and a rule first)."""
    out = subprocess.run([str(LIVING / "tools/stdb"), "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = out.splitlines()
    rule = next((i for i, l in enumerate(lines) if l.strip() and set(l.strip()) <= set("-+")), None)
    if rule is None:
        return []
    return [[x.strip().strip('"') for x in l.split("|")] for l in lines[rule + 1:] if l.strip()]


def sample(a):
    end = time.time() + a.minutes * 60
    t0 = time.time()
    print("  min  deer (young)  wolves (young) | deer killed/starved/old  wolves killed/starved/old | births  arrivals d/w", flush=True)
    while True:
        c = {"deer": [0, 0], "wolf": [0, 0]}
        for kind, stage in sql(a.db, "SELECT kind, stage FROM character WHERE alive = true"):
            if kind in c:
                c[kind][0] += 1
                c[kind][1] += stage in ("0", "1")
        dead = {"deer": [0, 0, 0], "wolf": [0, 0, 0]}
        for kind, cause in sql(a.db, "SELECT kind, cause FROM character WHERE alive = false"):
            if kind in dead:
                dead[kind][0 if cause.startswith("killed") else 1 if "starv" in cause else 2] += 1
        births = sum(int(r[0]) for r in sql(a.db, "SELECT births FROM stats") if r[0].isdigit())
        came = [r[0] for r in sql(a.db, "SELECT text FROM chronicle WHERE kind = 'arrival'")]
        arrivals = (sum("deer" in t for t in came), sum("wol" in t for t in came))
        d, w = c["deer"], c["wolf"]
        print(f"{(time.time() - t0) / 60:5.1f} {d[0]:5d} ({d[1]:3d}) {w[0]:6d} ({w[1]:3d})   | {'/'.join(map(str, dead['deer'])):>23}  {'/'.join(map(str, dead['wolf'])):>25} | {births:6d}  {arrivals[0]}/{arrivals[1]}  {time.strftime('%H:%M:%S')}", flush=True)
        if time.time() + a.every > end:
            break
        time.sleep(a.every)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("model")
    m.add_argument("--rev", default=None, help="read the numbers at this git revision (default: working tree)")
    m.add_argument("--hours", type=float, default=12)
    m.add_argument("--tail", type=float, default=6, help="hours at the end to average")
    m.add_argument("--seeds", type=int, default=5)
    m.add_argument("--every", type=int, default=30, help="table row every N minutes")
    m.add_argument("--deer", type=int, default=60)
    m.add_argument("--wolves", type=int, default=8)
    m.add_argument("--tiles", type=int, default=45793, help="grass and forest tiles (aske-coast realm: 25,960 + 19,833)")
    m.add_argument("--day-min", type=float, default=12)
    m.add_argument("--year-days", type=float, default=8)
    m.add_argument("--life-pace", type=float, default=1.5)
    m.add_argument("--old-young", action="store_true", help="young animals keep their young instinct until adult (before this change)")
    m.add_argument("--no-migrate", action="store_true")
    m.add_argument("--verbose", action="store_true")
    m.add_argument("--set", action="append", default=[], help="try another life number, e.g. wolf.interbirth=0.15")
    s = sub.add_parser("sample")
    s.add_argument("db")
    s.add_argument("--every", type=int, default=180)
    s.add_argument("--minutes", type=float, default=60)
    a = ap.parse_args()
    model(a) if a.cmd == "model" else sample(a)


if __name__ == "__main__":
    main()
