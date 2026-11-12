#!/usr/bin/env python3
"""Births, deaths and what grown people spend their days on, per run of a census trial
(docs/TRIALS.md, "Births that keep a settlement's numbers").

  births_report.py [--root DIR] [--every MIN] [--examples N] [--stores] BATCH [BATCH...]

BATCH is a batch name under DIR (default: this checkout's .local/living/trials) or a path to a
batch directory. Read-only. A run needs the runner's census (`census_s` in the trial: every
character every so many seconds, census.jsonl); a run still going is read as far as it got.

Per run:
  pop          people alive at the start, at the end and at every --every real minutes
               (stages i/c/a/e: infant, child, adult, elder)
  births       characters that first appear after the first census (born in the run)
  deaths       people who died in the run, by cause (the character row's `cause`)
  old_age_due  seeded people whose death of old age falls within the run: each creature's own
               point in its lifespan (`Life::deathline`, ported below) against its age at the
               start and the world's pace, from the seed the run used (resolved against the run
               checkout, mind-env's LIVING_ROOT), with the seed laws' `life_years` law applied
               when it has Cullet's `person_years()` shape; `old_age_died` against it shows
               whether old age ran as the life table says
  stationary   births a stationary population of the starting size needs over the run's length:
               N x run / (mean age at death), the mean age at death being (old_age + 1) / 2 of a
               lifespan (no other deaths)
  thinkers     mean people the mind service thought for (the census's `thinkers` under
               `minds.max`, else LIVING_ONLY, else everyone alive past infancy)
  calls_min    model calls per real minute per thinking mind (journal rows / thinker-minutes)
  food_plans, child_plans   share of grown people's plans (each deliberation reply's `plan`, from
               the journal, by actors who were adults or elders at that census) that are about food
               (life_share.FOOD) or about children (CHILD below); a plan can be both
  food_acts, child_acts     the same for decided acts (each reply's `acts`; moves left out):
               food by life_share.act_class, children = conceive, or an act toward an infant or
               a child, or an act whose words match CHILD
  with_infants share of grown-person census rows with an infant within 4 m (adult-minutes with an
               infant = rows x census_s / 60); infant_cover: share of infant census rows with a
               grown person within 4 m
  couples      distinct parent pairs among the run's births; kin_births: births whose parents
               share a parent or are parent and child (census `parents`); gen2_births: births with
               a parent who was born in the run
  conceive_acts  conceive acts in grown and young minds' replies, by whether the actor was seeded
               or born in the run; conceive_refused: why the body refused them, as each mind was
               told next (one per actor and game minute)
  adult_unthought  share of adult-minutes with no mind (outside the census `thinkers`: the
               `minds.max` cap leaves the youngest on their graphs, and graph adults do not conceive)
  hungry       share of census rows over hunger 50, by stage
  --stores     food in each storage every hour, from the contents residents' scenes showed
               (the latest scene within 15 minutes)
The plan and act classes are keyword and skill matches: read the printed examples.
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import life_share  # noqa: E402  (FOOD, act_class, reply)
import trials  # noqa: E402  (journal_file)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".local/living/trials"
CHILD = re.compile(r"\b(child\w*|baby|babies|infant\w*|newborn|son|daughter|famil\w*|conceiv\w*|pregnan\w*|expecting|little one\w*|toddler|nurs\w*|cradle|kid|kids)\b", re.I)
STAGES = "icae"
NEAR_M = 4.0
MASK = (1 << 64) - 1


def jl(p):
    out = []
    if not p.exists():
        return out
    for line in p.read_bytes().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def deathline(cid, old_age):
    """`living_rules::life::Life::deathline`: the fraction of its lifespan at which a creature
    dies of old age, fixed by its id."""
    h = ((cid * 0x9E3779B97F4A7C15) & MASK) ^ 0x5851F42D4C957F2D
    h ^= h >> 29
    h = (h * 0xBF58476D1CE4E5B9) & MASK
    h ^= h >> 32
    u = (h % 10_000) / 10_000.0
    return old_age + (1.0 - old_age) * u


def life_table(d):
    """The person life table and the pace of the seed the run's mind read (species.json with the
    seed's `species` merged over it, as the authority's build does)."""
    env = json.loads((d / "mind-env.json").read_text()) if (d / "mind-env.json").exists() else {}
    seed_rel = env.get("LIVING_SEED")
    # The seed path is relative to the run checkout's living/seeds (a trial's derived seed lives
    # under that checkout's .local), which need not be this one.
    roots = [Path(env["LIVING_ROOT"])] if env.get("LIVING_ROOT") and Path(env["LIVING_ROOT"]).is_dir() else []
    roots.append(ROOT)
    seed = {}
    for r in roots:
        f = r / "living/seeds" / f"{seed_rel}.json" if seed_rel else None
        if f is not None and f.exists():
            seed = json.loads(f.read_text())
            break
    if seed_rel and not seed:
        print(f"warning: {d.name}: seed {seed_rel} not found; pace falls back to the island's", file=sys.stderr)
    species = next((r / "living/seeds/species.json" for r in roots if (r / "living/seeds/species.json").exists()))
    life = dict(json.loads(species.read_text())["person"]["life"])
    life.update(((seed.get("species") or {}).get("person") or {}).get("life") or {})
    life = life_years(life, seed, roots, d)
    return life, seed.get("year_days", 8), seed.get("life_pace", 1.0), env


AGES = ("infant", "child", "elder", "old_age", "gestation", "interbirth")


def life_years(life, seed, roots, d):
    """The seed's laws' `life_years` law over the person table, as `Scripts::life_law` applies it:
    the law sees each age in years (fraction x years) and the lifespan, and what it returns becomes
    fractions of the returned lifespan. Python cannot run Rhai, so this reads only the shape
    Cullet's laws use, `fn person_years() { #{ lifespan: .., child: .., old_age: .. } }`, whose
    keys replace the table's; a `life_years` law of any other shape is reported and left out."""
    text = seed.get("laws") or ""
    if not text and seed.get("laws_file"):
        f = next((r / "living/seeds" / seed["laws_file"] for r in roots if (r / "living/seeds" / seed["laws_file"]).exists()), None)
        text = f.read_text() if f else ""
    if not re.search(r"^\s*fn\s+life_years\s*\(", text, re.M):
        return life
    m = re.search(r"fn\s+person_years\s*\(\s*\)\s*\{\s*#\{([^}]*)\}", text)
    if not m:
        print(f"warning: {d.name}: the laws have a life_years law this report cannot read; using species.json's table", file=sys.stderr)
        return life
    given = {k: float(v) for k, v in re.findall(r"(\w+)\s*:\s*([0-9.]+)", m.group(1))}
    y = float(life["years"])
    span = given.get("lifespan", y)
    out = dict(life, years=span)
    for k in AGES:
        if k in given:
            out[k] = given[k] / span
        elif span != y:
            out[k] = life[k] * y / span
    return out


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def run_dir(d, args):
    census = jl(d / "census.jsonl")
    if not census:
        return None
    s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {"partial": True}
    day_ms = s.get("day_ms") or 720_000
    life, year_days, pace, env = life_table(d)
    span_days = life["years"] * year_days * pace
    first, last = census[0], census[-1]
    t0_ms = first["now_ms"] - int((first["t"] or 0) * 1000)
    minutes = (last["now_ms"] - t0_ms) / 60_000
    seeded = {p["id"]: p for p in first["people"]}
    people = {}
    for c in census:
        for p in c["people"]:
            people[p["id"]] = p
    persons = {i: p for i, p in people.items() if p["kind"] == "person"}
    born = [p for i, p in persons.items() if i not in seeded]
    died = [p for p in persons.values() if not p["alive"] and p["died_ms"] and p["died_ms"] >= t0_ms]
    causes = Counter(p["cause"] or "?" for p in died)

    def alive_at(c):
        st = Counter(STAGES[p["stage"]] for p in c["people"] if p["kind"] == "person" and p["alive"])
        return sum(st.values()), st

    series = []
    step = args.every * 60
    nxt = 0
    for c in census:
        if (c["t"] or 0) >= nxt:
            n, st = alive_at(c)
            series.append(f"{round((c['t'] or 0) / 60)}m:{n}({''.join(f'{k}{st[k]}' for k in STAGES if st[k])})")
            nxt += step
    n0, _ = alive_at(first)
    n1, _ = alive_at(last)

    # Old age against the life table: when each seeded person was due to die of it.
    due = []
    for p in seeded.values():
        if p["kind"] != "person" or not p["alive"]:
            continue
        frac_line = deathline(p["id"], life["old_age"])
        due_min = (frac_line * span_days - p["age0"]) * day_ms / 60_000 + (p["born_ms"] - t0_ms) / 60_000
        due.append((round(due_min, 1), p["name"]))
    due.sort()
    old_due = [x for x in due if x[0] <= minutes]
    old_died = sum(1 for p in died if p["cause"] == "old age")
    mean_death_min = (life["old_age"] + 1) / 2 * span_days * day_ms / 60_000
    stationary = n0 * minutes / mean_death_min

    # Who thinks, and the calls per thinking mind.
    only = [int(x) for x in str(env.get("LIVING_ONLY", "")).split(",") if x.strip().isdigit()]
    think_min = 0.0
    for a, b in zip(census, census[1:]):
        alive = {p["id"] for p in a["people"] if p["alive"]}
        if a.get("thinkers"):
            n = len(set(a["thinkers"]) & alive)
        elif only:
            n = len(set(only) & alive)
        else:
            n = sum(1 for p in a["people"] if p["alive"] and p["stage"] != 0)
        think_min += n * (b["now_ms"] - a["now_ms"]) / 60_000
    live = d.parents[2] / "journal" / f"verify-trial-{d.parent.name}-{d.name}" if len(d.parents) > 2 else None
    jdir = live if live is not None and live.exists() else d / "journal"
    names = {trials.journal_file(p["name"])[:-6]: i for i, p in persons.items()}
    rows = []
    for f in sorted(jdir.glob("*.jsonl")) if jdir.exists() else []:
        if f.stem in names:
            rows += [dict(r, _id=names[f.stem]) for r in jl(f)]
    calls_min = len(rows) / think_min if think_min else None

    # Plans and acts of grown people, classed by their census stage at the time.
    stage_at = []
    for c in census:
        stage_at.append((c["now_ms"], {p["id"]: p["stage"] for p in c["people"]}))

    def stage_of(cid, at):
        best = None
        for t, m in stage_at:
            if t <= at:
                best = m
            else:
                break
        return (best or stage_at[0][1]).get(cid)

    plans, acts, ex = Counter(), Counter(), defaultdict(list)
    for r in rows:
        if r.get("error") or stage_of(r["_id"], r.get("at_ms") or 0) not in (2, 3):
            continue
        rep = life_share.reply(r)
        plan = rep.get("plan")
        if isinstance(plan, str) and plan.strip():
            plans["all"] += 1
            if life_share.FOOD.search(plan):
                plans["food"] += 1
            if CHILD.search(plan):
                plans["child"] += 1
                ex["child_plan"].append(f"{r.get('actor')}: {plan[:140]}")
        for a in rep.get("acts") or []:
            if not isinstance(a, dict) or not a.get("do"):
                continue
            k = life_share.act_class(a)
            if k == "move":
                continue
            acts["all"] += 1
            if k == "food":
                acts["food"] += 1
            tgt = (a.get("target") or {}).get("id") if isinstance(a.get("target"), dict) else None
            young = tgt in persons and stage_of(tgt, r.get("at_ms") or 0) in (0, 1)
            if a["do"] == "conceive" or young or CHILD.search(str(a.get("text") or "")):
                acts["child"] += 1
                ex["child_act"].append(f"{r.get('actor')}: {json.dumps(a)[:140]}")

    # Time with infants, from the census positions.
    grown_rows = with_inf = inf_rows = inf_cov = 0
    for c in census:
        alive = [p for p in c["people"] if p["kind"] == "person" and p["alive"] and p["pos"]]
        infants = [p for p in alive if p["stage"] == 0]
        grown = [p for p in alive if p["stage"] >= 2]
        grown_rows += len(grown)
        with_inf += sum(1 for g in grown if any(dist(g["pos"], i["pos"]) <= NEAR_M for i in infants))
        inf_rows += len(infants)
        inf_cov += sum(1 for i in infants if any(dist(g["pos"], i["pos"]) <= NEAR_M for g in grown))
    census_s = (census[1]["now_ms"] - census[0]["now_ms"]) / 1000 if len(census) > 1 else 0

    extra = lineage(census, persons, seeded, t0_ms, rows, args)

    share = lambda c, k: round(c[k] / c["all"], 3) if c["all"] else None  # noqa: E731
    return extra | {
        "run": d.name, "trial": s.get("trial") or re.sub(r"-[^-]+-r\d+$", "", d.name), "variant": s.get("variant"),
        "min": round(minutes), "partial": bool(s.get("partial")), "pop": f"{n0}->{n1}", "births": len(born),
        "deaths": sum(causes.values()), "causes": dict(causes), "old_age_due": len(old_due), "old_age_died": old_died,
        "stationary": round(stationary, 1), "thinkers": round(think_min / minutes, 1) if minutes else None,
        "calls_min": round(calls_min, 2) if calls_min is not None else None,
        "plans": plans["all"], "food_plans": share(plans, "food"), "child_plans": share(plans, "child"),
        "acts": acts["all"], "food_acts": share(acts, "food"), "child_acts": share(acts, "child"),
        "with_infants": round(with_inf / grown_rows, 3) if grown_rows else None,
        "adult_min_with_infants": round(with_inf * census_s / 60),
        "infant_cover": round(inf_cov / inf_rows, 3) if inf_rows else None,
        "_series": series, "_due": due, "_ex": ex,
    }


