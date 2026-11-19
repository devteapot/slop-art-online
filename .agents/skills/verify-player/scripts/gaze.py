#!/usr/bin/env python3
"""Drive gaze through real player and mind reducers on a fresh Cullet verify world."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verify/scripts"))
import verify as v

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--run", required=True)
a = p.parse_args()
if not a.run.startswith("player-gaze-") or v.CONTAINER == v.SHARED:
    p.error("use a fresh player-gaze-* Cullet world on the trial server")
st = v.load(a.run)
if st.get("seed") != "cullet" or st.get("server_url") != v.URL:
    p.error("launch and doctor this run as Cullet before driving it")
db = st["db"]
owner = v.admin_token()
player = st["token"]
out = v.run_dir(a.run) / "gaze-proof.jsonl"


def record(name, ok, data=None):
    with out.open("a") as f:
        f.write(json.dumps({"check": name, "passed": bool(ok), "data": data}) + "\n")
    assert ok, (name, data)


def call(reducer, args, token=owner):
    return v.http(f"/v1/database/{db}/call/{reducer}", args, token, timeout=90)


def do(reducer, args, token=owner):
    code, body = call(reducer, args, token)
    assert code == 200, (reducer, code, body)
    return body


def sql(query, token=owner):
    code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
    assert code == 200, (query, code, body)
    res = json.loads(body)[0]
    fields = [c["name"]["some"] for c in res["schema"]["elements"]]
    return [dict(zip(fields, r)) for r in res["rows"]]


def until(read, desc, limit=10):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(desc)


def gaze(token, band):
    do("human_gaze", [band], token)


def attention(id):
    return sql(f"SELECT * FROM attention WHERE id = {id}")


def applied(token, band):
    until(lambda: any(r["band"] == band for r in sql("SELECT * FROM my_senses_v_2", token)), f"band {band} never applied")
    return sql("SELECT * FROM my_senses_v_2", token)[0]


def visible():
    return target in {r["id"] for r in sql("SELECT id FROM seen_characters", player)}


def place(id, xy):
    do("place_at", [id, *xy])


def sight_setup(eye, other, facing=(1, 0)):
    place(actor, eye)
    place(target, other)
    do("human_face", list(facing), player)
    time.sleep(0.85)


actor = sql("SELECT id FROM my_characters", player)[0]["id"]
# Cullet ships gaze, facing sight and cover on (2026-11-19); the fixture starts from them off.
for name in ("gaze_on", "cover_sight_on", "fov_on"):
    do("set_world_law", [name, "false"])
time.sleep(0.4)
status, body = call("human_gaze", [1], player)
record("disabled gaze refused", status != 200 and "disabled" in body, status)
record("disabled gaze creates neither row", not attention(actor) and not sql("SELECT * FROM my_senses_v_2", player))
for table in ("attention", "applied_gaze"):
    status, _ = v.http(f"/v1/database/{db}/sql", "SELECT * FROM " + table, player, raw=True)
    record(table + " is private", status != 200, status)

status, created = v.http("/v1/identity", {})
assert status == 200
other = json.loads(created)["token"]
do("join", ["Gaze Target"], other)
target = sql("SELECT id FROM my_characters", other)[0]["id"]
do("set_world_law", ["fov_on", "true"])
time.sleep(0.4)
before = sql("SELECT * FROM my_senses", player)[0]
do("set_world_law", ["gaze_on", "true"])
middle = applied(player, 0)
fields = ("sight", "hearing", "field", "focal_deg", "side_deg", "side_share", "near_m", "margin_deg")
after = sql("SELECT * FROM my_senses", player)[0]
record("enabled Middle matches previous directional field", all(before[f] == after[f] for f in fields), {f: after[f] for f in fields})
gaze(player, 0)
record("default Middle repeat creates no attention", not attention(actor))
status, body = call("human_gaze", [255], player)
record("out-of-range band refused", status != 200 and "invalid gaze band" in body, status)
gaze(player, 1)
status, body = call("human_gaze", [2], player)
record("change within 250 ms refused", status != 200 and "250 ms" in body, status)
row = attention(actor)
gaze(player, 1)
record("accepted Far and repeat leaves timestamp intact", len(row) == 1 and row[0]["band"] == 1 and attention(actor) == row, row)
far = applied(player, 1)
record("second player sees only their own Middle", applied(other, 0)["id"] == target and far["id"] == actor)
record("anonymous view sees no rows", not sql("SELECT * FROM my_senses_v_2", None))
do("set_paused", [True])
try:
    gaze(other, 2)
    current = sql("SELECT * FROM my_senses_v_2", other)[0]
    record("a gaze request leaves the applied field unchanged between sweeps",
           current["band"] == 0 and attention(target)[0]["band"] == 2)
finally:
    do("set_paused", [False])
applied(other, 2)

if probe := os.environ.get("GAZE_SDK_PROBE"):
    def subscribe(token, *queries):
        req = {"uri": v.URL, "db": db, "queries": queries, "token": token, "seconds": 0}
        result = subprocess.run([probe], input=json.dumps(req), capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)
    for token, own, band in [(player, actor, 1), (other, target, 2)]:
        snapshot = subscribe(token, "SELECT * FROM my_senses_v_2")
        rows = snapshot["initial"]["perception"]["my_senses_v_2"]
        record(f"SDK subscription receives only owner's band {band}",
               len(rows) == 1 and rows[0]["id"] == own and rows[0]["band"] == band, rows)
    for table in ("attention", "applied_gaze"):
        denied = subscribe(player, f"SELECT * FROM {table}")
        record(f"SDK cannot subscribe to {table}", denied["status"] == "rejected" and bool(denied["error"]), denied["error"])
time.sleep(0.26)
gaze(player, 2)
near = applied(player, 2)
record("effective bounds ordered", near["ceiling"] < middle["ceiling"] < far["ceiling"])
record("full-day Near gets scaled ground entitlement", abs(near["ground"] - 14.4) < 0.01, near["ground"])

# The authored trunk fixture has line of sight when cover is off.
time.sleep(0.30)
gaze(player, 1)
sight_setup((781.5, 457.5), (785.5, 457.5))
record("Far sees target through control ray", visible())
do("set_world_law", ["cover_sight_on", "true"])
time.sleep(0.45)
record("Far still loses target behind the authored trunk", not visible())
do("set_world_law", ["cover_sight_on", "false"])

# Pick a clear range test in the open land beyond town. A Middle miss followed by a Far hit
# at the same position proves the ray is clear and the distance band is the reason.
cases = [
    ((781.5, 457.5), (837.5, 457.5)),
    ((781.5, 457.5), (725.5, 457.5)),
    ((849.5, 613.5), (905.5, 613.5)),
    ((390.5, 291.5), (446.5, 291.5)),
]
for eye, other_xy in cases:
    direction = (1 if other_xy[0] > eye[0] else -1, 0)
    gaze(player, 0)
    sight_setup(eye, other_xy, direction)
    mid_visible = visible()
    gaze(player, 1)
    time.sleep(0.35)
    if not mid_visible and visible():
        record("Far acquires a distant target outside Middle reach", True, [eye, other_xy])
        break
else:
    raise AssertionError("no clear long ray in range fixtures")

# 90 degrees off facing lies outside Far and in Near's full cone.
for eye, _ in cases:
    gaze(player, 1)
    sight_setup(eye, (eye[0], eye[1] + 12))
    far_visible = visible()
    gaze(player, 2)
    time.sleep(0.35)
    if not far_visible and visible():
        record("Near acquires a flank target outside Far field", True, eye)
        break
else:
    raise AssertionError("no clear flank ray in field fixtures")

# Twilight leaves a torch visible in Far's side field even when the glow cap is
# less than Far's full forward range.
installed = sql("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
twilight, changed = re.subn(r"^fn daylight\(hour\) \{\n.*?^\}", "fn daylight(hour) { 0.95 }", installed,
                            flags=re.MULTILINE | re.DOTALL)
assert changed == 1, "expected one daylight function in the fixture"
do("install_script", [twilight])
try:
    gaze(player, 1)
    sight_setup((781.5, 457.5), (802.5, 482.5))
    record("Far does not acquire an unlit side target beyond peripheral reach", not visible())
    do("grant_items", [target, "torch", 1])
    until(visible, "Far did not acquire the lit side target")
    record("Far acquires the same side target by its twilight torch", True)
finally:
    do("install_script", [installed])

previous = max(r["id"] for r in sql("SELECT id FROM character"))
do("spawn_crowd", [1, True])
mind = sql(f"SELECT id FROM character WHERE id > {previous}")[0]["id"]
place(mind, (781.5, 457.5))
bad = json.dumps({"do": "gaze", "band": "invalid"})
far_act = json.dumps({"do": "gaze", "band": "far"})
near_act = json.dumps({"do": "gaze", "band": "near"})
status, _ = call("mind_act", [mind, [far_act], "gaze-proof"], player)
record("other identity cannot change mind's attention", status != 200 and not attention(mind))
do("set_behavior", [mind, json.dumps({"wait": 5})])
brain = sql(f"SELECT revision FROM mind_state WHERE id = {mind}")
do("mind_act", [mind, [bad, far_act, far_act, near_act], "gaze-proof"])
record("mind accepts Far, repeats it and rate-limits Near in the same transaction", attention(mind)[0]["band"] == 1)
time.sleep(0.26)
status, body = call("mind_act_checked", [mind, [near_act, far_act, bad], "gaze-proof"])
record("checked mind act returns rate and input refusals", status == 200 and "250 ms" in body and "must be middle, far or near" in body, body)
time.sleep(0.26)
do("mind_act", [mind, [far_act], "gaze-proof"])
record("mind gaze leaves the graph revision intact", sql(f"SELECT revision FROM mind_state WHERE id = {mind}") == brain)
marker = "I finished my plan. Verify gaze Far."
do("set_behavior", [mind, json.dumps({"think": marker})])
pending = until(lambda: [r for r in sql(f"SELECT reason, scene FROM deliberation WHERE actor = {mind}") if marker in r["reason"]],
                "mind had no fresh gaze scene", limit=65)
scene = json.loads(pending[0]["scene"])
record("new mind scene carries its applied Far band and reach", scene["you"]["gaze"] == "far" and scene["time"]["sight"] > before["sight"], scene["time"])
do("kill", [actor, "gaze verification"])
record("death removes intent and projection", not attention(actor) and not sql("SELECT * FROM my_senses_v_2", player))
