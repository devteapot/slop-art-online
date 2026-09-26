#!/usr/bin/env python3
"""Combat experiment: two people with a feud and their own LLM minds, on a separate database.

Publishes a fresh database (default `living-duel`, deletes its data), spawns two armed,
fed people side by side with backgrounds that give them a quarrel, and runs a mind service
restricted to those two (LIVING_ONLY) under its own run name, so the live world's journal
and Neo4j minds are untouched. Nothing forces a fight: the minds decide. Samples health,
activities and combat counters, then reports what happened: blows, dodges, blocks, whether
graphs had a combat branch, mid-fight patches and what each said.

Usage: living/tools/duel.py [--db living-duel] [--seconds 360] [--per-min 40] [--per-side 1] [--out FILE]
With --per-side N > 1, two groups of N face each other (a group fight).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
MIND = ROOT / "living/target/release/living-mind"

FEUD = [
    {
        "origin": "band",
        "band": "the ridge people",
        "history": "{other} took the ridge people's winter stores and left your brother to starve. You swore that the next time you met {other}, you would make them pay. You carry a spear.",
    },
    {
        "origin": "band",
        "band": "the valley raiders",
        "history": "You took the ridge people's winter stores because your own family was starving; {other}'s brother died of it. {other} has sworn revenge. You are proud, you regret nothing and you will not run. You carry a spear.",
    },
]


def stdb(*args):
    r = subprocess.run([STDB, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[-300:]}")
    return r.stdout


def rows(db, q):
    out = stdb("sql", "-s", "local", db, q)
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, [v.strip() for v in l.split("|")])} for l in lines[1:]]


def call(db, reducer, *args):
    enc = [str(a) if isinstance(a, (int, float)) or (isinstance(a, str) and a.isdigit()) else json.dumps(a) for a in args]
    stdb("call", "-s", "local", db, reducer, *enc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living-duel")
    ap.add_argument("--seconds", type=int, default=360)
    ap.add_argument("--per-min", type=int, default=40)
    ap.add_argument("--per-side", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()
    db, run = a.db, f"duel-{int(time.time())}"
    stdb("publish", "-s", "local", "-b", "/wasm/living_authority.wasm", db, "--delete-data", "-y")
    time.sleep(3)
    n = max(1, a.per_side)
    stdb("call", "-s", "local", db, "spawn_crowd", str(2 * n), "true")
    time.sleep(1.5)
    ids = sorted(int(r["id"]) for r in rows(db, "SELECT id, name FROM character") if r["name"].startswith("Walker"))[: 2 * n]
    names = {i: n_ for i, n_ in ((int(r["id"]), r["name"]) for r in rows(db, "SELECT id, name FROM character")) if i in ids}
    sides = [ids[:n], ids[n:]]
    A, B = sides[0][0], sides[1][0]
    for side in sides:
        for i in side:
            call(db, "place_near", str(i), str(A))
    for k, side in enumerate(sides):
        others = sides[1 - k]
        other_names = " and ".join(f"{names[o]} (#{o})" for o in others)
        for me in side:
            call(db, "grant_know_how", str(me), "spear")
            call(db, "grant_items", str(me), "spear", "1")
            call(db, "grant_items", str(me), "cooked_meat", "4")
            story = FEUD[k]
            friends = [f for f in side if f != me]
            bg = dict(story, history=story["history"].format(other=other_names), companions=[{"id": f, "name": names[f]} for f in friends])
            if friends:
                bg["history"] += " " + ", ".join(names[f] for f in friends) + " stand with you."
            call(db, "set_background", str(me), json.dumps(bg))
    log = ROOT / f".local/living/{run}.log"
    env = dict(os.environ, LIVING_DB=db, LIVING_RUN=run, LIVING_ONLY=",".join(str(i) for i in ids), LIVING_LLM_PER_MIN=str(a.per_min), RUST_LOG="info")
    mind = subprocess.Popen([str(MIND)], cwd=ROOT, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT)
    samples = []
    start = time.time()
    try:
        while time.time() - start < a.seconds and mind.poll() is None:
            t = round(time.time() - start)
            vit = {int(r["id"]): r for r in rows(db, "SELECT id, hp, hp_rate, at_ms, max_hp FROM vitals") if int(r["id"]) in ids}
            act = {int(r["id"]): r["skill"] for r in rows(db, "SELECT id, skill FROM activity") if int(r["id"]) in ids}
            alive = {int(r["id"]): r["alive"] == "true" for r in rows(db, "SELECT id, alive FROM character") if int(r["id"]) in ids}
            now = time.time() * 1000
            hp = {i: round(min(float(v["max_hp"]), max(0.0, float(v["hp"]) + float(v["hp_rate"]) * (now - float(v["at_ms"])) / 60000)), 1) for i, v in vit.items()}
            samples.append({"t": t, "hp": {names[i]: hp.get(i) for i in ids}, "doing": {names[i]: act.get(i, "idle") for i in ids}, "alive": {names[i]: alive.get(i) for i in ids}})
            if any(not any(alive.get(i) for i in side) for side in sides):
                time.sleep(5)
                break
            time.sleep(2)
    finally:
        mind.terminate()
        mind.wait(timeout=20)
    stats = rows(db, "SELECT hits, dodged, blocked, missed FROM stats")
    chron = [r["text"] for r in rows(db, "SELECT kind, text, at_ms FROM chronicle") if r["kind"] not in ("arrival", "time")]
    minds = {}
    for i in ids:
        f = ROOT / ".local/living/journal" / run / f"{names[i]}.jsonl"
        entries = [json.loads(l) for l in f.open()] if f.exists() else []
        delib = [e for e in entries if e["purpose"] == "deliberate"]
        replies = []
        for e in delib:
            try:
                replies.append(json.loads(e["reply"][e["reply"].find("{"): e["reply"].rfind("}") + 1]))
            except ValueError:
                pass
        minds[names[i]] = {
            "deliberations": len(delib),
            "patches": sum(1 for r in replies if isinstance(r.get("patch"), dict)),
            "graphs_with_combat_branch": sum(1 for r in replies if '"combat"' in json.dumps(r.get("graph") or {}) or isinstance(r.get("patch"), dict)),
            "uses_dodge_or_block": sum(1 for r in replies if any(k in json.dumps(r) for k in ('"dodge"', '"block"'))),
            "plans": [r.get("plan") for r in replies if r.get("plan")],
            "said": [(r.get("say") or {}).get("text") for r in replies if isinstance(r.get("say"), dict) and (r.get("say") or {}).get("text")],
            "latency_ms_p50": sorted(e["latency_ms"] for e in delib)[len(delib) // 2] if delib else None,
        }
    report = {"db": db, "run": run, "fighters": {names[i]: i for i in ids}, "sides": [[names[i] for i in side] for side in sides], "seconds": round(time.time() - start), "counters": stats[0] if stats else {}, "story": chron[-40:], "minds": minds, "samples": samples[::3]}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    out = Path(a.out) if a.out else ROOT / f".local/living/{run}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"report: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
