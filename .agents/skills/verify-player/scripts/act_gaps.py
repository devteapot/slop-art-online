#!/usr/bin/env python3
"""A player's replacing command and its three gaps, closed (docs/INPUT_LATENCY.md, "Act
replacement gaps"), each beside its law off as a control. verify-core `act_gaps` drives the same
through a mind's `mind_act`.

1. `act_replace_checks`: a command refused as it would start (eat cooked meat the character does
   not carry) leaves the walk under way running, and the refusal reaches the player
   (`my_act_outcomes`, `my_experience`); off, the walk is broken off first and the body idles.
2. `act_input_cost`: 40 `human_act` calls sent at once are cut at the input bucket the player's
   moves and skill uses spend from (`input_burst` 15 plus `input_hz` 30/s refill during the
   burst); the rest are refused "too many inputs"; a second later a command goes through; off,
   all 40 go through.
3. `act_turned_back`: seven walks each given up within 3 s for one the other way; the sixth is
   told in `my_experience`, "You keep turning back and forth"; off, nothing is told.
4. `act_same_continues` (off as shipped): the same walk again while it runs goes on; off, it
   starts over.

    act_gaps.py --run RUN

Needs `verify.py launch --run RUN` (any seed with an open row of 30 tiles). Admin `place_at` and
`set_world_law` set the scene; admin SQL reads `activity` (developer truth); the player acts and
reads its own views with its own identity. Every law is set back at the end and the player is put back where it stood. Writes
`RUN/act_gaps.json`. Python standard library only.
"""

import argparse
import concurrent.futures
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

