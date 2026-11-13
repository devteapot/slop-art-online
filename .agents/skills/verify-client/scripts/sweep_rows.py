#!/usr/bin/env python3
"""The rows a real client holds of the scene's people, step by step, under a law that reads distance
(the sweep's kept answers, docs/PERCEPTION.md "The perceived set").

    sweep_rows.py --run client-...      (a run launched with verify.py launch --seed cullet)
    sweep_rows.py --compare A.json B.json

On Cullet, whose `perceived_of` names someone only within `known_within` (24 m), the sweep keeps
what each row was projected from and projects it again only when that changed. This drives a
fixed scene through every input the kept rows depend on and records, after each step, the
player's `seen_characters` rows of the scene's people as the player's own client receives them
(the Rust SDK probe, `drive.py --query --as-player`), keyed by role, not id:

1. the player and six held strangers on an open ray, at 2, 10, 20, 23, 26 and 30 m (clear of the cut: a body stands where `place_at` puts it, within a metre);
2. the two beside the cut cross it (23 → 25.6 m, 26 → 23.4 m);
3. the one at 2 m tells the player its name;
4. that one goes to 28 m (known, too far away to make out), then back to 5 m;
5. the player learns a technique (a write that can change answers, none here);
6. the one at 10 m is killed (admin `kill`).

Each step checks what the law says (named within 24 m once known, "someone too far away to make
out" beyond, no health beyond) and, with `--expect-kept`, that the world's log has `sweep kept`
lines with kept rows and no differences (the `regard_cache_check` law is on for the scene).
`--compare` diffs two runs' `sweep_rows.json` (main's module and a branch's): the same rows at
every step. Admin calls set the scene. Writes `RUN/sweep-seen-*.jsonl` and `RUN/sweep_rows.json`.
"""

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
STDB = ROOT / "living/tools/stdb"
FAR = "someone too far away to make out"
FIELDS = ("name", "label", "kind", "stage", "folk", "style", "band", "hp", "max_hp", "look")


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


def stream(rid, name, seconds=5):
    """The player's seen_characters through the SDK probe: the rows it held at the end, by id (the
    initial set, then each insert, delete and update in order). Evidence is never overwritten."""
    name = f"{name}-{time.strftime('%H%M%S')}"
    run(DRIVE, "--run", rid, "--query", "SELECT * FROM seen_characters", "--as-player", "--seconds", seconds, "--save", name)
    rows = {}
    for line in (ROOT / ".local/living/verify" / rid / f"{name}.jsonl").read_text().splitlines():
        ev = json.loads(line)
        if ev.get("event") == "initial":
            rows = {r["id"]: r for r in (ev.get("tables") or {}).get("seen_characters", []) if isinstance(r, dict) and "id" in r}
        elif ev.get("table") == "seen_characters" and isinstance(ev.get("row"), dict):
            r = ev["row"]
            if ev["event"] == "delete":
                if rows.get(r.get("id")) == r:
                    rows.pop(r["id"])
            else:
                if ev["event"] == "update" and isinstance(ev.get("old"), dict):
                    rows.pop(ev["old"].get("id"), None)
                rows[r["id"]] = r
    return rows


