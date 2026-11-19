#!/usr/bin/env python3
"""A person's look as a real client receives it (look-1, docs/LOOK.md §2-§3).

    look_rows.py --run client-...      (a run launched with verify.py launch --seed plan-test,
                                        or any seed whose `looks` are in force)

The player joins (its own identity). As that identity and anonymously, SQL on the private `look`
and `look_line` tables is refused. The admin installs an overlay of the shipped script whose
`perceived_of` law marks anyone farther than 4 m `far` (as Cullet's does past 24 m), spawns three
minded strangers, holds them still and places one 2 m and one 6 m from the player and one 60 m
away, and puts the player beside a deer when the world has one. The player's `seen_characters`
is streamed through the Rust SDK probe (`drive.py --query --as-player`):
- every person row (the player's own too) carries a key matching `^lk_[0-9a-f]{16}$`, equal to
  that person's `look.line` (admin SQL) and to a `look_line` key, and equal to no name slug;
- the far row (6 m) carries its key too (no far stand-in), with no name and the far label;
- no field of any row holds a hex colour;
- an animal's row has `look` "";
- the stranger 60 m away has no row at all;
- a second subscription (a reconnect) holds the same rows, key for key.
The shipped script is installed again at the end. Admin calls (`install_script`, `spawn_crowd`,
`set_behavior`, `place_at`) set the scene; they are not something a player can do. Writes
`RUN/look-seen-*.jsonl` and `RUN/look_rows.json`. Python standard library only.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
FAR = "someone too far away to make out"
FAR_LAW = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'
KEY = re.compile(r"^lk_[0-9a-f]{16}$")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r


def sql(rid, query, *flags):
    out = run(V, "sql", "--run", rid, query, *flags).stdout
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def refused(rid, query, *flags):
    r = run(V, "sql", "--run", rid, query, *flags, check=False)
    text = (r.stdout + r.stderr).lower()
    return r.returncode != 0 and ("private" in text or "not authorized" in text or "no such table" in text or "permission" in text), (r.stdout + r.stderr)[-300:]


def call(rid, reducer, args):
    run(V, "call", "--run", rid, reducer, json.dumps(args), "--as-admin")


def stream(rid, name, seconds=6):
    """The player's seen_characters through the SDK probe: the last row set it held, by id.
    Evidence is never overwritten: a rerun's stream gets its own name."""
    name = f"{name}-{time.strftime('%H%M%S')}"
    run(DRIVE, "--run", rid, "--query", "SELECT * FROM seen_characters", "--as-player", "--seconds", seconds, "--save", name)
    rows = {}
    for line in (ROOT / ".local/living/verify" / rid / f"{name}.jsonl").read_text().splitlines():
        ev = json.loads(line)
        for r in (ev.get("tables") or {}).get("seen_characters", []) + [x for k in ("inserts", "inserted") for x in ev.get(k) or []]:
            if isinstance(r, dict) and "id" in r:
                rows[r["id"]] = r
    return rows


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    rid, out, checks = a.run, ROOT / ".local/living/verify" / a.run, {}
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    overlay = shipped.replace("fn perceived_of(p)", "fn base_perceived_of(p)", 1) + "\n" + FAR_LAW + "\n"
    (out / "look-overlay.rhai").write_text(overlay)
    result = {}
    try:
        # The run's player joins (already joined on a rerun: kept).
        run(V, "player", "--run", rid, "join", "LookProbe", check=False)
        me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
        for table in ("look", "look_line"):
            for who, flags in (("player", ("--as-player",)), ("anonymous", ("--anonymous",))):
                ok, why = refused(rid, f"SELECT * FROM {table}", *flags)
                checks[f"SQL on {table} is refused to the {who}"] = ok
                result[f"refusal-{table}-{who}"] = why
        before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
        call(rid, "spawn_crowd", [3, True])
        near, far, away = sorted(c["id"] for c in sql(rid, "SELECT id FROM character") if c["id"] not in before)
        for x in (near, far, away):
            call(rid, "set_behavior", [x, json.dumps({"wait": 300})])
        run(ROOT / "living/tools/install_script.py", f"verify-{rid}", out / "look-overlay.rhai")
        deer = [c for c in sql(rid, "SELECT id, kind, alive FROM character WHERE kind = 'deer'") if c["alive"]]
        if deer:
            d = sql(rid, f"SELECT * FROM body WHERE id = {deer[0]['id']}")[0]
            call(rid, "place_at", [me, d["x"] + 1.5, d["y"]])
            time.sleep(1)
        body = sql(rid, "SELECT * FROM my_body", "--as-player")[0]
        call(rid, "place_at", [near, body["x"] + 2.0, body["y"]])
        call(rid, "place_at", [far, body["x"] + 6.0, body["y"]])
        call(rid, "place_at", [away, body["x"] + 60.0, body["y"]])
        time.sleep(3)
        looks = {l["id"]: l for l in sql(rid, "SELECT id, person, line, band, next_ms FROM look")}
        keys = {l["key"] for l in sql(rid, "SELECT key FROM look_line")}
        names = [c["name"] for c in sql(rid, "SELECT name FROM character")]
        slugs = {slug(n) for n in names} | {n for n in names}
        seen = stream(rid, "look-seen-first")
        people = {i: r for i, r in seen.items() if r.get("kind") == "person"}
        animals = {i: r for i, r in seen.items() if r.get("kind") != "person"}
        checks["the player sees itself and both placed strangers"] = {me, near, far} <= set(people)
        checks["every person row carries an lk_ key of 16 hex digits"] = bool(people) and all(KEY.match(r.get("look", "")) for r in people.values())
        checks["each key is that person's look.line and a look_line key"] = all(looks.get(i, {}).get("line") == r["look"] and r["look"] in keys for i, r in people.items())
        checks["no key equals or contains a name or a name slug"] = all(r["look"] not in slugs and not any(s and s in r["look"] for s in slugs if len(s) > 3) for r in people.values())
        f = people.get(far, {})
        checks["the far row (6 m) carries its key, no name, the far label"] = bool(KEY.match(f.get("look", ""))) and f.get("name") == "" and f.get("label") == FAR
        checks["the near row (2 m) carries its key, as a stranger"] = bool(KEY.match(people.get(near, {}).get("look", ""))) and people.get(near, {}).get("label") == "a stranger"
        checks["the player's own row carries its pool key"] = bool(KEY.match(people.get(me, {}).get("look", ""))) and people.get(me, {}).get("own") is True
        checks["no field of any row is a hex colour"] = not any(HEX.search(json.dumps(r)) for r in seen.values())
        checks["no row for the stranger 60 m away"] = away not in seen
        if deer:
            checks["an animal's row has look \"\""] = bool(animals) and all(r.get("look") == "" for r in animals.values())
        again = stream(rid, "look-seen-reconnect")
        # The people held still (animals wander off): the same rows, key for key.
        held = [me, near, far]
        checks["a second subscription holds the same rows of the people held still, key for key"] = all(i in again for i in held) and all(again[i].get("look") == seen[i].get("look") for i in held) and away not in again
        result.update({"player": me, "near": near, "far": far, "away": away, "deer": deer[:1], "seen": seen, "again": again, "look_rows": looks, "line_keys": len(keys), "checks": checks})
    finally:
        run(ROOT / "living/tools/install_script.py", f"verify-{rid}", check=False)
    (out / "look_rows.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if checks and all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
