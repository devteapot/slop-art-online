#!/usr/bin/env python3
"""Prepare or execute three fresh, isolated, no-model 36-person authority cases.

Default preparation performs no authority connection. Execution requires three
already published EMPTY databases on the exclusive localhost:3102 service.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time

PREFIX = 'sim-authority36-'
CASES = ('clock', 'status', 'reads')


def write(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, separators=(',', ':')) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(before, after, helper, reads, case):
    world, events = after['world'], after['events']
    assert helper.get('setup_ok') and helper.get('pause_acknowledged'), 'incomplete helper setup/pause'
    assert helper.get('connections_at_resume') == (0 if case == 'clock' else 36), 'wrong initial connection count'
    assert helper.get('connections_after_pause') == (0 if case == 'clock' else 36), 'connection loss during window'
    assert 60000 <= helper.get('pause_sent_elapsed_ms', 0), 'window shorter than 60s'
    assert [e['id'] for e in events] == list(range(1, world['next_event'])), 'noncontiguous audit'
    commands = [e for e in events if e['kind'] == 'participant_command']
    control = [e for e in events if e['kind'] == 'control_changed']
    assert len(control) == 36, 'expected identical 36 control changes before active window'
    disallowed = [e for e in events if e['kind'] in ('model_request', 'model_result', 'law_edit_staged', 'law_activated')]
    assert not disallowed, 'unexpected model/law activity'
    assert world['initial'] == before['world']['initial'], 'initial scenario mutated'
    assert all(e['data']['command']['op'] == 'read_observation' for e in commands), 'unexpected participant command'
    dispatched = reads.get('dispatched', [])
    assert len(dispatched) == (144 if case == 'reads' else 0), 'incomplete prospective read rounds'
    assert len({d['request_id'] for d in dispatched}) == len(dispatched)
    assert {e['data']['request_id'] for e in commands} <= {d['request_id'] for d in dispatched}
    if case != 'reads':
        assert not commands
    else:
        assert all(sum(d['actor'] == actor for d in dispatched) == 4 for actor in {d['actor'] for d in dispatched})
    command_map = {e['data']['request_id']: e for e in commands}
    receipts = {r['request_id']: dict(r, actor=int(actor))
                for actor, participant in world['participants'].items()
                for r in participant['receipts']}
    reconciled = []
    for dispatch in dispatched:
        rid = dispatch['request_id']
        event, receipt = command_map.get(rid), receipts.get(rid)
        client = next((r for r in reads.get('results', []) if r.get('request_id') == rid), None)
        if event:
            assert event['actor'] == dispatch['actor']
        if receipt:
            assert receipt['actor'] == dispatch['actor']
            if receipt['ok']:
                assert event and receipt['event'] == event['id']
        reconciled.append(dict(**dispatch, authority_event=event, authority_receipt=receipt,
                               client_result=client, authority_outcome=(
                                   'committed_ok' if receipt and receipt['ok'] else
                                   'committed_rejected' if receipt else
                                   'command_event_without_retained_receipt' if event else
                                   'absent_from_final_audit_and_receipts')))
    delta = world['timing']['time_ms'] - before['world']['timing']['time_ms']
    updates = world['timing']['updates'] - before['world']['timing']['updates']
    decision_tick_delta = world['tick'] - before['world']['tick']
    errors = [e for e in events if e['kind'] in ('script_error', 'script_tick_failed')]
    return dict(protocol_audit_pass=True, model_calls=0, command_count=len(commands),
                exact_scenario_preserved=True, simulation_delta_ms=delta, update_count=updates,
                decision_tick_delta=decision_tick_delta,
                simulation_seconds_to_configured_window_ratio=delta / 60000,
                update_count_divided_by_configured_window_seconds=updates / 60,
                resume_latency_ms=helper.get('resume_latency_ms'),
                pause_sent_elapsed_ms=helper.get('pause_sent_elapsed_ms'),
                resume_ack_to_pause_ack_ms=(helper.get('pause_sent_elapsed_ms', 0) + helper.get('pause_latency_ms', 0)),
                pause_overrun_ms=max(0, helper.get('pause_sent_elapsed_ms', 60000) - 60000),
                pause_latency_ms=helper.get('pause_latency_ms'), engine_errors=errors,
                request_reconciliation=reconciled,
                note='The status sample window is 60s after resume ACK. World delta can include simulation during resume latency and pause latency; dividing by 60 is a fixed-window normalization, not an exact active-time speed.')


def execute_case(args, out, case, database, scenario, actors):
    out.mkdir()
    credentials = out / 'credentials'
    credentials.mkdir(mode=0o700)
    run = PREFIX + case + '-' + str(time.time_ns())
    config = dict(server=args.server, database=database, run=run, case=case, output=str(out),
                  credential_dir=str(credentials), cli=str(args.cli.resolve()),
                  cli_config=str(args.cli_config.resolve()), actors=actors)
    write(out / 'config.json', config)
    report = dict(case=case, database=database, run=run, created=False, model_calls=0,
                  helper_ok=False, paused_verified=False, remaining_grants=None, cleanup_errors=[])
    process = None
    owner_api = getattr(args, 'owner_snapshot_api', 'sql')
    owner_checkpoints = []

    def record_owner_checkpoint(checkpoint, started, **values):
        owner_checkpoints.append(dict(checkpoint=checkpoint, api=owner_api,
            started_wall_ms=started, finished_wall_ms=time.time_ns() // 10**6, **values))
        write(out / 'owner-snapshot-checkpoints.json', owner_checkpoints)

    def cli(verb, *values):
        response = subprocess.run([str(args.cli), '--config-path', config['cli_config'], verb,
                                   database, *values, '--server', args.server, '--no-config'],
                                  capture_output=True, text=True, timeout=30)
        if response.returncode:
            raise RuntimeError(f'owner {verb} failed (output suppressed)')
        return response.stdout

    def call(name, *values):
        return cli('call', name, *map(json.dumps, values), '-y')

    def rows(query):
        if owner_api == 'procedure' and re.search(r'\bsim_run\b', query, re.IGNORECASE):
            raise RuntimeError('procedure observer contract forbids sim_run SQL materialization')
        return json.loads(cli('sql', query, '--format', 'json'))[0]['rows']

    def inventory(checkpoint):
        if owner_api == 'sql':
            return [row[0] for row in rows('SELECT id FROM sim_run')]
        from owner_snapshot import inventory as procedure_inventory
        started = time.time_ns() // 10**6
        ids = procedure_inventory(call)
        record_owner_checkpoint(checkpoint, started, owned_run_ids=ids)
        return ids

    def capture(name):
        started = time.time_ns() // 10**6
        if owner_api == 'procedure':
            from owner_snapshot import export_json
            state = export_json(call, run)
        else:
            raw = rows(f"SELECT state FROM sim_run WHERE id = '{run}'")
            assert len(raw) == 1
            state = raw[0][0]
        world = json.loads(state)
        events_raw = rows(f"SELECT json FROM sim_audit WHERE run = '{run}'")
        events = sorted((json.loads(x[0]) for x in events_raw), key=lambda e: e['id'])
        snapshot = dict(world=world, events=events, full_world_json_bytes=len(state.encode()),
                        audit_json_bytes=sum(len(r[0].encode()) for r in events_raw))
        write(out / name, snapshot)
        if owner_api == 'procedure':
            record_owner_checkpoint(name, started, run=run,
                                    full_world_json_bytes=snapshot['full_world_json_bytes'])
        return snapshot

    try:
        assert inventory('before-world-inventory') == [], 'database must be freshly published and empty'
        assert rows('SELECT run, paused FROM sim_client_clock') == [], 'unexpected preexisting clock'
        report['create_attempted'] = True
        call('sim_create_participant', run, scenario)
        report['created'] = True
        call('sim_setup_client_clock', run, 'live_fixture')
        call('sim_operator_clock', run, 50, True)
        before = capture('baseline-snapshot.json')
        assert len(before['world']['players']) == 36
        with (out / 'helper.log').open('w') as log:
            process = subprocess.Popen([str(args.probe_binary.resolve()), str(out / 'config.json')],
                                       cwd=args.implementation, stdout=log, stderr=log)
            try:
                report['helper_exit_code'] = process.wait(timeout=260)
            except subprocess.TimeoutExpired:
                raise RuntimeError('260s helper ceiling reached; no retry')
        report['helper_ok'] = report['helper_exit_code'] == 0
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        helper = json.loads((out / 'helper-result.json').read_text()) if (out / 'helper-result.json').exists() else {}
        try:
            if report.get('create_attempted'):
                # One safety pause if helper did not acknowledge. Preserve failure.
                if not helper.get('pause_acknowledged'):
                    report['cleanup_pause_attempted'] = True
                    call('sim_operator_pause', run)
                clocks = rows('SELECT run, paused FROM sim_client_clock')
                report['paused_verified'] = bool(clocks) and all(r[1] for r in clocks)
                assert report['paused_verified'], 'clock not authoritatively paused'
                after = capture('final-snapshot.json')
                if (out / 'baseline-snapshot.json').exists():
                    before = json.loads((out / 'baseline-snapshot.json').read_text())
                    reads = json.loads((out / 'read-results.json').read_text()) if (out / 'read-results.json').exists() else {}
                    checked = validate(before, after, helper, reads, case)
                    write(out / 'authority-validation.json', checked)
                    report['protocol_audit_pass'] = checked['protocol_audit_pass']
                samples = json.loads((out / 'status-samples.json').read_text()) if (out / 'status-samples.json').exists() else []
                start = helper.get('window_start_process_ms')
                active = [s for s in samples if start is not None and start <= s['elapsed_from_process_ms'] < start + 60000]
                late = [s for s in samples if start is not None and s['elapsed_from_process_ms'] >= start + 60000]
                sizes = sorted(s['body_bytes'] for s in active)
                write(out / 'payload-summary.json', dict(
                    status_samples_fixed_window=len(active), status_samples_after_window=len(late),
                    status_body_bytes_fixed_window=sum(sizes), status_body_bytes_p50=sizes[len(sizes)//2] if sizes else None,
                    status_body_bytes_max=max(sizes, default=None), samples_dropped=helper.get('samples_dropped'),
                    baseline_full_world_json_bytes=before['full_world_json_bytes'],
                    final_full_world_json_bytes=after['full_world_json_bytes'], final_audit_json_bytes=after['audit_json_bytes'],
                    note='JSON body sizes are payload measures, not network wire bytes. Status callback sampling excludes setup and pause overrun.'))
        except Exception as error:
            report['capture_or_pause_error'] = f'{type(error).__name__}: {error}'
        # Revoke only identities provisioned by this case, at most 36 with 8 workers.
        identities = json.loads((out / 'identities.json').read_text()) if (out / 'identities.json').exists() else []
        assert len(identities) <= 36
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(call, 'sim_revoke_client', identity) for identity in identities]
            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    report['cleanup_errors'].append(f'revoke: {type(error).__name__}: {error}')
        try:
            clocks = rows('SELECT run, paused FROM sim_client_clock')
            report['paused_verified'] = bool(clocks) and all(r[1] for r in clocks)
            report['remaining_grants'] = len(rows(f"SELECT actor FROM sim_client_access WHERE run = '{run}'"))
            if owner_api == 'procedure':
                assert inventory('after-cleanup-inventory') == [run], 'unexpected owner run inventory after cleanup'
            write(out / 'cleanup-verification.json', dict(clocks=clocks, remaining_grants=report['remaining_grants']))
        except Exception as error:
            report['cleanup_errors'].append(f'verify: {type(error).__name__}: {error}')
        report['cleanup_resolved'] = report['paused_verified'] and report['remaining_grants'] == 0 and not report['cleanup_errors']
        report['completed_protocol'] = (report['helper_ok'] and report.get('protocol_audit_pass', False)
                                        and report['cleanup_resolved'] and 'capture_or_pause_error' not in report)
        write(out / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--server', default='http://127.0.0.1:3102')
    parser.add_argument('--databases', nargs=3)
    parser.add_argument('--probe-binary', type=Path)
    parser.add_argument('--probe-source', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'server/bridge/examples/participant_authority36_probe.rs')
    parser.add_argument('--cli', type=Path, default=Path.home()/'.local/share/spacetime/bin/2.7.1/spacetimedb-cli')
    parser.add_argument('--cli-config', type=Path)
    parser.add_argument('--owner-snapshot-api', choices=('sql', 'procedure'), default='sql',
                        help='owner inventory/export contract; SQL keeps the original diagnostic workload')
    args = parser.parse_args()
    args.implementation = args.implementation.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    fixture = args.implementation / 'scenarios/faction-world-reality.json'
    source = fixture.read_bytes()
    scenario = json.loads(source)
    actors = [p['id'] for p in scenario['players']]
    assert len(set(actors)) == len(actors) == 36
    (out / 'scenario.json').write_bytes(source)
    manifest = dict(mode='execute' if args.execute else 'prepared_only', model_calls=0,
                    owner_snapshot_api=args.owner_snapshot_api,
                    owner_snapshot_contract=('owner sim_run SQL view inventory/export' if args.owner_snapshot_api == 'sql'
                                             else 'one-shot owner procedures; no sim_run SQL materialization; same mandatory baseline/final exports'),
                    owner_snapshot_helper_sha256=(sha(Path(__file__).with_name('owner_snapshot.py'))
                                                  if args.owner_snapshot_api == 'procedure' else None),
                    cases=list(CASES), scenario_source=str(fixture), scenario_sha256=sha(fixture),
                    scenario_copied_byte_exact=True, participants=36, inherited_policies_unchanged=True,
                    transport_json_whitespace_minified=True,
                    grant_setup_identical=True, territorial_editors_unchanged=True,
                    clock_interval_ms=50, fixed_wall_seconds=60, reads_per_actor=4,
                    read_round_seconds=[5,20,35,50], read_limit=128, read_timeout_seconds=10,
                    max_reads=144, retries=0, setup_cap_seconds=120, helper_cap_seconds=260,
                    owner_command_cap_seconds=30, paused_export_cap_seconds_per_query=30,
                    revoke_workers=8, revoke_cap_seconds=150,
                    no_full_world_exports_during_active_window=True,
                    no_observe_in_setup=True, no_policy_replacement=True,
                    stop_if_previous_cleanup_unresolved=True,
                    unresolved_coupling='C combines atomic-read creation and subscription delivery of retained observations; these costs are not isolated by A/B/C.',
                    scheduler_version='2.1.0', scheduler_semantics='reinsert interval after reducer completion at now + duration; no accumulated interval debt',
                    scheduler_source='https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/core/src/host/scheduler.rs#L300-L329',
                    helper_sha256=sha(args.probe_binary) if args.probe_binary else None,
                    helper_source_sha256=sha(args.probe_source),
                    runner_sha256=sha(Path(__file__)))
    write(out / 'prospective-manifest.json', manifest)
    if not args.execute:
        print(json.dumps(dict(prepared=True, authority_connections=0, output=str(out))))
        return
    assert args.server == 'http://127.0.0.1:3102'
    assert args.probe_binary and args.probe_binary.is_file() and args.cli_config and args.cli_config.is_file()
    assert args.databases and len(set(args.databases)) == 3
    assert all(re.fullmatch(PREFIX + case + r'-[a-zA-Z0-9-]+', db) for case, db in zip(CASES, args.databases))
    def interrupt(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    results = []
    for case, database in zip(CASES, args.databases):
        result = execute_case(args, out / case, case, database, json.dumps(scenario, separators=(',', ':')), actors)
        results.append(result)
        write(out / 'results.json', results)
        print(json.dumps(result), flush=True)
        if not result['cleanup_resolved']:
            break
    if len(results) != 3 or not all(r['completed_protocol'] for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
