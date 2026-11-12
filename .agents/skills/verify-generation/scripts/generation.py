#!/usr/bin/env python3
"""Prove seeded worlds through the real authority; retain evidence and delete each DB."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / ".local/living/verify"
SEEDS = ("realm", "valley", "authored-test", "aske-coast", "stage3-village", "island", "plan-test", "cullet", "floor-megacity-2k", "floor-megacity-4k", "cullet-laws", "cullet-laws-floor", "plan-test-floor")
# An inventory row held by a structure (`tables::STRUCTURE_BIT`).
STRUCTURE_BIT = 1 << 40
# Seeds derived from a tracked seed in the run's directory (published through `--seed` with an
# absolute path): the megacity floor (docs/FLOORS.md) at 2048 m, created inside `init` from a
# compiled seed, and at 4096 m as a floor: a module built without a seed (`--seed none`) given
# the seed at runtime by `create_floor`, which creates the land in scheduled steps (`genesis`).
DERIVED = {"floor-megacity-2k": ("floor-megacity", {"size": 2048}), "floor-megacity-4k": ("floor-megacity", {"size": 4096})}
FLOORS = ("floor-megacity-4k", "cullet-laws-floor", "plan-test-floor")
# Seeds with their own day and laws (`day_minutes`, `laws_file`; docs/CULLET_RULES.md): compiled in
# (`cullet-laws`, its laws file read in by build.rs) and given to a floor module (`cullet-laws-floor`,
# the same seed sent as living/tools/seed_text.py sends it). Both are created in the one call.
LAWS_FLOORS = {"cullet-laws-floor": "cullet-laws"}
# A runtime seed carrying look data (docs/LOOK.md §5): plan-test, with its `looks` fixture, given to
# a floor module by `create_floor` (created in the one call).
LOOKS_FLOORS = {"plan-test-floor": "plan-test"}
TABLES = ("world", "terrain_chunk", "character", "background", "community",
          "membership", "structure", "artifact", "resource_node", "genome", "body", "inventory",
          "place", "routine", "relation", "acquaintance", "world_law", "script", "rhythm", "look", "look_line")
HARNESS = ROOT / ".agents/skills/verify/scripts/verify.py"
# The server verify.py uses: the shared container, or a worker's own (see verify/SKILL.md).
CONTAINER = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")
STDB_URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def command(args, evidence, **kwargs):
    print("running", " ".join(map(str, args[:8])), flush=True)
    with evidence.open("w") as out:
        out.write(json.dumps([str(a) for a in args]) + "\n")
        out.flush()
        result = subprocess.run(args, stdout=out, stderr=subprocess.STDOUT, text=True, **kwargs)
        out.write(f"\nexit code: {result.returncode}\n")
    return result.returncode


def authored_copy(directory, world="aske-coast"):
    living = directory / f"source-{world}/living"
    (living / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "living/tools/author_world.py", living / "tools/author_world.py")
    shutil.copytree(ROOT / f"living/seeds/worlds/{world}", living / f"seeds/worlds/{world}")
    if world == "island":
        # A planned world (docs/SEEDED_LIVES.md) merges into an existing seed and checks
        # occupations and items against the repertoire and the rules' catalog.
        (living / "rules/src").mkdir(parents=True)
        shutil.copy2(ROOT / "living/rules/src/catalog.rs", living / "rules/src/catalog.rs")
        for f in ("island.json", "repertoire.json"):
            shutil.copy2(ROOT / f"living/seeds/{f}", living / f"seeds/{f}")
    return living


def harness(action, run, evidence, *args, env=None):
    return command([sys.executable, str(HARNESS), action, "--run", run, *map(str, args)],
                   evidence, cwd=ROOT, timeout=900, env=env)


def genesis_row(run, d, name="genesis"):
    if harness("sql", run, d / f"{name}-poll.log", "SELECT * FROM genesis", "--save", name) != 0:
        return {}
    rows = json.loads((d / f"{name}.json").read_text())
    return rows[0] if rows else {}


def stop_chain(run, d):
    """Leave the staged creation as a failed step leaves it: no step scheduled. SpacetimeDB
    2.14.1 deletes a one-shot schedule row after the call whatever the outcome, and a failed
    step rolled back its own scheduling of the next. The admin's `stop_genesis` unschedules
    the next step (owner SQL may not write to scheduled tables); the chain must then hold still
    for 8 s. Returns the stalled row."""
    if harness("call", run, d / "stop.log", "stop_genesis", "[]", "--as-admin") != 0:
        return {}
    before = genesis_row(run, d, "genesis-stopped")
    time.sleep(8)
    after = genesis_row(run, d, "genesis-stalled")
    timers = harness("sql", run, d / "stop-chain-timer.log", "SELECT * FROM genesis_timer", "--save", "genesis-timer")
    left = json.loads((d / "genesis-timer.json").read_text()) if timers == 0 else ["?"]
    stalled = not left and before.get("step") == after.get("step") and not after.get("done")
    return after if stalled else {}


def create_floor(run, d, seed):
    """Give a floor module its seed and wait for the staged creation (`genesis`) to finish;
    returns the checks. On the way: bad land sizes are refused, a chain of steps stopped
    midway (as a failed step leaves it) stalls, and `resume_genesis` carries it on."""
    checks = []
    for size, why in [(5000, "not a multiple of 16"), (9216, "above 8192"), (128, "below 256")]:
        bad = json.loads(json.dumps(seed))
        bad["map"]["size"] = size
        code = harness("call", run, d / f"create-floor-{size}.log", "create_floor", json.dumps([json.dumps(bad)]), "--as-admin", "--expect-refusal", "a land's side is a multiple of 16")
        checks.append({"check": f"create_floor refuses a {size} m land ({why})", "pass": code == 0})
    # A hand-authored plan the generator cannot honour (a stair whose rise disagrees with the
    # levels it joins) is refused before anything is kept (docs/AUTHORED_PLANS.md).
    plan = json.loads((ROOT / "living/seeds/plan-test.json").read_text())["map"]["params"]["plans"][0]
    plan["stairs"][0]["rise_m"] = 3.0
    bad = json.loads(json.dumps(seed))
    bad["map"].setdefault("params", {})["plans"] = [plan]
    code = harness("call", run, d / "create-floor-bad-plan.log", "create_floor", json.dumps([json.dumps(bad)]), "--as-admin", "--expect-refusal", "rises 3 m")
    checks.append({"check": "create_floor refuses a plan whose stair disagrees with its levels", "pass": code == 0})
    # A plan naming a resource or structure kind the world's tables lack (here the shipped
    # script, which has no `kelp` resource and no `furnace`) is refused, not silently left out.
    plan = json.loads((ROOT / "living/seeds/plan-test.json").read_text())["map"]["params"]["plans"][0]
    plan["resources"] = plan.get("resources", []) + [{"kind": "kelp", "at": plan["resources"][0]["at"]}]
    plan["structures"] = [{"kind": "furnace", "at": plan["resources"][0]["at"], "fuel": 4}]
    bad = json.loads(json.dumps(seed))
    bad["map"].setdefault("params", {})["plans"] = [plan]
    code = harness("call", run, d / "create-floor-unknown-kinds.log", "create_floor", json.dumps([json.dumps(bad)]), "--as-admin", "--expect-refusal", "names kinds this world's tables do not have")
    checks.append({"check": "create_floor refuses a plan naming a resource or structure kind the world does not have", "pass": code == 0})
    code = harness("call", run, d / "resume-none.log", "resume_genesis", "[]", "--as-admin", "--expect-refusal", "no staged creation")
    checks.append({"check": "resume_genesis is refused before any creation", "pass": code == 0})
    started = time.time()
    code = harness("call", run, d / "create-floor.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin")
    checks.append({"check": "create_floor accepted the seed", "pass": code == 0})
    rows, polls, stopped = [], 0, None
    while code == 0 and time.time() - started < 900:
        polls += 1
        g = genesis_row(run, d)
        rows = [g] if g else []
        if g.get("done"):
            break
        if stopped is None and g.get("step", 0) >= 3:
            busy = harness("call", run, d / "resume-busy.log", "resume_genesis", "[]", "--as-admin", "--expect-refusal", "already scheduled")
            checks.append({"check": "resume_genesis is refused while a step is scheduled", "pass": busy == 0})
            stopped = stop_chain(run, d)
            checks.append({"check": "a chain stopped midway stalls (no step scheduled, the step count holds for 8 s)", "pass": bool(stopped), "detail": {"step": stopped.get("step"), "label": stopped.get("label")}})
            again = harness("call", run, d / "stop-again.log", "stop_genesis", "[]", "--as-admin", "--expect-refusal", "no step is scheduled")
            checks.append({"check": "stop_genesis is refused when no step is scheduled", "pass": again == 0})
            resumed = harness("call", run, d / "resume.log", "resume_genesis", "[]", "--as-admin")
            checks.append({"check": "resume_genesis carries the stopped creation on", "pass": resumed == 0})
        time.sleep(3)
    g = rows[0] if rows else {}
    elapsed = round(time.time() - started, 1)
    write(d / "genesis-final.json", {"row": g, "seconds": elapsed, "polls": polls})
    checks.append({"check": "the staged creation finished", "pass": bool(g.get("done")), "detail": {"steps": g.get("step"), "seconds": elapsed}})
    done = harness("call", run, d / "resume-done.log", "resume_genesis", "[]", "--as-admin", "--expect-refusal", "already made")
    checks.append({"check": "resume_genesis is refused once the world is made", "pass": done == 0})
    checks.append({"check": "no generation restarts", "pass": g.get("restarts") == 0, "detail": g.get("restarts")})
    again = harness("call", run, d / "create-floor-again.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin", "--expect-refusal", "already has its seed")
    checks.append({"check": "a second create_floor is refused", "pass": again == 0})
    return checks


def create_floor_looks(run, d, seed):
    """Give a floor module a seed with look data, created in this call; returns the checks. On the
    way: looks that do not resolve (a resident wearing an unknown entry, a line without words)
    are refused, and nothing is written."""
    checks = []
    first = next(r for t in seed["towns"] for r in t.get("residents", []) if r.get("look"))
    for label, edit, words in [("unknown-person", lambda b: b["towns"][0]["residents"].__setitem__(0, dict(first, look="lp_0000000000000000")), "not among `people`"),
                               ("line-without-words", lambda b: b["looks"]["words"].pop(next(iter(b["looks"]["words"]))), "has no words")]:
        bad = json.loads(json.dumps(seed))
        edit(bad)
        code = harness("call", run, d / f"create-floor-{label}.log", "create_floor", json.dumps([json.dumps(bad)]), "--as-admin", "--expect-refusal", words)
        checks.append({"check": f"create_floor refuses a seed whose looks do not resolve: {label}", "pass": code == 0})
    code = harness("call", run, d / "create-floor.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin")
    checks.append({"check": "create_floor accepted the seed with its looks", "pass": code == 0})
    again = harness("call", run, d / "create-floor-again.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin", "--expect-refusal", "already has its seed")
    checks.append({"check": "a second create_floor is refused", "pass": again == 0})
    return checks


def check_looks(seed, rows):
    """A world's looks (docs/LOOK.md): with a seed's `looks`, the world wears its generation,
    `look_line` holds each (person, band) line with its words, every seeded resident wears its
    entry's line for its band, every living person has a look row whose line resolves, and no
    animal has one; without looks, no look rows and an empty `look_book`."""
    checks = []

    def present(name, condition, detail=None):
        checks.append({"check": name, "pass": bool(condition), "detail": detail})

    w = rows["world"][0]
    looks, lines, rows_look = seed.get("looks"), rows.get("look", []), rows.get("look_line", [])
    alive = {c["id"]: c for c in rows["character"] if c["alive"]}
    if not looks:
        present("a seed without looks: no look rows, no look lines, an empty look_book", not lines and not rows_look and w.get("look_book", "") == "", {"look": len(lines), "look_line": len(rows_look)})
        return checks
    bands = ["infant", "child", "youth", "adult", "elder"]
    want = {(p, bands.index(b) if b in bands else int(b), k) for p, m in looks["people"].items() for b, k in m.items()}
    got = {(r["person"], r["band"], r["key"]) for r in rows_look}
    present("the world wears the seed's look generation", w.get("look_book") == looks["generation"], {"look_book": w.get("look_book")})
    present("look_line holds each person entry's line by band", got == want and len(rows_look) == len(want), {"rows": len(rows_look), "entries": len(want)})
    # SQL's JSON gives a struct column as its fields in order (`LookWords`).
    fields = ["form", "girth", "height", "hair", "top", "bottom", "head", "beard"]
    as_words = lambda v: dict(zip(fields, v)) if isinstance(v, list) else v
    defaults = {"form": "", "girth": 1, "height": 1, "hair": "", "top": "", "bottom": "", "head": "", "beard": ""}
    words_ok = all(as_words(r["words"]) == dict(defaults, **looks["words"][r["key"]]) for r in rows_look if r["key"] in looks["words"])
    present("each look_line carries its line's words", words_ok and all(r["key"] in looks["words"] for r in rows_look))
    by_id = {r["id"]: r for r in lines}
    keyed = {r["key"] for r in rows_look}
    persons = [c for c in alive.values() if c["kind"] == "person"]
    present("every living person has a look row", all(c["id"] in by_id for c in persons), {"people": len(persons), "rows": len(lines)})
    present("every look row's line resolves in look_line, for its person and band", all((r["person"], r["band"], r["line"]) in got for r in lines), {"unresolved": [r["id"] for r in lines if (r["person"], r["band"], r["line"]) not in got][:10]})
    present("no animal or dead character has a look row", all(i in alive and alive[i]["kind"] == "person" for i in by_id))
    named = {r["name"]: r["look"] for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", []) if r.get("look")}
    wearing = [(c["name"], by_id.get(c["id"], {}).get("person")) for c in persons if c["name"] in named]
    present("each seeded resident wears its own entry", wearing and all(p == named[n] for n, p in wearing), {"residents": len(wearing), "wrong": [x for x in wearing if x[1] != named[x[0]]][:10]})
    pool = set(looks.get("pool", []))
    others = [by_id[c["id"]]["person"] for c in persons if c["name"] not in named and c["id"] in by_id]
    present("everyone else wears a pool entry" + ("" if others else " (none)"), all(p in pool for p in others), {"others": len(others)})
    present("every line key is lk_ and 16 hex digits", all(re.fullmatch(r"lk_[0-9a-f]{16}", k) for k in keyed))
    # char-4's cases for an authored world (worlds/<run>/look-cases.json, look_lines.py): the key
    # rule over the drawn fields only, and residents of each band wearing the case's entry and line.
    cases_file = ROOT / "living/seeds/worlds" / seed["run"] / "look-cases.json"
    if cases_file.exists():
        cases = json.loads(cases_file.read_text())
        present("the cases are of the world's generation", cases["generation"] == looks["generation"], {"cases": cases["generation"]})
        drawn = ("type", "height", "proportions", "identity", "colors", "styles", "belly", "grey")
        canon = lambda line: json.dumps({k: line[k] for k in drawn if k in line}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        hashed = [(c["key"], "lk_" + hashlib.sha256(canon(c["line"]).encode()).hexdigest()[:16], canon(c["line"]) == c["canonical"]) for c in cases["key_hash"]["cases"]]
        present("the key rule (lk_ + 16 hex of SHA-256 over the drawn fields' canonical JSON) gives each case's key; name and seed are left out", all(k == h and same for k, h, same in hashed), {"cases": len(hashed)})
        by_name = {c["name"]: c for c in persons}
        wrong = []
        for c in cases["bands"]["cases"]:
            ch = by_name.get(c["resident"])
            row = by_id.get(ch["id"]) if ch else None
            if not row or (row["person"], row["band"], row["line"], ch["stage"]) != (c["look"], c["band"], c["line"], c["stage"]):
                wrong.append((c["resident"], row and (row["person"], row["band"], row["line"]), ch and ch["stage"]))
        present(f"each band case's resident wears its entry, in its band, with its line, at its stage ({len(cases['bands']['cases'])} cases)", not wrong, {"wrong": wrong})
    return checks


def seed_text(path):
    """A seed as `create_floor` takes it: its `laws_file` read into `laws` (living/tools/seed_text.py)."""
    sys.path.insert(0, str(ROOT / "living/tools"))
    import seed_text as st
    return st.resolved(path)


def create_floor_laws(run, d, seed):
    """Give a floor module a seed with its own day and laws, created in this call; returns the
    checks. On the way: a seed naming a laws file without its text, laws that fail the install
    checks, and a day out of range are refused, and nothing is written."""
    checks = []
    for label, change, words in [("laws-file-unread", {"laws": ""}, "was not read into `laws`"),
                                 ("laws-broken", {"laws": "fn rates(a) { 1 }"}, "seed laws"),
                                 ("day-zero", {"day_minutes": 0}, "day_minutes is between")]:
        bad = dict(seed, **change)
        code = harness("call", run, d / f"create-floor-{label}.log", "create_floor", json.dumps([json.dumps(bad)]), "--as-admin", "--expect-refusal", words)
        checks.append({"check": f"create_floor refuses a seed: {label}", "pass": code == 0})
    code = harness("call", run, d / "create-floor.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin")
    checks.append({"check": "create_floor accepted the seed with its laws", "pass": code == 0})
    again = harness("call", run, d / "create-floor-again.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin", "--expect-refusal", "already has its seed")
    checks.append({"check": "a second create_floor is refused", "pass": again == 0})
    return checks


def snapshot(run, tables):
    directory = BASE / run
    result = {}
    for table in tables:
        code = harness("sql", run, directory / f"sql-{table}.log", f"SELECT * FROM {table}", "--save", table)
        if code:
            raise RuntimeError(f"snapshot failed: {run}/{table}")
        result[table] = json.loads((directory / f"{table}.json").read_text())
    return result


def database_identity(database):
    try:
        with urllib.request.urlopen(f"{STDB_URL}/v1/database/{database}/identity", timeout=30) as response:
            return response.status, response.read().decode().strip()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def check_seed(seed, rows):
    checks = []

    def equal(name, actual, expected):
        checks.append({"check": name, "pass": actual == expected, "actual": actual, "expected": expected})

    def present(name, condition, detail=None):
        checks.append({"check": name, "pass": bool(condition), "detail": detail})

    w = rows["world"][0]
    # The seed's day and its own laws (docs/CULLET_RULES.md): the world's day, and the installed
    # script is the shipped one with the overlay composed over it.
    equal("world day length", w["day_ms"], round(seed.get("day_minutes", 12) * 60000))
    script = (rows.get("script") or [{}])[0].get("source", "")
    if str(seed.get("laws") or "").strip():
        parts = script.split("// ---- floor overlay ----", 1)
        present("the seed's laws are composed over the shipped script", len(parts) == 2 and parts[1].strip() == seed["laws"].strip() and "fn base_rates(a)" in parts[0], {"chars": len(script)})
    else:
        present("the installed script is the shipped one", "// ---- floor overlay ----" not in script and script.strip() == (ROOT / "living/scripts/skills.rhai").read_text().strip())
    m = seed.get("map", {})
    if m.get("kind") == "land":
        size = [m.get("size") or max(m.get("w", 0), m.get("h", 0))] * 2
    else:
        size = [max(64, m.get(k, 0)) for k in ("w", "h")] if m.get("kind") == "realm" else [96, 96]
    equal("world dimensions", [w["width"], w["height"]], size)
    equal("world seed and run", [w["seed"], w["run"]], [seed["seed"], seed["run"]])
    ids = sorted((cy << 16) | cx for cy in range((size[1] + 15) // 16) for cx in range((size[0] + 15) // 16))
    equal("all terrain chunk ids", sorted(r["id"] for r in rows["terrain_chunk"]), ids)
    # SpacetimeDB JSON encodes Vec<u8> as a hex string.
    tiles = [bytes.fromhex(r["tiles"]) if isinstance(r["tiles"], str) else bytes(r["tiles"]) for r in rows["terrain_chunk"]]
    # Classes 0..9 (living_rules::map::Terrain): 7 wall (buildings, town walls), 8 drop (a
    # terrace's or a plan's edge), 9 low (a thing below eye height: a cart); 8 and 9 are
    # unwalkable and see-through.
    counts = {k: sum(t.count(k) for t in tiles) for k in range(10)}
    present("terrain chunks contain 256 valid tiles", all(len(t) == 256 and max(t) <= 9 for t in tiles), {"wall": counts[7], "drop": counts[8], "low": counts[9], "rock": counts[4]})
    chars = {r["id"]: r for r in rows["character"]}
    by_name = {r["name"]: r for r in chars.values() if r["kind"] == "person"}
    bgs = {r["id"]: json.loads(r["text"]) for r in rows["background"]}
    communities = {r["name"]: r for r in rows["community"]}
    structures = rows["structure"]
    artifacts = rows["artifact"]
    settlements = seed.get("towns", []) + seed.get("villages", [])
    equal("community names", sorted(communities), sorted({t["name"] for t in settlements} | {c["name"] for c in seed.get("communities", [])}))
    for t in settlements:
        ids = [i for i, bg in bgs.items() if bg.get("town") == t["name"]]
        residents = t.get("residents", [])
        if residents:
            equal(f"{t['name']} resident count", len(ids), len(residents))
            equal(f"{t['name']} resident names", sorted(chars[i]["name"] for i in ids), sorted(r["name"] for r in residents))
        else:
            grown = [i for i in ids if chars[i]["parent_a"] == 0]
            equal(f"{t['name']} drawn occupations", dict(Counter(bgs[i]["occupation"] for i in grown)), t.get("occupations", {}))
            children = [i for i in ids if i not in grown]
            present(f"{t['name']} added children have household parents", all(chars[i]["parent_a"] in ids and chars[i]["parent_b"] in ids and bgs[i]["occupation"] == "child" for i in children), {"requested_workers": len(grown), "added_children": len(children)})
        com = communities.get(t["name"], {})
        # A founder may die in the seconds the world ticks before the snapshot, and death ends
        # membership: compare the living.
        equal(f"{t['name']} memberships of the living", sorted(r["member"] for r in rows["membership"] if r["community"] == com.get("id")), sorted(i for i in ids if chars[i]["alive"]))
        # A town seeded with no people (Cullet's grey city, before its residents are written)
        # has no backgrounds or places to check; its buildings' signs are checked at their lots.
        peopled = bool(residents or t.get("occupations"))
        present(f"{t['name']} settlement backgrounds", (bool(ids) or not peopled) and all(bg.get("town_center") is not None and bg.get("walled") == t.get("walled", True) for i, bg in bgs.items() if i in ids))
        if t.get("ledger"):
            present(f"{t['name']} ledger", any(a["text"] == t["ledger"] for a in artifacts))
        for building in t.get("buildings", []):
            places = [p for i in ids for p in bgs[i].get("places", []) if p["name"] == building["name"] and p["kind"] == building["kind"]]
            present(f"building {building['name']} place", len(places) == len(ids))
            if not peopled:
                present(f"building {building['name']} structure (a town with no people: a {building['kind']} structure stands)", any(s["kind"] == building["kind"] for s in structures))
            else:
                present(f"building {building['name']} structure", bool(places) and any(s["kind"] == building["kind"] and abs(s["x"] - places[0]["at"][0]) <= 0.51 and abs(s["y"] - places[0]["at"][1]) <= 0.51 for s in structures))
            present(f"building {building['name']} sign", any(a["topic"] == building["name"] and a["text"] == building["name"] + (". " + building["about"] if building.get("about") else "") for a in artifacts))
        for kind, count in t.get("resources", {}).items():
            count_near = sum(r["kind"] == kind and (r["x"] - com.get("home_x", -10000)) ** 2 + (r["y"] - com.get("home_y", -10000)) ** 2 <= 24 ** 2 for r in rows["resource_node"])
            present(f"{t['name']} promised {kind}", count_near >= count, {"actual": count_near, "minimum": count})
        for resident in residents:
            ch = by_name.get(resident["name"])
            present(f"authored resident {resident['name']}", ch is not None and ch["id"] in ids)
            if ch is None:
                continue
            expected = json.loads(json.dumps(resident.get("sheet")))
            if expected is not None:
                expected.pop("secret", None)
                if "relations" in expected:
                    expected["relations"] = [dict(r, id=by_name[r["name"]]["id"]) for r in expected["relations"] if r.get("name") in by_name]
                for memory in expected.get("memories", []):
                    if "about" in memory:
                        names = [n if isinstance(n, str) else n.get("name", "") for n in memory["about"]]
                        memory["about"] = [{"name": n, "id": by_name[n]["id"]} for n in names if n in by_name]
                equal(f"{resident['name']} public sheet", bgs[ch["id"]].get("sheet"), expected)
            parents = [by_name[n]["id"] for n in resident.get("parents", [])[:2] if n in by_name]
            equal(f"{resident['name']} parents", [ch["parent_a"], ch["parent_b"]], (parents + [0, 0])[:2])
    for band in seed.get("bands", []):
        ids = [i for i, bg in bgs.items() if bg.get("band") == band["name"]]
        equal(f"band {band['name']} population", len(ids), len(band.get("family", [])) or band.get("size", 0))
        present(f"band {band['name']} backgrounds", bool(ids) and all(bgs[i].get("history") == band.get("history", "") for i in ids))
        for kind in band.get("camp", []):
            present(f"band {band['name']} camp {kind}", any(s["kind"] == kind and s["owner"] == min(ids, default=-1) for s in structures))
    for person in seed.get("people", []):
        present(f"explicit person {person['name']}", person["name"] in by_name)
    expected_people = len(seed.get("people", [])) + sum(len(t.get("residents", [])) or sum(t.get("occupations", {}).values()) for t in settlements) + sum(len(b.get("family", [])) or b.get("size", 0) for b in seed.get("bands", []))
    drawn_children = sum(c["parent_a"] != 0 and any(not t.get("residents") and bgs.get(c["id"], {}).get("town") == t["name"] for t in settlements) for c in by_name.values())
    equal("total people including drawn children", len(by_name), expected_people + drawn_children)
    for kind, count in seed["animals"].items():
        if not isinstance(count, int):
            continue  # `habitat`: where each kind lives, not a count
        # A seed's `packs` place animals of a kind on purpose, beside its `animals` (docs/COMBAT.md).
        packed = sum(p.get("count", 0) for p in seed.get("packs", []) if p.get("kind") == kind)
        equal(f"{kind} count including dead founders", sum(c["kind"] == kind for c in chars.values()), count + packed)
    for pack in seed.get("packs", []):
        # A pack placed near an animal kind starts where that kind lives: each member's start
        # (`home_x`, `home_y`) within the pack's reach (`to_m`, plus the 4 m spread) of one.
        near = pack.get("near", "arrival")
        if near in seed["animals"] and pack.get("name"):
            members = [c for c in chars.values() if c["kind"] == pack["kind"] and bgs.get(c["id"], {}).get("pack") == pack["name"]]
            prey = [(c["home_x"], c["home_y"]) for c in chars.values() if c["kind"] == near]
            far = [c["id"] for c in members if not any(math.dist((c["home_x"], c["home_y"]), q) <= pack.get("to_m", 100) + 8 for q in prey)]
            present(f"pack {pack['name']} starts near {near}", len(members) == pack["count"] and not far, {"members": len(members), "too_far": far})
    present("resources generated", len(rows["resource_node"]) > 0)
    for structure in seed.get("structures", []):
        owner = by_name.get(structure.get("owner"), {}).get("id", 0)
        matches = [s for s in structures if s["kind"] == structure["kind"] and s["owner"] == owner]
        present(f"explicit structure {structure['kind']} at {structure['at']}", any(abs(s["x"] - structure["at"][0]) <= 3 and abs(s["y"] - structure["at"][1]) <= 3 for s in matches), matches)
    for artifact in seed.get("artifacts", []):
        present(f"explicit artifact {artifact['topic']}", any(all(a[k] == artifact.get(k, "") for k in ("kind", "author_name", "topic", "text")) and any(s["id"] == (a["holder"] & ~(1 << 40)) and s["kind"] == artifact["kind"] for s in structures) for a in artifacts))
    for community in seed.get("communities", []):
        c = communities.get(community["name"], {})
        equal(f"{community['name']} home", [c.get("home_x"), c.get("home_y")], community["home"])
        equal(f"{community['name']} members", sorted(chars[m["member"]]["name"] for m in rows["membership"] if m["community"] == c.get("id")), sorted(community["members"]))
    # People's rhythms (docs/SEEDED_LIVES.md): a person without one from the seed has a drawn one
    # (rising 04:00-09:00, to bed 19:30-02:30, an evening of 1.5-4.5 hours, no working hours and
    # no second sleep: what every seed before lives-3 gives); one the seed gives is as given.
    people = [c for c in rows["character"] if c["kind"] == "person"]
    rhythm = {r["id"]: r for r in rows.get("rhythm", [])}
    given = {r["name"]: r["rhythm"] for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", []) if r.get("rhythm")}
    drawn_ok = lambda r: 4.0 <= r["rise_h"] <= 9.0 and 19.5 <= r["bed_h"] <= 26.5 and 1.5 <= r["evening_h"] <= 4.5 and (r.get("work_from_h", 0), r.get("work_to_h", 0), r.get("nap_from_h", 0), r.get("nap_to_h", 0)) == (0, 0, 0, 0)
    adults = [c for c in people if c.get("stage", 2) >= 1]
    unseeded = [c for c in adults if c["name"] not in given]
    bad = [(c["name"], rhythm.get(c["id"])) for c in unseeded if c["id"] in rhythm and not drawn_ok(rhythm[c["id"]])]
    present("people without a seeded rhythm have a drawn one (no working hours, no second sleep)" + ("" if unseeded else " (none)"), not bad and sum(c["id"] in rhythm for c in unseeded) >= 0.9 * len(unseeded), {"people": len(unseeded), "with_row": sum(c["id"] in rhythm for c in unseeded), "wrong": bad[:10]})
    def span(x):
        # A seed's [from, to] as stored: from in 0..24, to after it within a day; empty is none.
        if not x or (x[1] - x[0]) % 24 == 0:
            return (0.0, 0.0)
        return (x[0] % 24, x[0] % 24 + (x[1] - x[0]) % 24)

    def as_given(r, g):
        close = lambda a, b: abs(a - b) < 1e-3
        rise = g["rises"] % 24 if "rises" in g else r["rise_h"]
        work, nap = span(g.get("works")), span(g.get("second_sleep"))
        awake = r["bed_h"] - r["rise_h"]
        bed = "sleeps" not in g or close((r["bed_h"] - g["sleeps"]) % 24, 0) or close((r["bed_h"] - g["sleeps"]) % 24, 24) or close(awake, 8) or close(awake, 22)
        return close(r["rise_h"], rise) and bed and close(r.get("work_from_h", 0), work[0]) and close(r.get("work_to_h", 0), work[1]) and close(r.get("nap_from_h", 0), nap[0]) and close(r.get("nap_to_h", 0), nap[1])

    seeded = [(c["name"], c["id"]) for c in people if c["name"] in given]
    wrong = [(n, given[n], rhythm.get(i)) for n, i in seeded if i not in rhythm or not as_given(rhythm[i], given[n])]
    present("seeded rhythms are as given (any rising hour, working hours, a second sleep)" + ("" if seeded else " (none: the seed gives none)"), not wrong, {"seeded": len(seeded), "wrong": wrong[:10]})
    if m.get("kind") == "land":
        checks.extend(check_land(seed, rows, size[0], tiles))
    checks.extend(check_looks(seed, rows))
    return checks


WALKABLE = {0, 1, 3, 5, 6}  # grass, forest, sand, dirt, road (living_rules::map::Terrain)
DOOR_KINDS = {"house": "house", "townhouse": "house", "inn": "inn", "hall": "hall", "chapel": "hall", "workshop": "workshop", "barn": "storage"}
BLOCKING = {"house", "townhouse", "inn", "hall", "chapel", "workshop", "barn", "tower", "well", "market_stall"}


def check_land(seed, rows, side, tiles):
    """A `map.kind = "land"` world (docs/ISLAND_AUTHORITY.md): the land row, settlements, lots
    with their door structures, blocked footprints, residents' folk and mindless control."""
    checks = []

    def present(name, condition, detail=None):
        checks.append({"check": name, "pass": bool(condition), "detail": detail})

    grid = {r["id"]: t for r, t in zip(rows["terrain_chunk"], tiles)}

    def tile(x, y):
        x, y = int(x // 1), int(y // 1)
        if x < 0 or y < 0 or x >= side or y >= side:
            return 4
        return grid[((y // 16) << 16) | (x // 16)][(y % 16) * 16 + x % 16]

    land = rows.get("land", [])
    present("land row with seed and size", len(land) == 1 and land[0]["seed"] == seed["seed"] and land[0]["size"] == side, land)
    present("land digests set", bool(land) and all(land[0][k] for k in ("tiles_digest", "heights_digest", "layout_digest")))
    if land:
        present("arrival point walkable", tile(land[0]["arrive_x"], land[0]["arrive_y"]) in WALKABLE, [land[0]["arrive_x"], land[0]["arrive_y"]])
    settlements = rows.get("settlement", [])
    if land and settlements:
        # Newcomers arrive on the first town's square (`living_rules::host::arrival`), inside the
        # settlement among its people, not outside its wall.
        a = (land[0]["arrive_x"], land[0]["arrive_y"])
        home = min(settlements, key=lambda s: math.dist(a, (s["x"], s["y"])))
        d = math.dist(a, (home["x"], home["y"]))
        present("arrival point inside a settlement, near its square", d <= 0.5 * home["radius_m"], {"settlement": home["id"], "kind": home["kind"], "style": home["style"], "from_its_square_m": round(d, 1), "radius_m": round(home["radius_m"], 1)})
    if land:
        # A pack with a `band` starts within it (from the arrival point), and one with
        # `road_clear_m` that far from any road (members spread up to about 6 m from the centre).
        a = (land[0]["arrive_x"], land[0]["arrive_y"])
        bgs = {r["id"]: json.loads(r["text"]) for r in rows["background"] if r["text"].startswith("{")}
        for pack in seed.get("packs", []):
            band, clear = pack.get("band"), pack.get("road_clear_m", 0)
            if not pack.get("name") or not (band or clear):
                continue
            members = [c for c in rows["character"] if c["kind"] == pack["kind"] and bgs.get(c["id"], {}).get("pack") == pack["name"]]
            starts = [(c["home_x"], c["home_y"]) for c in members]
            if band and band.get("of", "arrival") == "arrival":
                off = [round(math.dist(q, a)) for q in starts if not band.get("from_m", 0) - 6 <= math.dist(q, a) <= band["to_m"] + 6]
                present(f"pack {pack['name']} starts {band.get('from_m', 0)}-{band['to_m']} m from the arrival", bool(members) and not off, {"members": len(members), "from_arrival_m": sorted(round(math.dist(q, a)) for q in starts)})
            if clear:
                r = max(clear - 6, 0)
                n = int(r) + 1
                roads = [q for q in starts if any(dx * dx + dy * dy <= r * r and tile(q[0] + dx, q[1] + dy) == 6 for dy in range(-n, n + 1) for dx in range(-n, n + 1))]
                present(f"pack {pack['name']} starts {clear} m clear of roads", bool(members) and not roads, {"members": len(members), "near_a_road": roads})
    communities = {r["name"]: r for r in rows["community"]}
    entries = seed.get("towns", []) + seed.get("villages", [])
    present("settlement rows", len(settlements) >= len(entries), {"rows": len(settlements), "seeded": len(entries)})
    linked = {s["community"] for s in settlements if s["community"]}
    present("every seeded settlement linked to its community", all(communities.get(t["name"], {}).get("id") in linked for t in entries), sorted(linked))
    plans = {p["id"]: p for p in seed.get("map", {}).get("params", {}).get("plans", [])}
    for t in entries:
        want = t.get("site") or ("town" if t in seed.get("towns", []) else "village")
        c = communities.get(t["name"], {}).get("id")
        # A town in its own style is named by its site id, `<style>_<kind>` (steampunk_town); a
        # hand-authored one by its plan's id, in the plan's style.
        planned = lambda s: want in plans and s["style"] == plans[want]["style"] and s["kind"] == plans[want].get("kind", "town")
        present(f"{t['name']} stands on a {want} site", any(s["community"] == c and (want in (s["kind"], f"{s['style']}_{s['kind']}") or planned(s)) for s in settlements))
    lots = rows.get("lot", [])
    structures = {s["id"]: s for s in rows["structure"]}
    present("lot ids are 0..n", sorted(l["id"] for l in lots) == list(range(len(lots))), len(lots))
    # A planned lot may name its own door structure (`lots[].structure`, a world's own kind of
    # store); the plan checks match each to its lot.
    own_door = {}
    for p in plans.values():
        for spec in p.get("lots", []):
            if spec.get("structure"):
                own_door.setdefault(spec["kind"], set()).add(spec["structure"])
    door_ok = lambda l: structures[l["structure"]]["kind"] == DOOR_KINDS[l["kind"]] or structures[l["structure"]]["kind"] in own_door.get(l["kind"], set())
    bad_door = [l["id"] for l in lots if l["kind"] in DOOR_KINDS and not (l["structure"] in structures and door_ok(l) and abs(structures[l["structure"]]["x"] - l["door_x"]) < 0.01 and abs(structures[l["structure"]]["y"] - l["door_y"]) < 0.01)]
    present("every building lot has its structure at its door", not bad_door, bad_door[:20])
    present("no structure on open lots", all(l["structure"] == 0 for l in lots if l["kind"] not in DOOR_KINDS))
    present("doors are walkable", all(tile(l["door_x"], l["door_y"]) in WALKABLE for l in lots if l["structure"]), [l["id"] for l in lots if l["structure"] and tile(l["door_x"], l["door_y"]) not in WALKABLE][:20])
    blocking = [l for l in lots if l["kind"] in BLOCKING]
    # Wall where a model is solid at eye height, low (9) where it is not (`LandParams.sight`,
    # the table's `eye_cells`; eye-2); over a drop's edge, a part that does not hide stays a
    # drop (8). Never walkable.
    walled = [l["id"] for l in blocking if tile(l["x"], l["y"]) in (7, 8, 9)]
    present("blocking lots stand on wall, low or drop tiles", len(walled) == len(blocking), {"blocking": len(blocking), "unwalkable_at_centre": len(walled), "wall_at_centre": sum(tile(l["x"], l["y"]) == 7 for l in blocking), "open": [l["id"] for l in blocking if l["id"] not in walled][:20]})
    # Drops between ground levels are `drop` (8), not `wall` (7): people see across them
    # (docs/PERCEPTION.md). A planned settlement always has some; terraced towns usually do.
    drops = sum(t.count(8) for t in tiles)
    if plans:
        present("a planned settlement's drops are drop tiles", drops > 0, {"drop_tiles": drops})
    present("open lots stay walkable", all(tile(l["x"], l["y"]) in WALKABLE | {2} for l in lots if l["kind"] in ("garden", "field", "lamp")))
    houses = {s["id"] for s in structures.values() if s["kind"] == "house"}
    lot_houses = {l["structure"] for l in lots if l["kind"] in ("house", "townhouse")}
    present("houses are lot houses", houses == lot_houses, {"houses": len(houses), "lot_houses": len(lot_houses)})
    owners = {structures[i]["owner"] for i in lot_houses if structures[i]["owner"]}
    peopled = any(t.get("residents") or t.get("occupations") for t in seed.get("towns", []) + seed.get("villages", []))
    present("households own lot houses" + ("" if peopled else " (none: the seed has no people)"), len(owners) > 0 if peopled else not owners, len(owners))
    bgs = {r["id"]: json.loads(r["text"]) for r in rows["background"]}
    folk = {s["community"]: s for s in settlements}
    members = {m["member"]: m["community"] for m in rows["membership"]}
    wrong = [i for i, c in members.items() if c in folk and (bgs.get(i, {}).get("folk") != folk[c]["kind"] or abs((bgs.get(i, {}).get("body_scale") or -1) - folk[c]["scale"]) > 1e-3)]
    present("residents' backgrounds name their folk and scale" + ("" if peopled else " (none: the seed has no people)"), (members if peopled else True) and not wrong, wrong[:20])
    # Town life (docs/TOWN_LIFE.md): residents know their places, found from their own
    # settlement's lots, and start on the seed's own ways.
    life = seed.get("town_life", {})
    if life:
        places = {}
        for p in rows.get("place", []):
            places.setdefault(p["actor"], {})[p["name"]] = (p["x"], p["y"])
        residents = [i for i, c in members.items() if c in folk]
        names = set(life.get("places", {})) | ({"evening"} if life.get("evening") else set())
        missing = [i for i in residents if not names <= set(places.get(i, {}))]
        present(f"residents know the seed's places ({', '.join(sorted(names))})", residents and len(missing) <= 0.05 * len(residents), {"residents": len(residents), "missing": missing[:20]})
        # A spread place is shared out like work (the nearest of the least used spots): with
        # spots to spare, residents mostly get different ones.
        for name in life.get("spread", []):
            spots = [places[i][name] for i in residents if name in places.get(i, {})]
            present(f"spread place {name!r} is spread over its spots", spots and len(set(spots)) >= 0.5 * len(spots), {"residents": len(spots), "distinct": len(set(spots))})
        workers = [i for i in residents if bgs.get(i, {}).get("occupation") in life.get("work", {})]
        no_work = [i for i in workers if "work" not in places.get(i, {})]
        present("workers have a workplace", workers and len(no_work) <= 0.05 * len(workers), {"workers": len(workers), "without": no_work[:20]})
        # In or by the settlement: within the search radius of its centre, or at one of its own
        # lots (fields can lie farther out).
        reach = {}
        for l in lots:
            s = next((x for x in settlements if x["id"] == l["settlement"]), None)
            if s:
                reach[s["community"]] = max(reach.get(s["community"], 0.0), ((l["x"] - s["x"]) ** 2 + (l["y"] - s["y"]) ** 2) ** 0.5 + max(l["width_m"], l["depth_m"]))
        # Places an author gave a resident (docs/SEEDED_LIVES.md) may lie elsewhere: a carrier's
        # work is another town's market, an outlaw's a spot on the road.
        authored = {r["name"]: r for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", [])}
        names_of = {c["id"]: c["name"] for c in rows["character"]}
        own_places = {i: {p["name"]: p for p in authored.get(names_of.get(i), {}).get("places", [])} for i in residents}
        given = [(i, p) for i in residents for p in own_places.get(i, {}).values()]
        missing_given = [(names_of[i], p["name"]) for i, p in given if p["name"] not in places.get(i, {}) or any(f"{p['name']} {k}" not in places.get(i, {}) for k in range(1, p.get("stages", 0) + 1))]
        present("authored places and the stages of known ways", not missing_given, {"given": len(given), "missing": missing_given[:20]})
        legs = []
        for i, p in given:
            at = (lambda c: (c["home_x"], c["home_y"]))(next(c for c in rows["character"] if c["id"] == i))
            for k in range(1, p.get("stages", 0) + 1):
                nxt = places[i].get(f"{p['name']} {k}")
                if nxt:
                    legs.append(((nxt[0] - at[0]) ** 2 + (nxt[1] - at[1]) ** 2) ** 0.5)
                    at = nxt
        present("each stage of a known way is a short walk (220 m or less)", all(d <= 220 for d in legs), {"legs": len(legs), "longest": round(max(legs, default=0), 1)})
        far = [i for i in workers if "work" in places.get(i, {}) and "work" not in own_places.get(i, {}) and (lambda s, w: ((w[0] - s["x"]) ** 2 + (w[1] - s["y"]) ** 2) ** 0.5 > max(max(40.0, s["radius_m"]) * 1.5, reach.get(s["community"], 0.0)) + 6)(folk[members[i]], places[i]["work"])]
        present("workplaces lie in or by their settlement", not far, far[:20])
        present("workplaces are walkable", all(tile(*w["work"]) in WALKABLE for i, w in places.items() if "work" in w), [i for i, w in places.items() if "work" in w and tile(*w["work"]) not in WALKABLE][:20])
        own = set(seed.get("ways", {}).get("common", {}))
        routines = {}
        for r in rows.get("routine", []):
            routines.setdefault(r["actor"], set()).add(r["name"].lower())
        # Infants have no ways yet: they start on their species' young instinct.
        stage = {c["id"]: c.get("stage", 2) for c in rows["character"]}
        lacking = [i for i in residents if bgs.get(i, {}).get("occupation") and stage.get(i, 2) >= 1 and not {n.lower() for n in own} <= routines.get(i, set())]
        present("residents start on the seed's own ways", own and not lacking, lacking[:20])
    # Dispersed settlements (hamlets) and the sheets' relations as rows (docs/SEEDED_LIVES.md).
    hamlets = [x for x in settlements if x["style"] == "hamlet"]
    want_hamlets = [t for t in entries if t.get("site") == "hamlet_village"]
    present("hamlets laid out, and peopled where the seed says", len(hamlets) >= len(want_hamlets) and sum(1 for x in hamlets if x["community"]) == len(want_hamlets), {"hamlets": len(hamlets), "seeded": len(want_hamlets)})
    names = {c["name"]: c["id"] for c in rows["character"] if c["kind"] == "person"}
    rel = {(r["actor"], r["other"]) for r in rows.get("relation", [])}
    sheet_pairs = {(names[r["name"]], names[x["name"]]) for t in entries for r in t.get("residents", []) if r["name"] in names for x in (r.get("sheet") or {}).get("relations", []) if x.get("name") in names and x["name"] != r["name"]}
    present("authored relations are relation rows", sheet_pairs <= rel, {"sheet_pairs": len(sheet_pairs), "rows": len(rel), "missing": sorted(sheet_pairs - rel)[:20]})
    # A feeling is not an introduction: an authored relation across communities is one, unless
    # the sheet says the person would not know the other by name (`knows_name: false`).
    member = {m["member"]: m["community"] for m in rows["membership"]}
    acq = {(a["observer"], a["known"]) for a in rows.get("acquaintance", [])}
    want, refuse = set(), set()
    for t in entries:
        for r in t.get("residents", []):
            for x in (r.get("sheet") or {}).get("relations", []):
                a, b = names.get(r["name"]), names.get(x.get("name"))
                if a is None or b is None or a == b or member.get(a) == member.get(b):
                    continue
                (refuse if x.get("knows_name") is False else want).add((a, b))
    present("authored relations across communities are introductions, unless not known by name", want <= acq and not (refuse & acq), {"introductions": len(want), "not_known_by_name": len(refuse), "missing": sorted(want - acq)[:20], "wrongly_known": sorted(refuse & acq)[:20]})
    # A land with a city (`map.params.metro`, docs/FLOORS.md): its wards in their district
    # styles, the core's towers, the wall's gates, and the land's other settlements outside it.
    metro = seed.get("map", {}).get("params", {}).get("metro")
    if metro is not None:
        # The seed's districts name the wards' styles (the prototype's defaults without them).
        styles = {d.get("style", "metro") for d in metro.get("districts", [])} or {"metro", "slum", "works"}
        wards = [s for s in settlements if s["style"] in styles]
        rings = len(metro.get("rings", [0.3, 0.58, 0.82]))
        arterials = metro.get("arterials", 8)
        present("city wards: the core and every band and sector", len(wards) == 1 + rings * arterials, {"wards": len(wards), "expected": 1 + rings * arterials})
        present("every district of the seed has a ward", styles <= {s["style"] for s in wards}, {"seed": sorted(styles), "wards": sorted({s["style"] for s in wards})})
        core = wards[0] if wards else None
        core_style = core["style"] if core else None
        tall = [l for l in lots if any(l["settlement"] == w["id"] for w in wards if w["style"] == core_style) and l["height_m"] >= 100.0]
        present("the core's district stands in towers of 100 m or more", len(tall) >= 6, len(tall))
        reach = max(((s["x"] - core["x"]) ** 2 + (s["y"] - core["y"]) ** 2) ** 0.5 + s["radius_m"] for s in wards) if wards else 0.0
        outside = [s for s in settlements if s not in wards]
        present("the land's other settlements stand outside the city", outside and all(((s["x"] - core["x"]) ** 2 + (s["y"] - core["y"]) ** 2) ** 0.5 > reach * 0.9 for s in outside), [(s["style"], s["x"], s["y"]) for s in outside])
        gates = rows.get("gate", [])
        present("the city wall has gate tiles on its arterials", len(gates) >= arterials * 4, len(gates))
    if plans:
        checks.extend(check_plans(seed, rows, plans, tile))
    # A seed's `rules` are the world's own law values, kept when it is made (docs/WORLD_RULES.md).
    kept = {r["name"]: json.loads(r["value"]) for r in rows.get("world_law", [])}
    present("the seed's rules are kept as the world's laws", kept == seed.get("rules", {}), {"kept": kept, "seed": seed.get("rules", {})})
    if seed.get("rules", {}).get("minds") is False:
        world = rows["world"][0]
        minded = [c["id"] for c in rows["character"] if c["ai"] or c["controller"] == world["admin"]]
        present("rules.minds false: nobody is mind-controlled", not minded, minded[:20])
    return checks


def check_plans(seed, rows, plans, tile):
    """Hand-authored settlements (`map.params.plans`, docs/AUTHORED_PLANS.md): the planned
    settlement's lot rows are its plan's lots in order, with their kinds, sizes, models and
    heights; its doors are walkable; households the seed binds to lots (`homes`) own those
    houses; named buildings at a lot (`buildings[].lot`) have their sign there; and residents'
    `lot:<id>` places stand at that lot (its spots, else its door)."""
    checks = []

    def present(name, condition, detail=None):
        checks.append({"check": name, "pass": bool(condition), "detail": detail})

    settlements, lots = rows.get("settlement", []), rows.get("lot", [])
    structures = {s["id"]: s for s in rows["structure"]}
    communities = {r["name"]: r["id"] for r in rows["community"]}
    by_name = {c["name"]: c for c in rows["character"]}
    for pid, plan in plans.items():
        town = next((t for t in seed.get("towns", []) + seed.get("villages", []) if t.get("site") == pid), None)
        mine = [s for s in settlements if s["style"] == plan["style"] and s["kind"] == plan.get("kind", "town")]
        present(f"plan {pid}: one settlement in its style", len(mine) == 1, [(s["id"], s["style"]) for s in mine])
        if len(mine) != 1:
            continue
        sid = mine[0]["id"]
        rows_of = sorted((l for l in lots if l["settlement"] == sid), key=lambda l: l["id"])
        want = plan.get("lots", [])
        present(f"plan {pid}: its {len(want)} lots, in order", len(rows_of) == len(want), {"rows": len(rows_of), "plan": len(want)})
        wrong = []
        for spec, row in zip(want, rows_of):
            h = spec.get("height_m", 6.0 if spec["kind"] not in ("garden", "field") else 0.0)
            ok = row["kind"] == spec["kind"] and row["model"] == (spec.get("model") or "") and abs(row["height_m"] - h) < 1e-4 and abs(row["width_m"] - spec["size"][0]) < 1e-3 and abs(row["depth_m"] - spec["size"][1]) < 1e-3
            level = next(lv for lv in plan["levels"] if lv["id"] == spec["level"])
            ok = ok and abs(row["floor_m"] - level["height_m"]) < 1e-4
            if not ok:
                wrong.append({"lot": spec["id"], "row": {k: row[k] for k in ("kind", "model", "height_m", "width_m", "depth_m", "floor_m")}})
        present(f"plan {pid}: lots have their kinds, sizes, models, heights and level floors", not wrong, wrong[:10])
        # Authored resources (`plans[].resources`): every one has a node of its kind at its point
        # (the nearest walkable tile); a kind the world's tables lack refuses the seed
        # (`floor::check`, checked in `guards`). Each node holds and regrows what the plan says
        # (`max`; `regrow_per_h` in game hours, kept per real minute for the world's day), and the
        # nodes naming one `pool` draw on the first one's stock.
        r = math.radians(plan.get("rotation_deg", 0.0))
        o, e, nv = plan["origin"], (math.cos(r), math.sin(r)), (math.sin(r), -math.cos(r))
        land_pt = lambda q: (o[0] + e[0] * q[0] + nv[0] * q[1], o[1] + e[1] * q[0] + nv[1] * q[1])
        hour_ms = rows["world"][0]["day_ms"] / 24.0
        nodes = {}
        for nd in rows["resource_node"]:
            nodes.setdefault(nd["kind"], []).append(nd)
        missing, wrong, pools = [], [], {}
        for rs in plan.get("resources", []):
            at = land_pt(rs["at"])
            nd = min(nodes.get(rs["kind"], []), key=lambda n: math.dist(at, (n["x"], n["y"])), default=None)
            if nd is None or math.dist(at, (nd["x"], nd["y"])) >= 2.5:
                missing.append({"kind": rs["kind"], "at": [round(at[0], 1), round(at[1], 1)]})
                continue
            if rs.get("pool"):
                pools.setdefault(rs["pool"], []).append(nd)
            if "max" in rs and abs(nd["max"] - rs["max"]) > 1e-3 or "regrow_per_h" in rs and abs(nd["regen"] - rs["regrow_per_h"] * 60000.0 / hour_ms) > 1e-5:
                wrong.append({"kind": rs["kind"], "node": {k: nd[k] for k in ("id", "max", "regen")}, "plan": {k: rs.get(k) for k in ("max", "regrow_per_h")}})
        if plan.get("resources"):
            kinds = Counter(rs["kind"] for rs in plan["resources"])
            present(f"plan {pid}: its {len(plan['resources'])} authored resources stand where written ({dict(kinds)})", not missing, missing[:10])
            present(f"plan {pid}: authored resources hold and regrow what the plan says, per real minute for the day", not wrong, wrong[:10])
            shared = {k: sorted({n["pool"] for n in v}) for k, v in pools.items()}
            heads = {k: v[0]["id"] for k, v in pools.items()}
            present(f"plan {pid}: each of its {len(pools)} pools is one stock its spots share", all(len(v) == 1 and v[0] == heads[k] and v[0] != 0 for k, v in shared.items()), {k: {"spots": len(pools[k]), "pool": v} for k, v in shared.items()})
        # Authored structures (`plans[].structures`) at their point, lot door or lot spot, lit for
        # the time their fuel lasts at their kind's burning rate (the seed's laws), with their
        # contents; and each lot's `contents` in the structure at its door.
        lot_of = {spec["id"]: row for spec, row in zip(want, rows_of)}
        spots = {spec["id"]: {sp["name"]: sp["at"] for sp in spec.get("spots", [])} for spec in want}

        def lot_pt(lid, spot=None):
            row = lot_of[lid]
            c, d = (row["x"], row["y"]), (row["door_x"], row["door_y"])
            k = row["depth_m"] * 0.5 + 0.5
            f = ((d[0] - c[0]) / k, (d[1] - c[1]) / k)
            if spot is None:
                return d
            q = spots[lid][spot]
            return (c[0] + f[1] * q[0] + f[0] * q[1], c[1] - f[0] * q[0] + f[1] * q[1])

        def spot_pt(spec, sp):
            """A lot's spot on the land, from the plan itself (`settle::plan::resolve`): metres
            along the lot's front and out toward it. (`lot_pt` reads the front off the row's
            door, which is exact only for a lot whose door is where its front is.)"""
            fc = spec["facing"]
            b = math.radians({"north": 0.0, "n": 0.0, "east": 90.0, "e": 90.0, "south": 180.0, "s": 180.0, "west": 270.0, "w": 270.0}[fc] if isinstance(fc, str) else fc)
            fx, fy = math.sin(b), math.cos(b)
            f = (e[0] * fx + nv[0] * fy, e[1] * fx + nv[1] * fy)
            c = land_pt(spec["at"])
            return (c[0] + f[1] * sp["at"][0] + f[0] * sp["at"][1], c[1] - f[0] * sp["at"][0] + f[1] * sp["at"][1])

        def lot_tiles(spec):
            """A lot's footprint tiles on the land (`host::footprint_tiles`: tile centres inside its
            rectangle; a planned lot has no margin)."""
            fc = spec["facing"]
            b = math.radians({"north": 0.0, "n": 0.0, "east": 90.0, "e": 90.0, "south": 180.0, "s": 180.0, "west": 270.0, "w": 270.0}[fc] if isinstance(fc, str) else fc)
            fx, fy = math.sin(b), math.cos(b)
            f = (e[0] * fx + nv[0] * fy, e[1] * fx + nv[1] * fy)
            c = land_pt(spec["at"])
            hw, hd = spec["size"][0] * 0.5, spec["size"][1] * 0.5
            r = int(math.ceil(math.hypot(hw, hd))) + 1
            out = set()
            for j in range(int(c[1] // 1) - r, int(c[1] // 1) + r + 1):
                for i in range(int(c[0] // 1) - r, int(c[0] // 1) + r + 1):
                    dx, dy = i + 0.5 - c[0], j + 0.5 - c[1]
                    if abs(-dx * f[1] + dy * f[0]) <= hw and abs(dx * f[0] + dy * f[1]) <= hd:
                        out.add((i, j))
            return out

        footprints = {spec["id"]: lot_tiles(spec) for spec in want}

        def own_tiles(lid):
            """The lot's own tiles (docs/AUTHORED_PLANS.md, "A household's own things stand inside
            its lot"): its footprint less street (road, 6) and water (2) tiles and tiles under
            another of the plan's lots."""
            others = set().union(*(t for k, t in footprints.items() if k != lid))
            return {t for t in footprints[lid] if t not in others and tile(t[0] + 0.5, t[1] + 0.5) not in (2, 6)}

        def stands_near(lid, at, reach=1.5):
            """The nearest tile one can stand on within `reach` of `at` that is joined to the lot's
            door by walkable tiles (4-connected, within 12 tiles of the door; doors are reachable:
            hosting refuses a plan otherwise). None when there is none."""
            row = lot_of[lid]
            start = (int(row["door_x"] // 1), int(row["door_y"] // 1))
            if tile(*start) not in WALKABLE:
                return None
            seen, todo = {start}, [start]
            while todo:
                x, y = todo.pop()
                for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if q not in seen and abs(q[0] - start[0]) <= 12 and abs(q[1] - start[1]) <= 12 and tile(q[0] + 0.5, q[1] + 0.5) in WALKABLE:
                        seen.add(q)
                        todo.append(q)
            d = min((math.dist((x + 0.5, y + 0.5), at) for x, y in seen), default=None)
            return d if d is not None and d <= reach else None

        # A structure a household owns placed for a lot without a spot stands inside the lot
        # (since hearth-1): on one of the lot's own tiles.
        inside_of = lambda st: st.get("owner") and st.get("lot") and not st.get("spot") and "at" not in st
        laws_src = seed.get("laws") or ((ROOT / "living/seeds" / seed["laws_file"]).read_text() if seed.get("laws_file") else "")
        rate = {m.group(1): float(m.group(2)) for m in re.finditer(r'name:\s*"(\w+)"[^\n]*?burns:\s*#\{[^}]*?rate:\s*([\d.]+)', laws_src)}
        held = {}
        for iv in rows["inventory"]:
            if iv["owner"] & STRUCTURE_BIT:
                held.setdefault(iv["owner"] & ~STRUCTURE_BIT, {})[iv["item"]] = held.get(iv["owner"] & ~STRUCTURE_BIT, {}).get(iv["item"], 0) + iv["qty"]
        by_kind = {}
        for st in rows["structure"]:
            by_kind.setdefault(st["kind"], []).append(st)
        absent, unlit, unstocked, taken, placed, used = [], [], [], set(), {}, []
        outside = []
        for i, st in enumerate(plan.get("structures", [])):
            at = land_pt(st["at"]) if "at" in st else lot_pt(st["lot"], st.get("spot"))
            if inside_of(st):
                own = own_tiles(st["lot"])
                near = [x for x in by_kind.get(st["kind"], []) if x["id"] not in taken and (int(x["x"] // 1), int(x["y"] // 1)) in own]
                if not near:
                    by = min(by_kind.get(st["kind"], []), key=lambda x: math.dist(at, (x["x"], x["y"])), default=None)
                    outside.append({"kind": st["kind"], "lot": st["lot"], "nearest": by and {"at": [round(by["x"], 2), round(by["y"], 2)], "tile": tile(by["x"], by["y"]), "of_lot": [k for k, t in footprints.items() if (int(by["x"] // 1), int(by["y"] // 1)) in t]}})
                    continue
            else:
                near = [x for x in by_kind.get(st["kind"], []) if x["id"] not in taken and math.dist(at, (x["x"], x["y"])) < 2.5]
            if not near:
                absent.append({"kind": st["kind"], "at": [round(at[0], 1), round(at[1], 1)], "lot": st.get("lot")})
                continue
            x = min(near, key=lambda x: math.dist(at, (x["x"], x["y"])))
            taken.add(x["id"])
            placed[i] = x
            fuel = st.get("fuel", 0.0)
            want_ms = fuel / rate[st["kind"]] * hour_ms if fuel > 0 and st["kind"] in rate else 0.0
            if abs((x["lit_until_ms"] - x["built_ms"] if x["lit_until_ms"] else 0) - want_ms) > 2.0:
                unlit.append({"kind": st["kind"], "lot": st.get("lot"), "fuel": fuel, "lit_ms": x["lit_until_ms"] - x["built_ms"] if x["lit_until_ms"] else 0, "want_ms": want_ms})
            h, c = held.get(x["id"], {}), st.get("contents", {})
            if st.get("owner"):
                # A household's own store is its people's from the first tick: in the seconds the
                # world runs before the snapshot (doctor), they may take from it or store in it.
                # It holds no more of the plan's items than the plan gives, and what is gone is
                # reported.
                gone = {k: c[k] - h.get(k, 0) for k in c if h.get(k, 0) != c[k]}
                if any(h.get(k, 0) > c[k] for k in c):
                    unstocked.append({"kind": st["kind"], "owner": st["owner"], "holds": h, "plan": c})
                elif gone or set(h) - set(c):
                    used.append({"owner": st["owner"], "taken": gone, "added": {k: v for k, v in h.items() if k not in c}})
            elif h != c:
                unstocked.append({"kind": st["kind"], "holds": h, "plan": c})
        for spec in want:
            if spec.get("contents"):
                row = lot_of[spec["id"]]
                if held.get(row["structure"], {}) != spec["contents"]:
                    unstocked.append({"lot": spec["id"], "holds": held.get(row["structure"], {}), "plan": spec["contents"]})
        # A lot's own door structure (`lots[].structure`): that kind stands at its door.
        own = [spec for spec in want if spec.get("structure")]
        if own:
            wrong_door = [{"lot": spec["id"], "plan": spec["structure"], "row": structures.get(lot_of[spec["id"]]["structure"], {}).get("kind")} for spec in own if structures.get(lot_of[spec["id"]]["structure"], {}).get("kind") != spec["structure"]]
            present(f"plan {pid}: {len(own)} lots have their own door structure ({', '.join(sorted({spec['structure'] for spec in own}))})", not wrong_door, wrong_door)
        # Structures a household owns (`owner: "household:<key>"`): the owner of the household's
        # house (the one on its `homes` lot), a resident of that household.
        owned = [(st, placed[i]) for i, st in enumerate(plan.get("structures", [])) if st.get("owner") and placed.get(i)]
        if any(st.get("owner") for st in plan.get("structures", [])):
            members_of = {}
            for r in (town or {}).get("residents", []):
                members_of.setdefault(r.get("household") or r["name"], set()).add(by_name.get(r["name"], {}).get("id"))
            home_lot = (town or {}).get("homes", {})
            badly = []
            for st, x in owned:
                hh = st["owner"].removeprefix("household:")
                house = structures.get(lot_of[home_lot[hh]]["structure"], {}) if hh in home_lot else {}
                if not x["owner"] or x["owner"] != house.get("owner") or x["owner"] not in members_of.get(hh, set()):
                    badly.append({"kind": st["kind"], "household": hh, "owner": x["owner"], "house_owner": house.get("owner")})
            n = sum(1 for st in plan.get("structures", []) if st.get("owner"))
            present(f"plan {pid}: its {n} household structures are placed and owned by their household's house owner", len(owned) == n and not badly, {"placed": len(owned), "wrong": badly[:10]})
            # Since hearth-1: those placed for a lot stand inside it, never on a street's tile or
            # another lot's, and each within act reach (1.5 m) of a tile one stands on that is
            # joined to the lot's door.
            ins = [(st, x) for st, x in owned if inside_of(st)]
            if any(inside_of(st) for st in plan.get("structures", [])):
                m = sum(1 for st in plan.get("structures", []) if inside_of(st))
                kinds = Counter(st["kind"] for st in plan["structures"] if inside_of(st))
                present(f"plan {pid}: its {m} household structures placed for a lot stand inside it, on its own tiles, not a street's or another lot's ({dict(kinds)})", len(ins) == m and not outside, {"inside": len(ins), "outside": outside[:10]})
                far = []
                on_floor = 0
                for st, x in ins:
                    d = stands_near(st["lot"], (x["x"], x["y"]))
                    on_floor += tile(x["x"], x["y"]) not in WALKABLE
                    if d is None:
                        far.append({"kind": st["kind"], "lot": st["lot"], "at": [round(x["x"], 2), round(x["y"], 2)]})
                present(f"plan {pid}: each of them is within 1.5 m (act reach) of a tile one stands on, joined to its lot's door ({on_floor} on a building's floor)", ins and not far, far[:10])
        if plan.get("structures"):
            kinds = Counter(st["kind"] for st in plan["structures"])
            present(f"plan {pid}: its {len(plan['structures'])} authored structures stand where written ({dict(kinds)})", not absent, absent[:10])
            present(f"plan {pid}: authored fires are lit for as long as their fuel lasts at their burning rate", not unlit, unlit[:10])
        if plan.get("structures") or any(spec.get("contents") for spec in want):
            present(f"plan {pid}: authored structures and lot stores hold what the plan says" + (f" ({len(used)} household stores already used by their people)" if used else ""), not unstocked, {"wrong": unstocked[:10], "used": used})
        present(f"plan {pid}: doors are walkable", all(tile(l["door_x"], l["door_y"]) in WALKABLE for l in rows_of if l["structure"]), [l["id"] for l in rows_of if l["structure"] and tile(l["door_x"], l["door_y"]) not in WALKABLE])
        # Fixtures that block (`plans[].fixtures`, since layout-2): every point along a blocking
        # line (outside its gaps) or inside a blocking rectangle is a tile no one walks on, a
        # wall that rises above the eye (1.6 m) is `Wall` (7) wherever it is not a drop's edge,
        # and a gap's middle is left open. Every spot of every lot is ground one can stand on.
        blocking = [fx for fx in plan.get("fixtures", []) if fx.get("blocks")]
        if blocking:
            walked, seen_over, shut, lines = [], [], [], 0
            for k, fx in enumerate(blocking):
                name = fx.get("id") or f"fixtures[{k}] ({fx.get('kind', '')})"
                tall = fx.get("height_m", 0.0) > 1.6 and fx.get("eye_solid", 1.0) >= 0.8
                pts = []
                if fx.get("points"):
                    lines += 1
                    q, along = fx["points"], 0.0
                    for a, b in zip(q, q[1:]):
                        ln = math.dist(a, b)
                        n = max(1, int(ln / 0.25))
                        for i in range(n + 1):
                            s_ = along + ln * i / n
                            if not any(g[0] - 0.75 <= s_ <= g[1] + 0.75 for g in fx.get("gaps", [])):
                                pts.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
                        for g in fx.get("gaps", []):
                            m = (g[0] + g[1]) / 2
                            if along <= m <= along + ln:
                                gp = land_pt((a[0] + (b[0] - a[0]) * (m - along) / ln, a[1] + (b[1] - a[1]) * (m - along) / ln))
                                if tile(*gp) not in WALKABLE:
                                    shut.append({"fixture": name, "gap": g, "tile": tile(*gp)})
                        along += ln
                else:
                    pts.append(tuple(fx["at"]))
                for q in pts:
                    t = tile(*land_pt(q))
                    if t in WALKABLE:
                        walked.append({"fixture": name, "at": [round(q[0], 2), round(q[1], 2)], "tile": t})
                    elif tall and t == 9:
                        seen_over.append({"fixture": name, "at": [round(q[0], 2), round(q[1], 2)]})
            present(f"plan {pid}: its {len(blocking)} blocking fixtures ({lines} lines) stand on tiles no one walks on", not walked, walked[:10])
            present(f"plan {pid}: a blocking fixture above the eye hides (Wall tiles), a lower one is seen over", not seen_over, seen_over[:10])
            present(f"plan {pid}: every gap in a blocking line is open at its middle", not shut, shut[:10])
        off = []
        for spec in want:
            for sp in spec.get("spots", []):
                q = spot_pt(spec, sp)
                if tile(*q) not in WALKABLE:
                    off.append({"lot": spec["id"], "spot": sp["name"], "tile": tile(*q)})
        present(f"plan {pid}: every one of its lots' {sum(len(spec.get('spots', [])) for spec in want)} spots is ground one can stand on", not off, off[:10])
        key = {spec["id"]: row for spec, row in zip(want, rows_of)}
        if not town:
            continue
        members = {}
        for r in town.get("residents", []):
            members.setdefault(r.get("household") or r["name"], []).append(r["name"])
        for hh, lot_id in town.get("homes", {}).items():
            row = key.get(lot_id)
            owner = structures.get(row["structure"], {}).get("owner") if row else None
            names = {by_name[n]["id"] for n in members.get(hh, []) if n in by_name}
            present(f"plan {pid}: household {hh} owns the house on lot {lot_id}", row and owner in names, {"owner": owner, "household": sorted(names)})
            homes = {(round(by_name[n]["home_x"], 1), round(by_name[n]["home_y"], 1)) for n in members.get(hh, []) if n in by_name}
            present(f"plan {pid}: household {hh} lives at lot {lot_id}'s door", row and homes == {(round(row["door_x"], 1), round(row["door_y"], 1))}, {"homes": sorted(homes), "door": row and [row["door_x"], row["door_y"]]})
        # Every household keeps its house and, where the plan gives its home a store of its own
        # and a fire (its own, or one at a spot of its lot: the Marver's public hearth), that
        # store and fire, standing at its home lot (since hearth-1).
        fires = set(rate) | {"campfire", "hearth"}
        stores = lambda k: k == "storage" or k.endswith("store")
        lacking = []
        for hh, lot_id in town.get("homes", {}).items():
            row = key.get(lot_id)
            if not row:
                continue
            house = structures.get(row["structure"], {})
            names = {by_name[n]["id"] for n in members.get(hh, []) if n in by_name}
            at_home = [st for st in plan.get("structures", []) if st.get("lot") == lot_id and (st.get("owner") in (None, f"household:{hh}"))]
            want_fire = any(st["kind"] in fires for st in at_home)
            here = lambda x: (int(x["x"] // 1), int(x["y"] // 1)) in footprints[lot_id] or math.dist((x["x"], x["y"]), (row["door_x"], row["door_y"])) <= 6.0
            fire = [x for x in rows["structure"] if x["kind"] in fires and (x["owner"] in names or not x["owner"]) and here(x)]
            store = [x for x in rows["structure"] if stores(x["kind"]) and x["owner"] in names and here(x)]
            want_store = any(stores(st["kind"]) and st.get("owner") for st in at_home)
            if house.get("owner") not in names or (want_store and not store) or (want_fire and not fire):
                lacking.append({"household": hh, "lot": lot_id, "house_owner": house.get("owner"), "store": len(store), "fire": len(fire), "plan_gives": {"store": want_store, "fire": want_fire}})
        if town.get("homes"):
            present(f"plan {pid}: each of its {len(town['homes'])} households has its house, and the store and fire its plan gives its home", not lacking, lacking[:10])
        signs = {a["topic"]: a for a in rows["artifact"] if a["kind"] == "sign"}
        for b in town.get("buildings", []):
            if not b.get("lot"):
                continue
            row, a = key.get(b["lot"]), signs.get(b["name"])
            st = structures.get((a or {}).get("holder", 0) & ~(1 << 40))
            present(f"plan {pid}: {b['name']}'s sign stands at lot {b['lot']}'s door", row and st and math.dist((st["x"], st["y"]), (row["door_x"], row["door_y"])) < 3.0, {"sign": st and [st["x"], st["y"]], "door": row and [row["door_x"], row["door_y"]]})
        places = {}
        for p in rows.get("place", []):
            places.setdefault(p["actor"], {})[p["name"]] = (p["x"], p["y"])
        residents = [by_name[r["name"]]["id"] for r in town.get("residents", []) if r["name"] in by_name]
        for name, kinds in seed.get("town_life", {}).get("places", {}).items():
            lk = next((k[4:] for k in kinds if k.startswith("lot:")), None)
            if not lk or lk not in key:
                continue
            spec = next(x for x in want if x["id"] == lk)
            row = key[lk]
            # A place by lot stands at one of the lot's spots (in the lot's frame: along its front,
            # then out toward it), else at its door. Since layout-2 a spot may lie anywhere on an
            # open lot (a court's washing line, a yard's far corner), so each resident's place is
            # held to a spot, not to the door's neighbourhood.
            stands = [spot_pt(spec, sp) for sp in spec.get("spots", [])] or [(row["door_x"], row["door_y"])]
            far = [i for i in residents if name in places.get(i, {}) and min(math.dist(places[i][name], q) for q in stands) > 1.0]
            known = [i for i in residents if name in places.get(i, {})]
            present(f"plan {pid}: place {name!r} is at lot {lk}, on one of its {len(spec.get('spots', []))} spots", known and not far, {"residents": len(known), "far": far})
        present(f"plan {pid}: its town's community stands on it", communities.get(town["name"]) == mine[0]["community"], {"community": mine[0]["community"]})
    return checks


def native_digests(d, rows, target):
    """The land row's digests against the same seed regenerated natively
    (`living/rules/examples/floor_preview.rs`): the WASM authority and a native client must
    derive the same tiles, heights and layout."""
    code = command(["cargo", "run", "--release", "-q", "-p", "living-rules", "--example", "floor_preview", "--target-dir", str(target), "--",
                    str(d / "seed.json"), "0", str(d / "native"), "16"], d / "native-digests.log", cwd=ROOT / "living", timeout=900)
    text = (d / "native-digests.log").read_text()
    found = re.search(r"digests tiles ([0-9a-f]{16}) heights ([0-9a-f]{16}) layout ([0-9a-f]{16})", text)
    land = rows.get("land", [{}])[0]
    row = [format(int(land.get(k, 0)), "016x") for k in ("tiles_digest", "heights_digest", "layout_digest")]
    native = list(found.groups()) if found else None
    # The arrival point is part of the layout digest; compared on its own too, so a mismatch
    # names it.
    at = re.search(r"arrival (-?[0-9.]+) (-?[0-9.]+)", text)
    arrive = [round(float(land.get(k, 0)), 2) for k in ("arrive_x", "arrive_y")]
    native_arrive = [float(at.group(1)), float(at.group(2))] if at else None
    return {"check": "land digests and arrival point match the native generator", "pass": code == 0 and native == row and native_arrive == arrive, "authority": row, "native": native, "arrival": arrive, "native_arrival": native_arrive}


def no_secrets(seed, rows):
    public = json.dumps(rows, ensure_ascii=False)
    sheets = [r.get("sheet", {}) for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", [])]
    secrets = [s["secret"] for s in sheets if s and s.get("secret")]
    # Nested JSON text columns are escaped by the outer export.
    decoded = "\n".join(str(value) for table in rows.values() for row in table for value in row.values())
    return {"pass": not any(secret in decoded or secret in public for secret in secrets) and all("secret" not in json.loads(r["text"]).get("sheet", {}) for r in rows["background"]), "nonempty_secrets_checked": len(secrets), "public_tables_checked": sorted(rows)}


def repeatability(first, second):
    def columns(table, keys, animals=False):
        return sorted([r[k] for k in keys] for r in table if not animals or r["kind"] != "person")
    comparisons = {
        "terrain": ("terrain_chunk", ("id", "tiles")),
        "settlement sites": ("community", ("name", "home_x", "home_y")),
        "resource positions": ("resource_node", ("kind", "x", "y")),
        # Without ids: two publications can number rows differently (an auto_inc sequence can
        # jump between them) while creating the same rows.
        "names": ("character", ("name",)),
        "ages": ("character", ("name", "birth_age_days")),
        "genes": ("genome", ("genes",)),
        "animal spawn positions": ("character", ("kind", "home_x", "home_y")),
    }
    report = {}
    for name, (table, keys) in comparisons.items():
        a, b = columns(first[table], keys, name == "animal spawn positions"), columns(second[table], keys, name == "animal spawn positions")
        report[name] = {"equal": a == b, "rows_first": len(a), "rows_second": len(b), "different_paired_rows": sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b)), "sha256_first": hashlib.sha256(json.dumps(a).encode()).hexdigest(), "sha256_second": hashlib.sha256(json.dumps(b).encode()).hexdigest()}
    def band_sites(rows):
        return sorted({(bg["band"], *bg["camp"]) for row in rows["background"] if (bg := json.loads(row["text"])).get("origin") == "band"})
    a, b = band_sites(first), band_sites(second)
    report["band sites"] = {"equal": a == b, "first": a, "second": b}
    # Since 2026-11-10 world creation draws from the world seed and the step (seed.rs `rng`),
    # so what it places at random repeats too.
    report["pass"] = all(report[k]["equal"] for k in ("terrain", "settlement sites", "band sites", "resource positions", "names", "ages", "genes", "animal spawn positions"))
    return report


def authored(directory, living, world="aske-coast"):
    directory = directory / f"authored-{world}" if world != "aske-coast" else directory
    directory.mkdir(exist_ok=True)
    wrapper = directory / "compile_offline.py"
    wrapper.write_text('''import json, pathlib, runpy, socket, sys, urllib.request
attempts = []
def blocked(*args, **kwargs):
    attempts.append("network attempt")
    raise RuntimeError("compile-only attempted network access")
socket.socket.connect = blocked
socket.create_connection = blocked
urllib.request.urlopen = blocked
sys.argv = [sys.argv[1], sys.argv[2], "--compile-only"]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    pathlib.Path(__file__).with_name("network.json").write_text(json.dumps(attempts))
''')
    code = command([sys.executable, str(wrapper), str(living / "tools/author_world.py"), world], directory / "compile.log", timeout=120)
    into = json.loads((living / f"seeds/worlds/{world}/world.json").read_text())["into"] if (living / f"seeds/worlds/{world}/world.json").exists() else world
    actual = living / f"seeds/{into}.json"
    original = ROOT / f"living/seeds/{into}.json"
    shutil.copy2(actual, directory / f"compiled-{into}.json")
    a, b = json.loads(actual.read_text()), json.loads(original.read_text())
    differences = []

    def diff(a, b, path="$"):
        if type(a) is not type(b):
            differences.append({"path": path, "compiled": a, "committed": b})
        elif isinstance(a, dict):
            for k in sorted(a.keys() | b.keys()):
                if k not in a or k not in b:
                    differences.append({"path": path + "." + k, "compiled": a.get(k), "committed": b.get(k)})
                else:
                    diff(a[k], b[k], path + "." + k)
        elif isinstance(a, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                diff(x, y, f"{path}[{i}]")
        elif a != b:
            differences.append({"path": path, "compiled": a, "committed": b})
    diff(a, b)
    write(directory / "compile-differences.json", differences)
    report = {"pass": code == 0 and json.loads((directory / "network.json").read_text()) == [], "byte_equal": actual.read_bytes() == original.read_bytes(), "semantic_equal": a == b, "differences": len(differences)}
    write(directory / "authored.json", report)
    return report


def suite(args):
    if not re.fullmatch(r"generation-[a-z0-9-]+", args.run):
        raise SystemExit("run must start generation- and contain lowercase letters, digits or hyphens")
    directory = BASE / args.run
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "target"
    original_seeds = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "living/seeds").rglob("*") if p.is_file()}
    results = {}
    snapshots = {}
    try:
        if args.feature in ("all", "authored"):
            results["authored"] = authored(directory, authored_copy(directory))
            results["authored island"] = authored(directory, authored_copy(directory, "island"), "island")
        if args.feature in ("all", "guards"):
            code = command(["cargo", "test", "-p", "living-authority", "--lib", "--target-dir", str(target), "seed::tests::", "--", "--nocapture"], directory / "seed-tests.log", cwd=ROOT / "living", env=dict(os.environ, LIVING_SEED="authored-test"), timeout=900)
            results["seed tests"] = {"pass": code == 0}
        seeds = list(SEEDS) + ["realm"] if args.feature in ("all", "worlds") else []
        if args.seeds:
            # Any tracked seed may be named (a trial world such as `hamlet`), not only the suite's.
            seeds = [x for x in args.seeds.split(",") if x in SEEDS or (ROOT / f"living/seeds/{x}.json").exists()]
        if args.feature in ("all", "guards"):
            malformed = json.loads((ROOT / "living/seeds/authored-test.json").read_text())
            del malformed["animals"]
            write(directory / "malformed.json", malformed)
            seeds.append("malformed")
        for index, seed_name in enumerate(seeds):
            active_run = f"{args.run}-{index}-{seed_name}"
            d = BASE / active_run
            d.mkdir(parents=True, exist_ok=False)
            if seed_name in DERIVED:
                source, change = DERIVED[seed_name]
                derived = json.loads((ROOT / f"living/seeds/{source}.json").read_text())
                derived["map"].update(change)
                derived["run"] = seed_name
                seed_path = directory / f"{seed_name}.json"
                write(seed_path, derived)
            elif seed_name in LAWS_FLOORS:
                seed_path = ROOT / f"living/seeds/{LAWS_FLOORS[seed_name]}.json"
            elif seed_name in LOOKS_FLOORS:
                seed_path = ROOT / f"living/seeds/{LOOKS_FLOORS[seed_name]}.json"
            else:
                seed_path = directory / "malformed.json" if seed_name == "malformed" else ROOT / f"living/seeds/{seed_name}.json"
            # As the world receives it: a laws file read in (build.rs, seed_text.py).
            write(d / "seed.json", seed_text(seed_path) if seed_name != "malformed" else json.loads(seed_path.read_text()))
            database = "verify-" + active_run
            seed_arg = "none" if seed_name in FLOORS else str(seed_path.with_suffix("")) if seed_name == "malformed" or seed_name in DERIVED else seed_name
            # A seed's `rules` are world laws kept at creation (`world_law`), not compiled in.
            launch_env = None
            container = subprocess.run(["docker", "ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Status}}"], capture_output=True, text=True, check=True, timeout=30)
            if not container.stdout.strip().startswith("Up"):
                raise RuntimeError("existing SpacetimeDB container is down; start it before running this skill")
            try:
                started = datetime.now(timezone.utc).isoformat()
                launch_code = harness("launch", active_run, d / "launch.log", "--seed", seed_arg, "--target-dir", target / ("floor" if seed_name in FLOORS else "seeded"), env=launch_env)
                ended = datetime.now(timezone.utc).isoformat()
                if seed_name == "malformed":
                    identity_status, identity = database_identity(database)
                    built = target / "seeded/wasm32-unknown-unknown/release/living_authority.wasm"
                    state = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
                    publication = {"started": started, "ended": ended, "identity_status": identity_status, "database_identity": identity, "wasm_sha256": hashlib.sha256(built.read_bytes()).hexdigest() if built.exists() else None, "publication_attempted": state.get("published", False)}
                    write(d / "publication.json", publication)
                    server = subprocess.run(["docker", "logs", "--since", started, "--until", ended, CONTAINER], capture_output=True, text=True, timeout=30)
                    records = re.split(r"(?=\d{4}-\d{2}-\d{2}T)", server.stdout + server.stderr)
                    launch_key = f"launching module db={identity} " if identity_status == 200 else "NO_CORRELATED_LAUNCH"
                    selected = [r for r in records if launch_key in r or "reducer \"init\" runtime error" in r or "seed: " in r or ("Frame #" in r and ("::seed::seed" in r or "rust_panic" in r or "__rust_start_panic" in r))]
                    (d / "server-init.log").write_text("".join(selected))
                    command([str(ROOT / "living/tools/stdb"), "logs", "-s", "local", database, "--num-lines", "100"], d / "module.log", timeout=30)
                    query_code = harness("sql", active_run, d / "init-state.log", "SELECT * FROM world")
                    query = (d / "init-state.log").read_text()
                    write(d / "init-state.json", {"exit_code": query_code, "output": query})
                    text = (d / "launch.log").read_text() + (d / "module.log").read_text()
                    trace = (d / "server-init.log").read_text()
                    readable = "animals" in text and "missing field" in text
                    rejected = launch_code != 0 and publication["publication_attempted"] and query_code != 0 and "sql: 404" in query
                    report = {"pass": rejected, "rejection": "PASS" if rejected else "FAIL",
                              "known_issue": {"label": "KNOWN ISSUE", "reference": "docs/LIVING_HANDOFF.md, Still open", "source": "living/authority/src/lib.rs (init)", "description": "init returns `seed: missing field ...` instead of panicking; the shared harness truncates publication stderr, so whether the field is named is recorded (missing_field_diagnostic_visible), not asserted", "readable_error_asserted": False},
                              "launch_exit_code": launch_code, "panic_reported": "::seed::seed" in trace and "rust_panic" in trace,
                              "missing_field_diagnostic_visible": readable, "database_launch_correlated": launch_key in trace}
                    write(d / "guards.json", report)
                    results["malformed seed"] = report
                    print(f"{report['rejection']} malformed seed rejection; readability is not asserted (KNOWN ISSUE, docs/LIVING_HANDOFF.md, Still open)", flush=True)
                    continue
                if launch_code:
                    raise RuntimeError(f"launch failed; read {d}/launch.log")
                floor_checks = create_floor_looks(active_run, d, seed_text(seed_path)) if seed_name in LOOKS_FLOORS else create_floor_laws(active_run, d, seed_text(seed_path)) if seed_name in LAWS_FLOORS else create_floor(active_run, d, json.loads(seed_path.read_text())) if seed_name in FLOORS else []
                if floor_checks and not all(c["pass"] for c in floor_checks):
                    write(d / "checks.json", floor_checks)
                    raise RuntimeError(f"floor creation failed; read {d}/create-floor.log and genesis-final.json")
                if harness("doctor", active_run, d / "doctor.log"):
                    raise RuntimeError(f"doctor failed; read {d}/doctor.log")
                if harness("call", active_run, d / "pause.log", "set_paused", "[true]", "--as-admin"):
                    raise RuntimeError(f"pause failed; read {d}/pause.log")
                rows = snapshot(active_run, TABLES)
                public_tables = re.findall(r"#\[spacetimedb::table\(accessor = (\w+), public\)\]", (ROOT / "living/authority/src/tables.rs").read_text())
                rows.update(snapshot(active_run, [t for t in public_tables if t not in rows]))
                checks = floor_checks + check_seed(json.loads((d / "seed.json").read_text()), rows)
                if json.loads((d / "seed.json").read_text()).get("map", {}).get("kind") == "land":
                    checks.append(native_digests(d, rows, target))
                checks.append({"check": "public tables exclude sheet secrets", **no_secrets(json.loads((d / "seed.json").read_text()), rows)})
                write(d / "checks.json", checks)
                results[active_run] = {"pass": all(c["pass"] for c in checks), "checks": len(checks), "failed": [c["check"] for c in checks if not c["pass"]]}
                if seed_name in snapshots:
                    report = repeatability(snapshots[seed_name], rows)
                    write(directory / "repeatability.json", report)
                    results["repeatability"] = {"pass": report["pass"]}
                else:
                    snapshots[seed_name] = rows
            finally:
                code = harness("cleanup", active_run, d / "cleanup.log")
                state = json.loads((d / "state.json").read_text())
                module = ROOT / "living/target/wasm32-unknown-unknown/release" / state.get("wasm", "unused")
                cleaned = code == 0 and not state.get("published", False) and not module.exists()
                evidence_exists = all((d / name).exists() for name in ("seed.json", "launch.log", "actions.log"))
                write(d / "cleanup.json", {"database": database, "exit_code": code, "deletion_confirmation": "shared harness requires SQL 404", "module_copy_removed": not module.exists(), "evidence_exists": evidence_exists, "pass": cleaned and evidence_exists})
                results[active_run + " cleanup"] = {"pass": cleaned and evidence_exists}
                if not cleaned or not evidence_exists:
                    raise RuntimeError(f"cleanup or evidence retention failed; read {d}/cleanup.log")
    finally:
        now = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "living/seeds").rglob("*") if p.is_file()}
        results["original seeds unchanged"] = {"pass": original_seeds == now}
        write(directory / "results.json", results)
    print(json.dumps(results, indent=2))
    return 0 if all(r["pass"] for r in results.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--feature", choices=("all", "worlds", "authored", "guards"), default="all")
    parser.add_argument("--seeds", help="comma-separated subset of the worlds' seeds (e.g. floor-megacity-2k,floor-megacity-4k)")
    args = parser.parse_args()
    return suite(args)


if __name__ == "__main__":
    sys.exit(main())
