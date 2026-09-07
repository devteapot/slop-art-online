#!/usr/bin/env python3
"""Exercise explicit outage recovery on a retained, stopped isolated deadline trial.

No timing/capacity claim: the original trial artifacts remain immutable. The owned
service is frozen for 62 seconds and is always unfrozen/stopped on cleanup.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request
from owner_snapshot import export_world, export_audit_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source = json.loads((args.trial / 'result.json').read_text())
    config = json.loads((args.trial / 'reads/config.json').read_text())
    manifest = json.loads((args.trial / 'manifest.json').read_text())
    assert manifest['deadline_clock'] and not source['after_stop']['Running']
    container = source['container']
    assert container.startswith('sao-native-state-') and config['server'] == 'http://127.0.0.1:3103'
    args.output.mkdir(parents=True, exist_ok=False)
    result = dict(passed=False, source=str(args.trial.resolve()), container=container,
                  frozen_seconds=62, capacity_claim=False)
    frozen = False
    def command(*values):
        p = subprocess.run(values, capture_output=True, text=True, timeout=60)
        if p.returncode: raise RuntimeError(f'{values[0]} {values[1]} failed')
        return p.stdout
    def call(name, *values):
        return command(config['cli'], '--config-path', config['cli_config'], 'call', config['database'],
                       name, *(json.dumps(v) for v in values), '--server', config['server'], '--no-config', '-y')
    def rows(query):
        return json.loads(command(config['cli'], '--config-path', config['cli_config'], 'sql', config['database'],
            query, '--server', config['server'], '--no-config', '--format', 'json'))[0]['rows']
    run_id = config['run']
    def capture(name):
        world = export_world(call, run_id)
        value = dict(world=world, clock=rows(f"SELECT paused FROM sim_client_clock WHERE run = '{run_id}'"),
            cadence=rows(f"SELECT pending_id, wakes, missed_slots, max_lateness_us FROM sim_clock_deadline WHERE run = '{run_id}'"))
        (args.output / name).write_text(json.dumps(value, separators=(',', ':'))+'\n')
        return value
    try:
        state = json.loads(command('podman', 'inspect', container))[0]['State']
        assert not state['Running'], 'source service is no longer stopped'
        command('podman', 'start', container)
        for _ in range(100):
            try:
                with urllib.request.urlopen(config['server'] + '/v1/ping', timeout=1): break
            except OSError: time.sleep(.1)
        before = capture('before.json')
        assert before['clock'] == [[True]] and before['cadence'][0][0] == 0
        call('sim_operator_clock', run_id, 50, False)
        command('podman', 'pause', container)
        frozen = True
        result['freeze_started_wall_ms'] = time.time_ns()//10**6
        print('Owned service frozen; testing the existing >60-second recovery rule.', flush=True)
        time.sleep(62)
        command('podman', 'unpause', container)
        frozen = False
        time.sleep(.5)
        after = capture('after-outage.json')
        assert after['clock'] == [[True]] and after['cadence'][0][0] == 0
        evidence = export_audit_json(call, run_id, after['world']['next_event'], start=before['world']['next_event'])
        (args.output/'recovery-events.json').write_text(json.dumps(evidence, indent=2)+'\n')
        recovery = [json.loads(e) for e in evidence if json.loads(e)['kind']=='clock_recovery_required']
        assert len(recovery)==1 and recovery[0]['data']['elapsed_ms'] > 60_000
        # No replay during the gap: only the tiny pre-freeze interval may advance.
        assert after['world']['timing']['time_ms'] - before['world']['timing']['time_ms'] < 2_000
        call('sim_operator_clock', run_id, 50, False)
        time.sleep(.5)
        call('sim_operator_pause', run_id)
        recovered = capture('after-explicit-resume.json')
        delta = recovered['world']['timing']['time_ms'] - after['world']['timing']['time_ms']
        assert 0 < delta < 2_000 and recovered['cadence'][0][0] == 0
        result.update(passed=True, recovery_pause=True, elapsed_ms=recovery[0]['data']['elapsed_ms'],
                      no_gap_replay=True, explicit_resume_delta_ms=delta)
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        try:
            if frozen: command('podman', 'unpause', container)
            call('sim_operator_pause', run_id)
            command('podman', 'stop', '--time', '10', container)
            result['stop'] = json.loads(command('podman', 'inspect', container))[0]['State']
        except Exception as error: result.update(passed=False, cleanup_error=str(error))
        (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='stop'}))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__': main()
