#!/usr/bin/env python3
"""One fresh database/service per measurement; real authority, no model calls.

Retains the volume and evidence after stopping the owned service. The existing
36-actor diagnostic supplies identical requests and cleanup for both candidates.
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import urllib.request

from run_authority36_probe import execute_case


IMAGE = 'dd611a1fe408fb1c5e898db119826b5929d64afb324d073a63db2ef69e29cc0c'
SERVER = 'http://127.0.0.1:3103'
ROOT = Path(__file__).resolve().parents[1]


def run(*args, timeout=60):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed: {p.stderr[:1000]}')
    return p.stdout


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_migration(cli, config, owner_identity, database, baseline, candidate, out):
    """Upgrade only a fresh fixture DB; never an existing experiment archive."""
    from owner_snapshot import export_world
    out.mkdir()
    run_id = 'sim-native-migration-' + str(time.time_ns())
    result = dict(database=database, run=run_id, baseline_sha256=digest(baseline),
                  candidate_sha256=digest(candidate), passed=False, model_calls=0)
    granted = False

    def invoke(verb, *args):
        return run(str(cli), '--config-path', str(config), verb, database, *args,
                   '--server', SERVER, '--no-config', timeout=60)

    def call(name, *args):
        return invoke('call', name, *(json.dumps(arg) for arg in args), '-y')

    def rows(query):
        return json.loads(invoke('sql', query, '--format', 'json'))[0]['rows']

    def audit():
        return sorted((json.loads(row[0]) for row in rows(
            f"SELECT json FROM sim_audit WHERE run = '{run_id}'")), key=lambda event: event['id'])

    try:
        invoke('publish', '--bin-path', str(baseline), '-y')
        scenario = json.loads((ROOT / 'scenarios/survival.json').read_text())
        call('sim_create_participant', run_id, json.dumps(scenario, separators=(',', ':')))
        call('sim_grant_client', run_id, owner_identity, False, 1)
        granted = True
        for request_id, command in [
            ('migration-read', dict(op='read_observation', after=0, limit=16)),
            ('migration-speech', dict(op='speak', text='Retained across storage migration.', expires_tick=10))]:
            call('sim_participant_command', json.dumps(dict(api_version='sao-participant-v1',
                 request_id=request_id, control_epoch=1, command=command), separators=(',', ':')))
        before = export_world(call, run_id)
        before_audit = audit()
        write(out / 'before.json', dict(world=before, events=before_audit))
        assert before['participants']['1']['evidence_leases'], 'fixture needs retained evidence'
        assert before['participants']['1']['speech'], 'fixture needs pending physical speech'
        invoke('publish', '--bin-path', str(candidate), '-y')
        call('sim_migrate_native_state', run_id)
        after = export_world(call, run_id)
        after_audit = audit()
        write(out / 'after.json', dict(world=after, events=after_audit))
        assert before == after, 'migration changed canonical World'
        assert before_audit == after_audit, 'migration changed audit evidence'
        assert not rows(f"SELECT id FROM sim_world_blob WHERE run = '{run_id}'"), 'legacy blobs remain'
        call('sim_migrate_native_state', run_id)
        assert export_world(call, run_id) == after, 'migration is not idempotent'
        call('sim_step', run_id)
        continued = export_world(call, run_id)
        continued_audit = audit()
        write(out / 'continued.json', dict(world=continued, events=continued_audit))
        assert continued['timing']['time_ms'] == before['timing']['time_ms'] + 2500
        assert any(e['kind'] == 'speech' and e['data']['text'] == 'Retained across storage migration.'
                   for e in continued_audit), 'queued speech did not execute after migration'
        assert not any(e['kind'] in ('script_error', 'script_tick_failed') for e in continued_audit)
        result.update(passed=True, exact_world=True, exact_audit=True,
                      idempotent=True, legacy_blobs_collected=True, queued_speech_executed=True)
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        if granted:
            try:
                call('sim_revoke_client', owner_identity)
                result['remaining_grants'] = len(rows(f"SELECT actor FROM sim_client_access WHERE run = '{run_id}'"))
                assert result['remaining_grants'] == 0
            except Exception as error:
                result['cleanup_error'] = str(error)
                result['passed'] = False
        write(out / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wasm', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', default=IMAGE,
                        help='Explicit standalone image for isolated runtime comparisons; default is the frozen 2.1.0 image')
    parser.add_argument('--capture-module-logs', action='store_true',
                        help='Retain module logs after the workload for opt-in diagnostic builds')
    parser.add_argument('--case', choices=('clock', 'status', 'reads'), default='reads')
    parser.add_argument('--page-pool-mib', type=int, default=8192)
    parser.add_argument('--access-probe', type=Path,
                        help='Optional no-model access check after the measured workload; uses separate fresh runs')
    parser.add_argument('--migration-baseline-wasm', type=Path,
                        help='Optional old module used only to create a separate fresh migration fixture database')
    parser.add_argument('--scenario', type=Path, default=ROOT / 'scenarios/faction-world-reality.json')
    parser.add_argument('--window-seconds', type=int, default=60)
    parser.add_argument('--round-seconds', type=int, nargs='+', default=[5, 20, 35, 50])
    parser.add_argument('--setup-seconds', type=int, default=120)
    parser.add_argument('--max-log-mib', type=int, default=4096)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.page_pool_mib <= 8192:
        parser.error('page pool must be 0..8192 MiB')
    if not 60 <= args.window_seconds <= 300 or not 120 <= args.setup_seconds <= 240:
        parser.error('bounded window 60..300s and setup 120..240s required')
    if (not args.round_seconds or len(args.round_seconds) > 20
            or args.round_seconds != sorted(set(args.round_seconds))
            or any(s <= 0 or s + 10 > args.window_seconds for s in args.round_seconds)):
        parser.error('ordered rounds must leave ten seconds before the end')
    if not 256 <= args.max_log_mib <= 8192:
        parser.error('log guard must be 256..8192 MiB')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    wasm, probe = args.wasm.resolve(), args.probe.resolve()
    scenario_path = args.scenario.resolve()
    scenario = json.loads(scenario_path.read_text())
    actors = [p['id'] for p in scenario['players']]
    assert len(actors) == len(set(actors)) and len(actors) in (36, 72, 144)
    write(out / 'scenario.json', scenario)
    cli = Path.home() / '.local/share/spacetime/bin/2.7.1/spacetimedb-cli'
    manifest = dict(case=args.case, server=SERVER, image=args.image,
                    page_pool_bytes=args.page_pool_mib * 1024**2,
                    service_memory_limit_bytes=12 * 1024**3, extra_swap_bytes=0,
                    wasm=str(wasm), wasm_sha256=digest(wasm),
                    probe=str(probe), probe_sha256=digest(probe),
                    runner_sha256=digest(Path(__file__)),
                    capture_module_logs=args.capture_module_logs,
                    case_runner_sha256=digest(ROOT / 'scripts/run_authority36_probe.py'),
                    scenario_sha256=digest(scenario_path), model_calls=0,
                    active_seconds=args.window_seconds, participants=len(actors), create_transport='http' if len(actors)>36 else 'cli',
                    read_round_seconds=args.round_seconds, setup_seconds=args.setup_seconds,
                    receipt_deadline_seconds=10,
                    resource_guards=dict(service_rss_bytes=11*1024**3, host_available_bytes=3*1024**3,
                        host_disk_free_bytes=8*1024**3, retained_log_bytes=args.max_log_mib*1024**2),
                    observer='procedure snapshots only at paused boundaries',
                    metrics='whole isolated service, exactly one database',
                    capture_gap_seconds=1, started_wall_ms=time.time_ns() // 10**6)
    write(out / 'manifest.json', manifest)
    if not args.execute:
        print(json.dumps(dict(prepared=True, output=str(out))))
        return
    # Resolve tags once, then use the immutable local image for the whole attempt.
    image_info = json.loads(run('podman', 'image', 'inspect', args.image))[0]
    image = image_info['Id']
    manifest['resolved_image_id'] = image
    manifest['image_repo_digests'] = image_info.get('RepoDigests', [])
    manifest['server_version'] = run('podman', 'run', '--rm', '--entrypoint',
        '/opt/spacetime/spacetimedb-standalone', image, '--version').strip()
    write(out / 'manifest.json', manifest)
    if len(actors) > 36:
        # Validate the exact seed through the production kernel before creating
        # a service. A failed preflight is never an active workload attempt.
        checked = json.loads(run(str(probe), '--check-fixture', str(scenario_path), timeout=60))
        assert checked.get('offline_fixture_valid') and checked.get('actors') == len(actors)
        write(out / 'fixture-preflight.json', checked)
    suffix = str(time.time_ns())
    container = 'sao-native-state-' + suffix
    volume = container + '-home'
    database = 'sim-authority36-' + args.case + '-' + suffix
    credentials = ROOT / '.local/credentials' / container
    credentials.mkdir(mode=0o700, parents=True)
    config_path = credentials / 'owner.toml'
    stopped = threading.Event()
    monitor_errors = []
    abort = []
    result = dict(container=container, volume=volume, database=database)
    created = False

    def monitor(pid):
        with (out / 'memory.jsonl').open('w') as samples:
            while not stopped.is_set():
                started = time.monotonic()
                try:
                    now = time.time_ns() // 10**6
                    with urllib.request.urlopen(SERVER + '/v1/metrics', timeout=3) as response:
                        metrics = response.read().decode()
                    (out / 'metrics' / f'{now}.prom').write_text(metrics)
                    proc = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
                    host = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
                    values = dict(wall_ms=now, rss_bytes=int(proc['VmRSS'].split()[0]) * 1024,
                                  hwm_bytes=int(proc['VmHWM'].split()[0]) * 1024,
                                  anon_bytes=int(proc['RssAnon'].split()[0]) * 1024,
                                  swap_bytes=int(proc['VmSwap'].split()[0]) * 1024,
                                  host_available_bytes=int(host['MemAvailable'].split()[0]) * 1024)
                    values['host_disk_free_bytes'] = shutil.disk_usage(ROOT).free
                    values['retained_log_bytes'] = sum(float(line.rsplit(' ',1)[1]) for line in metrics.splitlines()
                        if line.startswith('spacetime_message_log_size_bytes{'))
                    samples.write(json.dumps(values) + '\n')
                    samples.flush()
                    if (values['host_available_bytes'] < 3 * 1024**3 or values['rss_bytes'] > 11 * 1024**3
                            or values['host_disk_free_bytes'] < 8 * 1024**3
                            or values['retained_log_bytes'] > args.max_log_mib * 1024**2):
                        abort.append(dict(reason='resource guard', **values))
                        run('podman', 'stop', '--time', '5', container, timeout=15)
                        return
                except Exception as error:
                    monitor_errors.append(str(error))
                stopped.wait(max(0, 1 - (time.monotonic() - started)))

    thread = None
    try:
        # Every invocation has a distinct volume; no existing service is reused.
        run('podman', 'run', '--rm', '--user', 'spacetime', '--volume', volume + ':/home/spacetime',
            '--entrypoint', '/bin/sh', image, '-c',
            'umask 077; mkdir -p /home/spacetime/.config/spacetime; '
            'openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out /home/spacetime/.config/spacetime/id_ecdsa && '
            'openssl ec -in /home/spacetime/.config/spacetime/id_ecdsa -pubout -out /home/spacetime/.config/spacetime/id_ecdsa.pub')
        command = ['podman', 'run', '--detach', '--name', container, '--user', 'spacetime',
                   '--label', 'sao.purpose=native-state-benchmark', '--publish', '127.0.0.1:3103:3000',
                   '--volume', volume + ':/home/spacetime', '--memory', '12g', '--memory-swap', '12g',
                   '--pids-limit', '1024', '--restart', 'no', '--entrypoint', '/opt/spacetime/spacetimedb-standalone',
                   image, 'start', '--listen-addr', '0.0.0.0:3000', '--data-dir', '/home/spacetime/data',
                   '--non-interactive', '--page_pool_max_size', str(manifest['page_pool_bytes']),
                   '--jwt-pub-key-path', '/home/spacetime/.config/spacetime/id_ecdsa.pub',
                   '--jwt-priv-key-path', '/home/spacetime/.config/spacetime/id_ecdsa']
        write(out / 'service-command.json', command)
        run(*command)
        created = True
        for _ in range(50):
            try:
                with urllib.request.urlopen(urllib.request.Request(SERVER + '/v1/identity', method='POST'), timeout=2) as response:
                    identity = json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('service did not become ready')
        config_path.write_text('default_server = ' + json.dumps(SERVER) + '\nspacetimedb_token = ' + json.dumps(identity['token']) + '\n')
        os.chmod(config_path, 0o600)
        info = json.loads(run('podman', 'inspect', container))[0]
        result['pid'] = info['State']['Pid']
        (out / 'metrics').mkdir()
        # Verify telemetry before publishing or creating any workload.
        with urllib.request.urlopen(SERVER + '/v1/metrics', timeout=3) as response:
            (out / 'metrics' / 'ready.prom').write_bytes(response.read())
        thread = threading.Thread(target=monitor, args=(result['pid'],), daemon=True)
        thread.start()
        published = run(str(cli), '--config-path', str(config_path), 'publish', database,
                        '--bin-path', str(wasm), '--server', SERVER, '--no-config', '-y', timeout=60)
        (out / 'publish.log').write_text(published)
        call_args = SimpleNamespace(server=SERVER, cli=cli, cli_config=config_path,
                                    probe_binary=probe, implementation=ROOT, owner_snapshot_api='procedure',
                                    window_seconds=args.window_seconds, read_round_seconds=args.round_seconds,
                                    setup_seconds=args.setup_seconds, create_http=len(actors) > 36)
        result['case'] = execute_case(call_args, out / args.case, args.case, database,
                                     json.dumps(scenario, separators=(',', ':')), actors)
        if args.case == 'reads':
            reads = json.loads((out / args.case / 'read-results.json').read_text())
            results = reads.get('results', [])
            result['read_deadlines_pass'] = (len(results) == len(actors) * len(args.round_seconds)
                and not reads.get('unresolved_client_results')
                and all(r.get('client_outcome') == 'receipt_ok' and r.get('own_observation_verified')
                        and r.get('elapsed_ms', 10001) <= 10000 for r in results))
        result['measurement_end_wall_ms'] = time.time_ns() // 10**6
        if not result['case'].get('completed_protocol') or abort:
            raise RuntimeError('workload failed; optional compatibility checks were not started')
        if args.access_probe or args.migration_baseline_wasm:
            # Keep the performance sample population exactly the declared one.
            # The access check creates its own two small runs after measurement.
            stopped.set()
            thread.join(timeout=5)
            thread = None
        if args.access_probe:
            access_out = out / 'access'
            access_out.mkdir()
            access_config = dict(server=SERVER, database=database,
                                 run='sim-native-access-' + suffix, output=str(access_out),
                                 credentials=str(credentials / 'access'), cli=str(cli), cli_config=str(config_path))
            write(access_out / 'config.json', access_config)
            write(access_out / 'manifest.json', dict(probe=str(args.access_probe.resolve()),
                  probe_sha256=digest(args.access_probe.resolve()), measured_workload_complete=True))
            (access_out / 'helper.log').write_text(run(str(args.access_probe.resolve()), str(access_out / 'config.json'), timeout=180))
            result['access'] = json.loads((access_out / 'result.json').read_text())
        if args.migration_baseline_wasm:
            result['migration'] = verify_migration(cli, config_path, identity['identity'],
                'sim-authority36-migration-' + suffix, args.migration_baseline_wasm.resolve(), wasm, out / 'migration')
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        stopped.set()
        if thread:
            thread.join(timeout=5)
        if created and args.capture_module_logs:
            try:
                (out / 'module-logs.jsonl').write_text(run(str(cli), '--config-path', str(config_path),
                    'logs', database, '--server', SERVER, '--no-config', '--format', 'json', timeout=30))
            except Exception as error:
                result['module_log_error'] = str(error)
        result['monitor_errors'] = monitor_errors
        result['resource_abort'] = abort
        if created:
            try:
                logs = subprocess.run(['podman', 'logs', container], capture_output=True,
                                      text=True, timeout=15)
                (out / 'service.log').write_text(logs.stdout + logs.stderr)
                result['service_log_exit_code'] = logs.returncode
            except Exception as error:
                result['service_log_error'] = str(error)
            try:
                result['before_stop'] = json.loads(run('podman', 'inspect', container))[0]['State']
                run('podman', 'stop', '--time', '10', container, timeout=20)
                result['after_stop'] = json.loads(run('podman', 'inspect', container))[0]['State']
            except Exception as error:
                result['stop_error'] = str(error)
        result['finished_wall_ms'] = time.time_ns() // 10**6
        write(out / 'result.json', result)
    passed = (result.get('case', {}).get('completed_protocol') and not monitor_errors and not abort
              and result.get('read_deadlines_pass', args.case != 'reads')
              and not result.get('error') and not result.get('stop_error')
              and (not args.access_probe or result.get('access', {}).get('passed'))
              and (not args.migration_baseline_wasm or result.get('migration', {}).get('passed'))
              and not result.get('after_stop', {}).get('Running', True))
    print(json.dumps(dict(completed=bool(passed), output=str(out))), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
