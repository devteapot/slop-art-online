#!/usr/bin/env python3
"""Measure the native scheduled reducer in a fresh local authority. No model calls.

Use --database with a freshly published module and SPACETIME_CONFIG_PATH.
Retains timing samples and always pauses its own isolated run on exit.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database", required=True)
parser.add_argument("--server", default="http://127.0.0.1:3101")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
assert args.server.startswith(("http://127.0.0.1:", "http://localhost:"))
args.output.mkdir(parents=True, exist_ok=False)
run = f"sim-timing-{time.time_ns()}"
report = dict(database=args.database, run=run, interval_ms=50, samples=[])

def control(*argv):
    cmd = [os.environ["SPACETIME_CONTROL_CLI"], "--config-path", os.environ["SPACETIME_CONFIG_PATH"],
           *argv, "--server", args.server, "--no-config"]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30).stdout

def call(name, *values):
    return control("call", args.database, name, *map(json.dumps, values), "-y")

def sample():
    rows = json.loads(control("sql", args.database, f"SELECT state FROM sim_run WHERE id = '{run}'", "--format", "json"))
    w = json.loads(rows[0]["rows"][0][0])
    value = dict(wall=time.monotonic(), time_ms=w["timing"]["time_ms"], updates=w["timing"]["updates"],
                 hunger=w["players"][0]["hunger"], tick=w["tick"])
    report["samples"].append(value)
    return value

def world():
    rows = json.loads(control("sql", args.database, f"SELECT state FROM sim_run WHERE id = '{run}'", "--format", "json"))
    return json.loads(rows[0]["rows"][0][0])

def post(path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(args.server + path, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()

def replace(identity, action):
    w = world()
    request = dict(api_version="sao-participant-v1", request_id=f"timing-{time.time_ns()}",
                   control_epoch=w["participants"]["3"]["control_epoch"],
                   command=dict(op="replace_tree", expected_revision=w["players"][2]["generation"],
                                reason="explicit timing fixture", tree=dict(kind="action", action=action)))
    post(f"/v1/database/{args.database}/call/sim_participant_command", [json.dumps(request)], identity["token"])
    assert world()["participants"]["3"]["receipts"][-1]["ok"]

scenario = json.loads((ROOT / "scenarios/living-clearing.json").read_text())
call("sim_create_participant", run, json.dumps(scenario))
call("sim_setup_client_clock", run, "live_fixture")
try:
    for interval in (0, 49, 60001):
        try:
            call("sim_operator_clock", run, interval, False)
            raise AssertionError("invalid interval accepted")
        except subprocess.CalledProcessError:
            pass
    request = urllib.request.Request(
        args.server + f"/v1/database/{args.database}/call/sim_operator_clock",
        data=json.dumps([run, 50, False]).encode(), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=30)
        raise AssertionError("anonymous clock control accepted")
    except urllib.error.HTTPError as error:
        assert error.code in (400, 401, 403, 530)
        assert "operator only" in error.read().decode()
    call("sim_operator_clock", run, 50, False)
    before = sample()
    time.sleep(6)
    after = sample()
    elapsed = after["wall"] - before["wall"]
    hz = (after["updates"] - before["updates"]) / elapsed
    ratio = (after["time_ms"] - before["time_ms"]) / 1000 / elapsed
    report.update(observed_hz=hz, simulation_to_wall_ratio=ratio)
    assert 18 <= hz <= 22, report
    assert .95 <= ratio <= 1.05, report
    assert after["hunger"] - before["hunger"] in (4, 6), report
    call("sim_operator_pause", run)
    paused = sample()
    time.sleep(1)
    assert sample()["time_ms"] == paused["time_ms"]
    call("sim_operator_clock", run, 50, False)
    time.sleep(.3)
    resumed = sample()
    assert 200 <= resumed["time_ms"] - paused["time_ms"] <= 600, report
    identity = json.loads(post("/v1/identity", {}))
    call("sim_grant_client", run, identity["identity"], False, 3)
    replace(identity, dict(skill="rest", duration=5))
    time.sleep(.2)
    replace(identity, dict(skill="move", destination=8))
    time.sleep(.15)
    assert world()["players"][2]["position"] >= 1, "rest continuation blocked new input"
    report["cancel_rest_responded_within_ms"] = 150
    report["passed"] = True
finally:
    call("sim_operator_pause", run)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
