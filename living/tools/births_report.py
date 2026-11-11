#!/usr/bin/env python3
"""Births, deaths and what grown people spend their days on, per run of a census trial
(docs/TRIALS.md, "Births that keep a settlement's numbers").

  births_report.py [--root DIR] [--every MIN] [--examples N] BATCH [BATCH...]

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
               start and the world's pace, from the seed the run used; `due_by_end` against what
               happened shows whether old age ran as the life table says
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
    seed = json.loads((ROOT / "living/seeds" / f"{seed_rel}.json").read_text()) if seed_rel and (ROOT / "living/seeds" / f"{seed_rel}.json").exists() else {}
    life = dict(json.loads((ROOT / "living/seeds/species.json").read_text())["person"]["life"])
    life.update(((seed.get("species") or {}).get("person") or {}).get("life") or {})
    return life, seed.get("year_days", 8), seed.get("life_pace", 1.0), env


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

    share = lambda c, k: round(c[k] / c["all"], 3) if c["all"] else None  # noqa: E731
    return {
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


def batch_dir(b, root):
    p = Path(b)
    return p if p.is_dir() else root / b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--root", type=Path, default=OUT)
    ap.add_argument("--every", type=float, default=30.0, help="population every so many real minutes")
    ap.add_argument("--examples", type=int, default=2)
    a = ap.parse_args()
    rows = []
    for b in a.batches:
        for d in sorted(p for p in batch_dir(b, a.root).iterdir() if p.is_dir() and (p / "census.jsonl").exists()):
            r = run_dir(d, a)
            if r:
                rows.append(r)
    if not rows:
        sys.exit("no runs with a census (census.jsonl) in " + ", ".join(a.batches))
    keys = [k for k in rows[0] if k not in ("run", "trial", "variant") and not k.startswith("_")]
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
        for r in rs[:a.examples]:
            print(f"   {r['run']} population: {' '.join(r['_series'])}")
            print(f"   {r['run']} old age due (real min, name): {r['_due']}")
            for k, xs in r["_ex"].items():
                for x in xs[:a.examples]:
                    print(f"   e.g. {k}: {x}")


if __name__ == "__main__":
    main()
