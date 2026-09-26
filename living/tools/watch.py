#!/usr/bin/env python3
"""The watcher: every so often, gather how behavior is shaping and flag what looks strange.

Each round writes a report to `.local/living/watch/<run>/<time>.md` (and `.json`):
- population by kind and life stage, births, deaths since the last round and their causes;
- movement over a short window (moving, still, flickering, far from home, groups meeting);
- a time budget: what people are doing, grouped as survival, work, social, knowledge,
  travel, fighting and idle (by life stage);
- what speech and goals are about (survival, work, social, knowledge, trade);
- where animals are (in settlements or not; an observation, not an anomaly);
- flags: starvation, neglected babies, stuck or flickering people, repeated lines, model
  errors or slowness, slow ticks;
- optionally (--review) a short qualitative read by a model of a sample of speech, plans and
  goals: what people seem to live for, and what looks strange.

Usage: living/tools/watch.py [--db living] [--run realm-4] [--every 900] [--review]
"""
import argparse
import collections
import datetime
import json
import math
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
STAGES = ["infant", "child", "adult", "elder"]

TOPICS = {
    "survival": r"\b(hungry|hunger|eat|food|berries|starv|cold|freez|warm|fire|wolves|wolf|night|shelter|sleep|rest|safe)\b",
    "work": r"\b(build|wall|road|house|gate|stone|clay|wood|timber|plant|field|craft|tool|axe|pick|pave|repair|fish(ing)?|hunt)\b",
    "social": r"\b(feel|felt|remember|love|friend|story|stories|song|sing|laugh|family|together|miss|hope|afraid|trust|sorry|thank|glad|dream|brother|sister|mother|father|child|children)\b",
    "knowledge": r"\b(read|write|wrote|teach|learn|sign|tablet|record|ledger|know|lesson)\b",
    "trade": r"\b(trade|offer|exchange|swap|pay|price|market|sell|buy|owe)\b",
}

SKILL_GROUP = {
    "eat": "survival", "sleep": "survival", "rest": "survival", "graze": "survival", "flee": "survival", "cook": "survival",
    "build": "work", "craft": "work", "pave": "work", "plant": "work", "store": "work", "open": "work", "close": "work",
    "give": "social", "teach": "social", "tend": "social", "offer": "social", "accept": "social", "follow": "social",
    "conceive": "social", "found": "social", "join": "social", "welcome": "social", "signal": "social",
    "read": "knowledge", "write": "knowledge", "experiment": "knowledge",
    "goto": "travel", "wander": "travel",
    "attack": "fighting", "dodge": "fighting", "block": "fighting", "throw": "fighting",
    "wait": "idle",
}


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, [v.strip() for v in l.split("|")])} for l in lines[1:]]


def group_of_activity(skill, label):
    if skill == "gather" or skill == "take":
        return "survival" if any(k in label for k in ("berry", "fish", "food")) else "work"
    return SKILL_GROUP.get(skill, "idle" if not skill else "other")


