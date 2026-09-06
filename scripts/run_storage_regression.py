#!/usr/bin/env python3
"""Real 4-person normalized-storage regression on a supplied NEW local --active.

Creates only its own sim-storage-regression-* run. No host, inference, database
publication, compilation, or existing-run mutation. Keep replica WAL measurement
active while owner SQL, participant status and observer/client views materialize.
Requires the separately built participant_storage_probe bridge example.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

PREFIX = 'sim-storage-regression-'


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')) + '\n')
    temporary.replace(path)


def wal_sample(folder):
    """Observe physical WAL files; never infer write volume from compact DB rows."""
    files = {}
    for path in folder.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:  # log rotation while sampling
            continue
        files[str(path.relative_to(folder))] = dict(inode=stat.st_ino, size=stat.st_size,
            allocated_bytes=stat.st_blocks * 512, mtime_ns=stat.st_mtime_ns)
    return dict(wall_ms=time.time_ns() // 1_000_000,
                logical_bytes=sum(f['size'] for f in files.values()),
                allocated_bytes=sum(f['allocated_bytes'] for f in files.values()), files=files)


def wal_result(samples):
    if len(samples) < 2:
        return dict(measured=False)
    positive_logical = positive_allocated = 0
    for before, after in zip(samples, samples[1:]):
        previous = {(f['inode'], name): f for name, f in before['files'].items()}
        for name, current in after['files'].items():
            old = previous.get((current['inode'], name), {})
            positive_logical += max(0, current['size'] - old.get('size', 0))
            positive_allocated += max(0, current['allocated_bytes'] - old.get('allocated_bytes', 0))
    elapsed = (samples[-1]['wall_ms'] - samples[0]['wall_ms']) / 1000
    net = samples[-1]['logical_bytes'] - samples[0]['logical_bytes']
    return dict(measured=True, elapsed_seconds=elapsed,
        before_logical_bytes=samples[0]['logical_bytes'], after_logical_bytes=samples[-1]['logical_bytes'],
        net_logical_growth_bytes=net, sampled_positive_logical_growth_bytes=positive_logical,
        net_allocated_growth_bytes=samples[-1]['allocated_bytes'] - samples[0]['allocated_bytes'],
        sampled_positive_allocated_growth_bytes=positive_allocated,
        peak_logical_bytes=max(s['logical_bytes'] for s in samples),
        net_logical_bytes_per_second=net / elapsed if elapsed else None,
        sampled_positive_logical_bytes_per_second=positive_logical / elapsed if elapsed else None,
        measurement='Actual replica WAL file sizes and allocated blocks, sampled while views are subscribed. '
                    'Includes segment preallocation; overwritten preallocated bytes are not counted as appended growth. '
                    'No estimate based on compact state rows.')


def make_scenario(source):
    scenario = copy.deepcopy(source)
    assert [p['id'] for p in scenario['players']] == [1, 2, 3, 4]
    scenario.update(name='Explicit no-inference normalized-storage regression', max_ticks=1000,
                    weather=None, starting_behaviors={}, knowledge={})
    for player in scenario['players']:
        actor = player['id']
        player.update(position=84, controller='human', health=100, hunger=10, energy=100, food=8)
        scenario['knowledge'][str(actor)] = [dict(id=f'storage-private-{actor}', topic='Private fixture note',
            text=f'STORAGE_PRIVATE_ACTOR_{actor}_ ' + ('A personally retained test observation. ' * 16),
            location=None, confidence=40)]
    for site in scenario['sites']:
        site['hazard'] = 0
    if scenario.get('infrastructure'):
        scenario['infrastructure']['bodies'] = {}  # Ordinary nutrient support; no forced charging loop.
    for arena in scenario.get('arenas', []):
        arena['controllers'] = {str(actor): 'external' for actor in arena['actors']}
    return scenario


def assert_contiguous(snapshot):
    world, events = snapshot['world'], snapshot['events']
    assert world['run'].startswith(PREFIX)
    assert [e['id'] for e in events] == list(range(1, world['next_event']))
    assert all(e['run'] == world['run'] and e['tick'] <= world['tick'] for e in events)
    assert not world.get('events'), 'unflushed events in paused owner export'
    assert not any(e['kind'] in ('model_request', 'model_result', 'script_error', 'script_tick_failed',
                                 'clock_recovery_required') for e in events)
    assert all(player['health'] > 0 for player in world['players'])
    assert all(len(world['participants'][str(actor)]['evidence_leases']) == 4 for actor in range(1, 5))
    assert all(len(world['participants'][str(actor)]['experiences']) == 256 for actor in range(1, 5)), 'actual trace retention never filled'
    assert all(world['participants'][str(actor)]['experiences'][0]['cursor'] > 1 for actor in range(1, 5)), 'actual trace never rotated'
    return dict(contiguous=True, events=len(events), next_event=world['next_event'],
                time_ms=world['timing']['time_ms'], updates=world['timing']['updates'])


def verify_final_leases(snapshot, probe):
    world = snapshot['world']
    result = []
    for personal in probe['final_participants']:
        actor = personal['actor']
        leases = world['participants'][str(actor)]['evidence_leases']
        checks = []
        for read in personal['last_reads']:
            lease = next(l for l in leases if l['request_id'] == read['request_id'])
            observation = copy.deepcopy(lease['observation'])
            observation['experiences'] = lease['experiences']
            exact = observation == read['observation']
            cursor = lease['observed_cursor'] == observation['latest_cursor'] == observation['evidence_lease']['observed_cursor']
            expiry = lease['expires_ms'] == observation['time_ms'] + 330000
            checks.append(dict(request_id=read['request_id'], exact=exact, cursor_exact=cursor, expiry_exact=expiry))
        assert len(checks) == 4 and all(c['exact'] and c['cursor_exact'] and c['expiry_exact'] for c in checks)
        # Private subscription exactly equals the kernel reconstruction checked inside Rust.
        assert personal['client_view']['time_ms'] == world['timing']['time_ms']
        result.append(dict(actor=actor, reads=checks))
    assert probe['observer']['time_ms'] == world['timing']['time_ms']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--active', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe-binary', type=Path, required=True)
    parser.add_argument('--implementation', type=Path, default=Path.cwd())
    parser.add_argument('--credential-dir', type=Path)
    parser.add_argument('--cli', type=Path, default=Path.home()/'.local/share/spacetime/bin/2.7.1/spacetimedb-cli')
    parser.add_argument('--cli-config', type=Path)
    parser.add_argument('--private-table', action='append', required=True, help='Each actual private normalization table; owner existence and nonowner denial both checked')
    parser.add_argument('--seconds', type=int, choices=range(60, 91), default=75)
    parser.add_argument('--read-interval-ms', type=int, default=1000)
    parser.add_argument('--sql-interval-seconds', type=float, default=1.0)
    measurement = parser.add_mutually_exclusive_group(required=True)
    measurement.add_argument('--wal-dir', type=Path, help='Dedicated new database replica commit-log directory, not all server storage')
    measurement.add_argument('--external-wal-samples', type=Path, help='External sampler JSONL using wal_sample schema; no pass until before/after samples exist')
    parser.add_argument('--max-wal-growth-mib', type=int, default=2048)
    parser.add_argument('--min-free-gib', type=int, default=4)
    args = parser.parse_args()
    implementation = args.implementation.resolve()
    active = json.loads(args.active.read_text())
    server, db = active['server'], active['db']
    assert server.startswith(('http://127.0.0.1:', 'http://localhost:')), 'local authority required'
    assert re.fullmatch(r'[a-zA-Z0-9_-]+', db), 'unexpected database identifier'
    assert args.probe_binary.is_file(), 'build the single bridge example separately before running'
    assert args.read_interval_ms >= 500 and args.sql_interval_seconds >= 0.5
    if args.wal_dir:
        args.wal_dir = args.wal_dir.resolve()
        assert args.wal_dir.is_dir() and any(args.wal_dir.rglob('*')), 'actual replica WAL directory required'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    credential_dir = (args.credential_dir or implementation/'.local/credentials').resolve()
    credential_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cli_config = (args.cli_config or implementation/'.local/credentials/bevy-cli.toml').resolve()
    run = PREFIX + str(time.time_ns())
    report = dict(run=run, database=db, active_source=str(args.active.resolve()), original_active_run=active.get('run'),
                  phase='setup', all_pass=False, model_calls=0, scheduled_tick_ms=50, requested_seconds=args.seconds,
                  owner_sql_samples=[], wal_samples=[], cleanup_errors=[])
    process = None
    created = paused = False

    def control(verb, *values):
        command = [str(args.cli), '--config-path', str(cli_config), verb, db, *values,
                   '--server', server, '--no-config']
        response = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if response.returncode:
            raise RuntimeError(f'Authority {verb} failed (output suppressed)')
        return response.stdout

    def call(name, *values):
        return control('call', name, *map(json.dumps, values), '-y')

    def rows(query):
        return json.loads(control('sql', query, '--format', 'json'))[0]['rows']

    def read_world():
        result = rows(f"SELECT state FROM sim_run WHERE id = '{run}'")
        assert len(result) == 1, 'owner sim_run compatibility view did not return exactly one own run'
        raw = result[0][0]
        return json.loads(raw), len(raw.encode())

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        # The --active file supplies the normalized database only. Its run stays untouched.
        for table in args.private_table:
            assert re.fullmatch(r'[a-zA-Z0-9_]+', table), 'invalid table identifier'
            rows(f'SELECT COUNT(*) AS count FROM {table}')
        other_clocks = rows('SELECT run, paused FROM sim_client_clock')
        assert not any(not row[1] for row in other_clocks), 'another scheduled run is active; WAL attribution would be ambiguous'
        scenario = make_scenario(json.loads((implementation/'scenarios/infrastructure-baseline.json').read_text()))
        write(out/'scenario.json', scenario)
        call('sim_create_participant', run, json.dumps(scenario, separators=(',', ':')))
        created = True
        call('sim_setup_client_clock', run, 'live_fixture')
        call('sim_operator_clock', run, 50, True)
        config = dict(server=server, database=db, run=run, output=str(out), credential_dir=str(credential_dir),
                      cli=str(args.cli.resolve()), cli_config=str(cli_config), duration_seconds=args.seconds,
                      read_interval_ms=args.read_interval_ms, private_tables=args.private_table)
        write(out/'probe-config.json', config)
        with (out/'probe.log').open('w') as log:
            process = subprocess.Popen([str(args.probe_binary.resolve()), str(out/'probe-config.json')],
                                       cwd=implementation, stdout=log, stderr=log)
        ready_deadline = time.monotonic() + 120
        while not (out/'ready.json').exists():
            if process.poll() is not None:
                raise RuntimeError('participant setup failed; see probe result')
            if time.monotonic() > ready_deadline:
                raise TimeoutError('participant setup timed out')
            time.sleep(.1)
        before, state_bytes = read_world()
        report['before'] = dict(wall_ms=time.time_ns()//1_000_000, time_ms=before['timing']['time_ms'],
                                updates=before['timing']['updates'], self_contained_state_bytes=state_bytes)
        if args.wal_dir:
            report['wal_samples'].append(wal_sample(args.wal_dir))
        call('sim_operator_clock', run, 50, False)
        write(out/'go.json', dict(wall_ms=time.time_ns()//1_000_000))
        report['phase'] = 'measuring'
        write(out/'storage-regression.json', report)
        deadline = time.monotonic() + args.seconds + 40
        while not (out/'reads-done.json').exists():
            if process.poll() is not None:
                raise RuntimeError('participant probe exited during measurement')
            if time.monotonic() > deadline:
                raise TimeoutError('bounded measurement timed out')
            start = time.monotonic()
            world, size = read_world()  # Concurrent real owner materialized-view SELECT.
            report['owner_sql_samples'].append(dict(wall_ms=time.time_ns()//1_000_000,
                sql_elapsed_ms=round((time.monotonic()-start)*1000, 3), tick=world['tick'],
                time_ms=world['timing']['time_ms'], updates=world['timing']['updates'],
                self_contained_state_bytes=size,
                trace_counts={a:len(p['experiences']) for a,p in world['participants'].items()},
                lease_counts={a:len(p['evidence_leases']) for a,p in world['participants'].items()}))
            if args.wal_dir:
                sample = wal_sample(args.wal_dir)
                report['wal_samples'].append(sample)
                net = sample['logical_bytes'] - report['wal_samples'][0]['logical_bytes']
                if net > args.max_wal_growth_mib * 1024**2:
                    raise RuntimeError('actual WAL growth exceeded configured regression bound')
                stat = os.statvfs(args.wal_dir)
                if stat.f_bavail * stat.f_frsize < args.min_free_gib * 1024**3:
                    raise RuntimeError('replica volume free space crossed configured floor')
            write(out/'storage-regression.json', report)
            time.sleep(max(0, args.sql_interval_seconds - (time.monotonic()-start)))
        call('sim_operator_pause', run)
        paused = True
        world, size = read_world()
        events = sorted((json.loads(row[0]) for row in rows(f"SELECT json FROM sim_audit WHERE run = '{run}'")), key=lambda e:e['id'])
        assert read_world()[0] == world, 'paused state changed during final contiguous capture'
        snapshot = dict(world=world, events=events)
        report['final_capture'] = assert_contiguous(snapshot)
        write(out/'snapshot.json', snapshot)
        report['snapshot_sha256'] = hashlib.sha256((out/'snapshot.json').read_bytes()).hexdigest()
        report['after'] = dict(wall_ms=time.time_ns()//1_000_000, time_ms=world['timing']['time_ms'],
                               updates=world['timing']['updates'], self_contained_state_bytes=size)
        if args.wal_dir:
            report['wal_samples'].append(wal_sample(args.wal_dir))
        write(out/'paused.json', dict(time_ms=world['timing']['time_ms'], tick=world['tick'], updates=world['timing']['updates']))
        report['probe_exit_code'] = process.wait(timeout=45)
        probe = json.loads((out/'participant-storage-result.json').read_text())
        assert probe['all_pass'] and report['probe_exit_code'] == 0, 'participant/lease/view probe failed'
        report['final_lease_exactness'] = verify_final_leases(snapshot, probe)
        assert probe['kernel_world_roundtrip_exact'] and probe['kernel_status_exact'], 'kernel reconstruction changed API/serde'
        if args.external_wal_samples:
            report['wal_samples'] = [json.loads(line) for line in args.external_wal_samples.read_text().splitlines() if line.strip()]
        report['wal'] = wal_result(report['wal_samples'])
        assert report['wal']['measured'], 'actual before/after WAL measurement is mandatory'
        assert report['wal_samples'][0]['wall_ms'] <= report['before']['wall_ms'] + 1000, 'WAL start sample misses active subscriptions'
        assert report['wal_samples'][-1]['wall_ms'] >= report['after']['wall_ms'], 'WAL end sample precedes final subscribed capture'
        simulated = report['after']['time_ms'] - report['before']['time_ms']
        wall_elapsed = report['after']['wall_ms'] - report['before']['wall_ms']
        updates = report['after']['updates'] - report['before']['updates']
        report['cadence'] = dict(simulated_ms=simulated, wall_ms=wall_elapsed, simulation_to_wall_ratio=simulated/wall_elapsed,
                                 updates=updates, updates_per_wall_second=updates/(wall_elapsed/1000))
        assert simulated >= 60_000, 'did not advance at least 60 seconds on real scheduled clock'
        assert updates > 0 and all(b['time_ms'] >= a['time_ms'] and b['updates'] >= a['updates']
                                  for a,b in zip(report['owner_sql_samples'], report['owner_sql_samples'][1:]))
        report.update(phase='completed', all_pass=True, read_count=len(probe['reads']),
            read_errors=sum(not r['read_ok'] for r in probe['reads']),
            participant_connections=4, observer_connections=1,
            final_state_bytes=size, audit_bytes=len(json.dumps(events).encode()))
    except (Exception, KeyboardInterrupt) as error:
        report.update(phase='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed', error=f'{type(error).__name__}: {error}')
    finally:
        write(out/'stop.json', dict(wall_ms=time.time_ns()//1_000_000))
        if created and not paused:
            try:
                call('sim_operator_pause', run)
                paused = True
            except Exception as error:
                report['cleanup_errors'].append('Own-run pause: '+type(error).__name__)
        if process and process.poll() is None:
            if not (out/'paused.json').exists():
                write(out/'paused.json', dict(aborted=True))
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
        identities = []
        for name in ('identities.json', 'ready.json'):
            if (out/name).exists():
                value = json.loads((out/name).read_text())
                identities = value if isinstance(value,list) else value['identities']
                break
        for identity in identities:
            try:
                call('sim_revoke_client', identity)
            except Exception as error:
                report['cleanup_errors'].append('Own grant revoke: '+type(error).__name__)
        report['own_run_paused'] = paused
        report['wal'] = wal_result(report['wal_samples'])
        write(out/'storage-regression.json', report)
    print(json.dumps({k:report.get(k) for k in ('run','phase','all_pass','read_count','cadence','wal','error')}))
    if not report['all_pass']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
