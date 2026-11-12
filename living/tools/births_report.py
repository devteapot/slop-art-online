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
               are close kin (parent, child, sibling, uncle or aunt, niece or nephew: census
               `parents` and the seed sheets' relation labels, `Kin` below); gen2_births: births
               with a parent who was born in the run
  attempts     every conceive act in deliberation and talk replies, classed toward the actor's
               partner, toward close kin, or other; close_kin_share; cands_at_kin and cands_at_all:
               the mean number of unrelated, unpaired adults the actor could have asked at that
               moment (paired = co-parent of a living child, or a seed sheet's wife, husband or
               partner label: the worlds record no other agreement); zero_cand_attempts; each
               attempt is printed (* marks an actor born in the run), and the free adults over
               time (`unpaired/adults~mean candidates per adult`)
  why          per person who came of age in the run (run-born, and seeded children), why they
               did or did not pair (docs/MIND_RESEARCH_IDEAS.md #6): when they came of age, their
               candidates while adult (mean, peak, share of time with any, a series), the share of
               their deliberations whose scene held a candidate, the longing percepts their prompts
               carried, conceive attempts as adults and the time to the first, replies that name or
               aim at a candidate or speak of partnering, longing or children (examples printed,
               --mentions), the body's refusals, adult time on no mind, and their time budget by
               activity; per run rb_tried_by_cands: run-born adults who ever tried, of all, by mean
               candidates while adult (coa_* the same for seeded children)
  born_*       the run-born generation: how many grew up, tried to conceive, became parents, and
               their couples (with their births and close-kin couples in the printed line)
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
    return life, seed.get("year_days", 8), seed.get("life_pace", 1.0), env, seed


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
    life, year_days, pace, env, seed = life_table(d)
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

    extra = lineage(census, persons, seeded, t0_ms, rows, args, seed)
    extra |= attempts(census, persons, seeded, t0_ms, rows, seed, args)
    extra |= why_unpaired(census, persons, seeded, rows, seed, extra["_att"], args)

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


# Kinship. Close kin: parent, child, sibling, uncle or aunt, niece or nephew. Grandparents,
# grandchildren, cousins and in-laws are named but are not close kin.
CLOSE = {"parent", "child", "sibling", "uncle/aunt", "niece/nephew"}
# A seed sheet's relation label, as what the named person is to the sheet's owner. In-laws first:
# "brother-in-law" is not a brother.
LABELS = [
    (re.compile(r"in-law|in law", re.I), "in-law"),
    (re.compile(r"\bgrand(father|mother|parent|pa|ma)\b", re.I), "grandparent"),
    (re.compile(r"\bgrand(son|daughter|child)\b", re.I), "grandchild"),
    (re.compile(r"\b(mother|father|parent)\b", re.I), "parent"),
    (re.compile(r"\b(son|daughter|child)\b", re.I), "child"),
    (re.compile(r"\b(brother|sister|sibling)\b", re.I), "sibling"),
    (re.compile(r"\b(uncle|aunt)\b", re.I), "uncle/aunt"),
    (re.compile(r"\b(nephew|niece)\b", re.I), "niece/nephew"),
    (re.compile(r"\bcousin\b", re.I), "cousin"),
]
INVERSE = {"parent": "child", "child": "parent", "sibling": "sibling", "uncle/aunt": "niece/nephew", "niece/nephew": "uncle/aunt",
           "grandparent": "grandchild", "grandchild": "grandparent", "cousin": "cousin", "in-law": "in-law"}
SPOUSE = re.compile(r"\b(wife|husband|partner|spouse)\b", re.I)


def seed_residents(seed):
    for t in (seed.get("towns") or []) + (seed.get("villages") or []):
        yield from t.get("residents") or []


class Kin:
    """Who is kin to whom: parent links (the census `parents`, seeded and run-born alike) and,
    for seeded people, their seed sheets' relation labels (Cal Reed is Sefa's "uncle" by her late
    father, who is not in the world). Siblings share a parent; an uncle or aunt is a parent's
    sibling; a cousin a parent's sibling's child. `spouses` are the sheets' wife, husband or
    partner labels: the only recorded agreement to be a couple the worlds keep."""

    def __init__(self, persons, seed):
        self.persons = persons
        self.parents = {i: {q for q in (p.get("parents") or ()) if q} for i, p in persons.items()}
        ids = {p["name"]: i for i, p in persons.items()}
        self.label, self.spouses = {}, set()
        for r in seed_residents(seed):
            a = ids.get(r.get("name"))
            for rel in ((r.get("sheet") or {}).get("relations") or []) if a else []:
                b, lab = ids.get(rel.get("name")), str(rel.get("label") or "")
                if not b or b == a:
                    continue
                if SPOUSE.search(lab) and "in-law" not in lab.lower():
                    self.spouses.add(frozenset((a, b)))
                    continue
                for rx, what in LABELS:
                    if rx.search(lab):
                        # `what` is what b is to a.
                        self.label.setdefault((a, b), what)
                        self.label.setdefault((b, a), INVERSE[what])
                        break
        self.memo = {}

    def par(self, a):
        return self.parents.get(a, set()) | {b for (x, b), w in self.label.items() if x == a and w == "parent"}

    def sibs(self, a):
        by_parent = {c for c, ps in self.parents.items() if c != a and ps & self.par(a)}
        return by_parent | {b for (x, b), w in self.label.items() if x == a and w == "sibling"}

    def of(self, a, b):
        """What b is to a, or None."""
        k = (a, b)
        if k in self.memo:
            return self.memo[k]
        pa, pb = self.par(a), self.par(b)
        if b in pa:
            w = "parent"
        elif a in pb:
            w = "child"
        elif pa & pb or b in self.sibs(a):
            w = "sibling"
        elif any(b in self.sibs(p) for p in pa):
            w = "uncle/aunt"
        elif any(a in self.sibs(p) for p in pb):
            w = "niece/nephew"
        elif any(b in self.par(p) for p in pa):
            w = "grandparent"
        elif any(a in self.par(p) for p in pb):
            w = "grandchild"
        elif any(q in self.sibs(p) for p in pa for q in pb):
            w = "cousin"
        else:
            w = self.label.get((a, b))
        self.memo[k] = w
        return w

    def close(self, a, b):
        return self.of(a, b) in CLOSE


def census_at(census, ms):
    """The census row in force at wall time `ms` (the last taken at or before it)."""
    lo, hi = 0, len(census) - 1
    if ms <= census[0]["now_ms"]:
        return census[0]
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if census[mid]["now_ms"] <= ms:
            lo = mid
        else:
            hi = mid - 1
    return census[lo]


class Pairing:
    """Who is paired and who an actor's candidates are at a census row: unpaired adults alive
    then, not the actor and not the actor's close kin. Paired: co-parent of a child alive at that
    census (census parent links), or a seed sheet's wife, husband or partner label to someone
    alive (the only recorded agreement; the worlds keep no other)."""

    def __init__(self, k):
        self.k, self.smemo, self.cmemo = k, {}, {}

    def state(self, c):
        key = c["now_ms"]
        if key not in self.smemo:
            alive = {p["id"] for p in c["people"] if p["alive"]}
            pairs = {frozenset(s) for s in self.k.spouses if s <= alive}
            for p in c["people"]:
                ps = tuple(q for q in (p.get("parents") or ()) if q)
                if p["alive"] and len(ps) == 2 and set(ps) <= alive:
                    pairs.add(frozenset(ps))
            adults = [p["id"] for p in c["people"] if p["kind"] == "person" and p["alive"] and p["stage"] == 2]
            self.smemo[key] = (adults, pairs, {i for s in pairs for i in s})
        return self.smemo[key]

    def cands(self, c, actor):
        key = (c["now_ms"], actor)
        if key not in self.cmemo:
            adults, _, paired = self.state(c)
            self.cmemo[key] = frozenset(b for b in adults if b != actor and b not in paired and not self.k.close(actor, b))
        return self.cmemo[key]


def attempts(census, persons, seeded, t0_ms, rows, seed, args):
    """Every conceive act the minds decided (deliberation and talk replies alike): who, toward
    whom, what the target is to the actor, and how many others the actor could have asked at that
    moment: `candidates`, adults alive at the census in force who are not the actor's close kin and
    not paired. Paired: co-parent of a child alive at that census (census parent links), or a
    seed sheet's wife, husband or partner label to someone alive (the only recorded agreement;
    the worlds keep no other). Each attempt is classed `partner` (the target is paired with the
    actor), `close_kin`, or `other`. Per run: attempts, the share toward close kin, and the mean
    candidates the actor had at close-kin attempts against all attempts; `cand_series`, the
    unpaired adults and each adult's mean unrelated unpaired candidates every --every minutes; and
    the run-born generation: how many grew up, tried to conceive, toward whom, became parents, and
    their births."""
    k = Kin(persons, seed)
    at = lambda ms: round((ms - t0_ms) / 60_000, 1)  # noqa: E731
    born_ids = {i for i in persons if i not in seeded}

    pr = Pairing(k)
    state = pr.state

    def cands(c, actor):
        return len(pr.cands(c, actor))

    out = []
    for r in rows:
        if r.get("error") or r.get("purpose") not in ("deliberate", "talk"):
            continue
        for a in life_share.reply(r).get("acts") or []:
            if not isinstance(a, dict) or a.get("do") != "conceive":
                continue
            tgt = (a.get("target") or {}).get("id") if isinstance(a.get("target"), dict) else None
            ms = r.get("at_ms") or 0
            c = census_at(census, ms)
            actor = r["_id"]
            _, pairs, paired = state(c)
            rel = k.of(actor, tgt) if tgt in persons else None
            cls = "partner" if frozenset((actor, tgt)) in pairs else "close_kin" if rel in CLOSE else "other"
            out.append({"t": at(ms), "actor": actor, "target": tgt, "rel": rel, "cls": cls, "purpose": r.get("purpose"),
                        "cands": cands(c, actor), "actor_paired": actor in paired, "born": actor in born_ids})
    out.sort(key=lambda x: x["t"])
    name = lambda i: persons[i]["name"] if i in persons else f"#{i}"  # noqa: E731
    lines = [f"{x['t']}m {name(x['actor'])}{'*' if x['born'] else ''} -> {name(x['target']) if x['target'] else '?'} "
             f"[{x['cls']}{': ' + x['rel'] if x['rel'] else ''}] candidates {x['cands']} ({x['purpose']})" for x in out]

    series, nxt = [], 0
    for c in census:
        if (c["t"] or 0) >= nxt:
            adults, _, paired = state(c)
            free = [a for a in adults if a not in paired]
            per = [cands(c, a) for a in adults]
            series.append(f"{round((c['t'] or 0) / 60)}m:{len(free)}/{len(adults)}~{statistics.mean(per):.1f}" if adults else f"{round((c['t'] or 0) / 60)}m:0/0")
            nxt += args.every * 60

    # The run-born generation.
    grown = {p["id"] for c in census for p in c["people"] if p["id"] in born_ids and p["stage"] >= 2}
    kids = [p for i, p in persons.items() if i in born_ids]
    gen_parents = {q for p in kids for q in (p.get("parents") or ()) if q in born_ids}
    gen_pairs = Counter(frozenset(q for q in p["parents"] if q) for p in kids if any(q in born_ids for q in p.get("parents") or ()))
    gen = {
        "grown": len(grown), "tried": len({x["actor"] for x in out if x["born"]}),
        "attempts": Counter(x["cls"] for x in out if x["born"]),
        "toward_seeded": sum(1 for x in out if x["born"] and x["target"] in seeded),
        "parents": len(gen_parents), "couples": len(gen_pairs), "births": sum(gen_pairs.values()),
        "couples_close_kin": sum(1 for s in gen_pairs if len(s) == 2 and k.close(*s)),
    }
    n = len(out)
    ck = [x for x in out if x["cls"] == "close_kin"]
    return {
        "attempts": n, "to_partner": sum(x["cls"] == "partner" for x in out), "to_close_kin": len(ck),
        "close_kin_share": round(len(ck) / n, 3) if n else None,
        "cands_at_kin": round(statistics.mean(x["cands"] for x in ck), 1) if ck else None,
        "cands_at_all": round(statistics.mean(x["cands"] for x in out), 1) if out else None,
        "zero_cand_attempts": sum(x["cands"] == 0 for x in out),
        "born_grown": gen["grown"], "born_tried": gen["tried"], "born_parents": gen["parents"], "born_couples": gen["couples"],
        "_gen": gen, "_attempts": lines, "_cands": series, "_att": out,
    }


PARTNER = re.compile(r"\b(partner\w*|wife|husband|wed\w*|marr\w*|court\w*|sweetheart|beloved|lover|betroth\w*|my heart|hearth with|share my (?:hearth|house|home|life)|a life together|be together|start a family|family of (?:my|our) own)\b", re.I)
LONGING = re.compile(r"\b(long(?:s|ed|ing)? for|yearn\w*|ache for|wish(?:ed)? for a child|want(?:ed)? a child)\b", re.I)
LONG_PERCEPT = re.compile(r"\[(?:\d+\] )?day (\d+) (\d+:\d+)\]? You long for a child[^\n]*")
# Census activities by what they are for, for the run-born's time budget.
ACT_CLASS = {"sleep": "sleep", "gather": "work", "cook": "work", "store": "work", "take": "work", "give": "work", "teach": "work",
             "build": "work", "plant": "work", "keep": "work", "feed": "work", "craft": "work", "eat": "eat", "goto": "walk",
             "wait": "idle", "wander": "idle", "follow": "idle", "rest": "idle", None: "idle", "conceive": "family",
             "wave": "social", "nod": "social", "signal": "social", "offer": "social", "offer_terms": "social", "accept": "social",
             "host": "social", "read": "work"}
CAND_BINS = ((0, 0, "0"), (0.01, 2.99, "<3"), (3, 5.99, "3-6"), (6, 1e9, "6+"))


def strings(x, skip=("do", "nearest", "kind", "item", "believes")):
    """Every string in a reply, except act and selector words (`do: conceive` is not talk of children)."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k2, v in x.items():
            if k2 not in skip:
                yield from strings(v, skip)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v, skip)


def ids_in(x):
    """Ids a reply aims at: `target`/`to` ids and `{"id": n}` selectors."""
    if isinstance(x, dict):
        for k2, v in x.items():
            if k2 in ("id", "to") and isinstance(v, int):
                yield v
            else:
                yield from ids_in(v)
    elif isinstance(x, list):
        for v in x:
            yield from ids_in(v)


def scene_ids(r):
    """The creatures in the scene a request carried (`{"creatures": [...]}` under "What you perceive")."""
    for m in (r.get("request") or {}).get("messages") or []:
        t = m.get("content")
        if isinstance(t, str) and '{"creatures"' in t:
            i = t.find('{"creatures"')
            j = t.find("\n", i)
            try:
                return {c.get("id") for c in json.loads(t[i:j if j > 0 else None]).get("creatures") or []}
            except ValueError:
                return set()
    return set()


def prompt_text(r):
    return "\n".join(m["content"] for m in (r.get("request") or {}).get("messages") or [] if isinstance(m.get("content"), str))


def why_unpaired(census, persons, seeded, rows, seed, att, args):
    """Why the run-born do not pair (docs/MIND_RESEARCH_IDEAS.md #6), per run-born person who came
    of age: when (`adult_at`, real minutes from the run's start); their candidates while adult
    (`Pairing.cands` at each census: mean, peak, share of adult time with any, and a series); the
    share of their deliberations whose scene held a candidate; the longing percepts their prompts
    carried ("You long for a child…", one per game time) against their conceive attempts and the
    time from adulthood to the first; their deliberation and talk replies that name a candidate (by
    name or aimed id) or speak of partnering, longing or children (the printed lines show them);
    the body's refusals, by reason; their share of adult time on no mind (outside the census
    `thinkers`); and their time budget while adult (census activities by ACT_CLASS). Per run: how
    many came of age and how many ever tried, overall and by mean candidates while adult."""
    k = Kin(persons, seed)
    pr = Pairing(k)
    census_s = (census[1]["now_ms"] - census[0]["now_ms"]) / 1000 if len(census) > 1 else 0
    t_of = lambda c: (c["t"] or 0) / 60  # noqa: E731
    # Everyone who came of age in the run: the run-born, and seeded children (`seeded_child`).
    young0 = {p["id"] for p in census[0]["people"] if p["kind"] == "person" and p["stage"] < 2}
    born = sorted((i for i in persons if persons[i]["kind"] == "person" and (i not in seeded or i in young0)), key=lambda i: (persons[i]["born_ms"], i))
    by_actor = defaultdict(list)
    for r in rows:
        by_actor[r["_id"]].append(r)
    att_by = defaultdict(list)
    for x in att:
        att_by[x["actor"]].append(x)
    people, lines = [], []
    for i in born:
        adult = [c for c in census if any(p["id"] == i and p["alive"] and p["stage"] == 2 for p in c["people"])]
        if not adult:
            continue
        name = persons[i]["name"]
        adult_at = t_of(adult[0])
        cs = [len(pr.cands(c, i)) for c in adult]
        series, nxt = [], adult_at
        for c, n in zip(adult, cs):
            if t_of(c) >= nxt:
                series.append(f"{round(t_of(c))}m:{n}")
                nxt += args.every
        acts = Counter()
        unthought = 0
        for c in adult:
            p = next(p for p in c["people"] if p["id"] == i)
            acts[ACT_CLASS.get((p.get("activity") or [None])[0], "other")] += 1
            if c.get("thinkers") is not None and i not in c["thinkers"]:
                unthought += 1
        budget = {kk: round(v / len(adult), 2) for kk, v in acts.most_common()}
        delib = talk = scene_hit = 0
        mention = Counter()
        ex = []
        longing, refused = set(), Counter()
        seen_ref = set()
        first_long = None
        for r in sorted(by_actor.get(i, []), key=lambda r: r.get("at_ms") or 0):
            if r.get("error"):
                continue
            c = census_at(census, r.get("at_ms") or 0)
            me = next((p for p in c["people"] if p["id"] == i), None)
            text = prompt_text(r)
            for m in LONG_PERCEPT.finditer(text):
                if (m.group(1), m.group(2)) not in longing:
                    longing.add((m.group(1), m.group(2)))
                    first_long = first_long if first_long is not None else t_of(c)
            for m in REFUSED.finditer(text):
                key = (m.group(1), m.group(2), m.group(3))
                if key not in seen_ref:
                    seen_ref.add(key)
                    refused[re.sub(r"\d+", "#", m.group(3))] += 1
            if not me or me["stage"] != 2 or r.get("purpose") not in ("deliberate", "talk"):
                continue
            cands = pr.cands(c, i)
            if r["purpose"] == "deliberate":
                delib += 1
                scene_hit += bool(scene_ids(r) & cands)
            else:
                talk += 1
            rep = life_share.reply(r)
            words = " ".join(strings(rep))
            hit = []
            names = [persons[b]["name"] for b in cands if b in persons]
            if any(re.search(rf"\b{re.escape(n)}\b", words) or re.search(rf"\b{re.escape(n.split()[0])}\b", words) for n in names):
                hit.append("names_candidate")
            if set(ids_in(rep)) & cands:
                hit.append("aims_at_candidate")
            if PARTNER.search(words):
                hit.append("partnering")
            if LONGING.search(words):
                hit.append("longing")
            if CHILD.search(words):
                hit.append("children")
            for h in hit:
                mention[h] += 1
            if hit and len(ex) < args.mentions:
                ex.append(f"{round(t_of(c), 1)}m {r['purpose']} [{','.join(hit)}] {words[:160]}")
        mine = [x for x in att_by.get(i, []) if x["t"] >= adult_at - 0.5]
        rec = {
            "id": i, "name": name, "born": i not in seeded, "adult_at": round(adult_at), "adult_min": round(len(adult) * census_s / 60),
            "cands_mean": round(statistics.mean(cs), 1), "cands_max": max(cs), "with_cands": round(sum(n > 0 for n in cs) / len(cs), 2),
            "unthought": round(unthought / len(adult), 2), "deliberations": delib, "talk": talk,
            "scene_cand": round(scene_hit / delib, 2) if delib else None, "longing": len(longing),
            "first_longing": round(first_long) if first_long is not None else None,
            "attempts": len(mine), "to_first": round(mine[0]["t"] - adult_at) if mine else None,
            "mentions": dict(mention), "refused": dict(refused), "budget": budget,
        }
        people.append(rec)
        dash = lambda v: "-" if v is None else v  # noqa: E731
        lines.append(f"{name} (#{i}{'' if rec['born'] else ', seeded child'}) adult at {rec['adult_at']}m for {rec['adult_min']} min; candidates mean {rec['cands_mean']} max {rec['cands_max']} "
                     f"(any {rec['with_cands']}); no mind {rec['unthought']}; deliberations {delib} (scene with a candidate {rec['scene_cand']}), talk {talk}; "
                     f"longing {rec['longing']} (first {dash(rec['first_longing'])} m); attempts {rec['attempts']} (first {dash(rec['to_first'])} min after adulthood); "
                     f"mentions {rec['mentions']}; refused {rec['refused']}; time {budget}")
        lines.append(f"    candidates over time: {' '.join(series)}")
        lines += [f"    e.g. {x}" for x in ex]
    def tried_by(group):
        bins = {}
        for lo, hi, lab in CAND_BINS:
            g = [r for r in group if lo <= r["cands_mean"] <= hi]
            if g:
                bins[lab] = f"{sum(r['attempts'] > 0 for r in g)}/{len(g)}"
        return bins

    rb = [r for r in people if r["born"]]
    co = [r for r in people if not r["born"]]
    tried = [r for r in rb if r["attempts"]]
    scene = [r["scene_cand"] for r in rb if r["scene_cand"] is not None]
    return {
        "rb_adults": len(rb), "rb_tried": len(tried),
        "rb_tried_share": round(len(tried) / len(rb), 2) if rb else None, "rb_tried_by_cands": tried_by(rb),
        "rb_scene_cand": round(statistics.mean(scene), 2) if scene else None,
        "rb_longing": sum(r["longing"] for r in rb),
        "coa_adults": len(co), "coa_tried": sum(1 for r in co if r["attempts"]), "coa_tried_by_cands": tried_by(co),
        "_why": lines, "_people": people,
    }


def lineage(census, persons, seeded, t0_ms, rows, args, seed):
    """Who had the children, whether the run's own children had any, what refused the minds'
    conceive acts, how many grown people had no mind (the `minds.max` cap), hunger by stage, and
    the food in each store as the residents' scenes showed it."""
    at = lambda ms: round((ms - t0_ms) / 60_000, 1)  # noqa: E731
    parents = {i: tuple(p.get("parents") or (0, 0)) for i, p in persons.items()}
    name = lambda i: persons[i]["name"] if i in persons else f"#{i}"  # noqa: E731
    born = sorted((p for i, p in persons.items() if i not in seeded), key=lambda p: p["born_ms"])
    pairs = Counter(frozenset(parents[p["id"]]) for p in born)

    k = Kin(persons, seed)
    kin_births = [p for p in born if len(parents[p["id"]]) == 2 and k.close(*parents[p["id"]])]
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
    ap.add_argument("--attempts", type=int, default=1000, help="print at most so many conceive attempts per run")
    ap.add_argument("--mentions", type=int, default=3, help="example replies per run-born adult that name a candidate or speak of partnering, longing or children")
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
            print(f"   {r['run']} unpaired/adults~candidates per adult: {' '.join(r['_cands'])}")
            g = r["_gen"]
            print(f"   {r['run']} run-born: grown {g['grown']}, tried {g['tried']} (attempts {dict(g['attempts'])}, toward seeded {g['toward_seeded']}), "
                  f"parents {g['parents']}, couples {g['couples']} (close kin {g['couples_close_kin']}), births {g['births']}")
            for x in r["_attempts"][:a.attempts]:
                print(f"   attempt: {x}")
            print(f"   {r['run']} run-born adults: {r['rb_adults']}, ever tried {r['rb_tried']}; tried by mean candidates while adult: {r['rb_tried_by_cands']}; "
                  f"seeded children come of age: {r['coa_adults']}, tried {r['coa_tried']} {r['coa_tried_by_cands']}")
            for x in r["_why"]:
                print(f"   why: {x}")
            for sid, ser in r["_stores"].items():
                print(f"   {r['run']} store #{sid} food (latest scene within 15 min): {ser}")
            for k, xs in r["_ex"].items():
                for x in xs[:a.examples]:
                    print(f"   e.g. {k}: {x}")


if __name__ == "__main__":
    main()
