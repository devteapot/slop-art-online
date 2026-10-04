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
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / ".local/living/verify"
SEEDS = ("realm", "valley", "authored-test", "aske-coast", "stage3-village")
TABLES = ("world", "terrain_chunk", "character", "background", "community",
          "membership", "structure", "artifact", "resource_node", "genome", "body", "inventory")
HARNESS = ROOT / ".agents/skills/verify/scripts/verify.py"
CONTAINER = "sao-living_spacetimedb_1"


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


def authored_copy(directory):
    living = directory / "source/living"
    (living / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "living/tools/author_world.py", living / "tools/author_world.py")
    shutil.copytree(ROOT / "living/seeds/worlds/aske-coast", living / "seeds/worlds/aske-coast")
    return living


def harness(action, run, evidence, *args):
    return command([sys.executable, str(HARNESS), action, "--run", run, *map(str, args)],
                   evidence, cwd=ROOT, timeout=900)


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
        with urllib.request.urlopen(f"http://127.0.0.1:3300/v1/database/{database}/identity", timeout=30) as response:
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
        equal(f"{t['name']} memberships", sorted(r["member"] for r in rows["membership"] if r["community"] == com.get("id")), sorted(ids))
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
        equal(f"{kind} count including dead founders", sum(c["kind"] == kind for c in chars.values()), count)
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
    return checks


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


def authored(directory, living):
    wrapper = directory / "compile_offline.py"
    wrapper.write_text('''import json, pathlib, runpy, socket, sys, urllib.request
attempts = []
def blocked(*args, **kwargs):
    attempts.append("network attempt")
    raise RuntimeError("compile-only attempted network access")
socket.socket.connect = blocked
socket.create_connection = blocked
urllib.request.urlopen = blocked
sys.argv = [sys.argv[1], "aske-coast", "--compile-only"]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    pathlib.Path(__file__).with_name("network.json").write_text(json.dumps(attempts))
''')
    code = command([sys.executable, str(wrapper), str(living / "tools/author_world.py")], directory / "compile.log", timeout=120)
    actual = living / "seeds/aske-coast.json"
    original = ROOT / "living/seeds/aske-coast.json"
    shutil.copy2(actual, directory / "compiled-aske-coast.json")
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
        if args.feature in ("all", "guards"):
            code = command(["cargo", "test", "-p", "living-authority", "--lib", "--target-dir", str(target), "seed::tests::", "--", "--nocapture"], directory / "seed-tests.log", cwd=ROOT / "living", env=dict(os.environ, LIVING_SEED="authored-test"), timeout=900)
            results["seed tests"] = {"pass": code == 0}
        seeds = list(SEEDS) + ["realm"] if args.feature in ("all", "worlds") else []
        if args.feature in ("all", "guards"):
            malformed = json.loads((ROOT / "living/seeds/authored-test.json").read_text())
            del malformed["animals"]
            write(directory / "malformed.json", malformed)
            seeds.append("malformed")
        for index, seed_name in enumerate(seeds):
            active_run = f"{args.run}-{index}-{seed_name}"
            d = BASE / active_run
            d.mkdir(parents=True, exist_ok=False)
            seed_path = directory / "malformed.json" if seed_name == "malformed" else ROOT / f"living/seeds/{seed_name}.json"
            write(d / "seed.json", json.loads(seed_path.read_text()))
            database = "verify-" + active_run
            seed_arg = str(seed_path.with_suffix("")) if seed_name == "malformed" else seed_name
            container = subprocess.run(["docker", "ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Status}}"], capture_output=True, text=True, check=True, timeout=30)
            if not container.stdout.strip().startswith("Up"):
                raise RuntimeError("existing SpacetimeDB container is down; start it before running this skill")
            try:
                started = datetime.now(timezone.utc).isoformat()
                launch_code = harness("launch", active_run, d / "launch.log", "--seed", seed_arg, "--target-dir", target)
                ended = datetime.now(timezone.utc).isoformat()
                if seed_name == "malformed":
                    identity_status, identity = database_identity(database)
                    built = target / "wasm32-unknown-unknown/release/living_authority.wasm"
                    state = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
                    publication = {"started": started, "ended": ended, "identity_status": identity_status, "database_identity": identity, "wasm_sha256": hashlib.sha256(built.read_bytes()).hexdigest() if built.exists() else None, "publication_attempted": state.get("published", False)}
                    write(d / "publication.json", publication)
                    server = subprocess.run(["docker", "logs", "--since", started, "--until", ended, CONTAINER], capture_output=True, text=True, timeout=30)
                    records = re.split(r"(?=\d{4}-\d{2}-\d{2}T)", server.stdout + server.stderr)
                    launch_key = f"launching module db={identity} " if identity_status == 200 else "NO_CORRELATED_LAUNCH"
                    selected = [r for r in records if launch_key in r or ("reducer \"init\" runtime error" in r and "::seed::seed" in r) or ("Frame #" in r and ("::seed::seed" in r or "rust_panic" in r or "__rust_start_panic" in r))]
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
                              "known_issue": {"label": "KNOWN ISSUE", "reference": "docs/LIVING_HANDOFF.md, Still open", "source": "living/authority/src/seed.rs:444", "description": "initializer panics and publication does not name the missing field", "readable_error_asserted": False},
                              "launch_exit_code": launch_code, "panic_reported": "::seed::seed" in trace and "rust_panic" in trace,
                              "missing_field_diagnostic_visible": readable, "database_launch_correlated": launch_key in trace}
                    write(d / "guards.json", report)
                    results["malformed seed"] = report
                    print(f"{report['rejection']} malformed seed rejection; readability is not asserted (KNOWN ISSUE, docs/LIVING_HANDOFF.md, Still open)", flush=True)
                    continue
                if launch_code:
                    raise RuntimeError(f"launch failed; read {d}/launch.log")
                if harness("doctor", active_run, d / "doctor.log"):
                    raise RuntimeError(f"doctor failed; read {d}/doctor.log")
                if harness("call", active_run, d / "pause.log", "set_paused", "[true]", "--as-admin"):
                    raise RuntimeError(f"pause failed; read {d}/pause.log")
                rows = snapshot(active_run, TABLES)
                public_tables = re.findall(r"#\[spacetimedb::table\(accessor = (\w+), public\)\]", (ROOT / "living/authority/src/tables.rs").read_text())
                rows.update(snapshot(active_run, [t for t in public_tables if t not in rows]))
                checks = check_seed(json.loads((d / "seed.json").read_text()), rows)
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
    args = parser.parse_args()
    return suite(args)


if __name__ == "__main__":
    sys.exit(main())
