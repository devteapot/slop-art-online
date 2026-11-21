#!/usr/bin/env python3
"""Are the compiled seeds fresh? Files only: no publish, no build, no model (docs/TOOLING.md,
"Seed freshness").

A world authored under `living/seeds/worlds/<world>/` is compiled into a tracked seed,
`living/seeds/<into>.json` (`cast.json` or `world.json` names it with `into`; otherwise the
world's own name), by `living/tools/author_world.py <world> --compile-only`, and Cullet's land,
plan, ways and town life by `living/tools/cullet_plan.py`. The compilers stamp nothing but the look
data's own `generation`, so each block is compared with its source as the compiler copies it:

- `looks`: the seed's `looks.generation` against `looks.json`'s (the look generator's stamp, e.g.
  `c4-cbcc40bf`), then the whole `looks` block, then each resident's `look` that `looks.json`
  names (`residents`);
- `ways`: every entry of `ways.json`'s `top`, `common` and `occupations` as the seed's `ways`
  holds it, its `town_life` as the seed's, and its `work` within the seed's `town_life.work`;
- `residents`: the residents (everyone with a drafted sheet in `sheets/*.json`) by name, and each
  sheet's narrative as drafted;
- `plan`: a world with a plan compiler that checks itself (Cullet: `cullet_plan.py --check`, which
  rebuilds plan.json, the seed's land, plan, ways and town life, and the game's ground map in
  memory and compares them byte for byte).
- `compile`: the whole seed. `author_world.py <world> --compile-only --seed-out TMP` compiles the
  world from its sources over the tracked seed (as a recompile would) into a scratch file, and the
  two must be equal as JSON. This catches what the targeted checks above do not name: a field the
  compiler learned after the seed was last compiled (aske-coast's `sheet.pastimes`, 2026-11-20).
- `derived`: a tracked seed whose `run` names an authored world without being that world's seed
  (aske-coast's `-crypercept`, `-dynamic`, `-yieldnorm`, which differ only in their own `rules`)
  must carry the compiled world's residents exactly; nothing recompiles it, so it is rebuilt from
  the compiled seed by copying the residents.

Usage: seed_fresh.py [--json PATH] [--world NAME]...
Prints one line per stale block, `stale <seed> <block>: <what differs>; recompile: <command>`,
and `seeds fresh: …` at the end. Exit 0 all fresh, 1 something stale, 2 unreadable sources.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORLDS = ROOT / "living/seeds/worlds"
# Plan compilers with a --check of their own: world -> command (run from the repository root).
PLAN_CHECKS = {"cullet": ["living/tools/cullet_plan.py", "--check"]}


def recompile(world):
    steps = [f"python3 living/tools/author_world.py {world} --compile-only"]
    if world in PLAN_CHECKS:
        steps.insert(0, f"python3 {PLAN_CHECKS[world][0]}")
    return " && ".join(steps)


def load(path):
    return json.loads(path.read_text())


def residents(seed):
    return {r["name"]: r for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", [])}


def first_difference(a, b, path=""):
    """Where two JSON values first differ, for the message."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k} only in {'the seed' if k in a else 'the source'}"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path} has {len(a)} entries in the seed, {len(b)} in the source"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path or 'the value'} differs"


