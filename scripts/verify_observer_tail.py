#!/usr/bin/env python3
"""Check the real observer audit tail on a new isolated run, without inference.

Uses an already published local database supplied by --active. Never resumes or
mutates the active file's run. Fresh observer/participant credentials stay in
memory. Optional --export-snapshot checks a separately supplied isolated fixture
export offline; it does not attach a host or start controllers.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TAIL = 180
PREFIX = "sim-audit-tail-check-"


def observer_history(events):
    """The event projection contract in simulation/src/client_view.rs."""
    result = copy.deepcopy(events[-TAIL:])
    for event in result:
        data = event["data"]
        if event["kind"] == "model_result":
            metadata = data.get("metadata") or {}
            event["data"] = dict(request_id=data.get("request_id"),
                                 outcome=metadata.get("outcome"), error=metadata.get("error"))
        elif event["kind"] == "model_request":
            data.pop("context", None)
            data.pop("base_system_prompt", None)
    return result


def assert_consistent_export(snapshot):
    world, events = snapshot["world"], snapshot["events"]
    run, upper = world["run"], world["next_event"]
    assert run.startswith(PREFIX), "export must belong to an isolated audit-tail fixture"
    assert [e["id"] for e in events] == list(range(1, upper)), "export has missing, duplicate, unordered or future events"
    assert all(e["run"] == run for e in events), "export includes another run"
    assert all(e["tick"] <= world["tick"] for e in events), "export events exceed world tick"
    assert all(e["data"].get("time_ms", 0) <= world["timing"]["time_ms"] for e in events), "export events exceed world time"
    assert not world.get("events"), "export world retains unflushed audit events"
    return dict(run=run, next_event=upper, events=len(events), time_ms=world["timing"]["time_ms"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-snapshot", type=Path,
                        help="optional existing snapshot from an isolated sim-audit-tail-check-* host fixture")
    args = parser.parse_args()
    active = json.loads(args.active.read_text())
    server, db = active["server"], active["db"]
    assert server.startswith(("http://127.0.0.1:", "http://localhost:")), "local authority required"
    args.output.mkdir(parents=True, exist_ok=False)
    run = PREFIX + str(time.time_ns())
    report = dict(run=run, database=db, passed=False,
                  evidence_mode="isolated explicit no-inference authority regression",
                  observer_tail_limit=TAIL)
    identities = []
    created = False

    def control(verb, *values):
        command = [str(Path.home()/".local/share/spacetime/bin/2.7.1/spacetimedb-cli"),
                   "--config-path", str(ROOT/".local/credentials/bevy-cli.toml"), verb, db,
                   *values, "--server", server, "--no-config"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"Authority {verb} failed; output suppressed")
        return result.stdout

    def call(name, *values):
        return control("call", name, *map(json.dumps, values), "-y")

    def rows(query):
        return json.loads(control("sql", query, "--format", "json"))[0]["rows"]

    def world():
        return json.loads(rows(f"SELECT state FROM sim_run WHERE id = '{run}'")[0][0])

    def http(path, payload, token=None, sql=False):
        headers = {"Content-Type": "text/plain" if sql else "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = payload.encode() if sql else json.dumps(payload).encode()
        request = urllib.request.Request(server+path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Authenticated authority request failed with HTTP {error.code}") from None

    def client_view(session):
        result = json.loads(http(f"/v1/database/{db}/sql", "SELECT body FROM sim_my_snapshot",
                                 session["token"], sql=True))
        values = result[0]["rows"]
        assert len(values) == 1, "granted identity must receive exactly its own snapshot"
        return json.loads(values[0][0])

    try:
        scenario = json.loads((ROOT/"scenarios/woodland-pathfinding.json").read_text())
        scenario["max_ticks"] = max(120, scenario["max_ticks"])
        call("sim_create_participant", run, json.dumps(scenario))
        created = True
        call("sim_setup_client_clock", run, "live_fixture")
        call("sim_operator_pause", run)
        observer = json.loads(http("/v1/identity", {}))
        identities.append(observer["identity"])
        call("sim_grant_client", run, observer["identity"], True, 0)
        participant = json.loads(http("/v1/identity", {}))
        identities.append(participant["identity"])
        actor = scenario["players"][0]["id"]
        call("sim_grant_client", run, participant["identity"], False, actor)
        w = world()
        request = dict(api_version="sao-participant-v1", request_id="audit-tail-observe-fixture",
                       control_epoch=w["participants"][str(actor)]["control_epoch"],
                       command=dict(op="replace_tree", expected_revision=0,
                                    reason="explicit observer-tail regression; no inference",
                                    tree=dict(kind="action", action=dict(skill="observe"))))
        http(f"/v1/database/{db}/call/sim_participant_command", [json.dumps(request)], participant["token"])
        assert world()["participants"][str(actor)]["receipts"][-1]["ok"], "fixture policy was rejected"
        steps = 0
        while world()["next_event"] <= 2*TAIL+1 and steps < 100:
            call("sim_step", run)
            steps += 1
        w = world()
        assert w["next_event"] > 2*TAIL+1, "fixture did not create enough actual events"
        before = client_view(observer)
        # Advance after the first view so a cached initial tail cannot satisfy this check.
        call("sim_step", run)
        w = world()
        events = sorted((json.loads(row[0]) for row in rows(
            f"SELECT json FROM sim_audit WHERE run = '{run}'")), key=lambda e:e["id"])
        assert world() == w, "paused fixture changed during capture"
        assert not any(e["kind"] in ("model_request", "model_result", "script_error", "script_tick_failed") for e in events), "fixture inferred or encountered an engine error"
        snapshot = dict(world=w, events=events)
        report["authority_export"] = assert_consistent_export(snapshot)
        observed = client_view(observer)
        personal = client_view(participant)
        expected = observer_history(events)
        assert observed["run"] == run and observed["observer"] is True, "wrong observer grant"
        assert observed["tick"] == w["tick"] and observed["time_ms"] == w["timing"]["time_ms"], "observer world revision is stale"
        assert observed["events"] == expected, "observer tail differs from the exact projected authority tail"
        assert len(expected) == TAIL, "observer tail fixture is too short"
        assert expected[0]["id"] == w["next_event"]-TAIL and expected[-1]["id"] == w["next_event"]-1, "tail bounds differ from World.next_event"
        assert before["events"][-1]["id"] < expected[-1]["id"], "observer tail did not advance"
        me = next(p for p in w["players"] if p["id"] == actor)
        personal_history = [dict(id=m["source"], tick=m["tick"], actor=actor, kind=m["kind"],
                                 parents=[], data=m["content"]) for m in me["memories"]]
        assert personal["run"] == run and personal["actor"] == actor and personal["observer"] is False, "wrong participant grant"
        assert personal["events"] == personal_history, "participant history contains more than its own perceived memories"
        assert personal["events"] != expected and personal["pending"] is None and personal["arenas"] is None, "observer history or private pending state leaked"
        assert all(p["id"] == actor or ("beliefs" not in p and "health" not in p) for p in personal["players"]), "another mind leaked"
        assert personal["participant"]["actor"] == actor, "participant protocol projects another actor"
        report.update(passed=True, steps=steps+1, observer_tail_ids=[expected[0]["id"], expected[-1]["id"]],
                      observer_tail_matches=True, participant_own_memory_only=True)
        if args.export_snapshot:
            raw = args.export_snapshot.read_bytes()
            report["supplied_host_export"] = dict(path=str(args.export_snapshot.resolve()),
                sha256=hashlib.sha256(raw).hexdigest(), **assert_consistent_export(json.loads(raw)))
        (args.output/"snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        (args.output/"observer.json").write_text(json.dumps(observed, indent=2)+"\n")
        (args.output/"participant.json").write_text(json.dumps(personal, indent=2)+"\n")
    except Exception as error:
        report["passed"] = False
        report["error"] = str(error)
        raise
    finally:
        cleanup_errors = []
        if created:
            try:
                call("sim_operator_pause", run)
            except Exception:
                cleanup_errors.append("isolated run pause failed")
            for identity in identities:
                try:
                    call("sim_revoke_client", identity)
                except Exception:
                    cleanup_errors.append("fixture grant revocation failed")
        report["cleanup_errors"] = cleanup_errors
        if cleanup_errors:
            report["passed"] = False
        (args.output/"verification.json").write_text(json.dumps(report, indent=2)+"\n")
    if not report["passed"]:
        raise SystemExit("Observer-tail regression failed; inspect verification.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
