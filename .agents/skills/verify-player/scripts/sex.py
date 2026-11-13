#!/usr/bin/env python3
"""A player's body sex (sex-1, docs/LIVING_CORE.md "Body sex"): `join` keeps working and the world
picks; `join_as(name, sex)` chooses "f" or "m" and refuses anything else; the player is told its
own sex through `my_sex` and never reads the private `sex` table.

    sex.py --run player-...      (any seed; with `looks` in force, e.g. --seed plan-test, the
                                  players' looks are also checked against their sex)

Steps, each player a fresh identity of its own (POST /v1/identity):
- the run's player joins with `join`: its `sex` row (admin SQL; the table is private) is the world's
  pick, recomputed here (`living_rules::sex::pick`: splitmix64((seed ^ SALT) ^ id * 0x9E37…) >> 11
  over 2^53 against `female_share()` 0.5), and `my_sex` (as the player) says it;
- `join_as` with "f" and with "M": rows 1 and 2, `my_sex` "female" and "male";
- `join_as` with "x" and "": refused with `sex must be "f" or "m"`, and that identity has no
  character afterwards (nothing was made);
- with looks: each player's look entry shows its sex (its lines' forms), and its own
  `seen_characters` row carries that entry's line;
- as a player, SQL on `sex` is refused (private);
- a second `join_as` from a player who plays is refused like a second `join`.
Writes `RUN/player_sex.json`. Python standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
M = (1 << 64) - 1
SALT = 0x5E70F00D0B0D1E55


def splitmix64(x):
    z = (x + 0x9E3779B97F4A7C15) & M
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M
    return z ^ (z >> 31)


def sex_pick(seed, cid, share=0.5):
    x = splitmix64((seed ^ SALT) ^ ((cid * 0x9E3779B97F4A7C15) & M))
    return 1 if (x >> 11) / float(1 << 53) < share else 2


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r


def sql(rid, query, *flags):
    out = run(V, "sql", "--run", rid, query, *flags).stdout
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def http(path, body=None, token=None, raw=False):
    data = body.encode() if raw else json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(URL + path, data=data, method="POST")
    if not raw:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def rows(db, query, token):
    code, body = http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        return code, body
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return code, [dict(zip(names, r)) for r in res["rows"]]


def identity():
    code, body = http("/v1/identity", {})
    if code != 200:
        raise RuntimeError(f"identity: {code} {body[:200]}")
    return json.loads(body)["token"]


def entry_sex(looks, person):
    found = {{"woman": "f", "girl": "f", "man": "m", "boy": "m"}.get((looks["words"].get(k, {}).get("form") or "").strip().split(" ")[-1]) for k in looks["people"].get(person, {}).values()} - {None}
    return found.pop() if len(found) == 1 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    rid, out, checks, calls = a.run, ROOT / ".local/living/verify" / a.run, {}, []
    state = json.loads((out / "state.json").read_text())
    db = state["db"]
    seed_file = ROOT / "living/seeds" / f"{state.get('seed', 'world')}.json"
    looks = json.loads(seed_file.read_text()).get("looks") if seed_file.exists() else None
    world = sql(rid, "SELECT seed FROM world")[0]
    wseed = int(world["seed"])

    def join_as(token, name, sex):
        code, body = http(f"/v1/database/{db}/call/join_as", [name, sex], token)
        calls.append({"reducer": "join_as", "args": [name, sex], "status": code, "body": body[:200]})
        return code, body

    def mine(token):
        code, r = rows(db, "SELECT * FROM my_characters", token)
        return r if code == 200 else []

    def my_sex(token):
        code, r = rows(db, "SELECT * FROM my_sex", token)
        return r if code == 200 else [{"error": r}]

    # `join`: the world picks.
    run(V, "player", "--run", rid, "join", "SexPlain", check=False)
    plain = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
    srow = {r["id"]: r["sex"] for r in sql(rid, f"SELECT * FROM sex WHERE id = {plain}")}
    pick = sex_pick(wseed, plain)
    checks["join: the player's sex row is the world's pick for the world seed and its id"] = srow.get(plain) == pick
    checks["join: my_sex tells the player its own sex"] = [r.get("sex") for r in sql(rid, "SELECT * FROM my_sex", "--as-player")] == [{1: "female", 2: "male"}[pick]]
    refused = run(V, "call", "--run", rid, "join_as", json.dumps(["Again", "f"]), "--as-player", "--expect-refusal", "you already have a living character", check=False)
    checks["join_as from someone who already plays is refused like join"] = refused.returncode == 0
    code, body = rows(db, "SELECT * FROM sex", state.get("token"))
    checks["as a player, SQL on the sex table is refused (private)"] = code != 200 and "private" in str(body).lower()

    # join_as: chosen.
    players = {"SexF": ("f", 1, "female"), "SexM": ("M", 2, "male")}
    made = {}
    for name, (given, code_want, word) in players.items():
        token = identity()
        status, body = join_as(token, name, given)
        me = mine(token)
        made[name] = (token, me[0]["id"] if me else None)
        row = sql(rid, f"SELECT * FROM sex WHERE id = {made[name][1]}") if made[name][1] else []
        checks[f"join_as {given!r}: joins, sex row {code_want}, my_sex {word!r}"] = status == 200 and bool(me) and [r["sex"] for r in row] == [code_want] and [r.get("sex") for r in my_sex(token)] == [word]
    for bad in ("x", ""):
        token = identity()
        status, body = join_as(token, "SexBad", bad)
        checks[f"join_as {bad!r} is refused with its reason, and nothing is made"] = status != 200 and 'sex must be "f" or "m"' in body and not mine(token)

    # With looks: each player's look shows its sex.
    if looks:
        everyone = {"SexPlain": plain, **{n: i for n, (_, i) in made.items()}}
        by_id = {r["id"]: r for r in sql(rid, "SELECT id, person, line FROM look")}
        sexes = {r["id"]: r["sex"] for r in sql(rid, "SELECT * FROM sex")}
        shown = {n: (entry_sex(looks, by_id[i]["person"]) if i in by_id else None, {1: "f", 2: "m"}.get(sexes.get(i))) for n, i in everyone.items()}
        checks["with looks: every player's look entry shows its sex"] = all(a == b and a for a, b in shown.values())
        own = [r for r in sql(rid, "SELECT * FROM seen_characters", "--as-player") if r.get("own")]
        checks["with looks: the player's own seen_characters row carries its line"] = bool(own) and own[0].get("look") == by_id.get(plain, {}).get("line")
    result = {"world_seed": wseed, "plain": {"id": plain, "sex": srow.get(plain), "pick": pick}, "made": {n: i for n, (_, i) in made.items()}, "calls": calls, "checks": checks}
    (out / "player_sex.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
