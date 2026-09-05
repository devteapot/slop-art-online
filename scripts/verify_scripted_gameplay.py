#!/usr/bin/env python3
"""Real authority/participant regression. Explicit fixtures, no model inference.

Use a freshly published module/database and the operator's private CLI config.
This adds an isolated run; it never resets a database or prints credentials.
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
parser.add_argument("--output", type=Path)
args = parser.parse_args()
assert args.server.startswith(("http://127.0.0.1:", "http://localhost:")), "local test server required"
run = f"sim-scripted-{time.time_ns()}"
out = args.output or ROOT / "output" / run
out.mkdir(parents=True, exist_ok=False)
cli = os.environ.get("SPACETIME_CONTROL_CLI", "spacetime")
config = os.environ["SPACETIME_CONFIG_PATH"]


def control(*argv):
    result = subprocess.run(
        [cli, "--config-path", config, *map(str, argv), "--server", args.server, "--no-config"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def call(name, *values):
    return control("call", args.database, name, *map(json.dumps, values), "-y")


def rows(query):
    return json.loads(control("sql", args.database, query, "--format", "json"))[0]["rows"]


def world():
    return json.loads(rows(f"SELECT state FROM sim_run WHERE id = '{run}'")[0][0])


def http(path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(args.server + path, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def reducer(token, name, *values):
    status, body = http(f"/v1/database/{args.database}/call/{name}", values, token)
    assert status == 200, (name, status, body)


seq = 0
def command(actor, token, command):
    global seq
    seq += 1
    state = world()
    request_id = f"script-proof-{seq}"
    request = dict(api_version="sao-participant-v1", request_id=request_id,
                   control_epoch=state["participants"][str(actor)]["control_epoch"], command=command)
    reducer(token, "sim_participant_command", json.dumps(request))
    receipt = next(r for r in world()["participants"][str(actor)]["receipts"] if r["request_id"] == request_id)
    assert receipt["ok"], receipt


def install(actor, token, skill, **parameters):
    command(actor, token, dict(op="replace_tree", expected_revision=world()["players"][actor-1]["generation"],
                              reason="explicit scripting integration fixture",
                              tree=dict(kind="action", action=dict(skill=skill, **parameters))))


def stage(definitions):
    state = world()
    update = dict(api_version=1, expected_revision=state["scripts"]["revision"], definitions=definitions)
    call("sim_stage_scripts", run, json.dumps(update))
    assert world()["scripts"]["pending"] is not None
    return update


scenario = json.loads((ROOT / "scenarios/survival.json").read_text())
scenario["players"] = scenario["players"][:2]
scenario["sites"] = [dict(position=0, food=10, hazard=0)]
scenario["max_ticks"] = 30
for player in scenario["players"]:
    player.update(position=0, energy=70, hunger=10, food=2, beliefs=[])
scenario["players"][0]["controller"] = "human"
scenario["players"][1]["controller"] = "ai"
call("sim_create_participant", run, json.dumps(scenario))
tokens = []
for actor in (1, 2):
    status, body = http("/v1/identity", {})
    assert status == 200, (status, body)
    identity = json.loads(body)
    tokens.append(identity["token"])
    call("sim_grant_client", run, identity["identity"], False, actor)
    install(actor, tokens[-1], "move", destination=8)

call("sim_step", run)
assert [(p["position"], p["energy"]) for p in world()["players"]] == [(1, 69), (1, 69)]
state = world()
law = dict(state["scripts"]["history"]["law"]["1"], revision=2)
law["source"] = law["source"].replace('"move" => 1', '"move" => 3')
move = dict(state["scripts"]["history"]["move"]["1"], revision=2)
move["source"] = move["source"].replace("position+=1", "position+=2").replace("position-=1", "position-=2")
assert move["source"] != state["scripts"]["history"]["move"]["1"]["source"]
proposal = dict(api_version=1, expected_revision=1, definitions=[law, move])
status, body = http(f"/v1/database/{args.database}/call/sim_stage_scripts", [run, json.dumps(proposal)], tokens[0])
assert status != 200 and "operator" in body, (status, body)
assert world()["scripts"]["pending"] is None
stage([law, move])
assert world()["scripts"]["revision"] == 1
call("sim_step", run)
state = world()
assert state["scripts"]["revision"] == 2
assert [(p["position"], p["energy"]) for p in state["players"]] == [(2, 66), (2, 66)]
assert all(p["execution"]["script"]["definition"]["revision"] == 1 for p in state["players"])
install(1, tokens[0], "move", destination=8)
call("sim_step", run)
assert [p["position"] for p in world()["players"]] == [4, 3]

# A definition composed from a pinned old movement module still consults new laws.
stride = dict(id="stride", revision=1, description="Two composed steps under active movement costs",
              dependencies=[dict(id="move", revision=1)], source='''
fn validate(c) { move::validate(c) }
fn step(c) {
    let first=move::step(c);
    if first.status == "failure" { return first; }
    c.actor.position=first.effects[0].fields.position;
    c.actor.energy=first.effects[0].fields.energy;
    let second=move::step(c);
    first.effects += second.effects;
    first.status=second.status;
    first.progress=second.progress;
    first
}''')
stage([stride])
call("sim_step", run)
install(1, tokens[0], {"script": "stride"}, destination=8)
before = world()["players"][0]
command(1, tokens[0], dict(op="speak", text="Rhai rules are active", expires_tick=12))
call("sim_step", run)
after = world()["players"][0]
assert after["position"] == before["position"] + 2
assert after["energy"] == before["energy"] - 6

bad = dict(id="broken", revision=1, description="Atomic failure fixture", dependencies=[], source='''
fn validate(c) { "" }
fn step(c) { law::done([#{kind:"actor",fields:#{energy:999}}, #{kind:"actor",fields:#{health:999}}]) }
''')
stage([bad])
call("sim_step", run)
install(1, tokens[0], {"script": "broken"})
before = world()["players"][0]["energy"]
call("sim_step", run)
assert world()["players"][0]["energy"] == before
events = sorted((json.loads(r[0]) for r in rows(f"SELECT json FROM sim_audit WHERE run = '{run}'")), key=lambda e: e["id"])
assert any(e["kind"] == "script_error" and not e["data"]["effects_committed"] for e in events)
assert any(e["kind"] == "speech" and e["data"]["text"] == "Rhai rules are active" for e in events)
assert not any(e["kind"] == "script_tick_failed" for e in events)
report = dict(run=run, database=args.database, rules=world()["version"], ticks=world()["tick"],
              checks=["authenticated human/AI shared effects", "participant cannot install definitions",
                      "next-tick law activation", "running skill revision survives reducer reload",
                      "new attempts use new skill", "pinned composition follows active laws",
                      "queued scripted dialogue", "atomic effect rejection"], evidence_mode="explicit fixtures; no inference")
(out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
(out / "snapshot.json").write_text(json.dumps(dict(world=world(), events=events), indent=2) + "\n")
(out / "scenario.json").write_text(json.dumps(scenario, indent=2) + "\n")
print(json.dumps(report, indent=2))
