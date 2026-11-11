#!/usr/bin/env python3
"""Measure a whole world's people over game days (docs/SEEDED_LIVES.md, "Measured on the
Spark"): who dies of what, how in step people are, how much of their time goes to more than
getting by, what their minds cost, and short timelines of sampled people.

    lives_lab.py sample --url URL --db DB --container C --out DIR --minutes M [--every 10]
    lives_lab.py analyze DIR [--journal JOURNAL_DIR] [--people 10]

`sample` reads the authority as the database owner (the token from the container's CLI, kept
in memory) every `--every` real seconds: the clock, every person's activity, vitals and body,
and each minute the characters and the weather; at the end the chronicle, the thoughts, the
places and the rhythms. Rows go to DIR/samples.jsonl (gzipped at the end) and DIR/final.json.
It calls no reducer. `analyze` reads those and, with `--journal`, the mind service's journal,
and writes DIR/report.json and DIR/report.md.

Definitions (game time; the world's day is `world.day_ms`, 12 real minutes on the island):
- sheltered: the body's need-rate key says it is near shelter (`vitals.rate_key` bit 7);
- shelter entry at dusk: for each game day and each living adult, the first sample from 16:00
  on at which it is sheltered (people already sheltered at 16:00 are left out of the spread);
- in step: per pair of samples, the share of people whose activity changed; and per sample,
  the share doing the most common activity;
- time use: each sample's activity by its routine label and skill: sleep, survival (eating,
  getting food, keeping warm or dry, staying safe), work (the occupation's routine and making
  skills), social (gestures, speech, teaching, giving, hosting, evenings out), other.
"""

import argparse
import gzip
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "living/tools"))


# ---- sampling ---------------------------------------------------------------------------

def token_of(container):
    out = subprocess.run(["docker", "exec", container, "spacetime", "login", "show", "--token"], capture_output=True, text=True, check=True).stdout
    m = re.search(r"is (\S+)\s*$", out.strip())
    if not m:
        sys.exit("no admin token from the container's CLI")
    return m.group(1)


class Db:
    def __init__(self, url, db, token):
        self.url, self.db, self.token = url.rstrip("/"), db, token

    def sql(self, q):
        req = urllib.request.Request(f"{self.url}/v1/database/{self.db}/sql", data=q.encode(), method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, row)) for row in res["rows"]]


