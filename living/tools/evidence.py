#!/usr/bin/env python3
"""Checkpoint evidence from the live world (docs/CHECKPOINT_2.md, docs/CHECKPOINT_3.md).

Usage: living/tools/evidence.py [--db living] [--out FILE]

Reports how know-how spread (by source), tablets written and read, plantings, births and
deaths, exchanges between groups (group = the town or band in a person's background, else
the community they belong to, else the nearest valley camp), trades, thefts, fights,
community membership, the current season/day and population. Observational: counts what happened, judges nothing.
"""
import argparse
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
CAMPS = {"west": (19, 81), "lake": (61, 45), "ridge": (48, 13)}
CAMPS_ACTIVE = True


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    res = []
    for l in lines[1:]:
        r = {}
        for h, v in zip(head, [v.strip() for v in l.split("|")]):
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v in ("true", "false"):
                v = v == "true"
            else:
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
            r[h] = v
        res.append(r)
    return res


BACKGROUND = {}
MEMBER = {}


def camp_of(c):
    if c.get("kind") != "person":
        return None
    bg = BACKGROUND.get(c["id"])
    if bg:
        return bg.get("town") or bg.get("band")
    if c["id"] in MEMBER:
        return MEMBER[c["id"]]
    if not CAMPS_ACTIVE:
        return "loner"
    x, y = c["home_x"], c["home_y"]
    name, (cx, cy) = min(CAMPS.items(), key=lambda kv: (kv[1][0] - x) ** 2 + (kv[1][1] - y) ** 2)
    return name if (cx - x) ** 2 + (cy - y) ** 2 < 15 ** 2 else "loner"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living")
    ap.add_argument("--out")
    a = ap.parse_args()
    global CAMPS_ACTIVE
    for r in rows(a.db, "SELECT * FROM background"):
        try:
            BACKGROUND[r["id"]] = json.loads(r["text"].replace('\\"', '"'))
        except ValueError:
            pass
    comm = {r["id"]: r["name"] for r in rows(a.db, "SELECT * FROM community")}
    for m in rows(a.db, "SELECT * FROM membership"):
        MEMBER[m["member"]] = comm.get(m["community"], "?")
    CAMPS_ACTIVE = not BACKGROUND
    chars = {c["id"]: c for c in rows(a.db, "SELECT * FROM character")}
    camp = {i: camp_of(c) for i, c in chars.items()}
    know = rows(a.db, "SELECT * FROM know_how")
    by_source = Counter("seed" if k["source"] == "seed" else k["source"].split(" ")[0] for k in know)
    spread = [k for k in know if k["source"] != "seed"]
    beyond = []
    for k in spread:
        learner_camp = camp.get(k["actor"])
        if k["source"].startswith("taught by "):
            teacher = next((i for i, c in chars.items() if c["name"] == k["source"][10:]), None)
            beyond.append({"learner": chars[k["actor"]]["name"], "technique": k["technique"], "how": k["source"], "cross_camp": camp.get(teacher) != learner_camp})
        else:
            beyond.append({"learner": chars[k["actor"]]["name"], "technique": k["technique"], "how": k["source"], "cross_camp": None})
    chron = rows(a.db, "SELECT kind, a, b, text, at_ms FROM chronicle")
    # Learning events survive in the story even when the learner (and their know-how) died.
    learned_story = [r["text"] for r in chron if r["kind"] == "learn"]
    kinds = Counter(r["kind"] for r in chron)
    exchanges = [r for r in chron if r["kind"] in ("give", "learn", "trade", "teach") and r["a"] and r["b"] and camp.get(r["a"]) and camp.get(r["b"]) and camp.get(r["a"]) != camp.get(r["b"])]
    arts = rows(a.db, "SELECT kind, author_name, topic, text FROM artifact")
    people = [c for c in chars.values() if c["kind"] == "person"]
    deaths = [(c["name"], c["cause"]) for c in people if not c["alive"]]
    w = rows(a.db, "SELECT * FROM world")[0]
    import time
    now = time.time() * 1000
    day = int((now - w["epoch_ms"] + w["day_ms"] * 7 / 24) // w["day_ms"]) + 1
    season = ["spring", "summer", "autumn", "winter"][((day - 1) % 8) // 2]
    report = {
        "day": day,
        "season": season,
        "people_alive": sum(1 for c in people if c["alive"]),
        "people_born": sum(1 for c in people if c.get("parent_a")),
        "deaths": deaths,
        "know_how_by_source": dict(by_source),
        "learned": beyond,
        "learning_events": learned_story,
        "artifacts": [{"kind": x["kind"], "by": x["author_name"], "topic": x["topic"], "text": x["text"][:120]} for x in arts],
        "story_counts": dict(kinds),
        "cross_group_exchanges": [r["text"] for r in exchanges][-20:],
        "trades": [r["text"] for r in chron if r["kind"] == "trade"][-10:],
        "fights": [r["text"] for r in chron if r["kind"] in ("attack", "kill", "death", "fight")][-10:],
        "communities": {name: sorted(chars[m]["name"] for m, n in MEMBER.items() if n == name and m in chars and chars[m]["alive"]) for name in comm.values()},
        "people_by_group": dict(Counter(camp.get(c["id"]) for c in people if c["alive"])),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
