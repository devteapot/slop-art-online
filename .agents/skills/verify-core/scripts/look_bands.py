#!/usr/bin/env python3
"""Look bands at a lab pace (look-1, docs/LOOK.md §4): a child crosses 12 and then 18 years, each
one rewrite of its `look` row through the `look.due` index; a stage change (adult to elder)
rewrites the look in `grew`, in the stage change's transaction; a death deletes the row.

    look_bands.py seed --run RUN      # writes RUN/look-bands.json; launch with --seed <abs path>/look-bands
    look_bands.py drive --run RUN     # about 7 minutes

The seed is `living/seeds/plan-test.json` (its looks fixture, generation `fixture-1`) at a lab pace:
`year_days` 1 and `life_pace` 0.01, so a year is 0.01 game days, 7.2 real seconds on the
12-minute day. Nell Hollis is made 6 (12 at about 43 s, her stage 1 to 2 at 16.1 years, 18 at
about 86 s after genesis) and Tom Hollis 52 (an elder at 59.5, about 54 s; his death of old age
falls between 61 and 70 years, 65 to 130 s). Nobody else's age changes. No mind service runs.

The driver polls the private `look` and `character` rows as the owner every 0.5 s, then reads the
module log for the authority's `look: #id <band> -> <band> (<why>)` lines (one per band change:
`due` from housekeeping's index range over `look.next_ms`, `grew` from a stage change). It also
checks the source: housekeeping reads `look.due().filter(..=now)`, and `look` rows are iterated
only in `retime_all` (a script install) and `relook` (an admin's), never per second. Writes
`RUN/look-bands.json` (checks) and `RUN/look-bands-samples.jsonl`. Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
BANDS = ["infant", "child", "youth", "adult", "elder"]
CHILD, OLD = "Nell Hollis", "Tom Hollis"


def make_seed(run):
    out = ROOT / ".local/living/verify" / run
    out.mkdir(parents=True, exist_ok=True)
    seed = json.loads((ROOT / "living/seeds/plan-test.json").read_text())
    seed["run"] = "look-bands"
    seed["year_days"] = 1
    seed["life_pace"] = 0.01
    for r in seed["towns"][0]["residents"]:
        if r["name"] == OLD:
            r["age"] = 52
        if r["name"] == CHILD:
            r["age"] = 6
    path = out / "look-bands.json"
    path.write_text(json.dumps(seed, indent=1) + "\n")
    print(f"wrote {path}; launch with --seed {path.with_suffix('')}")


def sh(*args, check=True):
    r = subprocess.run([*map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=600)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r.stdout


def sql(rid, q):
    out = sh(sys.executable, V, "sql", "--run", rid, q)
    i = out.find("[")
    return json.loads(out[i:]) if i >= 0 else []


def drive(run, seconds):
    out = ROOT / ".local/living/verify" / run
    st = json.loads((out / "state.json").read_text())
    people = {c["name"]: c for c in sql(run, "SELECT id, name, born_ms, birth_age_days, stage, alive FROM character WHERE kind = 'person'")}
    child, old = people[CHILD]["id"], people[OLD]["id"]
    world = sql(run, "SELECT * FROM world")[0]
    samples = out / "look-bands-samples.jsonl"
    seen = {child: [], old: []}
    mismatched = 0
    t0 = time.time()
    with samples.open("a") as f:
        while time.time() - t0 < seconds:
            looks = {l["id"]: l for l in sql(run, f"SELECT id, line, band, next_ms FROM look WHERE id = {child} OR id = {old}")}
            chars = {c["id"]: c for c in sql(run, f"SELECT id, stage, alive FROM character WHERE id = {child} OR id = {old}")}
            row = {"t": round(time.time(), 2), "looks": looks, "chars": chars}
            f.write(json.dumps(row) + "\n")
            for i in (child, old):
                l = looks.get(str(i)) or looks.get(i)
                c = chars.get(str(i)) or chars.get(i)
                band = l["band"] if l else None
                if not seen[i] or seen[i][-1][1] != band:
                    seen[i].append((round(time.time() - t0, 1), band, c["stage"] if c else None, l["line"] if l else None))
                if l and c and (c["stage"] == 3) != (band == 4):
                    mismatched += 1
            if seen[old] and seen[old][-1][1] is None and seen[child][-1][1] == 3:
                break
            time.sleep(0.5)
    logs = sh("living/tools/stdb", "logs", "-s", "local", st["db"], "-n", "100000")
    (out / "look-bands-module.log").write_text(logs)
    lines = re.findall(r"look: #(\d+) (\w+) -> (\w+) \((\w+)\)", logs)
    of = lambda i: [(a, b, why) for (x, a, b, why) in lines if int(x) == i]
    src_tick = (ROOT / "living/authority/src/tick.rs").read_text()
    src_look = (ROOT / "living/authority/src/look.rs").read_text()
    iters = [m.start() for m in re.finditer(r"ctx\.db\.look\(\)\.iter\(\)", src_look)]
    fns = [(m.start(), m[1]) for m in re.finditer(r"\bfn (\w+)\(", src_look)]
    owner = lambda pos: max((p, n) for p, n in fns if p < pos)[1]
    checks = {
        "the child crosses 12: child -> youth, once, from the due read": of(child).count(("child", "youth", "due")) == 1,
        "the child crosses 18: youth -> adult, once, from the due read": of(child).count(("youth", "adult", "due")) == 1,
        "the child's look changed band exactly twice": len(of(child)) == 2,
        "its stage change at 16.1 years (child to adult) kept the youth line": [b for _, b, *_ in seen[child]].count(2) == 1,
        "the old man's stage change rewrote his look in grew: adult -> elder, once": of(old).count(("adult", "elder", "grew")) == 1,
        "no poll saw the elder stage without the elder band, or the band without the stage": mismatched == 0,
        "housekeeping reads looks through the due index": "crate::look::due(ctx, now)" in src_tick and ".due().filter(..=now)" in src_look,
        "look rows are iterated only in retime_all and relook": {owner(p) for p in iters} <= {"retime_all", "relook"},
    }
    if seen[old] and seen[old][-1][1] is None:
        dead = sql(run, f"SELECT alive, cause FROM character WHERE id = {old}")
        checks["his death deleted his look row"] = bool(dead) and not dead[0]["alive"] and not sql(run, f"SELECT id FROM look WHERE id = {old}")
    result = {"world": {k: world[k] for k in ("life_pace", "year_days", "day_ms", "look_book")}, "child": child, "old": old,
              "observed": {CHILD: seen[child], OLD: seen[old]}, "log_lines": {CHILD: of(child), OLD: of(old)}, "polls_mismatched": mismatched, "checks": checks}
    (out / "look-bands.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["seed", "drive"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--seconds", type=float, default=420)
    a = ap.parse_args()
    if a.what == "seed":
        make_seed(a.run)
        return 0
    return drive(a.run, a.seconds)


if __name__ == "__main__":
    sys.exit(main())
