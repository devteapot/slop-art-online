#!/usr/bin/env python3
"""Start a bounded genuine live pilot using the existing host, authority and participant runtimes.

The supervisor owns setup/time/evidence only. Models receive their scoped participant
views through the production harness or MCP; no observer state is supplied to them.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

from run_carlid_npc import ROOT, CREDENTIAL, load_key


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory")
    parser.add_argument("--port", type=int, default=18908)
    parser.add_argument("--minutes", type=int, default=5, choices=range(1, 61), metavar="1..60")
    parser.add_argument("--calls-per-actor", type=int, default=18, choices=range(0, 101), metavar="0..100", help="0 means no model-call cap; wall-time deadline still applies")
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/woodland-pathfinding.json"))
    parser.add_argument("--npc-runtime", choices=("host", "pilot"), default="host",
                        help="host runs the normal NPC harness; pilot reproduces the older shared schedule")
    parser.add_argument("--controllers", type=Path, help="per-actor config manifest; enables matched serial matrix schedules")
    parser.add_argument("--implementation", type=Path, help="verified frozen implementation bundle")
    parser.add_argument("--start-gate", type=Path, help="wait for the batch coordinator to release all ready variants")
    parser.add_argument("--serial-ms", type=int, default=15000)
    parser.add_argument("--recovery", action="store_true", help="enable explicit model feedback and priority retry after failed behavior proposals")
    args = parser.parse_args()
    os.chdir(ROOT)
    implementation=args.implementation.resolve() if args.implementation else ROOT
    if args.implementation:
        from experiment_artifacts import verify
        verify(implementation)
    if args.serial_ms < 1000:raise SystemExit("serial interval must be at least 1000 ms")
    scenario = args.scenario.resolve()
    scenario_data = json.loads(scenario.read_text())
    if not args.controllers and [p["id"] for p in scenario_data["players"][:2]] != [1, 2]:
        raise SystemExit("Pilot requires runtime actor 1 and external actor 2.")
    controllers = json.loads(args.controllers.resolve().read_text()) if args.controllers else []
    actor_ids = [p["id"] for p in scenario_data["players"]]
    if controllers and (set(c["actor"] for c in controllers) != set(actor_ids) or len(controllers) != len(actor_ids)):
        raise SystemExit("Controller manifest must cover each actor exactly once.")
    if controllers and args.npc_runtime != "host":
        raise SystemExit("Matrix uses the actual host NPC runtime.")
    out = args.output.resolve()
    if out.exists():
        raise SystemExit("Choose a new output directory; existing runs are retained.")
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", args.port))
    cli_root = Path.home() / ".local/share/spacetime/bin"
    config = ROOT / "configs/reasoning/codex-carlid-luna-streaming-proof.json"
    env = os.environ.copy()
    try:
        key = env.get("CARLID_NPC_API_KEY") or load_key(CREDENTIAL)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    env.update(
        CARLID_NPC_API_KEY=key,
        SPACETIME_CLI=str(cli_root / "2.1.0/spacetimedb-cli"),
        SPACETIME_CONTROL_CLI=str(cli_root / "2.7.1/spacetimedb-cli"),
        SPACETIME_CONFIG_PATH=str(ROOT / ".local/credentials/bevy-cli.toml"),
        NPC_REASONING_CONFIG=str(config),
        BEVY_DEV_PORT=str(args.port), BEVY_DEV_BIND="127.0.0.1",
        BEVY_DEV_PUBLIC_URL=f"http://127.0.0.1:{args.port}",
        BEVY_DEV_OUTPUT=str(out), BEVY_DEV_SCENARIO=str(scenario),
        BEVY_DEV_MAX_TICKS=str(args.minutes * 24), BEVY_DEV_TICK_MS="50",
        SAO_HARNESS_MANUAL="1" if args.npc_runtime == "pilot" else "0",
        BEVY_DEV_CREDENTIAL_DIR=str(ROOT / ".local/credentials"),
        BEVY_DEV_MODULE=str(implementation / "target/wasm32-unknown-unknown/release/server_module.wasm"),
    )
    env["SAO_HARNESS_RECOVERY"] = "1" if args.recovery else "0"
    if args.calls_per_actor:
        env["SAO_HARNESS_MAX_CALLS"]=str(args.calls_per_actor)
    else:
        env.pop("SAO_HARNESS_MAX_CALLS",None)
    if controllers:
        env.update(BEVY_DEV_CONTROLLERS=str(args.controllers.resolve()),SAO_HARNESS_SERIAL_MS=str(args.serial_ms),
                   SAO_HARNESS_START_FILE=str(out / "start-harness"))
    binaries = [implementation / "target/debug" / name for name in
                ("sao-dev-client", "sao-agent-mcp", "examples/participant_live_agent")]
    for binary in binaries:
        if not binary.is_file():
            raise SystemExit("Build the host, MCP and participant_live_agent example first.")
    out.mkdir(parents=True)
    stop = threading.Event()
    lock = threading.Lock()
    jobs = {}
    counters = {actor: 0 for actor in actor_ids}
    actor_configs = {}
    for c in controllers:
        path = out / f"actor-{c['actor']}-config.json"
        write(path,c["config"])
        actor_configs[c["actor"]] = path
    report = dict(recovery=args.recovery, phase="starting", url=env["BEVY_DEV_PUBLIC_URL"], minutes=args.minutes,
                  tick_ms=50, max_model_calls=args.calls_per_actor * len(actor_ids) if args.calls_per_actor else None,
                  implementation=str(implementation),
                  scenario=str(scenario), npc_runtime=args.npc_runtime,
                  controller_schedules={"builtin":"host independent behavior/communication/learning loops" if args.npc_runtime == "host" else "pilot serial rotation", "external":"separate MCP process; pilot serial rotation"},
                  model="gpt-5.6-luna", calls=[], evidence_mode="genuine model calls; no fixture policy",
                  provider_limits="one attempt/call, 300-second deadline; endpoint has no output-token cap",
                  artifacts={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in [*binaries, ROOT / "Cargo.lock", config,
                                       ROOT / env["BEVY_DEV_MODULE"],
                                       scenario]})
    if args.implementation:
        report["implementation_manifest"]=json.loads((implementation / "implementation.json").read_text())
    if controllers:
        report["artifacts"].update({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [args.controllers.resolve(),*actor_configs.values()]})
        write(out / "controller-manifest.json", controllers)
        report.update(arenas=scenario_data["arenas"],controller_manifest=str(args.controllers.resolve()),
                      controller_schedules={"builtin":f"host serial behavior/communication/learning; {args.serial_ms}ms after each completion", "external":f"MCP process serial behavior/communication/learning; {args.serial_ms}ms after each completion"},
                      reasoning_note="Requested effort sent explicitly; endpoint acceptance is not effective-effort attestation")
    write(out / "pilot.json", report)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    host_log = (out / "host.log").open("w")
    host = subprocess.Popen([str(binaries[0])], env=env, stdout=host_log, stderr=host_log,
                            start_new_session=True, cwd=implementation)
    report["host_pid"] = host.pid
    active = None
    participants = []

    def control(verb, *values):
        result = subprocess.run([env["SPACETIME_CONTROL_CLI"], "--config-path", env["SPACETIME_CONFIG_PATH"],
                                 verb, active["db"], *values, "--server", active["server"], "--no-config"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"Authority {verb} failed; inspect host/database logs")
        return result.stdout

    def call(name, *values):
        return control("call", name, *[json.dumps(v) for v in values], "-y")

    def state():
        rows = json.loads(control("sql", f"SELECT state FROM sim_run WHERE id = '{active['run']}'", "--format", "json"))
        return json.loads(rows[0]["rows"][0][0])

    def snapshot():
        # The host exports actual state/events; no local world is advanced here.
        try:
            return json.loads((out / active["run"] / "snapshot.json").read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def alive(actor):
        current = snapshot()
        return current is None or (not current["world"]["stopped"] and
                                   next(p for p in current["world"]["players"] if p["id"] == actor)["health"] > 0)

    def terminate(job):
        if job.poll() is None:
            try:
                os.killpg(job.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                job.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(job.pid, signal.SIGKILL)
                job.wait(timeout=3)

    def deliberate(actor, role):
        if stop.is_set() or not alive(actor) or (args.calls_per_actor and counters[actor] >= args.calls_per_actor):
            return
        counters[actor] += 1
        number = counters[actor]
        side = "internal" if participant_by_actor[actor]["role"] == "builtin" else "external"
        folder = out / active["run"] / "live-inference" / f"actor-{actor}" / f"{number:02}-{role}"
        folder.mkdir(parents=True)
        actor_env = {k: v for k, v in env.items() if not k.startswith(("SPACETIME_", "BEVY_DEV_"))}
        record = dict(actor=actor, responsibility=role, number=number, started_at=time.time(),
                      phase="started", journal=str(folder.relative_to(out)))
        with (folder / "process.log").open("w") as log:
            job = subprocess.Popen([str(binaries[2]), side, participant_by_actor[actor]["session_file"], str(actor_configs.get(actor,config)), role, str(folder)],
                                   env=actor_env, stdout=log, stderr=log, start_new_session=True, cwd=implementation)
            with lock:
                jobs[actor] = job
                report["calls"].append(record)
            deadline = time.monotonic() + 315
            interrupted = None
            while job.poll() is None:
                if stop.wait(0.5) or not alive(actor) or time.monotonic() >= deadline:
                    interrupted = "pilot ended, actor stopped, or process deadline"
                    terminate(job)
                    break
            with lock:
                record.update(phase="interrupted" if interrupted else ("completed" if job.returncode == 0 else "failed"), finished_at=time.time(),
                              exit_code=job.returncode, interruption=interrupted)
                jobs.pop(actor, None)

    def worker(actor):
        # Separate participant schedules. Failed outputs remain evidence; later calls
        # receive fresh observations and receipts, never silently repaired proposals.
        deliberate(actor, "behavior")
        if controllers and stop.wait(args.serial_ms/1000): return
        roles = ("communication", "learning", "behavior")
        index = 0
        while not stop.is_set() and alive(actor) and (not args.calls_per_actor or counters[actor] < args.calls_per_actor):
            deliberate(actor, roles[index % len(roles)])
            index += 1
            if stop.wait(args.serial_ms/1000 if controllers else 45):
                break

    try:
        until = time.monotonic() + 90
        while not (out / "active.json").exists():
            if host.poll() is not None or time.monotonic() > until or stop.wait(0.25):
                raise RuntimeError("Host did not become ready; inspect host.log")
        active = json.loads((out / "active.json").read_text())
        report.update(active, phase="ready")
        participants = json.loads((out / active["run"] / "participants.json").read_text())
        participant_by_actor = {p["actor"]: p for p in participants}
        write(out / "pilot.json", report)
        write(out / "ready.json",dict(run=active["run"],ready_at=time.time()))
        if args.start_gate:
            gate_deadline=time.monotonic()+180
            while not args.start_gate.exists():
                if host.poll() is not None or stop.wait(.1) or time.monotonic()>gate_deadline:
                    raise RuntimeError("Batch start gate was not released")
        print(f"Observer ready at {report['url']}; starting at the native 50 ms scheduled interval (20 Hz target)", flush=True)
        # No model-readiness gate. The authority advances even while initial reasoning
        # is pending; subsequent calls cannot pause or slow the simulation clock.
        call("sim_operator_clock", active["run"], report["tick_ms"], False)
        if controllers: (out / "start-harness").touch()
        report.update(phase="running", started_at=time.time(), deadline_at=time.time() + args.minutes * 60)
        write(out / "pilot.json", report)
        print(f"Live pilot running for {args.minutes} minutes; model-call cap: {report['max_model_calls'] or 'none'}", flush=True)
        deadline = time.monotonic() + args.minutes * 60
        last_tick = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(actor_ids)) as pool:
            workers = [pool.submit(worker, actor) for actor in actor_ids if args.npc_runtime == "pilot" or participant_by_actor[actor]["role"] == "external"]
            try:
                while not stop.wait(2) and time.monotonic() < deadline:
                    if host.poll() is not None:
                        raise RuntimeError("Observation host exited")
                    current = snapshot()
                    if current:
                        w, events = current["world"], current["events"]
                        if w["tick"] != last_tick:
                            last_tick = w["tick"]
                            metrics = dict(observed_at=time.time(), time_ms=w["timing"]["time_ms"], updates=w["timing"]["updates"], tick=w["tick"], stopped=w["stopped"], players=[
                                dict({k: p[k] for k in ("id", "name", "health", "hunger", "energy", "food", "position", "caution", "beliefs", "relationships")},
                                     policy_status=((p.get("execution") or {}).get("state") or {}).get("status"))
                                for p in w["players"]],
                                sites=w['sites'],
                                event_counts={kind: sum(e["kind"] == kind for e in events) for kind in
                                              ("skill_result", "speech", "identity_change", "participant_rejected", "script_error", "script_tick_failed", "death")})
                            write(out / "metrics.json", metrics)
                            with (out / "observations.jsonl").open("a") as stream:
                                stream.write(json.dumps(metrics) + "\n")
                        if w["stopped"] or all(p["health"] <= 0 for p in w["players"]):
                            break
                    with lock:
                        report["last_observed_tick"] = last_tick
                        write(out / "pilot.json", report)
                    for worker_job in workers:
                        if worker_job.done():
                            worker_job.result()
            finally:
                stop.set()
        report["phase"] = "completed"
    except Exception as error:
        report.update(phase="failed", error=str(error))
        raise
    finally:
        stop.set()
        with lock:
            remaining = list(jobs.values())
        for job in remaining:
            terminate(job)
        if active:
            try:
                call("sim_operator_pause", active["run"])
                report["final_tick"] = state()["tick"]
                if args.npc_runtime == "host":
                    for participant in participants:
                        if participant["role"] == "builtin":
                            call("sim_revoke_client", participant["identity"])
                final_world = state()
                rows = json.loads(control("sql", f"SELECT json FROM sim_audit WHERE run = '{active['run']}'", "--format", "json"))
                final_events = sorted((json.loads(row[0]) for row in rows[0]["rows"]), key=lambda e: e["id"])
                write(out / active["run"] / "final-snapshot.json", dict(world=final_world, events=final_events))
                report["final_time_ms"] = final_world["timing"]["time_ms"]
                report["final_snapshot"] = str(out / active["run"] / "final-snapshot.json")
                reasoning = list((out / active["run"] / "reasoning").rglob("harness-*.json"))
                report["builtin_model_calls"] = len(reasoning)
                report["builtin_journal"] = str(out / active["run"] / "reasoning")
            except Exception:
                report["pause_error"] = "Could not confirm final pause; inspect authority"
        else:
            terminate(host)
        report["finished_at"] = time.time()
        write(out / "pilot.json", report)
        host_log.close()
        print(f"Pilot {report['phase']}; evidence: {out}. Observer host remains available if started.", flush=True)


if __name__ == "__main__":
    main()
