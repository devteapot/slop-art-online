#!/usr/bin/env python3
"""Measure an isolated 36-person authority with concurrent reads and no model calls.

Uses the explicit release WASM, existing personal session grants and the real 50 ms
clock. Retains timing, hashes and paused authority evidence, then closes owned
clients and revokes only the diagnostic's participant grants.
"""
import argparse
import json
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

from experiment_artifacts import digest, write
from run_carlid_npc import CREDENTIAL, ROOT, load_key
from run_living_clearing import fresh_environment


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--implementation', type=Path, default=ROOT)
    parser.add_argument('--scenario', type=Path, default=ROOT / 'scenarios/faction-world.json')
    parser.add_argument('--controllers', type=Path, default=ROOT / 'configs/experiments/faction-36-medium.json')
    args = parser.parse_args()
    out = args.output.resolve()
    implementation = args.implementation.resolve()
    scenario = args.scenario.resolve()
    controllers = args.controllers.resolve()
    seed = json.loads(scenario.read_text())
    control = json.loads(controllers.read_text())
    actors = [p['id'] for p in seed['players']]
    if len(actors) != 36 or len(set(actors)) != 36:
        raise SystemExit('Expected exactly 36 distinct initial actors')
    if len(control) != 36 or {c['actor'] for c in control} != set(actors):
        raise SystemExit('Controller descriptors must cover the same 36 actors')
    if out.exists():
        raise SystemExit('Choose a fresh output directory; existing evidence is retained')
    if not 1024 <= args.port <= 65535:
        raise SystemExit('Expected an unprivileged valid port')
    with socket.socket() as check:
        check.bind(('127.0.0.1', args.port))
    host_binary = implementation / 'target/debug/sao-dev-client'
    probe_binary = implementation / 'target/debug/examples/participant_scale_probe'
    # Never use the host's default debug module: its schema/caps may be obsolete.
    module = implementation / 'target/wasm32-unknown-unknown/release/server_module.wasm'
    for path in [host_binary, probe_binary, module]:
        if not path.is_file():
            raise SystemExit(f'Build required artifact first: {path}')
    env = fresh_environment()
    env.update(
        CARLID_NPC_API_KEY=env.get('CARLID_NPC_API_KEY') or load_key(CREDENTIAL),
        SPACETIME_CLI=str(Path.home() / '.local/share/spacetime/bin/2.1.0/spacetimedb-cli'),
        SPACETIME_CONTROL_CLI=str(Path.home() / '.local/share/spacetime/bin/2.7.1/spacetimedb-cli'),
        SPACETIME_CONFIG_PATH=str(ROOT / '.local/credentials/bevy-cli.toml'),
        NPC_REASONING_CONFIG=str(ROOT / 'configs/reasoning/codex-carlid-luna-streaming-proof.json'),
        BEVY_DEV_PORT=str(args.port), BEVY_DEV_BIND='127.0.0.1',
        BEVY_DEV_PUBLIC_URL=f'http://127.0.0.1:{args.port}',
        BEVY_DEV_OUTPUT=str(out), BEVY_DEV_SCENARIO=str(out / 'scenario.json'),
        BEVY_DEV_CONTROLLERS=str(out / 'controllers.json'),
        BEVY_DEV_MAX_TICKS=str(seed['max_ticks']), BEVY_DEV_TICK_MS='50',
        BEVY_DEV_CREDENTIAL_DIR=str(ROOT / '.local/credentials'),
        BEVY_DEV_MODULE=str(module), SAO_HARNESS_MANUAL='1',
        SAO_HARNESS_START_FILE=str(out / 'unused-manual-harness-gate'),
    )
    out.mkdir(parents=True)
    write(out / 'scenario.json', seed)
    write(out / 'controllers.json', control)
    report = dict(phase='starting', started_at=time.time(), port=args.port,
        tick_ms=50, manual_harness=True, external_workers=0, model_calls=0,
        credential_use='Configuration validation only; no model harness or external workers launched',
        artifacts={str(p): digest(p) for p in [host_binary, probe_binary, module, scenario, controllers]},
        cleanup_errors=[])
    write(out / 'diagnostic.json', report)
    host = probe = None
    active = None
    participants = []

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    def cli(verb, *values):
        result = subprocess.run([env['SPACETIME_CONTROL_CLI'], '--config-path', env['SPACETIME_CONFIG_PATH'],
            verb, active['db'], *values, '--server', active['server'], '--no-config'],
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'Authority {verb} failed (exit {result.returncode})')
        return result.stdout

    def call(name, *values):
        return cli('call', name, *[json.dumps(v) for v in values], '-y')

    def sql(query):
        return json.loads(cli('sql', query, '--format', 'json'))[0]['rows']

    def state():
        return json.loads(sql(f"SELECT state FROM sim_run WHERE id = '{active['run']}'")[0][0])

    def capture(name):
        before = state()
        events = sorted([json.loads(row[0]) for row in sql(
            f"SELECT json FROM sim_audit WHERE run = '{active['run']}'")], key=lambda e: e['id'])
        if before != state():
            raise RuntimeError('Authority state changed during paused capture')
        path = out / active['run'] / name
        if path.exists():
            raise RuntimeError('Refusing to overwrite authority evidence')
        write(path, dict(world=before, events=events))
        return dict(path=str(path), sha256=digest(path), time_ms=before['timing']['time_ms'],
                    updates=before['timing']['updates'], events=len(events))

    try:
        with (out / 'host.log').open('w') as log:
            host = subprocess.Popen([str(host_binary)], cwd=implementation, env=env,
                stdout=log, stderr=log, start_new_session=True)
        report['host_pid'] = host.pid
        write(out / 'diagnostic.json', report)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if host.poll() is not None:
                raise RuntimeError('Host exited during setup; inspect host.log')
            if (out / 'active.json').exists():
                active = json.loads((out / 'active.json').read_text())
                if not re.fullmatch(r'sim-[a-zA-Z0-9-]+', active['run']):
                    raise RuntimeError('Invalid generated run identifier')
                path = out / active['run'] / 'participants.json'
                if path.exists():
                    participants = json.loads(path.read_text())
                    if len(participants) == 36 and {p['actor'] for p in participants} == set(actors):
                        break
            time.sleep(.2)
        else:
            raise RuntimeError('Timed out waiting for all 36 personal grants')
        report.update(run=active['run'], database=active['db'], phase='running', ready_at=time.time())
        call('sim_operator_clock', active['run'], 50, False)
        report['clock_enabled_at'] = time.time()
        before = state()
        report['before_probe'] = dict(wall=time.time(), time_ms=before['timing']['time_ms'], updates=before['timing']['updates'])
        write(out / 'diagnostic.json', report)
        print(json.dumps({'phase':'reading', 'run':active['run'], 'port':args.port}), flush=True)
        with (out / 'probe.log').open('w') as log:
            probe = subprocess.Popen([str(probe_binary), str(path), str(out / 'participant-scale-result.json')],
                cwd=implementation, stdout=log, stderr=log, start_new_session=True)
            report['probe_returncode'] = probe.wait(timeout=150)
        report['probe_finished_at'] = time.time()
        if (out / 'participant-scale-result.json').exists():
            results = json.loads((out / 'participant-scale-result.json').read_text())
            report['probe_passed'] = results['all_pass']
            report['rounds'] = [{key:r[key] for key in ('round','attempts','successes','reads_returned',
                'read_errors','validation_failures','wall_ms','latency_median_ms','latency_max_ms')} for r in results['rounds']]
        report['phase'] = 'completed' if report.get('probe_passed') else 'failed'
    except (Exception, KeyboardInterrupt) as error:
        report.update(phase='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                      error=f'{type(error).__name__}: {error}')
    finally:
        stop_process(probe)
        paused = False
        if active:
            try:
                report['pause_requested_at'] = time.time()
                call('sim_operator_pause', active['run'])
                report['pause_acknowledged_at'] = time.time()
                paused = bool(sql(f"SELECT paused FROM sim_client_clock WHERE run = '{active['run']}'")[0][0])
            except Exception as error:
                report['cleanup_errors'].append(f'Initial pause: {type(error).__name__}')
        # Removing only our host also releases its expensive observer subscription.
        stop_process(host)
        if active:
            try:
                if not paused:
                    call('sim_operator_pause', active['run'])
                    paused = bool(sql(f"SELECT paused FROM sim_client_clock WHERE run = '{active['run']}'")[0][0])
                if not paused:
                    raise RuntimeError('Diagnostic clock is not paused')
                report['paused_capture'] = capture('probe-complete-snapshot.json')
                report['after_probe'] = dict(wall=report.get('pause_acknowledged_at', time.time()), time_ms=report['paused_capture']['time_ms'],
                    updates=report['paused_capture']['updates'])
                revoked = []
                report['revoked_actors'] = revoked
                for participant in participants:
                    if not re.fullmatch(r'[0-9a-fA-F]{64}', participant['identity']):
                        raise RuntimeError('Invalid diagnostic participant identity')
                    call('sim_revoke_client', participant['identity'])
                    revoked.append(participant['actor'])
                report['final_capture'] = capture('final-snapshot.json')
                report['clock_paused'] = True
            except Exception as error:
                report['cleanup_errors'].append(f'Finalization: {type(error).__name__}: {error}')
        report['host_stopped'] = host is None or host.poll() is not None
        report['model_journals_found'] = len(list(out.glob('sim-*/reasoning/actor-*/harness*.json')))
        if report['model_journals_found']:
            report.update(phase='failed', error='Unexpected model journals in manual diagnostic')
        if report['cleanup_errors']:
            report['phase'] = 'failed'
        if 'before_probe' in report and 'after_probe' in report:
            before, after = report['before_probe'], report['after_probe']
            elapsed = after['wall'] - before['wall']
            report['observed_updates_per_wall_second'] = (after['updates'] - before['updates']) / elapsed
            report['simulation_to_wall_ratio'] = (after['time_ms'] - before['time_ms']) / 1000 / elapsed
        report['finished_at'] = time.time()
        write(out / 'diagnostic.json', report)
        print(json.dumps({key:report.get(key) for key in ('phase','run','rounds','observed_updates_per_wall_second',
            'simulation_to_wall_ratio','clock_paused','host_stopped','model_journals_found','cleanup_errors')}), flush=True)
    return 0 if report['phase'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
