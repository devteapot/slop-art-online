#!/usr/bin/env python3
"""Exercise grid movement and observer-only access against an already published local authority.

Creates its own isolated participant run. Uses explicit test policies, no inference.
Authentication tokens stay in memory and are never written to the evidence directory.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args()
    active = json.loads(args.active.read_text())
    server, db = active["server"], active["db"]
    assert server.startswith(("http://127.0.0.1:", "http://localhost:"))
    args.output.mkdir(parents=True, exist_ok=False)
    run = f"sim-spatial-check-{time.time_ns()}"
    report = dict(run=run, database=db, evidence_mode="explicit contract fixtures; no model calls")

    def control(verb, *values):
        command = [str(Path.home()/".local/share/spacetime/bin/2.7.1/spacetimedb-cli"),
                   "--config-path", str(ROOT/".local/credentials/bevy-cli.toml"), verb, db,
                   *values, "--server", server, "--no-config"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"Authority {verb} failed")
        return result.stdout

    def call(name, *values):
        return control("call", name, *map(json.dumps, values), "-y")

    def rows(query):
        return json.loads(control("sql", query, "--format", "json"))[0]["rows"]

    def world():
        return json.loads(rows(f"SELECT state FROM sim_run WHERE id = '{run}'")[0][0])

    def post(path, value, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(server+path, data=json.dumps(value).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode()

    scenario = json.loads((ROOT/("scenarios/luna-arena-matrix.json" if args.matrix else "scenarios/woodland-pathfinding.json")).read_text())
    # Equal starts let this check compare API execution; real live personalities are separate evidence.
    scenario["players"][1]["position"] = scenario["players"][0]["position"]
    goal=scenario["players"][0]["position"]+5 if args.matrix else 92
    call("sim_create_participant", run, json.dumps(scenario))
    call("sim_setup_client_clock", run, "live_fixture")
    try:
        observer = json.loads(post("/v1/identity", {}))
        call("sim_grant_client", run, observer["identity"], True, 0)
        actor_sessions = [json.loads(post("/v1/identity", {})) for _ in range(2)]
        for actor, session in enumerate(actor_sessions, 1):
            call("sim_grant_client", run, session["identity"], False, actor)
        w = world()
        command = dict(op="replace_tree", expected_revision=0, reason="explicit spatial fixture",
                       tree=dict(kind="guard", condition=dict(kind="not", condition=dict(kind="at", location=goal)),
                                 child=dict(kind="action", action=dict(skill="move", destination=goal))))
        if args.matrix:
            cross= dict(api_version="sao-participant-v1",request_id="cross-arena-denied",control_epoch=w["participants"]["1"]["control_epoch"],
                        command=dict(op="replace_tree",expected_revision=0,reason="explicit isolation fixture",tree=dict(kind="action",action=dict(skill="move",destination=scenario["players"][2]["position"]))))
            post(f"/v1/database/{db}/call/sim_participant_command",[json.dumps(cross)],actor_sessions[0]["token"])
            assert not world()["participants"]["1"]["receipts"][-1]["ok"], "cross-arena movement accepted"
            report["cross_arena_command_denied"]=True
        for actor, session in enumerate(actor_sessions, 1):
            request = dict(api_version="sao-participant-v1", request_id=f"grid-{actor}",
                           control_epoch=w["participants"][str(actor)]["control_epoch"], command=command)
            post(f"/v1/database/{db}/call/sim_participant_command", [json.dumps(request)], session["token"])
        try:
            post(f"/v1/database/{db}/call/sim_participant_command", [json.dumps(request)], observer["token"])
            raise AssertionError("observer submitted a participant command")
        except urllib.error.HTTPError as error:
            assert "participant ownership required" in error.read().decode()
        w = world()
        assert all(w["participants"][str(i)]["receipts"][-1]["ok"] for i in (1, 2))
        call("sim_operator_clock", run, 50, False)
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            w = world()
            if all(p["position"] == goal for p in w["players"][:2]):
                break
            time.sleep(.25)
        assert all(p["position"] == goal for p in w["players"][:2]), "route did not finish"
        call("sim_operator_pause", run)
        events = [json.loads(row[0]) for row in rows(f"SELECT json FROM sim_audit WHERE run = '{run}'")]
        events.sort(key=lambda e: e["id"])
        assert not any(e["kind"] in ("script_error", "script_tick_failed") for e in events)
        paths = {}
        grid = scenario["map"]
        for actor in (1, 2):
            path = [scenario["players"][actor-1]["position"]]
            path += [e["data"]["position"] for e in events
                     if e["actor"] == actor and e["kind"] == "skill_progress" and "position" in e["data"]]
            path.append(goal)
            for a, b in zip(path, path[1:]):
                assert b not in grid["blocked"]
                assert abs(a % grid["width"]-b % grid["width"]) + abs(a//grid["width"]-b//grid["width"]) == 1
            assert w["players"][actor-1]["energy"] == 70-(len(path)-1)
            paths[str(actor)] = path
        assert paths["1"] == paths["2"]
        report.update(passed=True, observer_grant_without_character=True, observer_command_denied=True,
                      paths=paths, simulation_ms=w["timing"]["time_ms"], rules=w["version"])
        (args.output/"snapshot.json").write_text(json.dumps(dict(world=w, events=events), indent=2)+"\n")
    finally:
        call("sim_operator_pause", run)
        (args.output/"verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