FOOD_ITEMS = {"berries", "fish", "cooked_fish", "smoked_fish", "meat", "cooked_meat", "smoked_meat"}
REFUSED = re.compile(r"\[(?:\d+\] )?day (\d+) (\d+:\d+)\]? (?:What you had decided did not work out: |You failed to )conceive → [^:\n]+: ([^.\n]+)")


def lineage(census, persons, seeded, t0_ms, rows, args):
    """Who had the children, whether the run's own children had any, what refused the minds'
    conceive acts, how many grown people had no mind (the `minds.max` cap), hunger by stage, and
    the food in each store as the residents' scenes showed it."""
    at = lambda ms: round((ms - t0_ms) / 60_000, 1)  # noqa: E731
    parents = {i: tuple(p.get("parents") or (0, 0)) for i, p in persons.items()}
    name = lambda i: persons[i]["name"] if i in persons else f"#{i}"  # noqa: E731
    born = sorted((p for i, p in persons.items() if i not in seeded), key=lambda p: p["born_ms"])
    pairs = Counter(frozenset(parents[p["id"]]) for p in born)

    def kin(a, b):
        pa, pb = set(parents.get(a, ())) - {0}, set(parents.get(b, ())) - {0}
        return bool(pa & pb) or a in pb or b in pa

    kin_births = [p for p in born if len(parents[p["id"]]) == 2 and kin(*parents[p["id"]])]
    gen2 = [p for p in born if any(q in persons and q not in seeded for q in parents[p["id"]])]
    events = [f"{at(p['born_ms'])}m {p['name']} <- {' + '.join(name(q) for q in parents[p['id']])}" for p in born]
    events += [f"{at(p['died_ms'])}m {p['name']} died ({p['cause']})" for p in persons.values() if not p["alive"] and p["died_ms"] and p["died_ms"] >= t0_ms]
    events.sort(key=lambda e: float(e.split("m ", 1)[0]))

    # Grown people without a mind: the cap (`minds.max`) leaves the youngest on their graphs,
    # and graph adults do not conceive.
    adult_min = unthought = 0.0
    for a, b in zip(census, census[1:]):
        if not a.get("thinkers"):
            break
        dt = (b["now_ms"] - a["now_ms"]) / 60_000
        th = set(a["thinkers"])
        for p in a["people"]:
            if p["kind"] == "person" and p["alive"] and p["stage"] == 2:
                adult_min += dt
                unthought += dt if p["id"] not in th else 0

    # Hunger by stage over every census row (hungry over 50; starving at 100 under Cullet's laws).
    hun = defaultdict(list)
    for c in census:
        for p in c["people"]:
            if p["kind"] == "person" and p["alive"] and p.get("hunger") is not None:
                hun[STAGES[p["stage"]]].append(p["hunger"])
    hungry = {k: round(sum(h > 50 for h in v) / len(v), 3) for k, v in hun.items() if v}

    # Conceive acts decided, and why the body refused them (as the mind was next told).
    by = Counter()
    refused, seen = Counter(), set()
    stores = defaultdict(list)
    for r in rows:
        if r.get("purpose") == "deliberate" and not r.get("error"):
            for a in life_share.reply(r).get("acts") or []:
                if isinstance(a, dict) and a.get("do") == "conceive":
                    by["seeded" if r["_id"] in seeded else "born"] += 1
        for m in (r.get("request") or {}).get("messages") or []:
            t = m.get("content")
            if not isinstance(t, str):
                continue
            for x in REFUSED.finditer(t):
                k = (r["_id"], x.group(1), x.group(2), x.group(3))
                if k not in seen:
                    seen.add(k)
                    refused[re.sub(r"\d+", "#", x.group(3))] += 1
            if args.stores and '{"creatures"' in t:
                i = t.find('{"creatures"')
                j = t.find("\n", i)
                try:
                    scene = json.loads(t[i:j if j > 0 else None])
                except ValueError:
                    continue
                for s in scene.get("structures") or []:
                    if s.get("kind") == "storage" and isinstance(s.get("contents"), dict):
                        stores[s["id"]].append((r.get("at_ms") or 0, sum(v for k2, v in s["contents"].items() if k2 in FOOD_ITEMS)))
    store_series = {}
    for sid, obs in stores.items():
        obs.sort()
        pts = []
        for target in range(0, int(at(census[-1]["now_ms"])) + 1, 60):
            near = [f for ms, f in obs if abs(at(ms) - target) <= 15]
            if near:
                pts.append(f"{target}m:{near[-1]}")
        store_series[sid] = " ".join(pts)
    return {
        "couples": len(pairs), "kin_births": len(kin_births), "gen2_births": len(gen2),
        "conceive_acts": dict(by), "conceive_refused": dict(refused),
        "adult_unthought": round(unthought / adult_min, 3) if adult_min else None,
        "hungry": hungry,
        "_events": events, "_stores": store_series,
    }


