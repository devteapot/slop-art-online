#!/usr/bin/env python3
"""Someone too far away to make out, as a real client receives them (far-label, docs/STRANGERS.md §1).

    far_label.py --run client-...      (a run launched with verify.py launch, any seed)

The player joins (its own identity). The admin installs an overlay of the shipped script whose
`perceived_of` law, as Cullet's does past 24 m, marks anyone farther than 4 m `far`; spawns two
minded strangers, holds them still and places one 2 m and one 6 m from the player. The player's
`seen_characters` is then streamed through the Rust SDK probe (`drive.py --query --as-player`):
the near one is labelled "a stranger", the far one "someone too far away to make out", neither
with a name. The far one is brought to 2 m and the stream must relabel it "a stranger". The
shipped script is installed again at the end. Admin calls (`install_script`, `spawn_crowd`,
`set_behavior`, `place_at`) set the scene; they are not something a player can do. Writes
`RUN/far-seen-*.jsonl` and `RUN/far_label.json`. Python standard library only.
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


def stream(rid, name, seconds=6):
    """The player's seen_characters through the SDK probe: the last row set it held, by id."""
    run(DRIVE, "--run", rid, "--query", "SELECT * FROM seen_characters", "--as-player", "--seconds", seconds, "--save", name)
    rows = {}
    for line in (ROOT / ".local/living/verify" / rid / f"{name}.jsonl").read_text().splitlines():
        ev = json.loads(line)
        # `initial` holds the subscribed rows by table; later events their changes.
        for r in (ev.get("tables") or {}).get("seen_characters", []) + [x for k in ("inserts", "inserted") for x in ev.get(k) or []]:
            if isinstance(r, dict) and "id" in r:
                rows[r["id"]] = r
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    rid, out, checks = a.run, ROOT / ".local/living/verify" / a.run, {}
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    overlay = shipped.replace("fn perceived_of(p)", "fn base_perceived_of(p)", 1) + "\n" + FAR_LAW + "\n"
    (out / "far-overlay.rhai").write_text(overlay)
    try:
        run(V, "player", "--run", rid, "join", "FarProbe")
        me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
        before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
        call(rid, "spawn_crowd", [2, True])
        near, far = sorted(c["id"] for c in sql(rid, "SELECT id FROM character") if c["id"] not in before)
        for x in (near, far):
            call(rid, "set_behavior", [x, json.dumps({"wait": 300})])
        run(ROOT / "living/tools/install_script.py", f"verify-{rid}", out / "far-overlay.rhai")
        body = sql(rid, "SELECT * FROM my_body", "--as-player")[0]
        call(rid, "place_at", [near, body["x"] + 2.0, body["y"]])
        call(rid, "place_at", [far, body["x"] + 6.0, body["y"]])
        time.sleep(3)
        seen = stream(rid, "far-seen-apart")
        n, f = seen.get(near, {}), seen.get(far, {})
        checks["near (2 m) is a stranger, unnamed"] = n.get("label") == "a stranger" and n.get("name") == ""
        checks["far (6 m) is someone too far away to make out, unnamed"] = f.get("label") == FAR and f.get("name") == ""
        call(rid, "place_at", [far, body["x"], body["y"] + 2.0])
        time.sleep(3)
        seen2 = stream(rid, "far-seen-closer")
        checks["brought to 2 m, the far one is a stranger"] = seen2.get(far, {}).get("label") == "a stranger"
        result = {"player": me, "near": near, "far": far, "apart": {"near": n, "far": f}, "closer": seen2.get(far), "checks": checks}
    finally:
        run(ROOT / "living/tools/install_script.py", f"verify-{rid}", check=False)
    (out / "far_label.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