def topics(texts):
    c = collections.Counter()
    for t in texts:
        low = t.lower()
        hit = [k for k, rx in TOPICS.items() if re.search(rx, low)]
        for k in hit or ["other"]:
            c[k] += 1
    n = max(1, len(texts))
    return {k: round(v / n, 2) for k, v in c.most_common()}


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for l in p.read_text().splitlines():
            l = l.strip()
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def review(digest):
    """A short qualitative read by the default model (Luna)."""
    models = json.loads((ROOT / "living/configs/models.json").read_text())
    prof = models["profiles"][models["default"]]
    key = load_env().get(prof["key_env"]) or os.environ.get(prof["key_env"], "")
    if not key:
        return "(no key for the review model)"
    prompt = (
        "You are reviewing a live simulation of a society of AI-driven people (towns, villages, wild bands) "
        "for its designers. From the digest below, answer briefly in plain prose and bullets:\n"
        "1. What do people seem to live for right now, beyond surviving? Give evidence (quotes, plans, goals).\n"
        "2. Up to 5 things that look strange, repetitive, stuck or inconsistent with a living society, each with evidence "
        "and a guess at the cause (world rules, missing mechanics, prompts, or model behavior).\n"
        "3. Signs of coordination, evolution or culture forming (or their absence).\n"
        "Do not praise; be concrete.\n\nDIGEST:\n" + json.dumps(digest, ensure_ascii=False)[:24000]
    )
    body = {"model": prof["model"], "messages": [{"role": "user", "content": prompt}]}
    if prof.get("reasoning_effort", {}).get("consolidate"):
        body["reasoning_effort"] = prof["reasoning_effort"]["consolidate"]
    req = urllib.request.Request(prof["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "living-watch"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=180))
        return r["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        return f"(review failed: {e})"


def round_once(a, state):
    db = a.db
    w = rows(db, "SELECT * FROM world")[0]
    stats = (rows(db, "SELECT * FROM stats") or [{}])[0]
    chars = {r["id"]: r for r in rows(db, "SELECT id, name, kind, alive, stage, cause, died_ms, home_x, home_y, parent_a, parent_b FROM character")}
    alive = {i: c for i, c in chars.items() if c["alive"] == "true"}
    now = time.time() * 1000
    since = state.get("last_ms", now - a.every * 1000)
    pop = collections.Counter((c["kind"], STAGES[int(c["stage"])] if c["stage"].isdigit() and int(c["stage"]) < 4 else "?") for c in alive.values())
    deaths = [c for c in chars.values() if c["alive"] == "false" and float(c["died_ms"] or 0) >= since]
    death_causes = collections.Counter((c["kind"], re.sub(r"killed by .*", "killed", c["cause"])) for c in deaths)
    people = {i: c for i, c in alive.items() if c["kind"] == "person"}
    # Movement and activity sampled over a short window.
    tracks = collections.defaultdict(list)
    acts = collections.defaultdict(list)
    for _ in range(a.sample):
        t = time.time() * 1000
        for b in rows(db, "SELECT id, x, y, vx, vy, t_ms FROM body"):
            if b["id"] in alive:
                dt = (t - float(b["t_ms"])) / 1000
                tracks[b["id"]].append((float(b["x"]) + float(b["vx"]) * dt, float(b["y"]) + float(b["vy"]) * dt))
        for r in rows(db, "SELECT id, skill, label FROM activity"):
            if r["id"] in people:
                acts[r["id"]].append((r["skill"], r["label"]))
        time.sleep(1)
    budget = collections.defaultdict(collections.Counter)
    for pid, c in people.items():
        stage = STAGES[int(c["stage"])] if c["stage"].isdigit() else "?"
        seen = acts.get(pid) or [("", "")]
        for skill, label in seen:
            budget[stage][group_of_activity(skill, label)] += 1
    budget = {s: {k: round(v / sum(cnt.values()), 2) for k, v in cnt.most_common()} for s, cnt in budget.items()}
    still = flicker = 0
    far = []
    for pid, tr in tracks.items():
        if pid not in people or len(tr) < 3:
            continue
        span = max(math.dist(p, tr[0]) for p in tr)
        still += span < 0.5
        steps = [(q[0] - p[0], q[1] - p[1]) for p, q in zip(tr, tr[1:])]
        rev = sum(1 for s1, s2 in zip(steps, steps[1:]) if s1[0] * s2[0] + s1[1] * s2[1] < -0.01)
        if rev >= 3 and span < 6:
            flicker += 1
        c = people[pid]
        d = math.dist(tr[-1], (float(c["home_x"]), float(c["home_y"])))
        if d > 40:
            far.append(f'{c["name"]} {d:.0f} tiles from home')
    # Settlements and animals in them (an observation).
    comms = rows(db, "SELECT id, name, home_x, home_y FROM community")
    animals_in = collections.Counter()
    for pid, tr in tracks.items():
        c = alive[pid]
        if c["kind"] == "person":
            continue
        for m in comms:
            if math.dist(tr[-1], (float(m["home_x"]), float(m["home_y"]))) < 16:
                animals_in[(c["kind"], m["name"])] += 1
    # Speech since the last round.
    chron = rows(db, "SELECT at_ms, kind, text FROM chronicle")
    recent = [r for r in chron if float(r["at_ms"]) >= since]
    speech = [r["text"] for r in recent if r["kind"] == "speech"]
    repeats = [t for t, n in collections.Counter(re.sub(r"\s+", " ", s)[:120] for s in speech).items() if n >= 3]
    story = collections.Counter(r["kind"] for r in recent)
    notable = [r["text"] for r in recent if r["kind"] not in ("speech", "time", "arrival")][-25:]
    goals = []
    for p in rows(db, "SELECT id, goals FROM persona"):
        if p["id"] in people:
            goals += [g for g in re.findall(r'"([^"]+)"', p["goals"].replace('\\"', '"'))]
    plans = [r["plan"] for r in rows(db, "SELECT id, plan FROM brain") if r["id"] in people][:60]
    status = rows(db, "SELECT id, status FROM mind_state")
    stuck = [s for s in status if s["id"] in people and s["status"].startswith("stuck")]
    vit = {r["id"]: r for r in rows(db, "SELECT id, hunger, hunger_rate, at_ms, hp FROM vitals")}

    def hunger(i):
        v = vit.get(i)
        return 0 if not v else float(v["hunger"]) + float(v["hunger_rate"]) * (now - float(v["at_ms"])) / 60000

    starving = [people[i]["name"] for i in people if hunger(i) > 90]
    babies = [i for i, c in people.items() if c["stage"] == "0"]
    neglected = []
    for b in babies:
        if hunger(b) > 75:
            neglected.append(f'{people[b]["name"]} (hunger {hunger(b):.0f})')
    load = subprocess.run(["python3", str(ROOT / "living/tools/llm_load.py"), "--run", w["run"], "--minutes", str(max(1, a.every // 60))], capture_output=True, text=True).stdout
    try:
        load = json.loads(load).get("all", {})
    except ValueError:
        load = {}
    flags = []
    if starving:
        flags.append(f"{len(starving)} people starving (hunger > 90): {', '.join(starving[:8])}")
    if neglected:
        flags.append(f"babies going hungry: {', '.join(neglected)}")
    if flicker >= 3:
        flags.append(f"{flicker} people flickering back and forth")
    tracked = max(1, len([p for p in tracks if p in people]))
    if still / tracked > 0.5:
        flags.append(f"{still} of {tracked} people did not move during the sample")
    if len(stuck) > len(people) * 0.15:
        flags.append(f"{len(stuck)} people stuck on a failing action, e.g. {stuck[0]['status'][:100]}")
    if repeats:
        flags.append(f"{len(repeats)} lines said 3+ times, e.g. “{repeats[0]}”")
    starved = sum(n for (k, cause), n in death_causes.items() if k == "person" and "starv" in cause)
    if starved:
        flags.append(f"{starved} people starved since the last round")
    if load.get("calls_per_min") and load.get("errors", 0) / max(1, load["calls_per_min"] * a.every / 60) > 0.02:
        flags.append(f"model errors: {load.get('errors')} in the window")
    if load.get("latency_p95_ms", 0) > 30000:
        flags.append(f"slow model replies: p95 {load['latency_p95_ms'] / 1000:.0f} s")
    if float(stats.get("max_tick_gap_ms", 0) or 0) > 25:
        flags.append(f"slow ticks: max gap {stats.get('max_tick_gap_ms')} ms")
    deer = sum(n for (k, _), n in pop.items() if k == "deer")
    wolves = sum(n for (k, _), n in pop.items() if k == "wolf")
    if deer < 10:
        flags.append(f"deer nearly gone ({deer} left)")
    if wolves < 3:
        flags.append(f"wolves nearly gone ({wolves} left)")
    report = {
        "time": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "run": w["run"],
        "day": int((now - float(w["epoch_ms"]) + float(w["day_ms"]) * 7 / 24) // float(w["day_ms"])) + 1,
        "population": {f"{k} {s}": n for (k, s), n in sorted(pop.items())},
        "births_total": stats.get("births"),
        "deaths_since_last": {f"{k}: {c}": n for (k, c), n in death_causes.items()},
        "movement": {"people": tracked, "still": still, "flickering": flicker, "far_from_home": far[:10]},
        "time_budget_by_stage": budget,
        "speech_lines": len(speech),
        "speech_topics": topics(speech),
        "goal_topics": topics(goals),
        "story_counts": dict(story),
        "animals_near_settlements": {f"{k} at {m}": n for (k, m), n in animals_in.items()},
        "llm": {k: load.get(k) for k in ("calls_per_min", "errors", "tokens_per_min", "latency_p50_ms", "latency_p95_ms")},
        "flags": flags,
        "notable_events": notable,
    }
    if a.review:
        digest = {"stats": {k: report[k] for k in ("population", "movement", "time_budget_by_stage", "speech_topics", "goal_topics", "flags")},
                  "speech_sample": speech[-60:], "plans_sample": plans, "goals_sample": goals[:60], "events": notable}
        report["review"] = review(digest)
    state["last_ms"] = now
    return report


def to_md(r):
    out = [f"# Watch {r['time']} — {r['run']}, day {r['day']}", ""]
    out.append("**Flags:** " + ("; ".join(r["flags"]) if r["flags"] else "none"))
    out.append("")
    for k in ("population", "deaths_since_last", "movement", "time_budget_by_stage", "speech_topics", "goal_topics", "story_counts", "animals_near_settlements", "llm"):
        out.append(f"- **{k.replace('_', ' ')}**: {json.dumps(r[k], ensure_ascii=False)}")
    out.append(f"- **speech lines**: {r['speech_lines']}")
    if r["notable_events"]:
        out.append("\n**Notable events**")
        out += [f"- {e}" for e in r["notable_events"]]
    if r.get("review"):
        out.append("\n**Review (model)**\n")
        out.append(r["review"])
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living")
    ap.add_argument("--every", type=int, default=900)
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    state = {}
    while True:
        r = round_once(a, state)
        d = ROOT / ".local/living/watch" / r["run"]
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
        (d / f"{stamp}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n")
        (d / f"{stamp}.md").write_text(to_md(r))
        print(f"[{r['time']}] {r['run']} day {r['day']}: flags: {'; '.join(r['flags']) or 'none'} -> {d / (stamp + '.md')}", flush=True)
        if a.once:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
