#!/usr/bin/env python3
"""Whose a house is, as a real client receives it, whatever its owner is doing (house-owner-label,
docs/PERCEPTION.md "Whose a thing is, and what places are called").

    house_label.py --run client-...      (a run launched with verify.py launch, any seed)

The player joins (its own identity). The admin spawns two minded characters, F and X, holds them
still, and has F tell the player its name (`mind_say`, "I'm <F>."): an introduction, so F is in
the player's `my_known_names`. It installs an overlay of the world's script whose `perceived_of`
marks anyone past 4 m too far away to make out (as Cullet's law does past 24 m) and whose
`structures()` lets a storage show its owner (`shows_owner`). With the player 40 m off, F puts up
a house and X a house and a storage; F and X then go 30 m off and the player comes beside them.

What the player's client receives, through the Rust SDK probe (`drive.py --query --as-player`):
- the public `structure` rows carry each owner id, and `my_known_names` has F and not X, so the
  client's own rule (`living/game/src/looks.rs` `structure_name`) reads "<F>'s house" and "house";
- the player's own lines (`my_experience`) notice F's house "built by <F>" though F is too far
  away to make out, X's house with no owner, and X's storage "built by <X>" (it shows its owner).
The world's script is installed again at the end. Admin calls set the scene; they are not
something a player can do. Writes `RUN/house-*.jsonl` and `RUN/house_label.json`. Python
standard library only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
FAR = "someone too far away to make out"
FAR_LAW = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'
SHOWS = 'fn structures() { let l = base_structures(); for i in 0..l.len() { if l[i].name == "storage" { l[i].shows_owner = true; } } l }'
THOUGHT = {"kind": "talk", "summary": "verify-client house-label line", "detail": "", "latency_ms": 0, "tokens": 0, "model": "", "reference": ""}


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r.stdout


def sql(rid, query, *flags):
    out = run(V, "sql", "--run", rid, query, *flags)
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def call(rid, reducer, args):
    run(V, "call", "--run", rid, reducer, json.dumps(args), "--as-admin")


def stream(rid, name, query, table):
    """What the player's client holds of `table` after subscribing to `query` (SDK probe), by id."""
    run(DRIVE, "--run", rid, "--query", query, "--as-player", "--seconds", 5, "--save", name)
    rows = {}
    for line in (ROOT / ".local/living/verify" / rid / f"{name}.jsonl").read_text().splitlines():
        ev = json.loads(line)
        for r in (ev.get("tables") or {}).get(table, []) + [x for k in ("inserts", "inserted") for x in ev.get(k) or []]:
            if isinstance(r, dict) and "id" in r:
                rows[r["id"]] = r
    return rows


def client_name(known, me, kind, owner):
    """`living/game/src/looks.rs` `structure_name`, as the shipped client has it."""
    if owner == 0:
        return kind
    if owner == me:
        return f"your {kind}"
    return f"{known[owner]}'s {kind}" if owner in known else kind


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    out = ROOT / ".local/living/verify" / rid
    base = sql(rid, "SELECT source FROM script")[0]["source"]
    overlay = base.replace("fn perceived_of(p)", "fn base_perceived_of(p)", 1).replace("fn structures()", "fn base_structures()", 1) + "\n" + FAR_LAW + "\n" + SHOWS + "\n"
    (out / "house-overlay.rhai").write_text(overlay)
    checks, result = {}, {}
    try:
        run(V, "player", "--run", rid, "join", "Wren Abbot")
        me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
        before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
        call(rid, "spawn_crowd", [2, True])
        f, x = sorted(c["id"] for c in sql(rid, "SELECT id FROM character") if c["id"] not in before)
        names = {c["id"]: c["name"] for c in sql(rid, "SELECT id, name FROM character")}
        for who in (f, x):
            call(rid, "set_behavior", [who, json.dumps({"wait": 300})])
        body = sql(rid, "SELECT * FROM my_body", "--as-player")[0]
        bx, by = body["x"], body["y"]
        call(rid, "place_at", [f, bx + 1.5, by])
        time.sleep(2)
        call(rid, "mind_say", [f, f"I'm {names[f]}.", me, "say", 0, THOUGHT])
        time.sleep(2.5)
        run(ROOT / "living/tools/install_script.py", f"verify-{rid}", out / "house-overlay.rhai")
        call(rid, "place_at", [me, bx, by - 40.0])
        call(rid, "place_at", [f, bx - 3.0, by])
        call(rid, "place_structure", [f, "house"])
        call(rid, "place_at", [x, bx + 3.0, by])
        call(rid, "place_structure", [x, "house"])
        call(rid, "place_at", [x, bx + 3.0, by + 2.0])
        call(rid, "place_structure", [x, "storage"])
        call(rid, "place_at", [f, bx - 30.0, by])
        call(rid, "place_at", [x, bx + 30.0, by])
        call(rid, "place_at", [me, bx, by + 1.0])
        time.sleep(4)
        known = {k["id"]: k["name"] for k in stream(rid, "house-known", "SELECT * FROM my_known_names", "my_known_names").values()}
        built = {(s["owner"], s["kind"]): s for s in stream(rid, "house-structures", "SELECT * FROM structure", "structure").values() if s["owner"] in (f, x)}
        lines = [r["text"] for r in stream(rid, "house-lines", f"SELECT * FROM my_experience WHERE observer = {me}", "my_experience").values()]
        fh, xh, xs = built.get((f, "house")), built.get((x, "house")), built.get((x, "storage"))
        checks["F is in my_known_names (introduced), X is not"] = f in known and x not in known
        checks["the public structure rows carry the owners"] = bool(fh and xh and xs)
        checks["client rule: F's house is named, X's house is not"] = bool(fh and xh) and client_name(known, me, "house", fh["owner"]) == f"{names[f]}'s house" and client_name(known, me, "house", xh["owner"]) == "house"
        checks["player notices F's house built by F, F too far to make out"] = any(f"house built by {names[f]}" in t for t in lines)
        checks["player notices X's house with no owner"] = any(t.startswith("You notice a house") and "built by" not in t for t in lines)
        checks["player notices X's storage built by X (it shows its owner)"] = any(f"storage built by {names[x]}" in t for t in lines)
        checks["no line names an owner as a far figure"] = not [t for t in lines if f"built by {FAR}" in t]
        result = {"player": me, "f": names[f], "x": names[x], "known": known, "structures": {f"{k[0]}:{k[1]}": v for k, v in built.items()},
                  "lines": [t for t in lines if "notice" in t], "client_reads_storage_as": xs and client_name(known, me, "storage", xs["owner"]), "checks": checks}
    finally:
        run(ROOT / "living/tools/install_script.py", f"verify-{rid}", check=False)
    (out / "house_label.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if checks and all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
