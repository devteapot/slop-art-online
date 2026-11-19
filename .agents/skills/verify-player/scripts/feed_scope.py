#!/usr/bin/env python3
"""A player in a scoped world (docs/FEED_SCOPING.md), on a `--seed cullet` run (its fires burn fuel).

The admin takes the world to stage 2 (`feed_scope_on`, `feed_scope_grace_s` 1). The player puts up a
hearth (`place_structure`) and, through its own reducers:
- sees it in `my_things` as out (`lit` false, no fuel or expiry field); feeds it peat (`human_act`
  feed) and sees it lit;
- looks it over (`human_act` inspect, the skill's name): `my_fuel_seen` holds the hours left and
  `my_experience` the line, as a mind is told;
- names a hearth beyond its sight and an id that does not exist: both are refused the same way
  (`my_act_outcomes`), so a hidden thing reads as an absent one.
A mind beside the hearth is sent it as "burning" with no hours; after its own `inspect` its pending
scene carries the fuel it found. Admin calls set the scene only. Writes `RUN/feed-player.json`.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
import verify as v  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    st = v.load(rid)
    db, player, owner = st["db"], st.get("token"), v.admin_token()
    if not player:
        ap.error("join the run's player first")
    out = v.run_dir(rid)
    checks = {}

    def check(name, ok, detail=None):
        checks[name] = {"passed": bool(ok), "detail": detail}
        print(("PASS " if ok else "FAIL ") + name, flush=True)

    def sql(query, token=player):
        code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
        if code != 200:
            return None
        res = json.loads(body)[-1]
        fields = [c["name"]["some"] for c in res["schema"]["elements"]]
        return [dict(zip(fields, r)) for r in res["rows"]]

    def call(reducer, args, token=owner, ok=True):
        code, body = v.http(f"/v1/database/{db}/call/{reducer}", args, token, timeout=90)
        if ok and code != 200:
            raise RuntimeError((reducer, code, body))
        return code, body

    def wait(pred, seconds=20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            got = pred()
            if got:
                return got
            call("human_move", [0.0, 0.0, False], player, ok=False)
            time.sleep(0.4)
        return None

    def thing(key):
        return next((r for r in sql("SELECT * FROM my_things") or [] if r["key"] == key), None)

    call("set_world_law", ["feed_scope_grace_s", "1"])
    call("set_world_law", ["feed_scope_on", "true"])
    check("stage 2", wait(lambda: (sql("SELECT * FROM feed_scope", None) or [{}])[0].get("stage") == 2, 30))
    me = sql("SELECT id FROM my_characters")[0]["id"]
    call("grant_items", [me, "peat", 4])
    call("grant_know_how", [me, "fire"], ok=False)
    call("place_structure", [me, "hearth"])
    hearth = max((r for r in sql(f"SELECT * FROM structure_held WHERE owner = {me}", owner) if r["kind"] == "hearth"), key=lambda r: r["id"])
    hk = 1 << 56 | hearth["id"]
    t = wait(lambda: thing(hk))
    check("the hearth is in my_things as out, with no fuel field", t is not None and t["lit"] is False and not {"lit_until_ms", "fuel"} & set(t), t)
    call("human_act", [json.dumps({"do": "feed", "target": {"id": hearth["id"]}, "item": "peat", "qty": 2})], player)
    t = wait(lambda: (lambda x: x if x and x["lit"] else None)(thing(hk)), 20)
    check("fed, it reads lit", t is not None, t)
    call("human_act", [json.dumps({"do": "inspect", "target": {"id": hearth["id"]}})], player)
    f = wait(lambda: [r for r in sql("SELECT * FROM my_fuel_seen") or [] if r["target"] == hearth["id"]], 20)
    check("inspect: my_fuel_seen holds the hours left", bool(f) and f[0]["left"] > 0, f)
    lines = [r["text"] for r in sql("SELECT * FROM my_experience") or [] if "look the hearth over" in r.get("text", "")]
    check("inspect: the player is told the fuel left", bool(lines), lines)

    # A hearth out of sight, and an id that is no thing at all.
    before = {c["id"] for c in sql("SELECT id FROM character", owner)}
    call("spawn_crowd", [2, True])
    x, mind = sorted(c["id"] for c in sql("SELECT id FROM character", owner) if c["id"] not in before)
    for who in (x, mind):
        call("set_behavior", [who, json.dumps({"wait": 600})])
    body = sql("SELECT * FROM my_body")[0]
    far = None
    for dx, dy in ((90, 0), (-90, 0), (0, 90), (0, -90), (70, 70), (-70, -70)):
        if call("place_at", [x, body["x"] + dx, body["y"] + dy], ok=False)[0] == 200:
            far = (dx, dy)
            break
    call("place_structure", [x, "hearth"])
    hidden = max((r for r in sql(f"SELECT * FROM structure_held WHERE owner = {x}", owner) if r["kind"] == "hearth"), key=lambda r: r["id"])
    wait(lambda: True, 1.5)
    check("the far hearth is not in my_things", thing(1 << 56 | hidden["id"]) is None, far)

    def outcome(target):
        n = len(sql("SELECT * FROM my_act_outcomes") or [])
        code, body = call("human_act", [json.dumps({"do": "inspect", "target": {"id": target}})], player, ok=False)
        rows = wait(lambda: (lambda r: r[n:] if len(r) > n else None)(sql("SELECT * FROM my_act_outcomes") or []), 15) or []
        return {"http": code, "body": body[-200:], "outcomes": [{k: r[k] for k in ("ok", "skill", "code")} for r in rows]}

    a, b = outcome(hidden["id"]), outcome(987654321)
    check("a hidden hearth and an absent id are refused alike", a["http"] == b["http"] and a["outcomes"] == b["outcomes"] and not any(o["ok"] for o in a["outcomes"]), {"hidden": a, "absent": b})

    # A mind's scene: lit or out only, the fuel after its own look.
    call("place_at", [mind, hearth["x"] + 1.0, hearth["y"]])

    def scene(marker):
        call("set_behavior", [mind, json.dumps({"think": marker})])
        row = wait(lambda: [r for r in sql(f"SELECT reason, scene FROM deliberation WHERE actor = {mind}", owner) if marker in r["reason"]], 70)
        entry = next((e for e in json.loads(row[0]["scene"]).get("structures", []) if e.get("id") == hearth["id"]), None) if row else None
        call("set_behavior", [mind, json.dumps({"wait": 600})])
        return entry

    e = scene("I finished my plan. Verify fuel unseen.")
    check("the mind's scene: burning, no hours, before it looks", e is not None and e.get("state") == "burning" and "fuel" not in e, e)
    call("mind_act", [mind, [json.dumps({"do": "inspect", "target": {"id": hearth["id"]}})], "verify-player"])
    wait(lambda: sql(f"SELECT * FROM fuel_seen WHERE observer = {mind}", owner), 20)
    e = scene("I finished my plan. Verify fuel seen.")
    check("the mind's scene: the fuel it found when it looked", e is not None and "hours" in e.get("fuel", ""), e)
    (out / "feed-player.json").write_text(json.dumps(checks, indent=2) + "\n")
    passed = sum(c["passed"] for c in checks.values())
    print(f"{passed}/{len(checks)} checks passed", flush=True)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