ACT = 65534  # act::ACT
LAWS = (("act_replace_checks", True), ("act_input_cost", True), ("act_turned_back", True), ("act_same_continues", False))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    st = V.load(a.run)
    db = st["db"]
    admin = V.admin_token()
    if not st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        st["token"], st["identity"] = j["token"], j["identity"]
        V.save(st)

    def sql(q, token):
        code, body = V.http(f"/v1/database/{db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(reducer, args, token=None, quiet=False):
        code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, token or st["token"])
        if not quiet:
            V.log(st, f"call {reducer}{json.dumps(args)} as {'admin' if token == admin else 'player'} -> {code} {body.strip()}", sys.stderr)
        return code, body

    def law(name, value):
        code, body = call("set_world_law", [name, json.dumps(value)], admin)
        if code != 200:
            raise RuntimeError(f"set_world_law {name}: {code} {body}")

    mine = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    if not mine:
        call("join", ["Gaps"])
        mine = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    me = mine[0]["id"]
    home = sql(f"SELECT x, y FROM body WHERE id = {me}", admin)[0]
    results = []

    def check(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + f": {detail}", flush=True)

    # An open row of 30 tiles (as verify-core's `open_line`).
    w = sql("SELECT width, height FROM world", admin)[0]
    W, H = w["width"], w["height"]
    tiles = bytearray(W * H)
    for row in sql("SELECT * FROM terrain_chunk", admin):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    line = next(([(x + i + .5, y + .5) for i in range(30)] for y in range(8, H - 8, 3) for x in range(8, W - 38, 2)
                 if all(walk(x + i, y + d) for i in range(30) for d in (-1, 0, 1))), None)
    if not line:
        raise RuntimeError("no open row of 30 tiles on this map")
    start, far, back = line[0], line[-1], line[14]
    goto = lambda p: json.dumps({"do": "goto", "target": {"at": [p[0], p[1]]}})
    doing = lambda: (sql(f"SELECT skill, node, started_ms, label FROM activity WHERE id = {me}", admin) or [None])[0]
    lines = lambda: sql("SELECT id, kind, text FROM my_experience", st["token"])
    outcomes = lambda: sql("SELECT * FROM my_act_outcomes", st["token"])

    def wait_for(fn, secs=10.0):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            r = fn()
            if r:
                return r
            time.sleep(0.25)
        return fn()

    def walking_far():
        call("place_at", [me, *start], admin)
        time.sleep(0.5)
        call("human_act", [goto(far)])
        return wait_for(lambda: (d := doing()) and d["skill"] == "goto" and d["node"] == ACT and d)

    try:
        # 1. A refused replacement.
        for checks in (True, False):
            law("act_replace_checks", checks)
            first = walking_far()
            seen = {r["id"] for r in lines()}
            rows = {r["id"] for r in outcomes()}
            time.sleep(0.5)
            code, body = call("human_act", [json.dumps({"do": {"skill": "eat", "item": "cooked_meat"}})])
            now = doing()
            told = wait_for(lambda: [r["text"] for r in lines() if r["id"] not in seen and r["kind"] == "act" and "cooked_meat" in r["text"]], 5.0)
            new_rows = wait_for(lambda: [r for r in outcomes() if r["id"] not in rows and r["skill"] == "eat"], 5.0)
            if checks:
                check("checks on: a refused command leaves the walk under way running", code == 200 and first and now and now["started_ms"] == first["started_ms"] and now["skill"] == "goto", {"first": first, "now": now})
            else:
                check("checks off (control): the walk is broken off before the refusal, the body idle", first and (not now or now["started_ms"] != first["started_ms"]), {"first": first, "now": now})
            check(f"checks {'on' if checks else 'off'}: the refusal reaches the player (my_experience and my_act_outcomes)", told and new_rows and not new_rows[-1]["ok"], {"told": told, "rows": new_rows})
        law("act_replace_checks", True)

        # 2. The input bucket.
        for cost in (True, False):
            law("act_input_cost", cost)
            call("place_at", [me, *start], admin)
            time.sleep(1.5)
            t0 = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(40) as pool:
                res = list(pool.map(lambda _: call("human_act", [goto(far)], quiet=True), range(40)))
            secs = time.monotonic() - t0
            ok = sum(1 for c, _ in res if c == 200)
            refused = [b.strip() for c, b in res if c != 200]
            V.log(st, f"burst of 40 human_act, act_input_cost={cost}: {ok} accepted, {len(refused)} refused in {secs:.3f} s: {sorted(set(refused))[:3]}", sys.stderr)
            detail = {"accepted": ok, "refused": len(refused), "burst_s": round(secs, 3), "refusals": sorted(set(refused))[:3]}
            if cost:
                check("input cost on: 40 commands at once are cut at the bucket (15 plus 30/s refill), the rest refused 'too many inputs'",
                      15 <= ok <= 15 + 30 * secs + 1 and refused and all("too many inputs" in b for b in refused), detail)
                time.sleep(1.0)
                code, body = call("human_act", [goto(back)])
                check("input cost on: a second later a command goes through again", code == 200, f"{code} {body.strip()[:120]}")
            else:
                check("input cost off (control): all 40 go through", ok == 40 and not refused, detail)
        law("act_input_cost", True)

        # 3. Turning back and forth (off first: nothing is counted, so the window starts clean).
        for counted in (False, True):
            law("act_turned_back", counted)
            call("place_at", [me, *back], admin)
            time.sleep(0.5)
            seen = {r["id"] for r in lines()}
            for i in range(7):
                call("human_act", [goto(far if i % 2 == 0 else start)])
                time.sleep(0.4)
            time.sleep(0.5)
            dither = [r["text"] for r in lines() if r["id"] not in seen and "turning back and forth" in r["text"]]
            if counted:
                check("turned back on: seven walks given up for one the other way are noticed and told once", len(dither) == 1, dither)
            else:
                check("turned back off (control): nothing is told", not dither, dither)

        # 4. The same command again.
        for same in (True, False):
            law("act_same_continues", same)
            first = walking_far()
            time.sleep(1.0)
            call("human_act", [goto(far)])
            now = doing()
            if same:
                check("same continues on: the same walk again goes on (its start unchanged)", first and now and now["started_ms"] == first["started_ms"], {"first": first, "now": now})
            else:
                check("same continues off (as shipped): the same walk again starts over", first and now and now["started_ms"] != first["started_ms"] and now["skill"] == "goto", {"first": first, "now": now})
    finally:
        for name, value in LAWS:
            call("set_world_law", [name, json.dumps(value)], admin)
        call("human_act", [json.dumps({"wait": 4})])
        # Back where it stood, so later scripts on this world find the player where they expect.
        call("place_at", [me, home["x"], home["y"]], admin)

    out = V.run_dir(a.run) / "act_gaps.json"
    out.write_text(json.dumps({"character": me, "line": [start, far], "results": results}, indent=2) + "\n")
    print(f"{sum(r['ok'] for r in results)} of {len(results)} checks pass; {out}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
