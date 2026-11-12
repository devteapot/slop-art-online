#!/usr/bin/env python3
"""The pack arena's measures (docs/PACK_MIND.md §5), read from trial instance folders.

  living/tools/pack_arena.py report DIR... [--json OUT] [--control ARM]
  living/tools/pack_arena.py selftest

Each DIR is a trial instance folder (or a batch folder: its instances are read) written by
`trials.py run` with `record.bodies` (5 Hz `bodies.jsonl`) and `record.uses` (`uses.jsonl`). The
trial's `arena` field names the roles: `{"people": "subject", "wolves": "pack"}`; `arena.night`
says the light (day sight 11 m, night 6 m). Read-only.

Measures, as defined in docs/PACK_MIND.md §5.3–5.4 (r_c 3.5 m, engagement gap 20 s):
  M1 coordinated approach (S2, S3, coordinated share, holding share);
  M2 flanking (coverage, concentration R, encircled share, rear-blow share);
  M3 isolation (selection index I, cut-offs per engagement-minute, focus);
  M4 people grouping (G before and after the first wolf in sight, standing together, assists);
  M5 casualties (deaths by side, health lost, wolves routed);
  M6 duration (first blow to the end, start to first blow).
Arms are trial names; `report` gives each instance and, per arm, the median and the range, and
with `--control` the decision rule of §5.5 (an arm differs on a measure when its median lies
outside the control's range and at least 2/3 of its replicates do).
"""
import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

R_C = 3.5          # contact ring: attack reach 1.4 + wolf lunge 1.8, rounded up
FAR = 10.0         # an approach starts at the last time at least this far
GAP_S = 20.0       # engagement ends after this long without a wolf blow on the target
COORD_S = 3.0      # coordinated: second arrival within this of the first
HOLD_BAND = (4.0, 10.0)
HOLD_S = 2.0
FLANK_R = 6.0
BLOCK_ARC = math.radians(75)
ISO_M = 8.0
NEAR_WOLF = 15.0
CUT_FROM, CUT_TO, CUT_WOLF = 5.0, 10.0, 8.0
CUT_ANGLE = math.radians(45)
LINK = 4.0
SIGHT = {False: 11.0, True: 6.0}
AWAY_M, AWAY_S = 30.0, 30.0
PEOPLE_BLOWS = {"strike", "attack", "throw", "bowshot", "firebolt", "shoot"}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def coverage(bearings):
    """360° less the largest circular gap between consecutive bearings (degrees); for two,
    the angle between them."""
    if len(bearings) < 2:
        return 0.0
    b = sorted(x % (2 * math.pi) for x in bearings)
    gaps = [b[i + 1] - b[i] for i in range(len(b) - 1)] + [b[0] + 2 * math.pi - b[-1]]
    return math.degrees(2 * math.pi - max(gaps))


def concentration(bearings):
    return math.hypot(sum(math.cos(x) for x in bearings), sum(math.sin(x) for x in bearings)) / len(bearings)


def clusters(points):
    """Single-linkage clusters with link LINK: {id: size of its cluster}."""
    ids = list(points)
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if dist(points[ids[i]], points[ids[j]]) <= LINK:
                parent[find(ids[i])] = find(ids[j])
    size = defaultdict(int)
    for i in ids:
        size[find(i)] += 1
    return {i: size[find(i)] for i in ids}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


# ---- reading an instance ---------------------------------------------------------------

def load(d):
    d = Path(d)
    meta = json.loads((d / "arena.json").read_text())
    trial = {"name": meta["trial"], "arena": meta.get("arena") or {}, "variant": meta.get("variant")}
    state = {"roles": meta["roles"]}
    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    arena = trial.get("arena", {"people": "subject", "wolves": "pack"})
    roles = state.get("roles", {})
    people = [int(i) for i in roles.get(arena.get("people", "subject"), [])]
    wolves = [int(i) for i in roles.get(arena.get("wolves", "pack"), [])]
    samples = []
    for line in (d / "bodies.jsonl").read_text().splitlines():
        r = json.loads(line)
        samples.append({"ms": r["ms"], "pos": {int(k): v for k, v in r["b"].items()}, "dead": {int(k): v for k, v in r.get("dead", {}).items()},
                        "hp": {int(k): v for k, v in r.get("hp", {}).items()}, "act": {int(k): v for k, v in r.get("act", {}).items()}})
    samples.sort(key=lambda s: s["ms"])
    uses = {}
    if (d / "uses.jsonl").exists():
        for line in (d / "uses.jsonl").read_text().splitlines():
            r = json.loads(line)
            uses[r["id"]] = r
    return {"dir": str(d), "trial": trial, "arm": f"{trial['name']}/{trial['variant']}", "summary": summary,
            "people": people, "wolves": wolves, "samples": samples, "uses": list(uses.values()), "night": bool(arena.get("night"))}


