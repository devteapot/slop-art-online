#!/usr/bin/env python3
"""Exercise cover through a scratch authority, including the pending mind scene."""
import argparse
import json
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root / ".agents/skills/verify/scripts"))
import verify as v

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", required=True)
parser.add_argument("--fixture", required=True, type=Path)
args = parser.parse_args()
run = args.run
if not run.startswith(("core-cover-", "client-cover-")) or v.CONTAINER == v.SHARED:
    parser.error("use a core-cover-* or client-cover-* run on your own scratch server")
fixture = json.loads(args.fixture.read_text())
st = v.load(run)
db = st["db"]
owner = v.admin_token()
player = st["token"]
out = v.run_dir(run) / "cover-proof.jsonl"

def save(check, ok, data=None):
    with out.open("a") as f:
        f.write(json.dumps(dict(check=check, passed=bool(ok), data=data)) + "\n")
    if not ok:
        raise AssertionError((check, data))

def sql(query, token=owner):
    code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError((query, code, body))
    res = json.loads(body)[0]
    fields = [c["name"]["some"] for c in res["schema"]["elements"]]
    return [dict(zip(fields, r)) for r in res["rows"]]

def call(reducer, args, token=owner, check=True):
    code, body = v.http(f"/v1/database/{db}/call/{reducer}", args, token, timeout=90)
    if check and code != 200:
        raise RuntimeError((reducer, code, body))
    return code == 200

def visible():
    return any(r["id"] == target for r in sql("SELECT id FROM seen_characters", player))

def settle():
    for _ in range(4):
        call("human_move", [0.0, 0.0, False], player, check=False)
        time.sleep(0.2)

r = sql("SELECT * FROM cover_law", player)
save("public singleton exact fields and off default", r == [
    {"id":0, "cover_sight_on": False, "cover_eye_height_m":1.6, "cover_brush_on":False,
     "cover_brush_min_fill":0.6, "cover_cliff_step_m":2.0}], r)
for table in ("cover_ground", "attention"):
    status, _ = v.http(f"/v1/database/{db}/sql",f"SELECT * FROM {table}",player,raw=True)
    save(f"non-admin cannot select {table}", status != 200, status)

call("set_world_law", ["cover_brush_on","true"])

actor = sql("SELECT id FROM my_characters",player)[0]["id"]
code, body = v.http("/v1/identity", {})
assert code == 200
target_token = json.loads(body)["token"]
call("join", ["Cover Screen Target"], target_token)
target = sql("SELECT id FROM my_characters",target_token)[0]["id"]
lines = sql("SELECT id FROM my_experience WHERE kind = 'saw'",player)
for enabled in (False, True, False):
    call("set_world_law", ["cover_sight_on",json.dumps(enabled)])
    save("law projected after admin change", sql("SELECT cover_sight_on FROM cover_law",player) ==
         [{"cover_sight_on": enabled}])
    for name, pair in fixture.items():
        call("place_at", [actor, *pair["from"]])
        call("place_at", [target, *pair["to"]])
        settle()
        found = visible()
        save(f"{name}, cover {'on' if enabled else 'off'}", found == (not enabled or name == "overlook"),
             dict(pair=pair, seen=found))

save("cover transitions add no player sight lines",
     sql("SELECT id FROM my_experience WHERE kind = 'saw'",player) == lines)
call("set_world_law", ["cover_sight_on","true"])
call("grant_items", [actor,"bow",1])
call("grant_items", [actor,"arrow",6])
for feature, passes in (("trunk",False),("brush",True)):
    pair = fixture[feature]
    call("place_at", [actor, *pair["from"]])
    call("place_at", [target, *pair["to"]])
    settle()
    before = sql(f"SELECT hp FROM vitals WHERE id = {target}")[0]["hp"]
    call("use_skill", ["bowshot",0,*pair["to"]], player)
    time.sleep(1.4)
    after = sql(f"SELECT hp FROM vitals WHERE id = {target}")[0]["hp"]
    save(feature + " arrow collision", (after < before-0.01) == passes, {"before":before,"after":after})
    time.sleep(1.0)

# Compare what the authority prepares for a mind by inspecting its pending scene. Do not
# start a provider or consume the request.
for enabled in (False, True):
    call("set_world_law", ["cover_sight_on", json.dumps(enabled)])
    current = max(x["id"] for x in sql("SELECT id FROM character"))
    call("spawn_crowd", [1,True])
    eye = sql(f"SELECT id FROM character WHERE id > {current}")[0]["id"]
    pair = fixture["trunk"]
    call("place_at", [eye,*pair["from"]])
    call("place_at", [target,*pair["to"]])
    marker = f"I finished my plan. Verify cover {enabled}."
    for attempt in range(3):
        call("set_behavior", [eye,json.dumps({"think":marker})])
        deadline = time.monotonic()+65
        while time.monotonic() < deadline:
            pending = sql(f"SELECT reason, scene FROM deliberation WHERE actor = {eye}")
            if pending and marker in pending[0]["reason"]:
                break
            time.sleep(0.5)
        else:
            continue
        break
    else:
        raise AssertionError("no mind request from cover fixture")
    observed = [c["id"] for c in json.loads(pending[0]["scene"])["creatures"]]
    save("authority mind scene cover " + str(enabled), (target in observed) != enabled, observed)
call("set_world_law", ["cover_sight_on","false"])