def open_ray(rid, length):
    """Points 0..length m along a ray over open ground with a clear line (as verify-core's
    `open_ray`), in a fixed search order so two worlds from one seed give the same ray."""
    w = sql(rid, "SELECT width, height FROM world")[0]
    W, H = w["width"], w["height"]
    tiles = bytearray(W * H)
    for row in sql(rid, "SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[int(y) * W + int(x)] not in (2, 4, 7, 8, 9)
    for k in range(32):
        t = k * math.pi / 16
        dx, dy = math.cos(t), math.sin(t)
        for y in range(4, H - 4, 3):
            for x in range(4, W - 4, 3):
                pts = [(x + 0.5 + dx * i, y + 0.5 + dy * i) for i in range(length + 1)]
                if all(walk(px + ox, py + oy) for px, py in pts for ox, oy in ((0, 0), (-dy, dx), (dy, -dx))):
                    return (x + 0.5, y + 0.5), (dx, dy)
    raise RuntimeError(f"no open {length} m ray on this map")


def compare(a, b):
    """Every row of the scene's people equal at every step, except the player's own exact health:
    a joining character's maximum health comes from its genes, drawn afresh in each world, so it is
    set aside (and printed), not compared."""
    A, B = json.loads(Path(a).read_text()), json.loads(Path(b).read_text())
    diffs, own = [], []
    for step in sorted(set(A["steps"]) | set(B["steps"])):
        sa, sb = [dict(x or {}) for x in (A["steps"].get(step), B["steps"].get(step))]
        for x, y in ((sa, sb),):
            pa, pb = dict(x.pop("player", {})), dict(y.pop("player", {}))
            own.append({"step": step, "a": [pa.pop("hp", None), pa.pop("max_hp", None)], "b": [pb.pop("hp", None), pb.pop("max_hp", None)]})
            x["player"], y["player"] = pa, pb
        for role in sorted(set(sa) | set(sb)):
            if sa.get(role) != sb.get(role):
                diffs.append({"step": step, "role": role, "a": sa.get(role), "b": sb.get(role)})
    print(json.dumps({"steps": len(A["steps"]), "differ": diffs, "own_health_set_aside": own[:1]}, indent=1))
    print(("PASS " if not diffs else "FAIL ") + f"the same rows of the scene's people at every step ({len(A['steps'])} steps)")
    return 0 if not diffs else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run")
    ap.add_argument("--expect-kept", action="store_true", help="also require `sweep kept` log lines with kept rows and no difference")
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)
    rid, out, checks, steps = a.run, ROOT / ".local/living/verify" / a.run, {}, {}
    run(V, "player", "--run", rid, "join", "SweepProbe")
    me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
    before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
    call(rid, "spawn_crowd", [6, True])
    figures = sorted(c["id"] for c in sql(rid, "SELECT id FROM character") if c["id"] not in before)
    assert len(figures) == 6, figures
    for x in figures:
        call(rid, "set_behavior", [x, json.dumps({"wait": 600})])
    call(rid, "set_world_law", ["regard_cache_check", "true"])
    (o, (dx, dy)) = open_ray(rid, 32)
    at = lambda d: [o[0] + dx * d, o[1] + dy * d]
    role = {me: "player", **{f: f"figure{i}" for i, f in enumerate(figures)}}

    def place(dists):
        call(rid, "place_at", [me, *at(0)])
        for f, d in zip(figures, dists):
            if d is not None:
                call(rid, "place_at", [f, *at(d)])

    def step(label):
        # A call as the player keeps its person present (the minds take over after `takeover_s`).
        run(V, "player", "--run", rid, "move", "0", "0", check=False)
        time.sleep(2)
        rows = stream(rid, f"sweep-seen-{label}")
        steps[label] = {role[r["id"]]: {k: r.get(k) for k in FIELDS} for r in rows.values() if r["id"] in role}
        return {role[r["id"]]: r for r in rows.values() if r["id"] in role}

    dists = [2, 10, 20, 23, 26, 30]
    place(dists)
    s = step("1-placed")
    checks["1: the player's own row is named"] = s.get("player", {}).get("name") != ""
    checks["1: within 24 m strangers are 'a stranger' with a band"] = all(s.get(f"figure{i}", {}).get("label") == "a stranger" and s[f"figure{i}"].get("band") != 255 for i in (0, 1, 2, 3))
    checks["1: beyond 24 m 'someone too far away to make out', no band"] = all(s.get(f"figure{i}", {}).get("label") == FAR and s[f"figure{i}"].get("band") == 255 for i in (4, 5))
    place([None, None, None, 25.6, 23.4, None])
    s = step("2-crossed")
    checks["2: 23 m to 25.6 m is too far away to make out"] = s.get("figure3", {}).get("label") == FAR
    checks["2: 26 m to 23.4 m is a stranger"] = s.get("figure4", {}).get("label") == "a stranger"
    name = sql(rid, f"SELECT name FROM character WHERE id = {figures[0]}")[0]["name"]
    call(rid, "set_behavior", [figures[0], json.dumps({"seq": [{"say": f"I am {name}."}, {"wait": 600}]})])
    end = time.monotonic() + 20
    while time.monotonic() < end and not sql(rid, f"SELECT * FROM acquaintance WHERE observer = {me} AND known = {figures[0]}"):
        time.sleep(0.5)
    s = step("3-introduced")
    checks["3: told its name, the one at 2 m is named"] = s.get("figure0", {}).get("name") == name
    place([28, None, None, None, None, None])
    s = step("4-known-far")
    checks["4: known but at 28 m, too far away to make out"] = s.get("figure0", {}).get("label") == FAR and s["figure0"].get("name") == ""
    place([5, None, None, None, None, None])
    s = step("4-known-near")
    checks["4: back at 5 m, named again"] = s.get("figure0", {}).get("name") == name
    call(rid, "grant_know_how", [me, "wound_tending"])
    step("5-learned")
    call(rid, "kill", [figures[1], "verify"])
    s = step("6-killed")
    checks["6: the killed one's row is gone"] = "figure1" not in s
    call(rid, "set_world_law", ["regard_cache_check", "false"])
    log = subprocess.run([str(STDB), "logs", "-s", "local", f"verify-{rid}", "-n", "200000"], capture_output=True, text=True, timeout=300).stdout
    kept = [tuple(int(x) for x in m.groups()) for m in re.finditer(r"sweep kept: kept=(\d+) projected=(\d+) full=(\d+) compared=(\d+) differed=(\d+)", log)]
    errors = [l for l in log.splitlines() if "sweep kept: #" in l][:10]
    total = [sum(k[i] for k in kept) for i in range(5)]
    if a.expect_kept:
        checks["the kept sweep ran (rows kept) and every row was compared"] = total[0] > 0 and total[3] > 0
        checks["no row differed from a fresh projection"] = total[4] == 0 and not errors
    result = {"player": me, "figures": figures, "ray": [o, [dx, dy]], "steps": steps, "kept": dict(zip(("kept", "projected", "full", "compared", "differed"), total)), "errors": errors, "checks": checks}
    (out / "sweep_rows.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["kept"]))
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
