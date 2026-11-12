#!/usr/bin/env python3
"""Wolves, people and deer in a running world, read from its rows (docs/STAMINA.md, "Wolves on
people and deer, before and after fix-pursuit-speed").

  living/tools/wolf_ecology.py sample --run RUN --out DIR [--every 2] [--game-hours 48]
  living/tools/wolf_ecology.py report DIR... [--json OUT]

`sample` polls every `--every` seconds until the world has run `--game-hours` from its start
(every world starts at 07:00), writing `DIR/samples.jsonl`: the clock, who is alive (kind,
stage, cause, died_ms), each wolf's activity (an attack and its victim, keyed by its start), the
people's positions, health and whether they sleep, and the warming structures (campfire, house,
hall, inn, shelter, hearth). Uses the verify harness's run state and admin token
(`.agents/skills/verify/scripts/verify.py`); `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL` select the
server. Read-only.

`report` adds up one or more sample folders (runs of one build), in game hours:
- wolf attacks on people, as episodes (one wolf on one person, a new episode after `EPISODE_S`
  without a blow begun) and as blows begun (an attack activity aimed at a person, once per start),
  and people killed by wolves (a death whose cause names a wolf), per resident-hour, by day and
  night (night: 20:00 to 06:00, the shipped and Cullet `night_hours`), and by the victim's state
  when the episode began, or at its last sample before a death: a child (stage 0 or 1), badly hurt
  (under half its health), asleep away from a fire (sleeping, no warming structure within 4 m),
  alone at night (no other person within 10 m);
- deer killed by wolves per wolf-hour, wolves starved, and wolf and deer numbers every 6 game hours.
"""
import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
import verify as V  # noqa: E402

WARM = {"campfire", "house", "hall", "inn", "shelter", "hearth"}
FIRE_M = 4.0
ALONE_M = 10.0
DUSK, DAWN = 20.0, 6.0
EPISODE_S = 20.0


