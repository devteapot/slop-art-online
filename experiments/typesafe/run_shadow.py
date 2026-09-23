#!/usr/bin/env python3
"""Isolated actual-authority shadow trial; existing production harness retains control."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from owner_snapshot import export_world, export_audit_json
from pilot_cleanup import finalize_fixed_run


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def stop(process):
    if process is None:
        return {'stopped': True, 'not_started': True}
    stages = []
    for sig, seconds in [(signal.SIGINT, 12), (signal.SIGTERM, 3), (signal.SIGKILL, 3)]:
        if process.poll() is not None:
            break
        stages.append(sig.name)
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            process.wait(timeout=seconds)
            break
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            pass
    return {'stopped': process.poll() is not None, 'returncode': process.poll(), 'signals': stages,
            'forced': 'SIGKILL' in stages}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--env-file', type=Path, default=ROOT / '.env')
    p.add_argument('--calls-per-actor', type=int, default=3)
    p.add_argument('--wall-seconds', type=int, default=180)
    a = p.parse_args()
    if not 1 <= a.calls_per_actor <= 12 or not 30 <= a.wall_seconds <= 300:
        p.error('calls-per-actor 1..12 and wall-seconds 30..300 required')
    out = a.out.resolve()
    env = os.environ.copy()
    for line in a.env_file.read_text().splitlines():
        name, sep, value = line.strip().removeprefix('export ').partition('=')
        if sep and name.strip() in ('TYPESAFE_API_KEY', 'CARLID_NPC_API_KEY'):
            value = value.strip()
            if value[:1] in ('"', "'") and value[-1:] == value[:1]:
                value = value[1:-1]
            env[name.strip()] = value
    if not all(env.get(k) for k in ('TYPESAFE_API_KEY', 'CARLID_NPC_API_KEY')):
        raise ValueError('Both model credentials are required; no substitution')
    # Reject stale host/controller destinations and inherited run selection.
    for name in list(env):
        if name.startswith(('BEVY_DEV_', 'SAO_', 'SPACETIME_')) or name == 'NPC_REASONING_CONFIG':
            env.pop(name)
    install = Path.home() / '.local/share/spacetime/bin'
    publish_cli = install / '2.1.0/spacetimedb-cli'
    control_cli = install / '2.7.1/spacetimedb-cli'
    files = [publish_cli, control_cli, ROOT/'target/debug/sao-dev-client',
             ROOT/'target/debug/examples/participant_shadow_trial',
             ROOT/'target/wasm32-unknown-unknown/debug/server_module.wasm',
             ROOT/'target/wasm32-unknown-unknown/debug/controller_module.wasm']
    for path in files:
        if not path.is_file():
            raise ValueError('Required build or CLI missing: ' + str(path))
    out.mkdir(parents=True, exist_ok=False)
    private = ROOT / '.local/credentials' / out.name
    private.mkdir(parents=True, exist_ok=False, mode=0o700)
    address = f'http://127.0.0.1:{free_port()}'
    host_port = free_port()
    env.update(SPACETIME_CLI=str(publish_cli), SPACETIME_CONTROL_CLI=str(control_cli),
               SPACETIME_CONFIG_PATH=str(private/'cli.toml'), BEVY_DEV_SERVER=address,
               BEVY_DEV_PORT=str(host_port), BEVY_DEV_OUTPUT=str(out/'host'),
               BEVY_DEV_SCENARIO=str(ROOT/'scenarios/settlement-renewable.json'),
               BEVY_DEV_MAX_TICKS='10000', BEVY_DEV_TICK_MS='50', SAO_HARNESS_MANUAL='1',
               BEVY_DEV_MODEL_ACTORS='[1,3]')
    config = json.loads((ROOT/'configs/reasoning/codex-carlid-luna.json').read_text())
    config['deadline_ms'] = 60000  # Frozen experiment deadline, never extended/retried.
    write(out/'primary-config.json', config)
    controllers = [{'actor': n, 'role': 'builtin', 'config': config} for n in (1,3)]
    write(out/'controllers.json', controllers)
    env['BEVY_DEV_CONTROLLERS'] = str(out/'controllers.json')
    manifest = {'protocol':'sao-typesafe-shadow-live-v1', 'server':address, 'host_port':host_port,
                'population':4, 'model_actors':[1,3], 'other_actors':'existing seed policies',
                'calls_per_actor':a.calls_per_actor, 'max_live_wall_seconds':a.wall_seconds,
                'configured_world_interval_ms':50, 'performance_acceptance':False,
                'scenario':json.loads((ROOT/'scenarios/settlement-renewable.json').read_text()),
                'primary_config':config, 'shadow_model':'jev-1.13.0',
                'observer':'none; existing developer host export loop retained, final owner export after stop',
                'subscription_policy':'existing scoped ParticipantService/controller subscriptions, no shadow DB connection',
                'sha256':{str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
                'started_at':time.time(), 'status':'starting'}
    source_paths = [ROOT/f for f in ('server/bridge/src/agent_harness.rs',
        'server/bridge/src/typesafe_shadow.rs', 'server/bridge/examples/participant_shadow_trial.rs',
        'experiments/typesafe/run_shadow.py', 'experiments/typesafe/summarize_shadow.py',
        'scripts/pilot_cleanup.py', 'scripts/owner_snapshot.py', 'Cargo.lock')]
    # Freeze source alongside binaries; uncommitted branch state is not a revision identifier.
    manifest['source_sha256'] = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in source_paths}
    for f in source_paths:
        snapshot = out/'source'/f.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(f.read_bytes())
    write(out/'manifest.json', manifest)
    service = host = None
    jobs = []
    active = None
    handles = []

    def launch(cmd, logfile, child_env):
        handle = (out/logfile).open('w'); handles.append(handle)
        return subprocess.Popen([str(x) for x in cmd], cwd=ROOT, env=child_env, stdout=handle,
                                stderr=subprocess.STDOUT, start_new_session=True)

    def control(verb, *values):
        cmd = [str(control_cli), '--config-path', env['SPACETIME_CONFIG_PATH'], verb, active['db'], *values,
               '--server', address, '--no-config', '-y']
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            # CLI errors must not echo supplied credential material.
            raise RuntimeError(f'Authority {verb} failed; exit {result.returncode}')
        return result.stdout

    def call(name, *values):
        return control('call', name, *(json.dumps(v) for v in values))

    try:
        service = launch([publish_cli,'start','--listen-addr',address.removeprefix('http://'),
                          '--data-dir',out/'service','--page_pool_max_size','536870912','--non-interactive'],
                         'service.log',env)
        deadline = time.monotonic()+30
        while True:
            if service.poll() is not None:
                raise RuntimeError('Isolated service exited; inspect service.log')
            try:
                with urllib.request.urlopen(address+'/v1/ping',timeout=1) as response:
                    if response.status==200: break
            except (OSError, TimeoutError):
                pass
            if time.monotonic()>deadline: raise RuntimeError('Isolated service readiness deadline')
            time.sleep(0.2)
        login = subprocess.run([str(publish_cli),'--config-path',env['SPACETIME_CONFIG_PATH'],
                                'login','--server-issued-login',address],cwd=ROOT,env=env,
                               capture_output=True,timeout=30)
        if login.returncode: raise RuntimeError('Isolated owner login failed')
        Path(env['SPACETIME_CONFIG_PATH']).chmod(0o600)
        host = launch([ROOT/'target/debug/sao-dev-client'],'host.log',env)
        deadline = time.monotonic()+90
        while not (out/'host/active.json').exists():
            if host.poll() is not None: raise RuntimeError('Host exited; inspect host.log')
            if time.monotonic()>deadline: raise RuntimeError('Host initialization deadline')
            time.sleep(0.2)
        active = json.loads((out/'host/active.json').read_text())
        manifest['active'] = active
        participants = json.loads((out/'host'/active['run']/'participants.json').read_text())
        call('sim_operator_clock',active['run'],50,False)
        manifest.update(status='running',live_started_at=time.time())
        write(out/'manifest.json',manifest)
        for actor in (1,3):
            session = next(v['session_file'] for v in participants if v['actor']==actor)
            child_env = {k:v for k,v in env.items() if not k.startswith(('SPACETIME_','BEVY_DEV_'))}
            jobs.append(launch([ROOT/'target/debug/examples/participant_shadow_trial',session,
                                out/'primary-config.json',out/f'actor-{actor}',str(a.calls_per_actor)],
                               f'actor-{actor}.log',child_env))
        deadline = time.monotonic()+a.wall_seconds
        while any(job.poll() is None for job in jobs) and time.monotonic()<deadline:
            if host.poll() is not None or service.poll() is not None:
                raise RuntimeError('Owned host/service exited during trial')
            time.sleep(0.2)
        manifest['worker_exit_codes'] = [job.poll() for job in jobs]
        manifest['status'] = 'completed' if all(job.poll()==0 for job in jobs) else 'incomplete'
    except KeyboardInterrupt:
        manifest.update(status='interrupted')
    except Exception as error:
        manifest.update(status='failed', error=str(error))
    finally:
        manifest['worker_cleanup'] = [stop(job) for job in jobs]
        if active is not None and service is not None and service.poll() is None:
            try:
                world, events = finalize_fixed_run(active['run'],stop_host=lambda:stop(host),control=control,
                    call=call,state=lambda:export_world(call,active['run']),
                    record=lambda value:write(out/'finalization.json',value),
                    audit_export=lambda run,end:export_audit_json(call,run,end))
                write(out/'final-world.json',world)
                write(out/'final-audit.json',events)
                manifest['final_population_alive'] = sum(p['health']>0 for p in world['players'])
                manifest['final_tick'] = world['tick']
                manifest['final_events'] = len(events)
            except Exception as error:
                manifest.update(status='incomplete',finalization_error=str(error))
        manifest['host_cleanup'] = stop(host)
        manifest['service_cleanup'] = stop(service)
        cleanup = [*manifest['worker_cleanup'], manifest['host_cleanup'], manifest['service_cleanup']]
        if any(not result['stopped'] or result.get('forced') for result in cleanup):
            manifest['status'] = 'incomplete'
        manifest['finished_at'] = time.time()
        write(out/'manifest.json',manifest)
        for handle in handles: handle.close()
    print(json.dumps({k:manifest.get(k) for k in ('status','error','worker_exit_codes','finalization_error','final_tick','final_events','final_population_alive','service_cleanup')},indent=2))
    return 0 if manifest['status']=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