def check_world(wd):
    """[(block, what differs)] for one authored world, and the seed it compiles into."""
    meta = next((load(wd / f) for f in ("cast.json", "world.json") if (wd / f).exists()), {})
    into = meta.get("into") or wd.name
    seed_path = ROOT / f"living/seeds/{into}.json"
    if not seed_path.exists():
        return into, [("seed", f"{seed_path.relative_to(ROOT)} does not exist")]
    seed = load(seed_path)
    people = residents(seed)
    stale = []

    looks_f = wd / "looks.json"
    if looks_f.exists():
        looks = load(looks_f)
        have, want = (seed.get("looks") or {}).get("generation"), looks["looks"].get("generation")
        if have != want:
            stale.append(("looks", f"look generation {have} in the seed, {want} in {looks_f.relative_to(ROOT)}"))
        elif seed.get("looks") != looks["looks"]:
            stale.append(("looks", f"same generation {want}, but {first_difference(seed.get('looks'), looks['looks'], 'looks')}"))
        wrong = sorted(n for n, look in looks.get("residents", {}).items() if n in people and people[n].get("look") != look)
        if wrong:
            stale.append(("looks", f"{len(wrong)} residents' look differ from looks.json's ({', '.join(wrong[:3])}{', …' if len(wrong) > 3 else ''})"))

    ways_f = wd / "ways.json"
    if ways_f.exists():
        ways = load(ways_f)
        held = seed.get("ways") or {}
        off = [f"ways.{part}.{k}" for part in ("top", "common", "occupations") if isinstance(ways.get(part), dict)
               for k, v in ways[part].items() if (held.get(part) or {}).get(k) != v]
        off += [f"ways.{part}" for part in ("top", "common", "occupations")
                if part in ways and not isinstance(ways[part], dict) and held.get(part) != ways[part]]
        if "town_life" in ways and seed.get("town_life") != ways["town_life"]:
            off.append(f"town_life ({first_difference(seed.get('town_life'), ways['town_life'], 'town_life')})")
        work = (seed.get("town_life") or {}).get("work") or {}
        off += [f"town_life.work.{k}" for k, v in (ways.get("work") or {}).items() if work.get(k) != v]
        if off:
            stale.append(("ways", f"{len(off)} entries differ from {ways_f.relative_to(ROOT)}: {', '.join(off[:4])}{', …' if len(off) > 4 else ''}"))

    sheets_dir = wd / "sheets"
    if sheets_dir.is_dir():
        sheets = {}
        for f in sorted(sheets_dir.glob("*.json")):
            sheets.update(load(f))
        missing = sorted(set(sheets) - set(people))
        extra = sorted(n for n, r in people.items() if r.get("sheet") is not None and n not in sheets)
        if missing or extra:
            stale.append(("residents", f"{len(missing)} drafted sheets have no resident ({', '.join(missing[:3])}), "
                                       f"{len(extra)} residents have no drafted sheet ({', '.join(extra[:3])})"))
        told = sorted(n for n, sh in sheets.items() if n in people and str(sh.get("narrative", "")).strip()
                      != str((people[n].get("sheet") or {}).get("narrative", "")).strip())
        if told:
            stale.append(("residents", f"{len(told)} residents' sheet narratives differ from {sheets_dir.relative_to(ROOT)} "
                                       f"({', '.join(told[:3])}{', …' if len(told) > 3 else ''})"))

    compiled = compile_seed(wd, into)
    if isinstance(compiled, str):
        stale.append(("compile", compiled))
    elif compiled != seed:
        stale.append(("compile", f"{count_differences(seed, compiled)} differences from a fresh compile, first {first_difference(seed, compiled)}"))

    if wd.name in PLAN_CHECKS:
        got = subprocess.run([sys.executable, str(ROOT / PLAN_CHECKS[wd.name][0]), *PLAN_CHECKS[wd.name][1:]],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
        if got.returncode:
            stale.append(("plan", f"{' '.join(PLAN_CHECKS[wd.name])} exit {got.returncode}: "
                                  f"{(got.stdout + got.stderr).strip().replace(str(ROOT) + '/', '')[-300:]}"))
    return into, stale, compiled if not isinstance(compiled, str) else None


def compile_seed(wd, into):
    """The world compiled now from its sources over the tracked seed, or what stopped the compile."""
    with tempfile.TemporaryDirectory(prefix="seed-fresh-") as tmp:
        out = Path(tmp) / f"{into}.json"
        got = subprocess.run([sys.executable, str(ROOT / "living/tools/author_world.py"), wd.name, "--compile-only", "--seed-out", str(out)],
                             cwd=ROOT, capture_output=True, text=True, timeout=300)
        if got.returncode or not out.exists():
            return f"author_world.py {wd.name} --compile-only exit {got.returncode}: {(got.stdout + got.stderr).strip()[-300:]}"
        return load(out)


def count_differences(a, b):
    """How many leaves differ between two JSON values (a key on one side only counts once)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return sum(1 if k not in a or k not in b else count_differences(a[k], b[k]) for k in set(a) | set(b))
    if isinstance(a, list) and isinstance(b, list):
        return 1 if len(a) != len(b) else sum(count_differences(x, y) for x, y in zip(a, b))
    return 0 if a == b else 1


def check_derived(compiled_by_run):
    """[(seed, run, why)] for tracked seeds derived from a compiled world: the same residents, exactly."""
    stale = []
    for path in sorted((ROOT / "living/seeds").glob("*.json")):
        try:
            seed = load(path)
        except ValueError:
            continue
        run = seed.get("run") if isinstance(seed, dict) else None
        if run not in compiled_by_run or path.stem == run:
            continue
        want, have = residents(compiled_by_run[run]), residents(seed)
        if want != have:
            off = sorted(n for n in set(want) | set(have) if want.get(n) != have.get(n))
            stale.append((path.stem, run, f"{len(off)} residents differ from {run}'s compiled residents ({', '.join(off[:3])}{', …' if len(off) > 3 else ''}), "
                                     f"first {first_difference(have, want, 'residents')}"))
    return stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="write {seed: {block: what differs}} and the commands here")
    ap.add_argument("--world", action="append", help="only this authored world (repeatable)")
    a = ap.parse_args(argv)
    worlds = sorted(d for d in WORLDS.iterdir() if d.is_dir() and (not a.world or d.name in a.world))
    report, fresh = {}, []
    try:
        compiled_by_run = {}
        for wd in worlds:
            into, stale, compiled = check_world(wd)
            if compiled is not None:
                compiled_by_run[into] = compiled
            if not stale:
                fresh.append(into)
            for block, why in stale:
                print(f"stale {into} {block}: {why}; recompile: {recompile(wd.name)}", flush=True)
                report.setdefault(into, {"world": wd.name, "recompile": recompile(wd.name), "stale": {}})["stale"].setdefault(block, []).append(why)
        for name, run, why in check_derived(compiled_by_run):
            how = f"copy the residents of living/seeds/{run}.json (recompiled) into living/seeds/{name}.json"
            print(f"stale {name} derived: {why}; rebuild: {how}", flush=True)
            report.setdefault(name, {"world": None, "recompile": how, "stale": {}})["stale"].setdefault("derived", []).append(why)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        print(f"seed freshness: cannot read the sources: {type(e).__name__}: {e}", flush=True)
        return 2
    print(f"seeds fresh: {', '.join(fresh) or 'none'}" + (f"; stale: {', '.join(sorted(report))}" if report else ""), flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps({"fresh": fresh, "stale": report}, indent=2, sort_keys=True) + "\n")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