def q(db, token, query):
    code, body = V.http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError(f"{code} {body[:300]}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def pos(b, now):
    t = max(0, min(now, b["next_ms"]) - b["t_ms"]) / 1000
    return (b["x"] + b["vx"] * t, b["y"] + b["vy"] * t)


def sample(a):
    st = V.load(a.run)
    db, token = st["db"], V.admin_token()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w = q(db, token, "SELECT epoch_ms, day_ms FROM world")[0]
    (out / "world.json").write_text(json.dumps({"run": a.run, "db": db, **w}) + "\n")
    f = (out / "samples.jsonl").open("a")
    warm, warm_at = [], 0.0
    while True:
        try:
            now = q(db, token, "SELECT last_ms FROM clock")[0]["last_ms"]
            game_h = (now - w["epoch_ms"]) / w["day_ms"] * 24
            if time.time() - warm_at > 60:
                warm = [[s["x"], s["y"]] for s in q(db, token, "SELECT kind, x, y FROM structure") if s["kind"] in WARM]
                warm_at = time.time()
            chars = q(db, token, "SELECT id, kind, alive, stage, cause, died_ms FROM character")
            kinds = {c["id"]: c["kind"] for c in chars}
            bodies = {b["id"]: b for b in q(db, token, "SELECT id, kind, x, y, t_ms, vx, vy, next_ms FROM body") if b["kind"] in ("person", "wolf", "deer")}
            vit = {v["id"]: v for v in q(db, token, "SELECT id, hp, max_hp, hp_rate, at_ms FROM vitals")}
            acts = q(db, token, "SELECT id, skill, phase, victim, started_ms FROM activity")
            people = {}
            for i, b in bodies.items():
                if kinds.get(i) != "person":
                    continue
                v = vit.get(i)
                hp = None
                if v:
                    hp = max(0.0, min(v["max_hp"], v["hp"] + v["hp_rate"] * max(0, now - v["at_ms"]) / 60000)) / max(v["max_hp"], 1e-3)
                people[i] = {"at": [round(c, 1) for c in pos(b, now)], "hp": round(hp, 3) if hp is not None else None}
            for x in acts:
                if x["id"] in people and x["skill"] in ("sleep", "rest"):
                    people[x["id"]]["sleep"] = x["skill"] == "sleep"
            hunts = [{"wolf": x["id"], "skill": x["skill"], "victim": x["victim"], "started_ms": x["started_ms"], "phase": x["phase"],
                      "vkind": kinds.get(x["victim"])} for x in acts if kinds.get(x["id"]) == "wolf" and x["victim"]]
            row = {"now": now, "game_h": round(game_h, 3), "chars": [[c["id"], c["kind"], c["alive"], c["stage"], c["cause"], c["died_ms"]] for c in chars if c["kind"] in ("person", "wolf", "deer")],
                   "people": people, "hunts": hunts, "warm": warm}
            f.write(json.dumps(row) + "\n")
            f.flush()
            if game_h >= a.game_hours:
                return
        except Exception as e:  # a slow server: keep going
            print(f"sample error: {e}", file=sys.stderr, flush=True)
        time.sleep(a.every)


def night(h):
    h = h % 24
    return h >= DUSK or h < DAWN


def tags_of(r, victim, ph):
    """A person's state in sample `r`: child, badly hurt, asleep away from a fire, alone at night."""
    v = r["people"].get(str(victim)) or r["people"].get(victim)
    stage = next((c[3] for c in r["chars"] if c[0] == victim), 2)
    tags = []
    if stage <= 1:
        tags.append("child")
    if v and v.get("hp") is not None and v["hp"] < 0.5:
        tags.append("badly_hurt")
    if v and v.get("sleep") and not any(math.dist(v["at"], s) <= FIRE_M for s in r["warm"]):
        tags.append("asleep_no_fire")
    if v and ph == "night" and not any(math.dist(v["at"], o["at"]) <= ALONE_M for k, o in r["people"].items() if str(k) != str(victim)):
        tags.append("alone_night")
    return tags or ["none_of_these"]


def one(d):
    rows = [json.loads(l) for l in (d / "samples.jsonl").open()]
    w = json.loads((d / "world.json").read_text())
    hour = lambda ms: (ms - w["epoch_ms"]) / w["day_ms"] * 24
    res = Counter()
    seen_attack = {}
    last_blow = {}
    last_seen = {}
    prev = None
    numbers = []
    for r in rows:
        alive = [c for c in r["chars"] if c[2]]
        n = Counter(c[1] for c in alive)
        if prev is not None:
            dt = r["game_h"] - prev["game_h"]
            pn = Counter(c[1] for c in prev["chars"] if c[2])
            ph = "night" if night(prev["game_h"] + 7) else "day"
            res[f"resident_h_{ph}"] += pn["person"] * dt
            res["wolf_h"] += pn["wolf"] * dt
        if not numbers or r["game_h"] >= numbers[-1]["game_h"] + 6:
            numbers.append({"game_h": round(r["game_h"], 1), "wolf": n["wolf"], "deer": n["deer"], "person": n["person"]})
        for h in r["hunts"]:
            key = (h["wolf"], h["started_ms"])
            if key in seen_attack or h["skill"] not in ("attack", "strike"):
                continue
            seen_attack[key] = True
            at_h = hour(h["started_ms"]) + 7
            ph = "night" if night(at_h) else "day"
            if h["vkind"] == "person":
                res[f"blows_{ph}"] += 1
                pair = (h["wolf"], h["victim"])
                if pair not in last_blow or h["started_ms"] - last_blow[pair] > EPISODE_S * 1000:
                    res[f"attacks_{ph}"] += 1
                    for t in tags_of(r, h["victim"], ph):
                        res[f"attacks_{t}"] += 1
                last_blow[pair] = h["started_ms"]
            elif h["vkind"] == "deer":
                res["deer_attacks"] += 1
        for k in r["people"]:
            last_seen[int(k)] = r
        prev = r
    last = rows[-1]
    first_ids = {c[0] for c in rows[0]["chars"]}
    for c in last["chars"]:
        cid, kind, is_alive, stage, cause, died = c
        if is_alive or not died or died < rows[0]["now"] - 1:
            continue
        by_wolf = "wolf" in (cause or "").lower()
        ph = "night" if night(hour(died) + 7) else "day"
        if kind == "person" and by_wolf:
            res[f"people_killed_{ph}"] += 1
            res["people_killed"] += 1
            for t in tags_of(last_seen.get(cid, last), cid, ph):
                res[f"people_killed_{t}"] += 1
        if kind == "deer" and by_wolf:
            res["deer_killed"] += 1
        if kind == "wolf":
            res["wolves_died"] += 1
            c_ = (cause or "?").lower()
            res["wolves_died_" + ("starved" if "starv" in c_ else "killed" if "killed" in c_ else "age" if "age" in c_ else "other")] += 1
        if kind == "person" and not by_wolf:
            res["people_died_other"] += 1
    res["game_h"] = last["game_h"] - rows[0]["game_h"]
    return res, numbers


def report(a):
    runs = []
    for d in a.dirs:
        res, numbers = one(Path(d))
        runs.append({"dir": d, "counts": dict(res), "numbers": numbers})
    def rate(r, num, den):
        c = r["counts"]
        n = sum(c.get(k, 0) for k in num)
        h = sum(c.get(k, 0) for k in den)
        return n / h if h else None
    out = {"runs": runs, "summary": {}}
    measures = {
        "attacks_per_resident_h": (["attacks_day", "attacks_night"], ["resident_h_day", "resident_h_night"]),
        "attacks_per_resident_h_day": (["attacks_day"], ["resident_h_day"]),
        "attacks_per_resident_h_night": (["attacks_night"], ["resident_h_night"]),
        "blows_per_resident_h": (["blows_day", "blows_night"], ["resident_h_day", "resident_h_night"]),
        "killed_per_resident_h": (["people_killed_day", "people_killed_night"], ["resident_h_day", "resident_h_night"]),
        "killed_per_resident_h_day": (["people_killed_day"], ["resident_h_day"]),
        "killed_per_resident_h_night": (["people_killed_night"], ["resident_h_night"]),
        "deer_killed_per_wolf_h": (["deer_killed"], ["wolf_h"]),
    }
    for k, (num, den) in measures.items():
        vals = [rate(r, num, den) for r in runs]
        vals = [v for v in vals if v is not None]
        out["summary"][k] = {"median": statistics.median(vals) if vals else None, "range": [min(vals), max(vals)] if vals else None}
    for k in ("attacks_day", "attacks_night", "attacks_child", "attacks_badly_hurt", "attacks_asleep_no_fire", "attacks_alone_night", "attacks_none_of_these",
              "people_killed", "people_killed_day", "people_killed_night", "people_killed_child", "people_killed_badly_hurt", "people_killed_asleep_no_fire", "people_killed_alone_night", "people_killed_none_of_these", "people_died_other",
              "wolves_died", "wolves_died_starved", "wolves_died_killed", "wolves_died_age", "wolves_died_other", "deer_killed", "deer_attacks"):
        out["summary"][k] = [r["counts"].get(k, 0) for r in runs]
    out["summary"]["wolves_deer_people_over_time"] = [[(n["game_h"], n["wolf"], n["deer"], n["person"]) for n in r["numbers"]] for r in runs]
    text = json.dumps(out["summary"], indent=1)
    print(text)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--run", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--every", type=float, default=2.0)
    s.add_argument("--game-hours", type=float, default=48.0)
    r = sub.add_parser("report")
    r.add_argument("dirs", nargs="+")
    r.add_argument("--json")
    a = ap.parse_args()
    sample(a) if a.cmd == "sample" else report(a)


if __name__ == "__main__":
    main()