def at(samples, ms):
    """The sample nearest `ms` (index)."""
    lo, hi = 0, len(samples) - 1
    while lo < hi:
        m = (lo + hi) // 2
        if samples[m]["ms"] < ms:
            lo = m + 1
        else:
            hi = m
    if lo > 0 and abs(samples[lo - 1]["ms"] - ms) < abs(samples[lo]["ms"] - ms):
        lo -= 1
    return lo


def living(s, ids):
    return {i: s["pos"][i] for i in ids if i in s["pos"] and i not in s["dead"]}


def d_iso(s, p, people):
    here = living(s, people)
    if p not in here:
        return None
    others = [dist(here[p], q) for i, q in here.items() if i != p]
    return min(others) if others else math.inf


# ---- the measures ------------------------------------------------------------------------

def measure(run):
    S, P, W = run["samples"], set(run["people"]), set(run["wolves"])
    out = {"dir": run["dir"], "arm": run["arm"], "stopped_by": run["summary"].get("stopped_by"), "samples": len(S)}
    if not S:
        return out
    t0 = S[0]["ms"]
    blows = [u for u in run["uses"] if u.get("accepted_ms")]
    wolf_blows = sorted([u for u in blows if u["actor"] in W and u["target"] in P and u["skill"] == "attack"], key=lambda u: u["accepted_ms"])
    people_blows = sorted([u for u in blows if u["actor"] in P and u["target"] in W and u["skill"] in PEOPLE_BLOWS], key=lambda u: u["accepted_ms"])
    out["wolf_blows"], out["people_blows"] = len(wolf_blows), len(people_blows)

    # Engagements: per target, wolf blows no more than GAP_S apart.
    engagements = []
    by_target = defaultdict(list)
    for u in wolf_blows:
        by_target[u["target"]].append(u)
    for p, us in by_target.items():
        cur = None
        for u in us:
            if cur and u["accepted_ms"] - cur["last"] <= GAP_S * 1000:
                cur["blows"].append(u)
                cur["last"] = u["accepted_ms"]
            else:
                cur = {"p": p, "start": u["accepted_ms"], "last": u["accepted_ms"], "blows": [u]}
                engagements.append(cur)
    for e in engagements:
        death = next((s["ms"] for s in S if e["p"] in s["dead"] and s["ms"] >= e["start"]), None)
        e["end"] = min(e["last"] + GAP_S * 1000, death or math.inf, S[-1]["ms"])
        e["wolves"] = sorted({u["actor"] for u in e["blows"]})
    out["engagements"] = len(engagements)

    # M1: arrivals.
    m1 = []
    holding, hold_n = 0, 0
    close_start = False
    for e in engagements:
        p = e["p"]
        arrivals = []
        for w in e["wolves"]:
            tb = min(u["accepted_ms"] for u in e["blows"] if u["actor"] == w)
            ib = at(S, tb)
            far = None
            for i in range(ib, -1, -1):
                a, b = S[i]["pos"].get(w), S[i]["pos"].get(p)
                if a and b and dist(a, b) >= FAR:
                    far = i
                    break
            if far is None:
                close_start = True
                far = 0
            arr = next((i for i in range(far, ib + 1) if S[i]["pos"].get(w) and S[i]["pos"].get(p) and dist(S[i]["pos"][w], S[i]["pos"][p]) <= R_C), ib)
            arrivals.append(S[arr]["ms"])
            # Holding: 2 s or more in the 4-10 m band before arriving.
            run_ms, best = None, 0
            for i in range(far, arr + 1):
                a, b = S[i]["pos"].get(w), S[i]["pos"].get(p)
                inb = a and b and HOLD_BAND[0] <= dist(a, b) <= HOLD_BAND[1]
                if inb:
                    run_ms = run_ms if run_ms is not None else S[i]["ms"]
                    best = max(best, S[i]["ms"] - run_ms)
                else:
                    run_ms = None
            hold_n += 1
            holding += best >= HOLD_S * 1000
        arrivals.sort()
        if len(arrivals) >= 2:
            m1.append({"S2": (arrivals[1] - arrivals[0]) / 1000, "S3": (arrivals[2] - arrivals[0]) / 1000 if len(arrivals) >= 3 else None})
    out["M1"] = {"multi_wolf_engagements": len(m1), "coordinated_share": round(sum(x["S2"] <= COORD_S for x in m1) / len(m1), 3) if m1 else None,
                 "S2_median_s": med([x["S2"] for x in m1]), "S3_median_s": med([x["S3"] for x in m1]),
                 "holding_share": round(holding / hold_n, 3) if hold_n else None, "close_start": close_start}

    # M2: bearings round the target during each engagement.
    cov_by_k, conc_by_k = defaultdict(list), defaultdict(list)
    enc, enc_n = 0, 0
    per_e_cov = []
    for e in engagements:
        p = e["p"]
        covs = []
        for s in S[at(S, e["start"]):at(S, e["end"]) + 1]:
            if p not in s["pos"] or p in s["dead"]:
                continue
            c = s["pos"][p]
            bs = [math.atan2(q[1] - c[1], q[0] - c[0]) for w, q in living(s, W).items() if dist(q, c) <= FLANK_R]
            k = len(bs)
            if k >= 2:
                kk = min(k, 4)
                cov_by_k[kk].append(coverage(bs))
                conc_by_k[kk].append(concentration(bs))
                covs.append(coverage(bs))
                if k >= 3:
                    enc_n += 1
                    enc += coverage(bs) >= 180.0
        if covs:
            per_e_cov.append(statistics.median(covs))
    rear, rear_n = 0, 0
    for u in wolf_blows:
        ms = u.get("released_ms") or (u["accepted_ms"] + 550)
        s = S[at(S, ms)]
        p, w = u["target"], u["actor"]
        if p in s["pos"] and w in s["pos"] and not s["pos"][p][3]:
            c, q = s["pos"][p], s["pos"][w]
            if dist(c, q) < 1e-3:
                continue
            rear_n += 1
            rear += abs(wrap(math.atan2(q[1] - c[1], q[0] - c[0]) - c[2])) > BLOCK_ARC
    out["M2"] = {"coverage_deg_median_by_k": {str(k): med(v) for k, v in sorted(cov_by_k.items())},
                 "R_median_by_k": {str(k): med(v) for k, v in sorted(conc_by_k.items())},
                 "engagement_coverage_median": med(per_e_cov),
                 "encircled_share_k3": round(enc / enc_n, 3) if enc_n else None,
                 "rear_blow_share": round(rear / rear_n, 3) if rear_n else None, "rear_blows_counted": rear_n}

    # M3: isolation.
    iso_blows = [d_iso(S[at(S, u["accepted_ms"])], u["target"], P) for u in wolf_blows]
    iso_blows = [x for x in iso_blows if x is not None]
    exposed, exposed_iso = 0, 0
    for s in S:
        lp, lw = living(s, P), living(s, W)
        for p, c in lp.items():
            if any(dist(c, q) <= NEAR_WOLF for q in lw.values()):
                exposed += 1
                x = d_iso(s, p, P)
                exposed_iso += x is not None and x >= ISO_M
    share_blows = sum(x >= ISO_M for x in iso_blows) / len(iso_blows) if iso_blows else None
    share_time = exposed_iso / exposed if exposed else None
    index = round(share_blows / share_time, 3) if share_blows is not None and share_time else None
    cuts = 0
    for p in P:
        armed = False
        for s in S:
            x = d_iso(s, p, P)
            if x is None:
                continue
            if x <= CUT_FROM:
                armed = True
            elif x >= CUT_TO and armed:
                armed = False
                c = s["pos"][p]
                others = [q for i, q in living(s, P).items() if i != p]
                if not others:
                    continue
                cen = (sum(q[0] for q in others) / len(others), sum(q[1] for q in others) / len(others))
                toward = math.atan2(cen[1] - c[1], cen[0] - c[0])
                for q in living(s, W).values():
                    if dist(c, q) <= CUT_WOLF and abs(wrap(math.atan2(q[1] - c[1], q[0] - c[0]) - toward)) <= CUT_ANGLE:
                        cuts += 1
                        break
    eng_min = sum(e["end"] - e["start"] for e in engagements) / 60000
    focus = []
    if wolf_blows:
        start = wolf_blows[0]["accepted_ms"]
        bins = defaultdict(list)
        for u in wolf_blows:
            bins[int((u["accepted_ms"] - start) // (GAP_S * 1000))].append(u)
        for us in bins.values():
            if len(us) < 2:
                continue
            top = max(sum(u["target"] == t for u in us) for t in {u["target"] for u in us}) / len(us)
            near = set()
            for u in us:
                s = S[at(S, u["accepted_ms"])]
                for w in {v["actor"] for v in us}:
                    if w in s["pos"]:
                        near |= {p for p, c in living(s, P).items() if dist(c, s["pos"][w]) <= FLANK_R}
            n = max(1, len(near))
            focus.append(top * n)
    out["M3"] = {"selection_index": index, "blows_on_isolated_share": round(share_blows, 3) if share_blows is not None else None,
                 "isolated_time_share": round(share_time, 3) if share_time is not None else None,
                 "cutoffs_per_engagement_min": round(cuts / eng_min, 3) if eng_min > 0 else None, "cutoffs": cuts,
                 "focus_over_chance_median": med(focus)}

    # M4: grouping.
    G = []
    for s in S:
        lp = living(s, P)
        if lp:
            sz = clusters(lp)
            G.append((s["ms"], statistics.mean(sz.values()) / len(lp)))
    sight = SIGHT[run["night"]]
    seen = next((s["ms"] for s in S if any(dist(c, q) <= sight for c in living(s, P).values() for q in living(s, W).values())), None)
    dG = None
    if seen is not None and G:
        before = [g for ms, g in G if seen - 30000 <= ms < seen]
        if not before and seen - G[0][0] <= 2000:
            # In sight from the start (close starts, §5.6): "before" is G at the first sample.
            before = [G[0][1]]
        after = [g for ms, g in G if seen < ms <= seen + 30000]
        if before and after:
            dG = round(statistics.median(after) - statistics.median(before), 3)
    together = []
    for u in wolf_blows:
        s = S[at(S, u["accepted_ms"])]
        x = d_iso(s, u["target"], P)
        if x is not None:
            together.append(x <= LINK)
    assists, assist_n = 0, 0
    for u in people_blows:
        s = S[at(S, u["accepted_ms"])]
        a = s["act"].get(u["target"])
        if a and a[1] in P:
            assist_n += 1
            assists += a[1] != u["actor"]
    out["M4"] = {"first_wolf_in_sight_s": round((seen - t0) / 1000, 1) if seen else None, "dG": dG,
                 "G_median": med([g for _, g in G]), "standing_together_share": round(sum(together) / len(together), 3) if together else None,
                 "assist_rate": round(assists / assist_n, 3) if assist_n else None, "people_blows_on_engaged_wolves": assist_n}

    # M5: casualties.
    last = S[-1]
    dead_people = {i: c for i, c in last["dead"].items() if i in P}
    dead_wolves = {i: c for i, c in last["dead"].items() if i in W}
    # Health lost to blows, from the blows' own outcomes ("hit for 8"); and to every cause, from
    # the sampled health (clamped to the body's range: the rate projection can overshoot full).
    lost = {"people": 0.0, "wolves": 0.0}
    for u in blows:
        o = u.get("outcome") or ""
        if o.startswith("hit for "):
            try:
                n = float(o.split()[2].rstrip(".,;:"))
            except (IndexError, ValueError):
                continue
            if u["target"] in P:
                lost["people"] += n
            elif u["target"] in W:
                lost["wolves"] += n
    lost_all = {"people": 0.0, "wolves": 0.0}
    prev = {}
    for s in S:
        for i, v in s["hp"].items():
            hp = max(0.0, min(v[0], v[1]))
            if i in prev and hp < prev[i]:
                lost_all["people" if i in P else "wolves"] += prev[i] - hp
            prev[i] = hp
    routed = {w for s in S for w, a in s["act"].items() if w in W and a[0] == "flee" and w in s["hp"] and s["hp"][w][0] < 0.25 * s["hp"][w][1]}
    out["M5"] = {"people_killed_by_wolves": sum("wolf" in (c or "") for c in dead_people.values()), "people_dead": len(dead_people),
                 "wolves_dead": len(dead_wolves), "people_health_lost": round(lost["people"], 1), "wolf_health_lost": round(lost["wolves"], 1),
                 "people_health_lost_all_causes": round(lost_all["people"], 1), "wolf_health_lost_all_causes": round(lost_all["wolves"], 1),
                 "wolves_routed": len(routed)}

    # M6: duration.
    firsts = [u["accepted_ms"] for u in wolf_blows + people_blows]
    if firsts:
        first = min(firsts)
        end, why = last["ms"], "run end"
        away_since = None
        for s in S:
            if s["ms"] < first:
                continue
            lp, lw = living(s, P), living(s, W)
            if not lp or not lw:
                end, why = s["ms"], "people all dead" if not lp else "wolves all dead"
                break
            apart = all(dist(c, q) > AWAY_M for c in lp.values() for q in lw.values())
            if apart:
                away_since = away_since or s["ms"]
                if s["ms"] - away_since >= AWAY_S * 1000:
                    end, why = away_since, "sides apart"
                    break
            else:
                away_since = None
        out["M6"] = {"to_first_blow_s": round((first - t0) / 1000, 1), "duration_s": round((end - first) / 1000, 1), "ended_by": why}
    else:
        out["M6"] = {"to_first_blow_s": None, "duration_s": None, "ended_by": "no blow"}
    return out


# ---- arms and the decision rule ------------------------------------------------------------

KEYS = [("M1", "coordinated_share"), ("M1", "S2_median_s"), ("M1", "holding_share"), ("M2", "engagement_coverage_median"),
        ("M2", "encircled_share_k3"), ("M2", "rear_blow_share"), ("M3", "selection_index"), ("M3", "cutoffs_per_engagement_min"),
        ("M3", "focus_over_chance_median"), ("M4", "dG"), ("M4", "standing_together_share"), ("M4", "assist_rate"),
        ("M5", "people_killed_by_wolves"), ("M5", "wolves_dead"), ("M5", "people_health_lost"), ("M5", "wolf_health_lost"),
        ("M6", "to_first_blow_s"), ("M6", "duration_s")]


def arms(results):
    by = defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    table = {}
    for arm, rs in by.items():
        row = {"n": len(rs), "engagements": [r.get("engagements", 0) for r in rs]}
        for m, k in KEYS:
            vals = [r.get(m, {}).get(k) for r in rs]
            have = [v for v in vals if v is not None]
            row[f"{m}.{k}"] = {"median": med(have), "min": min(have) if have else None, "max": max(have) if have else None, "values": vals}
        table[arm] = row
    return table


def decide(table, control):
    c = table.get(control)
    if not c:
        return {}
    out = {}
    for arm, row in table.items():
        if arm == control:
            continue
        d = {}
        for key, v in row.items():
            if not isinstance(v, dict) or v.get("median") is None or c[key].get("min") is None:
                continue
            lo, hi = c[key]["min"], c[key]["max"]
            vals = [x for x in v["values"] if x is not None]
            outside = [x for x in vals if x < lo or x > hi]
            d[key] = (v["median"] < lo or v["median"] > hi) and len(outside) >= math.ceil(2 * len(vals) / 3)
        out[arm] = d
    return out


def instances(paths):
    for p in paths:
        p = Path(p)
        if (p / "bodies.jsonl").exists():
            yield p
        else:
            for q in sorted(p.iterdir()):
                if q.is_dir() and (q / "bodies.jsonl").exists() and (q / "arena.json").exists():
                    yield q


def report(a):
    results = [measure(load(d)) for d in instances(a.dirs)]
    table = arms(results)
    out = {"instances": results, "arms": table}
    if a.control:
        out["differs_from_control"] = decide(table, a.control)
    for arm, row in sorted(table.items()):
        print(f"\n== {arm} (n={row['n']}, engagements {row['engagements']})")
        for m, k in KEYS:
            v = row[f"{m}.{k}"]
            print(f"  {m}.{k:28s} median {v['median']!s:>8}  range {v['min']!s}..{v['max']!s}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
        print("\nwrote", a.json)


# ---- self-test ---------------------------------------------------------------------------

def selftest(_a=None):
    rng = random.Random(7)
    ok = True

    def check(name, cond, got):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name, got)
        ok &= bool(cond)
    # The random-bearing nulls of §5.4: E[coverage] = 360 - E[largest gap], E[largest gap] =
    # 360/k * H_k for k uniform points on a circle.
    for k, want in ((2, 90.0), (3, 140.0), (4, 172.5)):
        got = statistics.mean(coverage([rng.uniform(0, 2 * math.pi) for _ in range(k)]) for _ in range(40000))
        check(f"random-bearing coverage null k={k} ~ {want}", abs(got - want) < 2.0, round(got, 1))
    for k, want in ((2, 180.0), (3, 240.0), (4, 270.0)):
        got = coverage([2 * math.pi * i / k + 0.3 for i in range(k)])
        check(f"even ring coverage k={k} = {want}", abs(got - want) < 1e-6, round(got, 1))
    check("one side: concentration ~1", concentration([0.0, 0.05, -0.05]) > 0.99, round(concentration([0.0, 0.05, -0.05]), 3))
    check("rear share null 210/360", abs((360 - 150) / 360 - 0.583) < 0.001, round(210 / 360, 3))
    check("clusters: 4 m link", clusters({1: (0, 0), 2: (3, 0), 3: (6.5, 0), 4: (20, 0)}) == {1: 3, 2: 3, 3: 3, 4: 1}, "")
    # A synthetic run: three wolves come in from 120° apart to a standing person, arrive 1 s
    # apart, bite; a second person stands 12 m off (isolated).
    S = []
    for i in range(0, 200):
        ms = 1_000_000 + i * 200
        pos = {1: [0.0, 0.0, 0.0, False], 2: [12.0, 0.0, math.pi, False]}
        for j, w in enumerate((11, 12, 13)):
            ang = 2 * math.pi * j / 3 + 1.0
            start = 2000 + 1000 * j
            r = max(2.0, 20.0 - 5.0 * max(0, ms - 1_000_000 - start) / 1000)
            pos[w] = [r * math.cos(ang), r * math.sin(ang), 0.0, True]
        S.append({"ms": ms, "pos": pos, "dead": {}, "hp": {}, "act": {}})
    uses = []
    uid = 0
    for j, w in enumerate((11, 12, 13)):
        for n in range(5):
            uid += 1
            t = 1_000_000 + 2000 + 1000 * j + 4000 + n * 1500
            uses.append({"id": uid, "actor": w, "target": 1, "skill": "attack", "accepted_ms": t, "released_ms": t + 550})
    run = {"dir": "synthetic", "arm": "synthetic", "summary": {}, "people": [1, 2], "wolves": [11, 12, 13], "samples": S, "uses": uses, "night": False}
    m = measure(run)
    check("synthetic: one engagement of three wolves", m["engagements"] == 1, m["engagements"])
    check("synthetic: coordinated (arrivals 1 s apart)", m["M1"]["coordinated_share"] == 1.0 and abs(m["M1"]["S2_median_s"] - 1.0) < 0.3, m["M1"])
    check("synthetic: ring coverage ~240", abs(m["M2"]["engagement_coverage_median"] - 240) < 5, m["M2"]["engagement_coverage_median"])
    check("synthetic: encircled share 1", m["M2"]["encircled_share_k3"] == 1.0, m["M2"]["encircled_share_k3"])
    check("synthetic: blows on the isolated person only", m["M3"]["blows_on_isolated_share"] == 1.0, m["M3"])
    print("selftest", "ok" if ok else "FAILED")
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("dirs", nargs="+")
    r.add_argument("--json")
    r.add_argument("--control")
    sub.add_parser("selftest")
    a = p.parse_args()
    if a.cmd == "report":
        report(a)
    else:
        sys.exit(selftest(a))


if __name__ == "__main__":
    main()