def batch_dir(b, root):
    p = Path(b)
    return p if p.is_dir() else root / b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--root", type=Path, default=OUT)
    ap.add_argument("--every", type=float, default=30.0, help="population every so many real minutes")
    ap.add_argument("--examples", type=int, default=2)
    ap.add_argument("--stores", action="store_true", help="food in each store over time, from the storage contents in residents' scenes (slow)")
    a = ap.parse_args()
    rows = []
    for b in a.batches:
        for d in sorted(p for p in batch_dir(b, a.root).iterdir() if p.is_dir() and (p / "census.jsonl").exists()):
            r = run_dir(d, a)
            if r:
                rows.append(r)
    if not rows:
        sys.exit("no runs with a census (census.jsonl) in " + ", ".join(a.batches))
    keys = [k for k in rows[0] if k not in ("run", "trial", "variant", "conceive_refused", "hungry") and not k.startswith("_")]
    print("| run | " + " | ".join(keys) + " |")
    print("| --- |" + " ---: |" * len(keys))
    for r in rows:
        print(f"| {r['run']} | " + " | ".join(str(r.get(k)) for k in keys) + " |")
    by = defaultdict(list)
    for r in rows:
        by[(r["trial"], r["variant"])].append(r)
    print()
    for (t, v), rs in by.items():
        parts = []
        for k in ("births", "deaths", "old_age_due", "stationary", "thinkers", "calls_min", "food_plans", "child_plans", "food_acts", "child_acts", "with_infants", "infant_cover"):
            xs = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
            if xs:
                parts.append(f"{k} {statistics.mean(xs):.2f} ({min(xs):g}-{max(xs):g})")
        print(f"{t} x {v} (n={len(rs)}): " + "; ".join(parts))
        for r in rs:
            print(f"   {r['run']} conceive refused (by reason): {r['conceive_refused']}; hungry (>50) share by stage: {r['hungry']}")
        for r in rs[:a.examples]:
            print(f"   {r['run']} population: {' '.join(r['_series'])}")
            print(f"   {r['run']} old age due (real min, name): {r['_due']}")
            print(f"   {r['run']} births and deaths: {'; '.join(r['_events'])}")
            for sid, ser in r["_stores"].items():
                print(f"   {r['run']} store #{sid} food (latest scene within 15 min): {ser}")
            for k, xs in r["_ex"].items():
                for x in xs[:a.examples]:
                    print(f"   e.g. {k}: {x}")


if __name__ == "__main__":
    main()