def sample(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Db(a.url, a.db, token_of(a.container))
    world = db.sql("SELECT * FROM world")[0]
    (out / "world.json").write_text(json.dumps(world, indent=1))
    people = None
    end = time.time() + a.minutes * 60
    n = 0
    with open(out / "samples.jsonl", "a") as f:
        while time.time() < end:
            t0 = time.time()
            try:
                row = {"t": t0, "clock": db.sql("SELECT last_ms FROM clock")[0]["last_ms"]}
                if people is None or n % max(1, round(60 / a.every)) == 0:
                    people = db.sql("SELECT id, name, kind, alive, ai, stage, home_x, home_y, died_ms, cause, controller FROM character")
                    row["characters"] = people
                    row["weather"] = db.sql("SELECT * FROM weather")
                row["activity"] = db.sql("SELECT id, skill, label, phase, item, started_ms FROM activity")
                row["vitals"] = db.sql("SELECT id, hp, hunger, energy, rate_key, at_ms, hp_rate, hunger_rate, energy_rate FROM vitals")
                row["body"] = db.sql("SELECT id, x, y, t_ms, vx, vy, next_ms FROM body")
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
                f.flush()
                n += 1
            except Exception as e:  # noqa: BLE001 - a missed sample is noted, the run goes on
                print(f"sample failed: {e}", flush=True)
            time.sleep(max(0.0, a.every - (time.time() - t0)))
    final = {}
    for name, q in (("chronicle", "SELECT * FROM chronicle"), ("thought", "SELECT id, actor, at_ms, kind, summary, model, tokens FROM thought"),
                    ("place", "SELECT * FROM place"), ("rhythm", "SELECT * FROM rhythm"), ("stats", "SELECT * FROM stats"),
                    ("persona", "SELECT * FROM persona"), ("character", "SELECT * FROM character"), ("background", "SELECT * FROM background")):
        try:
            final[name] = db.sql(q)
        except Exception as e:  # noqa: BLE001 - a table missing on one arm (main has no rhythm)
            final[name] = {"error": str(e)[:300]}
    (out / "final.json").write_text(json.dumps(final))
    subprocess.run(["gzip", "-f", str(out / "samples.jsonl")], check=False)
    print(f"{n} samples in {out}")


# ---- analysis ---------------------------------------------------------------------------

def load_samples(d):
    p = d / "samples.jsonl.gz"
    opener = gzip.open if p.exists() else open
    p = p if p.exists() else d / "samples.jsonl"
    with opener(p, "rt") as f:
        return [json.loads(l) for l in f if l.strip()]


def game(world, ms):
    """(day, hour) of the world at `ms` (rules/src/lib.rs `hour_of`, `day_of`)."""
    dm = world["day_ms"]
    t = max(0, ms - world["epoch_ms"]) + dm * 7 // 24
    return t // dm + 1, (t % dm) / dm * 24.0


def pos(b, now):
    """A body's position now from its segment (`common::pos`, straight-line part)."""
    if not b.get("vx") and not b.get("vy"):
        return b["x"], b["y"]
    t = max(0, min(now, b.get("next_ms") or now) - b["t_ms"]) / 1000.0
    return b["x"] + b["vx"] * t, b["y"] + b["vy"] * t


SURVIVAL_ROUTINES = ("find food", "eat", "keep warm", "get out of the rain", "stay safe", "flee", "shelter", "warm")
SOCIAL_SKILLS = {"wave", "nod", "face", "step_aside", "play", "teach", "give", "offer", "accept", "host", "talk", "say", "welcome", "join", "tend", "heal", "conceive", "follow"}
WORK_SKILLS = {"keep", "craft", "build", "cook", "smoke", "store", "pave", "clear", "write", "read", "plant", "experiment", "take", "gather", "carry", "trade"}


def classify(act, food_items):
    skill = (act or {}).get("skill") or ""
    label = ((act or {}).get("label") or "").lower()
    if not skill:
        return "idle"
    if skill == "sleep":
        return "sleep"
    if skill == "eat" or (skill in ("gather", "take") and (act.get("item") in food_items or "food" in label)) or any(k in label for k in SURVIVAL_ROUTINES) or skill in ("flee", "yield"):
        return "survival"
    if "evening" in label or "people" in label or "greeting" in label or "partner" in label or skill in SOCIAL_SKILLS:
        return "social"
    if skill in WORK_SKILLS or "work" in label or "tend the" in label:
        return "work"
    return "other"


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def analyze(a):
    d = Path(a.dir)
    world = json.loads((d / "world.json").read_text())
    S = load_samples(d)
    final = json.loads((d / "final.json").read_text())
    chars = {}
    for s in S:
        for c in s.get("characters", []):
            chars[c["id"]] = c
    for c in (final.get("character") if isinstance(final.get("character"), list) else []):
        chars[c["id"]] = c
    persons = {i for i, c in chars.items() if c["kind"] == "person"}
    adults = {i for i in persons if chars[i]["stage"] >= 2}
    food = {"berries", "fish", "meat", "cooked_fish", "cooked_meat", "smoked_fish", "smoked_meat", "food"}
    rep = {"dir": str(d), "samples": len(S)}
    if not S:
        sys.exit("no samples")
    t0, t1 = S[0]["clock"], S[-1]["clock"]
    (d0, h0), (d1, h1) = game(world, t0), game(world, t1)
    rep["real_minutes"] = round((S[-1]["t"] - S[0]["t"]) / 60, 1)
    rep["game_days"] = round((t1 - t0) / world["day_ms"], 2)
    rep["from"], rep["to"] = f"day {d0} {h0:05.2f}", f"day {d1} {h1:05.2f}"
    first_alive = {c["id"] for c in S[0].get("characters", []) if c["alive"] and c["kind"] == "person"}
    rep["people_at_start"] = len(first_alive)
    # Deaths during the window, by cause.
    deaths = [c for c in chars.values() if c["kind"] == "person" and not c["alive"] and c.get("died_ms") and t0 <= c["died_ms"] <= t1 + 60_000]
    rep["deaths"] = dict(Counter(c.get("cause") or "?" for c in deaths))
    rep["deaths_starvation"] = sum(1 for c in deaths if c.get("cause") == "starvation")
    rep["deaths_cold"] = sum(1 for c in deaths if c.get("cause") == "cold and exposure")
    rep["births"] = sum(1 for c in chars.values() if c["kind"] == "person" and c["id"] not in first_alive and c["alive"])

    # Shelter entry at dusk.
    by_day = defaultdict(dict)  # day -> id -> entry hours after 16:00
    sheltered_at_16 = defaultdict(set)
    last_hour = {}
    for s in S:
        day, hour = game(world, s["clock"])
        h = hour if hour >= 16 else hour + 24  # 16..30
        dusk_day = day if hour >= 16 else day - 1
        if not 16 <= h < 30:
            continue
        alive = {c["id"] for c in s.get("characters", [])} or None
        for v in s["vitals"]:
            i = v["id"]
            if i not in adults:
                continue
            sheltered = bool(v["rate_key"] & 128)
            first = i not in by_day[dusk_day] and i not in sheltered_at_16[dusk_day]
            if first and sheltered:
                if last_hour.get((dusk_day, i)) is None:
                    sheltered_at_16[dusk_day].add(i)
                else:
                    by_day[dusk_day][i] = h - 16
            last_hour[(dusk_day, i)] = h
    spreads = []
    for day, m in sorted(by_day.items()):
        xs = list(m.values())
        if len(xs) < 10:
            continue
        bins = Counter(int(x * 2) for x in xs)  # 30-minute bins
        spreads.append({"day": day, "entered": len(xs), "already_sheltered_at_16": len(sheltered_at_16[day]), "p10_h": round(16 + pct(xs, 0.1), 2), "median_h": round(16 + pct(xs, 0.5), 2), "p90_h": round(16 + pct(xs, 0.9), 2),
                        "iqr_h": round(pct(xs, 0.75) - pct(xs, 0.25), 2), "sd_h": round(statistics.pstdev(xs), 2), "max_30min_share": round(max(bins.values()) / len(xs), 3)})
    rep["shelter_entry"] = spreads

    # In step: activity changes between samples, and the modal share.
    prev = None
    changes, modal = [], []
    for s in S:
        cur = {x["id"]: x["skill"] for x in s["activity"] if x["id"] in adults}
        if cur:
            modal.append(max(Counter(cur.values()).values()) / len(cur))
        if prev is not None:
            common = [i for i in cur if i in prev]
            if common:
                changes.append(sum(1 for i in common if cur[i] != prev[i]) / len(common))
        prev = cur
    rep["in_step"] = {"changed_between_samples_median": round(pct(changes, 0.5) or 0, 3), "changed_p95": round(pct(changes, 0.95) or 0, 3), "changed_max": round(max(changes or [0]), 3),
                      "modal_activity_share_median": round(pct(modal, 0.5) or 0, 3), "modal_activity_share_p95": round(pct(modal, 0.95) or 0, 3)}
    # Moments where many change at once (the lockstep the play-test saw).
    spikes = []
    for k, s in enumerate(S[1:], 1):
        if k - 1 < len(changes) and changes[k - 1] >= 0.35:
            spikes.append(game(world, s["clock"]))
    rep["in_step"]["samples_with_35pct_changing"] = len(spikes)
    rep["in_step"]["spike_hours"] = sorted(Counter(round(h) % 24 for _, h in spikes).items())

    # Time use while awake and asleep.
    use = Counter()
    for s in S:
        acts = {x["id"]: x for x in s["activity"]}
        for i in adults:
            if not chars.get(i, {}).get("alive", True):
                continue
            use[classify(acts.get(i), food)] += 1
    total = sum(use.values()) or 1
    awake = total - use["sleep"]
    rep["time_use_share"] = {k: round(v / total, 3) for k, v in use.most_common()}
    rep["awake_share"] = {k: round(v / max(1, awake), 3) for k, v in use.most_common() if k != "sleep"}
    chron = final.get("chronicle") if isinstance(final.get("chronicle"), list) else []
    in_window = [c for c in chron if t0 <= c.get("at_ms", 0) <= t1]
    rep["chronicle_kinds"] = dict(Counter(c["kind"] for c in in_window).most_common(25))
    speech = [c for c in in_window if c["kind"] == "speech"]
    rep["speech_lines_per_person_game_day"] = round(len(speech) / max(1, len(first_alive)) / max(0.01, rep["game_days"]), 2)

    # Minds: calls and cost from the journal.
    if a.journal:
        try:
            import trials  # noqa: E402 - the price list lives there
            price = trials.cost
        except Exception:  # noqa: BLE001
            price = lambda *_: None
        jd = Path(a.journal)
        calls = []
        for f in jd.glob("*.jsonl"):
            for l in f.open():
                try:
                    e = json.loads(l)
                except ValueError:
                    continue
                if e.get("purpose") and e.get("at_ms"):
                    calls.append(e)
        if calls:
            ms0 = min(e["at_ms"] for e in calls)
            by_min = Counter((e["at_ms"] - ms0) // 60000 for e in calls)
            tok_min = Counter()
            for e in calls:
                tok_min[(e["at_ms"] - ms0) // 60000] += e.get("tokens") or 0
            by_purpose = defaultdict(lambda: {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "usd": 0.0, "errors": 0})
            for e in calls:
                b = by_purpose[e["purpose"]]
                b["calls"] += 1
                b["prompt"] += e.get("prompt_tokens") or 0
                b["cached"] += e.get("cached_tokens") or 0
                b["completion"] += e.get("completion_tokens") or 0
                b["usd"] += price(e.get("model"), e.get("prompt_tokens") or 0, e.get("completion_tokens") or 0, e.get("cached_tokens") or 0) or 0
                b["errors"] += 1 if e.get("error") else 0
            usd = sum(b["usd"] for b in by_purpose.values())
            hours = (max(e["at_ms"] for e in calls) - ms0) / 3.6e6
            minds = len({e.get("actor") for e in calls})
            people_minds = len(first_alive)
            game_hours = rep["game_days"] * 24
            rep["minds"] = {"calls": len(calls), "actors_calling": minds, "real_hours": round(hours, 2), "usd": round(usd, 3),
                            "usd_per_person_real_hour": round(usd / max(1e-9, people_minds * hours), 5),
                            "usd_per_person_game_day": round(usd / max(1e-9, people_minds * rep["game_days"]), 5),
                            "calls_per_person_game_hour": round(len(calls) / max(1e-9, people_minds * game_hours), 3),
                            "calls_per_min_median": pct(list(by_min.values()), 0.5), "calls_per_min_p95": pct(list(by_min.values()), 0.95), "calls_per_min_max": max(by_min.values()),
                            "tokens_per_min_median": pct(list(tok_min.values()), 0.5), "tokens_per_min_p95": pct(list(tok_min.values()), 0.95), "tokens_per_min_max": max(tok_min.values()),
                            "queue_wait_ms_p95": pct([e.get("queue_wait_ms") or 0 for e in calls], 0.95), "latency_ms_p50": pct([e.get("latency_ms") or 0 for e in calls], 0.5),
                            "errors": sum(1 for e in calls if e.get("error")),
                            "by_purpose": {k: dict(v, usd=round(v["usd"], 4)) for k, v in sorted(by_purpose.items(), key=lambda kv: -kv[1]["calls"])},
                            "by_model": dict(Counter(e.get("model") for e in calls))}
    # Timelines of sampled people.
    places = defaultdict(dict)
    for p in (final.get("place") if isinstance(final.get("place"), list) else []):
        places[p["actor"]][p["name"]] = (p["x"], p["y"])
    thoughts = defaultdict(list)
    for t in (final.get("thought") if isinstance(final.get("thought"), list) else []):
        if t0 <= t["at_ms"] <= t1:
            thoughts[t["actor"]].append(t)
    rhythm = {r["id"]: r for r in (final.get("rhythm") if isinstance(final.get("rhythm"), list) else [])}
    pick = sorted(i for i in adults & first_alive)
    step = max(1, len(pick) // max(1, a.people))
    sampled = pick[::step][: a.people]
    lines = []
    for i in sampled:
        c = chars[i]
        home = (c["home_x"], c["home_y"])
        segs = []
        for s in S:
            act = next((x for x in s["activity"] if x["id"] == i), None)
            b = next((x for x in s["body"] if x["id"] == i), None)
            where = "?"
            if b:
                xy = pos(b, s["clock"])
                near = [(n, math.dist(xy, p)) for n, p in [("home", home), *places[i].items()]]
                n, dd = min(near, key=lambda x: x[1])
                where = n if dd <= 8 else "out"
            what = f"{classify(act, food)}:{(act or {}).get('label') or (act or {}).get('skill') or 'idle'}"
            key = (what, where)
            day, hour = game(world, s["clock"])
            if segs and segs[-1]["key"] == key:
                segs[-1]["to"] = (day, hour)
            else:
                segs.append({"key": key, "from": (day, hour), "to": (day, hour)})
        segs = [x for x in segs if (x["to"][0] - x["from"][0]) * 24 + x["to"][1] - x["from"][1] >= 0.5 or x["key"][0].startswith("social")]
        tl = [f"d{x['from'][0]} {x['from'][1]:05.2f}-{x['to'][1]:05.2f} {x['key'][0]} @ {x['key'][1]}" for x in segs[:60]]
        th = [f"d{game(world, t['at_ms'])[0]} {game(world, t['at_ms'])[1]:05.2f} {t['kind']}: {t['summary'][:140]}" for t in sorted(thoughts[i], key=lambda t: t["at_ms"])[:20]]
        r = rhythm.get(i)
        lines.append({"id": i, "name": c["name"], "rhythm": {"rise": round(r["rise_h"], 2), "bed": round(r["bed_h"] % 24, 2), "evening_h": round(r["evening_h"], 1)} if r else None, "timeline": tl, "thoughts": th})
    rep["timelines"] = lines
    (d / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    md = [f"# {d.name}", "", f"{rep['samples']} samples over {rep['real_minutes']} real minutes, {rep['game_days']} game days ({rep['from']} to {rep['to']}); {rep['people_at_start']} people at the start.", ""]
    md += [f"- Deaths: {rep['deaths']} (starvation {rep['deaths_starvation']}, cold {rep['deaths_cold']}); births {rep['births']}.",
           f"- In step: {rep['in_step']}", f"- Time use (all samples): {rep['time_use_share']}", f"- Awake: {rep['awake_share']}",
           f"- Speech lines per person per game day: {rep['speech_lines_per_person_game_day']}", ""]
    md += ["## Shelter entry from 16:00", "", "| day | entered | sheltered at 16:00 | p10 | median | p90 | IQR h | sd h | most in one 30 min |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    md += [f"| {x['day']} | {x['entered']} | {x['already_sheltered_at_16']} | {x['p10_h']} | {x['median_h']} | {x['p90_h']} | {x['iqr_h']} | {x['sd_h']} | {x['max_30min_share']} |" for x in rep["shelter_entry"]]
    if "minds" in rep:
        m = rep["minds"]
        md += ["", "## Minds", "", f"{m['calls']} calls by {m['actors_calling']} actors over {m['real_hours']} h: ${m['usd']} (${m['usd_per_person_real_hour']} per person-hour, ${m['usd_per_person_game_day']} per person per game day; {m['calls_per_person_game_hour']} calls per person per game hour).",
               f"Calls per minute: median {m['calls_per_min_median']}, p95 {m['calls_per_min_p95']}, max {m['calls_per_min_max']}. Tokens per minute: median {m['tokens_per_min_median']}, p95 {m['tokens_per_min_p95']}, max {m['tokens_per_min_max']}. Queue wait p95 {m['queue_wait_ms_p95']} ms; errors {m['errors']}.", "",
               "| purpose | calls | prompt | cached | completion | USD |", "|---|---:|---:|---:|---:|---:|"]
        md += [f"| {k} | {v['calls']} | {v['prompt']} | {v['cached']} | {v['completion']} | {v['usd']} |" for k, v in m["by_purpose"].items()]
    md += ["", "## Sampled people", ""]
    for p in rep["timelines"]:
        md += [f"### {p['name']} (#{p['id']}) {p['rhythm'] or ''}", ""] + [f"- {x}" for x in p["timeline"][:30]] + [""] + [f"  - {x}" for x in p["thoughts"][:10]] + [""]
    (d / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:12]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--url", required=True)
    s.add_argument("--db", required=True)
    s.add_argument("--container", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--minutes", type=float, required=True)
    s.add_argument("--every", type=float, default=10.0)
    z = sub.add_parser("analyze")
    z.add_argument("dir")
    z.add_argument("--journal", default=None)
    z.add_argument("--people", type=int, default=10)
    a = ap.parse_args()
    sample(a) if a.cmd == "sample" else analyze(a)


if __name__ == "__main__":
    main()
