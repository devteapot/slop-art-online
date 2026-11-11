#!/usr/bin/env python3
"""Fill the wants beyond survival into an authored world's sheets (docs/SEEDED_LIVES.md,
"Wants beyond survival").

Sheets drafted before 2026-11-11 carry goals that are mostly the world's tensions (debts,
quarrels, the gate-due) and no pastimes or calling. This pass asks a model, one household at a
time, for each member's `pastimes` (2-3 things they enjoy for their own sake), `calling` (the
work they love, or long for instead) and one or two goals of their own beyond the situations,
written from the sheet as it stands. It writes them into the household's sheet file
(`living/seeds/worlds/<world>/sheets/`) and into the compiled seed's residents, and logs every
call's tokens to the world's `authoring-log.jsonl` (purpose `wants`). Sheets that already have
pastimes are left alone, so a rerun fills only what is missing.

    fill_wants.py island [--profile deepseek-flash] [--jobs 6] [--into island]
"""

import argparse
import concurrent.futures
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("author_world", Path(__file__).with_name("author_world.py"))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

SYSTEM = """You add to the character sheets of people in a persistent simulated world. Their sheets already say who they are, \
their relations, memories and stances; many of their goals are about the troubles of their town. A life is more than its troubles. \
For each person, write from who they already are:
- pastimes: 2-3 things they enjoy doing for their own sake, concrete and possible in this world (a song at the inn, dice, carving, \
fishing at dusk, walking to a place they love, tending a garden, visiting a friend, telling stories to children). Small children: play.
- calling: one line in their own words on the work they love, or the work they long for instead of their own.
- goals: one or two goals of their own beyond the town's troubles (a skill to master, a thing to make, a person to see more of, \
a place to go, a household wish). Not plots, not outcomes; wants.
Keep to what the world bible and their sheet allow. Reply with ONE JSON object: \
{"people": {"<name>": {"pastimes": ["..."], "calling": "...", "goals": ["..."]}}}"""


def household(world_dir, bible, path, profile, effort):
    sheets = json.loads(path.read_text())
    todo = {n: sh for n, sh in sheets.items() if not sh.get("pastimes")}
    if not todo:
        return path.name, 0
    lines = []
    for n, sh in todo.items():
        rel = "; ".join(f"{r['name']} ({r.get('label', '')})" for r in sh.get("relations", [])[:8])
        lines.append(f"### {n}\nnarrative: {sh.get('narrative', '')}\nvalues: {json.dumps(sh.get('values', []), ensure_ascii=False)}\ngoals: {json.dumps(sh.get('goals', []), ensure_ascii=False)}\nmood: {sh.get('mood', '')}\nrelations: {rel}")
    user = f"# World bible\n{bible}\n\n# The household ({path.stem})\n" + "\n\n".join(lines) + f"\n\nWrite pastimes, calling and goals for each of: {', '.join(todo)}."
    v = A.logged_call(profile, SYSTEM, user, effort, "wants")
    got = v.get("people", v)
    n = 0
    for name in todo:
        w = got.get(name) or {}
        pastimes = [str(x).strip()[:120] for x in w.get("pastimes", []) if str(x).strip()][:4]
        if not pastimes:
            continue
        sheets[name]["pastimes"] = pastimes
        calling = str(w.get("calling", "") or "").strip()
        if calling:
            sheets[name]["calling"] = calling[:200]
        goals = sheets[name].setdefault("goals", [])
        for g in w.get("goals", [])[:2]:
            g = str(g).strip()
            if g and g not in goals and len(goals) < 8:
                goals.append(g[:200])
        n += 1
    path.write_text(json.dumps(sheets, indent=2, ensure_ascii=False) + "\n")
    return path.name, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--profile", default="deepseek-flash")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--into", default=None, help="compiled seed to update (default: the world's name)")
    a = ap.parse_args()
    wd = ROOT / "living/seeds/worlds" / a.world
    A.LOG_PATH = wd / "authoring-log.jsonl"
    bible = (wd / "bible.md").read_text()
    files = sorted((wd / "sheets").glob("*.json"))
    filled = 0
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        for f in concurrent.futures.as_completed([ex.submit(household, wd, bible, p, a.profile, a.effort) for p in files]):
            try:
                name, n = f.result()
            except Exception as e:  # noqa: BLE001 - reported, the rest go on
                print(f"  failed: {e}", flush=True)
                continue
            filled += n
            print(f"  {name}: {n}", flush=True)
    # The compiled seed's residents carry the same sheets.
    sheets = {}
    for p in files:
        sheets.update(json.loads(p.read_text()))
    seed_path = ROOT / "living/seeds" / f"{a.into or a.world}.json"
    seed = json.loads(seed_path.read_text())
    updated = 0
    for t in seed.get("towns", []) + seed.get("villages", []):
        for r in t.get("residents", []):
            sh = sheets.get(r["name"])
            if not sh or not isinstance(r.get("sheet"), dict):
                continue
            for k in ("pastimes", "calling", "goals"):
                if k in sh and r["sheet"].get(k) != sh[k]:
                    r["sheet"][k] = sh[k]
                    updated += 1
    seed_path.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n")
    missing = [r["name"] for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", []) if isinstance(r.get("sheet"), dict) and r["sheet"] and not r["sheet"].get("pastimes")]
    print(f"filled {filled} people; {updated} fields updated in {seed_path.relative_to(ROOT)}; {len(missing)} residents still without pastimes {missing[:8]}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
