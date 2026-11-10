#!/usr/bin/env python3
"""Prove seeded worlds through the real authority; retain evidence and delete each DB."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
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
SEEDS = ("realm", "valley", "authored-test", "aske-coast", "stage3-village", "island", "floor-megacity-2k", "floor-megacity-4k")
# Seeds derived from a tracked seed in the run's directory (published through `--seed` with an
# absolute path): the megacity floor (docs/FLOORS.md) at 2048 m, created inside `init` from a
# compiled seed, and at 4096 m as a floor: a module built without a seed (`--seed none`) given
# the seed at runtime by `create_floor`, which creates the land in scheduled steps (`genesis`).
DERIVED = {"floor-megacity-2k": ("floor-megacity", {"size": 2048}), "floor-megacity-4k": ("floor-megacity", {"size": 4096})}
FLOORS = ("floor-megacity-4k",)
TABLES = ("world", "terrain_chunk", "character", "background", "community",
          "membership", "structure", "artifact", "resource_node", "genome", "body", "inventory",
          "place", "routine", "relation", "acquaintance")
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


def create_floor(run, d, seed):
    """Give a floor module its seed and wait for the staged creation (`genesis`) to finish;
    returns the checks."""
    started = time.time()
    code = harness("call", run, d / "create-floor.log", "create_floor", json.dumps([json.dumps(seed)]), "--as-admin")
    checks = [{"check": "create_floor accepted the seed", "pass": code == 0}]
    rows, polls = [], 0
    while code == 0 and time.time() - started < 900:
        polls += 1
        if harness("sql", run, d / "genesis-poll.log", "SELECT * FROM genesis", "--save", "genesis") == 0:
            rows = json.loads((d / "genesis.json").read_text())
            if rows and rows[0].get("done"):
                break
        time.sleep(3)
    g = rows[0] if rows else {}
    elapsed = round(time.time() - started, 1)
    write(d / "genesis-final.json", {"row": g, "seconds": elapsed, "polls": polls})
    checks.append({"check": "the staged creation finished", "pass": bool(g.get("done")), "detail": {"steps": g.get("step"), "seconds": elapsed}})
    checks.append({"check": "no generation restarts", "pass": g.get("restarts") == 0, "detail": g.get("restarts")})
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
    present("terrain chunks contain 256 valid tiles", all(len(t) == 256 and max(t) <= 7 for t in tiles))
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
        present(f"{t['name']} settlement backgrounds", bool(ids) and all(bg.get("town_center") is not None and bg.get("walled") == t.get("walled", True) for i, bg in bgs.items() if i in ids))
        if t.get("ledger"):
            present(f"{t['name']} ledger", any(a["text"] == t["ledger"] for a in artifacts))
        for building in t.get("buildings", []):
            places = [p for i in ids for p in bgs[i].get("places", []) if p["name"] == building["name"] and p["kind"] == building["kind"]]
            present(f"building {building['name']} place", len(places) == len(ids))
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
    if m.get("kind") == "land":
        checks.extend(check_land(seed, rows, size[0], tiles))
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
    communities = {r["name"]: r for r in rows["community"]}
    entries = seed.get("towns", []) + seed.get("villages", [])
    present("settlement rows", len(settlements) >= len(entries), {"rows": len(settlements), "seeded": len(entries)})
    linked = {s["community"] for s in settlements if s["community"]}
    present("every seeded settlement linked to its community", all(communities.get(t["name"], {}).get("id") in linked for t in entries), sorted(linked))
    for t in entries:
        want = t.get("site") or ("town" if t in seed.get("towns", []) else "village")
        c = communities.get(t["name"], {}).get("id")
        # A town in its own style is named by its site id, `<style>_<kind>` (steampunk_town).
        present(f"{t['name']} stands on a {want} site", any(s["community"] == c and want in (s["kind"], f"{s['style']}_{s['kind']}") for s in settlements))
    lots = rows.get("lot", [])
    structures = {s["id"]: s for s in rows["structure"]}
    present("lot ids are 0..n", sorted(l["id"] for l in lots) == list(range(len(lots))), len(lots))
    bad_door = [l["id"] for l in lots if l["kind"] in DOOR_KINDS and not (l["structure"] in structures and structures[l["structure"]]["kind"] == DOOR_KINDS[l["kind"]] and abs(structures[l["structure"]]["x"] - l["door_x"]) < 0.01 and abs(structures[l["structure"]]["y"] - l["door_y"]) < 0.01)]
    present("every building lot has its structure at its door", not bad_door, bad_door[:20])
    present("no structure on open lots", all(l["structure"] == 0 for l in lots if l["kind"] not in DOOR_KINDS))
    present("doors are walkable", all(tile(l["door_x"], l["door_y"]) in WALKABLE for l in lots if l["structure"]), [l["id"] for l in lots if l["structure"] and tile(l["door_x"], l["door_y"]) not in WALKABLE][:20])
    blocking = [l for l in lots if l["kind"] in BLOCKING]
    walled = [l["id"] for l in blocking if tile(l["x"], l["y"]) == 7]
    present("blocking lots stand on wall tiles", len(walled) == len(blocking), {"blocking": len(blocking), "wall_at_centre": len(walled), "open": [l["id"] for l in blocking if l["id"] not in walled][:20]})
    present("open lots stay walkable", all(tile(l["x"], l["y"]) in WALKABLE | {2} for l in lots if l["kind"] in ("garden", "field", "lamp")))
    houses = {s["id"] for s in structures.values() if s["kind"] == "house"}
    lot_houses = {l["structure"] for l in lots if l["kind"] in ("house", "townhouse")}
    present("houses are lot houses", houses == lot_houses, {"houses": len(houses), "lot_houses": len(lot_houses)})
    owners = {structures[i]["owner"] for i in lot_houses if structures[i]["owner"]}
    present("households own lot houses", len(owners) > 0, len(owners))
    bgs = {r["id"]: json.loads(r["text"]) for r in rows["background"]}
    folk = {s["community"]: s for s in settlements}
    members = {m["member"]: m["community"] for m in rows["membership"]}
    wrong = [i for i, c in members.items() if c in folk and (bgs.get(i, {}).get("folk") != folk[c]["kind"] or abs((bgs.get(i, {}).get("body_scale") or -1) - folk[c]["scale"]) > 1e-3)]
    present("residents' backgrounds name their folk and scale", members and not wrong, wrong[:20])
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
        present("residents know the seed's places (square, inn, evening)", residents and len(missing) <= 0.05 * len(residents), {"residents": len(residents), "missing": missing[:20]})
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
    if seed.get("rules", {}).get("minds") is False:
        world = rows["world"][0]
        minded = [c["id"] for c in rows["character"] if c["ai"] or c["controller"] == world["admin"]]
        present("rules.minds false: nobody is mind-controlled", not minded, minded[:20])
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
    return {"check": "land digests match the native generator", "pass": code == 0 and native == row, "authority": row, "native": native}


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
        "names": ("character", ("id", "name")),
        "ages": ("character", ("id", "birth_age_days")),
        "genes": ("genome", ("id", "genes")),
        "animal spawn positions": ("character", ("id", "home_x", "home_y")),
    }
    report = {}
    for name, (table, keys) in comparisons.items():
        a, b = columns(first[table], keys, name == "animal spawn positions"), columns(second[table], keys, name == "animal spawn positions")
        report[name] = {"equal": a == b, "rows_first": len(a), "rows_second": len(b), "different_paired_rows": sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b)), "sha256_first": hashlib.sha256(json.dumps(a).encode()).hexdigest(), "sha256_second": hashlib.sha256(json.dumps(b).encode()).hexdigest()}
    def band_sites(rows):
        return sorted({(bg["band"], *bg["camp"]) for row in rows["background"] if (bg := json.loads(row["text"])).get("origin") == "band"})
    a, b = band_sites(first), band_sites(second)
    report["band sites"] = {"equal": a == b, "first": a, "second": b}
    report["pass"] = all(report[k]["equal"] for k in ("terrain", "settlement sites", "band sites"))
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
            seeds = [x for x in args.seeds.split(",") if x in SEEDS]
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
            else:
                seed_path = directory / "malformed.json" if seed_name == "malformed" else ROOT / f"living/seeds/{seed_name}.json"
            write(d / "seed.json", json.loads(seed_path.read_text()))
            database = "verify-" + active_run
            seed_arg = "none" if seed_name in FLOORS else str(seed_path.with_suffix("")) if seed_name == "malformed" or seed_name in DERIVED else seed_name
            # A floor module compiles its seed's `rules` switches in (LIVING_RULES).
            rules = json.loads(seed_path.read_text()).get("rules", {})
            launch_env = dict(os.environ, LIVING_RULES=",".join(f"{k}={str(v).lower()}" for k, v in rules.items())) if seed_name in FLOORS else None
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
                floor_checks = create_floor(active_run, d, json.loads(seed_path.read_text())) if seed_name in FLOORS else []
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
