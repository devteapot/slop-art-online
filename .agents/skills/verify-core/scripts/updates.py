#!/usr/bin/env python3
"""Module updates in place on a ticking world (look-1, docs/LOOK.md §7 "The update panic").

    updates.py --run RUN --chain A,B,C [--chain A,D ...] [--settle 8]

Each `--chain` is a list of module files already in the server's `/wasm` mount (without `.wasm`).
The first is published fresh as `verify-<run>-<n>`; each next one is published over it with its
data kept, as `just living-publish` updates a world. After each step the driver waits `--settle`
seconds and reads, as the owner:
- the module log since the step: `PANIC` lines (a scheduled reducer that trapped) and the guard's
  "the database's tables changed under this module instance" lines (an outgoing instance that
  touched nothing);
- `stats.ticks` twice a second apart (the world still ticks), `stats.at_ms` (housekeeping runs);
- the `world` row's run and seed, the character count, and the `look` row count where the table
  exists (nothing was lost);
- the scheduled rows `tick_timer` and `slow_timer` (the clocks are kept);
- with `--relook GEN`, after a chain's last update: the admin's `relook(GEN)`, then the same reads
  (a world from before looks takes its seed's looks and goes on ticking);
- with `--crowd N`, after a chain's first step: N people made by the old module (`spawn_crowd`);
- with `--backfill SEED` (sex-1, docs/LIVING_CORE.md "Body sex"), after a chain's last update and
  before any relook: the `sex` row count (none on a world from before sex), the admin's
  `backfill_sex()` twice (the second gives no one a row: idempotent), then every person has one,
  each seeded resident (by name, minded) has the seed's `sex`, and, after the relook, every
  person's look entry shows their sex (the entry's lines' forms in the seed's `looks`).
Each chain's database is deleted at the end. Writes `RUN/updates.json` and each step's module
log. Uses the worker's own server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`) or the shared one.
Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CONTAINER = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")


def stdb(*args, check=True):
    r = subprocess.run(["podman", "exec", "-i", CONTAINER, "spacetime", *args], capture_output=True, text=True, timeout=600)
    if check and r.returncode:
        raise RuntimeError(f"spacetime {' '.join(args[:3])}: {r.stderr[-600:]}")
    return r.stdout


def sql(db, q):
    out = stdb("sql", "-s", "local", db, q, check=False)
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("WARNING") and not set(l.strip()) <= set("-+")]
    if len(lines) < 2:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [dict(zip(head, [c.strip().strip('"') for c in l.split("|")])) for l in lines[1:]]


def one(db, q, key):
    rows = sql(db, q)
    return rows[0].get(key) if rows else None


def state(db):
    t1 = one(db, "SELECT ticks FROM stats", "ticks")
    time.sleep(1.0)
    t2 = one(db, "SELECT ticks, at_ms FROM stats", "ticks")
    w = (sql(db, "SELECT run, seed FROM world") or [{}])[0]
    return {"ticks": [t1, t2], "ticking": t1 is not None and t2 is not None and int(t2) > int(t1), "housekeeping_at_ms": one(db, "SELECT at_ms FROM stats", "at_ms"),
            "world": w, "characters": one(db, "SELECT COUNT(*) AS n FROM character", "n"), "looks": one(db, "SELECT COUNT(*) AS n FROM look", "n"),
            "tick_timer": one(db, "SELECT COUNT(*) AS n FROM tick_timer", "n"), "slow_timer": one(db, "SELECT COUNT(*) AS n FROM slow_timer", "n")}


def backfill(db, seed_name, path, relook):
    """`backfill_sex()` on an updated world (before a relook), or the checks after one."""
    seed = json.loads((ROOT / "living/seeds" / f"{seed_name}.json").read_text())
    given = {r["name"]: {"f": "1", "m": "2"}[r["sex"]] for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", []) if r.get("sex") in ("f", "m")}
    people = sql(db, "SELECT id, name, ai FROM character WHERE kind = 'person'")
    report = json.loads(path.read_text()) if path.exists() else {}
    if relook is None:
        report["rows_before"] = one(db, "SELECT COUNT(*) AS n FROM sex", "n")
        calls = []
        for _ in range(2):
            r = subprocess.run(["podman", "exec", "-i", CONTAINER, "spacetime", "call", "-s", "local", db, "backfill_sex"], capture_output=True, text=True, timeout=120)
            time.sleep(1.5)
            calls.append(r.returncode)
        report["calls"] = calls
        report["chronicle"] = [r.get("text", "") for r in sql(db, "SELECT text FROM chronicle WHERE kind = 'sex'")]
    sexes = {r["id"]: r["sex"] for r in sql(db, "SELECT id, sex FROM sex")}
    report["people"], report["rows"] = len(people), len(sexes)
    wrong = [(c["name"], sexes.get(c["id"]), given[c["name"]]) for c in people if c["name"] in given and c["ai"] == "true" and sexes.get(c["id"]) != given[c["name"]]]
    checks = report.setdefault("checks", {})
    if relook is None:
        checks["a world from before sex has no sex rows"] = report["rows_before"] in ("0", 0)
        checks["backfill_sex succeeds twice"] = calls == [0, 0]
        checks["the second backfill gives no one a row (idempotent)"] = len(report["chronicle"]) == 2 and report["chronicle"][1].startswith("0 people given")
        checks["after backfill every person has a sex row"] = len(sexes) == len(people) and all(v in ("1", "2") for v in sexes.values())
        checks["each seeded resident has the seed's sex"] = not wrong
        report["wrong_seeded"] = wrong[:10]
    else:
        looks = seed.get("looks") or {}
        shows = lambda p: ({{"woman": "1", "girl": "1", "man": "2", "boy": "2"}.get((looks.get("words", {}).get(k, {}).get("form") or "").strip().split(" ")[-1]) for k in looks.get("people", {}).get(p, {}).values()} - {None})
        rows = sql(db, "SELECT id, person FROM look")
        mismatch = [(r["id"], sexes.get(r["id"]), sorted(shows(r["person"]))) for r in rows if shows(r["person"]) != {sexes.get(r["id"])}]
        checks[f"after relook({relook}) every person's look shows their sex"] = bool(rows) and not mismatch
        report["looks_after_relook"], report["mismatch_after_relook"] = len(rows), mismatch[:10]
    path.write_text(json.dumps(report, indent=1) + "\n")
    for k, v in checks.items():
        if relook is None or k.startswith("after relook"):
            print(("PASS " if v else "FAIL ") + k, flush=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--chain", action="append", required=True)
    ap.add_argument("--settle", type=float, default=8.0)
    ap.add_argument("--relook", help="after each chain's last step, the admin's relook(GEN) (a world from before looks takes its seed's)")
    ap.add_argument("--crowd", type=int, default=0, help="after each chain's first step, the admin's spawn_crowd(N): people made by the old module (pool looks where it has them)")
    ap.add_argument("--backfill", help="after each chain's last step (before any relook), the admin's backfill_sex() twice, checked against living/seeds/SEED.json")
    a = ap.parse_args()
    out = ROOT / ".local/living/verify" / a.run
    out.mkdir(parents=True, exist_ok=True)
    report = {"run": a.run, "container": CONTAINER, "chains": []}
    for n, chain in enumerate(a.chain):
        mods = chain.split(",")
        db = f"verify-{a.run}-{n}"
        steps = []
        try:
            seen = 0
            for i, m in enumerate(mods):
                stdb("publish", "-s", "local", "-b", f"/wasm/{m}.wasm", db, *(["--delete-data"] if i == 0 else []), "-y")
                time.sleep(a.settle)
                if a.crowd and i == 0:
                    stdb("call", "-s", "local", db, "spawn_crowd", str(a.crowd), "true")
                    time.sleep(1)
                log = stdb("logs", "-s", "local", db, "-n", "100000", check=False)
                lines = log.splitlines()
                new = lines[seen:]
                seen = len(lines)
                (out / f"chain{n}-step{i}-{m}.log").write_text("\n".join(new) + "\n")
                panics = [l[:300] for l in new if " PANIC: " in l]
                guarded = [l[:300] for l in new if "tables changed under this module instance" in l]
                s = state(db)
                steps.append({"module": m, "kept_data": i > 0, "panics": panics, "guard_lines": guarded, **s})
                if a.backfill and i == len(mods) - 1 and i > 0:
                    steps[-1]["backfill"] = backfill(db, a.backfill, out / f"chain{n}-backfill.json", relook=None)
                if a.relook and i == len(mods) - 1 and i > 0:
                    r = subprocess.run(["podman", "exec", "-i", CONTAINER, "spacetime", "call", "-s", "local", db, "relook", json.dumps(a.relook)], capture_output=True, text=True, timeout=120)
                    time.sleep(2)
                    steps[-1:] = []
                    s["relook"] = {"exit": r.returncode, "after": state(db)}
                    s["relook"]["panics_since"] = [l[:300] for l in stdb("logs", "-s", "local", db, "-n", "100000", check=False).splitlines()[seen:] if " PANIC: " in l]
                    if a.backfill:
                        s["backfill"] = backfill(db, a.backfill, out / f"chain{n}-backfill.json", relook=a.relook)
                    steps.append({"module": m, "kept_data": i > 0, "panics": panics, "guard_lines": guarded, **s})
                print(f"chain {n} step {i} {m}: panics {len(panics)}, guard {len(guarded)}, ticking {s['ticking']}, looks {s['looks']}, characters {s['characters']}, timers {s['tick_timer']}/{s['slow_timer']}" + (f"; relook exit {s['relook']['exit']}, looks {s['relook']['after']['looks']}, ticking {s['relook']['after']['ticking']}, panics {len(s['relook']['panics_since'])}" if s.get("relook") else ""), flush=True)
        finally:
            stdb("call", "-s", "local", db, "set_paused", "true", check=False)
            stdb("delete", "-s", "local", db, "-y", check=False)
        report["chains"].append({"chain": mods, "db": db, "steps": steps,
                                 "updates_without_panic": sum(1 for s in steps[1:] if not s["panics"]), "updates": len(steps) - 1})
    (out / "updates.json").write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
